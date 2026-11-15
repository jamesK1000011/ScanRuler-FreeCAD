# SPDX-License-Identifier: AGPL-3.0-only
# The Reverse engineer's feature editor (ported from ScanRuler by Stefan
# Hermann / CNC Kitchen: FeatureEditor.tsx, reGripSlice.ts, Builder.preview):
# a Create feature key opens the box, its numbers typed or dragged on a grip,
# the field on the grip taking a number or an expression, the ghost built on
# the part as it stands without committing anything, and Create or Save
# changes making it through the tools. On a part in memory built on a kernel
# of boxes, so no FreeCAD is needed.
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

from reverse_fakekernel import FakeKernel  # noqa: E402
from scanrulerfc.pages import reverse as RV  # noqa: E402
from scanrulerfc.reverse import doc as D  # noqa: E402
from scanrulerfc.reverse import ghost as GH  # noqa: E402
from scanrulerfc.reverse import grips as G  # noqa: E402
from scanrulerfc.reverse import handlers as H  # noqa: E402
from scanrulerfc.reverse.build import Builder  # noqa: E402
from scanrulerfc.reverse.editor import EDITOR, Editor, start_record  # noqa: E402
from scanrulerfc.reverse.parameters import evaluate_parameters  # noqa: E402
from scanrulerfc.reverse.sketch import add_rectangle, empty_sketch  # noqa: E402


def sketch_record(x0, y0, x1, y1):
    s = empty_sketch()
    add_rectangle(s, [x0, y0], [x1, y1])
    return {"kind": "sketch", "plane": {"kind": "world", "axis": "z", "offset": 0}, "sketch": s}


class Part:
    """A part in memory with a 10 mm square sketched, its tools and an env as
    the page and the view read it."""

    def __init__(self):
        self.store = H.MemoryStore(Builder(FakeKernel()))
        self.t = H.handlers(store=self.store)
        self.t["reverse_feature_add"]({"feature": sketch_record(0, 0, 10, 10)})
        self.env = {"store": lambda: self.store, "bodies": lambda: self.t["reverse_body_names"]({}).get("bodies") or [],
                    "scope": lambda: evaluate_parameters(self.store.part().get("parameters") or [])["scope"]}

    def run(self, tool, args):
        return self.t[tool](args)

    def volumes(self):
        return [round(b["volume"]) for b in self.store.builder.briefs()]


class Grips(unittest.TestCase):
    def setUp(self):
        self.p = Part()
        self.rec = start_record("extrude", self.p.store.part())

    def test_an_extrude_wears_its_two_arrows_and_the_taper(self):
        g = G.grips_of(self.rec, self.p.store.part()["features"])
        self.assertEqual([x["side"] for x in g], ["extrudeFrom", "extrudeTo", "taper"])
        self.assertEqual(g[1]["position"], [5, 5, 10])

    def test_a_drag_and_a_number_typed(self):
        d = G.Drag(self.rec, "extrudeTo")
        moved = d.move(self.rec, 4.567)
        self.assertEqual(moved["extent"], {"kind": "distance", "from": 0, "to": 14.57})
        self.assertEqual(G.field_value(moved, "extrudeTo"), {"value": 14.57, "unit": "mm"})
        typed = G.set_value(moved, "extrudeFrom", -3)
        self.assertEqual(typed["extent"]["from"], -3)
        tap = G.Drag(self.rec, "taper").move(self.rec, 10)
        self.assertEqual(G.field_value(tap, "taper"), {"value": 45, "unit": "°"})

    def test_a_drag_lets_the_expression_go(self):
        rec = G.with_expr(self.rec, "extent.to", "h * 2")
        self.assertEqual(G.field_value(rec, "extrudeTo")["expr"], "h * 2")
        self.assertNotIn("exprs", G.Drag(rec, "extrudeTo").move(rec, 1))

    def test_on_body_grips(self):
        fil = {"kind": "fillet", "body": 2, "edges": [{"mid": [5, 0, 10], "faces": [{"dir": [0, 0, 1]}, {"dir": [0, -1, 0]}]}], "radius": 1}
        self.assertEqual([x["side"] for x in G.grips_of(fil)], ["radius"])
        self.assertEqual(G.Drag(fil, "radius").move(fil, 0.5)["radius"], 1.5)
        self.assertEqual(G.Drag(fil, "radius").move(fil, -5)["radius"], 0.01)
        mv = {"kind": "moveBody", "bodies": [2], "pivot": [0, 0, 0], "translate": [0, 0, 0], "rotate": [0, 0, 0]}
        self.assertEqual(len(G.grips_of(mv)), 6)
        self.assertEqual(G.Drag(mv, "moveY").move(mv, 3.333)["translate"], [0, 3.33, 0])
        self.assertEqual(G.Drag(mv, "turnZ").move(mv, 44.6)["rotate"], [0, 0, 45])
        self.assertEqual(G.field_value(mv, "turnZ")["unit"], "°")

    def test_read_field(self):
        self.assertEqual(G.read_field("12.5", "length", None), {"ok": True, "value": 12.5, "expr": None})
        self.assertAlmostEqual(G.read_field("1", "length", None, "in")["value"], 25.4)
        scope = evaluate_parameters([{"id": 1, "name": "h", "kind": "length", "expression": "5 mm"}])["scope"]
        self.assertEqual(G.read_field("h * 2", "length", scope), {"ok": True, "value": 10, "expr": "h * 2"})
        self.assertFalse(G.read_field("nope", "length", scope)["ok"])
        self.assertEqual(G.field_text({"value": 14.567, "unit": "mm"}), "14.57")
        self.assertEqual(G.field_text({"value": 25.4, "unit": "mm"}, "in"), "1")


class TheBox(unittest.TestCase):
    def setUp(self):
        self.p = Part()
        self.ed = Editor()

    def test_new_extrude_its_numbers_and_create(self):
        self.ed.open_new("extrude", self.p.store.part())
        self.assertEqual(self.ed.title(), "Extrude 1")
        self.assertEqual([s["label"] for s in self.ed.slots()], ["From", "To", "Taper"])
        self.assertEqual(self.ed.create_label(), "Create extrude")
        self.assertTrue(self.ed.set_slot("extent.to", "20"))
        self.assertFalse(self.ed.set_slot("extent.to", "nope"))
        self.assertIn("nope", self.ed.error)
        tool, args = self.ed.create()
        self.assertEqual(tool, "reverse_feature_add")
        self.assertEqual(args["feature"]["extent"]["to"], 20)
        out = self.p.run(tool, args)
        self.assertEqual([round(b["volume"]) for b in out["bodies"]], [2000])

    def test_the_field_on_a_grip(self):
        self.ed.open_new("extrude", self.p.store.part())
        self.ed.grip_drag("extrudeTo", 0, "start")
        self.assertTrue(self.ed.dragging)
        self.ed.grip_drag("extrudeTo", 5, "move")
        self.ed.grip_drag(None, 0, "end")
        self.assertFalse(self.ed.dragging)
        self.assertEqual(self.ed.field_value(), {"value": 15, "unit": "mm"})
        scope = evaluate_parameters([{"id": 1, "name": "h", "kind": "length", "expression": "6 mm"}])["scope"]
        self.assertTrue(self.ed.commit_field("h * 3", scope))
        self.assertEqual(self.ed.record["extent"]["to"], 18)
        self.assertEqual(self.ed.record["exprs"], {"extent.to": "h * 3"})
        self.assertTrue(self.ed.commit_field("12"))
        self.assertNotIn("exprs", self.ed.record)
        self.ed.close_field()
        self.assertIsNone(self.ed.field_value())

    def test_reopened_saves_only_what_changed(self):
        self.p.run("reverse_feature_add", {"feature": {"kind": "extrude", "sketchId": 1, "extent": {"kind": "distance", "from": 0, "to": 10}, "op": "new"}})
        f = self.p.store.part()["features"][1]
        self.ed.open_edit(f)
        self.assertEqual(self.ed.create_label(), "Save changes")
        self.assertIsNone(self.ed.create())
        self.ed.grip_drag("extrudeTo", 0, "start")
        self.ed.grip_drag("extrudeTo", 5, "move")
        tool, args = self.ed.create()
        self.assertEqual((tool, args), ("reverse_feature_update", {"feature": 2, "set": {"extent": {"kind": "distance", "from": 0, "to": 15}}}))
        self.p.run(tool, args)
        self.assertEqual(self.p.volumes(), [1500])

    def test_listeners_hear_each_change(self):
        heard = []
        self.ed.listen(lambda e: heard.append(e.version))
        self.ed.open_new("extrude", self.p.store.part())
        self.ed.set_slot("extent.to", "11")
        self.ed.close()
        self.assertGreaterEqual(len(heard), 3)
        self.assertEqual(heard, sorted(heard))


class Ghost(unittest.TestCase):
    def setUp(self):
        self.p = Part()

    def test_a_new_extrude_s_ghost_leaves_the_part_as_it_was(self):
        rec = start_record("extrude", self.p.store.part())
        g = GH.dressed(GH.ghost(self.p.store, rec), rec, rec["id"])
        self.assertEqual(g["status"], "ok")
        self.assertEqual(round(g["volume"]), 1000)
        self.assertTrue(g["closed"])
        self.assertEqual(g["color"], D.body_color(2))
        self.assertEqual((g["replaces"], g["through"], g["solid"]), ([], False, False))
        self.assertTrue(g["mesh"]["indices"])
        self.assertEqual(self.p.volumes(), [])  # nothing built by the preview

    def test_a_reopened_feature_ghosts_on_the_part_before_it(self):
        self.p.run("reverse_feature_add", {"feature": {"kind": "extrude", "sketchId": 1, "extent": {"kind": "distance", "from": 0, "to": 10}, "op": "new"}})
        f = self.p.store.part()["features"][1]
        rec = {**f, "extent": {"kind": "distance", "from": 0, "to": 25}}
        g = GH.ghost(self.p.store, rec, editing=f["id"])
        self.assertEqual(round(g["volume"]), 2500)
        self.assertEqual(self.p.volumes(), [1000])

    def test_a_cut_is_red_and_drawn_through(self):
        rec = {**start_record("extrude", self.p.store.part()), "op": "cut"}
        g = GH.dressed({"status": "ok"}, rec, 2)
        self.assertEqual((g["color"], g["through"]), (GH.CUT_COLOR, True))

    def test_a_move_carries_the_bodies(self):
        self.p.run("reverse_feature_add", {"feature": {"kind": "extrude", "sketchId": 1, "extent": {"kind": "distance", "from": 0, "to": 10}, "op": "new"}})
        rec = {"id": 3, "kind": "moveBody", "name": "Move 1", "bodies": [2], "pivot": [5, 5, 5], "translate": [7, 0, 0], "rotate": [0, 0, 0], "copy": False}
        g = GH.dressed(GH.ghost(self.p.store, rec), rec, 3)
        self.assertEqual(g["status"], "ok")
        self.assertEqual(g["mesh"]["positions"][:3], [7, 0, 10])
        self.assertEqual(g["replaces"], [2])
        self.assertEqual(self.p.volumes(), [1000])

    def test_a_feature_that_cannot_build_says_why(self):
        rec = {**start_record("extrude", self.p.store.part()), "sketchId": 99}
        g = GH.ghost(self.p.store, rec)
        self.assertEqual(g["status"], "failed")
        self.assertTrue(g["message"])

    def test_replaced_bodies(self):
        self.assertEqual(GH.replaced_bodies({"kind": "fillet", "body": 4}), [4])
        self.assertEqual(GH.replaced_bodies({"kind": "moveFace", "body": 4}), [])
        self.assertEqual(GH.replaced_bodies({"kind": "boolean", "body": 4, "tool": [5, 6]}), [4, 5, 6])
        self.assertEqual(GH.replaced_bodies({"kind": "mirror", "body": 4, "join": False}), [])
        self.assertEqual(GH.replaced_bodies({"kind": "moveBody", "bodies": [1], "copy": True}), [])


class ThePage(unittest.TestCase):
    """The page's keys and fields open, fill and commit the shared box."""

    def setUp(self):
        self.p = Part()
        EDITOR.close()
        self.addCleanup(EDITOR.close)

    def test_key_box_fields_create(self):
        self.assertIsNone(RV.call_for("extrude", {}, env=self.p.env))
        self.assertEqual(EDITOR.record["kind"], "extrude")
        read = lambda t, a=None: (False, None)  # noqa: E731
        box = next(s for s in RV.build({}, read=read)["sections"] if s["id"] == RV.EDITOR_SECTION)
        self.assertEqual([f["label"] for f in box["fields"]], ["From", "To", "Taper"])
        self.assertEqual([k["label"] for k in box["keys"]], ["Create extrude", "Cancel"])
        RV.on_field(RV.EDITOR_SECTION, "extent.to", 30.0, env=self.p.env)
        self.assertEqual(EDITOR.record["extent"]["to"], 30)
        EDITOR.set_ghost({"status": "ok", "volume": 3000, "closed": True})
        self.assertTrue(RV.preview_line(EDITOR).startswith("Preview: 3000.0 mm³"))
        tool, args = RV.call_for("editor-create", {})
        got = {"ok": True, "answer": self.p.run(tool, args)}
        RV.after_press("editor-create", got)
        self.assertFalse(EDITOR.open)
        self.assertEqual(self.p.volumes(), [3000])

    def test_a_refused_create_keeps_the_box_open_saying_why(self):
        RV.call_for("fillet", {}, env=self.p.env)
        RV.after_press("editor-create", {"ok": False, "answer": {"error": {"message": "Pick the edges."}}})
        self.assertTrue(EDITOR.open)
        self.assertEqual(RV.preview_line(EDITOR), "⚠ Pick the edges.")

    def test_edit_from_the_list(self):
        self.p.run("reverse_feature_add", {"feature": {"kind": "extrude", "sketchId": 1, "extent": {"kind": "distance", "from": 0, "to": 10}, "op": "new"}})
        rows = {"features": [{"id": 1, "name": "Sketch 1", "kind": "sketch"}, {"id": 2, "name": "Extrude 1", "kind": "extrude"}]}
        m = RV.build({}, read=lambda t, a=None: (True, rows) if t == "reverse_feature_list" else (False, None))
        feats = next(s for s in m["sections"] if s["id"] == "features")
        self.assertEqual([o["label"] for o in feats["fields"][0]["options"]], ["—", "Extrude 1"])
        RV.on_field("features", RV.EDIT_FIELD, 2, env=self.p.env)
        self.assertEqual((EDITOR.mode, EDITOR.record["id"]), ("edit", 2))
        RV.call_for("editor-cancel", {})
        self.assertFalse(EDITOR.open)


if __name__ == "__main__":
    unittest.main()
