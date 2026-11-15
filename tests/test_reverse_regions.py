# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/tests/reRegionMatch.test.ts, reRegionsOverlap.test.ts, reRegionsOnArc.test.ts
# SPDX-License-Identifier: AGPL-3.0-only
#
# The closed regions of a sketch: their stable keys and how a key is found
# again after an edit, outlines that run along one line, and lines ending
# on arcs. The case of reRegionMatch that runs pickedProfiles waits for
# profiles.ts (build order step 5, with resolve.py).
import json
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from scanrulerfc.reverse.regions import find_regions, loop_geometry, match_region, match_regions, parse_region_key, point_in_polygon  # noqa: E402
from scanrulerfc.reverse.sketch import add_entity, add_rectangle, clone_sketch, empty_sketch, entity_of  # noqa: E402


def close(tc, a, b, digits):
    tc.assertLess(abs(a - b), 10 ** -digits / 2, f"{a} vs {b}")


class RegionMatch(unittest.TestCase):
    def test_own_key_back(self):
        s = empty_sketch()
        add_rectangle(s, [0, 0], [20, 10])
        r = find_regions(s)[0]
        parsed = parse_region_key(r["key"])
        self.assertEqual(parsed["ids"], [1, 2, 3, 4])
        close(self, parsed["centroid"][0], 10, 1)
        close(self, parsed["centroid"][1], 5, 1)
        self.assertIsNone(parse_region_key("nonsense"))

    def test_corner_dragged(self):
        s = empty_sketch()
        ids = add_rectangle(s, [0, 0], [20, 10])
        key = find_regions(s)[0]["key"]
        edited = clone_sketch(s)
        entity_of(edited, ids[1])["b"] = [30, 18]
        entity_of(edited, ids[2])["a"] = [30, 18]
        now = find_regions(edited)
        self.assertEqual(len(now), 1)
        self.assertNotEqual(now[0]["key"], key)
        self.assertIs(match_region(key, now), now[0])

    def test_side_replaced(self):
        s = empty_sketch()
        ids = add_rectangle(s, [0, 0], [20, 10])
        key = find_regions(s)[0]["key"]
        edited = clone_sketch(s)
        edited["entities"] = [e for e in edited["entities"] if e["id"] != ids[2]]
        edited["constraints"] = [c for c in edited["constraints"] if f'"entity": {ids[2]}' not in json.dumps(c)]
        add_entity(edited, {"kind": "line", "a": [20, 10], "b": [0, 10]})
        now = find_regions(edited)
        self.assertEqual(len(now), 1)
        self.assertIs(match_region(key, now), now[0])

    def test_two_faces_apart(self):
        s = empty_sketch()
        add_rectangle(s, [0, 0], [20, 10])
        add_rectangle(s, [30, 0], [50, 10])
        a, b = find_regions(s)
        edited = clone_sketch(s)
        for e in edited["entities"]:
            if e["kind"] == "line":
                e["a"] = [e["a"][0] * 1.3, e["a"][1] * 1.3]
                e["b"] = [e["b"][0] * 1.3, e["b"][1] * 1.3]
        now = find_regions(edited)
        self.assertEqual(len(now), 2)
        ma = match_region(a["key"], now)
        mb = match_region(b["key"], now)
        self.assertIsNot(ma, mb)
        self.assertEqual(parse_region_key(ma["key"])["ids"], parse_region_key(a["key"])["ids"])
        self.assertEqual(parse_region_key(mb["key"])["ids"], parse_region_key(b["key"])["ids"])

    def test_given_up(self):
        s = empty_sketch()
        ids = add_rectangle(s, [0, 0], [20, 10])
        key = find_regions(s)[0]["key"]
        other = clone_sketch(s)
        other["entities"] = [e for e in other["entities"] if e["id"] == ids[0]]
        other["constraints"] = []
        add_entity(other, {"kind": "line", "a": [20, 0], "b": [20, -10]})
        add_entity(other, {"kind": "line", "a": [20, -10], "b": [0, -10]})
        add_entity(other, {"kind": "line", "a": [0, -10], "b": [0, 0]})
        self.assertEqual(len(find_regions(other)), 1)
        self.assertIsNone(match_region(key, find_regions(other)))
        self.assertEqual(len(match_regions([key, key], find_regions(s))), 1)

    @unittest.skip("pickedProfiles is profiles.ts: ported with resolve.py (build order step 5)")
    def test_extrude_keeps_profile(self):
        pass


def bracket_sketch():
    s = empty_sketch()
    y0 = 0.00108020343438141
    y1 = 0.0011037711701751174
    for a, b in (
        ([-48.5432687675767, y0], [46.50914663649533, y0]), ([46.50914663649533, y0], [46.50914663649533, 9.404793781024047]),
        ([46.50914663649533, 9.404793781024047], [-48.5432687675767, 9.404793781024047]), ([-48.5432687675767, 9.404793781024047], [-48.5432687675767, y0]),
        ([42.32181529337595, y1], [48.33926773071289, y1]), ([48.33926773071289, y1], [48.33926773071289, 14.157892227172852]),
        ([48.33926773071289, 14.157892227172852], [42.32181529337595, 14.157892227172852]), ([42.32181529337595, 14.157892227172852], [42.32181529337595, y1]),
    ):
        add_entity(s, {"kind": "line", "a": a, "b": b})
    return s


def shortest_side(poly):
    return min(math.hypot(poly[(i + 1) % len(poly)][0] - p[0], poly[(i + 1) % len(poly)][1] - p[1]) for i, p in enumerate(poly))


class Overlap(unittest.TestCase):
    def test_no_sliver(self):
        regions = find_regions(bracket_sketch())
        self.assertEqual(len(regions), 3)
        self.assertEqual(sorted(len(r["outer"]["polygon"]) for r in regions), [4, 4, 6])
        for r in regions:
            self.assertGreater(shortest_side(r["outer"]["polygon"]), 1)
            self.assertEqual(r["holes"], [])
        left = next(r for r in regions if point_in_polygon([0, 5], r["outer"]["polygon"]))
        self.assertEqual(parse_region_key(left["key"])["ids"], [1, 3, 4, 8])
        close(self, left["area"], (42.32181529337595 + 48.5432687675767) * (9.404793781024047 - 0.00108), 2)
        heights = [0.00108020343438141, 9.404793781024047, 14.157892227172852]
        for r in regions:
            for _x, y in r["outer"]["polygon"]:
                self.assertLess(min(abs(y - h) for h in heights), 1e-12)
        total = sum(r["area"] for r in regions)
        outline = (46.50914663649533 + 48.5432687675767) * (9.404793781024047 - 0.00108)
        lip_beside = (48.33926773071289 - 46.50914663649533) * (9.404793781024047 - 0.0011)
        lip_top = (48.33926773071289 - 42.32181529337595) * (14.157892227172852 - 9.404793781024047)
        close(self, total, outline + lip_beside + lip_top, 2)

    def test_t_junction_a_hair_short(self):
        s = empty_sketch()
        add_rectangle(s, [0, 0], [40, 20])
        add_entity(s, {"kind": "line", "a": [15, 0.00002], "b": [15, 20]})
        regions = find_regions(s)
        self.assertEqual(len(regions), 2)
        for r in regions:
            self.assertEqual(len(r["outer"]["polygon"]), 4)
            self.assertGreater(shortest_side(r["outer"]["polygon"]), 1)
        close(self, sum(r["area"] for r in regions), 800, 3)

    def test_shallow_bend_kept_apart(self):
        top = [[-1.7695086248876635, 17.867300506251173], [-1.8290865930367382, 17.891050578042854], [-1.917863, 17.897537],
               [-2.77935015, 17.784015953333334], [-3.2940009233333334, 17.69293251], [-3.579473376666667, 17.64042503],
               [-4.372297913333333, 17.460849323333335], [-5.156204446666666, 17.245654293333335], [-5.929595483333333, 16.99527904]]
        corners = top + [[-5.929595483333333, 10], [-1.7695086248876635, 10]]
        s = empty_sketch()
        for i, a in enumerate(corners):
            add_entity(s, {"kind": "line", "a": a, "b": corners[(i + 1) % len(corners)]})
        regions = find_regions(s)
        self.assertEqual(len(regions), 1)
        self.assertEqual(len(regions[0]["outer"]["polygon"]), len(corners))

    def test_sides_over_each_other_one(self):
        s = empty_sketch()
        add_rectangle(s, [0, 0], [20, 10])
        add_rectangle(s, [20, 0], [30, 10])
        regions = find_regions(s)
        self.assertEqual(len(regions), 2)
        self.assertEqual([len(r["outer"]["polygon"]) for r in regions], [4, 4])
        close(self, sum(r["area"] for r in regions), 300, 6)


C = [-40.93, 0]
INNER = 29.6
OUTER = 30.9
START = 0.9828407376470754
ON_INNER = [-63.21250768285582, -19.484605496736908]
ON_OUTER = [-63.01980355035507, -21.60672532122164]


def band(a, b):
    s = empty_sketch()
    sweep = 3.148278037503994
    inner = add_entity(s, {"kind": "arc", "c": C, "r": INNER, "start": START, "sweep": sweep, "fixed": True, "projected": True})
    outer = add_entity(s, {"kind": "arc", "c": C, "r": OUTER, "start": START, "sweep": sweep, "fixed": True, "projected": True})

    def at(r, t):
        return [C[0] + r * math.cos(t), C[1] + r * math.sin(t)]

    add_entity(s, {"kind": "line", "a": at(INNER, START), "b": at(OUTER, START)})
    add_entity(s, {"kind": "line", "a": at(INNER, START + sweep), "b": at(OUTER, START + sweep)})
    divider = add_entity(s, {"kind": "line", "a": a, "b": b})
    return s, inner, outer, divider


def corner_off(r, radii):
    worst = 0
    for p in r["outer"]["pieces"]:
        radius = radii.get(p["entity"])
        if radius is None:
            continue
        for q in (p["p0"], p["p1"]):
            worst = max(worst, abs(math.hypot(q[0] - C[0], q[1] - C[1]) - radius))
    return worst


class OnArc(unittest.TestCase):
    def test_splits_band_where_ends_lie(self):
        sketch, inner, outer, divider = band(ON_INNER, ON_OUTER)
        close(self, math.hypot(ON_INNER[0] - C[0], ON_INNER[1] - C[1]), INNER, 12)
        close(self, math.hypot(ON_OUTER[0] - C[0], ON_OUTER[1] - C[1]), OUTER, 12)
        regions = find_regions(sketch)
        self.assertEqual(len(regions), 2)
        radii = {inner: INNER, outer: OUTER}
        for r in regions:
            self.assertIn(divider, parse_region_key(r["key"])["ids"])
            self.assertLess(corner_off(r, radii), 1e-9)
        whole = find_regions(band([-80, 0], [-80, 0.5])[0])
        self.assertEqual(len(whole), 1)
        self.assertLess(abs(regions[0]["area"] + regions[1]["area"] - whole[0]["area"]), 0.05)

    def test_line_drawn_past(self):
        d = [ON_OUTER[0] - ON_INNER[0], ON_OUTER[1] - ON_INNER[1]]
        n = math.hypot(*d)
        u = [d[0] / n, d[1] / n]
        sketch, inner, outer, _ = band([ON_INNER[0] - u[0] * 0.5, ON_INNER[1] - u[1] * 0.5], [ON_OUTER[0] + u[0] * 0.5, ON_OUTER[1] + u[1] * 0.5])
        regions = find_regions(sketch)
        self.assertEqual(len(regions), 2)
        radii = {inner: INNER, outer: OUTER}
        for r in regions:
            self.assertLess(corner_off(r, radii), 1e-9)
            for piece in loop_geometry(r["outer"], sketch):
                if piece["kind"] != "arc":
                    continue
                rs = [math.hypot(q[0] - C[0], q[1] - C[1]) for q in (piece["a"], piece["m"], piece["b"])]
                radius = INNER if abs(rs[1] - INNER) < abs(rs[1] - OUTER) else OUTER
                for x in rs:
                    self.assertLess(abs(x - radius), 1e-9)

    def test_circle_split_off_sample(self):
        s = empty_sketch()
        circle = add_entity(s, {"kind": "circle", "c": [0, 0], "r": 25})
        t = 0.4321
        line = add_entity(s, {"kind": "line", "a": [25 * math.cos(t), 25 * math.sin(t)], "b": [-25 * math.cos(t), -25 * math.sin(t)]})
        regions = find_regions(s)
        self.assertEqual(len(regions), 2)
        for r in regions:
            self.assertEqual(parse_region_key(r["key"])["ids"], [circle, line])
            for p in r["outer"]["pieces"]:
                for q in (p["p0"], p["p1"]):
                    self.assertLess(abs(math.hypot(*q) - 25), 1e-9)
        close(self, regions[0]["area"], regions[1]["area"], 6)

    def test_tangent_arcs_crescent(self):
        s = empty_sketch()
        add_entity(s, {"kind": "arc", "c": [0, 0], "r": 30, "start": 0, "sweep": math.pi / 2})
        inner = add_entity(s, {"kind": "arc", "c": [2, 0], "r": 28, "start": 0, "sweep": 0.3})
        end = [2 + 28 * math.cos(0.3), 28 * math.sin(0.3)]
        k = 30 / math.hypot(*end)
        add_entity(s, {"kind": "line", "a": end, "b": [end[0] * k, end[1] * k]})
        add_entity(s, {"kind": "line", "a": [0, 30], "b": [0, 0]})
        add_entity(s, {"kind": "line", "a": [0, 0], "b": [30, 0]})
        regions = find_regions(s)
        self.assertEqual(len(regions), 2)
        crescent = regions[1]
        self.assertIn(inner, parse_region_key(crescent["key"])["ids"])
        self.assertGreater(crescent["area"], 0.1)
        self.assertLess(crescent["area"], 0.5)


if __name__ == "__main__":
    unittest.main()
