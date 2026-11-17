# SPDX-License-Identifier: AGPL-3.0-only
# The Mesh Tools added headless — Densify, Boolean, Shell (hollow and
# thicken), Wrap and Trim to scan — with ScanRuler's own test cases where it
# has them (plugins/mesh-tools/tests: densify, meshBoolean, measuredSolids,
# meshOffset, wrap, breakSurface, extendRim, trimToScan), on small meshes.
# The boolean and the trim cut with meshbool (numpy only): they run with or
# without FreeCAD.
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
    import Mesh  # noqa: F401

    HAVE_FREECAD = True
except ImportError:
    HAVE_FREECAD = False

from meshkit import box_mesh  # noqa: E402
from scanrulerfc import mesh_core as M  # noqa: E402
from scanrulerfc import scanstate as S  # noqa: E402
from scanrulerfc.dev_surface import NominalSurface  # noqa: E402
from scanrulerfc.meshtools import boolean as BO  # noqa: E402
from scanrulerfc.meshtools import densify as DE  # noqa: E402
from scanrulerfc.meshtools import grid as G  # noqa: E402
from scanrulerfc.meshtools import handlers as H  # noqa: E402
from scanrulerfc.meshtools import shell as SH  # noqa: E402
from scanrulerfc.meshtools import solids as SO  # noqa: E402
from scanrulerfc.meshtools import trim as TR  # noqa: E402
from scanrulerfc.meshtools import wrap as WR  # noqa: E402


def cad_box(x, y, z):
    """densify.test.ts box: 12 triangles from the origin, wound outward."""
    P = np.array([0, 0, 0, x, 0, 0, x, y, 0, 0, y, 0, 0, 0, z, x, 0, z, x, y, z, 0, y, z], dtype=float).reshape(-1, 3)
    F = np.array([0, 2, 1, 0, 3, 2, 4, 5, 6, 4, 6, 7, 0, 1, 5, 0, 5, 4, 1, 2, 6, 1, 6, 5, 2, 3, 7, 2, 7, 6, 3, 0, 4, 3, 4, 7]).reshape(-1, 3)
    return P, F


def cuboid(mn, mx, n=4):
    return box_mesh(mx[0] - mn[0], mx[1] - mn[1], mx[2] - mn[2], n, center=[(a + b) / 2 for a, b in zip(mn, mx)])


def joined(*meshes):
    Vs, Fs, o = [], [], 0
    for V, F in meshes:
        Vs.append(V)
        Fs.append(F + o)
        o += len(V)
    return np.vstack(Vs), np.vstack(Fs)


def cylinder(r, z0, z1, x=0.0, y=0.0):
    return SO.frustum([x, y, (z0 + z1) / 2], [0, 0, 1], z1 - z0, r, r, 0.05)


def sheet(size=40, step=0.5, z=0.0, notch=None, seed=3):
    """sheet.ts: a flat sheet of scan, its points scattered a little along it."""
    rng = np.random.default_rng(seed)
    n = round(size / step)
    P = []
    for j in range(n + 1):
        for i in range(n + 1):
            border = i in (0, n) or j in (0, n)
            a = -size / 2 + i * step + (0 if border else (rng.random() - 0.5) * 0.4 * step)
            b = -size / 2 + j * step + (0 if border else (rng.random() - 0.5) * 0.4 * step)
            P.append([a, b, z])
    F = []
    for j in range(n):
        for i in range(n):
            ca, cb = -size / 2 + (i + 0.5) * step, -size / 2 + (j + 0.5) * step
            if notch and ca > notch[0] and abs(cb) < notch[1] / 2:
                continue
            at = lambda i, j: j * (n + 1) + i  # noqa: E731
            F += [[at(i, j), at(i + 1, j), at(i + 1, j + 1)], [at(i, j), at(i + 1, j + 1), at(i, j + 1)]]
    return np.array(P), np.array(F)


def grid_sheet(n=10):
    x = np.arange(n + 1.0)
    X, Y = np.meshgrid(x, x, indexing="ij")
    P = np.c_[X.ravel(), Y.ravel(), np.zeros(X.size)]
    idx = lambda i, j: i * (n + 1) + j  # noqa: E731
    F = []
    for i in range(n):
        for j in range(n):
            F += [[idx(i, j), idx(i + 1, j), idx(i + 1, j + 1)], [idx(i, j), idx(i + 1, j + 1), idx(i, j + 1)]]
    return P, np.array(F)


def shut(V, F):
    return M.closedness(F, len(V))


class Densify(unittest.TestCase):
    def test_cuts_a_box_closed_and_of_the_same_volume(self):
        P, F = cad_box(60, 40, 6)
        V2, F2, vmap, rep = DE.densify_mesh(P, F, 1)
        self.assertLessEqual(rep["longest"], 1 + 1e-9)
        self.assertEqual(rep["trianglesBefore"], 12)
        self.assertEqual(rep["triangles"], len(F2))
        self.assertEqual(rep["added"], len(V2) - 8)
        # Every directed edge once, and its reverse once: closed, no T-junction.
        a, b = F2.reshape(-1), F2[:, [1, 2, 0]].reshape(-1)
        keys = a * len(V2) + b
        self.assertEqual(len(np.unique(keys)), len(keys))
        self.assertTrue(np.isin(b * len(V2) + a, keys).all())
        self.assertAlmostEqual(G.signed_volume(V2, F2), 60 * 40 * 6, 6)
        self.assertEqual(vmap.tolist(), list(range(8)))
        np.testing.assert_array_equal(V2[:8], P)
        x, y, z = V2[8:].T
        on = np.min(np.abs(np.stack([x, 60 - x, y, 40 - y, z, 6 - z])), axis=0)
        self.assertTrue((on < 1e-5).all())

    def test_leaves_a_mesh_with_no_edge_too_long(self):
        P, F = cad_box(1, 1, 1)
        V2, F2, _, rep = DE.densify_mesh(P, F, 5)
        self.assertEqual(rep["added"], 0)
        np.testing.assert_array_equal(F2, F)

    def test_refuses_too_many_triangles_and_nothing(self):
        P, F = cad_box(1000, 1000, 1000)
        with self.assertRaisesRegex(M.MeshError, "longer maximum edge"):
            DE.densify_mesh(P, F, 0.01)
        with self.assertRaisesRegex(M.MeshError, "above zero"):
            DE.densify_mesh(P, F, 0)

    def test_edge_to_start(self):
        self.assertEqual(DE.densify_edge_for(173), 2)
        self.assertEqual(DE.densify_edge_for(1), 0.05)


class Solids(unittest.TestCase):
    def test_a_tilted_cylinder_closed_outward_to_the_chord(self):
        V, F = SO.frustum([1, 2, 3], [1, 1, 0], 10, 2, 2, 0.01)
        V, F = BO.weld(V, F)
        self.assertEqual(shut(V, F), {"open": 0, "bad": 0})
        n = SO.segments_for(2, 0.01)
        ngon = n / 2 * 4 * math.sin(2 * math.pi / n)
        self.assertAlmostEqual(G.signed_volume(V, F), ngon * 10, 6)
        self.assertLess(2 * (1 - math.cos(math.pi / n)), 0.01 + 1e-9)

    def test_a_cone_to_its_tip_a_frustum_and_a_sphere(self):
        for r0, r1 in ((0, 3), (1, 3)):
            V, F = BO.weld(*SO.element_solid({"kind": "cone", "center": [0, 0, 0], "axis": [0, 0, 1], "length": 6, "radius1": r0, "radius2": r1}, 0.05))
            self.assertEqual(shut(V, F), {"open": 0, "bad": 0})
            self.assertGreater(G.signed_volume(V, F), 0)
        V, F = BO.weld(*SO.element_solid({"kind": "sphere", "center": [0, 0, 0], "radius": 5}, 0.01))
        self.assertEqual(shut(V, F), {"open": 0, "bad": 0})
        self.assertLess(abs(G.signed_volume(V, F) / (4 / 3 * math.pi * 125) - 1), 0.01)

    def test_no_solid_for_a_kind_with_no_volume(self):
        self.assertIsNone(SO.element_solid({"kind": "plane"}))
        self.assertEqual(SO.drawn_fit({"kind": "cylinder", "radius": 2}, 6)["radius"], 3)
        self.assertEqual(SO.names_of(["A", "B", "C"]), "A, B and C")


class Boolean(unittest.TestCase):
    def test_says_what_is_wrong_before_any_kernel(self):
        V, F = box_mesh(20, 20, 20, 8)
        with self.assertRaisesRegex(M.MeshError, r"not closed — 3 open edges.*Fill holes"):
            BO.boolean_mesh(V, F[1:], [(*cylinder(3, -5, 15), None)], "subtract")
        cv, cf = cylinder(3, -5, 15)
        with self.assertRaisesRegex(M.MeshError, r"^Bore did not come out as a closed mesh"):
            BO.boolean_mesh(V, F, [(cv, cf[1:], "Bore")], "subtract")

    def test_runs_without_freecad(self):
        V, F = box_mesh(20, 20, 20, 8)
        V2, F2, _, rep = BO.boolean_mesh(V, F, [(*cylinder(3, -5, 15), None)], "subtract")
        self.assertEqual(shut(V2, F2), {"open": 0, "bad": 0})
        self.assertLess(rep["volumeAfter"], 8000)

    def test_names_a_solid_that_misses_and_carries_the_vertices(self):
        # A kernel that knows only solids apart: nothing is taken, nothing
        # is shared — the refusals and the carrying round it are the port's.
        def apart(op, a, b):
            if op == "add":
                return np.vstack([a[0], b[0]]), np.vstack([a[1], b[1] + len(a[0])])
            return (a[0], a[1]) if op == "subtract" else (np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64))

        V, F = box_mesh(20, 20, 20, 8)
        far = (*cylinder(2, 20, 30), "Cylinder 2")
        with self.assertRaisesRegex(M.MeshError, "^Cylinder 2 does not reach the mesh"):
            BO.boolean_mesh(V, F, [far], "subtract", apart)
        with self.assertRaisesRegex(M.MeshError, "^The solid does not reach"):
            BO.boolean_mesh(V, F, [(*cylinder(2, 20, 30), None)], "subtract", apart)
        with self.assertRaisesRegex(M.MeshError, "do not overlap"):
            BO.boolean_mesh(V, F, [far], "intersect", apart)
        V2, F2, vmap, kept = BO.carry_vertices(V, len(V), V[::-1].astype(np.float32), F)
        self.assertEqual(kept, len(F))
        np.testing.assert_array_equal(V2[vmap], V)

    def test_inside_is_read_off_the_surface_in_the_result(self):
        # As the original: a bore is judged by how much of its surface the
        # result holds, never by the result's volume. This stand-in hands back
        # the mesh and, of the bore, only the faces whose corners all lie in
        # the box — the bore's bottom cap, a part of its surface — and nothing
        # of the volume a real cut would leave; a bore poking out is cut.
        def part(op, a, b):
            inner = (np.abs(b[0][b[1]]) < 10).all(axis=(1, 2))
            return np.vstack([a[0], b[0]]), np.vstack([a[1], b[1][inner][:, ::-1] + len(a[0])])

        V, F = box_mesh(20, 20, 20, 8)
        bore = cylinder(3, -5, 15)
        _, _, _, rep = BO.boolean_mesh(V, F, [(*bore, "Bore")], "subtract", part)
        self.assertGreater(rep["added"], 0)
        self.assertGreater(BO.surface_share(*part("subtract", (V, F), bore), bore, (V, F)), BO.SHARE_NONE)

        # All of it back: a hollow sealed inside, refused in the original's words.
        def sealed(op, a, b):
            return np.vstack([a[0], b[0]]), np.vstack([a[1], b[1][:, ::-1] + len(a[0])])

        with self.assertRaisesRegex(M.MeshError, "^Bore lies wholly inside the mesh — taking it away would seal a hollow"):
            BO.boolean_mesh(V, F, [(*cylinder(3, -5, 5), "Bore")], "subtract", sealed)
        # None of it back, yet in the mesh: a kernel that drops the sealed
        # shell — still a hollow, not a miss.
        with self.assertRaisesRegex(M.MeshError, "^Bore lies wholly inside the mesh"):
            BO.boolean_mesh(V, F, [(*cylinder(3, -5, 5), "Bore")], "subtract", lambda op, a, b: a)
        with self.assertRaisesRegex(M.MeshError, "^Boss lies wholly inside the mesh — there is nothing to add"):
            BO.boolean_mesh(V, F, [(*cylinder(3, -5, 5), "Boss")], "add", lambda op, a, b: a)
        self.assertAlmostEqual(BO.winding(V, F, [0, 0, 0]), 1, 6)
        self.assertAlmostEqual(BO.winding(V, F, [0, 0, 30]), 0, 6)

    def test_bore_boss_and_common(self):
        V, F = box_mesh(20, 20, 20, 8)
        n = SO.segments_for(3, 0.05)
        ngon = n / 2 * 9 * math.sin(2 * math.pi / n)
        V2, F2, vmap, rep = BO.boolean_mesh(V, F, [(*cylinder(3, -5, 15), "Bore")], "subtract")
        self.assertEqual(shut(V2, F2), {"open": 0, "bad": 0})
        self.assertAlmostEqual(G.signed_volume(V2, F2), 8000 - ngon * 15, 0)
        self.assertGreater(rep["removed"], 0)
        _, _, _, rep = BO.boolean_mesh(V, F, [(*cylinder(3, 5, 15), "Boss")], "add")
        self.assertAlmostEqual(rep["volumeAfter"], 8000 + ngon * 5, 0)
        _, _, _, rep = BO.boolean_mesh(V, F, [(*cylinder(3, 5, 15), "Boss")], "intersect")
        self.assertAlmostEqual(rep["volumeAfter"], ngon * 5, 0)
        with self.assertRaisesRegex(M.MeshError, "wholly inside"):
            BO.boolean_mesh(V, F, [(*cylinder(3, -5, 5), None)], "subtract")

    def test_a_kernel_result_inside_out_is_turned_outward(self):
        V, F = box_mesh(20, 20, 20, 4)
        V2, F2 = BO.outward(V, F[:, ::-1])
        self.assertAlmostEqual(BO.volume(V2, F2), 8000, 6)
        self.assertEqual(shut(V2, F2), {"open": 0, "bad": 0})
        # A hollow: its wall faces into the hollow, whichever way both came.
        hollow = joined((V, F), cuboid([-3] * 3, [3] * 3))
        for flips in ((False, True), (True, False), (True, True), (False, False)):
            HV, HF = hollow
            HF = HF.copy()
            n = len(F)
            if flips[0]:
                HF[:n] = HF[:n, ::-1]
            if flips[1]:
                HF[n:] = HF[n:, ::-1]
            OV, OF = BO.outward(HV, HF)
            self.assertAlmostEqual(BO.volume(OV, OF[:n]), 8000, 6)
            self.assertAlmostEqual(BO.volume(OV, OF[n:]), -216, 6)
        # An open piece (a cut's patches meeting in T-junctions) is turned by which way it faces.
        self.assertTrue(np.array_equal(BO.outward(V, F[1:, ::-1])[1], F[1:]))
        self.assertTrue(np.array_equal(BO.outward(V, F[1:])[1], F[1:]))

    def test_the_freecad_kernel_turns_its_result_outward(self):
        from unittest import mock

        class Pt:
            def __init__(self, p):
                self.x, self.y, self.z = p

        class FakeMesh:
            """FreeCAD's Mesh as the booleans use it, its difference handed
            back inside out the way FreeCAD 1.0 to 1.1 hand it back."""

            def __init__(self, tris=None):
                self.tris = tris or []
                self.harmonized = False

            def addFacets(self, tris):
                self.tris += [list(t) for t in tris]

            def difference(self, other):
                return FakeMesh([t[::-1] for t in self.tris])

            unite = intersect = lambda self, other: FakeMesh(list(self.tris))

            def harmonizeNormals(self):
                self.harmonized = True

            @property
            def Topology(self):
                pts, idx, tris = [], {}, []
                for t in self.tris:
                    tris.append(tuple(idx.setdefault(p, len(idx)) for p in t))
                pts = [Pt(p) for p in sorted(idx, key=idx.get)]
                return pts, tris

        fake = type(sys)("Mesh")
        fake.Mesh = FakeMesh
        with mock.patch.dict(sys.modules, {"Mesh": fake}):
            kernel = BO.freecad_kernel()
            box = box_mesh(20, 20, 20, 4)
            for op in ("subtract", "add", "intersect"):
                RV, RF = kernel(op, box, box)
                self.assertAlmostEqual(BO.volume(RV, RF), 8000, 3)


class NearSurfaceGrid(unittest.TestCase):
    def test_large_triangles_and_a_small_reach_stay_bounded(self):
        # trim's on-body check: a box of 2.5 mm triangles searched within
        # 1e-3 once filed each triangle under millions of cells (12e9 in all).
        V, F = box_mesh(20, 20, 20, 8)
        near = G.NearSurface(V, F, 1e-3)
        self.assertLessEqual(len(near.tris), max(8 * len(F), G.FILE_TARGET))
        c = V[F].mean(axis=1)
        found, d, _, face = near.nearest(np.vstack([c, c + [0, 0, 0.5]]))
        self.assertTrue(found[: len(F)].all())
        np.testing.assert_array_equal(face[: len(F)], np.arange(len(F)))
        self.assertLess(d[: len(F)].max(), 1e-9)
        far = np.abs(c[:, 2]) < 9.99  # the side walls' points, moved up along them, stay on them
        self.assertFalse(found[len(F):][~far].any())

    def test_too_many_entries_refuses_without_allocating(self):
        V, F = box_mesh(20, 20, 20, 8)
        old = G.MAX_FILED
        G.MAX_FILED = 100
        try:
            with self.assertRaisesRegex(M.MeshError, "too large to search near its surface"):
                G.NearSurface(V, F, 1e-3)
        finally:
            G.MAX_FILED = old


class Shell(unittest.TestCase):
    def test_wall_to_start_and_what_the_mesh_calls_for(self):
        self.assertEqual(SH.default_wall_thickness(250), 2)
        self.assertEqual(SH.default_wall_thickness(60), 0.5)
        self.assertEqual(SH.shell_mode_of(0, 0, 0), "hollow")
        self.assertEqual(SH.shell_mode_of(12, 2, 2), "holes")
        self.assertEqual(SH.shell_mode_of(12, 2, 1), "thicken")

    def test_hollows_a_box_into_a_box(self):
        V, F = box_mesh(20, 20, 20, 8)
        V2, F2, vmap, rep = SH.hollow_mesh(V, F, 2)
        self.assertEqual(shut(V2, F2), {"open": 0, "bad": 0})
        self.assertEqual(rep["cavities"], 1)
        self.assertLess(abs(rep["removed"] / 16 ** 3 - 1), 0.03)
        self.assertAlmostEqual(G.signed_volume(V2, F2), rep["volumeBefore"] - rep["removed"], 3)
        self.assertEqual(vmap.tolist(), list(range(len(V))))
        inner = V2[np.unique(F2[len(F):])]
        self.assertTrue((inner.min(axis=0) > -8.1).all() and (inner.max(axis=0) < 8.1).all() and (inner.max(axis=0) > 7.7).all())

    def test_leaves_a_thin_part_solid_and_refuses_one_with_holes(self):
        with self.assertRaisesRegex(M.MeshError, "Nothing to hollow"):
            SH.hollow_mesh(*box_mesh(3, 3, 3, 4), 2)
        with self.assertRaisesRegex(M.MeshError, "not closed"):
            SH.hollow_mesh(*grid_sheet(), 1)

    def test_thickens_a_sheet_in_out_or_both_into_a_closed_slab(self):
        P, F = grid_sheet(10)
        ways = {"in": (-1, 0), "out": (0, 1), "both": (-0.5, 0.5)}
        for side, (lo, hi) in ways.items():
            V2, F2, vmap, rep = SH.thicken_mesh(P, F, 1, side)
            self.assertEqual(shut(V2, F2), {"open": 0, "bad": 0})
            self.assertAlmostEqual(G.signed_volume(V2, F2), 100, 3)
            self.assertAlmostEqual(V2[:, 2].min(), lo, 5)
            self.assertAlmostEqual(V2[:, 2].max(), hi, 5)
            self.assertEqual(rep["rimEdges"], 40)
            self.assertEqual(rep["triangles"], 200 + 80)
            if side != "both":
                self.assertTrue((V2[vmap, 2] == 0).all())


class Wrap(unittest.TestCase):
    def test_gap_to_start(self):
        self.assertEqual(WR.default_wrap_gap(200), 1)
        self.assertEqual(WR.default_wrap_gap(400), 2)
        self.assertEqual(WR.default_wrap_gap(30), 0.2)

    def test_a_box_with_a_box_inside_wraps_to_the_outer_box(self):
        outer, inner = cuboid([-10] * 3, [10] * 3, 6), cuboid([-4] * 3, [4] * 3, 4)
        V, F = joined(outer, inner)
        WV, WF, bridge, rep = WR.wrap_mesh(V, F, 1, edges="smooth")
        self.assertEqual(shut(WV, WF), {"open": 0, "bad": 0})
        self.assertEqual(rep["shells"], 1)
        self.assertGreater(rep["volume"], 8000 * 0.995)
        self.assertLess(rep["volume"], 8000 * 1.0001)
        self.assertEqual(rep["dropped"], len(inner[1]))
        self.assertTrue((np.abs(WV).max(axis=1) > 9.9).all())
        # Edges: Sharp puts the box's edges and corners back.
        WV, WF, bridge, rep = WR.wrap_mesh(V, F, 1, edges="sharp")
        self.assertEqual(shut(WV, WF), {"open": 0, "bad": 0})
        self.assertEqual(rep["sharpCorners"], 8)
        self.assertAlmostEqual(rep["volume"], 8000, 2)
        np.testing.assert_allclose(np.abs(WV).max(axis=1), 10, atol=1e-4)

    def test_bridges_a_slot_narrower_than_the_gap_and_follows_one_wider(self):
        gap = 2
        narrow, wide = 0.8 * gap, 1.5 * gap
        V, F = joined(cuboid([0, 0, 0], [40, 20, 4]), cuboid([0, 0, 3], [10, 20, 12]), cuboid([10 + narrow, 0, 3], [24, 20, 12]), cuboid([24 + wide, 0, 3], [40, 20, 12]))
        WV, WF, bridge, rep = WR.wrap_mesh(V, F, gap, edges="smooth")
        self.assertEqual(shut(WV, WF), {"open": 0, "bad": 0})
        self.assertEqual(rep["shells"], 1)
        self.assertGreater(rep["bridgedArea"], narrow * 20 * 0.5)
        # Nothing of the wrap goes down the narrow slot (the base's bottom,
        # unreduced here, has grid points under it: from z = 1 up).
        x, y, z = WV.T
        self.assertFalse(((z > 1) & (z < 10) & (y > 2) & (y < 18) & (x > 10.05) & (x < 10 + narrow - 0.05)).any())
        part = 40 * 20 * 4 + 20 * 8 * (10 + (24 - 10 - narrow) + (40 - 24 - wide))
        self.assertLess(abs(rep["volume"] - part - narrow * 20 * 8), 15)

    def test_refuses_an_open_sheet_at_grow_0_and_makes_it_a_slab(self):
        V, F = box_mesh(20, 20, 2, 4)
        top = F[V[F].mean(axis=1)[:, 2] > 0.99]
        V = V.copy()
        V[:, 2] = 0
        with self.assertRaisesRegex(M.MeshError, "Nothing to wrap — the mesh is an open surface"):
            WR.wrap_mesh(V, top, 1)
        WV, WF, _, rep = WR.wrap_mesh(V, top, 1, grow=0.5)
        self.assertEqual(shut(WV, WF), {"open": 0, "bad": 0})
        self.assertEqual(rep["shells"], 1)
        self.assertAlmostEqual(WV[:, 2].max(), 0.5, 1)
        self.assertAlmostEqual(WV[:, 2].min(), -0.5, 1)
        slab = 400 + 80 * math.pi * 0.125
        self.assertLess(abs(rep["volume"] / slab - 1), 0.03)

    def test_grows_the_wrap_all_round(self):
        a, t = 10, 0.25
        V, F = cuboid([0, 0, 0], [a, a, a], 4)
        WV, WF, _, rep = WR.wrap_mesh(V, F, 2, grow=t, edges="sharp")
        self.assertEqual(shut(WV, WF), {"open": 0, "bad": 0})
        self.assertEqual(rep["sharpEdges"] + rep["sharpCorners"], 0)
        exact = a ** 3 + 6 * a * a * t + 3 * math.pi * a * t * t + 4 / 3 * math.pi * t ** 3
        self.assertGreater(rep["volume"], exact * 0.99)
        self.assertLess(rep["volume"], exact * 1.001)
        d = np.maximum(0, np.abs(WV - a / 2) - a / 2)
        off = np.abs(np.linalg.norm(d, axis=1) - t)
        self.assertGreater((off < 0.01 * rep["cell"]).mean(), 0.8)
        self.assertLess(off.max(), 0.25 * rep["cell"])

    def test_refuses_a_gap_too_fine_for_the_part(self):
        with self.assertRaisesRegex(M.MeshError, "smallest gap that can be closed is"):
            WR.wrap_mesh(*box_mesh(2000, 2000, 2000, 2), 0.01)
        with self.assertRaisesRegex(M.MeshError, "Grow by at most the gap"):
            WR.wrap_mesh(*box_mesh(2, 2, 2, 2), 1, grow=2)


def cracked_box(mn, mx, z, walls_in, face_in):
    """A box whose face at height z is gridded unlike its walls, so the two
    meet in T-junctions, as FreeCAD's cut seams do; each wound either way."""
    W, WF = cuboid(mn, mx, 4)
    C, CF = cuboid(mn, mx, 3)
    WF = WF[~np.isclose(W[WF].mean(axis=1)[:, 2], z)]
    CF = CF[np.isclose(C[CF].mean(axis=1)[:, 2], z)]
    V, F = joined((W, WF[:, ::-1] if walls_in else WF), (C, CF[:, ::-1] if face_in else CF))
    return M.compact_edit(*BO.weld(V, F, 1e-6), 0)[:2]


class Break(unittest.TestCase):
    def setUp(self):
        self.body = NominalSurface(*box_mesh(20, 20, 20, 8))

    def test_the_sheet_the_depth_inside_the_box(self):
        V, F = sheet()
        FV, FF, verts, deep, rep = TR.find_break(V, F, self.body, 0.3, min_piece=1)
        self.assertAlmostEqual(rep["area"], (20 - 0.6) ** 2, 0)
        self.assertEqual((rep["pieces"], rep["specks"]), (1, 0))
        self.assertTrue((self.body.closest(FV).signed < -0.3 + 0.05 + 1e-4).all())
        loops, _ = M.boundary_loops(FF, len(FV))
        self.assertEqual(len(loops), 1)
        self.assertTrue((np.diff(verts) > 0).all())

    def test_narrowed_to_the_marking_and_refused_when_it_misses(self):
        V, F = sheet()
        marked = np.nonzero(V[:, 0] < 0)[0]
        _, _, _, _, rep = TR.find_break(V, F, self.body, 0.3, marked, 1)
        self.assertAlmostEqual(rep["area"] / ((20 - 0.6) * (9.7 - 0.0)), 1, 1)
        with self.assertRaisesRegex(M.MeshError, "The scan nowhere lies more than 0.3 mm inside the body"):
            TR.find_break(V + [100, 0, 0], F, self.body, 0.3)
        with self.assertRaisesRegex(M.MeshError, "Nothing marked lies more than 0.3 mm"):
            TR.find_break(V, F, self.body, 0.3, np.nonzero(V[:, 0] > 15)[0])

    def test_carried_out_past_the_body_and_a_gap_open_to_the_rim_shut(self):
        V, F = sheet()
        FV, FF, _, deep, _ = TR.find_break(V, F, self.body, 0.3, min_piece=1)
        EV, EF, rep = TR.extend_rim(FV, FF, self.body, 0.4, deep)
        self.assertEqual((rep["rims"], rep["holes"], rep["bays"]), (1, 0, 0))
        loops, _ = M.boundary_loops(EF, len(EV))
        self.assertEqual(len(loops), 1)
        self.assertGreater(self.body.closest(EV[loops[0][0]]).signed.min(), 0.4)
        self.assertTrue(np.allclose(EV[:, 2], 0))
        V, F = sheet(notch=(5, 1))
        FV, FF, _, deep, _ = TR.find_break(V, F, self.body, 0.3, min_piece=1)
        _, _, rep = TR.extend_rim(FV, FF, self.body, 0.4, deep)
        self.assertEqual(rep["bays"], 1)

    def test_the_body_is_checked_closed(self):
        body = TR.prepare_body(*box_mesh(20, 20, 20, 8), "Box")
        self.assertAlmostEqual(body[3], 8000, 3)
        with self.assertRaisesRegex(M.MeshError, r"^Box did not come out as a closed mesh"):
            V, F = box_mesh(20, 20, 20, 8)
            TR.prepare_body(V, F[1:], "Box")

    def slab(self, half=0.15):
        body = TR.prepare_body(*box_mesh(20, 20, 20, 8), "Box")
        FV, FF, _, deep, _ = TR.find_break(*sheet(), body[2], 0.3, None, TR.default_break_speck(body[2].bbox_diagonal))
        EV, EF, _ = TR.extend_rim(FV, FF, body[2], M.MAX_STRETCH * half + TR.CLEARANCE, deep)
        SV, SF, _, _ = SH.thicken_mesh(EV, EF, 2 * half, "both")
        return body, (SV, SF), len(EF), TR._area(EV, EF)

    def test_the_slab_is_a_closed_solid_faced_out_its_front_skin_on_the_breaks_facing(self):
        _, (SV, SF), n, area = self.slab()
        self.assertEqual(M.closedness(SF, len(SV)), {"open": 0, "bad": 0})
        self.assertAlmostEqual(BO.volume(SV, SF) / (0.3 * area), 1, 2)
        self.assertGreater(SV[SF[:n]][..., 2].mean(), 0.14)
        self.assertLess(SV[SF[n:2 * n]][..., 2].mean(), -0.14)

    def kernel_answers(self, h=0.15):
        """Box minus slab, exactly, as a kernel might hand it back: clean;
        wound inside out; and in patches meeting in T-junctions (the cut face
        gridded unlike the walls), each patch wound either way."""
        def halves(rebuild):
            return joined(rebuild([-10, -10, h], [10, 10, 10], h), rebuild([-10, -10, -10], [10, 10, -h], -h))

        def plain(mn, mx, z):
            return cuboid(mn, mx, 4)

        def cracked(walls_in, face_in):
            return lambda mn, mx, z: cracked_box(mn, mx, z, walls_in, face_in)

        V, F = halves(plain)
        yield "clean", (V, F)
        yield "inside out", (V, F[:, ::-1])
        for w, f in ((True, True), (True, False), (False, True)):
            yield f"patches {w} {f}", BO.outward(*halves(cracked(w, f)))

    def test_the_cut_sorted_right_whatever_shape_the_kernels_answer_comes_in(self):
        body, (SV, SF), n, _ = self.slab()
        for name, answer in self.kernel_answers():
            for flip in (False, True):
                with self.subTest(name, flip=flip):
                    _, _, _, mating_area, pieces, volume, dropped, specks = TR._cut_body(lambda *a: answer, *body[:2], body[3], SV, SF, n, flip)
                    self.assertEqual((pieces, dropped, specks), (1, 1, 0))
                    self.assertAlmostEqual(volume, 400 * (10 - 0.15), 3)
                    self.assertAlmostEqual(mating_area, 400, 3)
                    self.assertEqual([p["front" if flip else "back"] for p in TR.LAST_CUT["pieces"]].count(0), 1)

    def test_a_hollows_inner_wall_stays_with_the_piece_round_it(self):
        # A box with a sealed hollow above the break: the original's cut
        # (Manifold) carries the hollow's wall through; FreeCAD's mesh
        # difference drops a shell meeting nothing of the slab, or hands it
        # back as a piece of its own. Either way it stays with the kept half
        # — and goes with the dropped half when the side is flipped.
        h = 0.15
        void = cuboid([-4, -4, 2], [4, 4, 6], 4)
        void_in = (void[0], void[1][:, ::-1])
        body = TR.prepare_body(*joined(cuboid([-10] * 3, [10] * 3, 8), void_in), "Box")
        self.assertAlmostEqual(body[3], 8000 - 256, 3)
        FV, FF, _, deep, _ = TR.find_break(*sheet(), body[2], 0.3, None, TR.default_break_speck(body[2].bbox_diagonal))
        EV, EF, _ = TR.extend_rim(FV, FF, body[2], M.MAX_STRETCH * h + TR.CLEARANCE, deep)
        SV, SF, _, _ = SH.thicken_mesh(EV, EF, 2 * h, "both")
        top, bottom = cuboid([-10, -10, h], [10, 10, 10], 4), cuboid([-10, -10, -10], [10, 10, -h], 4)
        answers = {"wall dropped": joined(top, bottom), "wall kept": joined(top, bottom, void_in), "wall alone, inside out": joined(top, bottom, void)}
        for name, answer in answers.items():
            answer = BO.outward(*answer) if name != "wall dropped" else answer
            for flip in (False, True):
                with self.subTest(name, flip=flip):
                    V, F, _, mating_area, pieces, volume, dropped, specks = TR._cut_body(lambda *a, answer=answer: answer, *body[:2], body[3], SV, SF, len(EF), flip)
                    self.assertEqual((pieces, dropped, specks), (1, 1, 0))
                    self.assertAlmostEqual(volume, 400 * (10 - h) - (0 if flip else 256), 3)
                    self.assertAlmostEqual(BO.volume(V, F), volume, 3)
                    self.assertAlmostEqual(mating_area, 400, 3)
                    self.assertEqual(TR.LAST_CUT["restored"], 1 if name == "wall dropped" else 0)

    def test_outward_turns_patches_of_an_open_shell(self):
        V2, F2 = BO.outward(*cracked_box([0, 0, 0], [2, 3, 4], 4, True, False))
        self.assertAlmostEqual(BO.volume(V2, F2), 24, 6)

    def test_a_box_trimmed_to_a_flat_sheet(self):
        body = TR.prepare_body(*box_mesh(20, 20, 20, 8), "Box")
        for offset, flip in ((0.15, False), (0.15, True)):
            try:
                V, F, mating, gap, rep = TR.trim_to_scan(*sheet(), body, 0.3, offset, flip)
                self.assertAlmostEqual(rep["volume"], 400 * (10 - offset), 0)
                self.assertAlmostEqual(rep["matingArea"], 400, 0)
            except Exception as e:
                diagnostic = f"Trim (offset {offset}, flip {flip}): {e}\nFreeCAD's cut: {TR.LAST_CUT}"
                print(diagnostic, file=sys.stderr)
                self.fail(diagnostic)


    def test_a_hollow_box_trimmed_keeps_its_inner_wall(self):
        void = cuboid([-4, -4, 2], [4, 4, 6], 4)
        body = TR.prepare_body(*joined(box_mesh(20, 20, 20, 8), (void[0], void[1][:, ::-1])), "Box")
        for flip in (False, True):
            try:
                V, F, mating, gap, rep = TR.trim_to_scan(*sheet(), body, 0.3, 0.15, flip)
                self.assertAlmostEqual(rep["volume"], 400 * (10 - 0.15) - (0 if flip else 256), 0)
                self.assertAlmostEqual(BO.volume(V, F), rep["volume"], 0)
                self.assertEqual(rep["pieces"], 1)
            except Exception as e:
                diagnostic = f"Hollow trim (flip {flip}): {e}\nFreeCAD's cut: {TR.LAST_CUT}"
                print(diagnostic, file=sys.stderr)
                self.fail(diagnostic)

class Session:
    def __init__(self, V, F):
        self.family_state = {}
        self.doc = None
        S.state(self)["scan"] = S.Scan("part.stl", V, F)


class Handlers(unittest.TestCase):
    def test_densify_shell_and_wrap_edit_the_copy(self):
        s = Session(*cad_box(20, 20, 20))
        out = H.HANDLERS["mesh_densify"](s, {"maxEdge": 2})
        self.assertEqual(out["edit"]["text"], "densify")
        self.assertEqual(out["mesh"]["working"], "edited copy")
        self.assertAlmostEqual(out["mesh"]["volume"], 8000, 3)
        out = H.HANDLERS["mesh_shell"](s, {"thickness": 2})
        self.assertEqual(out["edit"]["mode"], "hollow")
        self.assertLess(out["mesh"]["volume"], 8000 * 0.6)
        with self.assertRaises(Exception) as c:
            H.HANDLERS["mesh_shell"](s, {"mode": "thicken"})
        self.assertEqual(c.exception.code, "invalid_state")
        s = Session(*joined(cuboid([-10] * 3, [10] * 3, 6), cuboid([-4] * 3, [4] * 3, 4)))
        out = H.HANDLERS["mesh_wrap"](s, {"gap": 1, "edges": "smooth"})
        self.assertEqual(out["wrap"]["shells"], 1)
        self.assertIn("mesh_apply_wrap", out["status"])
        out = H.HANDLERS["mesh_apply_wrap"](s, {})
        self.assertEqual(out["mesh"]["open"], 0)
        with self.assertRaises(Exception) as c:
            H.HANDLERS["mesh_apply_wrap"](s, {})
        self.assertEqual(c.exception.code, "invalid_state")

    def test_boolean_and_trim_name_their_solids(self):
        V, F = box_mesh(20, 20, 20, 8)
        s = Session(V, F)
        S.state(s)["elements"] = [{"id": 1, "name": "Bore 1", "kind": "cylinder", "fit": {"kind": "cylinder", "center": [0, 0, 5], "axis": [0, 0, 1], "length": 20, "radius": 3}}]
        with self.assertRaises(Exception) as c:
            H.HANDLERS["mesh_boolean"](s, {"op": "subtract", "solids": ["Cylinder 9"]})
        self.assertEqual(c.exception.code, "not_found")
        out = H.HANDLERS["mesh_boolean"](s, {"op": "subtract", "solids": ["Bore 1", 1]})
        self.assertEqual(out["edit"]["solid"], "Bore 1")
        self.assertEqual((out["mesh"]["open"], out["mesh"]["bad"]), (0, 0))
        self.assertLess(out["mesh"]["volume"], 8000)
        with self.assertRaises(Exception) as c:
            H.HANDLERS["mesh_trim"](Session(*sheet()), {"body": "Bore 1"})
        self.assertIn(c.exception.code, ("not_found", "failed"))
        s2 = Session(V, F[1:])
        S.state(s2)["elements"] = S.state(s)["elements"]
        with self.assertRaises(Exception) as c:
            H.HANDLERS["mesh_boolean"](s2, {"op": "add", "solids": ["Bore 1"]})
        self.assertEqual(c.exception.code, "invalid_state")

    def test_the_tool_data_names_every_handler(self):
        import json

        from scanrulerfc.handlers import meshtools as family

        with open(os.path.join(HERE, "..", "scanrulerfc", "data", "tools.json"), encoding="utf-8") as f:
            doc = json.load(f)
        # In the add-on's one tool data, in the meshtools family.
        for n in H.NAMES:
            self.assertEqual(doc["entries"][n]["group"], "meshtools", n)
            self.assertIn(n, family.NAMES)
        try:
            from agentlink import tooldata
        except ImportError:
            return
        self.assertEqual(tooldata.check(doc), [])



class _Pt:
    def __init__(self, p):
        self.x, self.y, self.z = p


class CountDecimator:
    """A stand-in for FreeCAD's Mesh with decimate(targetSize) as the
    1.1 source has it (src/Mod/Mesh/App/Core/Simplify.h, simplify_mesh):
    it comes down to the count asked whatever that costs in shape — here a
    40 x 30 x 20 box regridded to at most that count, its faces bulged by
    40 / count mm (so 4,000 triangles lie 0.01 mm off, 400 lie 0.1 mm off).

    And, as that loop reads and as the same source compiled by itself did
    on a densified block with a bore (asked 500 and asked 100 it left the
    same 704 triangles, 11 mm off; run again on those, 688; a third run,
    688): it can have a count it will not go under. FLOOR is that count
    for a mesh's first run — asking for less changes nothing, the count
    only says when to stop — AGAIN the count a run on its own result
    reaches, and under WRECK triangles what it leaves is OFF mm out (the
    last rounds collapse whatever does not turn a triangle over)."""

    asked = []
    FLOOR = 0
    AGAIN = 0
    WRECK = 0
    OFF = 10.0

    def __init__(self, data=None, runs=0):
        self.V, self.F = (np.asarray(data[0], float), np.asarray(data[1], np.int64)) if data is not None else (np.zeros((0, 3)), np.zeros((0, 3), np.int64))
        self.runs = runs

    def copy(self):
        return CountDecimator((self.V, self.F), self.runs)

    @property
    def CountFacets(self):
        return len(self.F)

    @property
    def Topology(self):
        return [_Pt(p) for p in self.V], [tuple(int(i) for i in t) for t in self.F]

    def decimate(self, *args):
        if len(args) != 1:
            raise AssertionError("mesh_reduce must use decimate(targetSize): the (tolerance, reduction) form holds no tolerance in mm")
        target = int(args[0])
        CountDecimator.asked.append(target)
        floor = self.FLOOR if self.runs == 0 else self.AGAIN
        self.runs += 1
        want = max(target, floor)
        n = max(1, int(math.sqrt(want / 12)))
        if 12 * n * n >= len(self.F):
            return  # nothing it can take off
        V, F = box_mesh(40, 30, 20, n)
        V = np.asarray(V, float)
        bulge = self.OFF if 12 * n * n < self.WRECK else 40.0 / max(12 * n * n, 1)
        inner = (np.abs(np.abs(V) - np.array([20, 15, 10])) > 1e-9).sum(axis=1) == 2  # a face's own points, not its rim
        V[inner] *= 1 + bulge / np.linalg.norm(V[inner], axis=1)[:, None]
        self.V, self.F = V, np.asarray(F, np.int64)


def figures(text):
    """Every number in a sentence, as floats (a full stop ending the
    sentence is not part of one)."""
    import re

    return [float(m) for m in re.findall(r"(?<![\w.])\d+(?:\.\d+)?", text)]


def report_figures(report):
    """Every number a mesh_reduce report holds, and each count's distance
    over the cap (the words give that too)."""
    out = set()

    def walk(v):
        if isinstance(v, bool) or v is None:
            return
        if isinstance(v, (int, float)):
            out.add(float(v))
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)

    walk(report)
    out.add(float(report["triangles"] - report["settings"]["maxTriangles"]))
    return out


class Reduce(unittest.TestCase):
    """Found live (run 2, Mesh Tools model calls 39 and 42): mesh_reduce
    { tolerance: 0.05, maxTriangles: 2000 } answered a mesh 14 mm off (held
    false, 2,136 triangles), and mesh_apply_reduced made it the edited
    copy without a word: volume 8,830 where it had been 22,429."""

    def lightest(self, triangles, cap, tol, err):
        tried = []

        def attempt(target):
            tried.append(target)
            got = int(target * 1.03)
            return {"triangles": got, "worst": err(got)}

        best, capped, tries = M.lightest_within(triangles, cap, tol, attempt)
        self.assertEqual(tries, len(tried))
        return best, capped, tried

    def test_the_count_is_searched_until_the_tolerance_holds(self):
        err = lambda n: 40.0 / n  # noqa: E731 — 0.05 mm at 800 triangles
        best, capped, tried = self.lightest(200_000, 50_000, 0.05, err)
        self.assertFalse(capped)
        self.assertLessEqual(best["worst"], 0.05)
        self.assertLess(best["triangles"], 1400)  # near the 800 that just hold, not the 50,000 of the cap
        self.assertGreaterEqual(best["triangles"], 800)
        self.assertLess(len(tried), 12)

    def test_the_cap_wins_and_says_so(self):
        best, capped, tried = self.lightest(200_000, 500, 0.05, lambda n: 40.0 / n)
        self.assertTrue(capped)
        self.assertEqual(tried, [500])
        self.assertGreater(best["worst"], 0.05)

    def test_nothing_lighter_holds(self):
        best, capped, tried = self.lightest(1000, 50_000, 0.001, lambda n: 40.0 / n)
        self.assertIsNone(best)
        self.assertFalse(capped)

    def test_a_decimator_that_gives_nothing_back(self):
        best, capped, tries = M.lightest_within(1000, 50_000, 0.05, lambda target: None)
        self.assertIsNone(best)

    def tools(self, V, F):
        from scanrulerfc import handlers

        s = Session(V, F)
        s.out_dir = "."
        return s, handlers.bound(s, "meshtools")

    def test_mesh_reduce_holds_its_tolerance_and_apply_warns_when_it_does_not(self):
        from unittest import mock

        fake = type(sys)("Mesh")
        fake.Mesh = CountDecimator
        V, F = box_mesh(40, 30, 20, 40)  # 19,200 triangles
        with mock.patch.dict(sys.modules, {"Mesh": fake}):
            CountDecimator.asked = []
            s, t = self.tools(np.asarray(V, float), np.asarray(F, np.int64))
            red = t["mesh_reduce"]({"tolerance": 0.05})["reduced"]
            self.assertTrue(red["held"], red)
            self.assertFalse(red["capped"])
            self.assertLessEqual(max(red["p999"], red["backP999"]), 0.05)
            self.assertLess(red["triangles"], 2500)  # 800 would just hold: well under the 19,200 it had
            self.assertEqual(red["tries"], len(CountDecimator.asked))
            self.assertNotIn("warning", red)
            out = t["mesh_apply_reduced"]({})
            self.assertNotIn("warning", out)
            self.assertAlmostEqual(out["mesh"]["volume"], 24000, delta=24000 * 0.01)
            # The cap is the harder rule: a mesh that cannot hold the
            # tolerance under it is said to, in the preview and on applying.
            s, t = self.tools(np.asarray(V, float), np.asarray(F, np.int64))
            red = t["mesh_reduce"]({"tolerance": 0.05, "maxTriangles": 200})["reduced"]
            self.assertLessEqual(red["triangles"], 200)
            self.assertEqual((red["held"], red["capped"], red["capMet"], red["won"]), (False, True, True, "cap"))
            self.assertIn("maxTriangles", red["warning"])
            # … and the reply says what count would hold the tolerance
            # (40 / n mm here: 0.05 mm from 800 triangles up).
            self.assertGreaterEqual(red["holds"]["triangles"], 800)
            self.assertLess(red["holds"]["triangles"], 1000)
            self.assertLess(red["notHolding"], red["holds"]["triangles"])
            self.assertIn(f"maxTriangles: {red['holds']['triangles']}", red["warning"])
            out = t["mesh_apply_reduced"]({})
            self.assertIn("does not hold its tolerance", out["warning"])
            self.assertIn("mesh_undo", out["warning"])
            # Nothing lighter holds: the mesh as it is, and a note.
            s, t = self.tools(np.asarray(V, float), np.asarray(F, np.int64))
            red = t["mesh_reduce"]({"tolerance": 0.0001})["reduced"]
            self.assertEqual(red["triangles"], len(F))
            self.assertTrue(red["held"])
            self.assertIn("No lighter mesh holds", red["note"])


class ReduceKeepsItsWord(unittest.TestCase):
    """Found live (run 3, Mesh Tools model calls 39 and 42): asked
    tolerance 0.05 and maxTriangles 2,000 on 10,022 triangles, mesh_reduce
    answered 2,142 triangles — over the cap — 10.4 mm off, with capped:
    true, held: false, tries: 1 and "Brought down to the cap of 2000
    triangles". Three things were wrong: asking FreeCAD's decimator for
    less does not make it go lower (the count only says when to stop:
    src/Mod/Mesh/App/Core/Simplify.h, simplify_mesh), so the cap was
    not kept; the search ended at the first try that did not hold, so
    nothing said where the tolerance starts to hold; and the words named
    the cap, not the count."""

    TOL = 0.05

    def search(self, triangles, cap, off, floor=0, **kw):
        tried = []

        def attempt(target):
            tried.append(target)
            got = max(int(target), floor)
            return None if got >= triangles else {"triangles": got, "worst": off(got)}

        out = M.reduction_search(triangles, cap, self.TOL, attempt, **kw)
        self.assertEqual(out["tries"], len(tried))
        return out, tried

    def test_cap_and_tolerance_both_hold_and_the_search_goes_on_down(self):
        out, tried = self.search(200_000, 50_000, lambda n: 40.0 / n)
        self.assertEqual((out["won"], out["capMet"], out["ended"]), ("both", True, "done"))
        self.assertEqual(tried[0], 50_000)
        self.assertLessEqual(out["best"]["worst"], self.TOL)
        self.assertLess(out["best"]["triangles"], 1400)  # 800 just hold
        self.assertGreaterEqual(out["best"]["triangles"], 800)
        self.assertIsNone(out["holds"])

    def test_the_cap_wins_and_the_count_that_would_hold_is_found(self):
        out, tried = self.search(200_000, 500, lambda n: 40.0 / n)
        self.assertEqual((out["won"], out["capMet"]), ("cap", True))
        self.assertEqual(out["best"]["triangles"], 500)
        self.assertIs(out["best"], out["atCap"])
        self.assertGreater(out["best"]["worst"], self.TOL)
        # 800 triangles is where 0.05 mm starts to hold: found from above,
        # with the largest count that did not hold beside it.
        self.assertGreaterEqual(out["holds"]["triangles"], 800)
        self.assertLess(out["notHolding"], 800)
        self.assertLessEqual(out["holds"]["triangles"], out["notHolding"] * 1.12)
        self.assertLessEqual(len(tried), 1 + M.REDUCE_CLIMB)

    def test_the_cap_cannot_be_met_so_the_tolerance_wins(self):
        # The decimator stops at 2,142 whatever is asked, and what it
        # leaves there is wrecked; from 2,600 up the tolerance holds.
        out, tried = self.search(10_022, 2000, lambda n: 10.4 if n < 2600 else 0.004, floor=2142)
        self.assertEqual((out["won"], out["capMet"]), ("tolerance", False))
        self.assertEqual(out["atCap"]["triangles"], 2142)
        self.assertGreaterEqual(out["best"]["triangles"], 2600)
        self.assertLess(out["best"]["triangles"], 2600 * 1.12)
        self.assertLessEqual(out["best"]["worst"], self.TOL)
        self.assertGreater(out["tries"], 1)  # tries: 1 was the live fault
        self.assertGreaterEqual(out["notHolding"], 2142)

    def test_stopped_above_the_cap_where_it_holds(self):
        out, tried = self.search(10_022, 2000, lambda n: 0.004, floor=2142)
        self.assertEqual((out["won"], out["capMet"]), ("tolerance", False))
        self.assertIs(out["best"], out["atCap"])
        self.assertEqual(tried, [2000])

    def test_stopped_above_the_cap_and_nothing_lighter_holds(self):
        out, tried = self.search(10_022, 2000, lambda n: 10.4, floor=2142)
        self.assertEqual((out["won"], out["capMet"]), ("tolerance", False))
        self.assertIsNone(out["best"])  # the mesh as it is
        self.assertIsNone(out["holds"])
        self.assertLessEqual(len(tried), 1 + M.REDUCE_CLIMB)

    def test_a_decimator_that_gives_nothing_back(self):
        out = M.reduction_search(10_022, 2000, self.TOL, lambda target: None)
        self.assertIsNone(out["best"])
        self.assertFalse(out["capMet"])
        self.assertIsNone(out["atCap"])

    def test_the_time_allowed_ends_the_search_and_says_so(self):
        now = [0.0]

        def clock():
            now[0] += 4.0  # every look at the clock is four seconds on
            return now[0]

        out, tried = self.search(200_000, 500, lambda n: 40.0 / n, seconds=10.0, clock=clock)
        self.assertEqual(out["ended"], "time")
        self.assertEqual(tried[0], 500)  # the try at the cap is always made
        self.assertLess(len(tried), 1 + M.REDUCE_CLIMB)
        self.assertEqual((out["won"], out["best"]["triangles"]), ("cap", 500))
        out, tried = self.search(200_000, 500, lambda n: 40.0 / n, seconds=1e9)
        self.assertEqual(out["ended"], "done")

    # ---- the tool, on a decimator that stops where the source says it can ----

    def reduce(self, args, floor=0, again=0, wreck=0, n=29):
        from unittest import mock

        from scanrulerfc import handlers

        fake = type(sys)("Mesh")
        fake.Mesh = CountDecimator
        V, F = box_mesh(40, 30, 20, n)  # n 29: 10,092 triangles (10,022 live)
        s = Session(np.asarray(V, float), np.asarray(F, np.int64))
        s.out_dir = "."
        t = handlers.bound(s, "meshtools")
        with mock.patch.dict(sys.modules, {"Mesh": fake}), mock.patch.multiple(CountDecimator, FLOOR=floor, AGAIN=again, WRECK=wreck, asked=[]):
            red = t["mesh_reduce"](args)["reduced"]
            asked = list(CountDecimator.asked)
            applied = t["mesh_apply_reduced"]({})
        return red, applied, asked

    def words_match(self, red, text):
        have = report_figures(red)
        for x in figures(text):
            self.assertTrue(any(abs(x - h) < 1e-9 for h in have), f"{x:g} is in the words and not in the report: {text}")

    def test_the_live_call_again(self):
        # Asked 2,000; the decimator stops at 2,142 on its first run (12 x
        # 13² = 2,028 here), a run on its own result takes nothing more
        # off, and under 2,500 triangles what it leaves is 10 mm out.
        red, applied, asked = self.reduce({"tolerance": 0.05, "maxTriangles": 2000}, floor=2142, again=2100, wreck=2500)
        self.assertEqual(red["inputTriangles"], 10_092)
        self.assertFalse(red["capMet"])
        self.assertEqual(red["won"], "tolerance")
        self.assertFalse(red["capped"])  # the cap did not come first: it could not be met
        self.assertTrue(red["held"], red)
        self.assertLessEqual(max(red["p999"], red["backP999"]), 0.05)
        self.assertEqual(red["triangles"], 2700)  # 12 x 15²: the lightest this decimator makes that holds
        self.assertGreater(red["tries"], 1)
        self.assertEqual(red["search"]["tries"], red["tries"])
        self.assertEqual(red["search"]["ended"], "done")
        # The true count at the cap, how it was reached and how far off.
        self.assertEqual((red["atCap"]["asked"], red["atCap"]["triangles"], red["atCap"]["passes"]), (2000, 2028, 2))
        self.assertGreater(red["atCap"]["max"], 5)
        self.assertEqual(asked[:2], [2000, 2000])  # run again on what it left, not asked for less
        w = red["warning"]
        self.assertIn("maxTriangles 2000 could not be met", w)
        self.assertIn("stops at 2028 triangles", w)
        self.assertIn("The tolerance won", w)
        self.assertIn("2700 triangles", w)
        self.assertNotIn("rought down to", w)
        self.words_match(red, w)
        # Applied, it says the same: over the cap, and why.
        self.assertEqual(applied["mesh"]["triangles"], 2700)
        self.assertIn("2700 triangles, over the maxTriangles of 2000", applied["warning"])
        self.assertIn("stops at 2028", applied["warning"])
        self.assertIn("holds its tolerance", applied["warning"])
        self.assertIn("mesh_undo", applied["warning"])
        self.words_match(red, applied["warning"])

    def test_a_second_run_gets_under_the_cap(self):
        # 2,142 on the first run, under 2,000 on a run of what that left:
        # the cap is kept, the mesh is 10 mm out, and the cap wins.
        red, applied, asked = self.reduce({"tolerance": 0.05, "maxTriangles": 2000}, floor=2142, again=1000, wreck=2500)
        self.assertLessEqual(red["triangles"], 2000)
        self.assertEqual((red["capMet"], red["won"], red["capped"], red["held"]), (True, "cap", True, False))
        self.assertNotIn("atCap", red)  # the try at the cap is the answer itself
        self.assertEqual(red["holds"]["triangles"], 2700)
        self.assertGreaterEqual(red["notHolding"], 2000)
        w = red["warning"]
        self.assertIn("The cap won over the tolerance", w)
        self.assertIn(f"brought down to {red['triangles']} triangles (maxTriangles 2000)", w)
        self.assertIn("mesh_reduce { maxTriangles: 2700 }", w)
        self.assertIn("mesh_discard", w)
        self.words_match(red, w)
        self.assertIn("does not hold its tolerance", applied["warning"])
        self.assertIn("2700 triangles would hold it", applied["warning"])
        self.words_match(red, applied["warning"])

    def test_stopped_above_the_cap_with_a_mesh_that_holds(self):
        red, applied, asked = self.reduce({"tolerance": 0.05, "maxTriangles": 2000}, floor=2142, again=2100)
        self.assertEqual((red["triangles"], red["capMet"], red["won"], red["held"]), (2028, False, "tolerance", True))
        self.assertIn("could not be met", red["warning"])
        self.assertIn("stops at 2028 triangles", red["warning"])
        self.assertIn("28 over the cap", red["warning"])
        self.words_match(red, red["warning"])
        self.assertIn("2028 triangles, over the maxTriangles of 2000", applied["warning"])
        self.words_match(red, applied["warning"])

    def test_the_cap_cannot_be_met_and_no_lighter_mesh_holds(self):
        red, applied, asked = self.reduce({"tolerance": 0.05, "maxTriangles": 2000}, floor=2142, again=2100, wreck=10 ** 9)
        self.assertEqual((red["triangles"], red["capMet"], red["held"]), (10_092, False, True))
        self.assertIn("this is the mesh as it is, 10092 triangles", red["warning"])
        self.assertIn("could not be met", red["warning"])
        self.words_match(red, red["warning"])
        self.assertIn("10092 triangles, over the maxTriangles of 2000", applied["warning"])

    def test_both_hold_and_nothing_is_said(self):
        red, applied, asked = self.reduce({"tolerance": 0.05, "maxTriangles": 2000})
        self.assertEqual((red["capMet"], red["won"], red["held"], red["capped"]), (True, "both", True, False))
        self.assertLessEqual(red["triangles"], 2000)
        self.assertLess(red["triangles"], 1300)  # it went on down: 800 just hold
        self.assertNotIn("warning", red)
        self.assertNotIn("note", red)
        self.assertNotIn("warning", applied)

    def test_a_corner_cut_off_shows_the_way_back(self):
        # Every vertex of the reduced mesh on the original, and a triangle
        # through the solid: read at the triangles' middles too.
        from scanrulerfc.handlers import meshtools as HM

        self.assertEqual(len(HM._sampled(np.zeros((9000, 3)), 2000)), 2000)
        red, _, _ = self.reduce({"tolerance": 0.05, "maxTriangles": 2000}, floor=2142, again=1000, wreck=2500)
        self.assertGreater(red["backMax"], 5)  # the bulged faces' middles, not only their rims

    def test_the_description_says_what_the_reply_does(self):
        import json

        with open(os.path.join(HERE, "..", "scanrulerfc", "data", "tools.json"), encoding="utf-8") as f:
            doc = json.load(f)["entries"]
        d = doc["mesh_reduce"]["description"]
        for word in ("capMet", "won", "atCap", "holds", "notHolding", "search", "passes", "decimate(targetSize)", "decimate(tolerance, reduction)"):
            self.assertIn(word, d)
        self.assertIn("over the cap asked", doc["mesh_apply_reduced"]["description"])


class Hardened(unittest.TestCase):
    """The hardening pass of 16 Nov 2026: what the Mesh Tools handlers say
    and keep, in plain Python on a CAD-style box (8 vertices, 12 triangles)."""

    def setUp(self):
        from scanrulerfc.handlers import meshtools as HM

        self.HM = HM
        self.s = Session(*cad_box(40, 30, 20))
        self.t = HM.bind(self.s)

    def refused(self, tool, code, **a):
        with self.assertRaises(Exception) as c:
            self.t[tool](a)
        self.assertEqual(c.exception.code, code, c.exception.message)
        return c.exception.message

    def test_the_wrap_preview_is_listed_and_discarded(self):
        self.assertIn("no wrap to discard", self.refused("mesh_discard", "invalid_state", what="wrap"))
        self.t["mesh_wrap"]({"gap": 4, "edges": "smooth"})
        parts = self.t["mesh_parts"]({})
        self.assertGreater(parts["wrap"]["triangles"], 0)
        self.assertIsNone(parts["piece"])
        self.assertEqual(self.t["mesh_discard"]({"what": "wrap"}), {"discarded": "wrap", "wrap": None})
        self.assertIsNone(self.t["mesh_parts"]({})["wrap"])
        self.assertIn("mesh_reduce makes one", self.refused("mesh_discard", "invalid_state", what="reduced"))

    def test_refusals_say_what_to_do_next(self):
        self.assertIn("no open rim", self.refused("mesh_fill_holes", "invalid_state"))
        msg = self.refused("mesh_cut", "failed", plane="XY", offset=50, keep="minus")
        self.assertIn("from offset 0 to 20", msg)
        self.assertIn("mesh_cut_preview", msg)
        msg = self.refused("mesh_remove_islands", "failed", size=5)
        self.assertIn("mesh_inspect", msg)
        self.t["mesh_densify"]({"maxEdge": 2})
        self.t["mesh_delete_marked"]({"region": {"box": {"min": [14, 9, 19], "max": [26, 21, 21]}}})
        msg = self.refused("mesh_fill_holes", "invalid_input", at=[20, 15, 20])
        self.assertIn("the smallest is 15.05", msg)
        out = self.t["mesh_fill_holes"]({"size": 30, "patch": "flat"})
        self.assertEqual((out["report"]["filled"], out["mesh"]["open"]), (1, 0))
        self.assertAlmostEqual(out["mesh"]["volume"], 24000, 3)

    def test_panel_words_name_their_tools(self):
        self.assertEqual(self.HM.said("close it with Fill holes first."), "close it with Fill holes (mesh_fill_holes) first.")
        self.assertEqual(self.HM.said("Fill holes (mesh_fill_holes)"), "Fill holes (mesh_fill_holes)")
        self.assertIn("mesh_reduce", self.HM.said("too large. Decimate it first."))

    def test_mirror_goes_through_the_middle_of_the_mesh_worked_on(self):
        # After a cut the scan's own middle (Z 10) is no longer the part's (Z 6).
        self.t["mesh_cut"]({"plane": "XY", "offset": 12, "keep": "minus"})
        out = self.t["mesh_mirror"]({"plane": "XY"})
        self.assertIn("Z 6 mm", out["edit"]["text"])
        self.assertEqual(out["mesh"]["bounds"]["max"][2], 12.0)

    def test_trim_on_a_sparse_mesh_says_to_densify(self):
        body = cad_box(10, 10, 10)
        doc = type("Doc", (), {})()
        mesh = type("M", (), {"Topology": ([type("P", (), {"x": p[0] + 35, "y": p[1] + 10, "z": p[2] + 5})() for p in body[0].tolist()], [tuple(t) for t in body[1].tolist()]), "CountFacets": 12})()
        doc.Objects = [type("O", (), {"Name": "Stub", "Label": "Stub", "Mesh": mesh})()]
        self.s.doc = doc
        with self.assertRaises(Exception) as c:
            H.HANDLERS["mesh_trim"](self.s, {"body": "Stub"})
        self.assertIn("mesh_densify first", c.exception.message)
        self.t["mesh_densify"]({"maxEdge": 2})
        out = H.HANDLERS["mesh_trim"](self.s, {"body": "Stub"})
        self.assertAlmostEqual(out["piece"]["volume"], 499, 0)
        self.assertAlmostEqual(out["piece"]["matingArea"], 100, 0)
        self.assertEqual(self.t["mesh_parts"]({})["piece"]["name"], "Stub")


class HardenedData(unittest.TestCase):
    """What data/tools.json declares of the Mesh Tools and 2D tools."""

    def test_flags(self):
        import json

        with open(os.path.join(HERE, "..", "scanrulerfc", "data", "tools.json"), encoding="utf-8") as f:
            E = json.load(f)["entries"]
        # A document write is a change, with its transaction and health; the file write is a read.
        self.assertTrue(E["mesh_export"]["changes"])
        self.assertEqual(E["mesh_export"]["reads"], {"to": ["file"]})
        self.assertEqual(E["mesh_export"]["inputSchema"]["properties"]["to"]["default"], "file")
        self.assertTrue(E["flat_curvature"]["changes"])
        self.assertEqual(E["flat_curvature"]["reads"], {"comb": [False]})
        self.assertIs(E["flat_curvature"]["inputSchema"]["properties"]["comb"]["default"], False)
        # Tools that write the path given are checked as writers.
        for n in ("mesh_export", "flat_export", "flat_render"):
            self.assertTrue(E[n].get("writes"), n)
        for n in ("mesh_smooth", "mesh_reduce", "mesh_cut", "mesh_cut_preview", "mesh_offset", "mesh_inspect", "mesh_shell", "mesh_wrap", "mesh_trim",
                  "flat_open_image", "flat_detect_edges", "flat_calibrate"):
            self.assertTrue(E[n].get("heavy"), n)
        for n, e in E.items():
            if e["group"] in ("meshtools", "flat", "reverse"):
                self.assertEqual(e.get("workbench"), "ScanRulerWorkbench", n)
                self.assertTrue(e.get("words"), n)
                self.assertIn("Stefan Hermann (CNC Kitchen)", e["source"], n)

    def test_a_job_leaves_the_document_write_for_later(self):
        from unittest import mock

        from scanrulerfc import docstate

        s = Session(*cad_box(1, 1, 1))
        with mock.patch.object(docstate, "mark_doc") as mark:
            S.touched(s, "mesh_wrap", write=False)
            self.assertEqual(mark.call_count, 0)
            self.assertEqual(S.state(s)["last_tool"], "mesh_wrap")
            S.touched(s, "mesh_parts")
            self.assertEqual(mark.call_count, 1)


if __name__ == "__main__":
    unittest.main()


class TrimReady(unittest.TestCase):
    def test_is_on(self):
        from scanrulerfc.meshtools import handlers as H

        # Back on since 5be1e43 passed in real FreeCAD 1.0, 1.1 and newest.
        self.assertTrue(H.TRIM_READY)

