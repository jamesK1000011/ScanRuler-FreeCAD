# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/tests/reNetworkSplit.test.ts
# SPDX-License-Identifier: AGPL-3.0-only
#
# Cells of three and five sides on a sphere cap split from their centres
# into as many four-sided patches, at the noise, meeting tangent along the
# spokes and at one corner of n patches; a centre dragged elsewhere taken;
# a triangle beside a quad splitting their shared side by a T-node, which
# the patches meet across within a few microns and, with more spans on a
# noisier scan, tangent.
import math
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

from network_meshes import network, sphere_scan  # noqa: E402
from scanrulerfc.reverse.network import read_network  # noqa: E402
from scanrulerfc.reverse.scan_path import ScanPaths  # noqa: E402

R = 40
NOISE = 0.02


def cap(deg, turn):
    """A point on the sphere deg from its +x pole, turned turn round it."""
    a = (deg * math.pi) / 180
    t = (turn * math.pi) / 180
    return [R * math.cos(a), R * math.sin(a) * math.cos(t), R * math.sin(a) * math.sin(t)]


def inside(corners):
    """A point inside a cell on the sphere: its corners' middle, on it."""
    c = [sum(p[k] for p in corners) for k in range(3)]
    l = math.hypot(*c)
    return [(R * c[0]) / l, (R * c[1]) / l, (R * c[2]) / l]


def polygon(n, deg, centre=None):
    nodes = {k + 1: cap(deg, (360 * k) / n) for k in range(n)}
    curves = [{"from": k + 1, "to": ((k + 1) % n) + 1} for k in range(n)]
    f = network(1, nodes, curves, [cap(2, 0)])
    if centre is not None:
        f["cells"][0]["centre"] = centre
    return f


def beside_triangle():
    """A quad and, beside it, a triangle on its right side."""
    nodes = {1: cap(30, 150), 2: cap(30, 210), 3: cap(8, 240), 4: cap(8, 120), 5: cap(40, 290)}
    return network(1, nodes, [{"from": 1, "to": 2}, {"from": 2, "to": 3}, {"from": 3, "to": 4}, {"from": 4, "to": 1}, {"from": 3, "to": 5}, {"from": 5, "to": 2}],
                   [cap(18, 180), inside([nodes[3], nodes[5], nodes[2]])])


class SplitCells(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scan = ScanPaths(*sphere_scan(R, NOISE, 6))

    def check_split(self, n):
        r = read_network(self.scan, polygon(n, 35))
        out = r["outcomes"][0]
        self.assertIn("patches", out)
        self.assertEqual(len(out["patches"]), n)
        self.assertEqual(out["sides"], n)
        fit = r["fit"]
        for p in fit["patches"]:
            self.assertGreater(p["rms"], 0.5 * NOISE)
            self.assertLess(p["rms"], 1.5 * NOISE)
        spokes = [s["curve"] for s in r["split"]["spokes"]]
        self.assertEqual(len(spokes), n)
        across = [s for s in fit["shared"] if s["curve"] in spokes]
        self.assertEqual(len(across), n)
        for s in across:
            self.assertLess(s["gap"], 1e-9)
            self.assertLess(s["angle"], 0.5)
        self.assertEqual(len(fit["corners"]), 1)
        self.assertEqual(fit["corners"][0]["patches"], n)
        self.assertTrue(math.isfinite(fit["corners"][0]["angle"]))
        c = r["split"]["centres"][0]["at"]
        self.assertLess(math.hypot(c[1], c[2]), 3)

    def test_splits_a_triangle_on_a_sphere_cap_into_3_patches(self):
        self.check_split(3)

    def test_splits_a_pentagon_on_a_sphere_cap_into_5_patches(self):
        self.check_split(5)

    def test_takes_a_centre_dragged_elsewhere(self):
        r = read_network(self.scan, polygon(3, 35, cap(8, 90)))
        out = r["outcomes"][0]
        self.assertEqual(len(out.get("patches", [])), 3)
        c = r["split"]["centres"][0]["at"]
        want = cap(8, 90)
        self.assertLess(math.hypot(c[0] - want[0], c[1] - want[1], c[2] - want[2]), 0.2)

    def test_splits_the_side_a_triangle_shares_with_a_four_sided_cell_by_a_t_node(self):
        r = read_network(self.scan, beside_triangle())
        self.assertEqual([len(o["patches"]) if "patches" in o else o["refused"] for o in r["outcomes"]], [1, 3])
        tee = [s for s in r["fit"]["shared"] if s.get("tee")]
        self.assertEqual(len(tee), 2)
        for s in tee:
            self.assertLess(s["gap"], 0.005)
        node = next((n for n in r["traced"]["nodes"] if n["id"] >= 1_000_000 and not any(c["at"] is n["at"] for c in r["split"]["centres"])), None)
        self.assertIsNotNone(node)

    def test_holds_a_t_junction_tangent(self):
        noisy = ScanPaths(*sphere_scan(R, 0.05, 6))
        f = beside_triangle()
        r = read_network(noisy, dict(f, spans={str(c["id"]): 16 for c in f["curves"]}))
        tee = [s for s in r["fit"]["shared"] if s.get("tee")]
        self.assertEqual(len(tee), 2)
        for s in tee:
            self.assertLess(s["angle"], 1)


if __name__ == "__main__":
    unittest.main()
