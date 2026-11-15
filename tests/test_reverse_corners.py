# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/tests/reSketch.test.ts (the corners cases)
# SPDX-License-Identifier: AGPL-3.0-only
#
# Corners inferred and a chain closed: a rounded rectangle joined at eight
# tangent corners into one solvable loop, two lines carried on to their
# corner and a gap bridged, a fillet made sharp, and a circle cut as one
# arc that corner inference closes into a circle.
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from scanrulerfc.chainsegment import segment_chain  # noqa: E402
from scanrulerfc.linalg import mulberry32  # noqa: E402
from scanrulerfc.reverse.corners import close_chain, infer_corners, place_segments, sharpen_corner  # noqa: E402
from scanrulerfc.reverse.regions import find_regions  # noqa: E402
from scanrulerfc.reverse.sketch import add_entity, anchor_point, empty_sketch, entity_of  # noqa: E402
from scanrulerfc.reverse.solver import solve_sketch  # noqa: E402


def gaussian(rand):
    u = 0
    while u == 0:
        u = rand()
    return math.sqrt(-2 * math.log(u)) * math.cos(2 * math.pi * rand())


def rounded_rect_chain(w, h, r, step, noise, seed=3):
    rand = mulberry32(seed)
    pts = []
    corners = [([w - r, r], -math.pi / 2), ([w - r, h - r], 0), ([r, h - r], math.pi / 2), ([r, r], math.pi)]
    straights = [([r, 0], [w - r, 0]), ([w, r], [w, h - r]), ([w - r, h], [r, h]), ([0, h - r], [0, r])]
    for side in range(4):
        a, b = straights[side]
        ln = math.hypot(b[0] - a[0], b[1] - a[1])
        n = max(1, int(math.floor(ln / step + 0.5)))
        nx = -(b[1] - a[1]) / ln
        ny = (b[0] - a[0]) / ln
        for i in range(n):
            t = i / n
            e = gaussian(rand) * noise
            pts.append([a[0] + (b[0] - a[0]) * t + nx * e, a[1] + (b[1] - a[1]) * t + ny * e])
        c, start = corners[side]
        m = max(2, int(math.floor((r * math.pi) / 2 / step + 0.5)))
        for i in range(m):
            ang = start + ((math.pi / 2) * i) / m
            rr = r + gaussian(rand) * noise
            pts.append([c[0] + rr * math.cos(ang), c[1] + rr * math.sin(ang)])
    pts.append([pts[0][0], pts[0][1]])
    return pts


class Corners(unittest.TestCase):
    def test_circle_closes_into_a_circle(self):
        rand = mulberry32(9)
        chain = []
        for i in range(360):
            a = (i * math.pi) / 180
            r = 12 + gaussian(rand) * 0.02
            chain.append([r * math.cos(a), r * math.sin(a)])
        chain.append(chain[0])
        cut = segment_chain(chain)
        self.assertEqual(len(cut["segments"]), 1)
        self.assertEqual(cut["segments"][0]["kind"], "arc")
        s = empty_sketch()
        placed = place_segments(s, cut)
        infer_corners(s, placed, cut["closed"])
        self.assertEqual(s["entities"][0]["kind"], "circle")
        self.assertAlmostEqual(s["entities"][0]["r"], 12, 1)

    def test_rounded_rectangle_eight_tangent_corners(self):
        cut = segment_chain(rounded_rect_chain(60, 40, 5, 0.25, 0.03))
        s = empty_sketch()
        placed = place_segments(s, cut)
        report = infer_corners(s, placed, cut["closed"])
        self.assertEqual(report, {"joined": 8, "tangent": 8, "open": 0})
        solved = solve_sketch(s)
        self.assertTrue(solved["ok"])
        self.assertLess(solved["softRms"], 0.08)
        for c in s["constraints"]:
            if c["kind"] != "coincident":
                continue
            p = anchor_point(entity_of(s, c["p"]["entity"]), c["p"]["at"])
            q = anchor_point(entity_of(s, c["q"]["entity"]), c["q"]["at"])
            self.assertLess(math.hypot(p[0] - q[0], p[1] - q[1]), 1e-4)
        regions = find_regions(s)
        self.assertEqual(len(regions), 1)
        self.assertLess(abs(regions[0]["area"] - (60 * 40 - (4 - math.pi) * 25)), 0.5)

    def test_carries_lines_to_corner_and_bridges(self):
        s = empty_sketch()
        a = add_entity(s, {"kind": "line", "a": [4, 0], "b": [46, 0]})
        b = add_entity(s, {"kind": "line", "a": [50, 4], "b": [50, 26]})
        c = add_entity(s, {"kind": "line", "a": [46, 30], "b": [4, 30]})
        order = [{"id": a, "from": "a", "to": "b"}, {"id": b, "from": "a", "to": "b"}, {"id": c, "from": "a", "to": "b"}]
        inferred = infer_corners(s, order, False)
        self.assertEqual(inferred["joined"], 0)
        self.assertEqual(inferred["open"], 2)
        self.assertEqual(close_chain(s, order), 3)

        def near(p, q):
            self.assertLess(math.hypot(p[0] - q[0], p[1] - q[1]), 1e-9)

        near(entity_of(s, a)["b"], [50, 0])
        near(entity_of(s, b)["a"], [50, 0])
        near(entity_of(s, c)["a"], [50, 30])
        self.assertEqual(len(s["entities"]), 4)
        bridge = s["entities"][3]
        self.assertEqual(bridge["kind"], "line")
        self.assertEqual(bridge["a"], [4, 30])
        self.assertEqual(bridge["b"], [4, 0])
        self.assertTrue(solve_sketch(s)["ok"])
        self.assertEqual(len(find_regions(s)), 1)

    def test_fillet_made_sharp(self):
        cut = segment_chain(rounded_rect_chain(60, 40, 5, 0.25, 0.02))
        s = empty_sketch()
        placed = place_segments(s, cut)
        infer_corners(s, placed, cut["closed"])
        fillet = next(e for e in s["entities"] if e["kind"] == "arc")
        self.assertTrue(sharpen_corner(s, fillet["id"]))
        self.assertEqual(len([e for e in s["entities"] if e["kind"] == "arc"]), 3)
        self.assertTrue(solve_sketch(s)["ok"])
        regions = find_regions(s)
        self.assertEqual(len(regions), 1)
        self.assertLess(abs(regions[0]["area"] - (60 * 40 - (3 * (4 - math.pi) * 25) / 4)), 0.5)


if __name__ == "__main__":
    unittest.main()
