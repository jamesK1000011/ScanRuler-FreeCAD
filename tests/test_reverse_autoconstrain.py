# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/tests/reAutoConstrain.test.ts
# SPDX-License-Identifier: AGPL-3.0-only
#
# Auto Constrain: a plane or a cylinder fitted to scan points, held to the
# part's coordinate planes and measured references where it nearly is so.
import math
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from scanrulerfc.linalg import mulberry32  # noqa: E402
from scanrulerfc.reverse.autoconstrain import COINCIDENCE_MM, constrain_cylinder, constrain_plane, fit_cylinder_free, relation_words  # noqa: E402


def gaussian(rand):
    u = 0
    while u == 0:
        u = rand()
    return math.sqrt(-2 * math.log(u)) * math.cos(2 * math.pi * rand())


def rad(d):
    return d * math.pi / 180


def norm(v):
    v = np.asarray(v, dtype=float)
    return v / np.linalg.norm(v)


def angle_deg(a, b):
    return math.acos(min(1, abs(float(np.dot(a, b))))) * 180 / math.pi


def _frame(n):
    u = norm(np.cross(n, [1, 0, 0] if abs(n[0]) < 0.9 else [0, 1, 0]))
    return u, np.cross(n, u)


def plane_patch(origin, normal, noise=0.02, seed=3):
    rand = mulberry32(seed)
    n = norm(normal)
    u, v = _frame(n)
    out = []
    for i in range(41):
        for j in range(31):
            a, b, e = i - 20, j - 15, gaussian(rand) * noise
            out += list(np.asarray(origin) + a * u + b * v + e * n)
    return np.array(out, dtype=np.float32)


def cylinder_patch(origin, axis, radius, span=120, noise=0.02, seed=5):
    rand = mulberry32(seed)
    d = norm(axis)
    u, v = _frame(d)
    out = []
    for i in range(61):
        for j in range(31):
            a, t, r = rad((i / 60) * span), j - 15, radius + gaussian(rand) * noise
            out += list(np.asarray(origin) + t * d + r * (math.cos(a) * u + math.sin(a) * v))
    return np.array(out, dtype=np.float32)


XY = {"key": "datum:xy", "kind": "plane", "name": "XY plane", "origin": [0, 0, 0], "normal": [0, 0, 1]}
YZ = {"key": "datum:yz", "kind": "plane", "name": "YZ plane", "origin": [0, 0, 0], "normal": [1, 0, 0]}
ZX = {"key": "datum:zx", "kind": "plane", "name": "ZX plane", "origin": [0, 0, 0], "normal": [0, 1, 0]}
DATUMS = [XY, YZ, ZX]
AUTO = {"mode": "auto"}


def close(tc, a, b, digits=2):
    tc.assertLess(abs(a - b), 10 ** -digits / 2)


class Plane(unittest.TestCase):
    def test_level_within_tolerance(self):
        tilted = [math.sin(rad(0.3)), 0, math.cos(rad(0.3))]
        fit = constrain_plane(plane_patch([5, 5, 12], tilted), DATUMS, AUTO)
        self.assertEqual(fit["normal"], [0, 0, 1])
        close(self, fit["origin"][2], 12)
        self.assertEqual(len(fit["relations"]), 1)
        self.assertEqual((fit["relations"][0]["relation"], fit["relations"][0]["ref"]), ("along", "datum:xy"))
        close(self, fit["relations"][0]["tiltDeg"], 0.3, 1)
        self.assertGreater(fit["rms"], fit["rmsFree"])
        self.assertLess(fit["rms"], 0.1)

    def test_keeps_facing(self):
        fit = constrain_plane(plane_patch([0, 0, -8], [0.002, 0, -1]), DATUMS, AUTO)
        self.assertEqual(abs(fit["normal"][2]), 1)

    def test_two_degrees_left_as_fitted(self):
        tilted = [math.sin(rad(2)) * math.cos(rad(40)), math.sin(rad(2)) * math.sin(rad(40)), math.cos(rad(2))]
        fit = constrain_plane(plane_patch([0, 0, 12], tilted), DATUMS, AUTO)
        self.assertEqual(fit["relations"], [])
        self.assertLess(angle_deg(fit["normal"], tilted), 0.05)
        self.assertEqual(fit["rms"], fit["rmsFree"])

    def test_coincident_within_a_millimetre(self):
        floor = {"key": "element:4", "kind": "plane", "name": "Plane 4", "origin": [0, 0, 12.4], "normal": [0, 0, 1]}
        fit = constrain_plane(plane_patch([60, 0, 12], [0.003, 0, 1]), [floor], AUTO)
        self.assertEqual((fit["relations"][0]["relation"], fit["relations"][0]["ref"]), ("on", "element:4"))
        close(self, fit["relations"][0]["shiftMm"], 0.4, 1)
        close(self, fit["origin"][2], 12.4, 6)
        apart = constrain_plane(plane_patch([60, 0, 12 - COINCIDENCE_MM - 0.5], [0.003, 0, 1]), [floor], AUTO)
        self.assertEqual(apart["relations"][0]["relation"], "along")

    def test_first_names_relation_coincident_still_found(self):
        step = {"key": "element:9", "kind": "plane", "name": "Plane 9", "origin": [0, 0, 12.3], "normal": [0, 0, 1]}
        far = constrain_plane(plane_patch([0, 0, 40], [0.002, 0, 1]), [XY, step], AUTO)
        self.assertEqual((far["relations"][0]["relation"], far["relations"][0]["ref"]), ("along", "datum:xy"))
        beside = constrain_plane(plane_patch([0, 0, 12], [0.002, 0, 1]), [XY, step], AUTO)
        self.assertEqual((beside["relations"][0]["relation"], beside["relations"][0]["ref"]), ("on", "element:9"))
        close(self, beside["origin"][2], 12.3, 6)

    def test_wall_made_square(self):
        lean = rad(0.35)
        upright = [math.cos(rad(25)), math.sin(rad(25)), 0]
        leaning = [upright[0] * math.cos(lean), upright[1] * math.cos(lean), math.sin(lean)]
        fit = constrain_plane(plane_patch([10, 10, 5], leaning), [XY], AUTO)
        self.assertEqual(len(fit["relations"]), 1)
        self.assertEqual((fit["relations"][0]["relation"], fit["relations"][0]["ref"]), ("across", "datum:xy"))
        self.assertLess(abs(fit["normal"][2]), 1e-9)
        self.assertLess(angle_deg(fit["normal"], upright), 0.05)

    def test_square_to_two(self):
        almost_y = norm([math.sin(rad(0.4)), 1, math.sin(rad(0.3))])
        fit = constrain_plane(plane_patch([0, 20, 0], almost_y), [XY, YZ], AUTO)
        self.assertEqual(sorted(r["ref"] for r in fit["relations"]), ["datum:xy", "datum:yz"])
        self.assertLess(angle_deg(fit["normal"], [0, 1, 0]), 1e-6)

    def test_forced_and_free(self):
        tilted = [math.sin(rad(4)), 0, math.cos(rad(4))]
        points = plane_patch([0, 0, 12], tilted)
        forced = constrain_plane(points, DATUMS, {"mode": "force", "relation": "along", "ref": "datum:xy"})
        self.assertEqual(forced["normal"], [0, 0, 1])
        close(self, forced["relations"][0]["tiltDeg"], 4, 1)
        on = constrain_plane(points, DATUMS, {"mode": "force", "relation": "on", "ref": "datum:xy"})
        close(self, on["origin"][2], 0, 9)
        level = constrain_plane(plane_patch([0, 0, 12], [0.001, 0, 1]), DATUMS, {"mode": "free"})
        self.assertEqual(level["relations"], [])
        self.assertNotEqual(level["normal"][2], 1)

    def test_no_plane_through_a_line(self):
        line = np.zeros(30, dtype=np.float32)
        for i in range(10):
            line[i * 3] = i
        self.assertIsNone(constrain_plane(line, DATUMS, AUTO))


class Cylinder(unittest.TestCase):
    def test_third_of_a_cylinder(self):
        axis = norm([0.3, -0.2, 1])
        c = fit_cylinder_free(cylinder_patch([4, 5, 6], axis, 8))
        close(self, c["r"], 8, 1)
        self.assertLess(angle_deg([c["ax"], c["ay"], c["az"]], axis), 0.2)

    def test_bore_made_upright(self):
        axis = [math.sin(rad(0.3)), 0, math.cos(rad(0.3))]
        fit = constrain_cylinder(cylinder_patch([10, -4, 0], axis, 6, 200), DATUMS, AUTO)
        self.assertEqual(angle_deg(fit["axis"], [0, 0, 1]), 0)
        close(self, fit["radius"], 6, 1)
        close(self, fit["origin"][0], 10, 1)
        close(self, fit["origin"][1], -4, 1)
        r = fit["relations"][0]
        self.assertEqual((r["relation"], r["ref"], r["refKind"]), ("along", "datum:xy", "plane"))
        self.assertEqual(relation_words("cylinder", "along", "plane"), "Perpendicular to")

    def test_takes_reference_axis(self):
        bore = {"key": "surface:3", "kind": "axis", "name": "Surface 3", "origin": [10.3, -4.2, 40], "dir": [0, 0, 1]}
        fit = constrain_cylinder(cylinder_patch([10, -4, 0], [0.002, 0, 1], 9, 240), [bore], AUTO)
        self.assertEqual((fit["relations"][0]["relation"], fit["relations"][0]["ref"]), ("on", "surface:3"))
        close(self, fit["relations"][0]["shiftMm"], math.hypot(0.3, 0.2), 1)
        close(self, fit["origin"][0], 10.3, 6)
        close(self, fit["origin"][1], -4.2, 6)
        self.assertLess(abs(fit["radius"] - 9), 0.36)
        self.assertGreater(fit["rms"], fit["rmsFree"])

    def test_axis_laid_into_plane(self):
        axis = norm([math.cos(rad(30)), math.sin(rad(30)), math.sin(rad(0.4))])
        fit = constrain_cylinder(cylinder_patch([0, 0, 10], axis, 5, 180), [XY], AUTO)
        self.assertEqual((fit["relations"][0]["relation"], fit["relations"][0]["ref"]), ("across", "datum:xy"))
        self.assertLess(abs(fit["axis"][2]), 1e-9)
        self.assertEqual(relation_words("cylinder", "across", "plane"), "Parallel to")


if __name__ == "__main__":
    unittest.main()
