# SPDX-License-Identifier: AGPL-3.0-only
# Window pass 7 (round 10) of ScanRuler's panel in FreeCAD (ScanRuler by
# Stefan Hermann, CNC Kitchen): the credit line, the panel's last row, sat
# level with FreeCAD's document tab bar at the window's foot and read as laid
# over its first tab (r9sr-1). It is now its own row under the panel's
# header, whole, inside the dock. No Qt here: the dock's source read, and the
# label's set-up run on a stand-in label.
import ast
import os
import sys
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

from scanrulerfc import dock  # noqa: E402
from scanrulerfc import workspaces as W  # noqa: E402

SRC = os.path.join(HERE, "..", "scanrulerfc", "dock.py")


def _init_calls():
    """The Dock's __init__ as (call text) lines, in order."""
    tree = ast.parse(open(SRC, encoding="utf-8").read())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Dock")
    init = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "__init__")
    return [ast.unparse(n) for n in ast.walk(init) if isinstance(n, ast.Call)]


class CreditRow(unittest.TestCase):
    def test_the_credit_is_added_right_under_the_header(self):
        calls = [c for c in _init_calls() if c.startswith("lay.addWidget(")]
        self.assertEqual(calls[:3], ["lay.addWidget(self.head)", "lay.addWidget(self.credit)", "lay.addWidget(self.stack, 1)"])
        self.assertEqual(calls.index("lay.addWidget(self.credit)"), dock.CREDIT_ROW)

    def test_the_credit_is_not_the_last_row_and_is_drawn_once(self):
        calls = [c for c in _init_calls() if c.startswith("lay.addWidget(")]
        self.assertNotEqual(calls[-1], "lay.addWidget(self.credit)")
        text = open(SRC, encoding="utf-8").read()
        self.assertEqual(text.count("QLabel(W.CREDIT)"), 1)
        self.assertNotIn("foot = QtWidgets.QLabel", text)

    def test_the_credit_names_stefan_hermann_and_cnc_kitchen(self):
        self.assertIn("Stefan Hermann (CNC Kitchen)", W.CREDIT)


class _Policy:
    def __init__(self, h="Preferred", v="Preferred"):
        self.h, self.v = h, v

    def horizontalPolicy(self):  # noqa: N802 (Qt)
        return self.h

    def verticalPolicy(self):  # noqa: N802 (Qt)
        return self.v


class _Label:
    """A QLabel stand-in: what credit_label sets."""

    def __init__(self):
        self.name = self.style = None
        self.wrap = False
        self.policy = _Policy()

    def setObjectName(self, n):  # noqa: N802 (Qt)
        self.name = n

    def setWordWrap(self, w):  # noqa: N802 (Qt)
        self.wrap = w

    def setStyleSheet(self, s):  # noqa: N802 (Qt)
        self.style = s

    def sizePolicy(self):  # noqa: N802 (Qt)
        return self.policy

    def setSizePolicy(self, h, v):  # noqa: N802 (Qt)
        self.policy = _Policy(h, v)


class CreditLabel(unittest.TestCase):
    def setUp(self):
        # PySide stand-in: the size policies by name.
        pol = types.SimpleNamespace(Ignored="Ignored", Minimum="Minimum", Preferred="Preferred")
        widgets = types.SimpleNamespace(QSizePolicy=pol)
        self._old = sys.modules.get("PySide")
        sys.modules["PySide"] = types.SimpleNamespace(QtWidgets=widgets)

    def tearDown(self):
        if self._old is None:
            sys.modules.pop("PySide", None)
        else:
            sys.modules["PySide"] = self._old

    def test_wrapped_whole_and_with_no_box_of_its_own(self):
        lab = dock.credit_label(_Label())
        self.assertEqual(lab.name, "ScanRulerCredit")
        self.assertTrue(lab.wrap)
        self.assertIn("transparent", lab.style)
        # follows the panel's width, never shorter than its wrapped text
        self.assertEqual((lab.policy.h, lab.policy.v), ("Ignored", "Minimum"))


if __name__ == "__main__":
    unittest.main()
