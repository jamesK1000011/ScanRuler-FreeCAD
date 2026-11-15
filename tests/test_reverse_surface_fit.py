# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/tests/reSurfaceFit.test.ts, reSurfaceNormal.test.ts, reSurfaceRunaway.test.ts (their kernel-free cases)
# SPDX-License-Identifier: AGPL-3.0-only
#
# The B-spline pieces; a tilted plane, a cylinder patch and a saddle
# recovered within the noise; a net too fine faired; the grid for the
# kernel on the fit; a height direction of the fit's own; the pull toward
# the plane holding a patchy region's empty corners and moving a curved
# patch by under the noise; a fit that runs away refused, naming where and
# what it was fitted along. The kernel's surface and its mesh wait for it.
import math
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from scanrulerfc.reverse.surface_fit import (DEFAULT_SURFACE_FIT, NET_MAX, NET_MIN, PULL, auto_net, basis_functions, clamped_knots, eval_surface,  # noqa: E402
                                             find_span, fit_surface, fit_surface_reported, greville, grid_of, height_frame, run_away)

KERNEL = "kernel (step 3) not ported"


def noise(seed):
    s = [seed & 0xFFFFFFFF]

    def nxt():
        s[0] = (s[0] * 1664525 + 1013904223) & 0xFFFFFFFF
        a = s[0] / 4294967296
        s[0] = (s[0] * 1664525 + 1013904223) & 0xFFFFFFFF
        b = s[0] / 4294967296
        return math.sqrt(-2 * math.log(a + 1e-12)) * math.cos(2 * math.pi * b)

    return nxt


def steps(lo, hi, step):
    x = lo
    while x <= hi:
        yield x
        x += step


def sample(f, w, h, step, sigma, seed=1):
    rnd = noise(seed)
    a = 0.6
    R = [[math.cos(a), -math.sin(a) * 0.8, math.sin(a) * 0.6], [math.sin(a), math.cos(a) * 0.8, -math.cos(a) * 0.6], [0, 0.6, 0.8]]

    def turn(x, y, z):
        return [R[0][0] * x + R[0][1] * y + R[0][2] * z + 5, R[1][0] * x + R[1][1] * y + R[1][2] * z - 3, R[2][0] * x + R[2][1] * y + R[2][2] * z + 11]

    def back(p):
        x, y, z = p[0] - 5, p[1] + 3, p[2] - 11
        return [R[0][0] * x + R[1][0] * y + R[2][0] * z, R[0][1] * x + R[1][1] * y + R[2][1] * z, R[0][2] * x + R[1][2] * y + R[2][2] * z]

    pts = []
    for x in steps(-w / 2, w / 2, step):
        for y in steps(-h / 2, h / 2, step):
            jx = x + rnd() * step * 0.2
            jy = y + rnd() * step * 0.2
            pts += turn(jx, jy, f(jx, jy) + rnd() * sigma)

    def truth(p):
        q = back(p)
        return f(q[0], q[1]) - q[2]

    return np.asarray(pts, dtype=np.float32), truth


def worst_error(fit, truth, shrink):
    u0, u1 = fit["uRange"]
    v0, v1 = fit["vRange"]
    mu, mv = (u1 - u0) * shrink, (v1 - v0) * shrink
    worst = 0
    for i in range(21):
        for j in range(21):
            p = eval_surface(fit, u0 + mu + ((u1 - u0 - 2 * mu) * i) / 20, v0 + mv + ((v1 - v0 - 2 * mv) * j) / 20)
            worst = max(worst, abs(truth(p)))
    return worst


def net(n):
    return {**DEFAULT_SURFACE_FIT, "net": {"u": n, "v": n}}


class Pieces(unittest.TestCase):
    def test_knots_greville_unity(self):
        knots = clamped_knots(6, 3, 0, 10)
        self.assertEqual([math.floor(k * 1000 + 0.5) / 1000 for k in knots], [0, 0, 0, 0, 3.333, 6.667, 10, 10, 10, 10])
        g = greville(knots, 6, 3)
        self.assertEqual((g[0], g[5]), (0, 10))
        for t in (0, 2.5, 5, 7.5, 10):
            b = basis_functions(knots, find_span(knots, 6, 3, t), 3, t)
            self.assertAlmostEqual(sum(b), 1, 12)

    def test_auto_net(self):
        self.assertEqual(auto_net(80, 40, 1), {"u": 10, "v": 5})
        self.assertEqual(auto_net(2, 2, 1), {"u": NET_MIN, "v": NET_MIN})
        self.assertEqual(auto_net(1000, 1000, 1), {"u": NET_MAX, "v": NET_MAX})


class Fit(unittest.TestCase):
    def test_tilted_plane(self):
        xyz, truth = sample(lambda x, y: 0, 40, 30, 1, 0.02)
        fit = fit_surface(xyz, DEFAULT_SURFACE_FIT)
        self.assertLess(fit["rms"], 0.03)
        self.assertLess(worst_error(fit, truth, 0.15), 0.01)
        span = fit["uRange"][1] - fit["uRange"][0]
        self.assertGreater(span, 40 * 1.3)
        self.assertLess(span, 40 * 1.4)

    def test_cylinder_and_saddle(self):
        R = 30
        xyz, truth = sample(lambda x, y: math.sqrt(R * R - x * x) - R, 30, 20, 0.5, 0.02, 7)
        f1 = fit_surface(xyz, {**DEFAULT_SURFACE_FIT, "net": {"u": 8, "v": 4}}, 0.02)
        self.assertLess(f1["rms"], 0.03)
        self.assertLess(worst_error(f1, truth, 0.15), 0.015)
        xyz, truth = sample(lambda x, y: (x * x - y * y) / 80, 40, 40, 1, 0.02, 3)
        f2 = fit_surface(xyz, DEFAULT_SURFACE_FIT)
        self.assertLess(f2["rms"], 0.03)
        self.assertLess(worst_error(f2, truth, 0.15), 0.03)
        self.assertGreater(f2["net"]["u"], NET_MIN + 2)

    def test_fairing_and_grid(self):
        xyz, truth = sample(lambda x, y: 0, 20, 20, 2, 0.05, 11)
        fit = fit_surface(xyz, {**DEFAULT_SURFACE_FIT, "net": {"u": 20, "v": 20}, "smoothness": 0.05}, 0.05)
        self.assertLess(worst_error(fit, truth, 0.15), 0.1)
        grid = grid_of(fit)
        self.assertEqual(grid["rows"], 19 * 3 + 1)
        self.assertEqual(len(grid["points"]), grid["rows"] * grid["cols"] * 3)
        q = eval_surface(fit, fit["uRange"][0], fit["vRange"][0])
        for a, b in zip(grid["points"][:3], q):
            self.assertAlmostEqual(float(a), b, 9)

    def test_too_few(self):
        with self.assertRaisesRegex(ValueError, "Too few"):
            fit_surface(np.zeros(6, dtype=np.float32), DEFAULT_SURFACE_FIT)


def patch(f, w, h, step, wiggle=0.0):
    pts = []
    for x in steps(-w / 2, w / 2, step):
        for y in steps(-h / 2, h / 2, step):
            pts += [x, y, f(x, y) + wiggle * math.sin(7 * x + 3 * y)]
    return np.asarray(pts, dtype=float)


class HeightDirection(unittest.TestCase):
    def test_plane_square_to_the_direction(self):
        u, v, n = height_frame([[0.8, 0, 0.6], [0, 1, 0], [-0.6, 0, 0.8]], [0, 0, 2])
        self.assertEqual(n, [0, 0, 1])
        self.assertAlmostEqual(sum(a * b for a, b in zip(u, n)), 0, 12)
        self.assertAlmostEqual(u[0], 1, 12)
        for a, b in zip(v, [0, 1, 0]):
            self.assertAlmostEqual(a, b, 12)
        self.assertEqual(height_frame([[1, 0, 0], [0, 1, 0], [0, 0, 1]]), [[1, 0, 0], [0, 1, 0], [0, 0, 1]])
        self.assertEqual(height_frame([[1, 0, 0], [0, 1, 0], [0, 0, 1]], [0, 0, 0])[2], [0, 0, 1])

    def test_hump_on_a_slope(self):
        xyz = patch(lambda x, y: 0.5 * x + 4 * math.exp(-(x * x + y * y) / 150), 40, 30, 0.5)
        leaning = fit_surface(xyz, net(12), 0.01)
        self.assertLess(abs(leaning["normal"][2]), 0.95)
        along = fit_surface(xyz, {**net(12), "normal": [0, 0, 5]}, 0.01)
        self.assertEqual(along["normal"], [0, 0, 1])
        self.assertLess(along["rms"], 0.02)

    def test_runaway_says_what_it_was_fitted_along(self):
        xyz = patch(lambda x, y: 0, 20, 20, 0.5)
        fit = fit_surface(xyz, net(20), 0.01, 0)
        fit["heights"][0] = 500
        said = run_away(fit, xyz, DEFAULT_SURFACE_FIT["expandPct"])
        self.assertRegex(said, r"Its height direction was \[-?0, -?0, -?1\] \(the region’s principal normal\); 95 % of the region’s normals are within 0° of it\.")
        self.assertRegex(said, r"Fit a coarser net, .* or take less margin — or give fit\.normal, the way the region faces, for its height direction\.$")
        self.assertRegex(run_away(fit, xyz, DEFAULT_SURFACE_FIT["expandPct"], [0, 0, 1]), r"\(fit\.normal\);.* or take less margin\.$")

    def test_region_bending_round(self):
        pts = []
        for a in range(-100, 101, 2):
            for y in steps(-20, 20, 0.5):
                pts += [15 * math.sin((a * math.pi) / 180), y, 15 * math.cos((a * math.pi) / 180)]
        xyz = np.asarray(pts)
        fit = fit_surface(xyz, net(20), 0.01, 0)
        fit["heights"][0] = 1e4
        said = run_away(fit, xyz, DEFAULT_SURFACE_FIT["expandPct"])
        self.assertRegex(said, r"95 % of the region’s normals are within (\d+)° of it\. The region bends round past what one height field holds — split it, or loft through stations\.$")
        import re
        self.assertGreater(int(re.search(r"are within (\d+)° of it", said).group(1)), 80)


def disc(f, r, hole, step, sigma, seed=1):
    rnd = noise(seed)
    pts = []
    for x in steps(-r, r, step):
        for y in steps(-r, r, step):
            d = math.hypot(x, y)
            if d > r or d < hole:
                continue
            pts += [x, y, f(x, y) + rnd() * sigma]
    return np.asarray(pts)


def levels(x, y):
    return (4 if x > 10 else 0) + (-3 if y < -20 else 0) + (2 if x < -30 else 0) + (x * y) / 2000


def rim(c, k):
    return lambda x, y: levels(x, y) + max(0, math.hypot(x, y) - c) ** 2 * k


def over_plane(fit, p):
    d = [p[0] - fit["origin"][0], p[1] - fit["origin"][1], p[2] - fit["origin"][2]]
    return [sum(d[k] * fit[a][k] for k in range(3)) for a in ("axisU", "axisV", "normal")]


def overshoot(fit, xyz):
    P = xyz.reshape(-1, 3)
    hs = [over_plane(fit, p)[2] for p in P]
    lo, hi = min(hs), max(hs)
    worst = 0
    ur, vr = fit["uRange"], fit["vRange"]
    for a in range(41):
        for b in range(41):
            h = over_plane(fit, eval_surface(fit, ur[0] + ((ur[1] - ur[0]) * a) / 40, vr[0] + ((vr[1] - vr[0]) * b) / 40))[2]
            worst = max(worst, h - hi, lo - h)
    return worst


def moved(a, b, xyz):
    worst = 0
    for p in xyz.reshape(-1, 3):
        pa, pb = over_plane(a, p), over_plane(b, p)
        qa, qb = eval_surface(a, pa[0], pa[1]), eval_surface(b, pb[0], pb[1])
        worst = max(worst, math.dist(qa, qb))
    return worst


class Pull(unittest.TestCase):
    def test_holds_empty_corners(self):
        for xyz, params, sigma in ((disc(levels, 60, 15, 1.5, 1, 5), net(14), 1), (disc(levels, 60, 45, 1.5, 0.5, 5), net(20), 0.5)):
            free = fit_surface(xyz, params, sigma, 0)
            held = fit_surface(xyz, params, sigma)
            self.assertGreater(overshoot(free, xyz), 4)
            self.assertLess(overshoot(held, xyz), 0.5)
            self.assertLess(moved(free, held, xyz), 0.5 * free["rms"] + 1e-9)
            self.assertLess(moved(free, held, xyz), sigma)

    def test_curved_patch_moved_under_the_noise(self):
        for sigma in (0.3, 0.02):
            xyz = disc(lambda x, y: (x * x + 0.6 * y * y) / 400, 60, 15, 1.5, sigma, 3)
            free = fit_surface(xyz, net(14), sigma, 0)
            held = fit_surface(xyz, net(14), sigma)
            self.assertLess(moved(free, held, xyz), sigma)
            self.assertGreater(overshoot(held, xyz), 10)

    def test_full_region_left_as_it_was(self):
        xyz = patch(lambda x, y: math.sqrt(900 - x * x) - 30, 30, 20, 0.5, 0.01)
        free = fit_surface(xyz, {**DEFAULT_SURFACE_FIT, "net": {"u": 8, "v": 4}}, 0.02, 0)
        held = fit_surface(xyz, {**DEFAULT_SURFACE_FIT, "net": {"u": 8, "v": 4}}, 0.02, PULL)
        self.assertEqual(held["heights"].tolist(), free["heights"].tolist())


class RunAway(unittest.TestCase):
    def test_refused_naming_the_spot(self):
        xyz = disc(rim(56, 1), 60, 15, 1, 0.5, 5)
        fit = fit_surface(xyz, net(14), 0.5)
        self.assertGreater(overshoot(fit, xyz), 0.425 * 120)
        self.assertRegex(run_away(fit, xyz, DEFAULT_SURFACE_FIT["expandPct"]),
                         r"^The surface runs away from its points: it stands [\d.]+ mm (above the highest|below the lowest) of them at \(-?[\d.]+, -?[\d.]+, -?[\d.]+\), [\d.]+ mm past where the region's points run out at \(")
        with self.assertRaisesRegex(ValueError, "runs away from its points"):
            fit_surface_reported(xyz, net(14))

    def test_curve_carried_on_not_refused(self):
        xyz = disc(lambda x, y: (x * x + 0.6 * y * y) / 400, 60, 15, 1.5, 0.3, 3)
        self.assertIsNone(run_away(fit_surface(xyz, net(14), 0.3), xyz, DEFAULT_SURFACE_FIT["expandPct"]))
        cyl = patch(lambda x, y: math.sqrt(900 - x * x) - 30, 30, 20, 0.5, 0.01)
        self.assertIsNone(run_away(fit_surface(cyl, {**DEFAULT_SURFACE_FIT, "net": {"u": 8, "v": 4}}, 0.02), cyl, DEFAULT_SURFACE_FIT["expandPct"]))

    @unittest.skip(KERNEL)
    def test_kernel_surface_and_mesh(self):
        pass


if __name__ == "__main__":
    unittest.main()
