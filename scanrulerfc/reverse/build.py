# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/core/build.ts, buildTypes.ts, booleanGuard.ts, buildExtrude.ts, primitives.ts, patternCopies.ts
# SPDX-License-Identifier: AGPL-3.0-only
#
# The Builder: plays the build steps (resolve.py) in order on the kernel
# (kernel.py), keeping every body as it stands after each step. A body is a
# dict {name, shape, origins, surface?}: its shape, and which feature first
# made each of its faces ({face hash: feature id}), which a fingerprint's
# origin is. A step that fails says why, in its place, and the build carries
# on: later features that use its body fail in turn, independent ones still
# stand. A boolean is held to its volume (volume_refusal, booleanGuard.ts)
# and played again the kernel's other ways when it comes back open or wrong:
# its faces kept as cut, then fuzzy at 1e-4 mm and 1e-3 mm. A step that
# leaves pieces makes a body a piece, the extras id + n/1024. The states
# after each step are kept by the steps' keys (buildtypes.step_keys), so a
# build whose first steps match a kept one starts from there.
#
# The ported steps are the solids (extrude, revolve and coil, extract,
# import) and the body features (shell, fillet, chamfer, hole, thread,
# cutPlane, mirror, combine, pattern, draft, moveFace, deleteFace, offset,
# moveBody). The rest (sheet, split, loft, sweep, thicken, fit surface,
# trim, patch network; extrude to next, to last, to a body or a curved face)
# fail with LATER, naming the build step that brings them. Imports nothing
# from FreeCAD: the kernel is handed in.

import math

from .buildtypes import boxes_meet, diagonal_of, mesh_deflection, pick_each, step_keys
from .features import island_id, pattern_pitch, ISLAND_IDS
from .origins import compose_history, origins_after, same_surface
from .topo import describe_edge, describe_face, edge_distance, face_distance, match_edge, match_face, match_tolerance, read_topology, split_edges, tangent_chain
from .vec import add_scaled, cross, dot, length, normalize, scale, sub

# How far a volume may stray from what it must be, of the larger.
VOLUME_SLACK = 0.002
HOLE_LEAD_MM = 0.01
SPLIT_TIE = 1e-3
STATES_KEPT = 64
LATER = {"sheet": 10, "split": 10, "loft": 10, "sweep": 10, "thicken": 10, "surface": 11, "trim": 11, "network": 11}
LATER_WORDS = "{what} is not built in this FreeCAD port yet (build step {n} of the port brings it)."


def _mm3(v):
    from ._js import num_str, precision_number

    return f"{num_str(precision_number(v, 6))} mm³"


def volume_refusal(ask):
    """booleanGuard.ts volumeRefusal: why a boolean's result cannot stand,
    or None when it can. `ask`: {kind: join, parts, result}, {kind: cut,
    body, result}, or {kind: union | subtract | intersect, body, tool,
    common?, result}; every volume in mm³."""
    def off(got, want, of):
        return abs(got - want) > VOLUME_SLACK * max(of, 1e-9)

    k = ask["kind"]
    r = ask["result"]
    if k == "join":
        largest = max([0, *ask["parts"]])
        total = sum(ask["parts"])
        if r < largest * (1 - VOLUME_SLACK):
            return f"the join lost volume — {_mm3(r)}, less than the largest part alone, {_mm3(largest)}"
        if r > total * (1 + VOLUME_SLACK):
            return f"the join made volume — {_mm3(r)}, more than its parts together, {_mm3(total)}"
        return None
    if k == "cut":
        if r > ask["body"] * (1 + VOLUME_SLACK):
            return f"the cut gained volume — {_mm3(r)} from {_mm3(ask['body'])}"
        if r < 0:
            return "the cut left less than nothing"
        return None
    b, t = ask["body"], ask["tool"]
    c = ask.get("common")
    if k == "union":
        if r < max(b, t) * (1 - VOLUME_SLACK):
            return f"the join lost volume — {_mm3(r)}, less than the larger body alone, {_mm3(max(b, t))}"
        if r > (b + t) * (1 + VOLUME_SLACK):
            return f"the join made volume — {_mm3(r)}, more than the two bodies together, {_mm3(b + t)}"
        if c is not None and off(r, b + t - c, b + t):
            return f"the join is {_mm3(r)} where the two bodies less what they share come to {_mm3(b + t - c)}"
        return None
    if k == "subtract":
        if r > b * (1 + VOLUME_SLACK):
            return f"the cut gained volume — {_mm3(r)} from {_mm3(b)}"
        if r < b - t - VOLUME_SLACK * b:
            return f"the cut took more than the tool holds — {_mm3(r)} left of {_mm3(b)} by a tool of {_mm3(t)}"
        if c is not None and off(r, b - c, b):
            return f"the cut left {_mm3(r)} where the body less what it shares with the tool comes to {_mm3(b - c)}"
        return None
    if r > min(b, t) * (1 + VOLUME_SLACK):
        return f"what the bodies share came to {_mm3(r)}, more than the smaller holds, {_mm3(min(b, t))}"
    return None


# Which of the Builder's plays each build step kind takes: the dispatch the
# tests check against resolve.py's STEP_KINDS.
DISPATCH = {
    "failed": "fail", "sketch": "place_sketch", "extrude": "solid", "revolve": "solid", "extract": "solid", "import": "import",
    "moveBody": "move_body", "offsetBody": "body", "mirror": "body", "shell": "body", "fillet": "body", "chamfer": "body", "hole": "body",
    "thread": "body", "cutPlane": "body", "boolean": "body", "pattern": "body", "draft": "body", "moveFace": "body", "deleteFace": "body",
    **{k: "later" for k in LATER},
}


class StepFailed(Exception):
    """A step that cannot be made, in the words its row says."""


def tools_of(step):
    t = step.get("tool")
    return list(t) if isinstance(t, list) else [t]


def cylinder_solid(k, origin, axis, radius, frm, to):
    n = normalize(axis)
    if not n:
        raise StepFailed("The axis has no direction.")
    disc = k.face({"outer": [{"kind": "circle", "center": origin, "normal": n, "radius": radius}], "holes": []})
    return k.extrude(disc, n, frm, to)


def primitive_solid(k, p):
    """primitives.ts primitiveSolid: the solid an extracted element becomes."""
    from .loops import rectangle_loop

    kind = p["kind"]
    if kind == "slab":
        u = normalize(p["basisU"]) or [1, 0, 0]
        v = normalize(p["basisV"]) or [0, 1, 0]
        corner = add_scaled(add_scaled(p["origin"], u, -p["extentU"]), v, -p["extentV"])
        face = k.face({"outer": rectangle_loop(corner, u, v, 2 * p["extentU"], 2 * p["extentV"]), "holes": []})
        return k.extrude(face, p["normal"], -p["thickness"] / 2, p["thickness"] / 2)
    if kind == "cylinder":
        return cylinder_solid(k, p["origin"], p["axis"], p["radius"], -p["length"] / 2, p["length"] / 2)
    if kind == "cone":
        n = normalize(p["axis"]) or [0, 0, 1]
        u = normalize(cross(n, [1, 0, 0] if abs(n[0]) < 0.9 else [0, 1, 0])) or [1, 0, 0]
        a = add_scaled(p["origin"], n, -p["length"] / 2)
        b = add_scaled(p["origin"], n, p["length"] / 2)
        pts = [a, add_scaled(a, u, max(p["radius1"], 1e-6)), add_scaled(b, u, max(p["radius2"], 1e-6)), b]
        face = k.face({"outer": [{"kind": "line", "a": q, "b": pts[(i + 1) % 4]} for i, q in enumerate(pts)], "holes": []})
        return k.revolve(face, p["origin"], n, 2 * math.pi)
    if kind == "sphere":
        c, r = p["center"], p["radius"]
        top, bottom, side = add_scaled(c, [0, 0, 1], r), add_scaled(c, [0, 0, 1], -r), add_scaled(c, [1, 0, 0], r)
        face = k.face({"outer": [{"kind": "arc", "a": bottom, "m": side, "b": top}, {"kind": "line", "a": top, "b": bottom}], "holes": []})
        return k.revolve(face, c, [0, 0, 1], 2 * math.pi)
    if kind == "torus":
        n = normalize(p["axis"]) or [0, 0, 1]
        u = normalize(cross(n, [1, 0, 0] if abs(n[0]) < 0.9 else [0, 1, 0])) or [1, 0, 0]
        ring = k.face({"outer": [{"kind": "circle", "center": add_scaled(p["center"], u, p["majorRadius"]), "normal": cross(n, u), "radius": p["minorRadius"]}], "holes": []})
        return k.revolve(ring, p["center"], n, 2 * math.pi)
    if kind == "prism":
        faces = [k.face(q) for q in p["profiles"]]
        return k.fuse_all([k.extrude(f, p["dir"], p["from"], p["to"]) for f in faces]) if len(faces) > 1 else k.extrude(faces[0], p["dir"], p["from"], p["to"])
    raise StepFailed(f"A {kind} cannot be extracted.")


def trim_by_planes(k, solid, planes, origin):
    """buildExtrude trimByPlanes: the half of space on the far side of each
    limiting plane, seen from the sketch, cut away."""
    from .profiles import side_of

    for plane in planes:
        side = side_of(plane, origin)
        solid = k.cut(solid, k.half_space(plane["origin"], scale(plane["normal"], -side)))
    return solid


def fuse_parts(k, parts):
    return parts[0] if len(parts) == 1 else k.fuse_all(parts)


def copy_motions(step):
    """patternCopies copyMotions: each copy's rigid motion {r, t}, the
    original's first one (the identity) left out."""
    def rot(axis, deg):
        a = math.radians(deg)
        x, y, z = normalize(axis)
        c, s, C = math.cos(a), math.sin(a), 1 - math.cos(a)
        return [c + x * x * C, x * y * C - z * s, x * z * C + y * s, y * x * C + z * s, c + y * y * C, y * z * C - x * s, z * x * C - y * s, z * y * C + x * s, c + z * z * C]

    def apply(r, p):
        return [r[0] * p[0] + r[1] * p[1] + r[2] * p[2], r[3] * p[0] + r[4] * p[1] + r[5] * p[2], r[6] * p[0] + r[7] * p[1] + r[8] * p[2]]

    eye = [1, 0, 0, 0, 1, 0, 0, 0, 1]
    row = []
    for i in range(step["count"]):
        if step["mode"] == "linear":
            row.append({"r": eye, "t": scale(normalize(step["dir"]), step["step"] * i)})
        else:
            r = rot(step["dir"], pattern_pitch(step["step"], step["count"]) * i)
            o = step["origin"]
            row.append({"r": r, "t": sub(o, apply(r, o))})
    if step.get("grid"):
        g = step["grid"]
        row = [{"r": m["r"], "t": add_scaled(m["t"], normalize(g["dir"]), g["step"] * j)} for j in range(g["count"]) for m in row]
    return row[1:]


def _moved_face(f, m):
    r, t = m["r"], m["t"]

    def pt(p):
        return [r[0] * p[0] + r[1] * p[1] + r[2] * p[2] + t[0], r[3] * p[0] + r[4] * p[1] + r[5] * p[2] + t[1], r[6] * p[0] + r[7] * p[1] + r[8] * p[2] + t[2]]

    def d(v):
        return [r[0] * v[0] + r[1] * v[1] + r[2] * v[2], r[3] * v[0] + r[4] * v[1] + r[5] * v[2], r[6] * v[0] + r[7] * v[1] + r[8] * v[2]]

    out = {**f, "centroid": pt(f["centroid"]), "dir": d(f["dir"])}
    if f.get("center"):
        out["center"] = pt(f["center"])
    return out


def trace_copies(before, after, motions):
    """patternCopies traceCopies: each copy's faces traced to the faces they
    copy — the face moved by the copy's motion lies on their surface — so a
    copy face keeps its original's maker. {history, copies}."""
    kept = {f["hash"] for f in before}
    left = [f for f in after if f["hash"] not in kept]
    history = {}
    copies = {}
    for n, m in enumerate(motions, start=1):
        for f in before:
            moved = _moved_face(f, m)
            if moved["kind"] != "plane" and moved.get("dir"):
                from .topo import canonical_dir

                moved["dir"] = canonical_dir(moved["dir"])
            hit = same_surface(moved, [x for x in left if length(sub(x["centroid"], moved["centroid"])) < 1e-3 * max(1, length(moved["centroid"])) + 1e-3])
            if hit:
                history.setdefault(f["hash"], []).append(hit["hash"])
                copies[hit["hash"]] = n
                left = [x for x in left if x["hash"] != hit["hash"]]
    return {"history": history, "copies": copies}


class Builder:
    """build.ts Builder on the kernel given (kernel.Kernel, or anything
    with its methods)."""

    def __init__(self, kernel):
        self.kernel = kernel
        self.bodies = {}
        self.aliases = {}
        self.issued = set()
        self.pieces = {}
        self.stages = {}
        self.names = {}
        self.step_warnings = []
        self.steps_in_play = []
        self._topologies = {}
        self._tree = {"children": {}, "state": None}
        self._states = 0
        self.last_steps = {"recomputed": 0, "restored": 0, "of": 0, "played": []}

    # ---- bodies and ids
    def resolve(self, i):
        for _ in range(64):
            if i in self.bodies:
                break
            to = self.aliases.get(i)
            if to is None:
                break
            i = to
        return i

    def body_by_id(self, i):
        return self.bodies.get(self.resolve(i))

    def body(self, i):
        b = self.body_by_id(i)
        return b["shape"] if b else None

    def body_ids(self):
        return list(self.bodies)

    def body_before(self, step_id, body_id):
        staged = self.stages.get(step_id) or {}
        return staged.get(body_id) or staged.get(self.resolve(body_id)) or self.body_by_id(body_id)

    def stage_body(self, step_id, body_id, body):
        staged = self.stages.setdefault(step_id, {})
        staged.setdefault(body_id, body)

    def keep_input(self, step):
        b = step.get("body")
        if not isinstance(b, (int, float)) or isinstance(b, bool):
            return
        body = self.body_before(step["id"], b)
        if body:
            self.stages.setdefault(step["id"], {}).setdefault(self.resolve(b), body)

    def fresh_id(self, step_id):
        for n in range(ISLAND_IDS):
            i = step_id if n == 0 else island_id(step_id, n)
            if i in self.issued or i in self.bodies:
                continue
            self.issued.add(i)
            return i
        raise StepFailed(f"The feature leaves more than {ISLAND_IDS} separate bodies.")

    def islands(self, shape):
        k = self.kernel
        if k.solid_count(shape) <= 1:
            return [{"shape": shape, "volume": 0}]
        pieces = [{"shape": p, "volume": k.volume(p)} for p in k.solids(shape)]
        return sorted(pieces, key=lambda p: -p["volume"])

    def _origins_on(self, piece, origins):
        return {h: origins.get(h, -1) for h in self.kernel.face_hashes(piece)}

    def settle(self, i, name, shape, origins, step_id, surface=False, by_place=False):
        if surface:
            self.bodies[i] = {"name": name, "shape": shape, "origins": origins, "surface": True}
            return [i]
        pieces = self.islands(shape)
        if by_place and len(pieces) > 1:
            self._nearest_first(i, pieces, step_id)
        ids = []
        for n, p in enumerate(pieces):
            at = i if n == 0 else self.fresh_id(step_id)
            self.bodies[at] = {"name": name, "shape": p["shape"], "origins": origins if len(pieces) == 1 else self._origins_on(p["shape"], origins)}
            ids.append(at)
        if len(ids) > 1:
            self.pieces[i] = list(dict.fromkeys([*self.pieces.get(i, []), *ids[1:]]))
        return ids

    def _nearest_first(self, i, pieces, step_id):
        was = (self.stages.get(step_id) or {}).get(i)
        if not was or was.get("surface"):
            return
        tied = sum(1 for p in pieces if p["volume"] >= pieces[0]["volume"] * (1 - SPLIT_TIE))
        if tied < 2:
            return
        at = self.kernel.centroid(was["shape"])
        far = [length(sub(self.kernel.centroid(p["shape"]), at)) for p in pieces[:tied]]
        best = 0
        for n in range(1, tied):
            if far[n] < far[best] - 1e-6 * max(1, far[best]):
                best = n
        if best > 0:
            pieces.insert(0, pieces.pop(best))

    def _say_split(self, what, name, ids):
        if len(ids) > 1:
            self.step_warnings.append(f"{what} leaves {name} in {len(ids)} pieces — bodies {', '.join(_id_words(i) for i in ids)}.")

    def propagate(self, shape, before, history, step_id):
        return origins_after(self.kernel.face_hashes(shape), before, history, step_id)

    def geometric_history(self, before, result):
        tol = match_tolerance(diagonal_of(self.kernel, result))

        def fp(f):
            return {"kind": f["kind"], "centroid": f["centroid"], "dir": f["dir"], "area": f["area"], "origin": 0, **({"radius": f["radius"]} if f.get("radius") is not None else {})}

        kept = {f["hash"] for f in before}
        history = {}
        for f in self.kernel.faces(result):
            if f["hash"] in kept:
                continue
            best, best_d = None, math.inf
            for b in before:
                d = face_distance(fp(b), fp(f), tol)
                if d is not None and d < best_d:
                    best, best_d = b["hash"], d
            if best is not None:
                history.setdefault(best, []).append(f["hash"])
        return history

    # ---- picks
    def _diagonal(self, body):
        return diagonal_of(self.kernel, body["shape"])

    def topology(self, body, deflection):
        key = (id(body["shape"]), deflection)
        hit = self._topologies.get(key)
        if hit is None or hit[0] is not body["shape"]:
            t = read_topology(self.kernel, body["shape"], body["origins"], deflection)
            self._topologies[key] = hit = (body["shape"], t)
        return hit[1]

    def _find(self, body_id, wanted, step_id, asked, what):
        body = self.body_by_id(body_id) if step_id is None else self.body_before(step_id, body_id)
        if not body:
            return {"lost": "the body is gone"}
        t = self.topology(body, 1)
        candidates = t["faces"] if what == "face" else t["edges"]
        match, strict, describe = (match_face, face_distance, describe_face) if what == "face" else (match_edge, edge_distance, describe_edge)
        tol = match_tolerance(self._diagonal(body))
        if asked:
            return self._find_picks(body, wanted, asked, what, candidates, match, strict, describe, tol)
        found = pick_each(wanted, candidates, tol, match, describe)
        if "hashes" in found:
            self._note_found_by_place(wanted, candidates, found["hashes"], describe)
        return found

    def find_faces(self, body_id, wanted, step_id=None, asked=None):
        return self._find(body_id, wanted, step_id, asked, "face")

    def find_edges(self, body_id, wanted, step_id=None, asked=None):
        return self._find(body_id, wanted, step_id, asked, "edge")

    def _find_picks(self, body, wanted, asked, what, candidates, match, strict, describe, tol):
        from .where import live_picks, run_stored_where, sharp_by_surfaces, where_words

        lp = live_picks(wanted, asked, lambda f, p: strict(f, p, tol) is not None)
        hashes = []
        prints = list(lp["rest"])
        if lp["live"]:
            t = self.topology(body, mesh_deflection(self._diagonal(body)))

            def sharp(deg):
                known = {}

                def is_sharp(i):
                    e = t["edges"][i]
                    if e["hash"] not in known:
                        known[e["hash"]] = sharp_by_surfaces(e, lambda face, pts: self.kernel.face_normals(body["shape"], face, pts), deg)
                    return known[e["hash"]]

                return is_sharp

            for p in lp["live"]:
                at = run_stored_where(p["where"], t, {"name": body["name"]}, what, sharp, tol)
                if at:
                    for i in at:
                        h = (t["faces"] if what == "face" else t["edges"])[i]["hash"]
                        if h not in hashes:
                            hashes.append(h)
                    continue
                back = [f for f in p["found"] if match(f, [c["fingerprint"] for c in candidates], tol) is not None] if p["where"].get("optional") else p["found"]
                if not back:
                    continue
                prints += back
                one = len(back) == 1
                self.step_warnings.append(f"{where_words(p['where'])} {'names no ' + what + ' now' if at is not None else 'cannot be read now'}: its {len(back)} earlier {what}{'' if one else 's'} used — check {'it' if one else 'them'}.")
        found = pick_each(prints, candidates, tol, match, describe)
        if "lost" in found:
            return found
        self._note_found_by_place(prints, candidates, found["hashes"], describe)
        for h in found["hashes"]:
            if h not in hashes:
                hashes.append(h)
        return {"hashes": hashes}

    def _note_found_by_place(self, wanted, candidates, hashes, describe):
        by_place = []
        for w, h in zip(wanted, hashes):
            got = next((c["fingerprint"] for c in candidates if c["hash"] == h), None)
            if got and w.get("origin", -1) >= 0 and got.get("origin") != w["origin"]:
                by_place.append(describe(w))
        if len(by_place) == 1:
            self.step_warnings.append(f"{by_place[0][0].upper()}{by_place[0][1:]} found again by where it lies, not by its maker — check it.")
        elif by_place:
            self.step_warnings.append(f"{len(by_place)} picks found again by where they lie, not by their maker — check them.")

    # ---- the guard
    def volume_of(self, shape):
        return self.kernel.volume(shape) if self.kernel.solid_count(shape) > 0 else 0

    def played_again(self, attempt):
        """A step whose work left no closed solid, played again: its faces
        kept as cut, then its booleans fuzzy (1e-4 mm, then 1e-3 mm). The
        first try that closes, or None."""
        k = self.kernel
        for again in (lambda: k.keeping_splits(attempt), lambda: k.fuzzy_booleans(attempt), lambda: k.fuzzy_booleans(attempt, k.coarse_fuzz)):
            try:
                r = again()
            except Exception:  # noqa: BLE001 — refused this way too: the next way
                continue
            if k.is_closed_solid(r["shape"]):
                return r
        return None

    def tried_words(self, bodies=()):
        from .kernel import FUZZY_COARSE_MM, FUZZY_MM

        tried = f"tried exact, keeping splits, fuzzy {FUZZY_MM} mm and fuzzy {FUZZY_COARSE_MM} mm"
        if not bodies:
            return tried
        bad = [b for b in bodies if not self.kernel.is_closed_solid(b["shape"])]
        if bad:
            one = len(bad) == 1
            return f"{tried}; {' and '.join(b['name'] for b in bad)} {'is' if one else 'are'} no valid closed solid alone — mend {'it' if one else 'them'} first (reverse.body.check)"
        return f"{tried}; {'both bodies check' if len(bodies) == 2 else 'every body checks'} valid alone, so the trouble is where they meet — faces flush on one another or touching along a line: make them overlap, or move one a hair"

    def guarded(self, attempt, ask, what, bodies=()):
        k = self.kernel
        first = attempt()
        closed = k.is_closed_solid(first["shape"])
        reason = volume_refusal(ask(self.volume_of(first["shape"]))) if closed else "left no closed solid"
        if reason is None:
            return first
        again = self.played_again(attempt)
        if not again:
            raise StepFailed(f"{what} cannot stand: {reason}." if closed else f"{what} left no closed solid — {self.tried_words(bodies)}.")
        still = volume_refusal(ask(self.volume_of(again["shape"])))
        if still is not None:
            raise StepFailed(f"{what} cannot stand: {still}.")
        self.step_warnings.append(f"{what} was played again the kernel's other way: the first result {reason}.")
        return again

    # ---- the build
    def build(self, steps, sketch_of=lambda i: None, reuse=False):
        """Play the steps; {results, bodies, steps}. With `reuse`, the longest
        run of first steps a kept state matches is taken up, not played."""
        self.steps_in_play = steps
        keys = step_keys(steps, sketch_of) if reuse else []
        path = []
        node = self._tree
        while reuse and len(path) < len(keys):
            nxt = node["children"].get(keys[len(path)])
            if not nxt or nxt["state"] is None:
                break
            path.append(nxt)
            node = nxt
        self._restore(path[-1]["state"] if path else None)
        results = list(path[-1]["state"]["results"]) if path else []
        played = []
        for s in steps:
            if isinstance(s.get("name"), str):
                self.names[s["id"]] = s["name"]
        for i in range(len(path), len(steps)):
            self.step_warnings = []
            import time

            t0 = time.perf_counter()
            self.play(steps[i], sketch_of, results)
            played.append({"id": steps[i]["id"], "ms": (time.perf_counter() - t0) * 1000})
            if self.step_warnings:
                r = next((x for x in reversed(results) if x["id"] == steps[i]["id"]), None)
                if r and r["status"] == "ok":
                    r["warning"] = " ".join(dict.fromkeys(self.step_warnings))
            if reuse:
                node = node["children"].setdefault(keys[i], {"children": {}, "state": None})
                if node["state"] is None:
                    self._states += 1
                node["state"] = self._snapshot(results)
        if reuse and self._states > STATES_KEPT:
            self._tree = {"children": {}, "state": None}
            self._states = 0
        self.last_steps = {"recomputed": len(played), "restored": len(steps) - len(played), "of": len(steps), "played": played}
        return {"results": results, "bodies": self.briefs(), "steps": self.last_steps}

    def _snapshot(self, results):
        return {"bodies": dict(self.bodies), "aliases": dict(self.aliases), "issued": set(self.issued), "pieces": {k: list(v) for k, v in self.pieces.items()},
                "stages": {k: dict(v) for k, v in self.stages.items()}, "results": [dict(r) for r in results]}

    def _restore(self, state):
        if state is None:
            self.bodies, self.aliases, self.issued, self.pieces, self.stages = {}, {}, set(), {}, {}
            return
        self.bodies = dict(state["bodies"])
        self.aliases = dict(state["aliases"])
        self.issued = set(state["issued"])
        self.pieces = {k: list(v) for k, v in state["pieces"].items()}
        self.stages = {k: dict(v) for k, v in state["stages"].items()}

    def briefs(self):
        k = self.kernel
        out = []
        for i, b in self.bodies.items():
            shape = b["shape"]
            box = k.bounds(shape)
            out.append({"id": i, "name": b["name"], "surface": bool(b.get("surface")), "volume": 0 if b.get("surface") else self.volume_of(shape), "area": k.surface_area(shape),
                        "box": box, "faces": k.face_count(shape), "closed": False if b.get("surface") else k.is_closed_solid(shape)})
        return out

    # ---- one step
    def input_fault(self, step, results):
        b = step.get("body")
        if not isinstance(b, (int, float)) or isinstance(b, bool):
            return None
        named = [(b, "the body it works on")]
        if step["kind"] == "boolean":
            named += [(t, f"the body it is combined with, {(self.bodies.get(t) or {}).get('name', t)},") for t in tools_of(step)]
        for i, what in named:
            body = self.body_before(step["id"], i)
            if not body or body.get("surface"):
                continue
            try:
                valid = self.kernel.is_valid(body["shape"])
            except Exception:  # noqa: BLE001
                continue
            if not valid:
                return f"{what} already fails the kernel check (last changed by {self._last_changed(i, step['id'], results)}): mend that step — reverse_body_check says what is wrong with it as it stood"
        return None

    def _last_changed(self, body_id, step_id, results):
        i = self.resolve(body_id)
        failed = {r["id"] for r in results if r["status"] == "failed"}
        last = math.floor(i)
        for s, staged in self.stages.items():
            if s == step_id:
                break
            if s not in failed and (i in staged or body_id in staged):
                last = s
        return self.names.get(last, f"feature {last}")

    def play(self, step, sketch_of, results):
        k = self.kernel

        def fail(i, message, on=None):
            self.keep_input(step)
            fault = self.input_fault(on, results) if on else None
            if fault:
                results.append({"id": i, "status": "failed", "message": f"{message.rstrip('.')} — {fault}."})
                return
            results.append({"id": i, "status": "failed", "message": message})

        kind = step["kind"]
        try:
            if kind == "failed":
                fail(step["id"], step["message"])
                return
            if kind in LATER:
                fail(step["id"], LATER_WORDS.format(what=_kind_words(kind), n=LATER[kind]))
                return
            if kind == "sketch":
                results.append({"id": step["id"], "status": "ok", "sketchFrame": step.get("frame")})
                return
            if kind in ("extrude", "revolve", "extract"):
                solid = primitive_solid(k, step["primitive"]) if kind == "extract" else self.solid_of(step, sketch_of(step.get("sketchId")))
                if not k.is_closed_solid(solid):
                    fail(step["id"], "The result is not a closed solid.")
                    return
                self.place(step, solid, fail, results)
                return
            if kind == "import":
                text = (getattr(self, "step_files", None) or {}).get(step["file"])
                if text is None:
                    fail(step["id"], "The STEP file of this import is not here — open it again, or import it again.")
                    return
                made = []
                for part in k.read_step_parts(text):
                    shape = part["shape"]
                    sheet = k.solid_count(shape) == 0
                    made += self.settle(self.fresh_id(step["id"]), step["name"], shape, {h: step["id"] for h in k.face_hashes(shape)}, step["id"], sheet)
                if not made:
                    fail(step["id"], "The STEP file holds no solid and no surface.")
                else:
                    results.append({"id": step["id"], "status": "ok", "bodies": made})
                return
            if kind == "moveBody":
                ids = list(dict.fromkeys(self.resolve(b) for b in step["bodies"]))
                sources = [(i, self.body_before(step["id"], i)) for i in ids]
                if any(b is None for _, b in sources):
                    fail(step["id"], "A body this move takes is gone, or failed to build.")
                    return
                moved = [(i, b, k.transform_tracked(b["shape"], step["matrix"])) for i, b in sources]
                made = []
                for i, b, tr in moved:
                    if step.get("copy"):
                        made += self.settle(self.fresh_id(step["id"]), b["name"], tr["shape"], {h: step["id"] for h in k.face_hashes(tr["shape"])}, step["id"], b.get("surface", False))
                    else:
                        self.stage_body(step["id"], i, b)
                        self.settle(i, b["name"], tr["shape"], self.propagate(tr["shape"], b["origins"], tr["history"], step["id"]), step["id"], b.get("surface", False))
                        made.append(i)
                results.append({"id": step["id"], "status": "ok", "bodies": made})
                return
            if kind == "offsetBody" and step.get("keep"):
                source = self.body_for(step)
                if source.get("surface"):
                    fail(step["id"], "A sheet has no inside to offset — offset a solid.")
                    return
                grown = k.offset_solid(source["shape"], step["distance"])
                bodies = self.settle(self.fresh_id(step["id"]), step["name"], grown, {h: step["id"] for h in k.face_hashes(grown)}, step["id"])
                results.append({"id": step["id"], "status": "ok", "bodies": bodies})
                return
            if kind == "mirror" and not step.get("join"):
                source = self.body_for(step)
                mirrored = self.apply_to_body(step)
                bodies = self.settle(self.fresh_id(step["id"]), step["name"], mirrored["shape"], {h: step["id"] for h in k.face_hashes(mirrored["shape"])}, step["id"], source.get("surface", False))
                results.append({"id": step["id"], "status": "ok", "bodies": bodies})
                return
            self.play_on_body(step, fail, results)
        except StepFailed as e:
            fail(step["id"], str(e), step)
        except Exception as e:  # noqa: BLE001 — the kernel's refusal: the step fails, the build carries on
            fail(step["id"], str(e), step)

    def body_for(self, step):
        body = self.body_before(step["id"], step["body"])
        if not body:
            raise StepFailed("The body this feature works on is gone, or failed to build.")
        return body

    def play_on_body(self, step, fail, results):
        k = self.kernel
        kind = step["kind"]
        body = self.body_for(step)
        body_id = self.resolve(step["body"])
        before = dict(body["origins"])
        if kind == "boolean":
            for t in tools_of(step):
                for h, o in ((self.bodies.get(self.resolve(t)) or {}).get("origins") or {}).items():
                    before[h] = o
        if body.get("surface") and kind not in ("pattern", "boolean"):
            fail(step["id"], "A sheet is not worked on as a solid — split a body with it, or thicken it first. A sheet takes a Pattern, a Split (by sheets or solids) and a Combine (trimmed by a solid, or sewn to a sheet).")
            return
        tools = [self.bodies.get(self.resolve(t)) for t in tools_of(step)] if kind == "boolean" else []
        tools = [t for t in tools if t is not None]
        volumes = {"body": self.volume_of(body["shape"]), "tool": sum(self.volume_of(t["shape"]) for t in tools)} if kind == "boolean" else None

        def combine_ask(shape):
            if kind != "boolean" or not volumes or body.get("surface"):
                return None
            if step["op"] == "join" and len(tools_of(step)) > 1:
                return {"kind": "join", "parts": [self.volume_of(b["shape"]) for b in [body, *tools]], "result": self.volume_of(shape)}
            what = "union" if step["op"] == "join" else "subtract" if step["op"] == "cut" else "intersect"
            common = None
            if what != "intersect" and len(tools) == 1:
                common = self.volume_of(k.common_tracked(body["shape"], tools[0]["shape"])["shape"])
            return {"kind": what, **volumes, **({"common": common} if common is not None else {}), "result": self.volume_of(shape)}

        def refusal_of(shape):
            ask = combine_ask(shape)
            return volume_refusal(ask) if ask else None

        first = self.apply_to_body(step)
        whole = k.is_surface(first["shape"]) if body.get("surface") else k.is_closed_solid(first["shape"])
        result = first
        if kind == "cutPlane" and not whole and self.volume_of(first["shape"]) <= 1e-9:
            fail(step["id"], f"The cut takes the whole of {body['name']} — nothing is left on the side kept. Keep the other side (keep: {-step['keep']}), or move the plane.")
            return
        refusal = refusal_of(first["shape"]) if whole else None
        if (not whole or refusal is not None) and not body.get("surface") and kind not in ("fillet", "chamfer"):
            why = refusal or "left no closed solid"
            result = self.played_again(lambda: self.apply_to_body(step))
            whole = result is not None
            refusal = refusal_of(result["shape"]) if result else None
            if result and refusal is None:
                self.step_warnings.append(f"The {'combine' if kind == 'boolean' else kind} was played again the kernel's other way: the first result {why}.")
        if result and refusal is not None:
            fail(step["id"], f"The combine cannot stand: {refusal}.")
            return
        if not whole or result is None:
            played = not body.get("surface") and kind not in ("fillet", "chamfer")
            tried = f" — {self.tried_words([body, *tools] if kind == 'boolean' else [])}" if played else ""
            if body.get("surface"):
                fail(step["id"], f"The {'combine' if kind == 'boolean' else kind} left no sheet the kernel's check passes.", step)
                return
            what = "cut" if kind == "cutPlane" else ("moved face" if len(step["faces"]) == 1 else "moved faces") if kind == "moveFace" else "offset" if kind == "offsetBody" else kind
            fail(step["id"], f"The {what} left no closed solid{tried}.", step)
            return
        self.stage_body(step["id"], body_id, body)
        origins = self.propagate(result["shape"], before, result["history"], step["id"])
        for i in result.get("consumed") or []:
            gone = self.bodies.get(i)
            if gone:
                self.stage_body(step["id"], i, gone)
            self.bodies.pop(i, None)
            self.aliases[i] = body_id
        split = kind in ("cutPlane", "boolean")
        settled = self.settle(body_id, body["name"], result["shape"], origins, step["id"], bool(body.get("surface")), split)
        if split:
            self._say_split("The cut" if kind == "cutPlane" else "The combine", body["name"], settled)
        out = {"id": step["id"], "status": "ok"}
        if result.get("note"):
            out["note"] = result["note"]
        if result.get("edges"):
            out["edges"] = result["edges"]
        if kind == "boolean":
            out["took"] = len(tools)
        results.append(out)

    # ---- solids from profiles
    def solid_of(self, step, sketch):
        from .profiles import grazing_joins_words, mend_near_tangent, mend_poles, mend_words, pole_words, profile_across_axis

        k = self.kernel
        if step["kind"] == "extrude" and step.get("faceProfile"):
            return self.pull_face(step, step["faceProfile"])
        if step["kind"] == "revolve" and step.get("pitch"):
            return self.coil_of(step)
        grazing = []
        if step["kind"] == "extrude" and abs(step.get("draftDeg") or 0) > 1e-9:
            mended = mend_near_tangent(step["profiles"])
            if mended["mends"]:
                step = {**step, "profiles": mended["profiles"]}
                self.step_warnings.append(mend_words(mended["mends"]))
            grazing = mended["left"]
        if step["kind"] == "revolve":
            axis = normalize(step["dir"])
            poles = mend_poles(step["profiles"], step["origin"], axis) if axis else None
            if poles:
                step = {**step, "profiles": poles["profiles"]}
                if poles["mends"]:
                    self.step_warnings.append(pole_words(poles["mends"]))
        faces = [k.face(p) for p in step["profiles"]]
        if step["kind"] == "extrude":
            if not grazing:
                return self.extrude(step, faces, sketch)
            try:
                solid = self.extrude(step, faces, sketch)
            except StepFailed:
                raise
            except Exception as e:  # noqa: BLE001 — a grazing join, named
                raise StepFailed(grazing_joins_words(grazing)) from e
            if k.is_closed_solid(solid):
                return solid
            raise StepFailed(grazing_joins_words(grazing))
        axis = normalize(step["dir"])
        across = profile_across_axis(step["profiles"], step["origin"], axis) if axis else None
        if across:
            from ._js import num_str, precision_number

            at = "(" + ", ".join(num_str(round(v * 1000) / 1000) for v in across["at"]) + ")"
            if across["across"] > 0:
                raise StepFailed(f"The profile crosses the revolve’s axis — it reaches {num_str(precision_number(across['across'], 3))} mm over it at {at}. A revolve turns what lies on one side of its axis: end the pieces on the axis (a profile may end on it, as a sphere’s arc does, or run along it), or pick only the region on one side.")
            raise StepFailed(f"The revolve’s axis runs through the profile at {at} — a revolve turns a profile beside its axis, or one with the axis on its edge.")
        return fuse_parts(k, [k.revolve(f, step["origin"], step["dir"], step["angleRad"]) for f in faces])

    def coil_of(self, step):
        from .profiles import profile_span, profiles_meet_axis

        d = normalize(step["dir"])
        if not d:
            raise StepFailed("The axis this revolve turns about has no direction.")
        if profiles_meet_axis(step["profiles"], step["origin"], d):
            raise StepFailed("The profile touches or crosses the axis — a coil winds round the axis, so its profile has to stand clear of it.")
        span = profile_span(step["profiles"], step["origin"], d)
        reach = span["max"] - span["min"]
        if step["angleRad"] >= 2 * math.pi - 1e-9 and reach >= abs(step["pitch"]) - 1e-6:
            from ._js import to_fixed

            r, p = to_fixed(reach, 3), to_fixed(abs(step["pitch"]), 3)
            raise StepFailed(f"The profile reaches {r} mm along the axis — as far as the pitch of {p} mm or further, so each turn would run into the next. Give a pitch over {r} mm, or turn less than once.")
        return fuse_parts(self.kernel, [self.kernel.screw(p, step["origin"], d, step["angleRad"], step["pitch"], step["leftHanded"]) for p in step["profiles"]])

    def pull_face(self, step, on):
        k = self.kernel
        found = self.find_faces(on["body"], [on["face"]], step["id"])
        if "lost" in found:
            raise StepFailed(f"The face this extrude pulls is gone (was: {found['lost']}).")
        body = self.body_before(step["id"], on["body"])
        f = next((x for x in k.faces(body["shape"]) if x["hash"] == found["hashes"][0]), None)
        if not f or f["kind"] != "plane":
            raise StepFailed("The face this extrude pulls is not flat.")
        face = k.face_copy(body["shape"], f["hash"])
        if not isinstance(step["from"], (int, float)) or not isinstance(step["to"], (int, float)):
            raise StepFailed(LATER_WORDS.format(what="An extrude from a face to a plane", n=10))
        return k.extrude(face, f["dir"], step["from"], step["to"], step.get("draftDeg") or 0)

    def extrude(self, step, faces, sketch):
        from .profiles import far_reach

        k = self.kernel
        if step.get("along"):
            step = {**step, "dir": step["along"]}
        until = step.get("until")
        if until and until["kind"] != "face":
            raise StepFailed(LATER_WORDS.format(what="An extrude to the next face, the last or a body", n=10))
        planes = [x for x in (step["from"], step["to"]) if not isinstance(x, (int, float))]
        to_face = None
        if until:
            found = self.find_faces(until["body"], [until["face"]], step["id"])
            if "lost" in found:
                raise StepFailed(f"The face this extrusion reaches to is gone (was: {found['lost']}).")
            body = self.body_before(step["id"], until["body"])
            f = body and next((x for x in k.faces(body["shape"]) if x["hash"] == found["hashes"][0]), None)
            if not f:
                raise StepFailed("The face this extrusion reaches to is not on the body.")
            if f["kind"] != "plane":
                raise StepFailed(LATER_WORDS.format(what="An extrude to a curved face", n=10))
            to_face = {"origin": f["centroid"], "normal": f["dir"]}
            planes.append(to_face)
        frm, to = step["from"], step["to"]
        if not to_face and isinstance(frm, (int, float)) and isinstance(to, (int, float)) and abs(to - frm) < 1e-9:
            raise StepFailed("The extrusion has no length.")
        if abs(step.get("draftDeg") or 0) > 1e-9:
            return trim_by_planes(k, self.tapered_prism(step, faces, to_face), planes, step["origin"])
        far = far_reach(step["origin"], step["dir"], sketch or {"entities": [], "constraints": [], "nextId": 1}, planes) if planes else 0
        lo = frm if isinstance(frm, (int, float)) else -far
        hi = to if isinstance(to, (int, float)) else far
        if to_face:
            hi = far if dot(sub(to_face["origin"], step["origin"]), step["dir"]) >= lo else -far
        parts = [k.extrude(f, step["dir"], min(lo, hi), max(lo, hi)) for f in faces]
        return trim_by_planes(k, fuse_parts(k, parts), planes, step["origin"])

    def tapered_prism(self, step, faces, to_face):
        """buildExtrude taperedPrism, its ends: from the profile at the sketch
        plane (or the extent's end nearest it) leaning away both ways, a
        plane end reached a hair past. The original's refusal of a taper
        that closes the profile before the end (taper.ts) is not ported:
        the kernel's refusal stands for it."""
        k = self.kernel
        d = normalize(step["dir"])
        if not d:
            raise StepFailed("The extrusion has no direction.")
        frm, to = step["from"], step["to"]

        def hits(plane):
            c = dot(d, plane["normal"])
            if abs(c) < 1e-9:
                raise StepFailed("A plane this extrusion reaches to runs along it, so it never ends it.")
            t = dot(sub(plane["origin"], step["origin"]), plane["normal"]) / c
            return {"min": t, "max": t}

        lo_on = hi_on = False
        if to_face or (isinstance(frm, (int, float)) and not isinstance(to, (int, float))):
            h = hits(to_face or to)
            lo = frm
            hi = h["max"] if (h["min"] + h["max"]) / 2 >= lo else h["min"]
            hi_on = True
        elif isinstance(frm, (int, float)) and isinstance(to, (int, float)):
            lo, hi = frm, to
        else:
            a, b = hits(frm), hits(to)
            lo, hi = min(a["min"], b["min"]), max(a["max"], b["max"])
            lo_on = hi_on = True
        start = min(max(0, min(lo, hi)), max(lo, hi))

        def past(e):
            return start + (e - start) + math.copysign(1, e - start) * (1e-3 * abs(e - start) + 1e-3)

        ends = [e for e in (past(lo) if lo_on else lo, past(hi) if hi_on else hi) if abs(e - start) > 1e-9]
        if not ends:
            raise StepFailed("The extrusion has no length.")
        return fuse_parts(k, [k.extrude(f, d, start, end, step["draftDeg"]) for f in faces for end in ends])

    # ---- placing a solid
    def place(self, step, solid, fail, results):
        k = self.kernel
        if step["op"] == "new":
            bodies = self.settle(self.fresh_id(step["id"]), step["name"], solid, {h: step["id"] for h in k.face_hashes(solid)}, step["id"])
            if len(bodies) > 1:
                self.step_warnings.append(f"The feature made {len(bodies)} separate solids — bodies {', '.join(_id_words(b) for b in bodies)}. A Combine on it takes them all; a shell or draft works on the one it names, and a fillet or chamfer named on this feature with edges by a query goes on each solid it hits.")
            results.append({"id": step["id"], "status": "ok", "bodies": bodies})
            return
        if step.get("target") is not None:
            self.place_on_target(step, step["target"], solid, fail, results)
            return
        try:
            bodies = self.join_all(step["id"], step["name"], solid) if step["op"] == "join" else self.cut_all(step["id"], solid)
            results.append({"id": step["id"], "status": "ok", "bodies": bodies})
        except Exception as e:  # noqa: BLE001
            fail(step["id"], str(e))

    def solids_near(self, shape):
        k = self.kernel
        box = k.extent(shape)
        return [(i, b) for i, b in self.bodies.items() if not b.get("surface") and boxes_meet(box, k.extent(b["shape"]))]

    def probe_of(self, shape):
        """A point on a solid's surface, in the middle of its largest
        triangle of a coarse mesh, and how far a chord may leave it."""
        sag = mesh_deflection(diagonal_of(self.kernel, shape))
        m = self.kernel.mesh(shape, sag)
        p, ix = m["positions"], m["indices"]
        best = -1
        at = [p[0], p[1], p[2]] if p else [0, 0, 0]
        for t in range(0, len(ix), 3):
            a, b, c = ix[t] * 3, ix[t + 1] * 3, ix[t + 2] * 3
            n = cross([p[b] - p[a], p[b + 1] - p[a + 1], p[b + 2] - p[a + 2]], [p[c] - p[a], p[c + 1] - p[a + 1], p[c + 2] - p[a + 2]])
            area = length(n)
            if area > best:
                best = area
                at = [(p[a] + p[b] + p[c]) / 3, (p[a + 1] + p[b + 1] + p[c + 1]) / 3, (p[a + 2] + p[b + 2] + p[c + 2]) / 3]
        return {"at": at, "tolerance": max(sag * 2, 1e-4)}

    def join_all(self, step_id, name, solid):
        k = self.kernel
        own = {h: step_id for h in k.face_hashes(solid)}
        near = self.solids_near(solid)
        if not near:
            return self.settle(self.fresh_id(step_id), name, solid, own, step_id)
        probes = [{"id": i, **self.probe_of(b["shape"])} for i, b in near]
        tool_probes = [self.probe_of(p) for p in k.solids(solid)] if k.solid_count(solid) > 1 else [self.probe_of(solid)]
        origins = dict(own)
        for _, b in near:
            origins.update(b["origins"])

        def fuse_near():
            at = solid
            history = {}
            for _, b in near:
                r = k.fuse_tracked(at, b["shape"])
                at = r["shape"]
                history = compose_history(history, r["history"])
            return {"shape": at, "history": history}

        parts = [self.volume_of(solid), *[self.volume_of(b["shape"]) for _, b in near]]
        joined = self.guarded(fuse_near, lambda r: {"kind": "join", "parts": parts, "result": r}, "Joining", [{"name": name, "shape": solid}, *[b for _, b in near]])
        made = self.propagate(joined["shape"], origins, joined["history"], step_id)
        claimed = set()
        pieces = []
        for p in self.islands(joined["shape"]):
            of = [q["id"] for q in probes if q["id"] not in claimed and k.contains_point(p["shape"], q["at"], q["tolerance"])]
            claimed.update(of)
            pieces.append({**p, "of": of, "tool": any(k.contains_point(p["shape"], q["at"], q["tolerance"]) for q in tool_probes)})
        ids = []
        kept = set()
        for p in pieces:
            if not p["tool"] and len(p["of"]) == 1:
                kept.add(p["of"][0])
                continue
            i = p["of"][0] if p["of"] else self.fresh_id(step_id)
            was = self.bodies.get(i)
            for gone in p["of"]:
                self.stage_body(step_id, gone, self.bodies[gone])
                if gone != i:
                    self.bodies.pop(gone, None)
                    self.aliases[gone] = i
                kept.add(gone)
            self.bodies[i] = {"name": was["name"] if was else name, "shape": p["shape"], "origins": {h: made.get(h, step_id) for h in k.face_hashes(p["shape"])}}
            ids.append(i)
        for i, b in near:
            if i in kept:
                continue
            self.stage_body(step_id, i, b)
            self.bodies.pop(i, None)
            if ids:
                self.aliases[i] = ids[0]
        return ids

    def cut_all(self, step_id, solid):
        k = self.kernel
        tool = k.face_hashes(solid)
        cuts = []
        for i, b in self.solids_near(solid):
            r = k.cut_tracked(b["shape"], solid)
            was = k.volume(b["shape"])
            left = self.volume_of(r["shape"])
            if abs(was - left) <= 1e-7 * max(1, was):
                continue
            if left <= 1e-9:
                cuts.append((i, b, None, {}))
                continue
            closed = k.is_closed_solid(r["shape"])
            why = volume_refusal({"kind": "cut", "body": was, "result": left}) if closed else "left no closed solid"
            if why is not None:
                again = self.played_again(lambda b=b: k.cut_tracked(b["shape"], solid))
                still = volume_refusal({"kind": "cut", "body": was, "result": self.volume_of(again["shape"])}) if again else why
                if not again or still is not None:
                    raise StepFailed(f"The cut left no closed solid of {b['name']}." if not again and not closed else f"The cut of {b['name']} cannot stand: {still}.")
                self.step_warnings.append(f"The cut of {b['name']} was played again the kernel's other way: the first result {why}.")
                r = again
            before = dict(b["origins"])
            for h in tool:
                before[h] = step_id
            cuts.append((i, b, r["shape"], self.propagate(r["shape"], before, r["history"], step_id)))
        if not cuts:
            raise StepFailed("The cut meets no body — there is nothing for it to take out.")
        ids = []
        for i, b, shape, origins in cuts:
            self.stage_body(step_id, i, b)
            if shape is not None:
                settled = self.settle(i, b["name"], shape, origins, step_id, False, True)
                self._say_split("The cut", b["name"], settled)
                ids += settled
            else:
                self.bodies.pop(i, None)
        return ids

    def place_on_target(self, step, target_id, solid, fail, results):
        k = self.kernel
        i = self.resolve(target_id)
        target = self.bodies.get(i)
        if not target:
            fail(step["id"], "The body to join or cut is gone, or failed to build.")
            return
        if target.get("surface"):
            fail(step["id"], f"{target['name']} is a surface, not a solid — a solid cannot {'join' if step['op'] == 'join' else 'cut'} it. Set the result to New body.")
            return
        before = dict(target["origins"])
        for h in k.face_hashes(solid):
            before[h] = step["id"]
        join = step["op"] == "join"

        def combine():
            return k.fuse_tracked(target["shape"], solid) if join else k.cut_tracked(target["shape"], solid)

        parts = [self.volume_of(target["shape"]), self.volume_of(solid)]
        pieces = [k.solid_count(target["shape"]), k.solid_count(solid)]
        try:
            combined = self.guarded(combine, lambda r: {"kind": "join", "parts": parts, "result": r} if join else {"kind": "cut", "body": parts[0], "result": r},
                                    "Joining" if join else "The cut", [target, {"name": step["name"], "shape": solid}])
            if join and k.solid_count(combined["shape"]) >= pieces[0] + pieces[1]:
                raise StepFailed(f"{step['name']} meets nothing of {target['name']} — joined, it would stand beside it as a body of its own. Check where it stands against the body and how far it reaches, or set the result to New body.")
        except Exception as e:  # noqa: BLE001
            why = str(e)
            fail(step["id"], why.replace("The cut left no closed solid", "The cut left no closed solid (did it take the whole body?)", 1) if why.startswith("The cut left no closed solid —") else why)
            return
        self.stage_body(step["id"], i, target)
        bodies = self.settle(i, target["name"], combined["shape"], self.propagate(combined["shape"], before, combined["history"], step["id"]), step["id"], False, not join)
        if not join or len(bodies) > pieces[0]:
            self._say_split("The cut" if not join else "The join", target["name"], bodies)
        results.append({"id": step["id"], "status": "ok", "bodies": bodies})

    # ---- a feature on a body
    def took_something(self, body, result, what):
        k = self.kernel
        was = k.volume(body["shape"])
        left = self.volume_of(result["shape"])
        if abs(was - left) <= 1e-7 * max(1, was):
            raise StepFailed(f"{what} meets nothing of {body['name']} — the cut took nothing out. Check where it stands against the body and how far it reaches.")
        return result

    def reach_of(self, shape):
        return max(diagonal_of(self.kernel, shape) * 2, 10)

    def draft_neutral(self, step, body):
        n = step["neutral"]
        if "face" not in n:
            return n["origin"], n["normal"]
        found = self.find_faces(step["body"], [n["face"]], step["id"])
        if "lost" in found:
            raise StepFailed(f"The neutral face of this draft is gone (was: {found['lost']}).")
        f = next((x for x in self.kernel.faces(body["shape"]) if x["hash"] == found["hashes"][0]), None)
        if not f or f["kind"] != "plane":
            raise StepFailed("The neutral face of this draft is not a plane.")
        return f["centroid"], scale(f["dir"], -1)

    def draft_picks(self, step):
        groups = [{"faces": step["faces"], "angleRad": step["angleRad"], "asked": step.get("facesWhere")}, *(step.get("groups") or [])]
        out = {"hashes": [], "angles": [], "refs": []}
        body = self.body_before(step["id"], step["body"])
        now = {f["hash"]: f["fingerprint"] for f in self.topology(body, 1)["faces"]} if body else {}
        for g in groups:
            found = self.find_faces(step["body"], g["faces"], step["id"], g.get("asked"))
            if "lost" in found:
                return found
            for n, h in enumerate(found["hashes"]):
                if h in out["hashes"]:
                    continue
                out["hashes"].append(h)
                out["angles"].append(g["angleRad"])
                out["refs"].append(now.get(h, g["faces"][n] if n < len(g["faces"]) else None))
        return out

    def _round_what_holds(self, step, body, hashes, edges, splits, brief):
        k = self.kernel

        def op(hs):
            if step["kind"] == "chamfer" and step.get("mode"):
                return self.chamfer_sided(step, body, hs)
            return k.fillet_tracked(body["shape"], hs, step["radius"]) if step["kind"] == "fillet" else k.chamfer_tracked(body["shape"], hs, step["distance"])

        def holds(hs):
            try:
                r = op(hs)
                return r if k.is_closed_solid(r["shape"]) else None
            except Exception:  # noqa: BLE001 — refused: that chain is the one left out
                return None

        whole = holds(hashes)
        if whole:
            return {**whole, "edges": [b for h in hashes for b in brief(h)]}
        left = list(hashes)
        chains = []
        for h in hashes:
            if h not in left:
                continue
            picked = [x for x in tangent_chain(edges, [h], splits) if x in left]
            left = [x for x in left if x not in picked]
            chains.append(picked)
        kept, made, skipped = [], None, []
        for c in chains:
            r = holds([*kept, *c])
            if r:
                made, kept = r, [*kept, *c]
            else:
                skipped.append(c)
        verb = "round" if step["kind"] == "fillet" else "bevel"
        size = step["radius"] if step["kind"] == "fillet" else step["distance"]
        if not made:
            raise StepFailed(f"None of the {len(chains)} chains {verb}s at {size} mm.")
        from ._js import to_fixed

        at = []
        for c in skipped[:12]:
            e = next((x for x in edges if x["hash"] == c[0]), None)
            at.append("(" + ", ".join(to_fixed(v, 3) for v in e["fingerprint"]["mid"]) + ")" if e else "(?)")
        one = len(skipped) == 1
        note = f"{len(skipped)} of the {len(chains)} chains left out — the kernel cannot {verb} {'it' if one else 'them'} with the rest: at {', '.join(at)}{' …' if len(skipped) > len(at) else ''}."
        return {**made, "edges": [b for h in kept for b in brief(h)], "note": note}

    def chamfer_sided(self, step, body, hashes):
        """build.ts chamferSided: a chamfer by two distances or by a distance
        and an angle, as the kernel's angled chamfer measuring from each
        edge's first face, the edges asking alike in one call."""
        from .kernel import dihedral

        k = self.kernel
        mode = step["mode"]
        t = self.topology(body, 1)
        edges = t["edges"]
        splits = split_edges(t)
        sides = k.edge_sides(body["shape"], hashes)
        for n, s in enumerate(sides):
            if s is None:
                e = next(x for x in edges if x["hash"] == hashes[n])
                raise StepFailed(f"A chamfer {'by two distances' if mode == 'twoDistances' else 'at an angle'} goes on an edge between two faces — {describe_edge(e['fingerprint'])} has one.")
        first_faces = k.faces(body["shape"])
        refs = reference_faces([s["faces"] for s in sides], bool(step.get("flip")))
        left = list(hashes)
        chains = []
        for n, h in enumerate(hashes):
            if h not in left:
                continue
            picked = [x for x in tangent_chain(edges, [h], splits) if x in left]
            left = [x for x in left if x not in picked]
            chains.append({"fingerprints": [next(e["fingerprint"] for e in edges if e["hash"] == x) for x in picked], "ref": next(f for f in first_faces if f["hash"] == refs[n])})
        current = {"shape": body["shape"], "history": {}}
        origins = body["origins"]
        pending = chains
        while pending:
            faces_now = first_faces if current["shape"] is body["shape"] else k.faces(current["shape"])
            edges_now = edges if current["shape"] is body["shape"] else self.topology({"name": body["name"], "shape": current["shape"], "origins": origins}, 1)["edges"]
            tol = match_tolerance(diagonal_of(k, current["shape"]))
            found = []
            for c in pending:
                hs = []
                for j, fp in enumerate(c["fingerprints"]):
                    at = match_edge(fp, [e["fingerprint"] for e in edges_now], tol)
                    if at is None and j == 0:
                        raise StepFailed(f"An edge this chamfer cuts is gone once its other edges are chamfered (was: {describe_edge(fp)}) — chamfer it in a feature of its own.")
                    if at is not None:
                        hs.append(edges_now[at]["hash"])
                found.append(hs)
            at = k.edge_sides(current["shape"], [f[0] for f in found])
            asks = []
            for n, c in enumerate(pending):
                s = at[n]
                if not s:
                    raise StepFailed(f"An edge this chamfer cuts no longer lies between two faces (was: {describe_edge(c['fingerprints'][0])}).")
                two = [f for f in faces_now if f["hash"] in s["faces"]]
                ref = same_surface(c["ref"], two)
                ask = angled_ask(step, ref is None or ref["hash"] == s["faces"][0], s["normals"], dihedral)
                if isinstance(ask, str):
                    raise StepFailed(f"At {describe_edge(c['fingerprints'][0])}: {ask}")
                asks.append(ask)

            def key(a):
                return f"{a['distance']:.6f}|{a['angleDeg']:.6f}"

            taken = [key(a) == key(asks[0]) for a in asks]
            nxt = k.chamfer_angled(current["shape"], [h for f, tk in zip(found, taken) if tk for h in f], asks[0]["distance"], asks[0]["angleDeg"])
            history = self.geometric_history(faces_now, nxt)
            origins = self.propagate(nxt, origins, history, step["id"])
            current = {"shape": nxt, "history": compose_history(current["history"], history)}
            pending = [c for c, tk in zip(pending, taken) if not tk]
        return current

    def apply_to_body(self, step):
        k = self.kernel
        body = self.body_for(step)
        kind = step["kind"]
        if kind == "shell":
            found = self.find_faces(step["body"], step["faces"], step["id"], step.get("facesWhere"))
            if "lost" in found:
                raise StepFailed(f"The face this shell opens is gone (was: {found['lost']}).")
            return k.shell_tracked(body["shape"], found["hashes"], step["thickness"])
        if kind in ("fillet", "chamfer"):
            varying = (step.get("variable") or []) if kind == "fillet" else []
            found = self.find_edges(step["body"], step["edges"], step["id"], step.get("edgesWhere")) if step["edges"] or not varying else {"hashes": []}
            if "lost" in found:
                raise StepFailed(f"The edge this {kind} was on is gone (was: {found['lost']}).")
            t = self.topology(body, 1)
            every = t["edges"]
            splits = split_edges(t)
            picked = tangent_chain(every, found["hashes"], splits) if step.get("chain") else found["hashes"]
            at = []
            for v in varying:
                f = self.find_edges(step["body"], [v["edge"]], step["id"])
                if "lost" in f:
                    raise StepFailed(f"An edge this fillet rounds at a varying radius is gone (was: {f['lost']}).")
                at.append(f["hashes"][0])
            theirs = set(tangent_chain(every, at, splits)) if at else set()
            hashes = [h for h in picked if h not in theirs]

            def brief(h):
                e = next((x for x in every if x["hash"] == h), None)
                if not e:
                    return []
                fp = e["fingerprint"]
                return [{"kind": fp["kind"], "mid": fp["mid"], "length": fp["length"], **({"radius": fp["radius"]} if fp.get("radius") is not None else {})}]

            edges = [b for h in hashes for b in brief(h)]
            if step.get("skipFailing") and not varying:
                return self._round_what_holds(step, body, hashes, every, splits, brief)
            if kind == "chamfer" and step.get("mode"):
                return {**self.chamfer_sided(step, body, hashes), "edges": edges}
            if not varying:
                made = k.fillet_tracked(body["shape"], hashes, step["radius"]) if kind == "fillet" else k.chamfer_tracked(body["shape"], hashes, step["distance"])
                return {**made, "edges": edges}
            radii = [{"hash": h, "radius": step["radius"]} for h in hashes] + [{"hash": h, "radius": list(v["radius"])} for h, v in zip(at, varying)]
            return {**k.fillet_radii(body["shape"], radii), "edges": edges + [b for h in at for b in brief(h)]}
        if kind == "hole":
            reach = self.reach_of(body["shape"])
            back = -HOLE_LEAD_MM if step.get("oneWay") else -reach if step["depth"] is None else -step["depth"]
            tool = cylinder_solid(k, step["origin"], step["dir"], step["radius"], back, reach if step["depth"] is None else step["depth"])
            return self.took_something(body, k.cut_tracked(body["shape"], tool), "The hole")
        if kind == "thread":
            found = self.find_faces(step["body"], [step["face"]], step["id"])
            if "lost" in found:
                raise StepFailed(f"The round face this thread is cut on is gone (was: {found['lost']}).")
            return k.thread_tracked(body["shape"], found["hashes"][0], step)
        if kind == "cutPlane":
            return k.cut_tracked(body["shape"], k.half_space(step["plane"]["origin"], scale(step["plane"]["normal"], -step["keep"])))
        if kind == "mirror":
            idx = next((n for n, o in enumerate(self.steps_in_play) if o["id"] == step["id"]), -1)
            threads = [o for n, o in enumerate(self.steps_in_play) if o["kind"] == "thread" and o.get("body") == step["body"] and (idx < 0 or n < idx)]
            if threads:
                names = [self.names.get(o["id"], f"feature {o['id']}") for o in threads]
                hands = {"left" if o.get("leftHanded") else "right" for o in threads}
                frm = next(iter(hands)) if len(hands) == 1 else None
                said = f"a {frm}-handed thread comes out {'left' if frm == 'right' else 'right'}-handed" if frm else "each thread comes out of the other hand"
                self.step_warnings.append(f"This mirrors {', '.join(names)}: {said}{' on the mirrored half' if step.get('join') else ' in the copy'}. To keep a thread's hand, copy the body with a 180° turn (moveBody) instead.")
            plane = step["plane"]
            if "face" in plane:
                found = self.find_faces(step["body"], [plane["face"]], step["id"])
                if "lost" in found:
                    raise StepFailed(f"The face this mirror is about is gone (was: {found['lost']}).")
                f = next((x for x in k.faces(body["shape"]) if x["hash"] == found["hashes"][0]), None)
                if not f or f["kind"] != "plane":
                    raise StepFailed("The face this mirror is about is not a plane.")
                plane = {"origin": f["centroid"], "normal": f["dir"]}
            mirrored = k.mirror_tracked(body["shape"], plane["origin"], plane["normal"])
            if not step.get("join"):
                return mirrored
            joined = k.fuse_tracked(body["shape"], mirrored["shape"])
            history = dict(joined["history"])
            for old, made in mirrored["history"].items():
                via = [x for h in made for x in joined["history"].get(h, [h])]
                history[old] = [*history.get(old, []), *via]
            return {"shape": joined["shape"], "history": history}
        if kind == "boolean":
            into = self.resolve(step["body"])
            if any(self.resolve(t) == into for t in tools_of(step)):
                raise StepFailed("The body this one is combined with has gone into it already." if len(tools_of(step)) == 1 else f"{(self.bodies.get(into) or {}).get('name', 'The body')} has taken in a tool already — a tool goes into it once.")
            family = list(dict.fromkeys(self.resolve(t) for t in tools_of(step)))
            tools = [self.bodies.get(i) for i in family]
            missing = [t for t, b in zip(tools_of(step), tools) if b is None]
            if not [b for b in tools if b]:
                raise StepFailed("The body this one is combined with is gone, or failed to build.")
            if missing:
                raise StepFailed(f"{'A tool' if len(missing) == 1 else 'Tools'} this one is combined with ({', '.join(_id_words(m) for m in missing)}) {'is' if len(missing) == 1 else 'are'} gone, or failed to build.")
            if body.get("surface"):
                raise StepFailed(LATER_WORDS.format(what="A Combine on a sheet", n=10))
            sheet = next((t for t in tools if t.get("surface")), None)
            if sheet:
                raise StepFailed(f"{sheet['name']} is a sheet, and {body['name']} a solid — a solid is combined with solids. Cut a body with a sheet by Split, or close sheets into a solid by Trim; to trim the sheet by the solid, make the sheet the body.")
            each = step["op"] == "intersect" and len(tools) > 1
            tool = k.fuse_all([t["shape"] for t in tools]) if not each and len(tools) > 1 else tools[0]["shape"]
            if each:
                shape = body["shape"]
                history = {}
                for t in tools:
                    r = k.common_tracked(shape, t["shape"])
                    shape, history = r["shape"], compose_history(history, r["history"])
                result = {"shape": shape, "history": history}
            elif step["op"] == "join":
                result = k.fuse_tracked(body["shape"], tool)
            elif step["op"] == "cut":
                result = self.took_something(body, k.cut_tracked(body["shape"], tool), tools[0]["name"] if len(tools) == 1 else "The tool")
            else:
                result = k.common_tracked(body["shape"], tool)
            return {**result, "consumed": [] if step.get("keep") else family}
        if kind == "draft":
            every = k.faces(body["shape"])
            origin, pull = self.draft_neutral(step, body)
            picks = self.draft_picks(step)
            if "lost" in picks:
                raise StepFailed(f"A face this draft leans is gone (was: {picks['lost']}).")
            skipped = []
            shape = k.draft_faces(body["shape"], picks["hashes"], origin, pull, picks["angles"], skipped)
            if skipped:
                one = len(skipped) == 1
                named = [describe_face(picks["refs"][n]) for n in skipped]
                self.step_warnings.append(f"{'A face' if one else f'{len(skipped)} faces'} picked already leaned by {'its' if one else 'their'} angle — drafted along with a tangent neighbour before {'it' if one else 'them'} — and {'was' if one else 'were'} passed over: {'; '.join(named)}.")
            return {"shape": shape, "history": self.geometric_history(every, shape)}
        if kind == "moveFace":
            found = self.find_faces(step["body"], step["faces"], step["id"], step.get("facesWhere"))
            if "lost" in found:
                raise StepFailed(f"A face this feature moves is gone (was: {found['lost']}).")
            return k.offset_faces_tracked(body["shape"], found["hashes"], step["offset"])
        if kind == "deleteFace":
            found = self.find_faces(step["body"], step["faces"], step["id"], step.get("facesWhere"))
            if "lost" in found:
                raise StepFailed(f"A face this feature deletes is gone (was: {found['lost']}).")
            before = k.faces(body["shape"])
            shape = k.delete_faces(body["shape"], found["hashes"])
            after = k.faces(shape)
            gone = set(found["hashes"])
            kept = {f["hash"] for f in after}
            history = {}
            for f in before:
                if f["hash"] in gone or f["hash"] in kept:
                    continue
                now = same_surface(f, after)
                if now:
                    history[f["hash"]] = [now["hash"]]
            if any(f["hash"] in gone for f in after) or (not body.get("surface") and not k.volume(shape) > 0):
                raise StepFailed("The faces could not be taken off — the faces round them do not run on to close the gap. Pick the whole of a round, a hole or a boss: every face it is made of.")
            return {"shape": shape, "history": history}
        if kind == "offsetBody":
            return {"shape": k.offset_solid(body["shape"], step["distance"]), "history": {}}
        if kind == "pattern":
            row = k.pattern(body["shape"], step["mode"], step["origin"], step["dir"], step["count"], step["step"])
            shape = k.pattern(row, "linear", step["origin"], step["grid"]["dir"], step["grid"]["count"], step["grid"]["step"]) if step.get("grid") else row
            traced = trace_copies(k.faces(body["shape"]), k.faces(shape), copy_motions(step))
            return {"shape": shape, "history": traced["history"], "copies": traced["copies"]}
        raise StepFailed(f"No feature of kind {kind} works on a body.")


def reference_faces(sides, flip):
    """chamferSides referenceFaces: each edge's face the chamfer's first
    distance is measured on — the one more of the picked edges share."""
    count = {}
    for s in sides:
        for f in set(s):
            count[f] = count.get(f, 0) + 1
    out = []
    for a, b in sides:
        ref = b if count.get(b, 0) > count.get(a, 0) else a
        out.append((b if ref == a else a) if flip else ref)
    return out


def angled_ask(step, ref_is_first, normals, dihedral):
    """chamferSides angledAsk: the kernel's distance on the edge's first face
    and angle to it that put the chamfer asked for on the reference face,
    or why it cannot."""
    phi = dihedral(normals)
    if not (1e-3 < phi < math.pi - 1e-3):
        return "the faces at the edge run on into each other — there is no corner to chamfer."
    if step["mode"] == "twoDistances":
        d1 = step["distance"]
        d2 = step.get("distance2") or d1
        a, b = (d1, d2) if ref_is_first else (d2, d1)
        distance = a
        angle = math.atan2(b * math.sin(phi), a - b * math.cos(phi))
    else:
        theta = math.radians(step.get("angleDeg") or 45)
        if ref_is_first:
            distance, angle = step["distance"], theta
        else:
            far = math.pi - phi - theta
            if not far > 1e-6:
                return f"at {round((step.get('angleDeg') or 45) * 10) / 10}° the chamfer does not reach the other face, which meets this one at {round(math.degrees(phi) * 10) / 10}°."
            distance = step["distance"] * math.sin(theta) / math.sin(phi + theta)
            angle = far
    deg = math.degrees(angle)
    if not (1e-6 < deg < 90 - 1e-6):
        return f"the kernel measures this edge's chamfer from its other face, where it would stand at {round(deg * 10) / 10}° — under 90° is all it takes there; flip the chamfer, or swap the distances."
    return {"distance": distance, "angleDeg": deg}


def _id_words(i):
    from ._js import num_str

    return num_str(i)


def _kind_words(kind):
    from .features import KIND_LABELS

    return f"A {KIND_LABELS.get(kind, kind)}"
