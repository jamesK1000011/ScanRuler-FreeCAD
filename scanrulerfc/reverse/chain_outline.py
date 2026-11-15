# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/core/chainOutline.ts (the joining of chain ends)
# SPDX-License-Identifier: AGPL-3.0-only
#
# A slice's chains made ready for a sketch. A scan full of small holes cuts
# into chains that stop wherever the surface has a gap: so the ends that
# stand closer than a gap the caller allows are joined across it, nearest
# first, two chains into one, a chain's own two ends into a loop. Only the
# joining is here; the runs kept in a box or on a side come with the
# section tools.

import math

from ..geom2d import view_chain


def chain_closed(c):
    return len(c) > 2 and math.hypot(c[0][0] - c[-1][0], c[0][1] - c[-1][1]) < 1e-9


def chain_length(c):
    return sum(math.hypot(c[i][0] - c[i - 1][0], c[i][1] - c[i - 1][1]) for i in range(1, len(c)))


def chain_area(c):
    if not chain_closed(c):
        return 0
    a2 = 0
    for i in range(1, len(c)):
        a2 += c[i - 1][0] * c[i][1] - c[i][0] * c[i - 1][1]
    return abs(a2) / 2


def unjoined(chains):
    return [{"chain": chain, "from": [i], "gaps": 0, "largest": 0} for i, chain in enumerate(chains)]


def join_chain_ends(chains, gap):
    """The chains with the ends closer than `gap` joined across it, nearest
    first: [{chain, from (the chains it is made of), gaps, largest}], by
    the first chain each is made of."""
    n = len(chains)
    is_open = [len(c) >= 2 and not chain_closed(c) for c in chains]

    def end(e):
        c = chains[e >> 1]
        return c[-1] if e & 1 else c[0]

    def dist(e, f):
        return math.hypot(end(e)[0] - end(f)[0], end(e)[1] - end(f)[1])

    pairs = []
    for i in range(n):
        if not is_open[i]:
            continue
        if len(chains[i]) >= 3:
            d = dist(2 * i, 2 * i + 1)
            if d <= gap:
                pairs.append((2 * i, 2 * i + 1, d))
        for j in range(i + 1, n):
            if not is_open[j]:
                continue
            for e in (2 * i, 2 * i + 1):
                for f in (2 * j, 2 * j + 1):
                    d = dist(e, f)
                    if d <= gap:
                        pairs.append((e, f, d))
    if not pairs:
        return unjoined(chains)
    pairs.sort(key=lambda p: p[2])
    mate = [-1] * (2 * n)
    width = [0.0] * (2 * n)
    for e, f, d in pairs:
        if mate[e] >= 0 or mate[f] >= 0:
            continue
        mate[e] = f
        mate[f] = e
        width[e] = width[f] = d
    spacings = sorted(view_chain(c)[2] for c in chains if len(c) >= 2)
    step = max(1e-3, spacings[len(spacings) >> 1] if spacings else math.inf)

    def bridge(out, a, b):
        k = int(math.floor(math.hypot(b[0] - a[0], b[1] - a[1]) / step))
        for t in range(1, k):
            out.append([a[0] + ((b[0] - a[0]) * t) / k, a[1] + ((b[1] - a[1]) * t) / k])

    done = [False] * n
    out = []
    for i in range(n):
        if done[i]:
            continue
        if not is_open[i] or (mate[2 * i] < 0 and mate[2 * i + 1] < 0):
            done[i] = True
            out.append({"chain": chains[i], "from": [i], "gaps": 0, "largest": 0})
            continue
        entry = 2 * i
        for _ in range(n + 1):
            m = mate[entry]
            if m < 0 or (m ^ 1) == 2 * i:
                break
            entry = m ^ 1
        start = entry
        pts = []
        frm = []
        gaps = 0
        largest = 0
        while True:
            c = chains[entry >> 1]
            done[entry >> 1] = True
            frm.append(entry >> 1)
            walk = list(c)[::-1] if entry & 1 else list(c)
            if pts:
                bridge(pts, pts[-1], walk[0])
            pts += walk
            exit_ = entry ^ 1
            m = mate[exit_]
            if m < 0:
                break
            gaps += 1
            largest = max(largest, width[exit_])
            if m == start:
                bridge(pts, pts[-1], pts[0])
                pts.append([pts[0][0], pts[0][1]])
                break
            entry = m
        out.append({"chain": pts, "from": sorted(frm), "gaps": gaps, "largest": largest})
    out.sort(key=lambda c: c["from"][0])
    return out


def bridged_of(chains):
    return {"gaps": sum(c["gaps"] for c in chains), "largest": max([0] + [c["largest"] for c in chains])}
