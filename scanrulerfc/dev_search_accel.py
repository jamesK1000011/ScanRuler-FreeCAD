# SPDX-License-Identifier: AGPL-3.0-only
"""Exact nearest-triangle search using a seeded hierarchy of leaf boxes.

Centroid neighbours supply a valid upper bound, not an approximate answer.
Every leaf box capable of improving that bound is visited. Triangle distance,
facing and pseudonormal calculations remain those of dev_surface.
"""

import numpy as np

try:
    from scipy.spatial import cKDTree as _KDTree
except ImportError:
    _KDTree = None

_MAX_FRONTIER = 500_000


def _prepare(surface):
    count = len(surface.leaf_lo)
    size = 1 << (count - 1).bit_length()
    lo = np.full((size, 3), np.inf)
    hi = np.full((size, 3), -np.inf)
    lo[:count] = surface.leaf_lo
    hi[:count] = surface.leaf_hi
    valid = np.arange(size) < count
    levels = [(lo, hi, valid)]
    while len(lo) > 1:
        lo = lo.reshape(-1, 2, 3).min(axis=1)
        hi = hi.reshape(-1, 2, 3).max(axis=1)
        valid = valid.reshape(-1, 2).any(axis=1)
        levels.append((lo, hi, valid))
    tree = _KDTree((surface.A + surface.B + surface.C) / 3)
    surface._nearest_accel = (levels, tree)
    return levels, tree


def search(surface, Q, cap2, facing, min_dot):
    # The original query treats non-finite locations as unmeasured. scipy's
    # tree rejects them, so preserve the original behavior for that batch.
    if _KDTree is None or not np.isfinite(Q).all():
        return surface._search_original(Q, cap2, facing, min_dot)

    from .dev_surface import _box_d2_pairs, closest_on_triangles

    cached = getattr(surface, "_nearest_accel", None)
    levels, tree = cached if cached is not None else _prepare(surface)
    count = len(Q)
    rows = np.arange(count)
    best2 = np.full(count, np.inf if not np.isfinite(cap2) else cap2 * (1 + 1e-12) + 1e-300)
    best_face = np.full(count, -1, dtype=np.int64)

    _, tris = tree.query(Q, k=min(4, surface.triangle_count))
    tris = np.asarray(tris).reshape(count, -1)
    pq = np.repeat(rows, tris.shape[1])
    pt = tris.ravel()
    points, _ = closest_on_triangles(Q[pq], surface.A[pt], surface.B[pt], surface.C[pt])
    distance = ((points - Q[pq]) ** 2).sum(axis=1).reshape(tris.shape)
    if facing is not None:
        away = np.einsum("ij,ij->i", surface.face_normal[pt], facing[pq]) < min_dot
        distance[away.reshape(tris.shape)] = np.inf
    at = distance.argmin(axis=1)
    seed = distance[rows, at]
    won = seed < best2
    best2[won] = seed[won]
    best_face[won] = tris[rows, at][won]
    seeded = best_face >= 0

    # No valid seed is not evidence that there is no facing surface. Keep
    # the original exact search for these rows, with their original cap.
    missed = np.flatnonzero(~seeded)
    if len(missed):
        faces, distances = surface._search_original(
            Q[missed], cap2, None if facing is None else facing[missed], min_dot
        )
        best_face[missed] = faces
        best2[missed] = distances

    rows = np.flatnonzero(seeded)
    nodes = np.zeros(len(rows), dtype=np.int64)
    for depth in range(len(levels) - 2, -1, -1):
        rows = np.repeat(rows, 2)
        nodes = (nodes[:, None] * 2 + np.arange(2)).ravel()
        lo, hi, valid = levels[depth]
        bounds = _box_d2_pairs(Q[rows], lo[nodes], hi[nodes])
        keep = valid[nodes] & (bounds < best2[rows])
        rows, nodes = rows[keep], nodes[keep]
        if not len(rows):
            break
        if len(rows) > _MAX_FRONTIER:
            # Pathological overlap must not grow an unbounded frontier.
            return surface._search_original(Q, cap2, facing, min_dot)
    if len(rows):
        surface._leaf_pass(Q, rows, nodes, facing, min_dot, best2, best_face)
    return best_face, best2
