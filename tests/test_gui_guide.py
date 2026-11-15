# SPDX-License-Identifier: AGPL-3.0-only
# The workbench as FreeCAD's design guide asks, and the keys never silent
# (found by the GUI pass on FreeCAD 1.1.3, macOS): Title Case names, every
# tooltip its own full sentence, an About box and a settings dialog of
# ScanRuler's own, the workspace's toolbars kept through FreeCAD's restore,
# and a key that cannot run saying why. ScanRuler by Stefan Hermann (CNC
# Kitchen), ported to FreeCAD. No Qt here.
import os
import re
import sys
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.dirname(HERE), HERE]

from scanrulerfc import commands as C  # noqa: E402
from scanrulerfc import settings as ST  # noqa: E402
from scanrulerfc import workbench as WB  # noqa: E402
from scanrulerfc import workspaces as W  # noqa: E402
from test_gui_commands import stubbed  # noqa: E402


def resources():
    return {n: c.GetResources() for n, c in C.build().items()}


class TitleCase(unittest.TestCase):
    def test_the_rule(self):
        for got, want in (("Align automatically", "Align Automatically"), ("New dimension", "New Dimension"),
                          ("Reverse engineer", "Reverse Engineer"), ("Align by picking points…", "Align by Picking Points…"),
                          ("Auto-align", "Auto-Align"), ("Shrink/expand", "Shrink/Expand"), ("Trim to scan", "Trim to Scan"),
                          ("Move / rotate by numbers", "Move / Rotate by Numbers"), ("Import STEP", "Import STEP"),
                          ("About ScanRuler", "About ScanRuler"), ("2D Measure", "2D Measure"), ("Cut by plane", "Cut by Plane"),
                          ("Mark surface to fit on…", "Mark Surface to Fit On…")):
            self.assertEqual(W.title_case(got), want)

    def test_every_menu_text_is_title_case(self):
        for name, r in resources().items():
            with self.subTest(name):
                self.assertEqual(r["MenuText"], W.title_case(r["MenuText"]))

    def test_group_titles_are_title_case(self):
        for name, title, _cmds in WB.toolbars():
            self.assertEqual(name, W.title_case(name))
            self.assertEqual(title, W.title_case(title))
        for path, _cmds in WB.menus():
            for p in path:
                self.assertEqual(p, W.title_case(p))

    def test_named_findings(self):
        r = resources()
        self.assertEqual(r["ScanRuler_AlignAutomatically"]["MenuText"], "Align Automatically")
        self.assertEqual(r["ScanRuler_NewDimension"]["MenuText"], "New Dimension")
        self.assertEqual(r["ScanRuler_WsReverse"]["MenuText"], "Reverse Engineer")


class Tooltips(unittest.TestCase):
    def test_full_sentences(self):
        for name, r in resources().items():
            tip = r["ToolTip"]
            with self.subTest(name):
                self.assertTrue(tip[0].isupper() or tip[0].isdigit(), tip)
                self.assertTrue(tip.endswith("."), tip)
                self.assertIsNone(re.search(r"\ba [aeiou]", tip), tip)

    def test_no_two_share_a_tooltip(self):
        seen = {}
        for name, r in resources().items():
            with self.subTest(name):
                self.assertNotIn(r["ToolTip"], seen, f"{name} and {seen.get(r['ToolTip'])}")
            seen[r["ToolTip"]] = name
        r = resources()
        self.assertNotEqual(r["ScanRuler_ViewBodies"]["ToolTip"], r["ScanRuler_ViewBodiesGroup"]["ToolTip"])
        self.assertEqual(r["ScanRuler_FlatArc"]["ToolTip"], "Fit an arc to the edges you pick on the flat scan.")

    def test_project_items_say_they_act_on_the_project(self):
        r = resources()
        for name in ("ScanRuler_New", "ScanRuler_Save", "ScanRuler_Load"):
            self.assertIn("ScanRuler project", r[name]["ToolTip"])
        self.assertEqual([r[n]["MenuText"] for n in ("ScanRuler_New", "ScanRuler_Save", "ScanRuler_Load")],
                         ["New Project", "Save Project", "Open Project…"])


class AboutAndSettings(unittest.TestCase):
    def test_about_names_version_licence_and_credit(self):
        import scanrulerfc

        text = C.about_text()
        for want in (scanrulerfc.VERSION, "AGPL-3.0-only", "Stefan Hermann (CNC Kitchen)", "github.com/CNCKitchen/ScanRuler"):
            self.assertIn(want, text)

    def test_settings_open_scanrulers_own_dialog(self):
        # Not FreeCAD's Preferences: showPreferences("ScanRuler") opened its
        # General page, no page of that group being registered.
        seen = []
        real = ST.show
        ST.show = lambda parent=None: seen.append(parent) or True
        try:
            self.assertTrue(C.SettingsCommand().Activated())
        finally:
            ST.show = real
        self.assertEqual(len(seen), 1)

    def test_settings_read_and_write_freecads_parameters(self):
        store = {}

        class P:
            def __init__(self, path):
                self.path = path

            def GetBool(self, name, default):
                return store.get((self.path, name), default)

            def SetBool(self, name, v):
                store[(self.path, name)] = v

        self.assertEqual(ST.read(P), {("Snapshot", "SaveBesideProject"): True})
        ST.write({("Snapshot", "SaveBesideProject"): False}, P)
        self.assertEqual(store, {(ST.PARAM_ROOT + "/Snapshot", "SaveBesideProject"): False})
        self.assertEqual(ST.read(P), {("Snapshot", "SaveBesideProject"): False})


class NeverSilent(unittest.TestCase):
    def setUp(self):
        self.told = []
        self._tell, C._tell = C._tell, self.told.append
        self._open = C.scan_is_open

    def tearDown(self):
        C._tell = self._tell
        C.scan_is_open = self._open

    @stubbed
    def test_a_refusal_is_said_as_a_person_reads_it(self, gui):
        C.scan_is_open = lambda: None
        C.set_runner(lambda tool, args: (False, {"error": {"code": "invalid_state", "message": "No scan open: scan_open { path } opens one."}}))
        C.build()["ScanRuler_AutoAlign"].Activated()
        self.assertEqual(self.told, ["ScanRuler: " + C.NEED_SCAN])
        C.set_runner(lambda tool, args: (True, {}))
        C.build()["ScanRuler_AutoAlign"].Activated()
        self.assertEqual(self.told[-1], "ScanRuler: Auto-Align done.")
        C.set_runner(lambda tool, args: (False, {"error": {"code": "invalid_input", "message": "Pick a plane first."}}))
        C.build()["ScanRuler_AlignAutomatically"].Activated()
        self.assertEqual(self.told[-1], "ScanRuler: Pick a plane first.")

    @stubbed
    def test_no_scan_says_so_before_the_key(self, gui):
        C.scan_is_open = lambda: False
        runs, seen = [], []
        C.set_runner(lambda tool, args: runs.append(tool) or (True, {}))
        C.set_ui(lambda key, *a: seen.append(key) or True)
        C.build()["ScanRuler_AutoAlign"].Activated()
        C.build()["ScanRuler_MeshFillHoles"].Activated()
        C.build()["ScanRuler_FlatPoint"].Activated()  # 2D Measure reads an image: its page says
        self.assertEqual(runs, [])
        self.assertEqual(self.told, [C.NEED_SCAN, C.NEED_SCAN])
        self.assertIn("mesh:fill", seen)  # the page still opens, to open a scan from
        self.assertIn("FlatPoint", seen)

    @stubbed
    def test_no_panel_says_so(self, gui):
        C.set_ui(None)
        self.assertIsNone(C.build()["ScanRuler_ElementSphere"].Activated())
        self.assertTrue(self.told and "panel" in self.told[-1])


class ToolbarsStaySwitched(unittest.TestCase):
    @stubbed
    def test_the_switch_is_written_where_freecad_restores_from(self, gui):
        prefs = {}
        app = sys.modules["FreeCAD"]
        app.ParamGet = lambda path: types.SimpleNamespace(SetBool=lambda n, v: prefs.__setitem__((path, n), v))
        C.switch_workspace("mesh")
        on = {n for (path, n), v in prefs.items() if v and path == C.TOOLBAR_PREFS}
        self.assertEqual(on, set(C.toolbar_names("mesh")))
        self.assertEqual(len(prefs), sum(len(b) for b in W.TOOLBARS.values()))


class ToolbarsSwapLive(unittest.TestCase):
    """GUI pass, round 4: the toolbar row was the same in all six
    workspaces; the switch is now applied to the QToolBars themselves, after
    FreeCAD's restore too, by these decisions."""

    def present(self):
        return [(n, n) for n, _t, _c in WB.toolbars()]

    def test_each_workspace_shows_only_its_own(self):
        for w in W.WORKSPACES:
            plan = C.toolbar_plan(w["id"], self.present())
            self.assertEqual({n for n, v in plan.items() if v}, set(C.toolbar_names(w["id"])))
            self.assertEqual(len(plan), sum(len(b) for b in W.TOOLBARS.values()))
        rows = {w["id"]: frozenset(n for n, v in C.toolbar_plan(w["id"], self.present()).items() if v) for w in W.WORKSPACES}
        self.assertEqual(len(set(rows.values())), len(W.WORKSPACES))  # six different rows

    def test_other_toolbars_left_alone(self):
        plan = C.toolbar_plan("mesh", self.present())
        self.assertNotIn(W.WORKSPACE_TOOLBAR, plan)
        self.assertNotIn(W.VIEW_TOOLBAR, plan)
        self.assertEqual(C.toolbar_plan("mesh", [("Std_File", "File")]), {})

    def test_nothing_shown_in_another_workbench(self):
        self.assertEqual(C.toolbar_plan("mesh", self.present(), active=False), {})

    def test_found_by_title_when_named_otherwise(self):
        name = C.toolbar_names("flat")[0]
        self.assertEqual(C.toolbar_plan("flat", [("toolbar_7", name)]), {"toolbar_7": True})

    def test_rehide_only_another_workspaces_toolbar(self):
        mine, other = C.toolbar_names("mesh")[0], C.toolbar_names("elements")[0]
        self.assertTrue(C.rehide(other, other, True, "mesh", True))
        self.assertFalse(C.rehide(mine, mine, True, "mesh", True))
        self.assertFalse(C.rehide(other, other, False, "mesh", True))
        self.assertFalse(C.rehide(other, other, True, "mesh", False))
        self.assertFalse(C.rehide("Std_View", "View", True, "mesh", True))


class SectionToggles(unittest.TestCase):
    """GUI pass, round 4: Section View opened FreeCAD's Clipping dock, could
    not close it, and grew the main window each time."""

    def test_open_then_close(self):
        self.assertEqual(C.section_action([]), "open")
        self.assertEqual(C.section_action([("Combo View", True)]), "open")
        self.assertEqual(C.section_action([(C.CLIP_DOCK, False)]), "open")  # another document's, hidden
        self.assertEqual(C.section_action([("Combo View", True), (C.CLIP_DOCK, True)]), "close")

    def test_window_size_kept(self):
        self.assertEqual(C.size_to_restore((1600, 2082), (1600, 2334), False), (1600, 2082))
        self.assertIsNone(C.size_to_restore((1600, 2082), (1600, 2082), False))
        self.assertIsNone(C.size_to_restore((1600, 2082), (1600, 2334), True))

    def test_the_view_key_is_the_toggle(self):
        g = next(g for g in W.VIEW_BAR if g["key"] == "ViewSection")
        self.assertEqual(g["native"], C.CLIP_COMMAND)


class PanelFollowsTheGuide(unittest.TestCase):
    """GUI pass, round 4: panel buttons and group titles in Title Case, the
    credit once, three dots as one ellipsis. No Qt: the view's helpers."""

    def test_buttons_and_group_titles(self):
        from scanrulerfc.pages import kit as K

        self.assertEqual(K.button_text("Auto-align"), "Auto-Align")
        self.assertEqual(K.button_text("Align part"), "Align Part")
        self.assertEqual(K.button_text("Move / rotate by numbers"), "Move / Rotate by Numbers")
        self.assertEqual(K.group_title(K.section("1", "x", "Create element")), "Create Element")
        self.assertEqual(K.group_title(K.section("1", "x", "In use for analysis")), "In Use for Analysis")

    def test_credit_drawn_once(self):
        import inspect

        from scanrulerfc.pages import kit as K
        from scanrulerfc.pages import measure3d as M3

        for fn in (K.widget, M3.widget):
            self.assertNotIn('model["footer"]', inspect.getsource(fn))
        dock = open(os.path.join(os.path.dirname(HERE), "scanrulerfc", "dock.py"), encoding="utf-8").read()
        self.assertEqual(dock.count("QLabel(W.CREDIT)"), 1)

    def test_no_three_dot_ellipsis(self):
        texts = [r["MenuText"] for r in resources().values()] + [C.NEED_SCAN]
        for name, title, _c in WB.toolbars():
            texts += [name, title]
        for t in texts:
            self.assertNotIn("...", t)


if __name__ == "__main__":
    unittest.main()
