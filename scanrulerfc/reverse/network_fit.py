# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/core/networkFit.ts
# SPDX-License-Identifier: AGPL-3.0-only
#
# A patch network's patches fitted to the scan together.
#
# Each four-sided cell is a cubic B-spline patch over the unit square its
# map put the cell's points on (network_map.py). Its four boundary rows of
# poles are its sides' curves, fitted first (network_curve.py) and faired
# by the same smoothness as the patches: a side that is one curve takes that
# curve's poles, so two neighbours share the poles of the curve between
# them and meet on it exactly. For that their knots along it must be the
# same, and so must a patch's on its opposite sides: the sides tied by
# either rule (opposite in a cell, the same curve in two cells) are put
# together by union-find into strips that run across the network, each with
# one span count, Auto's or the operator's. Auto starts every strip at four
# and grows it only where a patch on it misses its points by more than a
# tolerance beyond their noise (fit_network).
#
# The inner poles of all the patches are the unknowns of one system, three
# coordinates each, solved by conjugate gradient (sparse.py). Its terms:
#
# - the data: each scan point of a cell at its (u, v) on the patch;
# - the fairing: Fit Surface's third divided differences of the net along
#   u, along v and mixed, weighted for the patch's size, its slider
#   `smoothness`, of the patch's departure from its sides' Coons surface;
# - the pull: net cells with no point within a cell of them held near the
#   Coons surface of the patch's four sides;
# - tangency across every shared curve not marked a crease: with B a pole of
#   the curve and A and C the first inner poles either side of it,
#   (B - A) - lambda (C - B) = 0, lambda the ratio of the two cross-spacings
#   read off a first fit without it. Along the curve it is held exactly (A
#   and C written as B - d and B + lambda d, one unknown d for the two) and
#   at the two poles next to each corner as a heavy weight. At a corner
#   where three, five or six patches meet it is dropped there (the vertex
#   enclosure problem) and the angle there reported instead; so is it at a
#   corner of four whose ties fold the patches, which a patch turning more
#   than CORNER_TURN from the first fit tells. A T-junction's curve shares
#   no poles with the longer side, and is held tangent by weight, pole by
#   pole, as a body's face holds a patch.
#
# The data's (u, v) come from the map; after each solve every point is
# projected onto its patch (Gauss-Newton) and the fit solved again from the
# last: three rounds, or fewer once the RMS moves less than 1 %. A robust
# fit leaves out the points beyond three robust sigmas of the first pass.
#
# Here the original's per-patch 7 x 7 pole bands are kept, and the system
# in the unknowns is formed from them as a sparse matrix once a solve and
# handed to the conjugate gradient, with the original's Jacobi diagonal; the
# data's terms are added with numpy, point by point as the original adds
# them. Inputs and results are dicts with the original's fields.

import math

import numpy as np

from ..linalg import sym_eigen
from ._js import js_hypot, js_round
from .network_curve import (DEFAULT_TOLERANCE, SPANS_MAX, SPANS_MIN, auto_spans, curve_samples, end_tangent, fit_curve, join_traces, leaving_direction,
                            reversed_poles)
from .network_spline import (DEGREE, PatchNet, basis_at_v, curve_derivative, curve_point, curve_points_v, divided_weights, greville_of, hypot3_v,
                             patch_normal, patch_point, patch_points_v)
from .sparse import LinearOperator, conjugate_gradient, csr_from_triplets

SMOOTHNESS_SCALE = 1e-2
PULL = 0.01
PULL_REACH = 1
PULL_SAMPLES = 3
TIE_WEIGHT = 1e4
CORNER_TURN = 30
RATIO_LIMIT = 5
POINTS_PER_CELL = 50
ROUNDS = 3
ROUNDS_SETTLE = 0.01
NEWTON_STEPS = 3
ROBUST_SIGMAS = 3
ROBUST_FLOOR = 0.01
EDGES_PER_SPAN = 3
AUTO_START = 4
AUTO_GROWTH = 1.5
AUTO_ROUNDS = 8
AUTO_ALIKE = 0.75
AUTO_HELPS = 0.8
MISFIT_POINTS = 8
SOLVE_TOLERANCE = 1e-8
EDGE_SAMPLES = 24
WORST_POINTS = 3
BAND = 49


def _strips_of(patches):
    n = len(patches) * 4
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def join(a, b):
        x = find(a)
        y = find(b)
        if x != y:
            parent[max(x, y)] = min(x, y)

    by_curve = {}
    for i, p in enumerate(patches):
        join(i * 4, i * 4 + 2)
        join(i * 4 + 1, i * 4 + 3)
        for k, s in enumerate(p["sides"]):
            if len(s["edges"]) != 1:
                continue
            c = s["edges"][0]["curve"]
            had = by_curve.get(c)
            if had is not None:
                join(had, i * 4 + k)
            else:
                by_curve[c] = i * 4 + k
    ids = {}
    of = []
    for i in range(len(patches)):
        row = []
        for k in range(4):
            r = find(i * 4 + k)
            if r not in ids:
                ids[r] = len(ids)
            row.append(ids[r])
        of.append(row)
    return of, len(ids)


def _side_pole(nu, nv, k, s):
    """Where pole s (from the side's start) of a patch's side k is in its
    net, and the first inner pole in from it: (boundary, inner)."""
    if k == 0:
        return (s, 0), (s, 1)
    if k == 1:
        return (nu + 2, s), (nu + 1, s)
    if k == 2:
        return (nu + 2 - s, nv + 2), (nu + 2 - s, nv + 1)
    return (0, nv + 2 - s), (1, nv + 2 - s)


def fit_network(inp):
    """The patches fitted together; Auto's strips start at AUTO_START spans
    and grow only where a patch strays from its points by more than the
    tolerance beyond their scatter, and only while that helps."""
    patches = inp["patches"]
    curve_of = {c["id"]: c for c in inp["curves"]}
    of, count = _strips_of(patches)

    def points_of(cid):
        c = curve_of[cid]
        return c.get("exact") or c["trace"]

    def side_trace(side):
        return join_traces([(points_of(h["curve"]), not h["forward"]) for h in side["edges"]])

    strips = {"of": of, "auto": [True] * count, "curves": [[] for _ in range(count)], "sideLength": [[0.0] * 4 for _ in patches]}
    cap = [SPANS_MIN] * count
    spacing = inp.get("spacing")
    for i, p in enumerate(patches):
        for k, s in enumerate(p["sides"]):
            st = of[i][k]
            for h in s["edges"]:
                if h["curve"] not in strips["curves"][st]:
                    strips["curves"][st].append(h["curve"])
            length = side_trace(s)["length"]
            strips["sideLength"][i][k] = length
            dense = max(SPANS_MIN, math.floor(length / (EDGES_PER_SPAN * spacing))) if spacing else SPANS_MAX
            cap[st] = max(cap[st], min(SPANS_MAX, dense))
    spans = [min(AUTO_START, c) for c in cap]
    given_spans = inp.get("spans") or {}
    for st, curves in enumerate(strips["curves"]):
        given = None
        for c in sorted(curves):
            if str(c) in given_spans:
                given = given_spans[str(c)]
                break
        if given is not None:
            spans[st] = max(SPANS_MIN, min(SPANS_MAX, int(js_round(given))))
            strips["auto"][st] = False
    fit = _fit_at(inp, strips, spans)
    tolerance = inp.get("tolerance")
    if tolerance is None:
        tolerance = DEFAULT_TOLERANCE
    patches_of = [[] for _ in range(count)]
    for i, sides in enumerate(of):
        for st in dict.fromkeys(sides):
            patches_of[st].append(i)
    leaps = set()
    stays = set()

    def grows(st):
        return strips["auto"][st] and st not in stays and spans[st] < cap[st]

    for _ in range(AUTO_ROUNDS):
        grow = []
        for i, p in enumerate(fit["patches"]):
            if not p["misfit"] > tolerance:
                continue
            side = strips["sideLength"][i]
            ways = [{"st": of[i][0], "span": (side[0] + side[2]) / 2 / p["net"].nu}, {"st": of[i][1], "span": (side[1] + side[3]) / 2 / p["net"].nv}]
            ways = [w for w in ways if grows(w["st"])]
            longest = max([0.0] + [w["span"] for w in ways])
            for w in ways:
                if w["span"] >= AUTO_ALIKE * longest and w["st"] not in grow:
                    grow.append(w["st"])
        if not grow:
            break
        nxt = list(spans)
        for st in grow:
            nxt[st] = min(cap[st], math.ceil(spans[st] * (AUTO_GROWTH ** 2 if st in leaps else AUTO_GROWTH)))
        tried = _fit_at(inp, strips, nxt)
        kept = list(nxt)
        for st in grow:
            helped = any(fit["patches"][i]["misfit"] > tolerance and tried["patches"][i]["misfit"] <= AUTO_HELPS * fit["patches"][i]["misfit"] for i in patches_of[st])
            if helped:
                leaps.discard(st)
                continue
            kept[st] = spans[st]
            if st in leaps:
                stays.add(st)
            else:
                leaps.add(st)
        if all(x == nxt[st] for st, x in enumerate(kept)):
            spans = nxt
            fit = tried
            continue
        if all(x == spans[st] for st, x in enumerate(kept)):
            continue
        spans = kept
        fit = _fit_at(inp, strips, spans)
    return fit


def _unit(p):
    l = js_hypot(p[0], p[1], p[2])
    return [p[0] / l, p[1] / l, p[2] / l], l


def _band_entries(net):
    """The band's (pole, offset) pairs inside the net, as bandMultiply
    reads them: band index, row pole, column pole."""
    rows = net.nu + 3
    cols = net.nv + 3
    i = np.arange(rows)[:, None, None, None]
    j = np.arange(cols)[None, :, None, None]
    a = np.arange(7)[None, None, :, None]
    b = np.arange(7)[None, None, None, :]
    ok = (a >= np.maximum(0, 3 - i)) & (a <= np.minimum(6, rows + 2 - i)) & (b >= np.maximum(0, 3 - j)) & (b <= np.minimum(6, cols + 2 - j))
    p = i * cols + j
    q = p + (a - 3) * cols + (b - 3)
    band = p * BAND + a * 7 + b
    shape = (rows, cols, 7, 7)
    return np.broadcast_to(band, shape)[ok], np.broadcast_to(p, shape)[ok], np.broadcast_to(q, shape)[ok]


def _band_multiply(H, net, y):
    """H y over a patch's poles, three coordinates: (poles * 3,)."""
    bidx, p, q = _band_entries(net)
    Y = np.asarray(y, dtype=float).reshape(-1, 3)
    vals = H[bidx]
    out = np.zeros(Y.shape)
    for c in range(3):
        out[:, c] = np.bincount(p, weights=vals * Y[q, c], minlength=Y.shape[0])
    return out.reshape(-1)


def _fairing_band(net, smoothness, rows):
    rows_n = net.nu + 3
    cols = net.nv + 3
    H = np.zeros(rows_n * cols * BAND)
    if not smoothness > 0:
        return H

    def length_of(poles):
        P = np.asarray(poles, dtype=float).reshape(-1, 3)
        l = 0.0
        for m in range(1, P.shape[0]):
            l += js_hypot(P[m, 0] - P[m - 1, 0], P[m, 1] - P[m - 1, 1], P[m, 2] - P[m - 1, 2])
        return l

    Lu = max(1e-6, (length_of(rows[0]["poles"]) + length_of(rows[2]["poles"])) / 2)
    Lv = max(1e-6, (length_of(rows[1]["poles"]) + length_of(rows[3]["poles"])) / 2)
    s = smoothness * SMOOTHNESS_SCALE
    area = (1 / max(1, rows_n - 1)) * (1 / max(1, cols - 1))
    xu = greville_of(net.nu).tolist()
    xv = greville_of(net.nv).tolist()

    def add(idx, w, weight):
        for a in range(len(idx)):
            ia, ja = divmod(idx[a], cols)
            for b in range(len(idx)):
                ib, jb = divmod(idx[b], cols)
                H[idx[a] * BAND + (ib - ia + 3) * 7 + (jb - ja + 3)] += weight * w[a] * w[b]

    def cross(i, j, wu, wv, weight):
        idx = []
        w = []
        for a in range(len(wu)):
            for b in range(len(wv)):
                idx.append((i + a) * cols + j + b)
                w.append(wu[a] * wv[b])
        add(idx, w, weight)

    wu3 = s * area * (Lv / Lu) ** 3
    wv3 = s * area * (Lu / Lv) ** 3
    w21 = 3 * s * area * (Lv / Lu)
    w12 = 3 * s * area * (Lu / Lv)
    for i in range(rows_n):
        for j in range(cols):
            if i + 3 < rows_n:
                cross(i, j, divided_weights(xu, i, 3), [1], wu3)
            if j + 3 < cols:
                cross(i, j, [1], divided_weights(xv, j, 3), wv3)
            if i + 2 < rows_n and j + 1 < cols:
                cross(i, j, divided_weights(xu, i, 2), divided_weights(xv, j, 1), w21)
            if i + 1 < rows_n and j + 2 < cols:
                cross(i, j, divided_weights(xu, i, 1), divided_weights(xv, j, 2), w12)
    return H


def _add_points(H, g, cols, su, sv, bu, bv, xyz, weight):
    """Points' terms added to a patch's band and right-hand side (the
    original's addPoint, for many points at once)."""
    if su.shape[0] == 0:
        return
    wt = np.broadcast_to(np.asarray(weight, dtype=float), su.shape)
    G = g.reshape(-1, 3)
    for a1 in range(4):
        wa = wt * bu[:, a1]
        for b1 in range(4):
            w1 = wa * bv[:, b1]
            p1 = (su - 3 + a1) * cols + sv - 3 + b1
            for c in range(3):
                G[:, c] += np.bincount(p1, weights=w1 * xyz[:, c], minlength=G.shape[0])
            row = p1 * BAND + 3 - b1
            idx = []
            val = []
            for a2 in range(4):
                w = w1 * bu[:, a2]
                at = row + (a2 - a1 + 3) * 7
                for b2 in range(4):
                    idx.append(at + b2)
                    val.append(w * bv[:, b2])
            H += np.bincount(np.concatenate(idx), weights=np.concatenate(val), minlength=H.shape[0])


def _coons_points(net, u, v):
    rows = net.nu + 3
    cols = net.nv + 3
    P = np.asarray(net.poles).reshape(rows, cols, 3)
    a = curve_points_v(P[:, 0].reshape(-1), net.nu, u)
    c = curve_points_v(P[:, cols - 1].reshape(-1), net.nu, u)
    d = curve_points_v(P[0, :].reshape(-1), net.nv, v)
    e = curve_points_v(P[rows - 1, :].reshape(-1), net.nv, v)
    p00, p10, p01, p11 = P[0, 0], P[rows - 1, 0], P[0, cols - 1], P[rows - 1, cols - 1]
    u = np.asarray(u)[:, None]
    v = np.asarray(v)[:, None]
    return (1 - v) * a + v * c + (1 - u) * d + u * e - ((1 - u) * (1 - v) * p00 + u * (1 - v) * p10 + (1 - u) * v * p01 + u * v * p11)


def _coons_poles(net):
    """The poles of a net's Coons surface: the bilinearly blended surface of
    its four boundary rows, which a B-spline over the same knots holds
    exactly, so its boundary poles are the rows themselves."""
    rows = net.nu + 3
    cols = net.nv + 3
    gu = greville_of(net.nu)
    gv = greville_of(net.nv)
    P = np.asarray(net.poles, dtype=float).reshape(rows, cols, 3)
    out = P.copy()
    u = gu[1:rows - 1][:, None, None]
    v = gv[1:cols - 1][None, :, None]
    out[1:rows - 1, 1:cols - 1] = ((1 - v) * P[1:rows - 1, 0][:, None] + v * P[1:rows - 1, cols - 1][:, None] + (1 - u) * P[0, 1:cols - 1][None] + u * P[rows - 1, 1:cols - 1][None]
                                   - ((1 - u) * (1 - v) * P[0, 0] + u * (1 - v) * P[rows - 1, 0] + (1 - u) * v * P[0, cols - 1] + u * v * P[rows - 1, cols - 1]))
    return out.reshape(-1)


def _add_pull(H, g, net, held, points):
    held_count = int(held.sum())

    def near(a, b):
        for i in range(max(0, a - PULL_REACH), min(net.nu - 1, a + PULL_REACH) + 1):
            for j in range(max(0, b - PULL_REACH), min(net.nv - 1, b + PULL_REACH) + 1):
                if held[i * net.nv + j]:
                    return True
        return False

    weight = (PULL * max(1, points)) / max(1, held_count) / (PULL_SAMPLES * PULL_SAMPLES)
    us = []
    vs = []
    for a in range(net.nu):
        for b in range(net.nv):
            if near(a, b):
                continue
            for s in range(PULL_SAMPLES):
                for t in range(PULL_SAMPLES):
                    us.append((a + (s + 0.5) / PULL_SAMPLES) / net.nu)
                    vs.append((b + (t + 0.5) / PULL_SAMPLES) / net.nv)
    if not us:
        return
    u = np.array(us)
    v = np.array(vs)
    target = _coons_points(net, u, v)
    su, bu = basis_at_v(net.nu, u)
    sv, bv = basis_at_v(net.nv, v)
    _add_points(H, g, net.nv + 3, su, sv, bu, bv, target, weight)


def _smooth_ratios(ties):
    r = [t["ratio"] for t in ties]
    for i in range(len(ties)):
        s = r[i]
        n = 1
        for j in (i - 1, i + 1):
            if j < 0 or j >= len(ties) or ties[j]["curve"] != ties[i]["curve"]:
                continue
            s += r[j]
            n += 1
        ties[i]["ratio"] = s / n


def _torn_corners(nets, free, pole_base, patches, tied):
    torn = set()
    cos = math.cos((CORNER_TURN * math.pi) / 180)
    samples = 4
    for i, p in enumerate(patches):
        net = nets[i]
        size = (net.nu + 3) * (net.nv + 3)
        was = PatchNet(net.nu, net.nv, free[pole_base[i] * 3:(pole_base[i] + size) * 3])
        for k, node in enumerate(p["corners"]):
            if node not in tied or node in torn:
                continue
            cu = 1 if k in (1, 2) else 0
            cv = 1 if k >= 2 else 0
            uu = []
            vv = []
            for s in range(samples + 1):
                for t in range(samples + 1):
                    du = ((2 / net.nu) * s) / samples
                    dv = ((2 / net.nv) * t) / samples
                    uu.append(1 - du if cu else du)
                    vv.append(1 - dv if cv else dv)
            a = _normals(net, np.array(uu), np.array(vv))
            b = _normals(was, np.array(uu), np.array(vv))
            if ((a * b).sum(axis=1) < cos).any():
                torn.add(node)
    return torn


def _normals(net, u, v):
    _, du, dv = patch_points_v(net, u, v)
    n = np.cross(du, dv)
    l = hypot3_v(n[:, 0], n[:, 1], n[:, 2])
    l = np.where(l > 0, l, 1.0)
    return n / l[:, None]


def _project(nets, data):
    """Each point projected onto its patch: Gauss-Newton from its (u, v),
    held inside the square."""
    for net, d in zip(nets, data):
        if d["count"] == 0:
            continue
        U = d["uv"].reshape(-1, 2)
        u = U[:, 0].copy()
        v = U[:, 1].copy()
        X = d["xyz"].reshape(-1, 3)
        live = np.ones(u.shape[0], dtype=bool)
        for _ in range(NEWTON_STEPS):
            if not live.any():
                break
            p, du, dv = patch_points_v(net, u, v)
            r = X - p
            a = (du * du).sum(axis=1)
            b = (du * dv).sum(axis=1)
            c = (dv * dv).sum(axis=1)
            gu = (du * r).sum(axis=1)
            gv = (dv * r).sum(axis=1)
            det = a * c - b * b
            live &= det > 1e-300
            with np.errstate(divide="ignore", invalid="ignore"):
                nu_ = np.clip(u + (c * gu - b * gv) / det, 0.0, 1.0)
                nv_ = np.clip(v + (a * gv - b * gu) / det, 0.0, 1.0)
            u = np.where(live, nu_, u)
            v = np.where(live, nv_, v)
        U[:, 0] = u
        U[:, 1] = v


def _residuals(net, d):
    if d["count"] == 0:
        return np.zeros(0)
    U = d["uv"].reshape(-1, 2)
    p, du, dv = patch_points_v(net, U[:, 0], U[:, 1])
    n = np.cross(du, dv)
    r = d["xyz"].reshape(-1, 3) - p
    dist = hypot3_v(r[:, 0], r[:, 1], r[:, 2])
    return np.where((r * n).sum(axis=1) < 0, -dist, dist)


def _residual_rms(nets, data):
    sq = 0.0
    n = 0
    res = []
    for net, d in zip(nets, data):
        r = _residuals(net, d)
        k = d["keep"]
        sq += float((r[k] * r[k]).sum())
        n += int(k.sum())
        res.append(r)
    return (math.sqrt(sq / n) if n > 0 else 0.0), res


def _drop_outliers(nets, data):
    for net, d in zip(nets, data):
        r = _residuals(net, d)
        srt = np.sort(r)
        med = float(srt[srt.shape[0] >> 1]) if srt.shape[0] else 0.0
        dev = np.sort(np.abs(r - med))
        limit = max(ROBUST_SIGMAS * 1.4826 * (float(dev[dev.shape[0] >> 1]) if dev.shape[0] else 0.0), ROBUST_FLOOR)
        d["keep"] = np.abs(r - med) <= limit
        d["kept"] = int(d["keep"].sum())


def _take_evenly(p, cap):
    total = p["uv"].shape[0] // 2
    step = max(1, total / max(1, cap))
    count = min(total, math.ceil(total / step))
    i = np.minimum(total - 1, np.floor(np.arange(count) * step).astype(np.int64))
    X = np.asarray(p["xyz"], dtype=float).reshape(-1, 3)[i]
    U = np.asarray(p["uv"], dtype=float).reshape(-1, 2)[i]
    return {"count": count, "xyz": X.reshape(-1).copy(), "uv": U.reshape(-1).copy(), "keep": np.ones(count, dtype=bool), "kept": count}


def _misfit_of(d, r, aspect):
    k = d["keep"]
    rk = r[k]
    n = rk.shape[0]
    if n == 0:
        return 0.0
    sq = float((rk * rk).sum())
    cells = n / MISFIT_POINTS
    bu = max(1, int(js_round(math.sqrt(cells * aspect))))
    bv = max(1, int(js_round(math.sqrt(cells / aspect))))
    U = d["uv"].reshape(-1, 2)[k]
    c = np.clip(np.floor(U[:, 0] * bu), 0, bu - 1).astype(np.int64) * bv + np.clip(np.floor(U[:, 1] * bv), 0, bv - 1).astype(np.int64)
    s = np.bincount(c, weights=rk, minlength=bu * bv)
    s2 = np.bincount(c, weights=rk * rk, minlength=bu * bv)
    cnt = np.bincount(c, minlength=bu * bv)
    ok = cnt >= 2
    within = float((s2[ok] - (s[ok] * s[ok]) / cnt[ok]).sum())
    free = int((cnt[ok] - 1).sum())
    if free == 0:
        return math.sqrt(sq / n)
    scatter = within / free
    misfit = math.sqrt(max(0.0, sq / n - scatter))
    # A negative scatter (rounding) reads as the original's NaN: no misfit.
    return misfit if scatter >= 0 and misfit > math.sqrt(scatter) * (8 / n) ** 0.25 else 0.0


def _on_side(k, f):
    if k == 0:
        return f, 0.0
    if k == 1:
        return 1.0, f
    if k == 2:
        return 1 - f, 1.0
    return 0.0, 1 - f


def _acos_deg(cos):
    return (math.acos(max(-1.0, min(1.0, cos))) * 180) / math.pi


def _edge_reading(s, fitted, skip_from=0.0, skip_to=0.0):
    P, Q = fitted[s["patches"][0]], fitted[s["patches"][1]]
    forward_p = P["sides"][s["sides"][0]]["edges"][0]["forward"]
    forward_q = Q["sides"][s["sides"][1]]["edges"][0]["forward"]
    angle = 0.0
    gap = 0.0
    total = 0.0
    count = 0
    near_from = 0.0
    near_to = 0.0

    def angle_at(t):
        up, vp = _on_side(s["sides"][0], t if forward_p else 1 - t)
        uq, vq = _on_side(s["sides"][1], t if forward_q else 1 - t)
        np_ = patch_normal(P["net"], up, vp)
        nq = patch_normal(Q["net"], uq, vq)
        return _acos_deg(np_[0] * nq[0] + np_[1] * nq[1] + np_[2] * nq[2])

    pp = [0.0] * 3
    pq = [0.0] * 3
    for k in range(EDGE_SAMPLES + 1):
        t = k / EDGE_SAMPLES
        up, vp = _on_side(s["sides"][0], t if forward_p else 1 - t)
        uq, vq = _on_side(s["sides"][1], t if forward_q else 1 - t)
        patch_point(P["net"], up, vp, pp)
        patch_point(Q["net"], uq, vq, pq)
        gap = max(gap, js_hypot(pp[0] - pq[0], pp[1] - pq[1], pp[2] - pq[2]))
        if k == 0 or k == EDGE_SAMPLES or t < skip_from or t > 1 - skip_to:
            continue
        a = angle_at(t)
        angle = max(angle, a)
        total += a
        count += 1
    if s["crease"] and count > 0:
        angle = total / count
    for k in range(1, EDGE_SAMPLES + 1):
        if skip_from > 0:
            near_from = max(near_from, angle_at((skip_from * k) / EDGE_SAMPLES))
        if skip_to > 0:
            near_to = max(near_to, angle_at(1 - (skip_to * k) / EDGE_SAMPLES))
    return {"curve": s["curve"], "patches": s["patches"], "gap": gap, "angle": angle, "crease": s["crease"]}, near_from, near_to


def _nearest_on(poles, spans, x):
    """The parameter of a curve's point nearest x: the nearest of a few
    samples, then Gauss-Newton along it."""
    Y = curve_points_v(poles, spans, np.arange(65) / 64)
    d = hypot3_v(Y[:, 0] - x[0], Y[:, 1] - x[1], Y[:, 2] - x[2])
    s = int(np.argmin(d)) / 64
    for _ in range(4):
        y = curve_point(poles, spans, s)
        dd_ = curve_derivative(poles, spans, s)
        dd = dd_[0] * dd_[0] + dd_[1] * dd_[1] + dd_[2] * dd_[2]
        if not dd > 0:
            break
        s = min(1.0, max(0.0, s + ((x[0] - y[0]) * dd_[0] + (x[1] - y[1]) * dd_[1] + (x[2] - y[2]) * dd_[2]) / dd))
    return s


def _tee_reading(curve, fit, fitted, patches, sides, forward_p, crease):
    P, Q = fitted[patches[0]], fitted[patches[1]]
    row = Q["sides"][sides[1]]["poles"]
    spans = Q["net"].nu if sides[1] % 2 == 0 else Q["net"].nv
    gap = 0.0
    angle = 0.0
    for k in range(1, EDGE_SAMPLES):
        t = k / EDGE_SAMPLES
        x = curve_point(fit["poles"], fit["spans"], t)
        s = _nearest_on(row, spans, x)
        y = curve_point(row, spans, s)
        gap = max(gap, js_hypot(y[0] - x[0], y[1] - x[1], y[2] - x[2]))
        up, vp = _on_side(sides[0], t if forward_p else 1 - t)
        uq, vq = _on_side(sides[1], s)
        np_ = patch_normal(P["net"], up, vp)
        nq = patch_normal(Q["net"], uq, vq)
        angle = max(angle, _acos_deg(np_[0] * nq[0] + np_[1] * nq[1] + np_[2] * nq[2]))
    return {"curve": curve, "patches": list(patches), "gap": gap, "angle": angle, "crease": crease, "tee": True}


def _corner_reading(node, at, fitted):
    normals = []
    for p in fitted:
        if node not in p["corners"]:
            continue
        k = p["corners"].index(node)
        u, v = _on_side(k, 0)
        normals.append(patch_normal(p["net"], u, v))
    angle = 0.0
    for a in range(len(normals)):
        for b in range(a + 1, len(normals)):
            angle = max(angle, _acos_deg(normals[a][0] * normals[b][0] + normals[a][1] * normals[b][1] + normals[a][2] * normals[b][2]))
    return {"node": node, "at": at, "patches": len(normals), "angle": angle}


def _fit_at(inp, strips, strip_spans):
    patches = inp["patches"]
    side_length = strips["sideLength"]
    curve_of = {c["id"]: c for c in inp["curves"]}
    node_of = {n["id"]: n for n in inp["nodes"]}
    spacing = inp.get("spacing")
    curve_spans = {}
    for i, p in enumerate(patches):
        for k, s in enumerate(p["sides"]):
            if len(s["edges"]) == 1:
                curve_spans[s["edges"][0]["curve"]] = strip_spans[strips["of"][i][k]]

    # ---- the curves, held tangent where they go on through a node ---------
    leaving = {}
    held = {}
    for c in inp["curves"]:
        own = c.get("exact") or c["trace"]
        if spacing:
            out = leaving_direction(own, 0, spacing)
            back = leaving_direction(own, 1, spacing)
        else:
            out = end_tangent(c["fit"], 0)
            t = end_tangent(c["fit"], 1)
            back = [-t[0], -t[1], -t[2]]
        leaving.setdefault(c["from"], []).append({"curve": c["id"], "end": 0, "dir": out})
        leaving.setdefault(c["to"], []).append({"curve": c["id"], "end": 1, "dir": back})
        held[(c["id"], 0)] = out
        held[(c["id"], 1)] = back
    straight_on = math.cos((30 * math.pi) / 180)
    on_crease = set()
    for c in inp["curves"]:
        if not c["crease"]:
            continue
        on_crease.add(c["from"])
        on_crease.add(c["to"])
    for node, lst in leaving.items():
        pairs = []
        for a in range(len(lst)):
            for b in range(a + 1, len(lst)):
                if lst[a]["curve"] == lst[b]["curve"]:
                    continue
                if node in on_crease and not (curve_of.get(lst[a]["curve"], {}).get("crease") and curve_of.get(lst[b]["curve"], {}).get("crease")):
                    continue
                da, db = lst[a]["dir"], lst[b]["dir"]
                cos = -(da[0] * db[0] + da[1] * db[1] + da[2] * db[2])
                if cos > straight_on:
                    pairs.append((a, b, cos))
        pairs.sort(key=lambda x: -x[2])
        taken = set()
        for a, b, _ in pairs:
            if a in taken or b in taken:
                continue
            taken.add(a)
            taken.add(b)
            d = lst[a]["dir"]
            e = lst[b]["dir"]
            l = [d[0] - e[0], d[1] - e[1], d[2] - e[2]]
            n = js_hypot(l[0], l[1], l[2]) or 1
            line = [l[0] / n, l[1] / n, l[2] / n]
            held[(lst[a]["curve"], lst[a]["end"])] = line
            held[(lst[b]["curve"], lst[b]["end"])] = [-line[0], -line[1], -line[2]]

    def flatten_onto(x, normal):
        d = held.get((x["curve"], x["end"]), x["dir"])
        s = d[0] * normal[0] + d[1] * normal[1] + d[2] * normal[2]
        p = [d[0] - s * normal[0], d[1] - s * normal[1], d[2] - s * normal[2]]
        l = js_hypot(p[0], p[1], p[2])
        if l > 1e-9:
            held[(x["curve"], x["end"])] = [p[0] / l, p[1] / l, p[2] / l]

    for node, lst in leaving.items():
        if len(lst) < 3 or node in on_crease:
            continue
        dirs = [held.get((x["curve"], x["end"]), x["dir"]) for x in lst]
        m = [0.0] * 9
        for d in dirs:
            for a in range(3):
                for b in range(3):
                    m[a * 3 + b] += d[a] * d[b]
        normal = [float(x) for x in sym_eigen(m)[1][0]]
        for x, d in zip(lst, dirs):
            s = d[0] * normal[0] + d[1] * normal[1] + d[2] * normal[2]
            p = [d[0] - s * normal[0], d[1] - s * normal[1], d[2] - s * normal[2]]
            l = js_hypot(p[0], p[1], p[2])
            if l > 1e-9:
                held[(x["curve"], x["end"])] = [p[0] / l, p[1] / l, p[2] / l]
    tangent_to = {}
    for b in inp.get("bodySides") or []:
        if b["mode"] == "tangent":
            tangent_to[b["curve"]] = b
    for curve, side in tangent_to.items():
        c = curve_of.get(curve)
        if c is None:
            continue
        for node in (c["from"], c["to"]):
            at = node_of.get(node, {}).get("at")
            got = side["normals"]([at]) if at is not None else None
            normal = got[0] if got else None
            if normal is None:
                continue
            for x in leaving.get(node, []):
                flatten_onto(x, normal)
    smoothness = max(0.0, inp["smoothness"]) * SMOOTHNESS_SCALE
    patch_fairing = []
    for i, p in enumerate(patches):
        area = ((side_length[i][0] + side_length[i][2]) / 2) * ((side_length[i][1] + side_length[i][3]) / 2)
        points = min(p["uv"].shape[0] // 2, POINTS_PER_CELL * strip_spans[strips["of"][i][0]] * strip_spans[strips["of"][i][1]])
        patch_fairing.append((smoothness * area ** 3) / max(1, points))
    on_patches = {}
    for i, p in enumerate(patches):
        for s in p["sides"]:
            for h in s["edges"]:
                on_patches.setdefault(h["curve"], []).append(i)

    def fairing_of(trace, on):
        if not smoothness > 0 or not on or not trace["length"] > 0:
            return 0.0
        return ((len(trace["points"]) / 3) / trace["length"]) * (sum(patch_fairing[i] for i in on) / len(on))

    fits = {}
    for c in inp["curves"]:
        own = c.get("exact") or c["trace"]
        if c["id"] in curve_spans:
            spans = curve_spans[c["id"]]
        else:
            spans = min(auto_spans(own), max(SPANS_MIN, math.floor(own["length"] / (EDGES_PER_SPAN * spacing))) if spacing else SPANS_MAX)
        out = held.get((c["id"], 0))
        back = held.get((c["id"], 1))
        fairing = 0.0 if c.get("exact") else fairing_of(own, on_patches.get(c["id"], []))
        ends = {}
        if out is not None:
            ends["startTangent"] = out
        if back is not None:
            ends["endTangent"] = [-back[0], -back[1], -back[2]]
        fits[c["id"]] = fit_curve(own, spans, ends, fairing)

    # ---- the nets: boundary rows from the sides ---------------------------
    nets = []
    side_rows = []
    pole_base = []
    pole_count = 0
    for i, p in enumerate(patches):
        nu = strip_spans[strips["of"][i][0]]
        nv = strip_spans[strips["of"][i][1]]
        net = PatchNet(nu, nv, np.zeros((nu + 3) * (nv + 3) * 3))
        rows = []
        for k, s in enumerate(p["sides"]):
            spans = nu if k % 2 == 0 else nv
            if len(s["edges"]) == 1:
                f = fits[s["edges"][0]["curve"]]
                poles = f["poles"] if s["edges"][0]["forward"] else reversed_poles(f["poles"])
            else:
                poles = fit_curve(join_traces([(curve_samples(fits[h["curve"]]), not h["forward"]) for h in s["edges"]]), spans)["poles"]
            rows.append({"edges": s["edges"], "poles": poles, "single": len(s["edges"]) == 1})
            for m in range(spans + 3):
                (bi, bj), _ = _side_pole(nu, nv, k, m)
                net.poles[(bi * (nv + 3) + bj) * 3:(bi * (nv + 3) + bj) * 3 + 3] = poles[m * 3:m * 3 + 3]
        net.poles[:] = _coons_poles(net)
        nets.append(net)
        side_rows.append(rows)
        pole_base.append(pole_count)
        pole_count += (nu + 3) * (nv + 3)

    # ---- the data -----------------------------------------------------------
    data = [_take_evenly(p, POINTS_PER_CELL * nets[i].nu * nets[i].nv) for i, p in enumerate(patches)]
    _project(nets, data)

    # ---- the shared curves, the ties across them, and the corners -----------
    shared_by = {}
    for i, p in enumerate(patches):
        for k, s in enumerate(p["sides"]):
            if len(s["edges"]) != 1:
                continue
            h = s["edges"][0]
            shared_by.setdefault(h["curve"], []).append({"patch": i, "side": k, "forward": h["forward"]})
    corner_patches = {}
    for p in patches:
        for c in p["corners"]:
            corner_patches[c] = corner_patches.get(c, 0) + 1

    def surrounded(node):
        return all(len(shared_by.get(x["curve"], [])) == 2 for x in leaving.get(node, []))

    irregular = set()
    irregular_order = []
    for node, cnt in corner_patches.items():
        if cnt != 4 and cnt >= 3 and surrounded(node):
            irregular.add(node)
            irregular_order.append(node)
    ties = []
    shared = []
    for curve, users in shared_by.items():
        if len(users) != 2:
            continue
        c = curve_of[curve]
        shared.append({"curve": curve, "patches": [users[0]["patch"], users[1]["patch"]], "crease": c["crease"], "sides": [users[0]["side"], users[1]["side"]]})
        if c["crease"]:
            continue
        n = fits[curve]["spans"] + 3
        P_, Q_ = users
        for m in range(1, n - 1):
            near_from = m == 1
            near_to = m == n - 2
            if (near_from and c["from"] in irregular) or (near_to and c["to"] in irregular):
                continue

            def at(u):
                net = nets[u["patch"]]
                s = m if u["forward"] else n - 1 - m
                boundary, inner = _side_pole(net.nu, net.nv, u["side"], s)
                return pole_base[u["patch"]] + boundary[0] * (net.nv + 3) + boundary[1], pole_base[u["patch"]] + inner[0] * (net.nv + 3) + inner[1]

            pb, pi = at(P_)
            _, qi = at(Q_)
            ties.append({"curve": curve, "a": pi, "c": qi, "b": pb, "exact": not (near_from or near_to), "ratio": 1.0, "node": c["from"] if near_from else c["to"] if near_to else None})

    # ---- the patches beside a body's face, tangent to it ------------------
    face_rows = []
    for curve, side in tangent_to.items():
        users = shared_by.get(curve, [])
        f = fits.get(curve)
        if f is None:
            continue
        n = f["spans"] + 3
        gr = greville_of(f["spans"])
        at = [curve_point(f["poles"], f["spans"], float(gr[m])) for m in range(n)]
        normals = side["normals"](at)
        if not normals:
            continue
        for u in users:
            net = nets[u["patch"]]
            for m in range(1, n - 1):
                s = m if u["forward"] else n - 1 - m
                boundary, inner = _side_pole(net.nu, net.nv, u["side"], s)
                b = (boundary[0] * (net.nv + 3) + boundary[1]) * 3
                a = pole_base[u["patch"]] + inner[0] * (net.nv + 3) + inner[1]
                nm = normals[m]
                face_rows.append({"pole": a, "n": nm, "rhs": nm[0] * net.poles[b] + nm[1] * net.poles[b + 1] + nm[2] * net.poles[b + 2]})

    # ---- the system ---------------------------------------------------------
    all_poles = np.zeros(pole_count * 3)
    is_inner = np.zeros(pole_count, dtype=bool)
    for i, net in enumerate(nets):
        size = (net.nu + 3) * (net.nv + 3)
        all_poles[pole_base[i] * 3:(pole_base[i] + size) * 3] = net.poles
        g = np.arange(size).reshape(net.nu + 3, net.nv + 3)
        is_inner[pole_base[i] + g[1:net.nu + 2, 1:net.nv + 2].reshape(-1)] = True

    def layout(tied):
        base = all_poles.copy()
        z = np.full(pole_count * 3, -1, dtype=np.int64)
        coef = np.zeros(pole_count * 3)
        k = 0
        soft = []
        if tied:
            for t in ties:
                if not t["exact"]:
                    soft.append(t)
                    continue
                for c in range(3):
                    base[t["a"] * 3 + c] = all_poles[t["b"] * 3 + c]
                    base[t["c"] * 3 + c] = all_poles[t["b"] * 3 + c]
                    z[t["a"] * 3 + c] = k
                    coef[t["a"] * 3 + c] = -1.0
                    z[t["c"] * 3 + c] = k
                    coef[t["c"] * 3 + c] = t["ratio"]
                    k += 1
        free = np.nonzero(np.repeat(is_inner, 3) & (z < 0))[0]
        base[free] = 0.0
        z[free] = k + np.arange(free.shape[0])
        coef[free] = 1.0
        k += free.shape[0]
        return {"count": k, "base": base, "z": z, "coef": coef, "soft": soft}

    hessians = [np.zeros((net.nu + 3) * (net.nv + 3) * BAND) for net in nets]
    rhs = [np.zeros((net.nu + 3) * (net.nv + 3) * 3) for net in nets]
    fairings = [_fairing_band(net, inp["smoothness"], side_rows[i]) for i, net in enumerate(nets)]
    fairing_rhs = [_band_multiply(fairings[i], net, _coons_poles(net)) for i, net in enumerate(nets)]
    band_entries = [_band_entries(net) for net in nets]

    def assemble():
        for i, net in enumerate(nets):
            H = hessians[i]
            g = rhs[i]
            H[:] = fairings[i]
            g[:] = fairing_rhs[i]
            d = data[i]
            U = d["uv"].reshape(-1, 2)[d["keep"]]
            X = d["xyz"].reshape(-1, 3)[d["keep"]]
            su, bu = basis_at_v(net.nu, U[:, 0])
            sv, bv = basis_at_v(net.nv, U[:, 1])
            held_cells = np.zeros(net.nu * net.nv, dtype=bool)
            held_cells[(su - DEGREE) * net.nv + (sv - DEGREE)] = True
            _add_points(H, g, net.nv + 3, su, sv, bu, bv, X, 1.0)
            _add_pull(H, g, net, held_cells, d["kept"])

    def solve(lay, start):
        diag_sum = 0.0
        diag_count = 0
        for H in hessians:
            diag_sum += float(H[24::BAND].sum())
            diag_count += H.shape[0] // BAND
        ties_weight = TIE_WEIGHT * (diag_sum / max(1, diag_count))
        # The system in the poles' coordinates, M, and its constants k.
        Ri = []
        Ci = []
        Vi = []
        const = np.zeros(pole_count * 3)
        for i, net in enumerate(nets):
            bidx, p, q = band_entries[i]
            vals = hessians[i][bidx]
            base_i = pole_base[i]
            for c in range(3):
                Ri.append((base_i + p) * 3 + c)
                Ci.append((base_i + q) * 3 + c)
                Vi.append(vals)
        for t in lay["soft"]:
            w = ties_weight / (1 + t["ratio"] * t["ratio"])
            ra = t["ratio"]
            for c in range(3):
                a = t["a"] * 3 + c
                cc = t["c"] * 3 + c
                Ri.append(np.array([a, a, cc, cc]))
                Ci.append(np.array([a, cc, a, cc]))
                Vi.append(np.array([w, w * ra, w * ra, w * ra * ra]))
                k = (1 + ra) * all_poles[t["b"] * 3 + c]
                const[a] += w * k
                const[cc] += w * ra * k
        for row in face_rows:
            p = row["pole"] * 3
            nrm = row["n"]
            for a in range(3):
                for b in range(3):
                    Ri.append(np.array([p + a]))
                    Ci.append(np.array([p + b]))
                    Vi.append(np.array([ties_weight * nrm[a] * nrm[b]]))
                const[p + a] += ties_weight * nrm[a] * row["rhs"]
        Ri = np.concatenate(Ri)
        Ci = np.concatenate(Ci)
        Vi = np.concatenate(Vi)
        z = lay["z"]
        coef = lay["coef"]
        n = lay["count"]
        # The right-hand side: the data's, less what the constants do.
        base = lay["base"]
        Mb = np.bincount(Ri, weights=Vi * base[Ci], minlength=pole_count * 3)
        G = -(Mb - const)
        for i in range(len(nets)):
            G[pole_base[i] * 3:pole_base[i] * 3 + rhs[i].shape[0]] += rhs[i]
        live = z >= 0
        b = np.bincount(z[live], weights=coef[live] * G[live], minlength=n)
        on = (Ri == Ci)
        mdiag = np.bincount(Ri[on], weights=Vi[on], minlength=pole_count * 3)
        diagonal = np.bincount(z[live], weights=coef[live] ** 2 * mdiag[live], minlength=n)
        keep = (z[Ri] >= 0) & (z[Ci] >= 0)
        A = csr_from_triplets(n, z[Ri[keep]], z[Ci[keep]], coef[Ri[keep]] * coef[Ci[keep]] * Vi[keep])
        op = LinearOperator(n, A.multiply, diagonal)
        r = conjugate_gradient(op, b, x0=start, tolerance=SOLVE_TOLERANCE, max_iterations=20000)
        return r["x"], r["iterations"]

    def poles_of(lay, zv):
        z = lay["z"]
        all_poles[:] = lay["base"] + np.where(z >= 0, lay["coef"] * zv[np.maximum(z, 0)] if zv.shape[0] else 0.0, 0.0)
        for i, net in enumerate(nets):
            size = (net.nu + 3) * (net.nv + 3)
            net.poles[:] = all_poles[pole_base[i] * 3:(pole_base[i] + size) * 3]

    def z_of(lay):
        z = lay["z"]
        live = z >= 0
        v = (all_poles[live] - lay["base"][live]) / lay["coef"][live]
        s = np.bincount(z[live], weights=v, minlength=lay["count"])
        c = np.bincount(z[live], minlength=lay["count"])
        return s / np.maximum(c, 1)

    # ---- the first fit, free of the ties: the cross-spacings' ratios --------
    assemble()
    free = layout(False)
    iterations = 0
    zf, it = solve(free, None)
    iterations += it
    poles_of(free, zf)
    for t in ties:
        A = all_poles[t["a"] * 3:t["a"] * 3 + 3]
        B = all_poles[t["b"] * 3:t["b"] * 3 + 3]
        Cc = all_poles[t["c"] * 3:t["c"] * 3 + 3]
        num = float(((Cc - B) ** 2).sum())
        den = float(((B - A) ** 2).sum())
        t["ratio"] = math.sqrt(num / den) if den > 0 else 1.0
    _smooth_ratios(ties)
    for t in ties:
        t["ratio"] = min(RATIO_LIMIT, max(1 / RATIO_LIMIT, t["ratio"]))
    free_poles = all_poles.copy()

    # ---- tangency across a T-junction ---------------------------------------
    for qi, rows in enumerate(side_rows):
        for k, side in enumerate(rows):
            if side["single"]:
                continue
            Q = nets[qi]
            q_spans = Q.nu if k % 2 == 0 else Q.nv
            gq = greville_of(q_spans).tolist()
            for h in side["edges"]:
                p = next((u for u in shared_by.get(h["curve"], []) if u["patch"] != qi), None)
                if p is None or curve_of[h["curve"]]["crease"]:
                    continue
                f = fits[h["curve"]]
                n = f["spans"] + 3

                def normal_at(t, s, p=p, f=f, k=k, Q=Q):
                    a = patch_normal(nets[p["patch"]], *_on_side(p["side"], t if p["forward"] else 1 - t))
                    b = patch_normal(Q, *_on_side(k, s))
                    sign = -1 if a[0] * b[0] + a[1] * b[1] + a[2] * b[2] < 0 else 1
                    m = [a[0] + sign * b[0], a[1] + sign * b[1], a[2] + sign * b[2]]
                    d = curve_derivative(f["poles"], f["spans"], t)
                    along = (m[0] * d[0] + m[1] * d[1] + m[2] * d[2]) / max(1e-30, d[0] * d[0] + d[1] * d[1] + d[2] * d[2])
                    for c in range(3):
                        m[c] -= along * d[c]
                    l = js_hypot(m[0], m[1], m[2]) or 1
                    return [m[0] / l, m[1] / l, m[2] / l]

                def hold(patch, side_of, at, normal):
                    net = nets[patch]
                    boundary, inner = _side_pole(net.nu, net.nv, side_of, at)
                    b = (boundary[0] * (net.nv + 3) + boundary[1]) * 3
                    face_rows.append({"pole": pole_base[patch] + inner[0] * (net.nv + 3) + inner[1], "n": normal, "rhs": normal[0] * net.poles[b] + normal[1] * net.poles[b + 1] + normal[2] * net.poles[b + 2]})

                gp = greville_of(f["spans"]).tolist()
                for m in range(2, n - 2):
                    x = curve_point(f["poles"], f["spans"], gp[m])
                    hold(p["patch"], p["side"], m if p["forward"] else n - 1 - m, normal_at(gp[m], _nearest_on(side["poles"], q_spans, x)))
                ends = [_nearest_on(side["poles"], q_spans, curve_point(f["poles"], f["spans"], float(t))) for t in (0, 1)]
                lo = min(ends)
                hi = max(ends)
                for m in range(2, q_spans + 1):
                    if not (gq[m] > lo and gq[m] < hi):
                        continue
                    y = curve_point(side["poles"], q_spans, gq[m])
                    hold(qi, k, m, normal_at(_nearest_on(f["poles"], f["spans"], y), gq[m]))

    # ---- tied, and the parameters corrected ---------------------------------
    lay = layout(len(ties) > 0)
    rms, res = _residual_rms(nets, data)
    rounds = 0
    while rounds < ROUNDS:
        zr, it = solve(lay, z_of(lay))
        iterations += it
        poles_of(lay, zr)
        if rounds == 0:
            torn = _torn_corners(nets, free_poles, pole_base, patches, {t["node"] for t in ties if t["node"] is not None})
            if torn:
                ties[:] = [t for t in ties if t["node"] is None or t["node"] not in torn]
                for node in torn:
                    if node not in irregular:
                        irregular.add(node)
                        irregular_order.append(node)
                all_poles[:] = free_poles
                lay = layout(len(ties) > 0)
                za, it = solve(lay, z_of(lay))
                iterations += it
                poles_of(lay, za)
        if rounds == 0 and inp.get("robust"):
            _drop_outliers(nets, data)
        _project(nets, data)
        nrms, res = _residual_rms(nets, data)
        settled = abs(nrms - rms) <= ROUNDS_SETTLE * max(rms, 1e-9)
        rms = nrms
        if settled and rounds > 0:
            rounds += 1
            break
        if rounds < ROUNDS - 1:
            assemble()
        rounds += 1

    # ---- the answers ----------------------------------------------------------
    fitted = []
    for i, net in enumerate(nets):
        d = data[i]
        r = res[i]
        keep = d["keep"]
        rk = r[keep]
        n = int(rk.shape[0])
        sq = float((rk * rk).sum())
        mx = float(np.abs(rk).max()) if n else 0.0
        kept_idx = np.nonzero(keep)[0]
        order = kept_idx[np.argsort(-np.abs(rk), kind="stable")[:WORST_POINTS]] if n else []
        X = d["xyz"].reshape(-1, 3)
        worst = [{"at": [float(x) for x in X[k]], "off": float(r[k])} for k in order]
        out = {"net": net, "sides": side_rows[i], "corners": patches[i]["corners"], "seed": patches[i]["seed"], "points": n, "rms": math.sqrt(sq / n) if n > 0 else 0.0, "max": mx,
               "misfit": _misfit_of(d, r, (side_length[i][0] + side_length[i][2]) / max(1e-9, side_length[i][1] + side_length[i][3])), "worst": worst}
        if inp.get("robust"):
            out["dropped"] = d["count"] - n
        fitted.append(out)
    near_corner = {}
    shared_out = []
    for s in shared:
        c = curve_of[s["curve"]]
        reach = 2 / fits[s["curve"]]["spans"]
        reading, near_from, near_to = _edge_reading(s, fitted, reach if c["from"] in irregular else 0.0, reach if c["to"] in irregular else 0.0)
        if c["from"] in irregular and not s["crease"]:
            near_corner[c["from"]] = max(near_corner.get(c["from"], 0.0), near_from)
        if c["to"] in irregular and not s["crease"]:
            near_corner[c["to"]] = max(near_corner.get(c["to"], 0.0), near_to)
        shared_out.append(reading)
    for qi, q in enumerate(fitted):
        for k, side in enumerate(q["sides"]):
            if side["single"]:
                continue
            for h in side["edges"]:
                p = next((u for u in shared_by.get(h["curve"], []) if u["patch"] != qi), None)
                if p is None:
                    continue
                shared_out.append(_tee_reading(h["curve"], fits[h["curve"]], fitted, [p["patch"], qi], [p["side"], k], p["forward"], bool(curve_of.get(h["curve"], {}).get("crease"))))
    corners = []
    for node in irregular_order:
        at = _corner_reading(node, node_of[node]["at"], fitted)
        at["angle"] = max(at["angle"], near_corner.get(node, 0.0))
        corners.append(at)
    bodies_out = []
    for side in inp.get("bodySides") or []:
        f = fits.get(side["curve"])
        if f is None:
            continue
        for u in shared_by.get(side["curve"], []):
            ts = [(k + 1) / EDGE_SAMPLES for k in range(EDGE_SAMPLES - 1)]
            normals = side["normals"]([curve_point(f["poles"], f["spans"], t) for t in ts]) or []
            angle = 0.0
            for k, t in enumerate(ts):
                nf = normals[k] if k < len(normals) else None
                if not nf:
                    continue
                uu, vv = _on_side(u["side"], t if u["forward"] else 1 - t)
                np_ = patch_normal(fitted[u["patch"]]["net"], uu, vv)
                cos = min(1.0, abs(np_[0] * nf[0] + np_[1] * nf[1] + np_[2] * nf[2]))
                angle = max(angle, (math.acos(cos) * 180) / math.pi)
            bodies_out.append({"curve": side["curve"], "patch": u["patch"], "mode": side["mode"], "angle": angle, "gap": f["max"]})
    return {"patches": fitted, "curves": fits, "shared": shared_out, "bodies": bodies_out, "corners": corners,
            "strips": [{"spans": strip_spans[st], "auto": strips["auto"][st], "curves": curves} for st, curves in enumerate(strips["curves"])], "rounds": rounds, "iterations": iterations}
