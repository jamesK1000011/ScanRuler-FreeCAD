# SPDX-License-Identifier: AGPL-3.0-only
# Written for ScanRuler for FreeCAD (not in ScanRuler): scan_segment's
# fallback for sparse, CAD-style meshes.
#
# ScanRuler's segmentation (segment.py) grows planes vertex by vertex from
# the flattest places, and so needs a dense scan: a dozen or more vertices
# on every flat patch, with normals of their own. A mesh exported from CAD
# has none of that — a cylinder's cap is a fan of triangles whose only
# vertices sit on its rim, each with a normal halfway between the cap and
# the side — and it finds nothing there. Here the triangles are grouped
# instead: neighbours across an edge that lie in one plane (normals within
# PLANE_DEG, corners within maxRms of each other's plane) are one face, and
# triangles meeting at less than SMOOTH_STRIP_DEG are one smooth strip. A
# strip of several faces whose normals all stand square to one axis and
# whose corners lie on a cylinder within maxRms is a cylinder; every other
# face that is flat within maxRms and at least minArea is a plane.
#
# segment() picks: ScanRuler's vertex growing as it was, and this only when
# that found nothing on a sparse mesh (half or more of its vertices on
# creases, more than maxDeg off a triangle round them: few vertices for the
# area, all on the faces' edges), or when asked for by method.

import math

import numpy as np

from . import segment as SEG
from . import shapes as SH

# Triangles in one plane: their normals within this many degrees.
PLANE_DEG = 1.0
# Triangles of one smooth strip (a tessellated curve) meet at less than this.
SMOOTH_STRIP_DEG = 30.0
# A strip is a cylinder when every face normal stands within this of square
# to its axis, and it is made of at least this many faces.
CYL_SQUARE_DEG = 3.0
CYL_LEAST_FACES = 3
METHODS = ("auto", "vertices", "faces")
# A mesh is sparse (CAD-style) when at least this share of its vertices sit
# on creases: too few vertices inside its faces for the vertex growing.
SPARSE_CREASE_SHARE = 0.5


class _Union:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, a):
        p = self.p
        while p[a] != a:
            p[a] = p[p[a]]
            a = p[a]
        return a

    def join(self, a, b):
        a, b = self.find(a), self.find(b)
        if a != b:
            self.p[max(a, b)] = min(a, b)

    def labels(self):
        return np.array([self.find(i) for i in range(len(self.p))], dtype=np.int64)


def on_creases(g, max_deg):
    """The share of the vertices that sit on a crease: a triangle round
    them leans more than max_deg off their normal, so the vertex growing
    can never take them into a plane. On a CAD-style mesh, nearly all."""
    if g.n == 0 or len(g.F) == 0:
        return 0.0
    P, F, N = g.P, g.F, g.N
    cr = np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]])
    ln = np.linalg.norm(cr, axis=1)
    ok = ln > max(1e-12 * g.bbox_diag ** 2, 1e-30)
    fn = cr[ok] / ln[ok, None]
    Fk = F[ok]
    worst = np.full(g.n, -np.inf)
    for k in range(3):
        np.maximum.at(worst, Fk[:, k], 1 - np.einsum("ij,ij->i", N[Fk[:, k]], fn))
    used = np.isfinite(worst)
    if not used.any():
        return 0.0
    return float((worst[used] > 1 - math.cos(math.radians(min(89, max(0.1, max_deg))))).mean())


def is_sparse(g, max_deg):
    return on_creases(g, max_deg) >= SPARSE_CREASE_SHARE


def segment(g, min_area, max_rms, max_deg, box=None, method="auto"):
    """scan_segment's regions and which method found them: "vertices"
    (ScanRuler's, always first under auto) or "faces" (this module)."""
    if method not in METHODS:
        method = "auto"
    if method == "faces":
        res = segment_faces(g, min_area, max_rms, box)
        res["method"] = "faces"
        res["why"] = "asked for (method: faces)"
        return res
    res = SEG.segment_planes(g, min_area, max_rms, max_deg, box)
    for r in res["regions"]:
        r.setdefault("kind", "plane")
    res["method"] = "vertices"
    if method == "vertices" or res["regions"]:
        return res
    share = on_creases(g, max_deg)
    if share < SPARSE_CREASE_SHARE:
        return res
    alt = segment_faces(g, min_area, max_rms, box)
    alt["method"] = "faces"
    alt["why"] = f"the vertex growing found nothing on a sparse, CAD-style mesh ({100 * share:.0f} % of its vertices sit on creases, with no vertices inside its faces to grow from): the triangles were grouped instead"
    return alt


def _plane_of(P, verts, toward):
    m = SEG.Moments(P[verts[0]])
    m.add_many(P[verts])
    fit = m.plane(toward)
    if fit is None:
        # Fewer than three points off a line cannot happen on a real face;
        # a face of collinear corners has no plane.
        return None
    return fit


def segment_faces(g, min_area, max_rms, box=None):
    P, F = g.P, g.F
    n = g.n
    max_rms = max(float(max_rms), 1e-9)
    if box:
        allowed_v = np.all((P >= np.asarray(box["min"])) & (P <= np.asarray(box["max"])), axis=1)
    else:
        allowed_v = np.ones(n, dtype=bool)
    considered = int(allowed_v.sum())
    empty = {"regions": [], "considered": considered, "claimed": 0}
    if len(F) == 0:
        return empty
    A, B, C = P[F[:, 0]], P[F[:, 1]], P[F[:, 2]]
    cr = np.cross(B - A, C - A)
    dbl = np.linalg.norm(cr, axis=1)
    area = dbl / 2
    floor = max(1e-12 * g.bbox_diag ** 2, 1e-30)
    good = (dbl > floor) & allowed_v[F].all(axis=1)
    fn = np.zeros_like(cr)
    fn[good] = cr[good] / dbl[good, None]
    off = np.einsum("ij,ij->i", fn, A)

    # Faces across each interior edge.
    nf = len(F)
    e = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    e.sort(axis=1)
    owner = np.tile(np.arange(nf), 3)
    key = e[:, 0] * (n + 1) + e[:, 1]
    o = np.argsort(key, kind="stable")
    ks, ow = key[o], owner[o]
    same = ks[1:] == ks[:-1]
    fa, fb = ow[:-1][same], ow[1:][same]
    keep = good[fa] & good[fb]
    fa, fb = fa[keep], fb[keep]
    cosd = np.einsum("ij,ij->i", fn[fa], fn[fb])
    # The far corners of each across the other's plane.
    def far_off(x, y):
        return np.abs(np.einsum("ijk,ik->ij", P[F[y]], fn[x]) - off[x][:, None]).max(axis=1)

    if len(fa):
        flat = (cosd >= math.cos(math.radians(PLANE_DEG))) & (far_off(fa, fb) <= max_rms) & (far_off(fb, fa) <= max_rms)
        smooth = cosd >= math.cos(math.radians(SMOOTH_STRIP_DEG))
    else:
        flat = smooth = np.zeros(0, dtype=bool)

    faces_u = _Union(nf)
    for a, b in zip(fa[flat].tolist(), fb[flat].tolist()):
        faces_u.join(a, b)
    strip_u = _Union(nf)
    for a, b in zip(fa[smooth].tolist(), fb[smooth].tolist()):
        strip_u.join(a, b)
    face_lab = faces_u.labels()
    strip_lab = strip_u.labels()
    good_idx = np.nonzero(good)[0]

    def vertices_of(tris):
        return np.unique(F[tris].ravel())

    def plane_region(tris):
        verts = vertices_of(tris)
        w = area[tris]
        toward = (fn[tris] * w[:, None]).sum(axis=0)
        fit = _plane_of(P, verts, toward)
        if fit is None or fit["sigma"] > max_rms:
            return None
        a = float(w.sum())
        if a < min_area:
            return None
        nrm = fit["n"] if fit["n"] @ toward >= 0 else -fit["n"]
        return {"kind": "plane", "tris": tris, "members": verts, "normal": nrm, "point": fit["centroid"], "sigma": fit["sigma"], "area": a}

    def cylinder_region(tris):
        verts = vertices_of(tris)
        if len(verts) < 6:
            return None
        Nf = fn[tris] * np.sqrt(area[tris])[:, None]
        vals, vecs = np.linalg.eigh(Nf.T @ Nf)
        axis = vecs[:, 0]
        if not vals[1] > 1e-9 * max(vals[2], 1e-30):
            return None
        if np.abs(fn[tris] @ axis).max() > math.sin(math.radians(CYL_SQUARE_DEG)):
            return None
        c = SH.fit_cylinder_on_axis(P, verts, axis)
        if c is None:
            return None
        c = SH.refine_cylinder_geometric(P, verts, c)
        res = SH.cylinder_residual(c, P[verts])
        if not np.isfinite(res).all():
            return None
        sigma = float(np.sqrt(np.mean(res ** 2)))
        a = float(area[tris].sum())
        if sigma > max_rms or a < min_area:
            return None
        ax = np.array([c["ax"], c["ay"], c["az"]], dtype=float)
        ax /= np.linalg.norm(ax)
        p0 = np.array([c["px"], c["py"], c["pz"]], dtype=float)
        t = (P[verts] - p0) @ ax
        # The axis point at the strip's middle, the axis pointing the way of
        # most of its length from there (a sign of no meaning on its own).
        mid = p0 + ax * (t.min() + t.max()) / 2
        # Which side the material is: the face normals point away from the
        # axis on a boss, toward it in a bore.
        cent = (A[tris] + B[tris] + C[tris]) / 3
        radial = cent - mid
        radial -= np.outer(radial @ ax, ax)
        outward = float(np.einsum("ij,ij->i", radial, fn[tris]).sum()) >= 0
        return {"kind": "cylinder", "tris": tris, "members": verts, "axis": ax, "point": mid, "radius": float(c["r"]), "length": float(t.max() - t.min()), "bore": not outward, "sigma": sigma, "area": a}

    kept = []
    strips = {}
    for f in good_idx.tolist():
        strips.setdefault(int(strip_lab[f]), []).append(f)
    for tris in strips.values():
        tris = np.asarray(tris, dtype=np.int64)
        groups = {}
        for f in tris.tolist():
            groups.setdefault(int(face_lab[f]), []).append(f)
        # Several faces meeting smoothly, or one "face" that is not flat
        # (facets under PLANE_DEG apart chained into it): a cylinder?
        if len(groups) >= CYL_LEAST_FACES or (len(groups) == 1 and plane_region(tris) is None):
            cyl = cylinder_region(tris)
            if cyl is not None:
                kept.append(cyl)
                continue
        for gt in groups.values():
            r = plane_region(np.asarray(gt, dtype=np.int64))
            if r is not None:
                kept.append(r)
    if not kept:
        return empty

    kept.sort(key=lambda r: -r["area"])
    region_of = np.zeros(nf, dtype=np.int64)
    for k, r in enumerate(kept):
        region_of[r["tris"]] = k + 1
    ra, rb = region_of[fa], region_of[fb]
    sel = (ra != 0) & (rb != 0) & (ra != rb)
    pairs = np.unique(np.c_[np.minimum(ra[sel], rb[sel]), np.maximum(ra[sel], rb[sel])], axis=0) if sel.any() else np.zeros((0, 2), dtype=np.int64)

    regions = []
    for r in kept:
        Q = P[r["members"]]
        out = {k: v for k, v in r.items() if k != "tris"}
        out.update({"min": Q.min(axis=0), "max": Q.max(axis=0), "count": len(r["members"]), "neighbours": []})
        regions.append(out)
    for ia, ib in pairs.tolist():
        ra_, rb_ = regions[ia - 1], regions[ib - 1]
        d = _meet_deg(ra_, rb_)
        ra_["neighbours"].append({"id": ib, "deg": d})
        rb_["neighbours"].append({"id": ia, "deg": d})
    for r in regions:
        r["neighbours"].sort(key=lambda x: x["id"])
    claimed = len(np.unique(np.concatenate([r["members"] for r in regions])))
    return {"regions": regions, "considered": considered, "claimed": int(claimed)}


def _meet_deg(a, b):
    """The angle two neighbouring regions meet at, degrees: between plane
    normals; a plane and a cylinder, between the plane and the cylinder's
    side (90 for a cap on its cylinder); two cylinders, between their axes."""
    def ang(u, v):
        return math.degrees(math.acos(max(-1.0, min(1.0, float(u @ v)))))

    if a["kind"] == "plane" and b["kind"] == "plane":
        return ang(a["normal"], b["normal"])
    if a["kind"] == "cylinder" and b["kind"] == "cylinder":
        d = ang(a["axis"], b["axis"])
        return min(d, 180 - d)
    p, c = (a, b) if a["kind"] == "plane" else (b, a)
    return 90.0 - math.degrees(math.acos(min(1.0, abs(float(p["normal"] @ c["axis"])))))
