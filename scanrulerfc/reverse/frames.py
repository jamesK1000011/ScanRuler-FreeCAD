# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): src/core/section/frame.ts (the sketch frames plugins/reverse/core/resolve.ts reads), orthoBasis from src/core/fit/linalg.ts
# SPDX-License-Identifier: AGPL-3.0-only
#
# The frames a sketch is laid out on, in plain floats as the original works
# them (section_core.py has numpy ones for the section tools): a build
# step's planes are hashed by the prefix cache, so they are worked here the
# way the original works them, operation for operation.

import math

from ._js import js_hypot

from .vec import add_scaled, cross, dot, normalize

WORLD_AXES = ("x", "y", "z")


def world_axis_dir(axis):
    return [1, 0, 0] if axis == "x" else [0, 1, 0] if axis == "y" else [0, 0, 1]


def world_plane_name(axis):
    return "YZ plane" if axis == "x" else "XZ plane" if axis == "y" else "XY plane"


def _normalize_or_z(v):
    ln = js_hypot(v[0], v[1], v[2])
    if not (ln > 1e-20):
        return [0, 0, 1]
    return [v[0] / ln, v[1] / ln, v[2] / ln]


def ortho_basis(n):
    ax, ay, az = abs(n[0]), abs(n[1]), abs(n[2])
    helper = [1, 0, 0] if ax <= ay and ax <= az else [0, 1, 0] if ay <= az else [0, 0, 1]
    u = _normalize_or_z(cross(n, helper))
    v = _normalize_or_z(cross(n, u))
    return u, v


def in_plane_x(normal, want):
    if want:
        flat = normalize(add_scaled(want, normal, -dot(want, normal)))
        if flat:
            return flat
    return ortho_basis(normal)[0]


def sketch_x_axis(normal):
    a = [abs(normal[0]), abs(normal[1]), abs(normal[2])]
    nearest = 0 if a[0] >= a[1] and a[0] >= a[2] else 1 if a[1] >= a[2] else 2
    nxt = (nearest + 1) % 3
    return [1, 0, 0] if nxt == 0 else [0, 1, 0] if nxt == 1 else [0, 0, 1]


def sketch_frame_on(plane, seed_u=None):
    """The frame a CAD sketch takes on a plane {origin, normal}: zero at the
    world origin's foot on it, X the coordinate axis next round from the one
    the normal is nearest (or `seed_u` laid in the plane)."""
    normal = normalize(plane["normal"])
    if not normal:
        return None
    origin = add_scaled([0, 0, 0], normal, dot(plane["origin"], normal))
    basis_u = in_plane_x(normal, seed_u or sketch_x_axis(normal))
    return {"origin": origin, "normal": normal, "basisU": basis_u, "basisV": cross(normal, basis_u)}


def radial_frame(axis, angle_deg):
    """A plane through an axis {origin, dir} turned angle_deg about it."""
    up = normalize(axis["dir"])
    if not up or not math.isfinite(angle_deg):
        return None
    k = 0
    for i in (1, 2):
        if abs(up[i]) > abs(up[k]):
            k = i
    if up[k] < 0:
        up = [-up[0], -up[1], -up[2]]
    zero = in_plane_x(up, sketch_x_axis(up))
    quarter = cross(up, zero)
    a = (angle_deg * math.pi) / 180
    basis_u = normalize(add_scaled([zero[0] * math.cos(a), zero[1] * math.cos(a), zero[2] * math.cos(a)], quarter, math.sin(a)))
    return {"origin": axis["origin"], "normal": cross(basis_u, up), "basisU": basis_u, "basisV": up}
