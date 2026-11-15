# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/core/parameters.ts
# SPDX-License-Identifier: AGPL-3.0-only
#
# The parameters of a model and the numbers that read them. A parameter is
# a named expression of a kind - a length, an angle, a whole number, a
# plain number - in one list for the whole model, outside the feature list
# and the rollback bar. A feature's numbers stay numbers, holding the value
# last evaluated; beside them the feature keeps the expressions that drive
# them, keyed by slot - the field as the box shows it (an extrude's To, a
# hole's Diameter). A sketch dimension keeps its expression beside its
# value the same way. When a parameter changes, every expression is
# evaluated again, the numbers written, every sketch with a changed
# dimension solved again, and the part rebuilt from nothing but numbers.
#
# As the original, a feature that comes out the same is the same object.

import re

from ._js import js_round, num_str
from .datums import datum_traces
from .expression import RESERVED_NAMES, dim_of_kind, evaluate_for, references, rename_in, valid_name
from .features import dependents_of, plane_at_offset, plane_offset, plane_takes_offset, revolve_max_deg, with_plane_offset
from .regions import find_regions, match_region, region_by_place, regions_by_pick, split_parts
from .sketch import clone_sketch, is_dimension
from .solver import solve_sketch

PARAMETER_KINDS = (
    {"kind": "length", "label": "Length", "unit": "mm"},
    {"kind": "angle", "label": "Angle", "unit": "°"},
    {"kind": "integer", "label": "Integer", "unit": ""},
    {"kind": "number", "label": "Number", "unit": ""},
)

_PLAIN = re.compile(r"[+-]?\d*\.?\d+(e[+-]?\d+)?\Z", re.I | re.A)
_NEGATED = re.compile(r"-\s*\((.*)\)\Z", re.S)


def negated_expr(e):
    """An expression of the opposite sign: "-(e)", or e again for "-(e)"."""
    t = e.strip()
    if _PLAIN.match(t):
        return num_str(-float(t))
    m = _NEGATED.match(t)
    if m:
        depth = 0
        pairs = True
        for ch in m.group(1):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth < 0:
                    pairs = False
        if pairs and depth == 0:
            return m.group(1).strip()
    return f"-({t})"


def exprs_from_command(kind, given):
    if kind != "extrude" or "draftDeg" not in given:
        return given
    rest = {k: v for k, v in given.items() if k != "draftDeg"}
    dd = given["draftDeg"]
    return {**rest, "taper": negated_expr(dd) if isinstance(dd, str) and dd.strip() != "" else dd}


def exprs_for_command(kind, exprs):
    if kind != "extrude" or "taper" not in exprs:
        return exprs
    rest = {k: v for k, v in exprs.items() if k != "taper"}
    return {**rest, "draftDeg": negated_expr(exprs["taper"])}


# ---- the table ---------------------------------------------------------------------


def name_problem(name, others, self_id=None):
    """Why a name will not do, or None."""
    if name == "":
        return "needs a name"
    if name in RESERVED_NAMES:
        return f"“{name}” is a word the expressions keep"
    if not valid_name(name):
        return "a name is a letter or an underscore, then letters, digits and underscores"
    clash = next((p for p in others if p["id"] != self_id and p["name"].lower() == name.lower()), None)
    if clash:
        return f"another parameter is named “{name}” already" if clash["name"] == name else f"too like “{clash['name']}” — a name may not differ from another’s by its case alone"
    return None


def evaluate_parameters(parameters):
    """Evaluate the whole table, each parameter after the ones it reads.
    Returns {"readings": [...], "scope": fn}; a reading is
    {"id", "name", "kind", "value", "error"}."""
    by_name = {}
    for p in parameters:
        by_name.setdefault(p["name"], p)
    by_lower = {}
    for p in parameters:
        by_lower.setdefault(p["name"].lower(), []).append(p)
    readings = {}
    visiting = []
    looped = {}

    def read(p):
        done = readings.get(id(p))
        if done:
            return done
        at = next((i for i, q in enumerate(visiting) if q is p), -1)
        if at >= 0:
            loop = [q["name"] for q in visiting[at:]] + [p["name"]]
            message = f"goes round in a loop: {' → '.join(loop)}"
            for q in visiting[at:]:
                looped[id(q)] = message
            return {"id": p["id"], "name": p["name"], "kind": p["kind"], "value": None, "error": message}
        visiting.append(p)
        problem = name_problem(p["name"], by_lower.get(p["name"].lower(), []), p["id"])
        if problem:
            reading = {"id": p["id"], "name": p["name"], "kind": p["kind"], "value": None, "error": problem}
        else:
            def scope(name):
                q = by_name.get(name)
                if q is None:
                    return None
                r = read(q)
                return {"error": f"“{name}” has no value: {r['error']}"} if r["value"] is None else {"value": r["value"], "dim": dim_of_kind(r["kind"])}

            r = evaluate_for(p["expression"], p["kind"], scope, whole=True)
            reading = {"id": p["id"], "name": p["name"], "kind": p["kind"], "value": r["value"] if r["ok"] else None, "error": None if r["ok"] else r["error"]}
        visiting.pop()
        loop = looped.get(id(p))
        if loop:
            reading = {**reading, "value": None, "error": loop}
        readings[id(p)] = reading
        return reading

    ordered = set()
    for root in parameters:
        stack = [(root, False)]
        while stack:
            p, expanded = stack.pop()
            reads = [by_name[n] for n in references(p["expression"]) if n in by_name]
            if expanded:
                if all(id(q) in readings for q in reads):
                    read(p)
                continue
            if id(p) in ordered:
                continue
            ordered.add(id(p))
            stack.append((p, True))
            for q in reads:
                if id(q) not in ordered:
                    stack.append((q, False))
    lst = [read(p) for p in parameters]
    by_read = {}
    for r in lst:
        by_read.setdefault(r["name"], r)

    def scope(name):
        r = by_read.get(name)
        if r is None:
            return None
        return {"error": f"“{name}” has no value"} if r["value"] is None else {"value": r["value"], "dim": dim_of_kind(r["kind"])}

    return {"readings": lst, "scope": scope}


# ---- slots ------------------------------------------------------------------------------
# A slot is {"path", "label", "kind", "get": fn(x), "set": fn(x, v)}.


def _num(x, key):
    v = x.get(key)
    return 0 if v is None else v


def _field(path, label, kind, tidy=lambda v: v):
    return {"path": path, "label": label, "kind": kind, "get": lambda x: _num(x, path), "set": lambda x, v: {**x, path: tidy(v)}}


def _positive(v):
    return abs(v)


def _pitch_of(x):
    return x.get("pitch") or 0


def _rmin(y, v):
    return min(revolve_max_deg(_pitch_of(y)), max(0.1, v))


def slots_of(x, kind=None):
    """The slots a feature or a draft offers, as its box shows them."""
    kind = x.get("kind") if kind is None else kind
    f = x
    if kind == "extrude":
        extent = f["extent"]
        out = []

        def ext(key, label, tidy=lambda v: v):
            return {"path": f"extent.{key}", "label": label, "kind": "length", "get": lambda y: _num(y["extent"], key), "set": lambda y, v: {**y, "extent": {**y["extent"], key: tidy(v)}}}

        if extent["kind"] == "distance":
            out += [ext("from", "From"), ext("to", "To")]
        elif extent["kind"] == "symmetric":
            out.append(ext("total", "Total", _positive))
        elif extent["kind"] != "betweenPlanes":
            out.append(ext("from", "From"))

        def taper_get(y):
            d = y.get("draftDeg") or 0
            return 0 if d == 0 else -d

        out.append({"path": "taper", "label": "Taper", "kind": "angle", "get": taper_get, "set": lambda y, v: {**y, "draftDeg": 0 if v == 0 else -v}})
        return out
    if kind == "revolve":
        out = [{"path": "angleDeg", "label": "Angle", "kind": "angle", "get": lambda y: _num(y, "angleDeg"), "set": lambda y, v: {**y, "angleDeg": _rmin(y, abs(v))}}]
        if _pitch_of(f):
            def h_set(y, v):
                return {**y, "angleDeg": _rmin(y, (abs(v) / abs(_pitch_of(y))) * 360)} if _pitch_of(y) else y

            out += [
                _field("pitch", "Pitch", "length"),
                {"path": "turns", "label": "Turns", "kind": "number", "get": lambda y: _num(y, "angleDeg") / 360, "set": lambda y, v: {**y, "angleDeg": _rmin(y, abs(v) * 360)}},
                {"path": "height", "label": "Height", "kind": "length", "get": lambda y: (abs(_pitch_of(y)) * _num(y, "angleDeg")) / 360, "set": h_set},
            ]
        return out
    if kind == "shell":
        return [_field("thickness", "Wall", "length", _positive)]
    if kind == "fillet":
        return [_field("radius", "Radius", "length", _positive)]
    if kind == "chamfer":
        out = [_field("distance", "Distance", "length", _positive)]
        if f.get("mode") == "twoDistances":
            out.append(_field("distance2", "Distance 2", "length", _positive))
        if f.get("mode") == "distanceAngle":
            out.append(_field("angleDeg", "Angle", "angle", lambda v: min(89.9, max(0.1, abs(v)))))
        return out
    if kind == "hole":
        out = [{"path": "diameter", "label": "Diameter", "kind": "length", "get": lambda y: 2 * _num(y, "radius"), "set": lambda y, v: {**y, "radius": abs(v) / 2}}]
        if f.get("depth") is not None:
            out.append(_field("depth", "Depth", "length", _positive))
        return out
    if kind == "thread":
        out = [_field("diameter", "Diameter", "length", _positive), _field("pitch", "Pitch", "length", _positive)]
        runs = (not f["fullLength"]) if "fullLength" in f else f.get("length") is not None
        if runs:
            out += [_field("length", "Length", "length", _positive), _field("start", "Start", "length", _positive)]
        out.append(_field("offset", "Offset", "length"))
        return out
    if kind in ("extract", "thicken"):
        return [_field("thickness", "Thickness", "length", _positive)]
    if kind == "draft":
        return [_field("angleDeg", "Angle", "angle")]
    if kind == "moveFace":
        return [_field("offset", "Offset", "length")]
    if kind == "offsetBody":
        return [_field("distance", "Distance", "length")]
    if kind == "moveBody":
        def axis(key, i):
            def g(y):
                arr = y.get(key)
                return arr[i] if arr is not None and len(arr) > i and arr[i] is not None else 0

            def s(y, v):
                nxt = list(y.get(key) if y.get(key) is not None else [0, 0, 0])
                nxt[i] = v
                return {**y, key: nxt}

            return {"path": f"{key}.{'xyz'[i]}", "label": f"{'Move' if key == 'translate' else 'Turn'} {'XYZ'[i]}", "kind": "length" if key == "translate" else "angle", "get": g, "set": s}

        return [axis("translate", i) for i in range(3)] + [axis("rotate", i) for i in range(3)]
    if kind == "sheet":
        return [_field("from", "From", "length"), _field("to", "To", "length")]
    if kind == "sweep":
        if not f.get("route"):
            return []
        return [{"path": "route.bendRadius", "label": "Bend radius", "kind": "length", "get": lambda y: y["route"]["bendRadius"], "set": lambda y, v: {**y, "route": {**y["route"], "bendRadius": abs(v)}}}]
    if kind == "pattern":
        circ = f.get("mode") == "circular"
        out = [
            _field("count", "Count", "integer", lambda v: max(2, js_round(abs(v)))),
            _field("step", "Over" if circ else "Spacing", "angle" if circ else "length", _positive),
        ]
        if f.get("mode") == "linear" and f.get("axis2"):
            out += [_field("count2", "Count 2", "integer", lambda v: max(1, js_round(abs(v)))), _field("step2", "Spacing 2", "length", _positive)]
        return out
    if kind == "sketch":
        plane = f.get("plane")
        out = []
        if plane and plane_takes_offset(plane):
            out.append({"path": "offset", "label": f"{plane['axis'].upper()} =" if plane["kind"] == "world" else "Offset", "kind": "length", "get": lambda y: plane_offset(y["plane"]), "set": lambda y, v: with_plane_offset(y, v)})
        if f.get("inset"):
            out.append({"path": "inset", "label": "Inset", "kind": "length", "get": lambda y: y["inset"]["by"], "set": lambda y, v: {**y, "inset": {**y["inset"], "by": v}}})
        return out
    if kind in ("cutPlane", "mirror"):
        plane = f.get("plane")
        if not plane or plane["kind"] == "face" or not plane_takes_offset(plane):
            return []
        return [{"path": "plane.offset", "label": "Offset", "kind": "length", "get": lambda y: plane_offset(y["plane"]), "set": lambda y, v: {**y, "plane": plane_at_offset(y["plane"], v)}}]
    if kind == "surface":
        if not f.get("regionBox"):
            return []

        def corner(end, i):
            def s(y, v):
                was = y["regionBox"]
                at = list(was["box"][end])
                at[i] = v
                return {**y, "regionBox": {**was, "box": {**was["box"], end: at}}, "regionStale": True}

            return {"path": f"region.box.{end}.{'xyz'[i]}", "label": f"Box {end} {'XYZ'[i]}", "kind": "length", "get": lambda y: y["regionBox"]["box"][end][i], "set": s}

        return [corner(end, i) for end in ("min", "max") for i in range(3)]
    if kind in ("split", "trim"):
        return [
            _field("tolerance", "Tolerance", "length", _positive),
            {"path": "overlap", "label": "Overlap", "kind": "number", "get": lambda y: _num(y, "overlap") * 100, "set": lambda y, v: {**y, "overlap": min(1, max(0.05, abs(v) / 100))}},
        ]
    return []


def slot_at(x, path, kind=None):
    return next((s for s in slots_of(x, kind) if s["path"] == path), None)


def dimension_kind(kind):
    return "angle" if kind == "angle" else "length"


# ---- writing the expressions through -------------------------------------------------------


def _without_exprs(x):
    return {k: v for k, v in x.items() if k != "exprs"}


def apply_slots(x, scope, kind=None):
    """A feature or a draft with every expression it keeps evaluated and the
    numbers written - the same object back when nothing changes."""
    errors = {}
    if not x.get("exprs"):
        return {"next": x, "errors": errors}
    nxt = x
    exprs = None
    for path, expr in x["exprs"].items():
        slot = slot_at(nxt, path, kind)
        if not slot:
            if exprs is None:
                exprs = dict(x["exprs"])
            exprs.pop(path, None)
            continue
        r = evaluate_for(expr, slot["kind"], scope)
        if not r["ok"]:
            errors[path] = r["error"]
            continue
        if abs(slot["get"](nxt) - r["value"]) > 1e-9:
            nxt = slot["set"](nxt, r["value"])
    if exprs is not None:
        nxt = {**nxt, "exprs": exprs} if exprs else _without_exprs(nxt)
    return {"next": nxt, "errors": errors}


def with_slot(x, path, value, expr, kind=None):
    slot = slot_at(x, path, kind)
    nxt = slot["set"](x, value) if slot else x
    exprs = dict(x.get("exprs") or {})
    if expr:
        exprs[path] = expr
    else:
        exprs.pop(path, None)
    return {**nxt, "exprs": exprs} if exprs else _without_exprs(nxt)


def unlink_slot(x, path):
    if not x.get("exprs") or path not in x["exprs"]:
        return x
    exprs = {k: v for k, v in x["exprs"].items() if k != path}
    return {**x, "exprs": exprs} if exprs else _without_exprs(x)


def apply_sketch_expressions(sketch, frame, scope):
    errors = {}
    values = {}
    for c in sketch["constraints"]:
        if not is_dimension(c) or not c.get("expr"):
            continue
        r = evaluate_for(c["expr"], dimension_kind(c["kind"]), scope)
        if not r["ok"]:
            errors[f"dim:{num_str(c['id'])}"] = r["error"]
            continue
        if abs(c["value"] - r["value"]) > 1e-9:
            values[c["id"]] = r["value"]
    if not values:
        return {"next": sketch, "errors": errors}
    nxt = clone_sketch(sketch)
    nxt["constraints"] = [{**c, "value": values[c["id"]]} if c["id"] in values else c for c in nxt["constraints"]]
    try:
        solve_sketch(nxt, datums=datum_traces(frame))
    except Exception as e:  # noqa: BLE001 - reported as the original does
        errors["sketch"] = str(e)
    return {"next": nxt, "errors": errors}


def _same_keys(a, b):
    return len(a) == len(b) and all(k in b for k in a)


def _has(lst, r):
    return any(x is r for x in lst)


def _rekeyed(f, regions, before):
    pick = f["regionPick"] if f.get("regionPick") and _same_keys(f["regionPick"]["keys"], f["regions"]) else None
    asked = regions_by_pick(pick["given"], regions) if pick else None
    if pick and asked:
        keys = [r["key"] for r in asked]
        if _same_keys(keys, f["regions"]) and f.get("regionsByPlace") is None and all(k == f["regions"][i] for i, k in enumerate(keys)):
            return f
        rest = {k: v for k, v in f.items() if k != "regionsByPlace"}
        return {**rest, "regions": keys, "regionPick": {"given": pick["given"], "keys": keys}}
    taken = []
    by_place = []
    out = []
    for key in f["regions"]:
        r = match_region(key, regions)
        if r is None:
            was = next((x for x in before() if x["key"] == key), None)
            r = region_by_place(was, regions, taken) if was else None
            if r is not None:
                by_place.append(r["key"])
        if r is None or _has(taken, r):
            out.append(key)
            continue
        taken.append(r)
        out.append(r["key"])
    if not taken:
        return f
    for key in f["regions"]:
        was = next((r for r in before() if r["key"] == key), None)
        if not was:
            continue
        for part in split_parts(was, regions):
            if _has(taken, part):
                continue
            taken.append(part)
            out.append(part["key"])
    placed = []
    for k in [k for k in (f.get("regionsByPlace") or []) if k in out] + by_place:
        if k not in placed:
            placed.append(k)
    same = len(out) == len(f["regions"]) and all(k == f["regions"][i] for i, k in enumerate(out))
    if same and len(placed) == len(f.get("regionsByPlace") or []):
        return f
    rest = {k: v for k, v in f.items() if k != "regionsByPlace"}
    nxt = {**rest, "regions": out}
    if placed:
        nxt["regionsByPlace"] = placed
    return nxt


def replace_sketch(features, sid, sketch, patch=None):
    """The feature list with another sketch in the place of the one with
    `sid`; the features on it re-keyed to the regions they name now."""
    regions = find_regions(sketch)
    old = next((f for f in features if f["id"] == sid and f["kind"] == "sketch"), None)
    cache = []

    def before():
        if not cache:
            cache.append(find_regions(old["sketch"]) if old else [])
        return cache[0]

    out = []
    for f in features:
        if f["id"] == sid and f["kind"] == "sketch":
            out.append({**f, **(patch or {}), "sketch": sketch})
        elif f["kind"] in ("extrude", "revolve") and f.get("sketchId") == sid:
            out.append(_rekeyed(f, regions, before))
        else:
            out.append(f)
    return out


def _inset_again(f, features):
    inset = f["inset"]
    of = next((x for x in features if x["id"] == inset["of"] and x["kind"] == "sketch"), None)
    if not of:
        return f"the sketch it was moved in from ({num_str(inset['of'])}) is gone"
    try:
        from .stations import inset_chains  # stations.ts: a later build step
    except ImportError:
        return "moving a profile in again needs stations.ts, which is not ported yet"
    datums = datum_traces(f["frame"])
    moved = inset_chains(of["sketch"], by=inset["by"], keep=lambda: set(inset["keep"]), datums=datums, name=of["name"])
    if isinstance(moved, str):
        return moved
    try:
        solve_sketch(moved["sketch"], datums=datums)
    except Exception as e:  # noqa: BLE001
        return str(e)
    return moved["sketch"]


def apply_parameters(features, scope):
    """Every feature with its expressions evaluated against the parameters.
    Returns {"features", "changed", "errors"}; errors by feature id."""
    errors = {}
    out = list(features)
    changed = False
    for i in range(len(out)):
        f = out[i]
        if f["kind"] == "sketch":
            placed = apply_slots(f, scope) if f.get("exprs") else {"next": f, "errors": {}}
            moved_in = None
            if placed["next"].get("inset") and f.get("inset") and placed["next"]["inset"]["by"] != f["inset"]["by"]:
                again = _inset_again(placed["next"], out)
                if isinstance(again, str):
                    placed["errors"] = {**placed["errors"], "inset": again}
                    placed["next"] = {**placed["next"], "inset": f["inset"]}
                else:
                    moved_in = again
                    placed["next"] = {**placed["next"], "sketch": again}
            if placed["next"] is not f:
                out[i] = placed["next"]
                changed = True
            if moved_in is not None:
                out = replace_sketch(out, f["id"], moved_in)
            g = placed["next"]
            r = apply_sketch_expressions(g["sketch"], g["frame"], scope)
            wrong = {**placed["errors"], **r["errors"]}
            if wrong:
                errors[f["id"]] = wrong
            if r["next"] is not g["sketch"]:
                out = replace_sketch(out, f["id"], r["next"])
                changed = True
        else:
            r = apply_slots(f, scope)
            if r["errors"]:
                errors[f["id"]] = r["errors"]
            if r["next"] is not f:
                out[i] = r["next"]
                changed = True
    return {"features": out if changed else list(features), "changed": changed, "errors": errors}


def feature_expression_errors(f, scope):
    errors = {}
    if f["kind"] == "sketch":
        for path, expr in (f.get("exprs") or {}).items():
            r = evaluate_for(expr, "length", scope)
            if not r["ok"]:
                errors[path] = r["error"]
        for c in f["sketch"]["constraints"]:
            if not is_dimension(c) or not c.get("expr"):
                continue
            r = evaluate_for(c["expr"], dimension_kind(c["kind"]), scope)
            if not r["ok"]:
                errors[f"dim:{num_str(c['id'])}"] = r["error"]
        return errors
    for path, expr in (f.get("exprs") or {}).items():
        slot = slot_at(f, path)
        if not slot:
            continue
        r = evaluate_for(expr, slot["kind"], scope)
        if not r["ok"]:
            errors[path] = r["error"]
    return errors


# ---- who reads a parameter ---------------------------------------------------------------------


def feature_reads(f, name):
    if f.get("exprs") and any(name in references(e) for e in f["exprs"].values()):
        return True
    if f.get("sketch"):
        return any(is_dimension(c) and c.get("expr") and name in references(c["expr"]) for c in f["sketch"]["constraints"])
    return False


def users_of(name, parameters, features):
    out = [{"kind": "parameter", "id": p["id"], "name": p["name"]} for p in parameters if p["name"] != name and name in references(p["expression"])]
    out += [{"kind": "feature", "id": f["id"], "name": f["name"]} for f in features if feature_reads(f, name)]
    return out


def driven_by(name, parameters, features):
    names = [name]
    grew = True
    while grew:
        grew = False
        for p in parameters:
            if p["name"] in names or not any(n in names for n in references(p["expression"])):
                continue
            names.append(p["name"])
            grew = True
    out = []
    for f in features:
        if any(feature_reads(f, n) for n in names) and f["id"] not in out:
            out.append(f["id"])
    for f in features:
        if f["kind"] == "sketch" and f["id"] in out:
            for d in dependents_of(f["id"], features):
                if d["id"] not in out:
                    out.append(d["id"])
    return out


def fields_reading(f, name):
    slots = [path for path, e in (f.get("exprs") or {}).items() if name in references(e)]
    dims = [f"dimension {num_str(c['id'])}" for c in ((f.get("sketch") or {}).get("constraints") or []) if is_dimension(c) and c.get("expr") and name in references(c["expr"])]
    return slots + dims


def idle_parameters(parameters, features):
    driving = [p["name"] for p in parameters if any(feature_reads(f, p["name"]) for f in features)]
    grew = True
    while grew:
        grew = False
        for p in parameters:
            if p["name"] not in driving:
                continue
            for n in references(p["expression"]):
                if n in driving or not any(q["name"] == n for q in parameters):
                    continue
                driving.append(n)
                grew = True
    return [p for p in parameters if p["name"] not in driving]


def rename_in_sketch(sketch, frm, to):
    if not any(is_dimension(c) and c.get("expr") and frm in references(c["expr"]) for c in sketch["constraints"]):
        return sketch
    return {**sketch, "constraints": [{**c, "expr": rename_in(c["expr"], frm, to)} if is_dimension(c) and c.get("expr") else c for c in sketch["constraints"]]}


def rename_in_feature(f, frm, to):
    if not feature_reads(f, frm):
        return f
    nxt = f
    if f.get("exprs"):
        nxt = {**nxt, "exprs": {k: rename_in(e, frm, to) for k, e in f["exprs"].items()}}
    if f.get("sketch"):
        nxt = {**nxt, "sketch": rename_in_sketch(f["sketch"], frm, to)}
    return nxt


def rename_in_parameters(parameters, pid, to):
    frm = next((p["name"] for p in parameters if p["id"] == pid), None)
    if frm is None or frm == to:
        return list(parameters)
    return [{**p, "name": to} if p["id"] == pid else ({**p, "expression": rename_in(p["expression"], frm, to)} if frm in references(p["expression"]) else p) for p in parameters]
