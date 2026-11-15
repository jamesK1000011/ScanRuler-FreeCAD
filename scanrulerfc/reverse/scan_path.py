# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): src/core/geometry/scanPath.ts, adjacency.ts (what plugins/reverse/core/network*.ts trace along)
# SPDX-License-Identifier: AGPL-3.0-only
#
# A path along the scan's surface between two points on it.
#
# The path is a plane section: the plane through the two points that holds
# the scan's mean normal there, cut through the triangles in a tube round
# the segment between them, and of the section's chains the piece that runs
# from the one point to the other. On a smooth surface that is the curve a
# person means by "from here to there along the part": a straight line on a
# plane, an arc of a circle across a cylinder, a great circle on a sphere.
# Each point of the section lies on a triangle edge, and the path says
# which, so what is on either side of it can be told by the triangles.
#
# Where the section does not join the two points (a hole in the scan
# between them, a fold the plane leaves by another sheet) the path falls
# back to the shortest way along the mesh's edges (A*, the edges' lengths
# their weights), which goes round a hole rather than across it.
#
# The scan is prepared once (ScanPaths): its triangles in a grid by place,
# for the tube and the nearest point; the vertices' adjacency and which of
# them are joined at all, made the first time they are needed. The grid is
# built with numpy; the original's cell walk for the triangles a plane
# crosses gives the triangles of the box the plane crosses in the box's
# order, which is what triangles_crossing gives here, read off the box at
# once. A path is a dict with the original's fields; its points are
# float32, as the original's Float32Array.

import math

import numpy as np

from ._js import js_hypot

PER_CELL = 2
MAX_CELLS = 2_000_000
TUBE_SHARE = 0.75
TUBE_EDGES = 3
NORMAL_EDGES = 3
END_SLACK_EDGES = 0.5


def _f32(x):
    return float(np.float32(x))


class ScanPoint:
    """The nearest point of the scan to a point: where, in which triangle,
    the triangle's own normal and how far."""

    __slots__ = ("point", "triangle", "normal", "distance")

    def __init__(self, point, triangle, normal, distance):
        self.point = point
        self.triangle = triangle
        self.normal = normal
        self.distance = distance


def build_adjacency(F, vertex_count):
    """Vertex-to-vertex adjacency in CSR form (offsets, flat neighbour list),
    a neighbour once per shared triangle, in the original's order."""
    F = np.asarray(F, dtype=np.int64).reshape(-1, 3)
    a, b, c = F[:, 0], F[:, 1], F[:, 2]
    owner = np.stack([a, a, b, b, c, c], axis=1).ravel()
    nbr = np.stack([b, c, a, c, a, b], axis=1).ravel()
    order = np.argsort(owner, kind="stable")
    counts = np.bincount(owner, minlength=vertex_count)
    offsets = np.zeros(vertex_count + 1, dtype=np.int64)
    np.cumsum(counts, out=offsets[1:])
    return offsets, nbr[order]


def closest_on_triangles(p, A, B, C):
    """The nearest point of each triangle (A[i], B[i], C[i]) to p (Ericson,
    Real-Time Collision Detection 5.1.5), vectorised: (N, 3)."""
    p = np.asarray(p, dtype=float)
    ab = B - A
    ac = C - A
    ap = p - A
    d1 = (ab * ap).sum(axis=1)
    d2 = (ac * ap).sum(axis=1)
    n = A.shape[0]
    out = np.empty((n, 3))
    done = np.zeros(n, dtype=bool)

    def put(mask, val):
        m = mask & ~done
        if m.any():
            out[m] = val[m] if val.ndim == 2 else val
            done[m] = True

    put((d1 <= 0) & (d2 <= 0), A)
    bp = p - B
    d3 = (ab * bp).sum(axis=1)
    d4 = (ac * bp).sum(axis=1)
    put((d3 >= 0) & (d4 <= d3), B)
    vc = d1 * d4 - d3 * d2
    with np.errstate(divide="ignore", invalid="ignore"):
        m = (vc <= 0) & (d1 >= 0) & (d3 <= 0)
        v = d1 / (d1 - d3)
        put(m, A + v[:, None] * ab)
        cp = p - C
        d5 = (ab * cp).sum(axis=1)
        d6 = (ac * cp).sum(axis=1)
        put((d6 >= 0) & (d5 <= d6), C)
        vb = d5 * d2 - d1 * d6
        m = (vb <= 0) & (d2 >= 0) & (d6 <= 0)
        w = d2 / (d2 - d6)
        put(m, A + w[:, None] * ac)
        va = d3 * d6 - d5 * d4
        m = (va <= 0) & (d4 - d3 >= 0) & (d5 - d6 >= 0)
        w = (d4 - d3) / (d4 - d3 + (d5 - d6))
        put(m, B + w[:, None] * (C - B))
        denom = 1 / (va + vb + vc)
        v = vb * denom
        w = vc * denom
        put(np.ones(n, dtype=bool), A + ab * v[:, None] + ac * w[:, None])
    return out


def _closest_on_triangle(p, ax, ay, az, bx, by, bz, cx, cy, cz):
    abx, aby, abz = bx - ax, by - ay, bz - az
    acx, acy, acz = cx - ax, cy - ay, cz - az
    apx, apy, apz = p[0] - ax, p[1] - ay, p[2] - az
    d1 = abx * apx + aby * apy + abz * apz
    d2 = acx * apx + acy * apy + acz * apz
    if d1 <= 0 and d2 <= 0:
        return [ax, ay, az]
    bpx, bpy, bpz = p[0] - bx, p[1] - by, p[2] - bz
    d3 = abx * bpx + aby * bpy + abz * bpz
    d4 = acx * bpx + acy * bpy + acz * bpz
    if d3 >= 0 and d4 <= d3:
        return [bx, by, bz]
    vc = d1 * d4 - d3 * d2
    if vc <= 0 and d1 >= 0 and d3 <= 0:
        v = d1 / (d1 - d3)
        return [ax + v * abx, ay + v * aby, az + v * abz]
    cpx, cpy, cpz = p[0] - cx, p[1] - cy, p[2] - cz
    d5 = abx * cpx + aby * cpy + abz * cpz
    d6 = acx * cpx + acy * cpy + acz * cpz
    if d6 >= 0 and d5 <= d6:
        return [cx, cy, cz]
    vb = d5 * d2 - d1 * d6
    if vb <= 0 and d2 >= 0 and d6 <= 0:
        w = d2 / (d2 - d6)
        return [ax + w * acx, ay + w * acy, az + w * acz]
    va = d3 * d6 - d5 * d4
    if va <= 0 and d4 - d3 >= 0 and d5 - d6 >= 0:
        w = (d4 - d3) / (d4 - d3 + (d5 - d6))
        return [bx + w * (cx - bx), by + w * (cy - by), bz + w * (cz - bz)]
    denom = 1 / (va + vb + vc)
    v = vb * denom
    w = vc * denom
    return [ax + abx * v + acx * w, ay + aby * v + acy * w, az + abz * v + acz * w]


class _Heap:
    """The original's binary min-heap of (vertex, key), for its tie order."""

    def __init__(self):
        self.ids = []
        self.keys = []

    @property
    def size(self):
        return len(self.ids)

    def clear(self):
        self.ids.clear()
        self.keys.clear()

    def push(self, id_, key):
        ids = self.ids
        keys = self.keys
        ids.append(id_)
        keys.append(key)
        i = len(ids) - 1
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
        top = ids[0]
        top_key = keys[0]
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
        return top, top_key


class ScanPaths:
    """A scan prepared for paths: see above. `positions` x, y, z per vertex
    (float32, as the original's), `indices` three per triangle."""

    def __init__(self, positions, indices):
        P32 = np.asarray(positions, dtype=np.float32).reshape(-1, 3)
        self.positions32 = P32.reshape(-1)
        self.P = P32.astype(np.float64)
        self.positions = self.P.reshape(-1).tolist()
        self.F = np.asarray(indices, dtype=np.int64).reshape(-1, 3)
        self.indices = self.F.reshape(-1).tolist()
        self.triangle_count = int(self.F.shape[0])
        self.vertex_count = int(self.P.shape[0])
        p = self.positions
        idx = self.indices
        if self.vertex_count > 0:
            mn = self.P.min(axis=0)
            mx = self.P.max(axis=0)
        if self.vertex_count == 0 or not mn[0] <= mx[0]:
            mn = np.zeros(3)
            mx = np.zeros(3)
        mn = [float(x) for x in mn]
        mx = [float(x) for x in mx]
        step = max(1, self.triangle_count // 5000)
        total = 0.0
        count = 0
        for t in range(0, self.triangle_count, step):
            a, b, c = idx[t * 3] * 3, idx[t * 3 + 1] * 3, idx[t * 3 + 2] * 3
            total += js_hypot(p[b] - p[a], p[b + 1] - p[a + 1], p[b + 2] - p[a + 2]) + js_hypot(p[c] - p[b], p[c + 1] - p[b + 1], p[c + 2] - p[b + 2]) + js_hypot(p[a] - p[c], p[a + 1] - p[c + 1], p[a + 2] - p[c + 2])
            count += 3
        self.edge = total / count if count > 0 else 1.0
        span = [mx[0] - mn[0], mx[1] - mn[1], mx[2] - mn[2]]
        cell = max(self.edge * math.sqrt(PER_CELL), 1e-6)

        def cells_at(h):
            return (math.floor(span[0] / h) + 1) * (math.floor(span[1] / h) + 1) * (math.floor(span[2] / h) + 1)

        while cells_at(cell) > MAX_CELLS:
            cell *= 1.25
        self.cell = cell
        self.min = mn
        self.dims = [math.floor(span[0] / cell) + 1, math.floor(span[1] / cell) + 1, math.floor(span[2] / cell) + 1]
        nx, ny, nz = self.dims
        cells = nx * ny * nz
        T = self.P[self.F] if self.triangle_count else np.zeros((0, 3, 3))
        lo = T.min(axis=1) if self.triangle_count else np.zeros((0, 3))
        hi = T.max(axis=1) if self.triangle_count else np.zeros((0, 3))
        dims = np.array(self.dims)
        mnv = np.array(mn)
        b0 = np.clip(np.floor((lo - mnv) / cell), 0, dims - 1).astype(np.int64)
        b1 = np.clip(np.floor((hi - mnv) / cell), 0, dims - 1).astype(np.int64)
        side = (hi - lo).max(axis=1) if self.triangle_count else np.zeros(0)
        ext = b1 - b0
        tri_ids = []
        cell_ids = []
        tids = np.arange(self.triangle_count)
        if self.triangle_count:
            for dx in range(int(ext[:, 0].max()) + 1):
                mx_ = ext[:, 0] >= dx
                for dy in range(int(ext[:, 1].max()) + 1):
                    my_ = mx_ & (ext[:, 1] >= dy)
                    for dz in range(int(ext[:, 2].max()) + 1):
                        m = my_ & (ext[:, 2] >= dz)
                        if not m.any():
                            continue
                        x = b0[m, 0] + dx
                        y = b0[m, 1] + dy
                        z = b0[m, 2] + dz
                        cell_ids.append((x * ny + y) * nz + z)
                        tri_ids.append(tids[m])
        cell_ids = np.concatenate(cell_ids) if cell_ids else np.zeros(0, dtype=np.int64)
        tri_ids = np.concatenate(tri_ids) if tri_ids else np.zeros(0, dtype=np.int64)
        order = np.lexsort((tri_ids, cell_ids))
        cell_ids = cell_ids[order]
        tri_ids = tri_ids[order]
        counts = np.bincount(cell_ids, minlength=cells)
        offsets = np.zeros(cells + 1, dtype=np.int64)
        np.cumsum(counts, out=offsets[1:])
        reach = np.zeros(cells, dtype=np.float32)
        if tri_ids.size:
            sides = (side[tri_ids] * (1 + 1e-6)).astype(np.float32)
            np.maximum.at(reach, cell_ids, sides)
        r3 = reach.reshape(nx, ny, nz)
        self.column_reach = r3.max(axis=2).reshape(-1).astype(np.float64)
        self.slab_reach = r3.max(axis=(1, 2)).astype(np.float64)
        self.offsets = offsets
        self.list = tri_ids
        self.reach = reach.astype(np.float64)
        self._adjacency = None
        self._search = None

    # ---- the grid ---------------------------------------------------------------------------

    def _cell_range(self, lo, hi):
        c0 = []
        c1 = []
        for k in range(3):
            c0.append(max(0, math.floor((lo[k] - self.min[k]) / self.cell)))
            c1.append(min(self.dims[k] - 1, math.floor((hi[k] - self.min[k]) / self.cell)))
        return c0, c1

    def triangles_in(self, lo, hi):
        """Every triangle whose box may meet the box [lo, hi], each once, in
        the original's order (cells x, y, z; the triangles of a cell by
        number)."""
        c0, c1 = self._cell_range(lo, hi)
        if c0[0] > c1[0] or c0[1] > c1[1] or c0[2] > c1[2]:
            return np.zeros(0, dtype=np.int64)
        ny, nz = self.dims[1], self.dims[2]
        xs = np.arange(c0[0], c1[0] + 1)
        ys = np.arange(c0[1], c1[1] + 1)
        zs = np.arange(c0[2], c1[2] + 1)
        cid = ((xs[:, None, None] * ny + ys[None, :, None]) * nz + zs[None, None, :]).ravel()
        starts = self.offsets[cid]
        ends = self.offsets[cid + 1]
        lens = ends - starts
        total = int(lens.sum())
        if total == 0:
            return np.zeros(0, dtype=np.int64)
        keep = lens > 0
        starts = starts[keep]
        lens = lens[keep]
        pos = np.repeat(starts - np.concatenate(([0], np.cumsum(lens)[:-1])), lens) + np.arange(total)
        got = self.list[pos]
        _, first = np.unique(got, return_index=True)
        return got[np.sort(first)]

    def triangles_crossing(self, lo, hi, m, d0):
        """The triangles of triangles_in(lo, hi) that the plane m.x = d0
        crosses (a corner on either side of it, a corner on it counted on
        the side m points to), in the order triangles_in gives them."""
        ts = self.triangles_in(lo, hi)
        if ts.size == 0:
            return ts
        T = self.P[self.F[ts]]
        s = (m[0] * T[:, :, 0] + m[1] * T[:, :, 1] + m[2] * T[:, :, 2] - d0) >= 0
        cross = (s[:, 0] != s[:, 1]) | (s[:, 1] != s[:, 2])
        return ts[cross]

    # ---- points on the scan -----------------------------------------------------------------

    def _closest_among(self, ts, p):
        F = self.F[ts]
        Q = closest_on_triangles(p, self.P[F[:, 0]], self.P[F[:, 1]], self.P[F[:, 2]])
        d = Q - np.asarray(p, dtype=float)
        return Q, np.sqrt((d * d).sum(axis=1))

    def closest(self, p):
        """The nearest point of the scan to p, or None on an empty scan."""
        if self.triangle_count == 0:
            return None
        span = max(self.dims) * self.cell
        r = self.cell
        while True:
            ts = self.triangles_in([p[0] - r, p[1] - r, p[2] - r], [p[0] + r, p[1] + r, p[2] + r])
            best = math.inf
            best_t = -1
            at = None
            if ts.size:
                Q, d = self._closest_among(ts, p)
                i = int(np.argmin(d))
                best_t = int(ts[i])
                at = [float(x) for x in Q[i]]
                best = js_hypot(at[0] - p[0], at[1] - p[1], at[2] - p[2])
            if (best_t >= 0 and best <= r) or r > 2 * span + self._distance_to_grid(p):
                if best_t < 0:
                    return None
                return ScanPoint(at, best_t, self.triangle_normal(best_t), best)
            r *= 2

    def closest_inside(self, p):
        """The nearest point of the scan to p, taken a hair inside its
        triangle where it lies on the triangle's edge or corner."""
        c = self.closest(p)
        if c is None:
            return None
        pos = self.positions
        t = c.triangle
        corners = [self.indices[t * 3 + k] * 3 for k in range(3)]
        a, b, d = ([pos[corners[k]], pos[corners[k] + 1], pos[corners[k] + 2]] for k in range(3))
        n = self._triangle_cross(t)
        nn = n[0] * n[0] + n[1] * n[1] + n[2] * n[2]
        if not nn > 0:
            return c
        cp = c.point

        def w(u, v):
            e1 = [v[0] - u[0], v[1] - u[1], v[2] - u[2]]
            e2 = [cp[0] - u[0], cp[1] - u[1], cp[2] - u[2]]
            return ((e1[1] * e2[2] - e1[2] * e2[1]) * n[0] + (e1[2] * e2[0] - e1[0] * e2[2]) * n[1] + (e1[0] * e2[1] - e1[1] * e2[0]) * n[2]) / nn

        bary = [w(b, d), w(d, a), w(a, b)]
        hair = 1e-4
        if min(bary) >= hair:
            return c
        held = [max(x, hair) for x in bary]
        s = held[0] + held[1] + held[2]
        point = [(held[0] * a[k] + held[1] * b[k] + held[2] * d[k]) / s for k in range(3)]
        return ScanPoint(point, c.triangle, c.normal, js_hypot(point[0] - p[0], point[1] - p[1], point[2] - p[2]))

    def normal_at(self, p, triangle):
        """The scan's normal about a point on it: the triangles' normals
        within a few edges, by area."""
        r = NORMAL_EDGES * self.edge
        ts = self.triangles_in([p[0] - r, p[1] - r, p[2] - r], [p[0] + r, p[1] + r, p[2] + r])
        n = [0.0, 0.0, 0.0]
        if ts.size:
            _, d = self._closest_among(ts, p)
            ts = ts[~(d > r)]
            if ts.size:
                F = self.F[ts]
                A = self.P[F[:, 0]]
                W = np.cross(self.P[F[:, 1]] - A, self.P[F[:, 2]] - A)
                n = [float(x) for x in np.cumsum(W, axis=0)[-1]]
        l = js_hypot(n[0], n[1], n[2])
        return [n[0] / l, n[1] / l, n[2] / l] if l > 0 else self.triangle_normal(triangle)

    def triangle_normal(self, t):
        n = self._triangle_cross(t)
        l = js_hypot(n[0], n[1], n[2])
        return [n[0] / l, n[1] / l, n[2] / l] if l > 0 else [0.0, 0.0, 1.0]

    def triangle_normals(self):
        """Every triangle's unit normal, (N, 3), as triangle_normal."""
        A = self.P[self.F[:, 0]]
        n = np.cross(self.P[self.F[:, 1]] - A, self.P[self.F[:, 2]] - A)
        l = np.sqrt((n * n).sum(axis=1))
        out = np.tile([0.0, 0.0, 1.0], (n.shape[0], 1))
        ok = l > 0
        out[ok] = n[ok] / l[ok, None]
        return out

    def _triangle_cross(self, t):
        p = self.positions
        i = self.indices
        a, b, c = i[t * 3] * 3, i[t * 3 + 1] * 3, i[t * 3 + 2] * 3
        ux, uy, uz = p[b] - p[a], p[b + 1] - p[a + 1], p[b + 2] - p[a + 2]
        vx, vy, vz = p[c] - p[a], p[c + 1] - p[a + 1], p[c + 2] - p[a + 2]
        return [uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx]

    def closest_on_triangle(self, t, p, out):
        """How far p is from triangle t, its nearest point written to out."""
        pos = self.positions
        ia, ib, ic = self.indices[t * 3] * 3, self.indices[t * 3 + 1] * 3, self.indices[t * 3 + 2] * 3
        q = _closest_on_triangle(p, pos[ia], pos[ia + 1], pos[ia + 2], pos[ib], pos[ib + 1], pos[ib + 2], pos[ic], pos[ic + 1], pos[ic + 2])
        out[0], out[1], out[2] = q
        return js_hypot(q[0] - p[0], q[1] - p[1], q[2] - p[2])

    def _distance_to_grid(self, p):
        d = 0.0
        for k in range(3):
            lo = self.min[k]
            hi = self.min[k] + self.dims[k] * self.cell
            d = max(d, lo - p[k], p[k] - hi)
        return max(0.0, d)

    # ---- the edges --------------------------------------------------------------------------

    def neighbours(self):
        """The vertices' adjacency (CSR), made once: (offsets, list)."""
        if self._adjacency is None:
            o, l = build_adjacency(self.F, self.vertex_count)
            self._adjacency = (o, l, o.tolist(), l.tolist())
        return self._adjacency[0], self._adjacency[1]

    def _neighbour_lists(self):
        self.neighbours()
        return self._adjacency[2], self._adjacency[3]

    def _edge_search(self):
        if self._search is not None:
            return self._search
        n = self.vertex_count
        offsets, lst = self.neighbours()
        owner = np.repeat(np.arange(n), np.diff(offsets))
        label = np.arange(n)
        while True:
            nxt = label.copy()
            if lst.size:
                np.minimum.at(nxt, owner, label[lst])
                np.minimum.at(nxt, lst, label[owner])
            nxt = nxt[nxt]
            if np.array_equal(nxt, label):
                break
            label = nxt
        self._search = {"piece": label.tolist(), "g": [0.0] * n, "back": [0] * n, "state": [0] * n, "mark": [0] * n, "heap": _Heap(), "query": 0, "expansion": 0}
        return self._search

    def prepare_edge_routes(self):
        self._edge_search()

    def edge_route(self, frm, to):
        """The vertices of the shortest way along the mesh's edges from
        vertex frm to vertex to, both included, or None where no edges join
        them (A*, the original's search to the bit)."""
        s = self._edge_search()
        if s["piece"][frm] != s["piece"][to]:
            return None
        if frm == to:
            return [frm]
        p = self.positions
        offsets, lst = self._neighbour_lists()
        g, back, state, mark, heap = s["g"], s["back"], s["state"], s["mark"], s["heap"]
        if s["query"] >= 0xFFFFFFF0:
            for i in range(len(state)):
                state[i] = 0
            s["query"] = 0
        s["query"] += 2
        seen = s["query"]
        done = s["query"] + 1
        tx, ty, tz = p[to * 3], p[to * 3 + 1], p[to * 3 + 2]
        hair = 1 - 1e-9
        heap.clear()
        g[frm] = 0.0
        state[frm] = seen
        fx, fy, fz = p[frm * 3] - tx, p[frm * 3 + 1] - ty, p[frm * 3 + 2] - tz
        heap.push(frm, hair * math.sqrt(fx * fx + fy * fy + fz * fz))
        found = False
        while heap.size > 0:
            v, _ = heap.pop()
            if state[v] == done:
                continue
            state[v] = done
            if v == to:
                found = True
                break
            if s["expansion"] == 0xFFFFFFFF:
                for i in range(len(mark)):
                    mark[i] = 0
                s["expansion"] = 0
            s["expansion"] += 1
            e = s["expansion"]
            gv = g[v]
            vx, vy, vz = p[v * 3], p[v * 3 + 1], p[v * 3 + 2]
            for k in range(offsets[v], offsets[v + 1]):
                w = lst[k]
                if mark[w] == e:
                    continue
                mark[w] = e
                known = state[w] >= seen
                if known and g[w] <= gv:
                    continue
                wx, wy, wz = p[w * 3], p[w * 3 + 1], p[w * 3 + 2]
                nd = gv + js_hypot(wx - vx, wy - vy, wz - vz)
                if not known or nd < g[w]:
                    g[w] = nd
                    back[w] = v
                    state[w] = seen
                    dx, dy, dz = wx - tx, wy - ty, wz - tz
                    heap.push(w, nd + hair * math.sqrt(dx * dx + dy * dy + dz * dz))
                elif nd == g[w] and gv < g[back[w]]:
                    back[w] = v
        if not found:
            return None
        route = []
        v = to
        while True:
            route.append(v)
            if v == frm:
                break
            v = back[v]
        route.reverse()
        return route


def place_of(on, i):
    """Where a point of a path lies, read from its `on` pair."""
    a = on[i * 2]
    b = on[i * 2 + 1]
    if a < 0:
        return {"triangle": b}
    return {"vertex": a} if a == b else {"edge": [a, b]}


def _path(points, on, length, way, ends):
    return {"points": np.asarray(points, dtype=np.float32).reshape(-1), "on": np.asarray(on, dtype=np.int64).reshape(-1), "length": length, "way": way, "ends": list(ends)}


def trace_path(scan, a, b, normal=None):
    """The path along the scan from a to b, both on or near it: the plane
    section between them, or the shortest way along the edges where the
    section does not join them. Each end is taken inside its triangle
    first (closest_inside)."""
    ca = scan.closest_inside(a)
    cb = scan.closest_inside(b)
    if ca is None or cb is None:
        return _path([], [], 0.0, "section", [-1, -1])
    pa = ca.point
    pb = cb.point
    d = [pb[0] - pa[0], pb[1] - pa[1], pb[2] - pa[2]]
    dl = js_hypot(d[0], d[1], d[2])
    if ca.triangle == cb.triangle or dl < 1e-9:
        return _path([*pa, *pb], [-1, ca.triangle, -1, cb.triangle], dl, "section", [ca.triangle, cb.triangle])
    n = normal
    if n is None:
        na = scan.normal_at(pa, ca.triangle)
        nb = scan.normal_at(pb, cb.triangle)
        n = [na[0] + nb[0], na[1] + nb[1], na[2] + nb[2]]
        if js_hypot(n[0], n[1], n[2]) < 1e-6:
            n = na
    m = [d[1] * n[2] - d[2] * n[1], d[2] * n[0] - d[0] * n[2], d[0] * n[1] - d[1] * n[0]]
    ml = js_hypot(m[0], m[1], m[2])
    nl = js_hypot(n[0], n[1], n[2])
    section = _section_path(scan, pa, pb, ca.triangle, cb.triangle, [m[0] / ml, m[1] / ml, m[2] / ml], dl) if ml > 1e-3 * dl * nl else None
    return section if section is not None else _edge_path(scan, pa, pb, ca.triangle, cb.triangle)


def _point_segment(q, pts, i, j):
    x0, y0, z0 = pts[i * 3], pts[i * 3 + 1], pts[i * 3 + 2]
    dx, dy, dz = pts[j * 3] - x0, pts[j * 3 + 1] - y0, pts[j * 3 + 2] - z0
    dd = dx * dx + dy * dy + dz * dz
    t = max(0.0, min(1.0, ((q[0] - x0) * dx + (q[1] - y0) * dy + (q[2] - z0) * dz) / dd)) if dd > 0 else 0.0
    return js_hypot(q[0] - x0 - t * dx, q[1] - y0 - t * dy, q[2] - z0 - t * dz)


def _section_path(scan, pa, pb, ta, tb, m, dl):
    p = scan.positions
    idx = scan.indices
    radius = TUBE_SHARE * dl + TUBE_EDGES * scan.edge
    lo = [min(pa[k], pb[k]) - radius for k in range(3)]
    hi = [max(pa[k], pb[k]) + radius for k in range(3)]
    d0 = m[0] * pa[0] + m[1] * pa[1] + m[2] * pa[2]
    m0, m1, m2 = m

    def dist(v):
        return m0 * p[v * 3] + m1 * p[v * 3 + 1] + m2 * p[v * 3 + 2] - d0

    ax, ay, az = pb[0] - pa[0], pb[1] - pa[1], pb[2] - pa[2]
    aa = ax * ax + ay * ay + az * az

    def off_segment(x, y, z):
        t = max(0.0, min(1.0, ((x - pa[0]) * ax + (y - pa[1]) * ay + (z - pa[2]) * az) / aa))
        return js_hypot(x - pa[0] - t * ax, y - pa[1] - t * ay, z - pa[2] - t * az)

    point_of = {}
    pts = []
    edge_of = []
    vertex_count = scan.vertex_count

    def cross(i, j):
        lo2 = min(i, j)
        hi2 = max(i, j)
        key = lo2 * vertex_count + hi2
        had = point_of.get(key)
        if had is not None:
            return had
        di = dist(lo2)
        dj = dist(hi2)
        t = di / (di - dj)
        at = len(pts) // 3
        pts.extend((p[lo2 * 3] + t * (p[hi2 * 3] - p[lo2 * 3]), p[lo2 * 3 + 1] + t * (p[hi2 * 3 + 1] - p[lo2 * 3 + 1]), p[lo2 * 3 + 2] + t * (p[hi2 * 3 + 2] - p[lo2 * 3 + 2])))
        edge_of.extend((lo2, hi2))
        point_of[key] = at
        return at

    seg_a = []
    seg_b = []
    seg_tri = []
    for t in scan.triangles_crossing(lo, hi, m, d0).tolist():
        a, b, c = idx[t * 3], idx[t * 3 + 1], idx[t * 3 + 2]
        sa, sb, sc = dist(a) >= 0, dist(b) >= 0, dist(c) >= 0
        if sa == sb and sb == sc:
            continue
        cx = (p[a * 3] + p[b * 3] + p[c * 3]) / 3
        cy = (p[a * 3 + 1] + p[b * 3 + 1] + p[c * 3 + 1]) / 3
        cz = (p[a * 3 + 2] + p[b * 3 + 2] + p[c * 3 + 2]) / 3
        if off_segment(cx, cy, cz) > radius:
            continue
        ends = []
        if sa != sb:
            ends.append(cross(a, b))
        if sb != sc:
            ends.append(cross(b, c))
        if sc != sa:
            ends.append(cross(c, a))
        seg_a.append(ends[0])
        seg_b.append(ends[1])
        seg_tri.append(t)
    if not seg_a:
        return None
    count = len(pts) // 3
    segs_at = [[] for _ in range(count)]
    for s in range(len(seg_a)):
        segs_at[seg_a[s]].append(s)
        segs_at[seg_b[s]].append(s)
    slack = END_SLACK_EDGES * scan.edge

    def segment_at(q, tri):
        best = -1
        best_d = math.inf
        for s in range(len(seg_a)):
            if seg_tri[s] == tri:
                return s
            d = _point_segment(q, pts, seg_a[s], seg_b[s])
            if d < best_d:
                best_d, best = d, s
        return best if best_d <= slack else -1

    sa = segment_at(pa, ta)
    sb = segment_at(pb, tb)
    if sa < 0 or sb < 0:
        return None

    def walk(first):
        out = []
        seen = {sa}
        point = first
        seg = sa
        while True:
            if seg == sb:
                return out
            out.append(point)
            nxt = None
            for s in segs_at[point]:
                if s != seg and s not in seen:
                    nxt = s
                    break
            if nxt is None:
                return None
            seen.add(nxt)
            seg = nxt
            point = seg_b[seg] if seg_a[seg] == point else seg_a[seg]

    def length_of(route):
        l = 0.0
        prev = pa
        for i in route:
            q = [pts[i * 3], pts[i * 3 + 1], pts[i * 3 + 2]]
            l += js_hypot(q[0] - prev[0], q[1] - prev[1], q[2] - prev[2])
            prev = q
        return l + js_hypot(pb[0] - prev[0], pb[1] - prev[1], pb[2] - prev[2])

    if sa == sb:
        route = []
    else:
        one = walk(seg_a[sa])
        other = walk(seg_b[sa])
        if one is not None and other is not None:
            route = one if length_of(one) <= length_of(other) else other
        else:
            route = one if one is not None else other
    if route is None:
        return None
    points = list(pa)
    on = [-1, ta]
    for i in route:
        points.extend((pts[i * 3], pts[i * 3 + 1], pts[i * 3 + 2]))
        on.extend((edge_of[i * 2], edge_of[i * 2 + 1]))
    points.extend(pb)
    on.extend((-1, tb))
    return _path(points, on, length_of(route), "section", [ta, tb])


def _edge_path(scan, pa, pb, ta, tb):
    p = scan.positions
    idx = scan.indices

    def corner(q, t):
        best = idx[t * 3]
        best_d = math.inf
        for k in range(3):
            v = idx[t * 3 + k]
            d = js_hypot(p[v * 3] - q[0], p[v * 3 + 1] - q[1], p[v * 3 + 2] - q[2])
            if d < best_d:
                best_d, best = d, v
        return best

    route = scan.edge_route(corner(pa, ta), corner(pb, tb)) or []
    points = list(pa)
    on = [-1, ta]
    length = 0.0
    prev = pa
    for v in route:
        q = [p[v * 3], p[v * 3 + 1], p[v * 3 + 2]]
        points.extend(q)
        on.extend((v, v))
        length += js_hypot(q[0] - prev[0], q[1] - prev[1], q[2] - prev[2])
        prev = q
    points.extend(pb)
    on.extend((-1, tb))
    length += js_hypot(pb[0] - prev[0], pb[1] - prev[1], pb[2] - prev[2])
    return _path(points, on, length, "edges", [ta, tb])
