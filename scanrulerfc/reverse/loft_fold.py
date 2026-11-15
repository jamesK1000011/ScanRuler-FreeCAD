# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/core/loftFold.ts
# SPDX-License-Identifier: AGPL-3.0-only
#
# Where a smooth loft's skin crosses itself. The kernel answers such a loft
# valid, and the boolean after it comes out empty or wrong, so the Builder
# looks first: FOLD_CUTS cuts across the loft's curved faces, each at one v,
# laid flat across the sections' common normal (or each cut's own plane),
# and looked over for two of its pieces crossing. The cuts are read off the
# kernel's faces (loft_fold takes the Occt adapter); the rest is pure.

import math
import time

from .loops import piece_points
from .topo import face_kind_of
from .vec import add, cross, dot, length, normalize, scale, sub

FOLD_CUTS = 40
FOLD_STEPS = 8
PARALLEL_DEG = 1


def loop_normal(points):
    """Newell's sum: the loop's plane normal, None for a loop with no area."""
    n = [0.0, 0.0, 0.0]
    for i, a in enumerate(points):
        b = points[(i + 1) % len(points)]
        n[0] += (a[1] - b[1]) * (a[2] + b[2])
        n[1] += (a[2] - b[2]) * (a[0] + b[0])
        n[2] += (a[0] - b[0]) * (a[1] + b[1])
    return normalize(n)


def section_of(profile):
    points = [p for piece in profile["outer"] for p in piece_points(piece)]
    total = [0.0, 0.0, 0.0]
    for p in points:
        total = add(total, p)
    return {"middle": scale(total, 1 / max(1, len(points))), "normal": loop_normal(points)}


def _parallel(a, b):
    return abs(dot(a, b)) >= math.cos(math.radians(PARALLEL_DEG))


def sections_normal(profiles):
    """The sections' common normal, or None when their planes are not
    parallel (radial stations)."""
    normals = [section_of(p)["normal"] for p in profiles]
    first = normals[0] if normals else None
    if not first or any(not n or not _parallel(n, first) for n in normals):
        return None
    return first


def crossing(lines, normal):
    """The first point where two segments of a cut laid flat cross, not at a
    face's end, or None."""
    e1 = normalize(cross(normal, [1, 0, 0] if abs(normal[0]) < 0.9 else [0, 1, 0]))
    e2 = cross(normal, e1)
    flat = [[(dot(p, e1), dot(p, e2)) for p in line] for line in lines]
    every = [p for line in flat for p in line]
    size = max(1e-9, *[max(p[k] for p in every) - min(p[k] for p in every) for k in (0, 1)]) if every else 1e-9
    eps = 1e-12 * size * size
    end_tol = 1e-4 * size
    ends = [q for line in flat if line for q in (line[0], line[-1])]

    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    segments = [(i, j) for i, line in enumerate(flat) for j in range(len(line) - 1)]
    for s, (la, ja) in enumerate(segments):
        p1, p2 = flat[la][ja], flat[la][ja + 1]
        for lb, jb in segments[s + 1:]:
            if la == lb and abs(ja - jb) < 2:
                continue
            q1, q2 = flat[lb][jb], flat[lb][jb + 1]
            d1, d2, d3, d4 = orient(q1, q2, p1), orient(q1, q2, p2), orient(p1, p2, q1), orient(p1, p2, q2)
            if not ((d1 > eps and d2 < -eps) or (d1 < -eps and d2 > eps)):
                continue
            if not ((d3 > eps and d4 < -eps) or (d3 < -eps and d4 > eps)):
                continue
            f = d1 / (d1 - d2)
            x = (p1[0] + f * (p2[0] - p1[0]), p1[1] + f * (p2[1] - p1[1]))
            if any(math.hypot(e[0] - x[0], e[1] - x[1]) <= end_tol for e in ends):
                continue
            a, b = lines[la][ja], lines[la][ja + 1]
            return add(a, scale(sub(b, a), f))
    return None


def fold_of_cuts(cuts, normal=None):
    """loftFold's reading of the cuts (each a list of polylines): the fold,
    or None."""
    def own_normal(lines):
        points = [p for line in lines for p in line]
        if len(points) < 3:
            return None
        middle = scale([sum(p[k] for p in points) for k in range(3)], 1 / len(points))
        area = [0.0, 0.0, 0.0]
        for line in lines:
            for j in range(len(line) - 1):
                area = add(area, cross(sub(line[j], middle), sub(line[j + 1], middle)))
        return normalize(area)

    own = [own_normal(c) for c in cuts]
    if not normal:
        known = [n for n in own if n is not None]
        if known and all(_parallel(n, known[0]) for n in known):
            total = [0.0, 0.0, 0.0]
            for n in known:
                total = add(total, scale(n, -1) if dot(n, known[0]) < 0 else n)
            normal = normalize(total)
    folded = []
    at = None
    for i, lines in enumerate(cuts):
        n = normal or own[i]
        if not n or not lines:
            continue
        x = crossing(lines, n)
        if not x:
            continue
        at = at or x
        folded.append({"cut": i, "height": dot(x, normal) if normal else None})
    if not at:
        return None
    return {"at": at, "normal": normal, "folded": folded, "of": len(cuts)}


def loft_fold(o, shape, normal=None, faces=None, trimmed=False):
    """Where a smooth loft's curved faces (of `faces`, hashes, when given)
    cross themselves, read off the Occt adapter `o`, or None."""
    from .kernel import HASH_BOUND

    began = time.perf_counter()
    picked = []
    for f in o.getSubShapes(shape, "face"):
        if faces is not None and o.hashCode(f, HASH_BOUND) not in faces:
            continue
        if face_kind_of(o.surfaceType(f)) == "plane":
            continue
        picked.append((f, o.uvBounds(f)))
    if not picked:
        return None
    v_lo = min(uv["vMin"] for _, uv in picked)
    v_hi = max(uv["vMax"] for _, uv in picked)
    if not v_hi > v_lo:
        return None
    cuts = []
    for i in range(FOLD_CUTS):
        v = v_lo + (i + 0.5) / FOLD_CUTS * (v_hi - v_lo)
        lines = []
        for f, uv in picked:
            if v < uv["vMin"] or v > uv["vMax"]:
                continue
            line = []
            for j in range(FOLD_STEPS + 1):
                u = uv["uMin"] + j / FOLD_STEPS * (uv["uMax"] - uv["uMin"])
                if trimmed and o.classifyPointOnFace(f, u, v) == "out":
                    if len(line) > 1:
                        lines.append(line)
                    line = []
                    continue
                line.append(list(o.pointOnSurface(f, u, v)))
            if len(line) > 1:
                lines.append(line)
        cuts.append(lines)
    fold = fold_of_cuts(cuts, normal)
    if fold:
        fold["ms"] = (time.perf_counter() - began) * 1000
    return fold


def _one(x):
    from ._js import fixed_number, num_str

    return num_str(fixed_number(x, 1))


def where_words(at, normal):
    axis = next((k for k in range(3) if abs(normal[k]) > 1 - 1e-6), None) if normal else None
    if axis is None:
        return f"near ({', '.join(_one(v) for v in at)})"
    others = [k for k in range(3) if k != axis]
    return f"{'xyz'[axis]} {_one(at[axis])} near ({', '.join(_one(at[k]) for k in others)})"


def stretch_words(fold):
    runs = []
    for f in fold["folded"]:
        if runs and runs[-1][-1]["cut"] == f["cut"] - 1:
            runs[-1].append(f)
        else:
            runs.append([f])
    normal = fold["normal"]
    axis = next((k for k in range(3) if abs(normal[k]) > 1 - 1e-6), None) if normal else None
    sign = -1 if axis is not None and normal[axis] < 0 else 1
    words = []
    for r in runs:
        a, b = r[0], r[-1]
        if a["height"] is None or b["height"] is None:
            words.append(f"{a['cut'] + 1}" if a is b else f"{a['cut'] + 1}–{b['cut'] + 1}")
            continue
        lo, hi = sorted([a["height"] * sign, b["height"] * sign])
        words.append(_one(lo) if a is b else f"{_one(lo)}–{_one(hi)}")
    listed = f"{', '.join(words[:-1])} and {words[-1]}" if len(words) > 1 else words[0]
    if fold["folded"][0]["height"] is None:
        return f"cut{'' if len(fold['folded']) == 1 else 's'} {listed} of {fold['of']}"
    return f"{'xyz'[axis]} {listed}" if axis is not None else f"{listed} mm along the loft"


def fold_words(fold):
    return f"crosses itself at {where_words(fold['at'], fold['normal'])} (folded over {stretch_words(fold)})"


def loft_fold_refusal(fold, sections):
    """A smooth loft refused for folding, naming its sections ({name,
    profile}): the closest pair when far closer than the rest, and the pair
    the fold lies between."""
    read = [section_of(s["profile"]) for s in sections]
    normal = sections_normal([s["profile"] for s in sections])
    gaps = [abs(dot(sub(s["middle"], read[i]["middle"]), normal)) if normal else length(sub(s["middle"], read[i]["middle"])) for i, s in enumerate(read[1:])]
    between = 0
    if normal:
        h = dot(fold["at"], normal)
        at = next((i for i in range(len(gaps)) if (dot(read[i]["middle"], normal) - h) * (dot(read[i + 1]["middle"], normal) - h) <= 0), -1)
        between = at if at >= 0 else 0
    elif gaps:
        def far(i):
            return length(sub(fold["at"], read[i]["middle"])) + length(sub(fold["at"], read[i + 1]["middle"]))

        between = min(range(len(gaps)), key=lambda i: (far(i), i))
    srt = sorted(gaps)
    median = (srt[(len(srt) - 1) // 2] if len(srt) % 2 == 1 else (srt[len(srt) // 2 - 1] + srt[len(srt) // 2]) / 2) if srt else 0
    close = min(range(len(gaps)), key=lambda i: (gaps[i], i)) if gaps else 0

    def pair(i):
        return f"{sections[i]['name']} and {sections[i + 1]['name']}"

    def head(lies):
        return f"The smooth loft crosses itself at {where_words(fold['at'], fold['normal'])}{lies} (folded over {stretch_words(fold)})"

    if len(gaps) >= 2 and gaps[close] < 0.5 * median:
        return f"{head(f', between {pair(between)}' if between != close else '')}: {pair(close)} are {_one(gaps[close])} mm apart and differ — drop or move one, or make the loft ruled."
    return f"{head('')}: the skin between {pair(between)} overshoots — the sections differ more than one smooth skin through them all can follow; add a section between them, or make the loft ruled."
