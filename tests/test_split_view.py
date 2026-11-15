# SPDX-License-Identifier: AGPL-3.0-only
# The Surface Deviation workspace's split view (ScanRuler by Stefan Hermann /
# CNC Kitchen, CompareView.tsx and CompareScene.ts, ported): the scan on the
# left — coloured by its map (jet) while Colour plot is on, grey without —
# and the reference on the right; none without both; the two cameras linked,
# the one the hand moved leading; the Split view key opening and closing it,
# and let up again when it cannot open. On a stand-in FreeCADGui, coin and
# Qt handed in explicitly.
import os
import sys
import types
import unittest
import unittest.mock

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

from test_editor_view import _Field, _Node, walk  # noqa: E402
from scanrulerfc import commands as C  # noqa: E402
from scanrulerfc import dock as DK  # noqa: E402
from scanrulerfc import split_view as SV  # noqa: E402
from scanrulerfc import scanstate as S  # noqa: E402
from scanrulerfc.handlers.deviation import dstate  # noqa: E402

V = np.array([[0, 0, 0], [10, 0, 0], [0, 10, 0], [0, 0, 10]], dtype=float)
F = np.array([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]], dtype=np.int64)


def session(scan=True, reference=True, values=True):
    s = types.SimpleNamespace(family_state={})
    st = S.state(s)
    if scan:
        st["scan"] = S.Scan("part.stl", V, F)
    d = dstate(s)
    if reference:
        d["reference"] = {"name": "part.step", "V": V * 1.0, "F": F}
    if values and scan:
        d.update(scan=st["scan"], version=getattr(st["scan"], "version", None), values=np.array([-1.0, 0.0, 1.0, 9.0]), range=1.0)
    return s


def stand_in_coin():
    coin = types.ModuleType("coin_stand_in")
    for n in ("SoSeparator", "SoShapeHints", "SoMaterial", "SoMaterialBinding", "SoCoordinate3", "SoIndexedFaceSet"):
        setattr(coin, n, type(n, (_Node,), {}))
    coin.SoShapeHints.COUNTERCLOCKWISE, coin.SoShapeHints.UNKNOWN_SHAPE_TYPE = 1, 0
    coin.SoMaterialBinding.PER_VERTEX_INDEXED = 5
    return coin


class Camera:
    """An orthographic camera's fields."""

    def __init__(self):
        for f, v in (("position", (0, 0, 10)), ("orientation", (0, 0, 0, 1)), ("focalDistance", 10.0), ("height", 50.0)):
            setattr(self, f, _Field())
            getattr(self, f).setValue(v)


class Viewer:
    def __init__(self):
        self.graph, self.cam, self.fitted = None, Camera(), 0

    def setSceneGraph(self, root):  # noqa: N802
        self.graph = root

    def viewAll(self):  # noqa: N802
        self.fitted += 1

    def getSoRenderManager(self):  # noqa: N802
        return types.SimpleNamespace(getCamera=lambda: self.cam)


class Gui:
    def __init__(self):
        self.made = []

    def createViewer(self, n, title):  # noqa: N802
        viewers = [Viewer() for _ in range(n)]
        view = types.SimpleNamespace(title=title, closed=False, viewers=viewers)

        def get(i):
            if view.closed:
                raise RuntimeError("gone")
            return viewers[i]

        view.getViewer = get
        view.close = lambda: setattr(view, "closed", True)
        self.made.append(view)
        return view


class Timer:
    def __init__(self):
        self.timeout, self.running = types.SimpleNamespace(connect=lambda fn: None), False

    def setInterval(self, ms):  # noqa: N802
        pass

    def start(self):
        self.running = True

    def stop(self):
        self.running = False


QT = types.SimpleNamespace(QtCore=types.SimpleNamespace(QTimer=Timer))


class Halves(unittest.TestCase):
    def test_scan_with_its_map_beside_the_reference(self):
        got = SV.halves(session())
        self.assertEqual((got["left"]["name"], got["right"]["name"]), ("scan", "reference"))
        c = got["left"]["colors"]
        self.assertEqual(c.shape, (4, 3))
        self.assertGreater(c[2][0], c[0][0])  # +1 is red end, -1 the blue end (jet)
        self.assertEqual(got["right"]["color"], SV.REFERENCE_BLUE)

    def test_grey_without_the_plot_or_a_map_and_none_without_both(self):
        self.assertEqual(SV.halves(session(), colour_plot=False)["left"]["color"], SV.SCAN_GREY)
        self.assertEqual(SV.halves(session(values=False))["left"]["color"], SV.SCAN_GREY)
        self.assertEqual(SV.halves(session(reference=False)), SV.NEEDS)
        self.assertEqual(SV.halves(session(scan=False)), SV.NEEDS)

    def test_the_camera_the_hand_moved_leads(self):
        self.assertEqual(SV.link_step("a1", "s", "s"), ("a", "a1"))
        self.assertEqual(SV.link_step("s", "b1", "s"), ("b", "b1"))
        self.assertEqual(SV.link_step("s", "s", "s"), (None, "s"))


class TheViewer(unittest.TestCase):
    def setUp(self):
        self.s = session()
        self.gui = Gui()
        self.sv = SV.SplitView(self.gui, stand_in_coin(), QT, lambda: self.s)

    def test_opens_fills_links_and_closes(self):
        self.assertIsNone(self.sv.show())
        view = self.gui.made[0]
        self.assertEqual(view.title, SV.TITLE)
        left, right = (v.graph for v in view.viewers)
        self.assertTrue(any(type(n).__name__ == "SoMaterialBinding" for n in walk(left)))  # per-vertex map colours
        self.assertFalse(any(type(n).__name__ == "SoMaterialBinding" for n in walk(right)))
        a, b = (v.cam for v in view.viewers)
        a.position.setValue((5, 5, 5))  # the hand on the scan's side
        self.sv.tick()
        self.assertEqual(b.position.value, (5, 5, 5))
        b.height.setValue(20.0)  # then on the reference's
        self.sv.tick()
        self.assertEqual(a.height.value, 20.0)
        self.sv.close()
        self.assertTrue(view.closed)
        self.assertFalse(self.sv.open)

    def test_refills_when_the_map_changes_and_closes_with_its_tab(self):
        self.sv.show()
        view = self.gui.made[0]
        fits = view.viewers[0].fitted
        dstate(self.s)["values"] = np.array([0.0, 0.0, 0.0, 0.0])
        self.sv.tick()
        self.assertEqual(view.viewers[0].fitted, fits + 1)
        view.close()  # the person closed the tab
        self.sv.tick()
        self.assertFalse(self.sv.open)

    def test_without_a_reference_it_does_not_open(self):
        dstate(self.s)["reference"] = None
        self.assertEqual(self.sv.show(), SV.NEEDS)
        self.assertEqual(self.gui.made, [])


class TheKey(unittest.TestCase):
    def test_a_key_that_cannot_open_it_is_let_up(self):
        # The stand-in viewer, so no real one opens where FreeCAD's GUI runs.
        no_ref = session(reference=False)
        SV._live["split"] = SV.SplitView(Gui(), stand_in_coin(), QT, lambda: no_ref)
        self.addCleanup(SV._live.__setitem__, "split", None)
        self.addCleanup(C._state["view"].pop, "ViewSplit", None)
        C._state["view"]["ViewSplit"] = True
        self.assertEqual(DK.split_view_key("ViewSplit", True, lambda: no_ref), SV.NEEDS)
        self.assertFalse(C._state["view"]["ViewSplit"])
        self.assertIsNone(DK.split_view_key("ViewSplit", False, lambda: no_ref))

    def test_the_reason_goes_to_the_report_view(self):
        no_ref = session(reference=False)
        SV._live["split"] = SV.SplitView(Gui(), stand_in_coin(), QT, lambda: no_ref)
        self.addCleanup(SV._live.__setitem__, "split", None)
        self.addCleanup(C._state["view"].pop, "ViewSplit", None)
        said = []
        with unittest.mock.patch.object(C, "_say", said.append):
            DK.split_view_key("ViewSplit", True, lambda: no_ref)
        self.assertEqual(said, [f"ScanRuler: Split view: {SV.NEEDS}"])

    def test_a_closed_tab_lets_the_key_up(self):
        s = session()
        SV._live["split"] = SV.SplitView(Gui(), stand_in_coin(), QT, lambda: s)
        self.addCleanup(SV._live.__setitem__, "split", None)
        self.addCleanup(C._state["view"].pop, "ViewSplit", None)
        C._state["view"]["ViewSplit"] = True
        self.assertIsNone(DK.split_view_key("ViewSplit", True, lambda: s))
        SV._live["split"].view.close()  # the person closed the tab
        SV._live["split"].tick()
        self.assertFalse(C._state["view"]["ViewSplit"])


class OutsideDeviation(unittest.TestCase):
    """Pressed in another workspace (Reverse engineer, a scan open): the
    key says why in the Report view and the panel, and is let up."""

    def test_the_reason_said_and_the_key_let_up(self):
        s = session()
        SV._live["split"] = SV.SplitView(Gui(), stand_in_coin(), QT, lambda: s)
        self.addCleanup(SV._live.__setitem__, "split", None)
        self.addCleanup(C._state["view"].pop, "ViewSplit", None)
        C._state["view"]["ViewSplit"] = True
        said = []
        with unittest.mock.patch.object(C, "_say", said.append):
            why = DK.split_view_key("ViewSplit", True, lambda: s, "reverse")
        self.assertIn("Surface Deviation", why)
        self.assertEqual(said, [f"ScanRuler: Split view: {why}"])
        self.assertFalse(C._state["view"]["ViewSplit"])
        self.assertFalse(SV._live["split"].open)
        self.assertIn(why, DK.header_html({**DK.header({}), "error": why}))
        # In Surface Deviation with both open, it opens.
        self.assertIsNone(DK.split_view_key("ViewSplit", True, lambda: s, "deviation"))
        self.assertTrue(SV._live["split"].open)

    def test_the_command_is_active_everywhere(self):
        spec = next(x for x in _view_specs() if x["command"] == "ScanRuler_ViewSplit")
        was = C._state["workspace"]
        self.addCleanup(C._state.__setitem__, "workspace", was)
        C._state["workspace"] = "reverse"
        self.assertTrue(C.ViewCommand(spec).IsActive())


class RunAsACommand(unittest.TestCase):
    """FreeCADGui.runCommand(name) — Agent Link's cmd_run — calls a
    checkable command's Activated with 0 and leaves its action as it was:
    each run is a press. A click hands the action's new state."""

    def setUp(self):
        spec = next(x for x in _view_specs() if x["command"] == "ScanRuler_ViewSplit")
        self.cmd = C.ViewCommand(spec)
        self.sent = []
        p = unittest.mock.patch.object(C, "_to_panel", lambda *a: self.sent.append(a))
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(C._state["view"].pop, "ViewSplit", None)
        C._state["view"].pop("ViewSplit", None)

    def test_each_run_is_a_press(self):
        for _ in range(3):
            self.cmd.Activated(0)
        self.assertEqual([a[2] for a in self.sent], [True, False, True])

    def test_a_click_hands_the_new_state(self):
        self.cmd.Activated(True)
        self.cmd.Activated(False)
        self.cmd.Activated(None)
        self.assertEqual([a[2] for a in self.sent], [True, False, True])


def _view_specs():
    import scanrulerfc.workspaces as W

    out = []

    def walk_specs(x):
        if isinstance(x, dict):
            if str(x.get("command", "")).startswith("ScanRuler_View"):
                out.append(x)
            for v in x.values():
                walk_specs(v)
        elif isinstance(x, (list, tuple)):
            for v in x:
                walk_specs(v)

    walk_specs([getattr(W, n) for n in dir(W) if n.isupper()])
    return out


if __name__ == "__main__":
    unittest.main()
