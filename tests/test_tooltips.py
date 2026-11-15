# SPDX-License-Identifier: AGPL-3.0-only
# Every ScanRuler command's tooltip says more than its name (FreeCAD's design
# guide; about 30 only repeated it, found by the GUI pass on the Mac).
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scanrulerfc import commands  # noqa: E402


class Tooltips(unittest.TestCase):
    def test_no_tooltip_only_repeats_the_name(self):
        for name, cmd in commands.build().items():
            r = cmd.GetResources()
            tip = (r.get("ToolTip") or "").strip(" .…").lower()
            self.assertTrue(tip, name)
            self.assertNotEqual(tip, (r.get("MenuText") or "").strip(" .…").lower(), name)


if __name__ == "__main__":
    unittest.main()
