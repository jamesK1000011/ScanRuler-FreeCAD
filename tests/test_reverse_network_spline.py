# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/core/networkSpline.ts (checked against the original's own numbers)
# SPDX-License-Identifier: AGPL-3.0-only
#
# The patch network's B-splines against goldens the original computed: the
# basis and its derivative at the ends, inside and on knots, curve points
# and derivatives, patch points, derivatives and normals, the Greville
# abscissae and the divided differences' weights. The vectorised forms are
# checked against the scalar ones to the bit.
import json
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from scanrulerfc.reverse import network_spline as S  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "reverse_fixtures", "network_spline_goldens.json"), encoding="utf-8") as f:
    G = json.load(f)


class NetworkSplineGoldens(unittest.TestCase):
    def test_basis(self):
        for g in G["basis"]:
            b = [0.0] * 4
            s = S.basis_at(g["spans"], g["t"], b)
            self.assertEqual(s, g["s"])
            self.assertEqual(b, g["b"], g)
            sv, bv = S.basis_at_v(g["spans"], np.array([g["t"]]))
            self.assertEqual(int(sv[0]), g["s"])
            self.assertEqual(list(bv[0]), g["b"])

    def test_basis_with_derivative(self):
        for g in G["deriv"]:
            n0 = [0.0] * 4
            n1 = [0.0] * 4
            s = S.basis_with_derivative(g["spans"], g["t"], n0, n1)
            self.assertEqual(s, g["s"])
            self.assertEqual(n0, g["n0"], g)
            self.assertEqual(n1, g["n1"], g)
            sv, v0, v1 = S.basis_with_derivative_v(g["spans"], np.array([g["t"]]))
            self.assertEqual((int(sv[0]), list(v0[0]), list(v1[0])), (g["s"], g["n0"], g["n1"]))

    def test_curve(self):
        poles = G["curvePoles"]
        ts = np.array([g["t"] for g in G["curve"]])
        pv = S.curve_points_v(poles, 4, ts)
        dv = S.curve_derivatives_v(poles, 4, ts)
        for k, g in enumerate(G["curve"]):
            self.assertEqual(S.curve_point(poles, 4, g["t"]), g["p"])
            self.assertEqual(S.curve_derivative(poles, 4, g["t"]), g["d"])
            self.assertEqual(list(pv[k]), g["p"])
            self.assertEqual(list(dv[k]), g["d"])

    def test_patch(self):
        n = G["net"]
        net = S.PatchNet(n["nu"], n["nv"], np.array(n["poles"]))
        us = np.array([g["u"] for g in G["patch"]])
        vs = np.array([g["v"] for g in G["patch"]])
        P, DU, DV = S.patch_points_v(net, us, vs)
        for k, g in enumerate(G["patch"]):
            p, du, dv = [0.0] * 3, [0.0] * 3, [0.0] * 3
            S.patch_point(net, g["u"], g["v"], p, du, dv)
            self.assertEqual((p, du, dv), (g["p"], g["du"], g["dv"]))
            self.assertEqual((list(P[k]), list(DU[k]), list(DV[k])), (g["p"], g["du"], g["dv"]))
            self.assertEqual(S.patch_normal(net, g["u"], g["v"]), g["n"])

    def test_greville_and_divided(self):
        for spans, g in G["greville"].items():
            self.assertEqual(list(S.greville_of(int(spans))), g)
        for g in G["divided"]:
            self.assertEqual(S.divided_weights(G["dividedX"], g["from"], g["order"]), g["w"])


if __name__ == "__main__":
    unittest.main()
