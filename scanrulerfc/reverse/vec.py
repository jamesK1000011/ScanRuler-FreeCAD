# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): src/core/vec.ts, the vector arithmetic plugins/reverse/core/*.ts uses
# SPDX-License-Identifier: AGPL-3.0-only
#
# Vector arithmetic on plain [x, y, z] lists, as the original's core has it.
# normalize gives None for a vector shorter than 1e-12.

import math


def sub(a, b):
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def add(a, b):
    return [a[0] + b[0], a[1] + b[1], a[2] + b[2]]


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def length(a):
    return math.hypot(a[0], a[1], a[2])


def scale(a, s):
    return [a[0] * s, a[1] * s, a[2] * s]


def add_scaled(a, b, s):
    return [a[0] + b[0] * s, a[1] + b[1] * s, a[2] + b[2] * s]


def mid(a, b):
    return [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2]


def normalize(a):
    n = length(a)
    if n < 1e-12:
        return None
    return [a[0] / n, a[1] / n, a[2] / n]


def angle_between(a, b):
    return math.degrees(math.acos(max(-1.0, min(1.0, dot(a, b)))))


def acute_angle(a, b):
    return math.degrees(math.acos(min(1.0, abs(dot(a, b)))))


def foot_on_line(point, origin, d):
    return add_scaled(origin, d, dot(sub(point, origin), d))


def param_on_line(point, origin, d):
    return dot(sub(point, origin), d)
