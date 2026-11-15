# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/core/profiles.ts
# SPDX-License-Identifier: AGPL-3.0-only
#
# Sketch profiles lifted into the part: points and pieces taken from a
# sketch's plane to 3D, the regions a feature picked, a loft's sections and
# a sweep's path, and how far a profile reaches: whether it crosses a
# revolve's axis. Pieces and profiles are as loops.py has them.

import math

from ._js import fmod, js_hypot, js_round, num_str, precision_number, to_fixed
from .loops import circle_through, piece_points
from .regions import loop_geometry, match_regions, merge_regions, regions_by_pick
from .sketch import TOUCH_MM, anchor_point, arc_point, sketch_bounds
from .sketch_spline import is_closed, spline_curve, spline_dir_at, spline_end, spline_stretch
from .sweep_route import route_pieces
from .vec import add_scaled, cross, dot, length, normalize, scale, sub


def _n(x):
    return num_str(x)


def lift_point(frame, p):
    """Lift a sheet point through the frame into the part."""
    return add_scaled(add_scaled(frame["origin"], frame["basisU"], p[0]), frame["basisV"], p[1])


def _lift_piece(frame, piece):
    k = piece["kind"]
    if k == "line":
        return {"kind": "line", "a": lift_point(frame, piece["a"]), "b": lift_point(frame, piece["b"])}
    if k == "arc":
        return {"kind": "arc", "a": lift_point(frame, piece["a"]), "m": lift_point(frame, piece["m"]), "b": lift_point(frame, piece["b"])}
    if k == "circle":
        return {"kind": "circle", "center": lift_point(frame, piece["c"]), "normal": frame["normal"], "radius": piece["r"]}
    # A B-spline lifted pole by pole is the curve lifted: the map is affine.
    return {"kind": "spline", "poles": [lift_point(frame, p) for p in piece["poles"]], "knots": piece["knots"], "mults": piece["mults"]}


def _lift_spline(frame, e, t0=None, t1=None):
    fit = spline_curve(e)
    stretch = spline_stretch(fit, 0 if t0 is None else t0, spline_end(fit) if t1 is None else t1)
    return _lift_piece(frame, {"kind": "spline", **stretch}) if stretch else None


def sketch_pieces(sketch):
    """Every drawn piece of a sketch, construction left out, lifted into the
    part: for a sheet, no region needed."""
    frame = sketch["frame"]
    out = []
    for e in sketch["sketch"]["entities"]:
        if e.get("construction"):
            continue
        k = e["kind"]
        if k == "line":
            out.append({"kind": "line", "a": lift_point(frame, e["a"]), "b": lift_point(frame, e["b"])})
        elif k == "circle":
            out.append({"kind": "circle", "center": lift_point(frame, e["c"]), "normal": frame["normal"], "radius": e["r"]})
        elif k == "spline":
            piece = _lift_spline(frame, e)
            if piece:
                out.append(piece)
        elif k == "arc":
            def at(angle):
                return [e["c"][0] + e["r"] * math.cos(angle), e["c"][1] + e["r"] * math.sin(angle)]
            out.append({"kind": "arc", "a": lift_point(frame, at(e["start"])), "m": lift_point(frame, at(e["start"] + e["sweep"] / 2)),
                        "b": lift_point(frame, at(e["start"] + e["sweep"]))})
    return out


def frame_map(frm, to):
    """The rigid map that carries a sketch from one frame to another:
    {point, dir}, two functions."""
    def d(v):
        u = dot(v, frm["basisU"])
        w = dot(v, frm["basisV"])
        z = dot(v, frm["normal"])
        return add_scaled(add_scaled(scale(to["basisU"], u), to["basisV"], w), to["normal"], z)

    def point(p):
        return add_scaled(d([p[0] - frm["origin"][0], p[1] - frm["origin"][1], p[2] - frm["origin"][2]]), to["origin"], 1)

    return {"point": point, "dir": d}


def move_profiles(profiles, fmap):
    point = fmap["point"]

    def piece(p):
        k = p["kind"]
        if k == "line":
            return {**p, "a": point(p["a"]), "b": point(p["b"])}
        if k == "arc":
            return {**p, "a": point(p["a"]), "m": point(p["m"]), "b": point(p["b"])}
        if k == "spline":
            return {**p, "poles": [point(q) for q in p["poles"]]}
        return {**p, "center": point(p["center"]), "normal": fmap["dir"](p["normal"])}

    return [{"outer": [piece(p) for p in pr["outer"]], "holes": [[piece(p) for p in h] for h in pr["holes"]]} for pr in profiles]


def lift_regions(frame, sketch, picked, merge=True):
    """The picked regions of a sketch as profiles in the part; with `merge`,
    those that share a stretch of their boundary one profile."""
    regions = merge_regions(picked, sketch) if merge else picked

    def lift(loop):
        geometry = loop_geometry(loop, sketch)
        whole = len(geometry) == len(loop["pieces"])
        return [{**_lift_piece(frame, p), "entity": loop["pieces"][i]["entity"]} if whole else _lift_piece(frame, p) for i, p in enumerate(geometry)]

    return [{"outer": lift(r["outer"]), "holes": [lift(h) for h in r["holes"]]} for r in regions]


def picked_profiles(f, sketch, regions_of):
    """The profiles a feature picked, lifted into the part, or why there
    are none (a string)."""
    if not f["regions"]:
        return "No profile picked — click the sketch’s regions in the viewport."
    regions = regions_of(sketch)
    pick = f.get("regionPick")
    given = None
    if pick and len(pick["keys"]) == len(f["regions"]) and all(k in f["regions"] for k in pick["keys"]):
        given = regions_by_pick(pick["given"], regions)
    picked = given if given is not None else match_regions(f["regions"], regions)
    if not picked:
        if regions:
            return lost_pick_words(len(f["regions"]), sketch["name"], regions)
        return f"The picked profiles are no longer closed — the sketch changed under them.{open_ends_words(sketch['sketch'])}"
    return lift_regions(sketch["frame"], sketch["sketch"], picked, not f.get("draftDeg"))


REGIONS_NAMED = 8
OPEN_ENDS_NAMED = 4


def _mm_words(x):
    return precision_number(x, 2) if abs(x) < 0.01 else js_round(x * 1000) / 1000


def _mmw(x):
    return _n(_mm_words(x))


def lost_pick_words(picks, sketch, regions):
    listed = [f"{r['key']} ({_mmw(r['area'])} mm², at [{', '.join(_mmw(x) for x in r['inside'])}])" for r in regions[:REGIONS_NAMED]]
    more = f" and {len(regions) - len(listed)} more" if len(regions) > len(listed) else ""
    what = "profile" if picks == 1 else f"{picks} profiles"
    return (f"None of the {what} picked is in {sketch} as it is now — an edit remade the pieces round {'it' if picks == 1 else 'them'}. "
            f"It has {len(regions)} closed region{'' if len(regions) == 1 else 's'}: {'; '.join(listed)}{more} — pick again: regions \"all\", \"largest\", their keys, or a point inside each ({{ at: [u, v] }}).")


def open_ends_words(sketch):
    """A sketch's open ends in words, for an answer whose profile is no
    longer closed; empty when every end meets another."""
    from .corners import open_ends
    every = open_ends(sketch)
    opened = []
    for i, o in enumerate(every):
        mate = o["nearest"]
        told = mate is not None and any(p["piece"] == mate["piece"] and p["end"] == mate["end"] and p["nearest"] is not None
                                        and p["nearest"]["piece"] == o["piece"] and p["nearest"]["end"] == o["end"] for p in every[:i])
        if not told:
            opened.append(o)
    if not opened:
        return ""

    def one(o):
        if o["nearest"] and o["gap"] is not None:
            return f"piece {_n(o['piece'])} end {o['end']} is {_mmw(o['gap'])} mm from piece {_n(o['nearest']['piece'])} end {o['nearest']['end']}"
        return f"piece {_n(o['piece'])} end {o['end']} meets nothing"

    named = [one(o) for o in opened[:OPEN_ENDS_NAMED]]
    more = f" (and {len(opened) - len(named)} more)" if len(opened) > len(named) else ""
    return f" Its open ends: {'; '.join(named)}{more} — put the ends together (a coincident) or redraw the piece to end exactly there."


def _regions_of_one_chain(region, regions):
    group = [region]
    ids = {p["entity"] for p in region["outer"]["pieces"]}
    grew = True
    while grew:
        grew = False
        for r in regions:
            if any(r is g for g in group) or not any(p["entity"] in ids for p in r["outer"]["pieces"]):
                continue
            group.append(r)
            for p in r["outer"]["pieces"]:
                ids.add(p["entity"])
            grew = True
    return group


def _largest(regions):
    best = regions[0]
    for r in regions[1:]:
        if r["area"] > best["area"]:
            best = r
    return best


def loft_profile(sketch, regions, what="the loft"):
    """The profile a loft takes from a sketch: its largest region, or why
    there is none or why it would be the wrong one."""
    if not regions:
        return f"{sketch['name']} has no closed region for {what}.{open_ends_words(sketch['sketch'])}"
    region = _largest(regions)
    one = _regions_of_one_chain(region, regions)
    if len(one) > 1:
        areas = [_mmw(a) for a in sorted((r["area"] for r in one), reverse=True)]
        return (f"{sketch['name']}'s pieces close {len(one)} regions (areas {', '.join(areas)} mm²) — the profile crosses itself or is cut across, "
                f"and {what} would take the largest alone. Read its pieces (reverse.feature.list) and fit or draw it again so it closes one region.")
    return lift_regions(sketch["frame"], sketch["sketch"], [region])[0]


LOFT_EXTENT_JUMP = 3


def _profile_extent(profile):
    pts = [q for p in profile["outer"] for q in piece_points(p)]
    lo = [min(p[k] for p in pts) for k in range(3)]
    hi = [max(p[k] for p in pts) for k in range(3)]
    return js_hypot(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2])


def loft_problem(sketches, profiles):
    """What would make a loft through these sketches fail in the kernel or
    come out wrong without a word, in words, or None."""
    from .stations import STATION_MIN_PIECE_MM
    for s in sketches:
        for e in s["sketch"]["entities"]:
            if e.get("construction") or e["kind"] not in ("line", "arc"):
                continue
            ln = js_hypot(e["b"][0] - e["a"][0], e["b"][1] - e["a"][1]) if e["kind"] == "line" else e["r"] * abs(e["sweep"])
            if ln < STATION_MIN_PIECE_MM:
                return (f"{s['name']}'s piece {_n(e['id'])} ({'an arc' if e['kind'] == 'arc' else 'a line'}) is {_mmw(ln)} mm long — under {_n(STATION_MIN_PIECE_MM)} mm: "
                        "no piece of a section, and one the kernel can stop on (NCollection_DataMap::Find) or fold at. Take it out (reverse.sketch.edit remove) and join its neighbours, or fit that section again.")
    extents = [_profile_extent(p) for p in profiles]
    n = len(extents)

    def rnd(x):
        return js_round(x * 10) / 10

    if n >= 3:
        for i in range(n):
            near = [extents[j] for j in (i - 1, i + 1) if 0 <= j < n]
            growth = extents[1] / extents[2] if i == 0 else extents[n - 2] / extents[n - 3] if i == n - 1 else 1
            if extents[i] > LOFT_EXTENT_JUMP * max(1, growth) * max(near):
                return (f"{sketches[i]['name']} spans {_n(rnd(extents[i]))} mm across, its neighbours {' and '.join(_n(rnd(x)) for x in near)} mm — a piece of it runs far off, "
                        "likely two nearly parallel pieces met far out. Read its pieces (reverse.feature.list) and fit it again, pointed with within or facing.")
    return None


SWEEP_SQUARE_DEG = 1
ROUTE_ON_PLANE_MM = 0.05


def profile_middle(profile):
    points = [q for p in profile["outer"] for q in piece_points(p)]
    return [sum(p[k] for p in points) / len(points) for k in range(3)]


def sweep_path(sketch, frm):
    """A sweep's path: the one chain of a sketch's lines, arcs and splines,
    lifted and run from the end nearest `frm`, {pieces, start, tangent}; or
    why there is none."""
    name = sketch["name"]
    frame = sketch["frame"]
    own = [e for e in sketch["sketch"]["entities"] if not e.get("construction") and e["kind"] != "point"]
    if any(e["kind"] == "circle" for e in own):
        return f"{name} has a circle — a sweep's path is lines, arcs and splines end to end; draw a closed path as arcs."
    if any(e["kind"] == "spline" and is_closed(e) for e in own):
        return f"{name} has a closed spline — a sweep's path has a start; draw it open, its ends joined to the rest of the path."
    pieces = [e for e in own if e["kind"] in ("line", "arc", "spline")]
    if not pieces:
        return f"{name} has no line, arc or spline for the profile to follow."

    def lift(p):
        return lift_point(frame, p)

    ends = [{"piece": i, "end": end, "at": anchor_point(e, end)} for i, e in enumerate(pieces) for end in ("a", "b")]

    def meeting(p):
        return [q for q in ends if q["piece"] != p["piece"] and js_hypot(q["at"][0] - p["at"][0], q["at"][1] - p["at"][1]) <= TOUCH_MM]

    if any(len(meeting(p)) > 1 for p in ends):
        return f"{name} branches — three pieces meet at a point; a sweep follows one chain."
    loose = [p for p in ends if not meeting(p)]

    def far(p):
        return length(sub(lift(p["at"]), frm))

    pool = loose if loose else ends
    first = pool[0]
    for p in pool[1:]:
        if far(p) < far(first):
            first = p
    out = []
    used = set()
    at = first
    while at and at["piece"] not in used:
        e = pieces[at["piece"]]
        used.add(at["piece"])
        other = "b" if at["end"] == "a" else "a"
        if e["kind"] == "spline":
            end = spline_end(spline_curve(e))
            piece = _lift_spline(frame, e, 0, end) if at["end"] == "a" else _lift_spline(frame, e, end, 0)
            if piece:
                out.append(piece)
        elif e["kind"] == "line":
            out.append({"kind": "line", "a": lift(anchor_point(e, at["end"])), "b": lift(anchor_point(e, other))})
        else:
            out.append({"kind": "arc", "a": lift(anchor_point(e, at["end"])), "m": lift(arc_point(e, e["start"] + e["sweep"] / 2)), "b": lift(anchor_point(e, other))})
        piece_i = at["piece"]
        nxt = meeting(next(x for x in ends if x["piece"] == piece_i and x["end"] == other))
        at = nxt[0] if nxt else None
    if len(used) < len(pieces):
        chains = _n(len(loose) / 2) if len(loose) > 2 else "more than one"
        return f"{name} is in {chains} chains — a sweep follows one."
    e = pieces[first["piece"]]
    if e["kind"] == "line":
        d = [e["b"][0] - e["a"][0], e["b"][1] - e["a"][1]] if first["end"] == "a" else [e["a"][0] - e["b"][0], e["a"][1] - e["b"][1]]
    elif e["kind"] == "spline":
        fit = spline_curve(e)
        run = spline_dir_at(fit, 0 if first["end"] == "a" else spline_end(fit))
        d = run if first["end"] == "a" else [-run[0], -run[1]]
    else:
        angle = e["start"] if first["end"] == "a" else e["start"] + e["sweep"]
        sign = (e["sweep"] > 0) - (e["sweep"] < 0)
        turn = (1 if first["end"] == "a" else -1) * sign
        d = [-math.sin(angle) * turn, math.cos(angle) * turn]
    tangent = normalize(add_scaled(scale(frame["basisU"], d[0]), frame["basisV"], d[1]))
    if not tangent:
        return f"{name}'s path starts with a piece of no length."
    return {"pieces": out, "start": lift(first["at"]), "tangent": tangent}


def _sweep_start_words(path, start, tangent):
    def r(x):
        return js_round(x * 1000) / 1000 or 0

    at = f"({', '.join(_n(r(x)) for x in start)})"
    way = f"({', '.join(_n(r(x)) for x in tangent)})"
    k = 0
    for b in (1, 2):
        if abs(tangent[b]) > abs(tangent[k]):
            k = b
    axis = "xyz"[k]
    along = abs(tangent[k]) >= math.cos((SWEEP_SQUARE_DEG * math.pi) / 180)
    if along:
        plane = f'the plane {{ kind: "world", axis: "{axis}", offset: {_n(r(start[k]))} }} is square to it there'
    else:
        plane = "no coordinate plane is square to it there: sketch on a measured plane with that normal through that point, or start the path along a coordinate axis"
    return f"{path} starts at {at} and leaves along {way}; sketch the profile on a plane through that point square to that way — {plane}."


def _off_square(tangent, normal):
    return (math.acos(min(1, abs(dot(tangent, normal)))) * 180) / math.pi


def sweep_geometry(profile_sketch, regions, path_sketch):
    """What a sweep sweeps: {profile, path, from}, or why not."""
    profile = loft_profile(profile_sketch, regions, "the sweep")
    if isinstance(profile, str):
        return profile
    frm = profile_middle(profile)
    path = sweep_path(path_sketch, frm)
    if isinstance(path, str):
        return path
    off = _off_square(path["tangent"], profile_sketch["frame"]["normal"])
    if off > SWEEP_SQUARE_DEG:
        return f"{profile_sketch['name']}'s plane stands {to_fixed(off, 1)}° off square to the path where it starts — {_sweep_start_words(path_sketch['name'], path['start'], path['tangent'])}"
    return {"profile": profile, "path": path["pieces"], "from": frm}


def route_sweep_geometry(profile_sketch, regions, route):
    """What a sweep along a route sweeps: {profile, path, from}, or why not."""
    profile = loft_profile(profile_sketch, regions, "the sweep")
    if isinstance(profile, str):
        return profile
    frm = profile_middle(profile)
    path = route_pieces(route, frm)
    if isinstance(path, str):
        return path
    frame, name = profile_sketch["frame"], profile_sketch["name"]
    words = _sweep_start_words("The route", path["start"], path["tangent"])
    off = _off_square(path["tangent"], frame["normal"])
    if off > SWEEP_SQUARE_DEG:
        return f"{name}'s plane stands {to_fixed(off, 1)}° off square to the route where it starts — {words}"
    aside = abs(dot(sub(path["start"], frame["origin"]), frame["normal"]))
    if aside > ROUTE_ON_PLANE_MM:
        return f"{name}'s plane lies {to_fixed(aside, 3)} mm off the route's start — {words}"
    outline = [q for p in profile["outer"] for q in piece_points(p)]
    rnd = [length(sub(q, path["start"])) for q in outline]
    reach = max(length(sub(q, frm)) for q in outline)
    apart = length(sub(path["start"], frm))
    if apart > reach:
        return f"The route starts {to_fixed(apart, 3)} mm from the middle of {name}'s profile, which reaches {to_fixed(reach, 3)} mm — {words}"
    near = min(rnd)
    tight = next((b for b in path["bends"] if b["radius"] <= near), None)
    if tight:
        return (f"The bend at points[{tight['index']}] of radius {_n(tight['radius'])} mm is tighter than {name}'s profile, every side of it at least {to_fixed(near, 3)} mm "
                "from the route: the inside of the bend would fold through itself.")
    return {"profile": profile, "path": path["pieces"], "from": frm}


def far_reach(origin, d, sketch, planes):
    """How far "far" is for an extrusion limited by a plane."""
    b = sketch_bounds(sketch)
    reach = js_hypot(b["max"][0] - b["min"][0], b["max"][1] - b["min"][1]) if b else 10
    for p in planes:
        reach = max(reach, abs(dot([p["origin"][0] - origin[0], p["origin"][1] - origin[1], p["origin"][2] - origin[2]], d)) * 2)
    return max(reach * 4, 10)


def profile_span(profiles, origin, d):
    lo = math.inf
    hi = -math.inf
    for p in profiles:
        for loop in [p["outer"], *p["holes"]]:
            for piece in loop:
                for q in piece_points(piece):
                    along = dot([q[0] - origin[0], q[1] - origin[1], q[2] - origin[2]], d)
                    lo = min(lo, along)
                    hi = max(hi, along)
    return {"min": lo, "max": hi}


def _newell(pts):
    n = [0, 0, 0]
    for i, a in enumerate(pts):
        b = pts[(i + 1) % len(pts)]
        n = [n[0] + (a[1] - b[1]) * (a[2] + b[2]), n[1] + (a[2] - b[2]) * (a[0] + b[0]), n[2] + (a[0] - b[0]) * (a[1] + b[1])]
    return normalize(n)


def _loop_points(loop):
    return [q for piece in loop for q in piece_points(piece)]


def profiles_meet_axis(profiles, origin, d, tol=1e-6):
    """Whether any profile touches or crosses an axis through `origin`
    along unit `d`."""
    def off(q):
        return [q[0] - origin[0], q[1] - origin[1], q[2] - origin[2]]

    for p in profiles:
        outer = _loop_points(p["outer"])
        normal = _newell(outer)
        if not normal:
            continue
        across = dot(normal, d)
        if abs(across) < 1e-9:
            if abs(dot(off(outer[0]), normal)) > tol:
                continue
            side = cross(normal, d)
            lo = math.inf
            hi = -math.inf
            for q in outer:
                x = dot(off(q), side)
                lo = min(lo, x)
                hi = max(hi, x)
            if lo <= tol and hi >= -tol:
                return True
            continue
        pierce = add_scaled(origin, d, dot(off(outer[0]), normal) / across)
        u = normalize(cross(normal, [1, 0, 0] if abs(normal[0]) < 0.9 else [0, 1, 0])) or [1, 0, 0]
        v = cross(normal, u)

        def flat(q):
            w = [q[0] - pierce[0], q[1] - pierce[1], q[2] - pierce[2]]
            return dot(w, u), dot(w, v)

        def where(loop):
            inside = False
            j = len(loop) - 1
            for i in range(len(loop)):
                xi, yi = flat(loop[i])
                xj, yj = flat(loop[j])
                ex = xj - xi
                ey = yj - yi
                l2 = ex * ex + ey * ey
                t = max(0, min(1, -(xi * ex + yi * ey) / l2)) if l2 > 0 else 0
                if js_hypot(xi + ex * t, yi + ey * t) <= tol:
                    return "on"
                if (yi > 0) != (yj > 0) and 0 < xi - (yi * ex) / ey:
                    inside = not inside
                j = i
            return "in" if inside else "out"

        rim = where(outer)
        if rim == "on":
            return True
        if rim == "out":
            continue
        holes = [where(_loop_points(h)) for h in p["holes"]]
        if "on" in holes or "in" not in holes:
            return True
    return False


def profile_across_axis(profiles, origin, d, tol=1e-6):
    """Where a profile runs across a revolve's axis, {across, at}, or None."""
    def off(q):
        return [q[0] - origin[0], q[1] - origin[1], q[2] - origin[2]]

    for p in profiles:
        outer = _loop_points(p["outer"])
        normal = _newell(outer)
        if not normal or not outer:
            continue
        if abs(dot(normal, d)) < 1e-9:
            if abs(dot(off(outer[0]), normal)) > tol:
                continue
            side = cross(normal, d)
            lo = hi = 0
            lo_at = hi_at = outer[0]
            for q in outer:
                x = dot(off(q), side)
                if x < lo:
                    lo, lo_at = x, q
                if x > hi:
                    hi, hi_at = x, q
            if lo < -tol and hi > tol:
                return {"across": -lo, "at": lo_at} if -lo <= hi else {"across": hi, "at": hi_at}
            continue
        if profiles_meet_axis([p], origin, d, tol):
            return {"across": 0, "at": add_scaled(origin, d, dot(off(outer[0]), normal) / dot(normal, d))}
    return None


POLE_SNAP_MM = 1e-4
POLE_CENTRE_MM = 1e-3
POLE_QUIET_MM = 1e-6


def _um(mm):
    return f"{_n(precision_number(mm * 1000, 2))} µm"


def mend_poles(profiles, origin, d):
    """A revolve's profiles with the pieces that end on its axis made to end
    on it as the kernel turns them whole: {profiles, mends}."""
    mends = []

    def rel(p):
        return sub(p, origin)

    def off(p):
        return length(cross(rel(p), d))

    def foot(p):
        return add_scaled(origin, d, dot(rel(p), d))

    def on_axis(p):
        return off(p) <= 1e-9

    def ends(piece):
        if piece["kind"] in ("line", "arc"):
            return [piece["a"], piece["b"]]
        if piece["kind"] == "spline":
            return [piece["poles"][0], piece["poles"][-1]]
        return []

    def mend_loop(loop):
        targets = []
        for piece in loop:
            for p in ends(piece):
                if 0 < off(p) <= POLE_SNAP_MM:
                    targets.append({"at": p, "piece": piece.get("entity")})
        for piece in loop:
            if piece["kind"] != "line":
                continue
            for p, q in ((piece["a"], piece["b"]), (piece["b"], piece["a"])):
                dd = off(p)
                if POLE_SNAP_MM < dd <= TOUCH_MM and off(q) <= POLE_SNAP_MM and length(sub(p, q)) >= 10 * dd:
                    targets.append({"at": p, "piece": piece.get("entity")})
        farthest = None
        for t in targets:
            if farthest is None or off(t["at"]) > off(farthest["at"]):
                farthest = t
        if farthest and off(farthest["at"]) > POLE_QUIET_MM:
            e = farthest["piece"]
            who = f"piece {_n(e)}'s end" if e is not None else "an end"
            mends.append({"piece": e, "what": f"{who} {_n(precision_number(off(farthest['at']) * 1000, 2))} µm off the axis put on it", "movedMm": off(farthest["at"])})

        def snap(p):
            return foot(p) if any(length(sub(t["at"], p)) <= 1e-9 for t in targets) else p

        out = []
        for piece in loop:
            e = piece.get("entity")
            k = piece["kind"]
            if k == "line":
                out.append({**piece, "a": snap(piece["a"]), "b": snap(piece["b"])})
                continue
            if k == "spline":
                n = len(piece["poles"])
                poles = [snap(p) if i in (0, n - 1) else p for i, p in enumerate(piece["poles"])]
                if not on_axis(poles[-1]) or on_axis(poles[0]):
                    out.append({**piece, "poles": poles})
                    continue
                k0, k1 = piece["knots"][0], piece["knots"][-1]
                out.append({**piece, "poles": poles[::-1], "knots": [k0 + k1 - x for x in piece["knots"]][::-1], "mults": piece["mults"][::-1]})
                continue
            if k != "arc":
                out.append(piece)
                continue
            a = snap(piece["a"])
            b = snap(piece["b"])
            if not on_axis(a) and not on_axis(b):
                out.append({**piece, "a": a, "b": b})
                continue
            circle = circle_through(a, piece["m"], b)
            done = False
            if circle:
                dc = off(circle["center"])
                lim = max(POLE_CENTRE_MM, circle["radius"] / 1000)
                if 0 < dc <= lim:
                    along = dot(d, sub(rel(b), rel(a)))
                    t = (dot(rel(b), rel(b)) - dot(rel(a), rel(a))) / (2 * along) if abs(along) > 1e-12 else math.nan
                    c = add_scaled(origin, d, t)
                    r = length(sub(a, c))
                    outward = normalize(sub(piece["m"], c))
                    if math.isfinite(t) and outward and length(sub(c, circle["center"])) <= 10 * lim:
                        m = add_scaled(c, outward, r)
                        moved = length(sub(m, piece["m"]))
                        if dc > POLE_QUIET_MM:
                            who = f"arc {_n(e)}" if e is not None else "an arc"
                            mends.append({"piece": e, "what": f"{who} ending on the axis had its centre {_um(dc)} off it — re-pointed through its ends with the centre on the axis, a sphere; its middle moved {_um(moved)}",
                                          "movedMm": moved})
                        out.append({**piece, "a": a, "m": m, "b": b})
                        done = True
            if not done:
                out.append({**piece, "a": b, "b": a} if on_axis(b) and not on_axis(a) else {**piece, "a": a, "b": b})
        return out

    result = []
    for p in profiles:
        pts = _loop_points(p["outer"])
        normal = _newell(pts)
        if not normal or not pts or abs(dot(normal, d)) > 1e-9 or abs(dot(rel(pts[0]), normal)) > 1e-6:
            result.append(p)
        else:
            result.append({"outer": mend_loop(p["outer"]), "holes": [mend_loop(h) for h in p["holes"]]})
    return {"profiles": result, "mends": mends}


def pole_words(mends):
    return f"Made to meet the revolve's axis as a pole a STEP reader keeps: {'; '.join(m['what'] for m in mends)}."


def side_of(plane, point):
    """The side of a plane the point is on: +1 with its normal, -1 against."""
    x = dot([point[0] - plane["origin"][0], point[1] - plane["origin"][1], point[2] - plane["origin"][2]], plane["normal"])
    return 1 if x >= 0 else -1


# ---- near-tangent joins before a draft ------------------------------------------------

MEND_MAX_DEG = 0.5
MEND_MAX_RAD = (MEND_MAX_DEG * math.pi) / 180
MEND_MIN_RAD = 1e-5
MEND_MAX_MOVE_MM = 0.05
MERGE_MAX_MM = 0.01


def _sub2(a, b):
    return [a[0] - b[0], a[1] - b[1]]


def _dot2(a, b):
    return a[0] * b[0] + a[1] * b[1]


def _cross2(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _dist2(a, b):
    return js_hypot(a[0] - b[0], a[1] - b[1])


def _unit2(a):
    ln = js_hypot(a[0], a[1])
    return [a[0] / ln, a[1] / ln] if ln > 1e-15 else None


def _microns(mm):
    return f"{_n(js_round(mm * 1000 * 10) / 10)} µm"


def _deg_words(deg):
    return f"{_n(precision_number(deg, 2))}°"


def _plane_of(pieces):
    pts = [q for p in pieces for q in piece_points(p)]
    normal = _newell(pts) if pts else None
    if not normal:
        return None
    u = normalize(cross(normal, [1, 0, 0] if abs(normal[0]) < 0.9 else [0, 1, 0]))
    if not u:
        return None
    v = cross(normal, u)
    o = pts[0]
    return {"to2": lambda p: [dot(sub(p, o), u), dot(sub(p, o), v)], "to3": lambda p: add_scaled(add_scaled(o, u, p[0]), v, p[1])}


def _geo2(p, plane):
    to2 = plane["to2"]
    if p["kind"] == "line":
        return {"kind": "line", "a": to2(p["a"]), "b": to2(p["b"])}
    if p["kind"] == "spline":
        return {"kind": "spline", "poles": [to2(q) for q in p["poles"]]} if len(p["poles"]) >= 4 else {"kind": "other"}
    if p["kind"] != "arc":
        return {"kind": "other"}
    a = to2(p["a"])
    m = to2(p["m"])
    b = to2(p["b"])
    m1 = _sub2(m, a)
    b1 = _sub2(b, a)
    den = 2 * _cross2(m1, b1)
    if abs(den) < 1e-14:
        return {"kind": "other"}
    mm = _dot2(m1, m1)
    bb = _dot2(b1, b1)
    c = [a[0] + (b1[1] * mm - m1[1] * bb) / den, a[1] + (m1[0] * bb - b1[0] * mm) / den]
    return {"kind": "arc", "a": a, "b": b, "c": c, "r": (_dist2(a, c) + _dist2(b, c) + _dist2(m, c)) / 3, "ccw": den > 0}


def _start_of(g):
    return g["a"] if g["kind"] in ("line", "arc") else g["poles"][0] if g["kind"] == "spline" else None


def _end_of(g):
    return g["b"] if g["kind"] in ("line", "arc") else g["poles"][-1] if g["kind"] == "spline" else None


def _tangent_of(g, at_end):
    if g["kind"] == "line":
        return _unit2(_sub2(g["b"], g["a"]))
    if g["kind"] == "spline":
        p = g["poles"]
        return _unit2(_sub2(p[-1], p[-2])) if at_end else _unit2(_sub2(p[1], p[0]))
    if g["kind"] != "arc":
        return None
    rad = _unit2(_sub2(g["b"] if at_end else g["a"], g["c"]))
    if not rad:
        return None
    return [-rad[1], rad[0]] if g["ccw"] else [rad[1], -rad[0]]


def _sweep_of(g):
    ta = math.atan2(g["a"][1] - g["c"][1], g["a"][0] - g["c"][0])
    tb = math.atan2(g["b"][1] - g["c"][1], g["b"][0] - g["c"][0])
    turn = 2 * math.pi
    return fmod(fmod(tb - ta, turn) + turn, turn) if g["ccw"] else -fmod(fmod(ta - tb, turn) + turn, turn)


def _mid_of(g):
    t = math.atan2(g["a"][1] - g["c"][1], g["a"][0] - g["c"][0]) + _sweep_of(g) / 2
    return [g["c"][0] + g["r"] * math.cos(t), g["c"][1] + g["r"] * math.sin(t)]


def _crease_at(slots, i):
    n = len(slots)
    g = slots[i % n]["g"]
    h = slots[(i + 1) % n]["g"]
    e = _end_of(g)
    s = _start_of(h)
    if e is None or s is None or _dist2(e, s) > 1e-3:
        return None
    t1 = _tangent_of(g, True)
    t0 = _tangent_of(h, False)
    return math.atan2(abs(_cross2(t1, t0)), _dot2(t1, t0)) if t1 and t0 else None


def _fillet_arc(arc, prev, nxt):
    def bound(g, join_at_end):
        if g["kind"] == "line":
            far = g["a"] if join_at_end else g["b"]
            u = _unit2(_sub2(g["b"], g["a"]) if join_at_end else _sub2(g["a"], g["b"]))
            if not u:
                return None
            nrm = [-u[1], u[0]]
            lean = _dot2(nrm, _sub2(arc["c"], far))
            side = -1 if lean < 0 else 1

            def foot(c):
                x = _dot2(nrm, _sub2(c, far))
                return [c[0] - nrm[0] * x, c[1] - nrm[1] * x]

            return {"gap": lambda c: side * _dot2(nrm, _sub2(c, far)) - arc["r"], "grad": lambda c: [side * nrm[0], side * nrm[1]], "foot": foot}
        if g["kind"] == "arc":
            d0 = _dist2(arc["c"], g["c"])
            options = [t for t in (g["r"] + arc["r"], g["r"] - arc["r"], arc["r"] - g["r"]) if t > 0]
            reach = options[0]
            for y in options[1:]:
                if abs(y - d0) < abs(reach - d0):
                    reach = y

            def out(c):
                return _unit2(_sub2(c, g["c"])) or [1, 0]

            def foot(c):
                u = out(c)
                return [g["c"][0] + u[0] * g["r"], g["c"][1] + u[1] * g["r"]]

            return {"gap": lambda c: _dist2(c, g["c"]) - reach, "grad": out, "foot": foot}
        return None

    A = bound(prev, True)
    B = bound(nxt, False)
    if not A or not B:
        return None
    c = [arc["c"][0], arc["c"][1]]
    for _ in range(40):
        f1 = A["gap"](c)
        f2 = B["gap"](c)
        if abs(f1) < 1e-12 and abs(f2) < 1e-12:
            break
        g1 = A["grad"](c)
        g2 = B["grad"](c)
        det = _cross2(g1, g2)
        if abs(det) < 1e-6:
            return None
        c = [c[0] + (-f1 * g2[1] + f2 * g1[1]) / det, c[1] + (-g1[0] * f2 + g2[0] * f1) / det]
    if abs(A["gap"](c)) > 1e-9 or abs(B["gap"](c)) > 1e-9:
        return None
    made = {**arc, "c": c, "a": A["foot"](c), "b": B["foot"](c)}
    if abs(_sweep_of(made) - _sweep_of(arc)) > 0.05:
        return None
    return {"arc": made, "moved": max(_dist2(c, arc["c"]), _dist2(made["a"], arc["a"]), _dist2(made["b"], arc["b"]), _dist2(_mid_of(made), _mid_of(arc)))}


def _tangent_at_one_end(arc, at_start, t):
    e = arc["a"] if at_start else arc["b"]
    q = arc["b"] if at_start else arc["a"]
    n = [-t[1], t[0]] if arc["ccw"] else [t[1], -t[0]]
    w = _sub2(q, e)
    den = 2 * _dot2(n, w)
    if abs(den) < 1e-12:
        return None
    s = _dot2(w, w) / den
    if not (s > 0):
        return None
    made = {**arc, "c": [e[0] + n[0] * s, e[1] + n[1] * s], "r": s}
    if abs(_sweep_of(made) - _sweep_of(arc)) > 0.05:
        return None
    return {"arc": made, "moved": _dist2(_mid_of(made), _mid_of(arc))}


def _mend_one(slots, near, mends):
    n = len(slots)

    def at(i):
        return i % n

    def tangentish(c):
        return c is not None and c < MEND_MAX_RAD

    def ident(i):
        return slots[at(i)]["src"].get("entity")

    def name(i):
        return f" {_n(ident(i))}" if ident(i) is not None else ""

    def off_of(*joins):
        return max(near.get(at(j), 0) for j in joins) * (180 / math.pi)

    arcs = [i for i in range(n) if slots[i]["g"]["kind"] == "arc" and (at(i - 1) in near or i in near)]
    arcs.sort(key=lambda i: slots[i]["g"]["r"])
    for i in arcs:
        arc = slots[i]["g"]
        pi = at(i - 1)
        ni = at(i + 1)
        prev = slots[pi]["g"]
        nxt = slots[ni]["g"]
        c_prev = _crease_at(slots, pi)
        c_next = _crease_at(slots, i)
        if pi != ni and tangentish(c_prev) and tangentish(c_next):
            f = _fillet_arc(arc, prev, nxt)
            if f and f["moved"] <= MEND_MAX_MOVE_MM:
                slots[i]["g"] = f["arc"]
                if prev["kind"] in ("line", "arc"):
                    slots[pi]["g"] = {**prev, "b": f["arc"]["a"]}
                if nxt["kind"] in ("line", "arc"):
                    slots[ni]["g"] = {**nxt, "a": f["arc"]["b"]}
                slots[i]["moved"] = slots[pi]["moved"] = slots[ni]["moved"] = True
                joins = [j for j in (pi, i) if j in near]
                pieces = [ident(pi), ident(i), ident(ni)] if len(joins) == 2 else [ident(pi), ident(i)] if joins[0] == pi else [ident(i), ident(ni)]
                mends.append({"pieces": pieces, "deg": off_of(*joins), "what": f"arc{name(i)} made tangent to both neighbours at its radius", "movedMm": f["moved"]})
                return True
            if prev["kind"] != "spline" and nxt["kind"] != "spline":
                continue
        for join, at_start in ((pi, True), (i, False)):
            other = c_next if at_start else c_prev
            other_piece = nxt if at_start else prev
            if join not in near or (tangentish(other) and other_piece["kind"] != "spline"):
                continue
            t = _tangent_of(prev, True) if at_start else _tangent_of(nxt, False)
            f = t and _tangent_at_one_end(arc, at_start, t)
            if not f or f["moved"] > MEND_MAX_MOVE_MM:
                continue
            slots[i]["g"] = f["arc"]
            slots[i]["moved"] = True
            mends.append({"pieces": [ident(pi), ident(i)] if at_start else [ident(i), ident(ni)], "deg": off_of(join),
                          "what": f"arc{name(i)} redrawn through its ends, tangent to{name(pi if at_start else ni)}", "movedMm": f["moved"]})
            return True
    for j in near:
        g = slots[j]["g"]
        h = slots[at(j + 1)]["g"]
        if g["kind"] != "line" or h["kind"] != "line" or at(j + 1) == j:
            continue
        run = _unit2(_sub2(h["b"], g["a"]))
        if not run:
            continue
        off = abs(_cross2(run, _sub2(g["b"], g["a"])))
        if off > MERGE_MAX_MM:
            continue
        mends.append({"pieces": [ident(j), ident(j + 1)], "deg": off_of(j), "what": f"lines{name(j)} and{name(j + 1)} made one", "movedMm": off})
        slots[j]["g"] = {"kind": "line", "a": g["a"], "b": h["b"]}
        slots[j]["moved"] = True
        slots.pop(at(j + 1))
        return True
    for j in near:
        g = slots[j]["g"]
        h = slots[at(j + 1)]["g"]
        which = "next" if h["kind"] == "spline" and g["kind"] != "other" else "prev" if g["kind"] == "spline" and h["kind"] != "other" else None
        if not which:
            continue
        sp = h if which == "next" else g
        t = _tangent_of(g, True) if which == "next" else _tangent_of(h, False)
        if not t:
            continue
        k = 1 if which == "next" else len(sp["poles"]) - 2
        e = sp["poles"][0 if which == "next" else len(sp["poles"]) - 1]
        along = _dot2(_sub2(sp["poles"][k], e), t)
        if (along <= 0) if which == "next" else (along >= 0):
            continue
        pole = [e[0] + t[0] * along, e[1] + t[1] * along]
        moved = _dist2(pole, sp["poles"][k])
        if moved > MEND_MAX_MOVE_MM:
            continue
        poles = list(sp["poles"])
        poles[k] = pole
        si = at(j + 1) if which == "next" else j
        slots[si]["g"] = {"kind": "spline", "poles": poles}
        slots[si]["moved"] = True
        mends.append({"pieces": [ident(j), ident(j + 1)], "deg": off_of(j),
                      "what": f"spline{name(si)}'s {'first' if which == 'next' else 'last'} pole put in line with{name(j if which == 'next' else j + 1)}", "movedMm": moved})
        return True
    return False


def _mend_loop(pieces, plane, mends, left):
    if len(pieces) < 2:
        return pieces
    slots = [{"src": src, "g": _geo2(src, plane), "moved": False} for src in pieces]

    def near_joins():
        out = {}
        for i in range(len(slots)):
            c = _crease_at(slots, i)
            if c is not None and MEND_MIN_RAD < c < MEND_MAX_RAD:
                out[i] = c
        return out

    for _ in range(2 * len(pieces) + 2):
        near = near_joins()
        if not near or not _mend_one(slots, near, mends):
            break
    n = len(slots)
    for i, c in near_joins().items():
        left.append({"from": slots[i]["src"].get("entity"), "to": slots[(i + 1) % n]["src"].get("entity"), "deg": (c * 180) / math.pi, "at": plane["to3"](_end_of(slots[i]["g"]))})
    if n == len(pieces) and not any(s["moved"] for s in slots):
        return pieces

    def src_end(p, end):
        if p["kind"] in ("line", "arc"):
            return p[end]
        if p["kind"] == "spline":
            return p["poles"][0 if end == "a" else -1]
        return None

    out = []
    for i, s in enumerate(slots):
        if not s["moved"]:
            out.append(s["src"])
            continue
        prev = slots[(i - 1 + n) % n]
        nxt = slots[(i + 1) % n]
        a = (not prev["moved"] and src_end(prev["src"], "b")) or plane["to3"](_start_of(s["g"]))
        b = (not nxt["moved"] and src_end(nxt["src"], "a")) or plane["to3"](_end_of(s["g"]))
        entity = {"entity": s["src"]["entity"]} if s["src"].get("entity") is not None else {}
        g = s["g"]
        if g["kind"] == "line":
            out.append({"kind": "line", "a": a, "b": b, **entity})
        elif g["kind"] == "arc":
            out.append({"kind": "arc", "a": a, "m": plane["to3"](_mid_of(g)), "b": b, **entity})
        elif g["kind"] == "spline" and s["src"]["kind"] == "spline":
            last = len(g["poles"]) - 1
            out.append({**s["src"], "poles": [a if k == 0 else b if k == last else plane["to3"](p) for k, p in enumerate(g["poles"])]})
        else:
            out.append(s["src"])
    return out


def mend_near_tangent(profiles):
    """A drafted extrude's profiles with every near-tangent join made
    tangent: {profiles, mends, left}."""
    mends = []
    left = []
    out = []
    for p in profiles:
        plane = _plane_of(p["outer"])
        if not plane:
            out.append(p)
            continue
        out.append({"outer": _mend_loop(p["outer"], plane, mends, left), "holes": [_mend_loop(h, plane, mends, left) for h in p["holes"]]})
    return {"profiles": out, "mends": mends, "left": left}


def mend_words(mends):
    def pieces(ids):
        return f"pieces {' → '.join(_n(x) for x in ids)}" if all(x is not None for x in ids) else "two pieces"

    said = [f"{pieces(m['pieces'])} met {_deg_words(m['deg'])} off tangent — {m['what']}, moved {_microns(m['movedMm'])}" for m in mends]
    return f"Made tangent before the draft, which cannot join faces meeting at a grazing angle: {'; '.join(said)}."


def grazing_joins_words(left):
    def where(p):
        return f"({', '.join(_n(js_round(x * 100) / 100) for x in p)})"

    named = sorted(left, key=lambda j: j["deg"])[:3]

    def one(j, first):
        if j.get("from") is not None and j.get("to") is not None:
            who = f"{'Pieces' if first else 'pieces'} {_n(j['from'])} → {_n(j['to'])}"
        else:
            who = f"{'Two' if first else 'two'} pieces"
        return f"{who} meet {_deg_words(j['deg'])} off tangent at {where(j['at'])}"

    more = f" (and {len(left) - len(named)} more)" if len(left) > len(named) else ""
    they = "their faces meet" if len(named) == 1 else "the faces there meet"
    return (f"{'; '.join(one(j, i == 0) for i, j in enumerate(named))}{more}: drafted, {they} at a grazing angle the kernel cannot join, and making {'it' if len(named) == 1 else 'them'} "
            f"tangent here would move more than {_n(MEND_MAX_MOVE_MM)} mm — make them tangent (reverse.sketch.edit rounds, a tangent relation) or a real corner (≥ 0.2°).")
