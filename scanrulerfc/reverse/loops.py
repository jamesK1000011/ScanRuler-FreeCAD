# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/core/loops.ts (and circleThrough from kernelMath.ts)
# SPDX-License-Identifier: AGPL-3.0-only
#
# The loops a profile is drawn from: a polygon or a rectangle as pieces, an
# arc as a piece, the points along a piece, and a loop's middle. A loop
# piece is a dict: {kind: line, a, b}, {kind: arc, a, m, b}, {kind: circle,
# center, normal, radius} or {kind: spline, poles, knots, mults}, with an
# optional `entity`, the sketch piece it was lifted from. A profile is
# {outer: [piece], holes: [[piece]]}.

import math

from .sketch_spline import bspline_samples
from .vec import add, add_scaled, cross, dot, length, normalize, scale, sub


def circle_through(a, b, c):
    """The circle through three points: centre, radius, and the axis a → b
    → c runs counter-clockwise about; None for points in a line."""
    ab = sub(b, a)
    ac = sub(c, a)
    n = cross(ab, ac)
    nn = dot(n, n)
    if nn < 1e-18:
        return None
    t = scale(sub(scale(cross(n, ab), dot(ac, ac)), scale(cross(n, ac), dot(ab, ab))), 1 / (2 * nn))
    return {"center": add(a, t), "radius": length(t), "axis": normalize(n) or [0, 0, 1]}


def polygon_loop(points):
    return [{"kind": "line", "a": p, "b": points[(i + 1) % len(points)]} for i, p in enumerate(points)]


def rectangle_loop(origin, u, v, w, h):
    p1 = add_scaled(origin, u, w)
    return polygon_loop([origin, p1, add_scaled(p1, v, h), add_scaled(origin, v, h)])


def piece_points(piece, step=math.pi / 64):
    """Points along a loop's piece, its ends included: a line's two ends, an
    arc or a circle every `step` radians at most (a circle's last point is
    its first)."""
    k = piece["kind"]
    if k == "line":
        return [piece["a"], piece["b"]]
    if k == "spline":
        return bspline_samples(piece, max(16, 8 * (len(piece["knots"]) - 1)))
    if k == "circle":
        circle = {"center": piece["center"], "radius": piece["radius"], "axis": normalize(piece["normal"]) or [0, 0, 1]}
    else:
        circle = circle_through(piece["a"], piece["m"], piece["b"])
    if not circle:
        return [piece["a"], piece["m"], piece["b"]] if k == "arc" else [piece["center"]]
    center, radius, axis = circle["center"], circle["radius"], circle["axis"]
    if k == "arc":
        start = piece["a"]
    else:
        start = add_scaled(center, normalize(cross(axis, [1, 0, 0] if abs(axis[0]) < 0.9 else [0, 1, 0])) or [1, 0, 0], radius)
    u = normalize(sub(start, center)) or [1, 0, 0]
    v = cross(axis, u)

    def angle_of(p):
        a = math.atan2(dot(sub(p, center), v), dot(sub(p, center), u))
        return a + 2 * math.pi if a <= 0 else a

    sweep = angle_of(piece["b"]) if k == "arc" else 2 * math.pi
    n = max(2, math.ceil(sweep / step))
    out = []
    for i in range(n + 1):
        t = (sweep * i) / n
        out.append(add(center, add_scaled(scale(u, radius * math.cos(t)), v, radius * math.sin(t))))
    return out


def loop_middle(loop):
    """The middle of a loop by its length; of a ring, its centre."""
    total_sum = [0, 0, 0]
    total = 0
    for piece in loop:
        pts = piece_points(piece)
        for i in range(len(pts) - 1):
            ln = length(sub(pts[i + 1], pts[i]))
            total_sum = add_scaled(total_sum, add(pts[i], pts[i + 1]), ln / 2)
            total += ln
    if total > 0:
        return scale(total_sum, 1 / total)
    if not loop:
        return [0, 0, 0]
    first = loop[0]
    return first["center"] if first["kind"] == "circle" else first["poles"][0] if first["kind"] == "spline" else first["a"]


def arc_piece(center, normal, a, b, sweep):
    """The arc through a and b about `center`, `sweep` radians
    counter-clockwise about `normal`, named by its midpoint."""
    n = normalize(normal) or [0, 0, 1]
    ra = sub(a, center)
    r = length(ra)
    u = normalize(ra) or [1, 0, 0]
    v = cross(n, u)
    half = sweep / 2
    return {"kind": "arc", "a": a, "m": add(center, add_scaled(scale(u, r * math.cos(half)), v, r * math.sin(half))), "b": b}
