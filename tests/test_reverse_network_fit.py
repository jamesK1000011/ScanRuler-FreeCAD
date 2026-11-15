# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/tests/reNetworkFit.test.ts
# SPDX-License-Identifier: AGPL-3.0-only
#
# A patch network's patches fitted together: a 2 x 2 network on a noisy
# sphere fits at the noise and meets tangent across its curves, the same
# again from what the last read kept; a crease keeps its fold, and taken
# off, the fold is smoothed over; a strip round 270 degrees of a cylinder,
# which no height field holds, fits as one patch; a 3 x 3 network on a
# finely scanned sheet lets go of the ties at its inner corners when drawn
# askew and keeps them when square; a higher smoothness smooths the noise
# out of the patches; and Auto's span counts grow only where they bring a
# patch to the scan.
import math
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

from network_meshes import grid_network, grid_scan, network, sphere_scan  # noqa: E402
from scanrulerfc.reverse.network import read_network  # noqa: E402
from scanrulerfc.reverse.network_curve import DEFAULT_TOLERANCE  # noqa: E402
from scanrulerfc.reverse.network_spline import patch_normal, patch_point  # noqa: E402
from scanrulerfc.reverse.scan_path import ScanPaths  # noqa: E402
from scanrulerfc.reverse.surface_fit import DEFAULT_SURFACE_FIT, fit_surface_reported  # noqa: E402

R = 40
NOISE = 0.02


def on_sphere(u, v):
    a = (u - 0.5) * 1.4
    b = (v - 0.5) * 1.4
    l = math.hypot(1, a, b)
    return [R / l, (R * a) / l, (R * b) / l]


def poles_of(fit):
    return [list(p["net"].poles) for p in fit["patches"]]


def cylinder_scan(r=20):
    return grid_scan(180, 40, lambda u, v: [r * math.cos(2 * math.pi * u), r * math.sin(2 * math.pi * u), 40 * v], wrap=True, noise=NOISE)


def on_cylinder(deg, z, r=20):
    return [r * math.cos((deg * math.pi) / 180), r * math.sin((deg * math.pi) / 180), z]


def strip_network(id_=3):
    on = on_cylinder
    return network(id_, {1: on(0, 5), 2: on(270, 5), 3: on(270, 35), 4: on(0, 35)},
                   [{"from": 1, "to": 2, "via": [on(90, 5), on(180, 5)]}, {"from": 2, "to": 3}, {"from": 3, "to": 4, "via": [on(180, 35), on(90, 35)]}, {"from": 4, "to": 1}],
                   [on(135, 20)])


class PatchNetworkFit(unittest.TestCase):
    def test_fits_a_2x2_network_on_a_noisy_sphere_tangent_and_at_the_noise(self):
        P, F = sphere_scan(R, NOISE, 6)
        scan = ScanPaths(P, F)
        f = grid_network(1, 2, 2, on_sphere, 1)
        r = read_network(scan, f)
        self.assertTrue(all("patch" in o for o in r["outcomes"]))
        fit = r["fit"]
        self.assertEqual(len(fit["patches"]), 4)
        for p in fit["patches"]:
            self.assertGreater(p["rms"], 0.6 * NOISE)
            self.assertLess(p["rms"], 1.4 * NOISE)
        self.assertEqual(len(fit["shared"]), 4)
        for s in fit["shared"]:
            self.assertLess(s["gap"], 1e-9)
            self.assertLess(s["angle"], 0.5)
        # Read again: the cells' maps kept, the same patches.
        again = read_network(scan, f)
        self.assertLess(again["ms"]["map"], r["ms"]["map"] / 4 + 1)
        self.assertEqual(poles_of(again["fit"]), poles_of(fit))
        # A node moved: what was kept gives what a fresh read gives.
        moved = dict(f, nodes=[dict(n, at=on_sphere(0.55, 0.45)) if i == 4 else n for i, n in enumerate(f["nodes"])])
        kept = read_network(scan, moved)
        fresh = read_network(ScanPaths(P, F), moved)
        self.assertEqual(poles_of(kept["fit"]), poles_of(fresh["fit"]))
        self.assertNotEqual(poles_of(kept["fit"]), poles_of(fit))

    def test_keeps_a_crease_folded(self):
        def fold(u, v):
            x = 80 * u - 40
            return [x, 60 * v, abs(x) * math.tan((15 * math.pi) / 180)]

        scan = ScanPaths(*grid_scan(160, 120, fold, noise=NOISE))
        f = grid_network(2, 1, 2, fold, 1, [0.1, 0.9, 0.1, 0.9])
        at = {n["id"]: n["at"] for n in f["nodes"]}
        middle = next(c for c in f["curves"] if abs(at[c["from"]][0]) < 1e-6 and abs(at[c["to"]][0]) < 1e-6)
        middle["crease"] = True
        fit = read_network(scan, f)["fit"]
        shared = next(s for s in fit["shared"] if s["curve"] == middle["id"])
        self.assertTrue(shared["crease"])
        self.assertGreater(shared["angle"], 28)
        self.assertLess(shared["angle"], 32)
        for p in fit["patches"]:
            self.assertLess(p["rms"], 1.5 * NOISE)
        middle["crease"] = False
        smooth = read_network(scan, f)["fit"]
        self.assertLess(next(s for s in smooth["shared"] if s["curve"] == middle["id"])["angle"], 0.5)
        self.assertGreater(max(p["max"] for p in smooth["patches"]), 5 * NOISE)

    def test_fits_a_strip_round_270_degrees_of_a_cylinder_as_one_patch(self):
        r = 20
        P, F = cylinder_scan(r)
        scan = ScanPaths(P, F)
        reading = read_network(scan, strip_network())
        fit = reading["fit"]
        self.assertEqual(len(fit["patches"]), 1)
        p = fit["patches"][0]
        self.assertLess(p["rms"], 1.25 * NOISE)
        cell = reading["cells"]["cells"][0]
        self.assertEqual(cell["status"], "ok")
        vertices = sorted({int(F[t * 3 + k]) for t in cell["triangles"] for k in range(3)})
        region = P.reshape(-1, 3)[vertices].reshape(-1)
        with self.assertRaisesRegex(Exception, "bends round past what one height field holds"):
            fit_surface_reported(region, DEFAULT_SURFACE_FIT)
        q = [0.0, 0.0, 0.0]
        off = 0.0
        for i in range(21):
            for j in range(21):
                patch_point(p["net"], i / 20, j / 20, q)
                off = max(off, abs(math.hypot(q[0], q[1]) - r))
        self.assertLess(off, 0.05)


SIZE = 18


def fine_sheet(u, v):
    return [SIZE * u, SIZE * v, 1.2 * math.sin(2.2 * u) * math.cos(1.7 * v) + 0.6 * u * v]


def grid3(skew):
    nodes = {}

    def nid(i, j):
        return j * 4 + i + 1

    for j in range(4):
        for i in range(4):
            u = 0.1 + (0.8 * i) / 3 + (skew * (1 if j % 2 else -1) if 0 < i < 3 else 0)
            v = 0.1 + (0.8 * j) / 3 + (skew * (-1 if i % 2 else 1) if 0 < j < 3 else 0)
            nodes[nid(i, j)] = fine_sheet(u, v)
    curves = [{"from": nid(i, j), "to": nid(i + 1, j)} for j in range(4) for i in range(3)]
    curves += [{"from": nid(i, j), "to": nid(i, j + 1)} for j in range(3) for i in range(4)]
    seeds = []
    for j in range(3):
        for i in range(3):
            c = [nodes[k] for k in (nid(i, j), nid(i + 1, j), nid(i + 1, j + 1), nid(i, j + 1))]
            seeds.append([sum(p[k] for p in c) / 4 for k in range(3)])
    return network(1, nodes, curves, seeds)


def folds(fit):
    """How many samples of the patches face against the patch's own way."""
    n = 0
    q = [0.0, 0.0, 0.0]
    for p in fit["patches"]:
        mean = [0.0, 0.0, 0.0]
        for a in range(11):
            for b in range(11):
                patch_normal(p["net"], a / 10, b / 10, q)
                for k in range(3):
                    mean[k] += q[k]
        for a in range(61):
            for b in range(61):
                patch_normal(p["net"], a / 60, b / 60, q)
                if q[0] * mean[0] + q[1] * mean[1] + q[2] * mean[2] < 0:
                    n += 1
    return n


def ripple(fit):
    """How much the normals wander from their neighbours' mean over the
    patches, RMS, deg: the scan's noise left in them."""
    S = 48
    total = 0.0
    count = 0
    for p in fit["patches"]:
        n = [[patch_normal(p["net"], i / S, j / S) for j in range(S + 1)] for i in range(S + 1)]
        for i in range(1, S):
            for j in range(1, S):
                m = [n[i - 1][j][k] + n[i + 1][j][k] + n[i][j - 1][k] + n[i][j + 1][k] for k in range(3)]
                cos = (m[0] * n[i][j][0] + m[1] * n[i][j][1] + m[2] * n[i][j][2]) / math.hypot(*m)
                total += math.acos(min(1, cos)) ** 2
                count += 1
    return (math.sqrt(total / count) * 180) / math.pi


class FineSheetNetwork(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scan = ScanPaths(*grid_scan(90, 90, fine_sheet, noise=0.004, seed=7))

    def test_lets_go_of_the_ties_at_the_inner_corners_of_a_network_drawn_askew(self):
        fit = read_network(self.scan, grid3(0.06))["fit"]
        self.assertEqual(folds(fit), 0)
        for p in fit["patches"]:
            self.assertLess(p["rms"], 0.006)
            self.assertLess(p["max"], 0.05)
        self.assertEqual(sorted(c["node"] for c in fit["corners"]), [6, 7, 10, 11])
        for c in fit["corners"]:
            self.assertLess(c["angle"], 2)
        for s in fit["shared"]:
            self.assertLess(s["angle"], 0.5)

    def test_keeps_the_ties_at_the_corners_of_one_drawn_square(self):
        fit = read_network(self.scan, grid3(0))["fit"]
        self.assertEqual(folds(fit), 0)
        self.assertEqual(fit["corners"], [])
        for s in fit["shared"]:
            self.assertLess(s["angle"], 0.1)

    def test_smooths_the_curves_with_the_patches(self):
        f = grid3(0)

        def at(smoothness):
            return read_network(self.scan, dict(f, spans={str(c["id"]): 10 for c in f["curves"]}, fit={"smoothness": smoothness}))["fit"]

        usual = at(0.001)
        smooth = at(0.1)
        self.assertLess(ripple(smooth), ripple(usual) / 2)
        self.assertLess(ripple(usual), 0.02)
        for p in smooth["patches"]:
            self.assertLess(p["rms"], 0.01)
        for s in smooth["shared"]:
            self.assertLess(s["angle"], 0.1)


class AutoSpanCounts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scan = ScanPaths(*cylinder_scan())
        cls.strip = strip_network()

    def fit_of(self, **change):
        return read_network(self.scan, dict(self.strip, **change))["fit"]

    @staticmethod
    def spans_of(fit):
        rnd = next(s for s in fit["strips"] if 1 in s["curves"])
        up = next(s for s in fit["strips"] if 2 in s["curves"])
        return [rnd["spans"], up["spans"]]

    def test_starts_at_four_spans_and_adds_them_only_round_the_bend(self):
        four = self.fit_of(spans={"1": 4, "2": 4})
        self.assertGreater(four["patches"][0]["misfit"], 0.03)
        self.assertGreater(four["patches"][0]["rms"], 2 * NOISE)
        auto = self.fit_of()
        self.assertEqual(self.spans_of(auto), [6, 4])
        self.assertTrue(all(s["auto"] for s in auto["strips"]))
        self.assertLess(auto["patches"][0]["misfit"], DEFAULT_TOLERANCE)
        self.assertLess(auto["patches"][0]["rms"], 1.1 * NOISE)

    def test_goes_finer_for_a_finer_tolerance_no_finer_than_the_noise(self):
        fine = self.fit_of(fit={"smoothness": 0.001, "tolerance": 0.002})
        self.assertEqual(self.spans_of(fine), [9, 4])
        self.assertEqual(fine["patches"][0]["misfit"], 0)

    def test_reads_a_sheets_noise_as_no_misfit_and_keeps_it_at_four_spans(self):
        flat = ScanPaths(*grid_scan(100, 100, lambda u, v: [30 * u, 30 * v, 0], noise=NOISE))
        square = network(4, {1: [3, 3, 0], 2: [27, 3, 0], 3: [27, 27, 0], 4: [3, 27, 0]},
                         [{"from": 1, "to": 2}, {"from": 2, "to": 3}, {"from": 3, "to": 4}, {"from": 4, "to": 1}], [[15, 15, 0]])
        for n in (4, 12):
            self.assertEqual(read_network(flat, dict(square, spans={"1": n, "2": n}))["fit"]["patches"][0]["misfit"], 0)
        auto = read_network(flat, square)["fit"]
        self.assertEqual((auto["patches"][0]["net"].nu, auto["patches"][0]["net"].nv), (4, 4))


if __name__ == "__main__":
    unittest.main()
