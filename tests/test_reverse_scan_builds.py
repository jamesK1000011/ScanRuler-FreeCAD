# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/tests/reNetworkBody.test.ts (its kernel cases), and the build.ts plays read off the scan
# SPDX-License-Identifier: AGPL-3.0-only
#
# The build steps read off the scan (build steps 10 and 11 of the port):
# a split that keeps what lies on the scan, a fitted surface, a trim and a
# patch network. Pure where the stand-in kernel reaches (the share of a
# shape on the scan, the loft's fold reading); on FreeCAD each builds on a
# scan made here, to the volume or area worked out by hand.
import math
import os
import sys
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
if os.environ.get("FREECAD_LIB"):
    sys.path.append(os.environ["FREECAD_LIB"])
try:
    import FreeCAD  # noqa: F401
    import Part  # noqa: F401

    HAVE_FC = True
except ImportError:
    HAVE_FC = False

from meshkit import box_mesh  # noqa: E402
from network_meshes import grid_network, network, sphere_scan  # noqa: E402
from reverse_fakekernel import FakeKernel, Piece, Shape  # noqa: E402
from scanrulerfc.reverse.build import Builder  # noqa: E402
from scanrulerfc.reverse.features import constrain_refs  # noqa: E402
from scanrulerfc.reverse.loft_fold import crossing, fold_of_cuts, fold_words, loft_fold_refusal, sections_normal  # noqa: E402

R = 40


def on_sphere(u, v):
    a = (u - 0.5) * 1.4
    b = (v - 0.5) * 1.4
    ln = math.hypot(1, a, b)
    return [R / ln, (R * a) / ln, (R * b) / ln]


def closed_network():
    s = R / math.sqrt(3)
    nodes = {i + 1: [s if i & 1 else -s, s if i & 2 else -s, s if i & 4 else -s] for i in range(8)}
    curves = [{"from": i + 1, "to": (i | bit) + 1} for i in range(8) for bit in (1, 2, 4) if not i & bit]
    seeds = [[R, 0, 0], [-R, 0, 0], [0, R, 0], [0, -R, 0], [0, 0, R], [0, 0, -R]]
    return network(2, nodes, curves, seeds)


def box_scan(lo=(0, 0, 0), hi=(10, 10, 10), n=10):
    size = [b - a for a, b in zip(lo, hi)]
    V, F = box_mesh(*size, n, center=[(a + b) / 2 for a, b in zip(lo, hi)])
    return V, F


def circle(c, r, z=0.0):
    return {"outer": [{"kind": "circle", "center": [c[0], c[1], z], "normal": [0, 0, 1], "radius": r}], "holes": []}


class OnTheScan(unittest.TestCase):
    def test_the_share_of_a_shape_on_the_scan(self):
        b = Builder(FakeKernel())
        self.assertIsNone(b.on_scan_share(Shape([Piece(([0, 0, 0], [10, 10, 10]))]), 0.3))
        b.set_scan(*box_scan())
        # The stand-in meshes a box as one triangle on its top: on the scan.
        self.assertEqual(b.on_scan_share(Shape([Piece(([0, 0, 0], [10, 10, 10]))]), 0.3), 1.0)
        self.assertEqual(b.on_scan_share(Shape([Piece(([0, 0, 0], [10, 10, 12]))]), 0.3), 0.0)
        # What is left out counts neither way.
        self.assertEqual(b.on_scan_share(Shape([Piece(([0, 0, 0], [10, 10, 12]))]), 0.3, lambda p: True), 0.0)

    def test_a_new_scan_lets_the_kept_states_go(self):
        b = Builder(FakeKernel())
        b._tree["children"]["x"] = {"children": {}, "state": {}}
        b.set_scan(*box_scan())
        self.assertEqual(b._tree["children"], {})
        b.set_scan(None, None)
        self.assertIsNone(b.scan)


class LoftFold(unittest.TestCase):
    def test_a_cut_that_crosses_itself_is_found_and_said(self):
        # Two pieces of one cut, laid flat across Z, crossing at (5, 5).
        cut = [[[0, 0, 3], [10, 10, 3]], [[0, 10, 3], [10, 0, 3]]]
        x = crossing(cut, [0, 0, 1])
        self.assertEqual([round(v, 9) for v in x], [5, 5, 3])
        self.assertIsNone(crossing([[[0, 0, 3], [10, 0, 3], [10, 10, 3]]], [0, 0, 1]))
        fold = fold_of_cuts([[], cut, cut, []], [0, 0, 1])
        self.assertEqual([f["cut"] for f in fold["folded"]], [1, 2])
        self.assertEqual(fold_words(fold), "crosses itself at z 3 near (5, 5) (folded over z 3–3)")  # two cuts in a run, as the original says it

    def test_the_refusal_names_the_sections(self):
        def ring(z, r):
            return circle([0, 0], r, z)

        profiles = [ring(0, 5), ring(10, 8), ring(11, 3), ring(20, 5)]
        self.assertEqual(sections_normal(profiles), [0, 0, 1])
        fold = {"at": [4, 0, 10.5], "normal": [0, 0, 1], "folded": [{"cut": 20, "height": 10.5}], "of": 40}
        words = loft_fold_refusal(fold, [{"name": f"Sketch {i + 1}", "profile": p} for i, p in enumerate(profiles)])
        self.assertEqual(words, "The smooth loft crosses itself at z 10.5 near (4, 0) (folded over z 10.5): Sketch 2 and Sketch 3 are 1 mm apart and differ — drop or move one, or make the loft ruled.")


def surface_step(i, region, shape, **more):
    return {"kind": "surface", "id": i, "name": f"Surface {i}", "region": region, "fit": {"net": None, "degree": 3, "expandPct": 35, "smoothness": 0.01},
            "shape": shape, "constrain": {"mode": "auto"}, "refs": constrain_refs([]), "refSurfaces": [], **more}


def plane_tool(origin, normal, u, v):
    return {"kind": "plane", "origin": origin, "normal": normal, "basisU": u, "basisV": v}


@unittest.skipUnless(HAVE_FC, "needs FreeCAD")
class InFreeCAD(unittest.TestCase):
    def builder(self, V=None, F=None):
        from scanrulerfc.reverse.kernel import Kernel

        b = Builder(Kernel())
        if V is not None:
            b.set_scan(V, F)
        return b

    def test_a_split_keeps_what_lies_on_the_scan(self):
        b = self.builder(*box_scan((3, 0, 0), (10, 10, 10)))
        cube = {"kind": "extrude", "id": 1, "name": "Extrude 1", "profiles": [{"outer": [{"kind": "line", "a": a, "b": c} for a, c in zip([[0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0]], [[10, 0, 0], [10, 10, 0], [0, 10, 0], [0, 0, 0]])], "holes": []}],
                "regions": [], "dir": [0, 0, 1], "origin": [0, 0, 0], "from": 0, "to": 10, "draftDeg": 0, "op": "new"}
        sheet = {"kind": "sheet", "id": 2, "name": "Sheet 2", "sketchId": 9, "pieces": [{"kind": "line", "a": [3, -5, 0], "b": [3, 15, 0]}], "dir": [0, 0, 1], "from": -5, "to": 15}
        split = {"kind": "split", "id": 3, "name": "Split 3", "body": 1, "tools": [2], "keep": "scan", "tolerance": 0.3, "overlap": 0.5}
        out = b.build([cube, sheet, split])
        self.assertEqual([r["status"] for r in out["results"]], ["ok", "ok", "ok"], out["results"])
        got = {x["id"]: x for x in out["bodies"]}
        self.assertAlmostEqual(got[1]["volume"], 700, delta=1e-6 * 700)

    def test_a_plane_and_a_freeform_fitted_through_a_region(self):
        V, F = box_scan()
        top = [int(i) for i in np.nonzero(np.isclose(V[:, 2], 10))[0]]
        b = self.builder(V, F)
        out = b.build([surface_step(1, top, "plane"), surface_step(2, top, "freeform")])
        self.assertEqual([r["status"] for r in out["results"]], ["ok", "ok"], out["results"])
        plane = out["results"][0]["surface"]
        self.assertEqual(plane["shape"], "plane")
        self.assertLess(plane["rms"], 1e-6)
        self.assertAlmostEqual(abs(b.fitted[1]["normal"][2]), 1, 9)
        self.assertAlmostEqual(b.fitted[1]["origin"][2], 10, 6)
        self.assertLess(out["results"][1]["surface"]["rms"], 1e-3)
        self.assertTrue(all(x["surface"] for x in out["bodies"]))

    def test_a_trim_closes_a_box_of_six_planes_on_the_scan(self):
        b = self.builder(*box_scan())
        X, Y, Z = [1, 0, 0], [0, 1, 0], [0, 0, 1]
        planes = [plane_tool([0, 5, 5], X, Y, Z), plane_tool([10, 5, 5], X, Y, Z), plane_tool([5, 0, 5], Y, Z, X), plane_tool([5, 10, 5], Y, Z, X),
                  plane_tool([5, 5, 0], Z, X, Y), plane_tool([5, 5, 10], Z, X, Y)]
        out = b.build([{"kind": "trim", "id": 1, "name": "Trim 1", "bodies": [], "primitives": planes, "tolerance": 0.3, "overlap": 0.5}])
        r = out["results"][0]
        self.assertEqual(r["status"], "ok", r)
        self.assertTrue(r["trim"]["closed"], r)
        self.assertEqual(r["trim"]["kept"], 6)
        body = out["bodies"][0]
        self.assertFalse(body["surface"])
        self.assertAlmostEqual(body["volume"], 1000, delta=1e-6 * 1000)

    def test_a_2x2_network_on_a_sphere_is_a_sheet_that_thickens_in_and_out_not_both(self):
        b = self.builder(*sphere_scan(R, 0.02, 6))
        net = grid_network(1, 2, 2, on_sphere, 1)
        thick = [{"kind": "thicken", "id": 10 + n, "name": f"Thicken {n}", "sheet": 1, "thickness": 2, "side": side, "op": "new"} for n, side in enumerate(("out", "in", "both"))]
        out = b.build([net, *thick])
        res = {r["id"]: r for r in out["results"]}
        self.assertEqual(res[1]["status"], "ok", res[1])
        self.assertFalse(res[1]["network"]["closed"])
        self.assertEqual(len(res[1]["network"]["patches"]), 4)
        self.assertEqual((res[10]["status"], res[11]["status"]), ("ok", "ok"), (res[10], res[11]))
        self.assertEqual(res[12]["status"], "failed")
        self.assertTrue(res[12]["message"].startswith("A patch network’s sheet of several patches thickens one way at a time"), res[12])
        vols = {x["id"]: x["volume"] for x in out["bodies"] if not x["surface"]}
        area = next(x["area"] for x in out["bodies"] if x["id"] == 1)
        # A shell 2 thick on a sphere of radius 40: its area times 2, give
        # or take the curvature (out grows, in shrinks).
        self.assertLess(abs(vols[10] / (2 * area) - 1), 0.06)
        self.assertLess(abs(vols[11] / (2 * area) - 1), 0.06)
        self.assertGreater(vols[10], vols[11])

    def test_a_network_closed_round_a_sphere_sews_into_one_solid(self):
        b = self.builder(*sphere_scan(R, 0.02, 6))
        out = b.build([closed_network()])
        r = out["results"][0]
        self.assertEqual(r["status"], "ok", r)
        self.assertTrue(r["network"]["closed"], r["network"])
        body = out["bodies"][0]
        self.assertTrue(body["closed"])
        self.assertLess(abs(body["volume"] / ((4 / 3) * math.pi * R ** 3) - 1), 0.01)


if __name__ == "__main__":
    unittest.main()
