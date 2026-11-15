# SPDX-License-Identifier: AGPL-3.0-only
# The panel layout setting (layout.py, the same in every add-on of the
# suite), without a window: read with its default, and which panels show
# per workbench.
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scanrulerfc import layout  # noqa: E402


class Params:
    def __init__(self, **kw):
        self.v = dict(kw)

    def GetString(self, k, d=""):  # noqa: N802
        return self.v.get(k, d)


class Setting(unittest.TestCase):
    def test_default_and_values(self):
        self.assertEqual(layout.read(Params()), "right")
        self.assertEqual(layout.read(Params(PanelLayout="sideways")), "right")
        for v in ("right", "left-tab", "left-slide"):
            self.assertEqual(layout.read(Params(PanelLayout=v)), v)
        self.assertEqual(layout.PARAMS, "User parameter:BaseApp/Preferences/Mod/AgentLink")

    def test_caps(self):
        self.assertEqual(layout.TREE_MAX, 300)
        self.assertEqual(layout.TASK_MAX, 360)

    def test_only_the_active_workbenchs_panel(self):
        panels = {"own": "ScanRulerWorkbench", "other": "SomeOtherWorkbench", "hub": layout.EVERYWHERE}
        self.assertEqual(layout.shown("ScanRulerWorkbench", panels), ["own", "hub"])
        self.assertEqual(layout.shown("SomeOtherWorkbench", panels), ["other", "hub"])

    def test_alone_its_own_placer(self):
        self.assertIs(layout.placer(), layout.own())


class Tab(unittest.TestCase):
    """Under Agent Link the ScanRuler tab shows only in its workbench; an
    Agent Link without tabs per workbench still gets the tab."""

    def test_register_tab_names_the_workbench(self):
        from scanrulerfc import dock

        class Hooks:
            TABS = []

            def __init__(self, old=False):
                self.got, self.old = [], old

            def register_tab(self, title, factory, order=50, **kw):
                if self.old and kw:
                    raise TypeError("workbench")
                self.got.append((title, order, kw.get("workbench")))

        h = Hooks()
        dock.register_tab(h)
        self.assertEqual(h.got, [("ScanRuler", 70, "ScanRulerWorkbench")])
        h = Hooks(old=True)
        dock.register_tab(h)
        self.assertEqual(h.got, [("ScanRuler", 70, None)])


if __name__ == "__main__":
    unittest.main()
