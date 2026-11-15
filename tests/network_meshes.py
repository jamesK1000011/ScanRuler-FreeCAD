# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/tests/networkMeshes.ts, tests/helpers.ts (icosphere)
# SPDX-License-Identifier: AGPL-3.0-only
#
# The synthetic scans the patch network's tests draw on: a grid of (u, v)
# mapped into space (a sheet, a strip of a cylinder, a saddle) with noise
# along the normal and holes left out, and a noisy sphere. And a network
# written out as nodes and curves through grips. The same numbers as the
# original's: the generator is its mulberry32, the noise its Box-Muller.
import math

import numpy as np

from scanrulerfc.reverse._js import js_hypot

M32 = 0xFFFFFFFF


def _imul(a, b):
    return (a * b) & M32


def random(seed):
    """The original's small deterministic generator."""
    s = [seed & M32]

    def nxt():
        s[0] = (s[0] + 0x6D2B79F5) & M32
        t = s[0]
        t = _imul(t ^ (t >> 15), t | 1)
        t ^= (t + _imul(t ^ (t >> 7), t | 61)) & M32
        return ((t ^ (t >> 14)) & M32) / 4294967296

    return nxt


def gaussian(rand):
    u = max(rand(), 1e-12)
    return math.sqrt(-2 * math.log(u)) * math.cos(2 * math.pi * rand())


def grid_scan(nu, nv, at, wrap=False, hole=None, noise=0.0, seed=5):
    """A grid of nu x nv cells over [0, 1]^2 mapped by `at`, wound so its
    normals point the way at's du x dv does; `wrap` closes u round; `hole`
    leaves out the cells it says; `noise` moves each vertex along the
    grid's own normal there. (positions float32, indices)."""
    cols = nu if wrap else nu + 1
    rand = random(seed)
    positions = []
    for j in range(nv + 1):
        for i in range(cols):
            u = i / nu
            v = j / nv
            p = list(at(u, v))
            if noise:
                e = 1e-4
                pu = at(u + e, v)
                pv = at(u, v + e)
                du = [pu[0] - p[0], pu[1] - p[1], pu[2] - p[2]]
                dv = [pv[0] - p[0], pv[1] - p[1], pv[2] - p[2]]
                n = [du[1] * dv[2] - du[2] * dv[1], du[2] * dv[0] - du[0] * dv[2], du[0] * dv[1] - du[1] * dv[0]]
                l = js_hypot(n[0], n[1], n[2]) or 1
                g = gaussian(rand) * noise
                p[0] += (n[0] / l) * g
                p[1] += (n[1] / l) * g
                p[2] += (n[2] / l) * g
            positions.extend(p)
    indices = []

    def vid(i, j):
        return j * cols + (i % nu if wrap else i)

    for j in range(nv):
        for i in range(nu):
            if hole is not None and hole((i + 0.5) / nu, (j + 0.5) / nv):
                continue
            indices.extend((vid(i, j), vid(i + 1, j), vid(i + 1, j + 1), vid(i, j), vid(i + 1, j + 1), vid(i, j + 1)))
    return np.array(positions, dtype=np.float32), np.array(indices, dtype=np.int64)


def _normalize(v):
    l = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    return [v[0] / l, v[1] / l, v[2] / l]


def icosphere(subdivisions, radius, noise=0.0, seed=7):
    t = (1 + math.sqrt(5)) / 2
    verts = [_normalize(v) for v in [[-1, t, 0], [1, t, 0], [-1, -t, 0], [1, -t, 0], [0, -1, t], [0, 1, t], [0, -1, -t], [0, 1, -t], [t, 0, -1], [t, 0, 1], [-t, 0, -1], [-t, 0, 1]]]
    faces = [[0, 11, 5], [0, 5, 1], [0, 1, 7], [0, 7, 10], [0, 10, 11], [1, 5, 9], [5, 11, 4], [11, 10, 2], [10, 7, 6], [7, 1, 8],
             [3, 9, 4], [3, 4, 2], [3, 2, 6], [3, 6, 8], [3, 8, 9], [4, 9, 5], [2, 4, 11], [6, 2, 10], [8, 6, 7], [9, 8, 1]]
    for _ in range(subdivisions):
        cache = {}

        def midpoint(a, b):
            key = (a, b) if a < b else (b, a)
            hit = cache.get(key)
            if hit is not None:
                return hit
            verts.append(_normalize([(verts[a][0] + verts[b][0]) / 2, (verts[a][1] + verts[b][1]) / 2, (verts[a][2] + verts[b][2]) / 2]))
            cache[key] = len(verts) - 1
            return len(verts) - 1

        nxt = []
        for a, b, c in faces:
            ab = midpoint(a, b)
            bc = midpoint(b, c)
            ca = midpoint(c, a)
            nxt.extend(([a, ab, ca], [b, bc, ab], [c, ca, bc], [ab, bc, ca]))
        faces = nxt
    rand = random(seed)
    positions = np.zeros(len(verts) * 3, dtype=np.float32)
    for i, v in enumerate(verts):
        r = radius + (gaussian(rand) * noise if noise > 0 else 0)
        positions[i * 3] = v[0] * r
        positions[i * 3 + 1] = v[1] * r
        positions[i * 3 + 2] = v[2] * r
    return positions, np.array(faces, dtype=np.int64).reshape(-1)


def sphere_scan(r, noise, subdivisions=5):
    """A sphere of radius r about the origin with noise, closed."""
    return icosphere(subdivisions, r, noise, 3)


def network(id_, nodes, curves, seeds, spans=None):
    """A network written out: nodes by id at their points, curves as
    {from, to, via, crease}, seeds for the cells."""
    ns = [{"id": int(k), "at": list(at)} for k, at in nodes.items()]
    cs = []
    for i, c in enumerate(curves):
        d = {"id": i + 1, "from": c["from"], "to": c["to"], "via": [list(v) for v in c.get("via", [])]}
        if c.get("crease"):
            d["crease"] = True
        cs.append(d)
    return {"id": id_, "kind": "network", "name": f"Network {id_}", "nodes": ns, "curves": cs, "cells": [{"seed": list(s)} for s in seeds], "spans": dict(spans or {}), "fit": {"smoothness": 0.001}, "visible": True}


def grid_network(id_, rows, cols, at, grips=0, box=(0, 1, 0, 1)):
    """A rows x cols grid network over a surface given by `at` on [0, 1]^2:
    nodes on the grid's crossings, a curve along each line between two with
    `grips` grips evenly along it, and a seed in every cell."""
    u0, u1, v0, v1 = box

    def uu(i):
        return u0 + ((u1 - u0) * i) / cols

    def vv(j):
        return v0 + ((v1 - v0) * j) / rows

    def nid(i, j):
        return j * (cols + 1) + i + 1

    nodes = {}
    for j in range(rows + 1):
        for i in range(cols + 1):
            nodes[nid(i, j)] = at(uu(i), vv(j))

    def via(a, b):
        return [at(a[0] + ((b[0] - a[0]) * (k + 1)) / (grips + 1), a[1] + ((b[1] - a[1]) * (k + 1)) / (grips + 1)) for k in range(grips)]

    curves = []
    for j in range(rows + 1):
        for i in range(cols):
            curves.append({"from": nid(i, j), "to": nid(i + 1, j), "via": via([uu(i), vv(j)], [uu(i + 1), vv(j)])})
    for j in range(rows):
        for i in range(cols + 1):
            curves.append({"from": nid(i, j), "to": nid(i, j + 1), "via": via([uu(i), vv(j)], [uu(i), vv(j + 1)])})
    seeds = []
    for j in range(rows):
        for i in range(cols):
            seeds.append(at((uu(i) + uu(i + 1)) / 2, (vv(j) + vv(j + 1)) / 2))
    return network(id_, nodes, curves, seeds)
