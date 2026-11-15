# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/core/regions.ts
# SPDX-License-Identifier: AGPL-3.0-only
#
# The closed regions of a sketch: its pieces (construction left out) cut
# where they cross or touch into a planar graph, its dangling edges pruned,
# its faces traced by the next edge clockwise at every vertex. A face of
# positive area is a region; an outer loop of a component inside one is a
# hole of the smallest that holds it. Each region has a stable key, the ids
# of the pieces round its outside and its middle to a hundredth of a
# millimetre, so a pick names the same region after the sketch is edited
# and a key that no longer matches exactly is matched by its pieces and its
# place (matchRegion).

import math

from ._js import fmod, js_round, to_fixed
from .sketch import arc_point, cross2, len2, signed_area2, sub2
from .sketch_spline import is_closed, nearest_on_spline, spline_at, spline_curve, spline_deriv_at, spline_end, spline_samples, spline_stretch

ARC_SAMPLES_PER_TURN = 72
SPLINE_SAMPLES_PER_SEGMENT = 16
SNAP = 2e-3
TOUCH_HAIR = 1e-4
TURN = 2 * math.pi
PLACE_SAMPLES = 24
GREW_SHARE = 0.01


def _turn_mod(x):
    return fmod(fmod(x, TURN) + TURN, TURN)


# ---- curves ------------------------------------------------------------------------------
# A curve is a dict: {"kind": "line", entity, a, b} / {"kind": "arc", entity, c, r, t0, sweep}
# / {"kind": "spline", entity, fit, end}.


def _curves_of(sketch):
    out = []
    for e in sketch["entities"]:
        if e.get("construction"):
            continue
        k = e["kind"]
        if k == "line":
            if len2(sub2(e["b"], e["a"])) > SNAP:
                out.append({"kind": "line", "entity": e["id"], "a": e["a"], "b": e["b"]})
        elif k in ("arc", "circle"):
            t0 = e["start"] if k == "arc" else 0
            sweep = min(abs(e["sweep"]), TURN) if k == "arc" else TURN
            out.append({"kind": "arc", "entity": e["id"], "c": e["c"], "r": e["r"], "t0": t0, "sweep": sweep})
        elif k == "spline" and len(e["pts"]) >= 2:
            fit = spline_curve(e)
            if fit["length"] > SNAP:
                out.append({"kind": "spline", "entity": e["id"], "fit": fit, "end": spline_end(fit)})
    _align_collinear([c for c in out if c["kind"] == "line"])
    return out


def _align_collinear(curves):
    lines = sorted(curves, key=lambda c: -len2(sub2(c["b"], c["a"])))
    for i, a in enumerate(lines):
        d = sub2(a["b"], a["a"])
        ln = len2(d)
        if ln <= SNAP:
            continue
        u = [d[0] / ln, d[1] / ln]
        for b in lines[i + 1:]:
            w0 = sub2(b["a"], a["a"])
            w1 = sub2(b["b"], a["a"])
            if abs(cross2(u, w0)) > SNAP or abs(cross2(u, w1)) > SNAP:
                continue
            s0 = w0[0] * u[0] + w0[1] * u[1]
            s1 = w1[0] * u[0] + w1[1] * u[1]
            if max(s0, s1) < -SNAP or min(s0, s1) > ln + SNAP:
                continue
            overlap = min(max(s0, s1), ln) - max(min(s0, s1), 0)
            if overlap <= SNAP and (abs(cross2(u, w0)) > TOUCH_HAIR or abs(cross2(u, w1)) > TOUCH_HAIR):
                continue
            b["a"] = [a["a"][0] + u[0] * s0, a["a"][1] + u[1] * s0]
            b["b"] = [a["a"][0] + u[0] * s1, a["a"][1] + u[1] * s1]


def _point_at(c, t):
    if c["kind"] == "spline":
        return spline_at(c["fit"], t)
    if c["kind"] == "line":
        return [c["a"][0] + (c["b"][0] - c["a"][0]) * t, c["a"][1] + (c["b"][1] - c["a"][1]) * t]
    return arc_point(c, t)


def _deriv_at(c, t):
    if c["kind"] == "spline":
        return spline_deriv_at(c["fit"], t)
    if c["kind"] == "line":
        return sub2(c["b"], c["a"])
    return [-c["r"] * math.sin(t), c["r"] * math.cos(t)]


def _ends_of(c):
    if c["kind"] == "line":
        return [c["a"], c["b"]]
    if c["kind"] == "spline":
        return [] if c["fit"]["closed"] else [spline_at(c["fit"], 0), spline_at(c["fit"], c["end"])]
    return [] if c["sweep"] >= TURN else [arc_point(c, c["t0"]), arc_point(c, c["t0"] + c["sweep"])]


def _param_on(c, p, interior):
    if c["kind"] == "line":
        d = sub2(c["b"], c["a"])
        ln = len2(d)
        w = sub2(p, c["a"])
        if abs(cross2(d, w)) / ln > SNAP:
            return None
        t = (w[0] * d[0] + w[1] * d[1]) / (ln * ln)
        if abs(t) * ln <= SNAP:
            return None if interior else 0
        if abs(1 - t) * ln <= SNAP:
            return None if interior else 1
        return t if 0 < t < 1 else None
    if c["kind"] == "spline":
        near = nearest_on_spline(c["fit"], p, 8)
        if near["dist"] > SNAP:
            return None
        if not c["fit"]["closed"]:
            if len2(sub2(p, spline_at(c["fit"], 0))) <= SNAP:
                return None if interior else 0
            if len2(sub2(p, spline_at(c["fit"], c["end"]))) <= SNAP:
                return None if interior else c["end"]
        return near["t"]
    w = sub2(p, c["c"])
    if abs(len2(w) - c["r"]) > SNAP:
        return None
    rel = _turn_mod(math.atan2(w[1], w[0]) - c["t0"])
    if c["sweep"] >= TURN:
        return c["t0"] + rel
    if min(rel, TURN - rel) * c["r"] <= SNAP:
        return None if interior else c["t0"]
    if abs(c["sweep"] - rel) * c["r"] <= SNAP:
        return None if interior else c["t0"] + c["sweep"]
    return c["t0"] + rel if rel < c["sweep"] else None


def _line_meets_circle(l, c):
    d = sub2(l["b"], l["a"])
    ln = len2(d)
    u = [d[0] / ln, d[1] / ln]
    w = sub2(c["c"], l["a"])
    s = w[0] * u[0] + w[1] * u[1]
    h = abs(cross2(u, w))
    if abs(h - c["r"]) <= SNAP:
        return [[l["a"][0] + u[0] * s, l["a"][1] + u[1] * s]]
    if h > c["r"]:
        return []
    k = math.sqrt(c["r"] * c["r"] - h * h)
    return [[l["a"][0] + u[0] * (s - k), l["a"][1] + u[1] * (s - k)], [l["a"][0] + u[0] * (s + k), l["a"][1] + u[1] * (s + k)]]


def _circle_meets_circle(p, q):
    v = sub2(q["c"], p["c"])
    d = len2(v)
    if d <= SNAP:
        return []
    u = [v[0] / d, v[1] / d]

    def at(x, y):
        return [p["c"][0] + u[0] * x - u[1] * y, p["c"][1] + u[1] * x + u[0] * y]

    if abs(d - (p["r"] + q["r"])) <= SNAP:
        return [at(p["r"], 0)]
    if abs(d - abs(p["r"] - q["r"])) <= SNAP:
        return [at(p["r"] if p["r"] >= q["r"] else -p["r"], 0)]
    if d > p["r"] + q["r"] or d < abs(p["r"] - q["r"]):
        return []
    x = (d * d + p["r"] * p["r"] - q["r"] * q["r"]) / (2 * d)
    y = math.sqrt(max(0, p["r"] * p["r"] - x * x))
    return [at(x, y), at(x, -y)]


def _curve_meetings(a, b):
    sa = [(t, _point_at(a, t)) for t in _grid_of(a)]
    sb = [(t, _point_at(b, t)) for t in _grid_of(b)]
    out = []
    for i in range(len(sa) - 1):
        p0 = sa[i][1]
        p1 = sa[i + 1][1]
        da = sub2(p1, p0)
        for j in range(len(sb) - 1):
            q0 = sb[j][1]
            q1 = sb[j + 1][1]
            if max(q0[0], q1[0]) < min(p0[0], p1[0]) - SNAP or min(q0[0], q1[0]) > max(p0[0], p1[0]) + SNAP:
                continue
            if max(q0[1], q1[1]) < min(p0[1], p1[1]) - SNAP or min(q0[1], q1[1]) > max(p0[1], p1[1]) + SNAP:
                continue
            db = sub2(q1, q0)
            denom = cross2(da, db)
            if abs(denom) <= 1e-18:
                continue
            w = sub2(q0, p0)
            s = cross2(w, db) / denom
            u = cross2(w, da) / denom
            if s < -0.25 or s > 1.25 or u < -0.25 or u > 1.25:
                continue
            ta = sa[i][0] + (sa[i + 1][0] - sa[i][0]) * min(max(s, 0), 1)
            tb = sb[j][0] + (sb[j + 1][0] - sb[j][0]) * min(max(u, 0), 1)
            for _ in range(12):
                f = sub2(_point_at(a, ta), _point_at(b, tb))
                if len2(f) < 1e-12:
                    break
                ja = _deriv_at(a, ta)
                jb = _deriv_at(b, tb)
                det = -ja[0] * jb[1] + jb[0] * ja[1]
                if abs(det) < 1e-18:
                    break
                ta += (f[0] * jb[1] - jb[0] * f[1]) / det
                tb += (ja[0] * f[1] - f[0] * ja[1]) / det
            at = _point_at(a, ta)
            if len2(sub2(at, _point_at(b, tb))) > SNAP / 10:
                continue
            pa = _param_on(a, at, False)
            pb = _param_on(b, at, False)
            if pa is None or pb is None:
                continue
            if any(len2(sub2(_point_at(a, x), at)) <= SNAP for x, _y in out):
                continue
            out.append((pa, pb))
    return out


def _meetings(a, b):
    if a["kind"] == "spline" or b["kind"] == "spline":
        return _curve_meetings(a, b)
    if a["kind"] == "line" and b["kind"] == "line":
        da = sub2(a["b"], a["a"])
        db = sub2(b["b"], b["a"])
        denom = cross2(da, db)
        if abs(denom) <= 1e-12 * len2(da) * len2(db):
            return []
        s = cross2(sub2(b["a"], a["a"]), db) / denom
        points = [[a["a"][0] + da[0] * s, a["a"][1] + da[1] * s]]
    elif a["kind"] == "line" and b["kind"] == "arc":
        points = _line_meets_circle(a, b)
    elif a["kind"] == "arc" and b["kind"] == "line":
        points = _line_meets_circle(b, a)
    else:
        points = _circle_meets_circle(a, b)
    out = []
    for p in points:
        ta = _param_on(a, p, False)
        tb = _param_on(b, p, False)
        if ta is not None and tb is not None:
            out.append((ta, tb))
    return out


def _box_of(c):
    if c["kind"] == "arc":
        return (c["c"][0] - c["r"] - SNAP, c["c"][1] - c["r"] - SNAP, c["c"][0] + c["r"] + SNAP, c["c"][1] + c["r"] + SNAP)
    if c["kind"] == "spline":
        pts = [s["p"] for s in spline_samples(c["fit"], SPLINE_SAMPLES_PER_SEGMENT)]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        pad = SNAP + 0.01 * c["fit"]["length"]
        return (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)
    return (min(c["a"][0], c["b"][0]) - SNAP, min(c["a"][1], c["b"][1]) - SNAP, max(c["a"][0], c["b"][0]) + SNAP, max(c["a"][1], c["b"][1]) + SNAP)


def _grid_of(c):
    if c["kind"] == "line":
        return [0, 1]
    if c["kind"] == "spline":
        return [s["t"] for s in spline_samples(c["fit"], SPLINE_SAMPLES_PER_SEGMENT)]
    n = max(4, math.ceil((ARC_SAMPLES_PER_TURN * c["sweep"]) / TURN))
    return [c["t0"] + c["sweep"] if i == n else c["t0"] + (c["sweep"] * i) / n for i in range(n + 1)]


def _leaving(c, t, forward):
    if c["kind"] == "line":
        d = sub2(c["b"], c["a"]) if forward else sub2(c["a"], c["b"])
        return math.atan2(d[1], d[0])
    if c["kind"] == "spline":
        speed = max(len2(spline_deriv_at(c["fit"], t)), 1e-9)
        step = (1 if forward else -1) * (SNAP / speed)
        d = sub2(spline_at(c["fit"], t + step), spline_at(c["fit"], t))
        return math.atan2(d[1], d[0])
    bend = SNAP / (2 * c["r"])
    angle = t + math.pi / 2 + bend if forward else t - math.pi / 2 - bend
    return math.atan2(math.sin(angle), math.cos(angle))


def _uniq_sorted(ts):
    seen = []
    for t in ts:
        if t not in seen:
            seen.append(t)
    return sorted(seen)


def _build_graph(curves):
    splits = [list(_grid_of(c)) for c in curves]
    boxes = [_box_of(c) for c in curves]
    for i, a in enumerate(curves):
        ax0, ay0, ax1, ay1 = boxes[i]
        for j in range(i + 1, len(curves)):
            b = curves[j]
            bx0, by0, bx1, by1 = boxes[j]
            if bx1 < ax0 or bx0 > ax1 or by1 < ay0 or by0 > ay1:
                continue
            for ta, tb in _meetings(a, b):
                splits[i].append(ta)
                splits[j].append(tb)
            for p in _ends_of(b):
                t = _param_on(a, p, True)
                if t is not None:
                    splits[i].append(t)
            for p in _ends_of(a):
                t = _param_on(b, p, True)
                if t is not None:
                    splits[j].append(t)
    vertices = []
    grid = {}
    cell = 1e-3

    def vertex_of(p):
        cx = math.floor(p[0] / cell)
        cy = math.floor(p[1] / cell)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for v in grid.get((cx + dx, cy + dy), ()):
                    if len2(sub2(vertices[v], p)) <= SNAP:
                        return v
        v = len(vertices)
        vertices.append([p[0], p[1]])
        grid.setdefault((cx, cy), []).append(v)
        return v

    edges = []
    for i, c in enumerate(curves):
        ts = _uniq_sorted(splits[i])
        a = vertex_of(_point_at(c, ts[0]))
        t0 = ts[0]
        for k in range(1, len(ts)):
            b = vertex_of(_point_at(c, ts[k]))
            if a == b:
                continue
            edges.append({"a": a, "b": b, "piece": {"entity": c["entity"], "t0": t0, "t1": ts[k], "p0": vertices[a], "p1": vertices[b]}, "leave": (_leaving(c, t0, True), _leaving(c, ts[k], False))})
            a = b
            t0 = ts[k]
    seen = set()
    unique = []
    for e in edges:
        key = (e["a"], e["b"]) if e["a"] < e["b"] else (e["b"], e["a"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(e)
    return vertices, unique


def _prune_dangling(edges):
    live = list(edges)
    while True:
        degree = {}
        for e in live:
            degree[e["a"]] = degree.get(e["a"], 0) + 1
            degree[e["b"]] = degree.get(e["b"], 0) + 1
        kept = [e for e in live if degree.get(e["a"], 0) > 1 and degree.get(e["b"], 0) > 1]
        if len(kept) == len(live):
            return kept
        live = kept


def point_in_polygon(p, poly):
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        a = poly[i]
        b = poly[j]
        if (a[1] > p[1]) != (b[1] > p[1]) and p[0] < ((b[0] - a[0]) * (p[1] - a[1])) / (b[1] - a[1]) + a[0]:
            inside = not inside
        j = i
    return inside


def _trace(vertices, edges):
    halves = []
    for i, e in enumerate(edges):
        halves.append({"edge": i, "from": e["a"], "to": e["b"], "angle": e["leave"][0]})
        halves.append({"edge": i, "from": e["b"], "to": e["a"], "angle": e["leave"][1]})
    outgoing = {}
    for i, h in enumerate(halves):
        outgoing.setdefault(h["from"], []).append(i)
    for lst in outgoing.values():
        lst.sort(key=lambda x: halves[x]["angle"])

    def nxt(hi):
        h = halves[hi]
        twin = hi ^ 1
        lst = outgoing[h["to"]]
        k = lst.index(twin)
        return lst[(k - 1 + len(lst)) % len(lst)]

    used = [False] * len(halves)
    loops = []
    for start in range(len(halves)):
        if used[start]:
            continue
        loop = []
        seen_edges = set()
        h = start
        for _guard in range(len(halves) + 1):
            used[h] = True
            half = halves[h]
            if half["edge"] in seen_edges:
                return half["edge"]  # a bridge: both sides in one face
            seen_edges.add(half["edge"])
            loop.append(half)
            h = nxt(h)
            if h == start:
                break
        polygon = [vertices[x["from"]] for x in loop]
        loops.append({"halves": loop, "polygon": polygon, "area": signed_area2(polygon)})
    return loops


def _pieces_of(loop, edges, sketch):
    raw = []
    for h in loop["halves"]:
        e = edges[h["edge"]]
        pc = e["piece"]
        if h["from"] == e["a"]:
            raw.append(dict(pc))
        else:
            raw.append({"entity": pc["entity"], "t0": pc["t1"], "t1": pc["t0"], "p0": pc["p1"], "p1": pc["p0"]})
    periods = {e["id"]: len(e["pts"]) for e in sketch["entities"] if e["kind"] == "spline" and is_closed(e)}

    def across(entity, end, t):
        if abs(end - t) < 1e-9:
            return 0
        period = periods.get(entity)
        if period is None:
            return None
        turns = js_round((end - t) / period)
        return turns * period if turns != 0 and abs(end - t - turns * period) < 1e-9 else None

    merged = []
    for p in raw:
        last = merged[-1] if merged else None
        shift = across(p["entity"], last["t1"], p["t0"]) if last and last["entity"] == p["entity"] else None
        if last and shift is not None:
            last["t1"] = p["t1"] + shift
            last["p1"] = p["p1"]
        else:
            merged.append(dict(p))
    if len(merged) > 1:
        first = merged[0]
        last = merged[-1]
        shift = across(first["entity"], last["t1"], first["t0"]) if first["entity"] == last["entity"] else None
        if shift is not None:
            first["t0"] = last["t0"] - shift
            first["p0"] = last["p0"]
            merged.pop()
    ids = {e["id"] for e in sketch["entities"]}
    return [p for p in merged if p["entity"] in ids and abs(p["t1"] - p["t0"]) > 1e-9]


def _centroid(poly):
    x = 0.0
    y = 0.0
    for p in poly:
        x += p[0]
        y += p[1]
    return [x / len(poly), y / len(poly)]


def _inside_point(outer, holes):
    def ok(p):
        return point_in_polygon(p, outer) and not any(point_in_polygon(p, h) for h in holes)

    c = _centroid(outer)
    if ok(c):
        return c
    y0 = math.inf
    y1 = -math.inf
    for p in outer:
        y0 = min(y0, p[1])
        y1 = max(y1, p[1])
    for f in (0.5, 0.33, 0.66, 0.2, 0.8, 0.1, 0.9):
        y = y0 + (y1 - y0) * f
        xs = []
        for ring in [outer] + list(holes):
            for i in range(len(ring)):
                a = ring[i]
                b = ring[(i + 1) % len(ring)]
                if (a[1] > y) != (b[1] > y):
                    xs.append(a[0] + ((y - a[1]) * (b[0] - a[0])) / (b[1] - a[1]))
        xs.sort()
        best = None
        best_w = 0
        for i in range(0, len(xs) - 1, 2):
            mid = [(xs[i] + xs[i + 1]) / 2, y]
            w = xs[i + 1] - xs[i]
            if w > best_w and ok(mid):
                best_w = w
                best = mid
        if best:
            return best
    return c


class _UnionFind:
    def __init__(self, n):
        self.parent = list(range(n))

    def find(self, i):
        parent = self.parent
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(self, a, b):
        ra = self.find(a)
        rb = self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def _key_at(x):
    return "0.00" if abs(x) < 0.005 else to_fixed(x, 2)


def find_regions(sketch):
    """Every closed region of the sketch, largest first. A region is
    {"key", "outer": {"pieces", "polygon"}, "holes": [...], "area", "inside"};
    a piece is {"entity", "t0", "t1", "p0", "p1"}."""
    curves = _curves_of(sketch)
    if not curves:
        return []
    vertices, all_edges = _build_graph(curves)
    edges = _prune_dangling(all_edges)
    loops = []
    for _guard in range(64):
        result = _trace(vertices, edges)
        if isinstance(result, int):
            edges = _prune_dangling([e for i, e in enumerate(edges) if i != result])
            continue
        loops = result
        break
    faces = [lp for lp in loops if lp["area"] > 1e-4]
    outers = [lp for lp in loops if lp["area"] < -1e-4]
    uf = _UnionFind(len(vertices))
    for lp in loops:
        for h in lp["halves"]:
            uf.union(h["from"], h["to"])
    holes_of = {}
    for o in outers:
        probe = o["polygon"][0]
        component = uf.find(o["halves"][0]["from"])
        host = None
        for f in faces:
            if uf.find(f["halves"][0]["from"]) == component:
                continue
            if point_in_polygon(probe, f["polygon"]) and (host is None or f["area"] < host["area"]):
                host = f
        if host is not None:
            holes_of.setdefault(id(host), []).append(o)
    regions = []
    for f in faces:
        holes = holes_of.get(id(f), [])
        outer_pieces = _pieces_of(f, edges, sketch)
        ids = sorted(set(p["entity"] for p in outer_pieces))
        c = _centroid(f["polygon"])
        regions.append({
            "key": f"{'.'.join(str(i) for i in ids)}@{_key_at(c[0])},{_key_at(c[1])}",
            "outer": {"pieces": outer_pieces, "polygon": f["polygon"]},
            "holes": [{"pieces": _pieces_of(h, edges, sketch), "polygon": h["polygon"]} for h in holes],
            "area": f["area"] - sum(abs(h["area"]) for h in holes),
            "inside": _inside_point(f["polygon"], [h["polygon"] for h in holes]),
        })
    return sorted(regions, key=lambda r: -r["area"])


def _js_number(s):
    """Number(s) for a piece of a key."""
    t = s.strip()
    if t == "":
        return 0.0
    try:
        if t.lower() in ("infinity", "+infinity", "-infinity", "nan", "inf", "+inf", "-inf"):
            return {"infinity": math.inf, "+infinity": math.inf, "-infinity": -math.inf}.get(t.lower(), math.nan) if "infinity" in t.lower() else math.nan
        if "_" in t:
            return math.nan
        return float(t)
    except ValueError:
        return math.nan


def parse_region_key(key):
    at = key.rfind("@")
    if at < 0:
        return None
    ids = [v for v in (_js_number(s) for s in key[:at].split(".")) if math.isfinite(v)]
    parts = [_js_number(s) for s in key[at + 1:].split(",")]
    x = parts[0] if len(parts) > 0 else math.nan
    y = parts[1] if len(parts) > 1 else math.nan
    if not ids or not math.isfinite(x) or not math.isfinite(y):
        return None
    return {"ids": ids, "centroid": [x, y]}


def _inside_region(r, p):
    return point_in_polygon(p, r["outer"]["polygon"]) and not any(point_in_polygon(p, h["polygon"]) for h in r["holes"])


def match_region(key, regions):
    """The region a key names now: the same key, else the region of the
    same pieces nearest where it was, else the one under where it was that
    shares the most pieces, else the best overlap of pieces (half or more)."""
    for r in regions:
        if r["key"] == key:
            return r
    was = parse_region_key(key)
    if not was:
        return None
    was_ids = set(was["ids"])

    def ids_of(r):
        return set(p["entity"] for p in r["outer"]["pieces"])

    def shared(ids):
        return sum(1 for i in ids if i in was_ids)

    def dist(r):
        return len2(sub2(_centroid(r["outer"]["polygon"]), was["centroid"]))

    same = []
    for r in regions:
        ids = ids_of(r)
        if len(ids) == len(was_ids) and shared(ids) == len(ids):
            same.append(r)
    if same:
        return sorted(same, key=dist)[0]
    under = [(r, shared(ids_of(r))) for r in regions if _inside_region(r, was["centroid"])]
    under = [x for x in under if x[1] > 0]
    under.sort(key=lambda x: (-x[1], x[0]["area"]))
    if under:
        return under[0][0]
    best = None
    for r in regions:
        ids = ids_of(r)
        n = shared(ids)
        score = n / (len(ids) + len(was_ids) - n)
        if score >= 0.5 and (best is None or score > best[1] or (score == best[1] and dist(r) < dist(best[0]))):
            best = (r, score)
    return best[0] if best else None


def _includes(lst, r):
    return any(x is r for x in lst)


def match_regions(keys, regions):
    out = []
    for key in keys:
        r = match_region(key, regions)
        if r is not None and not _includes(out, r):
            out.append(r)
    return out


def regions_by_pick(given, regions):
    if not regions:
        return None
    if given == "all":
        return list(regions)
    if given == "largest":
        best = regions[0]
        for b in regions[1:]:
            if b["area"] > best["area"]:
                best = b
        return [best]
    out = []
    for p in given:
        r = match_region(p, regions) if isinstance(p, str) else region_at(regions, p["at"])
        if r is None:
            return None
        if not _includes(out, r):
            out.append(r)
    return out


def region_by_place(was, regions, skip=(), share=0.5):
    x0 = y0 = math.inf
    x1 = y1 = -math.inf
    for x, y in was["outer"]["polygon"]:
        x0 = min(x0, x)
        x1 = max(x1, x)
        y0 = min(y0, y)
        y1 = max(y1, y)
    points = []
    for i in range(PLACE_SAMPLES):
        for j in range(PLACE_SAMPLES):
            p = [x0 + ((i + 0.5) / PLACE_SAMPLES) * (x1 - x0), y0 + ((j + 0.5) / PLACE_SAMPLES) * (y1 - y0)]
            if _inside_region(was, p):
                points.append(p)
    if not points:
        points.append(was["inside"])
    best = None
    for r in regions:
        if _includes(skip, r):
            continue
        cover = sum(1 for p in points if _inside_region(r, p)) / len(points)
        if cover >= share and (best is None or cover > best[1]):
            best = (r, cover)
    return best[0] if best else None


def lost_picks(keys, regions):
    taken = []
    lost = []
    for key in keys:
        r = match_region(key, regions)
        if r is None or _includes(taken, r):
            lost.append(key)
        else:
            taken.append(r)
    return lost


def split_parts(was, now):
    ids = set(p["entity"] for p in was["outer"]["pieces"])
    return [r for r in now if _inside_region(was, r["inside"]) and any(p["entity"] in ids for p in r["outer"]["pieces"])]


def region_at(regions, p):
    best = None
    for r in regions:
        if not point_in_polygon(p, r["outer"]["polygon"]):
            continue
        if any(point_in_polygon(p, h["polygon"]) for h in r["holes"]):
            continue
        if best is None or r["area"] < best["area"]:
            best = r
    return best


def _sign(x):
    return 0 if x == 0 else (1 if x > 0 else -1) if x == x else math.nan


def merge_regions(regions, sketch):
    """Regions that share a stretch of a piece run the same way round
    neither - two halves of one picked region a construction line split -
    merged into one, where they make one outline."""
    if len(regions) < 2:
        return list(regions)
    kind = {e["id"]: e for e in sketch["entities"]}
    uf = _UnionFind(len(regions))
    touching = {}
    for i, r in enumerate(regions):
        for lp in [r["outer"]] + r["holes"]:
            for p in lp["pieces"]:
                e = kind.get(p["entity"])
                if e is not None and e["kind"] == "spline" and is_closed(e):
                    continue
                lst = touching.setdefault(p["entity"], [])
                if i not in lst:
                    lst.append(i)
    out = []
    for entity, ids in touching.items():
        if len(ids) < 2:
            continue
        for a in range(len(ids)):
            for b in range(a + 1, len(ids)):
                if uf.find(ids[a]) != uf.find(ids[b]) and _share_stretch(regions[ids[a]], regions[ids[b]], entity):
                    uf.union(ids[a], ids[b])
    groups = {}
    for i in range(len(regions)):
        groups.setdefault(uf.find(i), []).append(i)
    for ids in groups.values():
        group = [regions[i] for i in ids]
        merged = _merged_of(group, sketch) if len(ids) > 1 else None
        if merged:
            out.append(merged)
        else:
            out += group
    return out


def _share_stretch(a, b, entity):
    def of(r):
        return [p for lp in [r["outer"]] + r["holes"] for p in lp["pieces"] if p["entity"] == entity]

    for p in of(a):
        for q in of(b):
            if _sign(p["t1"] - p["t0"]) == _sign(q["t1"] - q["t0"]):
                continue
            lo = max(min(p["t0"], p["t1"]), min(q["t0"], q["t1"]))
            hi = min(max(p["t0"], p["t1"]), max(q["t0"], q["t1"]))
            if hi - lo > 1e-9:
                return True
    return False


def _merged_of(group, sketch):
    stretches = [p for r in group for lp in [r["outer"]] + r["holes"] for p in lp["pieces"]]
    cuts = {}

    def cut_at(entity, t, p):
        m = cuts.setdefault(entity, {})
        for known in m:
            if abs(known - t) < 1e-9:
                return
        m[t] = p

    for s in stretches:
        cut_at(s["entity"], s["t0"], s["p0"])
        cut_at(s["entity"], s["t1"], s["p1"])
    bits = {}
    for s in stretches:
        lo, hi = (s["t0"], s["t1"]) if s["t0"] < s["t1"] else (s["t1"], s["t0"])
        ts = sorted(t for t in cuts[s["entity"]] if lo + 1e-9 < t < hi - 1e-9)
        at = [lo] + ts + [hi]
        for i in range(len(at) - 1):
            key = f"{s['entity']}:{to_fixed(at[i], 9)}"
            bit = bits.get(key) or {"entity": s["entity"], "lo": at[i], "hi": at[i + 1], "net": 0}
            bit["net"] += 1 if s["t1"] > s["t0"] else -1
            bits[key] = bit

    def point_at(entity, t):
        for known, p in cuts[entity].items():
            if abs(known - t) < 1e-9:
                return p
        return [math.nan, math.nan]

    left = []
    for b in bits.values():
        if b["net"] == 0:
            continue
        if abs(b["net"]) > 1:
            return None
        t0, t1 = (b["lo"], b["hi"]) if b["net"] > 0 else (b["hi"], b["lo"])
        left.append({"entity": b["entity"], "t0": t0, "t1": t1, "p0": point_at(b["entity"], t0), "p1": point_at(b["entity"], t1)})

    def near(a, b):
        return len2(sub2(a, b)) <= SNAP

    used = set()
    loops = []
    for start in left:
        if id(start) in used:
            continue
        loop = [start]
        used.add(id(start))
        for _guard in range(len(left) + 1):
            last = loop[-1]
            if near(last["p1"], start["p0"]):
                break
            nxt = [p for p in left if id(p) not in used and near(p["p0"], last["p1"])]
            if len(nxt) != 1:
                return None
            loop.append(nxt[0])
            used.add(id(nxt[0]))
        if not near(loop[-1]["p1"], start["p0"]):
            return None
        loops.append(_joined_runs(loop, sketch))
    traced = []
    for pieces in loops:
        polygon = _loop_samples(pieces, sketch)
        traced.append({"pieces": pieces, "polygon": polygon, "area": signed_area2(polygon)})
    outers = [lp for lp in traced if lp["area"] > 1e-4]
    if len(outers) != 1:
        return None
    holes = [lp for lp in traced if lp["area"] < -1e-4]
    largest = group[0]
    for b in group[1:]:
        if b["area"] > largest["area"]:
            largest = b
    return {
        "key": "+".join(r["key"] for r in group),
        "outer": {"pieces": outers[0]["pieces"], "polygon": outers[0]["polygon"]},
        "holes": [{"pieces": h["pieces"], "polygon": h["polygon"]} for h in holes],
        "area": sum(r["area"] for r in group),
        "inside": largest["inside"],
    }


def _joined_runs(loop, sketch):
    kind = {e["id"]: e["kind"] for e in sketch["entities"]}

    def across(entity, end, t):
        if abs(end - t) < 1e-9:
            return 0
        if kind.get(entity) != "circle":
            return None
        turns = js_round((end - t) / (2 * math.pi))
        return turns * 2 * math.pi if turns != 0 and abs(end - t - turns * 2 * math.pi) < 1e-9 else None

    def same_way(a, b):
        return _sign(a["t1"] - a["t0"]) == _sign(b["t1"] - b["t0"])

    out = []
    for p in loop:
        last = out[-1] if out else None
        shift = across(p["entity"], last["t1"], p["t0"]) if last and last["entity"] == p["entity"] and same_way(last, p) else None
        if last and shift is not None:
            last["t1"] = p["t1"] + shift
            last["p1"] = p["p1"]
        else:
            out.append(dict(p))
    if len(out) > 1:
        first = out[0]
        last = out[-1]
        shift = across(first["entity"], last["t1"], first["t0"]) if first["entity"] == last["entity"] and same_way(first, last) else None
        if shift is not None:
            first["t0"] = last["t0"] - shift
            first["p0"] = last["p0"]
            out.pop()
    return out


def _entity(sketch, i):
    return next((x for x in sketch["entities"] if x["id"] == i), None)


def _loop_samples(pieces, sketch):
    out = []
    for p in pieces:
        e = _entity(sketch, p["entity"])
        out.append(p["p0"])
        if e is not None and e["kind"] in ("arc", "circle"):
            n = max(2, math.ceil((abs(p["t1"] - p["t0"]) / TURN) * ARC_SAMPLES_PER_TURN))
            for i in range(1, n):
                out.append(arc_point(e, p["t0"] + ((p["t1"] - p["t0"]) * i) / n))
        elif e is not None and e["kind"] == "spline":
            fit = spline_curve(e)
            for i in range(1, SPLINE_SAMPLES_PER_SEGMENT):
                out.append(spline_at(fit, p["t0"] + ((p["t1"] - p["t0"]) * i) / SPLINE_SAMPLES_PER_SEGMENT))
    return out


def loop_geometry(loop, sketch):
    """A loop as the pieces a profile is built of: lines, three-point arcs,
    a whole circle, B-spline stretches."""
    out = []
    for p in loop["pieces"]:
        e = _entity(sketch, p["entity"])
        if e is None:
            continue
        if e["kind"] == "line":
            out.append({"kind": "line", "a": p["p0"], "b": p["p1"]})
        elif e["kind"] in ("arc", "circle"):
            if len(loop["pieces"]) == 1 and abs(abs(p["t1"] - p["t0"]) - 2 * math.pi) < 1e-6:
                out.append({"kind": "circle", "c": e["c"], "r": e["r"]})
            else:
                out.append({"kind": "arc", "a": p["p0"], "m": arc_point(e, (p["t0"] + p["t1"]) / 2), "b": p["p1"]})
        elif e["kind"] == "spline":
            stretch = spline_stretch(spline_curve(e), p["t0"], p["t1"])
            if not stretch:
                continue
            stretch["poles"][0] = [p["p0"][0], p["p0"][1]]
            stretch["poles"][-1] = [p["p1"][0], p["p1"][1]]
            out.append({"kind": "spline", **stretch})
    return out


def picks_seen(sketch_id, regions):
    return {"sketchId": sketch_id, "regions": [{"key": r["key"], "area": r["area"], "inside": r["inside"]} for r in regions]}


def picks_grew(name, was, now, others):
    if not was or not now:
        return None
    before = sum(r["area"] for r in was["regions"])
    after = sum(r["area"] for r in now)
    keys = set(r["key"] for r in was["regions"])

    def fmt(x):
        return to_fixed(x, 1)

    def at(p):
        return f"({fmt(p[0])}, {fmt(p[1])})"

    for r in now:
        taken = [o for o in others if o["seen"]["sketchId"] == was["sketchId"] and any(x["key"] not in keys and _inside_region(r, x["inside"]) for x in o["seen"]["regions"])]
        if not taken:
            continue
        parts = " + ".join(f"{o['name']} {fmt(sum(x['area'] for x in o['seen']['regions']))}" for o in taken)
        return f"{name}’s region at {at(r['inside'])} now takes in {' and '.join(o['name'] + '’s' for o in taken)} ({name} {fmt(before)} + {parts} mm²): a junction came apart — a piece’s end slid off the piece it ended on (the sketch’s offPiece says which). Hold it there, or pick the regions again."
    if before > 0 and after > before * (1 + GREW_SHARE):
        return f"{name}’s region at {at(now[0]['inside'])} grew from {fmt(before)} to {fmt(after)} mm²: a junction may have come apart — a piece’s end slid off the piece it ended on (the sketch’s offPiece says which). Pick the region again if the sketch was meant to grow."
    return None


def same_pick(name, mine, others):
    for r in mine:
        also = [o for o in others if _includes(o["regions"], r)]
        if not also:
            continue
        return f"{name} picks the same region of its sketch as {' and '.join(o['name'] for o in also)} (at ({to_fixed(r['inside'][0], 1)}, {to_fixed(r['inside'][1], 1)}), {to_fixed(r['area'], 1)} mm²): if two regions ran into one, a junction came apart — a piece’s end slid off the piece it ended on (the sketch’s offPiece says which). Hold it there, or pick the regions again."
    return None
