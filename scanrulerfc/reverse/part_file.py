# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/app/projectSection.ts
# SPDX-License-Identifier: AGPL-3.0-only
#
# The Reverse engineer workspace's part of a project file, under the key
# `reverse`: the feature list by reference - the sketches with their
# pieces and relations, every pick as a fingerprint, every plane and axis
# by the id of the section or element it names - and the counters the
# names run on. No kernel data: the bodies are rebuilt on load. The STEP
# files the Imports brought in go beside it in the archive, all in one
# member, reverse-steps.json.
#
# The records are the original's JSON byte for byte: read a part and
# write it back, and the text is the same (`dumps` writes as
# JSON.stringify does). The original's store is a dict here with the same
# keys (features, rolledBack, nextFeatureId, ...).

import math
import os
import zipfile
from array import array

from ._js import UNDEFINED, is_finite_number, is_number, parse, safe_integer, stringify
from .features import full_turn
from .parameters import evaluate_parameters

PART_VERSION = 3
STEP_MEMBER = "reverse-steps.json"
PROJECT_MEMBER = "project.json"
KEY = "reverse"


class MalformedProject(ValueError):
    pass


def invalid(path):
    raise MalformedProject(f"Malformed project: {path}.")


# ---- src/core/project/validation.ts ------------------------------------------------------


def _object(value, path):
    if not isinstance(value, dict):
        invalid(path)
    return value


def _array(value, path):
    if not isinstance(value, list):
        invalid(path)
    return value


def _is_type(v, t):
    if t == "number":
        return is_finite_number(v)
    if t == "string":
        return isinstance(v, str)
    return isinstance(v, bool)


def _fields(value, names, t, path):
    for name in names.split(" "):
        if not _is_type(value.get(name, UNDEFINED), t):
            invalid(f"{path}.{name}")


def _indices(value, path):
    for i in _array(value, path):
        if not safe_integer(i) or i < 0:
            invalid(path)


def _vector(value, size, path):
    values = _array(value, path)
    if len(values) != size or not all(is_finite_number(v) for v in values):
        invalid(path)


def _entries(value, path, visit=None):
    ids = set()
    for item in _array(value, path):
        entry = _object(item, path)
        i = entry.get("id")
        if not safe_integer(i) or i < 0 or i in ids:
            invalid(f"{path} IDs")
        ids.add(i)
        if visit:
            visit(entry)


# ---- records ---------------------------------------------------------------------------------


def feature_to_json(f):
    if f["kind"] == "surface":
        return {**f, "region": [int(v) for v in f["region"]]}
    return f


def feature_from_json(f):
    if f["kind"] == "surface":
        return {**f, "region": array("I", (int(v) % 2 ** 32 for v in f["region"]))}
    if f["kind"] == "moveFace" and "face" in f:
        rest = {k: v for k, v in f.items() if k != "face"}
        return {**rest, "faces": [f["face"]]}
    return f


def validate_feature_json(e):
    _fields(e, "kind name", "string", "feature")
    kind = e["kind"]
    if kind == "sketch":
        sketch = _object(e.get("sketch"), "feature.sketch")
        _entries(sketch.get("entities"), "sketch.entities")
        _entries(sketch.get("constraints"), "sketch.constraints")
        _object(e.get("plane"), "sketch.plane")
        _object(e.get("frame"), "sketch.frame")
    if kind == "surface":
        _indices(e.get("region"), "surface.region")
    for key in ("edgesWhere", "facesWhere"):
        if key in e:
            for item in _array(e[key], f"{kind}.{key}"):
                q = _object(item, key)
                _object(q.get("where"), f"{key}.where")
                _array(q.get("found"), f"{key}.found")
    if "regionPick" in e:
        pick = _object(e["regionPick"], f"{kind}.regionPick")
        if pick.get("given") not in ("all", "largest"):
            _array(pick.get("given"), "regionPick.given")
        _array(pick.get("keys"), "regionPick.keys")
    if kind == "sweep" and "route" in e:
        route = _object(e["route"], "sweep.route")
        for p in _array(route.get("points"), "sweep.route.points"):
            _vector(p, 3, "sweep.route.points")
        _fields(route, "bendRadius", "number", "sweep.route")
    if kind == "import":
        file = _object(e.get("file"), "import.file")
        _fields(file, "key name", "string", "import.file")
        _fields(file, "size", "number", "import.file")
    if kind == "moveBody":
        for n in _array(e.get("bodies"), "moveBody.bodies"):
            if not is_finite_number(n):
                invalid("moveBody.bodies")
        for k in ("pivot", "translate", "rotate"):
            _vector(e.get(k), 3, f"moveBody.{k}")
        _fields(e, "copy", "boolean", "moveBody")
    if kind == "network":
        def node(n):
            _fields(n, "id", "number", "network.node")
            _vector(n.get("at"), 3, "network.node.at")

        def curve(c):
            _fields(c, "id from to", "number", "network.curve")
            for p in _array(c.get("via"), "network.curve.via"):
                _vector(p, 3, "network.curve.via")

        _entries(e.get("nodes"), "network.nodes", node)
        _entries(e.get("curves"), "network.curves", curve)
        for item in _array(e.get("cells"), "network.cells"):
            c = _object(item, "network.cell")
            _vector(c.get("seed"), 3, "network.cell.seed")
            if "centre" in c:
                _vector(c["centre"], 3, "network.cell.centre")
            if "corners" in c:
                _indices(c["corners"], "network.cell.corners")
        _object(e.get("spans"), "network.spans")
        fit = _object(e.get("fit"), "network.fit")
        _fields(fit, "smoothness", "number", "network.fit")
        if "tolerance" in fit:
            _fields(fit, "tolerance", "number", "network.fit")


def _folder_path(folders, fid):
    path = []
    seen = set()
    at = next((f for f in folders if f["id"] == fid), None) if fid is not None else None
    while at is not None and at["id"] not in seen:
        seen.add(at["id"])
        path.insert(0, at)
        parent = at["parent"]
        at = None if parent is None else next((f for f in folders if f["id"] == parent), None)
    return path


def validate_folders(raw):
    """validateFolders of core/bodyFolders.ts."""
    if not isinstance(raw, list):
        raise ValueError("reverse.bodyFolders")
    ids = set()
    for f in raw:
        if not isinstance(f, dict):
            raise ValueError("reverse.bodyFolders")
        if not safe_integer(f.get("id")) or not isinstance(f.get("name"), str) or not (f.get("parent", UNDEFINED) is None or safe_integer(f.get("parent"))):
            raise ValueError("reverse.bodyFolders")
        if not isinstance(f.get("bodies"), list) or not all(is_finite_number(b) for b in f["bodies"]):
            raise ValueError("reverse.bodyFolders")
        if f["id"] in ids:
            raise ValueError("reverse.bodyFolders")
        ids.add(f["id"])
    for f in raw:
        if f["parent"] is not None:
            path = _folder_path(raw, f["id"])
            if f["parent"] not in ids or not path or path[0]["parent"] is not None:
                raise ValueError("reverse.bodyFolders")
    return raw


def validate_reverse_part(raw):
    """The part as read from a file, checked before anything changes."""
    if not isinstance(raw, dict) or not isinstance(raw.get("features"), list):
        raise MalformedProject("Malformed project: reverse engineer entry.")
    r = raw
    _fields(r, "nextFeatureId", "number", "reverse")
    if "version" in r and not is_finite_number(r["version"]):
        invalid("reverse.version")
    for n in _object(r.get("nextOfKind"), "reverse.nextOfKind").values():
        if not safe_integer(n):
            invalid("reverse.nextOfKind")
    _entries(r["features"], "reverse.features", validate_feature_json)
    if "rolledTo" in r and (not safe_integer(r["rolledTo"]) or r["rolledTo"] < 0 or r["rolledTo"] > len(r["features"])):
        invalid("reverse.rolledTo")
    if "parameters" in r:
        names = set()

        def check(p):
            _fields(p, "id", "number", "parameter")
            _fields(p, "name kind expression", "string", "parameter")
            if p["kind"] not in ("length", "angle", "integer", "number"):
                invalid("parameter.kind")
            if p["name"] in names:
                invalid("parameter.name")
            if "pinned" in p and not isinstance(p["pinned"], bool):
                invalid("parameter.pinned")
            names.add(p["name"])

        _entries(r["parameters"], "reverse.parameters", check)
        if "nextParameterId" in r:
            _fields(r, "nextParameterId", "number", "reverse")
    if "stepFiles" in r and not isinstance(r["stepFiles"], str):
        invalid("reverse.stepFiles")
    if "hiddenBodies" in r:
        for n in _array(r["hiddenBodies"], "reverse.hiddenBodies"):
            if not is_finite_number(n):
                invalid("reverse.hiddenBodies")
    for k in ("scanSeeThrough", "bodiesSeeThrough", "bodyOpaque", "overlapsShown"):
        if k in r and not isinstance(r[k], bool):
            invalid(f"reverse.{k}")
    if "bodyStyles" in r:
        for key, style in _object(r["bodyStyles"], "reverse.bodyStyles").items():
            if not math.isfinite(_number_of(key)):
                invalid("reverse.bodyStyles")
            st = _object(style, "reverse.bodyStyles")
            if ("name" in st and not isinstance(st["name"], str)) or ("color" in st and not isinstance(st["color"], str)):
                invalid("reverse.bodyStyles")
    if "bodyFolders" in r:
        try:
            validate_folders(r["bodyFolders"])
        except (ValueError, KeyError, TypeError):
            invalid("reverse.bodyFolders")
    return raw


def _number_of(key):
    t = key.strip()
    if t == "":
        return 0.0
    try:
        return float(t) if t.lower().lstrip("+-") not in ("inf", "infinity", "nan") else math.nan
    except ValueError:
        return math.nan


# ---- migrations ----------------------------------------------------------------------------


def migrate_feature(f, version):
    """v2: a circular pattern's step is its span first to last, not its
    pitch times the count."""
    if version >= 2 or f["kind"] != "pattern" or f["mode"] != "circular" or full_turn(f["step"]) or not (f["count"] >= 2):
        return f
    n = math.floor(f["count"] + 0.5)
    step = (f["step"] * (n - 1)) / n
    expr = (f.get("exprs") or {}).get("step")
    if expr is None:
        return {**f, "step": step}
    from ._js import num_str
    count = f["exprs"]["count"] if f["exprs"].get("count") is not None else num_str(n)
    return {**f, "step": step, "exprs": {**f["exprs"], "step": f"({expr}) * (({count}) - 1) / ({count})"}}


_BODY_KEYS = ("body", "tool", "target")


def _rename_body(value, frm, to):
    if isinstance(value, list):
        return [_rename_body(v, frm, to) for v in value]
    if not isinstance(value, dict):
        return value
    out = {}
    for k, v in value.items():
        if k == "sketch":
            out[k] = v
        elif k in _BODY_KEYS and is_number(v) and v == frm:
            out[k] = to
        elif k in ("bodies", "tool") and isinstance(v, list):
            out[k] = [to if (is_number(b) and b == frm) else b for b in v]
        else:
            out[k] = _rename_body(v, frm, to)
    return out


def migrate_features(features, version):
    """v2 as above; v3: a mirror not joined made its copy under the mirror's
    own id, so what came after it naming the source meant the copy."""
    out = [migrate_feature(f, version) for f in features]
    if version >= 3:
        return out
    for i in range(len(out)):
        m = out[i]
        if m["kind"] != "mirror" or m.get("join"):
            continue
        out = out[:i + 1] + [_rename_body(f, m["body"], m["id"]) for f in out[i + 1:]]
    return out


def next_id_past(given, taken):
    past = 1
    for i in taken:
        if is_number(i) and math.isfinite(i):
            past = max(past, math.floor(i) + 1)
    return given if given is not None and safe_integer(given) and given > past else past


# ---- the store's state, in and out -------------------------------------------------------------


def _imported_keys(features):
    out = []
    for f in features:
        if f["kind"] == "import" and f["file"]["key"] not in out:
            out.append(f["file"]["key"])
    return out


def empty_state():
    """The store's persisted part as reset() leaves it."""
    return {"features": [], "rolledBack": [], "nextFeatureId": 1, "nextOfKind": {}, "parameters": [], "nextParameterId": 1, "bodyStyles": {}, "hiddenBodies": [], "bodyFolders": [], "scanSeeThrough": None, "bodiesSeeThrough": False, "overlapsShown": True, "elementsShown": True, "stepFiles": {}}


def collect_reverse_part(state, add_member=None):
    """The part a project saves (collectReversePart), or None with no
    feature. `add_member(name, bytes)` takes the STEP texts' member."""
    all_ = list(state["features"]) + list(state.get("rolledBack") or [])
    if not all_:
        return None
    keys = _imported_keys(all_)
    files = state.get("stepFiles") or {}
    texts = {k: files[k] for k in keys if k in files}
    steps = add_member is not None and len(texts) > 0
    if steps:
        add_member(STEP_MEMBER, stringify(texts).encode("utf-8"))
    playback = state.get("playback")
    rolled_to = playback["origin"] if playback and playback.get("origin") is not None else len(state["features"])
    hidden = state.get("hiddenBodies") or []
    part = {"version": PART_VERSION, "features": [feature_to_json(f) for f in all_]}
    if rolled_to < len(all_):
        part["rolledTo"] = rolled_to
    part["nextFeatureId"] = state["nextFeatureId"]
    part["nextOfKind"] = state["nextOfKind"]
    if state.get("parameters"):
        part["parameters"] = state["parameters"]
        part["nextParameterId"] = state["nextParameterId"]
    if state.get("bodyStyles"):
        part["bodyStyles"] = state["bodyStyles"]
    if hidden:
        part["hiddenBodies"] = hidden
    if state.get("bodyFolders"):
        part["bodyFolders"] = state["bodyFolders"]
    if state.get("scanSeeThrough") is not None:
        part["scanSeeThrough"] = state["scanSeeThrough"]
    part["bodiesSeeThrough"] = state.get("bodiesSeeThrough", False)
    if state.get("overlapsShown") is False:
        part["overlapsShown"] = False
    part["elementsShown"] = state["elementsShown"]
    if steps:
        part["stepFiles"] = STEP_MEMBER
    return part


def _step_files_of(p, members):
    name = p.get("stepFiles") if p else None
    data = members.get(name) if (name is not None and members) else None
    if not data:
        return {}
    try:
        parsed = parse(data.decode("utf-8") if isinstance(data, (bytes, bytearray)) else data)
    except (ValueError, UnicodeDecodeError):
        invalid("reverse.stepFiles")
    files = _object(parsed, "reverse.stepFiles")
    for text in files.values():
        if not isinstance(text, str):
            invalid("reverse.stepFiles")
    return files


def _see_through_of(p):
    if "bodiesSeeThrough" in p or "scanSeeThrough" in p:
        return {"scanSeeThrough": p.get("scanSeeThrough"), "bodiesSeeThrough": p.get("bodiesSeeThrough", False)}
    if p.get("bodyOpaque") is False:
        return {"scanSeeThrough": False, "bodiesSeeThrough": True}
    return {"scanSeeThrough": None, "bodiesSeeThrough": False}


def reverse_part_state(p, members=None):
    """The store's state a part opens as (reversePartState): migrated,
    split at the rollback bar, counters past every id. None for no part.
    `members` maps archive member names to their bytes."""
    if p is None:
        return None
    version = p.get("version") if p.get("version") is not None else 1
    all_ = migrate_features([feature_from_json(f) for f in p["features"]], version)
    at = len(all_) if p.get("rolledTo") is None else min(len(all_), max(0, p["rolledTo"]))
    parameters = p.get("parameters") or []
    styles = {}
    for k, st in (p.get("bodyStyles") or {}).items():
        from ._js import num_str
        styles[num_str(_number_of(k))] = st
    return {
        "features": all_[:at],
        "rolledBack": all_[at:],
        "nextFeatureId": next_id_past(p.get("nextFeatureId"), [f["id"] for f in all_]),
        "nextOfKind": p["nextOfKind"],
        "parameters": parameters,
        "nextParameterId": next_id_past(p.get("nextParameterId"), [q["id"] for q in parameters]),
        "parameterTable": evaluate_parameters(parameters),
        "bodyStyles": styles,
        "hiddenBodies": p.get("hiddenBodies") or [],
        "bodyFolders": p.get("bodyFolders") or [],
        **_see_through_of(p),
        "overlapsShown": p["overlapsShown"] if p.get("overlapsShown") is not None else True,
        "elementsShown": p.get("elementsShown"),
        "stepFiles": _step_files_of(p, members),
    }


def prepare(value, members=None):
    """reverseSection.prepare: validate, then the state to put in place."""
    part = None if value is None else validate_reverse_part(value)
    return reverse_part_state(part, members)


# ---- text and archives ----------------------------------------------------------------------------


def dumps(value):
    """The part (or anything of it) as the original writes it."""
    return stringify(value)


def loads(text):
    """JSON text read as the original reads it."""
    return parse(text)


def read_scanruler(path):
    """The Reverse engineer part of a .scanruler archive: (part, members),
    the part validated, members holding the STEP texts' member if any."""
    from .. import guard

    # Each read capped (red team 3, R3-6): a project from the web.
    with zipfile.ZipFile(path) as z:
        guard.zip_check(z, os.path.basename(path))
        manifest = parse(guard.zip_read(z, PROJECT_MEMBER, "project.json", 64 * 1024 * 1024).decode("utf-8"))
        part = manifest.get(KEY) if isinstance(manifest, dict) else None
        members = {}
        if isinstance(part, dict) and isinstance(part.get("stepFiles"), str) and part["stepFiles"] in z.namelist():
            members[part["stepFiles"]] = guard.zip_read(z, part["stepFiles"], "the project's STEP texts", 256 * 1024 * 1024)
    part = None if part is None else validate_reverse_part(part)
    # Feature names are text from the file that the agent reads: cleaned
    # (red team 3, R3-11).
    for f in (part or {}).get("features") or []:
        if isinstance(f, dict) and isinstance(f.get("name"), str):
            f["name"] = guard.text(f["name"], 120)
    return part, members


def write_members(state):
    """The part and its members as a save writes them: (part, {name: bytes})."""
    members = {}
    part = collect_reverse_part(state, lambda name, data: members.__setitem__(name, data))
    return part, members
