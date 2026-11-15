# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/tests/reSketchShapes.test.ts
# SPDX-License-Identifier: AGPL-3.0-only
#
# The sketch's shapes and relations through the solver: Equal, the regular
# polygon, the sketch pattern, and relations inferred on a sketch handed
# in as coordinates.
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from scanrulerfc.reverse.datums import datum_traces  # noqa: E402
from scanrulerfc.reverse.regions import find_regions  # noqa: E402
from scanrulerfc.reverse.sketch import (  # noqa: E402
    add_constraint, add_entity, add_polygon, add_rectangle, anchor_point, empty_sketch, entity_of, infer_relations, line_length,
    pattern_pieces, polygon_corners, relation_takes,
)
from scanrulerfc.reverse.solver import solve_sketch  # noqa: E402

TRACES = datum_traces({"origin": [0, 0, 0], "normal": [0, 0, 1], "basisU": [1, 0, 0], "basisV": [0, 1, 0]})


def close(tc, a, b, digits=6):
    tc.assertLess(abs(a - b), 10 ** -digits / 2, f"{a} vs {b}")


def near(tc, a, b, digits=6):
    close(tc, a[0], b[0], digits)
    close(tc, a[1], b[1], digits)


class Equal(unittest.TestCase):
    def test_takes(self):
        s = empty_sketch()
        l1 = add_entity(s, {"kind": "line", "a": [0, 0], "b": [10, 0]})
        l2 = add_entity(s, {"kind": "line", "a": [0, 5], "b": [4, 5]})
        c = add_entity(s, {"kind": "circle", "c": [20, 0], "r": 3})
        a = add_entity(s, {"kind": "arc", "c": [30, 0], "r": 2, "start": 0, "sweep": 1})
        e = lambda i: entity_of(s, i)  # noqa: E731
        self.assertTrue(relation_takes("equal", [e(l1), e(l2)]))
        self.assertTrue(relation_takes("equal", [e(c), e(a)]))
        self.assertFalse(relation_takes("equal", [e(l1), e(c)]))

    def test_one_dimension_drives_both(self):
        s = empty_sketch()
        l1 = add_entity(s, {"kind": "line", "a": [0, 0], "b": [10, 0]})
        l2 = add_entity(s, {"kind": "line", "a": [0, 5], "b": [4, 5]})
        c1 = add_entity(s, {"kind": "circle", "c": [20, 0], "r": 3})
        c2 = add_entity(s, {"kind": "circle", "c": [30, 0], "r": 1})
        add_constraint(s, {"kind": "equal", "a": l1, "b": l2})
        add_constraint(s, {"kind": "equal", "a": c1, "b": c2})
        add_constraint(s, {"kind": "length", "entity": l1, "value": 12})
        add_constraint(s, {"kind": "radius", "entity": c2, "value": 2.5})
        self.assertTrue(solve_sketch(s)["ok"])
        close(self, line_length(entity_of(s, l2)), 12, 5)
        close(self, entity_of(s, c1)["r"], 2.5, 5)


class Polygon(unittest.TestCase):
    def test_inscribed(self):
        corners = polygon_corners([0, 0], [10, 0], 6, "inscribed")
        self.assertEqual(len(corners), 6)
        near(self, corners[0], [10, 0])
        for c in corners:
            close(self, math.hypot(c[0], c[1]), 10, 9)

    def test_circumscribed(self):
        corners = polygon_corners([0, 0], [6.5, 0], 6, "circumscribed")
        self.assertEqual(len([c for c in corners if abs(c[0] - 6.5) < 1e-9]), 2)
        close(self, math.hypot(*corners[0]), 6.5 / math.cos(math.pi / 6), 9)

    def test_refuses(self):
        self.assertIsNone(polygon_corners([0, 0], [1, 0], 2, "inscribed"))
        self.assertIsNone(polygon_corners([0, 0], [0, 0], 6, "inscribed"))

    def test_regular_when_dimensioned(self):
        for fit in ("inscribed", "circumscribed"):
            s = empty_sketch()
            made = add_polygon(s, [3, 4], [9, 4], 6, fit)
            add_constraint(s, {"kind": "radius", "entity": made["circle"], "value": 8})
            self.assertTrue(solve_sketch(s)["ok"])
            want = 8 if fit == "inscribed" else (2 * 8) / math.sqrt(3)
            for i in made["lines"]:
                close(self, line_length(entity_of(s, i)), want, 4)
            self.assertEqual(len(find_regions(s)), 1)

    def test_fully_defined_nothing_twice(self):
        for fit in ("inscribed", "circumscribed"):
            for sides in (3, 5, 6, 8):
                s = empty_sketch()
                made = add_polygon(s, [0, 0], [5, 0], sides, fit)
                circle = made["circle"]
                add_constraint(s, {"kind": "pointOn", "p": {"entity": circle, "at": "center"}, "on": {"datum": "yz"}})
                add_constraint(s, {"kind": "pointOn", "p": {"entity": circle, "at": "center"}, "on": {"datum": "zx"}})
                add_constraint(s, {"kind": "radius", "entity": circle, "value": 5})
                loose = solve_sketch(s, datums=TRACES)
                self.assertTrue(loose["ok"])
                self.assertEqual(loose["redundant"], 0)
                self.assertGreater(len(loose["underConstrained"]), 0)
                add_constraint(s, {"kind": "pointOn", "p": {"entity": made["lines"][0], "at": "a"}, "on": {"datum": "zx"}})
                pinned = solve_sketch(s, datums=TRACES)
                self.assertTrue(pinned["ok"], f"{fit} {sides}")
                self.assertEqual(pinned["redundant"], 0, f"{fit} {sides}")
                self.assertEqual(pinned["underConstrained"], [], f"{fit} {sides}")


class Pattern(unittest.TestCase):
    def test_grid(self):
        s = empty_sketch()
        rect = add_rectangle(s, [0, 0], [4, 2])
        dim = add_constraint(s, {"kind": "length", "entity": rect[0], "value": 4, "expr": "w"})
        copies = pattern_pieces(s, rect, {"kind": "rectangular", "step": [10, 0], "count": 3, "step2": [0, 5], "count2": 2})
        self.assertEqual(len(copies), 5)
        self.assertEqual(len(s["entities"]), 24)
        for ids in copies:
            own = [c for c in s["constraints"] if (c["p"]["entity"] in ids if c["kind"] == "coincident" else ("entity" in c and c["entity"] in ids))]
            self.assertEqual(len([c for c in own if c["kind"] == "coincident"]), 4)
            self.assertEqual(len([c for c in own if c["kind"] in ("horizontal", "vertical")]), 4)
            length = next(c for c in own if c["kind"] == "length")
            self.assertEqual(length["expr"], "w")
            self.assertNotEqual(length["id"], dim)
        near(self, entity_of(s, copies[1][0])["a"], [20, 0])
        near(self, entity_of(s, copies[4][0])["a"], [20, 5])
        self.assertEqual(len(find_regions(s)), 6)
        self.assertTrue(solve_sketch(s)["ok"])

    def test_round_a_centre(self):
        s = empty_sketch()
        hole = add_entity(s, {"kind": "circle", "c": [10, 0], "r": 1.5})
        copies = pattern_pieces(s, [hole], {"kind": "circular", "centre": [0, 0], "count": 4, "angleDeg": 360})
        self.assertEqual(len(copies), 3)
        near(self, entity_of(s, copies[0][0])["c"], [0, 10])
        near(self, entity_of(s, copies[1][0])["c"], [-10, 0])
        t = empty_sketch()
        p = add_entity(t, {"kind": "point", "p": [5, 0]})
        opened = pattern_pieces(t, [p], {"kind": "circular", "centre": [0, 0], "count": 3, "angleDeg": 90})
        near(self, anchor_point(entity_of(t, opened[1][0]), "center"), [0, 5])

    def test_turned_rectangle_stays_square(self):
        s = empty_sketch()
        rect = add_rectangle(s, [20, 0], [30, 4])
        copies = pattern_pieces(s, rect, {"kind": "circular", "centre": [0, 0], "count": 4, "angleDeg": 360})
        turned = pattern_pieces(s, rect, {"kind": "circular", "centre": [0, 0], "count": 3, "angleDeg": 360})
        before = [[list(entity_of(s, i)["a"]) for i in ids] for ids in turned]
        report = solve_sketch(s)
        self.assertTrue(report["ok"])
        self.assertEqual(report["redundant"], 0)
        for k, ids in enumerate(turned):
            for i, eid in enumerate(ids):
                near(self, entity_of(s, eid)["a"], before[k][i])
        near(self, entity_of(s, turned[0][0])["a"], [20 * math.cos(2 * math.pi / 3), 20 * math.sin(2 * math.pi / 3)])
        for ids in turned:
            own = [c for c in s["constraints"] if ("entity" in c and c["entity"] in ids) or (isinstance(c.get("a"), int) and c["a"] in ids)]
            self.assertEqual(len([c for c in own if c["kind"] in ("horizontal", "vertical")]), 0)
            self.assertEqual(len([c for c in own if c["kind"] in ("parallel", "perpendicular")]), 3)
        quarter = copies[0]
        self.assertTrue(any(c["kind"] == "vertical" and c["entity"] == quarter[0] for c in s["constraints"]))
        self.assertTrue(any(c["kind"] == "horizontal" and c["entity"] == quarter[1] for c in s["constraints"]))
        sides = turned[1]
        ln = entity_of(s, sides[0])
        ln["a"] = [ln["a"][0] + 0.5, ln["a"][1] - 0.3]
        self.assertTrue(solve_sketch(s)["ok"])

        def direction(i):
            ln = entity_of(s, i)
            d = [ln["b"][0] - ln["a"][0], ln["b"][1] - ln["a"][1]]
            n = math.hypot(*d)
            return [d[0] / n, d[1] / n]

        for i in range(4):
            u, v = direction(sides[i]), direction(sides[(i + 1) % 4])
            close(self, u[0] * v[0] + u[1] * v[1], 0, 6)

    def test_ties_outside_stay_with_the_original(self):
        s = empty_sketch()
        other = add_entity(s, {"kind": "line", "a": [0, -5], "b": [10, -5]})
        bottom = add_rectangle(s, [0, 0], [4, 2])[0]
        add_constraint(s, {"kind": "distance", "p": {"entity": bottom, "at": "a"}, "q": {"datum": "yz"}, "value": 0})
        add_constraint(s, {"kind": "parallel", "a": bottom, "b": other})
        before = len(s["constraints"])
        pattern_pieces(s, [e["id"] for e in s["entities"] if e["id"] != other], {"kind": "rectangular", "step": [8, 0], "count": 2})
        self.assertEqual(len(s["constraints"]) - before, 8)


class Inferred(unittest.TestCase):
    def test_joins_and_levels_once(self):
        s = empty_sketch()
        pts = [[0, 0], [10, 0], [10, 6], [3, 9]]
        for i, p in enumerate(pts):
            add_entity(s, {"kind": "line", "a": p, "b": pts[(i + 1) % len(pts)]})
        self.assertEqual(infer_relations(s), 4 + 2)
        self.assertEqual(len([c for c in s["constraints"] if c["kind"] == "coincident"]), 4)
        self.assertEqual(len([c for c in s["constraints"] if c["kind"] == "horizontal"]), 1)
        self.assertEqual(len([c for c in s["constraints"] if c["kind"] == "vertical"]), 1)
        self.assertTrue(all(c.get("inferred") for c in s["constraints"]))
        self.assertEqual(infer_relations(s), 0)
        self.assertTrue(solve_sketch(s)["ok"])

    def test_chains_and_ends_apart(self):
        s = empty_sketch()
        a = add_entity(s, {"kind": "line", "a": [0, 0], "b": [5, 1]})
        b = add_entity(s, {"kind": "line", "a": [5, 1], "b": [9, 4]})
        c = add_entity(s, {"kind": "line", "a": [5, 1], "b": [1, 7]})
        add_constraint(s, {"kind": "coincident", "p": {"entity": a, "at": "b"}, "q": {"entity": b, "at": "a"}})
        add_constraint(s, {"kind": "coincident", "p": {"entity": b, "at": "a"}, "q": {"entity": c, "at": "a"}})
        add_entity(s, {"kind": "line", "a": [20, 0], "b": [20.01, 3]})
        self.assertEqual(infer_relations(s), 0)

    def test_only_pieces_named(self):
        s = empty_sketch()
        add_rectangle(s, [0, 0], [4, 4])
        loose = add_entity(s, {"kind": "line", "a": [4, 4], "b": [9, 4]})
        before = len(s["constraints"])
        self.assertEqual(infer_relations(s, {loose}), 2)
        self.assertEqual(len(s["constraints"]) - before, 2)


if __name__ == "__main__":
    unittest.main()
