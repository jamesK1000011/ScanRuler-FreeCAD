# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/core/kernelMath.ts, kernelOps.ts (tracedHistory, unifyHistory)
# SPDX-License-Identifier: AGPL-3.0-only
#
# Which face became which: the history a fingerprint's origin is carried
# through. The original reads it from OCCT (the *WithHistory calls: each old
# face's hash and the hashes of the faces it was modified into). FreeCAD's
# Python gives no such history for a fillet, a shell, a chamfer or a
# boolean, so it is traced here, after every step, from the shapes alone:
#
#   result face                                        origin
#   the same face (same hash, isSame)                  kept: the input face's
#   a point inside it lies on an input face            that face's (modified)
#     (on its surface, inside its edges)
#   a copy made by a rigid move or a mirror            the face at the same
#                                                      place in the order
#   otherwise                                          the step's own (generated)
#
# A history is a dict {old hash: [new hashes]}, as the original's FaceHistory
# map. The shape-reading half takes the occt-wasm adapter (kernel.Occt), so
# it runs on FreeCAD Part shapes; the rest is plain Python.

import math

from .vec import dot, scale, sub

HASH_BOUND = 0x7FFFFFFF
# How near a point must be to a face's surface to be on it, in mm.
ON_SURFACE = 1e-4
_ROUND = ("cylinder", "cone", "sphere", "torus")


def compose_history(first, then):
    """What `first` and then `then` did to the faces, as one history."""
    out = {}
    for old, made in first.items():
        out[old] = [x for h in made for x in then.get(h, [h])]
    for old, made in then.items():
        if old not in out:
            out[old] = list(made)
    return out


def parse_history(flat):
    """A history from the kernel's flat groups: an old hash, a count, and
    that many new hashes."""
    out = {}
    i = 0
    while i + 1 < len(flat):
        old, n = flat[i], flat[i + 1]
        out[old] = list(flat[i + 2:i + 2 + n])
        i += 2 + n
    return out


def flat_history(history):
    """A history as the kernel's flat groups (parse_history's inverse)."""
    out = []
    for old, made in history.items():
        out += [old, len(made), *made]
    return out


def same_surface(was, candidates):
    """kernelMath sameSurface: the candidate face on the surface `was` lies
    on (same kind, the same plane or axis and radius), the nearest; None."""
    best = None
    best_d = math.inf
    for f in candidates:
        if f["kind"] != was["kind"]:
            continue
        if was["kind"] == "plane":
            if dot(f["dir"], was["dir"]) < 1 - 1e-6:
                continue
            if abs(dot(sub(f["centroid"], was["centroid"]), was["dir"])) > 1e-4:
                continue
        else:
            if abs(dot(f["dir"], was["dir"])) < 1 - 1e-6:
                continue
            if was.get("radius") is not None and (f.get("radius") is None or abs(f["radius"] - was["radius"]) > 1e-4):
                continue
            if was.get("center") and f.get("center"):
                off = sub(f["center"], was["center"])
                along = dot(off, was["dir"])
                across = sub(off, scale(was["dir"], along))
                if math.hypot(*across) > 1e-4 or (was["kind"] == "sphere" and abs(along) > 1e-4):
                    continue
        d = math.hypot(*sub(f["centroid"], was["centroid"]))
        if d < best_d:
            best_d = d
            best = f
    return best


def history_by_order(before_hashes, after_hashes):
    """A copy's history: the faces of a rigid move or a mirror keep their
    order, so each old face became the face at its place."""
    if len(before_hashes) != len(after_hashes):
        return {}
    return {a: [b] for a, b in zip(before_hashes, after_hashes) if a != b}


def origins_after(face_hashes, before, history, step_id):
    """build.ts propagate, less the pattern marks: a face that kept its hash
    keeps its origin, one the history says came from an old face inherits
    that face's, the first such old face the body had winning over the
    step's own, and every other face is the step's."""
    frm = {}
    for old, made in history.items():
        origin = before.get(old)
        if origin is None:
            continue
        for h in made:
            had = frm.get(h)
            if had is None or had == step_id:
                frm[h] = origin
    return {h: before[h] if h in before else frm.get(h, step_id) for h in face_hashes}


# ---- traced on the shapes (needs the kernel adapter) ----------------------------------------


def _bbox_has(b, p):
    t = ON_SURFACE
    return b["xmin"] - t <= p[0] <= b["xmax"] + t and b["ymin"] - t <= p[1] <= b["ymax"] + t and b["zmin"] - t <= p[2] <= b["zmax"] + t


def point_inside(occt, face):
    """A point inside a face: the middle of its parameter box when the face
    has it, else the first of ever finer grids that it has; None."""
    uv = occt.uvBounds(face)
    for n in (1, 4, 16):
        for i in range(n):
            for j in range(n):
                u = uv["uMin"] + ((i + 0.5) / n) * (uv["uMax"] - uv["uMin"])
                v = uv["vMin"] + ((j + 0.5) / n) * (uv["vMax"] - uv["vMin"])
                if occt.classifyPointOnFace(face, u, v) == "in":
                    return occt.pointOnSurface(face, u, v)
    return None


def _on_face(occt, f, p):
    u, v = occt.uvFromPoint(f["face"], p)
    q = occt.pointOnSurface(f["face"], u, v)
    if math.hypot(q[0] - p[0], q[1] - p[1], q[2] - p[2]) > ON_SURFACE:
        return False
    turn = 2 * math.pi

    def into(t, frm):
        return frm + (((t - frm) % turn) + turn) % turn

    if f["kind"] in _ROUND:
        u = into(u, f["uv"]["uMin"])
    if f["kind"] == "torus":
        v = into(v, f["uv"]["vMin"])
    return occt.classifyPointOnFace(f["face"], u, v) == "in"


def _faces_read(occt, shapes):
    from .topo import face_kind_of

    out = []
    for s in shapes:
        for face in occt.getSubShapes(s, "face"):
            out.append({"face": face, "hash": occt.hashCode(face, HASH_BOUND), "box": occt.getBoundingBox(face), "kind": face_kind_of(occt.surfaceType(face)), "uv": occt.uvBounds(face)})
    return out


def traced_history(occt, before, after, only=None):
    """kernelOps tracedHistory: each face of `after` whose hash none of
    `before` has, followed by a point inside it to the face of `before`
    holding that point, which it is a piece of. A face on none (where a tool
    cut, a round, a wall) goes untraced: the operation's own. `only`, when
    given, the hashes of the old faces that may be traced to."""
    history = {}
    was = [f for f in _faces_read(occt, before) if only is None or f["hash"] in only]
    old = {f["hash"] for f in _faces_read(occt, before)}
    seen = set()
    for face in occt.getSubShapes(after, "face"):
        h = occt.hashCode(face, HASH_BOUND)
        if h in old or h in seen:
            continue
        seen.add(h)
        try:
            p = point_inside(occt, face)
        except Exception:  # noqa: BLE001 — a face the kernel cannot sample goes untraced, as in the original
            continue
        if p is None:
            continue
        src = next((f for f in was if _bbox_has(f["box"], p) and _on_face(occt, f, p)), None)
        if src is not None:
            history.setdefault(src["hash"], []).append(h)
    return history


def unify_history(occt, before, after):
    """kernelOps unifyHistory: what merging the faces on one surface did,
    each face of `before` whose hash `after` lacks followed by a point inside
    it to the face of `after` that took it in."""
    history = {}
    now = _faces_read(occt, [after])
    kept = {f["hash"] for f in now}
    old = set()
    was = occt.getSubShapes(before, "face")
    for f in was:
        old.add(occt.hashCode(f, HASH_BOUND))
    fresh = [f for f in now if f["hash"] not in old]
    if not fresh:
        return history
    for f in was:
        h = occt.hashCode(f, HASH_BOUND)
        if h in kept:
            continue
        try:
            p = point_inside(occt, f)
        except Exception:  # noqa: BLE001 — as tracedHistory
            continue
        into = p is not None and next((x for x in fresh if _bbox_has(x["box"], p) and _on_face(occt, x, p)), None)
        if into:
            history[h] = [into["hash"]]
    return history
