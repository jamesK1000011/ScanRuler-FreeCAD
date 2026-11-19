# SPDX-License-Identifier: AGPL-3.0-only
# Ported from ScanRuler by Stefan Hermann (CNC Kitchen),
# github.com/CNCKitchen/ScanRuler: src/core/project/manifest.ts (what a
# project carries: the scan, its alignment, elements, dimensions, sections,
# the deviation and the other workspaces' state).
#
# ScanRuler's state in the FreeCAD document, so FreeCAD's own New, Open and
# Save carry it (the original's New / Load / Save .scanruler keys are gone):
#
#   ScanRulerState  App::FeaturePython, hidden from the tree: State (a
#                   PropertyFileIncluded zip: state.json and arrays.npz, the
#                   session's ScanRuler state as written on each change),
#                   Roles (which document object is the scan, the
#                   reference), Revision (moved on each write, so the
#                   document shows unsaved changes) and Credit.
#   the scan        a Mesh::Feature (ScanRulerRole) holding the scan as read
#                   and scaled (k·V0), its Placement the alignment (R, t):
#                   FreeCAD's Visibility, Transparency, Display Mode and
#                   Placement (Std_Placement, Std_TransformManip) act on it,
#                   and a move made there carries the elements with it.
#   the reference   a Mesh::Feature as well when it came from a file; a
#                   reference taken from a body in the document is that body.
#
# encode / decode are pure (numpy, json, zipfile): any dict, list, tuple,
# set, number, string and numpy array of the state goes through; a Scan by
# its pose (its points in the scan object when there is one, else in the
# arrays); a rigid motion (dev_rigid.Rigid: a best fit's transform) by its
# rotation and translation, and back as a Rigid; the deviation reference's
# search structure is built again from its points; caches are left out.
# Nothing is unpickled: arrays load with allow_pickle=False.
#
# The scan's points are left to its mesh object only while that mesh holds
# them one for one, in the scan's own order (Scan.in_object): the state
# keeps the triangles as vertex numbers, and numbers into points in another
# order are another surface. See _mesh_built and points_in_order.
#
# What a write costs follows what changed, not how large the state is: each
# array is packed (compressed) on its own and its packed bytes are kept
# beside the document for as long as the state holds an array of the same
# content (Packs), so a call that renames an element on a dense scan packs
# the small JSON part again and none of the scan's arrays. Found live
# (run 2, 16 Nov 2026): every changing call took 1.2 to 1.6 s once the scan
# had 219,600 triangles, the whole state compressed again each time.

import hashlib
import io
import json
import os
import shutil
import tempfile
import threading
import time
import zipfile
import zlib

import numpy as np

STATE_OBJECT = "ScanRulerState"
STATE_LABEL = "ScanRuler state"
SCAN_OBJECT = "ScanRulerScan"
REFERENCE_OBJECT = "ScanRulerReference"
ROLE_PROPERTY = "ScanRulerRole"
CREDIT = "ScanRuler by Stefan Hermann (CNC Kitchen), ported to FreeCAD"
# The format written. 1: state.json and arrays.npz (numpy's compressed
# archive of every array, compressed a second time by the zip around it).
# 2: state.json and one member per array, arrays/<key>.npy.z (the array as
# numpy's .npy, zlib-compressed, stored in the zip as it is), so an array
# that did not change is not compressed again. Both are read.
FORMAT = 2
ARRAYS = "arrays/"
PACKED = ".npy.z"
# Left out: they are worked out again (caches) or say only that something moved.
SKIP_KEYS = frozenset({"version", "last_tool", "onReference"})
# Beside a "scan" in the same dict: the scan's points (scan.V itself) as
# they stood when a reading was taken, there to tell a reading of the pose
# the scan is in from one taken before it moved. It was written out as an
# array like any other: a second copy of every vertex in the document's
# state (2.6 MB at 109,800 vertices), compressed again after each
# alignment and each scan_scale — the unscaled points beside the scaled
# scan until the next wall-thickness call noticed — and useless once read
# back, because a copy is never the scan's own array, so a reopened
# document lost its thickness reading (found while looking for what
# scan_scale leaves in the state, run 3).
POSE_KEY = "V"
_READ_ONLY, _HIDDEN, _OUTPUT, _NO_RECOMPUTE = 1, 4, 8, 16


# ---- the codec (pure) --------------------------------------------------------------------------


def array_digest(a):
    """What tells one array's content from another's: its type, shape and
    bytes (BLAKE2, about a gigabyte a second: a few milliseconds for a
    dense scan's arrays, where compressing them takes a second)."""
    a = np.ascontiguousarray(a)
    h = hashlib.blake2b(digest_size=16)
    h.update(f"{a.dtype.str}{a.shape}".encode())
    h.update(a.data if a.size else b"")
    return h.hexdigest()


def pack_array(a):
    """An array as numpy's .npy, zlib-compressed. Never pickled."""
    buf = io.BytesIO()
    np.lib.format.write_array(buf, np.ascontiguousarray(a), allow_pickle=False)
    return zlib.compress(buf.getvalue(), 6)


def unpack_array(data, limit=None):
    """An array back from pack_array's bytes, unpacked to at most limit
    bytes (guard.MAX_TOTAL by default): a .FCStd from the web can hold a
    zlib bomb (red team 3, R3-6)."""
    from . import guard

    raw = guard.inflate(data, guard.MAX_TOTAL if limit is None else limit, "an array of the ScanRuler state")
    return np.lib.format.read_array(io.BytesIO(raw), allow_pickle=False)


class Packs:
    """The packed bytes of the arrays of one document's state, by content:
    an array met again unchanged (the scan's triangles, an element's
    region, a deviation's readings) is not compressed again. Only what the
    last write used is kept (keep_used), so it never holds more than the
    state's own arrays, packed."""

    def __init__(self):
        self.kept = {}
        self.used = {}
        self.packed_again = 0

    def take(self, a):
        key = array_digest(a)
        blob = self.used.get(key)
        if blob is None:
            blob = self.kept.get(key)
            if blob is None:
                blob = pack_array(a)
                self.packed_again += 1
            self.used[key] = blob
        return blob

    def keep_used(self):
        """After a write: (arrays written, of them packed again); what was
        not used is let go."""
        n, again = len(self.used), self.packed_again
        self.kept, self.used, self.packed_again = self.used, {}, 0
        return n, again


class _Enc:
    def __init__(self, scan_points=None):
        self.arrays = {}
        self.scans = {}
        self.dropped = []
        # fn(scan) -> True when the scan's points live in a document object
        self.scan_points = scan_points or (lambda scan: False)

    def array(self, a):
        key = f"a{len(self.arrays)}"
        self.arrays[key] = np.asarray(a)
        return {"__nd__": key}

    def scan(self, s):
        if id(s) in self.scans:
            return {"__scanref__": self.scans[id(s)]}
        n = self.scans[id(s)] = len(self.scans)
        kV0 = s.k * np.asarray(s.V0, dtype=float)
        out = {"id": n, "name": s.name, "path": s.path, "units": s.units, "k": float(s.k), "R": self.array(s.R), "t": self.array(s.t),
               "object": getattr(s, "object", None), "count": int(len(s.V0)),
               "box": [kV0.min(axis=0).tolist(), kV0.max(axis=0).tolist()] if len(kV0) else None,
               "F": self.array(s.F)}
        if not self.scan_points(s):
            out["V0"] = self.array(s.V0)
        return {"__scan__": out}

    def value(self, x, path):
        from .dev_rigid import Rigid
        from .scanstate import Scan

        if x is None or isinstance(x, (bool, str)):
            return x
        if isinstance(x, (int, float)) and not isinstance(x, bool):
            return x if not isinstance(x, float) or np.isfinite(x) else {"__float__": repr(x)}
        if isinstance(x, np.bool_):
            return bool(x)
        if isinstance(x, np.integer):
            return int(x)
        if isinstance(x, np.floating):
            return self.value(float(x), path)
        if isinstance(x, np.ndarray):
            if x.dtype.hasobject:
                # An array of Python objects could only be pickled, and is
                # never unpickled on the way back (one such array used to
                # make the whole state unreadable): left out, and said.
                self.dropped.append(f"{path} (an array of objects)")
                return _DROP
            return self.array(x)
        if isinstance(x, Scan):
            return self.scan(x)
        if isinstance(x, Rigid):
            # A best fit's transform (deviation.align.transform and .total)
            # was left out, and said in the Report View, on every write:
            # a reopened document held an alignment without its motion,
            # and the next deviation call failed on it (found live, run 4).
            # Kept as its numbers, in full precision.
            return {"__rigid__": {"r": self.value(np.asarray(x.r, dtype=float).reshape(3, 3).tolist(), path), "t": self.value(np.asarray(x.t, dtype=float).reshape(3).tolist(), path)}}
        if isinstance(x, dict):
            if all(isinstance(k, str) for k in x):
                out = {}
                for k, v in x.items():
                    if k in SKIP_KEYS:
                        continue
                    if k == "surface" and type(v).__name__ == "NominalSurface":
                        out[k] = {"__nominal__": True}  # built again from V and F beside it
                        continue
                    if k == POSE_KEY and isinstance(v, np.ndarray) and isinstance(x.get("scan"), Scan):
                        # Not data: the scan's points as they stood when
                        # this reading was taken, kept only to tell whether
                        # the scan has moved since (handlers/thickness.py).
                        # Written as that answer, never as the points.
                        out[k] = {"__pose__": v is x["scan"].V}
                        continue
                    got = self.value(v, f"{path}.{k}")
                    if got is not _DROP:
                        out[k] = got
                return out
            return {"__dict__": [[self.value(k, path), self.value(v, f"{path}[{k!r}]")] for k, v in x.items()]}
        if isinstance(x, (list, tuple, set, frozenset)):
            items = [self.value(v, f"{path}[{i}]") for i, v in enumerate(x)]
            items = [v for v in items if v is not _DROP]
            if isinstance(x, list):
                return items
            return {"__tuple__" if isinstance(x, tuple) else "__set__": items}
        self.dropped.append(f"{path} ({type(x).__name__})")
        return _DROP


_DROP = object()


def encode(st, scan_points=None, packs=None):
    """The state as bytes (a zip of state.json and one packed member per
    array) and what could not be kept, as paths. packs (Packs): the packed
    arrays kept from the last write of this state; one whose content is
    unchanged is written from there and not compressed again."""
    e = _Enc(scan_points)
    body = e.value(st, "state")
    packs = packs if packs is not None else Packs()
    buf = io.BytesIO()
    # The JSON part is small and changes with every call: deflated here.
    # The arrays are packed already: stored as they are.
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        z.writestr("state.json", json.dumps({"format": FORMAT, "state": body, "dropped": e.dropped}, allow_nan=False),
                   compress_type=zipfile.ZIP_DEFLATED)
        for key, a in e.arrays.items():
            z.writestr(f"{ARRAYS}{key}{PACKED}", packs.take(a), compress_type=zipfile.ZIP_STORED)
    return buf.getvalue(), e.dropped


def signature(st):
    """A cheap fingerprint of the state: moves when something in it changes
    (an array by identity, shape and a sum), so a write happens on change."""
    from .dev_rigid import Rigid
    from .scanstate import Scan

    h = hashlib.sha1()

    def walk(x):
        if isinstance(x, np.ndarray):
            h.update(f"nd{id(x)}{x.shape}{x.dtype}".encode())
            if x.size and x.dtype.kind in "fiub":
                h.update(repr(float(np.asarray(x, dtype=float).sum())).encode())
        elif isinstance(x, Scan):
            h.update(f"scan{id(x)}{x.version}{x.k}".encode())
        elif isinstance(x, Rigid):
            h.update(b"rigid" + np.asarray(x.r, dtype=float).tobytes() + np.asarray(x.t, dtype=float).tobytes())
        elif isinstance(x, dict):
            for k in sorted(x, key=repr):
                if k in SKIP_KEYS:
                    continue
                h.update(repr(k).encode())
                walk(x[k])
        elif isinstance(x, (list, tuple, set, frozenset)):
            h.update(f"{type(x).__name__}{len(x)}".encode())
            for v in (sorted(x, key=repr) if isinstance(x, (set, frozenset)) else x):
                walk(v)
        else:
            h.update(repr(x).encode())

    walk(st)
    return h.hexdigest()


def decode(data, scan_points=None):
    """The state back from encode's bytes. scan_points(record) gives a
    scan's points as read and scaled (k·V0) from its document object, in
    the order the record's triangles (record["F"], the array) number them,
    or None (then the arrays' copy is used, or the scan is left out)."""
    from .dev_rigid import Rigid
    from .scanstate import Scan

    from . import guard

    # The state comes in a .FCStd, which can come from the web: every read
    # is capped, all arrays together to guard.MAX_TOTAL (red team 3, R3-6).
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        guard.zip_check(z, "the ScanRuler state")
        head = json.loads(guard.zip_read(z, "state.json", "the ScanRuler state", 256 * 1024 * 1024).decode("utf-8"))
        if head.get("format", 0) > FORMAT:
            raise ValueError("The ScanRuler state in this document was written by a newer version of ScanRuler for FreeCAD: update the add-on to read it.")
        names = z.namelist()
        left = guard.MAX_TOTAL
        if "arrays.npz" in names:  # format 1
            npz_bytes = guard.zip_read(z, "arrays.npz", "the ScanRuler state")
            with zipfile.ZipFile(io.BytesIO(npz_bytes)) as inner:
                guard.zip_check(inner, "the ScanRuler state's arrays")
            with np.load(io.BytesIO(npz_bytes), allow_pickle=False) as npz:
                arrays = {k: npz[k] for k in npz.files}
        else:
            arrays = {}
            for n in names:
                if n.startswith(ARRAYS) and n.endswith(PACKED):
                    a = unpack_array(guard.zip_read(z, n, "the ScanRuler state", left), left)
                    left -= a.nbytes
                    arrays[n[len(ARRAYS):-len(PACKED)]] = a
    scans, missing = {}, []

    def scan(rec):
        if "V0" in rec:
            V0 = arrays[rec["V0"]["__nd__"]]
        else:
            kV0 = (scan_points or (lambda r: None))({**rec, "F": arrays[rec["F"]["__nd__"]]})
            if kV0 is None:
                missing.append(rec["name"])
                return None
            V0 = np.asarray(kV0, dtype=float) / rec["k"]
        s = Scan(rec["name"], V0, arrays[rec["F"]["__nd__"]], rec["units"], rec["path"])
        s.set_pose(rec["k"], arrays[rec["R"]["__nd__"]], arrays[rec["t"]["__nd__"]])
        s.version = 0
        s.object = rec.get("object")
        return s

    def value(x):
        if isinstance(x, list):
            return [value(v) for v in x]
        if not isinstance(x, dict):
            return x
        if "__nd__" in x:
            return arrays[x["__nd__"]]
        if "__float__" in x:
            return float(x["__float__"])
        if "__tuple__" in x:
            return tuple(value(v) for v in x["__tuple__"])
        if "__set__" in x:
            return set(value(v) for v in x["__set__"])
        if "__dict__" in x:
            return {value(k): value(v) for k, v in x["__dict__"]}
        if "__rigid__" in x:
            return Rigid(value(x["__rigid__"]["r"]), value(x["__rigid__"]["t"]))
        if "__scanref__" in x:
            return scans.get(x["__scanref__"])
        if "__scan__" in x:
            rec = x["__scan__"]
            s = scans[rec["id"]] = scan(rec)
            return s
        out = {k: value(v) for k, v in x.items()}
        mark = out.get(POSE_KEY)
        if isinstance(mark, dict) and "__pose__" in mark:
            # A reading taken in the pose the scan is saved in is still of
            # that pose (the very array, as the check reads it); one taken
            # before a move is of no pose the scan has now.
            sc = out.get("scan")
            out[POSE_KEY] = sc.V if mark["__pose__"] and sc is not None else np.zeros((0, 3))
        if isinstance(out.get("surface"), dict) and out["surface"].get("__nominal__") and "V" in out and "F" in out:
            from .dev_surface import NominalSurface

            out["surface"] = NominalSurface(out["V"], out["F"])
        return out

    st = value(head["state"])
    return st, {"dropped": head.get("dropped") or [], "missing": missing}


def placement_rt(m):
    """(R, t) from a 4 x 4 matrix as rows."""
    a = np.asarray(m, dtype=float).reshape(4, 4)
    return a[:3, :3].copy(), a[:3, 3].copy()


def rigid_between(R0, t0, R1, t1):
    """The rigid motion (R, t) taking pose (R0, t0) to (R1, t1)."""
    R = np.asarray(R1) @ np.asarray(R0).T
    return R, np.asarray(t1) - R @ np.asarray(t0)


def points_from_object(points, placement_rt_, box):
    """A scan's k·V0 from its object's mesh points: the mesh holds them as
    read and scaled, its Placement the alignment. Where FreeCAD hands the
    points already placed, the placement is taken off again; which reading
    it is, the box kept in the state says."""
    P = np.asarray(points, dtype=float).reshape(-1, 3)
    if box is None or not len(P):
        return P
    lo, hi = np.asarray(box[0]), np.asarray(box[1])

    def off(Q):
        return float(np.abs(Q.min(axis=0) - lo).max() + np.abs(Q.max(axis=0) - hi).max())

    R, t = placement_rt_
    unplaced = (P - t) @ R  # R orthonormal: R^T applied row-wise
    return P if off(P) <= off(unplaced) else unplaced


def _area(P, F):
    t = np.asarray(P, dtype=float)[np.asarray(F, dtype=np.int64)]
    return float(np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1).sum() / 2) if len(t) else 0.0


# How far the area of the state's triangles on an object's points may lie
# from the area of the object's own mesh for the two to be one surface.
ORDER_AREA_TOLERANCE = 0.005


def points_in_order(P, tris, F, count):
    """A scan's points as its mesh object holds them (P, with the object's
    own triangles tris) put in the order the state's triangles F number
    them: (points, how) — how "same" (the object's order is the state's),
    "mapped" (another order, read back through the triangles) — or
    (None, why) when the object's mesh is not the scan the state holds.

    The state keeps F and leaves the points to the object. A mesh built
    from loose triangles (Mesh.addFacets of a list) numbers its points by
    where they first come up in the triangles, merges equal ones and drops
    triangles with no area: the same points in another order. F on those
    is some other surface — a 10 mm cube read 1,800 mm² where it has 600,
    a scan of some ten thousand triangles millions of mm² (scan_info's
    area 9,049,056 mm² on a block tens of mm across, found live, run 4).
    Where the triangles stand one for one, corner for corner, each of the
    state's vertex numbers is the object's point at the same corner."""
    P = np.asarray(P, dtype=float).reshape(-1, 3)
    F = np.asarray(F, dtype=np.int64).reshape(-1, 3)
    if tris is None:
        return (P, "same") if len(P) == count else (None, "count")
    T = np.asarray(tris, dtype=np.int64).reshape(-1, 3)
    if len(P) == count and T.shape == F.shape and np.array_equal(T, F):
        return P, "same"
    if len(F) and (F.min() < 0 or F.max() >= count or (len(T) and (T.min() < 0 or T.max() >= len(P)))):
        return None, "range"
    if T.shape == F.shape and len(F):
        to = np.full(count, -1, dtype=np.int64)
        to[F.ravel()] = T.ravel()
        if np.array_equal(to[F.ravel()], T.ravel()):  # one object point for each of the state's
            if (to >= 0).all():
                return P[to], "mapped"
            used = to >= 0
            if len(P) == count and np.array_equal(to[used], np.nonzero(used)[0]):
                return P, "same"  # in order; the rest are on no triangle
            return None, "unreferenced"
    if len(P) == count and len(F) and len(T):
        # Triangles dropped or turned on the way in: the same surface when
        # the state's triangles cover what the object's own do.
        own = _area(P, T)
        if own > 0 and abs(_area(P, F) - own) <= ORDER_AREA_TOLERANCE * own:
            return P, "same"
    return None, "order"


# ---- in a document (FreeCAD) ---------------------------------------------------------------------


def _report(text):
    try:
        import FreeCAD

        FreeCAD.Console.PrintWarning(f"ScanRuler: {text}\n")
    except ImportError:
        pass


# ---- which thread writes the document --------------------------------------------------------------
# A heavy read (deviation_align, deviation_measure, thickness_measure,
# scan_segment, section_fit, mesh_shell, mesh_wrap, mesh_trim, …) may be run
# by its host on a worker thread beside the call (Agent Link's jobs, its
# threads named "agentlink-job-<tool>"). FreeCAD's document and its view are
# the GUI thread's: a Placement set or an object added from another thread
# reaches Qt and the 3D view from that thread. So nothing here writes the
# document from a worker, ever. What the scan tools write after such a call
# (the scan's Placement following a best fit, the state kept in the
# document) goes one of two ways, on_gui_thread deciding:
#   a window is up   handed to the GUI thread (a queued Qt signal, not
#                    waited for): it lands a moment after the answer.
#   no window / Qt   left for the next ScanRuler call on the document's
#                    thread: mark writes whenever the state differs from
#                    what it wrote last, and carries a waiting Placement
#                    with it (flush_pose).

_POSTER = []
_POSTER_LOCK = threading.Lock()


def _gui_up():
    try:
        import FreeCAD

        return bool(getattr(FreeCAD, "GuiUp", False))
    except ImportError:
        return False


def _poster():
    """An object living on the GUI thread whose signal runs a function
    there (a queued connection); None where there is no Qt application."""
    with _POSTER_LOCK:
        if not _POSTER:
            made = None
            try:
                from PySide import QtCore

                app = QtCore.QCoreApplication.instance()
                if app is not None:

                    class Poster(QtCore.QObject):
                        go = QtCore.Signal(object)

                        def __init__(self):
                            super().__init__()
                            self.go.connect(self._run, QtCore.Qt.QueuedConnection)

                        def _run(self, fn):
                            try:
                                fn()
                            except Exception as e:  # noqa: BLE001 — the call it followed has answered
                                _report(f"a document write handed to the GUI thread failed: {e}")

                    made = Poster()
                    made.moveToThread(app.thread())
            except Exception as e:  # noqa: BLE001 — no Qt here: written where it stands, as before
                _report(f"document writes cannot be handed to the GUI thread: {e}")
                made = None
            _POSTER.append(made)
        return _POSTER[0]


def on_document_thread():
    """True on the thread FreeCAD's documents live on (the interpreter's
    main thread: the GUI thread with a window, the only one without)."""
    return threading.current_thread() is threading.main_thread()


def on_gui_thread(fn):
    """fn() where the document may be written, never on a worker thread.
    True: run at once (this is the document's thread). False: queued for
    the GUI thread and not waited for — the GUI thread may be the one
    waiting for this worker. None: on a worker with no window (or no Qt)
    to hand it to, so not run at all: the caller leaves it for the next
    call on the document's thread."""
    if on_document_thread():
        fn()
        return True
    p = _poster() if _gui_up() else None
    if p is None:
        return None
    p.go.emit(fn)
    return False


class StateProxy:
    """The proxy of the ScanRulerState object: nothing to compute."""

    def __init__(self, obj):
        obj.Proxy = self
        self.setup(obj)

    def setup(self, obj):
        have = obj.PropertiesList
        for name, kind, doc, mode in (
            ("State", "App::PropertyFileIncluded", "ScanRuler's state (state.json and arrays.npz)", _OUTPUT | _NO_RECOMPUTE),
            ("Roles", "App::PropertyMap", "Which document object is the scan, the reference", _OUTPUT | _NO_RECOMPUTE),
            ("Revision", "App::PropertyInteger", "Moves on each write of the state", _OUTPUT | _NO_RECOMPUTE | _READ_ONLY),
            ("Credit", "App::PropertyString", "Whose work this is", _READ_ONLY),
        ):
            if name not in have:
                obj.addProperty(kind, name, "ScanRuler", doc, mode)
        if obj.Credit != CREDIT:
            obj.Credit = CREDIT

    def onDocumentRestored(self, obj):
        self.setup(obj)

    def execute(self, obj):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        return None

    __getstate__ = dumps
    __setstate__ = loads


def find_state(doc):
    return next((o for o in getattr(doc, "Objects", None) or [] if o.Name.startswith(STATE_OBJECT) and hasattr(o, "State")), None)


def state_object(doc, make=True):
    o = find_state(doc)
    if o is None and make:
        o = doc.addObject("App::FeaturePython", STATE_OBJECT)
        StateProxy(o)
        o.Label = STATE_LABEL
        vo = getattr(o, "ViewObject", None)
        if vo is not None:
            vo.Proxy = 0
    if o is not None:
        hide_from_tree(o)
    return o


def hide_from_tree(o):
    """The state object off the model tree (its ViewObject's ShowInTree, a
    property every document object's view has, listed or not), so nobody
    deletes it by accident; not drawn either. Set again on each write: a
    document opened without the GUI, or an older one, gets it then. True
    when it is off the tree."""
    vo = getattr(o, "ViewObject", None)
    if vo is None:
        return False
    try:
        if getattr(vo, "ShowInTree", True):
            vo.ShowInTree = False
        if getattr(vo, "Visibility", False):
            vo.Visibility = False
        return not vo.ShowInTree
    except Exception as e:  # noqa: BLE001 — an older FreeCAD: it shows, and still works
        _report(f"the ScanRuler state object could not be taken off the tree: {e}")
        return False


def role_object(doc, role):
    """The document object that is the scan ("scan") or the reference
    ("reference"), or None."""
    o = find_state(doc)
    name = (dict(getattr(o, "Roles", {}) or {}) if o is not None else {}).get(role)
    got = doc.getObject(name) if name else None
    if got is None:
        got = next((x for x in getattr(doc, "Objects", None) or [] if getattr(x, ROLE_PROPERTY, None) == role), None)
    return got


def set_role(doc, role, obj):
    o = state_object(doc)
    roles = dict(o.Roles or {})
    if obj is None:
        roles.pop(role, None)
    else:
        roles[role] = obj.Name
    o.Roles = roles


def _mesh_built(V, F):
    """(a FreeCAD mesh of V and F, ordered): ordered True when the mesh
    holds the points one for one in V's order, so they can be read back
    from it under F.

    By its points and triangles (FreeCAD 1.1 source: src/Mod/Mesh/App/
    MeshPyImp.cpp, MeshPy::addFacets, the tuple form; Core/MeshKernel.cpp,
    AddFacets(facets, points, checkManifolds): the points are appended as
    given). That form takes Base.Vector points and tuples of three numbers
    and nothing else: a point given as a list is passed over without a
    word and a triangle given as a list is a TypeError. Lists were what it
    was given, so every mesh fell to the loose triangles below — its points
    in another order than V (points_in_order), and 660,000 tuples for a
    scan of 220,000 triangles. The manifold check is off: it drops the
    triangles round an edge three share, and a scan has such edges."""
    import Mesh

    V = np.asarray(V, dtype=float).reshape(-1, 3)
    F = np.asarray(F, dtype=np.int64).reshape(-1, 3)
    try:
        import FreeCAD

        points = [FreeCAD.Vector(x, y, z) for x, y, z in V.tolist()]
        faces = [tuple(t) for t in F.tolist()]
        try:
            m = Mesh.Mesh()
            m.addFacets((points, faces), False)
        except TypeError:  # a Mesh from before the check could be turned off
            m = Mesh.Mesh((points, faces))
        if int(m.CountPoints) == len(V):
            # The points are in as given. With every triangle in too, the
            # mesh reads back as V and F; with some dropped, see for itself.
            return m, int(m.CountFacets) == len(F) or _ordered(m, V, F)
    except Exception:  # noqa: BLE001 — a Mesh without that form: facet by facet
        pass
    m = Mesh.Mesh()
    m.addFacets([[tuple(V[i]) for i in t] for t in F.tolist()])
    return m, _ordered(m, V, F)


def _ordered(m, V, F):
    """Whether mesh m holds V one for one in order under F — read back
    from it; only where the way it was built does not say."""
    try:
        from .scanstate import points_array

        pts, tris = m.Topology
        P, how = points_in_order(points_array(pts), tris, F, len(V))
        return P is not None and how == "same" and len(P) == len(V) and bool(np.abs(P - V).max(initial=0.0) <= 1e-5 * max(1.0, float(np.abs(V).max(initial=0.0))))
    except Exception:  # noqa: BLE001 — not known: the state keeps the points itself
        return False


def _mesh_of(V, F):
    return _mesh_built(V, F)[0]


def _placement(R, t):
    import FreeCAD

    R, t = np.asarray(R, dtype=float), np.asarray(t, dtype=float)
    m = FreeCAD.Matrix()
    for i in range(3):
        for j in range(3):
            setattr(m, f"A{i + 1}{j + 1}", float(R[i][j]))
        setattr(m, f"A{i + 1}4", float(t[i]))
    return FreeCAD.Placement(m)


def _read_placement(obj):
    return placement_rt(obj.Placement.toMatrix().A)


def put_mesh(doc, name, label, role, V, F, R=None, t=None, old=None, said=None):
    """A Mesh::Feature for the scan or the reference: its mesh V, F, its
    Placement (R, t). One it made before (old) is taken out first. said
    (a dict) is given ordered: whether the mesh holds V in V's order."""
    if old is not None and getattr(old, ROLE_PROPERTY, None) == role and old.Name.startswith((SCAN_OBJECT, REFERENCE_OBJECT)):
        doc.removeObject(old.Name)
    o = doc.addObject("Mesh::Feature", name)
    o.addProperty("App::PropertyString", ROLE_PROPERTY, "ScanRuler", "What ScanRuler reads this mesh as")
    setattr(o, ROLE_PROPERTY, role)
    o.Label = label
    o.Mesh, ordered = _mesh_built(V, F)
    if said is not None:
        said["ordered"] = ordered
    if R is not None:
        o.Placement = _placement(R, t)
    set_role(doc, role, o)
    return o


def attach_scan(doc, scan, obj, owned=True, push_now=True, ordered=True):
    """The scan read from (or put in) obj: its pose pushed to obj's
    Placement on each change, and a move made on obj in FreeCAD pulled
    back (pull_pose). A mesh of the document's own that was opened as the
    scan (owned False) is only shown and hidden through it. ordered: obj's
    mesh holds the scan's points in the scan's order (Scan.in_object), so
    the state leaves them to it; otherwise the state keeps them itself."""
    scan.object = obj.Name
    scan.in_object = bool(ordered)
    set_role(doc, "scan", obj)
    if not owned:
        scan.on_pose = None
        return

    def write(s):
        t0 = time.perf_counter()
        rebuilt = False
        try:
            o = doc.getObject(s.object)
            if o is None:
                return
            # The mesh first, then the Placement: a Mesh::Feature given a
            # new mesh takes that mesh's own placement (none) as its
            # Placement (FreeCAD 1.1 source: src/Mod/Mesh/App/MeshFeature.cpp,
            # Feature::onChanged). Set the other way round, a scan_scale on
            # an aligned scan left the object at the origin, and the next
            # call read that as a move made by the person and took the
            # alignment off (found live, run 2).
            if getattr(s, "meshed_k", s.k) != s.k:  # scaled: the mesh holds k·V0
                s.in_object = False  # till the new mesh is in and known to be in order
                o.Mesh, ordered = _mesh_built(s.k * s.V0, s.F)
                s.in_object = ordered
                s.meshed_k = s.k
                rebuilt = True
            o.Placement = _placement(s.R, s.t)
            s.placed = _read_placement(o)
        except Exception as e:  # noqa: BLE001 — the view only: the measurement holds
            _report(f"the scan's placement could not follow its alignment: {e}")
        # What this write into the document cost, for the tool that moved
        # the scan to answer (handlers/align.py: timing): a new record each
        # time, so a call can tell its own write from an earlier one.
        s.wrote = {"ms": int(round((time.perf_counter() - t0) * 1000)), "mesh": "rebuilt" if rebuilt else "kept"}

    def push(s):
        # From a worker thread (a best fit run as a job) the write waits
        # for the GUI thread; s.placed stays the object's placement till
        # then, so pull_pose reads no move in between. With no window to
        # hand it to, it waits for the next call (flush_pose, from mark).
        s.pose_waiting = False
        if on_gui_thread(lambda: write(s)) is None:
            s.pose_waiting = True

    scan.write_pose = write
    scan.on_pose = push
    scan.meshed_k = scan.k
    if push_now:
        push(scan)
    else:  # reopened: the object stands where it was saved, nothing written
        scan.placed = (np.array(scan.R, dtype=float), np.array(scan.t, dtype=float))


def put_scan(doc, scan):
    """The scan as a Mesh::Feature in doc (replacing the one put before)."""
    old = role_object(doc, "scan")
    said = {}
    o = put_mesh(doc, SCAN_OBJECT, scan.name, "scan", scan.k * scan.V0, scan.F, old=old, said=said)
    attach_scan(doc, scan, o, ordered=said.get("ordered", False))
    return o


def pull_pose(st, doc):
    """A move made on the scan object in FreeCAD (Std_Placement,
    Std_TransformManip, its Placement typed in) carried into the scan and
    everything measured on it, as Move / rotate by numbers did. True when
    it moved."""
    scan = st.get("scan")
    if scan is None or getattr(scan, "on_pose", None) is None or getattr(scan, "placed", None) is None:
        return False
    o = doc.getObject(scan.object) if getattr(scan, "object", None) else None
    if o is None:
        return False
    R1, t1 = _read_placement(o)
    R0, t0 = scan.placed
    if np.abs(R1 - R0).max() < 1e-9 and np.abs(t1 - t0).max() < 1e-7:
        return False
    from . import model

    if getattr(scan, "pose_waiting", False):
        # A best fit's pose still waits to be written to the object (it
        # ran on a worker with no window): the person's move is the one
        # from where the object stood, put on top of the fit.
        rig = rigid_between(R0, t0, R1, t1)
    else:
        # The pose the measurement stands in is the scan's own (R, t); the
        # object's new one is where the person put it.
        rig = rigid_between(scan.R, scan.t, R1, t1)
    model.transform_all(st, rig)
    return True


def flush_pose(st):
    """A scan pose that could not be written to its object when it was set
    (a worker thread with no window: on_gui_thread) written now. Called on
    the document's thread only (mark). True when one was waiting."""
    scan = st.get("scan")
    if scan is None or not getattr(scan, "pose_waiting", False):
        return False
    scan.pose_waiting = False
    w = getattr(scan, "write_pose", None)
    if w is not None and getattr(scan, "on_pose", None) is not None:
        w(scan)
    return True


def put_reference(doc, ref):
    """The deviation reference in doc: a body it came from is that body; a
    file's is put in as a Mesh::Feature."""
    if ref.get("kind") == "body" and ref.get("object") and doc.getObject(ref["object"]) is not None:
        set_role(doc, "reference", doc.getObject(ref["object"]))
        return doc.getObject(ref["object"])
    o = put_mesh(doc, REFERENCE_OBJECT, ref["name"], "reference", ref["V"], ref["F"], old=role_object(doc, "reference"))
    ref["object"] = o.Name
    return o


def _file_bytes(path):
    from . import guard

    if os.path.getsize(path) > guard.MAX_TOTAL:
        raise guard.TooLarge(f"The ScanRuler state in this document is larger than {guard.MAX_TOTAL // (1024 * 1024)} MB: not read.")
    with open(path, "rb") as f:
        return f.read()


# Per open document: the packed arrays its last write used and what that
# write cost. {document name: {"doc": the document, "packs": Packs, "last": {…}}}
_KEPT = {}


def _kept_for(doc):
    """The record kept for doc (see _KEPT); the records of documents closed
    since are let go, and a document reopened under an old name starts a
    new one."""
    from . import scanstate

    for name in [n for n, r in _KEPT.items() if r["doc"] is not doc and not scanstate.doc_open(r["doc"], n)]:
        del _KEPT[name]
    name = getattr(doc, "Name", None) or f"#{id(doc)}"
    rec = _KEPT.get(name)
    if rec is None or rec["doc"] is not doc:
        rec = _KEPT[name] = {"doc": doc, "packs": Packs(), "last": None}
    return rec


def last_write(doc):
    """What the last write of ScanRuler's state into doc cost, or None when
    nothing was written since the document was opened: { bytes, ms,
    arrays, packedAgain } — arrays the state holds, packedAgain how many of
    them had changed (or were new) and were compressed for this write."""
    rec = _KEPT.get(getattr(doc, "Name", None) or f"#{id(doc)}")
    return dict(rec["last"]) if rec is not None and rec["doc"] is doc and rec["last"] else None


def write(doc, st):
    """The state into the document's ScanRulerState (made if missing).
    Returns what could not be kept. An array whose content is as it was at
    the last write into this document is written from its packed bytes
    (Packs), so the cost follows what changed."""
    t0 = time.perf_counter()
    o = state_object(doc)
    scan_points = lambda s: (s is st.get("scan") and getattr(s, "on_pose", None) is not None and getattr(s, "in_object", False)  # noqa: E731
                             and doc.getObject(getattr(s, "object", "") or "") is not None)
    rec = _kept_for(doc)
    data, dropped = encode(st, scan_points, rec["packs"])
    folder = tempfile.mkdtemp(prefix="scanruler-state-")
    path = os.path.join(folder, "scanruler-state.zip")
    with open(path, "wb") as f:
        f.write(data)
    try:
        o.State = path  # FreeCAD copies it into the document's own folder
    except Exception:
        rec["packs"].used.clear()  # not written: what was kept before still stands for the file there
        rec["packs"].packed_again = 0
        raise
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    o.Revision = int(o.Revision or 0) + 1
    arrays, again = rec["packs"].keep_used()
    rec["last"] = {"bytes": len(data), "ms": int(round((time.perf_counter() - t0) * 1000)), "arrays": arrays, "packedAgain": again}
    return dropped


def sync_objects(doc, st):
    """The scan and the deviation reference as document objects: put in
    when the state has one the document does not show yet (a scan opened,
    replaced by Mesh Tools' edited copy or by an undo; a reference opened).
    Returns the names put in."""
    made = []
    scan = st.get("scan")
    if scan is not None:
        o = doc.getObject(scan.object) if getattr(scan, "object", None) else None
        if o is None:
            made.append(put_scan(doc, scan).Name)
        elif role_object(doc, "scan") is not o:
            set_role(doc, "scan", o)
    ref = (st.get("deviation") or {}).get("reference")
    if isinstance(ref, dict) and ref.get("V") is not None:
        o = doc.getObject(ref["object"]) if ref.get("object") else None
        if o is None or role_object(doc, "reference") is not o:
            made.append(put_reference(doc, ref).Name)
    return made


def read(doc):
    """The state the document holds, or None."""
    o = find_state(doc)
    path = str(getattr(o, "State", "") or "") if o is not None else ""
    if not path or not os.path.isfile(path):
        return None

    read_as = {}

    def scan_points(rec):
        obj = doc.getObject(rec.get("object") or "")
        if obj is None or not hasattr(obj, "Mesh"):
            return None
        pts, tris = obj.Mesh.Topology
        from .scanstate import points_array

        P = points_from_object(points_array(pts), _read_placement(obj), rec.get("box"))
        P, how = points_in_order(P, tris, rec["F"], rec.get("count"))
        read_as[rec.get("object")] = how
        return P

    st, notes = decode(_file_bytes(path), scan_points)
    scan = st.get("scan")
    obj = doc.getObject(getattr(scan, "object", None) or "") if scan is not None else None
    if obj is not None:
        owned = getattr(obj, ROLE_PROPERTY, None) == "scan" and obj.Name.startswith(SCAN_OBJECT)
        how = read_as.get(scan.object)
        # Read from the object in its order: left to it. Read through the
        # triangles, or from the state's own copy: kept in the state.
        attach_scan(doc, scan, obj, owned, push_now=False, ordered=how == "same")
        if how == "mapped":
            _report(f"the points of {scan.name} stand in another order in its mesh object than its triangles number them: read back through the triangles, and kept with the state from the next call on.")
    if notes["missing"]:
        if any(why in ("order", "unreferenced", "range", "count") for why in read_as.values()):
            _report(f"the scan's mesh ({', '.join(notes['missing'])}) in the document is not the mesh its triangles were kept for (its points changed, or stand in an order that cannot be read back): open the scan again.")
        else:
            _report(f"the scan's mesh ({', '.join(notes['missing'])}) is no longer in the document: open the scan again.")
    if notes["dropped"]:
        _report("not kept in the document: " + ", ".join(notes["dropped"]))
    return st


_SIGS = {}


def mark(session):
    """After a call: the state written into the document when it changed
    (scanstate.touched), and a scan Placement left waiting by a worker
    thread with it. On the document's thread only. The state is the
    document's own: a session that has moved to another document since
    its last call is settled first (scanstate.settle), so one document's
    state is never written into another."""
    from . import scanstate

    fs = getattr(session, "family_state", None)
    if getattr(session, "doc", None) is None or fs is None:
        return False
    if not on_document_thread():
        return False  # never from a worker: scanstate.touched hands it over or leaves it
    doc = scanstate.settle(session)
    if "scanruler" not in fs:
        return False
    return mark_doc(doc, fs["scanruler"], session)


def mark_doc(doc, st, session=None):
    """st written into doc, the document it belongs to, when it differs
    from what was written last. On the document's thread only, and only
    while the document is open (a write handed to the GUI thread can land
    after its document was closed)."""
    from . import scanstate

    if doc is None or st is None or not hasattr(doc, "addObject"):
        return False
    if not on_document_thread():
        return False
    if not scanstate.doc_open(doc):
        return False
    flush_pose(st)
    sig = signature(st)
    key = (getattr(doc, "Name", id(doc)), id(session))
    if _SIGS.get(key) == (id(doc), sig):
        return False
    if find_state(doc) is None and st.get("scan") is None and not st.get("elements"):
        _SIGS[key] = (id(doc), sig)
        return False  # nothing worth a state object yet
    sync_objects(doc, st)
    dropped = write(doc, st)
    _SIGS[key] = (id(doc), signature(st))  # the objects' names just set in it count as written
    if dropped:
        _report("not kept in the document: " + ", ".join(dropped))
    return True
