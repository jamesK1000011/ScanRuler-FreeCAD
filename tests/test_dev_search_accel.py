# SPDX-License-Identifier: AGPL-3.0-only
"""The normal large-reference route and its exact-search fallbacks."""
import unittest
from unittest.mock import patch

import numpy as np

from meshes import box_mesh
from scanrulerfc.dev_surface import NominalSurface
from scanrulerfc import dev_search_accel as accel


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
