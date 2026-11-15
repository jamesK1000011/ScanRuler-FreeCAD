# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/core/occtTypes.ts, kernel.ts, kernelMath.ts, thread.ts, chamferSides.ts (what they promise)
# SPDX-License-Identifier: AGPL-3.0-only
#
# The kernel adapter: every OCCT call the original names has its FreeCAD
# Part mapping, every ReKernel operation a method here (or the build step
# that brings it); the history and thread maths run here. The operations
# themselves run on FreeCAD's Part, one test each, against volumes worked
# out by hand; they skip where FreeCAD does not import ("needs FreeCAD").
import math
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
if os.environ.get("FREECAD_LIB"):
    sys.path.append(os.environ["FREECAD_LIB"])
try:
    import FreeCAD  # noqa: F401
    import Part  # noqa: F401

    HAVE_FC = True
except ImportError:
    HAVE_FC = False
NEEDS = "needs FreeCAD"

from scanrulerfc.reverse import kernel as K  # noqa: E402
from scanrulerfc.reverse.kernel_thread import chamfer_radius, fill_radius, minor_diameter, thread_span, tooth_outline  # noqa: E402
from scanrulerfc.reverse.loops import rectangle_loop  # noqa: E402
from scanrulerfc.reverse.origins import compose_history, flat_history, history_by_order, origins_after, parse_history, same_surface, traced_history  # noqa: E402

# occtTypes.ts OcctLike, every call in its order there.
OCCT_LIKE = """makeLineEdge makeArcEdge makeCircleEdge makeBSplineEdge makeWire makeFace addHolesInFace extrude draftPrism revolve makeHelixWireHanded
sweepOriented transform translate copy halfSpace sectionPlane section fuse fuseAll toBREPBinary fromBREPBinary cut common distanceBetween makeVertex
makeCompound unifySameDomain getSubShapes vertexPosition projectPointOnFace projectPointOnEdge makeSolid subShapeCount subShapeHashes hashCode surfaceType
surfaceNormal uvBounds getSurfaceCenterOfMass pointOnSurface uvFromPoint classifyPointOnFace getSurfaceArea getFaceCylinderData surfaceCurvature curveType
curveParameters curvePointAtParam curveTangent curveLength edgeToFaceMap wireframe fillet filletVariable loft linearPattern circularPattern split
bsplineSurface sew sewAndSolidify healSolid chamfer chamferDistAngle shell offset thicken thickenWithHistory defeature draft rotate mirror fuseWithHistory
cutWithHistory intersectWithHistory booleanOp filletWithHistory chamferWithHistory shellWithHistory mirrorWithHistory getShapeType containsPoint isValid
isNull getVolume getCenterOfMass getBoundingBox meshShape exportStep importStep createXCAFDocument release""".split()

# kernel.ts ReKernel's public operations.
REKERNEL = """face extrude revolve screw sheet surfaceThrough sweep loft loftFold pattern split distanceToPoint tracedHistory distanceBetween crossing
sheetNormals splitFaces sewFaces sheetPieces sewSheet sewPatches box halfSpace fuse fuseAll keepingSplits coarseFuzz fuzzyBooleans fuseTracked cutTracked
commonTracked filletTracked filletRadii filletVariable chamferTracked chamferAngled edgeSides deleteFaces shellTracked collapsingRounds clearance offsetSolid
faceOffsetLimits thickenTracked mirrorTracked draftFaces offsetFaceTracked threadTracked offsetFacesTracked faceCopy faceNormals facePoints faceHashes faces
edges cut solids facesOf common isClosedSolid isValid isSurface surfaceArea containsPoint solidCount faceCount shellsPerSolid voids volume measuredVolume
centroid bounds extent mesh exportStep exportStepMended readBackEdges readBackParts verifyStep oddEdges shortEdges smallConics narrowFaces sectionPolylines
sectionPieces probe readStepNames importStep readStepParts transformTracked toBrep fromBrep copy release""".split()


class CallMap(unittest.TestCase):
    def test_every_occt_call_is_mapped_by_its_own_name(self):
        self.assertEqual(set(OCCT_LIKE), set(K.OCCT_CALLS))
        for name, (how, status) in K.OCCT_CALLS.items():
            self.assertIn(status, ("direct", "workaround", "later"), name)
            self.assertTrue(how, name)
            self.assertTrue(callable(getattr(K.Occt, name, None)), name)

    def test_the_workarounds_are_the_designs(self):
        work = {n for n, (_, s) in K.OCCT_CALLS.items() if s == "workaround"}
        # Design §2.2: taper, draft and the distance-angle chamfer on the
        # scratch document; every *WithHistory traced (§2.4).
        self.assertTrue({"draftPrism", "draft", "chamferDistAngle"} <= work)
        self.assertTrue({n for n in OCCT_LIKE if n.endswith("WithHistory") and n != "thickenWithHistory"} | {"booleanOp"} <= work)

    def test_every_rekernel_op_is_a_method_or_a_later_step(self):
        self.assertEqual(set(REKERNEL), set(K.KERNEL_OPS))
        for name, py in K.KERNEL_OPS.items():
            if py is None:
                self.assertIn(name, K.LATER_STEP, name)
                self.assertGreater(K.LATER_STEP[name], 6, name)
            else:
                self.assertTrue(hasattr(K.Kernel, py), f"{name} -> {py}")
        self.assertEqual(set(K.LATER_STEP), {n for n, p in K.KERNEL_OPS.items() if p is None})

    def test_the_patch_network_finds_its_ops(self):
        # network_body.py calls the kernel by these names.
        for name in ("surface_through", "surface_area", "release", "distance_to_point", "copy", "sew_patches", "is_closed_solid", "edges", "open_edges", "face_points", "extent"):
            self.assertTrue(callable(getattr(K.Kernel, name, None)), name)

    def test_topo_reads_bodies_through_the_kernel(self):
        self.assertTrue(callable(K.Kernel.describe_faces) and callable(K.Kernel.describe_edges))

    def test_imports_without_freecad(self):
        # Nothing at module level reaches for FreeCAD: without it, the
        # import above ran and the kernel says it is missing.
        if not HAVE_FC:
            self.assertFalse(K.have_kernel())
            self.assertNotIn("Part", sys.modules)


class Maths(unittest.TestCase):
    def test_turn_onto_z(self):
        self.assertIsNone(K.turn_onto_z([0, 0, 1]))
        for d in ([1, 0, 0], [0, -1, 0], [0.6, 0, 0.8], [0, 0, -1]):
            t = K.turn_onto_z(d)
            z = K.rotate_vec(d, t)
            for a, b in zip(z, [0, 0, 1]):
                self.assertAlmostEqual(a, b, places=12)

    def test_far_distance_is_the_sine_rule(self):
        # Two planes square to each other: d2 = d tan(angle).
        self.assertAlmostEqual(K.far_distance(2, math.radians(30), math.pi / 2), 2 * math.tan(math.radians(30)), places=12)
        self.assertAlmostEqual(K.far_distance(1, math.radians(45), math.pi / 2), 1, places=12)
        self.assertAlmostEqual(K.dihedral([[1, 0, 0], [0, 1, 0]]), math.pi / 2, places=12)
        # A 120° inside corner (normals 60° apart).
        n2 = [math.cos(math.radians(60)), math.sin(math.radians(60)), 0]
        self.assertAlmostEqual(K.dihedral([[1, 0, 0], n2]), math.radians(120), places=12)


class Histories(unittest.TestCase):
    def test_flat_groups_round_trip(self):
        h = {7: [9, 10], 3: [], 5: [5]}
        self.assertEqual(parse_history(flat_history(h)), h)
        self.assertEqual(flat_history({1: [2, 3]}), [1, 2, 2, 3])

    def test_compose(self):
        self.assertEqual(compose_history({1: [2, 3]}, {2: [4], 9: [8]}), {1: [4, 3], 2: [4], 9: [8]})

    def test_by_order(self):
        self.assertEqual(history_by_order([1, 2, 3], [4, 2, 6]), {1: [4], 3: [6]})
        self.assertEqual(history_by_order([1], [1, 2]), {})

    def test_origins_after(self):
        # Face 10 kept, 20 modified into 21 and 22, 30 gone; 40 new.
        before = {10: 1, 20: 2, 30: 3}
        got = origins_after([10, 21, 22, 40], before, {20: [21, 22]}, 9)
        self.assertEqual(got, {10: 1, 21: 2, 22: 2, 40: 9})
        # Two old faces merged into one: the first the body had wins.
        self.assertEqual(origins_after([50], {1: 4, 2: 5}, {1: [50], 2: [50]}, 9), {50: 4})

    def test_same_surface(self):
        a = {"kind": "plane", "centroid": [0, 0, 5], "dir": [0, 0, 1], "area": 1}
        on = {"kind": "plane", "centroid": [3, 1, 5], "dir": [0, 0, 1], "area": 4, "hash": 1}
        off = {"kind": "plane", "centroid": [0, 0, 6], "dir": [0, 0, 1], "area": 1, "hash": 2}
        flipped = {"kind": "plane", "centroid": [0, 0, 5], "dir": [0, 0, -1], "area": 1, "hash": 3}
        self.assertIs(same_surface(a, [off, flipped, on]), on)
        cyl = {"kind": "cylinder", "centroid": [0, 0, 0], "dir": [0, 0, 1], "area": 1, "radius": 2, "center": [0, 0, 0]}
        same = {**cyl, "centroid": [0, 0, 7], "center": [0, 0, 7], "hash": 4}
        wider = {**cyl, "radius": 2.1, "hash": 5}
        self.assertIs(same_surface(cyl, [wider, same]), same)


class _Rect:
    """A flat rectangle o + u·du + v·dv, a stand-in face."""

    def __init__(self, h, o, du, dv, u1, v1, u0=0.0, v0=0.0):
        self.h, self.o, self.du, self.dv, self.uv = h, o, du, dv, (u0, u1, v0, v1)


class _RectOcct:
    """Just what traced_history reads, for flat rectangles."""

    def getSubShapes(self, shape, kind):
        return list(shape)

    def hashCode(self, f, upper=None):
        return f.h

    def surfaceType(self, f):
        return "plane"

    def uvBounds(self, f):
        return dict(zip(("uMin", "uMax", "vMin", "vMax"), f.uv))

    def pointOnSurface(self, f, u, v):
        return [f.o[i] + u * f.du[i] + v * f.dv[i] for i in range(3)]

    def uvFromPoint(self, f, p):
        d = [p[i] - f.o[i] for i in range(3)]
        return sum(a * b for a, b in zip(d, f.du)), sum(a * b for a, b in zip(d, f.dv))

    def classifyPointOnFace(self, f, u, v):
        return "in" if f.uv[0] < u < f.uv[1] and f.uv[2] < v < f.uv[3] else "out"

    def getBoundingBox(self, f):
        c = [self.pointOnSurface(f, u, v) for u in f.uv[:2] for v in f.uv[2:]]
        return {f"{a}{m}": fn(p[i] for p in c) for i, a in enumerate("xyz") for m, fn in (("min", min), ("max", max))}


class HalfSpace(unittest.TestCase):
    def test_the_box_stands_past_the_part_on_the_kept_side(self):
        # cutPlane's half-space is a finite box: OCCT's infinite one has a
        # plane face with no edges, and tracing the cut measured to them
        # (BRepExtrema_DistShapeShape failed).
        bounds = {"xmin": 2, "ymin": -3, "zmin": 1, "xmax": 42, "ymax": 17, "zmax": 11}
        for origin, n in (([20, 0, 6], [-1, 0, 0]), ([20, 0, 6], [1, 0, 0]), ([0, 0, 0], K.normalize([1, 2, 3])), ([100, 100, 100], [0, 0, -1])):
            corner, u, w, side, height = K.half_space_box(origin, n, bounds)
            self.assertAlmostEqual(K.dot(K.sub(corner, origin), n), 0, places=9)
            for p in ([x, y, z] for x in (2, 42) for y in (-3, 17) for z in (1, 11)):
                d = K.sub(p, corner)
                a, b, c = K.dot(d, u), K.dot(d, w), K.dot(d, n)
                if c > 0:
                    self.assertTrue(K.HALF_SPACE_MARGIN <= a <= side - K.HALF_SPACE_MARGIN and K.HALF_SPACE_MARGIN <= b <= side - K.HALF_SPACE_MARGIN and c <= height - K.HALF_SPACE_MARGIN, (origin, n, p))
        self.assertEqual(K.half_space_box([0, 0, 0], [0, 0, 1])[3], 2 * K.HALF_SPACE_BIG)

    def test_no_distance_is_taken_to_an_unbounded_face(self):
        class Unbounded:
            Edges = []

            def isPartOfDomain(self, u, v):
                return True

        self.assertEqual(K.Occt().classifyPointOnFace(Unbounded(), 0, 0), "in")


class TracedCut(unittest.TestCase):
    def test_the_tools_face_is_traced_too_not_the_box_twice(self):
        # A box 40 x 20 x 10 cut by a tool: four walls kept as they were, top
        # and bottom remade on their planes, and a new wall on the tool's own
        # face. The tool's face is traced like the box's — what CI counted
        # as a seventh box face — and no kept wall is traced at all.
        X, Y, Z = [1, 0, 0], [0, 1, 0], [0, 0, 1]
        walls = [_Rect(1, [0, 0, 0], X, Z, 40, 10), _Rect(2, [0, 20, 0], X, Z, 40, 10), _Rect(3, [0, 0, 0], Y, Z, 20, 10), _Rect(4, [40, 0, 0], Y, Z, 20, 10)]
        top, bottom = _Rect(5, [0, 0, 10], X, Y, 40, 20), _Rect(6, [0, 0, 0], X, Y, 40, 20)
        side = _Rect(7, [30, -5, -1], Y, Z, 30, 12)
        after = [*walls, _Rect(15, [0, 0, 10], X, Y, 30, 20), _Rect(16, [0, 0, 0], X, Y, 30, 20), _Rect(17, [30, 0, 0], Y, Z, 20, 10, 5, 0)]
        box = [*walls, top, bottom]
        history = traced_history(_RectOcct(), [box, [side]], after)
        self.assertEqual(history, {5: [15], 6: [16], 7: [17]})
        before, kept = {f.h for f in box}, {f.h for f in box} & {f.h for f in after}
        self.assertEqual(len(set(history) | kept), 7)
        self.assertEqual(len((set(history) & before) | kept), 6)


class ThreadForm(unittest.TestCase):
    M10 = {"standard": "metric", "diameter": 10, "pitch": 1.5, "offset": 0}

    def test_iso_m10_basic_profile(self):
        h = (5 / 8) * (math.sqrt(3) / 2) * 1.5
        self.assertAlmostEqual(minor_diameter(10, 1.5, "metric"), 10 - 2 * h, places=12)
        out = tooth_outline(self.M10, False, 0)
        self.assertAlmostEqual(out["root"], 5 - h, places=12)
        self.assertAlmostEqual(out["crest"], 5, places=12)
        self.assertFalse(out["pointed"])
        inner = tooth_outline(self.M10, True, 0)
        self.assertAlmostEqual(inner["root"], 5, places=12)
        self.assertAlmostEqual(inner["crest"], 5 - h, places=12)

    def test_fill_and_chamfer_radii(self):
        self.assertIsNone(fill_radius(self.M10, False, 5))
        self.assertAlmostEqual(fill_radius(self.M10, False, 4), 5)
        self.assertAlmostEqual(chamfer_radius(self.M10, False), tooth_outline(self.M10, False, 0)["root"] - 0.15)

    def test_span(self):
        self.assertEqual(thread_span({"lo": 0, "hi": 20}, None, 0, False), {"from": 0, "to": 20})
        self.assertEqual(thread_span({"lo": 0, "hi": 20}, 8, 2, False), {"from": 10, "to": 18})
        self.assertEqual(thread_span({"lo": 0, "hi": 20}, 8, 2, True), {"from": 2, "to": 10})
        self.assertIsNone(thread_span({"lo": 0, "hi": 20}, 19, 2, False))


def _rect(z, w, h, x0=0.0, y0=0.0):
    return {"outer": rectangle_loop([x0, y0, z], [1, 0, 0], [0, 1, 0], w, h), "holes": []}


@unittest.skipUnless(HAVE_FC, NEEDS)
class Operations(unittest.TestCase):
    def setUp(self):
        self.k = K.Kernel()

    def box(self, a=40, b=20, c=10):
        return self.k.extrude(self.k.face(_rect(0, a, b)), [0, 0, 1], 0, c)

    def edge_along_z(self, shape, x, y):
        for e in self.k.edges(shape, 0.1):
            if e["kind"] == "line" and abs(e["mid"][0] - x) < 1e-6 and abs(e["mid"][1] - y) < 1e-6:
                return e["hash"]
        self.fail("no such edge")

    def test_face_and_extrude(self):
        b = self.box()
        self.assertTrue(self.k.is_closed_solid(b))
        self.assertAlmostEqual(self.k.volume(b), 8000, places=6)
        self.assertAlmostEqual(self.k.surface_area(b), 2800, places=6)
        self.assertEqual(self.k.face_count(b), 6)
        both = self.k.extrude(self.k.face(_rect(0, 10, 10)), [0, 0, 1], 5, -3)
        self.assertAlmostEqual(self.k.volume(both), 800, places=6)
        self.assertAlmostEqual(self.k.bounds(both)["min"][2], -3, places=6)

    def test_face_with_a_hole(self):
        prof = {**_rect(0, 40, 20), "holes": [[{"kind": "circle", "center": [20, 10, 0], "normal": [0, 0, 1], "radius": 3}]]}
        s = self.k.extrude(self.k.face(prof), [0, 0, 1], 0, 5)
        self.assertAlmostEqual(self.k.volume(s), 4000 - 45 * math.pi, places=5)

    def test_revolve_a_tube(self):
        f = self.k.face({"outer": rectangle_loop([5, 0, 0], [1, 0, 0], [0, 0, 1], 5, 4), "holes": []})
        s = self.k.revolve(f, [0, 0, 0], [0, 0, 1], 2 * math.pi)
        self.assertAlmostEqual(self.k.volume(s), 300 * math.pi, places=5)

    def test_tapered_extrude_is_a_frustum(self):
        h, a, deg = 5.0, 10.0, 10.0
        s = self.k.extrude(self.k.face(_rect(0, a, a)), [0, 0, 1], 0, h, deg)
        top = a - 2 * h * math.tan(math.radians(deg))
        self.assertAlmostEqual(self.k.volume(s), h / 3 * (a * a + top * top + a * top), places=4)

    def test_cut_tracked_keeps_untouched_faces(self):
        b = self.box()
        tool = self.k.extrude(self.k.face({"outer": [{"kind": "circle", "center": [20, 10, 0], "normal": [0, 0, 1], "radius": 3}], "holes": []}), [0, 0, 1], -1, 11)
        r = self.k.cut_tracked(b, tool)
        self.assertAlmostEqual(self.k.volume(r["shape"]), 8000 - 90 * math.pi, places=5)
        before = set(self.k.face_hashes(b))
        after = set(self.k.face_hashes(r["shape"]))
        # The four walls stand as they were; top and bottom were holed and
        # are traced to the faces they were.
        self.assertGreaterEqual(len(before & after), 4)
        traced = {old for old, made in r["history"].items() if made}
        # The bore's wall lies on the tool's side and is traced to it, as
        # OCCT's history of the tool's face: of the box's faces, the two
        # holed ones are traced and none more.
        self.assertEqual(len((traced & before) | (before & after)), 6)
        self.assertEqual(len(traced - before), 1)
        self.assertTrue(traced - before <= set(self.k.face_hashes(tool)))

    def test_fuse_and_common_volume_identity(self):
        a = self.box(10, 10, 10)
        b = self.k.extrude(self.k.face(_rect(0, 10, 10, 5, 0)), [0, 0, 1], 0, 10)
        self.assertAlmostEqual(self.k.volume(self.k.fuse_tracked(a, b)["shape"]), 1500, places=6)
        self.assertAlmostEqual(self.k.volume(self.k.common_tracked(a, b)["shape"]), 500, places=6)
        self.assertAlmostEqual(self.k.volume(K.fuzzy_booleans(lambda: self.k.cut_tracked(a, b))["shape"]), 500, places=6)

    def test_fillet_removes_r2_one_less_quarter_pi_per_length(self):
        b = self.box()
        r = self.k.fillet_tracked(b, [self.edge_along_z(b, 40, 20)], 2)
        self.assertAlmostEqual(self.k.volume(r["shape"]), 8000 - 10 * 4 * (1 - math.pi / 4), places=4)
        self.assertEqual(self.k.face_count(r["shape"]), 7)

    def test_chamfers(self):
        b = self.box()
        e = self.edge_along_z(b, 40, 20)
        self.assertAlmostEqual(self.k.volume(self.k.chamfer_tracked(b, [e], 2)["shape"]), 8000 - 20, places=5)
        # 2 mm at 30° on two square faces: the far leg is 2 tan 30°.
        got = self.k.volume(self.k.chamfer_angled(b, [e], 2, 30))
        self.assertAlmostEqual(got, 8000 - 10 * 0.5 * 2 * 2 * math.tan(math.radians(30)), places=4)

    def test_shell_closed_and_open(self):
        b = self.box(10, 10, 10)
        self.assertAlmostEqual(self.k.volume(self.k.shell_tracked(b, [], 1)["shape"]), 1000 - 512, places=4)
        top = next(f["hash"] for f in self.k.faces(b) if f["kind"] == "plane" and f["dir"][2] > 0.5)
        self.assertAlmostEqual(self.k.volume(self.k.shell_tracked(b, [top], 1)["shape"]), 1000 - 8 * 8 * 9, places=4)

    def test_offset_solid_grows_by_the_minkowski_formula(self):
        b = self.box(10, 10, 10)
        d = 1
        want = 1000 + 2 * d * 300 + math.pi * d * d * 30 + 4 / 3 * math.pi * d ** 3
        self.assertAlmostEqual(self.k.volume(self.k.offset_solid(b, d)), want, delta=want * 1e-4)

    def test_half_space_cut(self):
        b = self.box()
        kept = self.k.cut(b, self.k.half_space([10, 0, 0], [-1, 0, 0]))
        self.assertAlmostEqual(self.k.volume(kept), 6000, places=5)

    def test_mirror_and_transform_keep_face_order(self):
        b = self.box(10, 10, 10)
        m = self.k.mirror_tracked(b, [0, 0, 0], [1, 0, 0])
        self.assertAlmostEqual(self.k.bounds(m["shape"])["min"][0], -10, places=6)
        self.assertEqual(len(m["history"]), 6)
        t = self.k.transform_tracked(b, [1, 0, 0, 5, 0, 1, 0, 0, 0, 0, 1, 0])
        self.assertAlmostEqual(self.k.bounds(t["shape"])["min"][0], 5, places=6)

    def test_pattern_fuses_overlaps_and_keeps_islands(self):
        b = self.box(10, 10, 10)
        apart = self.k.pattern(b, "linear", [0, 0, 0], [1, 0, 0], 3, 20)
        self.assertEqual(self.k.solid_count(apart), 3)
        self.assertAlmostEqual(self.k.volume(apart), 3000, places=5)
        lap = self.k.pattern(b, "linear", [0, 0, 0], [1, 0, 0], 3, 5)
        self.assertEqual(self.k.solid_count(lap), 1)
        self.assertAlmostEqual(self.k.volume(lap), 2000, places=5)

    def test_draft_one_wall(self):
        b = self.box(10, 10, 10)
        wall = next(f["hash"] for f in self.k.faces(b) if f["kind"] == "plane" and f["dir"][0] > 0.5)
        s = self.k.draft_faces(b, [wall], [0, 0, 0], [0, 0, 1], math.radians(5))
        self.assertAlmostEqual(self.k.volume(s), 1000 - 500 * math.tan(math.radians(5)), places=3)

    def test_move_faces(self):
        b = self.box(10, 10, 10)
        wall = next(f["hash"] for f in self.k.faces(b) if f["kind"] == "plane" and f["dir"][0] > 0.5)
        self.assertAlmostEqual(self.k.volume(self.k.offset_faces_tracked(b, [wall], 2)["shape"]), 1200, places=5)
        self.assertAlmostEqual(self.k.volume(self.k.offset_faces_tracked(b, [wall], -2)["shape"]), 800, places=5)

    def test_delete_a_hole(self):
        b = self.box(10, 10, 10)
        tool = self.k.extrude(self.k.face({"outer": [{"kind": "circle", "center": [5, 5, 0], "normal": [0, 0, 1], "radius": 2}], "holes": []}), [0, 0, 1], -1, 11)
        holed = self.k.cut(b, tool)
        bore = next(f["hash"] for f in self.k.faces(holed) if f["kind"] == "cylinder")
        self.assertAlmostEqual(self.k.volume(self.k.delete_faces(holed, [bore])), 1000, places=4)

    def test_sew_patches(self):
        b = self.box(10, 10, 10)
        faces = self.k.faces_of(b)
        solid = self.k.sew_patches(faces, 1e-6, True)
        self.assertTrue(self.k.is_closed_solid(solid))
        self.assertAlmostEqual(self.k.volume(solid), 1000, places=5)
        open_ = self.k.sew_patches(faces[:5], 1e-6, True)
        self.assertFalse(self.k.is_closed_solid(open_))
        self.assertEqual(self.k.face_count(self.k.sew_patches(faces[:5], 1e-6, False)), 5)

    def test_surface_through_a_grid(self):
        pts = [c for r in range(3) for q in range(3) for c in (q * 5.0, r * 5.0, 0.0)]
        f = self.k.surface_through(pts, 3, 3)
        self.assertAlmostEqual(self.k.surface_area(f), 100, places=4)
        self.assertAlmostEqual(self.k.distance_to_point(f, [5, 5, 2]), 2, places=6)
        self.assertEqual(len(self.k.face_points(f)), 1)

    def test_fingerprints_of_a_box(self):
        from scanrulerfc.reverse.topo import read_topology

        b = self.box()
        t = read_topology(self.k, b, {h: 1 for h in self.k.face_hashes(b)}, 0.1)
        self.assertEqual(len(t["faces"]), 6)
        self.assertEqual(len(t["edges"]), 12)
        dirs = sorted(tuple(round(x) for x in f["fingerprint"]["dir"]) for f in t["faces"])
        self.assertEqual(dirs, sorted([(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)]))
        self.assertTrue(all(len(e["fingerprint"]["faces"]) == 2 and e["fingerprint"]["origin"] == 1 for e in t["edges"]))

    def test_thread_on_a_boss(self):
        boss = self.k.extrude(self.k.face({"outer": [{"kind": "circle", "center": [0, 0, 0], "normal": [0, 0, 1], "radius": 5}], "holes": []}), [0, 0, 1], 0, 12)
        face = next(f["hash"] for f in self.k.faces(boss) if f["kind"] == "cylinder")
        r = self.k.thread_tracked(boss, face, {"standard": "metric", "diameter": 10, "pitch": 1.5, "offset": 0, "leftHanded": False, "length": None, "start": 0, "flip": False})
        v = self.k.volume(r["shape"])
        h = (5 / 8) * (math.sqrt(3) / 2) * 1.5
        # Between the minor cylinder and the boss.
        self.assertLess(v, 300 * math.pi)
        self.assertGreater(v, math.pi * (5 - h) ** 2 * 12)
        self.assertTrue(self.k.is_closed_solid(r["shape"]))


if __name__ == "__main__":
    unittest.main()


class SewRoutes(unittest.TestCase):
    """Sewing tries its routes in turn and keeps the one leaving the fewest
    open edges, the first leaving none at once (FreeCAD 1.1.3's sewShape
    takes no tolerance). On stand-ins for Part and the shapes."""

    class Shape:
        def __init__(self, free, valid=True):
            self.free, self.valid = free, valid

        def isNull(self):  # noqa: N802
            return False

        def isValid(self):  # noqa: N802
            return self.valid

    def sew_with(self, results):
        from unittest import mock

        def routes(P, shapes, tol):
            def make(r):
                def fn():
                    if isinstance(r, Exception):
                        raise r
                    return r
                return fn
            return [(n, make(r)) for n, r in results]

        o = K.Occt()
        with mock.patch.object(K, "sew_routes", routes), mock.patch.object(K, "_part", lambda: None), \
                mock.patch.object(K.Occt, "openEdgeMids", lambda self, s: [0] * s.free):
            got = o.sew([], 1e-3)
        return got, o.last_sew

    def test_the_fewest_open_edges_and_the_first_with_none(self):
        a, b, c = self.Shape(4), self.Shape(0), self.Shape(0)
        got, said = self.sew_with([("sewShape", a), ("ShapeFix.FaceConnect", b), ("ShapeTolerance+sewShape", c)])
        self.assertIs(got, b)
        self.assertEqual(said["route"], "ShapeFix.FaceConnect")
        self.assertEqual(said["tried"], [("sewShape", 4), ("ShapeFix.FaceConnect", 0)])

    def test_a_route_that_fails_or_is_invalid_is_passed_over(self):
        a = self.Shape(8)
        got, said = self.sew_with([("sewShape", a), ("ShapeFix.FaceConnect", AttributeError("no FaceConnect")), ("ShapeTolerance+sewShape", self.Shape(2, valid=False))])
        self.assertIs(got, a)
        self.assertEqual(said["route"], "sewShape")
        self.assertIn("AttributeError", said["tried"][1][1])
        self.assertEqual(said["tried"][2], ("ShapeTolerance+sewShape", "invalid"))
        with self.assertRaises(K.KernelError):
            self.sew_with([("sewShape", RuntimeError("x"))])


class SharedSeams(unittest.TestCase):
    """The shared-edge route on stand-ins: two square patches side by side,
    each with its own copy of every edge and corner, come out holding one
    vertex per corner and one edge on their common side."""

    def setUp(self):
        import types

        class Pt:
            def __init__(self, *c):
                self.c = c

            def __sub__(self, o):
                return types.SimpleNamespace(Length=sum((a - b) ** 2 for a, b in zip(self.c, o.c)) ** 0.5)

        class V:
            def __init__(self, *c):
                self.Point = Pt(*c)

            def isSame(self, o):
                return self is o

        class E:
            Degenerated = False
            FirstParameter, LastParameter = 0.0, 1.0

            def __init__(self, a, b):
                self.Vertexes = [a, b]

            def isSame(self, o):
                return self is o

            def valueAt(self, t):
                a, b = self.Vertexes[0].Point.c, self.Vertexes[1].Point.c
                return Pt(*[x + (y - x) * t for x, y in zip(a, b)])

            def distToShape(self, v):
                m = self.valueAt(0.5)
                return ((m - v.Point).Length,)

        class F:
            def __init__(self, edges):
                self.Edges = edges

            @property
            def Vertexes(self):  # noqa: N802
                out = []
                for e in self.Edges:
                    for v in e.Vertexes:
                        if v not in out:
                            out.append(v)
                return out

            def replaceShape(self, subs):
                m = dict((id(a), b) for a, b in subs)
                edges = []
                for e in self.Edges:
                    if id(e) in m:
                        edges.append(m[id(e)])
                    elif any(id(v) in m for v in e.Vertexes):
                        edges.append(E(*[m.get(id(v), v) for v in e.Vertexes]))
                    else:
                        edges.append(e)
                return F(edges)

        def square(x0):
            c = [V(x0, 0, 0), V(x0 + 1, 0, 0), V(x0 + 1, 1, 0), V(x0, 1, 0)]
            return F([E(c[i], c[(i + 1) % 4]) for i in range(4)])

        self.fixed = []
        edge_fix = types.SimpleNamespace(fixAddPCurve=lambda e, f, seam, tol: self.fixed.append(e), fixSameParameter=lambda e: None)
        shell = lambda faces: types.SimpleNamespace(ShapeType="Shell", Faces=faces)  # noqa: E731
        self.P = types.SimpleNamespace(Vertex=lambda m: V(*m.c), ShapeFix=types.SimpleNamespace(Edge=lambda: edge_fix), Shell=shell, makeShell=shell)
        self.faces = [square(0), square(1)]

    def test_one_vertex_per_corner_one_edge_on_the_common_side(self):
        got = K.share_seams(self.P, self.faces, 1e-3)
        a, b = got.Faces
        common = [e for e in a.Edges if any(e is x for x in b.Edges)]
        self.assertEqual(len(common), 1)
        self.assertEqual(K.share_seams.last, {"vertices": 2, "edges": 1})
        self.assertEqual(self.fixed, common)  # the shared edge given a curve on the second patch
        corners = {id(v) for f in got.Faces for v in f.Vertexes}
        self.assertEqual(len(corners), 6)


class ShellOf(unittest.TestCase):
    """FaceConnect is handed a Part.Shell however FreeCAD answers Part.Shell(faces)."""

    def P(self, sewn_shells, shell_answer):
        import types

        class Shell:
            def __init__(self, faces):
                self.Faces = faces

        class Comp:
            def __init__(self, faces):
                self.faces = faces
                self.Shells = []

            def sewShape(self, tol):
                self.Shells = sewn_shells(self.faces)

        def make(faces):
            return shell_answer(faces, Shell)

        return types.SimpleNamespace(Compound=Comp, Shell=Shell, makeShell=make), Shell

    def test_a_partial_sewing_s_one_shell(self):
        P, Shell = self.P(lambda f: [types_shell(f)], lambda f, S: None)
        got = K.shell_of(P, ["a", "b"], 1e-3)
        self.assertEqual(got.Faces, ["a", "b"])

    def test_part_shell_when_the_sewing_splits_them(self):
        P, Shell = self.P(lambda f: [types_shell(f[:1]), types_shell(f[1:])], lambda f, S: S(f))
        got = K.shell_of(P, ["a", "b"], 1e-3)
        self.assertIsInstance(got, Shell)
        self.assertEqual(got.Faces, ["a", "b"])


def types_shell(faces):
    import types

    return types.SimpleNamespace(Faces=list(faces))
