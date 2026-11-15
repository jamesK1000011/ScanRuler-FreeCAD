# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/core/networkSplit.ts
# SPDX-License-Identifier: AGPL-3.0-only
#
# A cell of three, five or six sides split into four-sided ones from its
# centre.
#
# The cell is mapped onto a regular polygon of as many corners
# (network_map.py); its centre is the scan point at the polygon's middle,
# or where the operator dragged it. Each side is split at its middle by arc
# length with a node (a T-node for the cell on its other side, whose side
# then runs through it straight on) and a spoke runs from the centre to
# each: n four-sided cells, meeting at a corner of n patches at the centre,
# where the fit reports the angle instead of holding it.
#
# The spokes and the nodes are made for the build and are not the
# feature's: they are made again from the cell's sides every build, so they
# follow the sides when a curve moves; only the centre a hand dragged is
# kept, on the cell. Their ids are counted from DERIVED_IDS on, in the order
# the cells and their sides come, so the same network gives the same ids
# build after build: what a strip's span count is keyed by.

import numpy as np

from .network_curve import fit_provisional, trace_curve
from .network_map import cell_mesh, map_cell, polygon_corners

DERIVED_IDS = 1_000_000
REUSE_SHARE = 0.02


def point_at_uv(mesh, mp, u, v):
    """The point of a mapped cell at (u, v) of its polygon, or None off it."""
    t = mesh["triangles"].reshape(-1, 3)
    U = mp["uv"].reshape(-1, 2)
    P = mesh["positions"].reshape(-1, 3)
    a, b, c = t[:, 0], t[:, 1], t[:, 2]
    x0, y0 = U[a, 0], U[a, 1]
    x1, y1 = U[b, 0] - x0, U[b, 1] - y0
    x2, y2 = U[c, 0] - x0, U[c, 1] - y0
    det = x1 * y2 - x2 * y1
    with np.errstate(divide="ignore", invalid="ignore"):
        s = ((u - x0) * y2 - x2 * (v - y0)) / det
        r = (x1 * (v - y0) - (u - x0) * y1) / det
        ok = (np.abs(det) > 1e-18) & ~(s < -1e-9) & ~(r < -1e-9) & ~(s + r > 1 + 1e-9)
    hit = np.nonzero(ok)[0]
    if hit.size == 0:
        return None
    f = int(hit[0])
    w = 1 - s[f] - r[f]
    return [float(w * P[a[f], k] + s[f] * P[b[f], k] + r[f] * P[c[f], k]) for k in range(3)]


def _slice_trace(t, frm, to):
    at = t["at"][frm:to + 1].copy()
    at -= at[0]
    return {
        "points": t["points"][frm * 3:(to + 1) * 3].copy(),
        "on": t["on"][frm * 2:(to + 1) * 2].copy(),
        "at": at,
        "length": float(at[-1]),
        "grips": [0, *[g - frm for g in t["grips"] if frm < g < to], to - frm],
        "runs": [dict(r, **{"from": max(r["from"], frm) - frm, "to": min(r["to"], to) - frm}) for r in t["runs"] if r["to"] > frm and r["from"] < to],
    }


def split_polygons(scan, traced, cells, centres_given):
    """The network's cells of three, five or six sides split, or None when
    there is none: {traced, seeds, owner, corners, spokes, centres, refused,
    originOf}."""
    if not any(c["status"] == "ok" and len(c["sides"]) != 4 for c in cells):
        return None
    nodes = [dict(n) for n in traced["nodes"]]
    curves = {c["id"]: c for c in traced["curves"]}
    pieces = {c["id"]: [c["id"]] for c in traced["curves"]}
    counter = [DERIVED_IDS]

    def next_id():
        i = counter[0]
        counter[0] += 1
        return i

    def node_at(nid):
        return next(n for n in nodes if n["id"] == nid)["at"]

    seeds = []
    owner = []
    quad_corners = []
    spokes = []
    centres = []
    refused = {}

    def side_pieces(side):
        out = []
        for h in side["edges"]:
            lst = pieces.get(h["curve"], [h["curve"]])
            for curve in (lst if h["forward"] else list(reversed(lst))):
                out.append({"curve": curve, "forward": h["forward"]})
        return out

    def middle_of(side):
        parts = side_pieces(side)
        lengths = [curves[p["curve"]]["trace"]["length"] for p in parts]
        total = sum(lengths)
        acc = 0.0
        for k in range(len(parts) - 1):
            acc += lengths[k]
            if abs(acc - total / 2) <= REUSE_SHARE * total:
                c = curves[parts[k]["curve"]]
                return c["to"] if parts[k]["forward"] else c["from"]
        acc = 0.0
        for k in range(len(parts)):
            if acc + lengths[k] < total / 2 and k + 1 < len(parts):
                acc += lengths[k]
                continue
            part = parts[k]
            c = curves[part["curve"]]
            t = c["trace"]
            along = total / 2 - acc if part["forward"] else t["length"] - (total / 2 - acc)
            i = 1
            while i < len(t["at"]) - 2 and t["at"][i] < along:
                i += 1
            node = next_id()
            second = next_id()
            at = [float(t["points"][i * 3]), float(t["points"][i * 3 + 1]), float(t["points"][i * 3 + 2])]
            nodes.append({"id": node, "at": at})
            a = _slice_trace(t, 0, i)
            b = _slice_trace(t, i, len(t["at"]) - 1)
            curves[c["id"]] = dict(c, to=node, trace=a, fit=fit_provisional(a, scan.edge))
            curves[second] = {"id": second, "from": node, "to": c["to"], "trace": b, "fit": fit_provisional(b, scan.edge)}
            for original, lst in pieces.items():
                if c["id"] in lst:
                    lst.insert(lst.index(c["id"]) + 1, second)
                    break
            return node
        return curves[parts[-1]["curve"]]["to"] if parts else -1

    for index, cell in enumerate(cells):
        if cell["status"] != "ok" or len(cell["sides"]) == 4:
            seeds.append(cell["seed"])
            owner.append(index)
            quad_corners.append(set(cell["corners"]) if cell["status"] == "ok" else None)
            continue
        n = len(cell["sides"])
        mesh = cell_mesh(scan, cell["triangles"], cell["holes"], [node_at(c) for c in cell["corners"]])
        mp = mesh if isinstance(mesh, str) else map_cell(mesh)
        if isinstance(mesh, str) or isinstance(mp, str):
            refused[index] = mesh if isinstance(mesh, str) else mp
            seeds.append(cell["seed"])
            owner.append(index)
            quad_corners.append(None)
            continue
        given = centres_given[index] if index < len(centres_given) else None
        middle = given if given is not None else point_at_uv(mesh, mp, 0.5, 0.5)
        on_scan = scan.closest_inside(middle) if middle is not None else None
        if on_scan is None:
            refused[index] = "its centre is off the scan"
            seeds.append(cell["seed"])
            owner.append(index)
            quad_corners.append(None)
            continue
        centre = next_id()
        nodes.append({"id": centre, "at": on_scan.point})
        centres.append({"cell": index, "at": on_scan.point})
        mids = [middle_of(s) for s in cell["sides"]]
        for k in range(n):
            cid = next_id()
            trace = trace_curve(scan, [on_scan.point, node_at(mids[k])])
            if len(trace["points"]) < 6:
                continue
            trace["points"][0:3] = on_scan.point
            trace["points"][-3:] = node_at(mids[k])
            curves[cid] = {"id": cid, "from": centre, "to": mids[k], "trace": trace, "fit": fit_provisional(trace, scan.edge)}
            spokes.append({"cell": index, "curve": cid, "points": trace["points"]})
        poly = polygon_corners(n)

        def mid(k):
            a = poly[((k % n) + n) % n]
            b = poly[(((k + 1) % n) + n) % n]
            return [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]

        for k in range(n):
            quad = [[0.5, 0.5], mid(k - 1), poly[k], mid(k)]
            u = sum(q[0] for q in quad) / 4
            v = sum(q[1] for q in quad) / 4
            seed = point_at_uv(mesh, mp, u, v)
            if seed is None:
                continue
            inside = scan.closest_inside(seed)
            seeds.append(inside.point if inside is not None else seed)
            owner.append(index)
            quad_corners.append({centre, mids[(k - 1 + n) % n], cell["corners"][k], mids[k]})
    origin_of = {}
    for original, lst in pieces.items():
        for cid in lst:
            if cid != original:
                origin_of[cid] = original
    return {"traced": {"nodes": nodes, "curves": list(curves.values()), "lost": traced["lost"]}, "seeds": seeds, "owner": owner, "corners": quad_corners,
            "spokes": spokes, "centres": centres, "refused": refused, "originOf": origin_of}
