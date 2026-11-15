# SPDX-License-Identifier: AGPL-3.0-only
# The header font's letter spacing on PySide2 and PySide6: PySide6 has no
# enum value on a QFont instance (f.AbsoluteSpacing), which raised in the
# ScanRuler workbench on FreeCAD 1.1.3 and kept its workspace from building.
import os
import re
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scanrulerfc.pages import fonts  # noqa: E402

PAGES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scanrulerfc", "pages")


class FontEnums(unittest.TestCase):
    def test_pyside6_nested_enum(self):
        spacing = types.SimpleNamespace(AbsoluteSpacing="abs6")
        qtgui = types.SimpleNamespace(QFont=types.SimpleNamespace(SpacingType=spacing))
        self.assertEqual(fonts.absolute_spacing(qtgui), "abs6")

    def test_pyside2_flat_enum(self):
        qtgui = types.SimpleNamespace(QFont=types.SimpleNamespace(AbsoluteSpacing="abs2"))
        self.assertEqual(fonts.absolute_spacing(qtgui), "abs2")

    def test_no_enum_read_off_an_instance(self):
        for name in os.listdir(PAGES):
            if name.endswith(".py"):
                text = open(os.path.join(PAGES, name), encoding="utf-8").read()
                self.assertIsNone(re.search(r"\bf\.(Absolute|Percentage)Spacing\b", text), name)


if __name__ == "__main__":
    unittest.main()
