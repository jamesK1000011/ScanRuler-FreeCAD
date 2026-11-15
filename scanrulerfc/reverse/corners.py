# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/core/corners.ts
# SPDX-License-Identifier: AGPL-3.0-only
#
# Corners inferred, and a profile closed. Fitted pieces never meet by
# themselves: every fit stops short of the blend, a sharp corner needs its
# two lines carried on to their intersection, a fillet needs its arc's ends
# put exactly on the sides it joins, and the outer-skin trace of a thin wall
# has to be closed across the wall's end. So the pieces of a chain are
# walked in order, and wherever two neighbouring ends lie within the gap a
# corner is allowed, they are brought to one point and held there with a
# coincidence, plus a tangency where a line meets an arc it runs into, or
# two arcs blend. What is left open after that is the operator's to close:
# the Close command bridges the remaining gaps, carrying two lines on to
# their intersection where they have one and drawing a straight bridge
# where they have not.

import math

from ..chainsegment import unwind_angle
from .sketch import (TOUCH_MM, add2, add_constraint, add_entity, anchor_point, arc_angle_of, constraint_entities, cross2, dot2, entity_of, len2,
                     nearest_on_entity, normalize2, perp2, scale2, sub2)

CORNER_GAP_MM = 2
TANGENT_SHARE = 0.5
TANGENT_DEG = 20
TANGENT_COS = math.cos((TANGENT_DEG * math.pi) / 180)
PARALLEL_DEG = 5
REACH_GAPS = 4
JOINED_MISS_MM = 1


def _tangent_slack(r, scatter, tol):
    return min(tol, max(r * (1 - TANGENT_COS), 2 * scatter))


def _nearest_sweep(raw, had):
    two = 2 * math.pi
    best = raw
    best_d = math.inf
    for c in (raw, raw + two, raw - two):
        if not (c > 1e-6 and c <= two + 1e-9):
            continue
        d = abs(c - had)
        if d < best_d:
            best_d = d
            best = c
    return best


def _set_arc_end(arc, at, angle):
    if at == "a":
        end = arc["start"] + arc["sweep"]
        raw = unwind_angle(end, angle) - angle
        arc["start"] = angle
        arc["sweep"] = _nearest_sweep(raw, arc["sweep"])
    else:
        raw = unwind_angle(angle, arc["start"]) - arc["start"]
        arc["sweep"] = _nearest_sweep(raw, arc["sweep"])


def _move_anchor(e, at, p):
    if e["kind"] == "line":
        e["a" if at == "a" else "b"] = [p[0], p[1]]
    elif e["kind"] == "arc":
        _set_arc_end(e, at, arc_angle_of(e, p))
    elif e["kind"] == "point":
        e["p"] = [p[0], p[1]]


def line_intersection(a, b):
    """Where two lines' carriers cross, or None when parallel."""
    da = sub2(a["b"], a["a"])
    db = sub2(b["b"], b["a"])
    denom = cross2(da, db)
    la = len2(da)
    lb = len2(db)
    if la < 1e-12 or lb < 1e-12:
        return None
    if abs(denom) / (la * lb) < math.sin((PARALLEL_DEG * math.pi) / 180):
        return None
    t = cross2(sub2(b["a"], a["a"]), db) / denom
    return add2(a["a"], scale2(da, t))


def _line_circle(l, c, r):
    d = normalize2(sub2(l["b"], l["a"]))
    if not d:
        return []
    off = dot2(sub2(c, l["a"]), perp2(d))
    if abs(off) > r:
        return []
    foot = add2(l["a"], scale2(d, dot2(sub2(c, l["a"]), d)))
    h = math.sqrt(max(0, r * r - off * off))
    return [foot] if h < 1e-9 else [add2(foot, scale2(d, h)), add2(foot, scale2(d, -h))]


def _circle_circle(c1, r1, c2, r2):
    d = len2(sub2(c2, c1))
    if d < 1e-9 or d > r1 + r2 or d < abs(r1 - r2):
        return []
    a = (r1 * r1 - r2 * r2 + d * d) / (2 * d)
    h = math.sqrt(max(0, r1 * r1 - a * a))
    u = scale2(sub2(c2, c1), 1 / d)
    foot = add2(c1, scale2(u, a))
    n = perp2(u)
    return [foot] if h < 1e-9 else [add2(foot, scale2(n, h)), add2(foot, scale2(n, -h))]


def _nearest_to(candidates, p):
    best = None
    best_d = math.inf
    for c in candidates:
        d = len2(sub2(c, p))
        if d < best_d:
            best_d = d
            best = c
    return best


def _tangent_point(l, arc, tol):
    d = normalize2(sub2(l["b"], l["a"]))
    if not d:
        return None
    off = dot2(sub2(arc["c"], l["a"]), perp2(d))
    slack = _tangent_slack(arc["r"], max(arc.get("scatter") or 0, l.get("scatter") or 0), tol)
    if abs(abs(off) - arc["r"]) > slack:
        return None
    return add2(l["a"], scale2(d, dot2(sub2(arc["c"], l["a"]), d)))


def _arcs_tangent_point(a, b, tol):
    d = len2(sub2(b["c"], a["c"]))
    if d < 1e-9:
        return None
    u = scale2(sub2(b["c"], a["c"]), 1 / d)
    slack = _tangent_slack(min(a["r"], b["r"]), max(a.get("scatter") or 0, b.get("scatter") or 0), tol)
    if abs(d - (a["r"] + b["r"])) <= slack:
        return add2(a["c"], scale2(u, a["r"]))
    if abs(d - abs(a["r"] - b["r"])) <= slack:
        return add2(a["c"], scale2(u, a["r"])) if a["r"] >= b["r"] else add2(a["c"], scale2(u, -a["r"]))
    return None


def join_ends(sketch, p, q, gap):
    """Bring two ends to one point and hold them with a coincidence, plus a
    tangency where one was found. Returns whether a tangency was added."""
    ea = entity_of(sketch, p["entity"])
    eb = entity_of(sketch, q["entity"])
    if not ea or not eb:
        return False
    pa = anchor_point(ea, p["at"])
    pb = anchor_point(eb, q["at"])
    mid = [(pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2]
    reach = max(REACH_GAPS * gap, len2(sub2(pa, pb)) * 2)

    def within(x):
        return x is not None and len2(sub2(x, pa)) <= reach and len2(sub2(x, pb)) <= reach

    meet = mid
    tangent = False
    tan_tol = gap * TANGENT_SHARE
    ka, kb = ea["kind"], eb["kind"]
    if ka == "line" and kb == "line":
        x = line_intersection(ea, eb)
        if within(x):
            meet = x
    elif (ka == "line" and kb == "arc") or (ka == "arc" and kb == "line"):
        line = ea if ka == "line" else eb
        arc = ea if ka == "arc" else eb
        t = _tangent_point(line, arc, tan_tol)
        if t and within(t):
            meet = t
            tangent = True
        else:
            x = _nearest_to(_line_circle(line, arc["c"], arc["r"]), mid)
            if within(x):
                meet = x
    elif ka == "arc" and kb == "arc":
        t = _arcs_tangent_point(ea, eb, tan_tol)
        if t and within(t):
            meet = t
            tangent = True
        else:
            x = _nearest_to(_circle_circle(ea["c"], ea["r"], eb["c"], eb["r"]), mid)
            if within(x):
                meet = x
    _move_anchor(ea, p["at"], meet)
    _move_anchor(eb, q["at"], meet)
    add_constraint(sketch, {"kind": "coincident", "p": p, "q": q})
    if tangent:
        add_constraint(sketch, {"kind": "tangent", "a": p["entity"], "b": q["entity"]})
    return tangent


def _consecutive(order, closed):
    pairs = []
    count = len(order) if closed else len(order) - 1
    for i in range(count):
        cur = order[i]
        nxt = order[(i + 1) % len(order)]
        if len(order) == 1 and not closed:
            break
        pairs.append(({"entity": cur["id"], "at": cur["to"]}, {"entity": nxt["id"], "at": nxt["from"]}, cur.get("joinNext") is True))
    return pairs


def _gap_of(sketch, p, q):
    ea = entity_of(sketch, p["entity"])
    eb = entity_of(sketch, q["entity"])
    if not ea or not eb:
        return math.inf
    return len2(sub2(anchor_point(ea, p["at"]), anchor_point(eb, q["at"])))


def _same_anchor(a, b):
    return a["entity"] == b["entity"] and a["at"] == b["at"]


def _already_joined(sketch, p, q):
    return any(c["kind"] == "coincident" and ((_same_anchor(c["p"], p) and _same_anchor(c["q"], q)) or (_same_anchor(c["q"], p) and _same_anchor(c["p"], q)))
               for c in sketch["constraints"])


def infer_corners(sketch, order, closed, gap=CORNER_GAP_MM):
    """Join every pair of neighbouring ends within `gap` of each other, and
    every pair the segmentation dropped a piece between. A single arc round
    a closed chain becomes a circle."""
    report = {"joined": 0, "tangent": 0, "open": 0}
    if len(order) == 1 and closed:
        e = entity_of(sketch, order[0]["id"])
        if e and e["kind"] == "arc":
            idx = next(i for i, x in enumerate(sketch["entities"]) if x["id"] == e["id"])
            circle = {"id": e["id"], "kind": "circle", "c": e["c"], "r": e["r"]}
            for k in ("points", "scatter"):
                if e.get(k) is not None:
                    circle[k] = e[k]
            sketch["entities"][idx] = circle
            report["joined"] = 1
        return report
    for p, q, corner in _consecutive(order, closed):
        if _already_joined(sketch, p, q):
            continue
        apart = _gap_of(sketch, p, q)
        if apart <= gap or (corner and math.isfinite(apart)):
            if join_ends(sketch, p, q, max(gap, apart)):
                report["tangent"] += 1
            report["joined"] += 1
        else:
            report["open"] += 1
    return report


def _ahead(l, at, x):
    frm = l["b"] if at == "a" else l["a"]
    to = l["a"] if at == "a" else l["b"]
    d = sub2(to, frm)
    ll = dot2(d, d)
    if ll < 1e-12:
        return True
    return dot2(sub2(x, frm), d) / ll >= 0.5


def close_chain(sketch, order, gap=CORNER_GAP_MM):
    """Bridge every gap corner inference left open, the chain's two ends
    too. Returns how many gaps were closed."""
    if not order:
        return 0
    closed_gaps = 0
    for p, q, _ in _consecutive(order, True):
        if _already_joined(sketch, p, q):
            continue
        ea = entity_of(sketch, p["entity"])
        eb = entity_of(sketch, q["entity"])
        if not ea or not eb:
            continue
        pa = anchor_point(ea, p["at"])
        pb = anchor_point(eb, q["at"])
        if len2(sub2(pa, pb)) <= gap:
            join_ends(sketch, p, q, gap)
            closed_gaps += 1
            continue
        if ea["kind"] == "line" and eb["kind"] == "line":
            x = line_intersection(ea, eb)
            if x and _ahead(ea, p["at"], x) and _ahead(eb, q["at"], x):
                _move_anchor(ea, p["at"], x)
                _move_anchor(eb, q["at"], x)
                add_constraint(sketch, {"kind": "coincident", "p": p, "q": q})
                closed_gaps += 1
                continue
        i = add_entity(sketch, {"kind": "line", "a": pa, "b": pb})
        add_constraint(sketch, {"kind": "coincident", "p": p, "q": {"entity": i, "at": "a"}})
        add_constraint(sketch, {"kind": "coincident", "p": {"entity": i, "at": "b"}, "q": q})
        closed_gaps += 1
    return closed_gaps


def sharpen_corner(sketch, arc_id):
    """Take out the fillet arc (or chamfer line) between two lines and carry
    the lines on to their intersection. False when it does not stand
    between two lines that cross."""
    arc = entity_of(sketch, arc_id)
    if not arc or arc["kind"] not in ("arc", "line"):
        return False

    def neighbour(at):
        for c in sketch["constraints"]:
            if c["kind"] != "coincident":
                continue
            other = c["q"] if c["p"]["entity"] == arc_id and c["p"]["at"] == at else c["p"] if c["q"]["entity"] == arc_id and c["q"]["at"] == at else None
            if not other:
                continue
            e = entity_of(sketch, other["entity"])
            if e and e["kind"] == "line":
                return e, other["at"]
        return None

    na = neighbour("a")
    nb = neighbour("b")
    if not na or not nb or na[0]["id"] == nb[0]["id"]:
        return False
    x = line_intersection(na[0], nb[0])
    if not x:
        return False
    _move_anchor(na[0], na[1], x)
    _move_anchor(nb[0], nb[1], x)
    sketch["entities"] = [e for e in sketch["entities"] if e["id"] != arc_id]
    sketch["constraints"] = [c for c in sketch["constraints"] if arc_id not in constraint_entities(c)]
    add_constraint(sketch, {"kind": "coincident", "p": {"entity": na[0]["id"], "at": na[1]}, "q": {"entity": nb[0]["id"], "at": nb[1]}})
    return True


def open_ends(sketch, touch=TOUCH_MM):
    """The ends of a sketch's outline that meet nothing, each with the end
    of another piece nearest it and the gap, the smallest gaps first."""
    outline = [e for e in sketch["entities"] if not e.get("construction") and e["kind"] != "point"]
    ends = [{"piece": e["id"], "end": end, "at": anchor_point(e, end)} for e in outline if e["kind"] in ("line", "arc") for end in ("a", "b")]

    def meets(p):
        return (any(q is not p and len2(sub2(q["at"], p["at"])) <= touch for q in ends)
                or any(e["id"] != p["piece"] and nearest_on_entity(e, p["at"])["dist"] <= touch for e in outline))

    out = []
    for p in ends:
        if meets(p):
            continue
        nearest = None
        gap = math.inf
        for q in ends:
            if q["piece"] == p["piece"]:
                continue
            d = len2(sub2(q["at"], p["at"]))
            if d > JOINED_MISS_MM and meets(q):
                continue
            if d < gap:
                gap = d
                nearest = q
        out.append({"piece": p["piece"], "end": p["end"], "at": p["at"], "nearest": nearest and {"piece": nearest["piece"], "end": nearest["end"]},
                    "gap": gap if nearest else None})
    out.sort(key=lambda o: math.inf if o["gap"] is None else o["gap"])
    return out


def place_segments(sketch, cut):
    """segment.ts placeSegments: each segment of a cut chain added to the
    sketch as its line or arc (its run's points and the cut's scatter kept
    as soft data), with the ends it runs from and to; the geometry is
    chainsegment.place_segments' own."""
    out = []
    for seg in cut["segments"]:
        join = {"joinNext": True} if seg.get("cornerAfter") else {}
        pts = [[float(p[0]), float(p[1])] for p in seg["points"]]
        first, last = pts[0], pts[-1]
        fit = seg["fit"]
        if seg["kind"] == "line":
            c = [float(x) for x in fit["center"]]
            d = [float(x) for x in fit["dir"]]

            def project(p):
                t = (p[0] - c[0]) * d[0] + (p[1] - c[1]) * d[1]
                return [c[0] + d[0] * t, c[1] + d[1] * t]

            i = add_entity(sketch, {"kind": "line", "a": project(first), "b": project(last), "points": pts, "scatter": cut["scatter"]})
            out.append({"id": i, "from": "a", "to": "b", **join})
            continue
        c = [float(x) for x in fit["center"]]

        def angle_of(p):
            return math.atan2(p[1] - c[1], p[0] - c[0])

        ta, tb, tm = angle_of(first), angle_of(last), angle_of(pts[len(pts) >> 1])
        ccw_sweep = unwind_angle(tb, ta) - ta
        ccw = unwind_angle(tm, ta) - ta <= ccw_sweep
        start, sweep = (ta, ccw_sweep if ccw_sweep > 1e-9 else 2 * math.pi) if ccw else (tb, 2 * math.pi - ccw_sweep)
        i = add_entity(sketch, {"kind": "arc", "c": c, "r": float(fit["radius"]), "start": start, "sweep": sweep, "points": pts, "scatter": cut["scatter"]})
        out.append({"id": i, "from": "a", "to": "b", **join} if ccw else {"id": i, "from": "b", "to": "a", **join})
    return out
