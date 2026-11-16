# SPDX-License-Identifier: AGPL-3.0-only
# Written for ScanRuler for FreeCAD (not a port: ScanRuler's own boolean is Manifold's).
#
# A closed triangle mesh and another made one — the second taken out of the
# first, added to it, or only what both enclose kept — in numpy alone, for
# meshes of any density (a 140,000-triangle scan and a CAD cutter alike).
#
# Why not FreeCAD's Mesh.unite / difference / intersect: they decide each
# step in floating point on its own, so on a dense scan the cut seam comes
# back open, T-junctioned and wound both ways. Here every topological
# decision is one orientation sign, computed once for a set of four points
# in a fixed order of their indices, so two triangles that share an edge
# always agree on where the other surface crosses it; and the cut is made
# only where the two surfaces meet — the rest of the mesh is never touched
# (the "local region": a triangle away from the other mesh keeps its exact
# points and indices).
#
#   1. The second mesh is moved by a tiny rigid jitter (1e-7 of the size) so
#      no point of one lies on a face of the other.
#   2. Every edge of each mesh is tested against the triangles of the other
#      it could meet (a grid on their boxes); a crossing is a new point
#      both meshes share.
#   3. Each triangle the other surface crosses is split along the crossing
#      path (chains edge to edge, or closed loops inside it) and the pieces
#      ear-clipped; its corners and edge points are the same indices its
#      neighbours use, so the seam is closed by construction.
#   4. The pieces of each mesh, joined across every edge that is not on the
#      seam, are kept or dropped by the winding number of one point of each
#      piece about the other mesh.
#
# A result that does not come out closed is tried again with another jitter;
# after three tries it is refused (never handed back broken).

import numpy as np

OPS = ("subtract", "add", "intersect")


class BooleanError(ValueError):
    """A boolean that could not be made closed."""


# ---- small helpers ---------------------------------------------------------------------------

def edges_of(F):
    """Unique undirected edges (m, 2), triangle -> edge ids (n, 3), edge ->
    its two triangles (m, 2). Raises unless every edge has exactly two."""
    F = np.asarray(F, dtype=np.int64).reshape(-1, 3)
    a = F.reshape(-1)
    b = F[:, [1, 2, 0]].reshape(-1)
    lo, hi = np.minimum(a, b), np.maximum(a, b)
    key = lo * (int(F.max()) + 1) + hi
    uniq, inv, counts = np.unique(key, return_inverse=True, return_counts=True)
    if (counts != 2).any():
        raise BooleanError(f"{int((counts == 1).sum())} open edges and {int((counts > 2).sum())} shared by more than two triangles")
    E = np.stack([lo, hi], axis=1)[np.unique(inv, return_index=True)[1]]
    TE = inv.reshape(-1, 3)
    order = np.argsort(inv, kind="stable")
    EF = (order // 3).reshape(-1, 2)
    return E, TE, EF


def closed_report(F):
    """open: half-edges with no opposite; bad: edges used other than once each way."""
    F = np.asarray(F, dtype=np.int64).reshape(-1, 3)
    if len(F) == 0:
        return {"open": 0, "bad": 0}
    a = F.reshape(-1)
    b = F[:, [1, 2, 0]].reshape(-1)
    n = int(F.max()) + 1
    fwd, cf = np.unique(a * n + b, return_counts=True)
    back = b * n + a
    i = np.clip(np.searchsorted(fwd, back), 0, len(fwd) - 1)
    has = fwd[i] == back
    return {"open": int((~has).sum()), "bad": int((cf > 1).sum())}


def volume(V, F):
    F = np.asarray(F, dtype=np.int64).reshape(-1, 3)
    if len(F) == 0:
        return 0.0
    t = np.asarray(V, dtype=float)[F]
    return float(np.einsum("ij,ij->i", t[:, 0], np.cross(t[:, 1], t[:, 2])).sum() / 6)


def winding(V, F, p):
    """The winding number of a closed mesh about the point p."""
    t = np.asarray(V, dtype=float)[F] - np.asarray(p, dtype=float)
    a, b, c = t[:, 0], t[:, 1], t[:, 2]
    la, lb, lc = (np.linalg.norm(x, axis=1) for x in (a, b, c))
    num = np.einsum("ij,ij->i", a, np.cross(b, c))
    den = la * lb * lc + np.einsum("ij,ij->i", a, b) * lc + np.einsum("ij,ij->i", b, c) * la + np.einsum("ij,ij->i", c, a) * lb
    return float(2 * np.arctan2(num, den).sum() / (4 * np.pi))


def labels(n, pairs):
    """Connected components of n items joined by pairs (k, 2): a label each."""
    lab = np.arange(n)
    if len(pairs) == 0:
        return lab
    i, j = pairs[:, 0], pairs[:, 1]
    while True:
        m = np.minimum(lab[i], lab[j])
        old = lab.copy()
        np.minimum.at(lab, i, m)
        np.minimum.at(lab, j, m)
        while True:
            nxt = lab[lab]
            if np.array_equal(nxt, lab):
                break
            lab = nxt
        if np.array_equal(old, lab):
            return lab


def box_pairs(lo1, hi1, lo2, hi2):
    """Index pairs (i, j) whose boxes overlap: a uniform grid, joined by key."""
    if len(lo1) == 0 or len(lo2) == 0:
        return np.zeros((0, 2), dtype=np.int64)
    ext = np.concatenate([(hi1 - lo1).max(axis=1), (hi2 - lo2).max(axis=1)])
    h = max(float(np.median(ext)) * 2.0, 1e-9)
    origin = np.minimum(lo1.min(axis=0), lo2.min(axis=0))

    def cells(lo, hi, h):
        c0 = np.floor((lo - origin) / h).astype(np.int64)
        c1 = np.floor((hi - origin) / h).astype(np.int64)
        span = c1 - c0 + 1
        count = span.prod(axis=1)
        item = np.repeat(np.arange(len(lo)), count)
        k = np.arange(int(count.sum())) - np.repeat(np.cumsum(count) - count, count)
        sx, sy = span[item, 0], span[item, 1]
        cx = c0[item, 0] + k % sx
        cy = c0[item, 1] + (k // sx) % sy
        cz = c0[item, 2] + k // (sx * sy)
        return item, (cx * 2097152 + cy) * 2097152 + cz, int(count.sum())

    while True:
        i1, k1, n1 = cells(lo1, hi1, h)
        i2, k2, n2 = cells(lo2, hi2, h)
        if n1 + n2 < 4e7:
            break
        h *= 2
    o = np.argsort(k1, kind="stable")
    k1, i1 = k1[o], i1[o]
    s = np.searchsorted(k1, k2, "left")
    e = np.searchsorted(k1, k2, "right")
    cnt = e - s
    j = np.repeat(i2, cnt)
    off = np.arange(int(cnt.sum())) - np.repeat(np.cumsum(cnt) - cnt, cnt)
    i = i1[np.repeat(s, cnt) + off]
    if len(i) == 0:
        return np.zeros((0, 2), dtype=np.int64)
    P = np.unique(i.astype(np.int64) * (len(lo2) + 1) + j, return_index=False)
    i, j = P // (len(lo2) + 1), P % (len(lo2) + 1)
    ok = ((lo1[i] <= hi2[j]) & (lo2[j] <= hi1[i])).all(axis=1)
    return np.stack([i[ok], j[ok]], axis=1)


# ---- the one predicate -----------------------------------------------------------------------

_INV = [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)]


def orient(P, ids):
    """sign of det[p1 - p0, p2 - p0, p3 - p0] for each row of 4 point ids,
    computed in ascending id order and corrected by the permutation's
    parity, a zero counted positive: the same 4 points always give the
    same answer, whichever triangle asks."""
    o = np.argsort(ids, axis=1, kind="stable")
    s = np.take_along_axis(ids, o, axis=1)
    inv = np.zeros(len(ids), dtype=np.int64)
    for a, b in _INV:
        inv += o[:, a] > o[:, b]
    p0, p1, p2, p3 = (P[s[:, k]] for k in range(4))
    d = np.einsum("ij,ij->i", p1 - p0, np.cross(p2 - p0, p3 - p0))
    sg = np.where(d < 0, -1, 1)
    return np.where(inv % 2 == 1, -sg, sg)


def crossings(P, E, F, edges, tris):
    """Whether each edge E[edges] crosses triangle F[tris] (ids into P), and
    where."""
    p, q = E[edges, 0], E[edges, 1]
    a, b, c = F[tris, 0], F[tris, 1], F[tris, 2]
    sp = orient(P, np.stack([a, b, c, p], axis=1))
    sq = orient(P, np.stack([a, b, c, q], axis=1))
    t1 = orient(P, np.stack([p, q, a, b], axis=1))
    t2 = orient(P, np.stack([p, q, b, c], axis=1))
    t3 = orient(P, np.stack([p, q, c, a], axis=1))
    hit = (sp != sq) & (t1 == t2) & (t2 == t3)
    A, B, C = P[a[hit]], P[b[hit]], P[c[hit]]
    n = np.cross(B - A, C - A)
    dp = np.einsum("ij,ij->i", n, P[p[hit]] - A)
    dq = np.einsum("ij,ij->i", n, P[q[hit]] - A)
    den = dp - dq
    t = np.clip(np.where(den != 0, dp / np.where(den != 0, den, 1), 0.5), 0, 1)
    X = P[p[hit]] + (P[q[hit]] - P[p[hit]]) * t[:, None]
    return hit, X


# ---- splitting one triangle ------------------------------------------------------------------

def _area2(pts):
    x, y = pts[:, 0], pts[:, 1]
    return float((x * np.roll(y, -1) - np.roll(x, -1) * y).sum())


def _inside(pt, poly):
    x, y = pt
    xs, ys = poly[:, 0], poly[:, 1]
    xs2, ys2 = np.roll(xs, -1), np.roll(ys, -1)
    cond = (ys > y) != (ys2 > y)
    with np.errstate(divide="ignore", invalid="ignore"):
        xc = xs + (y - ys) * (xs2 - xs) / (ys2 - ys)
    return bool((cond & (x < xc)).sum() % 2)


def bridge(outer, holes, xy):
    """One weakly simple polygon from an outer ring and its holes (each a
    list of ids, the holes wound the other way): each hole, rightmost first,
    joined by a cut to the nearest ring point it sees."""
    poly = list(outer)
    for hole in sorted(holes, key=lambda h: -max(xy[v][0] for v in h)):
        hi = max(range(len(hole)), key=lambda k: xy[hole[k]][0])
        h = hole[hi]
        H = xy[h]
        rings = [poly] + list(holes)
        sa = np.array([r[k] for r in rings for k in range(len(r))])
        sb = np.array([r[(k + 1) % len(r)] for r in rings for k in range(len(r))])
        A = np.array([xy[v] for v in sa.tolist()])
        B = np.array([xy[v] for v in sb.tolist()])
        P = np.array([xy[v] for v in poly])
        order = np.argsort(((P - H) ** 2).sum(axis=1), kind="stable")
        best = int(order[0])

        def cr(o, p, q):
            return (p[..., 0] - o[..., 0]) * (q[..., 1] - o[..., 1]) - (p[..., 1] - o[..., 1]) * (q[..., 0] - o[..., 0])

        d3 = cr(A, B, H[None, :])
        for k in order.tolist():
            v = poly[k]
            Q = P[k]
            skip = (sa == v) | (sb == v) | (sa == h) | (sb == h)
            d1, d2 = cr(H, Q, A), cr(H, Q, B)
            d4 = cr(A, B, Q[None, :])
            hit = (d1 * d2 < 0) & (d3 * d4 < 0) & ~skip
            if not hit.any():
                best = k
                break
        ring = hole[hi:] + hole[:hi] + [h]
        poly = poly[:best + 1] + ring + poly[best:]
    return poly


def canonical_cross(ids, pts):
    """The 2D cross (b - a) x (c - a) of each row's three points, worked in
    ascending id order and signed by the permutation: a corner seen from
    both sides of a cut path gets exactly opposite signs, so the two
    polygons there never both clip it (a near-straight run of seam points
    would otherwise be an ear on both sides, its diagonal used twice)."""
    o = np.argsort(ids, axis=1, kind="stable")
    P = np.take_along_axis(pts, o[:, :, None], axis=1)
    odd = (o[:, 0] > o[:, 1]).astype(int) + (o[:, 0] > o[:, 2]) + (o[:, 1] > o[:, 2])
    a, b, c = P[:, 0], P[:, 1], P[:, 2]
    cr = (b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0])
    return np.where(odd % 2 == 1, -cr, cr)


def earclip(poly, xy, banned=frozenset()):
    """Triangles (id triples, counter-clockwise in xy) of a simple or weakly
    simple counter-clockwise polygon: each step clips, of the convex corners
    no other point lies in, the one whose triangle is roundest. A diagonal
    in `banned` (sorted id pairs) is not drawn unless nothing else is left."""
    idx = np.array(poly, dtype=np.int64)
    pts = np.array([xy[v] for v in poly], dtype=float)
    out = []
    # the edges drawn so far: a bridged hole's points come twice in the
    # ring, and a diagonal from each copy to the same point would be one
    # edge of four triangles
    have = {(min(int(u), int(w)), max(int(u), int(w))) for u, w in zip(idx, np.roll(idx, -1))}
    banned = set(banned)
    while len(idx) > 3:
        n = len(idx)
        a, b, c = np.roll(pts, 1, axis=0), pts, np.roll(pts, -1, axis=0)
        ia, ic = np.roll(idx, 1), np.roll(idx, -1)
        cr = canonical_cross(np.stack([ia, idx, ic], axis=1), np.stack([a, b, c], axis=1))
        longest = np.maximum.reduce([((b - a) ** 2).sum(1), ((c - b) ** 2).sum(1), ((a - c) ** 2).sum(1)])
        q = cr / np.maximum(longest, 1e-300)
        q = np.where(q > 1e-12, q, -np.inf)  # a corner on a straight run is no ear
        best = None
        for k in np.argsort(-q, kind="stable").tolist():
            if not np.isfinite(q[k]):
                break
            u, w = int(ia[k]), int(ic[k])
            if (min(u, w), max(u, w)) in banned or (min(u, w), max(u, w)) in have:
                continue
            A, B, C = a[k], b[k], c[k]
            p = pts
            d1 = (B[0] - A[0]) * (p[:, 1] - A[1]) - (B[1] - A[1]) * (p[:, 0] - A[0])
            d2 = (C[0] - B[0]) * (p[:, 1] - B[1]) - (C[1] - B[1]) * (p[:, 0] - B[0])
            d3 = (A[0] - C[0]) * (p[:, 1] - C[1]) - (A[1] - C[1]) * (p[:, 0] - C[0])
            blocked = (d1 >= 0) & (d2 >= 0) & (d3 >= 0) & (idx != ia[k]) & (idx != idx[k]) & (idx != ic[k])
            if not blocked.any():
                best = k
                break
        if best is None:
            # nothing clean: the most convex corner whose diagonal is allowed,
            # else the most convex, so the ring still closes
            free = np.array([(min(int(u), int(w)), max(int(u), int(w))) not in banned and (min(int(u), int(w)), max(int(u), int(w))) not in have
                             for u, w in zip(ia, ic)])
            best = int(np.argmax(np.where(free, cr, -np.inf))) if free.any() else int(np.argmax(cr))
        out.append((int(ia[best]), int(idx[best]), int(ic[best])))
        have.add((min(int(ia[best]), int(ic[best])), max(int(ia[best]), int(ic[best]))))
        idx = np.delete(idx, best)
        pts = np.delete(pts, best, axis=0)
    if len(idx) == 3:
        out.append(tuple(int(v) for v in idx))
    return out


def split_triangle(corners, edge_pts, segs, X3):
    """A triangle cut along its crossing segments.

    corners: its 3 vertex ids in winding order; edge_pts[k]: ids on edge
    k (corner k -> k+1) in order along it; segs: (id, id) pairs; X3: id ->
    3D point. Returns a list of id triples, wound as the triangle is, or
    None when the crossings do not make sense (try another jitter)."""
    adj = {}
    for s, t in segs:
        adj.setdefault(s, []).append(t)
        adj.setdefault(t, []).append(s)
    on_edge = {v for pts in edge_pts for v in pts}
    for v, nb in adj.items():
        if len(nb) != (1 if v in on_edge else 2):
            return None
    if any(v not in adj for v in on_edge):
        return None
    ring = []
    for k in range(3):
        ring.append(corners[k])
        ring.extend(edge_pts[k])
    P3 = np.array([X3(v) for v in set(ring) | set(adj)])
    ids = list(set(ring) | set(adj))
    c = np.array([X3(v) for v in corners])
    nrm = np.cross(c[1] - c[0], c[2] - c[0])
    ax = int(np.argmax(np.abs(nrm)))
    u, w = [(1, 2), (2, 0), (0, 1)][ax]
    if nrm[ax] < 0:
        u, w = w, u
    xy = {v: np.array([p[u], p[w]]) for v, p in zip(ids, P3)}
    # chains edge to edge, then loops
    seen = set()
    chains, loops = [], []
    for v in on_edge:
        if v in seen:
            continue
        ch = [v]
        seen.add(v)
        prev, cur = None, v
        while True:
            nxt = [x for x in adj[cur] if x != prev]
            if not nxt:
                break
            prev, cur = cur, nxt[0]
            if cur in seen:
                return None
            ch.append(cur)
            seen.add(cur)
            if cur in on_edge:
                break
        if ch[-1] not in on_edge or len(ch) < 2:
            return None
        chains.append(ch)
    for v in adj:
        if v in seen:
            continue
        lp = [v]
        seen.add(v)
        prev, cur = None, v
        while True:
            nxt = [x for x in adj[cur] if x != prev and (x not in seen or x == v)]
            if not nxt:
                return None
            prev, cur = cur, nxt[0]
            if cur == v:
                break
            lp.append(cur)
            seen.add(cur)
        loops.append(lp)
    # Each cut path is given to one side: the piece on the other side may
    # draw no diagonal between two of its points. A near-straight run of
    # seam points, a hair off its true line, could otherwise be clipped as
    # an ear on both sides — the same diagonal twice, an edge of four
    # triangles. The side given a path is the one made of nothing else, if
    # either is; a loop's inside always has it.
    polys = [(ring, [])]
    for ch in chains:
        s, e = ch[0], ch[-1]
        hit = [k for k, (pg, _) in enumerate(polys) if s in pg and e in pg]
        if len(hit) != 1:
            return None
        pg, foreign = polys.pop(hit[0])
        i, j = pg.index(s), pg.index(e)
        n = len(pg)
        mid = ch[1:-1]
        part1 = [pg[(i + k) % n] for k in range(((j - i) % n) + 1)] + mid[::-1]
        part2 = [pg[(j + k) % n] for k in range(((i - j) % n) + 1)] + mid
        path = frozenset(ch)
        if all(v in path for v in part2):
            part1, part2 = part2, part1
        polys.append((part1, list(foreign)))
        polys.append((part2, foreign + [path]))
    regions = [[pg, [], foreign] for pg, foreign in polys]
    for lp in sorted(loops, key=lambda lp: -abs(_area2(np.array([xy[v] for v in lp])))):
        a = _area2(np.array([xy[v] for v in lp]))
        ccw = lp if a > 0 else lp[::-1]
        pt = xy[lp[0]] * 0.5 + xy[lp[1]] * 0.5 if len(lp) > 1 else xy[lp[0]]
        home = None
        for reg in regions:
            if _inside(pt, np.array([xy[v] for v in reg[0]])) and not any(_inside(pt, np.array([xy[v] for v in h])) for h in reg[1]):
                home = reg
        if home is None:
            home = regions[0]
        home[1].append(ccw[::-1])
        home[2] = home[2] + [frozenset(lp)]
        regions.append([ccw, [], []])
    # Nor between two points of one side of the triangle: the neighbour
    # across it has them joined one by one.
    side_pairs = set()
    for k in range(3):
        side = [corners[k], *edge_pts[k], corners[(k + 1) % 3]]
        side_pairs.update((min(u, v), max(u, v)) for i, u in enumerate(side) for v in side[i + 2:])
    tris = []
    for outer, holes, foreign in regions:
        pg = bridge(outer, holes, xy) if holes else outer
        banned = set(side_pairs)
        for path in foreign:
            pts = sorted(path)
            banned.update((u, v) for i, u in enumerate(pts) for v in pts[i + 1:])
        tris.extend(earclip(pg, xy, banned))
    return tris


# ---- the boolean -----------------------------------------------------------------------------

def _jitter(V, seed, size):
    rng = np.random.default_rng(1234 + seed)
    eps = size * 1e-7 * (1 + 9 * seed)
    ang = rng.normal(size=3)
    ang *= eps / max(size, 1e-12) / np.linalg.norm(ang)
    cx, cy, cz = np.cos(ang)
    sx, sy, sz = np.sin(ang)
    R = (np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]]) @ np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
         @ np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]]))
    c = V.mean(axis=0)
    t = rng.normal(size=3)
    t *= eps / np.linalg.norm(t)
    return (V - c) @ R.T + c + t


def _attempt(VA, FA, VB, FB, op, seed):
    nA, nB = len(VA), len(VB)
    size = float(np.linalg.norm(np.ptp(np.vstack([VA, VB]), axis=0)))
    VBj = _jitter(VB, seed, size)
    origin = VBj.mean(axis=0)
    P = np.vstack([VA, VBj]) - origin  # the predicate's points, about the cutter
    FBg = FB + nA
    EA, TEA, EFA = edges_of(FA)
    EB, TEB, EFB = edges_of(FB)
    EBg = EB + nA
    # broad phase: A's triangles near B's box, then triangle-box pairs
    TA, TB = P[FA], P[FBg]
    loA, hiA, loB, hiB = TA.min(axis=1), TA.max(axis=1), TB.min(axis=1), TB.max(axis=1)
    pad = size * 1e-9
    near = ((loA <= hiB.max(axis=0) + pad) & (hiA >= loB.min(axis=0) - pad)).all(axis=1)
    ia = np.nonzero(near)[0]
    pairs = box_pairs(loA[ia] - pad, hiA[ia] + pad, loB - pad, hiB + pad)
    ta, tb = ia[pairs[:, 0]], pairs[:, 1]
    # plane separation: no crossing when one triangle is all to one side of the other's plane
    if len(ta):
        def sep(T1, T2):
            n = np.cross(T2[:, 1] - T2[:, 0], T2[:, 2] - T2[:, 0])
            d = np.einsum("ijk,ik->ij", T1 - T2[:, :1], n)
            tol = 1e-9 * np.linalg.norm(n, axis=1)[:, None] * size
            return (d > tol).all(axis=1) | (d < -tol).all(axis=1)
        keep = ~(sep(TA[ta], TB[tb]) | sep(TB[tb], TA[ta]))
        ta, tb = ta[keep], tb[keep]
    # edge x triangle tests, both ways
    ea = np.unique(TEA[ta].reshape(-1) * (len(FB) + 1) + np.repeat(tb, 3))
    ea_e, ea_t = ea // (len(FB) + 1), ea % (len(FB) + 1)
    eb = np.unique(TEB[tb].reshape(-1) * (len(FA) + 1) + np.repeat(ta, 3))
    eb_e, eb_t = eb // (len(FA) + 1), eb % (len(FA) + 1)
    hA, XA = crossings(P, EA, FBg, ea_e, ea_t)
    hB, XB = crossings(P, EBg, FA, eb_e, eb_t)
    ca_e, ca_t = ea_e[hA], ea_t[hA]  # A edge crosses B triangle
    cb_e, cb_t = eb_e[hB], eb_t[hB]  # B edge crosses A triangle
    base = nA + nB
    idA = base + np.arange(len(ca_e))
    idB = base + len(ca_e) + np.arange(len(cb_e))
    X = np.vstack([XA, XB]) if len(XA) + len(XB) else np.zeros((0, 3))
    # segments: each crossing joins the triangle pairs it lies on
    pa = np.concatenate([EFA[ca_e, 0], EFA[ca_e, 1], cb_t, cb_t])
    pb = np.concatenate([ca_t, ca_t, EFB[cb_e, 0], EFB[cb_e, 1]])
    pid = np.concatenate([idA, idA, idB, idB])
    key = pa * (len(FB) + 1) + pb
    o = np.argsort(key, kind="stable")
    key, pa, pb, pid = key[o], pa[o], pb[o], pid[o]
    uk, start, cnt = np.unique(key, return_index=True, return_counts=True)
    if (cnt != 2).any():
        return None, "odd"
    s0, s1 = pid[start], pid[start + 1]
    sa, sb = pa[start], pb[start]
    Pall = np.vstack([P, X]) if len(X) else P

    def X3(v):
        return Pall[v]

    # per-triangle crossing data
    def split_side(F, TE, ownE, own_c_e, own_c_id, tri_of_seg, base_ids):
        # points on each own edge, sorted along it
        on = {}
        for e, v in zip(own_c_e.tolist(), own_c_id.tolist()):
            on.setdefault(e, []).append(v)
        segs_of = {}
        for t, x, y in zip(tri_of_seg.tolist(), s0.tolist(), s1.tolist()):
            segs_of.setdefault(t, []).append((x, y))
        new = {}
        for t, segs in segs_of.items():
            corners = [int(base_ids[k]) for k in F[t]]
            ep = []
            for k in range(3):
                e = int(TE[t, k])
                pts = on.get(e, [])
                if pts:
                    a, b = Pall[corners[k]], Pall[corners[(k + 1) % 3]]
                    d = b - a
                    pts = sorted(pts, key=lambda v: float(np.dot(Pall[v] - a, d)))
                ep.append(list(pts))
            tris = split_triangle(corners, ep, segs, X3)
            if tris is None:
                return None
            new[t] = tris
        return new

    newA = split_side(FA, TEA, EA, ca_e, idA, sa, np.arange(nA))
    if newA is None:
        return None, "splitA"
    newB = split_side(FB, TEB, EB, cb_e, idB, sb, np.arange(nA, nA + nB))
    if newB is None:
        return None, "splitB"
    seam = set()
    for x, y in zip(s0.tolist(), s1.tolist()):
        seam.add((min(x, y), max(x, y)))

    def side(F, new, offset):
        keepmask = np.ones(len(F), dtype=bool)
        keepmask[list(new.keys())] = False
        parts = [F[keepmask] + offset]
        extra = [t for ts in new.values() for t in ts]
        if extra:
            parts.append(np.array(extra, dtype=np.int64).reshape(-1, 3))
        return np.vstack(parts)

    def regions(G):
        a = G.reshape(-1)
        b = G[:, [1, 2, 0]].reshape(-1)
        lo, hi = np.minimum(a, b), np.maximum(a, b)
        n = int(Pall.shape[0]) + 1
        k = lo * n + hi
        if seam:
            sk = np.array([x * n + y for x, y in seam], dtype=np.int64)
            on_seam = np.isin(k, sk)
        else:
            on_seam = np.zeros(len(k), dtype=bool)
        tri = np.repeat(np.arange(len(G)), 3)
        k2, tri2 = k[~on_seam], tri[~on_seam]
        o = np.argsort(k2, kind="stable")
        k2, tri2 = k2[o], tri2[o]
        same = k2[1:] == k2[:-1]
        pr = np.stack([tri2[:-1][same], tri2[1:][same]], axis=1)
        return labels(len(G), pr)

    def classify(G, Vother, Fother):
        lab = regions(G)
        T = Pall[G]
        area = np.linalg.norm(np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0]), axis=1)
        inside = np.zeros(len(G), dtype=bool)
        for r in np.unique(lab).tolist():
            members = np.nonzero(lab == r)[0]
            rep = members[np.argmax(area[members])]
            w = winding(Vother, Fother, T[rep].mean(axis=0))
            inside[members] = w > 0.5
        return inside

    GA = side(FA, newA, 0)
    GB = side(FB, newB, nA)
    inA = classify(GA, P, FBg)
    inB = classify(GB, P, FA)
    if op == "subtract":
        R = np.vstack([GA[~inA], GB[inB][:, ::-1]])
    elif op == "add":
        R = np.vstack([GA[~inA], GB[~inB]])
    else:
        R = np.vstack([GA[inA], GB[inB]])
    c = closed_report(R)
    if c["open"] or c["bad"]:
        return None, f"open {c['open']} bad {c['bad']}"
    Vout = Pall + origin
    Vout[:nA] = VA  # the first mesh's own points, exactly
    used = np.zeros(len(Vout), dtype=bool)
    used[R.reshape(-1)] = True
    remap = np.full(len(Vout), -1, dtype=np.int64)
    remap[used] = np.arange(int(used.sum()))
    info = {"crossings": int(len(X)), "seamSegments": int(len(s0)), "splitTriangles": [len(newA), len(newB)], "jitter": seed}
    return (Vout[used], remap[R], remap[:nA], info), None


def boolean(VA, FA, VB, FB, op, tries=3):
    """The closed meshes A and B made one by op (subtract: A minus B; add;
    intersect): (V, F, vertex map of A's points -> result or -1, info).
    A's surviving points keep their exact positions and order, first."""
    if op not in OPS:
        raise ValueError(f"op: {', '.join(OPS)}")
    VA = np.asarray(VA, dtype=float).reshape(-1, 3)
    VB = np.asarray(VB, dtype=float).reshape(-1, 3)
    FA = np.asarray(FA, dtype=np.int64).reshape(-1, 3)
    FB = np.asarray(FB, dtype=np.int64).reshape(-1, 3)
    why = []
    for seed in range(tries):
        out, err = _attempt(VA, FA, VB, FB, op, seed)
        if out is not None:
            out[3]["tries"] = seed + 1
            return out
        why.append(err)
    raise BooleanError(f"the cut could not be made closed ({'; '.join(why)})")
