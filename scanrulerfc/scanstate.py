# SPDX-License-Identifier: AGPL-3.0-only
# The scan held by the session, as arrays: what every measuring tool reads.
# The part of ScanRuler's session that holds the scan (src/core/types.ts,
# src/core/meshUnits.ts), ported to numpy.

import itertools
import os

import numpy as np

KEY = "scanruler"
UNITS = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4}
# A scan's diagonal outside these, in millimetres, is most likely read in the
# wrong units (scan_open warns); past LARGE_TRIANGLES the tools grow slow
# (scan_open suggests mesh_reduce).
PLAUSIBLE_DIAG_MM = (1.0, 5000.0)
LARGE_TRIANGLES = 2_000_000


def finite_faces(verts, faces):
    """The vertices and faces with every non-finite vertex (NaN or infinity)
    taken out, the faces on one dropped and the rest renumbered:
    (V, F, faces dropped, vertices dropped)."""
    V = np.asarray(verts, dtype=float).reshape(-1, 3)
    F = np.asarray(faces, dtype=np.int64).reshape(-1, 3)
    bad = ~np.isfinite(V).all(axis=1)
    if not bad.any():
        return V, F, 0, 0
    keep = ~bad[F].any(axis=1) if len(F) else np.zeros(0, dtype=bool)
    new = np.cumsum(~bad) - 1
    return V[~bad].copy(), new[F[keep]], int((~keep).sum()), int(bad.sum())


def points_array(pts):
    """FreeCAD vectors (or any 3-sequences) as an N x 3 float array, without
    a Python loop where numpy can read them directly."""
    if len(pts) == 0:
        return np.zeros((0, 3))
    try:
        A = np.asarray(pts, dtype=float)
        if A.ndim == 2 and A.shape[1] == 3:
            return A
    except (TypeError, ValueError):
        pass
    return np.array([[p.x, p.y, p.z] for p in pts], dtype=float)


class Scan:
    def __init__(self, name, verts, faces, units="mm", path=None):
        self.name = name
        self.path = path
        self.units = units
        # Faces on a NaN or infinite vertex are dropped: every fit, search
        # and best fit downstream would otherwise read NaN or fail in the
        # linear algebra. With none left the scan is refused.
        V, F, dropped, bad = finite_faces(verts, faces)
        if bad and len(F) == 0:
            raise ValueError(f"{name}: every triangle touches a vertex that is not a number (NaN or infinite) — the file is damaged.")
        self.V = V
        self.F = F
        self.dropped = {"faces": dropped, "vertices": bad} if bad else None
        self._normals = None
        self._areas = None
        # The scan as read, the factor it was scaled by and the alignment
        # applied after it: V = R·(k·V0) + t.
        self.V0 = self.V.copy()
        self.k = 1.0
        self.R = np.eye(3)
        self.t = np.zeros(3)
        self.version = 0
        self._graph = None
        # The document object the scan is shown as (docstate.py), and the
        # hook that moves it when the pose changes: None without FreeCAD.
        self.object = None
        self.on_pose = None
        # True while that object's mesh holds these points one for one in
        # this order, so the state in the document leaves them to it
        # (docstate.attach_scan); otherwise the state keeps them itself.
        self.in_object = False

    def set_pose(self, k, R, t):
        self.k, self.R, self.t = float(k), np.asarray(R, dtype=float), np.asarray(t, dtype=float)
        self.V = (self.k * self.V0) @ self.R.T + self.t
        self._normals = self._areas = self._graph = None
        self.version += 1
        if self.on_pose is not None:
            self.on_pose(self)

    def graph(self):
        """The scan's mesh graph (adjacency, vertex normals) in its current
        pose."""
        if self._graph is None:
            from .meshgraph import MeshGraph

            self._graph = MeshGraph(self.V, self.F)
        return self._graph

    @property
    def tri(self):
        return self.V[self.F]

    def face_normals(self):
        if self._normals is None:
            t = self.tri
            n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
            a = np.linalg.norm(n, axis=1)
            self._areas = a / 2
            with np.errstate(invalid="ignore", divide="ignore"):
                self._normals = np.where(a[:, None] > 0, n / a[:, None], 0.0)
        return self._normals

    def face_areas(self):
        self.face_normals()
        return self._areas

    def summary(self):
        lo, hi = self.V.min(axis=0), self.V.max(axis=0)
        return {
            "file": self.name,
            "units": self.units,
            "vertices": int(len(self.V)),
            "triangles": int(len(self.F)),
            "box": {"min": [round(float(x), 3) for x in lo], "max": [round(float(x), 3) for x in hi], "size": [round(float(x), 3) for x in hi - lo]},
            "centre": [round(float(x), 3) for x in (lo + hi) / 2],
            "area": round(float(self.face_areas().sum()), 2),
        }

    def warnings(self):
        """What looks wrong with the scan as opened: a size that suggests the
        wrong units, a mesh large enough to slow every tool, damaged vertices."""
        out = []
        diag = float(np.linalg.norm(self.V.max(axis=0) - self.V.min(axis=0))) if len(self.V) else 0.0
        lo, hi = PLAUSIBLE_DIAG_MM
        if diag < lo:
            out.append(f"The scan is only {diag:.4g} mm across (read as {self.units}) — a part this small is unlikely: if the file is in metres, centimetres or inches, open it again with units (m, cm or in).")
        elif diag > hi:
            out.append(f"The scan is {diag / 1000:.4g} m across (read as {self.units}) — a part this large is unlikely: if the file is not in {self.units}, open it again with the right units (mm, cm, m or in).")
        if len(self.F) > LARGE_TRIANGLES:
            out.append(f"The scan has {len(self.F):,} triangles: fits, maps and best fits will be slow. mesh_reduce brings it down to a working size first.")
        if self.dropped:
            out.append(f"{self.dropped['vertices']} vertices were not numbers (NaN or infinite): they and the {self.dropped['faces']} triangles on them were dropped.")
        return out


def fresh():
    return {"scan": None, "elements": [], "dimensions": [], "next": 1, "dimNext": 1, "counters": {}, "marked": None, "scaled": None,
            "version": 0, "last_tool": None}


# One count for every session, so a version never comes round again (not
# even when scan_open starts the state afresh): the dock compares it.
_TICKS = itertools.count(1)


def touched(session, tool, write=True, args=None, answer=None):
    """After a call went through (the add-on's runner, or Agent Link's
    family layer): the session's version moves and last_tool names the
    tool, so the dock refreshes and turns to that tool's workspace. Every
    call counts, not only the ones that change the document (data/tools.json
    "changes"): a fit, an alignment or a map changes what the panels show
    without touching the document. The snapshot tools only read the shots.
    write: False leaves the copy in the document for a later call.

    The document is never written from a worker thread (a heavy tool run
    as an Agent Link job answers on one): docstate.on_gui_thread hands the
    write to the GUI thread when a window is up, and otherwise leaves it;
    the next call on the document's thread then writes it (docstate.mark
    writes whenever the state differs from what it wrote last).

    The write is of this state into the document it was made in: both are
    taken here, so a write that lands later (handed to the GUI thread)
    still goes to that document when the session has moved to another.

    With a window, the call's results are then drawn in the 3D view
    (scene_coin.after_call: the elements, dimensions, sections, markers,
    the colour map and its legend, Mesh Tools' edited copy), on the GUI
    thread after the write, so the scan object it draws round is in place.
    args, answer: the call's arguments and answer, for what only that call
    shows (the nearest point, an outline, a cut plane). Without a window
    nothing is drawn and nothing is computed for it."""
    if tool.startswith("scan_snapshot_") or getattr(session, "family_state", None) is None:
        return  # a session that keeps no state (a catalog-only caller): nothing to show
    st = state(session)
    st["version"] = next(_TICKS)
    st["last_tool"] = tool
    try:
        from . import docstate
    except ImportError:
        return
    doc = getattr(session, "doc", None)
    drawn = _window_up()
    seen = {}

    def to_document():
        if write:
            try:
                docstate.mark_doc(doc, st, session)  # FreeCAD's Save carries it from here
            except Exception as e:  # noqa: BLE001 — the call went through; only the copy in the document did not
                _report(f"the state could not be written into the document: {e}")
        if drawn:
            seen.update(window_after(session, tool, args, answer))

    if write or drawn:
        ran = docstate.on_gui_thread(to_document)
        # What the window shows, as facts in the answer (window review
        # round 6: colours, label size and the legend's words could only
        # be told from a picture). Only when drawn here and now, on the
        # thread that hands the answer back: a write queued from a job's
        # worker never touches an answer that may be on its way out.
        if ran is True and seen and isinstance(answer, dict) and "view3d" not in answer:
            answer["view3d"] = seen


def window_after(session, tool, args, answer):
    """The call's results drawn in the 3D view, then the panel drawn again
    (the change is in by now). Returns the facts of both, {} for none.
    Never raises."""
    out = {}
    try:
        from . import scene_coin

        got = scene_coin.after_call(session, tool, args, answer)
        if isinstance(got, dict) and got.get("facts"):
            out.update(got["facts"])
    except Exception as e:  # noqa: BLE001 — the view only: the call has answered
        _report(f"the results of {tool} could not be drawn: {e}")
    try:
        from . import dock

        panel = dock.after_call()
        if panel is not None:
            out["panel"] = panel
    except Exception as e:  # noqa: BLE001 — the panel only
        _report(f"the panel could not be drawn again after {tool}: {e}")
    return out


def _window_up():
    """FreeCAD with its window (the 3D view the results are drawn in)."""
    try:
        import FreeCAD
    except ImportError:
        return False
    return bool(getattr(FreeCAD, "GuiUp", False))


def _report(text):
    try:
        import FreeCAD

        FreeCAD.Console.PrintWarning(f"ScanRuler: {text}\n")
    except ImportError:
        pass


# ---- one state per document ----------------------------------------------------------------------
# ScanRuler's state (the scan, elements, dimensions, sections, the 2D sheet,
# the deviation, Mesh Tools' copy) belongs to the FreeCAD document it was
# made in. A session works in one document at a time and may move to
# another (Agent Link's doc_new, doc_open, doc_switch, doc_close set
# session.doc; they do not all empty family_state). So, before any state
# is handed out, settle() looks at the document the session is in now:
#   the same as last time   nothing to do.
#   another                 the state is written into the document it
#                           belongs to (when that is still open, and on
#                           the document's thread only), set aside under
#                           that document, and taken out of the session;
#                           the new document's own state comes back from
#                           where it was set aside, else from the document
#                           (docstate.read), else it starts empty.
# A document closed and another opened under the same name is another
# document (FreeCAD keeps one Python object per open document: identity
# tells them apart), so nothing of the old one is handed to it.
#
# Agent Link keeps every family's state per document as well since
# 16 Nov 2026 (agentlink/docstates.py: session.family_state is one dict per
# document, set aside on leaving and brought back on return). The two do
# not meet: a key whose add-on settles itself is carried along by Agent
# Link untouched — it is told so (agentlink_families: hooks.
# own_document_state("scanruler")) and would also see the book below on
# the session — so settle() here still finds, on arriving in another
# document, the state of the document it left, writes it there and sets
# it aside itself. Agent Link's settling runs first (it hangs on reading
# session.family_state and session.doc, which settle() does on its first
# two lines), so the dict this function works on is already the new
# document's. Where a host puts a kept dict back after reopening a
# document from a copy (session.family_state = kept), the state in it
# belongs to a document object that is closed: it is let go here and read
# again from the reopened document, which holds the state as it was when
# that copy was written — so a checkpoint restored from its copy takes
# ScanRuler's state back with the document, and a later state is never
# written over it.
_BOOK = "_scanruler_documents"


def _book(session):
    b = getattr(session, _BOOK, None)
    if b is None:
        b = {"owner": None, "name": None, "parked": {}}
        try:
            setattr(session, _BOOK, b)
        except AttributeError:  # a session that takes no attributes: one document, as before
            return None
    return b


def _doc_name(doc):
    try:
        return doc.Name
    except Exception:  # noqa: BLE001 — a document already closed
        return None


def doc_open(doc, name=None):
    """True while doc is an open document. Without FreeCAD's list of
    documents (the tests' stand-in) every document counts as open."""
    if doc is None:
        return False
    try:
        import FreeCAD
    except ImportError:
        return True
    ld = getattr(FreeCAD, "listDocuments", None)
    if ld is None:
        return True
    try:
        return ld().get(name if name is not None else doc.Name) is doc
    except Exception:  # noqa: BLE001 — the document is gone
        return False


def settle(session):
    """The session's ScanRuler state made the state of the document the
    session is in now (see above). Returns the document."""
    fs = getattr(session, "family_state", None)
    doc = getattr(session, "doc", None)
    if fs is None or doc is None:
        return doc
    book = _book(session)
    if book is None:
        return doc
    owner = book["owner"]
    if owner is doc:
        return doc
    if owner is None:  # the first call: what the session holds is this document's
        book["owner"], book["name"] = doc, _doc_name(doc)
        return doc
    old = fs.pop(KEY, None)
    was = book["name"]
    parked = book["parked"]
    if old is not None and doc_open(owner, was):
        try:
            from . import docstate

            docstate.mark_doc(owner, old, session)  # what a job left unwritten goes with it
        except Exception as e:  # noqa: BLE001 — kept in the session all the same
            _report(f"the state could not be written into {was}: {e}")
        parked[was] = (owner, old)
    for name in [n for n, (d, _st) in parked.items() if not doc_open(d, n)]:
        del parked[name]  # closed: FreeCAD's file has what was saved
    name = _doc_name(doc)
    rec = parked.pop(name, None)
    if rec is not None and rec[0] is doc:
        fs[KEY] = rec[1]
    book["owner"], book["name"] = doc, name
    return doc


def state(session):
    settle(session)
    fs = session.family_state
    if KEY not in fs:
        restored = _restored(session)
        if restored is not None:
            fs[KEY] = restored
    st = fs.setdefault(KEY, fresh())
    for k, v in fresh().items():
        st.setdefault(k, v)
    return st


def _restored(session):
    """The state a reopened document holds (docstate.read), or None."""
    doc = getattr(session, "doc", None)
    if doc is None or not hasattr(doc, "getObject"):
        return None
    try:
        from . import docstate

        return docstate.read(doc)
    except ImportError:
        return None
    except Exception as e:  # noqa: BLE001 — a state that cannot be read starts afresh, and says so
        _report(f"the ScanRuler state in {getattr(doc, 'Label', 'the document')} could not be read: {e}")
        return None


def before(session):
    """Before a call: a move made on the scan object in FreeCAD carried
    in (pull_pose); never stops the call."""
    try:
        if getattr(session, "family_state", None) is not None:
            state(session)  # a reopened document's state read in
            pull_pose(session)
    except Exception as e:  # noqa: BLE001
        _report(f"the scan's placement could not be read: {e}")


def pull_pose(session):
    """A move made on the scan object in FreeCAD carried into the scan and
    its elements (docstate.pull_pose); False without one."""
    doc = getattr(session, "doc", None)
    st = session.family_state.get(KEY) if getattr(session, "family_state", None) else None
    if doc is None or not st or st.get("scan") is None or getattr(st["scan"], "on_pose", None) is None:
        return False
    from . import docstate

    return docstate.pull_pose(st, doc)


def scan_of(session):
    from .errors import ToolError

    s = state(session)["scan"]
    if s is None:
        raise ToolError("invalid_state", "No scan open: scan_open { path } opens one.")
    return s


def more_formats():
    """Agent Link's readers for glTF/GLB, Collada, VRML and 3DS, where
    Agent Link has lent them (meshio.EXTRA)."""
    from . import meshio

    return meshio.extra()


def load(path, units="mm", given=True):
    """A scan from STL, PLY, OBJ, OFF or 3MF through FreeCAD's Mesh module,
    scaled to millimetres; glTF/GLB, Collada, VRML and 3DS through Agent
    Link's readers, in the units their format says unless given."""
    from . import meshio

    if units not in UNITS:
        raise ValueError(f"units: one of {', '.join(UNITS)}.")
    if meshio.extra_reads(path):
        V, F, _info = meshio.extra().read(path, units if given else None)
        return Scan(os.path.basename(path), V, F, units if given else "mm", path)
    V, F = meshio.read(path, UNITS[units])
    if len(F) == 0:
        raise ValueError(f"{os.path.basename(path)}: no triangles read.")
    return Scan(os.path.basename(path), V, F, units, path)


def from_mesh(m, name):
    """A scan from a FreeCAD mesh already in millimetres — a document's mesh object."""
    pts, tris = m.Topology
    V = points_array(pts)
    F = np.array(tris, dtype=np.int64)
    if len(F) == 0:
        raise ValueError(f"{name}: the mesh has no triangles.")
    return Scan(name, V, F, "mm", None)
