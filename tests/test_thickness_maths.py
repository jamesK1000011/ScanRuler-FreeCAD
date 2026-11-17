# SPDX-License-Identifier: AGPL-3.0-only
# Wall thickness maths alone, numpy only. Ported from ScanRuler's
# tests/thickness.test.ts.
import math
import os
import sys
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

import synth  # noqa: E402
from meshes import box_mesh, hollow_box  # noqa: E402
from scanrulerfc.dev_map import vertex_normals  # noqa: E402
from scanrulerfc.dev_surface import NominalSurface  # noqa: E402
from scanrulerfc.wall_thickness import compute_thickness, fill_from_neighbours, sample_points, suggest_thickness_scale, thickness_stats  # noqa: E402


def measure(V, F, **opts):
    s = NominalSurface(V, F)
    N = vertex_normals(V, F)
    diag = s.bbox_diagonal
    o = dict(method="ray", cone_rays=0, cone_angle=math.radians(30), max_normal_deviation=None, max_thickness=diag, epsilon=diag * 1e-5)
    o.update(opts)
    return compute_thickness(s, V, N, **o), N


def flat(N):
    return np.nonzero(np.abs(N).max(axis=1) > 0.999)[0]


class WallThickness(unittest.TestCase):
    def test_solid_block_full_width(self):
        V, F = box_mesh(20, 6)
        v, N = measure(V, F)
        f = flat(N)
        self.assertGreater(len(f), 100)
        np.testing.assert_allclose(v[f], 20, atol=1e-3)

    def test_hollow_box_wall_not_cavity(self):
        V, F = hollow_box(20, 4, (5, 4))
        v, N = measure(V, F)
        f = flat(N)
        self.assertGreater(len(f), 100)
        np.testing.assert_allclose(v[f], 4, atol=1e-3)

    def test_nothing_behind_is_unmeasured(self):
        V, F = box_mesh(20, 4)
        v, _ = measure(V, F[:1])
        used = np.unique(F[:1])
        self.assertTrue(np.isnan(v[used]).all())

    def test_refuses_a_wall_thicker_than_searched(self):
        V, F = box_mesh(20, 4)
        v, _ = measure(V, F, max_thickness=8)
        self.assertTrue(np.isnan(v).all())
        v, _ = measure(V, F, max_thickness=25)
        self.assertTrue((np.abs(v - 20) < 1e-3).any())

    def test_cone_never_longer(self):
        V, F = box_mesh(20, 5)
        single, _ = measure(V, F)
        cone, _ = measure(V, F, cone_rays=6)
        self.assertTrue((cone <= single + 1e-4).all())
        self.assertGreater((cone < single - 1e-4).sum(), 0)

    def test_cone_does_not_escape_with_facing(self):
        V, F = box_mesh(20, 5)
        v, N = measure(V, F, cone_rays=6, cone_angle=math.radians(22), max_normal_deviation=math.radians(60))
        f = flat(N)
        self.assertGreater(len(f), 50)
        np.testing.assert_allclose(v[f], 20, atol=1e-3)

    def test_sphere_across_the_wall_never_wider(self):
        V, F = hollow_box(20, 4, (5, 4))
        ray, _ = measure(V, F)
        sph, N = measure(V, F, method="sphere")
        f = flat(N)
        np.testing.assert_allclose(sph[f], 4, atol=1e-2)
        ok = ~np.isnan(ray)
        self.assertTrue((sph[ok] <= ray[ok] + 1e-4).all())

    def test_block_at_its_edges(self):
        V, F = box_mesh(20, 4)
        ray, N = measure(V, F)
        sph, _ = measure(V, F, method="sphere")
        edges = []
        for i, n in enumerate(N):
            zero = np.nonzero(np.abs(n) < 1e-6)[0]
            if len(zero) != 1 or (np.abs(n) > 0.6).sum() != 2:
                continue
            if abs(V[i, zero[0]]) < 1e-6:
                edges.append(i)
        self.assertEqual(len(edges), 12)
        np.testing.assert_allclose(ray[edges], 20 * math.sqrt(2), atol=1e-2)
        np.testing.assert_allclose(sph[edges], 20, atol=1e-2)

    def test_stats_and_scale(self):
        s = thickness_stats(np.array([0.8, 1.2, 2, np.nan, 0.5]), 1)
        self.assertEqual((s["measured"], s["total"], s["belowLimit"]), (4, 5, 2))
        self.assertAlmostEqual(s["min"], 0.5)
        self.assertAlmostEqual(s["mean"], (0.8 + 1.2 + 2 + 0.5) / 4)
        v = np.concatenate([np.full(1000, 3.0), [80.0] * 10])
        low, high = suggest_thickness_scale(v)
        self.assertLess(high, 10)



def shell(n=60, r_out=40.0, r_in=37.0):
    """A spherical shell 3 mm thick (open round the poles), outer side out."""
    Vo, Fo = synth.sphere(r=r_out, n=n, m=n // 2, cap=0.9)
    Vi, Fi = synth.sphere(r=r_in, n=n, m=n // 2, cap=0.9)
    return np.r_[Vo, Vi], np.r_[Fo[:, ::-1], Fi + len(Vo)]


class Speed(unittest.TestCase):
    def same_first_hits(self, s, O, D, near, far):
        """The grid's first hits are the leaf-ordered search's: the same
        rays hit, at the same distance (to rounding: a ray through an edge
        two triangles share reads t off either), the same face unless the
        ray meets both at once."""
        t, f = s.raycast_first(O, D, near, far)
        t0, f0 = s.raycast_first_leaves(O, D, near, far)
        np.testing.assert_array_equal(f >= 0, f0 >= 0)
        hit = f >= 0
        np.testing.assert_allclose(t[hit], t0[hit], rtol=0, atol=1e-9)
        differ = np.nonzero(hit & (f != f0))[0]
        if len(differ):
            from scanrulerfc.dev_surface import _moller_trumbore

            other = _moller_trumbore(O[differ], D[differ], s.A[f0[differ]], s.B[f0[differ]], s.C[f0[differ]])
            np.testing.assert_allclose(other, t[differ], rtol=0, atol=1e-9)  # both met at once
        return t, f

    def test_the_grid_hits_what_every_leaf_would(self):
        V, F = shell(70)
        s = NominalSurface(V, F)
        rng = np.random.default_rng(3)
        O = V[rng.choice(len(V), 900, replace=False)] + rng.normal(0, 0.2, (900, 3))
        D = rng.normal(size=(900, 3))
        D /= np.linalg.norm(D, axis=1)[:, None]
        far = rng.uniform(1, 30, 900)
        t, f = self.same_first_hits(s, O, D, np.full(900, 1e-4), far)
        self.assertGreater((f >= 0).sum(), 100)
        # Unbounded rays, rays that are not unit vectors, rays from outside.
        self.same_first_hits(s, O, D, np.full(900, 1e-4), np.full(900, np.inf))
        self.same_first_hits(s, O * 3, -O * 0.37 + D, np.zeros(900), np.full(900, 5.0))

    def test_the_grid_on_inward_rays_from_the_vertices(self):
        # What wall thickness casts: from each vertex along its inward
        # normal, on a solid block, a box with a cavity and a noisy sphere.
        cases = [box_mesh(20, 12), hollow_box(30.0, 3.0), synth.sphere(sigma=0.02), box_mesh(20, 1)]
        for V, F in cases:
            V, F = np.asarray(V, float), np.asarray(F)
            s = NominalSurface(V, F)
            N = vertex_normals(V, F)
            n = len(V)
            for far in (0.3 * s.bbox_diagonal, np.inf):
                self.same_first_hits(s, V, -N, np.full(n, 1e-6), np.full(n, far))
                self.same_first_hits(s, V, N, np.full(n, 1e-6), np.full(n, far))

    def test_a_large_triangle_among_small_ones_stays_out_of_the_cells(self):
        V, F = box_mesh(10, 20)
        V, F = np.asarray(V, float), np.asarray(F)
        V2 = np.vstack([V, [[-200, -200, -50], [200, -200, 60], [0, 300, 10]]])
        F2 = np.vstack([F, [[len(V), len(V) + 1, len(V) + 2]]])
        s = NominalSurface(V2, F2)
        self.assertEqual(list(s._ray_grid()["big"]), [len(F)])
        rng = np.random.default_rng(4)
        O = rng.uniform(-60, 60, (600, 3))
        D = rng.normal(size=(600, 3))
        D[:300] = -O[:300] + rng.normal(0, 2.0, (300, 3))  # half of them aimed at the small box
        t, f = self.same_first_hits(s, O, D, np.zeros(600), np.full(600, np.inf))
        self.assertGreater((f == len(F)).sum(), 20)  # the large one is hit too
        self.assertGreater(((f >= 0) & (f < len(F))).sum(), 5)

    def test_a_dense_block_with_long_rays_is_quick(self):
        # Found live (run 2): thickness_measure { maxThickness: 25,
        # maxPoints: 20000 } on a 219,600-triangle 60 x 40 x 20 block took
        # 221 s: every run of rays was tried against every leaf its 25 mm
        # sweep touched. The same reading here: 66 s before the grid.
        import time

        sys.path.insert(0, HERE)
        from meshkit import box_mesh as sized_box

        V, F = sized_box(60.0, 40.0, 20.0, n=135)
        V, F = np.asarray(V, float), np.asarray(F)
        self.assertGreater(len(F), 200_000)
        s = NominalSurface(V, F)
        N = vertex_normals(V, F)
        idx = sample_points(len(V), 20000)
        t0 = time.time()
        v = compute_thickness(s, V[idx], N[idx], max_thickness=25.0, max_normal_deviation=math.radians(60))
        took = time.time() - t0
        self.assertLess(took, 20)  # under a second here
        on_top = np.abs(N[idx][:, 2]) > 0.999
        np.testing.assert_allclose(v[on_top], 20.0, atol=1e-9)  # top to bottom
        self.assertTrue(np.isnan(v[np.abs(N[idx][:, 0]) > 0.999]).all())  # 60 mm across: past the 25 searched
        # and the same numbers as the leaf search gives, on a part of them
        part = idx[::40]
        t, f = s.raycast_first(V[part], -N[part], 1e-6, 25.0)
        t1, f1 = s.raycast_first_leaves(V[part], -N[part], 1e-6, 25.0)
        np.testing.assert_array_equal(f >= 0, f1 >= 0)
        np.testing.assert_allclose(t[f >= 0], t1[f1 >= 0], rtol=0, atol=1e-9)

    def test_a_shell_reads_its_wall_quickly(self):
        import time

        V, F = shell(160)
        t0 = time.time()
        v, _ = measure(V, F, max_thickness=10, max_normal_deviation=math.radians(60))
        took = time.time() - t0
        self.assertGreater(np.isfinite(v).mean(), 0.95)
        np.testing.assert_allclose(np.nanmedian(v), 3, atol=1e-3)
        # 50k triangles: under a second here, ~7 s before the rays went in
        # runs against the leaves near them; generous for a slow runner.
        self.assertLess(took, 6)

    def test_sampled_and_filled(self):
        V, F = shell(60)
        n = len(V)
        idx = sample_points(n, n // 3)
        self.assertEqual(len(idx), n // 3)
        self.assertIsNone(sample_points(n, 0))
        self.assertIsNone(sample_points(n, n))
        full, _ = measure(V, F, max_thickness=10, max_normal_deviation=math.radians(60))
        filled = fill_from_neighbours(n, idx, full[idx], F)
        np.testing.assert_array_equal(filled[idx], full[idx])
        ok = np.isfinite(full)
        self.assertGreater(np.isfinite(filled[ok]).mean(), 0.97)
        np.testing.assert_allclose(np.nanmedian(filled), 3, atol=1e-3)
        # Never thicker than the thinnest neighbour measured.
        v = np.array([5.0, 1.0, np.nan])
        out = fill_from_neighbours(4, np.array([0, 1, 3]), v, np.array([[0, 1, 2], [2, 3, 0]]))
        self.assertEqual(out[2], 1.0)
        self.assertTrue(np.isnan(out[3]))


class SampledThroughTheTool(unittest.TestCase):
    def test_max_points_samples_and_says_so(self):
        from scanrulerfc import scanstate as S
        from scanrulerfc.handlers import thickness as T

        class Session:
            def __init__(self):
                self.family_state = {}

        V, F = shell(60)
        se = Session()
        S.state(se)["scan"] = S.Scan("shell", V, F)
        h = T.bind(se)
        whole = h["thickness_measure"]({"maxThickness": 10, "maxPoints": 0})
        self.assertNotIn("sampled", whole["thickness"])
        part = h["thickness_measure"]({"maxPoints": 2000})
        self.assertEqual(part["thickness"]["sampled"]["points"], 2000)
        self.assertEqual(part["thickness"]["sampled"]["of"], len(V))
        self.assertEqual(part["thickness"]["stats"]["total"], 2000)
        self.assertEqual(part["thickness"]["settings"]["maxPoints"], 2000)
        self.assertIn("2000 of %d scan points measured" % len(V), part["report"])
        self.assertAlmostEqual(part["thickness"]["stats"]["mean"], whole["thickness"]["stats"]["mean"], delta=0.05)
        self.assertEqual(len(T.tstate(se)["values"]), len(V))


if __name__ == "__main__":
    unittest.main()
