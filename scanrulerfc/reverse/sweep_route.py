# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/core/sweepRoute.ts
# SPDX-License-Identifier: AGPL-3.0-only
#
# A sweep's route: a centreline in the part's frame whose inner points are
# corners rounded with tangent arcs (where the straights either side would
# meet, not a point on the arc), as the straights and arcs a sweep follows.

import math

from ._js import js_round, num_str
from .vec import add_scaled, dot, length, normalize, scale, sub

SAME_POINT_MM = 1e-3
STRAIGHT_DEG = 0.1
FOLD_DEG = 179.9
NO_STRAIGHT_MM = 1e-3


def _r3(x):
    return js_round(x * 1000) / 1000 or 0


def _point_words(i, p):
    return f"points[{i}] ({', '.join(num_str(_r3(x)) for x in p)})"


def _turn_of(a, b):
    return math.acos(max(-1, min(1, dot(a, b))))


def route_pieces(route, frm):
    """The route as straights and tangent arcs run from the end nearest
    `frm`: {pieces, start, tangent, bends}; or why not, in words."""
    points = route["points"]
    bend_radius = route["bendRadius"]
    radii = route.get("radii")
    if len(points) < 2:
        return "The route needs two points at least."
    if radii is not None and len(radii) != len(points) - 2:
        return f"The route has {len(points) - 2} inner points and {len(radii)} radii — one for each inner point, null for the bend radius."
    kept = [0]
    for i in range(1, len(points)):
        if length(sub(points[i], points[kept[-1]])) >= SAME_POINT_MM:
            kept.append(i)
    if len(kept) < 2:
        return "The route’s points are all one point."
    if length(sub(points[0], points[kept[-1]])) < SAME_POINT_MM:
        return "The route ends where it starts — a route has two ends; a closed path is a sketch’s, drawn as arcs."
    j = 1
    while j < len(kept) - 1:
        into = normalize(sub(points[kept[j]], points[kept[j - 1]]))
        out = normalize(sub(points[kept[j + 1]], points[kept[j]]))
        turn = (_turn_of(into, out) * 180) / math.pi
        if turn > FOLD_DEG:
            return f"The route folds back on itself at {_point_words(kept[j], points[kept[j]])}."
        if turn < STRAIGHT_DEG:
            kept.pop(j)
        else:
            j += 1
    at = [points[i] for i in kept]
    dirs = [normalize(sub(p, at[j])) for j, p in enumerate(at[1:])]
    runs = [length(sub(p, at[j])) for j, p in enumerate(at[1:])]
    corners = []
    for j, index in enumerate(kept):
        if j == 0 or j == len(kept) - 1:
            corners.append({"index": index, "turn": 0, "radius": 0, "slope": 0, "reach": 0})
            continue
        turn = _turn_of(dirs[j - 1], dirs[j])
        given = radii[index - 1] if radii is not None and index - 1 < len(radii) else None
        radius = bend_radius if given is None else given
        corners.append({"index": index, "turn": turn, "radius": radius, "slope": math.tan(turn / 2), "reach": radius * math.tan(turn / 2)})
    for j in range(1, len(kept) - 1):
        c = corners[j]
        if not (c["radius"] > 0):
            return f"The bend at {_point_words(c['index'], at[j])} needs a radius above 0 — a route’s corners are rounded, a sharp one has no section to carry round it."
        before = runs[j - 1] - corners[j - 1]["reach"]
        after = runs[j] - corners[j + 1]["reach"]
        if c["reach"] <= min(before, after) + NO_STRAIGHT_MM:
            continue
        room = max(0, min(before, after))
        straight = f"straight to {_point_words(kept[j + 1], at[j + 1])}" if after < before else f"straight from {_point_words(kept[j - 1], at[j - 1])}"
        most = math.floor((room / c["slope"]) * 1000) / 1000
        return (f"The bend at {_point_words(c['index'], at[j])} does not fit: a radius of {num_str(_r3(c['radius']))} mm turning {num_str(_r3((c['turn'] * 180) / math.pi))}° "
                f"takes {num_str(_r3(c['reach']))} mm of each straight, and the {straight} leaves it {num_str(_r3(room))} mm. It takes a radius of {num_str(most)} mm at most, its neighbours as they are.")
    pieces = []
    was = at[0]
    for j in range(1, len(at)):
        c = corners[j]
        end = add_scaled(at[j], dirs[j - 1], -c["reach"])
        if length(sub(end, was)) > NO_STRAIGHT_MM:
            pieces.append({"kind": "line", "a": was, "b": end})
            was = end
        if j == len(at) - 1:
            break
        inward = normalize(sub(dirs[j], dirs[j - 1]))
        exit_ = add_scaled(at[j], dirs[j], c["reach"])
        pieces.append({"kind": "arc", "a": was, "m": add_scaled(at[j], inward, c["radius"] * (1 / math.cos(c["turn"] / 2) - 1)), "b": exit_})
        was = exit_
    from_end = length(sub(at[-1], frm)) < length(sub(at[0], frm))
    bends = [{"index": c["index"], "radius": c["radius"]} for c in corners[1:-1]]
    if from_end:
        back = []
        for p in reversed(pieces):
            if p["kind"] == "line":
                back.append({"kind": "line", "a": p["b"], "b": p["a"]})
            else:
                back.append({"kind": "arc", "a": p["b"], "m": p["m"], "b": p["a"]})
        return {"pieces": back, "start": at[-1], "tangent": scale(dirs[-1], -1), "bends": bends}
    return {"pieces": pieces, "start": at[0], "tangent": dirs[0], "bends": bends}
