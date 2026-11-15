# SPDX-License-Identifier: AGPL-3.0-only
# Ported from ScanRuler by CNC Kitchen (Stefan Hermann):
# plugins/mesh-tools/core/wrap.ts, plugins/mesh-tools/core/wrapTile.ts and
# plugins/mesh-tools/core/wrapSharp.ts
#
# One closed skin round a part that is a mess inside — an assembly exported
# as one mesh, channels and bosses inside a casting, shells overlapping or
# facing the wrong way, a scan with cracks. What is inside is dropped, gaps
# narrower than a width are bridged.
#
# It is the part closed by a ball: the ball, of radius r — half the gap —
# rolls everywhere it can reach from outside without touching the part, and
# the wrap is where it stopped. Only the distance to the triangles is used,
# never which way they face or whether they close, so any triangle soup is
# input enough. Free space is every point further than r from the part; the
# outside is the free space joined to the grid's border; the wrap is the
# surface r from the outside — or r − t, grown by t.
#
# On a grid a third of r across (coarser when the part is too large for the
# grid, and refused when the cell passes r / 1.5):
#  1. the distance to the part — roughly from points spread over the
#     triangles, exactly (the nearest triangle) in a band round r;
#  2. the free space in pieces, those reaching the border the outside;
#  3. the field: inside the outside, the distance to the part less r; past
#     it, minus the distance to where the outside begins, found to within a
#     share of a cell along each grid edge it crosses;
#  4. the wrap through the field by marching cubes, specks dropped;
#  5. each vertex moved onto the nearest triangle within a cell and a half
#     that lies along the wrap there — grown, onto the part grown — unless
#     that would fold the wrap; those left off the part are its bridges;
#  6. with Edges: Sharp, the part's edges and corners the grid cut off put
#     back (wrapSharp.ts).
# ScanRuler works the grid in 64³ tiles on a pool of workers and measures
# only the tiles the outside reaches; here the grid is one numpy array, so
# its budget is in points (MAX_GRID_POINTS) rather than band points and
# tiles, and the report's tiles are the one grid. ScanRuler's last step,
# reducing the wrap with meshoptimizer to a sixteenth of a cell, has no
# reducer here: the wrap keeps the march's triangles (tolerance is kept in
# the settings for when one is).

import math

import numpy as np

from .. import mesh_core as M
from ..dev_surface import FACE, closest_on_triangles
from . import grid as G

MAX_GRID_POINTS = 6_000_000
CELLS_PER_R = 3
MIN_CELLS_PER_R = 1.5
SNAP_REACH = 1.5
SNAP_COS = 0.7
BRIDGE_CELLS = 0.5
REACH_MARGIN = 2.5
FREE_MARGIN = 1.5
MIN_SHELL_CELLS = 8
REDUCE_SHARE = 1 / 16
SNAP_PASSES = 4
FAR_OUT = 1e9

# wrapSharp.ts
FEATURE_COS = math.cos(math.radians(25))
ON_PART = 0.05
NEAR_EDGE = 1
NEAR_CORNER = 1.5
APART = 0.02


def fmt(x):
    return float(f"{x:.3g}")


def default_wrap_gap(diag):
    """A two-hundredth of the part's diagonal on the 1-2-5 steps."""
    return M.round125(diag / 200)


def vertex_normals(V, F):
    n = np.zeros_like(V)
    c = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    for k in range(3):
        np.add.at(n, F[:, k], c)
    L = np.linalg.norm(n, axis=1)
    n[L > 0] /= L[L > 0, None]
    return n


def unfold_snaps(V, F, snapped, target, second):
    """wrap.ts unfoldSnaps: each vertex moved to its target, one after
    another in their order — unless that turns a triangle round it over
    against the way it faced as the grid made it, or puts it where a vertex
    moved before it already is (then its second, the foot on its triangle's
    plane, is tried): then it waits for the next round. `snapped` is left
    saying which moved; V is moved in place."""
    nv = len(V)
    order = np.argsort(F.reshape(-1), kind="stable")
    tri_of = order // 3
    starts = np.searchsorted(F.reshape(-1)[order], np.arange(nv + 1))
    faced = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    P = V.tolist()
    Fl = F.tolist()
    fl = faced.tolist()
    tg = target.tolist()
    sc = second.tolist()
    taken = set()

    def key(p):
        return tuple(np.float32(x).item() for x in p)

    waiting = snapped.copy()
    snapped[:] = False
    for _ in range(SNAP_PASSES):
        moved = 0
        for v in np.nonzero(waiting)[0].tolist():
            if not waiting[v]:
                continue
            if key(tg[v]) in taken:
                if math.isnan(sc[v][0]):
                    waiting[v] = False
                    continue
                tg[v] = sc[v]
                sc[v] = [math.nan] * 3
                if key(tg[v]) in taken:
                    waiting[v] = False
                    continue
            old = P[v]
            P[v] = tg[v]
            folds = False
            for t in tri_of[starts[v]:starts[v + 1]].tolist():
                a, b, c = (P[i] for i in Fl[t])
                ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
                wx, wy, wz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
                nx, ny, nz = uy * wz - uz * wy, uz * wx - ux * wz, ux * wy - uy * wx
                f = fl[t]
                if nx * f[0] + ny * f[1] + nz * f[2] <= 0:
                    folds = True
                    break
            if folds:
                P[v] = old
                continue
            waiting[v] = False
            snapped[v] = True
            moved += 1
            taken.add(key(tg[v]))
        if moved == 0:
            break
    V[:] = np.array(P, dtype=float).reshape(-1, 3)


def _meet_two(p, n, a, b):
    na, nb = n[a], n[b]
    c = float(na @ nb)
    det = 1 - c * c
    if det < 1e-6:
        return None
    m = (p[a] + p[b]) / 2
    ra, rb = float(na @ (p[a] - m)), float(nb @ (p[b] - m))
    alpha, beta = (ra - c * rb) / det, (rb - c * ra) / det
    return m + alpha * na + beta * nb


def _meet_three(p, n, a, b, c):
    N = [n[a], n[b], n[c]]
    d = [float(N[0] @ p[a]), float(N[1] @ p[b]), float(N[2] @ p[c])]
    c12, c20, c01 = np.cross(N[1], N[2]), np.cross(N[2], N[0]), np.cross(N[0], N[1])
    det = float(N[0] @ c12)
    if abs(det) < 0.05:
        return None
    return (d[0] * c12 + d[1] * c20 + d[2] * c01) / det


def sharpen(V, F, bridge, plane, h, probe):
    """wrapSharp.ts sharpen: the wrap with the part's edges and corners put
    back. plane holds, for each vertex snapped onto the part, the unit
    normal of the face it lies on (zero for the rest); probe(points) gives
    each point's distance to the part."""
    nv, nt = len(V), len(F)
    has = np.any(plane != 0, axis=1)
    apart = APART * h
    on_part = np.nonzero(has)[0]
    cells = {}
    for v in on_part.tolist():
        cells.setdefault(tuple(np.floor(V[v] / apart).astype(int).tolist()), []).append(v)

    def near(x):
        i, j, k = np.floor(x / apart).astype(int).tolist()
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for dk in (-1, 0, 1):
                    for v in cells.get((i + di, j + dj, k + dk), ()):
                        if float(((V[v] - x) ** 2).sum()) < apart * apart:
                            return True
        return False

    on_edge = np.full((nt, 3), -1, dtype=np.int64)
    by_key = {}
    pts = []
    for t in range(nt):
        for k in range(3):
            a, b = int(F[t, k]), int(F[t, (k + 1) % 3])
            if not has[a] or not has[b] or float(plane[a] @ plane[b]) > FEATURE_COS:
                continue
            kk = (min(a, b), max(a, b))
            if kk in by_key:
                on_edge[t, k] = by_key[kk]
                continue
            by_key[kk] = -1
            x = _meet_two(V, plane, a, b)
            if x is None:
                continue
            if np.linalg.norm(x - (V[a] + V[b]) / 2) > NEAR_EDGE * h or near(x):
                continue
            by_key[kk] = len(pts)
            on_edge[t, k] = len(pts)
            pts.append(x)
    count = len(pts)
    P = np.array(pts).reshape(-1, 3)
    ok = np.zeros(count, dtype=bool)
    if count:
        ok = probe(P) <= ON_PART * h
    seen = set()
    for c in range(count):
        if not ok[c]:
            continue
        place = tuple(np.rint(P[c] / apart).astype(int).tolist())
        if place in seen:
            ok[c] = False
        else:
            seen.add(place)
    for t in np.nonzero((on_edge >= 0).any(axis=1))[0].tolist():
        for k in range(3):
            c = on_edge[t, k]
            if c < 0 or not ok[c]:
                continue
            a, b, o = F[t, k], F[t, (k + 1) % 3], F[t, (k + 2) % 3]
            n0 = np.cross(V[b] - V[a], V[o] - V[a])
            n1 = np.cross(P[c] - V[a], V[o] - V[a])
            if n0 @ n1 <= 0:
                ok[c] = False
            n1 = np.cross(V[b] - P[c], V[o] - P[c])
            if n0 @ n1 <= 0:
                ok[c] = False
    vertex_of = np.full(count, -1, dtype=np.int64)
    edges = int(ok.sum())
    vertex_of[ok] = nv + np.arange(edges)

    def split(t, k):
        c = on_edge[t, k]
        return -1 if c < 0 else int(vertex_of[c])

    corner_tri, corner_pts = [], []
    for t in range(nt):
        if split(t, 0) < 0 or split(t, 1) < 0 or split(t, 2) < 0:
            continue
        p0, p1, p2 = F[t]
        x = _meet_three(V, plane, p0, p1, p2)
        if x is None:
            continue
        if np.linalg.norm(x - (V[p0] + V[p1] + V[p2]) / 3) > NEAR_CORNER * h or near(x):
            continue
        corner_tri.append(t)
        corner_pts.append(x)
    corner_at = {}
    if corner_tri:
        on = probe(np.array(corner_pts))
        seen = set()
        for i, t in enumerate(corner_tri):
            if on[i] > ON_PART * h:
                continue
            place = tuple(np.rint(corner_pts[i] / apart).astype(int).tolist())
            if place in seen:
                continue
            seen.add(place)
            corner_at[t] = i
    corners = len(corner_at)
    out = np.vstack([V, P[ok], np.array([corner_pts[i] for i in corner_at.values()]).reshape(-1, 3)])
    corner_vertex = {t: nv + edges + j for j, t in enumerate(corner_at)}

    def d2(a, b):
        return float(((out[a] - out[b]) ** 2).sum())

    tris = []
    for t in range(nt):
        p = F[t].tolist()
        s = [split(t, 0), split(t, 1), split(t, 2)]
        n = sum(1 for x in s if x >= 0)
        if n == 0:
            tris.append(p)
        elif n == 1:
            r = next(i for i in range(3) if s[i] >= 0)
            a, b, c, m = p[r], p[(r + 1) % 3], p[(r + 2) % 3], s[r]
            tris += [[a, m, c], [m, b, c]]
        elif n == 2:
            r = (next(i for i in range(3) if s[i] < 0) + 2) % 3
            a, b, c = p[r], p[(r + 1) % 3], p[(r + 2) % 3]
            sab, sca = s[r], s[(r + 2) % 3]
            tris.append([a, sab, sca])
            if d2(sab, c) <= d2(b, sca):
                tris += [[sab, b, c], [sab, c, sca]]
            else:
                tris += [[sab, b, sca], [b, c, sca]]
        else:
            k = corner_vertex.get(t)
            if k is not None:
                ring = [p[0], s[0], p[1], s[1], p[2], s[2]]
                tris += [[ring[i], ring[(i + 1) % 6], k] for i in range(6)]
            else:
                tris += [[p[0], s[0], s[2]], [s[0], p[1], s[1]], [s[2], s[1], p[2]], [s[0], s[1], s[2]]]
    out_bridge = np.zeros(len(out), dtype=bool)
    out_bridge[:nv] = bridge
    return out, np.array(tris, dtype=np.int64).reshape(-1, 3), out_bridge, edges, corners


def _compact_with_flags(V, F, flags):
    """The mesh on the vertices its triangles use, in the order they first
    come, each with its flag."""
    flat = F.reshape(-1)
    _, first = np.unique(flat, return_index=True)
    order = flat[np.sort(first)]
    remap = np.full(len(V), -1, dtype=np.int64)
    remap[order] = np.arange(len(order))
    return V[order], remap[F], flags[order]


def wrap_mesh(V, F, gap, grow=0.0, edges="sharp", tolerance=None, progress=None):
    """The wrap round the triangles F of V: (V, F, bridge flags, report).
    Raises MeshError when there is nothing to wrap, or the gap is too fine
    for the part's size."""
    say = progress or (lambda text: None)
    if not (gap > 0) or not math.isfinite(gap):
        raise M.MeshError("The gap must be more than zero.")
    if not (grow >= 0) or not math.isfinite(grow):
        raise M.MeshError("Grow by must be zero or more.")
    if grow > gap:
        raise M.MeshError(f"Grow by at most the gap, {fmt(gap):g} mm — or close a larger gap.")
    V = np.asarray(V, dtype=float)
    F = np.asarray(F, dtype=np.int64).reshape(-1, 3)
    if len(F) == 0:
        raise M.MeshError("There is no mesh to wrap.")
    used = V[np.unique(F)]
    lo, hi = used.min(axis=0), used.max(axis=0)
    r = gap / 2

    def size_of(h):
        dmax = max(r / h + FREE_MARGIN, grow / h + REACH_MARGIN)
        pad = math.ceil(dmax) + 3
        return pad, [math.ceil((hi[k] - lo[k]) / h) + 1 + 2 * pad for k in range(3)]

    h = r / CELLS_PER_R
    pad, dims = size_of(h)
    while dims[0] * dims[1] * dims[2] > MAX_GRID_POINTS:
        h *= 1.1
        pad, dims = size_of(h)
    if r / h < MIN_CELLS_PER_R:
        raise M.MeshError(f"The part is too large to close gaps that fine — at its size the smallest gap that can be closed is {fmt(M.round125(2 * MIN_CELLS_PER_R * h)):g} mm.")
    coarsened = h > (r / CELLS_PER_R) * 1.0001
    nx, ny, nz = dims
    o = np.array([lo[k] - (pad + G.JITTER[k]) * h for k in range(3)])

    # ---- 1. the distance to the part -------------------------------------------------
    say("Wrapping — measuring the distance to the part…")
    S = G.spread_points(V, F, h)
    g = np.rint((S - o) / h).astype(np.int64)
    g = g[(g >= 0).all(axis=1) & (g[:, 0] < nx) & (g[:, 1] < ny) & (g[:, 2] < nz)]
    seeds = np.zeros(dims, dtype=bool)
    seeds[g[:, 0], g[:, 1], g[:, 2]] = True
    dist = np.sqrt(G.distance_squared(seeds)) * h
    band = (dist >= r - 2 * h) & (dist <= r + (REACH_MARGIN + 1) * h)
    if band.any():
        idx = np.argwhere(band)
        found, d, _, _ = G.NearSurface(V, F, r + (REACH_MARGIN + 3) * h).nearest(o + idx * h)
        dist[band] = np.where(found, d, dist[band])

    # ---- 2. the outside ----------------------------------------------------------------
    say("Wrapping — finding the outside…")
    free = dist > r
    lab, _ = G.label(free)
    border = np.unique(np.concatenate([lab[0].ravel(), lab[-1].ravel(), lab[:, 0].ravel(), lab[:, -1].ravel(), lab[:, :, 0].ravel(), lab[:, :, -1].ravel()]))
    border = border[border > 0]
    outside = np.isin(lab, border)

    # ---- 3. the field ------------------------------------------------------------------
    say("Wrapping — the field…")
    psi_o = (dist - r) / h
    feet_of = {}
    for ax in range(3):
        for sgn in (1, -1):
            a_sl = [slice(None)] * 3
            b_sl = [slice(None)] * 3
            n = dims[ax]
            if sgn == 1:
                a_sl[ax], b_sl[ax] = slice(0, n - 1), slice(1, n)
            else:
                a_sl[ax], b_sl[ax] = slice(1, n), slice(0, n - 1)
            cross = outside[tuple(a_sl)] & ~outside[tuple(b_sl)]
            ia = np.argwhere(cross)
            if not len(ia):
                continue
            if sgn == -1:
                ia[:, ax] += 1
            ib = ia.copy()
            ib[:, ax] += sgn
            pa = psi_o[ia[:, 0], ia[:, 1], ia[:, 2]]
            pb = psi_o[ib[:, 0], ib[:, 1], ib[:, 2]]
            s = np.clip(pa / np.where(pa - pb > 0, pa - pb, 1), 0, 1)
            foot = ia + s[:, None] * (ib - ia)
            fid = ia[:, 0] + nx * (ia[:, 1] + ny * ia[:, 2])
            feet_of.setdefault("id", []).append(fid)
            feet_of.setdefault("foot", []).append(foot)
    psi = np.where(outside, psi_o, -FAR_OUT)
    if feet_of:
        fid = np.concatenate(feet_of["id"])
        foot = np.vstack(feet_of["foot"])
        order = np.argsort(fid, kind="stable")
        fid, foot = fid[order], foot[order]
        uid, first, cnt = np.unique(fid, return_index=True, return_counts=True)
        width = int(cnt.max())
        table = np.full((len(uid), width, 3), np.nan)
        slot = np.arange(len(fid)) - np.repeat(first, cnt)
        table[np.repeat(np.arange(len(uid)), cnt), slot] = foot
        seed_mask = np.zeros(dims, dtype=bool)
        ui = np.stack([uid % nx, (uid // nx) % ny, uid // (nx * ny)], axis=1)
        seed_mask[ui[:, 0], ui[:, 1], ui[:, 2]] = True
        d2, ix = G.distance_squared(seed_mask, indices=True)
        dmaxF = r / h + REACH_MARGIN
        near = ~outside & (d2 <= (dmaxF + 1.5) ** 2)
        q = np.argwhere(near)
        src = ix[:, q[:, 0], q[:, 1], q[:, 2]].T
        sid = src[:, 0] + nx * (src[:, 1] + ny * src[:, 2])
        row = np.searchsorted(uid, sid)
        d = np.sqrt(np.nanmin(((table[row] - q[:, None, :]) ** 2).sum(axis=2), axis=1))
        psi[near] = np.where(d <= dmaxF, -d, -FAR_OUT)
    lc = (grow - r) / h
    phi = psi - lc

    # ---- 4. the wrap -------------------------------------------------------------------
    say("Wrapping — building the wrap…")
    WV, WF = G.march_cubes(phi, o[0], o[1], o[2], h)
    kept, _, _ = G.drop_specks(WV, WF, MIN_SHELL_CELLS * h ** 3, "out")
    if len(kept) == 0:
        open_ = M.closedness(F, len(V))["open"]
        if open_ > 0 and grow == 0:
            raise M.MeshError(f"Nothing to wrap — the mesh is an open surface ({open_:,} open edges), and an open surface has no inside to wrap at Grow by 0. Grow it by half the thickness it should have.")
        raise M.MeshError(f"Nothing to wrap — nothing of the part is thicker than the grid's cell, {fmt(h):g} mm. Grow it, or close a larger gap.")
    WV, WF = G.compact_mesh(WV, kept)

    # ---- 5. onto the part --------------------------------------------------------------
    say("Wrapping — snapping onto the part…")
    nv = len(WV)
    normals = vertex_normals(WV, WF)
    snapped = np.zeros(nv, dtype=bool)
    target = np.zeros((nv, 3))
    second = np.full((nv, 3), np.nan)
    plane = np.zeros((nv, 3))
    surf = G.NearSurface(V, F, SNAP_REACH * h + grow)
    if grow > 0:
        found, d, foot, _ = surf.nearest(WV)
        ok = found & (d > 0)
        off_part = np.where(ok, d - grow, np.inf)
        u = np.where(ok[:, None], (WV - foot) / np.where(ok, d, 1)[:, None], 0)
        snapped = ok & (np.abs(d - grow) <= SNAP_REACH * h) & (np.abs(np.einsum("ij,ij->i", u, normals)) >= SNAP_COS)
        target = foot + grow * u
    else:
        found, d, _, _ = surf.nearest(WV)
        off_part = np.where(found, d, np.inf)
        f1, d1, p1, t1 = surf.nearest(WV, facing=normals, min_dot=SNAP_COS)
        f2, d2, p2, t2 = surf.nearest(WV, facing=-normals, min_dot=SNAP_COS)
        two = f2 & (~f1 | (d2 < d1))
        face = np.where(two, t2, t1)
        snapped = f1 | f2
        target = np.where(two[:, None], p2, p1)
        sel = np.nonzero(snapped)[0]
        f = face[sel]
        plane[sel] = surf.normal[f]
        _, feat = closest_on_triangles(WV[sel], surf.A[f], surf.B[f], surf.C[f])
        corner = sel[feat != FACE]
        if len(corner):
            tn = plane[corner]
            k = np.einsum("ij,ij->i", WV[corner] - surf.A[face[corner]], tn)
            footp = WV[corner] - k[:, None] * tn
            flat = 0.01 * h
            ff, fd, _, _ = surf.nearest(footp)
            good = ff & (fd <= flat)
            second[corner[good]] = footp[good]
    unfold_snaps(WV, WF, snapped, target, second)
    bridge = ~snapped & (off_part > BRIDGE_CELLS * h)

    sharp_edges = sharp_corners = 0
    if edges == "sharp" and grow == 0:
        say("Wrapping — putting the edges back…")
        plane[~snapped] = 0

        def probe(P):
            ff, fd, _, _ = surf.nearest(P)
            return np.where(ff & (fd <= 0.5 * h), fd, np.inf)

        WV, WF, bridge, sharp_edges, sharp_corners = sharpen(WV, WF, bridge, plane, h, probe)

    OV, OF, flags = _compact_with_flags(WV, WF, bridge.astype(np.uint8))

    # ---- the report --------------------------------------------------------------------
    c = V[F].mean(axis=1)
    gi = np.clip(np.rint((c - o) / h).astype(np.int64), 0, np.array(dims) - 1)
    dropped = int((psi[gi[:, 0], gi[:, 1], gi[:, 2]] < lc - 1.5).sum())
    s = np.linalg.norm(np.cross(OV[OF[:, 1]] - OV[OF[:, 0]], OV[OF[:, 2]] - OV[OF[:, 0]]), axis=1) / 2
    area = float(s.sum())
    bridged = float((s * flags[OF].sum(axis=1) / 3).sum())
    lab_v = M.components(OF, len(OV))
    report = {
        "settings": {"gap": gap, "grow": grow, "edges": edges, **({"tolerance": tolerance} if tolerance is not None else {})},
        "cell": h, "coarsened": coarsened, "fullGap": M.round125(2 * CELLS_PER_R * h) if coarsened else None,
        "shells": int(len(np.unique(lab_v[OF[:, 0]]))), "inputTriangles": int(len(F)), "dropped": dropped,
        "triangles": int(len(OF)), "vertices": int(len(OV)), "area": area, "bridgedArea": bridged,
        "volume": G.signed_volume(OV, OF), "gridPoints": int(nx * ny * nz),
        "sharpEdges": sharp_edges, "sharpCorners": sharp_corners, "reduced": False, "warning": None,
    }
    if grow == 0 and report["volume"] < 0.01 * float(np.prod(hi - lo)):
        open_ = M.closedness(F, len(V))["open"]
        if open_ > 0:
            report["warning"] = (f"Little of the part is left: the mesh is open ({open_:,} open edges), and where an opening is wider than the gap the ball gets behind the surface, which then has no inside. "
                                 "Close a gap wider than the widest opening, or grow it.")
    return OV, OF, flags.astype(bool), report
