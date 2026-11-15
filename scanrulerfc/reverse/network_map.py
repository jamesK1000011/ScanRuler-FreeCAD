# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/core/networkMap.ts
# SPDX-License-Identifier: AGPL-3.0-only
#
# A cell of a patch network mapped onto the unit square (or, for a cell to
# be split from its centre, onto a regular polygon) so that each of its scan
# points has a (u, v) on the patch fitted through it.
#
# The cell's boundary goes onto the polygon's sides, corner to corner, by
# arc length; each interior vertex is placed at a weighted mean of its
# neighbours, the weights Floater's mean-value coordinates: positive for any
# triangle, shape-preserving on a flat one. Floater's theorem says a map
# with positive weights onto a convex boundary is one-to-one, however the
# cell lies in space, so a cell that folds back round a cylinder maps as
# well as a flat one, which is what Fit Surface's height field cannot do.
# The weights are not symmetric, so the system is solved by BiCGSTAB
# (sparse.py), u and v the same matrix.
#
# A scan hole wholly inside the cell is closed for the map by a fan from the
# hole's middle; the fan's vertex carries no data. Any triangle that comes
# out flipped refuses the cell, by where it is. A cell mesh is a dict with
# the original's fields; a refusal is a string.

import math

import numpy as np

from ._js import js_hypot, to_fixed
from .network_spline import hypot3_v
from .sparse import Triplets, biconjugate_gradient_stabilized

MAP_TOLERANCE = 1e-7


def _at(x):
    return "(" + ", ".join(to_fixed(float(v), 1) for v in x) + ")"


def cell_mesh(scan, triangles, holes, corners):
    """The cell's local mesh from its scan triangles, with a fan in each
    hole, its boundary loop and the corners found on it, or why there is
    none."""
    idx = scan.indices
    pos = scan.positions
    local = {}
    positions = []
    scan_vertex = []
    tri = []

    def take(v):
        l = local.get(v)
        if l is None:
            l = len(scan_vertex)
            local[v] = l
            scan_vertex.append(v)
            positions.extend((pos[v * 3], pos[v * 3 + 1], pos[v * 3 + 2]))
        return l

    for t in (int(x) for x in triangles):
        tri.extend((take(idx[t * 3]), take(idx[t * 3 + 1]), take(idx[t * 3 + 2])))
    for hole in holes:
        c = [0.0, 0.0, 0.0]
        for v in hole:
            for k in range(3):
                c[k] += pos[v * 3 + k] / len(hole)
        middle = len(scan_vertex)
        scan_vertex.append(-1)
        positions.extend(c)
        for i in range(len(hole)):
            tri.extend((take(hole[(i + 1) % len(hole)]), take(hole[i]), middle))
    count = len(tri) // 3
    edge_use = {}
    for t in range(count):
        for e in range(3):
            a = tri[t * 3 + e]
            b = tri[t * 3 + (e + 1) % 3]
            k = (a, b) if a < b else (b, a)
            edge_use[k] = edge_use.get(k, 0) + 1
    next_of = {}
    for t in range(count):
        for e in range(3):
            a = tri[t * 3 + e]
            b = tri[t * 3 + (e + 1) % 3]
            if edge_use.get((a, b) if a < b else (b, a)) != 1:
                continue
            next_of.setdefault(a, []).append(b)
    used = set()
    loops = []
    for a0, lst in next_of.items():
        for b0 in lst:
            if (a0, b0) in used:
                continue
            loop = [a0]
            b = b0
            a = a0
            for _ in range(len(scan_vertex) + 1):
                used.add((a, b))
                if b == a0:
                    break
                loop.append(b)
                options = [x for x in next_of.get(b, []) if (b, x) not in used]
                if not options:
                    break
                a = b
                b = options[0]
            loops.append(loop)
    if not loops:
        return "it has no boundary — the scan closes round it"
    if len(loops) > 1:
        loops.sort(key=lambda x: -len(x))
        v = loops[1][0]
        return f"it is a ring, not a disk — another boundary inside it at {_at(positions[v * 3:v * 3 + 3])}"
    loop = loops[0]
    L = np.array(loop)
    LP = np.array(positions).reshape(-1, 3)[L]
    corner_at = []
    for c in corners:
        d = hypot3_v(LP[:, 0] - c[0], LP[:, 1] - c[1], LP[:, 2] - c[2])
        corner_at.append(int(np.argmin(d)))
    rel = [(i - corner_at[0] + len(loop)) % len(loop) for i in corner_at]
    for k in range(1, len(rel)):
        if not rel[k] > rel[k - 1]:
            return "its corners do not come round its boundary in order — a side doubles back on itself"
    return {"positions": np.array(positions, dtype=float), "scanVertex": np.array(scan_vertex, dtype=np.int64), "triangles": np.array(tri, dtype=np.int64), "loop": loop, "cornerAt": corner_at}


def polygon_corners(n):
    """The polygon a cell is mapped onto: the unit square for four corners
    (side 0 along v = 0 from (0, 0), then round counter-clockwise) or a
    regular polygon of n corners in the unit disk, its first at angle 0."""
    if n == 4:
        return [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
    return [[0.5 + 0.5 * math.cos((2 * math.pi * k) / n), 0.5 + 0.5 * math.sin((2 * math.pi * k) / n)] for k in range(n)]


def map_cell(mesh, start=None):
    """The cell mapped onto its polygon, or why not: {mesh, uv, iterations}."""
    nv = mesh["scanVertex"].shape[0]
    pos = mesh["positions"]
    corners = polygon_corners(len(mesh["cornerAt"]))
    uv = np.zeros(nv * 2)
    fixed = np.zeros(nv, dtype=bool)
    loop = mesh["loop"]
    L = len(loop)
    ca = mesh["cornerAt"]
    for k in range(len(ca)):
        frm = ca[k]
        to = ca[(k + 1) % len(ca)]
        steps = (to - frm + L) % L or L
        along = [0.0]
        for s in range(1, steps + 1):
            a = loop[(frm + s - 1) % L]
            b = loop[(frm + s) % L]
            along.append(along[s - 1] + js_hypot(pos[b * 3] - pos[a * 3], pos[b * 3 + 1] - pos[a * 3 + 1], pos[b * 3 + 2] - pos[a * 3 + 2]))
        total = along[steps] or 1
        x0, y0 = corners[k]
        x1, y1 = corners[(k + 1) % len(corners)]
        for s in range(steps):
            v = loop[(frm + s) % L]
            f = along[s] / total
            uv[v * 2] = x0 + f * (x1 - x0)
            uv[v * 2 + 1] = y0 + f * (y1 - y0)
            fixed[v] = True
    unknown = np.full(nv, -1, dtype=np.int64)
    free = np.nonzero(~fixed)[0]
    m = free.shape[0]
    unknown[free] = np.arange(m)
    t = mesh["triangles"].reshape(-1, 3)
    P = pos.reshape(-1, 3)
    # Mean-value weights per triangle corner, in the original's order: for
    # each triangle, each corner c, toward j then k.
    I = t
    J = np.roll(t, -1, axis=1)
    K = np.roll(t, -2, axis=1)
    E = P[J] - P[I]
    Gv = P[K] - P[I]
    le = hypot3_v(E[..., 0], E[..., 1], E[..., 2])
    lg = hypot3_v(Gv[..., 0], Gv[..., 1], Gv[..., 2])
    ok = (le > 0) & (lg > 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        cos = np.clip((E[..., 0] * Gv[..., 0] + E[..., 1] * Gv[..., 1] + E[..., 2] * Gv[..., 2]) / (le * lg), -1, 1)
        half = np.sqrt(np.maximum(0, 1 - cos * cos)) / (1 + cos + 1e-300)
        wj = half / le
        wk = half / lg
    ci = np.stack([I, I], axis=-1).reshape(-1)
    cj = np.stack([J, K], axis=-1).reshape(-1)
    cw = np.stack([wj, wk], axis=-1).reshape(-1)
    cok = np.stack([ok, ok], axis=-1).reshape(-1)
    ui = unknown[ci]
    uj = unknown[cj]
    live = cok & (ui >= 0) & (cw > 0)
    ui, uj, cw, cj = ui[live], uj[live], cw[live], cj[live]
    # Each call: the diagonal, then the neighbour (unknown) or the rhs.
    rows = np.stack([ui, ui], axis=-1).reshape(-1)
    cols = np.stack([ui, uj], axis=-1).reshape(-1)
    vals = np.stack([cw, -cw], axis=-1).reshape(-1)
    keep = np.stack([np.ones_like(uj, dtype=bool), uj >= 0], axis=-1).reshape(-1)
    a = Triplets(m)
    a.add_many(rows[keep], cols[keep], vals[keep])
    known = uj < 0
    bu = np.bincount(ui[known], weights=cw[known] * uv[cj[known] * 2], minlength=m) if m else np.zeros(0)
    bv = np.bincount(ui[known], weights=cw[known] * uv[cj[known] * 2 + 1], minlength=m) if m else np.zeros(0)
    iterations = 0
    if m > 0:
        csr = a.to_csr()
        x0u = x0v = None
        if start is not None:
            st = np.asarray(start, dtype=float)
            x0u = st[free * 2]
            x0v = st[free * 2 + 1]
        su = biconjugate_gradient_stabilized(csr, bu, x0=x0u, tolerance=MAP_TOLERANCE)
        sv = biconjugate_gradient_stabilized(csr, bv, x0=x0v, tolerance=MAP_TOLERANCE)
        iterations = su["iterations"] + sv["iterations"]
        uv[free * 2] = su["x"]
        uv[free * 2 + 1] = sv["x"]
    U = uv.reshape(-1, 2)
    p, q, r = t[:, 0], t[:, 1], t[:, 2]
    signed = (U[q, 0] - U[p, 0]) * (U[r, 1] - U[p, 1]) - (U[r, 0] - U[p, 0]) * (U[q, 1] - U[p, 1])
    area = float(np.abs(signed).sum())
    slack = 1e-9 * (area / max(1, signed.shape[0]))
    bad = np.nonzero(signed < -slack)[0]
    if bad.size:
        v = int(p[bad[0]])
        return f"the map folds over at {_at(P[v])} — the cell's boundary is not a simple loop there"
    return {"mesh": mesh, "uv": uv, "iterations": iterations}
