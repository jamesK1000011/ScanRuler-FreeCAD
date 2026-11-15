# SPDX-License-Identifier: AGPL-3.0-only
# Ported from ScanRuler by CNC Kitchen (Stefan Hermann):
# plugins/mesh-tools/core/primitiveMesh.ts and plugins/mesh-tools/app/booleanSolids.ts
#
# A measured element that is a solid — a fitted cylinder, cone or sphere — as
# a closed triangle mesh, for the Boolean (and Trim to scan) to cut or add
# with as it is drawn: at its assumed Ø. Meshed the way a CAD body's mesh
# comes, face by face — a rim's vertices once for the wall and once for the
# end — and welded by the boolean. Wound outward, as a solid's is.

import math

import numpy as np

APEX = 1e-9
SOLID_KINDS = ("cylinder", "cone", "sphere")
# The chord a solid is meshed to for a boolean, mm (meshToolsSession.ts
# BOOLEAN_CHORD_MM): a bore's wall within a hundredth of its round.
BOOLEAN_CHORD_MM = 0.01


def segments_for(r, chord):
    """The segments round a circle of radius r for every chord to lie within
    `chord` of the round: at least 24, at most 720."""
    s = min(max(chord / r, 1e-12), 1)
    n = math.ceil(math.pi / math.acos(1 - s))
    return min(max(n, 24), 720)


def _frame(axis):
    a = np.asarray(axis, dtype=float)
    L = np.linalg.norm(a)
    a = a / L if L > 0 else np.array([0.0, 0.0, 1.0])
    u = np.cross(a, [1.0, 0, 0] if abs(a[0]) < 0.9 else [0, 1.0, 0])
    u /= np.linalg.norm(u)
    return a, u, np.cross(a, u)


class _Builder:
    def __init__(self):
        self.p, self.idx = [], []

    def point(self, q):
        self.p.append(list(map(float, q)))
        return len(self.p) - 1

    def ring(self, c, r, u, v, n):
        first = len(self.p)
        for i in range(n):
            t = 2 * math.pi * i / n
            self.point(c + u * (r * math.cos(t)) + v * (r * math.sin(t)))
        return first

    def done(self):
        return np.array(self.p, dtype=float).reshape(-1, 3), np.array(self.idx, dtype=np.int64).reshape(-1, 3)


def frustum(center, axis, length, r0, r1, chord):
    if not (length > 0) or not (r0 >= 0) or not (r1 >= 0):
        return None
    tip0, tip1 = r0 <= APEX, r1 <= APEX
    if tip0 and tip1:
        return None
    a, u, v = _frame(axis)
    n = segments_for(max(r0, r1), chord)
    center = np.asarray(center, dtype=float)
    back, front = center - a * (length / 2), center + a * (length / 2)
    m = _Builder()
    b = m.point(back) if tip0 else m.ring(back, r0, u, v, n)
    f = m.point(front) if tip1 else m.ring(front, r1, u, v, n)
    for i in range(n):
        j = (i + 1) % n
        bi, bj = (b, b) if tip0 else (b + i, b + j)
        fi, fj = (f, f) if tip1 else (f + i, f + j)
        if not tip0:
            m.idx += [bi, bj, fj]
        if not tip1:
            m.idx += [bi, fj, fi]
    if not tip1:
        c = m.point(front)
        r = m.ring(front, r1, u, v, n)
        for i in range(n):
            m.idx += [c, r + i, r + (i + 1) % n]
    if not tip0:
        c = m.point(back)
        r = m.ring(back, r0, u, v, n)
        for i in range(n):
            m.idx += [c, r + (i + 1) % n, r + i]
    return m.done()


def sphere(center, radius, chord):
    if not (radius > APEX):
        return None
    a, u, v = _frame([0, 0, 1])
    center = np.asarray(center, dtype=float)
    n = segments_for(radius, chord)
    bands = max(4, math.ceil(n / 2))
    m = _Builder()
    north = m.point(center + a * radius)
    rings = []
    for k in range(1, bands):
        phi = math.pi * k / bands
        rings.append(m.ring(center + a * (radius * math.cos(phi)), radius * math.sin(phi), u, v, n))
    south = m.point(center - a * radius)
    for i in range(n):
        j = (i + 1) % n
        m.idx += [north, rings[0] + i, rings[0] + j]
        for k in range(len(rings) - 1):
            up, down = rings[k], rings[k + 1]
            m.idx += [up + i, down + i, down + j, up + i, down + j, up + j]
        last = rings[-1]
        m.idx += [south, last + j, last + i]
    return m.done()


def drawn_fit(fit, assumed):
    """assumed.ts applyAssumed: a cylinder or sphere at its assumed Ø."""
    if assumed is None or not (float(assumed) > 0) or fit.get("kind") not in ("cylinder", "sphere"):
        return fit
    return {**fit, "radius": float(assumed) / 2}


def element_solid(fit, chord=BOOLEAN_CHORD_MM):
    """The closed mesh (V, F) of a fitted cylinder, cone or sphere; None for
    a kind with no volume."""
    k = fit.get("kind")
    if k == "cylinder":
        return frustum(fit["center"], fit["axis"], float(fit["length"]), float(fit["radius"]), float(fit["radius"]), chord)
    if k == "cone":
        return frustum(fit["center"], fit["axis"], float(fit["length"]), float(fit["radius1"]), float(fit["radius2"]), chord)
    if k == "sphere":
        return sphere(fit["center"], float(fit["radius"]), chord)
    return None


def names_of(names):
    """'Cylinder 1', 'Cylinder 1 and Solid 2', 'A, B and C'."""
    names = list(names)
    if len(names) <= 1:
        return names[0] if names else ""
    return f"{', '.join(names[:-1])} and {names[-1]}"
