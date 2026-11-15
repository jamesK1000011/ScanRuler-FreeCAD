# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/core/sketchSpline.ts (with src/core/flat/spline.ts)
# SPDX-License-Identifier: AGPL-3.0-only
#
# A sketch spline: a curve through its points, each stretch a cubic
# Hermite piece with the tangents a natural spline gives (an end held to a
# direction where startDir/endDir say), read by a parameter t that counts
# the stretches - t in [k, k+1] is the k-th. A fit is a dict as the
# original's FlatSplineFit: points, tangents, fixed, closed, length.

import math

from ._js import js_hypot

import numpy as np

HANDLE_REACH = 1 / 3


class SplineError(ValueError):
    pass


# ---- src/core/flat/spline.ts --------------------------------------------------------


def spline_segment_count(point_count, closed):
    return point_count if closed else point_count - 1


def _chords(points, closed):
    n = len(points)
    out = []
    for k in range(spline_segment_count(n, closed)):
        a = points[k]
        b = points[(k + 1) % n]
        out.append(js_hypot(b[0] - a[0], b[1] - a[1]))
    return out


def _reaches(points, closed, h):
    n = len(points)
    out = []
    for i in range(n):
        before = h[(i - 1 + n) % n] if closed else (h[i - 1] if i > 0 else None)
        after = h[i % n] if closed else (h[i] if i < n - 1 else None)
        if before is not None and after is not None:
            mean = (before + after) / 2
        else:
            mean = before if before is not None else (after if after is not None else 1)
        out.append(mean * HANDLE_REACH)
    return out


def _solve_linear(n, a, b):
    """solveLinear of src/core/fit/linalg.ts: elimination with partial pivots."""
    a = [row[:] for row in a]
    x = list(b)
    max_abs = 0.0
    for row in a:
        for v in row:
            max_abs = max(max_abs, abs(v))
    tiny = max(max_abs, 1) * 1e-13
    for col in range(n):
        pivot = col
        best = abs(a[col][col])
        for r in range(col + 1, n):
            v = abs(a[r][col])
            if v > best:
                best = v
                pivot = r
        if best < tiny:
            return None
        if pivot != col:
            a[col], a[pivot] = a[pivot], a[col]
            x[col], x[pivot] = x[pivot], x[col]
        piv = a[col][col]
        for r in range(col + 1, n):
            f = a[r][col] / piv
            if f == 0:
                continue
            ar, ac = a[r], a[col]
            for c in range(col, n):
                ar[c] -= f * ac[c]
            x[r] -= f * x[col]
    for row in range(n - 1, -1, -1):
        s = x[row]
        for c in range(row + 1, n):
            s -= a[row][c] * x[c]
        x[row] = s / a[row][row]
    return x


def fit_spline_points(points, handles, closed):
    n = len(points)
    if n < 2:
        raise SplineError("A spline needs at least two points.")
    if closed and n < 3:
        raise SplineError("A closed spline needs at least three points.")
    h = _chords(points, closed)
    if any(not (c > 1e-9) for c in h):
        raise SplineError("Two consecutive points coincide — move one of them apart.")
    reach = _reaches(points, closed, h)
    a = [[0.0] * n for _ in range(n)]
    bx = [0.0] * n
    by = [0.0] * n
    segments = spline_segment_count(n, closed)
    for i in range(n):
        handle = handles[i] if i < len(handles) else None
        if handle is not None:
            a[i][i] = 1
            bx[i] = handle[0] / reach[i]
            by[i] = handle[1] / reach[i]
            continue
        prev = (i - 1 + n) % n if closed else i - 1
        nxt = (i + 1) % n if closed else i + 1
        h_prev = h[(i - 1 + n) % n] if closed else (h[i - 1] if i > 0 else 0)
        h_next = h[i % segments] if closed else (h[i] if i < n - 1 else 0)
        if not closed and i == 0:
            a[i][i] = 2
            a[i][nxt] = 1
            bx[i] = (3 * (points[nxt][0] - points[i][0])) / h_next
            by[i] = (3 * (points[nxt][1] - points[i][1])) / h_next
            continue
        if not closed and i == n - 1:
            a[i][prev] = 1
            a[i][i] = 2
            bx[i] = (3 * (points[i][0] - points[prev][0])) / h_prev
            by[i] = (3 * (points[i][1] - points[prev][1])) / h_prev
            continue
        a[i][prev] += 1 / h_prev
        a[i][i] += 2 * (1 / h_prev + 1 / h_next)
        a[i][nxt] += 1 / h_next
        bx[i] = 3 * ((points[i][0] - points[prev][0]) / (h_prev * h_prev) + (points[nxt][0] - points[i][0]) / (h_next * h_next))
        by[i] = 3 * ((points[i][1] - points[prev][1]) / (h_prev * h_prev) + (points[nxt][1] - points[i][1]) / (h_next * h_next))
    mx = _solve_linear(n, a, bx)
    my = _solve_linear(n, a, by)
    if mx is None or my is None:
        raise SplineError("Couldn't lay a curve through these points.")
    fit = {
        "kind": "spline",
        "points": [[p[0], p[1]] for p in points],
        "tangents": [[mx[i], my[i]] for i in range(n)],
        "fixed": [(handles[i] if i < len(handles) else None) is not None for i in range(n)],
        "closed": closed,
        "length": 0,
        "sigma": 0,
        "usedPoints": n,
    }
    fit["length"] = _arc_length(fit)
    return fit


def eval_spline(fit, k, u):
    pts = fit["points"]
    n = len(pts)
    p0 = pts[k]
    p1 = pts[(k + 1) % n]
    h = js_hypot(p1[0] - p0[0], p1[1] - p0[1])
    m0 = fit["tangents"][k]
    m1 = fit["tangents"][(k + 1) % n]
    u2 = u * u
    u3 = u2 * u
    c0 = 2 * u3 - 3 * u2 + 1
    c1 = (u3 - 2 * u2 + u) * h
    c2 = -2 * u3 + 3 * u2
    c3 = (u3 - u2) * h
    return [c0 * p0[0] + c1 * m0[0] + c2 * p1[0] + c3 * m1[0], c0 * p0[1] + c1 * m0[1] + c2 * p1[1] + c3 * m1[1]]


def eval_spline_derivative(fit, k, u):
    pts = fit["points"]
    n = len(pts)
    p0 = pts[k]
    p1 = pts[(k + 1) % n]
    h = js_hypot(p1[0] - p0[0], p1[1] - p0[1])
    m0 = fit["tangents"][k]
    m1 = fit["tangents"][(k + 1) % n]
    u2 = u * u
    c0 = 6 * u2 - 6 * u
    c1 = (3 * u2 - 4 * u + 1) * h
    c2 = -6 * u2 + 6 * u
    c3 = (3 * u2 - 2 * u) * h
    return [c0 * p0[0] + c1 * m0[0] + c2 * p1[0] + c3 * m1[0], c0 * p0[1] + c1 * m0[1] + c2 * p1[1] + c3 * m1[1]]


_GAUSS_X = (0, 0.5384693101056831, -0.5384693101056831, 0.906179845938664, -0.906179845938664)
_GAUSS_W = (0.5688888888888889, 0.4786286704993665, 0.4786286704993665, 0.2369268850561891, 0.2369268850561891)
_PANELS = 4


def _arc_length(fit):
    total = 0.0
    for k in range(spline_segment_count(len(fit["points"]), fit["closed"])):
        for panel in range(_PANELS):
            u0 = panel / _PANELS
            half = 1 / (2 * _PANELS)
            s = 0.0
            for g in range(len(_GAUSS_X)):
                d = eval_spline_derivative(fit, k, u0 + half * (1 + _GAUSS_X[g]))
                s += _GAUSS_W[g] * js_hypot(d[0], d[1])
            total += s * half
    return total


# ---- plugins/reverse/core/sketchSpline.ts ----------------------------------------------


def is_closed(e):
    return bool(e.get("closed")) and len(e["pts"]) >= 3


def spline_segments_of(e):
    return len(e["pts"]) if is_closed(e) else max(0, len(e["pts"]) - 1)


def _segments_of_fit(fit):
    return len(fit["points"]) if fit["closed"] else max(0, len(fit["points"]) - 1)


def spline_curve(e):
    """The curve a sketch spline draws, as a fit."""
    pts = e["pts"]
    n = len(pts)
    closed = is_closed(e)

    def chord(i):
        return js_hypot(pts[(i + 1) % n][0] - pts[i][0], pts[(i + 1) % n][1] - pts[i][1])

    handles = [None] * n
    if not closed and n >= 2:
        if e.get("startDir") is not None:
            r = HANDLE_REACH * chord(0)
            handles[0] = [math.cos(e["startDir"]) * r, math.sin(e["startDir"]) * r]
        if e.get("endDir") is not None:
            r = HANDLE_REACH * chord(n - 2)
            handles[n - 1] = [math.cos(e["endDir"]) * r, math.sin(e["endDir"]) * r]
    if n >= 2:
        try:
            return fit_spline_points(pts, handles, closed)
        except SplineError:
            pass
    # Points that coincide: a polyline's corners with chord tangents, so
    # the sketch still draws and solves.
    tangents = []
    for i in range(n):
        before = pts[(i - 1 + n) % n if closed else max(0, i - 1)]
        after = pts[(i + 1) % n if closed else min(n - 1, i + 1)]
        d = [after[0] - before[0], after[1] - before[1]]
        ln = js_hypot(d[0], d[1])
        tangents.append([d[0] / ln, d[1] / ln] if ln > 1e-12 else [1, 0])
    length = 0.0
    for i in range(spline_segments_of(e)):
        length += chord(i)
    return {"kind": "spline", "points": [[p[0], p[1]] for p in pts], "tangents": tangents, "fixed": [False] * n, "closed": closed, "length": length, "sigma": 0, "usedPoints": n}


def _locate(fit, t):
    s = _segments_of_fit(fit)
    if s == 0:
        return 0, 0.0
    w = math.fmod(math.fmod(t, s) + s, s) if fit["closed"] else min(max(t, 0), s)
    k = min(math.floor(w), s - 1)
    return k, w - k


def spline_at(fit, t):
    if _segments_of_fit(fit) == 0:
        return [fit["points"][0][0], fit["points"][0][1]]
    k, u = _locate(fit, t)
    return eval_spline(fit, k, u)


def spline_deriv_at(fit, t):
    if _segments_of_fit(fit) == 0:
        return [1, 0]
    k, u = _locate(fit, t)
    return eval_spline_derivative(fit, k, u)


def spline_dir_at(fit, t):
    d = spline_deriv_at(fit, t)
    ln = js_hypot(d[0], d[1])
    return [d[0] / ln, d[1] / ln] if ln > 1e-12 else [1, 0]


def spline_end(fit):
    return _segments_of_fit(fit)


def spline_samples(fit, per_segment=16):
    s = _segments_of_fit(fit)
    if s == 0:
        return [{"t": 0, "p": [fit["points"][0][0], fit["points"][0][1]]}]
    out = []
    for k in range(s):
        for i in range(0 if k == 0 else 1, per_segment + 1):
            out.append({"t": k + i / per_segment, "p": eval_spline(fit, k, i / per_segment)})
    return out


def nearest_on_spline(fit, p, per_segment=16):
    s = _segments_of_fit(fit)

    def d2(t):
        q = spline_at(fit, t)
        return (q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2

    if s == 0:
        return {"t": 0, "point": spline_at(fit, 0), "dist": math.sqrt(d2(0))}
    best = 0
    best_d = math.inf
    for smp in spline_samples(fit, per_segment):
        d = d2(smp["t"])
        if d < best_d:
            best_d = d
            best = smp["t"]
    step = 1 / per_segment
    lo = best - step
    hi = best + step
    if not fit["closed"]:
        lo = max(lo, 0)
        hi = min(hi, s)
    g = (math.sqrt(5) - 1) / 2
    x1 = hi - g * (hi - lo)
    x2 = lo + g * (hi - lo)
    f1 = d2(x1)
    f2 = d2(x2)
    for _ in range(40):
        if f1 < f2:
            hi = x2
            x2 = x1
            f2 = f1
            x1 = hi - g * (hi - lo)
            f1 = d2(x1)
        else:
            lo = x1
            x1 = x2
            f1 = f2
            x2 = lo + g * (hi - lo)
            f2 = d2(x2)
    t = (lo + hi) / 2
    if d2(best) < d2(t):
        t = best
    if fit["closed"]:
        t = math.fmod(math.fmod(t, s) + s, s)
    point = spline_at(fit, t)
    return {"t": t, "point": point, "dist": js_hypot(point[0] - p[0], point[1] - p[1])}


def _lerp(a, b, u):
    return [a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u]


def _segment_bezier(fit, k):
    pts = fit["points"]
    n = len(pts)
    p0 = pts[k]
    p1 = pts[(k + 1) % n]
    h = js_hypot(p1[0] - p0[0], p1[1] - p0[1])
    m0 = fit["tangents"][k]
    m1 = fit["tangents"][(k + 1) % n]
    return [[p0[0], p0[1]], [p0[0] + (h * m0[0]) / 3, p0[1] + (h * m0[1]) / 3], [p1[0] - (h * m1[0]) / 3, p1[1] - (h * m1[1]) / 3], [p1[0], p1[1]]], h


def _sub_bezier(b, u0, u1):
    def split(c, u):
        a = _lerp(c[0], c[1], u)
        m = _lerp(c[1], c[2], u)
        d = _lerp(c[2], c[3], u)
        e = _lerp(a, m, u)
        f = _lerp(m, d, u)
        g = _lerp(e, f, u)
        return [c[0], a, e, g], [g, f, d, c[3]]

    c = b
    if u1 < 1:
        c = split(c, u1)[0]
    if u0 > 0:
        c = split(c, u0 / u1)[1]
    return c


def spline_stretch_beziers(fit, t0, t1):
    s = _segments_of_fit(fit)
    pieces = []
    spans = []
    if s == 0:
        return pieces, spans
    lo = min(t0, t1)
    hi = max(t0, t1)
    if not fit["closed"]:
        lo = max(lo, 0)
        hi = min(hi, s)
    first = math.floor(lo + 1e-12)
    last = math.ceil(hi - 1e-12) - 1
    for j in range(first, last + 1):
        u0 = max(lo - j, 0)
        u1 = min(hi - j, 1)
        if u1 - u0 < 1e-12:
            continue
        k = math.fmod(math.fmod(j, s) + s, s) if fit["closed"] else min(max(j, 0), s - 1)
        bez, h = _segment_bezier(fit, int(k))
        span = (u1 - u0) * h
        if not (span > 1e-12):
            continue
        pieces.append(_sub_bezier(bez, u0, u1))
        spans.append(span)
    if t0 > t1:
        pieces.reverse()
        spans.reverse()
        pieces = [[p[3], p[2], p[1], p[0]] for p in pieces]
    return pieces, spans


def bezier_chain_to_bspline(pieces, spans):
    m = len(pieces)
    knots = [0]
    for s in spans:
        knots.append(knots[-1] + s)
    dim = len(pieces[0][0]) if pieces else 2

    def mix(a, wa, b, wb):
        return [a[i] * wa + b[i] * wb for i in range(dim)]

    def span(k):
        return 0 if k < 0 or k >= m else spans[k]

    def weights(k):
        tot = span(k - 1) + span(k) + span(k + 1)
        return (span(k) + span(k + 1)) / tot, span(k - 1) / tot, span(k + 1) / tot, (span(k - 1) + span(k)) / tot

    de = [list(pieces[0][0])] + [None] * (m + 1)
    for k in range(m):
        a, b, c, d = weights(k)
        det = a * d - b * c
        b1 = pieces[k][1]
        b2 = pieces[k][2]
        de[k + 1] = mix(b1, d / det, b2, -b / det)
        if k == m - 1:
            de[k + 2] = mix(b2, a / det, b1, -c / det)
    de.append(list(pieces[m - 1][3]))
    size = 1
    for p in pieces:
        for q in p:
            for v in q:
                size = max(size, abs(v))
    tol = 1e-9 * size
    smooth = True
    k = 0
    while k < m and smooth:
        a, b, c, d = weights(k)
        b1 = mix(de[k + 1], a, de[k + 2], b)
        b2 = mix(de[k + 1], c, de[k + 2], d)
        b0 = de[0] if k == 0 else mix(pieces[k - 1][2], span(k) / (span(k - 1) + span(k)), pieces[k][1], span(k - 1) / (span(k - 1) + span(k)))
        for i in range(dim):
            if abs(b1[i] - pieces[k][1][i]) > tol or abs(b2[i] - pieces[k][2][i]) > tol or abs(b0[i] - pieces[k][0][i]) > tol:
                smooth = False
        k += 1
    if smooth:
        return {"poles": de, "knots": knots, "mults": [4 if (i == 0 or i == m) else 1 for i in range(len(knots))]}
    poles = [list(pieces[0][0])]
    for p in pieces:
        poles += [list(p[1]), list(p[2]), list(p[3])]
    return {"poles": poles, "knots": knots, "mults": [4 if (i == 0 or i == m) else 3 for i in range(len(knots))]}


def spline_stretch(fit, t0, t1):
    pieces, spans = spline_stretch_beziers(fit, t0, t1)
    if not pieces:
        return None
    return bezier_chain_to_bspline(pieces, spans)


def bspline_at(b, t):
    U = []
    for k, mlt in enumerate(b["mults"]):
        U += [b["knots"][k]] * mlt
    p = 3
    n = len(b["poles"])
    k = p
    while k < n - 1 and t >= U[k + 1]:
        k += 1
    d = [list(q) for q in b["poles"][k - p:k + 1]]
    for r in range(1, p + 1):
        for j in range(p, r - 1, -1):
            i = k - p + j
            den = U[i + p - r + 1] - U[i]
            a = (t - U[i]) / den if den > 0 else 0
            d[j] = [d[j - 1][c] * (1 - a) + v * a for c, v in enumerate(d[j])]
    return d[p]


def bspline_samples(b, count):
    t0 = b["knots"][0]
    t1 = b["knots"][-1]
    return [bspline_at(b, t0 + ((t1 - t0) * i) / count) for i in range(count + 1)]


def fit_spline_to_points(e, slice_):
    fit = spline_curve(e)
    reach = min(5, max(1, 0.05 * fit["length"]))
    points = points_along(fit, slice_, reach)
    if len(points) < max(4, len(e["pts"])):
        return None
    out = dict(e)
    out["points"] = points
    out["scatter"] = max(spline_scatter({**e, "points": points}), 0.01)
    return out


def spline_scatter(e):
    points = e.get("points") or []
    if not points:
        return 0
    fit = spline_curve(e)
    s = 0.0
    for p in points:
        s += nearest_on_spline(fit, p, 8)["dist"] ** 2
    return math.sqrt(s / len(points))


def fit_points_along(chain, count, closed):
    if closed and len(chain) > 1 and js_hypot(chain[0][0] - chain[-1][0], chain[0][1] - chain[-1][1]) < 1e-9:
        pts = list(chain[:-1])
    else:
        pts = list(chain)
    if closed:
        pts.append(pts[0])
    run = [0.0]
    for i in range(1, len(pts)):
        run.append(run[i - 1] + js_hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]))
    total = run[-1]
    if not (total > 1e-9):
        return None
    n = max(3 if closed else 2, int(np.floor(count + 0.5)))
    steps = n if closed else n - 1
    out = []
    j = 0
    for k in range(n):
        at = (total * k) / steps
        while j < len(run) - 2 and run[j + 1] < at:
            j += 1
        span = run[j + 1] - run[j]
        u = (at - run[j]) / span if span > 0 else 0
        out.append([pts[j][0] + (pts[j + 1][0] - pts[j][0]) * u, pts[j][1] + (pts[j + 1][1] - pts[j][1]) * u])
    return out


def points_along(fit, points, reach):
    s = _segments_of_fit(fit)
    xs = [p[0] for p in fit["points"]]
    ys = [p[1] for p in fit["points"]]
    pad = reach + 0.5 * fit["length"]
    box = [min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad]
    out = []
    for p in points:
        if p[0] < box[0] or p[0] > box[2] or p[1] < box[1] or p[1] > box[3]:
            continue
        near = nearest_on_spline(fit, p, 8)
        if near["dist"] > reach:
            continue
        if not fit["closed"] and (near["t"] < 1e-3 or near["t"] > s - 1e-3):
            continue
        out.append([p[0], p[1]])
    return out


_OVERSHOOT_MM = 0.01


def _r4(x):
    return math.floor(x * 1e4 + 0.5) / 1e4


def spline_overshoots(e):
    fit = spline_curve(e)
    n = len(e["pts"])
    closed = is_closed(e)
    segments = spline_segments_of(e)
    worst = {}
    for k in range(segments):
        around = [e["pts"][((i % n) + n) % n] for i in (k - 1, k, k + 1, k + 2) if closed or (0 <= i < n)]
        for axis, a in (("u", 0), ("v", 1)):
            values = [p[a] for p in around]
            steps = [x - values[i] for i, x in enumerate(values[1:])]
            if not all(d >= 0 for d in steps) and not all(d <= 0 for d in steps):
                continue
            p0 = e["pts"][k][a]
            p1 = e["pts"][(k + 1) % n][a]
            lo = min(p0, p1)
            hi = max(p0, p1)
            for i in range(1, 32):
                p = eval_spline(fit, k, i / 32)
                mm = max(lo - p[a], p[a] - hi)
                if mm > _OVERSHOOT_MM and mm > (worst[axis]["mm"] if axis in worst else 0):
                    worst[axis] = {"stretch": k, "axis": axis, "mm": _r4(mm), "at": [_r4(p[0]), _r4(p[1])]}
    return sorted(worst.values(), key=lambda w: -w["mm"])
