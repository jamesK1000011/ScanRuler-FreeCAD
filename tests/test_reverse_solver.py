# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/tests/reSketch.test.ts
# SPDX-License-Identifier: AGPL-3.0-only
#
# The sketch solver: inferred axis relations, typed dimensions met and
# fights reported, slice points held while a relation pulls, a drag let go
# with nothing left unmet, coincidence with pieces and with the coordinate
# planes' lines, what is still loose; and regions with holes and crossing
# lines. The original's cases on segmenting a slice chain belong to
# chainsegment.py's own tests; those on corners wait for corners.ts.
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from scanrulerfc.linalg import mulberry32  # noqa: E402
from scanrulerfc.reverse.datums import datum_traces  # noqa: E402
from scanrulerfc.reverse.regions import find_regions, loop_geometry, region_at  # noqa: E402
from scanrulerfc.reverse.sketch import add_constraint, add_entity, add_rectangle, anchor_point, axis_relation_of, empty_sketch, entity_of, line_length  # noqa: E402
from scanrulerfc.reverse.solver import measure_dimension, solve_sketch  # noqa: E402

TRACES = datum_traces({"origin": [0, 0, 0], "normal": [0, 0, 1], "basisU": [1, 0, 0], "basisV": [0, 1, 0]})


def gaussian(rand):
    u = 0
    while u == 0:
        u = rand()
    return math.sqrt(-2 * math.log(u)) * math.cos(2 * math.pi * rand())


def close(tc, a, b, digits=2):
    tc.assertLess(abs(a - b), 10 ** -digits / 2, f"{a} vs {b}")


class AxisRelations(unittest.TestCase):
    def test_within_three_degrees(self):
        self.assertEqual(axis_relation_of([0, 0], [10, 0]), "horizontal")
        self.assertEqual(axis_relation_of([0, 0], [10, 0.5]), "horizontal")
        self.assertEqual(axis_relation_of([0, 0], [-10, 0.4]), "horizontal")
        self.assertEqual(axis_relation_of([0, 0], [0.3, 10]), "vertical")
        self.assertEqual(axis_relation_of([5, 5], [5, -5]), "vertical")

    def test_further_off_none(self):
        self.assertIsNone(axis_relation_of([0, 0], [10, 0.6]))
        self.assertIsNone(axis_relation_of([0, 0], [10, math.tan(5 * math.pi / 180) * 10]))
        self.assertIsNone(axis_relation_of([0, 0], [10, 10]))
        self.assertIsNone(axis_relation_of([1, 1], [1, 1]))

    def test_rectangle_marked_inferred(self):
        s = empty_sketch()
        add_rectangle(s, [0, 0], [10, 5])
        axes = [c for c in s["constraints"] if c["kind"] in ("horizontal", "vertical")]
        self.assertEqual(len(axes), 4)
        self.assertTrue(all(c.get("inferred") for c in axes))


class Solver(unittest.TestCase):
    def test_typed_lengths_kept_square(self):
        s = empty_sketch()
        bottom, right = add_rectangle(s, [0, 0], [30, 17])[:2]
        add_constraint(s, {"kind": "length", "entity": bottom, "value": 40})
        add_constraint(s, {"kind": "length", "entity": right, "value": 25})
        report = solve_sketch(s)
        self.assertTrue(report["ok"])
        self.assertEqual(report["unmet"], [])
        self.assertEqual(report["redundant"], 0)
        close(self, line_length(entity_of(s, bottom)), 40, 5)
        close(self, line_length(entity_of(s, right)), 25, 5)
        b, rgt = entity_of(s, bottom), entity_of(s, right)
        close(self, b["b"][0], rgt["a"][0], 6)
        close(self, b["b"][1], rgt["a"][1], 6)
        self.assertLess(abs(b["b"][1] - b["a"][1]), 1e-6)
        self.assertLess(abs(rgt["b"][0] - rgt["a"][0]), 1e-6)

    def test_fight_reported(self):
        s = empty_sketch()
        ids = add_rectangle(s, [0, 0], [30, 17])
        add_constraint(s, {"kind": "length", "entity": ids[0], "value": 40})
        clash = add_constraint(s, {"kind": "length", "entity": ids[2], "value": 50})
        report = solve_sketch(s)
        self.assertFalse(report["ok"])
        self.assertIn(clash, [u["id"] for u in report["unmet"]])
        self.assertGreater(report["unmet"][0]["residual"], 1)

    def test_redundant(self):
        s = empty_sketch()
        bottom = add_rectangle(s, [0, 0], [30, 17])[0]
        add_constraint(s, {"kind": "horizontal", "entity": bottom})
        report = solve_sketch(s)
        self.assertTrue(report["ok"])
        self.assertGreaterEqual(report["redundant"], 1)

    def test_fitted_line_kept_on_points(self):
        s = empty_sketch()
        rand = mulberry32(5)
        points = [[i * 0.5, 10 + gaussian(rand) * 0.02] for i in range(60)]
        fitted = add_entity(s, {"kind": "line", "a": [0, 10.3], "b": [29.5, 9.8], "points": points, "scatter": 0.02})
        post = add_entity(s, {"kind": "line", "a": [40, 0], "b": [40, 20]})
        add_constraint(s, {"kind": "coincident", "p": {"entity": fitted, "at": "b"}, "q": {"entity": post, "at": "a"}})
        report = solve_sketch(s)
        self.assertTrue(report["ok"])
        ln = entity_of(s, fitted)
        close(self, ln["a"][1], 10, 1)
        close(self, ln["b"][1], 10, 1)
        close(self, ln["b"][0], entity_of(s, post)["a"][0], 6)
        close(self, ln["b"][1], entity_of(s, post)["a"][1], 6)
        self.assertLess(report["softRms"], 0.03)

    def test_drag_let_go_meets_everything(self):
        def build():
            s = empty_sketch()
            bottom, right, top, left = add_rectangle(s, [0, 0], [30, 20])
            add_constraint(s, {"kind": "horizontal", "entity": bottom})
            add_constraint(s, {"kind": "vertical", "entity": right})
            add_constraint(s, {"kind": "horizontal", "entity": top})
            add_constraint(s, {"kind": "vertical", "entity": left})
            add_constraint(s, {"kind": "pointOn", "p": {"entity": left, "at": "a"}, "on": {"datum": "yz"}})
            return s, top, left

        s, _top, left = build()
        ln = entity_of(s, left)
        s["entities"] = [{**ln, "a": [60, ln["a"][1]], "b": [60, ln["b"][1]]} if e["id"] == left else e for e in s["entities"]]
        pulls = [{"anchor": {"entity": left, "at": at}, "to": anchor_point(entity_of(s, left), at)} for at in ("a", "b")]
        for quick in (True, False):
            report = solve_sketch(s, pull=pulls, quick=quick, datums=TRACES)
            self.assertEqual(report["unmet"], [])
            self.assertLess(abs(entity_of(s, left)["a"][0]), 1e-6)
        s, top, _left = build()
        t = entity_of(s, top)
        to = [t["b"][0] - 60, t["b"][1] + 60]
        s["entities"] = [{**t, "b": to} if e["id"] == top else e for e in s["entities"]]
        report = solve_sketch(s, pull=[{"anchor": {"entity": top, "at": "b"}, "to": to}], datums=TRACES)
        self.assertEqual(report["unmet"], [])
        close(self, entity_of(s, top)["b"][0], 0, 6)
        close(self, entity_of(s, top)["b"][1], 80, 3)

    def test_tangent_and_radius(self):
        s = empty_sketch()
        ln = add_entity(s, {"kind": "line", "a": [0, 0], "b": [20, 0.4]})
        a = add_entity(s, {"kind": "arc", "c": [25, 5], "r": 4.7, "start": -math.pi / 2, "sweep": math.pi / 2})
        add_constraint(s, {"kind": "coincident", "p": {"entity": ln, "at": "b"}, "q": {"entity": a, "at": "a"}})
        add_constraint(s, {"kind": "tangent", "a": ln, "b": a})
        add_constraint(s, {"kind": "radius", "entity": a, "value": 5})
        add_constraint(s, {"kind": "horizontal", "entity": ln})
        self.assertTrue(solve_sketch(s)["ok"])
        ar = entity_of(s, a)
        close(self, ar["r"], 5, 4)
        close(self, ar["c"][1] - entity_of(s, ln)["a"][1], 5, 4)
        close(self, anchor_point(ar, "a")[0], entity_of(s, ln)["b"][0], 4)

    def test_diameter(self):
        s = empty_sketch()
        c = add_entity(s, {"kind": "circle", "c": [3, 4], "r": 4.6})
        add_constraint(s, {"kind": "diameter", "entity": c, "value": 10})
        self.assertTrue(solve_sketch(s)["ok"])
        circle = entity_of(s, c)
        close(self, circle["r"], 5, 6)
        close(self, measure_dimension(s, "diameter", circle), 10, 6)


class Coincidence(unittest.TestCase):
    def test_point_on_line_rim_and_plane(self):
        s = empty_sketch()
        base = add_entity(s, {"kind": "line", "a": [0, 0], "b": [40, 0], "fixed": True})
        ring = add_entity(s, {"kind": "circle", "c": [60, 0], "r": 5, "fixed": True})
        pt = add_entity(s, {"kind": "point", "p": [12, 3]})
        add_constraint(s, {"kind": "pointOn", "p": {"entity": pt, "at": "center"}, "on": {"line": base}})
        self.assertTrue(solve_sketch(s)["ok"])
        close(self, entity_of(s, pt)["p"][1], 0, 6)
        on_rim = add_entity(s, {"kind": "point", "p": [66, 1]})
        add_constraint(s, {"kind": "pointOn", "p": {"entity": on_rim, "at": "center"}, "on": {"curve": ring}})
        self.assertTrue(solve_sketch(s)["ok"])
        q = entity_of(s, on_rim)["p"]
        close(self, math.hypot(q[0] - 60, q[1]), 5, 5)
        on_axis = add_entity(s, {"kind": "line", "a": [3, 10], "b": [3, 30]})
        add_constraint(s, {"kind": "pointOn", "p": {"entity": on_axis, "at": "a"}, "on": {"datum": "yz"}})
        self.assertTrue(solve_sketch(s, datums=TRACES)["ok"])
        close(self, entity_of(s, on_axis)["a"][0], 0, 6)

    def test_collinear(self):
        s = empty_sketch()
        base = add_entity(s, {"kind": "line", "a": [0, 5], "b": [40, 5], "fixed": True})
        loose = add_entity(s, {"kind": "line", "a": [50, 7], "b": [70, 9]})
        add_constraint(s, {"kind": "collinear", "line": loose, "on": {"line": base}})
        self.assertTrue(solve_sketch(s)["ok"])
        close(self, entity_of(s, loose)["a"][1], 5, 6)
        close(self, entity_of(s, loose)["b"][1], 5, 6)
        upright = add_entity(s, {"kind": "line", "a": [2, 10], "b": [3, 30]})
        add_constraint(s, {"kind": "collinear", "line": upright, "on": {"datum": "yz"}})
        self.assertTrue(solve_sketch(s, datums=TRACES)["ok"])
        close(self, entity_of(s, upright)["a"][0], 0, 6)
        close(self, entity_of(s, upright)["b"][0], 0, 6)

    def test_loose_pieces(self):
        s = empty_sketch()
        ids = add_rectangle(s, [2, 3], [32, 20])
        bottom, right = ids[0], ids[1]
        self.assertEqual(sorted(solve_sketch(s, datums=TRACES)["underConstrained"]), sorted(ids))
        add_constraint(s, {"kind": "pointOn", "p": {"entity": bottom, "at": "a"}, "on": {"datum": "yz"}})
        add_constraint(s, {"kind": "pointOn", "p": {"entity": bottom, "at": "a"}, "on": {"datum": "zx"}})
        self.assertEqual(len(solve_sketch(s, datums=TRACES)["underConstrained"]), 4)
        add_constraint(s, {"kind": "length", "entity": bottom, "value": 30})
        add_constraint(s, {"kind": "length", "entity": right, "value": 17})
        pinned = solve_sketch(s, datums=TRACES)
        self.assertTrue(pinned["ok"])
        self.assertEqual(pinned["underConstrained"], [])
        t = empty_sketch()
        fitted = add_entity(t, {"kind": "line", "a": [0, 0], "b": [10, 0], "points": [[0, 0], [5, 0], [10, 0]], "scatter": 0.05})
        hung = add_entity(t, {"kind": "line", "a": [10, 0], "b": [10, 8]})
        add_constraint(t, {"kind": "coincident", "p": {"entity": hung, "at": "a"}, "q": {"entity": fitted, "at": "b"}})
        self.assertEqual(solve_sketch(t)["underConstrained"], [hung])
        add_constraint(t, {"kind": "vertical", "entity": hung})
        add_constraint(t, {"kind": "length", "entity": hung, "value": 8})
        self.assertEqual(solve_sketch(t)["underConstrained"], [])


class Regions(unittest.TestCase):
    def test_rectangle_with_hole(self):
        s = empty_sketch()
        add_rectangle(s, [0, 0], [40, 20])
        add_entity(s, {"kind": "circle", "c": [20, 10], "r": 4})
        regions = find_regions(s)
        self.assertEqual(len(regions), 2)
        outer, inner = regions
        self.assertEqual(len(outer["holes"]), 1)
        close(self, outer["area"], 800 - math.pi * 16, 0)
        self.assertEqual(len(inner["holes"]), 0)
        close(self, inner["area"], math.pi * 16, 0)
        self.assertIs(region_at(regions, [5, 5]), outer)
        self.assertIs(region_at(regions, [20, 10]), inner)
        self.assertIsNone(region_at(regions, [60, 5]))
        self.assertEqual([g["kind"] for g in loop_geometry(outer["outer"], s)], ["line"] * 4)
        self.assertEqual(loop_geometry(outer["holes"][0], s), [{"kind": "circle", "c": [20, 10], "r": 4}])

    def test_crossing_and_dangling(self):
        s = empty_sketch()
        add_rectangle(s, [0, 0], [40, 20])
        add_entity(s, {"kind": "line", "a": [-5, 10], "b": [45, 10]})
        add_entity(s, {"kind": "line", "a": [10, 12], "b": [15, 15]})
        regions = find_regions(s)
        self.assertEqual(len(regions), 2)
        close(self, regions[0]["area"], 400, 5)
        close(self, regions[1]["area"], 400, 5)
        lower = region_at(regions, [20, 5])
        self.assertEqual(len(lower["outer"]["pieces"]), 4)
        across = [g for g in loop_geometry(lower["outer"], s) if g["kind"] == "line" and abs(g["a"][1] - 10) < 1e-9 and abs(g["b"][1] - 10) < 1e-9]
        self.assertEqual(len(across), 1)
        close(self, min(across[0]["a"][0], across[0]["b"][0]), 0, 6)
        close(self, max(across[0]["a"][0], across[0]["b"][0]), 40, 6)


if __name__ == "__main__":
    unittest.main()
