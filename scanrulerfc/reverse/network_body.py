# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/core/networkBody.ts
# SPDX-License-Identifier: AGPL-3.0-only
#
# A patch network made a body.
#
# The kernel takes no control net: its surface_through is a surface through
# a grid of points, within a micron of them. So each patch is sampled on a
# grid a few times finer than its net and that grid goes to the kernel, with
# Fit Surface's retries at denser grids and its check on the area. A shared
# curve's samples are the curve's own, taken once and handed to both patches
# either side of it (the same points on both grids), so the two faces'
# edges lie within the kernel's micron of each other along it, and sew. The
# faces are sewn without being unified: each patch stays one face, traced
# back to its cell. A network that closes sews into a solid; an open one
# into a sheet. The edges left open must be the network's own outer
# boundary; one that lies along a shared curve is named, with the gap the
# faces left there.
#
# Everything up to the kernel is here and pure: the grids, the shared
# samples, the report, the ghost (the patches meshed without the kernel).
# network_body itself takes the kernel adapter (kernel.py, the original's
# op names in snake case): surface_through, surface_area, release,
# distance_to_point, copy, sew_patches, is_closed_solid, edges,
# face_points and extent.

import time

import numpy as np

from ._js import js_round, num_str, to_fixed
from .buildtypes import diagonal_of, mesh_deflection
from .network_spline import curve_point, curve_points_v, hypot3_v, patch_points_v
from .surface_fit import GRID_AREA_SLACK, GRID_RETRIES, grid_area

GRID_PER_SPAN = 3
GHOST_SIDE = 48
SEW_TOLERANCE = 1e-3
GAP_SAMPLES = 8
PATCH_GRID = 9


def _ms():
    return time.perf_counter() * 1000


def _where(p):
    return "(" + ", ".join(to_fixed(float(x), 1) for x in p) + ")"


def _split_of(reading):
    split = reading.get("split") or {}
    return {"spokes": [{"cell": s["cell"], "points": s["points"]} for s in split.get("spokes", [])], "centres": split.get("centres", [])}


def _sampled(p):
    """A patch sampled PATCH_GRID x PATCH_GRID, row-major along u."""
    g = np.arange(PATCH_GRID) / (PATCH_GRID - 1)
    U, V = np.meshgrid(g, g, indexing="ij")
    q, _, _ = patch_points_v(p["net"], U.ravel(), V.ravel())
    return q.reshape(-1).astype(np.float32)


def _patch_report(p):
    out = {"seed": p["seed"], "rms": p["rms"], "max": p["max"], "misfit": p["misfit"], "net": {"u": p["net"].nu, "v": p["net"].nv}, "points": p["points"], "worst": p["worst"],
           "sides": [[h["curve"] for h in s["edges"]] for s in p["sides"]], "corners": p["corners"], "grid": _sampled(p)}
    if p.get("dropped") is not None:
        out["dropped"] = p["dropped"]
    return out


def empty_report(reading):
    """The report of a reading with no body: its cells and, where the
    patches were fitted, the fit's own readings (the gaps the patches')."""
    fit = reading.get("fit")
    base = {"cells": reading["outcomes"], "unfilled": reading["cells"]["unfilled"], "lost": reading["traced"]["lost"], **_split_of(reading), "closed": False,
            "ms": dict(reading["ms"], faces=0)}
    if not fit:
        return dict(base, patches=[], curves=[], corners=[], strips=[], bodies=[], worstAngle=0, worstGap=0)
    curves = [{"curve": s["curve"], "gap": s["gap"], "angle": s["angle"], "crease": s["crease"]} for s in fit["shared"]]
    return dict(base, patches=[_patch_report(p) for p in fit["patches"]], curves=curves, corners=fit["corners"], strips=fit["strips"], bodies=fit["bodies"],
                worstAngle=max([0] + [s["angle"] for s in curves if not s["crease"]]), worstGap=max([0] + [s["gap"] for s in curves]))


def patch_grid(patch, per_span, side_samples, fewest=0):
    """A patch's grid for the kernel: per_span samples a span (more, to make
    `fewest` a side at least), row-major with u along the rows, its boundary
    rows the shared samples of its sides: {points, rows, cols}."""
    nu, nv = patch["net"].nu, patch["net"].nv
    rows = nu * max(per_span, -(-fewest // nu)) + 1
    cols = nv * max(per_span, -(-fewest // nv)) + 1
    G = np.zeros((rows, cols, 3))
    if rows > 2 and cols > 2:
        U, V = np.meshgrid(np.arange(1, rows - 1) / (rows - 1), np.arange(1, cols - 1) / (cols - 1), indexing="ij")
        q, _, _ = patch_points_v(patch["net"], U.ravel(), V.ravel())
        G[1:rows - 1, 1:cols - 1] = q.reshape(rows - 2, cols - 2, 3)
    s0 = side_samples(0, rows).reshape(-1, 3)
    s1 = side_samples(1, cols).reshape(-1, 3)
    s2 = side_samples(2, rows).reshape(-1, 3)
    s3 = side_samples(3, cols).reshape(-1, 3)
    G[:, 0] = s0
    G[:, cols - 1] = s2[::-1]
    G[rows - 1, :] = s1
    G[0, :] = s3[::-1]
    return {"points": G.reshape(-1), "rows": rows, "cols": cols}


def side_sampler(fit):
    """Each patch's side samples at a count: a curve sampled once at each
    count, forwards, and a side backwards on it given the samples in the
    other order: the same points on both grids either side of it."""
    samples = {}

    def curve_samples(curve, count):
        key = (curve, count)
        s = samples.get(key)
        if s is None:
            f = fit["curves"][curve]
            s = curve_points_v(f["poles"], f["spans"], np.arange(count) / (count - 1)).reshape(-1)
            samples[key] = s
        return s

    def side_samples_of(patch):
        def side_samples(k, count):
            side = patch["sides"][k]
            if side["single"]:
                s = curve_samples(side["edges"][0]["curve"], count)
                if side["edges"][0]["forward"]:
                    return s
                return s.reshape(-1, 3)[::-1].reshape(-1).copy()
            spans = patch["net"].nu if k % 2 == 0 else patch["net"].nv
            return curve_points_v(side["poles"], spans, np.arange(count) / (count - 1)).reshape(-1)

        return side_samples

    return side_samples_of


def network_body(k, reading):
    """The network's faces sewn into a body, and its report, or why not
    (raises ValueError): {shape, report, faceOf}. `k` is the kernel adapter."""
    fit = reading["fit"]
    began = _ms()
    side_samples_of = side_sampler(fit)
    faces = []
    try:
        for patch in fit["patches"]:
            made = None
            off = 0.0
            for per_span in (GRID_PER_SPAN, *GRID_RETRIES):
                grid = patch_grid(patch, per_span, side_samples_of(patch))
                face = k.surface_through(grid["points"], grid["rows"], grid["cols"])
                off = k.surface_area(face) / grid_area(grid)
                if not off > GRID_AREA_SLACK:
                    made = face
                    break
                k.release(face)
            if made is None:
                much = f"{num_str(js_round(off))} times" if off > 100 else f"{num_str(js_round((off - 1) * 100))} % more than"
                raise ValueError(f"The kernel's surface through the patch at {_where(patch['seed'])} does not follow it: {much} its area at every grid it was given. Give its strips fewer spans.")
            faces.append(made)
        shared = []
        for s in fit["shared"]:
            f = fit["curves"][s["curve"]]
            gap = 0.0
            for i in range(GAP_SAMPLES):
                q = curve_point(f["poles"], f["spans"], (i + 0.5) / GAP_SAMPLES)
                gap = max(gap, k.distance_to_point(faces[s["patches"][0]], q) + k.distance_to_point(faces[s["patches"][1]], q))
            shared.append({"curve": s["curve"], "gap": max(gap, s["gap"]), "angle": s["angle"], "crease": s["crease"]})
        worst_gap = max([0.0] + [s["gap"] for s in shared])
        sides = sum(len(p["sides"]) for p in fit["patches"])
        closed = len(fit["shared"]) * 2 == sides
        tolerance = max(SEW_TOLERANCE, 2 * worst_gap)
        shape = k.copy(faces[0]) if len(faces) == 1 else k.sew_patches(faces, tolerance, closed)
        if closed and not k.is_closed_solid(shape):
            k.release(shape)
            shape = k.sew_patches(faces, tolerance, False)
        solid = closed and k.is_closed_solid(shape)
        opened = [e for e in k.edges(shape, mesh_deflection(diagonal_of(k, shape))) if len(e["faceHashes"]) < 2]
        not_sewn = []
        t = np.arange(17) / 16
        for e in opened:
            for s in fit["shared"]:
                f = fit["curves"][s["curve"]]
                Q = curve_points_v(f["poles"], f["spans"], t)
                near = float(hypot3_v(Q[:, 0] - e["mid"][0], Q[:, 1] - e["mid"][1], Q[:, 2] - e["mid"][2]).min())
                if near < 10 * tolerance + 1e-6 and s["curve"] not in not_sewn:
                    not_sewn.append(s["curve"])
        if not_sewn:
            k.release(shape)
            gap_of = {s["curve"]: s["gap"] for s in shared}
            named = ", ".join(f"curve {c} (gap {to_fixed(gap_of[c] * 1000, 1)} µm)" for c in not_sewn)
            raise ValueError(f"The patches did not sew along {named} — their faces stand apart there; give the strip across it more spans, or draw the curve again.")
        middles = []
        for f in faces:
            pts = k.face_points(f)
            middles.append(pts[0]["at"] if pts else [0.0, 0.0, 0.0])
        M = np.asarray(middles, dtype=float).reshape(-1, 3)
        face_of = {}
        for f in k.face_points(shape):
            d = hypot3_v(M[:, 0] - f["at"][0], M[:, 1] - f["at"][1], M[:, 2] - f["at"][2])
            face_of[f["hash"]] = int(np.argmin(d))
        report = {"patches": [_patch_report(p) for p in fit["patches"]], "cells": reading["outcomes"], "unfilled": reading["cells"]["unfilled"], "curves": shared,
                  "corners": fit["corners"], "strips": fit["strips"], "lost": reading["traced"]["lost"], **_split_of(reading), "bodies": fit["bodies"], "closed": solid,
                  "worstAngle": max([0] + [s["angle"] for s in shared if not s["crease"]]), "worstGap": worst_gap, "ms": dict(reading["ms"], faces=_ms() - began)}
        return {"shape": shape, "report": report, "faceOf": face_of}
    finally:
        k.release(*faces)


def network_ghost(reading):
    """A network's ghost while it is being drawn: each patch meshed from its
    own grid, without the kernel, and the report of the fit:
    {mesh: {positions, normals, indices}, report, volume}."""
    fit = reading["fit"]
    began = _ms()
    side_samples_of = side_sampler(fit)
    positions = []
    normals = []
    indices = []
    base = 0
    for patch in fit["patches"]:
        grid = patch_grid(patch, GRID_PER_SPAN, side_samples_of(patch), GHOST_SIDE)
        rows, cols = grid["rows"], grid["cols"]
        positions.append(grid["points"].reshape(-1, 3))
        U, V = np.meshgrid(np.arange(rows) / (rows - 1), np.arange(cols) / (cols - 1), indexing="ij")
        _, du, dv = patch_points_v(patch["net"], U.ravel(), V.ravel())
        n = np.cross(du, dv)
        l = hypot3_v(n[:, 0], n[:, 1], n[:, 2])
        l = np.where(l > 0, l, 1.0)
        normals.append(n / l[:, None])
        i = np.arange(rows - 1)[:, None]
        j = np.arange(cols - 1)[None, :]
        a = (base + i * cols + j).ravel()
        b = a + cols
        indices.append(np.stack([a, b, b + 1, a, b + 1, a + 1], axis=1).reshape(-1))
        base += rows * cols
    P = np.concatenate(positions) if positions else np.zeros((0, 3))
    idx = np.concatenate(indices) if indices else np.zeros(0, dtype=np.int64)
    sides = sum(len(p["sides"]) for p in fit["patches"])
    closed = len(fit["shared"]) * 2 == sides
    volume = 0.0
    if closed and idx.size:
        T = P[idx.reshape(-1, 3)]
        a, b, c = T[:, 0], T[:, 1], T[:, 2]
        volume = float(np.cumsum((a * np.cross(b, c)).sum(axis=1) / 6)[-1])
    report = empty_report(reading)
    report["closed"] = closed
    report["ms"] = dict(report["ms"], faces=_ms() - began)
    mesh = {"positions": P.reshape(-1).astype(np.float32), "normals": (np.concatenate(normals) if normals else np.zeros((0, 3))).reshape(-1).astype(np.float32), "indices": idx}
    return {"mesh": mesh, "report": report, "volume": abs(volume)}
