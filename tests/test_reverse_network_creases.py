# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/tests/reNetworkCreases.test.ts
# SPDX-License-Identifier: AGPL-3.0-only
#
# Suggest creases: a box with sharp rims and rounded upright edges gives
# its two rims and nothing on the rounds; a sharp box its twelve edges
# meeting in its eight corners; a fold across a noisy sheet one curve from
# edge to edge, and a flat sheet nothing; a box of a 2-million-triangle
# scan read in a fraction of the whole scan's time, its twelve folds found.
import math
import os
import sys
import time
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

from network_meshes import grid_scan  # noqa: E402
from scanrulerfc.reverse.network_creases import suggest_creases  # noqa: E402
from scanrulerfc.reverse.network_curve import trace_curve  # noqa: E402
from scanrulerfc.reverse.scan_path import ScanPaths  # noqa: E402


def rounded_rect(a, b, r):
    """A rectangle of half-sides a, b with corners rounded to r: its point
    a share u of the way round, counter-clockwise from the middle of its +x
    side, and the signed distance of (x, y) from it."""

    def line(p, q):
        return (math.hypot(q[0] - p[0], q[1] - p[1]), lambda t: (p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])))

    def arc(c, frm):
        return ((math.pi * r) / 2, lambda t: (c[0] + r * math.cos(frm + (t * math.pi) / 2), c[1] + r * math.sin(frm + (t * math.pi) / 2)))

    pieces = [line((a, 0), (a, b - r)), arc((a - r, b - r), 0), line((a - r, b), (-a + r, b)), arc((-a + r, b - r), math.pi / 2), line((-a, b - r), (-a, -b + r)),
              arc((-a + r, -b + r), math.pi), line((-a + r, -b), (a - r, -b)), arc((a - r, -b + r), (3 * math.pi) / 2), line((a, -b + r), (a, 0))]
    perimeter = sum(p[0] for p in pieces)

    def at(u):
        d = (((u % 1) + 1) % 1) * perimeter
        for length, f in pieces:
            if d <= length:
                return f(d / length if length > 0 else 0)
            d -= length
        return pieces[-1][1](1)

    def signed(x, y):
        qx = abs(x) - (a - r)
        qy = abs(y) - (b - r)
        return math.hypot(max(qx, 0), max(qy, 0)) + min(max(qx, qy), 0) - r

    return perimeter, at, signed


def rounded_box(r, h, noise=0.01):
    """A 40 x 30 x 20 mm box scanned as one grid round it: a ring of its
    bottom, its four sides, a ring of its top, the rims between them sharp,
    the upright edges rounded to r, with edges about h long and noise."""
    height = 20
    perimeter, rat, signed = rounded_rect(20, 15, r)
    ring = js_round(6 / h)
    wall = js_round(height / h)
    rows = 2 * ring + wall
    inner = 0.6

    def at(u, v):
        j = min(rows, max(0, v * rows))
        x, y = rat(u)
        if j <= ring:
            s = inner + ((1 - inner) * j) / ring
            return [s * x, s * y, 0]
        if j <= ring + wall:
            return [x, y, (height * (j - ring)) / wall]
        s = 1 - ((1 - inner) * (j - ring - wall)) / ring
        return [s * x, s * y, height]

    mesh = grid_scan(js_round(perimeter / h), rows, at, wrap=True, noise=noise)

    def off_rim(p, i=0):
        return math.hypot(signed(p[i], p[i + 1]), min(abs(p[i + 2]), abs(p[i + 2] - height)))

    return ScanPaths(*mesh), perimeter, height, off_rim


def folded_sheet(deg, noise=0.02):
    """A 60 x 40 mm sheet on edges of 0.5 mm folded up by deg along the line
    from (12, 0) to (42, 40), slantwise to its triangles, with noise."""
    a = (12, 0)
    b = (42, 40)
    l = math.hypot(b[0] - a[0], b[1] - a[1])
    across = ((b[1] - a[1]) / l, -(b[0] - a[0]) / l)

    def off(x, y):
        return (x - a[0]) * across[0] + (y - a[1]) * across[1]

    slope = math.tan((deg * math.pi) / 180)
    mesh = grid_scan(120, 80, lambda u, v: [60 * u, 40 * v, slope * max(0, off(60 * u, 40 * v))], noise=noise)
    return ScanPaths(*mesh), a, b, lambda p, i=0: abs(off(p[i], p[i + 1]))


def traced_points(scan, s, c):
    at = {n["id"]: n["at"] for n in s["nodes"]}
    return trace_curve(scan, [at[c["from"]], *c["via"], at[c["to"]]])["points"]


def worst(points, off):
    P = np.asarray(points, dtype=float)
    return max((off(P, i) for i in range(0, P.shape[0], 3)), default=0.0)


def js_round(x):
    return math.floor(x + 0.5)


class SuggestCreases(unittest.TestCase):
    def test_gives_a_rounded_box_its_two_sharp_rims_and_nothing_on_the_rounds(self):
        for r, h in ((4, 0.5), (2, 0.5)):
            scan, perimeter, height, off_rim = rounded_box(r, h)
            s = suggest_creases(scan)
            self.assertEqual(len(s["curves"]), 8)
            self.assertEqual(len(s["nodes"]), 8)
            for n in s["nodes"]:
                self.assertEqual(len([c for c in s["curves"] if c["from"] == n["id"] or c["to"] == n["id"]]), 2)
            for c in s["curves"]:
                self.assertLess(worst(c["points"], off_rim), 0.1)
                self.assertGreater(c["angle"], 89)
                self.assertLess(c["angle"], 91)
                for g in c["via"]:
                    self.assertLess(scan.closest(g).distance, 1e-3)
                self.assertLess(worst(traced_points(scan, s, c), off_rim), 0.1)
            for z in (0, height):
                rnd = sum(c["length"] for c in s["curves"] if abs(float(c["points"][2]) - z) < 1)
                self.assertLess(abs(rnd - perimeter) / perimeter, 0.01)

    def test_gives_a_sharp_box_its_twelve_edges_meeting_in_its_eight_corners(self):
        scan, _, height, _ = rounded_box(0, 0.5)
        s = suggest_creases(scan)
        self.assertEqual(len(s["curves"]), 12)
        self.assertEqual(len(s["nodes"]), 8)
        for n in s["nodes"]:
            corner = math.hypot(abs(n["at"][0]) - 20, abs(n["at"][1]) - 15, min(abs(n["at"][2]), abs(n["at"][2] - height)))
            self.assertLess(corner, 0.05)
            self.assertEqual(len([c for c in s["curves"] if c["from"] == n["id"] or c["to"] == n["id"]]), 3)
        lengths = sorted(js_round(c["length"]) for c in s["curves"])
        self.assertEqual(lengths, [20, 20, 20, 20, 30, 30, 30, 30, 40, 40, 40, 40])
        for c in s["curves"]:
            self.assertLess(abs(c["angle"] - 90), 1)

    def test_finds_a_fold_across_a_noisy_sheet_as_one_curve_and_nothing_else(self):
        for deg in (30, 35, 40):
            scan, a, b, off_fold = folded_sheet(deg)
            s = suggest_creases(scan)
            self.assertEqual(len(s["curves"]), 1)
            self.assertEqual(len(s["nodes"]), 2)
            c = s["curves"][0]
            self.assertLess(worst(c["points"], off_fold), 0.25)
            self.assertLess(worst(traced_points(scan, s, c), off_fold), 0.25)
            self.assertLess(abs(c["angle"] - deg), 1)
            for n in s["nodes"]:
                self.assertLess(min(math.hypot(n["at"][0] - a[0], n["at"][1] - a[1]), math.hypot(n["at"][0] - b[0], n["at"][1] - b[1])), 2)
            self.assertGreater(c["length"], 46)
        self.assertEqual(suggest_creases(folded_sheet(0, 0.05)[0])["curves"], [])

    def test_reads_320000_triangles_in_a_box_of_a_2_million_triangle_scan_for_a_fraction_of_the_whole_scan(self):
        def timed(read):
            t0 = time.perf_counter()
            read()
            return (time.perf_counter() - t0) * 1000

        period = 25
        slope = math.tan((17.5 * math.pi) / 180)
        d = (math.cos((20 * math.pi) / 180), math.sin((20 * math.pi) / 180))

        def along(x, y):
            return x * d[0] + y * d[1]

        def at(u, v):
            m = (((along(300 * u, 300 * v) % period) + period) % period) - period / 2
            return [300 * u, 300 * v, slope * (period / 2 - abs(m))]

        scan = ScanPaths(*grid_scan(1000, 1000, at, noise=0.02))
        self.assertEqual(scan.triangle_count, 2_000_000)
        box = {"min": [90, 90, -10], "max": [210, 210, 10]}
        s = suggest_creases(scan, box=box)
        whole = timed(lambda: suggest_creases(scan))
        ms = min(timed(lambda: suggest_creases(scan, box=box)) for _ in range(3))
        self.assertEqual(len(s["curves"]), 12)

        def off_fold(p, i):
            dd = along(p[i], p[i + 1])
            return abs(dd - (period / 2) * js_round(dd / (period / 2)))

        for c in s["curves"]:
            self.assertLess(abs(c["angle"] - 35), 1)
            self.assertLess(worst(c["points"], off_fold), 0.3)
        print(f"creases: box {ms:.0f} ms, whole scan {whole:.0f} ms", file=sys.stderr)
        # The original's ratio; its 5 s ceiling is the browser's, and left out.
        self.assertLess(ms, whole / 2.5)

if __name__ == "__main__":
    unittest.main()
