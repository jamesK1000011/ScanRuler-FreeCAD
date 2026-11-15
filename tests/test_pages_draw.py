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

    def test_labels_wrap(self):
        mods = fake_pyside()
        with mock.patch.dict(sys.modules, mods):
            page = importlib.import_module("scanrulerfc.pages.measure3d")
            page.widget(page.build(fresh()), on_key=lambda *a: None)
        qw = mods["PySide.QtWidgets"]
        qw.QLabel.return_value.setWordWrap.assert_any_call(True)
        qw.QWidget.return_value.setMinimumWidth.assert_any_call(0)


if __name__ == "__main__":
    unittest.main()
