# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/core/autoConstrain.ts
# SPDX-License-Identifier: AGPL-3.0-only
#
# A plane or a cylinder fitted to scan points, held to what the part
# already has where the fit comes out nearly so: a plane parallel,
# perpendicular or coincident with a coordinate plane or a measured one, a
# cylinder's axis along, across or on a measured axis - within half a
# degree of tilt and a millimetre of shift. Or held by hand to the
# relation named (force), or not held at all (free).
#
# Points are a flat float32 array x,y,z,... as the original's Float32Array;
# a cylinder is the original's {"px","py","pz","ax","ay","az","r"}.

import math

from ._js import js_hypot

import numpy as np

from ..linalg import ortho_basis as _ortho_basis
from ..shapes import fit_cylinder_on_axis as _fit_on_axis, refine_cylinder_geometric as _refine

TILT_TOLERANCE_DEG = 0.5
COINCIDENCE_MM = 1
DEG = 180 / math.pi


def _v(a):
    return [float(a[0]), float(a[1]), float(a[2])]


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _sub(a, b):
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def _scale(a, s):
    return [a[0] * s, a[1] * s, a[2] * s]


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def _len(a):
    return math.sqrt(_dot(a, a))


def _normalize(a):
    ln = _len(a)
    if not (ln > 1e-12):
        return None
    return [a[0] / ln, a[1] / ln, a[2] / ln]


def ortho_basis(n):
    u, v = _ortho_basis(n)
    return _v(u), _v(v)


def _ref_dir(r):
    return r["normal"] if r["kind"] == "plane" else r["dir"]


def _line_angle_deg(a, b):
    return math.acos(min(1, abs(_dot(a, b)))) * DEG


def _facing(d, like):
    return _scale(d, -1) if _dot(d, like) < 0 else d


def relation_words(shape, relation, ref_kind):
    if shape == "plane":
        if ref_kind == "plane":
            return "Coincident with" if relation == "on" else "Parallel to" if relation == "along" else "Perpendicular to"
        return "Parallel to" if relation == "across" else "Perpendicular to"
    if ref_kind == "plane":
        return "Parallel to" if relation == "across" else "Perpendicular to"
    return "Coaxial with" if relation == "on" else "Parallel to" if relation == "along" else "Perpendicular to"


def relations_for(shape, ref_kind):
    if shape == "plane":
        return ["along", "across", "on"] if ref_kind == "plane" else ["along", "across"]
    return ["along", "across", "on"] if ref_kind == "axis" else ["along", "across"]


def _points(points):
    """The points as the original holds them, float32, read in doubles."""
    return np.asarray(points, dtype=np.float32).astype(np.float64).reshape(-1)


def _moments(P):
    n = len(P) // 3
    X = P.reshape(n, 3)
    mean = X.sum(axis=0) / n
    D = X - mean
    xx, xy, xz = float(D[:, 0] @ D[:, 0]), float(D[:, 0] @ D[:, 1]), float(D[:, 0] @ D[:, 2])
    yy, yz, zz = float(D[:, 1] @ D[:, 1]), float(D[:, 1] @ D[:, 2]), float(D[:, 2] @ D[:, 2])
    return {"n": n, "mean": _v(mean), "cov": (xx, xy, xz, yy, yz, zz)}


def _spread(m, v):
    xx, xy, xz, yy, yz, zz = m["cov"]
    return v[0] * (xx * v[0] + xy * v[1] + xz * v[2]) + v[1] * (xy * v[0] + yy * v[1] + yz * v[2]) + v[2] * (xz * v[0] + yz * v[1] + zz * v[2])


def _least_spread_across(m, r):
    u, v = ortho_basis(r)
    a = _spread(m, u)
    c = _spread(m, v)
    xx, xy, xz, yy, yz, zz = m["cov"]
    b = u[0] * (xx * v[0] + xy * v[1] + xz * v[2]) + u[1] * (xy * v[0] + yy * v[1] + yz * v[2]) + u[2] * (xz * v[0] + yz * v[1] + zz * v[2])
    low = (a + c) / 2 - js_hypot((a - c) / 2, b)
    e = [b, low - a] if abs(b) > 1e-300 else ([1, 0] if a <= c else [0, 1])
    ln = js_hypot(e[0], e[1])
    return [(u[0] * e[0] + v[0] * e[1]) / ln, (u[1] * e[0] + v[1] * e[1]) / ln, (u[2] * e[0] + v[2] * e[1]) / ln]


def symmetric_eigen3(m):
    """symmetricEigen3 of src/core/fit/linalg.ts: cyclic Jacobi from the
    identity, so the eigenvectors face the way the original's do."""
    a = [float(x) for x in m]
    v = [1.0, 0, 0, 0, 1.0, 0, 0, 0, 1.0]
    for _sweep in range(32):
        off = abs(a[1]) + abs(a[2]) + abs(a[5])
        diag = abs(a[0]) + abs(a[4]) + abs(a[8])
        if off <= 1e-14 * diag or off == 0:
            break
        for p, q in ((0, 1), (0, 2), (1, 2)):
            apq = a[p * 3 + q]
            if apq == 0:
                continue
            theta = (a[q * 3 + q] - a[p * 3 + p]) / (2 * apq)
            sign = 1 if theta >= 0 else -1
            t = sign / (abs(theta) + math.sqrt(theta * theta + 1))
            c = 1 / math.sqrt(t * t + 1)
            s = t * c
            for k in range(3):
                akp, akq = a[k * 3 + p], a[k * 3 + q]
                a[k * 3 + p] = c * akp - s * akq
                a[k * 3 + q] = s * akp + c * akq
            for k in range(3):
                apk, aqk = a[p * 3 + k], a[q * 3 + k]
                a[p * 3 + k] = c * apk - s * aqk
                a[q * 3 + k] = s * apk + c * aqk
            for k in range(3):
                vkp, vkq = v[k * 3 + p], v[k * 3 + q]
                v[k * 3 + p] = c * vkp - s * vkq
                v[k * 3 + q] = s * vkp + c * vkq
    order = sorted(range(3), key=lambda i: a[i * 3 + i])
    vecs = []
    for i in order:
        w = [v[i], v[3 + i], v[6 + i]]
        ln = math.sqrt(_dot(w, w))
        vecs.append([x / ln for x in w] if ln > 1e-20 else [0.0, 0.0, 1.0])
    return [a[i * 3 + i] for i in order], vecs


def _eigen3(m):
    c = m["cov"]
    return symmetric_eigen3([c[0], c[1], c[2], c[1], c[3], c[4], c[2], c[4], c[5]])


def _hold_direction(free, refs, mode, solve_across):
    if mode["mode"] == "free":
        return None

    def found(relation, r, tilt):
        return {"relation": relation, "ref": r["key"], "name": r["name"], "refKind": r["kind"], "tiltDeg": tilt}

    if mode["mode"] == "force":
        r = next((x for x in refs if x["key"] == mode["ref"]), None)
        if r is None:
            return None
        d = _ref_dir(r)
        if mode["relation"] == "across":
            return {"dir": _facing(solve_across(d), free), "relations": [found("across", r, abs(90 - _line_angle_deg(free, d)))], "same": []}
        return {"dir": _facing(d, free), "relations": [found(mode["relation"], r, _line_angle_deg(free, d))], "same": [r]}
    best = None
    best_tilt = math.inf
    for r in refs:
        tilt = _line_angle_deg(free, _ref_dir(r))
        if tilt <= TILT_TOLERANCE_DEG and tilt < best_tilt - 1e-9:
            best = r
            best_tilt = tilt
    if best is not None:
        d = _ref_dir(best)
        same = [best] + [r for r in refs if r is not best and _line_angle_deg(_ref_dir(r), d) < 1e-6]
        return {"dir": _facing(d, free), "relations": [found("along", best, best_tilt)], "same": same}
    square = [(r, abs(90 - _line_angle_deg(free, _ref_dir(r)))) for r in refs]
    square = sorted([x for x in square if x[1] <= TILT_TOLERANCE_DEG], key=lambda x: x[1])
    if not square:
        return None
    first = square[0]
    second = next((x for x in square if _line_angle_deg(_ref_dir(x[0]), _ref_dir(first[0])) > 5), None)
    if second is not None:
        both = _normalize(_cross(_ref_dir(first[0]), _ref_dir(second[0])))
        if both and _line_angle_deg(both, free) <= 2 * TILT_TOLERANCE_DEG:
            return {"dir": _facing(both, free), "relations": [found("across", first[0], first[1]), found("across", second[0], second[1])], "same": []}
    return {"dir": _facing(solve_across(_ref_dir(first[0])), free), "relations": [found("across", first[0], first[1])], "same": []}


def _plane_residuals(P, origin, normal):
    X = P.reshape(-1, 3)
    d = (X[:, 0] - origin[0]) * normal[0] + (X[:, 1] - origin[1]) * normal[1] + (X[:, 2] - origin[2]) * normal[2]
    return {"rms": math.sqrt(float(d @ d) / len(X)), "max": float(np.max(np.abs(d))) if len(d) else 0.0}


def constrain_plane(points, refs, mode):
    P = _points(points)
    if len(P) < 9:
        return None
    m = _moments(P)
    vals, vecs = _eigen3(m)
    if not (vals[1] > 1e-12 * max(vals[2], 1e-300)):
        return None
    free_normal = vecs[0]
    res_free = _plane_residuals(P, m["mean"], free_normal)
    held = _hold_direction(free_normal, refs, mode, lambda r: _least_spread_across(m, r))
    if not held:
        return {"origin": m["mean"], "normal": free_normal, "rms": res_free["rms"], "rmsFree": res_free["rms"], "max": res_free["max"], "relations": []}
    origin = m["mean"]
    relations = held["relations"]
    forced = mode["mode"] == "force" and mode["relation"] == "on"
    for r in held["same"]:
        if r["kind"] != "plane":
            continue
        shift = _dot(_sub(m["mean"], r["origin"]), held["dir"])
        if not forced and not (mode["mode"] == "auto" and abs(shift) <= COINCIDENCE_MM):
            continue
        origin = _sub(m["mean"], _scale(held["dir"], shift))
        relations[0] = {"relation": "on", "ref": r["key"], "name": r["name"], "refKind": r["kind"], "tiltDeg": _line_angle_deg(free_normal, r["normal"]), "shiftMm": abs(shift)}
        break
    res = _plane_residuals(P, origin, held["dir"])
    return {"origin": origin, "normal": held["dir"], "rmsFree": res_free["rms"], "rms": res["rms"], "max": res["max"], "relations": relations}


def _cylinder_residuals(P, c):
    X = P.reshape(-1, 3)
    q = X - np.array([c["px"], c["py"], c["pz"]])
    a = np.array([c["ax"], c["ay"], c["az"]])
    t = q @ a
    d = np.linalg.norm(q - np.outer(t, a), axis=1) - c["r"]
    return {"rms": math.sqrt(float(d @ d) / len(X)), "max": float(np.max(np.abs(d))) if len(d) else 0.0}


def _cyl(c):
    return {k: float(c[k]) for k in ("px", "py", "pz", "ax", "ay", "az", "r")}


def fit_cylinder_free(points):
    P = _points(points)
    if len(P) < 18:
        return None
    m = _moments(P)
    _vals, vecs = _eigen3(m)
    X = P.reshape(-1, 3)
    idx = np.arange(len(X))
    best = None
    best_rms = math.inf
    for start in vecs:
        seeded = _fit_on_axis(X, idx, start)
        if not seeded:
            continue
        c = _cyl(_refine(X, idx, seeded))
        if not (c["r"] > 0) or not math.isfinite(c["r"]):
            continue
        rms = _cylinder_residuals(P, c)["rms"]
        if rms < best_rms:
            best = c
            best_rms = rms
    return best


def constrain_cylinder(points, refs, mode):
    P = _points(points)
    free = fit_cylinder_free(P)
    if not free:
        return None
    free_axis = [free["ax"], free["ay"], free["az"]]
    free_res = _cylinder_residuals(P, free)
    mean = _moments(P)["mean"]

    def middle(c):
        t = (mean[0] - c["px"]) * c["ax"] + (mean[1] - c["py"]) * c["ay"] + (mean[2] - c["pz"]) * c["az"]
        return [c["px"] + t * c["ax"], c["py"] + t * c["ay"], c["pz"] + t * c["az"]]

    held = _hold_direction(free_axis, refs, mode, lambda r: _normalize(_sub(free_axis, _scale(r, _dot(free_axis, r)))) or free_axis)
    if not held:
        return {"origin": middle(free), "axis": free_axis, "radius": free["r"], "rms": free_res["rms"], "rmsFree": free_res["rms"], "max": free_res["max"], "relations": []}
    X = P.reshape(-1, 3)
    idx = np.arange(len(X))
    c = _fit_on_axis(X, idx, held["dir"])
    if not c:
        return None
    c = _cyl(c)
    relations = held["relations"]
    forced = mode["mode"] == "force" and mode["relation"] == "on"
    for r in held["same"]:
        if r["kind"] != "axis":
            continue
        off = _sub([c["px"], c["py"], c["pz"]], r["origin"])
        apart = _len(_sub(off, _scale(held["dir"], _dot(off, held["dir"]))))
        if forced or (mode["mode"] == "auto" and apart <= COINCIDENCE_MM):
            o = r["origin"]
            d = np.array(held["dir"])
            q = X - np.array(o)
            t = q @ d
            tot = float(np.sum(np.linalg.norm(q - np.outer(t, d), axis=1)))
            c = {"px": o[0], "py": o[1], "pz": o[2], "ax": held["dir"][0], "ay": held["dir"][1], "az": held["dir"][2], "r": tot / len(X)}
            relations[0] = {"relation": "on", "ref": r["key"], "name": r["name"], "refKind": r["kind"], "tiltDeg": _line_angle_deg(free_axis, r["dir"]), "shiftMm": apart}
            break
    res = _cylinder_residuals(P, c)
    return {"origin": middle(c), "axis": held["dir"], "radius": c["r"], "rmsFree": free_res["rms"], "rms": res["rms"], "max": res["max"], "relations": relations}


def plane_patch(points, plane, expand_pct):
    P = _points(points).reshape(-1, 3)
    u0, v0 = ortho_basis(plane["normal"])
    o = plane["origin"]
    D = P - np.array(o)
    a0 = D @ np.array(u0)
    b0 = D @ np.array(v0)
    ma = float(a0.sum()) / len(P)
    mb = float(b0.sum()) / len(P)
    a = a0 - ma
    b = b0 - mb
    aa, ab, bb = float(a @ a), float(a @ b), float(b @ b)
    turn = 0.5 * math.atan2(2 * ab, aa - bb)
    u = [u0[i] * math.cos(turn) + v0[i] * math.sin(turn) for i in range(3)]
    v = _cross(plane["normal"], u)
    au = D @ np.array(u)
    bv = D @ np.array(v)
    u_lo, u_hi, v_lo, v_hi = float(au.min()), float(au.max()), float(bv.min()), float(bv.max())
    gu = max((u_hi - u_lo) * (expand_pct / 100), 1e-3)
    gv = max((v_hi - v_lo) * (expand_pct / 100), 1e-3)
    corner = [o[i] + (u_lo - gu) * u[i] + (v_lo - gv) * v[i] for i in range(3)]
    return {"corner": corner, "u": u, "v": v, "width": u_hi - u_lo + 2 * gu, "height": v_hi - v_lo + 2 * gv}


def cylinder_patch(points, cylinder, expand_pct):
    P = _points(points).reshape(-1, 3)
    u, v = ortho_basis(cylinder["axis"])
    q = P - np.array(cylinder["origin"])
    t = q @ np.array(cylinder["axis"])
    lo = float(t.min())
    hi = float(t.max())
    angles = sorted(float(x) for x in np.arctan2(q @ np.array(v), q @ np.array(u)))
    grow = max((hi - lo) * (expand_pct / 100), 1e-3)
    gap = angles[0] + 2 * math.pi - angles[-1]
    start = angles[0]
    for i in range(1, len(angles)):
        if angles[i] - angles[i - 1] > gap:
            gap = angles[i] - angles[i - 1]
            start = angles[i]
    covered = 2 * math.pi - gap
    more = covered * (expand_pct / 100)
    sweep = covered + 2 * more
    full = sweep > 2 * math.pi - (20 * math.pi) / 180
    return {"from": lo - grow, "to": hi + grow, "u": u, "v": v, "start": start - more, "sweep": 2 * math.pi if full else sweep, "full": full}
