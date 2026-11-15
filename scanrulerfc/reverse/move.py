# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/core/move.ts (the rigid move of bodies)
# SPDX-License-Identifier: AGPL-3.0-only
#
# A move of bodies: a pivot, a translation and turns about X, then Y, then
# Z (degrees), as the kernel takes it: a row-major 3 x 4 matrix,
# p' = R (p - pivot) + pivot + translate. The mesh carrying and the rings'
# axes are the panel's and come with it.

import math

RAD = math.pi / 180


def _rot_x(a):
    c, s = math.cos(a), math.sin(a)
    return [1, 0, 0, 0, c, -s, 0, s, c]


def _rot_y(a):
    c, s = math.cos(a), math.sin(a)
    return [c, 0, s, 0, 1, 0, -s, 0, c]


def _rot_z(a):
    c, s = math.cos(a), math.sin(a)
    return [c, -s, 0, s, c, 0, 0, 0, 1]


def _mul3(a, b):
    return [a[r * 3] * b[c] + a[r * 3 + 1] * b[3 + c] + a[r * 3 + 2] * b[6 + c] for r in range(3) for c in range(3)]


def _apply3(m, v):
    return [m[0] * v[0] + m[1] * v[1] + m[2] * v[2], m[3] * v[0] + m[4] * v[1] + m[5] * v[2], m[6] * v[0] + m[7] * v[1] + m[8] * v[2]]


def rotation_of(rotate):
    return _mul3(_rot_z(rotate[2] * RAD), _mul3(_rot_y(rotate[1] * RAD), _rot_x(rotate[0] * RAD)))


def move_matrix(p):
    r = rotation_of(p["rotate"])
    turned = _apply3(r, p["pivot"])
    t = [p["pivot"][k] + p["translate"][k] - turned[k] for k in range(3)]
    return [r[0], r[1], r[2], t[0], r[3], r[4], r[5], t[1], r[6], r[7], r[8], t[2]]


def matrix4_of(m):
    return [m[0], m[4], m[8], 0, m[1], m[5], m[9], 0, m[2], m[6], m[10], 0, m[3], m[7], m[11], 1]


def move_point(m, p):
    return [m[0] * p[0] + m[1] * p[1] + m[2] * p[2] + m[3], m[4] * p[0] + m[5] * p[1] + m[6] * p[2] + m[7], m[8] * p[0] + m[9] * p[1] + m[10] * p[2] + m[11]]


def move_dir(m, d):
    return [m[0] * d[0] + m[1] * d[1] + m[2] * d[2], m[4] * d[0] + m[5] * d[1] + m[6] * d[2], m[8] * d[0] + m[9] * d[1] + m[10] * d[2]]
