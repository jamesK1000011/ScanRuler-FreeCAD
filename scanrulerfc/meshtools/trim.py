# SPDX-License-Identifier: AGPL-3.0-only
# Ported from ScanRuler by CNC Kitchen (Stefan Hermann):
# plugins/mesh-tools/core/trimToScan.ts, plugins/mesh-tools/core/breakSurface.ts
# and plugins/mesh-tools/core/extendRim.ts
#
# Trim to scan: a body modelled to mend a broken part, cut to fit the scanned
# break — the missing piece, to print and glue in. The body is modelled to
# the part's nominal shape, made a few millimetres too long at the break so
# it overlaps the material still there, and cut here with the fracture
# itself: the break is found (the scan where it lies deeper in the body than
# a depth), carried on past the body, thickened to each side into a thin
# closed slab, and the body minus the slab falls into pieces; those on the
# side the break's normals point to — towards the missing piece — are kept.
# Their face cut by the slab, the mating face, is the fracture moved the
# offset off it: 0 to cut on the break, a tenth or two to leave room for
# glue. A slab is never thinner than 0.02 mm.
#
# Finding the break and carrying it out are pure numpy here, as the original
# is pure TypeScript. The cut is a boolean: ScanRuler's Manifold tells the
# slab's two skins apart by a vertex property carried through the cut; here
# the kernel is FreeCAD's Mesh booleans (behind a lazy import — without
# FreeCAD the trim refuses), and each triangle of the result is told apart
# by where it lies: on the body's own surface, on the slab's front skin, on
# its back skin, or on its rim wall. A hollow's inner wall stays with the
# solid round it, as Manifold's pieces keep it; where FreeCAD's kernel drops
# a sealed shell the slab never meets, it is put back.

import numpy as np

from .. import mesh_core as M
from ..dev_surface import NominalSurface
from . import boolean as B
from . import grid as G
from .shell import thicken_mesh

DEFAULT_BREAK_DEPTH = 0.3
SNAP_SHARE = 0.1
MIN_HALF = 0.01
CLEARANCE = 0.25
SPECK_SHARE = 1e-4
NORMAL_REACH = 1
NORMAL_EDGES = 3
RIM_PASSES = 10
HOLD_SPAN = 3
BAY_EDGES = 2


def default_break_speck(body_diagonal):
    return M.round125(body_diagonal * 0.05)


def _area(V, F):
    if len(F) == 0:
        return 0.0
    return float(np.linalg.norm(np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]]), axis=1).sum() / 2)


def _mean_edge(V, F):
    e = np.concatenate([V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 1]], V[F[:, 0]] - V[F[:, 2]]])
    return float(np.linalg.norm(e, axis=1).mean()) if len(e) else 0.0


# ---- the break (breakSurface.ts) -------------------------------------------------------

def _clip_below(V, F, nv, field, halfway):
    side = np.sign(field).astype(np.int64)
    extra, crossings = [], {}

    def crossing(p, q):
        k = (min(p, q), max(p, q))
        if k in crossings:
            return crossings[k]
        t = 0.5 if halfway is not None and (halfway[p] or halfway[q]) else field[p] / (field[p] - field[q])
        extra.append(V[p] + t * (V[q] - V[p]))
        crossings[k] = nv + len(extra) - 1
        return crossings[k]

    s = side[F]
    keep = (s <= 0).all(axis=1) & ~(s >= 0).all(axis=1)
    out = [F[keep]]
    mixed = ~(s >= 0).all(axis=1) & ~(s <= 0).all(axis=1)
    poly_tris = []
    for t in np.nonzero(mixed)[0].tolist():
        c = F[t].tolist()
        poly = []
        for k in range(3):
            p, q = c[k], c[(k + 1) % 3]
            if side[p] <= 0:
                poly.append(p)
            if side[p] * side[q] < 0:
                poly.append(crossing(p, q))
        for k in range(1, len(poly) - 1):
            poly_tris.append([poly[0], poly[k], poly[k + 1]])
    out.append(np.array(poly_tris, dtype=np.int64).reshape(-1, 3))
    allV = np.vstack([V, np.array(extra).reshape(-1, 3)])
    allF = np.vstack(out)
    return M.compact_edit(allV, allF, nv)


def find_break(V, F, body, depth, marked=None, min_piece=1.0):
    """The scan where it lies deeper in the body (a NominalSurface) than
    depth, narrowed to the marked vertices if given, specks dropped:
    (V, F, scan vertices in it, deep flags, report)."""
    if not (depth > 0) or not np.isfinite(depth):
        raise M.MeshError("The depth must be more than zero.")
    V = np.asarray(V, dtype=float)
    F = np.asarray(F, dtype=np.int64).reshape(-1, 3)
    nv = len(V)
    edge = _mean_edge(V, F)
    snap = SNAP_SHARE * edge
    outside = max(edge, depth)
    allowed = None
    if marked is not None:
        allowed = np.zeros(nv, dtype=bool)
        m = np.asarray(marked, dtype=np.int64)
        allowed[m[m < nv]] = True
    cut_away = np.zeros(nv, dtype=bool) if allowed is not None else None
    field = np.full(nv, float(outside))
    pad = depth + 4 * edge
    near = ((V >= body.bbox_min - pad) & (V <= body.bbox_max + pad)).all(axis=1)
    rows = np.nonzero(near)[0]
    if len(rows):
        s = body.closest(V[rows]).signed + depth
        if cut_away is not None:
            away = ~allowed[rows] & (s < 0)
            cut_away[rows[away]] = True
            rows, s = rows[~away], s[~away]
        field[rows] = np.where(np.abs(s) < snap, 0, s)
    CV, CF, vmap = _clip_below(V, F, nv, field, cut_away)
    if len(CF) == 0:
        raise M.MeshError(f"Nothing marked lies more than {depth:g} mm inside the body — mark the break where the body reaches into the part." if marked is not None
                          else f"The scan nowhere lies more than {depth:g} mm inside the body — is the body in place over the break, reaching into the part?")
    survey, mask, _ = M.survey_pieces(CV, CF, min_piece)
    if survey["islands"] == survey["pieces"]:
        raise M.MeshError(f"What lies more than {depth:g} mm inside the body is only specks, none {min_piece:g} mm across — is the body in place over the break?")
    if survey["islands"]:
        KV, KF, kmap = M.without_triangles(CV, CF, mask)
        vmap = np.where(vmap >= 0, kmap[np.maximum(vmap, 0)], -1)
        CV, CF = KV, KF
    in_break = np.nonzero(vmap >= 0)[0]
    deep = np.zeros(len(CV), dtype=bool)
    deep[vmap[in_break]] = field[in_break] < 0
    report = {"depth": depth, "marked": None if marked is None else int(len(marked)), "triangles": int(len(CF)), "area": _area(CV, CF),
              "pieces": survey["pieces"] - survey["islands"], "specks": survey["islands"]}
    return CV, CF, in_break, deep, report


# ---- carried out past the body (extendRim.ts) ------------------------------------------

def _unit(v):
    L = np.linalg.norm(v, axis=-1, keepdims=True)
    return np.where(L > 0, v / np.where(L > 0, L, 1), 0)


def _smooth_loop(vals, passes):
    cur = np.asarray(vals, dtype=float)
    for _ in range(passes):
        cur = (np.roll(cur, 1, axis=0) + 2 * cur + np.roll(cur, -1, axis=0)) / 4
    return cur


def _shut_bays(V, F, nv, deep):
    pos = [list(p) for p in V.tolist()]
    out = F.tolist()
    edge = _mean_edge(V, F)

    def is_deep(v):
        return v < len(deep) and bool(deep[v])

    def point(v):
        return np.array(pos[v])

    def add(q):
        pos.append(list(map(float, q)))
        return len(pos) - 1

    bays = 0
    loops, _ = M.boundary_loops(F, nv)
    for verts, opp in loops:
        n = len(verts)

        def v(i):
            return verts[i % n]

        def own(i):
            return is_deep(v(i)) and is_deep(v(i + 1))

        taken = [False] * n
        for s in range(n):
            if own(s - 1) or not own(s):
                continue
            e = s
            while own(e) and e < s + n:
                e += 1
            run = e - s
            if run < BAY_EDGES or run + 4 > n:
                continue
            if any(taken[i % n] for i in range(s - 1, e + 2)):
                continue
            pv, a, b, nxt = v(s - 1), v(s), v(e), v(e + 1)
            facing = np.zeros(3)
            for i in range(s, e):
                facing += np.cross(point(v(i + 1)) - point(v(i)), point(opp[i % n]) - point(v(i)))
            turn = np.zeros(3)
            for i in range(s, e + 1):
                turn += np.cross(point(v(i)), point(a if i == e else v(i + 1)))
            if turn @ facing >= 0:
                continue
            A, Bp = point(a), point(b)
            across = Bp - A
            width = float(np.linalg.norm(across))
            if width == 0:
                continue
            outward = _unit(np.cross(across, _unit(facing)))
            m = max(2, int(np.ceil(width / edge)))
            lift = min(edge, width / m) / 2
            c, o = [a], [pv]
            for j in range(1, m):
                q = A + across * j / m
                c.append(add(q))
                o.append(add(q + lift * outward))
            c.append(b)
            o.append(nxt)
            out.append([a, pv, o[1]])
            for j in range(m):
                if j < m - 1:
                    out.append([c[j + 1], c[j], o[max(1, j)]])
                else:
                    out.append([b, c[j], o[j]])
                if 0 < j < m - 1:
                    out.append([c[j + 1], o[j], o[j + 1]])
            out.append([nxt, b, o[m - 1]])
            for i in range(s - 1, e + 2):
                taken[i % n] = True
            bays += 1
    return np.array(pos, dtype=float), np.array(out, dtype=np.int64).reshape(-1, 3), bays


def _outer_rims(V, F):
    lab = M.components(F, len(V))
    loops, _ = M.boundary_loops(F, len(V))
    largest = {}
    for li, (verts, _) in enumerate(loops):
        piece = lab[verts[0]]
        size = M.loop_size(V, verts)
        if piece not in largest or size > largest[piece][1]:
            largest[piece] = (li, size)
    pieces = set(lab[F[:, 0]].tolist())
    if len(largest) < len(pieces):
        raise M.MeshError("Part of the break is closed all round, with no edge to carry out past the body — it cannot cut anything.")
    rims = {li for li, _ in largest.values()}
    return [l for i, l in enumerate(loops) if i in rims], [l for i, l in enumerate(loops) if i not in rims]


def extend_rim(V, F, body, margin, deep=None):
    """The break carried on past the body: holes in it closed, its outer
    rims carried out until they are margin outside the body: (V, F, report)."""
    if not (margin > 0) or not np.isfinite(margin):
        raise M.MeshError("The margin must be more than zero.")
    p, idx = np.asarray(V, dtype=float), np.asarray(F, dtype=np.int64)
    bays = 0
    if deep is not None:
        p, idx, bays = _shut_bays(p, idx, len(p), deep)
    rims, holes = _outer_rims(p, idx)
    for verts, _ in holes:
        size = M.loop_size(p, verts)
        try:
            p, idx, _, _ = M.fill_holes(p, idx, size * 1.001 + 1e-6, "curved", p[verts].mean(axis=0).tolist())
        except M.MeshError:
            raise M.MeshError(f"A hole in the break, {size:.1f} mm across, could not be closed — close it on the scan with Fill holes, or mark the break across it.")
    if holes:
        rims, _ = _outer_rims(p, idx)
    edge = _mean_edge(p, idx)
    reach = max(NORMAL_REACH, NORMAL_EDGES * edge)
    T = p[idx]
    area = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
    centre = T.mean(axis=1)

    def normal_around(Q):
        out = np.zeros_like(Q)
        for s in range(0, len(Q), 256):
            d = np.linalg.norm(centre[None] - Q[s:s + 256, None], axis=2)
            out[s:s + 256] = (d <= reach).astype(float) @ area
        return _unit(out)

    pos, out = [p], [idx]
    count_v = len(p)
    step = min(edge, margin) / 4
    limit = body.bbox_diagonal + margin
    rows = 0
    shortest, longest = np.inf, 0.0
    for verts, opp in rims:
        verts = np.asarray(verts)
        n = len(verts)
        at = p[verts]
        e = np.roll(at, -1, axis=0) - at
        f = p[np.asarray(opp)] - at
        away = _unit(np.cross(e, _unit(np.cross(e, f))))
        outs = away + np.roll(away, 1, axis=0)
        normals = _unit(_smooth_loop(normal_around(at), RIM_PASSES))
        d = _smooth_loop(_unit(outs), RIM_PASSES)
        d = _unit(d - np.einsum("ij,ij->i", d, normals)[:, None] * normals)
        need = np.full(n, np.nan)
        s = step
        while np.isnan(need).any() and s <= limit:
            todo = np.nonzero(np.isnan(need))[0]
            sig = body.closest(at[todo] + s * d[todo]).signed
            need[todo[sig > margin]] = s
            s += step
        if np.isnan(need).any():
            raise M.MeshError("Part of the break’s edge does not come out of the body when carried on along the fracture — mark the break out to where the part’s surface leaves the body.")
        held = np.max(np.stack([np.roll(need, k) for k in range(-HOLD_SPAN, HOLD_SPAN + 1)]), axis=0)
        shortest, longest = min(shortest, float(held.min())), max(longest, float(held.max()))
        count = max(1, int(np.ceil(held.max() / edge)))
        rows = max(rows, count)
        prev = verts
        for r in range(1, count + 1):
            row = count_v + np.arange(n)
            pos.append(at + (held * r / count)[:, None] * d)
            count_v += n
            j = np.roll(np.arange(n), -1)
            out.append(np.stack([prev[j], prev, row, prev[j], row, row[j]], axis=1).reshape(-1, 3))
            prev = row
    report = {"rims": len(rims), "holes": len(holes), "bays": bays, "rows": rows, "shortest": float(shortest) if np.isfinite(shortest) else 0.0, "longest": longest}
    return np.vstack(pos), np.vstack(out), report


# ---- the trim (trimToScan.ts) ----------------------------------------------------------

def prepare_body(V, F, name=None):
    """The body welded and checked closed: (V, F, signed surface, volume)."""
    BV, BF = B.closed_tool(V, F, name or "The body")
    return BV, BF, NominalSurface(BV, BF), B.volume(BV, BF)


def _spread(values):
    read = np.sort(values[np.isfinite(values)])
    if len(read) == 0:
        return None

    def q(f):
        return float(read[min(len(read) - 1, int(round(f * (len(read) - 1))))])

    return {"min": float(read[0]), "p05": q(0.05), "median": q(0.5), "p95": q(0.95), "max": float(read[-1]), "measured": int(len(read))}


LAST_CUT = {}  # what the last cut's kernel handed back, read by the tests when FreeCAD's answer is not the one expected


def _solids(V, F, tol):
    """The kernel's result as solids: points it gave twice in single
    precision merged, and patches that only touch along a T-junction seam
    (FreeCAD's cuts leave them) taken as the one solid they bound — a patch
    joins another when its open edge's points lie on it."""
    V, F = B.weld(V, F, tol)
    pieces = B.pieces_of(V, F)
    opened = [i for i, (PV, PF) in enumerate(pieces) if M.closedness(PF, len(PV))["open"]]
    lab = list(range(len(pieces)))

    def root(i):
        while lab[i] != i:
            i = lab[i]
        return i

    for i in opened:
        PV, PF = pieces[i]
        loops, _ = M.boundary_loops(PF, len(PV))
        rim = PV[np.unique(np.concatenate([np.asarray(l) for l, _ in loops]))] if loops else PV[:0]
        for j in opened:
            if j == i or root(i) == root(j) or not len(rim):
                continue
            near, _, _, _ = G.NearSurface(*pieces[j], tol * 10).nearest(rim)
            if near.any():
                lab[root(i)] = root(j)
    out = {}
    for i, piece in enumerate(pieces):
        out.setdefault(root(i), []).append(piece)
    solids = []
    for group in out.values():
        Vs, Fs, off = [], [], 0
        for PV, PF in group:
            Vs.append(PV)
            Fs.append(PF + off)
            off += len(PV)
        solids.append((np.vstack(Vs), np.vstack(Fs)))
    return solids


def _restore_sealed(BV, BF, SV, SF, RV, RF, eps):
    """The body's sealed shells the slab never meets — a hollow's inner wall
    — put back where the kernel's answer lost them: FreeCAD's mesh booleans
    drop a closed shell that meets nothing of the other mesh, where
    Manifold carries it through the cut. (RV, RF, shells put back)."""
    shells = B.pieces_of(BV, BF)
    if len(shells) < 2:
        return RV, RF, 0
    c = RV[RF].mean(axis=1) if len(RF) else RV[:0]
    Vs, Fs, off, back = [RV], [RF], len(RV), 0
    for PV, PF in shells:
        if len(c) and G.NearSurface(PV, PF, eps).nearest(c)[0].any():
            continue  # some of it came back: the kernel kept it
        if B.winding(SV, SF, PV[0]) > 0.5 or G.NearSurface(SV, SF, eps).nearest(PV)[0].any():
            continue  # the slab meets it: the cut took it, and rightly
        Vs.append(PV)
        Fs.append(PF + off)
        off += len(PV)
        back += 1
    if not back:
        return RV, RF, 0
    return np.vstack(Vs), np.vstack(Fs), back


def _nested(solids):
    """Solids with each hollow's wall — a closed piece faced inward, its
    signed volume below zero — taken as part of the smallest solid round it,
    as Manifold keeps a hollow in the solid it lies in. A piece faced
    inward that nothing holds stays its own (wound inside out)."""
    vols = [B.volume(PV, PF) for PV, PF in solids]
    closed = [M.closedness(PF, len(PV))["open"] == 0 for PV, PF in solids]
    into = list(range(len(solids)))
    for i, (PV, PF) in enumerate(solids):
        if not (closed[i] and vols[i] < 0):
            continue
        round_it = [j for j in range(len(solids)) if j != i and vols[j] > 0 and abs(B.winding(*solids[j], PV[0])) > 0.5]
        if round_it:
            into[i] = min(round_it, key=lambda j: vols[j])
    out = []
    for j in range(len(solids)):
        if into[j] != j:
            continue
        group = [solids[j]] + [solids[i] for i in range(len(solids)) if into[i] == j and i != j]
        Vs, Fs, off = [], [], 0
        for PV, PF in group:
            Vs.append(PV)
            Fs.append(PF + off)
            off += len(PV)
        out.append((np.vstack(Vs), np.vstack(Fs)))
    return out


def _cut_body(kernel, BV, BF, body_volume, SV, SF, n_front, flip):
    """The body minus the slab, the pieces on the kept side, one mesh with
    its mating face marked. SF's first n_front triangles are its front skin,
    the next n_front its back skin, the rest its rim wall."""
    LAST_CUT.clear()
    LAST_CUT.update({"slabVolume": B.volume(SV, SF), "slabClosed": M.closedness(SF, len(SV)), "flip": flip, "pieces": []})
    try:
        RV, RF = kernel("subtract", (BV, BF), (SV, SF))
    except Exception as e:  # the kernel's own failure, in its words
        raise M.MeshError(f"FreeCAD's mesh boolean would not take the break as a slab to cut with ({e}). A larger offset can help, or the break smoothed first — Smooth on a marked region.")
    RV = np.asarray(RV, dtype=float)
    RF = np.asarray(RF, dtype=np.int64).reshape(-1, 3)
    LAST_CUT.update({"result": (len(RV), len(RF)), "resultVolume": B.volume(RV, RF), "resultClosed": M.closedness(RF, len(RV))})
    pts = np.vstack([BV, SV])
    tol = max(1e-6, 1e-6 * float(np.linalg.norm(pts.max(axis=0) - pts.min(axis=0))))  # the kernel's points come back in single precision
    eps = 1e-3
    on_body = G.NearSurface(BV, BF, eps)
    on_slab = G.NearSurface(SV, SF, eps)
    RV, RF, restored = _restore_sealed(BV, BF, SV, SF, RV, RF, eps)
    LAST_CUT["restored"] = restored
    speck = SPECK_SHARE * body_volume
    kept, volume, dropped, specks = [], 0.0, 0, 0
    for PV, PF in _nested(_solids(RV, RF, tol)):
        v = B.volume(PV, PF)
        c = PV[PF].mean(axis=1)
        fb, _, _, _ = on_body.nearest(c)
        fs, _, _, tri = on_slab.nearest(c)
        cut = fs & ~fb
        kind = np.where(tri < n_front, 1, np.where(tri < 2 * n_front, -1, 0))
        ahead = int((cut & (kind == 1)).sum())
        behind = int((cut & (kind == -1)).sum())
        wall = int((cut & (kind == 0)).sum())
        LAST_CUT["pieces"].append({"volume": round(v, 3), "triangles": len(PF), "open": M.closedness(PF, len(PV))["open"], "body": int(fb.sum()),
                                   "front": ahead, "back": behind, "wall": wall, "neither": int((~fb & ~fs).sum())})
        v = abs(v)  # a piece wound inside out is still that much material
        if v < speck:
            specks += 1
            continue
        if wall > 0:
            raise M.MeshError("The break, carried out past the body, still ends inside it somewhere — the cut would not go through. Mark the break out to where the part’s surface leaves the body.")
        if ahead > 0 and behind > 0:
            raise M.MeshError("The break does not cut the body through: somewhere the body overlaps the part where there is no break to cut it — the scan has a gap there, or the marking stops short. Mark the whole break, out to the body’s edges.")
        if (ahead if flip else behind) > 0:
            dropped += 1
            continue
        kept.append((PV, PF, cut))
        volume += v
    if not kept:
        raise M.MeshError("Nothing of the body lies on that side of the break — flip the side back." if flip else "Nothing of the body lies on the missing piece’s side of the break — flip the side.")
    Vs, Fs, Ms, off = [], [], [], 0
    for PV, PF, cut in kept:
        Vs.append(PV)
        Fs.append(PF + off)
        Ms.append(cut)
        off += len(PV)
    V, F, mating = np.vstack(Vs), np.vstack(Fs), np.concatenate(Ms)
    return V, F, mating, _area(V, F[mating]), len(kept), volume, dropped, specks


def _gap_to_break(V, F, mating, BRV, BRF, scan_surface, half, flip):
    gap = np.full(len(V), np.nan)
    on_face = np.zeros(len(V), dtype=bool)
    on_face[F[mating].reshape(-1)] = True
    rows = np.nonzero(on_face)[0]
    if not len(rows):
        return gap
    a, b = BRF.reshape(-1), BRF[:, [1, 2, 0]].reshape(-1)
    k = np.minimum(a, b) * len(BRV) + np.maximum(a, b)
    uniq, cnt = np.unique(k, return_counts=True)
    single = set(uniq[cnt == 1].tolist())
    brk = NominalSurface(BRV, BRF)
    hit = brk.closest(V[rows])
    rim = np.zeros(len(rows), dtype=bool)
    for r in range(len(rows)):
        f = hit.face[r]
        if f < 0:
            rim[r] = True
            continue
        x = hit.point[r]
        for kk in range(3):
            pa, pb = int(BRF[f, kk]), int(BRF[f, (kk + 1) % 3])
            if min(pa, pb) * len(BRV) + max(pa, pb) not in single:
                continue
            A, E = BRV[pa], BRV[pb] - BRV[pa]
            L2 = float(E @ E)
            if L2 == 0:
                rim[r] = True
                break
            s = min(1, max(0, float((x - A) @ E) / L2))
            dd = x - A - s * E
            if float(dd @ dd) < 1e-10 * L2:
                rim[r] = True
                break
    use = rows[~rim]
    if len(use):
        sg = scan_surface.closest(V[use]).signed
        gap[use] = (-sg if flip else sg) - half
    return gap


def trim_to_scan(SV, SF, body, depth=DEFAULT_BREAK_DEPTH, offset=0.0, flip=False, marked=None, kernel=None):
    """The body (prepare_body's) cut to fit the scan's break: (V, F, mating
    mask, gap per vertex, report)."""
    BV, BF, bsurf, bvol = body
    if not (offset >= 0) or not np.isfinite(offset):
        raise M.MeshError("The offset from the break must be zero or more.")
    half = max(offset, MIN_HALF)
    SV = np.asarray(SV, dtype=float)
    SF = np.asarray(SF, dtype=np.int64).reshape(-1, 3)
    FV, FF, _verts, deep, brep = find_break(SV, SF, bsurf, depth, marked, default_break_speck(bsurf.bbox_diagonal))
    EV, EF, erep = extend_rim(FV, FF, bsurf, M.MAX_STRETCH * half + CLEARANCE, deep)
    slabV, slabF, _vm, _ = thicken_mesh(EV, EF, 2 * half, "both")
    kernel = kernel or B.freecad_kernel()
    if kernel is None:
        raise B.NeedsKernel("Trim to scan cuts the body with a boolean, which needs FreeCAD's Mesh booleans — FreeCAD is not loaded here; run it inside FreeCAD (through Agent Link).")
    V, F, mating, mating_area, pieces, volume, dropped, specks = _cut_body(kernel, BV, BF, bvol, slabV, slabF, len(EF), flip)
    gap = _gap_to_break(V, F, mating, FV, FF, NominalSurface(SV, SF), half, flip)
    report = {"offset": offset, "slab": 2 * half, "break": brep, "extend": erep, "pieces": pieces, "volume": volume, "dropped": dropped, "specks": specks,
              "matingArea": mating_area, "bodyVolume": bvol, "fit": _spread(gap)}
    return V, F, mating, gap, report
