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

    def redirectToSceneGraph(self, on):  # noqa: N802
        self.redirected = on

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
        cones = [n for n in walk(self.ov.grip_sep) if type(n).__name__ == "SoCone"]
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


if __name__ == "__main__":
    unittest.main()
