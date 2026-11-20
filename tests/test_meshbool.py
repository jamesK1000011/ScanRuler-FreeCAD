# SPDX-License-Identifier: AGPL-3.0-only
# meshbool, the Boolean's and Trim to scan's kernel (numpy only), on a dense
# scan-like mesh: a noisy rounded box of 139,968 triangles — the size of the
# a scan whose cut FreeCAD's Mesh.difference left open and inside out —
# cut by a solid with large faces and a bore through it, placed every which
# way; boxes whose faces lie on the mesh's own planes; and the scan untouched
# away from the cut. The real pair itself is third-party and not in the
# repository: set SCANRULER_SCANPAIR_DIR to a folder holding scan.stl and fcu.stl
# to run that case too.
import os
import struct
import sys
import time
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

from meshkit import box_mesh  # noqa: E402
from scanrulerfc import mesh_core as M  # noqa: E402
from scanrulerfc.meshtools import boolean as BO  # noqa: E402
from scanrulerfc.meshtools import meshbool as MB  # noqa: E402


def scan_like(n=108, half=(40.0, 15.0, 60.0), r=6.0, noise=0.03, seed=0):
    """A rounded box with noise along its normals: 12 n² triangles."""
    V, F = box_mesh(2, 2, 2, n)
    h = np.array(half)
    core = np.clip(V * h, -(h - r), h - r)
    d = V * h - core
    L = np.linalg.norm(d, axis=1, keepdims=True)
    L[L == 0] = 1
    P = core + d / L * (r + np.random.default_rng(seed).normal(scale=noise, size=(len(V), 1)))
    return P, F


def coarse_box(lo, hi):
    V, F = box_mesh(1, 1, 1, 1, center=(0.5, 0.5, 0.5))
    return V * (np.asarray(hi, float) - lo) + lo, F


def cylinder(r, z0, z1, n=48):
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    ring = np.stack([np.cos(t) * r, np.sin(t) * r], 1)
    V = np.vstack([np.c_[ring, np.full(n, z0)], np.c_[ring, np.full(n, z1)], [[0, 0, z0], [0, 0, z1]]])
    F = []
    for i in range(n):
        j = (i + 1) % n
        F += [[i, j, n + j], [i, n + j, n + i], [2 * n, j, i], [2 * n + 1, n + i, n + j]]
    return V, np.array(F, dtype=np.int64)


def rotation(axis, angle):
    a = np.asarray(axis, float) / np.linalg.norm(axis)
    K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + np.sin(angle) * K + (1 - np.cos(angle)) * K @ K


def shut(F):
    return MB.closed_report(F)


def read_stl(path):
    with open(path, "rb") as f:
        b = f.read()
    n = struct.unpack("<I", b[80:84])[0]
    rec = np.frombuffer(b[84:84 + 50 * n], dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]))
    T = rec["v"].astype(float).reshape(-1, 3)
    key = np.ascontiguousarray(rec["v"].reshape(-1, 3)).view(np.dtype((np.void, 12))).ravel()
    _, first, inv = np.unique(key, return_index=True, return_inverse=True)
    return T[first], inv.reshape(-1, 3).astype(np.int64)


class DenseScan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scan = scan_like()
        # A cutter with features: a box (12 large triangles) with a bore's
        # cylinder through it, made one by the kernel itself.
        cls.cutter = MB.boolean(*coarse_box([-30, -30, -30], [30, 30, 30]), *cylinder(8, -100, 100), "add")[:2]

    def test_the_scan_and_cutter_are_what_the_cases_need(self):
        V, F = self.scan
        self.assertEqual(len(F), 139968)
        self.assertEqual(shut(F), {"open": 0, "bad": 0})
        self.assertEqual(shut(self.cutter[1]), {"open": 0, "bad": 0})
        self.assertAlmostEqual(MB.volume(*self.cutter), 216000 + np.pi * 64 * 140 * (48 / (2 * np.pi)) * np.sin(2 * np.pi / 48), 3)

    def test_subtract_add_intersect_closed_and_adding_up_wherever_it_is_put(self):
        V, F = self.scan
        whole = MB.volume(V, F)
        rng = np.random.default_rng(5)
        for k in range(2):
            R = rotation(rng.normal(size=3), rng.uniform(0, np.pi))
            B = (self.cutter[0] @ R.T + rng.uniform(-30, 30, 3) * [1, 0.3, 1], self.cutter[1])
            vol = {}
            for op in MB.OPS:
                with self.subTest(k=k, op=op):
                    t = time.time()
                    RV, RF, vmap, info = MB.boolean(V, F, *B, op)
                    self.assertLess(time.time() - t, 60)
                    self.assertEqual(shut(RF), {"open": 0, "bad": 0})
                    self.assertGreater(info["crossings"], 0)
                    vol[op] = MB.volume(RV, RF)
            self.assertAlmostEqual(vol["subtract"] + vol["intersect"], whole, delta=whole * 1e-9)
            self.assertAlmostEqual(vol["add"] + vol["intersect"], whole + MB.volume(*B), delta=whole * 1e-9)
            self.assertGreater(vol["intersect"], 1000)

    def test_away_from_the_cut_the_scan_is_untouched(self):
        V, F = self.scan
        B = (self.cutter[0] + [0, 0, 60], self.cutter[1])
        RV, RF, vmap, _ = MB.boolean(V, F, *B, "subtract")
        far = V[:, 2] < -10  # well below the cutter (z from 30)
        self.assertTrue((vmap[far] >= 0).all())
        np.testing.assert_array_equal(RV[vmap[far]], V[far])  # exactly, not to float32
        # the triangles there come back as they were, on the same points
        tri_far = far[F].all(axis=1)
        kept = {tuple(t) for t in RF.tolist()}
        self.assertTrue(all(tuple(vmap[t]) in kept for t in F[tri_far].tolist()))
        # the scan's own points that stay come first, in their order
        left = vmap[vmap >= 0]
        self.assertTrue((np.diff(left) > 0).all())

    def test_through_the_tool_on_a_dense_scan(self):
        V, F = self.scan
        R = rotation([0, 1, 1], np.pi)
        B = self.cutter[0] @ R.T + [10, 0, 50]
        V2, F2, vmap, rep = BO.boolean_mesh(V, F, [(B, self.cutter[1], "FCU cutout")], "subtract")
        self.assertEqual(M.closedness(F2, len(V2)), {"open": 0, "bad": 0})
        self.assertGreater(rep["volumeBefore"], rep["volumeAfter"])
        self.assertGreater(rep["volumeAfter"], 0)
        self.assertGreater(rep["removed"], 0)
        self.assertGreater(rep["added"], 0)


class Coplanar(unittest.TestCase):
    def test_faces_on_the_meshs_own_planes(self):
        C = box_mesh(40, 40, 40, 40)
        cases = [(([-30, -5, -5], [0, 5, 5]), 2000), (([-20, -20, -20], [20, 0, 20]), 32000),
                 (([0, 0, 0], [20, 20, 20]), 8000), (([30, 30, 30], [40, 40, 40]), 0)]
        for (lo, hi), common in cases:
            B = coarse_box(lo, hi)
            vb = MB.volume(*B)
            for op, want in (("subtract", 64000 - common), ("add", 64000 + vb - common), ("intersect", common)):
                with self.subTest(lo=lo, op=op):
                    RV, RF, _, _ = MB.boolean(*C, *B, op)
                    self.assertEqual(shut(RF), {"open": 0, "bad": 0})
                    self.assertAlmostEqual(MB.volume(RV, RF), want, delta=0.05)

    def test_refuses_an_open_mesh(self):
        V, F = box_mesh(20, 20, 20, 4)
        with self.assertRaises(MB.BooleanError):
            MB.boolean(V, F[1:], *coarse_box([0, 0, 0], [20, 20, 20]), "subtract")


PAIR = os.environ.get("SCANRULER_SCANPAIR_DIR")


@unittest.skipUnless(PAIR and os.path.exists(os.path.join(PAIR or "", "scan.stl")), "the scan pair is third-party: set SCANRULER_SCANPAIR_DIR to run it")
class M18TestDrive(unittest.TestCase):
    def test_scan_minus_fcu_cutout(self):
        V, F = read_stl(os.path.join(PAIR, "scan.stl"))
        BV, BF = read_stl(os.path.join(PAIR, "fcu.stl"))
        # Placement [20.41, -9.7, 112.87], axis [0, 1, 1], 180°: (x, y, z) -> (-x + 20.41, z - 9.7, y + 112.87)
        BV = np.stack([-BV[:, 0] + 20.41, BV[:, 2] - 9.7, BV[:, 1] + 112.87], axis=1)
        whole = MB.volume(V, F)
        V2, F2, vmap, rep = BO.boolean_mesh(V, F, [(BV, BF, "FCU cutout")], "subtract")
        self.assertEqual(M.closedness(F2, len(V2)), {"open": 0, "bad": 0})
        _, IF, _, _ = MB.boolean(V, F, BV, BF, "intersect")
        self.assertTrue(90000 < whole - rep["volumeAfter"] < 110000, whole - rep["volumeAfter"])
        print(f"\nM18 minus FCU: {rep['volumeBefore']:.1f} -> {rep['volumeAfter']:.1f} mm³, removed {rep['removed']}, added {rep['added']}, {len(F2)} triangles", file=sys.stderr)


if __name__ == "__main__":
    unittest.main()
