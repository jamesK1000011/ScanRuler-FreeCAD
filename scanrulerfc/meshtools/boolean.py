# SPDX-License-Identifier: AGPL-3.0-only
# Ported from ScanRuler by CNC Kitchen (Stefan Hermann):
# plugins/mesh-tools/core/boolean.ts
#
# The scan and a solid made one: the solid taken out of the scan, added to
# it, or only what the two have in common kept — a bore the scanner could not
# see to the bottom of cut out with a cylinder fitted where it could, a boss
# put back, a part trimmed to a box. Several solids go as one, their union.
#
# ScanRuler's boolean is Manifold's (Apache-2.0, in WebAssembly). Here the
# kernel is meshbool.py, in numpy alone: every crossing decided once by one
# orientation sign, so the seam is closed by construction and a dense scan
# keeps every triangle the solid does not touch. (It was FreeCAD's Mesh
# booleans — Mesh.unite / difference / intersect — until they came back open
# and inside out on a 140,698-triangle scan minus a 5,212-triangle cutter;
# freecad_kernel and outward stay for a caller that asks for them.)
# Everything round the kernel is the original's: both meshes must be closed,
# and it says so up front; the result is an edit like any other — the scan's
# own vertices that are left keep their order and come first; and a solid
# that does nothing anyone would want — taken away but never reaching the
# mesh, or lying wholly inside it and sealing a hollow there; added wholly
# inside it — is refused, naming it. As in the original, that is read off how
# much of each piece's surface is in the result (none of a piece taken away
# that missed or of one added inside, all of one taken away from inside).
# Manifold tags each result triangle with the solid it came from; the kernel
# here keeps no such tag, so a result triangle is the piece's when it lies on
# the piece's surface and not on the mesh's. A kernel that drops a shell
# meeting nothing leaves none of the piece either way; then one of its
# points, inside the mesh or not, tells which.

import numpy as np

from .. import mesh_core as M

SHARE_NONE = 1e-4


class NeedsKernel(M.MeshError):
    """No boolean kernel here: the tool needs FreeCAD."""


def mesh_kernel():
    """meshbool's boolean as kernel(op, (V, F), (V, F)) -> (V, F): numpy
    only, closed and faced outward, or a MeshError saying why not."""
    from . import meshbool as MB

    def run(op, a, b):
        try:
            V, F, _, _ = MB.boolean(a[0], a[1], b[0], b[1], op)
        except MB.BooleanError as e:
            raise M.MeshError(f"The boolean did not come out closed ({e}) — a solid that only grazes the mesh can do this; move it a little and try again.")
        return V, F

    return run


def freecad_kernel():
    """FreeCAD's Mesh booleans as kernel(op, (V, F), (V, F)) -> (V, F), or
    None outside FreeCAD."""
    try:
        import Mesh  # noqa: F401
    except ImportError:
        return None

    def to_mesh(V, F):
        m = Mesh.Mesh()
        m.addFacets([[tuple(map(float, V[i])) for i in t] for t in np.asarray(F).tolist()])
        return m

    def run(op, a, b):
        ma, mb = to_mesh(*a), to_mesh(*b)
        out = ma.unite(mb) if op == "add" else ma.difference(mb) if op == "subtract" else ma.intersect(mb)
        out.harmonizeNormals()  # each piece wound one way; outward() picks which
        pts, tris = out.Topology
        V = np.array([[p.x, p.y, p.z] for p in pts], dtype=float).reshape(-1, 3)
        return outward(V, np.array(tris, dtype=np.int64).reshape(-1, 3))

    return run


def outward(V, F):
    """A mesh from FreeCAD's mesh kernel faced outward. Its booleans can hand
    back a correct result wound inside out (a difference does, in FreeCAD
    1.0 to 1.1), and Mesh.harmonizeNormals only makes each piece agree with
    itself. So each closed piece is turned to face outward from what it
    bounds: away from its inside when it lies inside an even number of the
    other pieces (none, mostly), toward it — a hollow's wall — when inside
    an odd number. A piece that is open by its edges — FreeCAD's cut seams
    often meet in T-junctions, so a solid comes back as patches that touch
    without sharing edges — is turned patch by patch, by which way its
    largest triangles face: a point just off a triangle, on the side it
    faces, is outside the material when a ray from it crosses the whole
    result an even number of times, whatever way anything is wound."""
    V = np.asarray(V, dtype=float)
    F = np.asarray(F, dtype=np.int64).reshape(-1, 3).copy()
    if len(F) == 0:
        return V, F
    lab = M.components(F, len(V))[F[:, 0]]
    groups = [np.nonzero(lab == r)[0] for r in np.unique(lab).tolist()]
    closed = [M.closedness(F[g], len(V))["open"] == 0 for g in groups]
    shells = [g for g, c in zip(groups, closed) if c]
    for i, g in enumerate(shells):
        v = volume(V, F[g])
        if v == 0:
            continue
        p = V[F[g[0], 0]]
        depth = sum(abs(winding(V, F[h], p)) > 0.5 for j, h in enumerate(shells) if j != i)
        if (v > 0) == (depth % 2 == 1):
            F[g] = F[g][:, ::-1]
    patches = [g for g, c in zip(groups, closed) if not c]
    if patches:
        T0 = V[F]
        off = 1e-4 * float(np.linalg.norm(V.max(axis=0) - V.min(axis=0)))
        for g in patches:
            for h in edge_patches(F[g]):
                if facing_in(V, F[g[h]], T0, off):
                    F[g[h]] = F[g[h]][:, ::-1]
    return V, F


def edge_patches(F):
    """The triangles of F grouped by shared edges (a T-junction or a lone
    shared point does not join them): a list of index arrays."""
    F = np.asarray(F, dtype=np.int64).reshape(-1, 3)
    a, b = F.reshape(-1), F[:, [1, 2, 0]].reshape(-1)
    key = np.minimum(a, b) * (int(F.max()) + 1) + np.maximum(a, b)
    tri = np.repeat(np.arange(len(F)), 3)
    order = np.argsort(key, kind="stable")
    same = key[order][1:] == key[order][:-1]
    pairs = np.stack([tri[order][:-1][same], tri[order][1:][same]], axis=1)
    lab = M.components(pairs[:, [0, 1, 1]], len(F)) if len(pairs) else np.arange(len(F))
    return [np.nonzero(lab == r)[0] for r in np.unique(lab).tolist()]


RAY = np.array([0.5773, 0.6181, 0.5331])  # off every axis and diagonal, so it meets no edge of a gridded part head on


def crossings(T, p, d=RAY):
    """How many of the triangles T (k, 3, 3) a ray from p along d crosses."""
    e1, e2 = T[:, 1] - T[:, 0], T[:, 2] - T[:, 0]
    h = np.cross(d, e2)
    a = np.einsum("ij,ij->i", e1, h)
    ok = np.abs(a) > 1e-12
    f = np.where(ok, 1.0 / np.where(ok, a, 1.0), 0.0)
    s = p - T[:, 0]
    u = f * np.einsum("ij,ij->i", s, h)
    q = np.cross(s, e1)
    v = f * (q @ d)
    t = f * np.einsum("ij,ij->i", e2, q)
    return int((ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 0)).sum())


def facing_in(V, Fg, T_all, off, votes=5):
    """Whether a patch's triangles mostly face into the material bounded by
    all of T_all: up to `votes` of its largest triangles asked."""
    T = V[Fg]
    n = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
    size = np.linalg.norm(n, axis=1)
    inward = 0
    asked = np.argsort(-size)[:votes]
    asked = asked[size[asked] > 0]
    for i in asked:
        p = T[i].mean(axis=0) + off * n[i] / size[i]
        inward += crossings(T_all, p) % 2
    return 2 * inward > len(asked)


def subject_of(names):
    """The tools a piece of their union is made of, as a sentence's subject,
    and whether the verb takes the plural."""
    names = list(names)
    if not names:
        return "The solid", False
    if len(names) == 1:
        return names[0], False
    return f"{', '.join(names[:-1])} and {names[-1]}", True


def describe_open(c, what, fix):
    if c["open"] == 0 and c["bad"] == 0:
        return None
    parts = []
    if c["open"] > 0:
        parts.append(f"{c['open']:,} open edge{'' if c['open'] == 1 else 's'}")
    if c["bad"] > 0:
        parts.append(f"{c['bad']:,} edge{'' if c['bad'] == 1 else 's'} shared by more than two triangles")
    return f"{what} is not closed — {' and '.join(parts)}. A boolean needs a closed mesh: {fix}"


def weld(V, F, tol=1e-6):
    """A CAD body's mesh, face by face, made one: coincident points merged."""
    from ..dev_surface import weld as _weld

    return _weld(V, F, tol)


def volume(V, F):
    F = np.asarray(F, dtype=np.int64).reshape(-1, 3)
    if len(F) == 0:
        return 0.0
    t = np.asarray(V, dtype=float)[F]
    return float(np.einsum("ij,ij->i", t[:, 0], np.cross(t[:, 1], t[:, 2])).sum() / 6)


def _area(V, F):
    t = np.asarray(V, dtype=float)[np.asarray(F, dtype=np.int64).reshape(-1, 3)]
    return np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1) / 2


def surface_share(RV, RF, piece, subject):
    """How much of a tool piece's surface is in the result: the area of the
    result's triangles lying on the piece's surface and not on the subject's,
    over the piece's own area."""
    from . import grid as G

    PV, PF = piece
    RF = np.asarray(RF, dtype=np.int64).reshape(-1, 3)
    whole = float(_area(PV, PF).sum())
    if len(RF) == 0 or whole <= 0:
        return 0.0
    pts = np.vstack([np.asarray(PV, dtype=float), np.asarray(subject[0], dtype=float)])
    diag = float(np.linalg.norm(pts.max(axis=0) - pts.min(axis=0)))
    tol = max(1e-6, 1e-5 * diag)  # the kernel's points come back in single precision
    c = np.asarray(RV, dtype=float)[RF].mean(axis=1)
    on_piece, _, _, _ = G.NearSurface(PV, PF, tol).nearest(c)
    on_subject, _, _, _ = G.NearSurface(*subject, tol).nearest(c)
    mine = on_piece & ~on_subject
    return float(_area(RV, RF[mine]).sum()) / whole


def winding(V, F, p):
    """The winding number of a closed mesh round a point: 1 inside, 0 out."""
    t = np.asarray(V, dtype=float)[np.asarray(F, dtype=np.int64).reshape(-1, 3)] - np.asarray(p, dtype=float)
    a, b, c = t[:, 0], t[:, 1], t[:, 2]
    la, lb, lc = (np.linalg.norm(x, axis=1) for x in (a, b, c))
    num = np.einsum("ij,ij->i", a, np.cross(b, c))
    den = la * lb * lc + np.einsum("ij,ij->i", a, b) * lc + np.einsum("ij,ij->i", b, c) * la + np.einsum("ij,ij->i", c, a) * lb
    return float(2 * np.arctan2(num, den).sum() / (4 * np.pi))


def pieces_of(V, F):
    """A mesh's connected pieces, each its own (V, F)."""
    lab = M.components(F, len(V))
    out = []
    for r in np.unique(lab[F[:, 0]]).tolist():
        sel = lab[F[:, 0]] == r
        V2, F2, _ = M.compact_edit(V, F[sel], 0)
        out.append((V2, F2))
    return out


def closed_tool(V, F, name):
    """A tool welded and checked closed, or the refusal naming it."""
    V, F = weld(np.asarray(V, dtype=float), np.asarray(F, dtype=np.int64))
    c = M.closedness(F, len(V))
    if len(F) == 0 or c["open"] or c["bad"] or not volume(V, F) > 0:
        who, _ = subject_of([name] if name else [])
        raise M.MeshError(f"{who} did not come out as a closed mesh — is it a solid body, not a surface?")
    return V, F


def carry_vertices(SV, nv, RV, RF):
    """The result's vertices as the subject's where one came back at its
    place (each subject vertex once), else new ones after them: (V, F,
    vertex map, triangles kept whole)."""
    key32 = np.ascontiguousarray(np.asarray(SV, dtype=np.float32)).view(np.dtype((np.void, 12))).ravel()
    first = {}
    for i, k in enumerate(key32.tolist()):
        first.setdefault(k, i)
    rkey = np.ascontiguousarray(np.asarray(RV, dtype=np.float32)).view(np.dtype((np.void, 12))).ravel()
    index = np.empty(len(RV), dtype=np.int64)
    taken = set()
    fresh = []
    for v, k in enumerate(rkey.tolist()):
        i = first.get(k)
        if i is not None and i < nv and i not in taken:
            taken.add(i)
            index[v] = i
        else:
            index[v] = nv + len(fresh)
            fresh.append(RV[v])
    allV = np.vstack([np.asarray(SV, dtype=float), np.array(fresh, dtype=float).reshape(-1, 3)])
    F2 = index[np.asarray(RF, dtype=np.int64)]
    kept = int((F2 < nv).all(axis=1).sum())
    V3, F3, vmap = M.compact_edit(allV, F2, nv)
    return V3, F3, vmap, kept


def boolean_mesh(V, F, tools, op, kernel=None):
    """The subject (V, F) and the tool solids [(V, F, name)] made one by op —
    subtract, add or intersect — their union taken away, added, or kept
    where the mesh is: (V, F, vertex map, report). kernel defaults to
    meshbool's (mesh_kernel)."""
    if not tools:
        raise M.MeshError("No solid to make one with the mesh.")
    V = np.asarray(V, dtype=float)
    F = np.asarray(F, dtype=np.int64).reshape(-1, 3)
    nv = len(V)
    msg = describe_open(M.closedness(F, nv), "The mesh", "close its holes with Fill holes first.")
    if msg:
        raise M.MeshError(msg)
    solids = [closed_tool(tv, tf, name) for tv, tf, name in tools]
    names = [name for _, _, name in tools]
    kernel = kernel or mesh_kernel()

    union = solids[0]
    for s in solids[1:]:
        union = kernel("add", union, s)
    pieces = pieces_of(*union) if len(solids) > 1 else [union]
    result = kernel(op, (V, F), union)
    RV, RF = result
    if len(RF) == 0:
        raise M.MeshError("The solid and the mesh do not overlap — nothing would be left." if op == "intersect" else "Nothing would be left of the mesh.")
    before, after = volume(V, F), volume(RV, RF)

    if op != "intersect":
        for piece in pieces:
            share = surface_share(RV, RF, piece, (V, F))
            none, all_ = share < SHARE_NONE, share > 1 - SHARE_NONE
            if none and winding(V, F, piece[0][0]) > 0.5:
                # Nothing of it came back, yet it is in the mesh: a kernel
                # that dropped the sealed shell of one taken away from inside.
                none, all_ = op == "add", op == "subtract"
            elif none and op == "add":
                continue  # outside and left out: a kernel that dropped a piece apart
            if not (none or (op == "subtract" and all_)):
                continue
            if len(tools) == 1:
                who_names = [names[0]] if names[0] else []
            else:
                who_names = [n for n, s in zip(names, solids) if n and volume(*kernel("intersect", s, piece)) > 1e-9]
            who, many = subject_of(who_names)
            if op == "subtract" and all_:
                raise M.MeshError(f"{who} {'lie' if many else 'lies'} wholly inside the mesh — taking {'them' if many else 'it'} away would seal a hollow inside the part, not open a hole. Move {'their' if many else 'its'} end out through the surface first.")
            if op == "subtract":
                raise M.MeshError(f"{who} {'do' if many else 'does'} not reach the mesh — there is nothing to take away.")
            raise M.MeshError(f"{who} {'lie' if many else 'lies'} wholly inside the mesh — there is nothing to add.")

    V2, F2, vmap, kept = carry_vertices(V, nv, RV, RF)
    report = {"op": op, "removed": int(len(F) - kept), "added": int(len(RF) - kept), "volumeBefore": before, "volumeAfter": after}
    return V2, F2, vmap, report
