# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/core/topo.ts
# SPDX-License-Identifier: AGPL-3.0-only
#
# Stable names for the faces and edges of a body. A feature that fillets an
# edge or opens a face for a shell has to say which one, and an index into
# the kernel's face list is not a name: the list is remade on every rebuild
# and an earlier dimension changed reorders it. So a pick is stored as a
# fingerprint (the kind of surface or curve, where its middle is, which way
# it faces or runs, how big it is, and which feature first made it) and
# re-found on the body as it stands before the feature, the best candidate
# within a tolerance winning. A pick that cannot be found fails its feature
# loudly, with the fingerprint's description in the message, never a
# silently substituted neighbour.
#
# This module is the geometry and the matching, run on plain descriptors.
# Reading the descriptors off a shape is the kernel's: read_topology asks
# kernel.describe_faces(shape) and kernel.describe_edges(shape, deflection)
# (kernel.py, FreeCAD Part) for the original's RawFace and RawEdge records:
#   face {hash, kind, centroid, dir, area, radius?, center?, fullTurn?}
#   edge {hash, kind, mid, dir, length, radius?, faceHashes, polyline (flat
#         XYZ), ends [a, b], endTangents [ta, tb]}

import math

from ._js import to_fixed
from .units import fmt_area, fmt_len
from .vec import dot, length, normalize, scale, sub

FACE_KINDS = ("plane", "cylinder", "cone", "sphere", "torus", "other")
EDGE_KINDS = ("line", "circle", "other")
ONE_SURFACE_MM = 1e-3
ONE_SURFACE_ANGLE = 1e-4
_ROUND = ("cylinder", "cone", "torus")


def face_kind_of(t):
    return t if t in FACE_KINDS[:-1] else "other"


def edge_kind_of(t):
    return t if t in ("line", "circle") else "other"


def match_tolerance(diagonal):
    """An earlier dimension moved by a tenth of the part still lands on the
    same face; a face turned by more than ten degrees is another face."""
    return {"position": max(1, diagonal * 0.1), "angle": (10 * math.pi) / 180, "size": 0.5}


def canonical_dir(v):
    n = normalize(v) or [0, 0, 1]
    for k in range(3):
        if abs(n[k]) > 1e-6:
            return [0 - n[0], 0 - n[1], 0 - n[2]] if n[k] < 0 else n
    return n


def _rigid_apply(m, p):
    r, t = m["r"], m["t"]
    return [r[0] * p[0] + r[1] * p[1] + r[2] * p[2] + t[0], r[3] * p[0] + r[4] * p[1] + r[5] * p[2] + t[1], r[6] * p[0] + r[7] * p[1] + r[8] * p[2] + t[2]]


def _rigid_rotate(m, d):
    r = m["r"]
    return [r[0] * d[0] + r[1] * d[1] + r[2] * d[2], r[3] * d[0] + r[4] * d[1] + r[5] * d[2], r[6] * d[0] + r[7] * d[1] + r[8] * d[2]]


def transform_fingerprint(face, m):
    """A face's fingerprint carried through a rigid motion {r (9), t (3)}."""
    turned = _rigid_rotate(m, face["dir"])
    out = {**face, "centroid": _rigid_apply(m, face["centroid"]), "dir": canonical_dir(turned) if face["kind"] in _ROUND else turned}
    if face.get("center"):
        out["center"] = _rigid_apply(m, face["center"])
    return out


def transform_edge_fingerprint(edge, m):
    def turn(d):
        return _rigid_rotate(m, d)

    return {**edge, "mid": _rigid_apply(m, edge["mid"]), "dir": canonical_dir(turn(edge["dir"])),
            "faces": [{"kind": f["kind"], "dir": canonical_dir(turn(f["dir"])) if f["kind"] in _ROUND else turn(f["dir"])} for f in edge["faces"]]}


def _angle_between(a, b):
    d = max(-1, min(1, dot(a, b) / (max(length(a), 1e-12) * max(length(b), 1e-12))))
    return math.acos(d)


def _relative_difference(a, b):
    m = max(abs(a), abs(b))
    return abs(a - b) / m if m > 1e-12 else 0


def face_distance(wanted, candidate, tol):
    """How far a candidate face is from the wanted one, in tolerances; None
    when it is not a candidate at all."""
    if wanted["kind"] != candidate["kind"]:
        return None
    pos = length(sub(wanted["centroid"], candidate["centroid"])) / tol["position"]
    ang = _angle_between(wanted["dir"], candidate["dir"]) / tol["angle"]
    size = _relative_difference(wanted["area"], candidate["area"]) / tol["size"]
    if wanted.get("radius") is not None and candidate.get("radius") is not None:
        size = max(size, _relative_difference(wanted["radius"], candidate["radius"]) / tol["size"])
    if pos > 1 or ang > 1 or size > 1:
        return None
    return pos + ang + size + (0 if wanted["origin"] == candidate["origin"] else 0.5)


def _faces_agree(wanted, candidate, tol):
    if not wanted or not candidate:
        return 0
    taken = set()
    total = 0
    for w in wanted:
        best = -1
        best_ang = math.inf
        for i, c in enumerate(candidate):
            if i in taken or c["kind"] != w["kind"]:
                continue
            ang = _angle_between(w["dir"], c["dir"])
            if ang < best_ang:
                best_ang = ang
                best = i
        if best < 0 or best_ang > tol["angle"]:
            return None
        taken.add(best)
        total += best_ang / tol["angle"]
    return total / len(wanted)


def edge_distance(wanted, candidate, tol):
    if wanted["kind"] != candidate["kind"]:
        return None
    pos = length(sub(wanted["mid"], candidate["mid"])) / tol["position"]
    ang = _angle_between(wanted["dir"], candidate["dir"]) / tol["angle"]
    size = _relative_difference(wanted["length"], candidate["length"]) / tol["size"]
    if wanted.get("radius") is not None and candidate.get("radius") is not None:
        size = max(size, _relative_difference(wanted["radius"], candidate["radius"]) / tol["size"])
    if pos > 1 or ang > 1 or size > 1:
        return None
    faces = _faces_agree(wanted["faces"], candidate["faces"], tol)
    if faces is None:
        return None
    return pos + ang + size + faces + (0 if wanted["origin"] == candidate["origin"] else 0.5)


def _relaxed(tol):
    return {"position": tol["position"] * 4, "angle": tol["angle"], "size": 0.9}


def _best(candidates, distance):
    best_index = None
    best_distance = math.inf
    for i, c in enumerate(candidates):
        d = distance(c)
        if d is not None and d < best_distance:
            best_distance = d
            best_index = i
    return best_index


def match_face(wanted, candidates, tol):
    """The index of the candidate nearest the wanted fingerprint within the
    tolerance, or of those the same feature made within the relaxed one, or
    None."""
    strict = _best(candidates, lambda c: face_distance(wanted, c, tol))
    if strict is not None or wanted["origin"] < 0:
        return strict
    loose = _relaxed(tol)
    return _best(candidates, lambda c: face_distance(wanted, c, loose) if c["origin"] == wanted["origin"] else None)


def match_edge(wanted, candidates, tol):
    strict = _best(candidates, lambda c: edge_distance(wanted, c, tol))
    if strict is not None or wanted["origin"] < 0:
        return strict
    loose = _relaxed(tol)
    return _best(candidates, lambda c: edge_distance(wanted, c, loose) if c["origin"] == wanted["origin"] else None)


def tangent_chain(edges, seeds, skip=frozenset(), angle=(3 * math.pi) / 180, join_tolerance=1e-3):
    """The edges tangent-continuous with the seeds (each {hash, ends,
    endTangents}), the seeds first, in the walk's order."""
    by_hash = {e["hash"]: e for e in edges}
    taken = set()
    out = []
    queue = []
    for s in seeds:
        if s in by_hash and s not in taken:
            taken.add(s)
            out.append(s)
            queue.append(s)
    cos_limit = math.cos(angle)
    while queue:
        e = by_hash[queue.pop(0)]
        for k in range(2):
            end = e["ends"][k]
            t = e["endTangents"][k]
            for other in edges:
                if other["hash"] in taken or other["hash"] in skip:
                    continue
                for j in range(2):
                    if length(sub(other["ends"][j], end)) > join_tolerance:
                        continue
                    if abs(dot(t, other["endTangents"][j])) < cos_limit:
                        continue
                    taken.add(other["hash"])
                    out.append(other["hash"])
                    queue.append(other["hash"])
                    break
    return out


def on_one_surface(a, b):
    """Whether two faces that meet tangent lie on one surface."""
    if a["kind"] != b["kind"]:
        return False
    k = a["kind"]
    if k == "plane":
        return True
    if k in ("cylinder", "cone"):
        if not a.get("center") or not b.get("center") or abs(dot(a["dir"], b["dir"])) < math.cos(ONE_SURFACE_ANGLE):
            return False
        d = sub(b["center"], a["center"])
        if length(sub(d, scale(a["dir"], dot(d, a["dir"])))) > ONE_SURFACE_MM:
            return False
        return k == "cone" or (a.get("radius") is not None and b.get("radius") is not None and abs(a["radius"] - b["radius"]) <= ONE_SURFACE_MM)
    if k == "sphere":
        return (a.get("center") is not None and b.get("center") is not None and a.get("radius") is not None and b.get("radius") is not None
                and length(sub(a["center"], b["center"])) <= ONE_SURFACE_MM and abs(a["radius"] - b["radius"]) <= ONE_SURFACE_MM)
    return False


def split_edges(topology):
    """The edges between two faces of one surface, by hash."""
    by_hash = {f["hash"]: f["fingerprint"] for f in topology["faces"]}
    out = set()
    for e in topology["edges"]:
        faces = list(dict.fromkeys(e["faces"]))
        a = by_hash.get(faces[0]) if faces else None
        b = by_hash.get(faces[1]) if len(faces) > 1 else None
        if not a or not b or a["kind"] != b["kind"]:
            continue
        one = dot(a["dir"], b["dir"]) >= math.cos(ONE_SURFACE_ANGLE) if a["kind"] == "plane" else a["kind"] in ("cylinder", "sphere") and on_one_surface(a, b)
        if one:
            out.add(e["hash"])
    return out


def _tenths(mm, units):
    return to_fixed(mm, 1) if units == "mm" else fmt_len(mm, units, 1, bare=True)


def _at(p, units):
    return f"({', '.join(_tenths(x, units) for x in p)})"


def _face_words(f, units):
    if f["kind"] in ("cylinder", "sphere"):
        size = f" Ø{_tenths(2 * f['radius'], units)}" if f.get("radius") is not None else ""
    else:
        size = f" {fmt_area(f['area'], units, 0)}"
    return f"{'face' if f['kind'] == 'other' else f['kind']}{size} at {_at(f['centroid'], units)}"


def _edge_words(e, units):
    if e["kind"] == "circle" and e.get("radius") is not None:
        return f"circle Ø{_tenths(2 * e['radius'], units)} at {_at(e['mid'], units)}"
    return f"{'edge' if e['kind'] == 'other' else e['kind']} {fmt_len(e['length'], units, 1)} at {_at(e['mid'], units)}"


def describe_face(f):
    """A face as a message names it: "cylinder Ø6.0 at (10.0, 10.0, 5.0)"."""
    return _face_words(f, "mm")


def describe_edge(e):
    """An edge as a message names it: "line 40.0 mm at (20.0, 0.0, 10.0)"."""
    return _edge_words(e, "mm")


def describe_face_in(units):
    return lambda f: _face_words(f, units)


def describe_edge_in(units):
    return lambda e: _edge_words(e, units)


def read_topology(kernel, shape, origins, deflection):
    """build.ts readTopology: a body's faces and edges as FaceInfo and
    EdgeInfo, from the kernel's descriptors and the body's face origins
    ({face hash: feature id}). An edge belongs to the newest of its faces.
    The pattern-copy marks (patternCopies.ts) come with the builder."""
    faces = []
    for f in kernel.describe_faces(shape):
        fp = {"kind": f["kind"], "centroid": f["centroid"], "dir": f["dir"], "area": f["area"], "origin": origins.get(f["hash"], -1)}
        if f.get("radius") is not None:
            fp["radius"] = f["radius"]
        if f.get("center") is not None:
            fp["center"] = f["center"]
        info = {"hash": f["hash"], "fingerprint": fp}
        if f.get("fullTurn") is not None:
            info["fullTurn"] = f["fullTurn"]
        faces.append(info)
    by_hash = {f["hash"]: f["fingerprint"] for f in faces}
    edges = []
    for e in kernel.describe_edges(shape, deflection):
        sides = [by_hash[h] for h in e["faceHashes"] if h in by_hash]
        origin = max([-1] + [f["origin"] for f in sides])
        fp = {"kind": e["kind"], "mid": e["mid"], "dir": e["dir"], "length": e["length"], "faces": [{"kind": f["kind"], "dir": f["dir"]} for f in sides], "origin": origin}
        if e.get("radius") is not None:
            fp["radius"] = e["radius"]
        edges.append({"hash": e["hash"], "fingerprint": fp, "faces": e["faceHashes"], "ends": e["ends"], "endTangents": e["endTangents"], "polyline": e["polyline"]})
    return {"faces": faces, "edges": edges}

