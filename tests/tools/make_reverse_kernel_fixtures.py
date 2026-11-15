# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/tests/reKit.ts (the shape of its fixtures)
# SPDX-License-Identifier: AGPL-3.0-only
#
# Writes tests/reverse_fixtures/kernel_builds.json: feature lists (the
# original's ReversePart records, as reverse.feature.add takes them) for
# solids whose volume is known exactly by hand, each with what it must
# build to and the formula behind every number. These are not goldens of
# the original's builder (tests/tools/reverse_goldens.mjs makes those where
# occt-wasm runs); they hold the port to geometry, on FreeCAD's OCCT.
#
#   python3 tests/tools/make_reverse_kernel_fixtures.py
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..")
sys.path.insert(0, ROOT)

from scanrulerfc.reverse.regions import find_regions  # noqa: E402
from scanrulerfc.reverse.sketch import add_entity, add_rectangle, empty_sketch  # noqa: E402

XY = {"origin": [0, 0, 0], "normal": [0, 0, 1], "basisU": [1, 0, 0], "basisV": [0, 1, 0]}


def sketch(i, draw, plane=None, frame=None):
    s = empty_sketch()
    draw(s)
    return {"id": i, "kind": "sketch", "name": f"Sketch {i}", "plane": plane or {"kind": "world", "axis": "z", "offset": 0}, "frame": frame or XY, "sketch": s, "visible": True}


def rect(i, x0, y0, x1, y1):
    return sketch(i, lambda s: add_rectangle(s, [x0, y0], [x1, y1]))


def circle(i, cx, cy, r):
    return sketch(i, lambda s: add_entity(s, {"kind": "circle", "c": [cx, cy], "r": r}))


def extrude(i, sk, extent, op="new", **more):
    return {"id": i, "kind": "extrude", "name": f"Extrude {i}", "sketchId": sk["id"], "regions": [r["key"] for r in find_regions(sk["sketch"])], "extent": extent, "op": op, "visible": True, **more}


def dist(frm, to):
    return {"kind": "distance", "from": frm, "to": to}


def plane_face(c, d, area, origin):
    return {"kind": "plane", "centroid": c, "dir": d, "area": area, "origin": origin}


def vertical_edge(x, y, z0, z1, nx, ny, origin):
    return {"kind": "line", "mid": [x, y, (z0 + z1) / 2], "dir": [0, 0, 1], "length": z1 - z0, "faces": [{"kind": "plane", "dir": nx}, {"kind": "plane", "dir": ny}], "origin": origin}


def body(fid, volume, formula, **more):
    return {"id": fid, "volume": volume, "formula": formula, **more}


def box_40_20_10():
    s = rect(1, 0, 0, 40, 20)
    return [s, extrude(2, s, dist(0, 10))]


def cube(n=10):
    s = rect(1, 0, 0, n, n)
    return [s, extrude(2, s, dist(0, n))]


CORNER = vertical_edge(40, 20, 0, 10, [1, 0, 0], [0, 1, 0], 2)
TOP10 = plane_face([5, 5, 10], [0, 0, 1], 100, 2)
WALL_X10 = plane_face([10, 5, 5], [1, 0, 0], 100, 2)

FIXTURES = []


def fx(name, features, bodies, statuses=None, note=None, parameters=None):
    FIXTURES.append({"name": name, "features": features, **({"parameters": parameters} if parameters else {}), "bodies": bodies,
                     "status": statuses or {str(f["id"]): "ok" for f in features if f["kind"] != "sketch"}, **({"note": note} if note else {})})


fx("rectangle extrude, distance", box_40_20_10(), [body(2, 8000, "40·20·10", area=2800, faces=6, box=[[0, 0, 0], [40, 20, 10]])])
s = rect(1, -5, -5, 5, 5)
fx("rectangle extrude, symmetric", [s, extrude(2, s, {"kind": "symmetric", "total": 6})], [body(2, 600, "10·10·6", box=[[-5, -5, -3], [5, 5, 3]])])
s = circle(1, 0, 0, 5)
fx("circle extrude", [s, extrude(2, s, dist(0, 10))], [body(2, 250 * math.pi, "π·5²·10", area=150 * math.pi, faces=3)])
s = rect(1, 0, 0, 10, 10)
fx("extrude to a plane", [s, extrude(2, s, {"kind": "toPlane", "from": 0, "plane": {"kind": "world", "axis": "z", "offset": 7}})], [body(2, 700, "10·10·7", box=[[0, 0, 0], [10, 10, 7]])])
fx("taper", [s, extrude(2, s, dist(0, 5), draftDeg=10)],
   [body(2, 5 / 3 * (100 + (10 - 10 * math.tan(math.radians(10))) ** 2 + 10 * (10 - 10 * math.tan(math.radians(10)))), "frustum h/3·(A₁ + A₂ + √(A₁A₂)), top side 10 − 2·5·tan 10°")],
   note="the scratch Part::Extrusion's TaperAngle sign: a positive draft narrows")
ring = sketch(1, lambda s: add_rectangle(s, [5, 0], [10, 4]))
fx("revolve a tube about Y", [ring, {"id": 2, "kind": "revolve", "name": "Revolve 2", "sketchId": 1, "regions": [r["key"] for r in find_regions(ring["sketch"])],
                                     "axis": {"kind": "world", "axis": "y"}, "angleDeg": 360, "op": "new", "visible": True}],
   [body(2, 2 * math.pi * 7.5 * 20, "Pappus: 2π · 7.5 (the rectangle's centroid off Y) · 5·4", box=[[-10, 0, -10], [10, 4, 10]])])
fx("revolve half a turn", [ring, {"id": 2, "kind": "revolve", "name": "Revolve 2", "sketchId": 1, "regions": [r["key"] for r in find_regions(ring["sketch"])],
                                  "axis": {"kind": "world", "axis": "y"}, "angleDeg": 180, "op": "new", "visible": True}],
   [body(2, math.pi * 7.5 * 20, "Pappus, half: π · 7.5 · 20")])
plate = rect(1, 0, 0, 40, 20)
hole = circle(3, 20, 10, 3)
fx("cut a hole through a plate", [plate, extrude(2, plate, dist(0, 5)), hole, extrude(4, hole, dist(-1, 6), "cut")],
   [body(2, 4000 - 45 * math.pi, "40·20·5 − π·3²·5", faces=7)])
fx("cut on a target", [plate, extrude(2, plate, dist(0, 5)), hole, extrude(4, hole, dist(-1, 6), "cut", target=2)], [body(2, 4000 - 45 * math.pi, "40·20·5 − π·3²·5")])
a = rect(1, 0, 0, 10, 10)
b = rect(3, 5, 0, 15, 10)
fx("join two overlapping blocks", [a, extrude(2, a, dist(0, 10)), b, extrude(4, b, dist(0, 10), "join")], [body(2, 1500, "1000 + 1000 − 500 shared", box=[[0, 0, 0], [15, 10, 10]])])
fx("a join that meets nothing stands apart", [a, extrude(2, a, dist(0, 10)), rect(3, 50, 0, 60, 10), extrude(4, rect(3, 50, 0, 60, 10), dist(0, 10), "join")],
   [body(2, 1000, "10³"), body(4, 1000, "10³, a body of its own")])
slab = rect(3, 10, -1, 20, 21)
fx("a cut through the waist leaves two bodies", [rect(1, 0, 0, 30, 20), extrude(2, rect(1, 0, 0, 30, 20), dist(0, 10)), slab, extrude(4, slab, dist(-1, 11), "cut")],
   [body(2, 2000, "10·20·10, the piece kept the id"), body(4, 2000, "10·20·10, the other piece, a fresh id of the cut")])
fx("combine: join", [a, extrude(2, a, dist(0, 10)), b, extrude(4, b, dist(0, 10)), {"id": 5, "kind": "boolean", "name": "Combine 5", "op": "join", "body": 2, "tool": 4, "visible": True}],
   [body(2, 1500, "1000 + 1000 − 500")])
fx("combine: cut", [a, extrude(2, a, dist(0, 10)), b, extrude(4, b, dist(0, 10)), {"id": 5, "kind": "boolean", "name": "Combine 5", "op": "cut", "body": 2, "tool": 4, "visible": True}],
   [body(2, 500, "1000 − 500")])
fx("combine: intersect, keep the tool", [a, extrude(2, a, dist(0, 10)), b, extrude(4, b, dist(0, 10)), {"id": 5, "kind": "boolean", "name": "Combine 5", "op": "intersect", "body": 2, "tool": 4, "keep": True, "visible": True}],
   [body(2, 500, "the shared 5·10·10"), body(4, 1000, "the tool, kept")])
fx("fillet one edge", [*box_40_20_10(), {"id": 3, "kind": "fillet", "name": "Fillet 3", "body": 2, "edges": [CORNER], "radius": 2, "chain": False, "visible": True}],
   [body(2, 8000 - 10 * 4 * (1 - math.pi / 4), "8000 − L·r²(1 − π/4), L 10, r 2", faces=7)])
fx("fillet, chained round the top", [*cube(), {"id": 3, "kind": "fillet", "name": "Fillet 3", "body": 2, "edges": [{"kind": "line", "mid": [5, 0, 10], "dir": [1, 0, 0], "length": 10, "faces": [{"kind": "plane", "dir": [0, -1, 0]}, {"kind": "plane", "dir": [0, 0, 1]}], "origin": 2}], "radius": 1, "chain": True, "visible": True}],
   [body(2, 1000 - 10 * (1 - math.pi / 4), "chain: a sharp corner stops tangent propagation, so one edge: 1000 − 10·(1 − π/4)")])
fx("chamfer, equal", [*box_40_20_10(), {"id": 3, "kind": "chamfer", "name": "Chamfer 3", "body": 2, "edges": [CORNER], "distance": 2, "chain": False, "visible": True}],
   [body(2, 8000 - 20, "8000 − L·d²/2, L 10, d 2")])
fx("chamfer, two distances", [*box_40_20_10(), {"id": 3, "kind": "chamfer", "name": "Chamfer 3", "body": 2, "edges": [CORNER], "distance": 2, "distance2": 3, "mode": "twoDistances", "chain": False, "visible": True}],
   [body(2, 8000 - 30, "8000 − L·d₁d₂/2, L 10")])
fx("chamfer, distance and angle", [*box_40_20_10(), {"id": 3, "kind": "chamfer", "name": "Chamfer 3", "body": 2, "edges": [CORNER], "distance": 2, "angleDeg": 30, "mode": "distanceAngle", "chain": False, "visible": True}],
   [body(2, 8000 - 10 * 2 * 2 * math.tan(math.radians(30)) / 2, "8000 − L·d·(d tan 30°)/2 on two square faces")])
fx("shell, closed", [*cube(), {"id": 3, "kind": "shell", "name": "Shell 3", "body": 2, "faces": [], "thickness": 1, "visible": True}], [body(2, 1000 - 512, "10³ − 8³")])
fx("shell, open at the top", [*cube(), {"id": 3, "kind": "shell", "name": "Shell 3", "body": 2, "faces": [TOP10], "thickness": 1, "visible": True}], [body(2, 1000 - 576, "10³ − 8·8·9")])
fx("hole from a point on the top, through", [*cube(), {"id": 3, "kind": "hole", "name": "Hole 3", "body": 2, "axis": {"kind": "point", "at": [5, 5, 10], "face": TOP10}, "radius": 2, "depth": None, "visible": True}],
   [body(2, 1000 - 40 * math.pi, "10³ − π·2²·10")])
fx("hole from a point, 4 deep", [*cube(), {"id": 3, "kind": "hole", "name": "Hole 3", "body": 2, "axis": {"kind": "point", "at": [5, 5, 10], "face": TOP10}, "radius": 2, "depth": 4, "visible": True}],
   [body(2, 1000 - 16 * math.pi, "10³ − π·2²·4")])
fx("cut by plane", [*box_40_20_10(), {"id": 3, "kind": "cutPlane", "name": "Cut 3", "body": 2, "plane": {"kind": "world", "axis": "x", "offset": 10}, "keep": 1, "visible": True}],
   [body(2, 6000, "30·20·10, the side the normal points to", box=[[10, 0, 0], [40, 20, 10]])])
fx("cut by plane, the other side", [*box_40_20_10(), {"id": 3, "kind": "cutPlane", "name": "Cut 3", "body": 2, "plane": {"kind": "world", "axis": "x", "offset": 10}, "keep": -1, "visible": True}],
   [body(2, 2000, "10·20·10")])
fx("mirror, joined", [*cube(), {"id": 3, "kind": "mirror", "name": "Mirror 3", "body": 2, "plane": {"kind": "world", "axis": "x", "offset": 0}, "join": True, "visible": True}],
   [body(2, 2000, "2·10³", box=[[-10, 0, 0], [10, 10, 10]])])
fx("mirror, apart", [*cube(), {"id": 3, "kind": "mirror", "name": "Mirror 3", "body": 2, "plane": {"kind": "world", "axis": "x", "offset": -5}, "join": False, "visible": True}],
   [body(2, 1000, "10³"), body(3, 1000, "10³, mirrored", box=[[-20, 0, 0], [-10, 10, 10]])])
fx("pattern, linear, apart", [*cube(), {"id": 3, "kind": "pattern", "name": "Pattern 3", "body": 2, "mode": "linear", "axis": {"kind": "world", "axis": "x"}, "count": 3, "step": 20, "visible": True}],
   [body(2, 1000, "10³"), body(3, 1000, "10³, a copy"), body(3 + 1 / 1024, 1000, "10³, a copy (island id)")])
fx("pattern, circular, overlapping", [rect(1, 0, -1, 10, 1), extrude(2, rect(1, 0, -1, 10, 1), dist(0, 2)),
                                      {"id": 3, "kind": "pattern", "name": "Pattern 3", "body": 2, "mode": "circular", "axis": {"kind": "world", "axis": "z"}, "count": 4, "step": 360, "visible": True}],
   [body(2, 4 * 40 - 4 * 2, "a cross of four 10·2·2 arms, each next two sharing a 1·1·2 corner: 4·40 − 4·2")])
fx("move body", [*cube(), {"id": 3, "kind": "moveBody", "name": "Move 3", "bodies": [2], "pivot": [5, 5, 5], "translate": [100, 0, 0], "rotate": [0, 0, 0], "copy": False, "visible": True}],
   [body(2, 1000, "10³", box=[[100, 0, 0], [110, 10, 10]])])
fx("move body, copy turned", [*cube(), {"id": 3, "kind": "moveBody", "name": "Move 3", "bodies": [2], "pivot": [0, 0, 0], "translate": [0, 0, 0], "rotate": [0, 0, 90], "copy": True, "visible": True}],
   [body(2, 1000, "10³"), body(3, 1000, "10³, turned 90° about Z through the origin", box=[[-10, 0, 0], [0, 10, 10]])])
fx("offset body, kept beside", [*cube(), {"id": 3, "kind": "offsetBody", "name": "Offset 3", "body": 2, "distance": 1, "keep": True, "visible": True}],
   [body(2, 1000, "10³"), body(3, 1000 + 600 + 30 * math.pi + 4 / 3 * math.pi, "Steiner: V + d·A + d²·π·Σedges/4·… = 1000 + 600 + 30π + 4π/3", rel=1e-4)])
fx("draft one wall", [*cube(), {"id": 3, "kind": "draft", "name": "Draft 3", "body": 2, "neutral": {"kind": "world", "axis": "z", "offset": 0}, "faces": [WALL_X10], "angleDeg": 5, "visible": True}],
   [body(2, 1000 - 500 * math.tan(math.radians(5)), "10³ − ½·10·(10 tan 5°)·10", rel=1e-4)], note="the scratch PartDesign::Draft's sense: a positive angle leans the wall in going along the pull")
fx("move face out", [*cube(), {"id": 3, "kind": "moveFace", "name": "Move face 3", "body": 2, "faces": [WALL_X10], "offset": 2, "visible": True}], [body(2, 1200, "10·10·12")])
fx("move face in", [*cube(), {"id": 3, "kind": "moveFace", "name": "Move face 3", "body": 2, "faces": [WALL_X10], "offset": -3, "visible": True}], [body(2, 700, "10·10·7")])
bore = circle(3, 5, 5, 2)
fx("delete a bore", [*cube(), bore, extrude(4, bore, dist(-1, 11), "cut"),
                     {"id": 5, "kind": "deleteFace", "name": "Delete face 5", "body": 2, "faces": [{"kind": "cylinder", "centroid": [5, 5, 5], "dir": [0, 0, 1], "area": 40 * math.pi, "radius": 2, "center": [5, 5, 5], "origin": 4}], "visible": True}],
   [body(2, 1000, "the bore filled again: 10³")])
boss = circle(1, 0, 0, 5)
fx("thread a boss, M10", [boss, extrude(2, boss, dist(0, 12)),
                          {"id": 3, "kind": "thread", "name": "Thread 3", "body": 2, "face": {"kind": "cylinder", "centroid": [0, 0, 6], "dir": [0, 0, 1], "area": 120 * math.pi, "radius": 5, "center": [0, 0, 6], "origin": 2},
                           "standard": "metric", "diameter": 10, "pitch": 1.5, "leftHanded": False, "length": None, "start": 0, "flip": False, "offset": 0, "visible": True}],
   [body(2, None, "between the minor cylinder π·(5 − h)²·12 and the boss π·5²·12, h = 5/8·(√3/2)·1.5",
         between=[math.pi * (5 - (5 / 8) * (math.sqrt(3) / 2) * 1.5) ** 2 * 12, 300 * math.pi])])
fx("suppressed features are left out", [*cube(), {"id": 3, "kind": "shell", "name": "Shell 3", "body": 2, "faces": [], "thickness": 1, "visible": True, "suppressed": True}], [body(2, 1000, "10³")],
   statuses={"2": "ok"})
fx("a lost pick fails loudly, the rest stands", [*cube(), {"id": 3, "kind": "fillet", "name": "Fillet 3", "body": 2, "edges": [vertical_edge(60, 60, 0, 10, [1, 0, 0], [0, 1, 0], 2)], "radius": 1, "chain": False, "visible": True},
                                                rect(4, 30, 0, 40, 10), extrude(5, rect(4, 30, 0, 40, 10), dist(0, 10))],
   [body(2, 1000, "10³, unrounded"), body(5, 1000, "10³, independent")], statuses={"2": "ok", "3": "failed", "5": "ok"})

s = rect(1, 0, 0, 10, 10)
fx("parameters drive the extrude", [s, extrude(2, s, dist(0, 8), exprs={"extent.to": "h * 2"})], [body(2, 1200, "10·10·(h·2), h 6")],
   parameters=[{"id": 1, "name": "h", "kind": "length", "expression": "6"}])

if __name__ == "__main__":
    out = os.path.join(ROOT, "tests", "reverse_fixtures", "kernel_builds.json")
    with open(out, "w", encoding="utf-8") as f:
        about = "Feature lists with volumes worked out by hand (tests/tools/make_reverse_kernel_fixtures.py); not goldens of the original's builder."
        f.write('{"about": ' + json.dumps(about, ensure_ascii=False) + ',\n "fixtures": [\n')
        f.write(",\n".join("  " + json.dumps(x, ensure_ascii=False, separators=(",", ":")) for x in FIXTURES))
        f.write("\n]}\n")
    print(f"{len(FIXTURES)} fixtures")
