# SPDX-License-Identifier: AGPL-3.0-only
# The Reverse engineer wired in: its 22 tools in data/tools.json and the
# handlers registry, a deferred group of its own, its echo declared with the
# other families', the page's keys calling the present tools through the
# runner, and a .scanruler project's part opening in the document's
# container (in FreeCAD).
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
if os.environ.get("FREECAD_LIB"):
    sys.path.append(os.environ["FREECAD_LIB"])
try:
    import FreeCAD  # noqa: F401
    import Part  # noqa: F401

    HAVE_FC = True
except ImportError:
    HAVE_FC = False
try:
    import agentlink.hooks  # noqa: F401

    HAVE_AL = True
except ImportError:
    HAVE_AL = False

from scanrulerfc import dock as DK  # noqa: E402
from scanrulerfc import handlers, runner  # noqa: E402
from scanrulerfc import workspaces as W  # noqa: E402
from scanrulerfc.pages import reverse as RV  # noqa: E402
from scanrulerfc.reverse import build as RB  # noqa: E402
from scanrulerfc.reverse import handlers as RH  # noqa: E402

# The tree before the Reverse engineer was wired in.
BASE = "0f44f35"
ADDED = sorted("""reverse_feature_add reverse_feature_update reverse_feature_remove reverse_feature_move reverse_feature_suppress
reverse_feature_rollback reverse_feature_clear reverse_feature_list reverse_feature_schema reverse_build reverse_build_stop
reverse_parameter_list reverse_parameter_add reverse_parameter_set reverse_parameter_rename reverse_parameter_remove
reverse_body_names reverse_body_describe reverse_body_check reverse_body_clearance reverse_body_set reverse_import_step""".split())


# Renamed since: Agent Link's core has snapshot_list / snapshot_latest.
RENAMED = {f"snapshot_{x}": f"scan_snapshot_{x}" for x in ("list", "latest", "wait")}


def _renamed(entries):
    """The base's entries under today's names, their text naming them so."""
    out = {}
    for k, v in entries.items():
        text = json.dumps(v)
        for a, b in RENAMED.items():
            text = text.replace(a, b)
        out[RENAMED.get(k, k)] = json.loads(text)
    return out


def _declared():
    with open(os.path.join(ROOT, "scanrulerfc", "data", "tools.json"), encoding="utf-8") as f:
        return json.load(f)["entries"]


def _base_entries():
    try:
        out = subprocess.run(["git", "-C", ROOT, "show", f"{BASE}:scanrulerfc/data/tools.json"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return _renamed(json.loads(out.stdout)["entries"]) if out.returncode == 0 else None


class Registry(unittest.TestCase):
    def test_22_tools_in_the_data_and_the_handlers(self):
        self.assertEqual(len(ADDED), 22)
        self.assertEqual(sorted(RH.tool_names()), ADDED)
        self.assertEqual(sorted(n for n, e in _declared().items() if e["group"] == "reverse"), ADDED)
        self.assertIn("reverse", handlers.MODULES)
        self.assertEqual(sorted(handlers.module("reverse").NAMES), ADDED)
        self.assertTrue(set(ADDED) <= set(handlers.all_handlers()))
        self.assertFalse(set(ADDED) & set(RH.LATER))

    def test_tool_dump_differs_from_before_only_by_the_reverse_tools(self):
        # (and the snapshot tools' rename, RENAMED)
        base = _base_entries()
        if base is None:
            self.skipTest(f"{BASE} is not in this clone")
        now = _declared()
        self.assertEqual(sorted(set(now) - set(base)), ADDED)
        self.assertEqual(set(base) - set(now), set())
        # Edited since on purpose: the boolean and the trim no longer need
        # FreeCAD's Mesh booleans (meshbool), and their descriptions say so.
        edited = {"mesh_boolean", "mesh_trim"}
        self.assertEqual(sorted(k for k in base if base[k] != now[k] and k not in edited), [])
        for k in edited:
            self.assertEqual({f: v for f, v in base[k].items() if f != "description"}, {f: v for f, v in now[k].items() if f != "description"})

    def test_a_refusal_is_the_add_ons(self):
        # Imported here: other tests load scanrulerfc afresh.
        from scanrulerfc import errors
        from scanrulerfc import runner as R
        from scanrulerfc.reverse import handlers as fresh

        self.assertTrue(issubclass(fresh.Refusal, errors.ToolError))
        ok, got = R.local(ctx=R.Context(None))("reverse_feature_list", {})
        self.assertFalse(ok)
        self.assertEqual(got["error"]["code"], "unavailable")

    def test_later_keys_are_the_engines_later_kinds(self):
        # The workbench's keys may lag the engine (they are the GUI's to turn
        # on), never lead it: a kind the engine cannot build has no live key.
        self.assertLessEqual(set(RB.LATER) | {"import"}, set(W.REVERSE_LATER))
        self.assertNotIn("reverse_import_step", RH.LATER)  # build step 10: here
        self.assertIn("reverse_import_step", RH.tool_names())


@unittest.skipUnless(HAVE_AL, "Agent Link is not importable here")
class Family(unittest.TestCase):
    def test_deferred_group_with_the_tools(self):
        import scanrulerfc.agentlink_families as fl
        from scanrulerfc.agentlink import fam_reverse

        self.assertIn(fam_reverse, fl.FAMILIES)
        self.assertEqual(fam_reverse.GROUP, "reverse")
        self.assertFalse(getattr(fam_reverse, "LEAN", False))  # not in the lean list: deferred
        sess = types.SimpleNamespace(family_state={}, out_dir=tempfile.mkdtemp(), doc=None)
        self.assertEqual(sorted(t.name for t in fam_reverse.tools(sess)), ADDED)

    def test_family_dump_differs_from_before_only_by_the_reverse_tools(self):
        import scanrulerfc.agentlink_families as fl

        base = _base_entries()
        if base is None:
            self.skipTest(f"{BASE} is not in this clone")
        sess = types.SimpleNamespace(family_state={}, out_dir=tempfile.mkdtemp(), doc=None)
        now = {t.name: (t.description, t.schema, t.changes, fam.GROUP) for fam in fl.FAMILIES for t in fam.tools(sess)}
        was = {k: (v["description"], v["inputSchema"], v["changes"], v["group"]) for k, v in base.items()}
        self.assertEqual(sorted(set(now) - set(was)), ADDED)
        self.assertEqual(set(was) - set(now), set())
        self.assertEqual(sorted(k for k in was if was[k] != now[k]), [])

    def test_echo(self):
        import scanrulerfc.agentlink_families as fl

        self.assertEqual(fl.WORKBENCHES["reverse_"], "ScanRulerWorkbench")
        self.assertEqual(fl.AREAS["reverse_"], "Reverse engineer")
        self.assertIn("reverse_feature_list", fl.SHOWN)
        self.assertIn("reverse_build_stop", fl.NO_BUTTON)
        self.assertEqual(fl.command_for("reverse_feature_add", {"feature": {"kind": "fillet"}}), "ScanRuler_ReFillet")
        self.assertEqual(fl.command_for("reverse_feature_add", {"features": [{"kind": "boolean"}]}), "ScanRuler_ReBoolean")
        self.assertIsNone(fl.command_for("reverse_feature_add", {}))
        self.assertEqual(fl.COMMANDS["reverse_import_step"], "ScanRuler_ReImport")
        commands = {k["command"] for k in W.keys("reverse")}
        self.assertTrue(set(RH.GRID_COMMANDS.values()) <= commands)
        self.assertTrue(set(RH.ECHO["COMMANDS"].values()) <= commands)


class Page(unittest.TestCase):
    def test_keys_of_present_tools_call_them_through_the_runner(self):
        calls = []

        def run(tool, args):
            calls.append((tool, args))
            return True, {}

        read = lambda t, a=None: (True, {"parameters": [{"id": 1, "name": "p1", "expression": "2"}]}) if t == "reverse_parameter_list" else (False, None)
        m = RV.build({}, read=read)
        on = [k["id"] for s in m["sections"] for k in s["keys"] if k["enabled"]]
        self.assertEqual(set(on), set(RV.READY_KINDS) | {"play", "parameter-add"})
        present = set(RH.tool_names())
        from scanrulerfc.reverse.editor import EDITOR

        self.addCleanup(EDITOR.close)
        for kid in on:
            calls.clear()
            if kid == "parameter-add":
                got = DK.press(types.SimpleNamespace(call_for=lambda k, ui: RV.call_for(k, ui, read=read)), kid, {}, run=run)
            elif kid in RV.READY_KINDS:
                # A Create feature key opens the kind's box; its Create calls the tool.
                self.assertIsNone(DK.press(RV, kid, {}, run=run), kid)
                self.assertEqual((calls, EDITOR.record["kind"]), ([], kid))
                got = DK.press(RV, "editor-create", {}, run=run)
                self.assertFalse(EDITOR.open, kid)
            else:
                got = DK.press(RV, kid, {}, run=run)
            self.assertIsNotNone(got, kid)
            self.assertEqual(len(calls), 1, kid)
            self.assertIn(calls[0][0], present, kid)
        self.assertIsNone(RV.call_for("fillet", {}))
        self.assertEqual(RV.call_for("editor-create", {})[0], "reverse_feature_add")
        self.assertEqual(RV.call_for("editor-create", {})[1]["feature"]["kind"], "fillet")
        self.assertIsNone(RV.call_for("editor-cancel", {}))
        self.assertFalse(EDITOR.open)
        self.assertEqual(RV.call_for("play", {}), ("reverse_build", {}))
        self.assertEqual(RV.call_for("parameter-add", {}, read=read), ("reverse_parameter_add", {"name": "p2", "expression": "0"}))
        for kid in W.REVERSE_LATER:
            self.assertIsNone(RV.call_for(kid, {}), kid)

    def test_lists_read_the_tools(self):
        answers = {"reverse_feature_list": {"features": [{"id": 1, "name": "Sketch 1", "kind": "sketch", "status": "ok"},
                                                        {"id": 2, "name": "Extrude 1", "kind": "extrude", "rolledBack": True}]},
                   "reverse_body_names": {"bodies": [{"id": 1, "name": "Body 1", "volume": 1000.0, "closed": True, "surface": False, "visible": True}]},
                   "reverse_parameter_list": {"parameters": []}}
        asked = []
        m = RV.build({}, read=lambda t, a=None: asked.append(t) or (True, answers[t]))
        self.assertEqual(sorted(asked), sorted(RV.READS))
        sec = {s["id"]: s for s in m["sections"]}
        self.assertEqual([(r["name"], r["reading"]) for r in sec["features"]["rows"]], [("Sketch 1", "ok"), ("Extrude 1", "rolled back")])
        self.assertEqual(sec["features"]["count"], 2)
        self.assertEqual([(r["name"], r["reading"]) for r in sec["bodies"]["rows"]], [("Body 1", "1000 mm³")])
        self.assertEqual(sec["parameters"]["count"], 0)


def _project(folder, part):
    path = os.path.join(folder, "part.scanruler")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("project.json", json.dumps({"app": "ScanRuler", "schemaVersion": 1, "name": "Bracket", "scan": None, "reverse": part}))
    return path


PART = {"version": 3, "features": [], "nextFeatureId": 1, "nextOfKind": {},
        "parameters": [{"id": 1, "name": "w", "kind": "length", "expression": "10"}], "nextParameterId": 2}


@unittest.skipUnless(HAVE_FC, "needs FreeCAD")
class InFreeCAD(unittest.TestCase):
    def setUp(self):
        self.doc = FreeCAD.newDocument("ReverseWiringTest")
        self.doc.UndoMode = 1

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)

    def test_scanruler_load_into_the_container(self):
        from scanrulerfc import project_import as P
        from scanrulerfc.reverse import doc as D

        got = P.load(_project(tempfile.mkdtemp(), PART), lambda t, a: (True, {}), doc_fn=lambda: self.doc)
        self.assertEqual(got["reverse"], {"features": 0, "failed": 0})
        self.assertNotIn(P.REVERSE_LATER, got["notLoaded"])
        c = D.find_container(self.doc)
        self.assertIsNotNone(c)
        self.assertEqual(D.part_of(c.PartJson)["parameters"][0]["name"], "w")

    def test_runner_call_is_one_undo_step(self):
        run = runner.local(ctx=runner.Context(self.doc))
        before = self.doc.UndoCount
        ok, got = run("reverse_parameter_add", {"name": "w", "expression": "12"})
        self.assertTrue(ok, got)
        self.assertEqual(self.doc.UndoCount, before + 1)
        ok, got = run("reverse_parameter_list", {})
        self.assertEqual([p["name"] for p in got["parameters"]], ["w"])


if __name__ == "__main__":
    unittest.main()
