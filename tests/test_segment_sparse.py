# SPDX-License-Identifier: AGPL-3.0-only
# scan_segment on sparse, CAD-style meshes: ScanRuler's vertex growing finds
# nothing on a drum whose vertices are all on its rims, and the triangles
# are grouped instead (planes and cylinders); a dense scan is segmented by
# ScanRuler's method exactly as before.
import math
import os
import sys
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

import synth  # noqa: E402
from meshkit import box_mesh  # noqa: E402
from scanrulerfc import model as M  # noqa: E402
from scanrulerfc import segment as SEG  # noqa: E402
from scanrulerfc import segment_sparse as SS  # noqa: E402
from scanrulerfc.meshgraph import MeshGraph  # noqa: E402
from scanrulerfc.scanstate import Scan, fresh  # noqa: E402


def drum(r=20.0, h=30.0, seg=144, bore=None):
    """A closed cylinder as CAD exports it: the side a ring of long
    triangles, each cap a fan, every vertex on a rim (seg 144: 288 vertices,
    572 triangles). bore: a coaxial hole of that radius through it."""
    t = np.linspace(0, 2 * np.pi, seg, endpoint=False)
    ring = np.c_[np.cos(t), np.sin(t), np.zeros(seg)]
    if bore is None:
        V = np.r_[ring * [r, r, 0], ring * [r, r, 0] + [0, 0, h]]
        F = []
        for i in range(seg):
            j = (i + 1) % seg
            F += [[i, j, seg + j], [i, seg + j, seg + i]]
        for i in range(1, seg - 1):
            F += [[0, i + 1, i], [seg, seg + i, seg + i + 1]]
        return V, np.array(F)
    ob, ot, ib, it = (ring * [r, r, 0], ring * [r, r, 0] + [0, 0, h], ring * [bore, bore, 0], ring * [bore, bore, 0] + [0, 0, h])
    V = np.r_[ob, ot, ib, it]
    F = []
    for i in range(seg):
        j = (i + 1) % seg
        F += [[i, j, seg + j], [i, seg + j, seg + i]]  # outer side
        F += [[2 * seg + i, 3 * seg + j, 2 * seg + j], [2 * seg + i, 3 * seg + i, 3 * seg + j]]  # bore
        F += [[i, 2 * seg + j, j], [i, 2 * seg + i, 2 * seg + j]]  # bottom annulus
        F += [[seg + i, seg + j, 3 * seg + j], [seg + i, 3 * seg + j, 3 * seg + i]]  # top annulus
    return V, np.array(F)


def state_of(V, F, name="part"):
    st = fresh()
    st["scan"] = Scan(name, V, F)
    return st


class SparseDrum(unittest.TestCase):
    def test_the_live_drum_vertex_method_alone_finds_nothing(self):
        V, F = drum()
        self.assertEqual((len(V), len(F)), (288, 572))
        g = MeshGraph(V, F)
        ma = (0.02 * g.bbox_diag) ** 2
        self.assertEqual(SEG.segment_planes(g, ma, 0.05, 15)["regions"], [])
        self.assertEqual(SS.on_creases(g, 15), 1.0)
        self.assertTrue(SS.is_sparse(g, 15))

    def test_scan_segment_falls_back_to_faces(self):
        st = state_of(*drum())
        seg = M.scan_segment(st, {})
        self.assertEqual(seg["method"], "faces")
        self.assertIn("sparse", seg["why"])
        self.assertEqual(seg["found"], 3)
        kinds = sorted(r["kind"] for r in seg["regions"])
        self.assertEqual(kinds, ["cylinder", "plane", "plane"])
        cyl = next(r for r in seg["regions"] if r["kind"] == "cylinder")
        self.assertAlmostEqual(cyl["radius"], 20, delta=1e-6)
        self.assertAlmostEqual(abs(cyl["axis"][2]), 1, delta=1e-6)
        self.assertAlmostEqual(cyl["length"], 30, delta=1e-6)
        self.assertAlmostEqual(cyl["point"][2], 15, delta=1e-6)
        self.assertFalse(cyl["bore"])
        caps = [r for r in seg["regions"] if r["kind"] == "plane"]
        self.assertEqual(sorted(round(r["normal"][2]) for r in caps), [-1, 1])
        self.assertEqual(sorted(round(r["point"][2], 3) for r in caps), [0, 30])
        for r in caps:
            self.assertEqual(r["vertices"], 144)
            self.assertAlmostEqual(r["area"], 144 / 2 * 400 * math.sin(2 * math.pi / 144), delta=0.2)
            self.assertEqual([nb["deg"] for nb in r["neighbours"]], [90.0])
        # A cap marked and fitted is the cap.
        cap = next(r for r in caps if r["normal"][2] > 0)
        M.scan_segment(st, {"mark": cap["id"]})
        el = M.element_fit_marked(st, {"kind": "plane", "marked": True})["element"]
        self.assertAlmostEqual(abs(el["fit"]["normal"][2]), 1, delta=1e-6)

    def test_a_bore_is_a_cylinder_facing_in(self):
        st = state_of(*drum(bore=8.0))
        seg = M.scan_segment(st, {})
        self.assertEqual(seg["method"], "faces")
        cyls = sorted((r for r in seg["regions"] if r["kind"] == "cylinder"), key=lambda r: r["radius"])
        self.assertEqual(len(cyls), 2)
        self.assertAlmostEqual(cyls[0]["radius"], 8, delta=1e-6)
        self.assertTrue(cyls[0]["bore"])
        self.assertAlmostEqual(cyls[1]["radius"], 20, delta=1e-6)
        self.assertFalse(cyls[1]["bore"])
        self.assertEqual(sum(r["kind"] == "plane" for r in seg["regions"]), 2)

    def test_cad_box_of_twelve_triangles(self):
        V, F = box_mesh(40, 30, 20, n=1)
        self.assertEqual(len(F), 12)
        seg = M.scan_segment(state_of(V, F), {})
        self.assertEqual(seg["method"], "faces")
        self.assertEqual(seg["found"], 6)
        self.assertTrue(all(r["kind"] == "plane" for r in seg["regions"]))
        self.assertAlmostEqual(seg["regions"][0]["area"], 1200, delta=1e-6)
        for r in seg["regions"]:
            self.assertEqual(sorted(nb["deg"] for nb in r["neighbours"]), [90.0] * 4)

    def test_coarse_facets_are_planes_not_a_cylinder(self):
        # An octagonal prism: 45 degree turns are edges, not a smooth strip.
        V, F = drum(r=20, h=30, seg=8)
        seg = M.scan_segment(state_of(V, F), {})
        self.assertEqual(seg["found"], 10)
        self.assertTrue(all(r["kind"] == "plane" for r in seg["regions"]))

    def test_box_limits_the_faces(self):
        st = state_of(*drum())
        seg = M.scan_segment(st, {"box": {"min": [-25, -25, 25], "max": [25, 25, 35]}})
        self.assertEqual(seg["found"], 1)
        self.assertEqual(seg["regions"][0]["kind"], "plane")
        self.assertEqual(seg["considered"], 144)

    def test_method_vertices_keeps_upstreams_answer(self):
        seg = M.scan_segment(state_of(*drum()), {"method": "vertices"})
        self.assertEqual((seg["method"], seg["found"]), ("vertices", 0))
        self.assertNotIn("why", seg)


class DenseUnchanged(unittest.TestCase):
    def test_dense_box_runs_upstreams_method_unchanged(self):
        P, F = synth.box(sigma=0.005)
        st = state_of(P, F, "box")
        seg = M.scan_segment(st, {"maxRms": 0.05})
        self.assertEqual(seg["method"], "vertices")
        self.assertNotIn("why", seg)
        self.assertEqual(seg["found"], 6)
        g = st["scan"].graph()
        diag = 2 * M.model_size(st["scan"])
        ref = SEG.segment_planes(g, (0.02 * diag) ** 2, 0.05, 15)
        self.assertFalse(SS.is_sparse(g, 15))
        self.assertEqual([r["count"] for r in ref["regions"]], [r["vertices"] for r in seg["regions"]])
        for a, b in zip(ref["regions"], seg["regions"]):
            np.testing.assert_allclose(np.round(a["normal"], 5), b["normal"], atol=1e-5)
            self.assertEqual(b["kind"], "plane")

    def test_dense_scan_finding_nothing_is_not_sent_to_faces(self):
        # A dense sphere has no planes within 1 micron: still vertices, no
        # fallback.
        P, F = synth.sphere(r=10, n=90, m=45, sigma=0.01)
        seg = M.scan_segment(state_of(P, F, "ball"), {"maxRms": 0.001})
        self.assertEqual((seg["method"], seg["found"]), ("vertices", 0))

    def test_faces_asked_for_on_a_dense_box(self):
        P, F = synth.box(sigma=0.0)
        seg = M.scan_segment(state_of(P, F, "box"), {"method": "faces"})
        self.assertEqual(seg["method"], "faces")
        self.assertEqual(seg["found"], 6)


if __name__ == "__main__":
    unittest.main()
