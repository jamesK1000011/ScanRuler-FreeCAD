# SPDX-License-Identifier: AGPL-3.0-only
# Ported from ScanRuler by CNC Kitchen (Stefan Hermann):
# plugins/mesh-tools/core/densify.ts
#
# Densify: a mesh's triangles cut until no edge is longer than a maximum, the
# surface unchanged — every new vertex the middle of an edge, so it lies on
# the facet it was cut from. What an STL exported from CAD needs before it is
# measured like a scan: such a mesh has vertices only on its edges and rims,
# none inside its faces, and a fit or a segmentation looking for points on a
# face finds none (issue 42).
#
# Pass by pass, every edge longer than the maximum gets one vertex in its
# middle, shared by the two triangles on it, and each triangle is cut by how
# many of its edges were: in two, in three (the quad left over cut across its
# shorter diagonal) or in four. The cuts on either side of an edge meet, so
# the mesh stays as closed as it was — no T-junction, no new rim. Here each
# pass works on every triangle at once; the triangles come out in the order
# the original puts them, and a pass's middles numbered by their edge.

import math

import numpy as np

from .. import mesh_core as M

DENSIFY_MAX_TRIANGLES = 20_000_000
MAX_PASSES = 48


def densify_edge_for(diagonal):
    """scanQa.ts densifyEdgeFor: a hundredth of the part's diagonal (0.05 mm
    at the least) on the 1-2-5 steps — the panel's length to start."""
    raw = max(diagonal / 100, 0.05)
    p = 10 ** math.floor(math.log10(raw))
    m = raw / p
    return (1 if m < 1.5 else 2 if m < 3.5 else 5 if m < 7.5 else 10) * p


def _rot(T, turn):
    out = T.copy()
    for r in (1, 2):
        sel = turn == r
        out[sel] = np.roll(T[sel], -r, axis=1)
    return out


def densify_mesh(V, F, max_edge):
    """The mesh with every edge cut down to max_edge or shorter: (V, F,
    vertex map — the identity —, report). The vertices stay where they are,
    numbered as they were; the new ones follow them."""
    if not (max_edge > 0):
        raise M.MeshError("Give a maximum edge length above zero.")
    pos = np.asarray(V, dtype=float).copy()
    nv0 = len(pos)
    tris = np.asarray(F, dtype=np.int64).reshape(-1, 3).copy()
    before = len(tris)
    max2 = max_edge * max_edge

    def len2(a, b):
        d = pos[a] - pos[b]
        return np.einsum("ij,ij->i", d, d)

    passes = 0
    while passes < MAX_PASSES:
        n = len(tris)
        a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]
        m = (len2(a, b) > max2).astype(np.int64) | ((len2(b, c) > max2).astype(np.int64) << 1) | ((len2(c, a) > max2).astype(np.int64) << 2)
        ones = (m & 1) + ((m >> 1) & 1) + ((m >> 2) & 1)
        made = int((ones + 1).sum())
        if made == n:
            break
        if made > DENSIFY_MAX_TRIANGLES:
            raise M.MeshError(f"Cut that fine the mesh would pass {DENSIFY_MAX_TRIANGLES / 1e6:.0f} million triangles — give a longer maximum edge.")
        # The middles of this pass's long edges, one per edge.
        long_edges = []
        for bit, (x, y) in ((1, (a, b)), (2, (b, c)), (4, (c, a))):
            s = (m & bit) > 0
            long_edges.append(np.stack([np.minimum(x[s], y[s]), np.maximum(x[s], y[s])], axis=1))
        E = np.unique(np.vstack(long_edges), axis=0)
        cnt = len(pos)
        pos = np.vstack([pos, (pos[E[:, 0]] + pos[E[:, 1]]) / 2])
        ekey = E[:, 0] * (cnt + len(E)) + E[:, 1]
        width = cnt + len(E)

        def middle(x, y):
            k = np.minimum(x, y) * width + np.maximum(x, y)
            return cnt + np.searchsorted(ekey, k)

        out = np.full((n, 4, 3), -1, dtype=np.int64)
        out[m == 0, 0] = tris[m == 0]
        all3 = m == 7
        if all3.any():
            ta, tb, tc = a[all3], b[all3], c[all3]
            ab, bc, ca = middle(ta, tb), middle(tb, tc), middle(tc, ta)
            out[all3, 0] = np.stack([ta, ab, ca], 1)
            out[all3, 1] = np.stack([ab, tb, bc], 1)
            out[all3, 2] = np.stack([ca, bc, tc], 1)
            out[all3, 3] = np.stack([ab, bc, ca], 1)
        # Turned so the long edges come first round the triangle, the
        # winding kept: one long edge is a–b; two are a–b and b–c.
        one = ones == 1
        if one.any():
            turn = np.where(m[one] == 1, 0, np.where(m[one] == 2, 1, 2))
            T = _rot(tris[one], turn)
            ta, tb, tc = T[:, 0], T[:, 1], T[:, 2]
            ab = middle(ta, tb)
            out[one, 0] = np.stack([ta, ab, tc], 1)
            out[one, 1] = np.stack([ab, tb, tc], 1)
        two = ones == 2
        if two.any():
            turn = np.where(m[two] == 3, 0, np.where(m[two] == 6, 1, 2))
            T = _rot(tris[two], turn)
            ta, tb, tc = T[:, 0], T[:, 1], T[:, 2]
            ab, bc = middle(ta, tb), middle(tb, tc)
            out[two, 0] = np.stack([ab, tb, bc], 1)
            short = len2(ta, bc) <= len2(ab, tc)
            out[two, 1] = np.where(short[:, None], np.stack([ta, ab, bc], 1), np.stack([ta, ab, tc], 1))
            out[two, 2] = np.where(short[:, None], np.stack([ta, bc, tc], 1), np.stack([ab, bc, tc], 1))
        flat = out.reshape(-1, 3)
        tris = flat[flat[:, 0] >= 0]
        passes += 1
    longest = 0.0
    if len(tris):
        longest = float(max(len2(tris[:, 0], tris[:, 1]).max(), len2(tris[:, 1], tris[:, 2]).max(), len2(tris[:, 2], tris[:, 0]).max()))
    report = {"maxEdge": max_edge, "trianglesBefore": before, "triangles": int(len(tris)), "added": int(len(pos) - nv0), "longest": math.sqrt(longest), "passes": passes}
    return pos, tris, np.arange(nv0), report


def status(report):
    """meshToolsSession.ts densifyScan's status line, in mm."""
    if report["added"] == 0:
        return f"No edge was longer than {report['maxEdge']:g} mm — nothing to cut."
    return f"Densified: {report['trianglesBefore']:,} triangles cut into {report['triangles']:,}, none with an edge over {report['maxEdge']:g} mm — the surface where it was."
