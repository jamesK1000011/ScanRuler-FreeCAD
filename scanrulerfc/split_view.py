# SPDX-License-Identifier: AGPL-3.0-only
# Ported from ScanRuler by Stefan Hermann (CNC Kitchen),
# github.com/CNCKitchen/ScanRuler: src/ui/CompareView.tsx and
# src/viewer/CompareScene.ts (the split view: the reference in a viewport of
# its own beside the scan's, the two cameras linked, each following the
# other when the hand is on it) and the Split view key of src/ui/ViewBar.tsx.
#
# The Surface Deviation workspace's split view in FreeCAD: a two-pane 3D
# viewer (FreeCADGui.createViewer(2)) beside the document's own view, the
# scan on the left — coloured by its deviation map when Colour plot is on,
# jet as ScanRuler's default — and the reference on the right, their
# cameras linked both ways. ScanRuler's Split view key opens and closes
# it; it needs a scan and a reference, as the original's key does.
#
# The top half is pure (what each half shows, which camera leads); the
# SplitView class takes FreeCADGui, the coin module and Qt as arguments, so
# the tests drive it with stand-ins.

import numpy as np

TITLE = "ScanRuler split view"
TICK_MS = 50
SCAN_GREY = (0.72, 0.72, 0.70)
REFERENCE_BLUE = (0.45, 0.62, 0.85)
NEEDS = "The split view shows the scan beside the reference: open a scan and a reference first."


# ---- what each half shows (pure) ------------------------------------------------------------------


def halves(session, colour_plot=True):
    """{"left": half, "right": half} — the scan, the reference — or a str
    saying why there is no split view. A half: {name, V, F, color} or, for a
    scan with its map shown, {name, V, F, colors} (per-vertex RGB 0..1)."""
    from . import scanstate as S
    from .handlers.deviation import dstate

    scan = S.state(session)["scan"]
    ref = dstate(session)["reference"]
    if scan is None or ref is None:
        return NEEDS
    left = {"name": "scan", "V": np.asarray(scan.V, dtype=float), "F": np.asarray(scan.F, dtype=np.int64), "color": SCAN_GREY}
    if colour_plot:
        colors = _map_colors(session)
        if colors is not None and len(colors) == len(left["V"]):
            left = {**left, "colors": colors}
            left.pop("color")
    right = {"name": "reference", "V": np.asarray(ref["V"], dtype=float), "F": np.asarray(ref["F"], dtype=np.int64), "color": REFERENCE_BLUE}
    return {"left": left, "right": right}


def _map_colors(session):
    from . import colormap
    from .errors import ToolError
    from .render_layers import deviation_map

    try:
        m = deviation_map(session, {})
    except ToolError:
        return None
    lo, hi = m["range"]
    rgb = colormap.map_values(m["layers"][0]["values"], lo, hi, m.get("cmap") or colormap.DEFAULT)
    return rgb.astype(float) / 255.0


def contents_key(session, colour_plot=True):
    """Moves when what the halves show changes: another scan or pose,
    another reference, another map, Colour plot switched."""
    from . import scanstate as S
    from .handlers.deviation import dstate

    st = S.state(session)
    d = dstate(session)
    scan = st["scan"]
    return (id(scan), getattr(scan, "version", None), id(d["reference"]), id(d.get("values")), d.get("range"), d.get("maxDistance"), bool(colour_plot))


def link_step(a, b, last):
    """Which camera leads (CompareView: the one the hand is on): ("a", s) to
    copy a onto b, ("b", s) the other way, or (None, last) when neither
    moved. `a`, `b` are the cameras' states, `last` the state both were
    left in."""
    if a != last:
        return "a", a
    if b != last:
        return "b", b
    return None, last


# ---- coin ----------------------------------------------------------------------------------------


def mesh_node(coin, half):
    """A half as a Coin subgraph: its triangles, in one colour or coloured
    per vertex."""
    sep = coin.SoSeparator()
    hints = coin.SoShapeHints()
    hints.vertexOrdering.setValue(coin.SoShapeHints.COUNTERCLOCKWISE)
    hints.shapeType.setValue(coin.SoShapeHints.UNKNOWN_SHAPE_TYPE)
    sep.addChild(hints)
    mat = coin.SoMaterial()
    if "colors" in half:
        c = np.asarray(half["colors"], dtype=float)
        mat.diffuseColor.setValues(0, len(c), c.tolist())
        bind = coin.SoMaterialBinding()
        bind.value.setValue(coin.SoMaterialBinding.PER_VERTEX_INDEXED)
        sep.addChild(mat)
        sep.addChild(bind)
    else:
        mat.diffuseColor.setValue(*half["color"])
        sep.addChild(mat)
    V = np.asarray(half["V"], dtype=float)
    coords = coin.SoCoordinate3()
    coords.point.setValues(0, len(V), V.tolist())
    sep.addChild(coords)
    F = np.asarray(half["F"], dtype=np.int64)
    flat = np.hstack([F, -np.ones((len(F), 1), dtype=np.int64)]).reshape(-1).tolist()
    faces = coin.SoIndexedFaceSet()
    faces.coordIndex.setValues(0, len(flat), flat)
    if "colors" in half:
        faces.materialIndex.setValues(0, len(flat), flat)
    sep.addChild(faces)
    return sep


def camera_state(cam):
    """A camera as a tuple to compare and copy: its type, position,
    orientation, focal distance and height (or height angle)."""
    def val(field):
        v = field.getValue()
        return tuple(round(float(x), 9) for x in (v.getValue() if hasattr(v, "getValue") else v)) if not isinstance(v, (int, float)) else round(float(v), 9)

    size = "height" if hasattr(cam, "height") else "heightAngle"
    return (type(cam).__name__, val(cam.position), val(cam.orientation), val(cam.focalDistance), size, val(getattr(cam, size)))


def copy_camera(src, dst):
    for f in ("position", "orientation", "focalDistance"):
        getattr(dst, f).setValue(getattr(src, f).getValue())
    for f in ("height", "heightAngle"):
        if hasattr(src, f) and hasattr(dst, f):
            getattr(dst, f).setValue(getattr(src, f).getValue())


class SplitView:
    """The split viewer, open or not. `gui` is FreeCADGui (createViewer),
    `coin` pivy's coin, `qt` the PySide module (a QTimer), `session_fn` the
    panel's session, `colour_plot_fn` whether Colour plot is on."""

    def __init__(self, gui, coin, qt, session_fn, colour_plot_fn=lambda: True):
        self.gui, self.coin, self.qt = gui, coin, qt
        self.session_fn, self.colour_plot_fn = session_fn, colour_plot_fn
        self.view = None
        self.viewers = []
        self.roots = []
        self.shown = None
        self.last = None
        self.timer = None
        self.on_closed = None  # fn(): the person closed its tab (the key let up)

    @property
    def open(self):
        return self.view is not None

    def show(self):
        """Open it (or refresh it); a str saying why not."""
        got = halves(self.session_fn(), self.colour_plot_fn())
        if isinstance(got, str):
            self.close()
            return got
        if self.view is None:
            self.view = self.gui.createViewer(2, TITLE)
            self.viewers = [self.view.getViewer(0), self.view.getViewer(1)]
            self.roots = []
            for v in self.viewers:
                root = self.coin.SoSeparator()
                root.setName("ScanRulerSplit")
                _put_scene(v, root)
                self.roots.append(root)
            self.timer = self.qt.QtCore.QTimer()
            self.timer.setInterval(TICK_MS)
            self.timer.timeout.connect(self.tick)
            self.timer.start()
        self._fill(got)
        return None

    def _fill(self, got):
        for root, half in zip(self.roots, (got["left"], got["right"])):
            root.removeAllChildren()
            root.addChild(mesh_node(self.coin, half))
        self.shown = contents_key(self.session_fn(), self.colour_plot_fn())
        for v in self.viewers:
            try:
                v.viewAll()
            except Exception:  # noqa: BLE001
                pass
        self.last = None
        self._link(first=True)

    def tick(self):
        if self.view is None:
            return
        if not _alive(self.view):
            self.close()
            if self.on_closed is not None:
                self.on_closed()
            return
        key = contents_key(self.session_fn(), self.colour_plot_fn())
        if key != self.shown:
            if isinstance(self.show(), str):
                return
        self._link()

    def _cameras(self):
        return [v.getSoRenderManager().getCamera() for v in self.viewers]

    def _link(self, first=False):
        a, b = self._cameras()
        if first:
            copy_camera(a, b)
            self.last = camera_state(a)
            return
        lead, self.last = link_step(camera_state(a), camera_state(b), self.last)
        if lead == "a":
            copy_camera(a, b)
        elif lead == "b":
            copy_camera(b, a)

    def close(self):
        if self.timer is not None:
            self.timer.stop()
            self.timer = None
        if self.view is not None:
            try:
                if _alive(self.view):
                    self.view.close()
            except Exception:  # noqa: BLE001 — closed by the person already
                pass
        self.view = None
        self.viewers, self.roots, self.shown, self.last = [], [], None, None


def _put_scene(viewer, root):
    fn = getattr(viewer, "setSceneGraph", None)
    if fn is not None:
        fn(root)
    else:
        viewer.getSceneGraph().addChild(root)


def _alive(view):
    """False once the person closed the split viewer's tab."""
    try:
        view.getViewer(0)
        return True
    except Exception:  # noqa: BLE001
        return False


_live = {"split": None}


def toggle(on, session_fn, colour_plot_fn=lambda: True):
    """The Split view key: the split viewer opened or closed. A str saying
    why it could not open, else None."""
    sv = _live["split"]
    if not on:
        if sv is not None:
            sv.close()
        return None
    if sv is None:
        try:
            import FreeCADGui
            from pivy import coin
            import PySide as qt
        except ImportError:
            return "The split view needs FreeCAD's GUI."
        sv = _live["split"] = SplitView(FreeCADGui, coin, qt, session_fn, colour_plot_fn)
    return sv.show()
