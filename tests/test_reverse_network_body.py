# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/tests/reNetworkBody.test.ts (its kernel-free part)
# SPDX-License-Identifier: AGPL-3.0-only
#
# A patch network made a body, up to the kernel: a network closed round a
# sphere meshes, without the kernel, into a closed ghost of the sphere's
# volume, its grids sharing their samples along every shared curve; and the
# body's own steps run through the kernel adapter's op names, here a stand-in
# that makes each face its grid. The original's cases that build, sew and
# export with the kernel wait for it.
import math
import os
import sys
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

from network_meshes import grid_network, network, sphere_scan  # noqa: E402
from scanrulerfc.reverse.network import read_network  # noqa: E402
from scanrulerfc.reverse.network_body import GRID_PER_SPAN, SEW_TOLERANCE, empty_report, network_body, network_ghost, patch_grid, sew_tolerances, side_sampler  # noqa: E402
from scanrulerfc.reverse.network_spline import curve_point  # noqa: E402
from scanrulerfc.reverse.scan_path import ScanPaths, closest_on_triangles  # noqa: E402
from scanrulerfc.reverse.surface_fit import grid_area  # noqa: E402

KERNEL = "kernel (step 3) not ported"
R = 40
NOISE = 0.02


def on_sphere(u, v):
    a = (u - 0.5) * 1.4
    b = (v - 0.5) * 1.4
    l = math.hypot(1, a, b)
    return [R / l, (R * a) / l, (R * b) / l]


def closed_network():
    s = R / math.sqrt(3)
    nodes = {i + 1: [s if i & 1 else -s, s if i & 2 else -s, s if i & 4 else -s] for i in range(8)}
    curves = [{"from": i + 1, "to": (i | bit) + 1} for i in range(8) for bit in (1, 2, 4) if not i & bit]
    seeds = [[R, 0, 0], [-R, 0, 0], [0, R, 0], [0, -R, 0], [0, 0, R], [0, 0, -R]]
    return network(2, nodes, curves, seeds)


class GridKernel:
    """A stand-in for the kernel adapter: a face is its grid, a sewn shape
    the list of them."""

    def __init__(self):
        self.released = 0

    def surface_through(self, points, rows, cols):
        return {"grid": {"points": np.asarray(points, dtype=float), "rows": rows, "cols": cols}}

    def surface_area(self, face):
        return grid_area(face["grid"])

    def release(self, *shapes):
        self.released += len(shapes)

    def distance_to_point(self, face, q):
        g = face["grid"]
        G = g["points"].reshape(g["rows"], g["cols"], 3)
        a, b, c, d = (x.reshape(-1, 3) for x in (G[:-1, :-1], G[:-1, 1:], G[1:, :-1], G[1:, 1:]))
        A, B, C = np.concatenate([a, a]), np.concatenate([b, d]), np.concatenate([d, c])
        Q = closest_on_triangles(q, A, B, C)
        return float(np.sqrt(((Q - np.asarray(q)) ** 2).sum(axis=1)).min())

    def copy(self, shape):
        return {"faces": [shape]}

    def sew_patches(self, faces, tolerance, closed):
        return {"faces": list(faces), "closed": closed}

    def is_closed_solid(self, shape):
        return bool(shape.get("closed"))

    def extent(self, shape):
        P = np.concatenate([f["grid"]["points"].reshape(-1, 3) for f in shape["faces"]])
        return {"min": P.min(axis=0).tolist(), "max": P.max(axis=0).tolist()}

    def edges(self, shape, deflection):
        return []

    def face_points(self, shape):
        faces = shape["faces"] if "faces" in shape else [shape]
        out = []
        for i, f in enumerate(faces):
            g = f["grid"]
            mid = g["points"].reshape(g["rows"], g["cols"], 3)[g["rows"] // 2, g["cols"] // 2]
            out.append({"hash": 100 + i, "at": mid.tolist()})
        return out


class NetworkBody(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scan = ScanPaths(*sphere_scan(R, NOISE, 6))

    @unittest.skip(KERNEL)
    def test_makes_a_2x2_network_on_a_sphere_a_sheet_that_reads_back_from_step(self):
        pass

    @unittest.skip(KERNEL)
    def test_sews_a_network_closed_round_a_sphere_into_one_valid_solid(self):
        pass

    @unittest.skip(KERNEL)
    def test_thickens_the_sheet_in_and_out_and_refuses_both_ways_rather_than_hang_the_kernel(self):
        pass

    def test_meshes_a_network_closed_round_a_sphere_into_a_closed_ghost_of_its_volume(self):
        reading = read_network(self.scan, closed_network())
        fit = reading["fit"]
        self.assertEqual(len(fit["patches"]), 6)
        self.assertEqual(len(fit["corners"]), 8)
        ghost = network_ghost(reading)
        self.assertTrue(ghost["report"]["closed"])
        self.assertLess(abs(ghost["volume"] / ((4 / 3) * math.pi * R ** 3) - 1), 0.01)
        # Along every shared curve the two patches' grids hold the same samples.
        sampler = side_sampler(fit)
        on = {}
        for p in fit["patches"]:
            for k, side in enumerate(p["sides"]):
                count = (p["net"].nu if k % 2 == 0 else p["net"].nv) * GRID_PER_SPAN + 1
                row = sampler(p)(k, count).reshape(-1, 3)
                h = side["edges"][0]
                on.setdefault(h["curve"], []).append(row if h["forward"] else row[::-1])
        self.assertEqual(sorted(len(v) for v in on.values()), [2] * 12)
        for a, b in on.values():
            if a.shape == b.shape:
                self.assertEqual(np.abs(a - b).max(), 0)

    def test_runs_the_body_through_the_kernel_adapter(self):
        reading = read_network(self.scan, grid_network(1, 2, 2, on_sphere, 1))
        k = GridKernel()
        out = network_body(k, reading)
        report = out["report"]
        self.assertEqual(len(report["patches"]), 4)
        self.assertFalse(report["closed"])
        self.assertLess(report["worstAngle"], 0.5)
        # The stand-in's faces are flat between their samples: the gap read is
        # their chords' sag, under 0.05 mm here, and never less than the fit's.
        self.assertLess(report["worstGap"], 0.05)
        self.assertGreaterEqual(report["worstGap"], max(s["gap"] for s in reading["fit"]["shared"]))
        self.assertEqual(sorted(out["faceOf"].values()), [0, 1, 2, 3])
        self.assertEqual(k.released, 4)
        grid = patch_grid(reading["fit"]["patches"][0], GRID_PER_SPAN, side_sampler(reading["fit"])(reading["fit"]["patches"][0]))
        self.assertEqual(grid["rows"], reading["fit"]["patches"][0]["net"].nu * GRID_PER_SPAN + 1)
        empty = empty_report(dict(reading, fit=None))
        self.assertEqual((empty["patches"], empty["closed"]), ([], False))

    def test_a_seam_left_open_is_sewn_again_looser(self):
        """FreeCAD 1.1.3's OCCT left two seams of a sphere's network open at
        the original's tolerance: the patches are sewn again at looser ones,
        relative to the model, before the network is refused."""
        reading = read_network(self.scan, grid_network(1, 2, 2, on_sphere, 1))
        fit = reading["fit"]
        seam = fit["curves"][fit["shared"][0]["curve"]]
        mid = curve_point(seam["poles"], seam["spans"], 0.5)

        class Stubborn(GridKernel):
            def __init__(self, tries):
                super().__init__()
                self.tries, self.tried = tries, []

            def sew_patches(self, faces, tolerance, closed):
                self.tried.append(tolerance)
                return {**super().sew_patches(faces, tolerance, closed), "tolerance": tolerance}

            def open_edges(self, shape):
                return [] if len(self.tried) >= self.tries else [list(mid)]

        k = Stubborn(2)  # the second, looser sewing closes the seam
        out = network_body(k, reading)
        self.assertEqual(len(k.tried), 2)
        self.assertEqual(k.tried[0], max(SEW_TOLERANCE, 2 * out["report"]["worstGap"]))
        self.assertGreater(k.tried[1], k.tried[0])
        never = Stubborn(99)
        with self.assertRaises(ValueError) as e:
            network_body(never, reading)
        self.assertIn(f"curve {fit['shared'][0]['curve']} (gap", str(e.exception))
        self.assertGreaterEqual(len(never.tried), 2)
        self.assertEqual(never.tried, sorted(never.tried))

    def test_the_tolerances_tried(self):
        self.assertEqual(sew_tolerances(1e-3, 100), [1e-3, 1e-2, 0.1])
        self.assertEqual(sew_tolerances(1e-3, 1), [1e-3])  # a small part: no looser than its own share
        self.assertEqual(sew_tolerances(1e-3, 5), [1e-3, 0.005])
        self.assertEqual(sew_tolerances(0.5, 100), [0.5])  # a fit already looser than the cap


if __name__ == "__main__":
    unittest.main()
