# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/core/surfaceFit.ts
# SPDX-License-Identifier: AGPL-3.0-only
#
# Fit Surface: a smooth B-spline through a region of the scan. The region's
# principal frame is the base plane; every point becomes (u, v, height)
# over it, and a tensor-product B-spline of degree 3 with a U x V control
# net is solved for its heights by linear least squares, the net's u and v
# fixed at the Greville abscissae, so only the heights are unknown. A
# fairness term on third divided differences of the net (their null space
# holds every quadratic, so a cylinder or a saddle extrapolates as itself)
# keeps the surface fair, weighted by the smoothness times the region's
# area squared; the cells with no points near are pulled toward the plane.
# Dense Cholesky: the largest net is 20 x 20. The kernel takes no control
# net: the fit is sampled on a grid a few times denser (grid_of) and the
# kernel makes the exact surface through that (bsplineSurface, kernel.py).
# In numpy; a fit is a dict with the original's fields.

import math

import numpy as np

from ..dev_rigid import principal_frame
from ..linalg import cholesky_solve, solve_linear
from ._js import js_hypot, js_round, num_str, to_fixed

NET_MIN = 3
NET_MAX = 20
DEFAULT_SURFACE_FIT = {"net": None, "degree": 3, "expandPct": 35, "smoothness": 0.01}
GRID_PER_SPAN = 3
GRID_RETRIES = (6, 8)
GRID_AREA_SLACK = 1.02
MESH_SURPLUS = 3
SMOOTHNESS_SCALE = 1e-2
PILOT_NET = 6
PULL = 0.01
PULL_REACH = 1
PULL_SAMPLES = 3
PULL_MOVE = 0.5
PULL_FLOOR = 0.01
PULL_ROUNDS = 3
WORST_POINTS = 5
ROBUST_SIGMAS = 3
ROBUST_FLOOR = 0.01
ROBUST_ROUNDS = 3
FACING_DEG = 30
SHEET_CELL_MM = 2
SHEET_GAP_MM = 1
SHEET_REACH = 2
STRAY_FAR_MM = 1
STRAY_VOXEL_MM = 5
STRAY_MIN_POINTS = 10
STRAYS_NAMED = 6
STRAY_MOST = 0.8
STRAY_PAD_MM = 1
RUNAWAY_SHARE = 0.25
HEIGHT_FIELD_DEG = 70
SPREAD_POINTS = 5000
REACH_SAMPLES = 96


def _r1(x):
    return js_round(x * 10) / 10


# ---- the B-spline pieces ---------------------------------------------------------------------


def clamped_knots(n, p, a, b):
    m = n + p + 1
    knots = np.zeros(m)
    inner = n - p - 1
    knots[:p + 1] = a
    for i in range(1, inner + 1):
        knots[p + i] = a + ((b - a) * i) / (inner + 1)
    knots[m - p - 1:] = b
    return knots


def greville(knots, n, p):
    return np.array([sum(knots[i + k] for k in range(1, p + 1)) / p for i in range(n)])


def find_span(knots, n, p, t):
    if t >= knots[n]:
        return n - 1
    if t <= knots[p]:
        return p
    lo, hi = p, n
    while hi - lo > 1:
        mid = (lo + hi) >> 1
        if t < knots[mid]:
            hi = mid
        else:
            lo = mid
    return lo


def basis_functions(knots, span, p, t, out=None):
    """The p + 1 basis functions non-zero at t in the span (Cox-de Boor)."""
    if out is None:
        out = [0.0] * (p + 1)
    left = [0.0] * (p + 1)
    right = [0.0] * (p + 1)
    out[0] = 1.0
    for j in range(1, p + 1):
        left[j] = t - knots[span + 1 - j]
        right[j] = knots[span + j] - t
        saved = 0.0
        for r in range(j):
            temp = out[r] / (right[r + 1] + left[j - r])
            out[r] = saved + right[r + 1] * temp
            saved = left[j - r] * temp
        out[j] = saved
    return out


def auto_net(extent_u, extent_v, scatter):
    def per(extent):
        return int(max(NET_MIN, min(NET_MAX, js_round(extent / (8 * max(scatter, 1e-3))))))

    return {"u": per(extent_u), "v": per(extent_v)}


def height_frame(axes, normal=None):
    ln = js_hypot(*normal) if normal is not None else 0
    if normal is None or not (ln > 1e-12):
        return [list(map(float, axes[0])), list(map(float, axes[1])), list(map(float, axes[2]))]
    n = [normal[0] / ln, normal[1] / ln, normal[2] / ln]

    def square(a):
        d = a[0] * n[0] + a[1] * n[1] + a[2] * n[2]
        return [a[0] - d * n[0], a[1] - d * n[1], a[2] - d * n[2]]

    u = square(axes[0])
    if js_hypot(*u) < 0.3:
        u = square(axes[1])
    lu = js_hypot(*u)
    u = [u[0] / lu, u[1] / lu, u[2] / lu]
    v = [n[1] * u[2] - n[2] * u[1], n[2] * u[0] - n[0] * u[2], n[0] * u[1] - n[1] * u[0]]
    return [u, v, n]


def _clamp_net(count, p):
    return int(max(max(NET_MIN, p + 1), min(NET_MAX, js_round(count))))


def _divided_weights(x, frm, order):
    fact = math.factorial(order)
    w = []
    for k in range(order + 1):
        denom = 1.0
        for j in range(order + 1):
            if j != k:
                denom *= x[frm + k] - x[frm + j]
        w.append(fact / denom)
    return w


def _basis_rows(knots_u, knots_v, nu, nv, p, u, v):
    """For each (u, v): the (p + 1)^2 net indices it touches and their
    weights, as two (n, (p + 1)^2) arrays."""
    k = (p + 1) * (p + 1)
    cols = np.zeros((len(u), k), dtype=np.int64)
    vals = np.zeros((len(u), k))
    bu = [0.0] * (p + 1)
    bv = [0.0] * (p + 1)
    for i in range(len(u)):
        su = find_span(knots_u, nu, p, u[i])
        sv = find_span(knots_v, nv, p, v[i])
        basis_functions(knots_u, su, p, u[i], bu)
        basis_functions(knots_v, sv, p, v[i], bv)
        c = 0
        for a in range(p + 1):
            row = (su - p + a) * nv
            for b in range(p + 1):
                cols[i, c] = row + (sv - p + b)
                vals[i, c] = bu[a] * bv[b]
                c += 1
    return cols, vals


def _heights_at(cols, vals, heights):
    return (vals * heights[cols]).sum(axis=1)


def eval_height(fit, uu, vv):
    p = fit["degree"]
    su = find_span(fit["knotsU"], fit["nu"], p, uu)
    sv = find_span(fit["knotsV"], fit["nv"], p, vv)
    bu = basis_functions(fit["knotsU"], su, p, uu)
    bv = basis_functions(fit["knotsV"], sv, p, vv)
    h = fit["heights"]
    nv = fit["nv"]
    s = 0.0
    for a in range(p + 1):
        row = (su - p + a) * nv
        for b in range(p + 1):
            s += bu[a] * bv[b] * h[row + (sv - p + b)]
    return float(s)


def _over_plane(fit, xyz):
    P = np.asarray(xyz, dtype=float).reshape(-1, 3) - np.asarray(fit["origin"], dtype=float)
    return P @ np.asarray(fit["axisU"]), P @ np.asarray(fit["axisV"]), P @ np.asarray(fit["normal"])


def fit_surface(xyz, params, scatter=None, pull=PULL):
    """A surface fitted through the points (xyz flat or n x 3)."""
    P = np.asarray(xyz, dtype=float).reshape(-1, 3)
    n = len(P)
    if n < 4:
        raise ValueError("Too few points to fit a surface through.")
    frame = principal_frame(P)
    au, av, an = height_frame(frame["axes"], params.get("normal"))
    c = [float(x) for x in frame["centroid"]]
    p = int(max(1, min(5, js_round(params["degree"]))))
    D = P - np.asarray(c)
    u = D @ np.asarray(au)
    v = D @ np.asarray(av)
    h = D @ np.asarray(an)
    u_min, u_max, v_min, v_max = float(u.min()), float(u.max()), float(v.min()), float(v.max())
    extent_u = max(u_max - u_min, 1e-6)
    extent_v = max(v_max - v_min, 1e-6)
    margin = max(0, params["expandPct"]) / 200
    u_range = [u_min - extent_u * margin, u_max + extent_u * margin]
    v_range = [v_min - extent_v * margin, v_max + extent_v * margin]
    if scatter is not None:
        noise = scatter
    elif params.get("net"):
        noise = math.sqrt(float(frame["spread"][2]))
    else:
        noise = fit_surface(P, {**params, "net": {"u": PILOT_NET, "v": PILOT_NET}}, 0, 0)["rms"]
    net = {"u": _clamp_net(params["net"]["u"], p), "v": _clamp_net(params["net"]["v"], p)} if params.get("net") else auto_net(extent_u, extent_v, noise)
    nu = max(net["u"], p + 1)
    nv = max(net["v"], p + 1)
    knots_u = clamped_knots(nu, p, u_range[0], u_range[1])
    knots_v = clamped_knots(nv, p, v_range[0], v_range[1])
    m = nu * nv
    cols, vals = _basis_rows(knots_u, knots_v, nu, nv, p, u, v)
    A = np.zeros((n, m))
    np.put_along_axis(A, cols, vals, axis=1)
    ata = A.T @ A
    atb = A.T @ h

    lam = max(0, params["smoothness"]) * (extent_u * extent_v) ** 2 * SMOOTHNESS_SCALE
    xu = greville(knots_u, nu, p)
    xv = greville(knots_v, nv, p)
    area = ((u_range[1] - u_range[0]) / max(1, nu - 1)) * ((v_range[1] - v_range[0]) / max(1, nv - 1))

    def cross(i, j, wu, wv, scale):
        idx = [(i + a) * nv + (j + b) for a in range(len(wu)) for b in range(len(wv))]
        w = np.array([wu[a] * wv[b] for a in range(len(wu)) for b in range(len(wv))])
        ata[np.ix_(idx, idx)] += lam * scale * np.outer(w, w)

    for i in range(nu):
        for j in range(nv):
            if i + 3 < nu:
                cross(i, j, _divided_weights(xu, i, 3), [1], area)
            if j + 3 < nv:
                cross(i, j, [1], _divided_weights(xv, j, 3), area)
            if i + 2 < nu and j + 1 < nv:
                cross(i, j, _divided_weights(xu, i, 2), _divided_weights(xv, j, 1), 3 * area)
            if i + 1 < nu and j + 2 < nv:
                cross(i, j, _divided_weights(xu, i, 1), _divided_weights(xv, j, 2), 3 * area)
    diag = float(np.trace(ata))
    ata[np.diag_indices(m)] += 1e-12 * max(diag / m, 1e-12)

    def solve(extra, weight):
        a = ata + weight * extra if extra is not None else ata
        x = cholesky_solve(a, atb)
        return x if x is not None else solve_linear(a, atb)

    heights = solve(None, 0)
    if heights is None:
        raise ValueError("The surface fit is singular — the region is too thin for this net.")
    toward = _pull_system(u, v, knots_u, knots_v, nu, nv, p) if pull > 0 else None
    if toward:
        free = heights
        allowed = max(PULL_MOVE * math.sqrt(float(((h - _heights_at(cols, vals, free)) ** 2).sum()) / n), PULL_FLOOR)
        weight = pull * (n / max(1, toward["cells"]))
        for _ in range(PULL_ROUNDS):
            held = solve(toward["system"], weight)
            if held is None:
                break
            moved = float(np.abs(_heights_at(cols, vals, held - free)).max())
            if moved <= allowed:
                heights = held
                break
            weight *= ((0.8 * allowed) / moved) ** 4
    r = h - _heights_at(cols, vals, heights)
    return {"origin": c, "axisU": au, "axisV": av, "normal": an, "uRange": u_range, "vRange": v_range, "degree": p, "knotsU": knots_u, "knotsV": knots_v,
            "nu": nu, "nv": nv, "heights": np.asarray(heights, dtype=float), "rms": math.sqrt(float((r * r).sum()) / n), "max": float(np.abs(r).max()), "net": {"u": nu, "v": nv}}


def _pull_system(u, v, knots_u, knots_v, nu, nv, p):
    cu, cv = nu - p, nv - p
    held = np.zeros(cu * cv, dtype=bool)
    for i in range(len(u)):
        held[(find_span(knots_u, nu, p, u[i]) - p) * cv + (find_span(knots_v, nv, p, v[i]) - p)] = True
    cells = int(held.sum())
    H = held.reshape(cu, cv)

    def near(a, b):
        return bool(H[max(0, a - PULL_REACH):min(cu - 1, a + PULL_REACH) + 1, max(0, b - PULL_REACH):min(cv - 1, b + PULL_REACH) + 1].any())

    m = nu * nv
    system = np.zeros((m, m))
    w = 1 / (PULL_SAMPLES * PULL_SAMPLES)
    pulled = False
    for a in range(cu):
        for b in range(cv):
            if near(a, b):
                continue
            pulled = True
            idx = [(a + a1) * nv + b + b1 for a1 in range(p + 1) for b1 in range(p + 1)]
            for s in range(PULL_SAMPLES):
                bu = basis_functions(knots_u, p + a, p, knots_u[p + a] + ((knots_u[p + a + 1] - knots_u[p + a]) * (s + 0.5)) / PULL_SAMPLES)
                for t in range(PULL_SAMPLES):
                    bv = basis_functions(knots_v, p + b, p, knots_v[p + b] + ((knots_v[p + b + 1] - knots_v[p + b]) * (t + 0.5)) / PULL_SAMPLES)
                    vec = np.array([bu[a1] * bv[b1] for a1 in range(p + 1) for b1 in range(p + 1)])
                    system[np.ix_(idx, idx)] += w * np.outer(vec, vec)
    return {"system": system, "cells": cells} if pulled else None


def surface_residuals(fit, xyz):
    """Each point's distance from the fitted surface along its normal,
    signed, mm."""
    u, v, h = _over_plane(fit, xyz)
    cols, vals = _basis_rows(fit["knotsU"], fit["knotsV"], fit["nu"], fit["nv"], fit["degree"], u, v)
    return h - _heights_at(cols, vals, fit["heights"])


class StraysRefusal(ValueError):
    """A refusal of a fit that names its strays."""

    def __init__(self, message, strays):
        super().__init__(message)
        self.strays = strays


def fit_surface_reported(xyz, params, facing=None):
    """A surface fitted as fit_surface fits it, robust where asked, with its
    worst points, how many a robust fit left out and its strays; a fit that
    runs away is refused (StraysRefusal)."""
    full = np.asarray(xyz, dtype=float).reshape(-1, 3)
    points = full
    fit = fit_surface(points, params)
    dropped = 0
    robust_at = None
    for _ in range(ROBUST_ROUNDS if params.get("robust") else 0):
        r = surface_residuals(fit, points)
        med = float(np.sort(r)[len(r) >> 1])
        dev = np.sort(np.abs(r - med))
        limit = max(ROBUST_SIGMAS * 1.4826 * float(dev[len(dev) >> 1]), ROBUST_FLOOR)
        robust_at = {"med": med, "limit": limit}
        keep = np.abs(r - med) <= limit
        if keep.all() or keep.sum() < 16:
            break
        dropped += int(len(r) - keep.sum())
        points = points[keep]
        fit = fit_surface(points, params)
    away = run_away(fit, full, params["expandPct"], params.get("normal"), facing)
    if away:
        strays = stray_groups(fit, full, robust_at)
        raise StraysRefusal(f"{away}{_strays_words(strays)}", strays)
    r = surface_residuals(fit, points)
    order = sorted(range(len(r)), key=lambda i: -abs(r[i]))[:WORST_POINTS]
    worst = [{"at": [float(x) for x in points[i]], "off": float(r[i])} for i in order]
    strays = stray_groups(fit, full, robust_at) if params.get("robust") else []
    fit["footprint"] = footprint_of(fit, full)
    out = {"fit": fit, "worst": worst, "dropped": dropped}
    if strays:
        out["strays"] = strays
    return out


def footprint_of(fit, xyz):
    u, v, _ = _over_plane(fit, xyz)
    return np.stack([u, v], axis=1).astype(np.float32).reshape(-1)


# ---- strays -----------------------------------------------------------------------------------


def _range_mm(lo, hi):
    return num_str(_r1(lo)) if _r1(lo) == _r1(hi) else f"{num_str(_r1(lo))}–{num_str(_r1(hi))}"


def _stray_box(P, members):
    q = P[members]
    lo, hi = q.min(axis=0), q.max(axis=0)
    return {"min": [math.floor((float(x) - STRAY_PAD_MM) * 10) / 10 + 0 for x in lo], "max": [math.ceil((float(x) + STRAY_PAD_MM) * 10) / 10 + 0 for x in hi]}


def _flood_groups(keys, near):
    left = dict.fromkeys(keys)
    groups = []
    for start in list(left):
        if start not in left:
            continue
        del left[start]
        group = [start]
        at = 0
        while at < len(group):
            for k in near(group[at]):
                if k in left:
                    del left[k]
                    group.append(k)
            at += 1
        groups.append(group)
    return groups


def _stray_of(P, members, offs, why):
    a = np.abs(np.asarray(offs, dtype=float))
    lo, hi = float(a.min()), float(max(0.0, a.max()))
    under = int((np.asarray(offs) < 0).sum())
    return {"points": len(members), "box": _stray_box(P, members), "offMm": [_r1(lo), _r1(hi)], "why": why(_range_mm(lo, hi), "under" if under > len(offs) / 2 else "over")}


def _second_sheets(fit, P, named):
    n = len(P)
    if n < 4:
        return []
    u, v, hh = _over_plane(fit, P)
    cols_, vals = _basis_rows(fit["knotsU"], fit["knotsV"], fit["nu"], fit["nv"], fit["degree"], u, v)
    h = hh - _heights_at(cols_, vals, fit["heights"])
    u_lo, u_hi, v_lo, v_hi = float(u.min()), float(u.max()), float(v.min()), float(v.max())
    spacing = math.sqrt(max((u_hi - u_lo) * (v_hi - v_lo), 1e-12) / n)
    size = max(SHEET_CELL_MM, 2 * spacing)
    cols = int(math.floor((v_hi - v_lo) / size)) + 1
    cells = {}
    for i in range(n):
        c = int(math.floor((u[i] - u_lo) / size)) * cols + int(math.floor((v[i] - v_lo) / size))
        cells.setdefault(c, []).append(i)

    def median(lst):
        s = sorted(h[i] for i in lst)
        return s[len(s) >> 1]

    single = {}
    parted = {}
    for c, lst in cells.items():
        lst.sort(key=lambda i: h[i])
        gap, at = 0, 0
        for j in range(1, len(lst)):
            if h[lst[j]] - h[lst[j - 1]] > gap:
                gap, at = h[lst[j]] - h[lst[j - 1]], j
        if gap > SHEET_GAP_MM:
            parted[c] = (lst[:at], lst[at:])
        else:
            single[c] = median(lst)
    if not parted:
        return []
    far = {}
    for c, (under, over) in parted.items():
        cu, cv = c // cols, c % cols
        rnd = []
        for a in range(-SHEET_REACH, SHEET_REACH + 1):
            for b in range(-SHEET_REACH, SHEET_REACH + 1):
                if 0 <= cv + b < cols:
                    x = single.get((cu + a) * cols + cv + b)
                    if x is not None:
                        rnd.append(x)
        mu, mo = median(under), median(over)
        rnd.sort()
        ref = rnd[len(rnd) >> 1] if rnd else 0
        members, kept = (under, mo) if abs(mu - ref) > abs(mo - ref) else (over, mu)
        far[c] = {"members": members, "off": [h[i] - kept for i in members]}

    def near(c):
        cu, cv = c // cols, c % cols
        return [(cu + a) * cols + cv + b for a in (-1, 0, 1) for b in (-1, 0, 1) if (a or b) and 0 <= cv + b < cols and ((cu + a) * cols + cv + b) in far]

    strays = []
    for group in _flood_groups(far.keys(), near):
        members = [i for c in group for i in far[c]["members"]]
        if len(members) < STRAY_MIN_POINTS:
            continue
        named.update(members)
        offs = [x for c in group for x in far[c]["off"]]
        strays.append(_stray_of(P, members, offs, lambda mm, side: f"a second sheet {mm} mm {side} the one fitted, along its height direction — no height field holds both"))
    return strays


def _far_points(fit, P, robust, named):
    r = surface_residuals(fit, P)
    beyond = max(STRAY_FAR_MM, 2 * robust["limit"])
    voxels = {}
    for i in range(len(r)):
        if not (abs(r[i] - robust["med"]) > beyond) or i in named:
            continue
        key = tuple(int(math.floor(P[i, k] / STRAY_VOXEL_MM)) for k in range(3))
        voxels.setdefault(key, []).append(i)

    def near(key):
        x, y, z = key
        return [(x + a, y + b, z + c) for a in (-1, 0, 1) for b in (-1, 0, 1) for c in (-1, 0, 1) if a or b or c]

    strays = []
    for group in _flood_groups(voxels.keys(), near):
        members = [i for k in group for i in voxels[k]]
        if len(members) < STRAY_MIN_POINTS:
            continue
        strays.append(_stray_of(P, members, [r[i] for i in members], lambda mm, side: f"left out by the robust fit, {mm} mm {side} its surface"))
    return strays


def stray_groups(fit, xyz, robust):
    """The strays of a region against its fitted surface, the largest
    first: second sheets, and with `robust` the points it left out far off."""
    P = np.asarray(xyz, dtype=float).reshape(-1, 3)
    named = set()
    out = _second_sheets(fit, P, named) + (_far_points(fit, P, robust, named) if robust else [])
    n = len(P)

    def most(s):
        lo, hi = np.asarray(s["box"]["min"]), np.asarray(s["box"]["max"])
        return int(((P >= lo) & (P <= hi)).all(axis=1).sum()) > STRAY_MOST * n

    out.sort(key=lambda s: -s["points"])
    return [s for s in out if not most(s)][:STRAYS_NAMED]


def _strays_words(strays):
    if not strays:
        return ""

    def at(b):
        return f"({', '.join(num_str(x) for x in b['min'])})–({', '.join(num_str(x) for x in b['max'])})"

    named = [f"{s['points']} points {s['why'].split(' — ')[0]} in {at(s['box'])}" for s in strays[:2]]
    more = f", and {len(strays) - 2} more" if len(strays) > 2 else ""
    return f" Strays (strays): {'; '.join(named)}{more} — give their boxes in region.exclude and fit again."


# ---- the runaway check ------------------------------------------------------------------------


def normal_spread(xyz, normal):
    """How far a region's normals turn from a height direction: the 95th
    percentile of the local planes' angles from it, degrees."""
    P = np.asarray(xyz, dtype=float).reshape(-1, 3)
    n = len(P)
    if n < 4:
        return {"p95": 0}
    sides = sorted((P.max(axis=0) - P.min(axis=0)).tolist(), reverse=True)
    reach = 3 * math.sqrt(max(sides[0] * sides[1], 1e-12) / n)
    keys = np.floor(P / reach).astype(np.int64)
    cells = {}
    for i, k in enumerate(map(tuple, keys)):
        cells.setdefault(k, []).append(i)
    ln = js_hypot(*normal) or 1
    nrm = np.asarray(normal, dtype=float)
    step = max(1, math.ceil(n / SPREAD_POINTS))
    angles = []
    for i in range(0, n, step):
        cx, cy, cz = keys[i]
        cand = [j for a in (-1, 0, 1) for b in (-1, 0, 1) for d in (-1, 0, 1) for j in cells.get((cx + a, cy + b, cz + d), ())]
        if len(cand) < 6:
            continue
        Q = P[cand]
        Q = Q[np.linalg.norm(Q - P[i], axis=1) <= reach]
        if len(Q) < 6:
            continue
        D = Q - Q.mean(axis=0)
        _, vecs = np.linalg.eigh(D.T @ D)
        m = vecs[:, 0]
        cos = abs(float(m @ nrm)) / ln
        angles.append(math.degrees(math.acos(min(1, cos))))
    if not angles:
        return {"p95": 0}
    angles.sort()
    return {"p95": angles[min(len(angles) - 1, int(math.floor(0.95 * len(angles))))]}


def run_away(fit, xyz, expand_pct, asked=None, facing=None):
    """Why a fitted surface is no surface of its points, or None: where it
    leaves the points' height range by more than its margin plus a quarter
    of the region's extent."""
    P = np.asarray(xyz, dtype=float).reshape(-1, 3)
    n = len(P)
    if n == 0:
        return None
    pu, pv, ph = _over_plane(fit, P)
    h_lo, h_hi = float(ph.min()), float(ph.max())
    extent = max(float(pu.max() - pu.min()), float(pv.max() - pv.min()))
    allowed = (extent * max(0, expand_pct)) / 200 + RUNAWAY_SHARE * extent
    rows = max(4, (fit["nu"] - 1) * GRID_PER_SPAN + 1)
    cols = max(4, (fit["nv"] - 1) * GRID_PER_SPAN + 1)
    worst, wu, wv, wh = 0, 0, 0, 0
    ur, vr = fit["uRange"], fit["vRange"]
    for r in range(rows):
        uu = ur[0] + ((ur[1] - ur[0]) * r) / (rows - 1)
        for c in range(cols):
            vv = vr[0] + ((vr[1] - vr[0]) * c) / (cols - 1)
            hh = eval_height(fit, uu, vv)
            off = max(hh - h_hi, h_lo - hh)
            if off > worst:
                worst, wu, wv, wh = off, uu, vv, hh
    if not (worst > allowed):
        return None
    d2 = (pu - wu) ** 2 + (pv - wv) ** 2
    last = int(np.argmin(d2))
    best = float(d2[last])

    def at(uu, vv, hh):
        return ", ".join(to_fixed(fit["origin"][k] + uu * fit["axisU"][k] + vv * fit["axisV"][k] + hh * fit["normal"][k], 1) for k in range(3))

    last_at = ", ".join(to_fixed(float(x), 1) for x in P[last])
    spread = normal_spread(P, fit["normal"])

    def dir_of(d):
        return f"[{', '.join(num_str(js_round(x * 1000) / 1000 + 0) for x in d)}]"

    normal = dir_of(fit["normal"])
    faced = None
    if facing:
        fl = js_hypot(*facing["dir"]) or 1
        fd = [x / fl for x in facing["dir"]]
        within = facing["withinDeg"] if facing.get("withinDeg") is not None else FACING_DEG
        apart = math.degrees(math.acos(min(1, abs(fd[0] * fit["normal"][0] + fd[1] * fit["normal"][1] + fd[2] * fit["normal"][2]))))
        faced = {"dir": fd, "within": within, "apart": apart}
    which = "fit.normal" if asked else "the region’s principal normal"
    if faced:
        off_dir = f", {num_str(js_round(faced['apart']))}° off the height direction" if faced["apart"] >= 1 else ""
        along = (f"Its height direction was {normal} ({which}); the region was read facing {dir_of(faced['dir'])} within {num_str(_r1(faced['within']))}°, "
                 f"so its normals are within {num_str(_r1(faced['within']))}° of that by construction{off_dir}.")
    else:
        along = f"Its height direction was {normal} ({which}); 95 % of the region’s normals are within {num_str(js_round(spread['p95']))}° of it."
    bends = spread["p95"] > HEIGHT_FIELD_DEG and not (faced and faced["within"] + faced["apart"] <= HEIGHT_FIELD_DEG)
    if asked:
        direction = ""
    elif faced and faced["apart"] >= 1:
        direction = f" — or give fit.normal: {dir_of(faced['dir'])}, the way the region was read facing, for its height direction"
    else:
        direction = " — or give fit.normal, the way the region faces, for its height direction"
    advice = ("The region bends round past what one height field holds — split it, or loft through stations." if bends else
              f"Fit a coarser net, keep the region to one surface (a box closer round it, or exclude what stands off it), or take less margin{direction}.")
    return (f"The surface runs away from its points: it stands {num_str(_r1(worst))} mm {'above the highest' if wh > h_hi else 'below the lowest'} of them at ({at(wu, wv, wh)}), "
            f"{num_str(_r1(math.sqrt(best)))} mm past where the region's points run out at ({last_at}) — more than the margin and a quarter of the region's {num_str(_r1(extent))} mm allow. "
            f"{along} {advice}")


def mesh_triangles(fit, chord, angle=0.15):
    """About how many triangles the kernel's mesher makes of a fitted
    surface at a chord and an angle."""
    su = max(4, (fit["nu"] - 1) * 4)
    sv = max(4, (fit["nv"] - 1) * 4)
    ur, vr = fit["uRange"], fit["vRange"]
    du = (ur[1] - ur[0]) / su
    dv = (vr[1] - vr[0]) / sv
    whole = min(ur[1] - ur[0], vr[1] - vr[0])
    total = 0.0
    for a in range(su):
        uu = ur[0] + du * (a + 0.5)
        for b in range(sv):
            vv = vr[0] + dv * (b + 0.5)
            h0 = eval_height(fit, uu, vv)
            hu1, hu0 = eval_height(fit, uu + du / 2, vv), eval_height(fit, uu - du / 2, vv)
            hv1, hv0 = eval_height(fit, uu, vv + dv / 2), eval_height(fit, uu, vv - dv / 2)
            hu = (hu1 - hu0) / du
            hv = (hv1 - hv0) / dv
            huu = (hu1 - 2 * h0 + hu0) / ((du * du) / 4)
            hvv = (hv1 - 2 * h0 + hv0) / ((dv * dv) / 4)
            w = math.sqrt(1 + hu * hu + hv * hv)
            k = max(abs(huu) / (w * (1 + hu * hu)), abs(hvv) / (w * (1 + hv * hv)))
            edge = min(whole, min(math.sqrt((8 * chord) / k), angle / k) if k > 1e-12 else math.inf)
            total += (2 * du * dv * w) / (edge * edge)
    return int(js_round(MESH_SURPLUS * total))


# ---- the surface for the kernel ---------------------------------------------------------------


def eval_surface(fit, uu, vv):
    hh = eval_height(fit, uu, vv)
    return [fit["origin"][k] + uu * fit["axisU"][k] + vv * fit["axisV"][k] + hh * fit["normal"][k] for k in range(3)]


def grid_of(fit, per_span=GRID_PER_SPAN):
    """The fitted surface sampled on a regular grid for the kernel:
    {points (rows * cols * 3, row-major), rows, cols}."""
    rows = max(4, (fit["nu"] - 1) * per_span + 1)
    cols = max(4, (fit["nv"] - 1) * per_span + 1)
    ur, vr = fit["uRange"], fit["vRange"]
    us = np.array([ur[0] + ((ur[1] - ur[0]) * r) / (rows - 1) for r in range(rows)])
    vs = np.array([vr[0] + ((vr[1] - vr[0]) * c) / (cols - 1) for c in range(cols)])
    U, V = np.meshgrid(us, vs, indexing="ij")
    cols_, vals = _basis_rows(fit["knotsU"], fit["knotsV"], fit["nu"], fit["nv"], fit["degree"], U.ravel(), V.ravel())
    H = _heights_at(cols_, vals, fit["heights"])
    pts = np.asarray(fit["origin"]) + np.outer(U.ravel(), fit["axisU"]) + np.outer(V.ravel(), fit["axisV"]) + np.outer(H, fit["normal"])
    return {"points": pts.reshape(-1), "rows": rows, "cols": cols}


def grid_area(grid):
    g = np.asarray(grid["points"], dtype=float).reshape(grid["rows"], grid["cols"], 3)
    a, b, d, e = g[:-1, :-1], g[:-1, 1:], g[1:, :-1], g[1:, 1:]
    return float(0.5 * (np.linalg.norm(np.cross(b - a, e - a), axis=2).sum() + np.linalg.norm(np.cross(e - a, d - a), axis=2).sum()))


def reach_over(fit, points, margin):
    """The (u, v) a surface needs to span to reach over a body's points,
    margin mm wider, or None where it spans that already."""
    u, v, _ = _over_plane(fit, points)
    ur = [min(fit["uRange"][0], float(u.min()) - margin), max(fit["uRange"][1], float(u.max()) + margin)]
    vr = [min(fit["vRange"][0], float(v.min()) - margin), max(fit["vRange"][1], float(v.max()) + margin)]
    if ur == list(fit["uRange"]) and vr == list(fit["vRange"]):
        return None
    return {"u": ur, "v": vr}


def carried_height(fit, uu, vv):
    """The fit's height within its range; past its edge, flat along the
    slope it has there."""
    ur, vr = fit["uRange"], fit["vRange"]
    eu = (ur[1] - ur[0]) * 1e-4
    ev = (vr[1] - vr[0]) * 1e-4
    cu = min(ur[1], max(ur[0], uu))
    cv = min(vr[1], max(vr[0], vv))
    at = eval_height(fit, cu, cv)
    if cu == uu and cv == vv:
        return at
    du = 0 if cu == uu else ((at - eval_height(fit, cu - eu, cv)) if cu == ur[1] else (eval_height(fit, cu + eu, cv) - at)) / eu
    dv = 0 if cv == vv else ((at - eval_height(fit, cu, cv - ev)) if cv == vr[1] else (eval_height(fit, cu, cv + ev) - at)) / ev
    return at + du * (uu - cu) + dv * (vv - cv)


def reaching_grid_of(fit, u, v, per_span=GRID_PER_SPAN):
    """The fitted surface sampled for the kernel, carried on flat past its
    own range to span u and v."""
    inner = grid_of(fit, per_span)

    def along(rng, reach, n):
        step = (rng[1] - rng[0]) / (n - 1)
        count = min(REACH_SAMPLES, max(n, math.ceil((reach[1] - reach[0]) / step) + 1))
        return [reach[0] + ((reach[1] - reach[0]) * i) / (count - 1) for i in range(count)]

    us = along(fit["uRange"], u, inner["rows"])
    vs = along(fit["vRange"], v, inner["cols"])
    pts = []
    for uu in us:
        for vv in vs:
            hh = carried_height(fit, uu, vv)
            pts += [fit["origin"][k] + uu * fit["axisU"][k] + vv * fit["axisV"][k] + hh * fit["normal"][k] for k in range(3)]
    return {"points": np.asarray(pts), "rows": len(us), "cols": len(vs)}
