# SPDX-License-Identifier: AGPL-3.0-only
# ScanRuler for FreeCAD stands without Agent Link: every module but the
# family layer (agentlink_families and scanrulerfc.agentlink.*) imports with
# Agent Link blocked; the tools' declarations are data (data/tools.json)
# and match what Agent Link is given; the add-on's own runner answers as
# the hosted tools do; the manual maker runs manual_plan then
# manual_render through whatever runner it is handed.
import glob
import json
import os
import subprocess
import sys
import tempfile
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from meshkit import box_mesh  # noqa: E402

try:
    import agentlink.hooks  # noqa: F401

    HAVE_AL = True
except ImportError:
    HAVE_AL = False

BLOCK = r'''
import importlib.abc, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name == "agentlink" or name.startswith("agentlink."):
            raise ImportError("blocked: " + name)
        return None
sys.meta_path.insert(0, Block())
sys.path.insert(0, ROOT)
import importlib
for n in NAMES:
    importlib.import_module(n)
import scanrulerfc
assert scanrulerfc._hosted is False
assert not any(m == "agentlink" or m.startswith("agentlink.") for m in sys.modules), "agentlink imported"
print("ok", len(NAMES))
'''


def plain_modules():
    pkg = os.path.join(ROOT, "scanrulerfc")
    out = []
    for p in sorted(glob.glob(os.path.join(pkg, "**", "*.py"), recursive=True)):
        rel = os.path.relpath(p, ROOT)[:-3].replace(os.sep, ".")
        rel = rel[: -len(".__init__")] if rel.endswith(".__init__") else rel
        if rel == "scanrulerfc.agentlink_families" or rel == "scanrulerfc.agentlink" or rel.startswith("scanrulerfc.agentlink."):
            continue
        out.append(rel)
    return out


def declared():
    with open(os.path.join(ROOT, "scanrulerfc", "data", "tools.json"), encoding="utf-8") as f:
        return json.load(f)


class Alone(unittest.TestCase):
    def test_every_module_imports_with_agentlink_blocked(self):
        names = plain_modules()
        self.assertIn("scanrulerfc.handlers.scan", names)
        code = f"ROOT = {ROOT!r}\nNAMES = {names!r}\n" + BLOCK
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        self.assertIn(f"ok {len(names)}", r.stdout)

    def test_only_the_family_layer_names_agentlink(self):
        for n in plain_modules():
            path = os.path.join(ROOT, *n.split(".")) + (".py" if not os.path.isdir(os.path.join(ROOT, *n.split("."))) else os.sep + "__init__.py")
            with open(path, encoding="utf-8") as f:
                src = f.read()
            self.assertNotRegex(src, r"(?m)^\s*(from agentlink[ .]|import agentlink)", n)

    def test_handlers_and_declarations_are_one_set(self):
        from scanrulerfc import handlers

        doc = declared()
        self.assertEqual(set(handlers.all_handlers()), set(doc["entries"]))
        for m in handlers.MODULES:
            mod = handlers.module(m)
            groups = {doc["entries"][n]["group"] for n in mod.NAMES}
            self.assertEqual(len(groups), 1, m)

    def test_declarations_are_in_agent_links_format(self):
        doc = declared()
        self.assertEqual(doc["dataVersion"].split(".")[0], "1")
        for name, e in doc["entries"].items():
            for k, t in {"group": str, "description": str, "inputSchema": dict, "changes": bool, "source": str, "date": str}.items():
                self.assertIsInstance(e.get(k), t, f"{name}.{k}")
            self.assertEqual(e["inputSchema"].get("type"), "object", name)

    def test_no_agentlink_dependency_in_package_xml(self):
        with open(os.path.join(ROOT, "package.xml"), encoding="utf-8") as f:
            xml = f.read()
        self.assertNotIn("<depend>Agent Link</depend>", xml)
        # 1.0: the oldest FreeCAD CI runs, as the rest of the suite.
        self.assertIn("<freecadmin>1.0.0</freecadmin>", xml)

    def test_credit_lives_in_the_package(self):
        import scanrulerfc

        self.assertIn("Stefan Hermann (CNC Kitchen)", scanrulerfc.CREDIT)

    def test_local_runner_refuses_as_agent_link_does(self):
        from scanrulerfc import runner

        run = runner.local(ctx=runner.Context(out_dir=tempfile.mkdtemp()))
        ok, out = run("scan_nearest", {"at": {"point": [0, 0, 0]}})
        self.assertFalse(ok)
        self.assertEqual(out, {"error": {"code": "no_scan", "message": "No scan is open — open one with scan_open first."}})
        ok, out = run("no_such_tool", {})
        self.assertEqual(out["error"]["code"], "not_found")


class Bare:
    """A session as the tools see one, with no FreeCAD document."""

    def __init__(self, out):
        self.family_state = {}
        self.out_dir = out
        self.doc = None


# One call (or a refusal) per family, on the test box scan, FreeCAD absent.
CALLS = [
    ("scan_info", {}),
    ("scan_nearest", {"at": {"point": [0, 0, 10.5]}}),
    ("element_fit", {"kind": "plane", "at": {"point": [0, 0, 10]}}),
    ("element_list", {}),
    ("align_auto", {}),
    ("element_list", {}),
    ("report_get", {}),
    ("section_list", {}),
    ("mesh_inspect", {}),
    ("flat_report", {}),
    ("deviation_settings", {}),
    ("thickness_settings", {}),
    ("scan_noise", {}),
    ("scan_thread", {"axis": {"origin": [0, 0, -10], "direction": [0, 0, 1], "radius": 5}}),
    ("wear_diff", {}),
    ("catalog_links", {"query": "M3 screw"}),
    ("manual_check", {}),
    ("fit_scan_features", {}),
]


# Bad arguments: refused by the local runner as Agent Link's server refuses
# them (its check_input before the tool), and the ones it takes in another
# dress (a number as text, a synonym, an enum's case) taken the same way.
BAD_CALLS = [
    ("scan_info", {"verbose": True}),
    ("element_fit", {"at": {"point": [0, 0, 10]}}),
    ("element_fit", {"kind": "blob", "at": {"point": [0, 0, 10]}}),
    ("element_fit", {"kind": "PLANE", "at": {"point": [0, 0, 10]}}),
    ("element_fit", {"kind": "plane", "at": {"point": [0, 0, 10]}, "name": 5}),
    ("scan_open", {"units": "furlong"}),
    ("scan_open", {"discard": "maybe"}),
    ("scan_snapshot_latest", {"index": "1"}),
    ("scan_snapshot_latest", {"index": 1.5}),
    ("mesh_wrap", {}),
    ("mesh_apply_wrap", {}),
    ("mesh_export", {"part": "whole"}),
]


@unittest.skipUnless(HAVE_AL, "Agent Link is not importable here")
class SameAnswers(unittest.TestCase):
    def _scan(self, ctx):
        from scanrulerfc import scanstate as S

        V, F = box_mesh(40.0, 30.0, 20.0, n=10)
        S.state(ctx)["scan"] = S.Scan("box.stl", np.asarray(V, float), np.asarray(F, np.int64))

    def test_local_runner_answers_as_the_hosted_tools(self):
        import importlib

        from agentlink.protocol import ToolError

        import scanrulerfc.agentlink_families as fl
        from scanrulerfc import runner

        hosted = Bare(tempfile.mkdtemp())
        self._scan(hosted)
        T = {}
        for fam in fl.FAMILIES:
            for t in fam.tools(hosted):
                T[t.name] = t
        local = runner.Context(out_dir=tempfile.mkdtemp())
        self._scan(local)
        run = runner.local(ctx=local)
        from agentlink.protocol import check_input

        seen = set()
        for name, args in CALLS + BAD_CALLS:
            try:
                a = dict(args)
                check_input(T[name].schema, a)  # what Agent Link's server does first
                out = T[name].fn(a)
                if isinstance(out, dict):
                    out.pop("_png", None)
                want = (True, runner.plain(out))
            except ToolError as e:
                want = (False, {"error": {"code": e.code, "message": e.message}})
            got = run(name, dict(args))
            self.assertEqual(got, want, (name, args))
            seen.add(T[name].group)
        self.assertGreaterEqual(len(seen), 16)
        refused = [run(n, dict(a)) for n, a in BAD_CALLS]
        self.assertGreaterEqual(sum(1 for ok, out in refused if not ok and out["error"]["code"] == "invalid_input"), 7)
        importlib.import_module("scanrulerfc")

    def test_declarations_are_what_agent_link_lists(self):
        import scanrulerfc.agentlink_families as fl

        entries = declared()["entries"]
        listed = []
        for fam in fl.FAMILIES:
            for t in fam.tools(Bare(tempfile.mkdtemp())):
                listed.append(t.name)
                e = entries[t.name]
                self.assertEqual((t.description, t.schema, t.changes, fam.GROUP), (e["description"], e["inputSchema"], e["changes"], e["group"]), t.name)
        self.assertEqual(listed, list(entries))
        self.assertEqual(fl.SKIPPED, [])

    def test_family_layer_says_hosted_and_provides_the_manual_maker(self):
        from agentlink import hooks

        import scanrulerfc
        import scanrulerfc.agentlink_families as fl
        from scanrulerfc.manual_maker import ManualMaker

        self.assertTrue(scanrulerfc._hosted)
        self.assertIsInstance(hooks.service("manual_maker"), ManualMaker)
        from scanrulerfc.pack_service import LibraryPack

        self.assertIsInstance(hooks.service("library_pack"), LibraryPack)
        self.assertEqual(fl.CREDIT, scanrulerfc.CREDIT)

    def test_refusals_cross_the_boundary_unchanged(self):
        from agentlink.protocol import ToolError

        import scanrulerfc.agentlink_families as fl

        T = {t.name: t for fam in fl.FAMILIES for t in fam.tools(Bare(tempfile.mkdtemp()))}
        with self.assertRaises(ToolError) as c:
            T["scan_nearest"].fn({"at": {"point": [0, 0, 0]}})
        self.assertEqual((c.exception.code, c.exception.message), ("no_scan", "No scan is open — open one with scan_open first."))


class ManualMakerService(unittest.TestCase):
    def _runner(self, answers):
        calls = []

        def run(tool, args):
            calls.append((tool, args))
            return answers[tool]

        return run, calls

    def test_plan_then_render_through_the_runner(self):
        from scanrulerfc import CREDIT
        from scanrulerfc.manual_maker import ManualMaker

        run, calls = self._runner({"manual_plan": (True, {"steps": []}),
                                   "manual_render": (True, {"file": {"path": "/x/manual.html", "name": "manual.html", "bytes": 10}, "steps": 2, "lint": {"step 1": ["passive"]}})})
        rows = [{"title": "Base", "bodies": ["Base"], "note": ""}, {"title": "Lid on", "bodies": ["Lid", "Screw"], "note": "Press the lid down."}, {"title": "Empty", "bodies": [], "note": ""}]
        ok, out = ManualMaker().make(run, rows, "Box")
        self.assertTrue(ok)
        self.assertEqual(out, {"file": {"path": "/x/manual.html", "name": "manual.html", "bytes": 10}, "steps": 2, "credit": CREDIT, "lint": {"step 1": ["passive"]}})
        self.assertEqual([c[0] for c in calls], ["manual_plan", "manual_render"])
        self.assertEqual(calls[0][1], {"fromBodies": True, "steps": [
            {"id": "s1", "place": [{"part": "Base"}], "text": "Base"},
            {"id": "s2", "place": [{"part": "Lid"}, {"part": "Screw"}], "text": "Press the lid down.", "notes": "Lid on"}],
            "settings": {"title": "Box"}})
        self.assertEqual(calls[1][1], {})

    def test_a_refusal_comes_back_and_render_is_not_asked(self):
        from scanrulerfc.manual_maker import ManualMaker

        no = {"error": {"code": "not_found", "message": "Part 'Lid': no body 'Lid' in the document."}}
        run, calls = self._runner({"manual_plan": (False, no)})
        self.assertEqual(ManualMaker().make(run, [{"title": "Lid", "bodies": ["Lid"]}], ""), (False, no))
        self.assertEqual([c[0] for c in calls], ["manual_plan"])
        self.assertNotIn("settings", calls[0][1])

    def test_no_parts_ticked_is_refused_without_a_call(self):
        from scanrulerfc.manual_maker import ManualMaker

        run, calls = self._runner({})
        ok, out = ManualMaker().make(run, [{"title": "x", "bodies": []}], "")
        self.assertFalse(ok)
        self.assertEqual(out["error"]["code"], "invalid_input")
        self.assertEqual(calls, [])

    def test_documents_reads_the_answer(self):
        # Workshop Documents' make_manual reads file["path"], steps, lint, credit.
        from scanrulerfc.manual_maker import ManualMaker

        run, _ = self._runner({"manual_plan": (True, {}), "manual_render": (True, {"file": {"path": "/m.html"}, "steps": 1})})
        ok, out = ManualMaker().make(run, [{"title": "A", "bodies": ["A"], "note": ""}], "")
        self.assertTrue(ok)
        self.assertEqual((out["file"]["path"], out["steps"], out["lint"]), ("/m.html", 1, {}))
        self.assertTrue(out["credit"])


if __name__ == "__main__":
    unittest.main()
