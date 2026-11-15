# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/core/kernel.ts, occtTypes.ts, kernelOps.ts, kernelFaces.ts, kernelRounds.ts, kernelShell.ts, kernelMath.ts
# SPDX-License-Identifier: AGPL-3.0-only
#
# The CAD kernel behind the Reverse engineer workspace. The original runs
# Open CASCADE compiled to WebAssembly (occt-wasm) behind an adapter that
# names every OCCT call it makes (occtTypes.ts OcctLike); its ReKernel
# (kernel.ts and the kernel*.ts beside it) builds the workspace's operations
# on those calls. Here the same two layers stand on FreeCAD's Part module,
# which is OCCT too:
#
#   Occt    the OcctLike calls, by their own names, each on Part (OCCT_CALLS
#           says how, and which are workarounds); a handle is a Part.Shape
#   Kernel  ReKernel's operations, snake_case of the original names
#           (KERNEL_OPS maps each), with the same refusals, retries and
#           history rules
#   Scratch the hidden document a few operations need, where Part has no
#           Python call: a tapered extrude (Part::Extrusion), a draft
#           (PartDesign::Draft), per-edge fillet radii (Part::Fillet) and an
#           exact distance-angle chamfer (PartDesign::Chamfer)
#
# Kernel history is the one thing Part does not hand back: the *WithHistory
# calls trace it from the shapes (origins.py). Part and FreeCAD are imported
# on first use, so this module imports anywhere.

import contextlib
import math

from .loops import circle_through, loop_middle, polygon_loop, rectangle_loop
from .origins import HASH_BOUND, compose_history, flat_history, history_by_order, parse_history, traced_history, unify_history
from .topo import canonical_dir, edge_kind_of, face_kind_of
from .vec import add_scaled, cross, dot, length, normalize, scale, sub

FUZZY_MM = 1e-4
FUZZY_COARSE_MM = 1e-3
FULL_WIDTH_SLACK = (1e-8, 1e-6, 1e-5)
# SweepMode: the section's binormal held to one direction (a screw), or the
# corrected Frenet frame (a sweep along a drawn path).
SWEEP_FIXED_UP = 2
SWEEP_FIXED = 0

# How each OcctLike call (occtTypes.ts) is made on FreeCAD Part: the call,
# and "direct" (one Part call does it), "workaround" (no Part call: built
# another way, said how) or "later" (not needed until a later build step).
OCCT_CALLS = {
    "makeLineEdge": ("Part.LineSegment(a, b).toShape()", "direct"),
    "makeArcEdge": ("Part.Arc(a, m, b).toShape()", "direct"),
    "makeCircleEdge": ("Part.makeCircle(r, center, normal)", "direct"),
    "makeBSplineEdge": ("Part.BSplineCurve().buildFromPolesMultsKnots(...).toShape()", "direct"),
    "makeWire": ("Part.Wire(edges)", "direct"),
    "makeFace": ("Part.Face(wire)", "direct"),
    "addHolesInFace": ("Part.makeFace([outer, *holes], 'Part::FaceMakerBullseye')", "direct"),
    "extrude": ("shape.extrude(vec)", "direct"),
    "draftPrism": ("Part::Extrusion with TaperAngle on the scratch document", "workaround"),
    "revolve": ("shape.revolve(pnt, dir, deg)", "direct"),
    "makeHelixWireHanded": ("Part.makeHelix(pitch, height, radius, 0, leftHanded)", "direct"),
    "sweepOriented": ("Part.BRepOffsetAPI.MakePipeShell(spine): setBiNormalMode(up) / setFrenetMode(False)", "direct"),
    "transform": ("shape.transformed(FreeCAD.Matrix)", "direct"),
    "translate": ("shape.translated(vec)", "direct"),
    "copy": ("shape.copy()", "direct"),
    "halfSpace": ("a box past the part (Part.Face(Part.Wire(...)).extrude), not makeHalfSpace: an infinite solid fails the tracing's distToShape", "workaround"),
    "sectionPlane": ("Part.Compound(shape.slice(n, d))", "direct"),
    "section": ("a.section(b)", "direct"),
    "fuse": ("a.fuse(b)", "direct"),
    "fuseAll": ("a.multiFuse(rest)", "direct"),
    "toBREPBinary": ("shape.exportBrepToString() (text)", "direct"),
    "fromBREPBinary": ("Part.Shape().importBrepFromString(text)", "direct"),
    "cut": ("a.cut(b)", "direct"),
    "common": ("a.common(b)", "direct"),
    "distanceBetween": ("a.distToShape(b)[0]", "direct"),
    "makeVertex": ("Part.Vertex(x, y, z)", "direct"),
    "makeCompound": ("Part.Compound(shapes)", "direct"),
    "unifySameDomain": ("shape.removeSplitter()", "direct"),
    "getSubShapes": ("shape.Solids / Shells / Faces / Edges / Vertexes", "direct"),
    "vertexPosition": ("vertex.Point", "direct"),
    "projectPointOnFace": ("face.Surface.value(*face.Surface.parameter(p))", "direct"),
    "projectPointOnEdge": ("edge.distToShape(Part.Vertex(p)) and edge.Curve.parameter", "direct"),
    "makeSolid": ("Part.Solid(shell)", "direct"),
    "subShapeCount": ("len(shape.Faces) and the like", "direct"),
    "subShapeHashes": ("sub.hashCode() for each sub-shape", "direct"),
    "hashCode": ("shape.hashCode()", "direct"),
    "surfaceType": ("type(face.Surface).__name__", "direct"),
    "surfaceNormal": ("face.normalAt(u, v)", "direct"),
    "uvBounds": ("face.ParameterRange", "direct"),
    "getSurfaceCenterOfMass": ("face.CenterOfMass", "direct"),
    "pointOnSurface": ("face.valueAt(u, v)", "direct"),
    "uvFromPoint": ("face.Surface.parameter(p)", "direct"),
    "classifyPointOnFace": ("face.isPartOfDomain(u, v), 'on' within 1e-7 of its edges", "direct"),
    "getSurfaceArea": ("shape.Area", "direct"),
    "getFaceCylinderData": ("face.Surface.Radius", "direct"),
    "surfaceCurvature": ("face.curvatureAt(u, v)", "direct"),
    "curveType": ("type(edge.Curve).__name__", "direct"),
    "curveParameters": ("edge.ParameterRange", "direct"),
    "curvePointAtParam": ("edge.valueAt(t)", "direct"),
    "curveTangent": ("edge.tangentAt(t)", "direct"),
    "curveLength": ("edge.Length", "direct"),
    "edgeToFaceMap": ("shape.ancestorsOfType(edge, Part.Face)", "direct"),
    "wireframe": ("edge.discretize(Deflection=d)", "direct"),
    "fillet": ("solid.makeFillet(r, edges)", "direct"),
    "filletVariable": ("solid.makeFillet(r1, r2, [edge])", "direct"),
    "loft": ("Part.makeLoft(wires, solid, ruled)", "direct"),
    "linearPattern": ("translated copies in a compound", "direct"),
    "circularPattern": ("rotated copies (angle / count apart) in a compound", "direct"),
    "split": ("BOPTools.SplitAPI.slice(shape, tools, 'Split')", "direct"),
    "bsplineSurface": ("Part.BSplineSurface().interpolate(grid)", "direct"),
    "sew": ("compound.sewShape() at the tolerance", "direct"),
    "sewAndSolidify": ("sewShape, then Part.Solid(Part.Shell(faces))", "direct"),
    "healSolid": ("shape.fix(t, t, t)", "direct"),
    "chamfer": ("solid.makeChamfer(d, edges)", "direct"),
    "chamferDistAngle": ("solid.makeChamfer(d, d2, edges), d2 from the dihedral (exact for plane-plane); PartDesign::Chamfer 'Distance and Angle' on the scratch document otherwise", "workaround"),
    "shell": ("solid.makeThickness(faces, -t, tol)", "direct"),
    "offset": ("solid.makeOffsetShape(d, tol)", "direct"),
    "thicken": ("sheet.makeOffsetShape(t, tol, fill=True)", "direct"),
    "thickenWithHistory": ("thicken; history traced (origins.py)", "later"),
    "defeature": ("shape.defeaturing(faces)", "direct"),
    "draft": ("PartDesign::Draft on the scratch document, neutral plane the body's XY", "workaround"),
    "rotate": ("shape.rotated(pnt, dir, deg)", "direct"),
    "mirror": ("shape.mirror(pnt, normal)", "direct"),
    "fuseWithHistory": ("a.fuse(b); history traced (origins.py)", "workaround"),
    "cutWithHistory": ("a.cut(b); history traced (origins.py)", "workaround"),
    "intersectWithHistory": ("a.common(b); history traced (origins.py)", "workaround"),
    "booleanOp": ("a.fuse / cut / common(tools, fuzzy); history traced (origins.py)", "workaround"),
    "filletWithHistory": ("makeFillet, or Part::Fillet on the scratch document for a radius an edge; history traced", "workaround"),
    "chamferWithHistory": ("makeChamfer; history traced (origins.py)", "workaround"),
    "shellWithHistory": ("makeThickness; history traced (origins.py)", "workaround"),
    "mirrorWithHistory": ("shape.mirror; history by face order", "workaround"),
    "getShapeType": ("shape.ShapeType", "direct"),
    "containsPoint": ("solid.isInside(p, tol, True)", "direct"),
    "isValid": ("shape.isValid()", "direct"),
    "isNull": ("shape.isNull()", "direct"),
    "getVolume": ("shape.Volume", "direct"),
    "getCenterOfMass": ("shape.CenterOfMass (volume-weighted over solids)", "direct"),
    "getBoundingBox": ("shape.BoundBox; optimalBoundingBox() when precise", "direct"),
    "meshShape": ("face.tessellate(d) face by face", "direct"),
    "exportStep": ("shape.exportStep(path) through a temporary file", "direct"),
    "importStep": ("Part.Shape().read(path) through a temporary file", "direct"),
    "createXCAFDocument": ("Import.export with Labels (names); colours need the GUI", "later"),
    "release": ("nothing: Python lets go", "direct"),
}

# ReKernel's operations (kernel.ts and the kernel*.ts beside it) by their
# original names: the Kernel method each is, or None where a later build
# step brings it (with the step).
KERNEL_OPS = {
    "face": "face", "extrude": "extrude", "revolve": "revolve", "screw": "screw", "sheet": "sheet", "surfaceThrough": "surface_through",
    "sweep": "sweep", "loft": "loft", "loftFold": None, "pattern": "pattern", "split": "split", "distanceToPoint": "distance_to_point",
    "tracedHistory": "traced_history", "distanceBetween": "distance_between", "crossing": None, "sheetNormals": None, "splitFaces": None,
    "sewFaces": None, "sheetPieces": None, "sewSheet": None, "sewPatches": "sew_patches", "box": "box", "halfSpace": "half_space", "fuse": "fuse",
    "fuseAll": "fuse_all", "keepingSplits": "keeping_splits", "fuzzyBooleans": "fuzzy_booleans", "coarseFuzz": "coarse_fuzz",
    "fuseTracked": "fuse_tracked", "cutTracked": "cut_tracked", "commonTracked": "common_tracked", "filletTracked": "fillet_tracked",
    "filletRadii": "fillet_radii", "filletVariable": "fillet_variable", "chamferTracked": "chamfer_tracked", "chamferAngled": "chamfer_angled",
    "edgeSides": "edge_sides", "deleteFaces": "delete_faces", "shellTracked": "shell_tracked", "collapsingRounds": None, "clearance": "clearance",
    "offsetSolid": "offset_solid", "faceOffsetLimits": None, "thickenTracked": None, "mirrorTracked": "mirror_tracked", "draftFaces": "draft_faces",
    "offsetFaceTracked": "offset_face_tracked", "threadTracked": "thread_tracked", "offsetFacesTracked": "offset_faces_tracked", "faceCopy": "face_copy",
    "faceNormals": "face_normals", "facePoints": "face_points", "faceHashes": "face_hashes", "faces": "faces", "edges": "edges", "cut": "cut",
    "solids": "solids", "facesOf": "faces_of", "common": "common", "isClosedSolid": "is_closed_solid", "isValid": "is_valid", "isSurface": "is_surface",
    "surfaceArea": "surface_area", "containsPoint": "contains_point", "solidCount": "solid_count", "faceCount": "face_count", "shellsPerSolid": "shells_per_solid",
    "voids": None, "volume": "volume", "measuredVolume": None, "centroid": "centroid", "bounds": "bounds", "extent": "extent", "mesh": "mesh",
    "exportStep": "export_step", "exportStepMended": None, "readBackEdges": None, "readBackParts": None, "verifyStep": None, "oddEdges": None,
    "shortEdges": None, "smallConics": None, "narrowFaces": None, "sectionPolylines": "section_polylines", "sectionPieces": None, "probe": None,
    "readStepNames": None, "importStep": "import_step", "readStepParts": "read_step_parts", "transformTracked": "transform_tracked", "toBrep": "to_brep",
    "fromBrep": "from_brep", "copy": "copy", "release": "release",
}
# The build step that brings each op KERNEL_OPS leaves out (design §7.1).
LATER_STEP = {"loftFold": 10, "crossing": 11, "sheetNormals": 11, "splitFaces": 10, "sewFaces": 11, "sheetPieces": 11, "sewSheet": 11,
              "collapsingRounds": 13, "faceOffsetLimits": 13, "thickenTracked": 10, "voids": 13, "measuredVolume": 13, "exportStepMended": 10,
              "readBackEdges": 10, "readBackParts": 10, "verifyStep": 10, "oddEdges": 13, "shortEdges": 13, "smallConics": 10, "narrowFaces": 13,
              "sectionPieces": 13, "probe": 13, "readStepNames": 10}


class KernelError(Exception):
    """What the kernel refused, in words."""


def _part():
    import Part  # noqa: PLC0415 — FreeCAD only where a kernel call runs

    return Part


def _v(p):
    import FreeCAD  # noqa: PLC0415

    return FreeCAD.Vector(float(p[0]), float(p[1]), float(p[2]))


def _l(v):
    return [v.x, v.y, v.z]


def have_kernel():
    """Whether FreeCAD's Part imports here."""
    try:
        _part()
        return True
    except ImportError:
        return False


# ---- the switches the retries flip (kernelOps keepingSplits, fuzzyBooleans) -----------------

_state = {"unifying": True, "fuzzy": 0.0}


@contextlib.contextmanager
def _flag(key, value):
    was = _state[key]
    _state[key] = value
    try:
        yield
    finally:
        _state[key] = was


def keeping_splits(fn):
    """fn run with the faces its operations leave on one surface kept as cut."""
    with _flag("unifying", False):
        return fn()


def fuzzy_booleans(fn, mm=FUZZY_MM):
    """fn run with the tracked booleans fuzzy at `mm`."""
    with _flag("fuzzy", mm):
        return fn()


def boolean_fuzz():
    return _state["fuzzy"]


def unifying():
    return _state["unifying"]


def run(what, fn):
    """kernelOps run: what the kernel throws as a KernelError headed by
    what was being done."""
    try:
        return fn()
    except KernelError as e:
        raise KernelError(f"{what}: {e}") from e
    except Exception as e:  # noqa: BLE001 — OCCT's own errors come as Part.OCCError and others
        raise KernelError(f"{what}: {e}") from e


# ---- small geometry (kernelMath.ts) ------------------------------------------------------------


def turn_onto_z(d):
    angle = math.acos(max(-1, min(1, d[2])))
    if angle < 1e-9:
        return None
    return {"axis": normalize(cross(d, [0, 0, 1])) or [1, 0, 0], "angle": angle}


def rotate_vec(v, turn):
    axis, angle = turn["axis"], turn["angle"]
    c, s = math.cos(angle), math.sin(angle)
    k = cross(axis, v)
    d = dot(axis, v) * (1 - c)
    return [v[i] * c + k[i] * s + axis[i] * d for i in range(3)]


def dihedral(normals):
    """chamferSides faceAngle: the angle inside the material between two
    faces with these outward normals."""
    c = max(-1, min(1, dot(normals[0], normals[1])))
    return math.pi - math.acos(c)


def far_distance(distance, angle_rad, phi):
    """How far along the second face a chamfer `distance` along the first,
    at `angle_rad` to it, reaches where the two meet at `phi`: exact for
    two planes (the sine rule)."""
    return distance * math.sin(angle_rad) / math.sin(phi + angle_rad)


def is_full_turn(uv):
    return uv["uMax"] - uv["uMin"] >= 2 * math.pi - 1e-6


# ---- Occt: the OcctLike calls on Part -------------------------------------------------------------

_SURFACE = {"Plane": "plane", "Cylinder": "cylinder", "Cone": "cone", "Sphere": "sphere", "Toroid": "torus"}
_CURVE = {"Line": "line", "LineSegment": "line", "Circle": "circle", "ArcOfCircle": "circle"}


def _hash(s, upper=HASH_BOUND):
    try:
        return s.hashCode(upper)
    except TypeError:
        return s.hashCode() % upper


class Occt:
    """occtTypes.ts OcctLike on FreeCAD Part: same names, a handle is a
    Part.Shape, a point a list [x, y, z]."""

    def __init__(self, scratch=None):
        self.scratch = scratch or Scratch()

    # ---- edges, wires, faces
    def makeLineEdge(self, a, b):
        return _part().LineSegment(_v(a), _v(b)).toShape()

    def makeArcEdge(self, a, m, b):
        return _part().Arc(_v(a), _v(m), _v(b)).toShape()

    def makeCircleEdge(self, center, normal, radius):
        return _part().makeCircle(radius, _v(center), _v(normal))

    def makeBSplineEdge(self, poles, weights, knots, mults, degree, periodic=False):
        P = _part()
        pts = [_v(poles[i:i + 3]) for i in range(0, len(poles), 3)]
        c = P.BSplineCurve()
        c.buildFromPolesMultsKnots(pts, mults, knots, periodic, degree, weights)
        return c.toShape()

    def makeWire(self, edges):
        P = _part()
        try:
            w = P.Wire(edges)
        except Exception:  # noqa: BLE001 — edges out of order: sorted, as MakeWire would join them
            w = P.Wire(P.__sortEdges__(edges))
        return w

    def makeFace(self, wire):
        return _part().Face(wire)

    def addHolesInFace(self, face, holes):
        P = _part()
        return P.makeFace([face.OuterWire, *holes], "Part::FaceMakerBullseye")

    # ---- sweeps
    def extrude(self, shape, dx, dy, dz):
        return shape.extrude(_v([dx, dy, dz]))

    def draftPrism(self, shape, dx, dy, dz, angle_deg):
        return self.scratch.tapered_prism(shape, [dx, dy, dz], angle_deg)

    def revolve(self, shape, axis, angle_rad):
        return shape.revolve(_v(axis["point"]), _v(axis["direction"]), math.degrees(angle_rad))

    def makeHelixWireHanded(self, origin, axis, pitch, height, radius, left_handed=False):
        helix = _part().makeHelix(pitch, height, radius, 0, bool(left_handed))
        if tuple(origin) != (0, 0, 0):
            helix = helix.translated(_v(origin))
        return helix

    def sweepOriented(self, profile, spine, mode=SWEEP_FIXED, up=None):
        P = _part()
        wire = spine if spine.ShapeType == "Wire" else P.Wire(spine.Edges)
        ps = P.BRepOffsetAPI.MakePipeShell(wire)
        if mode == SWEEP_FIXED_UP and up is not None:
            ps.setBiNormalMode(_v(up))
        else:
            ps.setFrenetMode(False)
        ps.add(profile, False, False)
        ps.build()
        ps.makeSolid()
        return ps.shape()

    # ---- placement
    def transform(self, shape, m):
        import FreeCAD  # noqa: PLC0415

        mat = FreeCAD.Matrix(m[0], m[1], m[2], m[3], m[4], m[5], m[6], m[7], m[8], m[9], m[10], m[11], 0, 0, 0, 1)
        return shape.transformed(mat)

    def translate(self, shape, dx, dy, dz):
        return shape.translated(_v([dx, dy, dz]))

    def rotate(self, shape, axis, angle_rad):
        return shape.rotated(_v(axis["point"]), _v(axis["direction"]), math.degrees(angle_rad))

    def mirror(self, shape, point, normal):
        return shape.mirror(_v(point), _v(normal))

    def copy(self, shape):
        return shape.copy()

    def halfSpace(self, origin, normal, bounds=None):
        """The side of the plane `normal` points to, as a box past the part
        (bounds: its bounding box) rather than OCCT's infinite half-space:
        an infinite solid's plane face has no edges, and the faces' tracing
        after a cut (classifyPointOnFace, distToShape to the edges) fails on
        it with BRepExtrema_DistShapeShape."""
        P = _part()
        corner, u, w, side, height = half_space_box(origin, normalize(normal), bounds)
        box = P.Face(P.Wire([P.LineSegment(_v(a), _v(b)).toShape() for a, b in _square(corner, u, w, side)]))
        return box.extrude(_v(scale(normalize(normal), height)))

    # ---- sections and booleans
    def sectionPlane(self, shape, origin, normal):
        n = normalize(normal)
        return _part().Compound(shape.slice(_v(n), dot(n, origin)))

    def section(self, a, b):
        return a.section(b)

    def fuse(self, a, b):
        return a.fuse(b)

    def fuseAll(self, shapes):
        return shapes[0].multiFuse(list(shapes[1:]))

    def cut(self, a, b):
        return a.cut(b)

    def common(self, a, b):
        return a.common(b)

    def booleanOp(self, op, args, tools, options):
        fuzz = options.get("fuzzyValue") or 0.0
        a = args[0] if len(args) == 1 else _part().Compound(args)
        r = (a.fuse if op == 0 else a.cut if op == 1 else a.common)(list(tools), fuzz)
        return self._with_history([*args, *tools], r, options.get("inputFaceHashes"))

    def _with_history(self, inputs, result, faces):
        only = set(faces) if faces is not None else None
        return {"result": result, "modified": flat_history(traced_history(self, inputs, result, only))}

    def fuseWithHistory(self, a, b, faces, upper=HASH_BOUND):
        return self._with_history([a, b], a.fuse(b), faces)

    def cutWithHistory(self, a, b, faces, upper=HASH_BOUND):
        return self._with_history([a, b], a.cut(b), faces)

    def intersectWithHistory(self, a, b, faces, upper=HASH_BOUND):
        return self._with_history([a, b], a.common(b), faces)

    def distanceBetween(self, a, b):
        return a.distToShape(b)[0]

    # ---- brep
    def toBREPBinary(self, shape):
        return shape.exportBrepToString().encode()

    def fromBREPBinary(self, data):
        s = _part().Shape()
        s.importBrepFromString(data.decode() if isinstance(data, (bytes, bytearray)) else data)
        return s

    def makeVertex(self, x, y, z):
        return _part().Vertex(x, y, z)

    def makeCompound(self, shapes):
        return _part().Compound(list(shapes))

    def makeSolid(self, shell):
        return _part().Solid(shell)

    def unifySameDomain(self, shape):
        return shape.removeSplitter()

    # ---- reading
    def getSubShapes(self, shape, kind):
        return list({"solid": shape.Solids, "shell": shape.Shells, "face": shape.Faces, "edge": shape.Edges, "vertex": shape.Vertexes}[kind])

    def subShapeCount(self, shape, kind):
        return len(self.getSubShapes(shape, kind))

    def subShapeHashes(self, shape, kind, upper=HASH_BOUND):
        return [_hash(s, upper) for s in self.getSubShapes(shape, kind)]

    def hashCode(self, shape, upper=HASH_BOUND):
        return _hash(shape, upper)

    def vertexPosition(self, v):
        return _l(v.Point)

    def projectPointOnFace(self, face, p):
        u, v = face.Surface.parameter(_v(p))
        return _l(face.Surface.value(u, v))

    def projectPointOnEdge(self, edge, p):
        d = edge.distToShape(_part().Vertex(_v(p)))
        q = d[1][0][0]
        t = edge.Curve.parameter(q)
        return {"point": _l(q), "tangent": _l(edge.tangentAt(t)), "parameter": t}

    def surfaceType(self, face):
        name = type(face.Surface).__name__
        return _SURFACE.get(name, name.lower())

    def surfaceNormal(self, face, u, v):
        return _l(face.normalAt(u, v))

    def uvBounds(self, face):
        r = face.ParameterRange
        return {"uMin": r[0], "uMax": r[1], "vMin": r[2], "vMax": r[3]}

    def getSurfaceCenterOfMass(self, face):
        return _l(face.CenterOfMass)

    def pointOnSurface(self, face, u, v):
        return _l(face.valueAt(u, v))

    def uvFromPoint(self, face, p):
        u, v = face.Surface.parameter(_v(p))
        return u, v

    def classifyPointOnFace(self, face, u, v):
        if not face.isPartOfDomain(u, v):
            return "out"
        if not face.Edges:  # an unbounded face: nothing to be on, and no distance to take
            return "in"
        P = _part()
        near = P.Vertex(face.valueAt(u, v)).distToShape(P.Compound(face.Edges))[0]
        return "on" if near < 1e-7 else "in"

    def getSurfaceArea(self, shape):
        return shape.Area

    def getFaceCylinderData(self, face):
        s = face.Surface
        return {"radius": s.Radius} if type(s).__name__ == "Cylinder" else None

    def surfaceCurvature(self, face, u, v):
        k = face.curvatureAt(u, v)
        return {"min": min(k), "max": max(k), "mean": (k[0] + k[1]) / 2}

    def curveType(self, edge):
        name = type(edge.Curve).__name__
        return _CURVE.get(name, name.lower())

    def curveParameters(self, edge):
        r = edge.ParameterRange
        return {"first": r[0], "last": r[1]}

    def curvePointAtParam(self, edge, t):
        return _l(edge.valueAt(t))

    def curveTangent(self, edge, t):
        return _l(edge.tangentAt(t))

    def curveLength(self, edge):
        return edge.Length

    def edgeToFaceMap(self, shape, upper=HASH_BOUND):
        P = _part()
        out = []
        for e in shape.Edges:
            faces = []
            for f in shape.ancestorsOfType(e, P.Face):
                h = _hash(f, upper)
                if h not in faces:
                    faces.append(h)
            out += [_hash(e, upper), len(faces), *faces]
        return out

    def wireframe(self, shape, deflection):
        points = []
        groups = []
        for e in shape.Edges:
            start = len(points)
            for p in e.discretize(Deflection=deflection):
                points += [p.x, p.y, p.z]
            groups += [start, len(points) - start, _hash(e)]
        return {"points": points, "edgeGroups": groups}

    # ---- rounds, walls, offsets
    def fillet(self, solid, edges, radius):
        return solid.makeFillet(radius, list(edges))

    def filletVariable(self, solid, edge, r1, r2):
        return solid.makeFillet(r1, r2, [edge])

    def filletWithHistory(self, solid, edges, radius, faces, upper=HASH_BOUND):
        if isinstance(radius, (int, float)):
            r = solid.makeFillet(radius, list(edges))
        else:
            radii = [(x, x) if isinstance(x, (int, float)) else (x["start"], x["end"]) for x in radius]
            if len(set(radii)) == 1:
                r = solid.makeFillet(radii[0][0], radii[0][1], list(edges))
            else:
                r = self.scratch.fillet_radii(solid, edges, radii)
        return self._with_history([solid], r, faces)

    def chamfer(self, solid, edges, distance):
        return solid.makeChamfer(distance, list(edges))

    def chamferWithHistory(self, solid, edges, distance, faces, upper=HASH_BOUND):
        return self._with_history([solid], solid.makeChamfer(distance, list(edges)), faces)

    def chamferDistAngle(self, solid, edges, distance, angle_deg):
        # Two planes meeting along every edge at one angle: the far distance
        # is exact, and one makeChamfer does it. Otherwise PartDesign's.
        far = []
        for e in edges:
            sides = [f for f in solid.ancestorsOfType(e, _part().Face)]
            if len(sides) != 2 or any(self.surfaceType(f) != "plane" for f in sides):
                far = None
                break
            phi = dihedral([_l(f.normalAt(*f.Surface.parameter(e.valueAt((e.FirstParameter + e.LastParameter) / 2)))) for f in sides])
            far.append(far_distance(distance, math.radians(angle_deg), phi))
        if far and max(far) - min(far) < 1e-9:
            return solid.makeChamfer(distance, far[0], list(edges))
        return self.scratch.chamfer_distance_angle(solid, edges, distance, angle_deg)

    def shell(self, solid, faces, thickness, tolerance):
        return solid.makeThickness(list(faces), -thickness, tolerance)

    def shellWithHistory(self, solid, removed, thickness, tolerance, faces, upper=HASH_BOUND):
        return self._with_history([solid], solid.makeThickness(list(removed), -thickness, tolerance), faces)

    def offset(self, solid, distance, tolerance):
        return solid.makeOffsetShape(distance, tolerance)

    def thicken(self, shape, thickness, tolerance):
        return shape.makeOffsetShape(thickness, tolerance, fill=True)

    def thickenWithHistory(self, shape, thickness, tolerance, faces, upper=HASH_BOUND):
        return self._with_history([shape], self.thicken(shape, thickness, tolerance), faces)

    def defeature(self, shape, faces, tolerance):
        return shape.defeaturing(list(faces))

    def draft(self, shape, face, angle_rad, direction):
        return self.scratch.draft(shape, face, math.degrees(angle_rad))

    def mirrorWithHistory(self, shape, point, normal, faces, upper=HASH_BOUND):
        r = shape.mirror(_v(point), _v(normal))
        return {"result": r, "modified": flat_history(history_by_order(self.subShapeHashes(shape, "face"), self.subShapeHashes(r, "face")))}

    # ---- more solids
    def loft(self, wires, is_solid, ruled):
        return _part().makeLoft(list(wires), bool(is_solid), bool(ruled))

    def linearPattern(self, shape, direction, spacing, count):
        d = normalize(direction)
        return _part().Compound([shape.translated(_v(scale(d, spacing * i))) for i in range(count)])

    def circularPattern(self, shape, center, axis, angle_rad, count):
        step = math.degrees(angle_rad) / count
        return _part().Compound([shape.copy() if i == 0 else shape.rotated(_v(center), _v(axis), step * i) for i in range(count)])

    def split(self, shape, tools):
        from BOPTools import SplitAPI  # noqa: PLC0415

        return SplitAPI.slice(shape, list(tools), "Split")

    def bsplineSurface(self, points, rows, cols):
        s = _part().BSplineSurface()
        s.interpolate([[_v(points[r * cols + c]) for c in range(cols)] for r in range(rows)])
        return s.toShape()

    def sew(self, shapes, tolerance=1e-6):
        c = _part().Compound(list(shapes))
        c.sewShape(tolerance)
        return c

    def sewAndSolidify(self, faces, tolerance=1e-6):
        P = _part()
        sewn = self.sew(faces, tolerance)
        try:
            return P.Solid(P.Shell(sewn.Faces))
        except Exception:  # noqa: BLE001 — they do not close: the sewn shell, as OCCT's sewing leaves it
            return sewn.Shells[0] if len(sewn.Shells) == 1 else sewn

    def healSolid(self, shape, tolerance=1e-6):
        s = shape.copy()
        s.fix(tolerance, tolerance, tolerance)
        return s

    # ---- checks and measures
    def getShapeType(self, shape):
        return shape.ShapeType.lower()

    def containsPoint(self, shape, p, tolerance=1e-6):
        v = _v(p)
        return any(s.isInside(v, tolerance, True) for s in shape.Solids)

    def isValid(self, shape):
        return shape.isValid()

    def isNull(self, shape):
        return shape.isNull()

    def getVolume(self, shape):
        return shape.Volume

    def getCenterOfMass(self, shape):
        solids = shape.Solids
        if len(solids) == 1:
            return _l(solids[0].CenterOfMass)
        total = sum(s.Volume for s in solids)
        if total <= 0:
            return _l(shape.BoundBox.Center)
        return [sum(s.CenterOfMass[i] * s.Volume for s in solids) / total for i in range(3)]

    def getBoundingBox(self, shape, options=None):
        b = shape.optimalBoundingBox() if (options or {}).get("precise", True) else shape.BoundBox
        return {"xmin": b.XMin, "ymin": b.YMin, "zmin": b.ZMin, "xmax": b.XMax, "ymax": b.YMax, "zmax": b.ZMax}

    def meshShape(self, shape, options=None):
        d = (options or {}).get("linearDeflection", 0.1)
        positions, indices, groups = [], [], []
        for f in shape.Faces:
            pts, tris = f.tessellate(d)
            base = len(positions) // 3
            start = len(indices)
            for p in pts:
                positions += [p.x, p.y, p.z]
            for t in tris:
                indices += [base + t[0], base + t[1], base + t[2]]
            groups += [start, len(indices) - start, _hash(f)]
        return {"positions": positions, "normals": [], "indices": indices, "faceGroups": groups}

    def exportStep(self, shape):
        import os  # noqa: PLC0415
        import tempfile  # noqa: PLC0415

        fd, path = tempfile.mkstemp(suffix=".step")
        os.close(fd)
        try:
            shape.exportStep(path)
            with open(path, encoding="utf-8", errors="replace") as f:
                return f.read()
        finally:
            os.remove(path)

    def importStep(self, data):
        import os  # noqa: PLC0415
        import tempfile  # noqa: PLC0415

        fd, path = tempfile.mkstemp(suffix=".step")
        with os.fdopen(fd, "wb") as f:
            f.write(data.encode() if isinstance(data, str) else bytes(data))
        try:
            s = _part().Shape()
            s.read(path)
            return s
        finally:
            os.remove(path)

    def createXCAFDocument(self):
        raise KernelError("named, coloured STEP export comes with build step 10.")

    def release(self, shape):
        return None


# A half-space's box past a part: this far beyond it, in mm; without the
# part's extent, this big.
HALF_SPACE_MARGIN = 1.0
HALF_SPACE_BIG = 1e5


def half_space_box(origin, n, bounds=None):
    """The box standing for the half of space on n's side of the plane
    through origin: (corner, u, w, side, height), a square of `side` in the
    plane from `corner` along u and w, raised `height` along n — past every
    corner of `bounds` ({xmin … zmax}) on that side."""
    u = normalize(cross(n, [1, 0, 0] if abs(n[0]) < 0.9 else [0, 1, 0]))
    w = cross(n, u)
    if bounds is None:
        centre, reach = list(origin), HALF_SPACE_BIG
    else:
        lo = [bounds["xmin"], bounds["ymin"], bounds["zmin"]]
        hi = [bounds["xmax"], bounds["ymax"], bounds["zmax"]]
        mid = [(a + b) / 2 for a, b in zip(lo, hi)]
        up = dot(sub(mid, origin), n)
        centre = add_scaled(mid, n, -up)
        reach = length(sub(hi, lo)) + abs(up) + HALF_SPACE_MARGIN
    corner = add_scaled(add_scaled(centre, u, -reach), w, -reach)
    return corner, u, w, 2 * reach, reach


def _square(corner, u, w, size):
    a = corner
    b = add_scaled(a, u, size)
    c = add_scaled(b, w, size)
    d = add_scaled(a, w, size)
    return [(a, b), (b, c), (c, d), (d, a)]


# ---- Scratch: the hidden document --------------------------------------------------------------


class Scratch:
    """One hidden document a session, for the operations Part has no Python
    call for: each input goes in as a Part::Feature, the result is read and
    copied, the objects removed. Kept out of undo, never saved."""

    NAME = "ReverseScratch"

    def __init__(self):
        self._doc = None

    def doc(self):
        import FreeCAD  # noqa: PLC0415

        if self._doc is not None:
            try:
                self._doc.Name  # noqa: B018 — a closed document raises
                return self._doc
            except Exception:  # noqa: BLE001
                self._doc = None
        try:
            d = FreeCAD.newDocument(self.NAME, hidden=True, temp=True)
        except TypeError:
            d = FreeCAD.newDocument(self.NAME, hidden=True)
        d.UndoMode = 0
        self._doc = d
        return d

    @contextlib.contextmanager
    def _objects(self):
        d = self.doc()
        made = []
        try:
            yield d, made
        finally:
            for o in reversed(made):
                try:
                    d.removeObject(o.Name)
                except Exception:  # noqa: BLE001 — removed with its body already
                    pass

    def _feature(self, d, made, shape, name="Input"):
        o = d.addObject("Part::Feature", name)
        o.Shape = shape
        made.append(o)
        return o

    @staticmethod
    def _result(d, o, what):
        d.recompute()
        if o.isValid() is False or o.Shape.isNull():
            raise KernelError(f"the {what} could not be made.")
        return o.Shape.copy()

    def tapered_prism(self, face, vec, angle_deg):
        """The face swept along vec, the sides leaning in by angle_deg (a
        positive draft narrows the prism as it goes, as occt-wasm's)."""
        with self._objects() as (d, made):
            src = self._feature(d, made, face)
            e = d.addObject("Part::Extrusion", "Taper")
            made.append(e)
            e.Base = src
            e.DirMode = "Custom"
            e.Dir = _v(normalize(vec))
            e.LengthFwd = length(vec)
            e.Solid = True
            e.TaperAngle = -angle_deg
            return self._result(d, e, "tapered extrusion")

    def _body(self, d, made, shape):
        import PartDesign  # noqa: F401, PLC0415 — registers the PartDesign types headless

        body = d.addObject("PartDesign::Body", "Body")
        made.append(body)
        base = self._feature(d, made, shape, "Base")
        body.BaseFeature = base
        return body, base

    def draft(self, shape, face, angle_deg):
        """PartDesign's Draft of one face, the neutral plane the body's XY
        (through the origin, square to +Z), pulled along +Z."""
        with self._objects() as (d, made):
            body, base = self._body(d, made, shape)
            name = f"Face{_index_of(shape.Faces, face) + 1}"
            dr = body.newObject("PartDesign::Draft", "Draft")
            made.append(dr)
            dr.Base = (base, [name])
            xy = next(o for o in body.Origin.OriginFeatures if getattr(o, "Role", "") == "XY_Plane")
            dr.NeutralPlane = (xy, [""])
            dr.Angle = angle_deg
            dr.Reversed = False
            return self._result(d, dr, "draft")

    def chamfer_distance_angle(self, shape, edges, distance, angle_deg):
        with self._objects() as (d, made):
            body, base = self._body(d, made, shape)
            ch = body.newObject("PartDesign::Chamfer", "Chamfer")
            made.append(ch)
            ch.Base = (base, [f"Edge{_index_of(shape.Edges, e) + 1}" for e in edges])
            ch.ChamferType = "Distance and Angle"
            ch.Size = distance
            ch.Angle = angle_deg
            ch.UseAllEdges = False
            return self._result(d, ch, "chamfer")

    def fillet_radii(self, shape, edges, radii):
        """Part::Fillet with a radius pair an edge: what makeFillet cannot."""
        with self._objects() as (d, made):
            src = self._feature(d, made, shape)
            f = d.addObject("Part::Fillet", "Fillet")
            made.append(f)
            f.Base = src
            f.Edges = [(_index_of(shape.Edges, e) + 1, float(r[0]), float(r[1])) for e, r in zip(edges, radii)]
            return self._result(d, f, "fillet")


def _index_of(subs, s):
    for i, x in enumerate(subs):
        if x.isSame(s):
            return i
    raise KernelError("the sub-shape is not on the body.")


# ---- the kernel's helpers (kernelOps.ts) ----------------------------------------------------------------


def lone_solid(occt, shape):
    if occt.getShapeType(shape) != "compound":
        return shape
    solids = occt.getSubShapes(shape, "solid")
    return solids[0] if len(solids) == 1 else shape


def as_solid(occt, shape):
    solid = lone_solid(occt, shape)
    if solid is shape or not unifying():
        return solid
    return occt.unifySameDomain(solid)


def tracked(occt, ev):
    history = parse_history(ev["modified"])
    solid = lone_solid(occt, ev["result"])
    if solid is ev["result"] or not unifying():
        return {"shape": solid, "history": history}
    unified = occt.unifySameDomain(solid)
    return {"shape": unified, "history": compose_history(history, unify_history(occt, solid, unified))}


def with_sub_shapes(occt, shape, kind, hashes, fn):
    by_hash = {}
    for h in occt.getSubShapes(shape, kind):
        by_hash.setdefault(occt.hashCode(h, HASH_BOUND), h)
    picked = []
    for x in hashes:
        if x not in by_hash:
            raise KernelError(f"the {kind} is not on the body.")
        picked.append(by_hash[x])
    if not picked:
        raise KernelError(f"no {kind} given.")
    return fn(picked)


def read_face(occt, f):
    """kernelOps readFace: a face read for its fingerprint (RawFace)."""
    o = occt
    h = o.hashCode(f, HASH_BOUND)
    kind = face_kind_of(o.surfaceType(f))
    uv = o.uvBounds(f)
    area = o.getSurfaceArea(f)
    centroid = o.getSurfaceCenterOfMass(f)
    um = (uv["uMin"] + uv["uMax"]) / 2
    vm = (uv["vMin"] + uv["vMax"]) / 2

    def normal_at(u, v):
        return normalize(o.surfaceNormal(f, u, v)) or [0, 0, 1]

    d = normal_at(um, vm)
    out = {"hash": h, "kind": kind, "centroid": centroid, "dir": d, "area": area}
    if kind in ("cylinder", "cone", "torus"):
        out["fullTurn"] = is_full_turn(uv)
        span = uv["uMax"] - uv["uMin"]
        n0, n1, n2 = normal_at(uv["uMin"], vm), normal_at(uv["uMin"] + span / 3, vm), normal_at(uv["uMin"] + 2 * span / 3, vm)
        axis = normalize(cross(sub(n0, n1), sub(n1, n2))) or normalize(cross(n0, n2))
        if axis:
            out["dir"] = canonical_dir(axis)
        if kind == "cylinder":
            cyl = o.getFaceCylinderData(f)
            if cyl:
                out["radius"] = cyl["radius"]
        if kind in ("cylinder", "cone"):
            q = math.pi / 2
            pts = [o.pointOnSurface(f, uv["uMin"] + i * q, vm) for i in range(4)]
            out["center"] = [sum(p[k] for p in pts) / 4 for k in range(3)]
    elif kind == "sphere":
        c = o.surfaceCurvature(f, um, vm)
        if abs(c["mean"]) > 1e-12:
            r = 1 / abs(c["mean"])
            p = o.pointOnSurface(f, um, vm)
            q = o.pointOnSurface(f, (uv["uMin"] + um) / 2, (uv["vMin"] + vm) / 2)
            behind = add_scaled(p, d, -r)
            ahead = add_scaled(p, d, r)
            out["radius"] = r
            out["center"] = ahead if abs(length(sub(q, ahead)) - r) < abs(length(sub(q, behind)) - r) else behind
    return out


def read_round(occt, handle, d, center, needs):
    uv = occt.uvBounds(handle)
    if not is_full_turn(uv):
        raise KernelError(f"the round face does not go the whole way round — {needs}.")
    axis = normalize(d) or [0, 0, 1]
    um = (uv["uMin"] + uv["uMax"]) / 2
    vm = (uv["vMin"] + uv["vMax"]) / 2
    p = occt.pointOnSurface(handle, um, vm)
    radial = sub(sub(p, center), scale(axis, dot(sub(p, center), axis)))
    convex = dot(occt.surfaceNormal(handle, um, vm), radial) > 0
    # v is a round surface's height up its axis: the ends read off the
    # surface in doubles.
    ends = [dot(sub(occt.pointOnSurface(handle, um, v), center), axis) for v in (uv["vMin"], uv["vMax"])]
    lo, hi = min(ends), max(ends)
    if not hi - lo > 1e-9:
        raise KernelError("the round face has no length.")
    return {"axis": axis, "convex": convex, "lo": lo, "hi": hi}


def on_copy(occt, kernel, solid, face_hashes, fn):
    """kernelShell onCopy: fn on a copy of the solid, the faces named on the
    copy, the history handed back keyed by the solid's own faces."""
    copy = occt.copy(solid)
    was = kernel.face_hashes(solid)
    now = kernel.face_hashes(copy)
    if len(was) != len(now):
        raise KernelError("the body could not be copied.")
    to_copy = dict(zip(was, now))
    result = fn(copy, [to_copy.get(h, h) for h in face_hashes])
    if result is None or isinstance(result, str):
        return result
    from_copy = dict(zip(now, was))
    history = {from_copy.get(h, h): made for h, made in result["history"].items()}
    for h, c in to_copy.items():
        history.setdefault(h, [c])
    return {**result, "history": history}


# ---- the kernel (kernel.ts ReKernel) ------------------------------------------------------------------


class Kernel:
    """ReKernel on FreeCAD Part. Shapes are Part.Shape; nothing to release."""

    coarse_fuzz = FUZZY_COARSE_MM

    def __init__(self, occt=None):
        self.occt = occt or Occt()
        self.trapped = None

    @property
    def version(self):
        try:
            import FreeCAD  # noqa: PLC0415

            v = FreeCAD.Version()
            return f"FreeCAD {'.'.join(v[:3])} · OCCT {_part().OCC_VERSION}"
        except Exception:  # noqa: BLE001
            return "FreeCAD"

    keeping_splits = staticmethod(keeping_splits)
    fuzzy_booleans = staticmethod(fuzzy_booleans)

    def release(self, *shapes):
        return None

    def copy(self, shape):
        return shape.copy()

    # ---- profiles to solids
    def wire(self, loop):
        if not loop:
            raise KernelError("A profile loop has no edges.")
        o = self.occt
        edges = []
        for p in loop:
            k = p["kind"]
            if k == "line":
                edges.append(o.makeLineEdge(p["a"], p["b"]))
            elif k == "arc":
                edges.append(o.makeArcEdge(p["a"], p["m"], p["b"]))
            elif k == "circle":
                edges.append(o.makeCircleEdge(p["center"], p["normal"], p["radius"]))
            else:
                edges.append(o.makeBSplineEdge([x for q in p["poles"] for x in q], [1] * len(p["poles"]), p["knots"], p["mults"], 3))
        return o.makeWire(edges)

    def face(self, profile):
        def go():
            f = self.occt.makeFace(self.wire(profile["outer"]))
            if profile.get("holes"):
                f = self.occt.addHolesInFace(f, [self.wire(h) for h in profile["holes"]])
            return f

        return run("Building the sketch face", go)

    def extrude(self, face, d, frm, to, draft_deg=0):
        def go():
            n = normalize(d)
            if not n:
                raise KernelError("the extrusion has no direction.")
            if not abs(to - frm) > 1e-9:
                raise KernelError("the extrusion has no length.")
            drafted = abs(draft_deg) > 1e-9
            lo = frm if drafted else min(frm, to)
            hi = to if drafted else max(frm, to)
            start = scale(n, lo)
            moved = self.occt.translate(face, *start)
            sweep = scale(n, hi - lo)
            solid = self.occt.draftPrism(moved, *sweep, draft_deg) if drafted else self.occt.extrude(moved, *sweep)
            return as_solid(self.occt, solid)

        return run("Extruding", go)

    def revolve(self, face, origin, d, angle_rad):
        def go():
            n = normalize(d)
            if not n:
                raise KernelError("the axis has no direction.")
            if not abs(angle_rad) > 1e-6:
                raise KernelError("the revolve has no angle.")
            return as_solid(self.occt, self.occt.revolve(face, {"point": origin, "direction": n}, angle_rad))

        return run("Revolving", go)

    def screw(self, profile, origin, d, angle_rad, pitch, left_handed, turn_by_turn=False):
        def go():
            n = normalize(d)
            if not n:
                raise KernelError("the axis has no direction.")
            if not angle_rad > 1e-6:
                raise KernelError("the coil has no angle.")
            if not abs(pitch) > 1e-9:
                raise KernelError("the coil has no pitch.")
            middle = loop_middle(profile["outer"])
            foot = add_scaled(origin, n, dot(sub(middle, origin), n))
            radius = length(sub(middle, foot))
            if not radius > 1e-6:
                raise KernelError("the middle of the profile lies on the axis.")
            x = scale(sub(middle, foot), 1 / radius)
            z = n if pitch > 0 else scale(n, -1)
            y = cross(z, x)
            turns = angle_rad / (2 * math.pi)
            o = self.occt
            made = self._helix_by_turns(abs(pitch), turns, radius, left_handed) if turn_by_turn else o.makeHelixWireHanded([0, 0, 0], [0, 0, 1], abs(pitch), turns * abs(pitch), radius, left_handed)
            helix = o.transform(made, [x[0], y[0], z[0], foot[0], x[1], y[1], z[1], foot[1], x[2], y[2], z[2], foot[2]])
            solid = o.sweepOriented(self.wire(profile["outer"]), helix, SWEEP_FIXED_UP, z)
            for hole in profile.get("holes") or []:
                solid = o.cut(solid, o.sweepOriented(self.wire(hole), helix, SWEEP_FIXED_UP, z))
            return as_solid(o, solid)

        return run("Sweeping the coil", go)

    def _helix_by_turns(self, pitch, turns, radius, left_handed):
        o = self.occt
        whole = math.floor(turns + 1e-9)
        rest = turns - whole
        edges = []

        def turn(at, height):
            return o.getSubShapes(o.makeHelixWireHanded([0, 0, at], [0, 0, 1], pitch, height, radius, left_handed), "edge")

        if whole > 0:
            one = turn(0, pitch)
            for i in range(whole):
                edges += [o.copy(e) if i == 0 else o.translate(e, 0, 0, i * pitch) for e in one]
        if rest > 1e-9:
            edges += turn(whole * pitch, rest * pitch)
        return o.makeWire(edges)

    def sheet(self, pieces, d, frm, to):
        def go():
            n = normalize(d)
            if not n:
                raise KernelError("the sheet has no direction.")
            lo, hi = min(frm, to), max(frm, to)
            if not hi - lo > 1e-9:
                raise KernelError("the sheet has no height.")
            moved = self.occt.translate(self.wire(pieces), *scale(n, lo))
            return self.occt.extrude(moved, *scale(n, hi - lo))

        return run("Making the sheet", go)

    def surface_through(self, points, rows, cols):
        def go():
            if rows < 2 or cols < 2 or len(points) != rows * cols * 3:
                raise KernelError("the surface grid is malformed.")
            grid = [[float(points[i * 3]), float(points[i * 3 + 1]), float(points[i * 3 + 2])] for i in range(rows * cols)]
            f = self.occt.bsplineSurface(grid, rows, cols)
            if self.occt.isNull(f):
                raise KernelError("the surface could not be made through the grid.")
            return f

        return run("Making the surface", go)

    def sew_patches(self, faces, tolerance, closed):
        """Faces that meet edge to edge sewn into one shell — a solid where
        `closed` asks for one and they close, healed to the tolerance — and
        never unified: each face stays the face it came as."""

        def go():
            o = self.occt
            if not faces:
                raise KernelError("no faces to sew.")
            if not closed:
                return o.sew(list(faces), tolerance)
            sewn = o.sewAndSolidify(list(faces), tolerance)
            if o.getShapeType(sewn) != "solid":
                return sewn
            try:
                healed = o.healSolid(sewn, tolerance)
                if not o.isNull(healed) and o.getShapeType(healed) == "solid":
                    return healed
            except Exception:  # noqa: BLE001 — the sewn solid as it is
                pass
            return sewn

        return run("Sewing the patches", go)

    def sweep(self, profile, path):
        def go():
            o = self.occt
            spine = self.wire(path)
            solid = o.sweepOriented(self.wire(profile["outer"]), spine, SWEEP_FIXED)
            for hole in profile.get("holes") or []:
                solid = o.cut(solid, o.sweepOriented(self.wire(hole), spine, SWEEP_FIXED))
            return as_solid(o, solid)

        return run("Sweeping", go)

    def loft(self, profiles, ruled):
        def go():
            if len(profiles) < 2:
                raise KernelError("a loft needs two or more profiles.")
            return as_solid(self.occt, self.occt.loft([self.wire(p["outer"]) for p in profiles], True, ruled))

        return run("Lofting", go)

    def pattern(self, shape, mode, origin, d, count, step):
        from .features import pattern_pitch

        def go():
            n = normalize(d)
            if not n:
                raise KernelError("the pattern has no direction.")
            if not count >= 2:
                raise KernelError("a pattern needs a count of two or more.")
            o = self.occt
            compound = o.linearPattern(shape, n, step, count) if mode == "linear" else o.circularPattern(shape, origin, n, (pattern_pitch(step, count) * count * math.pi) / 180, count)
            copies = o.getSubShapes(compound, "solid")
            if not copies and o.subShapeCount(compound, "face") > 0:
                return compound
            if not copies:
                raise KernelError("the pattern made nothing.")
            return self._fuse_solids(copies)

        return run("Patterning", go)

    def _fuse_solids(self, solids):
        o = self.occt
        if len(solids) == 1:
            return o.copy(solids[0])
        try:
            every = o.fuseAll(list(solids))
        except Exception:  # noqa: BLE001 — fused one after another below
            every = None
        if every is not None and (len(solids) == 2 or o.isValid(every)):
            return as_solid(o, every)
        acc = o.fuse(solids[0], solids[1])
        for s in solids[2:]:
            acc = o.fuse(acc, s)
        return as_solid(o, acc)

    def split(self, shape, tools):
        return run("Splitting", lambda: self.occt.getSubShapes(self.occt.split(shape, list(tools)), "solid"))

    def distance_to_point(self, shape, p):
        return run("Measuring the distance", lambda: self.occt.distanceBetween(self.occt.makeVertex(float(p[0]), float(p[1]), float(p[2])), shape))

    def traced_history(self, before, after):
        return run("Tracing the faces", lambda: traced_history(self.occt, before if isinstance(before, (list, tuple)) else [before], after))

    def distance_between(self, a, b):
        return run("Measuring the distance", lambda: self.occt.distanceBetween(a, b))

    def box(self, lo, hi):
        def go():
            f = self.face({"outer": rectangle_loop(list(lo), [1, 0, 0], [0, 1, 0], hi[0] - lo[0], hi[1] - lo[1]), "holes": []})
            return self.extrude(f, [0, 0, 1], 0, hi[2] - lo[2])

        return run("Making the box", go)

    def half_space(self, origin, normal, around=None):
        """The side of the plane `normal` points to: a box past `around`
        (the part to be cut) when given, a very large one otherwise."""
        def go():
            n = normalize(normal)
            if not n:
                raise KernelError("the plane has no normal.")
            return self.occt.halfSpace(origin, n, None if around is None else self.occt.getBoundingBox(around))

        return run("Building a half-space", go)

    # ---- booleans
    def fuse(self, a, b):
        return run("Joining", lambda: as_solid(self.occt, self.occt.fuse(a, b)))

    def fuse_all(self, shapes):
        def go():
            if not shapes:
                raise KernelError("nothing to join.")
            return self._fuse_solids(list(shapes))

        return run("Joining", go)

    def cut(self, a, b):
        return run("Cutting", lambda: as_solid(self.occt, self.occt.cut(a, b)))

    def common(self, a, b):
        return run("Intersecting", lambda: as_solid(self.occt, self.occt.common(a, b)))

    def _boolean_with_history(self, op, a, b):
        o = self.occt
        hashes = self.face_hashes(a) + self.face_hashes(b)
        fuzz = boolean_fuzz()
        if fuzz > 0:
            return o.booleanOp(op, [a], [b], {"fuzzyValue": fuzz, "inputFaceHashes": hashes, "hashUpperBound": HASH_BOUND})
        return (o.fuseWithHistory if op == 0 else o.cutWithHistory if op == 1 else o.intersectWithHistory)(a, b, hashes, HASH_BOUND)

    def fuse_tracked(self, a, b):
        return run("Joining", lambda: tracked(self.occt, self._boolean_with_history(0, a, b)))

    def cut_tracked(self, a, b):
        return run("Cutting", lambda: tracked(self.occt, self._boolean_with_history(1, a, b)))

    def common_tracked(self, a, b):
        return run("Intersecting", lambda: tracked(self.occt, self._boolean_with_history(2, a, b)))

    # ---- rounds and chamfers (made on a copy, kernel.ts roundOnCopy)
    def _edges_on_copy(self, solid, copy, edge_hashes):
        was = self.occt.subShapeHashes(solid, "edge")
        now = self.occt.subShapeHashes(copy, "edge")
        if len(was) != len(now):
            raise KernelError("the body could not be copied.")
        to = dict(zip(was, now))
        return [to.get(h, h) for h in edge_hashes]

    def _round_on_copy(self, solid, edge_hashes, make):
        return on_copy(self.occt, self, solid, [], lambda copy, _: make(copy, self._edges_on_copy(solid, copy, edge_hashes)))

    def _full_width(self, size, make):
        """kernelRounds fullWidth: a round that does not close at its size
        tried a hair under it. The sliver closers are not ported: the near
        result stands as made."""
        exact = None
        failure = None
        try:
            exact = make(size)
            if self.is_closed_solid(exact["shape"]):
                return exact
        except Exception as e:  # noqa: BLE001
            failure = e
        for s in FULL_WIDTH_SLACK:
            try:
                near = make(size * (1 - s))
            except Exception:  # noqa: BLE001
                continue
            if self.is_closed_solid(near["shape"]):
                return near
        if exact is not None:
            return exact
        raise failure

    def fillet_tracked(self, solid, edge_hashes, radius):
        def go():
            if not radius > 0:
                raise KernelError("the radius must be positive.")
            return self._round_on_copy(solid, edge_hashes, lambda copy, hashes: self._full_width(
                radius, lambda r: with_sub_shapes(self.occt, copy, "edge", hashes, lambda edges: tracked(self.occt, self.occt.filletWithHistory(copy, edges, r, self.face_hashes(copy))))))

        return run("Filleting", go)

    def fillet_radii(self, solid, edges):
        def go():
            sizes = [x for e in edges for x in ([e["radius"]] if isinstance(e["radius"], (int, float)) else list(e["radius"]))]
            if not all(r > 0 for r in sizes):
                raise KernelError("the radii must be positive.")
            most = max(sizes)

            def make(copy, hashes):
                def at(size):
                    k = size / most
                    radii = [e["radius"] * k if isinstance(e["radius"], (int, float)) else {"start": e["radius"][0] * k, "end": e["radius"][1] * k} for e in edges]
                    return with_sub_shapes(self.occt, copy, "edge", hashes, lambda hs: tracked(self.occt, self.occt.filletWithHistory(copy, hs, radii, self.face_hashes(copy))))

                return self._full_width(most, at)

            return self._round_on_copy(solid, [e["hash"] for e in edges], make)

        return run("Filleting", go)

    def fillet_variable(self, solid, edge_hash, r1, r2):
        def go():
            if not (r1 > 0 and r2 > 0):
                raise KernelError("the radii must be positive.")
            copy = self.occt.copy(solid)
            hashes = self._edges_on_copy(solid, copy, [edge_hash])
            return with_sub_shapes(self.occt, copy, "edge", hashes, lambda es: as_solid(self.occt, self.occt.filletVariable(copy, es[0], r1, r2)))

        return run("Filleting", go)

    def chamfer_tracked(self, solid, edge_hashes, distance):
        def go():
            if not distance > 0:
                raise KernelError("the distance must be positive.")
            return self._round_on_copy(solid, edge_hashes, lambda copy, hashes: self._full_width(
                distance, lambda d: with_sub_shapes(self.occt, copy, "edge", hashes, lambda edges: tracked(self.occt, self.occt.chamferWithHistory(copy, edges, d, self.face_hashes(copy))))))

        return run("Chamfering", go)

    def chamfer_angled(self, solid, edge_hashes, distance, angle_deg):
        def go():
            if not distance > 0:
                raise KernelError("the distance must be positive.")
            if not 0 < angle_deg < 90:
                raise KernelError("the angle must lie between 0° and 90°.")
            copy = self.occt.copy(solid)
            hashes = self._edges_on_copy(solid, copy, edge_hashes)
            return with_sub_shapes(self.occt, copy, "edge", hashes, lambda es: as_solid(self.occt, self.occt.chamferDistAngle(copy, es, distance, angle_deg)))

        return run("Chamfering", go)

    def edge_sides(self, solid, edge_hashes):
        def go():
            o = self.occt
            faces_of = parse_history(o.edgeToFaceMap(solid, HASH_BOUND))
            face_at = {}
            for order, f in enumerate(o.getSubShapes(solid, "face")):
                face_at.setdefault(o.hashCode(f, HASH_BOUND), (f, order))
            edge_at = {o.hashCode(e, HASH_BOUND): e for e in o.getSubShapes(solid, "edge")}
            out = []
            for h in edge_hashes:
                e = edge_at.get(h)
                sides = [(x, *face_at[x]) for x in dict.fromkeys(faces_of.get(h, [])) if x in face_at]
                if e is None or len(sides) != 2:
                    out.append(None)
                    continue
                sides.sort(key=lambda s: s[2])
                r = o.curveParameters(e)
                mid = o.curvePointAtParam(e, (r["first"] + r["last"]) / 2)

                def normal_at(f):
                    u, v = o.uvFromPoint(f, mid)
                    return normalize(o.surfaceNormal(f, u, v)) or [0, 0, 1]

                out.append({"faces": [sides[0][0], sides[1][0]], "normals": [normal_at(sides[0][1]), normal_at(sides[1][1])]})
            return out

        return run("Reading the faces at the edges", go)

    def delete_faces(self, solid, face_hashes):
        def go():
            def do(faces):
                out = self.occt.defeature(solid, faces, 0)
                if self.occt.isNull(out):
                    raise KernelError("the faces round them cannot be run on to close the gap.")
                return as_solid(self.occt, out)

            return with_sub_shapes(self.occt, solid, "face", face_hashes, do)

        return run("Deleting faces", go)

    def shell_tracked(self, solid, face_hashes, thickness):
        """kernelShell shellPlain on a copy. The original's two fallbacks (the
        rounds left sharp inside, the long way by offset and cut) come with
        the diagnosis work (build step 13): a shell the thick solid refuses
        fails here with the kernel's words."""

        def plain(copy, faces):
            o = self.occt
            core = None
            why = None
            try:
                core = o.offset(copy, -thickness, 1e-3)
                if o.isNull(core) or not o.getVolume(core) > 1e-9:
                    core, why = None, "the wall is as thick as the body — nothing is left inside to take away."
            except Exception as e:  # noqa: BLE001
                why = f"the kernel's offset of the body inward by the wall failed ({e})."
            if not faces:
                if core is None:
                    raise KernelError(why)
                return tracked(o, o.cutWithHistory(copy, core, self.face_hashes(copy)))
            volume = o.getVolume(copy)
            most = min(volume * (1 - 1e-6), math.inf if core is None else volume - o.getVolume(core) + volume * 1e-4)
            result = with_sub_shapes(o, copy, "face", faces, lambda fs: tracked(o, o.shellWithHistory(copy, fs, thickness, 1e-3, self.face_hashes(copy))))
            if not self.is_closed_solid(result["shape"]) or not o.getVolume(result["shape"]) < most:
                raise KernelError("the thick solid handed the body back without hollowing it.")
            return result

        def go():
            if not thickness > 0:
                raise KernelError("the thickness must be positive.")
            return on_copy(self.occt, self, solid, face_hashes, plain)

        return run("Shelling", go)

    def clearance(self, a, b):
        def go():
            gap = self.occt.distanceBetween(a, b)
            if gap > 1e-6:
                return {"gap": gap, "overlap": 0}
            c = self.occt.common(a, b)
            return {"gap": 0, "overlap": 0 if self.occt.isNull(c) else max(0, self.occt.getVolume(c))}

        return run("Measuring the clearance", go)

    def offset_solid(self, solid, distance):
        def go():
            if not abs(distance) > 1e-9:
                raise KernelError("the offset needs a distance.")
            what = f"the kernel's offset of the body {'outward' if distance > 0 else 'inward'} by {abs(distance)} mm"
            try:
                made = self.occt.offset(solid, distance, 1e-3)
            except Exception as e:  # noqa: BLE001
                raise KernelError(f"{what} failed ({e}).") from e
            if made.isNull() or not made.Solids or not made.isValid():
                raise KernelError(f"{what} came out broken: no valid closed solid.")
            return as_solid(self.occt, made)

        return run("Offsetting", go)

    def mirror_tracked(self, shape, origin, normal):
        def go():
            n = normalize(normal)
            if not n:
                raise KernelError("the mirror plane has no normal.")
            return tracked(self.occt, self.occt.mirrorWithHistory(shape, origin, n, self.face_hashes(shape)))

        return run("Mirroring", go)

    def draft_faces(self, solid, face_hashes, origin, pull, angle_rad, skipped=None):
        """kernelFaces draftFaces: the solid carried so the neutral plane is
        the kernel's (through the origin, square to +Z), drafted one face a
        call, each face found again by what it is, and carried back."""

        def lean_of(handle, up):
            uv = self.occt.uvBounds(handle)
            n = normalize(self.occt.surfaceNormal(handle, (uv["uMin"] + uv["uMax"]) / 2, (uv["vMin"] + uv["vMax"]) / 2))
            return math.asin(max(-1, min(1, dot(n, up)))) if n else 0

        def across(v, up):
            return normalize(sub(v, scale(up, dot(v, up))))

        def go():
            o = self.occt
            d = normalize(pull)
            if not d:
                raise KernelError("the pull direction has no length.")
            turn = turn_onto_z(d)

            def place(p):
                return rotate_vec(sub(p, origin), turn) if turn else sub(p, origin)

            def aim(v):
                return rotate_vec(v, turn) if turn else v

            angles = [angle_rad if isinstance(angle_rad, (int, float)) else angle_rad[i] for i in range(len(face_hashes))]
            if any(not abs(a) > 1e-9 for a in angles):
                raise KernelError("the draft has no angle.")
            if not face_hashes:
                raise KernelError("no face given.")
            every = self.faces(solid)
            wanted = []
            for h in face_hashes:
                f = next((x for x in every if x["hash"] == h), None)
                if not f:
                    raise KernelError("the face is not on the body.")
                if f["kind"] == "plane" and abs(dot(f["dir"], d)) > 0.999:
                    raise KernelError("a face square to the pull direction cannot be drafted — it is the kind of face the neutral plane is.")
                wanted.append(f)
            leans = with_sub_shapes(o, solid, "face", face_hashes, lambda hs: [lean_of(h, d) for h in hs])
            Z = [0, 0, 1]
            current = o.translate(solid, -origin[0], -origin[1], -origin[2])
            if turn:
                current = o.rotate(current, {"point": [0, 0, 0], "direction": turn["axis"]}, turn["angle"])
            for i, w in enumerate(wanted):
                if next(j for j, x in enumerate(wanted) if x["hash"] == w["hash"]) < i:
                    continue
                handles = o.getSubShapes(current, "face")
                at = place(w["centroid"])
                along = aim(w["dir"])
                rnd = w["kind"] in ("cylinder", "cone")
                wall = across(along, Z) if w["kind"] == "plane" else None
                best, best_d = -1, math.inf
                for k, h in enumerate(handles):
                    f = read_face(o, h)
                    if w["kind"] == "plane" and wall:
                        a = across(f["dir"], Z) if f["kind"] == "plane" else None
                        if not a or dot(a, wall) < 0.9999:
                            continue
                    elif rnd:
                        if f["kind"] not in ("cylinder", "cone") or abs(dot(f["dir"], along)) < 0.9999:
                            continue
                    else:
                        if f["kind"] != w["kind"] or abs(dot(f["dir"], along)) < 0.9999:
                            continue
                        if f["kind"] == "plane" and dot(f["dir"], along) < 0:
                            continue
                    dd = length(sub(f["centroid"], at))
                    if dd < best_d:
                        best, best_d = k, dd
                if best < 0:
                    raise KernelError("a face to draft was lost after the one before it was drafted.")
                if w["kind"] == "plane" or rnd:
                    lean = lean_of(handles[best], Z) - leans[i]
                    tol = min(1e-3, abs(angles[i]) / 3)
                    if abs(lean) > tol:
                        if abs(abs(lean) - abs(angles[i])) <= tol:
                            if skipped is not None:
                                skipped.append(i)
                            continue

                        def deg(x):
                            return f"{round(math.degrees(abs(x)) * 100) / 100}°"

                        raise KernelError(f"pick #{i + 1} was leaned already, by {deg(lean)}, with a tangent neighbour drafted before it — faces that meet tangent lean together, at one angle; give them the same angle ({deg(angles[i])} is asked).")
                current = o.draft(current, handles[best], angles[i], [0, 0, 1])
            if turn:
                current = o.rotate(current, {"point": [0, 0, 0], "direction": turn["axis"]}, -turn["angle"])
            return as_solid(o, o.translate(current, *origin))

        return run("Drafting", go)

    def offset_face_tracked(self, solid, face_hash, offset):
        return run("Moving the face", lambda: self._move_face(solid, face_hash, offset))

    def _move_face(self, solid, face_hash, offset):
        if not abs(offset) > 1e-9:
            raise KernelError("the face has nowhere to move — the offset is zero.")
        o = self.occt

        def go(handles):
            handle = handles[0]
            f = read_face(o, handle)
            faces = self.face_hashes(solid)
            if f["kind"] == "plane":
                v = scale(f["dir"], offset)
                prism = o.extrude(o.translate(handle, *v), -v[0], -v[1], -v[2])
                hashes = faces + o.subShapeHashes(prism, "face")
                return tracked(o, o.fuseWithHistory(solid, prism, hashes) if offset > 0 else o.cutWithHistory(solid, prism, hashes))
            if f["kind"] != "cylinder" or f.get("radius") is None or not f.get("center"):
                raise KernelError("only a flat or a cylindrical face can be moved.")
            rd = read_round(o, handle, f["dir"], f["center"], "only a full cylinder can be resized")
            radius = f["radius"] + offset
            if not radius > 1e-6:
                raise KernelError("the radius would not be positive.")

            def circle(r):
                return {"kind": "circle", "center": f["center"], "normal": rd["axis"], "radius": r}

            grow = offset > 0
            profile = self.face({"outer": [circle(radius)], "holes": []} if not rd["convex"] and grow else {"outer": [circle(max(radius, f["radius"]))], "holes": [[circle(min(radius, f["radius"]))]]})
            tool = self.extrude(profile, rd["axis"], rd["lo"], rd["hi"])
            hashes = faces + o.subShapeHashes(tool, "face")
            return tracked(o, o.fuseWithHistory(solid, tool, hashes) if rd["convex"] == grow else o.cutWithHistory(solid, tool, hashes))

        return with_sub_shapes(o, solid, "face", [face_hash], go)

    def offset_faces_tracked(self, solid, face_hashes, offset):
        from .origins import same_surface

        def go():
            if not face_hashes:
                raise KernelError("no face given.")
            if len(face_hashes) == 1:
                return self._move_face(solid, face_hashes[0], offset)
            before = self.faces(solid)
            wanted = []
            for h in face_hashes:
                f = next((x for x in before if x["hash"] == h), None)
                if not f:
                    raise KernelError("the face is not on the body.")
                wanted.append(f)
            shape = solid
            history = {}
            for i, w in enumerate(wanted):
                h = w["hash"]
                if i > 0:
                    now = self.faces(shape)
                    if not any(f["hash"] == h for f in now):
                        found = same_surface(w, now)
                        if not found:
                            raise KernelError("a face to move was lost after the one before it was moved.")
                        h = found["hash"]
                moved = self._move_face(shape, h, offset)
                history = compose_history(history, moved["history"])
                shape = moved["shape"]
            return {"shape": shape, "history": history}

        return run("Moving the faces", go)

    def thread_tracked(self, solid, face_hash, t):
        from .kernel_thread import thread_tracked

        return thread_tracked(self, solid, face_hash, t)

    def transform_tracked(self, shape, matrix):
        def go():
            moved = self.occt.transform(shape, list(matrix[:12]) if len(matrix) >= 12 else matrix)
            return {"shape": moved, "history": history_by_order(self.face_hashes(shape), self.face_hashes(moved))}

        return run("Moving the body", go)

    # ---- faces
    def face_copy(self, shape, face_hash):
        return run("Copying the face", lambda: with_sub_shapes(self.occt, shape, "face", [face_hash], lambda fs: self.occt.copy(fs[0])))

    def face_normals(self, shape, face_hash, points):
        def go(fs):
            out = []
            for p in points:
                u, v = self.occt.uvFromPoint(fs[0], p)
                out.append(normalize(self.occt.surfaceNormal(fs[0], u, v)) or [0, 0, 1])
            return out

        return run("Reading the face", lambda: with_sub_shapes(self.occt, shape, "face", [face_hash], go))

    def face_points(self, shape):
        def go():
            out = []
            for f in self.occt.getSubShapes(shape, "face"):
                b = self.occt.uvBounds(f)
                out.append({"hash": self.occt.hashCode(f), "at": self.occt.pointOnSurface(f, (b["uMin"] + b["uMax"]) / 2, (b["vMin"] + b["vMax"]) / 2)})
            return out

        return run("Reading the faces", go)

    def face_hashes(self, shape):
        return run("Listing the faces", lambda: self.occt.subShapeHashes(shape, "face"))

    def faces(self, shape):
        return run("Reading the faces", lambda: [read_face(self.occt, f) for f in self.occt.getSubShapes(shape, "face")])

    def edges(self, shape, deflection):
        def go():
            o = self.occt
            faces_of = parse_history(o.edgeToFaceMap(shape, HASH_BOUND))
            wire = o.wireframe(shape, deflection)
            g = wire["edgeGroups"]
            polylines = {g[i + 2]: wire["points"][g[i]:g[i] + g[i + 1]] for i in range(0, len(g) - 2, 3)}
            out = []
            for e in o.getSubShapes(shape, "edge"):
                h = o.hashCode(e, HASH_BOUND)
                kind = edge_kind_of(o.curveType(e))
                r = o.curveParameters(e)
                first, last = r["first"], r["last"]

                def at(t, e=e, first=first, last=last):
                    return o.curvePointAtParam(e, first + (last - first) * t)

                def tangent_at(t, e=e, first=first, last=last):
                    return normalize(o.curveTangent(e, first + (last - first) * t)) or [0, 0, 1]

                raw = {"hash": h, "kind": kind, "mid": at(0.5), "dir": canonical_dir(o.curveTangent(e, (first + last) / 2)), "length": o.curveLength(e),
                       "faceHashes": faces_of.get(h, []), "polyline": polylines.get(h, []), "ends": [at(0), at(1)], "endTangents": [tangent_at(0), tangent_at(1)]}
                if kind == "circle":
                    c = circle_through(at(0.25), at(0.5), at(0.75))
                    if c:
                        raw["dir"] = canonical_dir(c["axis"])
                        raw["radius"] = c["radius"]
                out.append(raw)
            return out

        return run("Reading the edges", go)

    # topo.py reads a body through these two names.
    def describe_faces(self, shape):
        return self.faces(shape)

    def describe_edges(self, shape, deflection):
        return self.edges(shape, deflection)

    def solids(self, shape):
        return run("Reading the solids", lambda: self.occt.getSubShapes(shape, "solid"))

    def faces_of(self, shape):
        return run("Reading the faces", lambda: self.occt.getSubShapes(shape, "face"))

    # ---- checks and measures
    def is_closed_solid(self, shape):
        def go():
            o = self.occt
            if shape is None or o.isNull(shape):
                return False
            if o.getShapeType(shape) not in ("solid", "compound"):
                return False
            if o.subShapeCount(shape, "solid") < 1:
                return False
            return o.isValid(shape) and o.getVolume(shape) > 1e-9

        return run("Checking the body", go)

    def is_valid(self, shape):
        return run("Checking the body", lambda: not self.occt.isNull(shape) and self.occt.isValid(shape))

    def is_surface(self, shape):
        def go():
            o = self.occt
            if o.isNull(shape):
                return False
            return o.getShapeType(shape) in ("shell", "face", "compound") and o.subShapeCount(shape, "solid") == 0 and o.subShapeCount(shape, "face") > 0 and o.isValid(shape)

        return run("Checking the sheet", go)

    def surface_area(self, shape):
        return run("Measuring the area", lambda: self.occt.getSurfaceArea(shape))

    def contains_point(self, shape, p, tolerance=1e-6):
        return run("Locating a point", lambda: self.occt.containsPoint(shape, p, tolerance))

    def solid_count(self, shape):
        return run("Counting solids", lambda: self.occt.subShapeCount(shape, "solid"))

    def face_count(self, shape):
        return run("Counting faces", lambda: self.occt.subShapeCount(shape, "face"))

    def shells_per_solid(self, shape):
        return run("Counting shells", lambda: [self.occt.subShapeCount(s, "shell") for s in self.occt.getSubShapes(shape, "solid")])

    def volume(self, shape):
        return run("Measuring the volume", lambda: self.occt.getVolume(shape))

    def centroid(self, shape):
        return run("Measuring the centroid", lambda: self.occt.getCenterOfMass(shape))

    def bounds(self, shape):
        def go():
            b = self.occt.getBoundingBox(shape)
            return {"min": [b["xmin"], b["ymin"], b["zmin"]], "max": [b["xmax"], b["ymax"], b["zmax"]]}

        return run("Measuring the extent", go)

    def extent(self, shape):
        def go():
            b = self.occt.getBoundingBox(shape, {"precise": False})
            return {"min": [b["xmin"], b["ymin"], b["zmin"]], "max": [b["xmax"], b["ymax"], b["zmax"]]}

        return run("Measuring the extent", go)

    def mesh(self, shape, linear_deflection, angular_deflection=0.15):
        def go():
            m = self.occt.meshShape(shape, {"linearDeflection": linear_deflection, "angularDeflection": angular_deflection})
            face_hash = []
            g = m["faceGroups"]
            for i in range(0, len(g) - 2, 3):
                face_hash += [g[i + 2]] * (g[i + 1] // 3)
            return {"positions": m["positions"], "normals": m["normals"], "indices": m["indices"], "faceHash": face_hash}

        return run("Tessellating the body", go)

    def section_polylines(self, shape, origin, normal, deflection):
        def go():
            cut = self.occt.sectionPlane(shape, origin, normal)
            out = []
            for e in cut.Edges:
                pts = e.discretize(Deflection=deflection)
                out.append([c for p in pts for c in (p.x, p.y, p.z)])
            return out

        return run("Cutting a section", go)

    # ---- files
    def export_step(self, shapes, labels=None):
        return run("Writing the STEP file", lambda: self.occt.exportStep(shapes[0] if len(shapes) == 1 else self.occt.makeCompound(shapes)))

    def import_step(self, text):
        def go():
            s = self.occt.importStep(text)
            if s.isNull():
                raise KernelError("the STEP file holds no shape.")
            return s

        return run("Reading the STEP file", go)

    def read_step_parts(self, text):
        """The file's parts, nameless: named parts come with build step 10."""
        s = self.import_step(text)
        parts = s.Solids or ([s] if s.Faces else [])
        return [{"shape": p} for p in parts]

    def to_brep(self, shape):
        return self.occt.toBREPBinary(shape)

    def from_brep(self, data):
        return self.occt.fromBREPBinary(data)


__all__ = ["FUZZY_MM", "FUZZY_COARSE_MM", "KERNEL_OPS", "LATER_STEP", "OCCT_CALLS", "Kernel", "KernelError", "Occt", "Scratch", "as_solid", "dihedral", "far_distance",
           "have_kernel", "keeping_splits", "fuzzy_booleans", "lone_solid", "on_copy", "polygon_loop", "read_face", "read_round", "rotate_vec", "run", "tracked", "turn_onto_z",
           "with_sub_shapes"]
