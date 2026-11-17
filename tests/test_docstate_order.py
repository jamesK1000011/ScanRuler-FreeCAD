# SPDX-License-Identifier: AGPL-3.0-only
# ScanRuler's state in the FreeCAD document (ScanRuler by Stefan Hermann,
# CNC Kitchen, ported): the scan's points read back from its mesh object in
# the order its triangles number them (scan_info's area was some thousand
# times too large live, run 4), a best fit's transform (dev_rigid.Rigid)
# kept as plain numbers and read back as a Rigid, and a scaled scan's mesh
# that still holds the points in order, so the state does not carry them
# too. On a stand-in document (fakedoc.py).
import os
import sys
import tempfile
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.dirname(HERE), HERE]

import fakedoc  # noqa: E402
from meshkit import box_mesh  # noqa: E402

from scanrulerfc import docstate as D  # noqa: E402
from scanrulerfc import runner  # noqa: E402
from scanrulerfc import scanstate as S  # noqa: E402
from scanrulerfc.dev_rigid import Rigid  # noqa: E402


def cube(size=10.0):
    """A closed cube, 8 points, 12 triangles, outward."""
    V = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]], float) * size
    F = np.array([[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4],
                  [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]], np.int64)
    return V, F


def welded_cube(size=10.0, n=12):
    """A closed size mm cube, each face an n x n grid, its points welded
    (one point where faces meet), as a scan read from a file is."""
    V, F = box_mesh(size, size, size, n=n)
    V = np.round(np.asarray(V, float), 9)
    U, inv = np.unique(V, axis=0, return_inverse=True)
    rng = np.random.default_rng(6)
    order = rng.permutation(len(U))  # the file's order, not sorted
    back = np.empty_like(order)
    back[order] = np.arange(len(U))
    return U[order] + size / 2, back[np.asarray(inv).reshape(-1)][np.asarray(F, np.int64)]


def loose_mesh(V, F):
    """A mesh built the way the add-on built every mesh before (the tuple
    form refused the lists it was given): from loose triangles."""
    import Mesh

    m = Mesh.Mesh()
    m.addFacets([[tuple(V[i]) for i in t] for t in F.tolist()])
    return m


def rot(axis, deg):
    a = np.radians(deg)
    c, s = np.cos(a), np.sin(a)
    i, j = [(1, 2), (2, 0), (0, 1)][axis]
    R = np.eye(3)
    R[i, i] = R[j, j] = c
    R[i, j], R[j, i] = -s, s
    return R


class Area(unittest.TestCase):
    def test_a_10_mm_cube_has_600_mm2(self):
        V, F = cube()
        self.assertAlmostEqual(S.Scan("cube.stl", V, F).summary()["area"], 600.0, places=6)

    def test_a_list_of_lists_is_not_freecads_tuple_form(self):
        # FreeCAD 1.1 MeshPy::addFacets, tuple form: points must be Vectors
        # (others are skipped), triangles tuples (a list is a TypeError).
        V, F = cube()
        with fakedoc.installed():
            import Mesh

            with self.assertRaises(TypeError):
                Mesh.Mesh((V.tolist(), F.tolist()))
            m = loose_mesh(V, F)
            pts = np.array(m.Topology[0])
            self.assertEqual(len(pts), 8)
            self.assertFalse(np.array_equal(pts, V))  # same points, another order
            # the state's triangles on those points: another surface
            self.assertNotAlmostEqual(D._area(pts, F), 600.0, places=3)
            m2, ordered = D._mesh_built(V, F)
            self.assertTrue(ordered)
            np.testing.assert_allclose(np.array(m2.Topology[0]), V)
            self.assertEqual([tuple(t) for t in m2.Topology[1]], [tuple(t) for t in F.tolist()])

    def test_points_in_order(self):
        V, F = cube()
        with fakedoc.installed():
            m = loose_mesh(V, F)
        P, T = np.array(m.Topology[0]), np.array(m.Topology[1])
        got, how = D.points_in_order(P, T, F, len(V))
        self.assertEqual(how, "mapped")
        np.testing.assert_allclose(got, V)
        got, how = D.points_in_order(V, F, F, len(V))
        self.assertEqual(how, "same")
        got, how = D.points_in_order(P, T[::-1], F, len(V))  # triangles not one for one
        self.assertIsNone(got)
        self.assertEqual(how, "order")
        self.assertEqual(D.points_in_order(V[:5], None, F, len(V)), (None, "count"))


class InTheDocument(unittest.TestCase):
    def setUp(self):
        self.fc = fakedoc.installed()
        self.app = self.fc.__enter__()
        self.addCleanup(self.fc.__exit__, None, None, None)
        D._SIGS.clear()
        self.doc = fakedoc.Doc("Cube")
        self.ctx = runner.Context(doc=self.doc, out_dir=tempfile.mkdtemp())
        self.run = runner.local(ctx=self.ctx)
        V, F = welded_cube()
        S.state(self.ctx)["scan"] = S.Scan("cube.stl", V, F)
        self.assertAlmostEqual(S.state(self.ctx)["scan"].summary()["area"], 600.0, places=6)
        ok, out = self.run("element_fit", {"kind": "plane", "at": {"point": [5, 5, 10]}, "name": "Top"})
        self.assertTrue(ok, out)

    def reopen(self):
        return S.state(runner.Context(doc=self.doc, out_dir=tempfile.mkdtemp()))

    def info(self, ctx_state=None):
        ok, out = self.run("scan_info", {})
        self.assertTrue(ok, out)
        return out

    def test_scan_info_area_after_reopen(self):
        self.assertAlmostEqual(self.info()["scan"]["area"], 600.0, places=3)
        st = self.reopen()
        self.assertAlmostEqual(st["scan"].summary()["area"], 600.0, places=3)
        np.testing.assert_allclose(st["scan"].V, S.state(self.ctx)["scan"].V, atol=1e-9)
        self.assertTrue(st["scan"].in_object)
        self.assertEqual(self.app.warnings, [])

    def test_a_document_saved_with_the_old_loose_mesh_still_reads_600(self):
        # A document written before this fix: the scan object holds the
        # points in loose-triangle order and the state left them to it.
        sc = S.state(self.ctx)["scan"]
        obj = self.doc.getObject(sc.object)
        obj.Mesh = loose_mesh(sc.k * sc.V0, sc.F)
        sc.in_object = True
        self.run("element_rename", {"element": "Top", "name": "Lid"})
        st = self.reopen()
        self.assertAlmostEqual(st["scan"].summary()["area"], 600.0, places=3)
        self.assertFalse(st["scan"].in_object)  # kept with the state from now on
        self.assertTrue(any("another order" in w for w in self.app.warnings), self.app.warnings)

    def test_a_scale_keeps_the_points_in_the_mesh_object_and_out_of_the_state(self):
        ok, out = self.run("scan_scale", {"factor": 2})
        self.assertTrue(ok, out)
        sc = S.state(self.ctx)["scan"]
        self.assertTrue(sc.in_object)
        self.assertAlmostEqual(out["scan"]["area"], 2400.0, places=3)
        self.run("element_rename", {"element": "Top", "name": "Lid"})
        import json
        import zipfile

        with zipfile.ZipFile(D.find_state(self.doc).State) as z:
            body = json.loads(z.read("state.json"))
        self.assertNotIn("V0", body["state"]["scan"]["__scan__"])  # not carried twice
        st = self.reopen()
        self.assertAlmostEqual(st["scan"].summary()["area"], 2400.0, places=3)

    def test_a_best_fit_transform_is_kept_and_read_back_as_a_rigid(self):
        r = Rigid(rot(0, 12.5) @ rot(2, -33.0), [1.25, -0.1, 1e-7 + 3.0])
        total = Rigid(rot(1, 0.001), [0.0, 0.0, 1 / 3])
        S.state(self.ctx)["deviation"] = {"align": {"transform": r, "total": total, "rms": 0.01}}
        self.run("element_rename", {"element": "Top", "name": "Lid"})
        self.assertEqual(self.app.warnings, [])  # nothing "not kept"
        st = self.reopen()
        got = st["deviation"]["align"]
        for want, key in ((r, "transform"), (total, "total")):
            self.assertIsInstance(got[key], Rigid)
            np.testing.assert_array_equal(got[key].r, want.r)  # exactly: full precision
            np.testing.assert_array_equal(got[key].t, want.t)
        self.assertEqual(self.app.warnings, [])


class Codec(unittest.TestCase):
    def test_rigid_round_trip_and_signature(self):
        r = Rigid(rot(2, 47.0), [0.1, 0.2, 0.3])
        data, dropped = D.encode({"align": {"transform": r}})
        self.assertEqual(dropped, [])
        got, notes = D.decode(data)
        self.assertEqual(notes["dropped"], [])
        self.assertIsInstance(got["align"]["transform"], Rigid)
        np.testing.assert_array_equal(got["align"]["transform"].r, r.r)
        np.testing.assert_array_equal(got["align"]["transform"].t, r.t)
        a = D.signature({"align": {"transform": r}})
        self.assertNotEqual(a, D.signature({"align": {"transform": Rigid(r.r, [0.1, 0.2, 0.4])}}))


if __name__ == "__main__":
    unittest.main()
