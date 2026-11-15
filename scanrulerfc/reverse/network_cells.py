# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/core/networkCells.ts
# SPDX-License-Identifier: AGPL-3.0-only
#
# The cells of a patch network: the regions of the scan its curves close.
#
# Two readings of the same network meet here. The curves as a graph (the
# nodes, and the curves leaving each in the order they leave it round the
# scan's normal there) have faces: walk along a curve, and at each node take
# the next curve clockwise from the one arrived by, and the walk goes round
# the face on its left. That gives a face's sides in order and its corners,
# but says nothing about which triangles it covers. The curves as cuts in
# the scan do: each trace marks the triangle edges it crosses (a section's
# point lies on one; a run along the edges marks the edges it runs along),
# and the triangles are flooded without crossing a marked edge. Each piece
# of the flood is a region; the curve on either side of the edges round it
# says which face of the graph it is.
#
# A face is a cell when its piece is closed (the flood stays inside the box
# round the curves and meets the scan's rim only round holes wholly inside
# it, which the map fills with a fan) and it has three to six sides. A node
# is a corner of the face where the boundary turns more than 30 degrees
# there, unless the node says otherwise.
#
# Nodes, curves, faces and readings are dicts with the original's fields; a
# half-edge is a dict {curve, forward}.

import math

import numpy as np

from ._js import js_hypot, js_round, to_fixed
from .network_curve import end_tangent

CORNER_DEG = 30
SIDES_MIN = 3
SIDES_MAX = 6
BOX_MARGIN = 0.5
UNFILLED_MARGIN = 0.25
FACE_AGREEMENT = 0.9
CRUMB_TRIANGLES = 12


def _key(h):
    return (h["curve"], bool(h["forward"]))


def _incidence(scan):
    """The triangles round each vertex (CSR, as lists), made once a scan."""
    inc = getattr(scan, "_cells_incidence", None)
    if inc is not None:
        return inc
    flat = scan.F.reshape(-1)
    order = np.argsort(flat, kind="stable")
    counts = np.bincount(flat, minlength=scan.vertex_count)
    offsets = np.zeros(scan.vertex_count + 1, dtype=np.int64)
    np.cumsum(counts, out=offsets[1:])
    inc = (offsets.tolist(), (order // 3).tolist())
    scan._cells_incidence = inc
    return inc


def _across(scan, inc, t, a, b):
    """The triangles across edge (a, b) from t."""
    idx = scan.indices
    offsets, lst = inc
    out = []
    for k in range(offsets[a], offsets[a + 1]):
        u = lst[k]
        if u == t:
            continue
        if idx[u * 3] == b or idx[u * 3 + 1] == b or idx[u * 3 + 2] == b:
            out.append(u)
    return out


def _mark_edges(scan, curves):
    vertex_count = scan.vertex_count
    by_edge = {}
    m_curve = []
    m_at = []
    m_dir = []
    nan3 = [math.nan, math.nan, math.nan]

    def mark(a, b, curve, p, d):
        k = a * vertex_count + b if a < b else b * vertex_count + a
        m = len(m_curve)
        m_curve.append(curve)
        m_at.append(p if p is not None else nan3)
        m_dir.append(d if d is not None else nan3)
        by_edge.setdefault(k, []).append(m)

    p = scan.positions
    for c in curves:
        t = c["trace"]
        P = t["points"].astype(float).tolist()
        on = t["on"].tolist()
        n = len(P) // 3

        def pt(i):
            return P[i * 3:i * 3 + 3]

        for run in t["runs"]:
            if run["way"] == "section":
                for i in range(max(run["from"], 1), min(run["to"], n - 2) + 1):
                    a = on[i * 2]
                    b = on[i * 2 + 1]
                    if a < 0 or a == b:
                        continue
                    q0 = pt(i - 1)
                    q1 = pt(i + 1)
                    mark(a, b, c["id"], pt(i), [q1[0] - q0[0], q1[1] - q0[1], q1[2] - q0[2]])
            else:
                for i in range(run["from"], run["to"]):
                    a = on[i * 2]
                    b = on[(i + 1) * 2]
                    if a < 0 or b < 0 or a != on[i * 2 + 1] or b != on[(i + 1) * 2 + 1] or a == b:
                        continue
                    mark(a, b, c["id"], [p[a * 3], p[a * 3 + 1], p[a * 3 + 2]], [p[b * 3] - p[a * 3], p[b * 3 + 1] - p[a * 3 + 1], p[b * 3 + 2] - p[a * 3 + 2]])
                for tri in run["ends"]:
                    if tri < 0:
                        continue
                    v = [scan.indices[tri * 3], scan.indices[tri * 3 + 1], scan.indices[tri * 3 + 2]]
                    for e in range(3):
                        mark(v[e], v[(e + 1) % 3], c["id"], None, None)
    return by_edge, m_curve, m_at, m_dir


def _perpendicular(n):
    a = [1.0, 0.0, 0.0] if abs(n[0]) < 0.9 else [0.0, 1.0, 0.0]
    d = a[0] * n[0] + a[1] * n[1] + a[2] * n[2]
    u = [a[0] - d * n[0], a[1] - d * n[1], a[2] - d * n[2]]
    l = js_hypot(u[0], u[1], u[2]) or 1
    return [u[0] / l, u[1] / l, u[2] / l]


def graph_faces(scan, nodes, curves):
    """The graph's faces from the order the curves leave each node in."""
    around = {}
    node_at = {n["id"]: n for n in nodes}

    def add(node, edge, d):
        n = node_at.get(node)
        if n is None:
            return
        c = scan.closest(n["at"])
        normal = scan.normal_at(c.point, c.triangle) if c is not None else [0.0, 0.0, 1.0]
        e1 = _perpendicular(normal)
        e2 = [normal[1] * e1[2] - normal[2] * e1[1], normal[2] * e1[0] - normal[0] * e1[2], normal[0] * e1[1] - normal[1] * e1[0]]
        angle = math.atan2(d[0] * e2[0] + d[1] * e2[1] + d[2] * e2[2], d[0] * e1[0] + d[1] * e1[1] + d[2] * e1[2])
        around.setdefault(node, []).append({"edge": edge, "angle": angle})

    for c in curves:
        out = end_tangent(c["fit"], 0)
        into = end_tangent(c["fit"], 1)
        add(c["from"], {"curve": c["id"], "forward": True}, out)
        add(c["to"], {"curve": c["id"], "forward": False}, [-into[0], -into[1], -into[2]])
    for lst in around.values():
        lst.sort(key=lambda x: x["angle"])
    curve_of = {c["id"]: c for c in curves}

    def arrives(h):
        c = curve_of[h["curve"]]
        return c["to"] if h["forward"] else c["from"]

    def nxt(h):
        lst = around.get(arrives(h))
        if lst is None:
            return None
        back = -1
        for i, l in enumerate(lst):
            if l["edge"]["curve"] == h["curve"] and l["edge"]["forward"] == (not h["forward"]):
                back = i
                break
        if back < 0:
            return None
        return lst[(back - 1 + len(lst)) % len(lst)]["edge"]

    seen = set()
    faces = []
    for c in curves:
        for forward in (True, False):
            start = {"curve": c["id"], "forward": forward}
            if _key(start) in seen:
                continue
            edges = []
            nodes_of = []
            h = start
            guard = 0
            while h is not None and _key(h) not in seen and guard < 4 * len(curves) + 4:
                seen.add(_key(h))
                edges.append(h)
                nodes_of.append(arrives(h))
                h = nxt(h)
                guard += 1
            if edges:
                faces.append({"edges": edges, "nodes": nodes_of})
    return faces


def _where(p):
    return "(" + ", ".join(to_fixed(js_round(x * 10) / 10, 1) for x in p) + ")"


def face_sides(face, nodes, curves, corners_given=None):
    """A face's corners and sides, {corners, sides}, or why it has none to
    fill, {message, at?}."""
    curve_of = {c["id"]: c for c in curves}
    node_of = {n["id"]: n for n in nodes}
    m = len(face["edges"])
    if any(g["curve"] == h["curve"] and g["forward"] != h["forward"] for h in face["edges"] for g in face["edges"]):
        valence = {}
        for c in curves:
            valence[c["from"]] = valence.get(c["from"], 0) + 1
            valence[c["to"]] = valence.get(c["to"], 0) + 1
        dangling = None
        for nid in face["nodes"]:
            n = node_of.get(nid)
            if n is not None and valence.get(n["id"]) == 1:
                dangling = n
                break
        out = {"message": f"a curve ends inside it{' at ' + _where(dangling['at']) if dangling else ''} — take it on to another curve, or delete it"}
        if dangling:
            out["at"] = dangling["at"]
        return out

    def leave(h):
        c = curve_of[h["curve"]]
        if h["forward"]:
            return end_tangent(c["fit"], 0)
        t = end_tangent(c["fit"], 1)
        return [-t[0], -t[1], -t[2]]

    corners = []
    corner_after = []
    for i in range(m):
        h = face["edges"][i]
        g = face["edges"][(i + 1) % m]
        node = face["nodes"][i]
        back = leave({"curve": h["curve"], "forward": not h["forward"]})
        out = leave(g)
        cos = -(back[0] * out[0] + back[1] * out[1] + back[2] * out[2])
        turn = (math.acos(max(-1.0, min(1.0, cos))) * 180) / math.pi
        if corners_given is not None:
            given = node in corners_given
        else:
            given = node_of.get(node, {}).get("corner")
        if (given if given is not None else turn > CORNER_DEG):
            corners.append(node)
            corner_after.append(i)
    if not corners:
        return {"message": "one side — a closed curve with no corner; add a node where it turns"}
    sides = []
    for k in range(len(corner_after)):
        frm = corner_after[k]
        to = corner_after[(k + 1) % len(corner_after)]
        edges = []
        i = (frm + 1) % m
        while True:
            edges.append(face["edges"][i])
            if i == to:
                break
            i = (i + 1) % m
        sides.append({"edges": edges})
    return {"corners": [face["nodes"][i] for i in corner_after], "sides": sides}


def _scan_is_closed(scan):
    had = getattr(scan, "_cells_closed", None)
    if had is not None:
        return had
    F = scan.F
    a = np.concatenate([F[:, 0], F[:, 1], F[:, 2]])
    b = np.concatenate([F[:, 1], F[:, 2], F[:, 0]])
    key = np.minimum(a, b) * scan.vertex_count + np.maximum(a, b)
    _, counts = np.unique(key, return_counts=True)
    closed = bool(scan.triangle_count > 0 and (counts >= 2).all()) or scan.triangle_count == 0
    scan._cells_closed = closed
    return closed


def _inside_point(scan, triangles):
    T = np.asarray(triangles, dtype=np.int64)
    M = scan.P[scan.F[T]].sum(axis=1) / 3
    c = M.sum(axis=0) / T.shape[0]
    d = M - c
    i = int(np.argmin(np.sqrt((d * d).sum(axis=1))))
    return [float(x) for x in M[i]]


def read_cells(scan, nodes, curves, seeds, corners_of=()):
    """The network's cells: {faces, cells, unfilled}."""
    faces = graph_faces(scan, nodes, curves)
    if not curves:
        return {"faces": faces, "cells": [{"status": "refused", "seed": s, "message": "no curves close it"} for s in seeds], "unfilled": []}
    inc = _incidence(scan)
    by_edge, m_curve, m_at, m_dir = _mark_edges(scan, curves)
    idx = scan.indices
    pos = scan.positions
    vertex_count = scan.vertex_count
    lo = [math.inf] * 3
    hi = [-math.inf] * 3
    for c in curves:
        P = c["trace"]["points"].reshape(-1, 3)
        if P.shape[0]:
            mn = P.min(axis=0)
            mx = P.max(axis=0)
            for k in range(3):
                lo[k] = min(lo[k], float(mn[k]))
                hi[k] = max(hi[k], float(mx[k]))
    diagonal = js_hypot(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2])
    margin = BOX_MARGIN * diagonal + 4 * scan.edge
    near = UNFILLED_MARGIN * diagonal + 4 * scan.edge
    near_lo = [lo[k] - near for k in range(3)]
    near_hi = [hi[k] + near for k in range(3)]
    lo = [lo[k] - margin for k in range(3)]
    hi = [hi[k] + margin for k in range(3)]
    centre = (scan.P[scan.F].sum(axis=1) / 3)

    def box_mask(a, b):
        return ((centre >= np.array(a)) & (centre <= np.array(b))).all(axis=1).tolist()

    in_box = box_mask(lo, hi)
    in_near = box_mask(near_lo, near_hi)
    face_of = {}
    for i, f in enumerate(faces):
        for h in f["edges"]:
            face_of[_key(h)] = i
    label = [-1] * scan.triangle_count
    pieces = []

    def flood(start, within=in_box, stop=False):
        pid = len(pieces)
        piece = {"triangles": [], "leaked": None, "rim": [], "votes": {}}
        pieces.append(piece)
        queue = [start]
        label[start] = pid
        votes = piece["votes"]
        while queue and not (stop and piece["leaked"] is not None):
            t = queue.pop()
            piece["triangles"].append(t)
            for e in range(3):
                a = idx[t * 3 + e]
                b = idx[t * 3 + (e + 1) % 3]
                w = idx[t * 3 + (e + 2) % 3]
                marked = by_edge.get(a * vertex_count + b if a < b else b * vertex_count + a)
                if marked is not None:
                    for m in marked:
                        d = m_dir[m]
                        if d[0] != d[0]:
                            continue
                        n = scan.triangle_normal(t)
                        left = [n[1] * d[2] - n[2] * d[1], n[2] * d[0] - n[0] * d[2], n[0] * d[1] - n[1] * d[0]]
                        at = m_at[m]
                        side = (pos[w * 3] - at[0]) * left[0] + (pos[w * 3 + 1] - at[1]) * left[1] + (pos[w * 3 + 2] - at[2]) * left[2]
                        k = (m_curve[m], side > 0)
                        votes[k] = votes.get(k, 0) + 1
                    continue
                nb = _across(scan, inc, t, a, b)
                if not nb:
                    piece["rim"].append((a, b))
                    continue
                for u in nb:
                    if label[u] >= 0:
                        if label[u] != pid and pieces[label[u]]["leaked"] is not None and piece["leaked"] is None:
                            piece["leaked"] = pieces[label[u]]["leaked"]
                        continue
                    if not within[u]:
                        if piece["leaked"] is None:
                            piece["leaked"] = [pos[a * 3], pos[a * 3 + 1], pos[a * 3 + 2]]
                        continue
                    label[u] = pid
                    queue.append(u)
        return pid

    curve_count = {}
    for c in curves:
        curve_count[c["from"]] = curve_count.get(c["from"], 0) + 1
        curve_count[c["to"]] = curve_count.get(c["to"], 0) + 1

    def open_at(near_p, fallback):
        best = None
        best_d = math.inf
        for n in nodes:
            if curve_count.get(n["id"], 0) != 1:
                continue
            d = js_hypot(n["at"][0] - near_p[0], n["at"][1] - near_p[1], n["at"][2] - near_p[2])
            if d < best_d:
                best_d, best = d, n["at"]
        return best if best is not None else fallback

    def turning(loop):
        total = 0.0
        m = len(loop)
        for i in range(m):
            p = loop[(i - 1 + m) % m] * 3
            q = loop[i] * 3
            r = loop[(i + 1) % m] * 3
            a = [pos[q] - pos[p], pos[q + 1] - pos[p + 1], pos[q + 2] - pos[p + 2]]
            b = [pos[r] - pos[q], pos[r + 1] - pos[q + 1], pos[r + 2] - pos[q + 2]]
            n = scan.normal_at([pos[q], pos[q + 1], pos[q + 2]], 0)
            c = [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
            total += math.atan2(c[0] * n[0] + c[1] * n[1] + c[2] * n[2], a[0] * b[0] + a[1] * b[1] + a[2] * b[2])
        return total

    def holes_of(piece):
        if not piece["rim"]:
            return []
        next_of = {}
        for a, b in piece["rim"]:
            next_of.setdefault(a, []).append(b)
        used = set()
        loops = []
        for a0, b0 in piece["rim"]:
            if (a0, b0) in used:
                continue
            loop = [a0]
            a = a0
            b = b0
            while True:
                used.add((a, b))
                if b == a0:
                    break
                loop.append(b)
                options = [x for x in next_of.get(b, []) if (b, x) not in used]
                if not options:
                    return None
                a = b
                b = options[0]
            if turning(loop) > 0:
                return None
            loops.append(loop)
        return loops

    dangling_in = {}
    for n in nodes:
        if curve_count.get(n["id"], 0) != 1:
            continue
        c = scan.closest_inside(n["at"])
        if c is not None:
            dangling_in[c.triangle] = n["at"]

    def gap_in(piece):
        for t in piece["triangles"]:
            at = dangling_in.get(t)
            if at is not None:
                return at
        return None

    def read(piece, seed, corners=None):
        if piece["leaked"] is not None:
            gap = gap_in(piece)
            at = gap if gap is not None else open_at(seed, piece["leaked"])
            return {"status": "refused", "seed": seed, "message": f"not closed — open at {_where(at)}", "at": at}
        holes = holes_of(piece)
        if holes is None:
            gap = gap_in(piece)
            if gap is not None:
                return {"status": "refused", "seed": seed, "message": f"not closed — open at {_where(gap)}", "at": gap}
            v = piece["rim"][0][0]
            return {"status": "refused", "seed": seed, "message": "the scan’s rim runs through it", "at": [pos[v * 3], pos[v * 3 + 1], pos[v * 3 + 2]]}
        total = 0
        by_face = {}
        for k, v in piece["votes"].items():
            total += v
            f = face_of.get(k)
            if f is not None:
                by_face[f] = by_face.get(f, 0) + v
        face = -1
        best = 0
        for f, v in by_face.items():
            if v > best:
                best, face = v, f
        if face < 0 or best < FACE_AGREEMENT * total:
            return {"status": "refused", "seed": seed, "message": "two curves cross where no node joins them — snap one to the other"}
        sides = face_sides(faces[face], nodes, curves, corners)
        if "message" in sides:
            out = {"status": "refused", "seed": seed, "message": sides["message"]}
            if sides.get("at") is not None:
                out["at"] = sides["at"]
            return out
        count = len(sides["corners"])
        if count < SIDES_MIN:
            return {"status": "refused", "seed": seed, "message": "two sides" if count == 2 else "one side"}
        if count > SIDES_MAX:
            return {"status": "refused", "seed": seed, "message": f"{count} sides — split it with a curve"}
        return {"status": "ok", "seed": seed, "face": face, "corners": sides["corners"], "sides": sides["sides"], "triangles": np.array(piece["triangles"], dtype=np.int64), "holes": holes}

    cells = []
    seeded = set()
    corners_of = list(corners_of)
    for k, seed in enumerate(seeds):
        c = scan.closest(seed)
        if c is None:
            cells.append({"status": "refused", "seed": seed, "message": "not on the scan"})
            continue
        pid = label[c.triangle] if label[c.triangle] >= 0 else flood(c.triangle)
        piece = pieces[pid]
        reading = read(piece, seed, corners_of[k] if k < len(corners_of) else None)
        if pid in seeded and reading["status"] == "ok":
            cells.append({"status": "refused", "seed": seed, "message": "filled already by another seed"})
            continue
        seeded.add(pid)
        cells.append(reading)
    offsets, lst = inc
    for k in list(by_edge.keys()):
        a = k // vertex_count
        b = k - a * vertex_count
        for i in range(offsets[a], offsets[a + 1]):
            t = lst[i]
            if label[t] >= 0 or not in_near[t]:
                continue
            if idx[t * 3] == b or idx[t * 3 + 1] == b or idx[t * 3 + 2] == b:
                flood(t, in_near, True)
    candidates = []
    for pid, piece in enumerate(pieces):
        if len(piece["triangles"]) < CRUMB_TRIANGLES and pid not in seeded:
            continue
        r = read(piece, [0.0, 0.0, 0.0])
        if r["status"] == "ok":
            candidates.append({"id": pid, "size": len(piece["triangles"]), "sides": len(r["corners"]), "seeded": pid in seeded})
    if _scan_is_closed(scan) and candidates:
        largest = candidates[0]
        for c in candidates[1:]:
            if c["size"] > largest["size"]:
                largest = c
        candidates.remove(largest)
    unfilled = [{"seed": _inside_point(scan, pieces[c["id"]]["triangles"]), "sides": c["sides"]} for c in candidates if not c["seeded"]]
    return {"faces": faces, "cells": cells, "unfilled": unfilled}
