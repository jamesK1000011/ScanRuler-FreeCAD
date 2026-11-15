# SPDX-License-Identifier: AGPL-3.0-only
# The workbench's commands and icons, and InitGui under stub FreeCAD modules:
# every key in the tables is a command with an icon drawn from ScanRuler's
# own pictures (ScanRuler by Stefan Hermann, CNC Kitchen), the hooks carry
# the runs, and none of the new modules reaches for Agent Link.
import ast
import os
import subprocess
import sys
import types
import unittest
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [ROOT, HERE]

import tsxsource as T  # noqa: E402
from scanrulerfc import commands as C  # noqa: E402
from scanrulerfc import workspaces as W  # noqa: E402

NEW = ["InitGui.py", "scanrulerfc/workspaces.py", "scanrulerfc/commands.py", "scanrulerfc/workbench.py",
       "scanrulerfc/pages/__init__.py", "scanrulerfc/pages/measure3d.py", "scanrulerfc/pages/infotext.py",
       "scanrulerfc/pages/fonts.py", "tools/gen_icons.py", "tools/gen_infotext.py", "tools/icon_lint.py"]


class StubGui(types.ModuleType):
    def __init__(self):
        super().__init__("FreeCADGui")
        self.commands, self.workbenches = {}, []

        class Workbench:
            def __init__(self):
                self.toolbars, self.menus = [], []

            def appendToolbar(self, name, cmds):
                self.toolbars.append((name, list(cmds)))

            def appendMenu(self, path, cmds):
                self.menus.append((path, list(cmds)))

        self.Workbench = Workbench

    def addCommand(self, name, cmd):
        self.commands[name] = cmd

    def addWorkbench(self, wb):
        self.workbenches.append(wb)

    def getMainWindow(self):
        raise ImportError("no window here")


def stubbed(test):
    def run(self):
        gui, app = StubGui(), types.ModuleType("FreeCAD")
        app.Console = types.SimpleNamespace(PrintMessage=lambda m: None)
        saved = {k: sys.modules.get(k) for k in ("FreeCADGui", "FreeCAD", "PySide")}
        sys.modules.update({"FreeCADGui": gui, "FreeCAD": app, "PySide": None})
        C._registered.clear()
        try:
            return test(self, gui)
        finally:
            for k, v in saved.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v
            C._registered.clear()
            C.set_runner(None)
            C.set_ui(None)
            C._state["workspace"] = W.DEFAULT_WORKSPACE
    return run


class Commands(unittest.TestCase):
    def test_every_table_command_exists(self):
        built = C.build()
        for name in W.all_commands():
            self.assertIn(name, built)
        from scanrulerfc import workbench as WB

        for _n, _t, cmds in WB.toolbars():
            for c in cmds:
                self.assertTrue(c in built or c.startswith("Std_"), c)
        for _p, cmds in WB.menus():
            for c in cmds:
                self.assertTrue(c in built or c == "Separator", c)

    def test_every_icon_resolves(self):
        for name, cmd in C.build().items():
            res = cmd.GetResources()
            with self.subTest(name):
                self.assertTrue(os.path.isfile(res["Pixmap"]), res["Pixmap"])
                self.assertTrue(res["MenuText"] and res["ToolTip"])
        self.assertTrue(os.path.isfile(C.icon_path("ScanRulerWorkbench")))

    def test_icons_are_clean_svgs(self):
        out = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "icon_lint.py"), C.ICONS], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stdout[-500:])
        for f in os.listdir(C.ICONS):
            s = open(os.path.join(C.ICONS, f), encoding="utf-8").read()
            ET.fromstring(s.split("?>", 1)[1])
            self.assertIn("Stefan Hermann (CNC Kitchen)", s)
            self.assertNotIn("brand", s)
        self.assertEqual(sorted(f[:-4] for f in os.listdir(C.ICONS)), sorted(W.icon_names() + ["ScanRulerWorkbench"]))

    @unittest.skipUnless(T.available(), "ScanRuler's source is not here")
    def test_icons_drawn_from_the_originals_tables(self):
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import gen_icons

        for n in W.icon_names():
            with self.subTest(n):
                rel, _jsx = gen_icons.body_of(n)
                self.assertFalse(rel.startswith("docs/"))
                with open(os.path.join(C.ICONS, n + ".svg"), encoding="utf-8") as f:
                    self.assertEqual(f.read(), gen_icons.svg(n), "regenerate: python3 tools/gen_icons.py")

    @stubbed
    def test_run_keys_go_to_the_runner(self, gui):
        calls = []
        C.set_runner(lambda tool, args: calls.append((tool, args)) or "ok")
        self.assertTrue(C.has_runner())
        self.assertEqual(C.build()["ScanRuler_AutoAlign"].Activated(), "ok")
        C.build()["ScanRuler_MeshFillHoles"].Activated()  # a tool's box: to the panel, not the runner
        C.build()["ScanRuler_FindVolumeErrors"].Activated()
        self.assertEqual(calls, [("align_auto", {}), ("deviation_volume", {})])
        self.assertEqual(C.current_workspace(), "deviation")

    @stubbed
    def test_ui_keys_and_workspaces_go_to_the_panel(self, gui):
        seen = []
        C.set_ui(lambda key, *a: seen.append((key,) + a))
        C.build()["ScanRuler_ElementSphere"].Activated()
        C.build()["ScanRuler_WsMeshTools"].Activated()
        C.build()["ScanRuler_ViewScanMesh"].Activated(True)
        self.assertEqual(seen, [("ElementSphere", {"kind": "sphere"}), ("workspace", "mesh"), ("view", "ViewScanMesh", True)])
        self.assertTrue(C.build()["ScanRuler_WsMeshTools"].GetResources()["Checkable"])
        self.assertFalse(C.build()["ScanRuler_Ws3DMeasure"].GetResources()["Checkable"])
        self.assertTrue(C.build()["ScanRuler_ViewCopyDeviation"].IsActive())
        self.assertFalse(C.build()["ScanRuler_ViewSplit"].IsActive())

    def test_reverse_keys_wait_for_their_engine(self):
        # Kinds this port builds stand for reverse_feature_add; the rest wait.
        self.assertTrue(C.build()["ScanRuler_ReExtrude"].IsActive())
        self.assertFalse(C.build()["ScanRuler_ReLoft"].IsActive())
        self.assertFalse(C.build()["ScanRuler_ReImport"].IsActive())
        self.assertTrue(C.build()["ScanRuler_WsReverse"].IsActive())

    def test_load_takes_fcstd_and_scanruler(self):
        seen = []
        C.set_ui(lambda key, *a: seen.append((key,) + a))
        try:
            # Not there: refused in words, the panel not told (a real one:
            # test_wiring.ProjectImport).
            self.assertIsNone(C.load("/tmp/no-such-old.scanruler"))
            with self.assertRaises(ValueError):
                C.load("/tmp/x.stl")
        finally:
            C.set_ui(None)
        self.assertEqual(seen, [])

    def test_placeholder_runner_says_so(self):
        C.set_runner(None)
        self.assertFalse(C.has_runner())
        self.assertIsNone(C.runner()("align_auto", {}))


class InitGui(unittest.TestCase):
    @stubbed
    def test_initgui_adds_the_workbench(self, gui):
        with open(os.path.join(ROOT, "InitGui.py"), encoding="utf-8") as f:
            exec(compile(f.read(), "InitGui.py", "exec"), {"__name__": "InitGui"})
        self.assertEqual(len(gui.workbenches), 1)
        wb = gui.workbenches[0]
        self.assertEqual(type(wb).__name__, "ScanRulerWorkbench")
        self.assertEqual(wb.MenuText, "ScanRuler")
        self.assertEqual(wb.ToolTip, "ScanRuler by Stefan Hermann (CNC Kitchen), ported to FreeCAD")
        wb.Initialize()
        names = [n for n, _ in wb.toolbars]
        self.assertEqual(names[:2], ["ScanRuler workspaces", "ScanRuler project"])
        self.assertEqual(names[-1], "ScanRuler view")
        for ws, bars in W.TOOLBARS.items():
            for title, _ in bars:
                self.assertIn(W.toolbar_name(ws, title), names)
        self.assertEqual(dict(wb.toolbars)["ScanRuler project"], ["Std_Undo", "Std_Redo", "ScanRuler_New", "ScanRuler_Save", "ScanRuler_Load"])
        self.assertEqual(dict(wb.toolbars)["ScanRuler workspaces"], [w["command"] for w in W.WORKSPACES])
        self.assertEqual(wb.menus[0][0], ["ScanRuler", "Workspace"])
        self.assertEqual(wb.menus[-1][1][-3:], ["ScanRuler_Snapshot", "ScanRuler_Settings", "ScanRuler_About"])
        self.assertTrue(set(W.all_commands()) <= set(gui.commands))
        wb.Activated()  # no window: switches the workspace headless
        self.assertEqual(C.current_workspace(), "elements")


class NoAgentLink(unittest.TestCase):
    def test_no_agentlink_import(self):
        for rel in NEW:
            tree = ast.parse(open(os.path.join(ROOT, rel), encoding="utf-8").read())
            for node in ast.walk(tree):
                names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
                for n in names:
                    with self.subTest(rel):
                        self.assertFalse(n.split(".")[0] in ("agentlink", "agentlink_families") or "agentlink_families" in n, n)

    def test_imports_with_agentlink_blocked(self):
        code = ("import sys; sys.modules['agentlink'] = None; sys.path.insert(0, %r)\n"
                "import scanrulerfc.workspaces, scanrulerfc.commands, scanrulerfc.workbench\n"
                "import scanrulerfc.pages.measure3d, scanrulerfc.pages.fonts\n"
                "from scanrulerfc import scanstate\n"
                "scanrulerfc.pages.measure3d.build(scanstate.fresh())\n") % ROOT
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr[-800:])


if __name__ == "__main__":
    unittest.main()
