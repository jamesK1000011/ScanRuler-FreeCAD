# SPDX-License-Identifier: AGPL-3.0-only
# The feature editor in the 3D view (editor_view.py; ScanRuler by Stefan
# Hermann / CNC Kitchen, extendGrips.ts and reScene.ts, ported): the screen
# maths of a drag along an arrow and round a ring, which grip is under the
# pointer, where the field stands off an arrow's tip; then the Overlay on a
# stand-in coin, a stand-in Qt and a stand-in view (an orthographic camera
# looking down -Z, 1 px per mm) — the ghost and the grips added to the scene
# graph, a press away from the grips left to the navigation, a press on a
# grip taken, dragged and let go with the field on it, and everything taken
# away again. The stand-ins are handed in explicitly: no pivy or PySide is
# imported, whatever is installed.
import math
import os
import sys
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

from test_reverse_editor import Part  # noqa: E402
from scanrulerfc import editor_view as V  # noqa: E402
from scanrulerfc.reverse.editor import Editor  # noqa: E402


# ---- a stand-in coin -------------------------------------------------------------------------------

class _Field:
    def __init__(self):
        self.value = None

    def setValue(self, *a):  # noqa: N802
        self.value = a[0] if len(a) == 1 else a

    def setValues(self, start, n, values):  # noqa: N802
        self.value = list(values)[:n]

    def getValue(self):  # noqa: N802
        return self.value


class _Node:
    def __init__(self, *a):
        self.children = []
        self.name = None

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        f = _Field()
        setattr(self, name, f)
        return f

    def addChild(self, c):  # noqa: N802
        self.children.append(c)

    def removeChild(self, c):  # noqa: N802
        self.children.remove(c)

    def removeAllChildren(self):  # noqa: N802
        self.children = []

    def setName(self, n):  # noqa: N802
        self.name = n


class _Event:
    BUTTON1 = 1

    def __init__(self, kind, x, y, press=None, shift=False):
        self.kind, self.pos, self.press, self.shift = kind, (x, y), press, shift

    def getPosition(self):  # noqa: N802
        return types.SimpleNamespace(getValue=lambda: self.pos)

    def isOfType(self, t):  # noqa: N802
        return t == self.kind

    def wasShiftDown(self):  # noqa: N802
        return self.shift

    def wasCtrlDown(self):  # noqa: N802
        return False


def stand_in_coin():
    coin = types.ModuleType("coin_stand_in")
    for n in ("SoSeparator", "SoAnnotation", "SoMatrixTransform", "SoMaterial", "SoShapeHints", "SoCoordinate3", "SoNormal", "SoNormalBinding",
              "SoIndexedFaceSet", "SoLightModel", "SoPickStyle", "SoBaseColor", "SoDrawStyle", "SoLineSet", "SoTransform", "SoCone"):
        setattr(coin, n, type(n, (_Node,), {}))
    coin.SoShapeHints.COUNTERCLOCKWISE = 1
    coin.SoShapeHints.UNKNOWN_SHAPE_TYPE = 0
    coin.SoNormalBinding.PER_VERTEX_INDEXED = 5
    coin.SoLightModel.BASE_COLOR = 0
    coin.SoPickStyle.UNPICKABLE = 2
    coin.SbVec3f = lambda *a: a
    coin.SbRotation = lambda a, b: (a, b)
    coin.SbMatrix = lambda *a: a

    class Loc:
        @staticmethod
        def getClassTypeId():  # noqa: N802
            return "loc"

    class Btn:
        BUTTON1 = 1

        @staticmethod
        def getClassTypeId():  # noqa: N802
            return "btn"

        @staticmethod
        def isButtonPressEvent(ev, b):  # noqa: N802
            return ev.press is True

        @staticmethod
        def isButtonReleaseEvent(ev, b):  # noqa: N802
            return ev.press is False

    coin.SoLocation2Event, coin.SoMouseButtonEvent = Loc, Btn
    return coin


class _Vec:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


class StandInView:
    """Looking down -Z, orthographic, 1 px per mm, the viewport 800 x 600
    with (0, 0) of the part at (400, 300)."""

    def __init__(self):
        self.graph = _Node()
        self.callbacks = []
        self.redirected = False
        self.widget = None

    def getSceneGraph(self):  # noqa: N802
        return self.graph

    def addEventCallbackPivy(self, t, fn):  # noqa: N802
        self.callbacks.append((t, fn))
        return fn

    def removeEventCallbackPivy(self, t, fn):  # noqa: N802
        self.callbacks.remove((t, fn))

    def getPointOnViewport(self, v):  # noqa: N802
        return (v.x + 400, v.y + 300)

    def projectPointToLine(self, x, y):  # noqa: N802
        return _Vec(x - 400, y - 300, 100), _Vec(x - 400, y - 300, -100)

    def getViewDirection(self):  # noqa: N802
        return _Vec(0, 0, -1)

    def getSize(self):  # noqa: N802
        return (800, 600)

    def getObjectInfo(self, pos):  # noqa: N802
        """The scan under every pixel, as a plane at z = 30."""
        x, y = pos
        return {"Document": "D", "Object": "Scan", "Component": "Facet1", "x": x - 400.0, "y": y - 300.0, "z": 30.0}

    def getViewer(self):  # noqa: N802
        """FreeCAD's View3DInventorViewerPy, where the redirect lives."""
        view = self

        class Viewer:
            def setRedirectToSceneGraph(self, on):  # noqa: N802
                view.redirected = on

        return Viewer()

    def graphicsView(self):  # noqa: N802
        if self.widget is None:
            raise AttributeError("no graphics view")
        return self.widget

    def send(self, ev):
        handled = []
        cb = types.SimpleNamespace(getEvent=lambda: ev, setHandled=lambda: handled.append(True))
        for t, fn in list(self.callbacks):
            if t == ev.kind:
                fn(cb)
        return bool(handled)


# ---- a stand-in Qt for the field ---------------------------------------------------------------------

class _Signal:
    def __init__(self):
        self.fns = []

    def connect(self, fn):
        self.fns.append(fn)

    def emit(self, *a):
        for fn in self.fns:
            fn(*a)


class _Widget:
    def __init__(self, *a):
        self.visible, self.pos, self.text_, self.ro, self.focused = False, None, "", False, False
        self.returnPressed, self.activated = _Signal(), _Signal()

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return lambda *a, **k: None

    def show(self):
        self.visible = True

    def hide(self):
        self.visible = False

    def move(self, x, y):
        self.pos = (x, y)

    def width(self):
        return 80

    def height(self):
        return 20

    def setText(self, t):  # noqa: N802
        self.text_ = t

    def text(self):
        return self.text_

    def hasFocus(self):  # noqa: N802
        return self.focused

    def setReadOnly(self, ro):  # noqa: N802
        self.ro = ro

    def setFocus(self):  # noqa: N802
        self.focused = True

    def viewport(self):
        return self

    def devicePixelRatioF(self):  # noqa: N802
        return 1.0


def stand_in_qt():
    w = types.SimpleNamespace(QFrame=_Widget, QHBoxLayout=_Widget, QLineEdit=_Widget, QLabel=_Widget, QShortcut=_Widget)
    core = types.SimpleNamespace(Qt=types.SimpleNamespace(Key_Escape=1, WidgetShortcut=0))
    gui = types.SimpleNamespace(QKeySequence=lambda k: k)
    return types.SimpleNamespace(QtWidgets=w, QtCore=core, QtGui=gui)


def walk(node):
    yield node
    for c in getattr(node, "children", []):
        yield from walk(c)


# ---- the tests ---------------------------------------------------------------------------------------

class ScreenMaths(unittest.TestCase):
    def test_along_an_arrow(self):
        # The ray straight down through x = 7 meets the X axis at 7.
        self.assertAlmostEqual(V.param_along([0, 0, 0], [1, 0, 0], [7, 3, 50], [0, 0, -1]), 7)
        self.assertIsNone(V.param_along([0, 0, 0], [0, 0, 1], [0, 0, 50], [0, 0, -1]))  # looking down the arrow

    def test_round_a_ring(self):
        a = V.angle_around([0, 0, 0], [0, 0, 1], [1, 0, 0], [0, 1, 0], [0, 5, 50], [0, 0, -1])
        self.assertAlmostEqual(a, math.pi / 2)
        self.assertIsNone(V.angle_around([0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1], [0, 5, 50], [0, 0, -1]))  # edge on
        self.assertAlmostEqual(V.short_step(-3.0, 3.0), 2 * math.pi - 6.0)

    def test_which_grip_and_the_shape_at_the_zoom(self):
        screen = [{"side": "a", "points": [(0, 0), (40, 0)]}, {"side": "b", "points": [(0, 20), (40, 20)]}]
        self.assertEqual(V.grip_at(screen, 20, 3), "a")
        self.assertEqual(V.grip_at(screen, 20, 17), "b")
        self.assertIsNone(V.grip_at(screen, 20, 10))
        s = V.grip_shape({"side": "x", "shape": "arrow", "position": [0, 0, 0], "dir": [0, 0, 2], "size": 44, "pixels": True, "standoff": 10}, 0.5)
        self.assertEqual((s["base"], s["tip"]), ([0, 0, 5], [0, 0, 27]))
        r = V.grip_shape({"side": "t", "shape": "ring", "position": [1, 1, 1], "dir": [0, 1, 0], "size": 3}, 0.5)
        self.assertEqual(r["radius"], 3)
        pts = V.ring_points([0, 0, 0], [0, 0, 1], 2, 8)
        self.assertTrue(all(abs(math.hypot(p[0], p[1]) - 2) < 1e-9 for p in pts))

    def test_the_field_stands_off_the_tip_the_way_it_points(self):
        x, y = V.field_place((100, 100), (1, 0), (80, 20), gap=6)
        self.assertEqual((x, y), (106, 90))  # to the right, centred on it
        x, y = V.field_place((100, 100), (0, -1), (80, 20), gap=6)
        self.assertEqual((x, y), (60, 74))  # pointing up: above it
        self.assertEqual(V.field_place((100, 100), None, (80, 20)), (60, 90))  # a ring: centred


class OverlayInAView(unittest.TestCase):
    def setUp(self):
        self.p = Part()
        self.ed = Editor()
        self.ed.open_new("extrude", self.p.store.part())
        self.view = StandInView()
        self.view.widget = _Widget()
        self.coin = stand_in_coin()
        self.hidden = []
        env = {**self.p.env, "features": lambda: self.p.store.part()["features"], "units": lambda: "mm",
               "hide": lambda ids, on: self.hidden.append((list(ids), on)), "body_of": lambda d, o: None,
               "keep_selection": lambda: (lambda: self.restored.append(True)), "later": lambda fn: fn()}
        self.restored = []
        self.ov = V.Overlay(self.ed, self.view, self.coin, stand_in_qt(), _Vec, env)

    def test_attached_drawn_and_taken_away(self):
        self.assertIn(self.ov.root, self.view.graph.children)
        self.assertEqual(len(self.view.callbacks), 2)
        self.ov.tick()
        self.assertEqual(self.ed.ghost["status"], "ok")
        names = [type(n).__name__ for n in walk(self.ov.ghost_sep)]
        self.assertIn("SoIndexedFaceSet", names)
        fills = [n for n in walk(self.ov.grip_sep) if getattr(n, "name", None) == "GripFill"]
        cones = [n for f in fills for n in walk(f) if type(n).__name__ == "SoCone"]
        self.assertEqual(len(cones), 3)  # From, To and the taper
        self.ov.detach()
        self.assertEqual(self.view.graph.children, [])
        self.assertEqual(self.view.callbacks, [])

    def test_a_press_off_the_grips_is_the_navigation_s(self):
        self.ov.tick()
        self.assertFalse(self.view.send(_Event("loc", 50, 50)))
        self.assertFalse(self.view.redirected)
        self.assertFalse(self.view.send(_Event("btn", 50, 50, press=True)))
        self.assertFalse(self.ed.dragging)

    def test_a_grip_hovered_pressed_dragged_and_let_go(self):
        self.ov.tick()
        to = next(s for s in self.ov.screen if s["side"] == "extrudeTo")
        # Seen from above, the To arrow is a point at (405, 305): hover it.
        x, y = to["points"][0]
        self.view.send(_Event("loc", x, y))
        self.assertEqual(self.ov.lit, "extrudeTo")
        self.assertTrue(self.view.redirected)  # the orbit kept from under the hand
        # Seen from above the arrow runs into the screen and cannot be
        # dragged: the press is refused, the navigation keeps it.
        self.assertFalse(self.view.send(_Event("btn", x, y, press=True)))

    def test_a_drag_along_the_taper_arrow(self):
        self.ov.tick()
        taper = next(s for s in self.ov.screen if s["side"] == "taper")
        (x0, y0), (x1, y1) = taper["points"]
        self.view.send(_Event("loc", x0, y0))
        self.assertEqual(self.ov.lit, "taper")
        self.assertTrue(self.view.send(_Event("btn", x0, y0, press=True)))
        self.assertTrue(self.ed.dragging)
        self.assertEqual(self.ed.field, "taper")
        self.assertTrue(self.view.send(_Event("loc", x0 + 10, y0)))  # 10 mm out at a 10 mm run: 45°
        self.assertEqual(self.ed.record["draftDeg"], -45)
        self.assertTrue(self.ov.field.edit.ro)  # the field reads while the hand is on the grip
        self.assertTrue(self.view.send(_Event("btn", x0 + 200, y0 + 200, press=False)))
        self.assertFalse(self.ed.dragging)
        self.assertFalse(self.view.redirected)
        self.ov.tick()
        f = self.ov.field
        self.assertTrue(f.frame.visible)
        self.assertEqual(f.edit.text(), "45")
        self.assertFalse(f.edit.ro)
        f.edit.returnPressed.fns[0]()  # Enter on the text as it stands
        f.edit.setText("30")
        f.edit.returnPressed.emit()
        self.assertEqual(self.ed.record["draftDeg"], -30)

    def test_a_straight_extrude_s_ghost_stretches_under_the_hand(self):
        self.ov.tick()
        self.assertIsNotNone(self.ov.ghost_base)
        self.ed.grip_drag("extrudeTo", 0, "start")
        self.ed.grip_drag("extrudeTo", 10, "move")
        self.ov.changed_at = 1e9  # the hand still moving
        self.ov.ghost_step(1e9, self.p.store.part()["features"])
        m = self.ov.stretch_node.matrix.value
        self.assertAlmostEqual(m[10], 2.0)  # Z scaled from 0..10 to 0..20

    def test_a_click_on_the_part_sets_the_extrude_s_end_and_selects_nothing(self):
        self.ov.tick()
        # A drag of the view: the navigation's, and nothing for the box.
        self.assertFalse(self.view.send(_Event("btn", 100, 100, press=True)))
        self.view.send(_Event("loc", 160, 140))
        self.assertFalse(self.view.send(_Event("btn", 160, 140, press=False)))
        self.assertEqual(self.ed.record["extent"]["to"], 10)
        # A click: the scan's point is 30 over the sketch plane.
        self.assertFalse(self.view.send(_Event("btn", 100, 100, press=True)))
        self.assertTrue(self.view.send(_Event("btn", 101, 100, press=False)))
        self.assertEqual(self.ed.record["extent"], {"kind": "distance", "from": 0, "to": 30})
        self.assertEqual(self.restored, [True])  # FreeCAD's selection put back as it was

    def test_grips_read_on_the_ghost_white_in_a_dark_rim_lit_amber(self):
        self.ov.tick()
        self.assertEqual(self.ed.ghost["status"], "ok")
        sep = self.ov.grip_sep.children[2]  # after the light model and the pick style
        rim, fill = [n for n in sep.children if getattr(n, "name", None) in ("GripOutline", "GripFill")]
        self.assertLess(sep.children.index(rim), sep.children.index(fill))  # the rim under the fill
        colour = lambda n: next(c for c in n.children if type(c).__name__ == "SoBaseColor").rgb.value  # noqa: E731
        width = lambda n: next(c for c in n.children if type(c).__name__ == "SoDrawStyle").lineWidth.value  # noqa: E731
        self.assertEqual(colour(rim), V.rgb(V.GRIP_OUTLINE))
        self.assertEqual(width(rim), V.GRIP_LINE_PX + 2 * V.GRIP_OUTLINE_PX)
        self.assertEqual(width(fill), V.GRIP_LINE_PX)  # the grip's size kept
        fills = [colour(n) for n in walk(self.ov.grip_sep) if getattr(n, "name", None) == "GripFill"]
        self.assertNotIn(V.rgb(self.ed.ghost["color"]), fills)  # never the ghost's own colour
        self.assertIn(V.rgb(V.GRIP_FILL), fills)
        # The rim's cone a little bigger than the head it rims.
        cone = lambda n: next(c for c in n.children if type(c).__name__ == "SoCone")  # noqa: E731
        taper = next(s for s in self.ov.shapes if s["side"] == "taper")
        i = self.ov.shapes.index(taper)
        tsep = self.ov.grip_sep.children[2 + i]
        trim, tfill = [n for n in tsep.children if getattr(n, "name", None) in ("GripOutline", "GripFill")]
        self.assertAlmostEqual(cone(trim).height.value, cone(tfill).height.value * V.GRIP_CONE_RIM)
        # Hovered: lit.
        x0, y0 = next(s for s in self.ov.screen if s["side"] == "taper")["points"][0]
        self.view.send(_Event("loc", x0, y0))
        tsep = self.ov.grip_sep.children[2 + i]
        tfill = next(n for n in tsep.children if getattr(n, "name", None) == "GripFill")
        self.assertEqual(colour(tfill), V.rgb(V.GRIP_LIT))

    def test_a_replaced_body_is_hidden_and_shown_again(self):
        self.ov.ghost_sep.removeAllChildren()
        self.ed.set_ghost({"status": "ok", "mesh": {"positions": [0, 0, 0, 1, 0, 0, 0, 1, 0], "indices": [0, 1, 2]}, "color": "#1877c0", "replaces": [2], "solid": True})
        self.ov.draw_ghost()
        self.assertEqual(self.hidden, [([2], True)])
        self.ov.detach()
        self.assertEqual(self.hidden[-1], ([2], False))

    def test_a_box_that_picks_on_the_body_keeps_it_in_sight(self):
        self.ed.open_new("fillet", self.p.store.part(), [{"id": 2, "surface": False, "box": None}])
        self.ed.set_ghost({"status": "ok", "mesh": {"positions": [0, 0, 0, 1, 0, 0, 0, 1, 0], "indices": [0, 1, 2]}, "color": "#1877c0", "replaces": [2], "solid": True})
        self.ov.draw_ghost()
        self.assertEqual(self.hidden, [])
        mat = next(n for n in walk(self.ov.ghost_sep) if type(n).__name__ == "SoMaterial")
        self.assertEqual(mat.transparency.value, V.GHOST_TRANSPARENCY)
        self.assertTrue(any(type(n).__name__ == "SoPickStyle" for n in walk(self.ov.ghost_sep)))


class BodyView(StandInView):
    """The stand-in view with a body under every pixel at z = 10: the
    container's compound left of x = 0 of the part, the body right of it."""

    def getObjectInfo(self, pos):  # noqa: N802
        x, y = pos
        obj = "ScanRulerReverse" if x < 400 else "ReverseBody"
        return {"Document": "D", "Object": obj, "Component": getattr(self, "component", "Edge1"), "x": x - 400.0, "y": y - 300.0, "z": 10.0}


class FilletPicks(unittest.TestCase):
    """A fillet's (and a chamfer's) edges clicked on the body in the view:
    the edge under the click toggled in the box, whether the scene graph saw
    the press, only the release, or neither."""

    def setUp(self):
        from test_reverse_picks import BACK, FRONT, Builder as PickBuilder

        self.FRONT, self.BACK = FRONT, BACK
        self.ed = Editor()
        self.ed.open_new("fillet", {"features": [], "nextFeatureId": 2}, [{"id": 2, "surface": False, "box": None}])
        self.view = BodyView()
        self.coin = stand_in_coin()
        self.warned, self.later = [], []
        # FreeCAD's selection, as the stand-in's keep_selection reads it and
        # its restore puts it back; unselect takes the box's hits out.
        self.sel, self.unselected = [("D", "Other", "Face1")], []

        def keep():
            was = list(self.sel)

            def restore():
                self.sel[:] = was
            return restore

        def unselect(hits):
            self.unselected.append(list(hits))
            self.sel[:] = [s for s in self.sel if not V.selected_by(hits, *s)]

        store = types.SimpleNamespace(builder=PickBuilder())
        env = {"store": lambda: store, "features": lambda: [], "hide": lambda ids, on: None,
               "body_of": lambda d, o: 2 if o == "ReverseBody" else None,
               "body_at": lambda d, p: 2 if abs(p[2] - 10) < 1e-6 else None,
               "keep_selection": keep, "unselect": unselect, "later": self.later.append, "warn": self.warned.append}
        self.ov = V.Overlay(self.ed, self.view, self.coin, None, _Vec, env)

    def run_later(self):
        while self.later:
            self.later.pop(0)()

    def click(self, x, y, press=True, release=True, qt=False):
        if qt:
            self.ov.qt_pressed(x, 600 - y)
        if press:
            self.view.send(_Event("btn", x, y, press=True))
        if qt:
            self.ov.qt_released(x, 600 - y)
        handled = self.view.send(_Event("btn", x, y, press=False)) if release else False
        self.run_later()
        return handled

    def test_an_edge_clicked_is_picked_and_clicked_again_let_go(self):
        self.assertTrue(self.ed.wants_clicks())
        self.assertTrue(self.click(403, 300))  # (3, 0, 10): the front top edge
        self.assertEqual(self.ed.record["edges"], [self.FRONT])
        self.assertTrue(self.click(405, 310))  # the back one
        self.assertEqual(self.ed.record["edges"], [self.FRONT, self.BACK])
        self.assertTrue(self.click(403, 300))
        self.assertEqual(self.ed.record["edges"], [self.BACK])
        self.assertEqual(self.warned, [])

    def test_a_chamfer_too(self):
        self.ed.open_new("chamfer", {"features": [], "nextFeatureId": 2}, [{"id": 2, "surface": False, "box": None}])
        self.assertTrue(self.click(403, 300))
        self.assertEqual(self.ed.record["edges"], [self.FRONT])

    def test_the_press_taken_by_the_navigation(self):
        self.assertTrue(self.click(403, 300, press=False, qt=True))
        self.assertEqual(self.ed.record["edges"], [self.FRONT])
        self.assertEqual(self.ov.qt_click, False)

    def test_press_and_release_both_taken_by_the_navigation(self):
        self.click(403, 300, press=False, release=False, qt=True)
        self.assertEqual(self.ed.record["edges"], [self.FRONT])

    def test_one_click_seen_twice_counts_once(self):
        self.click(403, 300, qt=True)
        self.assertEqual(self.ed.record["edges"], [self.FRONT])

    def test_a_drag_seen_by_qt_is_no_click(self):
        self.ov.qt_pressed(403, 300)
        self.ov.qt_released(460, 340)
        self.view.send(_Event("btn", 460, 260, press=False))
        self.run_later()
        self.assertEqual(self.ed.record["edges"], [])

    def test_a_click_on_the_container_s_compound_finds_the_body(self):
        self.ed.record = {**self.ed.record, "body": 2}
        self.ov.click(388, 300)  # the container is hit at (-12, 0, 10): no edge within 8 px
        self.assertEqual(self.ed.record["edges"], [])
        self.assertTrue(self.warned and self.warned[-1].startswith("fillet pick: no edge of body 2"))
        self.assertTrue(self.ov.click(398 + 5, 300))
        self.assertEqual(self.ed.record["edges"], [self.FRONT])

    def test_a_click_on_the_face_beside_an_edge_takes_the_edge(self):
        # The live run: the view's pick found the top face a hair inside the
        # edge (Face2, not Edge1). Within EDGE_REACH_PX pixels of the edge
        # the edge wins, whatever the zoom (here 1 mm a pixel: 4 mm off,
        # twice EDGE_REACH_MM).
        self.assertAlmostEqual(V.mm_per_pixel(self.view, [3, 4, 10], _Vec), 1.0, places=6)
        self.view.component = "Face2"
        self.assertTrue(self.ov.click(403, 304))
        self.assertEqual(self.ed.record["edges"], [self.FRONT])
        self.assertEqual(self.warned, [])
        # Past 8 px from every edge: the face's middle picks nothing.
        self.assertFalse(self.ov.click(405, 290))
        self.assertIn("within 8.00 mm", self.warned[-1])

    def test_the_reach_is_pixels_at_the_zoom_never_under_two_mm(self):
        from scanrulerfc.reverse import picks as K

        self.assertEqual(K.edge_reach(1.0), 8.0)
        self.assertEqual(K.edge_reach(0.01), K.EDGE_REACH_MM)
        self.assertEqual(K.edge_reach(None), K.EDGE_REACH_MM)
        self.assertEqual(K.edge_reach(float("nan")), K.EDGE_REACH_MM)

    def test_a_miss_says_why(self):
        self.ov.env["body_at"] = lambda d, p: None
        self.ov.click(390, 300)
        self.assertIn("is not a Reverse engineer body", self.warned[-1])

    def test_a_retina_view_converts_both_axes(self):
        # FreeCAD 1.1.3 on a Retina Mac: a 496 x 825 logical view, Coin's
        # viewport 992 x 1650 device pixels. The press and release both
        # swallowed, the click at logical (194, 396.9) must reach Coin's
        # (388, 856.2), not (194, 1253).
        class Retina(BodyView):
            def __init__(self):
                super().__init__()
                self.asked = []

            def getSize(self):  # noqa: N802
                return (992, 1650)

            def getObjectInfo(self, pos):  # noqa: N802
                self.asked.append(pos)
                return super().getObjectInfo(pos)

        widget = _Widget()
        widget.devicePixelRatioF = lambda: 2.0
        self.ov.detach()
        self.view = Retina()
        self.view.widget = widget
        self.ov = V.Overlay(self.ed, self.view, self.coin, None, _Vec, self.ov.env)
        self.ov.qt_pressed(194.0, 396.9)
        self.ov.qt_released(194.0, 396.9)
        self.run_later()
        self.assertEqual(self.view.asked, [(388, 856)])  # whole pixels, as getObjectInfo takes them

    def picked(self):
        return [n for n in walk(self.ov.pick_sep) if getattr(n, "name", None) == "PickedEdge"]

    def test_picked_edges_drawn_along_their_run_and_let_go(self):
        self.assertEqual(self.picked(), [])
        self.click(403, 300)
        lines = self.picked()
        self.assertEqual(len(lines), 1)
        coords = next(n for n in lines[0].children if type(n).__name__ == "SoCoordinate3")
        self.assertEqual(coords.point.value, [[0, 0, 10], [10, 0, 10]])  # the whole front edge, not a dot
        colours = [n.rgb.value for n in walk(lines[0]) if type(n).__name__ == "SoBaseColor"]
        widths = [n.lineWidth.value for n in walk(lines[0]) if type(n).__name__ == "SoDrawStyle"]
        self.assertEqual(colours, [V.rgb(V.GRIP_OUTLINE), V.rgb(V.PICKED_COLOR)])  # a dark rim, then the pick's colour
        self.assertEqual(widths, [V.PICKED_LINE_PX + 2 * V.PICKED_OUTLINE_PX, V.PICKED_LINE_PX])
        self.assertTrue(any(type(n).__name__ == "SoPickStyle" for n in self.ov.pick_sep.children))  # clicks go through it
        self.assertEqual(type(self.ov.pick_sep).__name__, "SoAnnotation")  # above the body
        self.click(405, 310)
        self.assertEqual(len(self.picked()), 2)
        self.click(403, 300)  # the front one let go
        lines = self.picked()
        self.assertEqual(len(lines), 1)
        coords = next(n for n in lines[0].children if type(n).__name__ == "SoCoordinate3")
        self.assertEqual(coords.point.value, [[0, 10, 10], [10, 10, 10]])
        self.click(405, 310)
        self.assertEqual(self.ov.pick_sep.children, [])
        self.click(403, 300)
        self.ov.draw_picks()  # drawn the same on the tick: nothing built again
        self.assertEqual(len(self.picked()), 1)
        self.ov.detach()  # the box closed: the picks go with it
        self.assertNotIn(self.ov.root, self.view.graph.children)

    def test_a_shell_s_faces_draw_no_edges(self):
        self.ed.open_new("shell", {"features": [], "nextFeatureId": 2}, [{"id": 2, "surface": False, "box": None}])
        self.ov.click(405, 305)
        self.ov.draw_picks()
        self.assertEqual(self.ov.pick_sep.children, [])

    def freecad_selects(self):
        """FreeCAD selecting the edge under the cursor, as it does when the
        navigation hands it the release."""
        self.sel.append(("D", "ScanRulerReverse", "Edge7"))

    def test_the_swallowed_press_puts_the_selection_back(self):
        # 231481b/98355c0: press and release both taken by the navigation.
        # FreeCAD selects on the release; the click runs after it, so the
        # selection to put back must be the one read at the press.
        self.ov.qt_pressed(403, 300)
        self.ov.qt_released(403, 300)
        self.freecad_selects()
        self.run_later()
        self.assertEqual(self.ed.record["edges"], [self.FRONT])
        self.assertEqual(self.sel, [("D", "Other", "Face1")])

    def test_the_scene_graph_s_route_puts_it_back_too(self):
        self.view.send(_Event("btn", 403, 300, press=True))
        self.freecad_selects()  # FreeCAD selects on the press
        self.view.send(_Event("btn", 403, 300, press=False))
        self.run_later()
        self.assertEqual(self.ed.record["edges"], [self.FRONT])
        self.assertEqual(self.sel, [("D", "Other", "Face1")])

    def test_qt_s_press_then_the_scene_graph_s_release(self):
        self.ov.qt_pressed(403, 300)
        self.freecad_selects()
        self.ov.qt_released(403, 300)
        self.view.send(_Event("btn", 403, 300, press=False))
        self.run_later()
        self.assertEqual(self.sel, [("D", "Other", "Face1")])

    def test_a_miss_puts_it_back_as_well(self):
        self.ov.env["body_at"] = lambda d, p: None
        self.ov.qt_pressed(390, 300)
        self.ov.qt_released(390, 300)
        self.freecad_selects()
        self.run_later()
        self.assertEqual(self.ed.record["edges"], [])
        self.assertEqual(self.sel, [("D", "Other", "Face1")])

    def test_create_or_cancel_clears_what_the_box_selected(self):
        self.click(403, 300)
        self.click(398, 300)  # on the container's compound
        self.sel.append(("D", "ReverseBody", "Edge1"))  # left behind somehow
        self.sel.append(("D", "ScanRulerReverse", "Edge1"))
        self.sel.append(("D", "ScanRulerReverse", "Face3"))  # the person's own
        self.ov.detach()  # Create or Cancel: the box closes
        self.assertEqual(self.sel, [("D", "Other", "Face1"), ("D", "ScanRulerReverse", "Face3")])
        self.assertEqual(len(self.unselected), 1)
        self.assertEqual(self.ov.touched, [])

    def test_selected_by(self):
        hits = [{"doc": "D", "object": "ReverseBody", "element": "Edge7", "parent": "ScanRulerReverse"}]
        self.assertTrue(V.selected_by(hits, "D", "ScanRulerReverse", "Edge7"))
        self.assertTrue(V.selected_by(hits, "D", "ReverseBody", "Edge7"))
        self.assertTrue(V.selected_by(hits, "D", "Assembly", "ReverseBody.Edge7"))
        self.assertFalse(V.selected_by(hits, "D", "ScanRulerReverse", "Edge17"))
        self.assertFalse(V.selected_by(hits, "E", "ReverseBody", "Edge7"))
        self.assertFalse(V.selected_by(hits, "D", "Other", "Edge7"))

    def test_nearest_body_and_the_qt_point(self):
        self.assertEqual(V.nearest_body([(1, 0.5), (2, 0.0), (3, None)], 0.01), 2)
        self.assertIsNone(V.nearest_body([(1, 0.5)], 0.01))
        self.assertEqual(V.qt_to_coin(10, 20, 600, 2.0), (20, 560))


if __name__ == "__main__":
    unittest.main()
