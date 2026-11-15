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


if __name__ == "__main__":
    unittest.main()
