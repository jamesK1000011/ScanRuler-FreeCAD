# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/core/solver.ts
# SPDX-License-Identifier: AGPL-3.0-only
#
# The sketch solver: every piece's numbers in one vector, and every wish as
# a block of residuals - the slice points a piece was fitted to (soft, by
# their scatter), a weak pull back to where each piece stood (so free
# geometry stays put), a drag's pull, and each relation and dimension at a
# high weight - solved together by Levenberg-Marquardt on the stacked,
# weighted residuals. What is left unmet is reported by relation; the hard
# rows' rank says how many are redundant and which pieces still move.

import math

import numpy as np

from ..linalg import cholesky_solve, solve_linear, sym_eigen
from ._js import fmod
from .datums import trace_line, trace_of, trace_offset
from .sketch import anchor_point, distance_along, dot2, len2, normalize2, perp2, spline_joint, sub2
from .sketch_spline import is_closed, nearest_on_spline, spline_at, spline_curve, spline_dir_at, spline_end

HARD_WEIGHT = 1e4
FREE_WEIGHT = 1e-1
PULL_WEIGHT = 1e2
RELEASE_ITERATIONS = 6
UNMET_TOLERANCE = 1e-3
CLOSE_FROM = 1e-7
MAX_POINTS = 240
MAX_ITERATIONS = 60
QUICK_ITERATIONS = 4
REFIT_ROUNDS = 24


class _Block:
    __slots__ = ("params", "weight", "constraint_id", "bound", "eval", "refresh")

    def __init__(self, params, weight, ev, constraint_id=None, bound=False, refresh=None):
        self.params = params
        self.weight = weight
        self.eval = ev
        self.constraint_id = constraint_id
        self.bound = bound
        self.refresh = refresh


def _mean_chord(s):
    tot = 0.0
    n = len(s["pts"])
    segments = n if is_closed(s) else n - 1
    for i in range(segments):
        tot += len2(sub2(s["pts"][(i + 1) % n], s["pts"][i]))
    return tot / segments if segments > 0 else 1


def params_of(e):
    k = e["kind"]
    if k == "line":
        return [e["a"][0], e["a"][1], e["b"][0], e["b"][1]]
    if k == "arc":
        return [e["c"][0], e["c"][1], e["r"], e["start"], e["sweep"]]
    if k == "circle":
        return [e["c"][0], e["c"][1], e["r"]]
    if k == "spline":
        out = [v for p in e["pts"] for v in p]
        if e.get("startDir") is not None:
            out.append(e["startDir"])
        if e.get("endDir") is not None:
            out.append(e["endDir"])
        return out
    return [e["p"][0], e["p"][1]]


def with_params(e, x, at):
    k = e["kind"]
    f = lambda i: float(x[i])  # noqa: E731
    if k == "line":
        return {**e, "a": [f(at), f(at + 1)], "b": [f(at + 2), f(at + 3)]}
    if k == "arc":
        return {**e, "c": [f(at), f(at + 1)], "r": f(at + 2), "start": f(at + 3), "sweep": f(at + 4)}
    if k == "circle":
        return {**e, "c": [f(at), f(at + 1)], "r": f(at + 2)}
    if k == "spline":
        n = len(e["pts"])
        out = {**e, "pts": [[f(at + 2 * i), f(at + 2 * i + 1)] for i in range(n)]}
        j = at + 2 * n
        if e.get("startDir") is not None:
            out["startDir"] = f(j)
            j += 1
        if e.get("endDir") is not None:
            out["endDir"] = f(j)
            j += 1
        return out
    return {**e, "p": [f(at), f(at + 1)]}


def _spline_end_dir(s, end):
    angle = s.get("startDir") if end == "a" else s.get("endDir")
    if angle is not None:
        return [math.cos(angle), math.sin(angle)]
    fit = spline_curve(s)
    return spline_dir_at(fit, 0 if end == "a" else spline_end(fit))


def _with_held_ends(s, sketch):
    held = set()
    if not is_closed(s):
        for c in sketch["constraints"]:
            if c["kind"] != "tangent" or (c["a"] != s["id"] and c["b"] != s["id"]):
                continue
            joint = spline_joint(sketch, s["id"], c["b"] if c["a"] == s["id"] else c["a"])
            if joint:
                held.add(joint["end"])

    def has(end):
        return (s.get("startDir") if end == "a" else s.get("endDir")) is not None

    if (("a" in held) == has("a")) and (("b" in held) == has("b")):
        return s
    fit = spline_curve(s)
    out = dict(s)
    out.pop("startDir", None)
    out.pop("endDir", None)

    def direction(t):
        d = spline_dir_at(fit, t)
        return math.atan2(d[1], d[0])

    if "a" in held:
        out["startDir"] = s["startDir"] if s.get("startDir") is not None else direction(0)
    if "b" in held:
        out["endDir"] = s["endDir"] if s.get("endDir") is not None else direction(spline_end(fit))
    return out


def _thin(points):
    if len(points) <= MAX_POINTS:
        return points
    step = len(points) / MAX_POINTS
    return [points[math.floor(i * step)] for i in range(MAX_POINTS)]


def _ok(sketch):
    return {"ok": True, "iterations": 0, "unmet": [], "redundant": 0, "equations": 0, "softRms": 0, "underConstrained": []}


def solve_sketch(sketch, pull=None, quick=False, datums=None):
    """Solve the sketch in place: its pieces moved to meet what is held.
    `pull` is a list of {"anchor", "to"} - a drag - and `datums` the
    coordinate planes' traces. Returns the original's SolveReport."""
    if any(e["kind"] == "spline" for e in sketch["entities"]):
        sketch["entities"] = [_with_held_ends(e, sketch) if e["kind"] == "spline" else e for e in sketch["entities"]]
    slots = {}
    x0 = []
    for e in sketch["entities"]:
        p = params_of(e)
        slots[e["id"]] = (e, len(x0), len(p))
        x0 += p
    n = len(x0)
    x = np.array(x0, dtype=float)
    if n == 0:
        return _ok(sketch)

    free = np.ones(n, dtype=bool)
    for e in sketch["entities"]:
        if e.get("fixed"):
            _e, off, cnt = slots[e["id"]]
            free[off:off + cnt] = False

    blocks = []

    def rng(s):
        return list(range(s[1], s[1] + s[2]))

    def read(i, xs):
        s = slots[i]
        return with_params(s[0], xs, s[1])

    soft_count = 0
    rests = []
    for e in sketch["entities"]:
        s = slots[e["id"]]
        if e.get("fixed"):
            continue
        at = s[1]
        init = np.array(x0[at:at + s[2]], dtype=float)
        rests.append((at, init))
        if e["kind"] == "arc":
            unit = np.array([max(abs(e["r"]), 1e-3) if i >= 3 else 1.0 for i in range(s[2])])
        elif e["kind"] == "spline":
            mc = max(_mean_chord(e), 1e-3)
            unit = np.array([mc if i >= 2 * len(e["pts"]) else 1.0 for i in range(s[2])])
        else:
            unit = np.ones(s[2])

        def rest_eval(xs, at=at, init=init, unit=unit):
            return list((xs[at:at + len(init)] - init) * unit)

        blocks.append(_Block(rng(s), FREE_WEIGHT, rest_eval))
        points = _thin(e["points"]) if e.get("points") else None
        if not points or e["kind"] == "point":
            continue
        scatter = max(e.get("scatter") or 0, 1e-3)
        soft_count += len(points)
        count = len(points)
        px = np.array([p[0] for p in points], dtype=float)
        py = np.array([p[1] for p in points], dtype=float)
        o = s[1]
        if e["kind"] == "line":
            def line_eval(xs, o=o, px=px, py=py):
                ax = xs[o]
                ay = xs[o + 1]
                dx = xs[o + 2] - ax
                dy = xs[o + 3] - ay
                ln = math.hypot(dx, dy)
                if ln > 0:
                    dx /= ln
                    dy /= ln
                else:
                    dx, dy = 1.0, 0.0
                return list((py - ay) * dx - (px - ax) * dy)

            blocks.append(_Block(rng(s), 1 / scatter, line_eval))
        elif e["kind"] == "spline":
            fit0 = spline_curve(e)
            foot = [nearest_on_spline(fit0, p, 8)["t"] for p in points]
            sid = e["id"]

            def refresh(xs, sid=sid, foot=foot, px=px, py=py, count=count):
                fit = spline_curve(read(sid, xs))
                moved = 0.0
                for i in range(count):
                    t = nearest_on_spline(fit, [px[i], py[i]], 8)["t"]
                    moved = max(moved, abs(t - foot[i]))
                    foot[i] = t
                return moved

            def spline_eval(xs, sid=sid, foot=foot, px=px, py=py, count=count):
                fit = spline_curve(read(sid, xs))
                out = [0.0] * (2 * count)
                for i in range(count):
                    c = spline_at(fit, foot[i])
                    out[2 * i] = px[i] - c[0]
                    out[2 * i + 1] = py[i] - c[1]
                return out

            blocks.append(_Block(rng(s), 1 / scatter, spline_eval, refresh=refresh))
        else:
            def round_eval(xs, o=o, px=px, py=py):
                return list(np.hypot(px - xs[o], py - xs[o + 1]) - xs[o + 2])

            blocks.append(_Block(rng(s), 1 / scatter, round_eval))

    def anchor_at(xs, a):
        return anchor_point(read(a["entity"], xs), a["at"])

    pulls = []
    for pl in pull or ():
        s = slots.get(pl["anchor"]["entity"])
        if not s:
            continue

        def pull_eval(xs, pl=pl):
            p = anchor_at(xs, pl["anchor"])
            return [p[0] - pl["to"][0], p[1] - pl["to"][1]]

        pulls.append(_Block(rng(s), PULL_WEIGHT, pull_eval))
    blocks += pulls

    def dir_of(xs, i):
        ln = read(i, xs)
        if ln["kind"] != "line":
            return [1, 0]
        return normalize2(sub2(ln["b"], ln["a"])) or [1, 0]

    def line_of(xs, i):
        ln = read(i, xs)
        return ln if ln["kind"] == "line" else None

    def params_for(ids):
        out = []
        seen = []
        for i in ids:
            if i in seen:
                continue
            seen.append(i)
            s = slots.get(i)
            if s:
                out += rng(s)
        return out

    def hard(c, ids, fn):
        blocks.append(_Block(params_for(ids), HARD_WEIGHT, fn, constraint_id=c["id"]))

    def scale_of():
        sc = 0.0
        for e in sketch["entities"]:
            if e["kind"] == "line":
                sc = max(sc, len2(sub2(e["b"], e["a"])))
            elif e["kind"] == "spline":
                for p in e["pts"]:
                    for q in e["pts"]:
                        sc = max(sc, len2(sub2(p, q)))
            elif e["kind"] != "point":
                sc = max(sc, 2 * e["r"])
        return max(sc, 1)

    L = scale_of()

    def joint_of(a, b):
        for k in sketch["constraints"]:
            if k["kind"] != "coincident":
                continue
            p = k["p"]["at"]
            q = k["q"]["at"]
            if p not in ("a", "b") or q not in ("a", "b"):
                continue
            if k["p"]["entity"] == a and k["q"]["entity"] == b:
                return {"a": p, "b": q}
            if k["p"]["entity"] == b and k["q"]["entity"] == a:
                return {"a": q, "b": p}
        return None

    def radial_at(arc, at):
        t = arc["start"] if at == "a" else arc["start"] + arc["sweep"]
        return [math.cos(t), math.sin(t)]

    for c in sketch["constraints"]:
        _add_constraint_blocks(c, sketch, slots, options_datums=datums, hard=hard, read=read, anchor_at=anchor_at, dir_of=dir_of, line_of=line_of, joint_of=joint_of, radial_at=radial_at, L=L, blocks=blocks, params_for=params_for)

    free_index = np.full(n, -1, dtype=int)
    m = 0
    for i in range(n):
        if free[i]:
            free_index[i] = m
            m += 1
    if m == 0:
        return _finish(sketch, slots, x, blocks, 0, soft_count, False)

    state = {"iterations": 0}

    def cost(rs):
        return float(sum(float(np.dot(r, r)) for r in rs))

    def descend(active, max_iterations, step_tol, gain_tol):
        def residuals(xs):
            return [np.asarray(b.eval(xs), dtype=float) * b.weight for b in active]

        lam = 1e-3
        converged = False
        rs = residuals(x)
        current = cost(rs)
        it = 0
        while it < max_iterations and not converged:
            JtJ = np.zeros((m, m))
            Jtr = np.zeros(m)
            xt = x.copy()
            for bi, b in enumerate(active):
                r0 = rs[bi]
                cols = [p for p in b.params if free[p]]
                if not cols:
                    continue
                J = np.empty((len(cols), len(r0)))
                for ci, p in enumerate(cols):
                    h = 1e-6 * max(1.0, abs(x[p]))
                    xt[p] = x[p] + h
                    rp = np.asarray(b.eval(xt), dtype=float)
                    xt[p] = x[p] - h
                    rm = np.asarray(b.eval(xt), dtype=float)
                    xt[p] = x[p]
                    J[ci] = (rp - rm) * (b.weight / (2 * h))
                idx = free_index[cols]
                Jtr[idx] += J @ r0
                JtJ[np.ix_(idx, idx)] += J @ J.T
            grad_norm = float(np.max(np.abs(Jtr))) if m else 0.0
            if grad_norm < 1e-9:
                break
            improved = False
            diag = np.diag(JtJ).copy()
            for _attempt in range(12):
                S = 1 / np.sqrt(diag * (1 + lam) + 1e-30)
                A = JtJ * np.outer(S, S)
                A[np.diag_indices(m)] += lam * diag * S * S
                rhs = -Jtr * S
                scaled = cholesky_solve(A, rhs)
                if scaled is None:
                    scaled = solve_linear(A, rhs)
                if scaled is None:
                    lam *= 10
                    continue
                d = np.zeros(n)
                d[free] = scaled * S
                xt = x + d
                step_norm = float(np.max(np.abs(d))) if n else 0.0
                rt = residuals(xt)
                ct = cost(rt)
                if ct < current:
                    x[:] = xt
                    rs = rt
                    gain = current - ct
                    current = ct
                    lam = max(lam / 3, 1e-12)
                    improved = True
                    if step_norm < step_tol or gain < gain_tol * max(1, current):
                        converged = True
                    break
                lam *= 4
            if not improved:
                break
            it += 1
            state["iterations"] += 1

    descend(blocks, QUICK_ITERATIONS if quick else MAX_ITERATIONS, 1e-6 if quick else 1e-9, 1e-8 if quick else 1e-12)
    refreshed = [b for b in blocks if b.refresh]
    rnd = 0
    while not quick and refreshed and rnd < REFIT_ROUNDS:
        moved = 0.0
        for b in refreshed:
            moved = max(moved, b.refresh(x))
        if moved < 1e-7:
            break
        descend(blocks, MAX_ITERATIONS, 1e-9, 1e-12)
        rnd += 1
    if pulls:
        for at, init in rests:
            init[:] = x[at:at + len(init)]
        descend([b for b in blocks if b not in pulls], RELEASE_ITERATIONS, 1e-9, 1e-12)
    if not quick and soft_count > 0 and _worst_hard(blocks, x) > CLOSE_FROM:
        for at, init in rests:
            init[:] = x[at:at + len(init)]
        descend([b for b in blocks if b not in pulls and (b.constraint_id is not None or b.weight == FREE_WEIGHT)], RELEASE_ITERATIONS, 1e-9, 1e-12)
    return _finish(sketch, slots, x, blocks, state["iterations"], soft_count, quick)


def _add_constraint_blocks(c, sketch, slots, options_datums, hard, read, anchor_at, dir_of, line_of, joint_of, radial_at, L, blocks, params_for):
    k = c["kind"]
    if k == "coincident":
        def ev(xs):
            p = anchor_at(xs, c["p"])
            q = anchor_at(xs, c["q"])
            return [p[0] - q[0], p[1] - q[1]]
        hard(c, [c["p"]["entity"], c["q"]["entity"]], ev)
    elif k == "horizontal":
        def ev(xs):
            ln = line_of(xs, c["entity"])
            return [ln["b"][1] - ln["a"][1]] if ln else [0]
        hard(c, [c["entity"]], ev)
    elif k == "vertical":
        def ev(xs):
            ln = line_of(xs, c["entity"])
            return [ln["b"][0] - ln["a"][0]] if ln else [0]
        hard(c, [c["entity"]], ev)
    elif k == "parallel":
        def ev(xs):
            da = dir_of(xs, c["a"])
            db = dir_of(xs, c["b"])
            return [(da[0] * db[1] - da[1] * db[0]) * L]
        hard(c, [c["a"], c["b"]], ev)
    elif k == "perpendicular":
        hard(c, [c["a"], c["b"]], lambda xs: [dot2(dir_of(xs, c["a"]), dir_of(xs, c["b"])) * L])
    elif k == "angle":
        target = (c["value"] * math.pi) / 180

        def ev(xs):
            da = dir_of(xs, c["a"])
            db = dir_of(xs, c["b"])
            angle = math.atan2(da[0] * db[1] - da[1] * db[0], dot2(da, db))
            folded = fmod(fmod(angle, math.pi) + math.pi, math.pi)
            diff = folded - target
            if diff > math.pi / 2:
                diff -= math.pi
            if diff < -math.pi / 2:
                diff += math.pi
            return [diff * L]
        hard(c, [c["a"], c["b"]], ev)
    elif k == "tangent":
        kinds = [slots[c["a"]][0]["kind"] if c["a"] in slots else None, slots[c["b"]][0]["kind"] if c["b"] in slots else None]
        if "spline" in kinds:
            spline = c["a"] if kinds[0] == "spline" else c["b"]
            other = c["b"] if spline == c["a"] else c["a"]
            joint = spline_joint(sketch, spline, other)
            if not joint:
                return

            def ev(xs):
                s = read(spline, xs)
                o = read(other, xs)
                if s["kind"] != "spline":
                    return [0]
                u = _spline_end_dir(s, joint["end"])
                if o["kind"] == "line":
                    d = normalize2(sub2(o["b"], o["a"])) or [1, 0]
                    return [(u[0] * d[1] - u[1] * d[0]) * L]
                if o["kind"] == "arc" and joint["at"] in ("a", "b"):
                    return [dot2(radial_at(o, joint["at"]), u) * L]
                if o["kind"] == "spline" and joint["at"] in ("a", "b"):
                    v = _spline_end_dir(o, joint["at"])
                    return [(u[0] * v[1] - u[1] * v[0]) * L]
                return [0]
            hard(c, [c["a"], c["b"]], ev)
            return
        joint = joint_of(c["a"], c["b"])
        if joint and "arc" in kinds and ("line" in kinds or (kinds[0] == "arc" and kinds[1] == "arc")):
            def ev(xs):
                ea = read(c["a"], xs)
                eb = read(c["b"], xs)
                if ea["kind"] == "arc" and eb["kind"] == "arc":
                    ua = radial_at(ea, joint["a"])
                    ub = radial_at(eb, joint["b"])
                    return [(ua[0] * ub[1] - ua[1] * ub[0]) * min(abs(ea["r"]), abs(eb["r"]))]
                arc = ea if ea["kind"] == "arc" else eb
                line = eb if ea["kind"] == "arc" else ea
                if line["kind"] != "line" or arc["kind"] != "arc":
                    return [0]
                d = normalize2(sub2(line["b"], line["a"])) or [1, 0]
                return [dot2(radial_at(arc, joint["a"] if ea["kind"] == "arc" else joint["b"]), d) * abs(arc["r"])]
            hard(c, [c["a"], c["b"]], ev)
            return

        def ev(xs):
            ea = read(c["a"], xs)
            eb = read(c["b"], xs)
            line = ea if ea["kind"] == "line" else eb if eb["kind"] == "line" else None
            rnd = eb if ea["kind"] == "line" else ea
            if rnd["kind"] in ("line", "point", "spline"):
                return [0]
            if line:
                d = normalize2(sub2(line["b"], line["a"])) or [1, 0]
                off = dot2(sub2(rnd["c"], line["a"]), perp2(d))
                return [abs(off) - rnd["r"]]
            if ea["kind"] in ("point", "line", "spline") or eb["kind"] in ("point", "line", "spline"):
                return [0]
            dist = len2(sub2(ea["c"], eb["c"]))
            external = abs(dist - (ea["r"] + eb["r"]))
            internal = abs(dist - abs(ea["r"] - eb["r"]))
            return [dist - (ea["r"] + eb["r"]) if external <= internal else dist - abs(ea["r"] - eb["r"])]
        hard(c, [c["a"], c["b"]], ev)
    elif k == "equal":
        def size(e):
            return len2(sub2(e["b"], e["a"])) if e["kind"] == "line" else 0 if e["kind"] in ("point", "spline") else e["r"]
        hard(c, [c["a"], c["b"]], lambda xs: [size(read(c["a"], xs)) - size(read(c["b"], xs))])
    elif k == "concentric":
        def centre(e):
            return e["p"] if e["kind"] == "point" else e["a"] if e["kind"] == "line" else e["pts"][0] if e["kind"] == "spline" else e["c"]

        def ev(xs):
            ca = centre(read(c["a"], xs))
            cb = centre(read(c["b"], xs))
            return [ca[0] - cb[0], ca[1] - cb[1]]
        hard(c, [c["a"], c["b"]], ev)
    elif k == "symmetric":
        about = c["about"]
        ids = [c["p"]["entity"], c["q"]["entity"]]
        if isinstance(about, dict) and "line" in about:
            ids.append(about["line"])
        trace = trace_of(options_datums, about["datum"]) if isinstance(about, dict) and "datum" in about else None
        axis = trace_line(trace) if trace else None
        if not isinstance(about, dict) or "line" in about or axis:
            def ev(xs):
                p = anchor_at(xs, c["p"])
                q = anchor_at(xs, c["q"])
                if about == "x":
                    return [p[1] + q[1], p[0] - q[0]]
                if about == "y":
                    return [p[0] + q[0], p[1] - q[1]]
                line = line_of(xs, about["line"]) if "line" in about else None
                a = line["a"] if line else (axis["a"] if axis else None)
                d = (normalize2(sub2(line["b"], line["a"])) or [1, 0]) if line else (axis["d"] if axis else None)
                if not a or not d:
                    return [0, 0]
                mid = [(p[0] + q[0]) / 2, (p[1] + q[1]) / 2]
                return [dot2(sub2(mid, a), perp2(d)), dot2(sub2(q, p), d)]
            hard(c, ids, ev)
    elif k == "length":
        def ev(xs):
            ln = line_of(xs, c["entity"])
            return [len2(sub2(ln["b"], ln["a"])) - c["value"]] if ln else [0]
        hard(c, [c["entity"]], ev)
    elif k in ("radius", "diameter"):
        def ev(xs):
            e = read(c["entity"], xs)
            return [e["r"] - (c["value"] if k == "radius" else c["value"] / 2)] if e["kind"] in ("arc", "circle") else [0]
        hard(c, [c["entity"]], ev)
    elif k == "distance":
        q = c["q"]
        if "line" in q:
            def ev(xs):
                p = anchor_at(xs, c["p"])
                ln = line_of(xs, q["line"])
                if not ln:
                    return [0]
                d = normalize2(sub2(ln["b"], ln["a"])) or [1, 0]
                return [abs(dot2(sub2(p, ln["a"]), perp2(d))) - c["value"]]
            hard(c, [c["p"]["entity"], q["line"]], ev)
        elif "datum" in q:
            trace = trace_of(options_datums, q["datum"])
            if trace:
                hard(c, [c["p"]["entity"]], lambda xs: [abs(trace_offset(trace, anchor_at(xs, c["p"]))) - c["value"]])
        else:
            axis = c.get("axis")
            hard(c, [c["p"]["entity"], q["entity"]], lambda xs: [distance_along(anchor_at(xs, c["p"]), anchor_at(xs, q), axis) - c["value"]])
    elif k == "pointOn":
        on = c["on"]
        if "line" in on:
            def ev(xs):
                ln = line_of(xs, on["line"])
                if not ln:
                    return [0]
                d = normalize2(sub2(ln["b"], ln["a"])) or [1, 0]
                return [dot2(sub2(anchor_at(xs, c["p"]), ln["a"]), perp2(d))]
            hard(c, [c["p"]["entity"], on["line"]], ev)
        elif "curve" in on:
            def ev(xs):
                e = read(on["curve"], xs)
                p = anchor_at(xs, c["p"])
                if e["kind"] == "spline":
                    fit = spline_curve(e)
                    near = nearest_on_spline(fit, p, 8)
                    d = spline_dir_at(spline_curve(e), near["t"])
                    side = (p[1] - near["point"][1]) * d[0] - (p[0] - near["point"][0]) * d[1]
                    return [-near["dist"] if side < 0 else near["dist"]]
                return [len2(sub2(p, e["c"])) - e["r"]] if e["kind"] in ("arc", "circle") else [0]
            hard(c, [c["p"]["entity"], on["curve"]], ev)
        else:
            trace = trace_of(options_datums, on["datum"])
            if trace:
                hard(c, [c["p"]["entity"]], lambda xs: [trace_offset(trace, anchor_at(xs, c["p"]))])
        if c.get("bounded") and "datum" not in on:
            oid = on["line"] if "line" in on else on["curve"]

            def ev(xs):
                e = read(oid, xs)
                p = anchor_at(xs, c["p"])
                if e["kind"] == "line":
                    d = sub2(e["b"], e["a"])
                    ln = len2(d)
                    if not (ln > 0):
                        return [0]
                    s = dot2(sub2(p, e["a"]), d) / ln
                    return [s if s < 0 else s - ln if s > ln else 0]
                if e["kind"] != "arc":
                    return [0]
                start = e["start"] + e["sweep"] if e["sweep"] < 0 else e["start"]
                sweep = abs(e["sweep"])
                two = 2 * math.pi
                along = fmod(fmod(math.atan2(p[1] - e["c"][1], p[0] - e["c"][0]) - start, two) + two, two)
                if sweep >= two or along <= sweep:
                    return [0]
                r = abs(e["r"])
                return [(along - sweep) * r if along - sweep <= two - along else -(two - along) * r]
            blocks.append(_Block(params_for([c["p"]["entity"], oid]), HARD_WEIGHT, ev, constraint_id=c["id"], bound=True))
    elif k == "collinear":
        on = c["on"]
        if "line" in on:
            def ev(xs):
                ln = line_of(xs, c["line"])
                mm = line_of(xs, on["line"])
                if not ln or not mm:
                    return [0, 0]
                nrm = perp2(normalize2(sub2(mm["b"], mm["a"])) or [1, 0])
                return [dot2(sub2(ln["a"], mm["a"]), nrm), dot2(sub2(ln["b"], mm["a"]), nrm)]
            hard(c, [c["line"], on["line"]], ev)
        else:
            trace = trace_of(options_datums, on["datum"])
            if trace:
                def ev(xs):
                    ln = line_of(xs, c["line"])
                    return [trace_offset(trace, ln["a"]), trace_offset(trace, ln["b"])] if ln else [0, 0]
                hard(c, [c["line"]], ev)


def _worst_hard(blocks, x):
    worst = 0.0
    for b in blocks:
        if b.constraint_id is not None:
            for v in b.eval(x):
                worst = max(worst, abs(v))
    return worst


def _finish(sketch, slots, x, blocks, iterations, soft_count, quick):
    out_entities = []
    two = 2 * math.pi
    for e in sketch["entities"]:
        s = slots[e["id"]]
        out = with_params(e, x, s[1])
        if out["kind"] in ("arc", "circle"):
            out["r"] = abs(out["r"])
        if out["kind"] == "arc":
            if out["sweep"] < 0:
                out["start"] += out["sweep"]
                out["sweep"] = -out["sweep"]
            wrapped = fmod(fmod(out["sweep"], two) + two, two)
            out["sweep"] = two if (wrapped < 1e-9 and out["sweep"] > 1e-9) else wrapped
            out["start"] = fmod(fmod(out["start"], two) + two, two)
        out_entities.append(out)
    sketch["entities"] = out_entities

    unmet = []
    soft_sq = 0.0
    hard_rows = []
    hard_cols = []
    for b in blocks:
        r = [float(v) for v in b.eval(x)]
        if b.constraint_id is None:
            if b.weight != FREE_WEIGHT:
                soft_sq += sum(v * v for v in r)
            continue
        worst = max(abs(v) for v in r) if r else -math.inf
        if worst > UNMET_TOLERANCE:
            had = next((u for u in unmet if u["id"] == b.constraint_id), None)
            if had:
                had["residual"] = max(had["residual"], worst)
            else:
                unmet.append({"id": b.constraint_id, "residual": worst})
        if quick or b.bound:
            continue
        cols = b.params
        rows = [[0.0] * len(cols) for _ in r]
        xt = x.copy()
        for ci, p in enumerate(cols):
            h = 1e-6 * max(1.0, abs(x[p]))
            xt[:] = x
            xt[p] += h
            rp = b.eval(xt)
            xt[p] -= 2 * h
            rm = b.eval(xt)
            for kk in range(len(r)):
                rows[kk][ci] = (rp[kk] - rm[kk]) / (2 * h)
        for row in rows:
            hard_rows.append(row)
            hard_cols.append(cols)
    redundant = 0 if quick else _redundant_rows(hard_rows, hard_cols, len(x), sketch)
    return {
        "ok": len(unmet) == 0,
        "iterations": iterations,
        "unmet": unmet,
        "redundant": redundant,
        "equations": len(hard_rows),
        "softRms": math.sqrt(soft_sq / soft_count) if soft_count > 0 else 0,
        "underConstrained": [] if quick else _loose_entities(hard_rows, hard_cols, len(x), sketch),
    }


def _held_by_itself(e):
    return bool(e.get("fixed") or e.get("projected") or e.get("points"))


def _loose_entities(rows, cols, n, sketch):
    held = np.zeros(n, dtype=bool)
    owner = [0] * n
    at = 0
    for e in sketch["entities"]:
        count = len(params_of(e))
        for i in range(count):
            owner[at + i] = e["id"]
            if _held_by_itself(e):
                held[at + i] = True
        at += count
    column = [-1] * n
    param = []
    for p in range(n):
        if held[p]:
            continue
        column[p] = len(param)
        param.append(p)
    m = len(param)
    if m == 0:
        return []
    dense = []
    for i, r in enumerate(rows):
        row = np.zeros(m)
        norm = 0.0
        for ci, p in enumerate(cols[i]):
            if column[p] >= 0:
                row[column[p]] = r[ci]
                norm += r[ci] * r[ci]
        norm = math.sqrt(norm)
        if norm > 1e-9:
            dense.append(row / norm)
    EPS = 1e-6
    pivot_of = [-1] * m
    rank = 0
    j = 0
    while j < m and rank < len(dense):
        best = rank
        for i in range(rank + 1, len(dense)):
            if abs(dense[i][j]) > abs(dense[best][j]):
                best = i
        if abs(dense[best][j]) < EPS:
            j += 1
            continue
        dense[rank], dense[best] = dense[best], dense[rank]
        pivot = dense[rank]
        pivot *= 1 / pivot[j]
        for i in range(len(dense)):
            if i == rank:
                continue
            f = dense[i][j]
            if abs(f) < EPS:
                continue
            dense[i] -= f * pivot
        pivot_of[j] = rank
        rank += 1
        j += 1
    loose = []
    for j in range(m):
        if pivot_of[j] < 0:
            if owner[param[j]] not in loose:
                loose.append(owner[param[j]])
            continue
        row = dense[pivot_of[j]]
        for kk in range(m):
            if pivot_of[kk] < 0 and abs(row[kk]) > EPS:
                if owner[param[j]] not in loose:
                    loose.append(owner[param[j]])
                break
    return loose


def _redundant_rows(rows, cols, n, sketch):
    k = len(rows)
    if k == 0:
        return 0
    fixed = np.zeros(n, dtype=bool)
    at = 0
    for e in sketch["entities"]:
        count = len(params_of(e))
        if e.get("fixed"):
            fixed[at:at + count] = True
        at += count
    dense = np.zeros((k, n))
    for i, r in enumerate(rows):
        for ci, p in enumerate(cols[i]):
            if not fixed[p]:
                dense[i, p] = r[ci]
        norm = math.sqrt(float(dense[i] @ dense[i]))
        if norm > 0:
            dense[i] /= norm
    gram = dense @ dense.T
    largest = float(np.max(np.diag(gram)))
    if largest == 0:
        return k
    values, _v = sym_eigen(gram)
    return sum(1 for v in values if v < 1e-6 * largest)


def measure_dimension(sketch, kind, a, b=None, datums=None, axis=None):
    """What a dimension of the kind would read on the sketch as it stands."""
    def ent(i):
        return next((e for e in sketch["entities"] if e["id"] == i), None)

    def point_of(x):
        if "at" in x:
            e = ent(x["entity"])
            return anchor_point(e, x["at"]) if e else None
        return x["p"] if x["kind"] == "point" else None if x["kind"] in ("line", "spline") else x["c"]

    if kind == "length":
        return len2(sub2(a["b"], a["a"])) if a.get("kind") == "line" else None
    if kind in ("radius", "diameter"):
        return (a["r"] if kind == "radius" else 2 * a["r"]) if a.get("kind") in ("arc", "circle") else None
    if kind == "angle":
        if a.get("kind") != "line" or not b or b.get("kind") != "line":
            return None
        da = normalize2(sub2(a["b"], a["a"]))
        db = normalize2(sub2(b["b"], b["a"]))
        if not da or not db:
            return None
        angle = math.atan2(da[0] * db[1] - da[1] * db[0], dot2(da, db))
        return (fmod(fmod(angle, math.pi) + math.pi, math.pi) * 180) / math.pi
    p = point_of(a)
    if not p or not b:
        return None
    if "datum" in b:
        trace = trace_of(datums, b["datum"])
        return abs(trace_offset(trace, p)) if trace else None
    if "line" in b:
        ln = ent(b["line"])
        if not ln or ln["kind"] != "line":
            return None
        d = normalize2(sub2(ln["b"], ln["a"]))
        return abs(dot2(sub2(p, ln["a"]), perp2(d))) if d else None
    q = point_of(b)
    return distance_along(p, q, axis) if q else None
