# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/core/sketch.ts
# SPDX-License-Identifier: AGPL-3.0-only
#
# A sketch: pieces (lines, arcs, circles, splines, points) in the sketch
# plane's own u,v millimetres, and the relations and dimensions held between
# them. Plain dicts with the original's keys - a sketch is
# {"entities", "constraints", "nextId"} - so a sketch saved by the original
# reads here as it is and is written back the same. The solver
# (solver.py) moves the pieces to meet what is held; the regions they close
# (regions.py) are what an extrude takes.

import math

from ._js import clone, fmod, js_hypot
from .sketch_spline import is_closed, nearest_on_spline, spline_at, spline_curve, spline_end, spline_samples
from ..chainsegment import unwind_angle  # sketch.ts's unwindAngle, already ported with segment.ts

QUADRANTS = ("q0", "q1", "q2", "q3")
INFER_AXIS_DEG = 3
DIMENSION_KINDS = ("length", "distance", "radius", "diameter", "angle")
POLYGON_MAX_SIDES = 64
TOUCH_MM = 2e-3


def _is_quadrant(at):
    return at in QUADRANTS


# ---- 2D vectors (src/core/flat/vec2.ts) ------------------------------------------------


def add2(a, b):
    return [a[0] + b[0], a[1] + b[1]]


def sub2(a, b):
    return [a[0] - b[0], a[1] - b[1]]


def scale2(a, s):
    return [a[0] * s, a[1] * s]


def dot2(a, b):
    return a[0] * b[0] + a[1] * b[1]


def len2(a):
    return js_hypot(a[0], a[1])


def perp2(a):
    return [-a[1], a[0]]


def cross2(a, b):
    return a[0] * b[1] - a[1] * b[0]


def normalize2(a):
    ln = len2(a)
    if not (ln > 1e-12):
        return None
    return [a[0] / ln, a[1] / ln]


def signed_area2(poly):
    a = 0.0
    n = len(poly)
    for i in range(n):
        a += cross2(poly[i], poly[(i + 1) % n])
    return a / 2


# ---- the sketch -------------------------------------------------------------------------


def distance_along(p, q, axis=None):
    if axis == "x":
        return abs(q[0] - p[0])
    if axis == "y":
        return abs(q[1] - p[1])
    return len2(sub2(q, p))


def axis_relation_of(a, b, degrees=INFER_AXIS_DEG):
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    ln = js_hypot(dx, dy)
    if not (ln > 1e-9):
        return None
    limit = math.sin((degrees * math.pi) / 180)
    if abs(dy) / ln <= limit:
        return "horizontal"
    if abs(dx) / ln <= limit:
        return "vertical"
    return None


def is_dimension(c):
    return "value" in c


def fix_id(entity):
    return -1 - entity


def fixed_entity_of(i):
    return -1 - i if i < 0 else None


def fixed_pieces(sketch):
    return [e for e in sketch["entities"] if e.get("fixed") and not e.get("projected")]


def empty_sketch():
    return {"entities": [], "constraints": [], "nextId": 1}


def arc_point(arc, angle):
    return [arc["c"][0] + arc["r"] * math.cos(angle), arc["c"][1] + arc["r"] * math.sin(angle)]


def _anchor_index(at):
    if not isinstance(at, str) or len(at) < 2 or at[0] != "p":
        return None
    txt = at[1:]
    try:
        v = float(txt) if txt.strip() == txt and txt else math.nan
    except ValueError:
        return None
    if not math.isfinite(v) or v != int(v):
        return None
    return int(v)


def spline_point_index(e, at):
    n = len(e["pts"])
    closed = is_closed(e)
    if at == "a":
        return None if closed else 0
    if at == "b":
        return None if closed else n - 1
    if at == "center":
        return None
    i = _anchor_index(at)
    if i is None or i < 0 or i >= n:
        return None
    return i if closed or (0 < i < n - 1) else None


def spline_anchor(e, i):
    if not is_closed(e) and i == 0:
        return "a"
    if not is_closed(e) and i == len(e["pts"]) - 1:
        return "b"
    return f"p{i}"


def anchor_point(e, at):
    k = e["kind"]
    if k == "line":
        return e["b"] if at == "b" else e["a"] if at == "a" else [(e["a"][0] + e["b"][0]) / 2, (e["a"][1] + e["b"][1]) / 2]
    if k == "arc":
        if _is_quadrant(at):
            return arc_point(e, (int(at[1]) * math.pi) / 2)
        return arc_point(e, e["start"]) if at == "a" else arc_point(e, e["start"] + e["sweep"]) if at == "b" else e["c"]
    if k == "circle":
        return arc_point(e, (int(at[1]) * math.pi) / 2) if _is_quadrant(at) else e["c"]
    if k == "spline":
        i = spline_point_index(e, at)
        if i is not None:
            return e["pts"][i]
        fit = spline_curve(e)
        return spline_at(fit, spline_end(fit) / 2)
    return e["p"]


def anchors_of(e):
    if e["kind"] in ("line", "arc"):
        return ["a", "b"]
    if e["kind"] == "spline":
        if is_closed(e):
            return [f"p{i}" for i in range(len(e["pts"]))]
        return ["a", "b"] + [f"p{i + 1}" for i in range(len(e["pts"][1:-1]))]
    return ["center"]


def pick_points_of(e):
    if e["kind"] == "line":
        return ["center"]
    if e["kind"] == "circle":
        return list(QUADRANTS)
    if e["kind"] != "arc":
        return []
    out = ["center"]
    two = 2 * math.pi
    for q in QUADRANTS:
        along = fmod(fmod((int(q[1]) * math.pi) / 2 - e["start"], two) + two, two)
        if 1e-6 < along < e["sweep"] - 1e-6:
            out.append(q)
    return out


def ends_of(e):
    if e["kind"] in ("line", "arc"):
        return ["a", "b"]
    if e["kind"] == "spline" and not is_closed(e):
        return ["a", "b"]
    return []


def line_dir(line):
    return normalize2(sub2(line["b"], line["a"]))


def line_length(line):
    return len2(sub2(line["b"], line["a"]))


def _line_foot(line, p):
    ab = sub2(line["b"], line["a"])
    ll = dot2(ab, ab)
    t = dot2(sub2(p, line["a"]), ab) / ll if ll > 0 else 0
    return add2(line["a"], scale2(ab, t)), t


def arc_angle_of(arc, p):
    return math.atan2(p[1] - arc["c"][1], p[0] - arc["c"][0])


def nearest_on_entity(e, p):
    k = e["kind"]
    if k == "point":
        return {"point": e["p"], "dist": len2(sub2(p, e["p"]))}
    if k == "line":
        foot, t = _line_foot(e, p)
        clamped = e["a"] if t < 0 else e["b"] if t > 1 else foot
        return {"point": clamped, "dist": len2(sub2(p, clamped))}
    if k == "circle":
        d = normalize2(sub2(p, e["c"])) or [1, 0]
        point = add2(e["c"], scale2(d, e["r"]))
        return {"point": point, "dist": len2(sub2(p, point))}
    if k == "arc":
        angle = unwind_angle(arc_angle_of(e, p), e["start"])
        if angle - e["start"] <= e["sweep"]:
            point = arc_point(e, angle)
            return {"point": point, "dist": len2(sub2(p, point))}
        a = arc_point(e, e["start"])
        b = arc_point(e, e["start"] + e["sweep"])
        da = len2(sub2(p, a))
        db = len2(sub2(p, b))
        return {"point": a, "dist": da} if da <= db else {"point": b, "dist": db}
    near = nearest_on_spline(spline_curve(e), p)
    return {"point": near["point"], "dist": near["dist"]}


def entity_polyline(e, steps=96):
    k = e["kind"]
    if k == "point":
        return [e["p"]]
    if k == "line":
        return [e["a"], e["b"]]
    if k in ("circle", "arc"):
        start = e["start"] if k == "arc" else 0
        sweep = e["sweep"] if k == "arc" else 2 * math.pi
        n = max(2, math.ceil((steps * abs(sweep)) / (2 * math.pi)))
        return [arc_point(e, start + (sweep * i) / n) for i in range(n + 1)]
    return [s["p"] for s in spline_samples(spline_curve(e), max(4, int(math.floor(steps / 6 + 0.5))))]


def sketch_bounds(sketch):
    x0 = y0 = math.inf
    x1 = y1 = -math.inf
    for e in sketch["entities"]:
        pts = list(entity_polyline(e, 32))
        if e.get("points"):
            pts += e["points"]
        for p in pts:
            x0 = min(x0, p[0])
            x1 = max(x1, p[0])
            y0 = min(y0, p[1])
            y1 = max(y1, p[1])
    return {"min": [x0, y0], "max": [x1, y1]} if math.isfinite(x0) else None


def entity_of(sketch, i):
    for e in sketch["entities"]:
        if e["id"] == i:
            return e
    return None


def constraint_entities(c):
    k = c["kind"]
    if k in ("coincident", "symmetric"):
        ids = [c["p"]["entity"], c["q"]["entity"]]
        if k == "symmetric" and isinstance(c["about"], dict) and "line" in c["about"]:
            ids.append(c["about"]["line"])
        return ids
    if k in ("horizontal", "vertical", "length", "radius", "diameter"):
        return [c["entity"]]
    if k in ("parallel", "perpendicular", "tangent", "concentric", "equal", "angle"):
        return [c["a"], c["b"]]
    if k == "distance":
        q = c["q"]
        return [c["p"]["entity"]] if "datum" in q else [c["p"]["entity"], q["line"] if "line" in q else q["entity"]]
    if k == "pointOn":
        on = c["on"]
        return [c["p"]["entity"]] if "datum" in on else [c["p"]["entity"], on["line"] if "line" in on else on["curve"]]
    if k == "collinear":
        on = c["on"]
        return [c["line"]] if "datum" in on else [c["line"], on["line"]]
    return []


def spline_joint(sketch, spline, other):
    for c in sketch["constraints"]:
        if c["kind"] != "coincident":
            continue
        for mine, theirs in ((c["p"], c["q"]), (c["q"], c["p"])):
            if mine["entity"] == spline and theirs["entity"] == other and mine["at"] in ("a", "b") and theirs["at"] != "center":
                return {"end": mine["at"], "at": theirs["at"]}
    return None


def add_entity(sketch, entity):
    i = sketch["nextId"]
    sketch["nextId"] += 1
    e = {k: v for k, v in entity.items() if k != "id"}
    e["id"] = i
    sketch["entities"].append(e)
    return i


def add_constraint(sketch, constraint):
    i = sketch["nextId"]
    sketch["nextId"] += 1
    c = {k: v for k, v in constraint.items() if k != "id"}
    c["id"] = i
    sketch["constraints"].append(c)
    return i


def remove_entities(sketch, ids):
    gone = set(ids)
    sketch["entities"] = [e for e in sketch["entities"] if e["id"] not in gone]
    sketch["constraints"] = [c for c in sketch["constraints"] if not any(i in gone for i in constraint_entities(c))]


def remove_constraint(sketch, i):
    sketch["constraints"] = [c for c in sketch["constraints"] if c["id"] != i]


def relation_takes(kind, entities):
    kinds = [e["kind"] for e in entities]

    def round_(k):
        return k in ("arc", "circle")

    def curved(k):
        return round_(k) or k == "spline"

    n = len(entities)
    if kind in ("horizontal", "vertical"):
        return n >= 1 and all(k == "line" for k in kinds)
    if kind in ("parallel", "perpendicular", "angle"):
        return n == 2 and all(k == "line" for k in kinds)
    if kind == "tangent":
        return n == 2 and any(curved(k) for k in kinds) and all(k == "line" or curved(k) for k in kinds) and not ("circle" in kinds and "spline" in kinds)
    if kind == "concentric":
        return n == 2 and all(round_(k) for k in kinds)
    if kind == "equal":
        return n == 2 and (all(k == "line" for k in kinds) or all(round_(k) for k in kinds))
    if kind == "length":
        return n == 1 and kinds[0] == "line"
    if kind in ("radius", "diameter"):
        return n == 1 and round_(kinds[0])
    return False


def clone_sketch(sketch):
    """JSON.parse(JSON.stringify(sketch)): a deep copy, as plain data."""
    return clone(sketch)


def add_rectangle(sketch, p, q):
    x0 = min(p[0], q[0])
    x1 = max(p[0], q[0])
    y0 = min(p[1], q[1])
    y1 = max(p[1], q[1])
    corners = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    ids = [add_entity(sketch, {"kind": "line", "a": c, "b": corners[(i + 1) % 4]}) for i, c in enumerate(corners)]
    for i in range(4):
        add_constraint(sketch, {"kind": "coincident", "p": {"entity": ids[i], "at": "b"}, "q": {"entity": ids[(i + 1) % 4], "at": "a"}})
        add_constraint(sketch, {"kind": "horizontal" if i % 2 == 0 else "vertical", "entity": ids[i], "inferred": True})
    return ids


def add_turned_rectangle(sketch, corners):
    ids = [add_entity(sketch, {"kind": "line", "a": c, "b": corners[(i + 1) % 4]}) for i, c in enumerate(corners)]
    for i in range(4):
        add_constraint(sketch, {"kind": "coincident", "p": {"entity": ids[i], "at": "b"}, "q": {"entity": ids[(i + 1) % 4], "at": "a"}})
    axis = axis_relation_of(corners[0], corners[1])
    if axis:
        for i in range(4):
            even = i % 2 == 0
            add_constraint(sketch, {"kind": "horizontal" if even == (axis == "horizontal") else "vertical", "entity": ids[i], "inferred": True})
        return ids
    add_constraint(sketch, {"kind": "parallel", "a": ids[0], "b": ids[2]})
    add_constraint(sketch, {"kind": "parallel", "a": ids[1], "b": ids[3]})
    add_constraint(sketch, {"kind": "perpendicular", "a": ids[0], "b": ids[1]})
    return ids


def add_rectangle_centre(sketch, lines):
    def corner(i):
        e = entity_of(sketch, lines[i])
        return e["a"] if e and e["kind"] == "line" else [0, 0]

    diagonals = []
    for i, j in ((0, 2), (1, 3)):
        d = add_entity(sketch, {"kind": "line", "a": corner(i), "b": corner(j), "construction": True})
        add_constraint(sketch, {"kind": "coincident", "p": {"entity": d, "at": "a"}, "q": {"entity": lines[i], "at": "a"}})
        add_constraint(sketch, {"kind": "coincident", "p": {"entity": d, "at": "b"}, "q": {"entity": lines[j], "at": "a"}})
        diagonals.append(d)
    a = corner(0)
    b = corner(2)
    centre = add_entity(sketch, {"kind": "point", "p": [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2], "construction": True})
    for line in diagonals:
        add_constraint(sketch, {"kind": "pointOn", "p": {"entity": centre, "at": "center"}, "on": {"line": line}})
    return centre


def arc_through(p, q, r):
    ax, ay, bx, by, cx, cy = p[0], p[1], q[0], q[1], r[0], r[1]
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-9:
        return None
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
    c = [ux, uy]
    radius = js_hypot(ax - ux, ay - uy)
    theta_p = math.atan2(ay - uy, ax - ux)
    theta_q = math.atan2(by - uy, bx - ux)
    theta_r = math.atan2(cy - uy, cx - ux)
    two = 2 * math.pi
    ccw_pq = fmod(fmod(theta_q - theta_p, two) + two, two)
    ccw_pr = fmod(fmod(theta_r - theta_p, two) + two, two)
    if ccw_pr <= ccw_pq:
        return {"c": c, "r": radius, "start": theta_p, "sweep": ccw_pq, "startsAtP": True}
    return {"c": c, "r": radius, "start": theta_q, "sweep": two - ccw_pq, "startsAtP": False}


def polygon_corners(centre, at, sides, fit):
    n = int(math.floor(sides + 0.5))
    if not (3 <= n <= POLYGON_MAX_SIDES):
        return None
    d = sub2(at, centre)
    r = len2(d)
    if not (r > 1e-9):
        return None
    half = math.pi / n
    radius = r if fit == "inscribed" else r / math.cos(half)
    start = math.atan2(d[1], d[0]) - (0 if fit == "inscribed" else half)
    out = []
    for i in range(n):
        t = start + (2 * math.pi * i) / n
        out.append([centre[0] + radius * math.cos(t), centre[1] + radius * math.sin(t)])
    return out


def add_polygon(sketch, centre, at, sides, fit):
    corners = polygon_corners(centre, at, sides, fit)
    if not corners:
        return None
    n = len(corners)
    lines = [add_entity(sketch, {"kind": "line", "a": p, "b": corners[(i + 1) % n]}) for i, p in enumerate(corners)]
    rim = add_entity(sketch, {"kind": "circle", "c": [centre[0], centre[1]], "r": len2(sub2(corners[0], centre)), "construction": True})
    flats = add_entity(sketch, {"kind": "circle", "c": [centre[0], centre[1]], "r": len2(sub2(at, centre)), "construction": True}) if fit == "circumscribed" else None
    for i in range(n):
        add_constraint(sketch, {"kind": "coincident", "p": {"entity": lines[i], "at": "b"}, "q": {"entity": lines[(i + 1) % n], "at": "a"}})
        add_constraint(sketch, {"kind": "pointOn", "p": {"entity": lines[i], "at": "a"}, "on": {"curve": rim}})
        if i > 0:
            add_constraint(sketch, {"kind": "equal", "a": lines[0], "b": lines[i]})
    if flats is None:
        return {"lines": lines, "circle": rim, "rim": rim}
    add_constraint(sketch, {"kind": "concentric", "a": flats, "b": rim})
    add_constraint(sketch, {"kind": "tangent", "a": lines[0], "b": flats})
    return {"lines": lines, "circle": flats, "rim": rim}


def _pattern_placements(spec):
    out = []
    if spec["kind"] == "rectangular":
        n1 = max(1, int(math.floor(spec["count"] + 0.5)))
        n2 = max(1, int(math.floor((spec.get("count2") if spec.get("count2") is not None else 1) + 0.5))) if spec.get("step2") else 1
        for j in range(n2):
            for i in range(n1):
                if i == 0 and j == 0:
                    continue
                v = scale2(spec["step2"], j) if spec.get("step2") else [0, 0]
                out.append({"move": add2(scale2(spec["step"], i), v), "turn": 0, "about": [0, 0]})
        return out
    n = max(1, int(math.floor(spec["count"] + 0.5)))
    full = abs(abs(spec["angleDeg"]) - 360) < 1e-9
    step = (spec["angleDeg"] * math.pi) / 180 / (n if full else n - 1) if n > 1 else 0
    for i in range(1, n):
        out.append({"move": [0, 0], "turn": step * i, "about": spec["centre"]})
    return out


def _place_point(p, at):
    cos = math.cos(at["turn"])
    sin = math.sin(at["turn"])
    d = sub2(p, at["about"])
    return add2(add2(at["about"], [d[0] * cos - d[1] * sin, d[0] * sin + d[1] * cos]), at["move"])


def renumbered(c, new_id):
    cp = clone(c)
    for k in ("entity", "a", "b", "line"):
        if isinstance(cp.get(k), (int, float)) and not isinstance(cp.get(k), bool):
            cp[k] = new_id(cp[k])
    for k in ("p", "q", "on", "about"):
        v = cp.get(k)
        if not isinstance(v, dict):
            continue
        for key in ("entity", "line", "curve"):
            if v.get(key) is not None:
                v[key] = new_id(v[key])
    return cp


def pattern_pieces(sketch, ids, spec):
    chosen = set(ids)
    pieces = [e for e in sketch["entities"] if e["id"] in chosen]
    if not pieces:
        return []

    def inner_ok(c):
        if not all(i in chosen for i in constraint_entities(c)):
            return False
        if (c["kind"] == "distance" and "datum" in c["q"]) or (c["kind"] in ("pointOn", "collinear") and "datum" in c["on"]):
            return False
        if c["kind"] == "symmetric" and (not isinstance(c["about"], dict) or "datum" in c["about"]):
            return False
        return True

    inner = [c for c in sketch["constraints"] if inner_ok(c)]
    copies = []
    for at in _pattern_placements(spec):
        def place(p, at=at):
            return _place_point(p, at)

        mapping = {}
        for e in pieces:
            base = {"construction": True} if e.get("construction") else {}
            k = e["kind"]
            if k == "line":
                made = {"kind": "line", "a": place(e["a"]), "b": place(e["b"]), **base}
            elif k == "arc":
                made = {"kind": "arc", "c": place(e["c"]), "r": e["r"], "start": e["start"] + at["turn"], "sweep": e["sweep"], **base}
            elif k == "circle":
                made = {"kind": "circle", "c": place(e["c"]), "r": e["r"], **base}
            elif k == "spline":
                made = {"kind": "spline", "pts": [place(p) for p in e["pts"]]}
                if e.get("closed"):
                    made["closed"] = True
                if e.get("startDir") is not None:
                    made["startDir"] = e["startDir"] + at["turn"]
                if e.get("endDir") is not None:
                    made["endDir"] = e["endDir"] + at["turn"]
                made.update(base)
            else:
                made = {"kind": "point", "p": place(e["p"]), **base}
            mapping[e["id"]] = add_entity(sketch, made)

        def new_id(old, mapping=mapping):
            return mapping[old]

        q = at["turn"] / (math.pi / 2)
        quarters = ((int(math.floor(q + 0.5)) % 4) + 4) % 4 if abs(q - math.floor(q + 0.5)) < 1e-9 else None
        square = []
        for c in inner:
            rest = {k: v for k, v in c.items() if k not in ("id", "place")}
            if c["kind"] in ("horizontal", "vertical"):
                if quarters is None:
                    square.append(c)
                    continue
                if quarters % 2 == 1:
                    rest["kind"] = "vertical" if c["kind"] == "horizontal" else "horizontal"
            add_constraint(sketch, renumbered(rest, new_id))
        if square:
            first = square[0]
            for c in square[1:]:
                if c["entity"] == first["entity"]:
                    continue
                made = {"kind": "parallel" if c["kind"] == first["kind"] else "perpendicular", "a": new_id(first["entity"]), "b": new_id(c["entity"])}
                if c.get("inferred"):
                    made["inferred"] = True
                add_constraint(sketch, made)
        copies.append([new_id(e["id"]) for e in pieces])
    return copies


def infer_relations(sketch, pieces=None, shaped=None):
    """Coincidences where ends touch, and horizontal or vertical on lines
    that run so to a hair: the relations a sketch drawn with them implies."""
    ends = []
    for e in sketch["entities"]:
        for at in ends_of(e):
            ends.append(({"entity": e["id"], "at": at}, anchor_point(e, at)))

    def key(a):
        return f"{a['entity']}:{a['at']}"

    parent = {}

    def find(k):
        r = k
        while r in parent and parent[r] != r:
            r = parent[r]
        parent[k] = r
        return r

    for c in sketch["constraints"]:
        if c["kind"] == "coincident":
            parent[find(key(c["p"]))] = find(key(c["q"]))
    size = TOUCH_MM * 4
    grid = {}
    for i, (_a, p) in enumerate(ends):
        grid.setdefault((math.floor(p[0] / size), math.floor(p[1] / size)), []).append(i)
    added = 0
    for i, (ea, ep) in enumerate(ends):
        cx = math.floor(ep[0] / size)
        cy = math.floor(ep[1] / size)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in grid.get((cx + dx, cy + dy), ()):
                    if j <= i:
                        continue
                    fa, fp = ends[j]
                    if fa["entity"] == ea["entity"]:
                        continue
                    if pieces is not None and ea["entity"] not in pieces and fa["entity"] not in pieces:
                        continue
                    if len2(sub2(ep, fp)) > TOUCH_MM:
                        continue
                    if find(key(ea)) == find(key(fa)):
                        continue
                    add_constraint(sketch, {"kind": "coincident", "p": ea, "q": fa, "inferred": True})
                    parent[find(key(ea))] = find(key(fa))
                    added += 1
    for e in sketch["entities"]:
        if e["kind"] != "line" or e.get("construction") or (pieces is not None and e["id"] not in pieces) or (shaped is not None and e["id"] in shaped):
            continue
        if any(c["kind"] in ("horizontal", "vertical") and c.get("entity") == e["id"] for c in sketch["constraints"]):
            continue
        axis = axis_relation_of(e["a"], e["b"], 1e-6)
        if not axis:
            continue
        add_constraint(sketch, {"kind": axis, "entity": e["id"], "inferred": True})
        added += 1
    return added

