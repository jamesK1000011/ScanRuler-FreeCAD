# SPDX-License-Identifier: AGPL-3.0-only
# Every page model drawn through the one shared view (pages/kit.widget) with
# a stand-in Qt, so a model the view cannot draw fails here and not in the
# panel (3D Measure's GD&T "slots" are names, not slot rows: the panel did
# not open on the Mac).
import importlib
import os
import sys
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

import synth  # noqa: E402
from scanrulerfc import model as M  # noqa: E402
from scanrulerfc.scanstate import Scan, fresh  # noqa: E402

PAGES = ("measure3d", "deviation", "flat2d", "meshtools", "thickness", "reverse")


def fake_pyside():
    widgets = mock.MagicMock(name="QtWidgets")
    widgets.QApplication.instance.return_value = object()
    pyside = types.ModuleType("PySide")
    pyside.QtWidgets = widgets
    pyside.QtCore = mock.MagicMock(name="QtCore")
    pyside.QtGui = mock.MagicMock(name="QtGui")
    return {"PySide": pyside, "PySide.QtWidgets": widgets, "PySide.QtCore": pyside.QtCore, "PySide.QtGui": pyside.QtGui}


def states():
    yield fresh()
    V, F = synth.sphere()
    st = fresh()
    st["scan"] = Scan("ball.stl", V, F)
    fit = {"kind": "sphere", "center": [0, 0, 0], "radius": 5.0, "sigma": 0.01, "usedPoints": 100, "regionSize": 100}
    src = {"type": "fitted", "settings": {"sigma": 3}, "seeds": [0]}
    a = M._add(st, "sphere", fit, src)
    b = M._add(st, "sphere", {**fit, "center": [10, 0, 0], "radius": 4.0}, src)
    M.dimension_add(st, {"refs": [a["id"], b["id"]]})
    yield st


class EveryPageDraws(unittest.TestCase):
    def test_every_page_and_state(self):
        with mock.patch.dict(sys.modules, fake_pyside()):
            for name in PAGES:
                page = importlib.import_module("scanrulerfc.pages." + name)
                for st in states():
                    with self.subTest(page=name, scan=st.get("scan") is not None):
                        page.widget(page.build(st), on_key=lambda *a: None)


class FitsTheWidth(unittest.TestCase):
    """The page follows its panel's width: key grids drop to two columns and
    labels stack above their buttons under 320 px; labels wrap."""

    def test_columns_and_stacking(self):
        from scanrulerfc.pages import kit

        self.assertEqual(kit.columns_for(360, 3), 3)
        self.assertEqual(kit.columns_for(280, 3), 2)
        self.assertEqual(kit.columns_for(280, 1), 1)
        self.assertEqual(kit.columns_for(0, 3), 3)  # not laid out yet
        # Whole keys only: four 90 px keys don't fit a 354 px panel, three do.
        self.assertEqual(kit.columns_for(354, 4, 90), 3)
        self.assertEqual(kit.columns_for(600, 4, 90), 4)
        self.assertEqual(kit.columns_for(354, 4, 400), 1)
        self.assertTrue(kit.stacked(280))
        self.assertFalse(kit.stacked(340))

    def test_reflow(self):
        from scanrulerfc.pages import kit

        class Grid:
            def __init__(self):
                self.at = {}

            def removeWidget(self, b):  # noqa: N802
                self.at.pop(b, None)

            def addWidget(self, b, r, c):  # noqa: N802
                self.at[b] = (r, c)

        class Row:
            d = "across"

            def direction(self):
                return self.d

            def setDirection(self, d):  # noqa: N802
                self.d = d

        g, row = Grid(), Row()
        keys = ["Plane", "Cylinder", "Sphere", "Cone", "Section", "Point"]
        grids = [[g, keys, 3, 3]]
        self.assertEqual(kit.reflow(280, grids, [row], "down", "across"), (1, 1))
        self.assertEqual(g.at["Cone"], (1, 1))
        self.assertEqual(row.d, "down")
        self.assertEqual(kit.reflow(280, grids, [row], "down", "across"), (0, 0))
        kit.reflow(360, grids, [row], "down", "across")
        self.assertEqual(g.at["Cone"], (1, 0))
        self.assertEqual(row.d, "across")

    def test_field_label_above_its_list_in_a_narrow_dock(self):
        """A field's label goes above its list under FIELD_NARROW, so the list
        gets the whole row ("Center to ce…" was cut at 330 px)."""
        from scanrulerfc.pages import kit

        class Row:
            d = "across"

            def direction(self):
                return self.d

            def setDirection(self, d):  # noqa: N802
                self.d = d

        slot, field = Row(), Row()
        kit.reflow(330, [], [slot], "down", "across", [field])
        self.assertEqual((slot.d, field.d), ("across", "down"))
        kit.reflow(450, [], [slot], "down", "across", [field])
        self.assertEqual(field.d, "across")

    def test_dense_and_info_on_the_title_row(self):
        from scanrulerfc.pages import kit

        self.assertLessEqual(kit.SPACING, 6)
        self.assertLessEqual(kit.MARGIN, 6)
        self.assertTrue(all(m <= 6 for m in kit.GROUP_MARGINS))
        # The (i) key and the count sit on the group's title row.
        self.assertEqual(kit.head_row({"header": "FIT SETTINGS", "info": "Fit", "count": None}), ["title", "stretch", "info"])
        self.assertEqual(kit.head_row({"header": "ELEMENTS", "info": "x", "count": 3}), ["title", "stretch", "count", "info"])
        self.assertEqual(kit.head_row({"header": "VIEW"}), ["title"])
        self.assertEqual(kit.head_row({"info": "x"}), ["stretch", "info"])
        self.assertEqual(kit.head_row({}), [])

    def test_page_follows_the_theme(self):
        """The sheet carries concrete colours worked out from the palette
        (never palette(...), which Qt resolves against the app's palette:
        the panel stayed near-black in FreeCAD Light on the Mac); the only
        fixed colour is CNC Kitchen blue, on primary keys and links."""
        from scanrulerfc import workspaces as W
        from scanrulerfc.pages import kit

        q = kit.page_qss({"window": "#efefef", "window_text": "#000000", "button": "#f5f5f5", "button_text": "#000000",
                          "highlight": "#3d7fd6"})
        self.assertNotIn("palette(", q)
        for line in q.splitlines():
            if W.ACCENT in line:
                self.assertIn("primary", line)
        self.assertIn('QPushButton[primary="true"]:disabled', q)

    def test_labels_wrap(self):
        mods = fake_pyside()
        with mock.patch.dict(sys.modules, mods):
            page = importlib.import_module("scanrulerfc.pages.measure3d")
            page.widget(page.build(fresh()), on_key=lambda *a: None)
        qw = mods["PySide.QtWidgets"]
        qw.QLabel.return_value.setWordWrap.assert_any_call(True)
        qw.QWidget.return_value.setMinimumWidth.assert_any_call(0)


def recording_pyside():
    """fake_pyside, with a fresh mock for every QLabel, QComboBox,
    QPushButton and QScrollArea made, kept by class name."""
    mods = fake_pyside()
    qw = mods["PySide.QtWidgets"]
    made = {}

    def maker(cls):
        def make(*a, **k):
            w = mock.MagicMock(name=cls)
            w.text_ = a[0] if a and isinstance(a[0], str) else ""
            made.setdefault(cls, []).append(w)
            return w
        return make

    for cls in ("QLabel", "QComboBox", "QPushButton", "QScrollArea", "QStackedWidget", "QCheckBox"):
        getattr(qw, cls).side_effect = maker(cls)
    qw.QSizePolicy.Ignored = "Ignored"
    qw.QComboBox.AdjustToMinimumContentsLengthWithIcon = "AdjustToMinimumContentsLengthWithIcon"
    return mods, made


PANEL = 354  # the dock's width beside the tree on the Mac (GUI pass)
CHAR_PX, KEY_PAD = 7, 24  # an average character of the panel's font; a key's frame and padding


class FitsThePanelWithAScan(unittest.TestCase):
    """Live check: with a scan open the dock came up about 640 px wide,
    the 3D view a strip. Nothing in any workspace may ask for more than the
    panel's 354 px: lists shrink to eight letters, labels wrap, no row of
    keys is wider than the panel, and the dock's own parts ask for no width
    of their own (dock.follow_width)."""

    def test_every_workspace_fits(self):
        from scanrulerfc.pages import kit

        st = list(states())[1]
        room = PANEL - 2 * kit.MARGIN - sum(kit.GROUP_MARGINS[::2]) - 2 * kit.MARGIN
        for name in PAGES:
            mods, made = recording_pyside()
            with mock.patch.dict(sys.modules, mods):
                page = importlib.import_module("scanrulerfc.pages." + name)
                page.widget(page.build(st), on_key=lambda *a: None)
            with self.subTest(page=name):
                for c in made.get("QComboBox", []):
                    c.setSizeAdjustPolicy.assert_called_with("AdjustToMinimumContentsLengthWithIcon")
                    n = c.setMinimumContentsLength.call_args[0][0]
                    self.assertLessEqual(n, 8)
                for lab in made.get("QLabel", []):
                    lab.setWordWrap.assert_called_with(True)
                for b in made.get("QPushButton", []):
                    self.assertLessEqual(len(b.text_) * CHAR_PX + KEY_PAD, room, b.text_)
                for cb in made.get("QCheckBox", []):
                    self.assertLessEqual(len(cb.text_) * CHAR_PX + KEY_PAD, room, cb.text_)

    def test_toggle_rows_fit(self):
        from scanrulerfc.pages import kit

        st = list(states())[1]
        room = PANEL - 4 * kit.MARGIN - sum(kit.GROUP_MARGINS[::2])

        def walk(secs):
            for s in secs:
                yield s
                yield from walk(s.get("children", []))

        for name in PAGES:
            page = importlib.import_module("scanrulerfc.pages." + name)
            for s in walk(page.build(st)["sections"]):
                for fd in s.get("fields", []):
                    if fd.get("kind") == "toggle":
                        w = sum(len(kit.button_text(o["label"])) * CHAR_PX + KEY_PAD for o in fd["options"])
                        with self.subTest(page=name, field=fd["id"]):
                            self.assertLessEqual(w, room)

    def test_the_docks_parts_ask_for_no_width(self):
        from scanrulerfc import dock

        mods, made = recording_pyside()
        with mock.patch.dict(sys.modules, mods):
            d = dock.Dock.__new__(dock.Dock)
            real = dock.Dock.refresh
            dock.Dock.refresh = lambda self, force=False: None
            try:
                dock.Dock.__init__(d, session_fn=lambda: (None, None))
            finally:
                dock.Dock.refresh = real
                dock._dock.pop("live", None)
                from scanrulerfc import commands as C

                C.set_ui(None)
        parts = made["QLabel"] + made["QScrollArea"] + made["QStackedWidget"]
        self.assertEqual(len(made["QScrollArea"]), len(dock.ORDER))
        for w in parts:
            self.assertEqual(w.setSizePolicy.call_args[0][0], "Ignored", w)
        for lab in made["QLabel"]:
            lab.setWordWrap.assert_called_with(True)


if __name__ == "__main__":
    unittest.main()
