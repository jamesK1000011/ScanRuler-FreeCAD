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
# arrays); the deviation reference's search structure is built again from
# its points; caches are left out. Nothing is unpickled: arrays load with
# allow_pickle=False.

import hashlib
import io
import json
import os
import shutil
import tempfile
import threading
import zipfile

import numpy as np

STATE_OBJECT = "ScanRulerState"
STATE_LABEL = "ScanRuler state"
SCAN_OBJECT = "ScanRulerScan"
REFERENCE_OBJECT = "ScanRulerReference"
ROLE_PROPERTY = "ScanRulerRole"
CREDIT = "ScanRuler by Stefan Hermann (CNC Kitchen), ported to FreeCAD"
FORMAT = 1
# Left out: they are worked out again (caches) or say only that something moved.
SKIP_KEYS = frozenset({"version", "last_tool", "onReference"})
_READ_ONLY, _HIDDEN, _OUTPUT, _NO_RECOMPUTE = 1, 4, 8, 16


# ---- the codec (pure) --------------------------------------------------------------------------


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
            return self.array(x)
        if isinstance(x, Scan):
            return self.scan(x)
        if isinstance(x, dict):
            if all(isinstance(k, str) for k in x):
                out = {}
                for k, v in x.items():
                    if k in SKIP_KEYS:
                        continue
                    if k == "surface" and type(v).__name__ == "NominalSurface":
                        out[k] = {"__nominal__": True}  # built again from V and F beside it
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


def encode(st, scan_points=None):
    """The state as bytes (a zip of state.json and arrays.npz) and what
    could not be kept, as paths."""
    e = _Enc(scan_points)
    body = e.value(st, "state")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("state.json", json.dumps({"format": FORMAT, "state": body, "dropped": e.dropped}, allow_nan=False))
        arr = io.BytesIO()
        np.savez_compressed(arr, **e.arrays)
        z.writestr("arrays.npz", arr.getvalue())
    return buf.getvalue(), e.dropped


def signature(st):
    """A cheap fingerprint of the state: moves when something in it changes
    (an array by identity, shape and a sum), so a write happens on change."""
    from .scanstate import Scan

    h = hashlib.sha1()

    def walk(x):
        if isinstance(x, np.ndarray):
            h.update(f"nd{id(x)}{x.shape}{x.dtype}".encode())
            if x.size and x.dtype.kind in "fiub":
                h.update(repr(float(np.asarray(x, dtype=float).sum())).encode())
        elif isinstance(x, Scan):
            h.update(f"scan{id(x)}{x.version}{x.k}".encode())
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
    scan's points as read and scaled (k·V0) from its document object, or
    None (then the arrays' copy is used, or the scan is left out)."""
    from .scanstate import Scan

    with zipfile.ZipFile(io.BytesIO(data)) as z:
        head = json.loads(z.read("state.json").decode("utf-8"))
        with np.load(io.BytesIO(z.read("arrays.npz")), allow_pickle=False) as npz:
            arrays = {k: npz[k] for k in npz.files}
    if head.get("format", 0) > FORMAT:
        raise ValueError("The ScanRuler state in this document was written by a newer version.")
    scans, missing = {}, []

    def scan(rec):
        if "V0" in rec:
            V0 = arrays[rec["V0"]["__nd__"]]
        else:
            kV0 = (scan_points or (lambda r: None))(rec)
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
        if "__scanref__" in x:
            return scans.get(x["__scanref__"])
        if "__scan__" in x:
            rec = x["__scan__"]
            s = scans[rec["id"]] = scan(rec)
            return s
        out = {k: value(v) for k, v in x.items()}
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


def _mesh_of(V, F):
    import Mesh

    V = np.asarray(V, dtype=float)
    F = np.asarray(F, dtype=np.int64)
    try:
        return Mesh.Mesh((V.tolist(), F.tolist()))  # from its topology: the points' order kept
    except Exception:  # noqa: BLE001 — an older Mesh: facet by facet
        m = Mesh.Mesh()
        m.addFacets([[tuple(V[i]) for i in t] for t in F.tolist()])
        return m


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


def put_mesh(doc, name, label, role, V, F, R=None, t=None, old=None):
    """A Mesh::Feature for the scan or the reference: its mesh V, F, its
    Placement (R, t). One it made before (old) is taken out first."""
    if old is not None and getattr(old, ROLE_PROPERTY, None) == role and old.Name.startswith((SCAN_OBJECT, REFERENCE_OBJECT)):
        doc.removeObject(old.Name)
    o = doc.addObject("Mesh::Feature", name)
    o.addProperty("App::PropertyString", ROLE_PROPERTY, "ScanRuler", "What ScanRuler reads this mesh as")
    setattr(o, ROLE_PROPERTY, role)
    o.Label = label
    o.Mesh = _mesh_of(V, F)
    if R is not None:
        o.Placement = _placement(R, t)
    set_role(doc, role, o)
    return o


def attach_scan(doc, scan, obj, owned=True, push_now=True):
    """The scan read from (or put in) obj: its pose pushed to obj's
    Placement on each change, and a move made on obj in FreeCAD pulled
    back (pull_pose). A mesh of the document's own that was opened as the
    scan (owned False) is only shown and hidden through it."""
    scan.object = obj.Name
    set_role(doc, "scan", obj)
    if not owned:
        scan.on_pose = None
        return

    def write(s):
        try:
            o = doc.getObject(s.object)
            if o is None:
                return
            o.Placement = _placement(s.R, s.t)
            s.placed = _read_placement(o)
            if getattr(s, "meshed_k", s.k) != s.k:  # scaled: the mesh holds k·V0
                o.Mesh = _mesh_of(s.k * s.V0, s.F)
                s.meshed_k = s.k
        except Exception as e:  # noqa: BLE001 — the view only: the measurement holds
            _report(f"the scan's placement could not follow its alignment: {e}")

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
    o = put_mesh(doc, SCAN_OBJECT, scan.name, "scan", scan.k * scan.V0, scan.F, old=old)
    attach_scan(doc, scan, o)
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
    with open(path, "rb") as f:
        return f.read()


def write(doc, st):
    """The state into the document's ScanRulerState (made if missing).
    Returns what could not be kept."""
    o = state_object(doc)
    scan_points = lambda s: s is st.get("scan") and getattr(s, "on_pose", None) is not None and doc.getObject(getattr(s, "object", "") or "") is not None  # noqa: E731
    data, dropped = encode(st, scan_points)
    folder = tempfile.mkdtemp(prefix="scanruler-state-")
    path = os.path.join(folder, "scanruler-state.zip")
    with open(path, "wb") as f:
        f.write(data)
    try:
        o.State = path  # FreeCAD copies it into the document's own folder
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    o.Revision = int(o.Revision or 0) + 1
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

    def scan_points(rec):
        obj = doc.getObject(rec.get("object") or "")
        if obj is None or not hasattr(obj, "Mesh"):
            return None
        pts = obj.Mesh.Topology[0]
        from .scanstate import points_array

        P = points_from_object(points_array(pts), _read_placement(obj), rec.get("box"))
        return P if len(P) == rec.get("count") else None

    st, notes = decode(_file_bytes(path), scan_points)
    scan = st.get("scan")
    obj = doc.getObject(getattr(scan, "object", None) or "") if scan is not None else None
    if obj is not None:
        owned = getattr(obj, ROLE_PROPERTY, None) == "scan" and obj.Name.startswith(SCAN_OBJECT)
        attach_scan(doc, scan, obj, owned, push_now=False)
    if notes["missing"]:
        _report(f"the scan's mesh ({', '.join(notes['missing'])}) is no longer in the document: open the scan again.")
    if notes["dropped"]:
        _report("not kept in the document: " + ", ".join(notes["dropped"]))
    return st


_SIGS = {}


def mark(session):
    """After a call: the state written into the document when it changed
    (scanstate.touched), and a scan Placement left waiting by a worker
    thread with it. On the document's thread only."""
    doc = getattr(session, "doc", None)
    fs = getattr(session, "family_state", None)
    if doc is None or not fs or "scanruler" not in fs or not hasattr(doc, "addObject"):
        return False
    st = fs["scanruler"]
    if not on_document_thread():
        return False  # never from a worker: scanstate.touched hands it over or leaves it
    flush_pose(st)
    sig = signature(st)
    key = (getattr(doc, "Name", id(doc)), id(session))
    if _SIGS.get(key) == sig:
        return False
    if find_state(doc) is None and st.get("scan") is None and not st.get("elements"):
        _SIGS[key] = sig
        return False  # nothing worth a state object yet
    sync_objects(doc, st)
    dropped = write(doc, st)
    _SIGS[key] = signature(st)  # the objects' names just set in it count as written
    if dropped:
        _report("not kept in the document: " + ", ".join(dropped))
    return True
