# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/core/networkCreases.ts
# SPDX-License-Identifier: AGPL-3.0-only
#
# Suggest creases: the scan's sharp edges and folds, traced and offered as
# crease curves for a patch network.
#
# An edge of the scan is on a crease where the surface turns sharply across
# it. Raw, the angle between an edge's two triangles is mostly noise, so the
# triangles' normals are filtered first, three rounds of a bilateral mean:
# each becomes the mean of the normals of the triangles sharing a corner
# with it, by area, each weighed by a Gaussian in how far it is from its
# own. Noise is averaged away, while across a crease the other side's
# normals are tens of degrees off and weigh next to nothing, so a 90 degree
# edge keeps its 90.
#
# Two angles are read at an edge: its own, between its two triangles'
# filtered normals, and the angle across it a few edges out (across_angle),
# between the mean normals of the triangles 1.5 to 4 edges off it on either
# side. A crease that crosses the triangles slantwise shares its turn out
# between two edges, but across it reads its whole angle; a speck of noise
# turns its own edges and nothing a few edges out.
#
# The candidates are the edges whose own angle is over the weak threshold,
# thinned to one line by non-maximum suppression across the crease. Their
# vertices make pieces, and a piece is kept that holds an edge whose angle
# across is over the strong threshold (hysteresis). Each piece is traced
# into paths, TEASAR's way: from the vertex farthest from the root along the
# tree of shortest ways back to the root or to a path already taken, the
# band round each path covered, until none is left. The ways keep to the
# kept edges, a step off them costing three times its length.
#
# A round is no crease, and its edges can pass the weak threshold; what
# tells it from a crease is where the turn is: a crease puts it on one edge,
# or two slantwise; a round a little on every edge. So along each path the
# share of the angle across that the edge itself turns is read as a running
# median (crease_runs), and the path kept only where it is 0.4 or more. The
# ridges are traced again without the rounds found.
#
# The paths' ends within MERGE_MM are one node; loose ends pointing at each
# other a little farther apart are bridged; two chains through a node no
# other reaches are one; spurs and crumbs go, and a chain shorter than four
# times the scatter-scaled span is dropped. The chains are cut at their
# corners, where they turn 45 degrees or more over 4 mm either side, and a
# closed one with fewer than three into four, so that every curve runs
# between two nodes. A node where chains end is put where they meet carried
# on straight, and taken onto the scan. Each chain is fitted as a network
# curve is, its grips the fitted curve's points each as far on from the last
# as the chord stays within a tenth of an edge of it, never more than 10 mm
# apart. Its angle is the mean angle across it, read along it on the scan.
#
# The region's mesh, its edges and the normal filter are built with numpy in
# the original's order; the tracing is the original's, loop for loop.

import math

import numpy as np

from ._js import js_hypot, js_round
from .network_curve import auto_spans, curve_points, fit_curve, sample_curve
from .network_spline import hypot3_v

STRONG_DEG = 25
WEAK_DEG = 12
MERGE_MM = 2
RANGE = 0.2
ROUNDS = 3
PARALLEL_COS = math.cos((35 * math.pi) / 180)
ACROSS_SKIP = 1.5
ACROSS_REACH = 4
COVER_EDGES = 2
JOIN_EDGES = 2
OFF_RIDGE = 3
SPUR_EDGES = 2
CONCENTRATION = 0.4
CONCENTRATION_WINDOW = 3
TRACE_PASSES = 3
MIN_SPANS = 4
SCATTER_SPAN = 8
SPAN_FLOOR_EDGES = 3
SCATTER_SAMPLES = 4000
BRIDGE_MM = 2 * MERGE_MM
BRIDGE_DEG = 20
CORNER_TURN_DEG = 45
CORNER_REACH = 2 * MERGE_MM
LOOP_PIECES = 4
NODE_FAR = 2 * MERGE_MM
NODE_NEAR = MERGE_MM / 2
NODE_HOLD = 1e-3
GRIP_SAG_EDGES = 0.1
GRIP_SPACING = 10
SAMPLE_EDGES = 0.5
MAX_SAMPLES = 4000
ANGLE_OFFSET_EDGES = 3
ANGLE_RADIUS_EDGES = 1.5
ANGLE_STEP = 2


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def _acos_deg(c):
    return (math.acos(max(-1.0, min(1.0, c))) * 180) / math.pi


class _Heap:
    """The original's binary min-heap of (vertex, distance)."""

    def __init__(self):
        self.ids = []
        self.keys = []

    @property
    def size(self):
        return len(self.ids)

    def push(self, id_, key):
        ids = self.ids
        keys = self.keys
        i = len(ids)
        ids.append(id_)
        keys.append(key)
        while i > 0:
            parent = (i - 1) >> 1
            if keys[parent] <= key:
                break
            ids[i] = ids[parent]
            keys[i] = keys[parent]
            i = parent
        ids[i] = id_
        keys[i] = key

    def pop(self):
        ids = self.ids
        keys = self.keys
        top = (ids[0], keys[0])
        last_id = ids.pop()
        last_key = keys.pop()
        n = len(ids)
        if n > 0:
            i = 0
            while True:
                l = 2 * i + 1
                if l >= n:
                    break
                r = l + 1
                c = r if r < n and keys[r] < keys[l] else l
                if keys[c] >= last_key:
                    break
                ids[i] = ids[c]
                keys[i] = keys[c]
                i = c
            ids[i] = last_id
            keys[i] = last_key
        return top


class _Region:
    """The triangles a suggestion reads, as a mesh of their own with its
    edges: numpy arrays, and plain lists of the ones the loops read."""


def suggest_creases(scan, box=None, strong_deg=None, weak_deg=None):
    """The scan's creases, in `box` ({min, max}) when given:
    {nodes: [{id, at}], curves: [{from, to, via, length, angle, points}]}."""
    strong = STRONG_DEG if strong_deg is None else strong_deg
    weak = min(WEAK_DEG if weak_deg is None else weak_deg, strong)
    r = _region_of(scan, box)
    if r.triangles == 0:
        return {"nodes": [], "curves": []}
    normals = _filtered_normals(r)
    angle = _edge_angles(r, normals)
    kept = _thinned(r, angle, weak)
    min_length = MIN_SPANS * max(SCATTER_SPAN * _scatter_of(r, normals), SPAN_FLOOR_EDGES * scan.edge)
    scratch = {"stamp": [0] * r.triangles, "mark": 0}
    across_of = {}
    nl = normals.reshape(-1).tolist()
    angle_l = angle.tolist()

    def across(e):
        v = across_of.get(e)
        if v is None:
            v = _across_angle(r, nl, e, scan.edge, scratch)
            across_of[e] = v
        return v

    def seed(e):
        return across(e) >= strong

    def share(e):
        return angle_l[e] / max(angle_l[e], across(e))

    off = [0] * r.vertices
    runs = []
    for _ in range(TRACE_PASSES):
        paths = _ridge_paths(r, kept, seed, scan.edge, off)
        runs = _crease_runs(r, paths, kept, share, SPUR_EDGES * scan.edge)
        in_run = set()
        for p in runs:
            in_run.update(p)
        dropped = 0
        for p in paths:
            for v in p:
                if v in in_run or off[v]:
                    continue
                off[v] = 1
                dropped += 1
        if dropped == 0:
            break
    linked = _settle_nodes(scan, _split_chains(_link_chains(r, runs, min_length)), min_length)
    return _curves_of(scan, linked, weak, min_length)


# ---- the region and its edges -------------------------------------------------------------


def _region_of(scan, box):
    F = scan.F
    if box is not None:
        near = scan.triangles_in(box["min"], box["max"])
        c = scan.P[F[near]].sum(axis=1) / 3
        inside = ((c >= np.array(box["min"], dtype=float)) & (c <= np.array(box["max"], dtype=float))).all(axis=1)
        chosen = near[inside]
    else:
        chosen = np.arange(scan.triangle_count)
    r = _Region()
    n = chosen.shape[0]
    r.triangles = n
    flat = F[chosen].reshape(-1)
    if n == 0:
        r.vertices = 0
        return r
    uniq, first = np.unique(flat, return_index=True)
    in_order = uniq[np.argsort(first, kind="stable")]
    local_of = np.full(scan.vertex_count, -1, dtype=np.int64)
    m = in_order.shape[0]
    local_of[in_order] = np.arange(m)
    tri = local_of[flat]
    r.vertices = m
    r.tri = tri
    r.xyz = scan.P[in_order].reshape(-1).copy()
    # The triangles round each vertex.
    vt_order = np.argsort(tri, kind="stable")
    vt_offsets = np.zeros(m + 1, dtype=np.int64)
    np.cumsum(np.bincount(tri, minlength=m), out=vt_offsets[1:])
    r.vt_offsets = vt_offsets
    r.vt_list = vt_order // 3
    # The edges: each triangle side under its lower vertex, the sides under
    # one vertex with the same upper vertex paired; a side shared by more
    # than two triangles each its own, a rim.
    sides = np.arange(n * 3)
    a = tri
    b = tri.reshape(-1, 3)[:, [1, 2, 0]].reshape(-1)
    lo = np.minimum(a, b)
    hi = np.maximum(a, b)
    key = lo * m + hi
    order = np.lexsort((sides, key))
    ks = key[order]
    starts = np.nonzero(np.concatenate(([True], ks[1:] != ks[:-1])))[0]
    sizes = np.diff(np.concatenate((starts, [ks.shape[0]])))
    g_first = order[starts]
    g_lo = lo[g_first]
    g_order = np.lexsort((g_first, g_lo))
    ids_per = np.where(sizes <= 2, 1, sizes)
    g_base = np.zeros(starts.shape[0], dtype=np.int64)
    g_base[g_order] = np.concatenate(([0], np.cumsum(ids_per[g_order])[:-1]))
    edges = int(ids_per.sum())
    group_of = np.repeat(np.arange(starts.shape[0]), sizes)
    rank = np.arange(ks.shape[0]) - starts[group_of]
    side_edge = np.where(sizes[group_of] <= 2, g_base[group_of], g_base[group_of] + rank)
    tri_edge = np.zeros(n * 3, dtype=np.int64)
    tri_edge[order] = side_edge
    ea = np.zeros(edges, dtype=np.int64)
    eb = np.zeros(edges, dtype=np.int64)
    t1 = np.full(edges, -1, dtype=np.int64)
    t2 = np.full(edges, -1, dtype=np.int64)
    side_sorted = order
    first_of_edge = np.ones(ks.shape[0], dtype=bool)
    first_of_edge[1:] = side_edge[1:] != side_edge[:-1]
    e_first = side_edge[first_of_edge]
    s_first = side_sorted[first_of_edge]
    ea[e_first] = lo[s_first]
    eb[e_first] = hi[s_first]
    t1[e_first] = s_first // 3
    pair = np.nonzero(sizes == 2)[0]
    t2[g_base[pair]] = order[starts[pair] + 1] // 3
    r.edges = edges
    r.ea = ea
    r.eb = eb
    r.t1 = t1
    r.t2 = t2
    r.tri_edge = tri_edge
    # The edges round each vertex.
    owner = np.stack([ea, eb], axis=1).reshape(-1)
    eid = np.repeat(np.arange(edges), 2)
    ve_order = np.argsort(owner, kind="stable")
    ve_offsets = np.zeros(m + 1, dtype=np.int64)
    np.cumsum(np.bincount(owner, minlength=m), out=ve_offsets[1:])
    r.ve_offsets = ve_offsets
    r.ve_list = eid[ve_order]
    # Lists for the loops.
    r.L_xyz = r.xyz.tolist()
    r.L_tri = tri.tolist()
    r.L_ea = ea.tolist()
    r.L_eb = eb.tolist()
    r.L_t1 = t1.tolist()
    r.L_t2 = t2.tolist()
    r.L_tri_edge = tri_edge.tolist()
    r.L_ve_offsets = ve_offsets.tolist()
    r.L_ve_list = r.ve_list.tolist()
    return r


# ---- the normals and the angle at each edge -------------------------------------------------


def _filtered_normals(r):
    n = r.triangles
    X = r.xyz.reshape(-1, 3)
    T = r.tri.reshape(-1, 3)
    U = X[T[:, 1]] - X[T[:, 0]]
    V = X[T[:, 2]] - X[T[:, 0]]
    N = np.cross(U, V)
    l = hypot3_v(N[:, 0], N[:, 1], N[:, 2])
    area = l / 2
    cur = np.zeros((n, 3))
    ok = l > 0
    cur[ok] = N[ok] / l[ok, None]
    # Each triangle's ring: the triangles sharing a corner with it, each
    # once, in the original's order (corner by corner).
    corner = r.tri
    owner_tri = np.repeat(np.arange(n), 3)
    cnt = np.diff(r.vt_offsets)[corner]
    rt = np.repeat(owner_tri, cnt)
    pos = np.repeat(r.vt_offsets[corner] - np.concatenate(([0], np.cumsum(cnt)[:-1])), cnt) + np.arange(int(cnt.sum()))
    ru = r.vt_list[pos]
    k = rt * n + ru
    _, first = np.unique(k, return_index=True)
    first.sort()
    rt = rt[first]
    ru = ru[first]
    inv = 1 / (2 * RANGE * RANGE)
    for _ in range(ROUNDS):
        d = 2 - 2 * (cur[rt] * cur[ru]).sum(axis=1)
        w = area[ru] * np.exp(-d * inv)
        S = np.stack([np.bincount(rt, weights=w * cur[ru, c], minlength=n) for c in range(3)], axis=1)
        sl = hypot3_v(S[:, 0], S[:, 1], S[:, 2])
        nxt = cur.copy()
        good = sl > 0
        nxt[good] = S[good] / sl[good, None]
        cur = nxt
    return cur


def _edge_angles(r, normals):
    out = np.zeros(r.edges, dtype=np.float32)
    ok = (r.t1 >= 0) & (r.t2 >= 0)
    a = r.t1[ok]
    b = r.t2[ok]
    c = (normals[a] * normals[b]).sum(axis=1)
    out[ok] = ((np.arccos(np.clip(c, -1, 1)) * 180) / math.pi).astype(np.float32)
    return out.astype(np.float64)


def _thinned(r, angle, weak):
    kept = [0] * r.edges
    xyz = r.L_xyz
    ea, eb, t1, t2, tri_edge = r.L_ea, r.L_eb, r.L_t1, r.L_t2, r.L_tri_edge
    ang = angle.tolist()
    for e in np.nonzero((angle >= weak) & (r.t2 >= 0))[0].tolist():
        s = ang[e]
        near = []
        for t in (t1[e], t2[e]):
            for k in range(3):
                f = tri_edge[t * 3 + k]
                if f == e:
                    continue
                near.append(f)
                u = t2[f] if t1[f] == t else t1[f]
                if u < 0:
                    continue
                for j in range(3):
                    g = tri_edge[u * 3 + j]
                    if g != f:
                        near.append(g)
        a = ea[e] * 3
        b = eb[e] * 3
        dx, dy, dz = xyz[b] - xyz[a], xyz[b + 1] - xyz[a + 1], xyz[b + 2] - xyz[a + 2]
        dl = js_hypot(dx, dy, dz) or 1
        dx /= dl
        dy /= dl
        dz /= dl
        mx, my, mz = (xyz[a] + xyz[b]) / 2, (xyz[a + 1] + xyz[b + 1]) / 2, (xyz[a + 2] + xyz[b + 2]) / 2
        top = True
        for f in near:
            if f == e or ang[f] <= s:
                continue
            p = ea[f] * 3
            q = eb[f] * 3
            fx, fy, fz = xyz[q] - xyz[p], xyz[q + 1] - xyz[p + 1], xyz[q + 2] - xyz[p + 2]
            fl = js_hypot(fx, fy, fz) or 1
            fx /= fl
            fy /= fl
            fz /= fl
            if abs(fx * dx + fy * dy + fz * dz) < PARALLEL_COS:
                continue
            ox = (xyz[p] + xyz[q]) / 2 - mx
            oy = (xyz[p + 1] + xyz[q + 1]) / 2 - my
            oz = (xyz[p + 2] + xyz[q + 2]) / 2 - mz
            along = ox * dx + oy * dy + oz * dz
            off = ox * ox + oy * oy + oz * oz - along * along
            if off > along * along:
                top = False
                break
        if top:
            kept[e] = 1
    return kept


def _scatter_of(r, normals):
    xyz = r.L_xyz
    vo, vl, ea, eb = r.L_ve_offsets, r.L_ve_list, r.L_ea, r.L_eb
    to = r.vt_offsets.tolist()
    tl = r.vt_list.tolist()
    nl = normals.reshape(-1).tolist()
    step = max(1, r.vertices // SCATTER_SAMPLES)
    offsets = []
    for v in range(0, r.vertices, step):
        k = vo[v + 1] - vo[v]
        if k < 3:
            continue
        cx = cy = cz = 0.0
        for i in range(vo[v], vo[v + 1]):
            e = vl[i]
            w = (eb[e] if ea[e] == v else ea[e]) * 3
            cx += xyz[w]
            cy += xyz[w + 1]
            cz += xyz[w + 2]
        nx = ny = nz = 0.0
        for i in range(to[v], to[v + 1]):
            t = tl[i]
            nx += nl[t * 3]
            ny += nl[t * 3 + 1]
            nz += nl[t * 3 + 2]
        n = js_hypot(nx, ny, nz)
        if not n > 0:
            continue
        offsets.append(abs((xyz[v * 3] - cx / k) * nx + (xyz[v * 3 + 1] - cy / k) * ny + (xyz[v * 3 + 2] - cz / k) * nz) / n)
    if not offsets:
        return 0.0
    offsets.sort()
    return offsets[len(offsets) >> 1] / 0.73


# ---- the ridges: the angle across, and the paths -----------------------------------------


def _across_angle(r, normals, e, edge, scratch):
    xyz, tri, ea, eb, t1, t2, tri_edge = r.L_xyz, r.L_tri, r.L_ea, r.L_eb, r.L_t1, r.L_t2, r.L_tri_edge
    a = ea[e] * 3
    b = eb[e] * 3
    dx, dy, dz = xyz[b] - xyz[a], xyz[b + 1] - xyz[a + 1], xyz[b + 2] - xyz[a + 2]
    dl = js_hypot(dx, dy, dz) or 1
    dx /= dl
    dy /= dl
    dz /= dl
    f = t1[e]
    g = t2[e]
    if f < 0 or g < 0:
        return 0.0
    nx = normals[f * 3] + normals[g * 3]
    ny = normals[f * 3 + 1] + normals[g * 3 + 1]
    nz = normals[f * 3 + 2] + normals[g * 3 + 2]
    sx, sy, sz = dy * nz - dz * ny, dz * nx - dx * nz, dx * ny - dy * nx
    sl = js_hypot(sx, sy, sz)
    if not sl > 0:
        return 0.0
    sx /= sl
    sy /= sl
    sz /= sl
    mx, my, mz = (xyz[a] + xyz[b]) / 2, (xyz[a + 1] + xyz[b + 1]) / 2, (xyz[a + 2] + xyz[b + 2]) / 2
    skip = ACROSS_SKIP * edge
    reach = ACROSS_REACH * edge
    side = [0.0] * 6
    scratch["mark"] += 1
    mark = scratch["mark"]
    stamp = scratch["stamp"]
    queue = [f, g]
    stamp[f] = mark
    stamp[g] = mark
    q = 0
    while q < len(queue):
        t = queue[q]
        q += 1
        i, j, k = tri[t * 3] * 3, tri[t * 3 + 1] * 3, tri[t * 3 + 2] * 3
        cx = (xyz[i] + xyz[j] + xyz[k]) / 3 - mx
        cy = (xyz[i + 1] + xyz[j + 1] + xyz[k + 1]) / 3 - my
        cz = (xyz[i + 2] + xyz[j + 2] + xyz[k + 2]) / 3 - mz
        if cx * cx + cy * cy + cz * cz > reach * reach:
            continue
        o_ = cx * sx + cy * sy + cz * sz
        if abs(o_) >= skip:
            o = 0 if o_ > 0 else 3
            side[o] += normals[t * 3]
            side[o + 1] += normals[t * 3 + 1]
            side[o + 2] += normals[t * 3 + 2]
        for nn in range(3):
            h = tri_edge[t * 3 + nn]
            u = t2[h] if t1[h] == t else t1[h]
            if u < 0 or stamp[u] == mark:
                continue
            stamp[u] = mark
            queue.append(u)
    l1 = js_hypot(side[0], side[1], side[2])
    l2 = js_hypot(side[3], side[4], side[5])
    if not (l1 > 0 and l2 > 0):
        return 0.0
    return _acos_deg((side[0] * side[3] + side[1] * side[4] + side[2] * side[5]) / (l1 * l2))


def _ridge_paths(r, kept, seed, edge, off):
    m = r.vertices
    ea, eb, vo, vl, xyz = r.L_ea, r.L_eb, r.L_ve_offsets, r.L_ve_list, r.L_xyz
    cover = COVER_EDGES * edge
    join_reach = cover + JOIN_EDGES * edge
    spur = SPUR_EDGES * edge
    ridge = [0] * m
    for e in range(r.edges):
        if not kept[e]:
            continue
        ridge[ea[e]] = 1
        ridge[eb[e]] = 1
    for v in range(m):
        if off[v]:
            ridge[v] = 0
    piece = [-1] * m
    dist = [0.0] * m
    parent = [0] * m
    seen = [-1] * m
    settled = [-1] * m
    blocked = [-1] * m
    on_path = [-1] * m
    covered = [0] * m
    from_root = [0.0] * m
    up = [0] * m
    state = {"stamp": 0}
    heap = _Heap()

    def step(v, w):
        return js_hypot(xyz[w * 3] - xyz[v * 3], xyz[w * 3 + 1] - xyz[v * 3 + 1], xyz[w * 3 + 2] - xyz[v * 3 + 2])

    def reach(pid, sources, limit, along=False):
        stamp = state["stamp"]
        out = []
        for s in sources:
            dist[s] = 0.0
            parent[s] = -1
            seen[s] = stamp
            heap.push(s, 0.0)
        while heap.size > 0:
            v, d = heap.pop()
            if settled[v] == stamp or d > dist[v]:
                continue
            settled[v] = stamp
            out.append(v)
            for i in range(vo[v], vo[v + 1]):
                e = vl[i]
                w = eb[e] if ea[e] == v else ea[e]
                if piece[w] != pid or settled[w] == stamp or blocked[w] == stamp:
                    continue
                nd = d + (OFF_RIDGE if along and not kept[e] else 1) * step(v, w)
                if nd > limit:
                    continue
                if seen[w] != stamp or nd < dist[w]:
                    seen[w] = stamp
                    dist[w] = nd
                    parent[w] = v
                    heap.push(w, nd)
        return out

    paths = []
    pieces = 0
    for v0 in range(m):
        if not ridge[v0] or piece[v0] >= 0:
            continue
        pid = pieces
        pieces += 1
        members = [v0]
        edges = []
        piece[v0] = pid
        q = 0
        while q < len(members):
            v = members[q]
            q += 1
            for i in range(vo[v], vo[v + 1]):
                e = vl[i]
                w = eb[e] if ea[e] == v else ea[e]
                if kept[e] and ea[e] == v:
                    edges.append(e)
                if ridge[w] and piece[w] < 0:
                    piece[w] = pid
                    members.append(w)
        if len(members) < 2 or not any(seed(e) for e in edges):
            continue
        state["stamp"] += 1
        order = reach(pid, [v0], math.inf, True)
        root = v0
        for v in order:
            if dist[v] > dist[root]:
                root = v
        state["stamp"] += 1
        order = reach(pid, [root], math.inf, True)
        for v in order:
            from_root[v] = dist[v]
            up[v] = parent[v]
        while True:
            tip = -1
            far = -1.0
            for v in order:
                if covered[v]:
                    continue
                if from_root[v] > far:
                    far, tip = from_root[v], v
            if tip < 0:
                break
            path = [tip]
            v = tip
            length = 0.0
            while on_path[v] < 0 and v != root:
                w = up[v]
                if w < 0:
                    break
                length += step(v, w)
                v = w
                path.append(v)
            state["stamp"] += 1
            for i in range(1, len(path)):
                blocked[path[i]] = state["stamp"]
            end = path[-1]
            near = next((u for u in reach(pid, [tip], join_reach) if on_path[u] >= 0 and u != end), None)
            if near is not None:
                lead = []
                u = near
                while u != tip:
                    lead.append(u)
                    u = parent[u]
                for i in range(len(lead)):
                    length += step(lead[i], lead[i + 1] if i + 1 < len(lead) else tip)
                path = lead + path
            state["stamp"] += 1
            for u in reach(pid, path, cover):
                covered[u] = 1
            for u in path:
                covered[u] = 1
            if length < spur:
                continue
            for u in path:
                if on_path[u] < 0:
                    on_path[u] = len(paths)
            paths.append(path)
    return _split_at_joins(paths, on_path)


def _split_at_joins(paths, on_path):
    cuts = [set() for _ in paths]
    for p, path in enumerate(paths):
        for end in (path[0], path[-1]):
            q = on_path[end]
            if q < 0 or q == p:
                continue
            at = paths[q].index(end)
            if 0 < at < len(paths[q]) - 1:
                cuts[q].add(at)
    out = []
    for p, path in enumerate(paths):
        frm = 0
        for c in sorted(cuts[p]):
            out.append(path[frm:c + 1])
            frm = c
        out.append(path[frm:])
    return out


def _crease_runs(r, paths, kept, share, spur):
    xyz, vo, vl, ea, eb = r.L_xyz, r.L_ve_offsets, r.L_ve_list, r.L_ea, r.L_eb
    out = []
    for p in paths:
        steps = len(p) - 1
        ratio = [math.nan] * steps
        for i in range(steps):
            u = p[i]
            v = p[i + 1]
            for k in range(vo[u], vo[u + 1]):
                e = vl[k]
                if (ea[e] == v or eb[e] == v) and kept[e]:
                    ratio[i] = share(e)
        good = [0] * steps
        for i in range(steps):
            near = [ratio[j] for j in range(max(0, i - CONCENTRATION_WINDOW), min(steps - 1, i + CONCENTRATION_WINDOW) + 1) if ratio[j] == ratio[j]]
            if not near:
                continue
            near.sort()
            good[i] = 1 if near[len(near) >> 1] >= CONCENTRATION else 0
        i = 0
        while i < steps:
            if not good[i]:
                i += 1
                continue
            j = i
            length = 0.0
            while j < steps and good[j]:
                a = p[j] * 3
                b = p[j + 1] * 3
                length += js_hypot(xyz[b] - xyz[a], xyz[b + 1] - xyz[a + 1], xyz[b + 2] - xyz[a + 2])
                j += 1
            if length >= spur:
                out.append(p[i:j + 1])
            i = j
    return out


# ---- chains between nodes -------------------------------------------------------------------


def _polyline_length(pts):
    l = 0.0
    for i in range(3, len(pts), 3):
        l += js_hypot(pts[i] - pts[i - 3], pts[i + 1] - pts[i - 2], pts[i + 2] - pts[i - 1])
    return l


def _reversed(pts):
    out = []
    for i in range(len(pts) - 3, -1, -3):
        out.extend((pts[i], pts[i + 1], pts[i + 2]))
    return out


def _point_along(pts, t):
    left = t
    for i in range(3, len(pts), 3):
        l = js_hypot(pts[i] - pts[i - 3], pts[i + 1] - pts[i - 2], pts[i + 2] - pts[i - 1])
        if l >= left and l > 0:
            f = left / l
            return [pts[i - 3] + f * (pts[i] - pts[i - 3]), pts[i - 2] + f * (pts[i + 1] - pts[i - 2]), pts[i - 1] + f * (pts[i + 2] - pts[i - 1])]
        left -= l
    return [pts[-3], pts[-2], pts[-1]]


def _bridge(nodes, chains, min_length):
    valence = [0] * len(nodes)
    for c in chains:
        valence[c["from"]] += 1
        valence[c["to"]] += 1
    loose = []
    for i, c in enumerate(chains):
        length = _polyline_length(c["pts"])
        for end in (0, 1):
            node = c["from"] if end == 0 else c["to"]
            if valence[node] != 1:
                continue
            pts = c["pts"] if end == 0 else _reversed(c["pts"])
            at = [pts[0], pts[1], pts[2]]
            back = _point_along(pts, min(NODE_FAR, 0.5 * length))
            u = [at[0] - back[0], at[1] - back[1], at[2] - back[2]]
            l = js_hypot(*u)
            if l > 0:
                loose.append({"node": node, "chain": i, "at": at, "out": [u[0] / l, u[1] / l, u[2] / l]})
    cos = math.cos((BRIDGE_DEG * math.pi) / 180)
    pairs = []
    for i in range(len(loose)):
        for j in range(i + 1, len(loose)):
            a = loose[i]
            b = loose[j]
            if a["chain"] == b["chain"] and _polyline_length(chains[a["chain"]]["pts"]) < min_length:
                continue
            g = [b["at"][0] - a["at"][0], b["at"][1] - a["at"][1], b["at"][2] - a["at"][2]]
            d = js_hypot(*g)
            if d > BRIDGE_MM:
                continue
            along = (a["out"][0] * g[0] + a["out"][1] * g[1] + a["out"][2] * g[2]) / d if d > 0 else 1
            back = -(b["out"][0] * g[0] + b["out"][1] * g[1] + b["out"][2] * g[2]) / d if d > 0 else 1
            facing = -(a["out"][0] * b["out"][0] + a["out"][1] * b["out"][1] + a["out"][2] * b["out"][2])
            if along >= cos and back >= cos and facing >= cos:
                pairs.append((d, i, j))
    pairs.sort(key=lambda x: x[0])
    done = [0] * len(loose)
    for _, i, j in pairs:
        if done[i] or done[j]:
            continue
        done[i] = done[j] = 1
        a = loose[i]
        b = loose[j]
        nodes[a["node"]] = [(a["at"][0] + b["at"][0]) / 2, (a["at"][1] + b["at"][1]) / 2, (a["at"][2] + b["at"][2]) / 2]
        for c in chains:
            if c["from"] == b["node"]:
                c["from"] = a["node"]
            if c["to"] == b["node"]:
                c["to"] = a["node"]


def _clusters(at, apart):
    n = len(at)
    order = sorted(range(n), key=lambda i: at[i][0])

    def d(i, j):
        return js_hypot(at[i][0] - at[j][0], at[i][1] - at[j][1], at[i][2] - at[j][2])

    pairs = []
    for a in range(n):
        b = a + 1
        while b < n and at[order[b]][0] - at[order[a]][0] < MERGE_MM:
            dist = d(order[a], order[b])
            if dist < MERGE_MM:
                pairs.append((dist, order[a], order[b]))
            b += 1
    pairs.sort(key=lambda x: x[0])
    of = list(range(n))
    members = [[i] for i in range(n)]
    for _, i, j in pairs:
        a = of[i]
        b = of[j]
        if a == b:
            continue
        if any(apart(p, q) or d(p, q) >= MERGE_MM for p in members[a] for q in members[b]):
            continue
        for q in members[b]:
            of[q] = a
        members[a].extend(members[b])
        members[b] = []
    return of


def _joined_through(nodes, chains):
    live = list(chains)
    at = [[] for _ in nodes]
    for i, c in enumerate(live):
        at[c["from"]].append(i)
        at[c["to"]].append(i)
    for n in range(len(nodes)):
        if len(at[n]) != 2 or at[n][0] == at[n][1]:
            continue
        ia, ib = at[n]
        a = live[ia]
        b = live[ib]
        into = a["pts"] if a["to"] == n else _reversed(a["pts"])
        out = b["pts"] if b["from"] == n else _reversed(b["pts"])
        c = {"pts": into[:-3] + list(nodes[n]) + out[3:], "from": a["from"] if a["to"] == n else a["to"], "to": b["to"] if b["from"] == n else b["from"]}
        live[ia] = live[ib] = None
        ic = len(live)
        live.append(c)
        at[n] = []
        for end in dict.fromkeys((c["from"], c["to"])):
            at[end] = [ic if i in (ia, ib) else i for i in at[end]]
    return [c for c in live if c is not None]


def _link_chains(r, paths, min_length):
    xyz = r.L_xyz if r.triangles else []
    ends = []
    for p in paths:
        for v in (p[0], p[-1]):
            ends.append([xyz[v * 3], xyz[v * 3 + 1], xyz[v * 3 + 2]])
    group_of = _clusters(ends, lambda i, j: i >> 1 == j >> 1)
    node_of = {}
    sums = []
    end_node = []
    for i, e in enumerate(ends):
        root = group_of[i]
        n = node_of.get(root)
        if n is None:
            n = len(sums)
            node_of[root] = n
            sums.append([0.0, 0.0, 0.0, 0])
        sums[n][0] += e[0]
        sums[n][1] += e[1]
        sums[n][2] += e[2]
        sums[n][3] += 1
        end_node.append(n)
    nodes = [[s[0] / s[3], s[1] / s[3], s[2] / s[3]] for s in sums]
    chains = []
    for i, p in enumerate(paths):
        pts = []
        for v in p:
            pts.extend((xyz[v * 3], xyz[v * 3 + 1], xyz[v * 3 + 2]))
        chains.append({"pts": pts, "from": end_node[i * 2], "to": end_node[i * 2 + 1]})
    _bridge(nodes, chains, min_length)
    while True:
        chains = _joined_through(nodes, chains)
        valence = [0] * len(nodes)
        for c in chains:
            valence[c["from"]] += 1
            valence[c["to"]] += 1
        before = len(chains)
        chains = [c for c in chains if not (_polyline_length(c["pts"]) < min_length and (valence[c["from"]] == 1 or valence[c["to"]] == 1 or c["from"] == c["to"]))]
        if len(chains) == before:
            break
    for c in chains:
        c["pts"][0:3] = nodes[c["from"]]
        c["pts"][-3:] = nodes[c["to"]]
    return {"nodes": nodes, "chains": chains, "cut": set()}


def _split_chains(linked):
    nodes = list(linked["nodes"])
    cut = set(linked["cut"])
    valence = [0] * len(nodes)
    for c in linked["chains"]:
        valence[c["from"]] += 1
        valence[c["to"]] += 1
    chains = []
    for c in linked["chains"]:
        closed = c["from"] == c["to"]
        pts = c["pts"]
        n = len(pts) // 3
        s = [0.0] * n
        for i in range(1, n):
            s[i] = s[i - 1] + js_hypot(pts[i * 3] - pts[i * 3 - 3], pts[i * 3 + 1] - pts[i * 3 - 2], pts[i * 3 + 2] - pts[i * 3 - 1])
        total = s[n - 1] if n else 0.0
        if n < 3 or total <= 0:
            chains.append(c)
            continue

        def point_at(t, pts=pts, s=s, n=n, total=total, closed=closed):
            if closed:
                t = ((t % total) + total) % total
            elif t < 0 or t > total:
                return None
            lo = 0
            hi = n - 1
            while hi - lo > 1:
                mid = (lo + hi) >> 1
                if s[mid] <= t:
                    lo = mid
                else:
                    hi = mid
            f = (t - s[lo]) / (s[hi] - s[lo]) if s[hi] > s[lo] else 0
            return [pts[lo * 3 + k] + f * (pts[hi * 3 + k] - pts[lo * 3 + k]) for k in range(3)]

        turn = [0.0] * n
        last = n - 1 if closed else n
        for i in range(last):
            b = point_at(s[i] - CORNER_REACH)
            f = point_at(s[i] + CORNER_REACH)
            if b is None or f is None:
                continue
            p = pts[i * 3:i * 3 + 3]
            u = [p[0] - b[0], p[1] - b[1], p[2] - b[2]]
            w = [f[0] - p[0], f[1] - p[1], f[2] - p[2]]
            l = js_hypot(*u) * js_hypot(*w)
            if l > 0:
                turn[i] = _acos_deg((u[0] * w[0] + u[1] * w[1] + u[2] * w[2]) / l)

        def apart(i, j, s=s, total=total, closed=closed):
            d = abs(s[i] - s[j])
            return min(d, total - d) if closed else d

        cuts = []
        if closed and valence[c["from"]] > 2:
            cuts.append(0)
        order = sorted([i for i in range(last) if turn[i] >= CORNER_TURN_DEG], key=lambda i: -turn[i])
        for i in order:
            if all(apart(i, j) >= 2 * CORNER_REACH for j in cuts):
                cuts.append(i)
        if closed and len(cuts) < 3:
            if not cuts:
                best = 0
                for i in range(1, last):
                    if turn[i] > turn[best]:
                        best = i
                cuts.append(best)
            while len(cuts) < LOOP_PIECES:
                cuts.sort(key=lambda i: s[i])
                gap = -1.0
                at = 0
                for k in range(len(cuts)):
                    a = s[cuts[k]]
                    b = s[cuts[k + 1]] if k + 1 < len(cuts) else s[cuts[0]] + total
                    if b - a > gap:
                        gap, at = b - a, k
                mid = math.fmod(s[cuts[at]] + gap / 2, total)
                best = 0
                for i in range(last):
                    if abs(s[i] - mid) < abs(s[best] - mid):
                        best = i
                if best in cuts:
                    break
                cuts.append(best)
        cuts.sort(key=lambda i: s[i])
        if not cuts:
            chains.append(c)
            continue
        node_at = []
        for i in cuts:
            if closed and i == 0 and valence[c["from"]] > 2:
                node_at.append(c["from"])
                continue
            nodes.append([pts[i * 3], pts[i * 3 + 1], pts[i * 3 + 2]])
            cut.add(len(nodes) - 1)
            node_at.append(len(nodes) - 1)

        def piece(i, j, pts=pts, n=n):
            if j > i:
                return pts[i * 3:j * 3 + 3]
            return pts[i * 3:(n - 1) * 3] + pts[0:j * 3 + 3]

        if closed:
            for k in range(len(cuts)):
                i = cuts[k]
                j = cuts[(k + 1) % len(cuts)]
                chains.append({"pts": piece(i, j), "from": node_at[k], "to": node_at[(k + 1) % len(cuts)]})
        else:
            at = [0, *cuts, n - 1]
            ids = [c["from"], *node_at, c["to"]]
            for k in range(len(at) - 1):
                chains.append({"pts": pts[at[k] * 3:at[k + 1] * 3 + 3], "from": ids[k], "to": ids[k + 1]})
    return {"nodes": nodes, "chains": chains, "cut": cut}


def _solve3(m, b):
    det = m[0] * (m[4] * m[8] - m[5] * m[7]) - m[1] * (m[3] * m[8] - m[5] * m[6]) + m[2] * (m[3] * m[7] - m[4] * m[6])
    if not abs(det) > 1e-12:
        return None
    x = (b[0] * (m[4] * m[8] - m[5] * m[7]) - m[1] * (b[1] * m[8] - m[5] * b[2]) + m[2] * (b[1] * m[7] - m[4] * b[2])) / det
    y = (m[0] * (b[1] * m[8] - m[5] * b[2]) - b[0] * (m[3] * m[8] - m[5] * m[6]) + m[2] * (m[3] * b[2] - b[1] * m[6])) / det
    z = (m[0] * (m[4] * b[2] - b[1] * m[7]) - m[1] * (m[3] * b[2] - b[1] * m[6]) + b[0] * (m[3] * m[7] - m[4] * m[6])) / det
    return [x, y, z]


def _settle_nodes(scan, linked, min_length):
    n = len(linked["nodes"])
    used = [0] * n
    for c in linked["chains"]:
        used[c["from"]] = 1
        used[c["to"]] = 1
    long_ = set()
    for c in linked["chains"]:
        if _polyline_length(c["pts"]) >= min_length:
            long_.add(min(c["from"], c["to"]) * n + max(c["from"], c["to"]))
    ids = [i for i in range(n) if used[i]]
    group_of = _clusters([linked["nodes"][i] for i in ids], lambda a, b: (min(ids[a], ids[b]) * n + max(ids[a], ids[b])) in long_)
    position = [0] * n
    for k, i in enumerate(ids):
        position[i] = k

    def find(i):
        return ids[group_of[position[i]]]

    sums = [[0.0, 0.0, 0.0, 0] for _ in linked["nodes"]]
    for i in range(n):
        if not used[i]:
            continue
        r = find(i)
        for k in range(3):
            sums[r][k] += linked["nodes"][i][k]
        sums[r][3] += 1
    nodes = [[v[0] / v[3], v[1] / v[3], v[2] / v[3]] if v[3] > 0 else linked["nodes"][i] for i, v in enumerate(sums)]
    ended = set()
    for i in ids:
        if i not in linked["cut"]:
            ended.add(find(i))
    chains = [{"pts": c["pts"], "from": find(c["from"]), "to": find(c["to"])} for c in linked["chains"]]
    chains = [c for c in chains if not (c["from"] == c["to"] and _polyline_length(c["pts"]) < min_length)]
    lines = {}
    for c in chains:
        length = _polyline_length(c["pts"])
        for end in (0, 1):
            pts = c["pts"] if end == 0 else _reversed(c["pts"])
            far = _point_along(pts, min(NODE_FAR, 0.5 * length))
            near = _point_along(pts, min(NODE_NEAR, 0.15 * length))
            u = [near[0] - far[0], near[1] - far[1], near[2] - far[2]]
            l = js_hypot(*u)
            if not l > 0:
                continue
            node = c["from"] if end == 0 else c["to"]
            lines.setdefault(node, []).append({"p": far, "u": [u[0] / l, u[1] / l, u[2] / l]})
    for node, lst in lines.items():
        if len(lst) < 2 or (len(lst) < 3 and node not in ended):
            continue
        x0 = nodes[node]
        m = [0.0] * 9
        b = [0.0] * 3
        hold = NODE_HOLD * len(lst)
        for i in range(3):
            m[i * 4] += hold
            b[i] += hold * x0[i]
        for ln in lst:
            p, u = ln["p"], ln["u"]
            for i in range(3):
                for j in range(3):
                    a = (1 if i == j else 0) - u[i] * u[j]
                    m[i * 3 + j] += a
                    b[i] += a * p[j]
        x = _solve3(m, b)
        if x is not None and js_hypot(x[0] - x0[0], x[1] - x0[1], x[2] - x0[2]) < MERGE_MM:
            nodes[node] = x
    for node in lines:
        c = scan.closest(nodes[node])
        if c is not None:
            nodes[node] = c.point
    for c in chains:
        c["pts"] = list(c["pts"])
        c["pts"][0:3] = nodes[c["from"]]
        c["pts"][-3:] = nodes[c["to"]]
    return {"nodes": nodes, "chains": chains, "cut": set()}


# ---- the curves -----------------------------------------------------------------------------


def _curves_of(scan, linked, weak, min_length):
    fitted = []
    for c in linked["chains"]:
        count = len(c["pts"]) // 3
        if count < 2:
            continue
        trace = curve_points(c["pts"])
        if not trace["length"] > 0:
            continue
        fit = fit_curve(trace, auto_spans(trace))
        samples = max(8, min(MAX_SAMPLES, math.ceil(trace["length"] / (SAMPLE_EDGES * scan.edge)) + 1))
        line = sample_curve(fit, samples)
        L = line.reshape(-1, 3)
        s = np.zeros(samples)
        dd = np.diff(L, axis=0)
        s[1:] = np.cumsum(hypot3_v(dd[:, 0], dd[:, 1], dd[:, 2]))
        angle = _angle_along(scan, line, s)
        if angle >= weak:
            fitted.append({"from": c["from"], "to": c["to"], "line": line, "s": s, "angle": angle})
    group = list(range(len(linked["nodes"])))

    def root(i):
        while group[i] != i:
            group[i] = group[group[i]]
            i = group[i]
        return i

    for f in fitted:
        group[root(f["from"])] = root(f["to"])
    total = [0.0] * len(linked["nodes"])
    for f in fitted:
        total[root(f["from"])] += float(f["s"][-1])
    ids = {}
    nodes = []

    def id_of(n):
        i = ids.get(n)
        if i is None:
            i = len(nodes) + 1
            ids[n] = i
            nodes.append({"id": i, "at": linked["nodes"][n]})
        return i

    curves = []
    for f in fitted:
        if total[root(f["from"])] < min_length:
            continue
        line = f["line"]
        via = []
        for i in _grips_of(line, f["s"], GRIP_SAG_EDGES * scan.edge):
            p = [float(line[i * 3]), float(line[i * 3 + 1]), float(line[i * 3 + 2])]
            c = scan.closest(p)
            via.append(c.point if c is not None else p)
        curves.append({"from": id_of(f["from"]), "to": id_of(f["to"]), "via": via, "length": float(f["s"][-1]), "angle": f["angle"], "points": line.astype(np.float32)})
    return {"nodes": nodes, "curves": curves}


def _grips_of(line, s, sag):
    n = s.shape[0]
    L = line.reshape(-1, 3)
    out = []
    i = 0
    while i < n - 1:
        j = i + 1
        while j + 1 < n and s[j + 1] - s[i] <= GRIP_SPACING and _chord_holds(L, i, j + 1, sag):
            j += 1
        if j >= n - 1:
            break
        out.append(j)
        i = j
    return out


def _chord_holds(L, i, j, sag):
    a = L[i]
    d = L[j] - a
    dd = float(d @ d)
    if j - i < 2:
        return True
    P = L[i + 1:j] - a
    t = np.clip((P @ d) / dd, 0, 1) if dd > 0 else np.zeros(P.shape[0])
    Q = P - t[:, None] * d
    return not (hypot3_v(Q[:, 0], Q[:, 1], Q[:, 2]) > sag).any()


def _angle_along(scan, line, s):
    n = s.shape[0]
    total = float(s[n - 1])
    off = ANGLE_OFFSET_EDGES * scan.edge
    radius = ANGLE_RADIUS_EDGES * scan.edge
    acc = 0.0
    count = 0
    margin = min(off, total / 4)
    steps = max(2, int(js_round(total / ANGLE_STEP)))
    k = 0
    for step in range(steps + 1):
        want = (total * step) / steps
        if want < margin or want > total - margin:
            continue
        while k + 1 < n and s[k + 1] <= want:
            k += 1
        a = max(0, k - 1)
        b = min(n - 1, k + 1)
        p = [float(line[k * 3]), float(line[k * 3 + 1]), float(line[k * 3 + 2])]
        t = [float(line[b * 3] - line[a * 3]), float(line[b * 3 + 1] - line[a * 3 + 1]), float(line[b * 3 + 2] - line[a * 3 + 2])]
        c = scan.closest(p)
        if c is None:
            continue
        normal = scan.normal_at(c.point, c.triangle)
        across = _cross(t, normal)
        al = js_hypot(*across)
        if not al > 0:
            continue
        one = _normal_near(scan, [p[i] + (across[i] / al) * off for i in range(3)], radius)
        two = _normal_near(scan, [p[i] - (across[i] / al) * off for i in range(3)], radius)
        if one is None or two is None:
            continue
        acc += _acos_deg(one[0] * two[0] + one[1] * two[1] + one[2] * two[2])
        count += 1
    return acc / count if count > 0 else 0.0


def _normal_near(scan, q, radius):
    c = scan.closest(q)
    if c is None:
        return None
    p = c.point
    ts = scan.triangles_in([p[0] - radius, p[1] - radius, p[2] - radius], [p[0] + radius, p[1] + radius, p[2] + radius])
    total = [0.0, 0.0, 0.0]
    if ts.size:
        _, d = scan._closest_among(ts, p)
        ts = ts[~(d > radius)]
        if ts.size:
            F = scan.F[ts]
            A = scan.P[F[:, 0]]
            W = np.cross(scan.P[F[:, 1]] - A, scan.P[F[:, 2]] - A)
            total = [float(x) for x in np.cumsum(W, axis=0)[-1]]
    l = js_hypot(*total)
    return [total[0] / l, total[1] / l, total[2] / l] if l > 0 else c.normal
