# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): src/core/geometry/scanPath.ts, plugins/reverse/core/networkCurve.ts (checked against the original's own numbers)
# SPDX-License-Identifier: AGPL-3.0-only
#
# Scan paths and a patch network's curves against goldens the original
# computed on the networks' synthetic scans: a noisy wavy sheet, a noisy
# cylinder traced round and up, and a sheet with a hole a path has to go
# round by the edges. The scans themselves, the plane sections, the edge
# fallback, the nearest points and the normal come out the same to the
# bit; the traces too; the fits (free, held tangent, faired), Auto's span
# counts, the provisional fit and the leaving directions within rounding.
import json
import math
import os
import sys
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

from network_meshes import grid_scan  # noqa: E402
from scanrulerfc.reverse import network_curve as C  # noqa: E402
from scanrulerfc.reverse.scan_path import ScanPaths, trace_path  # noqa: E402

with open(os.path.join(HERE, "reverse_fixtures", "network_curve_goldens.json"), encoding="utf-8") as f:
    G = json.load(f)

R = 20
SCANS = {
    "sheet": lambda: grid_scan(60, 48, lambda u, v: [100 * u, 80 * v, 3 * math.sin(2 * u) * math.cos(v)], noise=0.02),
    "cylinder": lambda: grid_scan(90, 20, lambda u, v: [R * math.cos(2 * math.pi * u), R * math.sin(2 * math.pi * u), 40 * v], wrap=True, noise=0.01),
    "hole": lambda: grid_scan(30, 30, lambda u, v: [60 * u, 60 * v, 0], hole=lambda u, v: math.hypot(u - 0.5, v - 0.5) < 0.2),
}
TOL = 1e-9


class ScanPathAndCurveGoldens(unittest.TestCase):
    def each(self):
        for sc in G["scans"]:
            P, F = SCANS[sc["name"]]()
            yield sc, P, F, ScanPaths(P, F)

    def test_scans(self):
        for sc, P, F, scan in self.each():
            self.assertEqual(list(P[:60].astype(float)), sc["positionsHead"])
            self.assertAlmostEqual(float(P.astype(float).sum()), sc["positionsSum"], places=6)
            self.assertEqual(len(F) // 3, sc["triangles"])
            self.assertEqual(scan.edge, sc["edge"])

    def test_paths(self):
        for sc, _, _, scan in self.each():
            for g in sc["paths"]:
                p = trace_path(scan, g["a"], g["b"])
                self.assertEqual(p["way"], g["way"])
                self.assertEqual(list(p["points"].astype(float)), g["points"])
                self.assertEqual(list(p["on"]), g["on"])
                self.assertEqual(p["ends"], g["ends"])
                self.assertAlmostEqual(p["length"], g["length"], places=12)

    def test_nearest(self):
        for sc, _, _, scan in self.each():
            g = sc["closest"]
            c = scan.closest([31, 29, 7])
            self.assertEqual((c.triangle, c.point), (g["triangle"], g["point"]))
            self.assertAlmostEqual(c.distance, g["distance"], places=12)
            self.assertEqual(scan.closest_inside([31, 29, 7]).point, g["inside"])
            np.testing.assert_allclose(scan.normal_at(c.point, c.triangle), g["normal"], atol=1e-14)
            self.assertEqual(scan.edge_route(0, scan.vertex_count - 1), g["route"])

    def test_traces_and_fits(self):
        for sc, _, _, scan in self.each():
            for g in sc["traces"]:
                t = C.trace_curve(scan, g["points"])
                gt = g["trace"]
                self.assertEqual(list(t["points"].astype(float)), gt["points"])
                self.assertEqual(list(t["on"]), gt["on"])
                self.assertEqual(t["grips"], gt["grips"])
                self.assertEqual(t["runs"], gt["runs"])
                np.testing.assert_allclose(t["at"], gt["at"], atol=1e-12)
                self.assertEqual(C.auto_spans(t), g["auto"])
                prov = C.fit_provisional(t, scan.edge)
                self.assertEqual(prov["spans"], g["prov"]["spans"])
                np.testing.assert_allclose(prov["poles"], g["prov"]["poles"], atol=TOL)
                st = C.leaving_direction(t, 0, scan.edge)
                en = C.leaving_direction(t, 1, scan.edge)
                np.testing.assert_allclose([st, en], g["leaving"], atol=1e-12)
                fits = {
                    "f4": C.fit_curve(t, 4),
                    "f9": C.fit_curve(t, 9),
                    "tan": C.fit_curve(t, 6, {"startTangent": st, "endTangent": [-x for x in en]}, 0.05),
                    "fair": C.fit_curve(t, 8, {}, 3),
                }
                for k, f in fits.items():
                    gf = g["fits"][k]
                    self.assertEqual(f["spans"], gf["spans"])
                    np.testing.assert_allclose(f["poles"], gf["poles"], atol=TOL)
                    self.assertAlmostEqual(f["rms"], gf["rms"], places=10)
                    self.assertAlmostEqual(f["max"], gf["max"], places=10)

    def test_helpers(self):
        fit = {"spans": 3, "poles": np.array([0, 0, 0, 1, 0, 0, 2, 1, 0, 3, 1, 1, 4, 0, 1, 5, 0, 0], dtype=float)}
        back = C.reversed_poles(fit["poles"])
        self.assertEqual(list(back[:3]), [5.0, 0.0, 0.0])
        s = C.sample_curve(fit, 5)
        self.assertEqual(list(s[:3]), [0.0, 0.0, 0.0])
        self.assertEqual(list(s[-3:]), [5.0, 0.0, 0.0])
        cs = C.curve_samples(fit)
        self.assertEqual(len(cs["points"]) // 3, 25)
        joined = C.join_traces([(cs, False), (cs, True)])
        self.assertEqual(len(joined["points"]) // 3, 49)
        self.assertAlmostEqual(joined["length"], 2 * cs["length"], places=4)
        np.testing.assert_allclose(C.end_tangent(fit, 0), [1, 0, 0], atol=1e-12)


if __name__ == "__main__":
    unittest.main()
