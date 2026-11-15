# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/app/reCommands.ts, reFeatureCommands.ts, reParameterCommands.ts, reBodyCommands.ts (what their commands promise)
# SPDX-License-Identifier: AGPL-3.0-only
#
# The Reverse engineer's tools: tools.json is Agent Link's tool-data format
# and names exactly the handlers there are; every tool of the design's list
# is there or waits for its build step; the echo declarations name real
# tools and the grid's commands. Then the tools at work, on a part in memory
# built on a kernel of boxes: features added, changed, suppressed, rolled
# back and removed, parameters driving a feature, picks by index, and the
# refusals in the original's words.
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

from reverse_fakekernel import FakeKernel  # noqa: E402
from scanrulerfc.reverse import handlers as H  # noqa: E402
from scanrulerfc.reverse.build import Builder  # noqa: E402
from scanrulerfc.reverse.features import KIND_LABELS  # noqa: E402
from scanrulerfc.reverse.sketch import add_rectangle, empty_sketch  # noqa: E402

try:
    from agentlink import tooldata

    HAVE_AL = True
except ImportError:
    HAVE_AL = False

# Design §4.1, every tool named there.
DESIGN = """reverse_feature_add reverse_feature_update reverse_feature_remove reverse_feature_move reverse_feature_suppress reverse_feature_rollback
reverse_feature_refit reverse_feature_clear reverse_feature_list reverse_feature_schema reverse_build reverse_build_stop reverse_sketch_edit
reverse_sketch_candidates reverse_parameter_add reverse_parameter_set reverse_parameter_rename reverse_parameter_remove reverse_parameter_list
reverse_body_describe reverse_body_names reverse_body_check reverse_body_review reverse_body_probe reverse_body_section reverse_body_volume_compare
reverse_body_clearance reverse_body_fillet_read reverse_body_fillet_try reverse_body_selected_faces reverse_body_face_triangles reverse_body_set
reverse_body_compare_in_deviation reverse_plane_describe reverse_section_fit reverse_section_outline reverse_section_stack reverse_thread_read
reverse_scan_tube_trace reverse_network_create reverse_network_edit reverse_network_read reverse_network_suggest_creases reverse_import_step
reverse_export_step reverse_export_stl reverse_import_scanruler""".split()
READS = {"reverse_feature_list", "reverse_feature_schema", "reverse_parameter_list", "reverse_body_names", "reverse_body_describe", "reverse_body_check", "reverse_body_clearance"}


def doc():
    """data/tools.json with only the reverse group's entries."""
    with open(os.path.join(HERE, "..", "scanrulerfc", "data", "tools.json"), encoding="utf-8") as f:
        d = json.load(f)
    d["entries"] = {k: v for k, v in d["entries"].items() if v["group"] == H.GROUP}
    return d


class ToolData(unittest.TestCase):
    def test_tools_and_handlers_are_the_same_names(self):
        self.assertEqual(set(H.tool_names()), set(H.handlers(store=H.MemoryStore(Builder(FakeKernel())))))
        self.assertFalse(set(H.tool_names()) & set(H.LATER))

    def test_every_design_tool_is_here_or_later(self):
        self.assertEqual(set(DESIGN), set(H.tool_names()) | set(H.LATER))
        self.assertTrue(all(7 <= n <= 14 for n in H.LATER.values()))

    def test_the_format(self):
        d = doc()
        if HAVE_AL:
            self.assertEqual(tooldata.check(d), [])
        self.assertRegex(d["dataVersion"], r"^1\.\d+\.\d+$")
        for name, e in d["entries"].items():
            self.assertRegex(name, r"^reverse_[a-z0-9_]+$")
            self.assertEqual(e["group"], H.GROUP)
            for k, t in (("description", str), ("inputSchema", dict), ("changes", bool), ("source", str), ("date", str)):
                self.assertIsInstance(e[k], t, f"{name}.{k}")
            self.assertGreaterEqual(len(e["description"]), 20)
            self.assertEqual(e["inputSchema"]["type"], "object")
            self.assertIn("ScanRuler by Stefan Hermann (CNC Kitchen)", e["source"])
            self.assertEqual(e["changes"], name not in READS, name)
            self.assertTrue(re.match(r"^\d{4}-\d{2}-\d{2}$", e["date"]))

    def test_required_fields_are_properties(self):
        for name, e in doc()["entries"].items():
            for r in e["inputSchema"].get("required", []):
                self.assertIn(r, e["inputSchema"]["properties"], name)


class Echo(unittest.TestCase):
    def test_declarations_name_tools(self):
        known = set(H.tool_names()) | set(H.LATER)
        for k in ("SHOWN", "NO_BUTTON"):
            for name in H.ECHO[k]:
                self.assertIn(name, known, f"{k}: {name}")
        for name in H.ECHO["COMMANDS"]:
            self.assertIn(name, known)
        self.assertEqual(H.ECHO["WORKBENCHES"], {"reverse_": "ScanRulerWorkbench"})
        self.assertEqual(H.ECHO["AREAS"], {"reverse": "Reverse engineer"})

    def test_a_command_for_every_grid_key(self):
        self.assertEqual(set(H.GRID_COMMANDS), set(KIND_LABELS) - {"sketch", "coil"})
        self.assertTrue(all(c.startswith("ScanRuler_Re") for c in H.GRID_COMMANDS.values()))
        self.assertEqual(H.command_for("reverse_feature_add", {"feature": {"kind": "extrude"}}), "ScanRuler_ReExtrude")
        self.assertEqual(H.command_for("reverse_feature_add", {"features": [{"kind": "boolean"}]}), "ScanRuler_ReBoolean")
        self.assertIsNone(H.command_for("reverse_feature_add", {"feature": {"kind": "sketch"}}))
        self.assertIsNone(H.command_for("reverse_feature_list", {}))


def sketch_record(x0, y0, x1, y1, name=None):
    s = empty_sketch()
    add_rectangle(s, [x0, y0], [x1, y1])
    return {"kind": "sketch", "plane": {"kind": "world", "axis": "z", "offset": 0}, "sketch": s, **({"name": name} if name else {})}


class AtWork(unittest.TestCase):
    def setUp(self):
        self.store = H.MemoryStore(Builder(FakeKernel()))
        self.t = H.handlers(store=self.store)

    def call(self, tool, **args):
        return self.t[tool](args)

    def refused(self, tool, code, **args):
        with self.assertRaises(H.Refusal) as e:
            self.call(tool, **args)
        self.assertEqual(e.exception.code, code)
        return e.exception.message

    def block(self):
        self.call("reverse_feature_add", feature=sketch_record(0, 0, 10, 10))
        return self.call("reverse_feature_add", feature={"kind": "extrude", "sketchId": 1, "extent": {"kind": "distance", "from": 0, "to": 10}, "op": "new"})

    def test_sketch_then_extrude(self):
        out = self.block()
        self.assertEqual(out["added"][0]["id"], 2)
        self.assertEqual(out["added"][0]["name"], "Extrude 1")
        self.assertEqual(out["added"][0]["status"], "ok")
        self.assertEqual([round(b["volume"]) for b in out["bodies"]], [1000])
        rows = self.call("reverse_feature_list")["features"]
        self.assertEqual([(r["kind"], r["name"]) for r in rows], [("sketch", "Sketch 1"), ("extrude", "Extrude 1")])
        whole = self.call("reverse_feature_list", feature="Extrude 1")
        self.assertEqual(whole["regions"], self.store.part()["features"][1]["regions"])
        self.assertEqual(whole["result"]["status"], "ok")

    def test_update_suppress_rollback(self):
        self.block()
        out = self.call("reverse_feature_update", feature=2, set={"extent": {"kind": "distance", "from": 0, "to": 4}})
        self.assertEqual([round(b["volume"]) for b in out["bodies"]], [400])
        out = self.call("reverse_feature_suppress", feature="extrude 1")
        self.assertEqual(out["bodies"], [])
        self.assertTrue(self.store.part()["features"][1]["suppressed"])
        self.call("reverse_feature_suppress", feature=2, suppressed=False)
        self.assertNotIn("suppressed", self.store.part()["features"][1])
        out = self.call("reverse_feature_rollback", after=1)
        self.assertEqual(out["rollback"], {"after": 1, "built": 1, "of": 2})
        self.assertEqual(out["bodies"], [])
        self.assertTrue(self.call("reverse_feature_list")["features"][1]["rolledBack"])
        out = self.call("reverse_feature_rollback")
        self.assertEqual(out["rollback"]["built"], 2)
        self.assertNotIn("rolledTo", self.store.part())

    def test_adding_at_a_rolled_back_bar(self):
        self.block()
        self.call("reverse_feature_rollback", after=1)
        self.call("reverse_feature_add", feature=sketch_record(20, 0, 30, 10, "Second"))
        p = self.store.part()
        self.assertEqual([f["name"] for f in p["features"]], ["Sketch 1", "Second", "Extrude 1"])
        self.assertEqual(p["rolledTo"], 2)

    def test_names_are_unique(self):
        self.block()
        msg = self.refused("reverse_feature_add", "invalid_input", feature={**sketch_record(0, 0, 1, 1), "name": "extrude 1"})
        self.assertIn("is already named “Extrude 1”", msg)
        self.assertIn("“extrude 2”, say", msg)
        msg = self.refused("reverse_feature_add", "invalid_input", features=[sketch_record(0, 0, 1, 1, "A"), sketch_record(0, 0, 1, 1, "a")])
        self.assertIn("Two features in this batch", msg)

    def test_parameters_drive_a_feature(self):
        self.block()
        self.call("reverse_parameter_add", name="h", expression="6")
        out = self.call("reverse_feature_update", feature=2, set={"exprs": {"extent.to": "h * 2"}})
        self.assertEqual([round(b["volume"]) for b in out["bodies"]], [1200])
        out = self.call("reverse_parameter_set", parameter="h", expression=2)
        self.assertEqual([round(b["volume"]) for b in out["bodies"]], [400])
        self.assertEqual(self.call("reverse_parameter_list")["parameters"][0]["value"], 2)
        self.assertIn("is read by Extrude 1", self.refused("reverse_parameter_remove", "invalid_state", parameter="h"))
        self.call("reverse_parameter_rename", parameter="h", to="height")
        self.assertEqual(self.store.part()["features"][1]["exprs"], {"extent.to": "height * 2"})
        self.assertIn("needs a name", self.refused("reverse_parameter_add", "invalid_input", name="", expression=1))

    def test_remove_with_dependents(self):
        self.block()
        self.call("reverse_feature_add", feature={"kind": "shell", "body": 2, "faces": [0], "thickness": 1})
        msg = self.refused("reverse_feature_remove", "invalid_state", feature=2)
        self.assertIn("Shell 1 uses what Extrude 1 makes", msg)
        out = self.call("reverse_feature_remove", feature=2, dependents=True)
        self.assertEqual(out["removed"], [2, 3])

    def test_picks_by_index_are_stored_as_fingerprints(self):
        self.block()
        faces = self.call("reverse_body_describe", body=2)["faces"]
        self.call("reverse_feature_add", feature={"kind": "shell", "body": "Extrude 1", "faces": [1], "thickness": 1})
        stored = self.store.part()["features"][2]["faces"][0]
        self.assertEqual(stored, {k: v for k, v in faces[1].items() if k != "index"})
        self.assertIn("no faces 99", self.refused("reverse_feature_add", "invalid_input", feature={"kind": "shell", "body": 2, "faces": [99], "thickness": 1}).replace("face 99", "faces 99"))

    def test_a_feature_that_is_not_ready_is_refused(self):
        self.block()
        self.assertIn("not ready to make", self.refused("reverse_feature_add", "invalid_input", feature={"kind": "fillet", "body": 2, "edges": [], "radius": 1}))
        self.assertIn("No feature kind", self.refused("reverse_feature_add", "invalid_input", feature={"kind": "gear"}))
        self.assertIn("not ready to make", self.refused("reverse_feature_add", "invalid_input", feature={"kind": "extrude", "sketchId": 99}))

    def test_bodies(self):
        self.block()
        names = self.call("reverse_body_names")["bodies"]
        self.assertEqual([(b["id"], b["visible"]) for b in names], [(2, True)])
        out = self.call("reverse_body_set", body=2, name="Base", color="blue", visible=False)
        self.assertEqual(out["bodies"][0]["style"], {"name": "Base", "color": "#2f73c4"})
        self.assertFalse(out["bodies"][0]["visible"])
        self.assertEqual(self.store.part()["hiddenBodies"], [2])
        self.assertIn("No body is 'Nope'", self.refused("reverse_body_check", "not_found", body="Nope"))
        self.assertEqual(self.call("reverse_body_describe", body=2, detail="brief")["faces"], 6)

    def test_move_and_clear(self):
        self.block()
        self.call("reverse_feature_add", feature=sketch_record(20, 0, 30, 10))
        self.assertIn("after names a feature that is moved", self.refused("reverse_feature_move", "invalid_state", feature=3, after=3))
        self.call("reverse_feature_move", feature=3)
        self.assertEqual([f["id"] for f in self.store.part()["features"]], [3, 1, 2])
        self.refused("reverse_feature_clear", "invalid_input")
        self.call("reverse_feature_clear", confirm=True)
        self.assertEqual(self.store.part()["features"], [])

    def test_schema_and_stop(self):
        s = self.call("reverse_feature_schema", kind="fillet")
        self.assertEqual(s["fields"]["radius"], 1)
        self.assertTrue(s["fields"]["chain"])
        self.assertEqual(self.call("reverse_feature_schema", kind="extrude")["fields"]["extent"], {"kind": "distance", "from": 0, "to": 10})
        self.assertNotIn("builds", self.call("reverse_feature_schema", kind="loft"))  # build step 10 is in
        self.refused("reverse_build_stop", "unavailable")
        self.assertEqual(self.call("reverse_build")["bodies"], [])


if __name__ == "__main__":
    unittest.main()
