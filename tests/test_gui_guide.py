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


if __name__ == "__main__":
    unittest.main()
