# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/core/stations.ts (and kindsOfChain from segment.ts)
# SPDX-License-Identifier: AGPL-3.0-only
#
# The stations of a loft taken from the scan. A styled part (a cover's
# wing, a fairing) is a loft through sections of it, and a loft through
# sections only lofts cleanly when every station has the same pieces in the
# same order: the same lines and arcs, tangent where the others are. So a
# station is fitted like one already made: the scan's run on its plane cut
# into that station's pieces, kind for kind (kinds_of_chain), its relations
# copied, and the pieces it was closed with (a line across the base, drawn
# rather than fitted) copied where they lie, the run's ends run on to meet
# them. And a thin shell's inner station is its outer one moved in by the
# wall: each line along its normal, each arc about its centre, the corners
# met again, the pieces drawn to close it staying where they are, so the
# inner loft reaches the same base and the cut opens it there.

import json
import math
import re

import numpy as np

from ..chainsegment import TOLERANCE_SCATTERS, TOLERANCE_SPACING, chain_statistics, unwind_angle
from ..geom2d import FitError, fit_arc, fit_line
from ._js import js_round, num_str, precision_number
from .corners import place_segments
from .datums import trace_line, trace_of, trace_offset
from .regions import find_regions
from .sketch import (TOUCH_MM, add2, anchor_point, arc_angle_of, arc_point, constraint_entities, cross2, dot2, ends_of, entity_of, entity_polyline, is_dimension,
                     len2, normalize2, perp2, scale2, signed_area2, sub2)
from .solver import measure_dimension

STATION_MIN_PIECE_MM = 0.05
STATION_MIN_ARC_DEG = 5
CORNER_REACH = 2
GAPS_NAMED = 5
HOLDS = 1e-5
INSET_ARC_SLACK_DEG = 15
STATION_FOLD_HELP = "the scan’s run does not fall into the template’s pieces there, and a loft through it folds. Point the fit with within or facing, give it a tolerance, or draw this station."

KIND_BREAKS = 100
KIND_COST_POINTS = 200


def _other_end(end):
    return "b" if end == "a" else "a"


def _a_kind(kind):
    return f"{'an' if re.match('[aeiou]', kind) else 'a'} {kind}"


def _mm(x):
    return num_str(precision_number(x, 2) if abs(x) < 0.01 else js_round(x * 1000) / 1000)


def _deg_of(rad):
    return num_str(js_round(((rad * 180) / math.pi) * 10) / 10)


def _sign(x):
    return (x > 0) - (x < 0)


def _mid2(a, b):
    return [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]


def _copy(x):
    return json.loads(json.dumps(x))


def _chain_box(points):
    lo = [math.inf, math.inf]
    hi = [-math.inf, -math.inf]
    for p in points:
        lo = [min(lo[0], p[0]), min(lo[1], p[1])]
        hi = [max(hi[0], p[0]), max(hi[1], p[1])]
    return {"min": lo, "max": hi}


def _piece_length(e):
    return len2(sub2(e["b"], e["a"])) if e["kind"] == "line" else e["r"] * abs(e["sweep"])


def _travel_at(e, frm, at):
    if e["kind"] == "line":
        return normalize2(sub2(e["b"], e["a"]) if frm == "a" else sub2(e["a"], e["b"]))
    angle = e["start"] if at == "a" else e["start"] + e["sweep"]
    turn = (1 if frm == "a" else -1) * _sign(e["sweep"] or 1)
    return [-math.sin(angle) * turn, math.cos(angle) * turn]


def _ends_along(sketch, ids, closed):
    out = {}
    n = len(ids)

    def piece(k):
        return entity_of(sketch, ids[k])

    def nearer(k, other):
        o = piece(other)

        def gap(end):
            p = anchor_point(piece(k), end)
            return min(len2(sub2(p, anchor_point(o, "a"))), len2(sub2(p, anchor_point(o, "b"))))

        return "a" if gap("a") <= gap("b") else "b"

    for k in range(n):
        if n == 1:
            out[ids[k]] = {"from": "a", "to": "b"}
        elif k < n - 1 or closed:
            to = nearer(k, (k + 1) % n)
            out[ids[k]] = {"from": _other_end(to), "to": to}
        else:
            frm = nearer(k, k - 1)
            out[ids[k]] = {"from": frm, "to": _other_end(frm)}
    return out


def station_faults(template, loop, made, ids=None):
    """What is wrong with a station made like `template`, piece by piece, in
    words; empty when nothing is."""
    if ids is None:
        ids = [p["id"] for p in loop["pieces"]]
    ends = _ends_along(made, ids, loop["closed"])
    out = []
    for k, p in enumerate(loop["pieces"]):
        e = entity_of(made, ids[k])
        t = entity_of(template, p["id"])
        if not e or not t or e["kind"] != t["kind"]:
            continue
        what = f"piece {num_str(ids[k])} ({_a_kind(e['kind'])})"
        ln = _piece_length(e)
        if ln < STATION_MIN_PIECE_MM:
            out.append(f"{what} is {_mm(ln)} mm long — under {num_str(STATION_MIN_PIECE_MM)} mm")
            continue
        way = ends[ids[k]]
        now = _travel_at(e, way["from"], way["to"])
        was = _travel_at(t, p["from"], p["to"])
        if e["kind"] == "line":
            if now and was and dot2(now, was) < 0:
                out.append(f"{what} runs {_mm(ln)} mm backwards against the template’s piece {num_str(p['id'])}")
            continue
        sense = (1 if way["from"] == "a" else -1) * _sign(e["sweep"] or 1)
        had = (1 if p["from"] == "a" else -1) * _sign(t["sweep"] or 1)
        if sense != had:
            out.append(f"{what} bends the other way from the template’s piece {num_str(p['id'])}")
        elif abs(e["sweep"]) < (STATION_MIN_ARC_DEG * math.pi) / 180:
            out.append(f"{what} sweeps {_deg_of(abs(e['sweep']))}° — under {STATION_MIN_ARC_DEG}°")
    return out


def station_loop(sketch, name, any_runs=False):
    """A sketch's profile as a station {pieces, closed}, or why not."""
    own = [e for e in sketch["entities"] if not e.get("construction") and e["kind"] != "point"]
    if not own:
        return f"{name} has no pieces."
    odd = next((e for e in own if e["kind"] not in ("line", "arc")), None)
    if odd:
        return f"{name} has {_a_kind(odd['kind'])} (piece {num_str(odd['id'])}) — a station is lines and arcs end to end."
    pieces = own
    sliver = next((e for e in pieces if len2(sub2(anchor_point(e, "a"), anchor_point(e, "b"))) <= TOUCH_MM and _piece_length(e) <= TOUCH_MM), None)
    if sliver:
        return (f"{name}'s piece {num_str(sliver['id'])} ({_a_kind(sliver['kind'])}) is {_mm(_piece_length(sliver))} mm long — shorter than the {num_str(TOUCH_MM)} mm two ends meet within, "
                "so the pieces either side meet across it. Take it out (reverse.sketch.edit remove) and join its neighbours, or fit the station again.")
    ends = [{"piece": i, "end": end, "at": anchor_point(e, end)} for i, e in enumerate(pieces) for end in ("a", "b")]
    partners = [[q for q in ends if q["piece"] != p["piece"] and len2(sub2(q["at"], p["at"])) <= TOUCH_MM] for p in ends]
    if any(len(x) > 1 for x in partners):
        return f"{name} branches — three pieces meet at a point; a station is one chain of pieces end to end."
    loose = [p for i, p in enumerate(ends) if not partners[i]]
    start = loose[0] if loose else ends[0]
    order = []
    seen = set()
    at = start
    closed = False
    while True:
        e = pieces[at["piece"]]
        seen.add(at["piece"])
        to = _other_end(at["end"])
        order.append({"id": e["id"], "kind": e["kind"], "from": at["end"], "to": to, "fitted": bool(e.get("points"))})
        idx = next(i for i, q in enumerate(ends) if q["piece"] == at["piece"] and q["end"] == to)
        nxt = partners[idx][0] if partners[idx] else None
        if not nxt:
            break
        if nxt["piece"] in seen:
            closed = nxt["piece"] == start["piece"]
            break
        at = nxt
    if len(order) < len(pieces):
        return (f"{name} is more than one chain — a station is one chain of pieces end to end (its pieces {', '.join(num_str(p['id']) for p in order)} make one; "
                f"{len(pieces) - len(order)} more lie apart).")
    n = len(order)
    if closed and any(p["fitted"] for p in order) and any(not p["fitted"] for p in order):
        first = next(i for i, p in enumerate(order) if p["fitted"] and not order[(i - 1 + n) % n]["fitted"])
        order = order[first:] + order[:first]
    runs = len([p for i, p in enumerate(order) if p["fitted"] and (i == 0 or not order[i - 1]["fitted"])])
    if runs > 1 and not any_runs:
        return f"{name}'s fitted pieces are {runs} runs with drawn pieces between them — a station is one run fitted to the scan, closed by what is drawn."
    return {"pieces": order, "closed": closed}


def _meeting(a, b, near):
    def nearest(cs):
        if not cs:
            return None
        best = cs[0]
        for y in cs[1:]:
            if len2(sub2(y, near)) < len2(sub2(best, near)):
                best = y
        return best

    if a["kind"] == "line" and b["kind"] == "line":
        da = sub2(a["b"], a["a"])
        db = sub2(b["b"], b["a"])
        denom = cross2(da, db)
        if abs(denom) < 1e-9 * len2(da) * len2(db):
            return None
        return add2(a["a"], scale2(da, cross2(sub2(b["a"], a["a"]), db) / denom))
    if a["kind"] == "arc" and b["kind"] == "arc":
        d = len2(sub2(b["c"], a["c"]))
        if d < 1e-9 or d > a["r"] + b["r"] or d < abs(a["r"] - b["r"]):
            return None
        along = (a["r"] * a["r"] - b["r"] * b["r"] + d * d) / (2 * d)
        h = math.sqrt(max(0, a["r"] * a["r"] - along * along))
        u = scale2(sub2(b["c"], a["c"]), 1 / d)
        foot = add2(a["c"], scale2(u, along))
        return nearest([add2(foot, scale2(perp2(u), h)), add2(foot, scale2(perp2(u), -h))])
    line = a if a["kind"] == "line" else b
    arc = a if a["kind"] == "arc" else b
    d = normalize2(sub2(line["b"], line["a"]))
    if not d:
        return None
    foot = add2(line["a"], scale2(d, dot2(sub2(arc["c"], line["a"]), d)))
    off = len2(sub2(arc["c"], foot))
    if off >= arc["r"]:
        return foot
    h = math.sqrt(arc["r"] * arc["r"] - off * off)
    return nearest([add2(foot, scale2(d, h)), add2(foot, scale2(d, -h))])


def _nearest_sweep(raw, had):
    two = 2 * math.pi
    best = raw
    for y in (raw, raw + two, raw - two):
        if 1e-9 < y <= two + 1e-9 and abs(y - had) < abs(best - had):
            best = y
    return best


def _set_end(e, at, p):
    if e["kind"] == "line":
        e[at] = [p[0], p[1]]
        return
    angle = arc_angle_of(e, p)
    if at == "a":
        end = e["start"] + e["sweep"]
        raw = unwind_angle(end, angle) - angle
        e["start"] = angle
        e["sweep"] = _nearest_sweep(raw, e["sweep"])
    else:
        e["sweep"] = _nearest_sweep(unwind_angle(angle, e["start"]) - e["start"], e["sweep"])


def _meet_corners(sketch, loop, ends, still, near):
    pieces = loop["pieces"]
    n = len(pieces)
    met = []
    for i in range(n if loop["closed"] else n - 1):
        A = pieces[i]
        B = pieces[(i + 1) % n]
        if still(A["id"]) and still(B["id"]):
            continue
        ea = entity_of(sketch, A["id"])
        eb = entity_of(sketch, B["id"])
        at_a = ends[A["id"]]["to"]
        at_b = ends[B["id"]]["from"]
        pa = anchor_point(ea, at_a)
        pb = anchor_point(eb, at_b)
        spot = near(i, pa, pb)
        m = _meeting(ea, eb, spot) or spot
        _set_end(ea, at_a, m)
        _set_end(eb, at_b, m)
        met.append({"a": A["id"], "b": B["id"], "reach": max(len2(sub2(m, pa)), len2(sub2(m, pb)))})
    return met


def kinds_of_chain(chain, kinds, tolerance=None, closed=False):
    """segment.ts kindsOfChain: a chain as the pieces `kinds` names, end to
    end and in that order, the breaks where the pieces together sit closest
    on the points; `cost` the sum of their squared misses, mm². Raises
    FitError when the chain is too short for the pieces or no cut fits."""
    spacing, scatter, _closed, pts = chain_statistics(chain)
    points = [[float(p[0]), float(p[1])] for p in pts]
    if closed:
        points = points + [points[0]]
    n = len(points)
    grid = np.asarray(points, dtype=float)
    pieces = len(kinds)
    if pieces == 0:
        raise FitError("There are no pieces to cut the chain into.")

    def fewest(k):
        return 5 if k == "arc" else 3

    needed = 1 + sum(fewest(k) - 1 for k in kinds)
    if n < needed:
        raise FitError(f"The chain has {n} points — too few for {pieces} pieces ({', '.join(kinds)}).")
    tol = tolerance if tolerance is not None else max(TOLERANCE_SCATTERS * scatter, TOLERANCE_SPACING * spacing)
    stride = max(1, math.ceil((n - 1) / KIND_BREAKS))
    at = list(range(0, n - 1, stride)) + [n - 1]
    m = len(at)
    costs = {}

    def try_fit(kind, run):
        try:
            return fit_arc(run) if kind == "arc" else fit_line(run)
        except FitError:
            return None

    def cost_of(a, b, kind):
        key = (a, b, kind)
        if key in costs:
            return costs[key]
        count = at[b] - at[a] + 1
        cost = math.inf
        if count >= fewest(kind):
            step = max(1, math.ceil(count / KIND_COST_POINTS))
            idx = list(range(at[a], at[b] + 1, step))
            if idx[-1] != at[b]:
                idx.append(at[b])
            fit = try_fit(kind, grid[idx])
            if fit and math.isfinite(fit["sigma"]) and (kind == "line" or math.isfinite(fit["radius"])):
                cost = fit["sigma"] * fit["sigma"] * count
        costs[key] = cost
        return cost

    best = [[math.inf] * m for _ in range(pieces)]
    frm = [[-1] * m for _ in range(pieces)]
    for k in range(pieces):
        for b in range(1, m):
            if k == 0:
                best[0][b] = cost_of(0, b, kinds[0])
                continue
            for a in range(k, b):
                if not math.isfinite(best[k - 1][a]):
                    continue
                total = best[k - 1][a] + cost_of(a, b, kinds[k])
                if total < best[k][b]:
                    best[k][b] = total
                    frm[k][b] = a
    if not math.isfinite(best[pieces - 1][m - 1]):
        raise FitError(f"The chain cannot be cut into {', '.join(kinds)} — a stretch of it is too short for its piece, or no piece fits it.")
    ends = [m - 1]
    for k in range(pieces - 1, 0, -1):
        ends.insert(0, frm[k][ends[0]])
    ends.insert(0, 0)
    segments = []
    cost = 0
    for k in range(pieces):
        lo = at[ends[k]]
        hi = at[ends[k + 1]]
        run = points[lo:hi + 1]
        fit = try_fit(kinds[k], run)
        if not fit:
            raise FitError(f"Piece {k + 1} ({kinds[k]}) does not fit its stretch of the chain.")
        cost += fit["sigma"] * fit["sigma"] * len(run)
        segments.append({"kind": kinds[k], "lo": lo, "hi": hi, "points": run, "fit": fit})
    return {"segments": segments, "points": points, "closed": bool(closed), "scatter": scatter, "spacing": spacing, "tolerance": tol, "cost": cost}


def like_station(template, loop, chain, tolerance=None):
    """The scan's run on a station's plane fitted like `template`:
    {sketch, reversed}, or why not, in words."""
    every_drawn = all(not p["fitted"] for p in loop["pieces"])
    if every_drawn and loop["closed"]:
        return "it is closed and has no piece fitted to the scan, so its run cannot be told from what closes it — fit it to the scan, or leave it open."
    pieces = [{**p, "fitted": True} for p in loop["pieces"]] if every_drawn else loop["pieces"]
    stretch = [p for p in pieces if p["fitted"]]
    whole = loop["closed"] and len(stretch) == len(pieces)
    _spacing, _scatter, closed, pts = chain_statistics(chain)
    points = [[float(p[0]), float(p[1])] for p in pts]
    if whole and not closed:
        return "it is a closed outline fitted whole, and this run is open — fit a closed chain (closeGaps), or close the template with a drawn piece."
    if not whole and closed and len(stretch) < len(pieces):
        return "this chain is closed and the template’s run is open, closed by drawn pieces — keep to one run (skin, facing or within)."

    def tmpl(i):
        return entity_of(template, i)

    first = anchor_point(tmpl(stretch[0]["id"]), stretch[0]["from"])
    kinds = [p["kind"] for p in stretch]
    ways = []
    for run in (points, points[::-1]):
        if whole:
            k = 0
            for i, p in enumerate(run):
                if len2(sub2(p, first)) < len2(sub2(run[k], first)):
                    k = i
            run = run[k:] + run[:k]
        try:
            ways.append(kinds_of_chain(run, kinds, tolerance=tolerance, closed=whole))
        except FitError as e:
            ways.append(str(e))
    fits = [w for w in ways if not isinstance(w, str)]
    if not fits:
        return ways[0]

    def off(cut):
        total = 0
        for k, s in enumerate(cut["segments"]):
            t = tmpl(stretch[k]["id"])
            total += len2(sub2(s["points"][0], anchor_point(t, stretch[k]["from"]))) + len2(sub2(s["points"][-1], anchor_point(t, stretch[k]["to"])))
        return total

    cut = fits[0]
    if len(fits) == 2:
        f, r = fits
        clearly = 2
        cut = f if f["cost"] * clearly < r["cost"] else r if r["cost"] * clearly < f["cost"] else f if off(f) <= off(r) else r
    reversed_ = cut is ways[1]

    scratch = {"entities": [], "constraints": [], "nextId": 1}
    placed = place_segments(scratch, cut)
    out = {"entities": [], "constraints": [], "nextId": 1}
    ends = {}
    k = 0
    for p in pieces:
        if p["fitted"]:
            made = {**entity_of(scratch, placed[k]["id"]), "id": p["id"]}
            out["entities"].append(made)
            ends[p["id"]] = {"from": placed[k]["from"], "to": placed[k]["to"]}
            k += 1
        else:
            out["entities"].append(_copy(tmpl(p["id"])))
            ends[p["id"]] = {"from": p["from"], "to": p["to"]}
    fitted = {p["id"] for p in pieces if p["fitted"]}
    n = len(pieces)

    def near(i, pa, pb):
        if pieces[i]["id"] not in fitted:
            return pb
        if pieces[(i + 1) % n]["id"] not in fitted:
            return pa
        return _mid2(pa, pb)

    met = _meet_corners(out, {"pieces": pieces, "closed": loop["closed"]}, ends, lambda i: i not in fitted, near)
    box = _chain_box(points)
    extent = len2(sub2(box["max"], box["min"]))
    far = None
    for c in met:
        if c["reach"] > CORNER_REACH * extent and (not far or c["reach"] > far["reach"]):
            far = c
    if far:
        return (f"the corner of pieces {num_str(far['a'])} and {num_str(far['b'])} lands {_mm(far['reach'])} mm past the run’s ends — over {CORNER_REACH}× the run’s extent ({_mm(extent)} mm): "
                "the two run nearly parallel and meet far off, likely because the run takes in something beside the station (a boss, a rib). Point it with within or facing.")
    faults = station_faults(template, {"pieces": pieces, "closed": loop["closed"]}, out)
    if faults:
        return f"{'; '.join(faults)} — {STATION_FOLD_HELP}"

    by_id = {p["id"]: p for p in pieces}

    def map_at(a):
        p = by_id.get(a["entity"])
        if not p or not p["fitted"] or a["at"] not in ("a", "b"):
            return a
        now = ends[p["id"]]
        return {"entity": a["entity"], "at": now["from"] if a["at"] == p["from"] else now["to"]}

    nxt = max([0] + [e["id"] for e in out["entities"]]) + 1
    for c in template["constraints"]:
        named = constraint_entities(c)
        if not all(i in by_id for i in named):
            continue
        if is_dimension(c) and any(i in fitted for i in named):
            continue
        cp = _copy(c)
        if cp.get("p"):
            cp["p"] = map_at(cp["p"])
        if isinstance(cp.get("q"), dict) and "entity" in cp["q"]:
            cp["q"] = map_at(cp["q"])
        cp["id"] = nxt
        nxt += 1
        out["constraints"].append(cp)
    out["nextId"] = nxt
    return {"sketch": out, "reversed": reversed_}


def _closed_chain(c):
    return len(c) > 2 and len2(sub2(c[0], c[-1])) < 1e-9


def gaps_round(chains, frm, close_gaps=0):
    """The gaps round the outline a run came from, widest first: {bridged,
    open}."""
    n = len(chains)
    is_open = [len(c) >= 2 and not _closed_chain(c) for c in chains]

    def end(e):
        c = chains[e >> 1]
        return c[-1] if e & 1 else c[0]

    pairs = []
    for i in range(n):
        if not is_open[i]:
            continue
        if len(chains[i]) >= 3:
            pairs.append((2 * i, 2 * i + 1, len2(sub2(end(2 * i), end(2 * i + 1)))))
        for j in range(i + 1, n):
            if not is_open[j]:
                continue
            for e in (2 * i, 2 * i + 1):
                for f in (2 * j, 2 * j + 1):
                    pairs.append((e, f, len2(sub2(end(e), end(f)))))
    pairs.sort(key=lambda p: p[2])
    mate = [-1] * (2 * n)
    width = [0.0] * (2 * n)
    for e, f, d in pairs:
        if mate[e] >= 0 or mate[f] >= 0:
            continue
        mate[e] = f
        mate[f] = e
        width[e] = width[f] = d
    seen = []
    links = []
    todo = [i for i in frm if i < n]
    while todo:
        c = todo.pop()
        if c in seen:
            continue
        seen.append(c)
        for e in (2 * c, 2 * c + 1):
            m = mate[e]
            if m < 0:
                continue
            if min(e, m) not in links:
                links.append(min(e, m))
            todo.append(m >> 1)
    box = _chain_box([p for c in seen for p in chains[c]])
    extent = len2(sub2(box["max"], box["min"]))
    widths = sorted((width[e] for e in links if 1e-9 < width[e] < extent), reverse=True)
    return {"bridged": [d for d in widths if d <= close_gaps], "open": [d for d in widths if d > close_gaps]}


def run_facts_words(loop, f):
    """What a station's refusal adds of the numbers it decided on; empty
    when there is nothing to add."""
    def lst(ds):
        return ", ".join(_mm(d) for d in ds[:GAPS_NAMED]) + (f" and {len(ds) - GAPS_NAMED} more" if len(ds) > GAPS_NAMED else "")

    fit = f["fit"]
    g = gaps_round(f["chains"], f["joined"]["from"], fit.get("closeGaps") or 0)
    bridged, opened = g["bridged"], g["open"]
    given = f"closeGaps {_mm(fit['closeGaps'])}" if fit.get("closeGaps") is not None else "no closeGaps given"
    bridges = f"{given} bridged {len(bridged)} gap{'' if len(bridged) == 1 else 's'} ({lst(bridged)} mm)" if bridged else f"{given}, none bridged"
    whole = loop["closed"] and all(p["fitted"] for p in loop["pieces"])
    run = f["run"]
    if not whole or _closed_chain(run):
        return f" ({bridges} — a bridge is a straight run across a hole, and the station’s pieces may not fall on it)" if bridged else ""
    ends = _mm(len2(sub2(run[0], run[-1])))
    by = [k for k in ("within", "skin", "facing") if fit.get(k) is not None]
    if _closed_chain(f["joined"]["chain"]) and by:
        return (f" The run’s ends stand {ends} mm apart: its chain closed ({bridges}), and {' and '.join(by)} split it into {f['runs']} run{'' if f['runs'] == 1 else 's'}, the longest taken — "
                f"fit the closed chain without {'it' if len(by) == 1 else 'them'}, or close the template with a drawn piece where the run stops.")
    still = f"; still open: {lst(opened)} mm" if opened else ""
    reach = (f" closeGaps {_mm(opened[0] * 1.05)} bridges them where they are holes in the scan; where they are the part’s own (a gap between keys), "
             "close the template with a drawn piece across them instead.") if opened else ""
    return f" The run’s ends stand {ends} mm apart; {bridges}{still}.{reach}"


def _holds(sketch, c, datums):
    def e(i):
        return entity_of(sketch, i)

    def pt(a):
        return anchor_point(e(a["entity"]), a["at"])

    def direction(i):
        ln = e(i)
        return normalize2(sub2(ln["b"], ln["a"])) if ln and ln["kind"] == "line" else None

    def off_line(p, a, d):
        return abs(dot2(sub2(p, a), perp2(d)))

    def carrier(on):
        if "line" in on:
            ln = e(on["line"])
            d = direction(on["line"])
            return {"a": ln["a"], "d": d} if ln and ln["kind"] == "line" and d else None
        t = trace_of(datums, on["datum"])
        return trace_line(t) if t else None

    k = c["kind"]
    if k == "coincident":
        return len2(sub2(pt(c["p"]), pt(c["q"]))) <= HOLDS
    if k in ("horizontal", "vertical"):
        d = direction(c["entity"])
        return not d or abs(d[1 if k == "horizontal" else 0]) <= HOLDS
    if k in ("parallel", "perpendicular"):
        a, b = direction(c["a"]), direction(c["b"])
        return not a or not b or abs(cross2(a, b) if k == "parallel" else dot2(a, b)) <= HOLDS
    if k == "tangent":
        a, b = e(c["a"]), e(c["b"])
        if not a or not b:
            return True

        def rnd(x):
            return x["kind"] in ("arc", "circle")

        if a["kind"] == "line" or b["kind"] == "line":
            ln = a if a["kind"] == "line" else b
            r = b if a["kind"] == "line" else a
            d = normalize2(sub2(ln["b"], ln["a"]))
            return not d or not rnd(r) or abs(off_line(r["c"], ln["a"], d) - r["r"]) <= HOLDS
        if not rnd(a) or not rnd(b):
            return True
        d = len2(sub2(b["c"], a["c"]))
        return min(abs(d - (a["r"] + b["r"])), abs(d - abs(a["r"] - b["r"]))) <= HOLDS
    if k == "concentric":
        a, b = e(c["a"]), e(c["b"])
        return not a or not b or "c" not in a or "c" not in b or len2(sub2(a["c"], b["c"])) <= HOLDS
    if k == "equal":
        a, b = e(c["a"]), e(c["b"])
        if a and b and a["kind"] == "line" and b["kind"] == "line":
            return abs(len2(sub2(a["b"], a["a"])) - len2(sub2(b["b"], b["a"]))) <= HOLDS
        return not a or not b or "r" not in a or "r" not in b or abs(a["r"] - b["r"]) <= HOLDS
    if k == "pointOn":
        p = pt(c["p"])
        on = c["on"]
        if "curve" in on:
            r = e(on["curve"])
            return not r or "r" not in r or abs(len2(sub2(p, r["c"])) - r["r"]) <= HOLDS
        if "datum" in on:
            t = trace_of(datums, on["datum"])
            return not t or abs(trace_offset(t, p)) <= HOLDS
        cr = carrier(on)
        return not cr or off_line(p, cr["a"], cr["d"]) <= HOLDS
    if k == "collinear":
        ln = e(c["line"])
        cr = carrier(c["on"])
        return not ln or ln["kind"] != "line" or not cr or max(off_line(ln["a"], cr["a"], cr["d"]), off_line(ln["b"], cr["a"], cr["d"])) <= HOLDS
    if k == "symmetric":
        p, q = pt(c["p"]), pt(c["q"])
        about = c["about"]
        if about == "x":
            return abs(p[1] + q[1]) <= HOLDS and abs(p[0] - q[0]) <= HOLDS
        if about == "y":
            return abs(p[0] + q[0]) <= HOLDS and abs(p[1] - q[1]) <= HOLDS
        axis = carrier(about)
        if not axis:
            return True
        return abs(dot2(sub2(_mid2(p, q), axis["a"]), perp2(axis["d"]))) <= HOLDS and abs(dot2(sub2(q, p), axis["d"])) <= HOLDS
    return True


def _corner_slack(sketch, loop, i, keep):
    pieces = loop["pieces"]
    n = len(pieces)

    def at(k, end):
        p = pieces[k]
        return _travel_at(entity_of(sketch, p["id"]), p["from"], p["from"] if end == "from" else p["to"])

    def corner(k, other, end):
        if pieces[other]["id"] in keep:
            return math.pi / 2
        t, u = at(k, end), at(other, "to" if end == "from" else "from")
        return 2 * math.asin(min(1, abs(cross2(t, u)))) if t and u else math.pi / 2

    return corner(i, (i - 1 + n) % n, "from") + corner(i, (i + 1) % n, "to") + (INSET_ARC_SLACK_DEG * math.pi) / 180


def _source_folds(sketch, loop):
    pieces = loop["pieces"]
    n = len(pieces)

    def piece(k):
        return entity_of(sketch, pieces[k]["id"])

    short_k = next((k for k in range(n) if _piece_length(piece(k)) < STATION_MIN_PIECE_MM), None)
    worst = None
    for k in range(n if loop["closed"] else n - 1):
        A = pieces[k]
        B = pieces[(k + 1) % n]
        t = _travel_at(piece(k), A["from"], A["to"])
        u = _travel_at(piece((k + 1) % n), B["from"], B["from"])
        if not t or not u:
            continue
        turn = math.acos(max(-1, min(1, dot2(t, u))))
        if turn > math.pi / 2 and (not worst or turn > worst["turn"]):
            worst = {"a": A["id"], "b": B["id"], "turn": turn}
    words = []
    if worst:
        words.append(f"the source folds back at the corner of pieces {num_str(worst['a'])} and {num_str(worst['b'])} (it turns {_deg_of(worst['turn'])}° there)")
    if short_k is not None:
        words.append(f"its piece {num_str(pieces[short_k]['id'])} is {_mm(_piece_length(piece(short_k)))} mm long")
    if not words:
        return None
    said = "; ".join(words)
    return said[0].upper() + said[1:]


def _crossing_pairs(sketch, loop):
    pieces = loop["pieces"]
    n = len(pieces)
    lines = [entity_polyline(entity_of(sketch, p["id"]), 48) for p in pieces]
    ends = []
    for p in pieces:
        e = entity_of(sketch, p["id"])
        ends.append([anchor_point(e, "a"), anchor_point(e, "b")])
    out = []
    for i in range(n):
        for j in range(i + 1, n):
            beside = j == i + 1 or (loop["closed"] and i == 0 and j == n - 1)

            def at_corner(p):
                return beside and any(len2(sub2(p, q)) <= 10 * TOUCH_MM for q in ends[i] + ends[j])

            found = False
            for s in range(len(lines[i]) - 1):
                if found:
                    break
                p0, p1 = lines[i][s], lines[i][s + 1]
                da = sub2(p1, p0)
                for t in range(len(lines[j]) - 1):
                    q0, q1 = lines[j][t], lines[j][t + 1]
                    db = sub2(q1, q0)
                    denom = cross2(da, db)
                    if abs(denom) < 1e-18:
                        continue
                    w = sub2(q0, p0)
                    x = cross2(w, db) / denom
                    y = cross2(w, da) / denom
                    if x < 0 or x > 1 or y < 0 or y > 1:
                        continue
                    if not at_corner(add2(p0, scale2(da, x))):
                        found = True
                        break
            if found:
                out.append([pieces[i]["id"], pieces[j]["id"]])
    return out


def inset_keeps(loop, sketch=None):
    """The pieces a profile keeps where they lie when moved in and none are
    named: the drawn ones where it has fitted ones too, a round drawn on the
    outline (an arc held tangent both ways) moving with it."""
    fitted = [p for p in loop["pieces"] if p["fitted"]]
    if not (0 < len(fitted) < len(loop["pieces"])):
        return []
    constraints = (sketch or {}).get("constraints") or []

    def rnd(i):
        return len([c for c in constraints if c["kind"] == "tangent" and (c["a"] == i or c["b"] == i)]) >= 2

    return [p["id"] for p in loop["pieces"] if not p["fitted"] and not (p["kind"] == "arc" and rnd(p["id"]))]


def inset_sketch(sketch, loop, by, keep, datums=None):
    """A closed profile moved inward by `by` mm (outward for a negative
    `by`): {sketch, moved, dropped}, or why not."""
    made = _moved_inward(sketch, loop, by, keep)
    if isinstance(made, str):
        return made
    return {**made, "dropped": _relations_settled(made["sketch"], made["moved"], datums)}


def _moved_inward(sketch, loop, by, keep):
    if not loop["closed"]:
        return "the profile is open — an inset moves a closed profile inward; close it with a line across its ends first."
    out = _copy(sketch)
    outline = []
    for p in loop["pieces"]:
        pts = entity_polyline(entity_of(sketch, p["id"]), 48)
        outline += pts if p["from"] == "a" else pts[::-1]
    left = signed_area2(outline) > 0

    def inward(travel):
        return perp2(travel) if left else scale2(perp2(travel), -1)

    moved = []
    for p in loop["pieces"]:
        if p["id"] in keep:
            continue
        e = entity_of(out, p["id"])
        if e["kind"] == "line":
            d = normalize2(sub2(e["b"] if p["to"] == "b" else e["a"], e["a"] if p["to"] == "b" else e["b"]))
            if not d:
                return f"piece {num_str(p['id'])} has no length."
            shift = scale2(inward(d), by)
            e["a"] = add2(e["a"], shift)
            e["b"] = add2(e["b"], shift)
        else:
            mid = e["start"] + e["sweep"] / 2
            m = arc_point(e, mid)
            ccw = [-math.sin(mid), math.cos(mid)]
            travel = ccw if p["from"] == "a" else scale2(ccw, -1)
            r = e["r"] - by if dot2(inward(travel), sub2(e["c"], m)) > 0 else e["r"] + by
            if not (r > 1e-6):
                return (f"the arc {num_str(p['id'])} (R{num_str(js_round(e['r'] * 1000) / 1000)}) is tighter than {num_str(abs(by))} mm — it would close up. "
                        "Make the wall thinner, or round that corner wider first.")
            e["r"] = r
        e.pop("points", None)
        e.pop("scatter", None)
        moved.append(p["id"])
    ends = {p["id"]: {"from": p["from"], "to": p["to"]} for p in loop["pieces"]}
    _meet_corners(out, loop, ends, lambda i: i in keep, lambda i, pa, pb: anchor_point(entity_of(sketch, loop["pieces"][i]["id"]), loop["pieces"][i]["to"]))
    fold = _source_folds(sketch, loop)
    why = f" {fold} — fit that station again (fit.like refuses a fold) before insetting it." if fold else " Give a smaller inset."
    for i, p in enumerate(loop["pieces"]):
        a, b = entity_of(sketch, p["id"]), entity_of(out, p["id"])
        if a["kind"] == "line" and b["kind"] == "line":
            was = sub2(a["b"], a["a"])
            now = sub2(b["b"], b["a"])
            if not (dot2(was, now) > 0) or len2(now) < 1e-6:
                return (f"piece {num_str(p['id'])} would turn inside out at {num_str(by)} mm — the profile is narrower there than the inset takes; give it a smaller one, "
                        f"or keep that piece (keep).{f' {fold}.' if fold else ''}")
        elif a["kind"] == "arc" and b["kind"] == "arc":
            allowed = min(math.pi, _corner_slack(sketch, loop, i, keep))
            if abs(b["sweep"] - a["sweep"]) > allowed or b["sweep"] < 1e-6:
                return (f"the arc {num_str(p['id'])} would turn inside out at {num_str(by)} mm — its sweep goes from {_deg_of(a['sweep'])}° to {_deg_of(b['sweep'])}°, "
                        f"more than the corners it meets its neighbours at let it ({_deg_of(allowed)}°): they cross past it.{why}")
    ids = {p["id"] for p in loop["pieces"]}
    regions = find_regions({"entities": [e for e in out["entities"] if e["id"] in ids]})
    if len(regions) > 1:
        pairs = _crossing_pairs(out, loop)
        crossing = f", pieces {', '.join(f'{num_str(x)} and {num_str(y)}' for x, y in pairs)} crossing" if pairs else ""
        return f"the inset at {num_str(by)} mm crosses itself: it closes {len(regions)} regions (areas {', '.join(_mm(r['area']) for r in regions)} mm²){crossing}.{why}"
    return {"sketch": out, "moved": moved}


def _relations_settled(out, moved, datums):
    dropped = []
    moved_set = set(moved)
    kept = []
    for c in out["constraints"]:
        if not any(i in moved_set for i in constraint_entities(c)):
            kept.append(c)
            continue
        if is_dimension(c):
            def at(i):
                return entity_of(out, i)
            k = c["kind"]
            if k in ("length", "radius", "diameter"):
                value = measure_dimension(out, k, at(c["entity"]))
            elif k == "angle":
                value = measure_dimension(out, "angle", at(c["a"]), at(c["b"]))
            else:
                value = measure_dimension(out, "distance", c["p"], c["q"], datums)
            if value is None:
                dropped.append({"id": c["id"], "kind": k})
                continue
            c["value"] = value
            c.pop("expr", None)
            kept.append(c)
            continue
        if _holds(out, c, datums):
            kept.append(c)
            continue
        dropped.append({"id": c["id"], "kind": c["kind"]})
    out["constraints"] = kept
    return dropped


def _chains_of(sketch):
    own = [e for e in sketch["entities"] if not e.get("construction") and e["kind"] != "point"]
    parent = list(range(len(own)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    ends = [[anchor_point(e, at) for at in ends_of(e)] for e in own]
    for i in range(len(own)):
        for j in range(i + 1, len(own)):
            if any(len2(sub2(p, q)) <= TOUCH_MM for p in ends[i] for q in ends[j]):
                parent[root(i)] = root(j)
    out = {}
    for i, e in enumerate(own):
        out.setdefault(root(i), []).append(e)
    return list(out.values())


def _inside_polygon(poly, p):
    inn = False
    j = len(poly) - 1
    for i in range(len(poly)):
        a, b = poly[i], poly[j]
        if (a[1] > p[1]) != (b[1] > p[1]) and p[0] < ((b[0] - a[0]) * (p[1] - a[1])) / (b[1] - a[1]) + a[0]:
            inn = not inn
        j = i
    return inn


def _outlines_cross(a, b):
    for la in a:
        for lb in b:
            for s in range(len(la) - 1):
                da = sub2(la[s + 1], la[s])
                for t in range(len(lb) - 1):
                    db = sub2(lb[t + 1], lb[t])
                    denom = cross2(da, db)
                    if abs(denom) < 1e-18:
                        continue
                    w = sub2(lb[t], la[s])
                    x = cross2(w, db) / denom
                    y = cross2(w, da) / denom
                    if 0 <= x <= 1 and 0 <= y <= 1:
                        return True
    return False


def _points_moved(was, now):
    if not was.get("points"):
        return None
    if was["kind"] == "line" and now["kind"] == "line":
        d = normalize2(sub2(now["b"], now["a"]))
        if not d:
            return None
        n = perp2(d)
        by = scale2(n, dot2(n, sub2(now["a"], was["a"])))
        return [add2(p, by) for p in was["points"]]
    if was["kind"] == now["kind"] and was["kind"] in ("arc", "circle"):
        out = []
        for p in was["points"]:
            o = sub2(p, was["c"])
            r = len2(o)
            out.append(add2(now["c"], scale2(o, (r + now["r"] - was["r"]) / r)) if r > 1e-9 else p)
        return out
    return None


def _joined_outline(r, lines):
    if not r.get("loop"):
        return [p for ln in lines for p in ln]
    out = []
    for p in r["loop"]["pieces"]:
        k = next(i for i, e in enumerate(r["pieces"]) if e["id"] == p["id"])
        out += list(lines[k]) if p["from"] == "a" else list(lines[k])[::-1]
    return out


def inset_chains(sketch, ask):
    """Every closed chain of a sketch moved inward on its own, all or
    nothing. `ask`: {by (a number, or a function of how many closed chains
    lie round the chain), keep? (loop -> set), only? (set of ids),
    keepPoints?, name, datums?}. Returns {sketch, moved, dropped, chains,
    kept, open}, or why not."""
    name = ask["name"]
    every = _chains_of(sketch)
    if not every:
        return f"{name} has no pieces."
    only = ask.get("only")
    chains = [c for c in every if any(e["id"] in only for e in c)] if only else every

    def named(c):
        return f"pieces {', '.join(num_str(e['id']) for e in c)}"

    read = []
    refused = []
    open_ = []
    for pieces in chains:
        if len(pieces) == 1 and pieces[0]["kind"] == "circle":
            read.append({"pieces": pieces})
            continue
        loop = station_loop({"entities": pieces}, name, any_runs=True)
        if isinstance(loop, str):
            refused.append(loop if len(chains) == 1 else f"{named(pieces)}: {loop}")
        elif loop["closed"]:
            read.append({"pieces": pieces, "loop": loop})
        elif len(chains) == 1:
            return _moved_inward(sketch, loop, 0, set())
        else:
            open_.append([e["id"] for e in pieces])

    def none_move(words, of):
        return words[0] if of == 1 else f"{len(words)} of the {of} chains do not move: {'; '.join(words)} — nothing was moved."

    if refused:
        return none_move(refused, len(chains))
    if not read:
        return "every chain is open — an inset moves a closed profile inward; close them with a line across their ends first."

    def outline_of(s, r):
        return [entity_polyline(entity_of(s, e["id"]), 48) for e in r["pieces"]]

    before = [outline_of(sketch, r) for r in read]

    def depth_of(i):
        return len([k for k, o in enumerate(before) if k != i and _inside_polygon(_joined_outline(read[k], o), before[i][0][0])])

    out = sketch
    moved = []
    chains_out = []
    kept = []
    by_ask = ask["by"]
    for i, r in enumerate(read):
        by = by_ask(depth_of(i)) if callable(by_ask) else by_ask

        def say(why):
            refused.append(why if len(read) == 1 else f"{named(r['pieces'])}: {why}")

        if not r.get("loop"):
            was = r["pieces"][0]
            if not (was["r"] - by > 1e-6):
                say(f"the circle {num_str(was['id'])} (R{_mm(was['r'])}) is tighter than {num_str(abs(by))} mm — it would close up. Give a smaller inset.")
                continue
            out = _copy(out)
            e = entity_of(out, was["id"])
            e["r"] = was["r"] - by
            e.pop("points", None)
            e.pop("scatter", None)
            moved.append(was["id"])
            chains_out.append({"pieces": [was["id"]], "by": by, "kept": []})
            continue
        keep = ask["keep"](r["loop"]) if ask.get("keep") else set(inset_keeps(r["loop"], sketch))
        made = _moved_inward(out, r["loop"], by, keep)
        if isinstance(made, str):
            say(made)
            continue
        out = made["sketch"]
        moved += made["moved"]
        held = [p["id"] for p in r["loop"]["pieces"] if p["id"] in keep]
        kept += held
        chains_out.append({"pieces": [e["id"] for e in r["pieces"]], "by": by, "kept": held})
    if refused:
        return none_move(refused, len(read))
    after = [outline_of(out, r) for r in read]
    for i in range(len(read)):
        for j in range(i + 1, len(read)):
            if _outlines_cross(after[i], after[j]) and not _outlines_cross(before[i], before[j]):
                return f"moved, the chains of {named(read[i]['pieces'])} and of {named(read[j]['pieces'])} would cross — give a smaller inset, or inset them apart. Nothing was moved."
    if ask.get("keepPoints"):
        for i in moved:
            was = entity_of(sketch, i)
            now = entity_of(out, i)
            points = _points_moved(was, now)
            if points:
                now["points"] = points
                if was.get("scatter") is not None:
                    now["scatter"] = was["scatter"]
    return {"sketch": out, "moved": moved, "dropped": _relations_settled(out, moved, ask.get("datums")), "chains": chains_out, "kept": kept, "open": open_}
