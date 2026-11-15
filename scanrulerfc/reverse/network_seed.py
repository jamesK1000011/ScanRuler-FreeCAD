# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/core/networkSeed.ts
# SPDX-License-Identifier: AGPL-3.0-only
#
# A point well inside a loop drawn on the scan: the seed a patch placed by
# its corners is filled at. The cell reader takes a region by the point
# inside it, and the patch's corners move afterwards, so the seed is put as
# far from the loop as it can be, not just over its first edge.
#
# The loop is seen along the way it faces: its vector area (Newell's),
# turned to agree with the scan's normals along it, each by the length of
# loop it stands for. Seen so, the loop is flattened onto the plane across
# it, and the point of that polygon farthest from its sides is found on a
# grid (the middle of a square, the inside of an L's corner, not its
# centroid, which an L or a U puts outside). That point is taken back onto
# the scan along the normal: of the scan's crossings with the line there,
# the one nearest the plane among those facing the loop's way, so a loop
# round the outside of a shell takes the outer skin, not the inner wall.
#
# A loop the flattening folds over (a strip round more than half a
# cylinder) has no such polygon; nor has one whose seed, so found, comes out
# within MARGIN_EDGES of the loop. Then the seed is stepped in from the
# loop's sides, across them on the scan, to the farthest that stays inside
# the polygon there.

import math

import numpy as np

from ._js import js_hypot
from .network_spline import hypot3_v

GRID = 24
MARGIN_EDGES = 2
MAX_POINTS = 400


def _sub(a, b):
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def _unit(a):
    l = js_hypot(a[0], a[1], a[2])
    return [a[0] / l, a[1] / l, a[2] / l] if l > 0 else [0.0, 0.0, 1.0]


def seed_inside(scan, outline):
    """A point on the scan inside a closed loop of points on it (x, y, z
    each, the last joined to the first), or None for a loop too small."""
    outline = np.asarray(outline, dtype=float).reshape(-1)
    total = outline.shape[0] // 3
    if total < 3:
        return None
    stride = max(1, math.ceil(total / MAX_POINTS))
    pts = [outline[i * 3:i * 3 + 3].tolist() for i in range(0, total, stride)]
    m = len(pts)
    if m < 3:
        return None
    c = [0.0, 0.0, 0.0]
    for p in pts:
        for k in range(3):
            c[k] += p[k] / m
    n = [0.0, 0.0, 0.0]
    for i in range(m):
        w = _cross(_sub(pts[i], c), _sub(pts[(i + 1) % m], c))
        for k in range(3):
            n[k] += w[k] / 2
    nl = js_hypot(n[0], n[1], n[2])
    if not nl > 0:
        return None
    n = [x / nl for x in n]
    lean = 0.0
    for i in range(m):
        on = scan.closest_inside(pts[i])
        if on is not None:
            lean += _dot(scan.triangle_normal(on.triangle), n) * js_hypot(*_sub(pts[(i + 1) % m], pts[i]))
    if lean < 0:
        n = [-x for x in n]
    u = _unit(_cross(n, [1, 0, 0]) if abs(n[0]) < 0.9 else _cross(n, [0, 1, 0]))
    v = _cross(n, u)
    xs = [_dot(_sub(p, c), u) for p in pts]
    ys = [_dot(_sub(p, c), v) for p in pts]
    margin = MARGIN_EDGES * scan.edge
    flat = _farthest_inside(xs, ys)
    if flat is not None and flat["distance"] > margin:
        base = [c[k] + flat["x"] * u[k] + flat["y"] * v[k] for k in range(3)]
        hit = _along_normal(scan, base, n, pts)
        if hit is not None and _nearest_of(hit, pts) > margin:
            inside = scan.closest_inside(hit)
            return inside.point if inside is not None else hit
    return _stepped_in(scan, pts, c, n, u, v, xs, ys)


def _inside_polygon_v(X, Y, x, y):
    """insidePolygon for arrays of points (x, y)."""
    inside = np.zeros(np.shape(x), dtype=bool)
    j = len(X) - 1
    for i in range(len(X)):
        xi, yi, xj, yj = X[i], Y[i], X[j], Y[j]
        with np.errstate(divide="ignore", invalid="ignore"):
            cond = ((yi > y) != (yj > y)) & (x < ((xj - xi) * (y - yi)) / (yj - yi) + xi)
        inside ^= cond
        j = i
    return inside


def _inside_polygon(X, Y, x, y):
    inside = False
    j = len(X) - 1
    for i in range(len(X)):
        if (Y[i] > y) != (Y[j] > y) and x < ((X[j] - X[i]) * (y - Y[i])) / (Y[j] - Y[i]) + X[i]:
            inside = not inside
        j = i
    return inside


def _polygon_distance_v(X, Y, x, y):
    best = np.full(np.shape(x), math.inf)
    j = len(X) - 1
    for i in range(len(X)):
        dx = X[i] - X[j]
        dy = Y[i] - Y[j]
        l2 = dx * dx + dy * dy
        t = np.clip(((x - X[j]) * dx + (y - Y[j]) * dy) / l2, 0, 1) if l2 > 0 else np.zeros(np.shape(x))
        ex = X[j] + t * dx - x
        ey = Y[j] + t * dy - y
        best = np.minimum(best, hypot3_v(ex, ey, np.zeros(np.shape(x))))
        j = i
    return best


def _farthest_inside(xs, ys):
    X = np.array(xs)
    Y = np.array(ys)
    x0, x1, y0, y1 = float(X.min()), float(X.max()), float(Y.min()), float(Y.max())
    best = [None]

    def search(ax, bx, ay, by):
        i = np.arange(GRID)
        gx = ax + ((i + 0.5) / GRID) * (bx - ax)
        gy = ay + ((i + 0.5) / GRID) * (by - ay)
        PX, PY = np.meshgrid(gx, gy, indexing="ij")
        PX = PX.ravel()
        PY = PY.ravel()
        ins = _inside_polygon_v(xs, ys, PX, PY)
        if not ins.any():
            return
        d = _polygon_distance_v(xs, ys, PX[ins], PY[ins])
        k = int(np.argmax(d))
        if best[0] is None or d[k] > best[0]["distance"]:
            best[0] = {"x": float(PX[ins][k]), "y": float(PY[ins][k]), "distance": float(d[k])}

    search(x0, x1, y0, y1)
    if best[0] is None:
        return None
    hx = (x1 - x0) / GRID
    hy = (y1 - y0) / GRID
    x = best[0]["x"]
    y = best[0]["y"]
    search(x - hx, x + hx, y - hy, y + hy)
    return best[0]


def _along_normal(scan, base, n, pts):
    reach = 0.0
    for p in pts:
        reach = max(reach, js_hypot(p[0] - base[0], p[1] - base[1], p[2] - base[2]))
    reach += 4 * scan.edge
    lo = [min(base[k] - reach * n[k], base[k] + reach * n[k]) - scan.edge for k in range(3)]
    hi = [max(base[k] - reach * n[k], base[k] + reach * n[k]) + scan.edge for k in range(3)]
    ts = scan.triangles_in(lo, hi)
    if ts.size == 0:
        return None
    F = scan.F[ts]
    A = scan.P[F[:, 0]]
    B = scan.P[F[:, 1]]
    C = scan.P[F[:, 2]]
    o = np.asarray(base, dtype=float)
    d = np.asarray(n, dtype=float)
    e1 = B - A
    e2 = C - A
    h = np.cross(d, e2)
    det = (e1 * h).sum(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        s = o - A
        uu = (s * h).sum(axis=1) / det
        q = np.cross(s, e1)
        vv = (q * d).sum(axis=1) / det
        t = (e2 * q).sum(axis=1) / det
    ok = ~(np.abs(det) < 1e-12) & ~(uu < 0) & ~(uu > 1) & ~(vv < 0) & ~(uu + vv > 1)
    if not ok.any():
        return None
    normals = scan.triangle_normals()[ts]
    facing = ok & ((normals * d).sum(axis=1) > 0.2)

    def first_min(mask):
        idx = np.nonzero(mask)[0]
        if idx.size == 0:
            return None
        return float(t[idx[int(np.argmin(np.abs(t[idx])))]])

    hit = first_min(facing)
    if hit is None:
        hit = first_min(ok)
    return [base[k] + hit * n[k] for k in range(3)]


def _stepped_in(scan, pts, c, n, u, v, xs, ys):
    m = len(pts)
    area = 0.0
    for i in range(m):
        area += xs[i] * ys[(i + 1) % m] - xs[(i + 1) % m] * ys[i]
    sign = 1 if area >= 0 else -1
    width = 0.0
    for p in pts:
        width = max(width, js_hypot(*_sub(p, pts[0])))
    best = None
    for j in range(12):
        i = (j * m) // 12
        p = pts[i]
        t = _sub(pts[(i + 1) % m], pts[(i - 1 + m) % m])
        on = scan.closest_inside(p)
        normal = scan.triangle_normal(on.triangle) if on is not None else n
        left = _unit(_cross(normal, t))
        step = width / 5
        while step > scan.edge:
            q = [p[k] + sign * step * left[k] for k in range(3)]
            back = scan.closest_inside(q)
            if back is None:
                break
            r = back.point
            if not _inside_polygon(xs, ys, _dot(_sub(r, c), u), _dot(_sub(r, c), v)):
                step /= 2
                continue
            d = _nearest_of(r, pts)
            if best is None or d > best["distance"]:
                best = {"at": r, "distance": d}
            break
    if best is not None:
        return best["at"]
    inside = scan.closest_inside(pts[0])
    return inside.point if inside is not None else None


def _nearest_of(p, pts):
    best = math.inf
    for q in pts:
        best = min(best, js_hypot(p[0] - q[0], p[1] - q[1], p[2] - q[2]))
    return best
