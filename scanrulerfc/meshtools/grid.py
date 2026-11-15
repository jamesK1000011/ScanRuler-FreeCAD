# SPDX-License-Identifier: AGPL-3.0-only
# Ported from ScanRuler by CNC Kitchen (Stefan Hermann):
# plugins/mesh-tools/core/distanceGrid.ts and plugins/mesh-tools/core/marching.ts
#
# What Shell's hollow and Wrap share: distance on a grid, a surface where a
# field crosses zero — marching tetrahedra (Kuhn's six to a cube) for the
# hollow's inner wall, marching cubes for the wrap's skin, the cube table
# made here by the original's rule rather than copied — and the specks the
# grid leaves dropped.
#
# ScanRuler runs Felzenszwalb & Huttenlocher's transform line by line; here
# scipy's exact Euclidean transform does the same work on the whole grid
# (the same squared distances to the nearest seed), with an exact numpy
# fallback, line by line, when scipy is missing. The marches are the
# original's tables applied to every crossed cube at once.

import numpy as np

from .. import mesh_core as M

# A grid's origin moved off the part's own corner by these shares of a cell,
# a different one on each axis (distanceGrid.ts JITTER).
JITTER = (0.381966, 0.2763932, 0.145898)


# ---- distance on a grid ---------------------------------------------------------------

def _edt_line_brute(f, chunk=1 << 22):
    """Along the last axis: min_p f[..., p] + (q - p)^2, and the p."""
    n = f.shape[-1]
    lines = f.reshape(-1, n)
    out = np.empty_like(lines, dtype=float)
    arg = np.empty(lines.shape, dtype=np.int64)
    q = np.arange(n)
    sq = (q[:, None] - q[None, :]) ** 2  # (q, p)
    step = max(1, chunk // (n * n))
    for s in range(0, len(lines), step):
        L = lines[s:s + step]
        cost = L[:, None, :] + sq[None]
        a = cost.argmin(axis=2)
        arg[s:s + step] = a
        out[s:s + step] = np.take_along_axis(cost, a[..., None], axis=2)[..., 0]
    return out.reshape(f.shape), arg.reshape(f.shape)


def distance_squared(seeds, indices=False):
    """Squared distance in cells from every point of a 3-D grid to the
    nearest point `seeds` marks — and, with indices, that point's (i, j, k)
    as an array (3, ...). Points with no seed anywhere are at np.inf."""
    seeds = np.asarray(seeds, dtype=bool)
    if not seeds.any():
        d = np.full(seeds.shape, np.inf)
        return (d, np.zeros((3,) + seeds.shape, dtype=np.int64)) if indices else d
    try:
        from scipy import ndimage

        if indices:
            d, ix = ndimage.distance_transform_edt(~seeds, return_indices=True)
            return d * d, ix
        d = ndimage.distance_transform_edt(~seeds)
        return d * d
    except ImportError:
        pass
    # One axis at a time, exact: the lower envelope found by brute force.
    big = 1e30
    f = np.where(seeds, 0.0, big)
    src = [np.indices(seeds.shape)[k] for k in range(3)]
    for ax in range(3):
        g = np.moveaxis(f, ax, -1)
        d, a = _edt_line_brute(g)
        moved = [np.moveaxis(s, ax, -1) for s in src]
        src = [np.moveaxis(np.take_along_axis(s, a, axis=-1), -1, ax) for s in moved]
        f = np.moveaxis(d, -1, ax)
    f = np.where(f >= big / 2, np.inf, f)
    return (f, np.stack(src)) if indices else f


def label(mask):
    """Labels of the 6-connected pieces of mask, 0 off it, and their count."""
    mask = np.asarray(mask, dtype=bool)
    try:
        from scipy import ndimage

        return ndimage.label(mask)
    except ImportError:
        pass
    lab = np.where(mask, np.arange(1, mask.size + 1).reshape(mask.shape), 0)
    big = mask.size + 2
    # Without scipy: each point takes the least label beside it until none
    # changes — slow on a large grid, but the same pieces.
    while True:
        cur = np.where(mask, lab, big)
        new = np.where(mask, np.minimum(lab, _no_wrap_min(cur, big)), 0)
        if np.array_equal(new, lab):
            break
        lab = new
    uniq = np.unique(lab[mask])
    out = np.zeros(lab.shape, dtype=np.int64)
    out[mask] = np.searchsorted(uniq, lab[mask]) + 1
    return out, len(uniq)


def _no_wrap_min(cur, big):
    m = cur.copy()
    for ax in range(3):
        n = cur.shape[ax]
        a = [slice(None)] * 3
        b = [slice(None)] * 3
        a[ax], b[ax] = slice(1, n), slice(0, n - 1)
        m[tuple(a)] = np.minimum(m[tuple(a)], cur[tuple(b)])
        m[tuple(b)] = np.minimum(m[tuple(b)], cur[tuple(a)])
    return m


def spread_points(V, F, h):
    """Points spread over every triangle no further apart than half a cell
    (hollow.ts, wrapTile.ts seedTriangle): a crack narrower than a cell still
    counts as surface."""
    V = np.asarray(V, dtype=float)
    F = np.asarray(F, dtype=np.int64)
    A, B, C = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    longest = np.maximum.reduce([np.linalg.norm(B - A, axis=1), np.linalg.norm(C - B, axis=1), np.linalg.norm(A - C, axis=1)])
    steps = np.maximum(1, np.ceil(2 * longest / h)).astype(np.int64)
    out = []
    for s in np.unique(steps).tolist():
        rows = np.nonzero(steps == s)[0]
        i, j = np.meshgrid(np.arange(s + 1), np.arange(s + 1), indexing="ij")
        keep = (i + j) <= s
        u, w = (i[keep] / s), (j[keep] / s)
        per = max(1, (1 << 22) // len(u))
        for k in range(0, len(rows), per):
            r = rows[k:k + per]
            a, b, c = A[r], B[r], C[r]
            P = a[:, None] + u[None, :, None] * (b - a)[:, None] + w[None, :, None] * (c - a)[:, None]
            out.append(P.reshape(-1, 3))
    return np.vstack(out) if out else np.zeros((0, 3))


# ---- marching cubes' table (marching.ts CUBE_TRIANGLES) ----------------------------------

CUBE_EDGE_FROM = []
CUBE_EDGE_DIR = []
for _dir in (1, 2, 4):
    for _a in range(8):
        if not _a & _dir:
            CUBE_EDGE_FROM.append(_a)
            CUBE_EDGE_DIR.append(_dir)


def _cube_triangles():
    def at(c):
        return [c & 1, (c >> 1) & 1, (c >> 2) & 1]

    def edge_of(a, b):
        lo, d = min(a, b), abs(a - b)
        for e in range(12):
            if CUBE_EDGE_FROM[e] == lo and CUBE_EDGE_DIR[e] == d:
                return e
        raise ValueError("not a cube edge")

    def middle(e):
        p, d = at(CUBE_EDGE_FROM[e]), at(CUBE_EDGE_DIR[e])
        return [p[k] + d[k] / 2 for k in range(3)]

    faces = []
    for ax in range(3):
        bit, u, v = 1 << ax, 1 << ((ax + 1) % 3), 1 << ((ax + 2) % 3)
        for side in (0, 1):
            base = bit if side else 0
            normal = [0, 0, 0]
            normal[ax] = 1 if side else -1
            faces.append(([base, base | u, base | u | v, base | v], normal))
    table = []
    for c in range(256):
        def above(k):
            return (c >> k) & 1

        nxt = [-1] * 12

        def join(fr, to, corner, normal):
            a, b, p = middle(fr), middle(to), at(corner)
            ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
            wx, wy, wz = p[0] - a[0], p[1] - a[1], p[2] - a[2]
            left = (uy * wz - uz * wy) * normal[0] + (uz * wx - ux * wz) * normal[1] + (ux * wy - uy * wx) * normal[2]
            if left > 0:
                nxt[fr] = to
            else:
                nxt[to] = fr

        for q, normal in faces:
            crossed = [i for i in range(4) if above(q[i]) != above(q[(i + 1) % 4])]
            if len(crossed) == 2:
                corner = next(k for k in q if above(k))
                join(edge_of(q[crossed[0]], q[(crossed[0] + 1) % 4]), edge_of(q[crossed[1]], q[(crossed[1] + 1) % 4]), corner, normal)
            elif len(crossed) == 4:
                for i in range(4):
                    if above(q[i]):
                        join(edge_of(q[(i + 3) % 4], q[i]), edge_of(q[i], q[(i + 1) % 4]), q[i], normal)
        tris = []
        seen = [0] * 12
        for e in range(12):
            if nxt[e] < 0 or seen[e]:
                continue
            loop = []
            x = e
            while not seen[x]:
                seen[x] = 1
                loop.append(x)
                x = nxt[x]
            n = len(loop)

            def shares_face(a, b):
                pa, pb = middle(a), middle(b)
                return any((x in (0, 1)) and x == pb[k] for k, x in enumerate(pa))

            apex = -1
            for s in range(n):
                if all(not shares_face(loop[s], loop[(s + i) % n]) for i in range(2, n - 1)):
                    apex = s
                    break
            if apex < 0:
                raise ValueError(f"cube case {c}: no fan")
            for i in range(1, n - 1):
                tris += [loop[apex], loop[(apex + i) % n], loop[(apex + i + 1) % n]]
        table.append(tris)
    return table


CUBE_TRIANGLES = _cube_triangles()
_CT_LEN = np.array([len(t) // 3 for t in CUBE_TRIANGLES], dtype=np.int64)
_CT_MAX = int(_CT_LEN.max())
_CT = np.full((256, _CT_MAX, 3), -1, dtype=np.int64)
for _c, _t in enumerate(CUBE_TRIANGLES):
    if _t:
        _CT[_c, :len(_t) // 3] = np.array(_t).reshape(-1, 3)

# The six tetrahedra of a cube, Kuhn's (marching.ts TETS).
TETS = ((0, 1, 3, 7), (0, 1, 5, 7), (0, 2, 3, 7), (0, 2, 6, 7), (0, 4, 5, 7), (0, 4, 6, 7))


def _corner_offsets(nx, ny):
    return np.array([0, 1, nx, nx + 1, nx * ny, nx * ny + 1, nx * ny + nx, nx * ny + nx + 1], dtype=np.int64)


def _bits(c):
    return np.array([c & 1, (c >> 1) & 1, (c >> 2) & 1], dtype=float)


def _tet_table():
    """For each tetrahedron and case of its four corners above zero, its
    triangles by corner pairs — wound as marching.ts's emitter winds them,
    which depends only on the corners' places in the cube."""
    table = {}
    for ti, tet in enumerate(TETS):
        for m in range(1, 15):
            pos = [tet[k] for k in range(4) if (m >> k) & 1]
            neg = [tet[k] for k in range(4) if not (m >> k) & 1]
            d = np.mean([_bits(p) for p in pos], axis=0) - np.mean([_bits(q) for q in neg], axis=0)
            if len(pos) == 1 or len(neg) == 1:
                lone, others = (pos[0], neg) if len(pos) == 1 else (neg[0], pos)
                tris = [((lone, others[0]), (lone, others[1]), (lone, others[2]))]
            else:
                a, b, c, e = (pos[0], neg[0]), (pos[0], neg[1]), (pos[1], neg[1]), (pos[1], neg[0])
                tris = [(a, b, c), (a, c, e)]
            out = []
            for t in tris:
                mid = [(_bits(x) + _bits(y)) / 2 for x, y in t]
                dot = np.cross(mid[1] - mid[0], mid[2] - mid[0]) @ d
                out.append(t if dot >= 0 else (t[0], t[2], t[1]))
            table[(ti, m)] = out
    return table


_TET_TABLE = _tet_table()


def _vertices_on_edges(field, ga, gb, ox, oy, oz, h, nx, ny):
    """One vertex per grid edge (ga, gb), where the field crosses zero along
    it; the inverse maps each edge given to its vertex."""
    lo, hi = np.minimum(ga, gb), np.maximum(ga, gb)
    total = field.size
    key = lo * total + hi
    uniq, first, inv = np.unique(key, return_index=True, return_inverse=True)
    a, b = ga[first], gb[first]
    fa, fb = field[a], field[b]
    s = fa / (fa - fb)

    def place(g):
        i = g % nx
        j = (g // nx) % ny
        k = g // (nx * ny)
        return np.stack([ox + i * h, oy + j * h, oz + k * h], axis=1)

    pa, pb = place(a), place(b)
    return pa + s[:, None] * (pb - pa), inv.reshape(-1)


def march_cubes(field, ox, oy, oz, h):
    """The surface where field (nx, ny, nz; point i + nx*(j + ny*k) is
    field[i, j, k]) crosses zero, by marching cubes: triangles facing the
    side where it is positive."""
    nx, ny, nz = field.shape
    flat = np.asarray(field, dtype=float).ravel(order="F")
    pos = flat > 0
    cube = np.arange(nx * ny * nz).reshape((nx, ny, nz), order="F")[:-1, :-1, :-1].ravel(order="F")
    off = _corner_offsets(nx, ny)
    case = np.zeros(len(cube), dtype=np.int64)
    for c in range(8):
        case |= pos[cube + off[c]].astype(np.int64) << c
    mixed = (case > 0) & (case < 255)
    cube, case = cube[mixed], case[mixed]
    if len(cube) == 0:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64)
    tris = _CT[case]  # (n, max, 3) cube edges
    valid = tris[:, :, 0] >= 0
    ci = np.repeat(np.arange(len(cube)), valid.sum(axis=1))
    E = tris[valid]  # (m, 3)
    efrom = np.array(CUBE_EDGE_FROM)[E]
    edir = np.array(CUBE_EDGE_DIR)[E]
    base = cube[ci][:, None]
    ga = base + off[efrom]
    gb = base + off[efrom + edir]
    P, inv = _vertices_on_edges(flat, ga.ravel(), gb.ravel(), ox, oy, oz, h, nx, ny)
    return P, inv.reshape(-1, 3)


def march_tetrahedra(field, ox, oy, oz, h):
    """The surface where field crosses zero, by marching tetrahedra: one
    vertex on each grid edge it crosses, every triangle facing the positive
    side (marching.ts marchTetrahedra)."""
    nx, ny, nz = field.shape
    flat = np.asarray(field, dtype=float).ravel(order="F")
    pos = flat > 0
    cube = np.arange(nx * ny * nz).reshape((nx, ny, nz), order="F")[:-1, :-1, :-1].ravel(order="F")
    off = _corner_offsets(nx, ny)
    count = np.zeros(len(cube), dtype=np.int64)
    for c in range(8):
        count += pos[cube + off[c]]
    cube = cube[(count > 0) & (count < 8)]
    if len(cube) == 0:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64)
    GA, GB = [], []
    for ti, tet in enumerate(TETS):
        m = np.zeros(len(cube), dtype=np.int64)
        for k in range(4):
            m |= pos[cube + off[tet[k]]].astype(np.int64) << k
        for case in np.unique(m).tolist():
            if case in (0, 15):
                continue
            rows = cube[m == case]
            for t in _TET_TABLE[(ti, case)]:
                GA.append(np.stack([rows + off[x] for x, _ in t], axis=1))
                GB.append(np.stack([rows + off[y] for _, y in t], axis=1))
    ga, gb = np.vstack(GA), np.vstack(GB)
    P, inv = _vertices_on_edges(flat, ga.ravel(), gb.ravel(), ox, oy, oz, h, nx, ny)
    return P, inv.reshape(-1, 3)


def drop_specks(V, F, min_volume, facing="in"):
    """The pieces enclosing at least min_volume (negative for "in", a
    cavity's wall): the triangles kept, how many pieces, the kept mask."""
    F = np.asarray(F, dtype=np.int64).reshape(-1, 3)
    if len(F) == 0:
        return F, 0, np.zeros(0, dtype=bool)
    sign = -1 if facing == "in" else 1
    lab = M.components(F, len(V))
    root = lab[F[:, 0]]
    t = np.asarray(V, dtype=float)[F]
    v6 = np.einsum("ij,ij->i", t[:, 0], np.cross(t[:, 1], t[:, 2]))
    roots, inv = np.unique(root, return_inverse=True)
    vol = np.zeros(len(roots))
    np.add.at(vol, inv, v6 / 6)
    good = sign * vol >= min_volume
    kept = good[inv]
    return F[kept], int(good.sum()), kept


def compact_mesh(V, F):
    """The mesh on the vertices its triangles use, in their order."""
    V2, F2, _ = M.compact_edit(V, F, 0)
    return V2, F2


def signed_volume(V, F):
    F = np.asarray(F, dtype=np.int64).reshape(-1, 3)
    if len(F) == 0:
        return 0.0
    t = np.asarray(V, dtype=float)[F]
    return float(np.einsum("ij,ij->i", t[:, 0], np.cross(t[:, 1], t[:, 2])).sum() / 6)


# ---- nearest triangles within a reach ----------------------------------------------------

def _ragged(lo, hi):
    """Every integer box cell between lo and hi (inclusive, per row): the
    row each comes from and its (i, j, k)."""
    w = np.maximum(hi - lo + 1, 0)
    cnt = w[:, 0] * w[:, 1] * w[:, 2]
    row = np.repeat(np.arange(len(lo)), cnt)
    local = np.arange(int(cnt.sum())) - np.repeat(np.cumsum(cnt) - cnt, cnt)
    wx, wy = w[row, 0], w[row, 1]
    i = lo[row, 0] + local % wx
    j = lo[row, 1] + (local // wx) % wy
    k = lo[row, 2] + local // (wx * wy)
    return row, i, j, k


class NearSurface:
    """The triangles of a mesh filed by the cells of a uniform grid that
    their box, grown by `reach`, overlaps — so a point's candidates within
    reach are those filed under its own cell. What ScanRuler's wrapTile.ts
    tileSnap does tile by tile, here for any batch of points: the nearest
    triangle within reach, optionally only among those whose normal is
    within min_dot of a direction."""

    def __init__(self, V, F, reach):
        from ..dev_surface import closest_on_triangles

        self._closest = closest_on_triangles
        V = np.asarray(V, dtype=float)
        F = np.asarray(F, dtype=np.int64).reshape(-1, 3)
        self.A, self.B, self.C = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
        n = np.cross(self.B - self.A, self.C - self.A)
        L = np.linalg.norm(n, axis=1)
        self.normal = np.where(L[:, None] > 0, n / np.where(L > 0, L, 1)[:, None], 0)
        self.reach = float(reach)
        T = np.stack([self.A, self.B, self.C], axis=1)
        bmin, bmax = T.min(axis=1) - reach, T.max(axis=1) + reach
        self.g = g = max(reach, 1e-9)
        self.o = bmin.min(axis=0)
        span = bmax.max(axis=0) - self.o
        self.n = np.maximum(1, np.ceil(span / g).astype(np.int64) + 1)
        lo = np.floor((bmin - self.o) / g).astype(np.int64)
        hi = np.floor((bmax - self.o) / g).astype(np.int64)
        row, i, j, k = _ragged(lo, hi)
        key = i + self.n[0] * (j + self.n[1] * k)
        order = np.argsort(key, kind="stable")
        self.keys = key[order]
        self.tris = row[order]

    def nearest(self, P, facing=None, min_dot=None, chunk=1 << 21):
        """For each point: (found, distance, point, face), the nearest
        triangle within reach (inf, -1 where none)."""
        P = np.asarray(P, dtype=float).reshape(-1, 3)
        m = len(P)
        dist = np.full(m, np.inf)
        pt = np.zeros((m, 3))
        face = np.full(m, -1, dtype=np.int64)
        c = np.floor((P - self.o) / self.g).astype(np.int64)
        inside = (c >= 0).all(axis=1) & (c < self.n).all(axis=1)
        key = np.where(inside, c[:, 0] + self.n[0] * (c[:, 1] + self.n[1] * c[:, 2]), -1)
        s = np.searchsorted(self.keys, key, "left")
        e = np.searchsorted(self.keys, key, "right")
        cnt = np.where(inside, e - s, 0)
        q_all = np.nonzero(cnt)[0]
        # In batches of queries whose pairs stay under chunk.
        cum = np.cumsum(cnt[q_all])
        start = 0
        while start < len(q_all):
            base = cum[start - 1] if start else 0
            stop = int(np.searchsorted(cum, base + chunk, "right"))
            stop = max(stop, start + 1)
            q = q_all[start:stop]
            qc = cnt[q]
            qi = np.repeat(q, qc)
            local = np.arange(int(qc.sum())) - np.repeat(np.cumsum(qc) - qc, qc)
            t = self.tris[np.repeat(s[q], qc) + local]
            X, _ = self._closest(P[qi], self.A[t], self.B[t], self.C[t])
            d2 = ((X - P[qi]) ** 2).sum(axis=1)
            bad = d2 > self.reach * self.reach
            if facing is not None:
                bad |= np.einsum("ij,ij->i", self.normal[t], facing[qi]) < min_dot
            d2[bad] = np.inf
            order = np.lexsort((d2, qi))
            first = np.ones(len(order), dtype=bool)
            first[1:] = qi[order][1:] != qi[order][:-1]
            pick = order[first]
            good = np.isfinite(d2[pick])
            pq = qi[pick][good]
            dist[pq] = np.sqrt(d2[pick][good])
            pt[pq] = X[pick][good]
            face[pq] = t[pick][good]
            start = stop
        return face >= 0, dist, pt, face
