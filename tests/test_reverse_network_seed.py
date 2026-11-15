# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/tests/reNetworkSeed.test.ts
# SPDX-License-Identifier: AGPL-3.0-only
#
# A patch's seed, put well inside the loop of its corners: in the middle of
# a square; in a U's bar or arms, not its notch, where its centroid is; on
# a shell's outer skin, not the inner wall its loop's plane lies under; in
# the middle of a strip round 270 degrees of a cylinder, which folds over
# seen along any one way. And the corners a patch was placed with are its
# corners: a node on a straight side one, a square corner none.
import math
import os
import sys
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

from network_meshes import grid_scan, network, sphere_scan  # noqa: E402
from scanrulerfc.reverse.network import read_network  # noqa: E402
from scanrulerfc.reverse.network_seed import seed_inside  # noqa: E402
from scanrulerfc.reverse.scan_path import ScanPaths  # noqa: E402


def loop(corners):
    """A closed loop through corners, a point every half millimetre along
    each straight side."""
    out = []
    for i in range(len(corners)):
        a = corners[i]
        b = corners[(i + 1) % len(corners)]
        n = max(1, math.ceil(math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2]) / 0.5))
        for k in range(n):
            out.extend((a[0] + ((b[0] - a[0]) * k) / n, a[1] + ((b[1] - a[1]) * k) / n, a[2] + ((b[2] - a[2]) * k) / n))
    return out


def inside_polygon(poly, x, y):
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < ((xj - xi) * (y - yi)) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


class PatchSeed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.flat = ScanPaths(*grid_scan(100, 100, lambda u, v: [100 * u, 100 * v, 0], noise=0.01))

    def test_lies_in_the_middle_of_a_square(self):
        seed = seed_inside(self.flat, loop([[20, 20, 0], [60, 20, 0], [60, 60, 0], [20, 60, 0]]))
        self.assertLess(math.hypot(seed[0] - 40, seed[1] - 40), 2)
        self.assertLess(abs(seed[2]), 0.1)

    def test_lies_in_a_us_bar_or_arms_not_in_its_notch(self):
        u = [[20, 20], [80, 20], [80, 80], [60, 80], [60, 40], [40, 40], [40, 80], [20, 80]]
        seed = seed_inside(self.flat, loop([[x, y, 0] for x, y in u]))
        self.assertTrue(inside_polygon(u, seed[0], seed[1]))
        self.assertGreater(min(seed[0] - 20, 80 - seed[0], seed[1] - 20), 5)

    def test_lies_on_a_shells_outer_skin_not_on_the_inner_wall(self):
        op, oi = sphere_scan(40, 0.01, 5)
        ip, ii = sphere_scan(38.5, 0.01, 5)
        flipped = ii.reshape(-1, 3)[:, [0, 2, 1]].reshape(-1)
        positions = np.concatenate([op, ip])
        indices = np.concatenate([oi, flipped + op.shape[0] // 3])
        shell = ScanPaths(positions, indices)
        ring = []
        for k in range(360):
            t = (k * math.pi) / 180
            ring.extend((40 * math.cos(math.pi / 6), 40 * math.sin(math.pi / 6) * math.cos(t), 40 * math.sin(math.pi / 6) * math.sin(t)))
        seed = seed_inside(shell, ring)
        self.assertLess(abs(math.hypot(*seed) - 40), 0.1)
        self.assertGreater(seed[0], 39)

    def test_lies_in_the_middle_of_a_strip_round_270_degrees_of_a_cylinder(self):
        r = 20
        scan = ScanPaths(*grid_scan(180, 40, lambda u, v: [r * math.cos(2 * math.pi * u), r * math.sin(2 * math.pi * u), 40 * v], wrap=True, noise=0.01))

        def on(deg, z):
            return [r * math.cos((deg * math.pi) / 180), r * math.sin((deg * math.pi) / 180), z]

        out = []
        for a in range(0, 270, 2):
            out.extend(on(a, 5))
        z = 5.0
        while z < 35:
            out.extend(on(270, z))
            z += 0.5
        for a in range(270, 0, -2):
            out.extend(on(a, 35))
        z = 35.0
        while z > 5:
            out.extend(on(0, z))
            z -= 0.5
        seed = seed_inside(scan, out)
        angle = (math.atan2(seed[1], seed[0]) * 180) / math.pi
        deg = angle + 360 if angle < 0 else angle
        self.assertLess(abs(math.hypot(seed[0], seed[1]) - r), 0.1)
        self.assertGreater(deg, 5)
        self.assertLess(deg, 265)
        self.assertGreater(seed[2], 7)
        self.assertLess(seed[2], 33)


class PlacedCorners(unittest.TestCase):
    def test_are_its_corners_a_node_on_a_straight_side_one_a_square_corner_none(self):
        scan = ScanPaths(*grid_scan(100, 100, lambda u, v: [100 * u, 100 * v, 0], noise=0.01))
        f = network(1, {1: [20, 20, 0], 5: [40, 20, 0], 2: [60, 20, 0], 3: [60, 60, 0], 4: [20, 60, 0]},
                    [{"from": 1, "to": 5}, {"from": 5, "to": 2}, {"from": 2, "to": 3}, {"from": 3, "to": 4}, {"from": 4, "to": 1}], [[40, 40, 0]])
        by_rule = read_network(scan, f)
        self.assertEqual(sorted(by_rule["fit"]["patches"][0]["corners"]), [1, 2, 3, 4])
        f["cells"][0]["corners"] = [1, 5, 3, 4]
        placed = read_network(scan, f)
        self.assertEqual(placed["outcomes"][0].get("sides"), 4)
        self.assertEqual(sorted(placed["fit"]["patches"][0]["corners"]), [1, 3, 4, 5])
        self.assertLess(placed["fit"]["patches"][0]["rms"], 0.02)


if __name__ == "__main__":
    unittest.main()
