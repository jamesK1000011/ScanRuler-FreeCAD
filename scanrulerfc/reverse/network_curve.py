# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/core/networkCurve.ts
# SPDX-License-Identifier: AGPL-3.0-only
#
# A curve of a patch network: its trace along the scan and the smooth curve
# fitted to it.
#
# The trace is the scan path (scan_path.py) between each two of the curve's
# points in turn (its end node, its grips, its other end node), so it lies
# on the scan and follows its noise. The curve is a clamped cubic B-spline
# with uniform knots (network_spline.py), fitted to the trace by least
# squares at its arc-length parameter: through its two ends exactly (the
# nodes, which the curves meeting there share) and kept fair by a slight
# term on the poles' second differences, which holds a span with no points
# in it between its neighbours; in a network, its smoothness fairs the curve
# as well (fit_curve's `fairing`). Where the curve goes on smoothly into
# another at a node, the end's tangent is given and its second pole held on
# that line, so the two meet tangent.
#
# Its span count is its strip's (network_fit.py, whose Auto starts every
# strip at four and grows it where a patch misses the scan). A curve that is
# no cell's whole side takes auto_spans: the trace's length over eight times
# the scan's scatter along it, between 2 and 20, the rule Fit Surface sizes
# its net by. The scatter is read off a pilot fit's residual.
#
# A trace is a dict with the original's fields: points (float32, x, y, z per
# point), on, at, length, grips, runs. A fit: spans, poles, rms, max. The
# normal equations are formed with numpy from the same rows as the
# original's.

import math

import numpy as np

from ..linalg import cholesky_solve, solve_linear
from ._js import js_hypot, js_round
from .network_spline import DEGREE, basis_at_v, curve_derivative, curve_derivatives_v, curve_points_v, divided_weights, greville_of
from .scan_path import trace_path

SPANS_MIN = 2
SPANS_MAX = 20
DEFAULT_TOLERANCE = 0.01
PILOT_SPANS = 6
FAIRING = 1e-6
SCATTER_FLOOR = 1e-3
CURVE_ROUNDS = 0
PROVISIONAL_EDGES = 6
LEAVING_EDGES = 10
LEAVING_SHARE = 0.3


def arc_lengths(points):
    """The arc length at each point of a flat x, y, z polyline."""
    P = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    at = np.zeros(P.shape[0])
    if P.shape[0] > 1:
        d = np.diff(P, axis=0)
        at[1:] = np.cumsum(np.sqrt((d * d).sum(axis=1)))
    return at


def curve_points(points):
    """A polyline as the points a curve is fitted to: points (float32), at,
    length."""
    pts = np.asarray(points, dtype=np.float32).reshape(-1)
    at = arc_lengths(pts)
    return {"points": pts, "at": at, "length": float(at[-1]) if at.size else 0.0}


def trace_curve(scan, points):
    """The trace through `points`, each taken to the scan, in order."""
    xyz = []
    on = []
    grips = []
    runs = []
    for k in range(len(points) - 1):
        path = trace_path(scan, points[k], points[k + 1])
        P = path["points"]
        n = len(P) // 3
        if n == 0:
            continue
        skip = 1 if xyz else 0
        frm = len(xyz) // 3 - skip
        if skip == 0:
            grips.append(0)
        xyz.extend(P[skip * 3:].tolist())
        on.extend(path["on"][skip * 2:].tolist())
        grips.append(len(xyz) // 3 - 1)
        runs.append({"way": path["way"], "from": frm, "to": len(xyz) // 3 - 1, "ends": list(path["ends"])})
    if not xyz and points:
        c = scan.closest(points[0])
        if c is not None:
            xyz.extend(c.point)
            on.extend((-1, c.triangle))
            grips.append(0)
    pts = np.asarray(xyz, dtype=np.float32)
    at = arc_lengths(pts)
    return {"points": pts, "on": np.asarray(on, dtype=np.int64), "at": at, "length": float(at[-1]) if at.size else 0.0, "grips": grips, "runs": runs}


def fit_curve(trace, spans, ends=None, fairing=0.0):
    """The clamped cubic of `spans` spans through the trace's two ends,
    fitted to the rest of it. `ends` may give startTangent and endTangent;
    `fairing` is a network's smoothness on the curve, the weight of the
    integral of |C'''|^2 ds against the points, mm^5."""
    ends = ends or {}
    start_t = ends.get("startTangent")
    end_t = ends.get("endTangent")
    pts = np.asarray(trace["points"], dtype=np.float64).reshape(-1, 3)
    count = pts.shape[0]
    n = max(SPANS_MIN, int(js_round(spans))) + DEGREE
    s = n - DEGREE
    length = trace["length"] if trace["length"] > 0 else 1.0
    first = pts[0].tolist() if count > 0 else [0.0, 0.0, 0.0]
    last = pts[count - 1].tolist() if count > 0 else first
    base = np.zeros(n * 3)
    unknown = np.full(n * 3, -1, dtype=np.int64)
    coef = np.zeros(n * 3)
    k = 0
    for c in range(3):
        base[c] = first[c]
        base[(n - 1) * 3 + c] = last[c]
    start_held = -1
    end_held = -1
    if start_t is not None:
        start_held = k
        k += 1
    if end_t is not None:
        end_held = k
        k += 1
    for i in range(1, n - 1):
        for c in range(3):
            at = i * 3 + c
            if i == 1 and start_t is not None:
                base[at] = first[c]
                unknown[at] = start_held
                coef[at] = start_t[c]
            elif i == n - 2 and end_t is not None:
                base[at] = last[c]
                unknown[at] = end_held
                coef[at] = -end_t[c]
            else:
                unknown[at] = k
                k += 1
                coef[at] = 1.0

    # The fixed rows (fairing and smoothness): pole indices, weights, weight.
    fixed_idx = []
    fixed_w = []
    fixed_weight = []
    fair = FAIRING * max(1, count / n)
    for i in range(1, n - 1):
        fixed_idx.append([i - 1, i, i + 1, 0])
        fixed_w.append([1.0, -2.0, 1.0, 0.0])
        fixed_weight.append(fair)
    if fairing > 0:
        g = greville_of(s)
        weight = fairing / ((n - 1) * length ** 5)
        for i in range(n - 3):
            fixed_idx.append([i, i + 1, i + 2, i + 3])
            fixed_w.append(divided_weights(g, i, 3))
            fixed_weight.append(weight)
    fixed_idx = np.array(fixed_idx, dtype=np.int64).reshape(-1, 4)
    fixed_w = np.array(fixed_w, dtype=float).reshape(-1, 4)
    fixed_weight = np.array(fixed_weight, dtype=float)

    def system_rows(idx, w, rhs, weight):
        """Each row (pole indices, weights) per coordinate: A, r, weight."""
        rows = idx.shape[0]
        A = np.zeros((rows * 3, k))
        r = np.zeros(rows * 3)
        wt = np.repeat(weight, 3)
        for c in range(3):
            at = idx * 3 + c
            sel = slice(c, rows * 3, 3)
            r[sel] = rhs[:, c] - (w * base[at]).sum(axis=1)
            U = unknown[at]
            CW = w * coef[at]
            sub = np.zeros((rows, k))
            for m in range(idx.shape[1]):
                ok = U[:, m] >= 0
                sub[np.nonzero(ok)[0], U[ok, m]] += CW[ok, m]
            A[sel] = sub
        return A, r, wt

    fixed = system_rows(fixed_idx, fixed_w, np.zeros((fixed_idx.shape[0], 3)), fixed_weight) if fixed_idx.shape[0] else None

    def solve_at(t):
        span, basis = basis_at_v(s, t)
        idx = (span - DEGREE)[:, None] + np.arange(DEGREE + 1)[None, :]
        A, r, wt = system_rows(idx, basis, pts, np.ones(count))
        if fixed is not None:
            A = np.vstack([A, fixed[0]])
            r = np.concatenate([r, fixed[1]])
            wt = np.concatenate([wt, fixed[2]])
        Aw = A * wt[:, None]
        ata = Aw.T @ A
        atb = Aw.T @ r
        diag = float(np.trace(ata))
        ata[np.diag_indices(k)] += 1e-12 * max(diag / max(1, k), 1e-12)
        z = cholesky_solve(ata, atb) if k > 0 else np.zeros(0)
        if z is None:
            z = solve_linear(ata, atb)
        if z is None:
            z = np.zeros(k)
        z = np.asarray(z, dtype=float)
        poles = base + np.where(unknown >= 0, coef * z[np.maximum(unknown, 0)] if k > 0 else 0.0, 0.0)
        return poles, z

    t = np.asarray(trace["at"], dtype=float)[:count] / length
    poles, z = solve_at(t)
    for _ in range(CURVE_ROUNDS):
        _project_onto(poles, s, pts, t)
        poles, z = solve_at(t)
    start_wrong = start_held >= 0 and z[start_held] < 0
    end_wrong = end_held >= 0 and z[end_held] < 0
    if start_wrong or end_wrong:
        return fit_curve(trace, spans, {"startTangent": None if start_wrong else start_t, "endTangent": None if end_wrong else end_t}, fairing)
    _project_onto(poles, s, pts, t)
    fit = {"spans": s, "poles": poles, "rms": 0.0, "max": 0.0}
    if count > 0:
        q = curve_points_v(poles, s, t)
        d = np.sqrt(((q - pts) ** 2).sum(axis=1))
        fit["max"] = float(max(0.0, d.max()))
        fit["rms"] = math.sqrt(float((d * d).sum()) / count)
    return fit


def _project_onto(poles, spans, pts, t):
    """Each point but the two ends taken to the parameter of its nearest
    point on the curve: a few Gauss-Newton steps, in [0, 1]."""
    if t.shape[0] <= 2:
        return
    tt = t[1:-1].copy()
    P = pts[1:-1]
    live = np.ones(tt.shape[0], dtype=bool)
    for _ in range(3):
        if not live.any():
            break
        q = curve_points_v(poles, spans, tt)
        d = curve_derivatives_v(poles, spans, tt)
        dd = (d * d).sum(axis=1)
        live &= dd > 0
        g = ((P - q) * d).sum(axis=1)
        with np.errstate(divide="ignore", invalid="ignore"):
            step = np.clip(tt + g / dd, 0.0, 1.0)
        tt = np.where(live, step, tt)
    t[1:-1] = tt


def auto_spans(trace):
    """Auto's span count for a trace: its length over eight times its
    scatter (a pilot fit's RMS), between SPANS_MIN and SPANS_MAX."""
    if trace["length"] <= 0:
        return SPANS_MIN
    scatter = fit_curve(trace, PILOT_SPANS)["rms"]
    return max(SPANS_MIN, min(SPANS_MAX, int(js_round(trace["length"] / (8 * max(scatter, SCATTER_FLOOR))))))


def fit_provisional(trace, spacing):
    """A curve fitted for the directions it leaves its ends by, before its
    strip says its spans: Auto, but no finer than a span every
    PROVISIONAL_EDGES of the scan's edges (spacing, mm)."""
    dense = max(SPANS_MIN, math.floor(trace["length"] / (PROVISIONAL_EDGES * spacing))) if spacing > 0 else SPANS_MAX
    return fit_curve(trace, min(auto_spans(trace), dense))


def leaving_direction(trace, end, spacing):
    """The way a trace leaves its first end (0) or its last (1), a unit
    vector along it away from the end: a quadratic through the end fitted to
    the points within LEAVING_EDGES of the scan's edges of it."""
    P = trace["points"]
    n = len(P) // 3
    if n < 2:
        return [1.0, 0.0, 0.0]
    at = trace["at"]
    reach = min(max(LEAVING_EDGES * spacing, 2), LEAVING_SHARE * trace["length"])
    i0 = 0 if end == 0 else n - 1
    step = 1 if end == 0 else -1
    p0 = [float(P[i0 * 3]), float(P[i0 * 3 + 1]), float(P[i0 * 3 + 2])]
    ss = s3 = s4 = 0.0
    b1 = [0.0, 0.0, 0.0]
    b2 = [0.0, 0.0, 0.0]
    used = 0
    a0 = float(at[i0])
    i = i0 + step
    while 0 <= i < n:
        s = abs(float(at[i]) - a0)
        if s > reach and used >= 2:
            break
        if s > 0:
            for k in range(3):
                d = float(P[i * 3 + k]) - p0[k]
                b1[k] += s * d
                b2[k] += s * s * d
            ss += s * s
            s3 += s * s * s
            s4 += s * s * s * s
            used += 1
        i += step
    det = ss * s4 - s3 * s3
    dvec = [0.0, 0.0, 0.0]
    for k in range(3):
        if det > 1e-18 * max(1, ss * s4):
            dvec[k] = (b1[k] * s4 - b2[k] * s3) / det
        else:
            dvec[k] = b1[k] / ss if ss > 0 else 0.0
    l = js_hypot(dvec[0], dvec[1], dvec[2])
    if not l > 0:
        q = 1 if end == 0 else n - 2
        d = [float(P[q * 3]) - p0[0], float(P[q * 3 + 1]) - p0[1], float(P[q * 3 + 2]) - p0[2]]
        ld = js_hypot(*d) or 1
        return [d[0] / ld, d[1] / ld, d[2] / ld]
    return [dvec[0] / l, dvec[1] / l, dvec[2] / l]


def end_tangent(fit, end):
    """The unit tangent of a fitted curve at its start (along it) or its
    end (into it)."""
    d = curve_derivative(fit["poles"], fit["spans"], float(end))
    l = js_hypot(d[0], d[1], d[2]) or 1
    return [d[0] / l, d[1] / l, d[2] / l]


def sample_curve(fit, count):
    """The fitted curve sampled at `count` evenly spaced parameters, flat."""
    t = np.array([i / (count - 1) if count > 1 else 0.0 for i in range(count)])
    return curve_points_v(fit["poles"], fit["spans"], t).reshape(-1)


def join_traces(parts):
    """Traces end to end, each forwards or backwards, as one: a cell's side
    made of more than one curve. Each starts where the one before ended.
    `parts`: (trace, reversed) pairs."""
    chunks = []
    had = 0
    for trace, rev in parts:
        P = np.asarray(trace["points"], dtype=np.float32).reshape(-1, 3)
        if rev:
            P = P[::-1]
        if had and P.shape[0]:
            P = P[1:]
        had += P.shape[0]
        chunks.append(P)
    pts = np.concatenate(chunks).reshape(-1) if chunks else np.zeros(0, dtype=np.float32)
    return curve_points(pts)


def curve_samples(fit, per_span=8):
    """A fitted curve as points along it, per_span a span, with their arc
    length: to fit another curve to."""
    count = fit["spans"] * per_span + 1
    t = np.arange(count) / (count - 1)
    return curve_points(curve_points_v(fit["poles"], fit["spans"], t).astype(np.float32))


def reversed_poles(poles):
    """A curve's poles in the other order: the same curve run backwards."""
    return np.asarray(poles, dtype=float).reshape(-1, 3)[::-1].reshape(-1).copy()
