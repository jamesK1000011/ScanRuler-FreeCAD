# SPDX-License-Identifier: AGPL-3.0-only
# Ported from ScanRuler by CNC Kitchen (Stefan Hermann):
# plugins/mesh-tools/core/hollow.ts, plugins/mesh-tools/core/offset.ts
# (thickenMesh) and plugins/mesh-tools/state/meshStore.ts (shellModeOf)
#
# Shell: a closed part hollowed — its outside left as scanned and an inner
# wall the thickness in from it all round, facing into a sealed cavity — or
# an open surface thickened into a solid: a second skin the thickness from
# it and a wall round every rim.
#
# The inner wall is not the scan moved in; moved point by point a surface
# folds through itself wherever the part is thinner than twice the wall. It
# is the surface the thickness in from the part's own, read off the part's
# distance field on a grid a third of the thickness across (coarser on a part
# too large for that many points): which grid points are inside (each column
# along Z crossed by the triangles over it, counted by the way each faces),
# roughly how far in (an exact Euclidean transform from every point outside
# and next to the surface), exactly how far in a band round the wall (the
# nearest triangle, the deviation maps' search), and the wall where the
# distance crosses the thickness, by marching tetrahedra, so it closes.
# Specks of cavity under eight cubic cells stay solid. ScanRuler then reduces
# the wall with meshoptimizer; there is no such reducer here, so the wall
# keeps the grid's triangles (the original's own path without a simplifier).
#
# Thickening moves each skin by the even move (offset.ts, as mesh_offset
# does here); ScanRuler's fold mending of each skin (mendFolds.ts) is not
# ported — as with mesh_offset, its counts come back 0.

import numpy as np

from .. import mesh_core as M
from ..dev_surface import NominalSurface
from . import grid as G

MAX_POINTS = 12_000_000
MIN_CAVITY_CELLS = 8


def default_wall_thickness(diag):
    """A hundred-and-twenty-fifth of the part's diagonal on the 1-2-5 steps."""
    return M.round125(diag * 0.008)


def shell_mode_of(open_edges, rims, holes):
    """meshStore.ts shellModeOf: hollow a closed part; a part closed but for
    holes is to be filled first; anything else is thickened."""
    if open_edges == 0:
        return "hollow"
    return "holes" if rims > 0 and holes == rims else "thicken"


def inside_grid(V, F, nx, ny, nz, ox, oy, oz, h):
    """Which grid points are inside the mesh (hollow.ts insideGrid): every
    column along Z crossed by the triangles over it, entering through one
    facing down and leaving through one facing up."""
    T = np.asarray(V, dtype=float)[F]
    ax, ay, az = T[:, 0, 0], T[:, 0, 1], T[:, 0, 2]
    bx, by, bz = T[:, 1, 0], T[:, 1, 1], T[:, 1, 2]
    cx, cy, cz = T[:, 2, 0], T[:, 2, 1], T[:, 2, 2]
    area = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
    i0 = np.maximum(0, np.ceil((np.minimum.reduce([ax, bx, cx]) - ox) / h)).astype(np.int64)
    i1 = np.minimum(nx - 1, np.floor((np.maximum.reduce([ax, bx, cx]) - ox) / h)).astype(np.int64)
    j0 = np.maximum(0, np.ceil((np.minimum.reduce([ay, by, cy]) - oy) / h)).astype(np.int64)
    j1 = np.minimum(ny - 1, np.floor((np.maximum.reduce([ay, by, cy]) - oy) / h)).astype(np.int64)
    wi, wj = np.maximum(0, i1 - i0 + 1), np.maximum(0, j1 - j0 + 1)
    cnt = np.where(area != 0, wi * wj, 0)
    diff = np.zeros((nx * ny, nz + 1), dtype=np.int32)
    total = int(cnt.sum())
    step = 1 << 22
    t_all = np.repeat(np.arange(len(F)), cnt)
    start = np.cumsum(cnt) - cnt
    for s in range(0, total, step):
        t = t_all[s:s + step]
        local = np.arange(s, min(total, s + step)) - start[t]
        i = i0[t] + local % np.maximum(wi[t], 1)
        j = j0[t] + local // np.maximum(wi[t], 1)
        px, py = ox + i * h, oy + j * h
        wc = (bx[t] - ax[t]) * (py - ay[t]) - (by[t] - ay[t]) * (px - ax[t])
        wa = (cx[t] - bx[t]) * (py - by[t]) - (cy[t] - by[t]) * (px - bx[t])
        wb = (ax[t] - cx[t]) * (py - cy[t]) - (ay[t] - cy[t]) * (px - cx[t])
        ar = area[t]
        skip = np.where(ar > 0, (wa <= 0) | (wb <= 0) | (wc <= 0), (wa >= 0) | (wb >= 0) | (wc >= 0))
        k = ~skip
        t, i, j, wa, wb, wc, ar = t[k], i[k], j[k], wa[k], wb[k], wc[k], ar[k]
        z = (wa * az[t] + wb * bz[t] + wc * cz[t]) / ar
        enter = np.where(ar < 0, 1, -1)
        # A crossing counts for every grid point above it.
        ks = np.clip(np.floor((z - oz) / h).astype(np.int64) + 1, 0, nz)
        np.add.at(diff, (i + nx * j, ks), enter)
    wind = np.cumsum(diff[:, :nz], axis=1)  # (columns, nz)
    inside = (wind > 0).T.reshape(nz, ny, nx).transpose(2, 1, 0)
    return inside


def hollow_mesh(V, F, thickness, surface=None):
    """The part hollowed with a wall `thickness` thick: the outside as it
    is, every vertex kept, the inner wall's triangles after them: (V, F,
    vertex map, report)."""
    V = np.asarray(V, dtype=float)
    F = np.asarray(F, dtype=np.int64).reshape(-1, 3)
    nv = len(V)
    if not (thickness > 0) or not np.isfinite(thickness):
        raise M.MeshError("The wall thickness must be more than zero.")
    shut = M.closedness(F, nv)
    if shut["open"] > 0:
        raise M.MeshError(f"The mesh is not closed — {shut['open']:,} open edge{'' if shut['open'] == 1 else 's'}. Hollowing needs a closed part: close it with Fill holes first.")
    before = G.signed_volume(V, F)
    if not before > 0:
        raise M.MeshError("The mesh encloses no volume — is it turned inside out?")
    P = V[np.unique(F)]
    lo, hi = P.min(axis=0), P.max(axis=0)
    h = thickness / 3

    def dims(cell):
        return [int(np.ceil((hi[k] - lo[k]) / cell + 1 + G.JITTER[k])) + 2 for k in range(3)]

    nx, ny, nz = dims(h)
    while nx * ny * nz > MAX_POINTS:
        h *= 1.1
        nx, ny, nz = dims(h)
    o = np.array([lo[k] - h * (1 + G.JITTER[k]) for k in range(3)])

    inside = inside_grid(V, F, nx, ny, nz, o[0], o[1], o[2], h)
    seeds = ~inside
    S = G.spread_points(V, F, h)
    g = np.rint((S - o) / h).astype(np.int64)
    g = g[(g >= 0).all(axis=1) & (g[:, 0] < nx) & (g[:, 1] < ny) & (g[:, 2] < nz)]
    seeds[g[:, 0], g[:, 1], g[:, 2]] = True
    rough = np.sqrt(G.distance_squared(seeds)) * h

    slack = np.sqrt(3) * h + 1.5 * h
    lo_b, hi_b = thickness - slack, thickness + slack
    reach = hi_b + h
    field = rough - thickness
    field[~inside] = -thickness
    band = inside & (rough >= lo_b) & (rough <= hi_b)
    if band.any():
        surface = surface or NominalSurface(V, F)
        idx = np.argwhere(band)
        hits = surface.closest(o + idx * h, max_distance=reach)
        d = np.where(hits.found, hits.distance, reach)
        field[band] = d - thickness

    WV, WF = G.march_tetrahedra(field, o[0], o[1], o[2], h)
    kept, pieces, _ = G.drop_specks(WV, WF, MIN_CAVITY_CELLS * h ** 3, "in")
    if pieces == 0:
        raise M.MeshError(f"Nothing to hollow — the part is nowhere thicker than twice the wall, {float(f'{2 * thickness:.3g}'):g} mm. Take a thinner wall.")
    IV, IF = G.compact_mesh(WV, kept)
    removed = -G.signed_volume(IV, IF)
    allV = np.vstack([V, IV])
    allF = np.vstack([F, IF + nv])
    V2, F2, vmap = M.compact_edit(allV, allF, nv)
    return V2, F2, vmap, {"thickness": thickness, "cell": h, "cavities": pieces, "removed": removed, "volumeBefore": before, "triangles": int(len(IF))}


def unit_move(V, F, thickness):
    """Each vertex's even move for a unit distance (offset.ts evenMove), the
    normals smoothed as for `thickness` — mesh_offset's own move."""
    V2, _F2, vmap, _ = M.offset_mesh(V, F, thickness)
    moved = np.zeros_like(V)
    ok = vmap >= 0
    moved[ok] = V2[vmap[ok]] - V[ok]
    return moved / thickness


def thicken_mesh(V, F, thickness, side="in"):
    """An open surface made a solid (offset.ts thickenMesh): a second skin
    `thickness` from it — side in (the surface stays the outside), out, or
    both — and a wall along each open edge: (V, F, vertex map, report)."""
    if not (thickness > 0) or not np.isfinite(thickness):
        raise M.MeshError("The thickness must be more than zero.")
    V = np.asarray(V, dtype=float)
    F = np.asarray(F, dtype=np.int64).reshape(-1, 3)
    n = len(V)
    unit = unit_move(V, F, thickness)
    front = 0.0 if side == "in" else thickness if side == "out" else thickness / 2
    back = -thickness if side == "in" else 0.0 if side == "out" else -thickness / 2
    front_keeps = back != 0
    fs, bs = V + front * unit, V + back * unit
    allV = np.vstack([fs, bs] if front_keeps else [bs, fs])

    def fi(v):
        return v if front_keeps else v + n

    def bi(v):
        return v + n if front_keeps else v

    a = F.reshape(-1)
    e = F[:, [1, 2, 0]].reshape(-1)
    pairs = set(zip(a.tolist(), e.tolist()))
    rim = [(x, y) for x, y in zip(a.tolist(), e.tolist()) if (y, x) not in pairs]
    wall = []
    for x, y in rim:
        wall += [fi(y), fi(x), bi(x), fi(y), bi(x), bi(y)]
    out = np.vstack([fi(F), bi(F)[:, [0, 2, 1]], np.array(wall, dtype=np.int64).reshape(-1, 3)])
    V2, F2, vmap = M.compact_edit(allV, out, n)
    return V2, F2, vmap, {"thickness": thickness, "side": side, "triangles": int(len(out) - len(F)), "rimEdges": len(rim), "relaxed": 0, "merged": 0}


def hollow_status(r):
    pct = f" ({100 * r['removed'] / r['volumeBefore']:.0f} %)" if r["volumeBefore"] else ""
    return (f"Hollowed with a {r['thickness']:g} mm wall — {r['cavities']} {'cavity' if r['cavities'] == 1 else 'cavities'}, {r['removed']:.1f} mm³ of material out{pct}, "
            f"an inner wall of {r['triangles']:,} triangles. Where the part is thinner than {2 * r['thickness']:g} mm it stays solid.")


def thicken_status(r):
    way = "outward" if r["side"] == "out" else "to both sides" if r["side"] == "both" else "inward"
    return f"Thickened {r['thickness']:g} mm {way} — a second skin and a wall round {r['rimEdges']:,} open edges, {r['triangles']:,} triangles."
