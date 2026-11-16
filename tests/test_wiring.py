# SPDX-License-Identifier: AGPL-3.0-only
# The workbench wired to its tools: the runner set at registration (alone
# the add-on's handlers, hosted Agent Link's panel._call), arguments checked
# as Agent Link's server checks them, scanstate's version and last_tool for
# the dock, the snapshot tools, the Mesh Tools keys, .scanruler Load, and
# the tool list against the one before the GUI (4bb0eff).
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
import zipfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from meshkit import box_mesh  # noqa: E402

import scanrulerfc  # noqa: E402
from scanrulerfc import commands as C  # noqa: E402
from scanrulerfc import dock as DK  # noqa: E402
from scanrulerfc import handlers, runner  # noqa: E402
from scanrulerfc import scanstate as S  # noqa: E402
from scanrulerfc import workspaces as W  # noqa: E402
from scanrulerfc.pages import meshtools as MP  # noqa: E402

try:
    import agentlink.hooks  # noqa: F401

    HAVE_AL = True
except ImportError:
    HAVE_AL = False

BASE = "4bb0eff"
SNAPSHOT = ("scan_snapshot_list", "scan_snapshot_latest", "scan_snapshot_wait")
MESH_ADDED = ("mesh_densify", "mesh_boolean", "mesh_shell", "mesh_wrap", "mesh_apply_wrap", "mesh_trim")


def _fresh():
    """The modules as sys.modules has them now: other tests reload the
    package under stub FreeCAD modules, so names bound at import go stale."""
    import importlib

    g = globals()
    for name, mod in (("scanrulerfc", "scanrulerfc"), ("C", "scanrulerfc.commands"), ("DK", "scanrulerfc.dock"),
                      ("handlers", "scanrulerfc.handlers"), ("runner", "scanrulerfc.runner"), ("S", "scanrulerfc.scanstate"),
                      ("W", "scanrulerfc.workspaces"), ("MP", "scanrulerfc.pages.meshtools")):
        g[name] = importlib.import_module(mod)


class Fresh(unittest.TestCase):
    def setUp(self):
        _fresh()
        self._was_hosted = scanrulerfc._hosted
        scanrulerfc._hosted = False
        self.addCleanup(setattr, scanrulerfc, "_hosted", self._was_hosted)


def with_scan(ctx):
    V, F = box_mesh(40.0, 30.0, 20.0, n=10)
    S.state(ctx)["scan"] = S.Scan("box.stl", np.asarray(V, float), np.asarray(F, np.int64))
    return ctx


class Runner(Fresh):
    def tearDown(self):
        runner.set_hosted(None)
        C.set_runner(None)

    def test_alone_the_handlers(self):
        run = runner.gui(doc_fn=lambda: None)
        ok, out = run("scan_nearest", {"at": {"point": [0, 0, 0]}})
        self.assertFalse(ok)
        self.assertEqual(out["error"]["code"], "no_scan")

    def test_hosted_the_panels_call(self):
        calls = []
        runner.set_hosted(lambda t, a: calls.append((t, a)) or (True, {"via": "panel"}))
        run = runner.gui(doc_fn=lambda: None)
        self.assertFalse(run("scan_nearest", {"at": {"point": [0, 0, 0]}})[0])  # not hosted yet: still alone
        scanrulerfc._hosted = True
        self.assertEqual(run("scan_info", {"x": 1}), (True, {"via": "panel"}))
        self.assertEqual(calls, [("scan_info", {"x": 1})])

    def test_set_at_registration_and_reexported(self):
        added = {}
        gui = types.SimpleNamespace(addCommand=lambda n, c: added.setdefault(n, c))
        run = runner.gui(doc_fn=lambda: None)
        C.register(gui, run=run)
        self.assertIs(C.runner(), run)
        self.assertIs(scanrulerfc.runner(), run)
        self.assertIs(scanrulerfc.runner.local, runner.local)  # still the module
        scanrulerfc.set_runner(None)
        self.assertFalse(C.has_runner())

    def test_a_key_runs_through_the_runner(self):
        seen = []
        got = DK.press(MP, "wrap", {"mesh": {"wrapGap": 2.0}}, run=lambda t, a: seen.append((t, a)) or (True, {}))
        self.assertEqual(seen, [("mesh_wrap", {"gap": 2.0, "grow": 0.0, "edges": "sharp"})])
        self.assertTrue(got["ok"])
        self.assertIsNone(DK.press(MP, "select-all", {}, run=lambda t, a: self.fail("opens, runs nothing")))

    def test_every_mesh_run_key_names_a_tool(self):
        tools = handlers.all_handlers()
        for key, tool in MP.RUN_KEYS.items():
            self.assertIn(tool, tools)
            self.assertEqual(MP.call_for(key)[0], tool)
        self.assertEqual(MP.call_for("densify"), ("mesh_densify", {}))  # on auto: the tool's own start


class InputChecks(Fresh):
    def setUp(self):
        super().setUp()
        self.run = runner.local(ctx=with_scan(runner.Context(out_dir=tempfile.mkdtemp())))

    def err(self, tool, args):
        ok, out = self.run(tool, args)
        self.assertFalse(ok, out)
        return out["error"]["code"], out["error"]["message"]

    def test_refused_as_agent_link_refuses(self):
        self.assertEqual(self.err("scan_info", {"verbose": True}), ("invalid_input", "input.verbose: not a known field — the fields here: none"))
        self.assertEqual(self.err("element_fit", {"at": {"point": [0, 0, 10]}}), ("invalid_input", "input.kind: required."))
        self.assertEqual(self.err("scan_open", {"units": "furlong"}), ("invalid_input", "input.units: one of mm, cm, m, in — not 'furlong'."))
        self.assertEqual(self.err("scan_snapshot_latest", {"index": 1.5}), ("invalid_input", "input.index: a whole number, not a number."))
        self.assertEqual(self.err("mesh_wrap", {}), ("invalid_input", "input.gap: required."))

    def test_taken_in_another_dress(self):
        ok, out = self.run("element_fit", {"kind": "PLANE", "at": {"point": [0, 0, 10]}})
        self.assertTrue(ok, out)


class Version(Fresh):
    def test_moves_after_a_call_that_went_through(self):
        ctx = with_scan(runner.Context(out_dir=tempfile.mkdtemp()))
        run = runner.local(ctx=ctx)
        st = S.state(ctx)
        v0 = st["version"]
        self.assertTrue(run("element_fit", {"kind": "plane", "at": {"point": [0, 0, 10]}})[0])
        v1, last = DK.poll(st)
        self.assertGreater(v1, v0)
        self.assertEqual(last, "element_fit")
        self.assertEqual(DK.workspace_of(st, "mesh"), "elements")
        self.assertFalse(run("element_fit", {"kind": "plane", "at": {"vertex": 10 ** 9}})[0])
        self.assertEqual(DK.poll(st), (v1, "element_fit"))  # a refusal moves nothing
        self.assertTrue(run("scan_snapshot_list", {})[0])
        self.assertEqual(DK.poll(st), (v1, "element_fit"))  # nor reading the shots
        self.assertTrue(run("thickness_settings", {})[0])
        self.assertEqual(DK.workspace_of(st, "elements"), "thickness")

    def test_never_comes_round_again(self):
        ctx = with_scan(runner.Context(out_dir=tempfile.mkdtemp()))
        S.touched(ctx, "scan_info")
        a = S.state(ctx)["version"]
        S.state(ctx).update(S.fresh())
        S.touched(ctx, "scan_info")
        self.assertGreater(S.state(ctx)["version"], a)

    @unittest.skipUnless(HAVE_AL, "Agent Link is not importable here")
    def test_hosted_family_moves_it_too(self):
        import scanrulerfc.agentlink_families as fl

        sess = types.SimpleNamespace(family_state={}, out_dir=tempfile.mkdtemp(), doc=None)
        with_scan(sess)
        T = {t.name: t for fam in fl.FAMILIES for t in fam.tools(sess)}
        T["deviation_settings"].fn({})
        self.assertEqual(DK.poll(S.state(sess))[1], "deviation_settings")
        self.assertEqual(DK.workspace_of(S.state(sess)), "deviation")


class Snapshot(Fresh):
    def test_listed_and_answered_alone(self):
        from scanrulerfc.snapshot.store import STORE, Shot

        decl = runner.declared()
        for n in SNAPSHOT:
            self.assertEqual(decl[n]["group"], "snapshot")
            self.assertFalse(decl[n]["changes"])  # no tool takes a shot
            self.assertIn(n, handlers.all_handlers())
        run = runner.local(ctx=runner.Context(out_dir=tempfile.mkdtemp()))
        keep = list(STORE.shots)
        del STORE.shots[:]
        try:
            self.assertEqual(run("scan_snapshot_list", {}), (True, {"shots": []}))
            ok, out = run("scan_snapshot_latest", {})
            self.assertEqual((ok, out["error"]["code"]), (False, "not_found"))
            ok, out = run("scan_snapshot_wait", {"timeout": 0})
            self.assertEqual((ok, out["came"]), (True, False))
            STORE.save = False
            STORE.add(Shot(b"\x89PNG fake", 100, 50, "Wall Thickness", note="this edge"))
            ok, out = run("scan_snapshot_latest", {})
            self.assertTrue(ok, out)
            self.assertEqual((out["workspace"], out["note"], out["of"]), ("Wall Thickness", "this edge", 1))
            self.assertNotIn("_png", out)  # the picture rides beside an agent's answer, not in JSON
        finally:
            STORE.shots[:] = keep

    @unittest.skipUnless(HAVE_AL, "Agent Link is not importable here")
    def test_the_notice_is_provided(self):
        from agentlink import hooks

        import scanrulerfc.agentlink_families  # noqa: F401
        from scanrulerfc.snapshot.handlers import notice

        self.assertIs(hooks.service("notice"), notice)


class Echo(Fresh):
    @unittest.skipUnless(HAVE_AL, "Agent Link is not importable here")
    def test_declarations(self):
        from agentlink import echo, hooks

        import scanrulerfc.agentlink_families as fl

        self.assertEqual(fl.WORKBENCHES["deviation_"], "ScanRulerWorkbench")
        self.assertEqual(fl.AREAS, W.AREAS)
        self.assertEqual(fl.COMMANDS["mesh_wrap"], "ScanRuler_MeshWrap")
        self.assertEqual(fl.command_for("element_fit", {"kind": "sphere"}), W.command_for("element_fit", {"kind": "sphere"}))
        self.assertIn(("deviation_", "ScanRulerWorkbench"), echo.WORKBENCH)
        # Through declare(), not Agent Link's own table: the argument-dependent
        # key (element kind) must win over a fixed one.
        self.assertNotIn("mesh_wrap", echo.COMMAND)
        self.assertEqual(echo.command_for("mesh_wrap", {}), "ScanRuler_MeshWrap")
        self.assertEqual(echo.command_for("element_fit", {"kind": "sphere"}), "ScanRuler_ElementSphere")
        self.assertEqual(echo.command_for("element_fit", {"kind": "cylinder"}), "ScanRuler_ElementCylinder")
        self.assertTrue(any(t.get("title") == DK.TAB_TITLE for t in hooks.TABS))
        self.assertEqual(fl.SKIPPED, [])


def _project(folder, manifest, scan=None):
    path = os.path.join(folder, "old.scanruler")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("project.json", json.dumps(manifest))
        if scan:
            z.writestr("scan.stl", scan)
        z.writestr("reference.step", "x")
    return path


class ProjectImport(Fresh):
    def test_scan_elements_and_sections_through_the_tools(self):
        from scanrulerfc import project_import as P

        d = tempfile.mkdtemp()
        man = {"app": "ScanRuler", "schemaVersion": 1, "name": "Bracket", "workspace": "elements", "deviation": {}, "thickness": {}, "flat": {},
               "reverse": {"features": [1]},
               "scan": {"fileName": "bracket.stl", "member": "scan.stl", "units": "mm", "appliedAlignment": None, "dimensions": [],
                        "elements": [{"kind": "plane", "name": "Top", "source": {"type": "fitted", "seeds": [4]}},
                                     {"kind": "line", "name": "Edge", "source": {"type": "constructed"}}],
                        "sections": [{"name": "Mid", "kind": "cut", "frame": {"origin": [0, 0, 5], "normal": [0, 0, 1]}}]}}
        path = _project(d, man, b"solid x\nendsolid x\n")
        calls = []
        got = P.load(path, lambda t, a: calls.append((t, a)) or (True, {}), folder=d, doc_fn=lambda: None)
        self.assertEqual([c[0] for c in calls], ["scan_open", "element_fit", "section_cut"])
        self.assertEqual(calls[0][1], {"path": os.path.join(d, "bracket.stl"), "discard": True, "units": "mm"})
        self.assertEqual(calls[1][1], {"kind": "plane", "at": {"vertex": 4}, "name": "Top"})
        self.assertEqual(calls[2][1], {"across": {"origin": [0, 0, 5], "normal": [0, 0, 1]}, "name": "Mid", "kind": "cut"})
        self.assertEqual((got["project"], got["scan"], got["elements"], got["sections"]), ("Bracket", "bracket.stl", 1, 1))
        self.assertIn(P.REVERSE_LATER, got["notLoaded"])
        self.assertIn("needs FreeCAD", P.REVERSE_LATER)
        self.assertIsNone(got["reverse"])
        self.assertEqual(len(got["notLoaded"]), 3)  # reverse, the line, the reference

    def test_import_command_tells_the_panel(self):
        d = tempfile.mkdtemp()
        man = {"app": "ScanRuler", "schemaVersion": 1, "workspace": "elements", "deviation": {}, "thickness": {}, "flat": {}, "scan": None}
        path = _project(d, man)
        seen = []
        C.set_ui(lambda key, *a: seen.append((key,) + a))
        C.set_runner(lambda t, a: self.fail("no scan, no call"))
        try:
            got = C.import_project(path)
        finally:
            C.set_ui(None)
            C.set_runner(None)
        self.assertEqual(seen, [("load-scanruler", got)])
        self.assertEqual(got["project"], "old")

    def test_not_a_project(self):
        from scanrulerfc import project_import as P
        from scanrulerfc.errors import ToolError

        d = tempfile.mkdtemp()
        path = _project(d, {"app": "Other"})
        with self.assertRaises(ToolError) as c:
            P.load(path, lambda t, a: None)
        self.assertEqual(c.exception.message, "Not a ScanRuler project file.")


class Package(Fresh):
    def test_workbench_entry_and_version(self):
        with open(os.path.join(ROOT, "package.xml"), encoding="utf-8") as f:
            xml = f.read()
        self.assertIn("<classname>ScanRulerWorkbench</classname>", xml)
        self.assertIn("<icon>scanrulerfc/icons/ScanRulerWorkbench.svg</icon>", xml)
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "scanrulerfc", "icons", "ScanRulerWorkbench.svg")))
        self.assertIn(f"<version>{scanrulerfc.VERSION}</version>", xml)


def _base_entries():
    try:
        out = subprocess.run(["git", "-C", ROOT, "show", f"{BASE}:scanrulerfc/data/tools.json"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return json.loads(out.stdout)["entries"] if out.returncode == 0 else None


@unittest.skipUnless(HAVE_AL, "Agent Link is not importable here")
class ToolDump(Fresh):
    def test_only_the_added_tools_differ_from_before_the_gui(self):
        import scanrulerfc.agentlink_families as fl

        base = _base_entries()
        if base is None:
            self.skipTest(f"{BASE} is not in this clone")
        sess = types.SimpleNamespace(family_state={}, out_dir=tempfile.mkdtemp(), doc=None)
        now = {t.name: (t.description, t.schema, t.changes, fam.GROUP) for fam in fl.FAMILIES for t in fam.tools(sess)}
        was = {k: (v["description"], v["inputSchema"], v["changes"], v["group"]) for k, v in base.items()}
        from scanrulerfc.reverse.handlers import tool_names

        self.assertEqual(sorted(set(now) - set(was)), sorted(SNAPSHOT + MESH_ADDED + tuple(tool_names())))
        self.assertEqual(set(was) - set(now), set())
        changed = sorted(k for k in was if was[k] != now[k])
        # mesh_export also writes the trimmed piece and the wrap.
        self.assertEqual(changed, ["mesh_export"])
        self.assertEqual(now["mesh_export"][1]["properties"]["part"]["enum"], ["edited", "reduced", "piece", "wrap"])


if __name__ == "__main__":
    unittest.main()
