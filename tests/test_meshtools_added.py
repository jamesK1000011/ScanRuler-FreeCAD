# SPDX-License-Identifier: AGPL-3.0-only
# The Mesh Tools added headless — Densify, Boolean, Shell (hollow and
# thicken), Wrap and Trim to scan — with ScanRuler's own test cases where it
# has them (plugins/mesh-tools/tests: densify, meshBoolean, measuredSolids,
# meshOffset, wrap, breakSurface, extendRim, trimToScan), on small meshes.
# The boolean and the trim need FreeCAD's Mesh booleans: those cases skip
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

    @unittest.skipIf(HAVE_FREECAD, "FreeCAD is here: the kernel runs")
    def test_needs_freecad_without_it(self):
        V, F = box_mesh(20, 20, 20, 8)
        with self.assertRaises(BO.NeedsKernel):
            BO.boolean_mesh(V, F, [(*cylinder(3, -5, 15), None)], "subtract")

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

    @unittest.skipUnless(HAVE_FREECAD, "needs FreeCAD's Mesh booleans")
    def test_bore_boss_and_common_with_freecad(self):
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

    @unittest.skipIf(HAVE_FREECAD, "FreeCAD is here: the kernel runs")
    def test_the_cut_needs_freecad(self):
        body = TR.prepare_body(*box_mesh(20, 20, 20, 8), "Box")
        self.assertAlmostEqual(body[3], 8000, 3)
        with self.assertRaises(BO.NeedsKernel):
            TR.trim_to_scan(*sheet(), body, 0.3, 0.15)
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

    @unittest.skipUnless(HAVE_FREECAD, "needs FreeCAD's Mesh booleans")
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


    @unittest.skipUnless(HAVE_FREECAD, "needs FreeCAD's Mesh booleans")
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
        if not HAVE_FREECAD:
            with self.assertRaises(Exception) as c:
                H.HANDLERS["mesh_boolean"](s, {"op": "subtract", "solids": ["Bore 1", 1]})
            self.assertEqual(c.exception.code, "unavailable")
            with self.assertRaises(Exception) as c:
                H.HANDLERS["mesh_trim"](Session(*sheet()), {"body": "Bore 1"})
            self.assertIn(c.exception.code, ("not_found", "unavailable", "failed"))
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


if __name__ == "__main__":
    unittest.main()


class TrimReady(unittest.TestCase):
    def test_is_on(self):
        from scanrulerfc.meshtools import handlers as H

        # Back on since 5be1e43 passed in real FreeCAD 1.0, 1.1 and newest.
        self.assertTrue(H.TRIM_READY)

