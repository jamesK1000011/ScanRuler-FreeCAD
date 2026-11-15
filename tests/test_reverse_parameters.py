# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/tests/reParameters.test.ts
# SPDX-License-Identifier: AGPL-3.0-only
#
# The parameter table and the slots the features read it through: the
# table evaluated in dependency order with its refusals, every slot's
# reading and writing, the expressions written through to features and
# sketches, and a parameter renamed wherever it is read.
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from scanrulerfc.reverse.parameters import (  # noqa: E402
    apply_parameters, apply_sketch_expressions, apply_slots, evaluate_parameters, feature_expression_errors, name_problem,
    rename_in_feature, rename_in_parameters, replace_sketch, slot_at, slots_of, unlink_slot, users_of, with_slot,
)
from scanrulerfc.reverse.sketch import add_constraint, add_entity, add_rectangle, empty_sketch, is_dimension, line_length  # noqa: E402

XY = {"origin": [0, 0, 0], "normal": [0, 0, 1], "basisU": [1, 0, 0], "basisV": [0, 1, 0]}


def param(i, name, expression, kind="length"):
    return {"id": i, "name": name, "kind": kind, "expression": expression}


def none(_n):
    return None


def square(size):
    sketch = empty_sketch()
    ids = add_rectangle(sketch, [0, 0], [size, size])
    origin = add_entity(sketch, {"kind": "point", "p": [0, 0], "fixed": True})
    add_constraint(sketch, {"kind": "coincident", "p": {"entity": ids[0], "at": "a"}, "q": {"entity": origin, "at": "center"}})
    width = add_constraint(sketch, {"kind": "length", "entity": ids[0], "value": size, "expr": "width"})
    add_constraint(sketch, {"kind": "length", "entity": ids[1], "value": size})
    return sketch, width


def sketch_feature(sketch):
    return {"id": 1, "kind": "sketch", "name": "Sketch 1", "plane": {"kind": "world", "axis": "z", "offset": 0}, "frame": XY, "sketch": sketch, "visible": True}


EXTRUDE = {"id": 2, "kind": "extrude", "name": "Extrude 1", "sketchId": 1, "regions": ["r:1"], "extent": {"kind": "distance", "from": 0, "to": 10}, "draftDeg": 0, "op": "new", "visible": True}


class Table(unittest.TestCase):
    def test_dependency_order(self):
        t = evaluate_parameters([param(1, "total", "width + height"), param(2, "width", "40"), param(3, "height", "width / 2")])
        self.assertEqual([[r["name"], r["value"], r["error"]] for r in t["readings"]], [["total", 60, None], ["width", 40, None], ["height", 20, None]])
        self.assertEqual(t["scope"]("total"), {"value": 60, "dim": {"mm": 1, "deg": 0}})
        self.assertIsNone(t["scope"]("nothing"))

    def test_kinds(self):
        t = evaluate_parameters([param(1, "turn", "30", "angle"), param(2, "count", "6", "integer"), param(3, "ratio", "0.5", "number"), param(4, "bad", "turn + 2 mm", "angle"), param(5, "worse", "count", "length")])
        self.assertEqual([t["readings"][i]["value"] for i in range(3)], [30, 6, 0.5])
        self.assertEqual((t["readings"][3]["value"], t["readings"][3]["error"]), (None, "an angle and a length cannot be added"))
        self.assertIsNone(t["readings"][4]["value"])
        self.assertIn("comes out as a number; a length is wanted", t["readings"][4]["error"])

    def test_whole(self):
        t = evaluate_parameters([param(1, "holes", "7.3", "integer"), param(2, "teeth", "round(7.3)", "integer")])
        self.assertIn("not whole", t["readings"][0]["error"])
        self.assertEqual(t["readings"][1]["value"], 7)

    def test_loop(self):
        t = evaluate_parameters([param(1, "a", "b + 1"), param(2, "b", "c * 2"), param(3, "c", "a"), param(4, "d", "a + 5"), param(5, "f", "3")])
        for r in t["readings"][:3]:
            self.assertIsNone(r["value"])
            self.assertIn("goes round in a loop", r["error"])
        self.assertIsNone(t["readings"][3]["value"])
        self.assertIn("“a” has no value", t["readings"][3]["error"])
        self.assertEqual(t["readings"][4]["value"], 3)
        self.assertEqual(t["scope"]("a"), {"error": "“a” has no value"})

    def test_names(self):
        others = [param(1, "width", "1"), param(2, "Height", "2")]
        self.assertEqual(name_problem("", others), "needs a name")
        self.assertIn("a word the expressions keep", name_problem("sin", others))
        self.assertIn("a letter or an underscore", name_problem("2wide", others))
        self.assertIn("already", name_problem("width", others))
        self.assertIsNone(name_problem("width", others, 1))
        self.assertIn("case alone", name_problem("height", others))
        self.assertIsNone(name_problem("depth", others))
        t = evaluate_parameters([param(1, "w", "1"), param(2, "w", "2"), param(3, "mm", "3")])
        self.assertIn("already", t["readings"][1]["error"])
        self.assertIn("keep", t["readings"][2]["error"])


class Slots(unittest.TestCase):
    def test_extrude(self):
        ex = EXTRUDE
        self.assertEqual([s["path"] for s in slots_of(ex)], ["extent.from", "extent.to", "taper"])
        to = slot_at(ex, "extent.to")
        self.assertEqual(to["get"](ex), 10)
        self.assertEqual(to["set"](ex, 25)["extent"], {"kind": "distance", "from": 0, "to": 25})
        taper = slot_at(ex, "taper")
        self.assertEqual(taper["get"]({**ex, "draftDeg": -5}), 5)
        self.assertEqual(taper["set"](ex, 5)["draftDeg"], -5)
        self.assertEqual(taper["set"](ex, 0)["draftDeg"], 0)
        self.assertEqual([s["path"] for s in slots_of({**ex, "extent": {"kind": "symmetric", "total": 8}})], ["extent.total", "taper"])
        self.assertEqual([s["path"] for s in slots_of({**ex, "extent": {"kind": "toNext", "from": 2}})], ["extent.from", "taper"])
        between = {"kind": "betweenPlanes", "a": {"kind": "world", "axis": "z", "offset": 0}, "b": {"kind": "world", "axis": "z", "offset": 5}}
        self.assertEqual([s["path"] for s in slots_of({**ex, "extent": between})], ["taper"])

    def test_others(self):
        hole = {"id": 3, "kind": "hole", "name": "Hole 1", "body": 2, "axis": {"kind": "element", "id": 1}, "radius": 3, "depth": None, "visible": True}
        self.assertEqual([s["path"] for s in slots_of(hole)], ["diameter"])
        self.assertEqual(slot_at(hole, "diameter")["get"](hole), 6)
        self.assertEqual(slot_at(hole, "diameter")["set"](hole, 10)["radius"], 5)
        self.assertEqual([s["path"] for s in slots_of({**hole, "depth": 4})], ["diameter", "depth"])
        revolve = {"id": 4, "kind": "revolve", "name": "Revolve 1", "sketchId": 1, "regions": [], "axis": {"kind": "world", "axis": "z"}, "angleDeg": 180, "op": "new", "visible": True}
        self.assertEqual([s["path"] for s in slots_of(revolve)], ["angleDeg"])
        self.assertEqual(slot_at(revolve, "angleDeg")["set"](revolve, 720)["angleDeg"], 360)
        coil = {**revolve, "pitch": 2, "angleDeg": 720}
        self.assertEqual([s["path"] for s in slots_of(coil)], ["angleDeg", "pitch", "turns", "height"])
        self.assertEqual(slot_at(coil, "turns")["get"](coil), 2)
        self.assertEqual(slot_at(coil, "turns")["set"](coil, 3)["angleDeg"], 1080)
        self.assertEqual(slot_at(coil, "height")["get"](coil), 4)
        self.assertEqual(slot_at(coil, "height")["set"](coil, 10)["angleDeg"], 1800)
        pattern = {"id": 5, "kind": "pattern", "name": "Pattern 1", "body": 2, "mode": "circular", "axis": {"kind": "world", "axis": "z"}, "count": 4, "step": 360, "visible": True}
        self.assertEqual([[s["path"], s["kind"]] for s in slots_of(pattern)], [["count", "integer"], ["step", "angle"]])
        self.assertEqual(slot_at(pattern, "count")["set"](pattern, 7.3)["count"], 7)
        self.assertEqual(slot_at(pattern, "count")["set"](pattern, 1)["count"], 2)
        self.assertEqual([[s["path"], s["kind"]] for s in slots_of({**pattern, "mode": "linear"})], [["count", "integer"], ["step", "length"]])
        split = {"id": 6, "kind": "split", "name": "Split 1", "body": 2, "tools": [], "keep": "scan", "tolerance": 0.3, "overlap": 0.5, "visible": True}
        self.assertEqual(slot_at(split, "overlap")["get"](split), 50)
        self.assertEqual(slot_at(split, "overlap")["set"](split, 80)["overlap"], 0.8)
        shell = {"id": 7, "kind": "shell", "name": "Shell 1", "body": 2, "faces": [], "thickness": 2, "visible": True}
        self.assertEqual(slot_at(shell, "thickness")["set"](shell, -3)["thickness"], 3)
        sketch = sketch_feature(empty_sketch())
        self.assertEqual([x["path"] for x in slots_of(sketch)], ["offset"])
        lifted = slot_at(sketch, "offset")["set"](sketch, 7)
        self.assertEqual((lifted["plane"]["kind"], lifted["plane"]["offset"]), ("world", 7))
        self.assertEqual(lifted["frame"]["origin"], [0, 0, 7])
        self.assertEqual(slots_of({**sketch, "plane": {"kind": "fitted", "frame": XY}}), [])

    def test_write_through_and_let_go(self):
        scope = evaluate_parameters([param(1, "height", "20")])["scope"]
        bound = with_slot(EXTRUDE, "extent.to", 25, "height + 5")
        self.assertEqual((bound["extent"]["to"], bound["exprs"]), (25, {"extent.to": "height + 5"}))
        r = apply_slots(bound, evaluate_parameters([param(1, "height", "30")])["scope"])
        self.assertEqual(r["errors"], {})
        self.assertEqual(r["next"]["extent"]["to"], 35)
        self.assertIs(apply_slots(bound, scope)["next"], bound)
        typed = with_slot(bound, "extent.to", 12, None)
        self.assertEqual(typed["extent"]["to"], 12)
        self.assertNotIn("exprs", typed)
        self.assertNotIn("exprs", unlink_slot(bound, "extent.to"))
        self.assertIs(unlink_slot(EXTRUDE, "extent.to"), EXTRUDE)

    def test_unreadable_and_dropped(self):
        bound = with_slot(EXTRUDE, "extent.to", 25, "height + 5")
        r = apply_slots(bound, none)
        self.assertIs(r["next"], bound)
        self.assertEqual(r["errors"], {"extent.to": "there is no parameter “height”"})
        self.assertEqual(feature_expression_errors(bound, none), {"extent.to": "there is no parameter “height”"})
        stale = {**bound, "extent": {"kind": "symmetric", "total": 8}, "exprs": {"extent.to": "height", "taper": "2"}}
        dropped = apply_slots(stale, evaluate_parameters([param(1, "height", "20")])["scope"])
        self.assertEqual(dropped["next"]["exprs"], {"taper": "2"})
        self.assertEqual(dropped["next"]["draftDeg"], -2)


class Sketches(unittest.TestCase):
    def test_dimension_solved_again(self):
        sketch, _w = square(10)
        scope = evaluate_parameters([param(1, "width", "30")])["scope"]
        r = apply_sketch_expressions(sketch, XY, scope)
        self.assertEqual(r["errors"], {})
        self.assertIsNot(r["next"], sketch)
        self.assertAlmostEqual(line_length(r["next"]["entities"][0]), 30, 6)
        self.assertAlmostEqual(line_length(sketch["entities"][0]), 10, 6)
        self.assertEqual(next(c for c in r["next"]["constraints"] if is_dimension(c) and c.get("expr") == "width")["value"], 30)
        self.assertIs(apply_sketch_expressions(r["next"], XY, scope)["next"], r["next"])

    def test_unreadable_dimension(self):
        sketch, width = square(10)
        r = apply_sketch_expressions(sketch, XY, none)
        self.assertIs(r["next"], sketch)
        self.assertEqual(r["errors"], {f"dim:{width}": "there is no parameter “width”"})

    def test_features_keep_regions(self):
        sketch, width = square(10)
        features = [
            sketch_feature(sketch),
            {"id": 2, "kind": "extrude", "name": "Extrude 1", "sketchId": 1, "regions": ["r:1"], "extent": {"kind": "distance", "from": 0, "to": 10}, "op": "new", "visible": True, "exprs": {"extent.to": "width / 2"}},
            {"id": 3, "kind": "fillet", "name": "Fillet 1", "body": 2, "edges": [], "radius": 1, "chain": True, "visible": True},
        ]
        wide = evaluate_parameters([param(1, "width", "30")])["scope"]
        r = apply_parameters(features, wide)
        self.assertTrue(r["changed"])
        self.assertEqual(len(r["errors"]), 0)
        self.assertIsNot(r["features"][0]["sketch"], sketch)
        self.assertEqual(r["features"][1]["extent"]["to"], 15)
        self.assertEqual(len(r["features"][1]["regions"]), 1)
        self.assertIs(r["features"][2], features[2])
        again = apply_parameters(r["features"], wide)
        self.assertFalse(again["changed"])
        self.assertIs(again["features"][0], r["features"][0])
        self.assertIs(again["features"][1], r["features"][1])
        broken = apply_parameters(r["features"], evaluate_parameters([param(1, "width", "nothing")])["scope"])
        self.assertFalse(broken["changed"])
        self.assertIn("“width” has no value", broken["errors"][1][f"dim:{width}"])
        self.assertIn("“width” has no value", broken["errors"][2]["extent.to"])

    def test_replace_and_rekey(self):
        sketch, _w = square(10)
        features = [sketch_feature(sketch), {"id": 2, "kind": "extrude", "name": "Extrude 1", "sketchId": 1, "regions": ["r:nothing"], "extent": {"kind": "distance", "from": 0, "to": 10}, "op": "new", "visible": True}]
        other = square(20)[0]
        nxt = replace_sketch(features, 1, other, {"name": "Renamed"})
        self.assertEqual(nxt[0]["name"], "Renamed")
        self.assertIs(nxt[0]["sketch"], other)
        self.assertEqual(nxt[1]["regions"], ["r:nothing"])


class Users(unittest.TestCase):
    def setUp(self):
        sketch, _w = square(10)
        self.parameters = [param(1, "width", "40"), param(2, "height", "width / 2"), param(3, "depth", "5")]
        self.features = [sketch_feature(sketch), {"id": 2, "kind": "extrude", "name": "Extrude 1", "sketchId": 1, "regions": [], "extent": {"kind": "distance", "from": 0, "to": 10}, "op": "new", "visible": True, "exprs": {"extent.to": "height + 1"}}]

    def test_lists(self):
        self.assertEqual(users_of("width", self.parameters, self.features), [{"kind": "parameter", "id": 2, "name": "height"}, {"kind": "feature", "id": 1, "name": "Sketch 1"}])
        self.assertEqual(users_of("height", self.parameters, self.features), [{"kind": "feature", "id": 2, "name": "Extrude 1"}])
        self.assertEqual(users_of("depth", self.parameters, self.features), [])

    def test_renames_everywhere(self):
        renamed = rename_in_parameters(self.parameters, 1, "w")
        self.assertEqual([[p["name"], p["expression"]] for p in renamed], [["w", "40"], ["height", "w / 2"], ["depth", "5"]])
        s = rename_in_feature(self.features[0], "width", "w")
        self.assertEqual(next(c for c in s["sketch"]["constraints"] if is_dimension(c) and c.get("expr"))["expr"], "w")
        self.assertIs(rename_in_feature(self.features[1], "width", "w"), self.features[1])
        self.assertEqual(rename_in_feature(self.features[1], "height", "h")["exprs"], {"extent.to": "h + 1"})


if __name__ == "__main__":
    unittest.main()
