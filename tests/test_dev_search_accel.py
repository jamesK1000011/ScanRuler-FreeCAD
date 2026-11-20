# SPDX-License-Identifier: AGPL-3.0-only
"""The normal large-reference route and its exact-search fallbacks."""
import unittest
from unittest.mock import patch

import numpy as np

from meshes import box_mesh
from scanrulerfc.dev_surface import NominalSurface
from scanrulerfc import dev_search_accel as accel
from scanrulerfc import dev_surface


class AcceleratedSearch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        V, F = box_mesh(20, 24)
        cls.surface = NominalSurface(V, F)
        rng = np.random.default_rng(918)
        cls.points = rng.uniform(-16, 16, (512, 3))
        cls.normals = rng.normal(size=(512, 3))
        cls.normals /= np.linalg.norm(cls.normals, axis=1)[:, None]

    def original(self, points, cap=np.inf, facing=None, min_dot=None):
        with patch.object(self.surface, "_search", self.surface._search_original):
            return self.surface.closest(points, cap, facing, min_dot)

    def same(self, a, b):
        np.testing.assert_array_equal(a.found, b.found)
        np.testing.assert_allclose(a.distance[a.found], b.distance[b.found], atol=1e-10, rtol=1e-12)
        np.testing.assert_allclose(a.signed[a.found], b.signed[b.found], atol=1e-10, rtol=1e-12)

    def test_large_reference_uses_acceleration(self):
        if accel._KDTree is None:
            self.skipTest("scipy unavailable")
        self.assertGreaterEqual(self.surface.triangle_count, 4096)
        a = self.original(self.points)
        with patch.object(accel, "search", wraps=accel.search) as used:
            b = self.surface.closest(self.points)
        self.assertTrue(used.called)
        self.same(a, b)

    def test_caps_and_facing_match_original(self):
        for cap, facing, dot in [(0., None, None), (1., None, None), (10., self.normals, .3), (np.inf, self.normals, -.1)]:
            with self.subTest(cap=cap, facing=dot):
                self.same(self.original(self.points, cap, facing, dot), self.surface.closest(self.points, cap, facing, dot))

    def test_without_scipy_uses_original(self):
        a = self.original(self.points)
        with patch.object(accel, "_KDTree", None), patch.object(self.surface, "_search_original", wraps=self.surface._search_original) as used:
            b = self.surface.closest(self.points)
        self.assertTrue(used.called)
        self.same(a, b)

    def test_frontier_limit_retains_exact_result(self):
        a = self.original(self.points)
        with patch.object(accel, "_MAX_FRONTIER", 0), patch.object(self.surface, "_search_original", wraps=self.surface._search_original) as used:
            b = self.surface.closest(self.points)
        self.assertTrue(used.called)
        self.same(a, b)

    def test_facing_seed_miss_searches_other_surface(self):
        points = np.array([[11., 0., 0.]])
        normals = np.array([[-1., 0., 0.]])
        a = self.original(points, np.inf, normals, .9)
        with patch.object(self.surface, "_search_original", wraps=self.surface._search_original) as used:
            b = self.surface.closest(points, np.inf, normals, .9)
        self.assertTrue(used.called)
        self.assertTrue(b.found[0])
        self.same(a, b)

    def test_empty_and_exact_surface_queries(self):
        self.assertEqual(len(self.surface.closest(np.empty((0, 3))).found), 0)
        points = np.array([[10., 0., 0.], [10., 10., 0.], [10., 10., 10.]])
        self.same(self.original(points), self.surface.closest(points))

    def test_nonfinite_queries_keep_original_unmeasured_behavior(self):
        points = np.array([[np.nan, 0., 0.], [np.inf, 0., 0.], [11., 0., 0.]])
        a = self.original(points)
        b = self.surface.closest(points)
        np.testing.assert_array_equal(b.found, [False, False, True])
        self.same(a, b)

    def test_query_batches_also_bound_fallback_calls(self):
        a = self.original(self.points)
        with patch.object(accel, "_QUERY_BATCH", 16), patch.object(accel, "_KDTree", None), \
                patch.object(self.surface, "_search_original", wraps=self.surface._search_original) as used:
            b = self.surface.closest(self.points)
        self.assertGreater(used.call_count, 1)
        self.assertLessEqual(max(len(c.args[0]) for c in used.call_args_list), 16)
        self.same(a, b)

    def test_hit_resolution_is_bounded(self):
        a = self.original(self.points)
        with patch.object(dev_surface, "_HIT_BATCH", 64), \
                patch.object(self.surface, "_fill", wraps=self.surface._fill) as used:
            b = self.surface.closest(self.points)
        self.assertGreater(used.call_count, 1)
        self.assertLessEqual(max(len(c.args[1]) for c in used.call_args_list), 64)
        self.same(a, b)

    def test_hints_keep_upstream_bound_search_without_extra_index(self):
        a = self.original(self.points)
        for hint in (a.face, np.full(len(self.points), -1), np.zeros(len(self.points), dtype=np.int64)):
            with self.subTest(hint=int(hint[0])):
                with patch.object(accel, "search", side_effect=AssertionError("hinted queries must use upstream search")):
                    b = self.surface.closest(self.points, hint=hint)
                self.same(a, b)
        a = self.original(self.points, 10., self.normals, .3)
        b = self.surface.closest(self.points, 10., self.normals, .3,
                                 hint=np.zeros(len(self.points), dtype=np.int64))
        self.same(a, b)

    def test_automatic_guesses_keep_upstream_path_and_bounded_hits(self):
        points = np.tile(self.points, (5, 1))
        a = self.original(points)
        with patch.object(accel, "search", side_effect=AssertionError("automatic hints must use upstream search")), \
                patch.object(dev_surface, "_HIT_BATCH", 64), \
                patch.object(self.surface, "_fill", wraps=self.surface._fill) as used:
            b = self.surface.closest(points)
        self.assertLessEqual(max(len(c.args[1]) for c in used.call_args_list), 64)
        self.same(a, b)

    def test_hinted_preparation_is_bounded(self):
        a = self.original(self.points)
        with patch.object(dev_surface, "_HIT_BATCH", 64), \
                patch.object(self.surface, "_hinted_batch", wraps=self.surface._hinted_batch) as prepared, \
                patch.object(self.surface, "_search_original", wraps=self.surface._search_original) as searched:
            b = self.surface.closest(self.points, hint=a.face)
        self.assertGreater(prepared.call_count, 1)
        self.assertLessEqual(max(len(c.args[0]) for c in prepared.call_args_list), 64)
        self.assertTrue(searched.called)
        self.same(a, b)
