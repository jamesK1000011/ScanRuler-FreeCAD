# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/core/datums.ts
# SPDX-License-Identifier: AGPL-3.0-only
#
# The part's coordinate planes as a sketch sees them: each one that crosses
# the sketch plane leaves a line on it, its trace, which a dimension or a
# relation can be held to. A trace is {"plane", "n": [a, b], "d"}: the
# points p with n.p + d = 0 lie on it.

import math

DATUM_PLANES = (
    {"plane": "xy", "name": "XY plane", "normal": [0, 0, 1]},
    {"plane": "yz", "name": "YZ plane", "normal": [1, 0, 0]},
    {"plane": "zx", "name": "XZ plane", "normal": [0, 1, 0]},
)


def datum_name(plane):
    for p in DATUM_PLANES:
        if p["plane"] == plane:
            return p["name"]
    return plane


def _dot3(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def datum_traces(frame):
    out = []
    if not frame or not frame.get("origin") or not frame.get("basisU") or not frame.get("basisV"):
        return out
    for dp in DATUM_PLANES:
        normal = dp["normal"]
        a = _dot3(frame["basisU"], normal)
        b = _dot3(frame["basisV"], normal)
        ln = math.hypot(a, b)
        if ln < 1e-6:
            continue
        out.append({"plane": dp["plane"], "n": [a / ln, b / ln], "d": _dot3(frame["origin"], normal) / ln})
    return out


def trace_of(traces, plane):
    for t in traces or ():
        if t["plane"] == plane:
            return t
    return None


def trace_offset(t, p):
    return t["n"][0] * p[0] + t["n"][1] * p[1] + t["d"]


def trace_foot(t, p):
    off = trace_offset(t, p)
    return [p[0] - off * t["n"][0], p[1] - off * t["n"][1]]


def trace_near(traces, spot, radius):
    best = None
    best_d = radius
    for t in traces:
        d = abs(trace_offset(t, spot))
        if d <= best_d:
            best_d = d
            best = t
    return best


def trace_line(t):
    return {"a": [-t["d"] * t["n"][0], -t["d"] * t["n"][1]], "d": [-t["n"][1], t["n"][0]]}


def trace_segment(t, near, half):
    foot = trace_foot(t, near)
    d = [-t["n"][1], t["n"][0]]
    return [[foot[0] - d[0] * half, foot[1] - d[1] * half], [foot[0] + d[0] * half, foot[1] + d[1] * half]]
