# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/core/network.ts (checked against the original's own numbers)
# SPDX-License-Identifier: AGPL-3.0-only
#
# Whole network reads against goldens the original computed: a 2 x 2
# network on a wavy sheet, a strip round 270 degrees of a cylinder sized by
# Auto, and a triangle on a sphere split from its centre. The outcomes, the
# nodes, the strips' span counts, the patches' nets and points, the shared
# curves and the corners come out as the original's, the poles within a
# micron and the readings within rounding; the conjugate gradient takes the
# same iterations.
import json
import math
import os
import sys
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

from network_meshes import grid_network, grid_scan, network, sphere_scan  # noqa: E402
from scanrulerfc.reverse.network import read_network  # noqa: E402
from scanrulerfc.reverse.scan_path import ScanPaths  # noqa: E402

with open(os.path.join(HERE, "reverse_fixtures", "network_read_goldens.json"), encoding="utf-8") as f:
    G = json.load(f)

R = 40
r = 20


def cap(deg, turn):
    a = deg * math.pi / 180
    t = turn * math.pi / 180
    return [R * math.cos(a), R * math.sin(a) * math.cos(t), R * math.sin(a) * math.sin(t)]


def sheet(u, v):
    return [100 * u, 80 * v, 3 * math.sin(2 * u) * math.cos(v)]


def on(deg, z):
    return [r * math.cos(deg * math.pi / 180), r * math.sin(deg * math.pi / 180), z]


CASES = {
    "sheet": (lambda: grid_scan(60, 48, sheet, noise=0.02), lambda: grid_network(1, 2, 2, sheet, 1, [0.15, 0.85, 0.15, 0.85])),
    "strip": (lambda: grid_scan(120, 30, lambda u, v: [r * math.cos(2 * math.pi * u), r * math.sin(2 * math.pi * u), 40 * v], wrap=True, noise=0.02),
              lambda: network(3, {1: on(0, 5), 2: on(270, 5), 3: on(270, 35), 4: on(0, 35)},
                              [{"from": 1, "to": 2, "via": [on(90, 5), on(180, 5)]}, {"from": 2, "to": 3}, {"from": 3, "to": 4, "via": [on(180, 35), on(90, 35)]}, {"from": 4, "to": 1}],
                              [on(135, 20)])),
    "triangle": (lambda: sphere_scan(R, 0.02, 5), lambda: network(1, {k + 1: cap(35, 120 * k) for k in range(3)}, [{"from": 1, "to": 2}, {"from": 2, "to": 3}, {"from": 3, "to": 1}], [cap(2, 0)])),
}


def without_seed(o):
    return {k: v for k, v in o.items() if k != "seed"}


class NetworkReadGoldens(unittest.TestCase):
    def check(self, name):
        mk, net = CASES[name]
        g = G[name]
        x = read_network(ScanPaths(*mk()), net())
        fit = x["fit"]
        self.assertEqual([without_seed(o) for o in x["outcomes"]], [without_seed(o) for o in g["outcomes"]])
        self.assertEqual([n["id"] for n in x["traced"]["nodes"]], [n["id"] for n in g["nodes"]])
        np.testing.assert_allclose([n["at"] for n in x["traced"]["nodes"]], [n["at"] for n in g["nodes"]], atol=1e-6)
        self.assertEqual(fit["strips"], g["strips"])
        self.assertEqual((fit["rounds"], fit["iterations"]), (g["rounds"], g["iterations"]))
        self.assertEqual(len(fit["patches"]), len(g["patches"]))
        for p, q in zip(fit["patches"], g["patches"]):
            self.assertEqual(((p["net"].nu, p["net"].nv), p["points"], p["corners"]), ((q["nu"], q["nv"]), q["points"], q["corners"]))
            np.testing.assert_allclose(p["net"].poles, q["poles"], atol=1e-6)
            for k in ("rms", "max", "misfit"):
                self.assertAlmostEqual(p[k], q[k], delta=1e-8)
        self.assertEqual([(s["curve"], s.get("tee"), s["crease"]) for s in fit["shared"]], [(s["curve"], s.get("tee"), s["crease"]) for s in g["shared"]])
        for s, t in zip(fit["shared"], g["shared"]):
            self.assertAlmostEqual(s["angle"], t["angle"], delta=1e-6)
            self.assertAlmostEqual(s["gap"], t["gap"], delta=1e-9)
        self.assertEqual([(c["node"], c["patches"]) for c in fit["corners"]], [(c["node"], c["patches"]) for c in g["corners"]])
        for c, d in zip(fit["corners"], g["corners"]):
            self.assertAlmostEqual(c["angle"], d["angle"], delta=1e-5)

    def test_sheet(self):
        self.check("sheet")

    def test_strip(self):
        self.check("strip")

    def test_triangle(self):
        self.check("triangle")


if __name__ == "__main__":
    unittest.main()
