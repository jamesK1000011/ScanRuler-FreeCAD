# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/core/network.ts
# SPDX-License-Identifier: AGPL-3.0-only
#
# A patch network read off the scan, stage by stage: its nodes taken onto
# the scan and its curves traced along it (network_curve.py), the regions
# the curves close read into cells (network_cells.py), each four-sided cell
# mapped onto the square (network_map.py), and the patches fitted together
# (network_fit.py). Pure geometry over the scan's triangles: the build runs
# it, a test runs it on a synthetic scan.
#
# A preview reads the network again at every edit, and an edit changes a
# curve or two and a cell or two: each curve's trace is kept by the points
# it was traced through, and each cell's points and their (u, v) by the
# triangles and corners they were mapped from, for the next read on the
# same scan; what the last few reads did not use is let go. The same input
# gives the same answer, kept or not.
#
# The feature, nodes, curves and the reading are dicts with the original's
# fields. `bodies`, where a network rests on bodies, is an object with
# edge(body, ref) -> float32 points or None and normals(body, face, points)
# -> unit normals or None (the build's, over the kernel).

import json
import math
import time

import numpy as np

from ._js import js_hypot
from .network_cells import read_cells
from .network_curve import curve_points, fit_provisional, trace_curve
from .network_fit import fit_network
from .network_map import cell_mesh, map_cell

KEPT_READS = 4
EDGE_GRIP_MM = 3
EDGE_STEP_MM = 0.5


def _ms():
    return time.perf_counter() * 1000


class ReadCache:
    """What the reads of networks on one scan keep for the next."""

    def __init__(self):
        self.read = 0
        self.traces = {}
        self.cells = {}

    def begin(self):
        self.read += 1
        for store in (self.traces, self.cells):
            for k in [k for k, v in store.items() if v["used"] <= self.read - KEPT_READS]:
                del store[k]

    def trace(self, scan, points):
        key = json.dumps([[float(x) for x in p] for p in points])
        had = self.traces.get(key)
        if had is None:
            trace = trace_curve(scan, points)
            if len(trace["points"]) < 6:
                return None
            trace["points"][0:3] = points[0]
            trace["points"][-3:] = points[-1]
            had = {"trace": trace, "fit": fit_provisional(trace, scan.edge), "used": 0}
            self.traces[key] = had
        had["used"] = self.read
        return {"trace": dict(had["trace"], points=had["trace"]["points"].copy()), "fit": had["fit"]}

    def cell(self, triangles, holes, corners, make):
        key = _cell_key(triangles, holes, corners)
        had = self.cells.get(key)
        if had is None:
            had = {"data": make(), "used": 0}
            self.cells[key] = had
        had["used"] = self.read
        return had["data"]


def _cell_key(triangles, holes, corners):
    return (np.asarray(triangles, dtype=np.int64).tobytes(), tuple(tuple(h) for h in holes), np.asarray(corners, dtype=float).tobytes())


def _cache_of(scan):
    c = getattr(scan, "_network_read_cache", None)
    if c is None:
        c = ReadCache()
        scan._network_read_cache = c
    return c


def read_network(scan, f, bodies=None):
    """The network read off the scan, every stage: {traced, cells,
    outcomes, fit, split, ms}."""
    from .network_split import split_polygons

    t0 = _ms()
    cache = _cache_of(scan)
    cache.begin()
    traced = trace_network(scan, f["nodes"], f["curves"], bodies, cache)
    t1 = _ms()
    cells_given = f["cells"]
    first = read_cells(scan, traced["nodes"], traced["curves"], [c["seed"] for c in cells_given],
                       [set(c["corners"]) if c.get("corners") and len(c["corners"]) >= 3 else None for c in cells_given])
    split = split_polygons(scan, traced, first["cells"], [c.get("centre") for c in cells_given])
    graph = split["traced"] if split else traced
    if split:
        cells = dict(read_cells(scan, graph["nodes"], graph["curves"], split["seeds"], split["corners"]), faces=first["faces"])
        owner = split["owner"]
    else:
        cells = first
        owner = list(range(len(first["cells"])))
    t2 = _ms()
    at = {n["id"]: n["at"] for n in graph["nodes"]}
    patches = []
    read = []
    for c in cells["cells"]:
        if c["status"] != "ok":
            r = {"refused": c["message"]}
            if c.get("at") is not None:
                r["at"] = c["at"]
            read.append(r)
            continue
        if len(c["sides"]) != 4:
            read.append({"refused": f"{len(c['sides'])} sides — split from its centre, it did not come out four-sided"})
            continue
        corners = [at[i] for i in c["corners"]]

        def make(c=c, corners=corners):
            mesh = cell_mesh(scan, c["triangles"], c["holes"], corners)
            if isinstance(mesh, str):
                return mesh
            mp = map_cell(mesh)
            if isinstance(mp, str):
                return mp
            on_loop = np.zeros(mesh["scanVertex"].shape[0], dtype=bool)
            on_loop[mesh["loop"]] = True
            take = (mesh["scanVertex"] >= 0) & ~on_loop
            xyz = mesh["positions"].reshape(-1, 3)[take].reshape(-1)
            uv = mp["uv"].reshape(-1, 2)[take].reshape(-1)
            return {"xyz": xyz.copy(), "uv": uv.copy()}

        data = cache.cell(c["triangles"], c["holes"], corners, make)
        if isinstance(data, str):
            read.append({"refused": data})
            continue
        patches.append({"sides": c["sides"], "corners": c["corners"], "xyz": data["xyz"], "uv": data["uv"], "seed": c["seed"]})
        read.append({"patch": len(patches) - 1})
    outcomes = []
    for i, cell in enumerate(cells_given):
        fc = first["cells"][i] if i < len(first["cells"]) else None
        sides = len(fc["sides"]) if fc is not None and fc["status"] == "ok" else 0
        why = split["refused"].get(i) if split else None
        if why:
            outcomes.append({"seed": cell["seed"], "refused": f"{sides} sides, and it could not be split from its centre: {why}"})
            continue
        mine = [r for k, r in enumerate(read) if owner[k] == i]
        bad = next((r for r in mine if "refused" in r), None)
        if bad is not None:
            o = {"seed": cell["seed"], "refused": f"split from its centre: {bad['refused']}" if sides > 0 and sides != 4 else bad["refused"]}
            if bad.get("at") is not None:
                o["at"] = bad["at"]
            outcomes.append(o)
            continue
        lst = [r["patch"] if "patch" in r else -1 for r in mine]
        if not lst:
            outcomes.append({"seed": cell["seed"], "refused": "nothing came of it"})
            continue
        outcomes.append({"seed": cell["seed"], "sides": sides, "patch": lst[0], "patches": lst})
    t3 = _ms()
    crease = {c["id"]: c.get("crease") is True for c in f["curves"]}

    def crease_of(cid):
        if cid in crease:
            return crease[cid]
        if split and cid in split["originOf"]:
            return crease.get(split["originOf"][cid], False)
        return False

    fit = None
    if patches:
        fit_opts = f.get("fit") or {}
        body_sides = []
        for c in f["curves"]:
            if c.get("side") and bodies is not None:
                side = c["side"]
                body_sides.append({"curve": c["id"], "mode": side["mode"], "normals": (lambda points, side=side: bodies.normals(side["body"], side["face"], points))})
        fit = fit_network({
            "patches": patches,
            "curves": [dict(c, crease=crease_of(c["id"])) for c in graph["curves"]],
            "nodes": graph["nodes"],
            "spans": f.get("spans") or {},
            "smoothness": fit_opts.get("smoothness", 0.001),
            "robust": fit_opts.get("robust"),
            "tolerance": fit_opts.get("tolerance"),
            "spacing": scan.edge,
            "bodySides": body_sides,
        })
    t4 = _ms()
    return {"traced": graph, "cells": cells, "outcomes": outcomes, "fit": fit, "split": {"spokes": split["spokes"], "centres": split["centres"]} if split else None,
            "ms": {"trace": t1 - t0, "cells": t2 - t1, "map": t3 - t2, "fit": t4 - t3}}


def _densified(points, step):
    P = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    out = []
    for i in range(P.shape[0]):
        if i > 0:
            d = js_hypot(*(P[i] - P[i - 1]).tolist())
            k = math.ceil(d / step)
            for j in range(1, k):
                for c in range(3):
                    out.append(P[i - 1, c] + ((P[i, c] - P[i - 1, c]) * j) / k)
        out.extend(P[i].tolist())
    return np.asarray(out, dtype=np.float32)


def _along_polyline(p, t):
    want = min(1.0, max(0.0, t)) * p["length"]
    at = p["at"]
    pts = p["points"]
    i = 1
    while i < len(at) - 1 and at[i] < want:
        i += 1
    span = (at[i] - at[i - 1]) or 1
    f = min(1.0, max(0.0, (want - at[i - 1]) / span))
    return [float(pts[(i - 1) * 3 + k]) + f * (float(pts[i * 3 + k]) - float(pts[(i - 1) * 3 + k])) for k in range(3)]


def _nearest_index(p, q):
    P = np.asarray(p, dtype=np.float64).reshape(-1, 3)
    d = P - np.asarray(q, dtype=float)
    return int(np.argmin(np.sqrt((d * d).sum(axis=1))))


def _trace_ends(scan, points):
    trace = trace_curve(scan, points)
    if len(trace["points"]) < 6:
        return None
    trace["points"][0:3] = points[0]
    trace["points"][-3:] = points[-1]
    return {"trace": trace, "fit": fit_provisional(trace, scan.edge)}


def trace_network(scan, nodes, curves, bodies=None, cache=None):
    """Each node taken onto the scan (or onto the body edge or corner it is
    on), each curve traced from its node through its grips to its other
    node and fitted at its own Auto for the directions it leaves its nodes
    by: {nodes, curves, lost, lostWhy?}."""
    placed = {}
    for n in nodes:
        at = None
        on = n.get("on")
        if on and bodies is not None:
            edge = bodies.edge(on["body"], on["edge"] if "edge" in on else on["vertex"])
            if edge is not None and len(edge) >= 6:
                p = curve_points(edge)
                if "edge" in on:
                    at = _along_polyline(p, on["t"])
                elif on.get("end") == 0:
                    at = [float(edge[0]), float(edge[1]), float(edge[2])]
                else:
                    at = [float(edge[-3]), float(edge[-2]), float(edge[-1])]
        if at is None:
            c = scan.closest_inside(n["at"])
            at = c.point if c is not None else list(n["at"])
        g = {"id": n["id"], "at": at}
        if n.get("corner") is not None:
            g["corner"] = n["corner"]
        placed[n["id"]] = g
    edges = {}

    def edge_of(c):
        if not c.get("along"):
            return None
        if c["id"] not in edges:
            found = bodies.edge(c["along"]["body"], c["along"]["edge"]) if bodies is not None else None
            edges[c["id"]] = _densified(found, EDGE_STEP_MM) if found is not None else None
        return edges[c["id"]]

    for c in curves:
        edge = edge_of(c)
        if edge is None:
            continue
        for nid in (c["from"], c["to"]):
            n = placed.get(nid)
            own = next((x for x in nodes if x["id"] == nid), None)
            if n is None or (own is not None and own.get("on")):
                continue
            i = _nearest_index(edge, n["at"])
            n["at"] = [float(edge[i * 3]), float(edge[i * 3 + 1]), float(edge[i * 3 + 2])]
    traced = []
    lost = []
    lost_why = {}
    for c in curves:
        a = placed.get(c["from"])
        b = placed.get(c["to"])
        if a is None or b is None:
            lost.append(c["id"])
            continue
        exact = None
        grips = c.get("via") or []
        if c.get("along"):
            edge = edge_of(c)
            if edge is None or len(edge) < 6:
                lost.append(c["id"])
                lost_why[c["id"]] = "the body edge it runs along is not found on the body as built"
                continue
            i = _nearest_index(edge, a["at"])
            j = _nearest_index(edge, b["at"])
            E = np.asarray(edge, dtype=np.float64).reshape(-1, 3)
            if i == j:
                pts = [*a["at"], *b["at"]]
            else:
                seg = E[i:j + 1] if i <= j else E[j:i + 1][::-1]
                pts = seg.reshape(-1).tolist()
                pts[0:3] = a["at"]
                pts[-3:] = b["at"]
            exact = curve_points(pts)
            count = max(0, math.floor(exact["length"] / EDGE_GRIP_MM) - 1)
            grips = [_along_polyline(exact, (k + 1) / (count + 1)) for k in range(count)]
        pts = [a["at"], *grips, b["at"]]
        got = cache.trace(scan, pts) if cache is not None else _trace_ends(scan, pts)
        if got is None:
            lost.append(c["id"])
            continue
        g = {"id": c["id"], "from": c["from"], "to": c["to"], "trace": got["trace"], "fit": fit_provisional(exact, scan.edge) if exact is not None else got["fit"]}
        if exact is not None:
            g["exact"] = exact
        traced.append(g)
    out = {"nodes": list(placed.values()), "curves": traced, "lost": lost}
    if lost_why:
        out["lostWhy"] = lost_why
    return out
