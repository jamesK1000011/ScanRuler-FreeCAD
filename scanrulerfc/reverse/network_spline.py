# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/core/networkSpline.ts
# SPDX-License-Identifier: AGPL-3.0-only
#
# The B-splines of a patch network: cubic, clamped, with uniform knots over
# [0, 1]. A curve of `spans` spans has spans + 3 poles, a patch of nu x nv
# spans (nu + 3) x (nv + 3), row-major with u along the rows' index. Two
# curves or two patch sides with the same span count have the same knots,
# so a side whose poles are a curve's poles is that curve exactly. The basis
# and its first derivative are Cox-de Boor's (Piegl and Tiller, The NURBS
# Book, A2.3); the knots are Fit Surface's.
#
# Every function has a scalar form, as the original's, and the ones the
# network fit calls a few million times a pass a vectorised form over numpy
# arrays of parameters (names ending in _v). The vectorised forms do the
# original's operations in its order, element by element, so their numbers
# are the scalar forms'.

import math

import numpy as np

from ._js import js_hypot
from .surface_fit import clamped_knots

DEGREE = 3

_knot_cache = {}
_knot_lists = {}


def knots_of(spans):
    """The clamped uniform knots of a cubic of `spans` spans over [0, 1]."""
    k = _knot_cache.get(spans)
    if k is None:
        k = clamped_knots(spans + DEGREE, DEGREE, 0.0, 1.0)
        _knot_cache[spans] = k
        _knot_lists[spans] = [float(x) for x in k]
    return k


def _knots_list(spans):
    if spans not in _knot_lists:
        knots_of(spans)
    return _knot_lists[spans]


def _span_of(k, spans, t):
    if not t < 1:
        return spans + DEGREE - 1
    if t <= 0:
        return DEGREE
    s = min(spans + DEGREE - 1, DEGREE + math.floor(t * spans))
    while t < k[s]:
        s -= 1
    while t >= k[s + 1]:
        s += 1
    return s


def _clamp01(t):
    if t != t:
        return t
    return min(1.0, max(0.0, t))


def basis_with_derivative(spans, t, n0, n1):
    """The four basis functions non-zero at t and their first derivatives,
    written to n0 and n1; returns the span they are of (pole span - 3 + i
    takes n0[i])."""
    k = _knots_list(spans)
    tt = _clamp01(float(t))
    s = _span_of(k, spans, tt)
    l1 = tt - k[s]
    l2 = tt - k[s - 1]
    l3 = tt - k[s - 2]
    r1 = k[s + 1] - tt
    r2 = k[s + 2] - tt
    r3 = k[s + 3] - tt
    temp = 1 / (r1 + l1)
    e0 = r1 * temp
    e1 = l1 * temp
    temp = e0 / (r1 + l2)
    f0 = r1 * temp
    saved = l2 * temp
    temp = e1 / (r2 + l1)
    f1 = saved + r2 * temp
    f2 = l1 * temp
    a = r1 + l3
    b = r2 + l2
    c = r3 + l1
    temp = f0 / a
    n0[0] = r1 * temp
    saved = l3 * temp
    temp = f1 / b
    n0[1] = saved + r2 * temp
    saved = l2 * temp
    temp = f2 / c
    n0[2] = saved + r3 * temp
    n0[3] = l1 * temp
    fa = f0 / a
    fb = f1 / b
    fc = f2 / c
    n1[0] = 3 * (0 - fa)
    n1[1] = 3 * (fa - fb)
    n1[2] = 3 * (fb - fc)
    n1[3] = 3 * fc
    return s


def basis_at(spans, t, out):
    """The basis functions alone, written to out; the span they are of."""
    knots = _knots_list(spans)
    tt = _clamp01(float(t))
    s = _span_of(knots, spans, tt)
    left = [0.0] * (DEGREE + 1)
    right = [0.0] * (DEGREE + 1)
    out[0] = 1.0
    for j in range(1, DEGREE + 1):
        left[j] = tt - knots[s + 1 - j]
        right[j] = knots[s + j] - tt
        saved = 0.0
        for r in range(j):
            temp = out[r] / (right[r + 1] + left[j - r])
            out[r] = saved + right[r + 1] * temp
            saved = left[j - r] * temp
        out[j] = saved
    return s


# ---- vectorised over parameters ----------------------------------------------------------------


def _span_of_v(k, spans, tt):
    s = np.minimum(spans + DEGREE - 1, DEGREE + np.floor(tt * spans)).astype(np.int64)
    s = np.where(np.isnan(tt), spans + DEGREE - 1, s)
    s = np.clip(s, DEGREE, spans + DEGREE - 1)
    for _ in range(3):
        down = tt < k[s]
        if not down.any():
            break
        s = np.where(down, s - 1, s)
    for _ in range(3):
        up = tt >= k[s + 1]
        if not up.any():
            break
        s = np.where(up, s + 1, s)
    s = np.where(~(tt < 1), spans + DEGREE - 1, s)
    s = np.where(tt <= 0, DEGREE, s)
    return s


def basis_at_v(spans, t):
    """basis_at for an array of t: (spans, basis (N, 4))."""
    knots = knots_of(spans)
    tt = np.clip(np.asarray(t, dtype=float), 0.0, 1.0)
    s = _span_of_v(knots, spans, tt)
    n = tt.shape[0]
    out = np.zeros((n, DEGREE + 1))
    left = [None] * (DEGREE + 1)
    right = [None] * (DEGREE + 1)
    out[:, 0] = 1.0
    for j in range(1, DEGREE + 1):
        left[j] = tt - knots[s + 1 - j]
        right[j] = knots[s + j] - tt
        saved = np.zeros(n)
        for r in range(j):
            temp = out[:, r] / (right[r + 1] + left[j - r])
            out[:, r] = saved + right[r + 1] * temp
            saved = left[j - r] * temp
        out[:, j] = saved
    return s, out


def basis_with_derivative_v(spans, t):
    """basis_with_derivative for an array of t: (spans, n0 (N, 4), n1 (N, 4))."""
    k = knots_of(spans)
    tt = np.clip(np.asarray(t, dtype=float), 0.0, 1.0)
    s = _span_of_v(k, spans, tt)
    l1 = tt - k[s]
    l2 = tt - k[s - 1]
    l3 = tt - k[s - 2]
    r1 = k[s + 1] - tt
    r2 = k[s + 2] - tt
    r3 = k[s + 3] - tt
    temp = 1 / (r1 + l1)
    e0 = r1 * temp
    e1 = l1 * temp
    temp = e0 / (r1 + l2)
    f0 = r1 * temp
    saved = l2 * temp
    temp = e1 / (r2 + l1)
    f1 = saved + r2 * temp
    f2 = l1 * temp
    a = r1 + l3
    b = r2 + l2
    c = r3 + l1
    n0 = np.empty((tt.shape[0], 4))
    n1 = np.empty((tt.shape[0], 4))
    temp = f0 / a
    n0[:, 0] = r1 * temp
    saved = l3 * temp
    temp = f1 / b
    n0[:, 1] = saved + r2 * temp
    saved = l2 * temp
    temp = f2 / c
    n0[:, 2] = saved + r3 * temp
    n0[:, 3] = l1 * temp
    fa = f0 / a
    fb = f1 / b
    fc = f2 / c
    n1[:, 0] = 3 * (0 - fa)
    n1[:, 1] = 3 * (fa - fb)
    n1[:, 2] = 3 * (fb - fc)
    n1[:, 3] = 3 * fc
    return s, n0, n1


def _poles3(poles):
    return np.asarray(poles, dtype=float).reshape(-1, 3)


def curve_point(poles, spans, t, out=None):
    """A curve's point at t, poles flat (x, y, z per pole)."""
    b0 = [0.0] * 4
    s = basis_at(spans, t, b0)
    x = y = z = 0.0
    for i in range(DEGREE + 1):
        at = (s - DEGREE + i) * 3
        x += b0[i] * poles[at]
        y += b0[i] * poles[at + 1]
        z += b0[i] * poles[at + 2]
    if out is None:
        return [x, y, z]
    out[0] = x
    out[1] = y
    out[2] = z
    return out


def curve_derivative(poles, spans, t, out=None):
    """A curve's derivative at t."""
    b0 = [0.0] * 4
    b1 = [0.0] * 4
    s = basis_with_derivative(spans, t, b0, b1)
    x = y = z = 0.0
    for i in range(DEGREE + 1):
        at = (s - DEGREE + i) * 3
        x += b1[i] * poles[at]
        y += b1[i] * poles[at + 1]
        z += b1[i] * poles[at + 2]
    if out is None:
        return [x, y, z]
    out[0] = x
    out[1] = y
    out[2] = z
    return out


def curve_points_v(poles, spans, t):
    """curve_point at each of an array of t: (N, 3)."""
    P = _poles3(poles)
    s, b = basis_at_v(spans, t)
    out = np.zeros((b.shape[0], 3))
    for i in range(DEGREE + 1):
        out += b[:, i:i + 1] * P[s - DEGREE + i]
    return out


def curve_derivatives_v(poles, spans, t):
    """curve_derivative at each of an array of t: (N, 3)."""
    P = _poles3(poles)
    s, _, b1 = basis_with_derivative_v(spans, t)
    out = np.zeros((b1.shape[0], 3))
    for i in range(DEGREE + 1):
        out += b1[:, i:i + 1] * P[s - DEGREE + i]
    return out


class PatchNet:
    """A patch: its spans each way and its poles, (nu + 3) rows of (nv + 3),
    x, y, z each, flat."""

    __slots__ = ("nu", "nv", "poles")

    def __init__(self, nu, nv, poles):
        self.nu = nu
        self.nv = nv
        self.poles = poles

    def __repr__(self):
        return f"PatchNet(nu={self.nu}, nv={self.nv})"


def patch_point(net, u, v, p, du=None, dv=None):
    """A patch's point and first derivatives at (u, v), into p, du, dv."""
    u0 = [0.0] * 4
    u1 = [0.0] * 4
    v0 = [0.0] * 4
    v1 = [0.0] * 4
    su = basis_with_derivative(net.nu, u, u0, u1)
    sv = basis_with_derivative(net.nv, v, v0, v1)
    cols = net.nv + DEGREE
    poles = net.poles
    px = py = pz = 0.0
    ux = uy = uz = 0.0
    vx = vy = vz = 0.0
    for a in range(DEGREE + 1):
        row = (su - DEGREE + a) * cols
        ua = u0[a]
        ud = u1[a]
        for b in range(DEGREE + 1):
            at = (row + sv - DEGREE + b) * 3
            x = poles[at]
            y = poles[at + 1]
            z = poles[at + 2]
            w = ua * v0[b]
            px += w * x
            py += w * y
            pz += w * z
            wu = ud * v0[b]
            ux += wu * x
            uy += wu * y
            uz += wu * z
            wv = ua * v1[b]
            vx += wv * x
            vy += wv * y
            vz += wv * z
    p[0] = px
    p[1] = py
    p[2] = pz
    if du is not None:
        du[0] = ux
        du[1] = uy
        du[2] = uz
    if dv is not None:
        dv[0] = vx
        dv[1] = vy
        dv[2] = vz


def patch_points_v(net, u, v):
    """patch_point at arrays of (u, v): points, du, dv, each (N, 3)."""
    P = np.asarray(net.poles, dtype=float).reshape(net.nu + 3, net.nv + 3, 3)
    su, u0, u1 = basis_with_derivative_v(net.nu, u)
    sv, v0, v1 = basis_with_derivative_v(net.nv, v)
    n = u0.shape[0]
    p = np.zeros((n, 3))
    du = np.zeros((n, 3))
    dv = np.zeros((n, 3))
    for a in range(DEGREE + 1):
        ri = su - DEGREE + a
        ua = u0[:, a:a + 1]
        ud = u1[:, a:a + 1]
        for b in range(DEGREE + 1):
            q = P[ri, sv - DEGREE + b]
            p += (ua * v0[:, b:b + 1]) * q
            du += (ud * v0[:, b:b + 1]) * q
            dv += (ua * v1[:, b:b + 1]) * q
    return p, du, dv


def patch_normal(net, u, v, out=None):
    """The patch's unit normal at (u, v): du x dv."""
    p = [0.0, 0.0, 0.0]
    du = [0.0, 0.0, 0.0]
    dv = [0.0, 0.0, 0.0]
    patch_point(net, u, v, p, du, dv)
    x = du[1] * dv[2] - du[2] * dv[1]
    y = du[2] * dv[0] - du[0] * dv[2]
    z = du[0] * dv[1] - du[1] * dv[0]
    l = js_hypot(x, y, z) or 1
    if out is None:
        out = [0.0, 0.0, 0.0]
    out[0] = x / l
    out[1] = y / l
    out[2] = z / l
    return out


def patch_normals_v(net, u, v):
    """patch_normal at arrays of (u, v): (N, 3)."""
    _, du, dv = patch_points_v(net, u, v)
    n = np.cross(du, dv)
    l = np.sqrt((n * n).sum(axis=1))
    l = np.where(l > 0, l, 1.0)
    return n / l[:, None]


def greville_of(spans):
    """The Greville abscissae of a cubic of `spans` spans."""
    knots = _knots_list(spans)
    n = spans + DEGREE
    return np.array([(knots[i + 1] + knots[i + 2] + knots[i + 3]) / 3 for i in range(n)])


def divided_weights(x, frm, order):
    """The weights of the `order`-th divided difference over x[frm ...],
    scaled by order! so it reads as the derivative."""
    fact = 1
    for k in range(2, order + 1):
        fact *= k
    w = []
    for k in range(order + 1):
        denom = 1.0
        for j in range(order + 1):
            if j != k:
                denom *= x[frm + k] - x[frm + j]
        w.append(fact / denom)
    return w
