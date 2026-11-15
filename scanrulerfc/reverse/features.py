# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/core/features.ts (with state/reDrafts.ts, reFeatureSlice.ts, reSolidSlice.ts, reFeatureHelpers.ts)
# SPDX-License-Identifier: AGPL-3.0-only
#
# The feature list: one linear list of plain JSON records, as the original
# keeps them - every record has id, kind, name, visible, an optional
# suppressed and an optional exprs - and what is read off it without a
# kernel: what a feature builds on, what a move would break, the names and
# ids the counters hand out. Then the editor's side: the starting draft of
# each kind (its defaults), the Create key's test (ready), and the feature
# a ready draft makes.

import math
import re

from ._js import fmod, js_round, num_str
from .datums import DATUM_PLANES
from .regions import find_regions

ISLAND_IDS = 1024
FACE_SLICE_INSET_MM = 0.25
FULL_TURN_DEG = 360
MIN_SWEEP_RAD = (1 * math.pi) / 180
MAX_COIL_DEG = 360 * 1000
SURFACE_MIN_REGION = 16

DEFAULT_SPLIT_TOLERANCE_MM = 0.3
DEFAULT_SPLIT_OVERLAP = 0.5
DEFAULT_WALL_MM = 2
DEFAULT_DRAFT_DEG = 2
DEFAULT_FILLET_MM = 1
DEFAULT_FLOOD_DEG = 1
DEFAULT_SURFACE_FIT = {"net": None, "degree": 3, "expandPct": 35, "smoothness": 0.01}
DEFAULT_NETWORK_FIT = {"smoothness": 0.001}

KIND_LABELS = {
    "sketch": "Sketch", "extrude": "Extrude", "revolve": "Revolve", "coil": "Coil", "shell": "Shell", "fillet": "Fillet",
    "chamfer": "Chamfer", "hole": "Hole", "thread": "Thread", "extract": "Extract", "cutPlane": "Cut", "mirror": "Mirror",
    "boolean": "Combine", "sheet": "Sheet", "split": "Split", "loft": "Loft", "sweep": "Sweep", "thicken": "Thicken",
    "pattern": "Pattern", "offsetBody": "Offset", "import": "Import", "moveBody": "Move", "draft": "Draft",
    "moveFace": "Move face", "deleteFace": "Delete face", "surface": "Surface", "network": "Patch network", "trim": "Trim",
}


# ---- ids and names ------------------------------------------------------------------


def next_feature_id(state):
    """The id the next feature takes, and the counter past it."""
    i = state["nextFeatureId"]
    return i, i + 1


def name_for(next_of_kind, kind):
    """What a feature is called, by its kind ("Extrude 3"), and the counters after it."""
    n = (next_of_kind.get(kind) or 0) + 1
    return f"{KIND_LABELS[kind]} {n}", {**next_of_kind, kind: n}


def island_id(step_id, n):
    return step_id + n / ISLAND_IDS


def body_maker(body_id):
    return math.floor(body_id)


def island_of(body_id):
    return int(js_round((body_id - math.floor(body_id)) * ISLAND_IDS))


def full_turn(step_deg):
    return abs(abs(step_deg) - 360) < 1e-9


def pattern_pitch(step_deg, count):
    n = max(1, js_round(count))
    return step_deg / (n if full_turn(step_deg) else n - 1) if n > 1 else 0


def revolve_max_deg(pitch):
    return MAX_COIL_DEG if pitch else FULL_TURN_DEG


def extent_ends_on_part(e):
    return e["kind"] in ("toPlane", "toFace", "toBody", "toNext", "toLast")


def with_kept_queries(old, new):
    """An edited feature keeps the stored queries its picks were given by."""
    if old["kind"] != new["kind"]:
        return new
    if (not old.get("edgesWhere") or new.get("edgesWhere")) and (not old.get("facesWhere") or new.get("facesWhere")):
        return new
    out = dict(new)
    if old.get("edgesWhere") and not new.get("edgesWhere"):
        out["edgesWhere"] = old["edgesWhere"]
    if old.get("facesWhere") and not new.get("facesWhere"):
        out["facesWhere"] = old["facesWhere"]
    return out


# ---- planes ---------------------------------------------------------------------------


def _add_scaled(a, d, s):
    return [a[0] + d[0] * s, a[1] + d[1] * s, a[2] + d[2] * s]


def plane_takes_offset(ref):
    return ref["kind"] != "fitted"


def plane_offset(ref):
    return 0 if ref["kind"] == "fitted" else (ref.get("offset") if ref.get("offset") is not None else 0)


def plane_at_offset(ref, offset):
    if not plane_takes_offset(ref) or not math.isfinite(offset):
        return ref
    if ref["kind"] != "bodyFace":
        return {**ref, "offset": offset}
    delta = offset - plane_offset(ref)
    return {**ref, "offset": offset, "frame": {**ref["frame"], "origin": _add_scaled(ref["frame"]["origin"], ref["frame"]["normal"], delta)}}


def with_plane_offset(x, offset):
    if not plane_takes_offset(x["plane"]) or not math.isfinite(offset):
        return x
    delta = offset - plane_offset(x["plane"])
    if abs(delta) < 1e-12:
        return x

    def shift(f):
        return {**f, "origin": _add_scaled(f["origin"], f["normal"], delta)}

    plane = {**x["plane"], "offset": offset, "frame": shift(x["plane"]["frame"])} if x["plane"]["kind"] == "bodyFace" else {**x["plane"], "offset": offset}
    return {**x, "plane": plane, "frame": shift(x["frame"])}


def frame_on_face(face):
    """The frame a sketch on a body's planar face lies in, or None."""
    if face["kind"] != "plane":
        return None
    from ..section_core import sketch_frame_on
    f = sketch_frame_on(face["centroid"], face["dir"])
    return f and {k: [float(v) for v in f[k]] for k in ("origin", "normal", "basisU", "basisV")}


def movable_face(face):
    return face["kind"] in ("plane", "cylinder")


def partial_round(face):
    return face.get("fullTurn") is False


def body_face_plane(body, face):
    frame = frame_on_face(face)
    return frame and {"kind": "bodyFace", "body": body, "face": face, "frame": frame}


# ---- files -----------------------------------------------------------------------------


def _imul(a, b):
    return ((a & 0xFFFFFFFF) * (b & 0xFFFFFFFF)) & 0xFFFFFFFF


def _base36(n):
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    if n == 0:
        return "0"
    out = ""
    while n:
        n, r = divmod(n, 36)
        out = digits[r] + out
    return out


def step_file_key(text):
    """The key a STEP file's text is kept under: its length and a 53-bit
    digest of it (cyrb53), both in base 36."""
    h1 = 0xDEADBEEF
    h2 = 0x41C6CE57
    units = text.encode("utf-16-le")
    n = len(units) // 2
    for i in range(n):
        c = units[2 * i] | (units[2 * i + 1] << 8)
        h1 = _imul(h1 ^ c, 2654435761)
        h2 = _imul(h2 ^ c, 1597334677)
    h1 = _imul(h1 ^ (h1 >> 16), 2246822507) ^ _imul(h2 ^ (h2 >> 13), 3266489909)
    h2 = _imul(h2 ^ (h2 >> 16), 2246822507) ^ _imul(h1 ^ (h1 >> 13), 3266489909)
    digest = 4294967296 * (2097151 & h2) + (h1 & 0xFFFFFFFF)
    return f"{_base36(n)}-{_base36(digest)}"


def tools_of(f):
    t = f["tool"]
    return [t] if not isinstance(t, list) else list(t)


def constrain_refs(elements):
    """What a fitted plane or cylinder can be held to: the coordinate planes
    and the measured planes, cylinders and cones."""
    refs = [{"key": f"datum:{p['plane']}", "kind": "plane", "name": p["name"], "origin": [0, 0, 0], "normal": p["normal"]} for p in DATUM_PLANES]
    for e in elements:
        fit = e.get("fit")
        if not fit:
            continue
        name = e.get("name") if e.get("name") is not None else f"Element {num_str(e['id'])}"
        if fit["kind"] == "plane":
            refs.append({"key": f"element:{num_str(e['id'])}", "kind": "plane", "name": name, "origin": fit["center"], "normal": fit["normal"]})
        elif fit["kind"] in ("cylinder", "cone"):
            refs.append({"key": f"element:{num_str(e['id'])}", "kind": "axis", "name": name, "origin": fit["center"], "dir": fit["axis"]})
    return refs


# ---- what builds on what ------------------------------------------------------------------


def references_of(f):
    """The ids of the features this one builds on."""
    k = f["kind"]
    if k == "sketch":
        refs = [f["plane"]["body"]] if f["plane"]["kind"] == "bodyFace" else []
        for e in f["sketch"]["entities"]:
            src = e.get("source")
            frm = (src["body"] if "body" in src else src["sketch"]) if e.get("projected") and src else None
            if frm is not None and frm != f["id"] and frm not in refs:
                refs.append(frm)
        return refs
    if k == "extrude":
        refs = [f["face"]["body"]] if f.get("face") else [f["sketchId"]]
        if f.get("target") is not None and f["target"] not in refs:
            refs.append(f["target"])
        if f["extent"]["kind"] in ("toFace", "toBody") and f["extent"]["body"] not in refs:
            return refs + [f["extent"]["body"]]
        return refs
    if k == "revolve":
        return [f["sketchId"]] if f.get("target") is None else [f["sketchId"], f["target"]]
    if k == "extract":
        return [] if f.get("target") is None else [f["target"]]
    if k == "boolean":
        return [f["body"]] + tools_of(f)
    if k == "sheet":
        return [f["sketchId"]]
    if k == "surface":
        con = f.get("constrain")
        held = re.fullmatch(r"surface:(\d+)", con["ref"]) if con and con.get("mode") == "force" else None
        return [int(held.group(1))] if held else []
    if k == "network":
        refs = []

        def add(i):
            if i not in refs:
                refs.append(i)

        for nd in f["nodes"]:
            if nd.get("on"):
                add(nd["on"]["body"])
        for c in f["curves"]:
            if c.get("along"):
                add(c["along"]["body"])
            if c.get("side"):
                add(c["side"]["body"])
        return refs
    if k == "trim":
        return [t["id"] for t in f["tools"] if t["kind"] == "body"]
    if k == "split":
        return [f["body"]] + list(f["tools"])
    if k == "loft":
        return list(f["sketches"]) if f.get("target") is None else list(f["sketches"]) + [f["target"]]
    if k == "sweep":
        return [f["profile"]] + ([] if f.get("path") is None else [f["path"]]) + ([] if f.get("target") is None else [f["target"]])
    if k == "thicken":
        return [f["sheet"]] if f.get("target") is None else [f["sheet"], f["target"]]
    if k == "import":
        return []
    if k == "moveBody":
        return list(f["bodies"])
    return [f["body"]]


def dependents_of(i, features):
    return [f for f in features if any(body_maker(r) == i for r in references_of(f))]


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def built_on(f):
    ids = []

    def add(i):
        if i not in ids:
            ids.append(i)

    for r in references_of(f):
        add(body_maker(r))

    def walk(v, key=None):
        if v is None or not isinstance(v, (dict, list)):
            if key == "madeBy" and _is_num(v):
                add(body_maker(v))
            return
        if isinstance(v, list):
            for x in v:
                walk(x, key)
            return
        if _is_num(v.get("origin")) and ("centroid" in v or "mid" in v):
            add(body_maker(v["origin"]))
        if v.get("kind") == "bodyFace" and _is_num(v.get("body")):
            add(body_maker(v["body"]))
        for kk, x in v.items():
            if kk != "sketch" or f["kind"] != "sketch":
                walk(x, kk)

    walk(f)
    return [i for i in ids if i != f["id"]]


def moved_list(features, ids, after):
    """The list with the features `ids` moved to just after `after` (None:
    to the top), or why not, as the original says it."""
    moving = [f for f in features if f["id"] in ids]
    if after is not None and after in ids:
        return "after names a feature that is moved — name one that stays."
    rest = [f for f in features if f["id"] not in ids]
    at = 0 if after is None else next((i for i, f in enumerate(rest) if f["id"] == after), -1) + 1
    order = rest[:at] + moving + rest[at:]
    place = {f["id"]: i for i, f in enumerate(order)}
    for f in order:
        for used in built_on(f):
            if used not in place:
                continue
            u = order[place[used]]
            if place[used] < place[f["id"]] or not (f["id"] in ids or used in ids):
                continue
            if f["id"] in ids:
                return f"{f['name']} builds on {u['name']}, which would then come after it — move {u['name']} with it, or put {f['name']} lower."
            return f"{f['name']} builds on {u['name']}, which the move puts after it — move {f['name']} with it, or put {u['name']} higher."
    return order


# ---- threads (core/thread.ts, the part the Create key needs) ---------------------------------

_V60 = {"sec": 2 / math.sqrt(3), "depth": (5 / 8) * (math.sqrt(3) / 2)}
_PRINT45 = {"sec": math.sqrt(2), "depth": 0.3}
_FORMS = {"metric": _V60, "unc": _V60, "unf": _V60, "print45": _PRINT45}


def thread_depth(pitch, standard):
    return _FORMS[standard]["depth"] * pitch


def max_thread_offset(pitch, standard):
    return pitch / (4 * _FORMS[standard]["sec"])


def _length_words(v, units="mm"):
    k = 10 ** (max(3, 4) if units == "in" else 3)
    shown = v / 25.4 if units == "in" else v
    return f"{num_str(js_round(shown * k) / k)} {units}"


def thread_problem(t, units="mm"):
    mm = lambda v: _length_words(v, units)  # noqa: E731
    if not (t["diameter"] > 0):
        return "The thread needs a diameter."
    if not (t["pitch"] > 0):
        return "The thread needs a pitch."
    if not (t["offset"] >= 0):
        return "The offset only takes material away — it has to be zero or more."
    mx = max_thread_offset(t["pitch"], t["standard"])
    if t["offset"] >= mx:
        return f"An offset of {mm(t['offset'])} leaves the tooth no thickness at the pitch diameter — under {mm(mx)} for a pitch of {mm(t['pitch'])}."
    if t["diameter"] / 2 - thread_depth(t["pitch"], t["standard"]) - t["offset"] < t["pitch"] / 4:
        return f"A pitch of {mm(t['pitch'])} is too coarse for Ø{mm(t['diameter'])} — the thread would reach the axis."
    return None


# ---- drafts: the editor's starting values -----------------------------------------------------


def last_solid(bodies):
    for b in reversed(bodies):
        if not b.get("surface"):
            return b["id"]
    return None


def auto_regions(sketch):
    if not sketch:
        return []
    found = find_regions(sketch)
    return [found[0]["key"]] if len(found) == 1 else []


def pivot_of(boxes):
    if not boxes:
        return [0, 0, 0]
    lo = [min(b["min"][i] for b in boxes) for i in range(3)]
    hi = [max(b["max"][i] for b in boxes) for i in range(3)]
    return [js_round((lo[i] + hi[i]) / 2 * 1000) / 1000 for i in range(3)]


def move_pivot(bodies, ids):
    boxes = []
    for i in ids:
        b = next((x for x in bodies if x["id"] == i), None)
        if b and b.get("box"):
            boxes.append(b["box"])
    return pivot_of(boxes)


def trim_tolerance_for(tools, results):
    sig = []
    for t in tools:
        s = ((results.get(t["id"]) or {}).get("surface") or {}).get("rms") if t["kind"] == "body" else None
        if s is not None and math.isfinite(s) and s > 0:
            sig.append(s)
    sig.sort()
    if not sig:
        return DEFAULT_SPLIT_TOLERANCE_MM
    return js_round(min(0.5, max(0.05, 3 * sig[len(sig) >> 1])) * 1000) / 1000


def _sketches(features):
    return [f for f in features if f["kind"] == "sketch"]


def start_extrude(features, sketch_id=None, regions=None):
    """The Extrude box as it opens: the sketch asked for or the last one,
    its one region, 0 to 10 mm, no taper, join."""
    sks = _sketches(features)
    sk = next((f for f in sks if f["id"] == sketch_id), None) if sketch_id is not None else (sks[-1] if sks else None)
    return {"sketchId": sk["id"] if sk else None, "regions": regions if regions is not None else auto_regions(sk and sk["sketch"]), "extent": {"kind": "distance", "from": 0, "to": 10}, "draftDeg": 0, "op": "join"}


def start_revolve(features, sketch_id=None, regions=None, axis=None):
    """The Revolve box as it opens: a full turn, no pitch, right-handed, join."""
    sks = _sketches(features)
    sk = next((f for f in sks if f["id"] == sketch_id), None) if sketch_id is not None else (sks[-1] if sks else None)
    return {"sketchId": sk["id"] if sk else None, "regions": regions if regions is not None else auto_regions(sk and sk["sketch"]), "axis": axis, "angleDeg": FULL_TURN_DEG, "pitch": 0, "leftHanded": False, "op": "join"}


def empty_network_draft():
    return {"nodes": [], "curves": [], "cells": [], "spans": {}, "fit": dict(DEFAULT_NETWORK_FIT), "nextId": 1, "placing": None, "history": [], "future": [], "picked": None, "tool": "draw", "suggested": None}


def start_feature(kind, bodies=(), features=(), init=None, results=None):
    """A feature box as it opens (startFeature): the kind's defaults, on the
    last solid body. `bodies` are the built bodies ({id, surface, box})."""
    bodies = list(bodies)
    solid = last_solid(bodies)
    body = solid if solid is not None else (bodies[-1]["id"] if bodies else None)
    if kind == "shell":
        d = {"kind": kind, "body": body, "faces": [], "thickness": DEFAULT_WALL_MM, "thicknessFrom": "default"}
    elif kind == "fillet":
        d = {"kind": kind, "body": body, "edges": [], "radius": DEFAULT_FILLET_MM, "chain": True, "radiusTyped": False, "estimate": {"status": "idle"}, "mode": "constant"}
    elif kind == "chamfer":
        d = {"kind": kind, "body": body, "edges": [], "distance": DEFAULT_FILLET_MM, "chain": True, "mode": "equal", "distance2": DEFAULT_FILLET_MM, "angleDeg": 45, "flip": False}
    elif kind == "hole":
        d = {"kind": kind, "body": body, "axis": None, "radius": 3, "depth": None, "insert": None}
    elif kind == "thread":
        d = {"kind": kind, "body": body, "face": None, "internal": None, "standard": "metric", "diameter": 10, "pitch": 1.5, "leftHanded": False, "fullLength": True, "length": 10, "start": 0, "flip": False, "offset": 0, "chamfer": False, "sized": False}
    elif kind == "extract":
        d = {"kind": kind, "element": None, "section": None, "thickness": DEFAULT_WALL_MM, "op": "new"}
    elif kind == "cutPlane":
        d = {"kind": kind, "body": body, "plane": None, "keep": 1}
    elif kind == "mirror":
        d = {"kind": kind, "body": body, "plane": None, "join": True, "symmetry": {"status": "idle"}}
    elif kind == "boolean":
        tool = next((b["id"] for b in bodies if b["id"] != body and not b.get("surface")), None)
        d = {"kind": kind, "op": "join", "body": body, "tool": tool, "keep": False}
    elif kind == "sheet":
        sks = _sketches(features)
        d = {"kind": kind, "sketchId": sks[-1]["id"] if sks else None, "from": -10, "to": 10}
    elif kind == "split":
        d = {"kind": kind, "body": body, "tools": [], "keep": "scan", "tolerance": DEFAULT_SPLIT_TOLERANCE_MM, "overlap": DEFAULT_SPLIT_OVERLAP}
    elif kind == "loft":
        d = {"kind": kind, "sketches": [], "ruled": True, "op": "join"}
    elif kind == "sweep":
        last2 = _sketches(features)[-2:]
        a = last2[0] if len(last2) > 0 else None
        b = last2[1] if len(last2) > 1 else None

        def closes(f):
            return f is not None and len(find_regions(f["sketch"])) > 0

        profile, path = (b, a) if closes(b) and not closes(a) else (a, b)
        d = {"kind": kind, "profile": profile["id"] if profile else None, "path": path["id"] if path else None, "op": "join"}
    elif kind == "thicken":
        sheets = [b for b in bodies if b.get("surface")]
        d = {"kind": kind, "sheet": sheets[-1]["id"] if sheets else None, "thickness": DEFAULT_WALL_MM, "side": "in", "op": "new"}
    elif kind == "pattern":
        d = {"kind": kind, "body": body, "mode": "circular", "axis": None, "count": 4, "step": 360, "axis2": None, "count2": 2, "step2": 10}
    elif kind == "draft":
        d = {"kind": kind, "body": body, "neutral": None, "faces": [], "angleDeg": DEFAULT_DRAFT_DEG}
    elif kind == "moveFace":
        d = {"kind": kind, "body": body, "faces": [], "snap": False, "offset": 0, "reading": None, "fitting": False, "error": None, "lean": False, "history": False}
    elif kind == "deleteFace":
        d = {"kind": kind, "body": body, "faces": [], "tangent": True}
    elif kind == "offsetBody":
        d = {"kind": kind, "body": body, "distance": 1, "keep": True}
    elif kind == "import":
        d = {"kind": kind, "file": None}
    elif kind == "moveBody":
        asked = [i for i in ((init or {}).get("bodies") or []) if any(b["id"] == i for b in bodies)]
        d = {"kind": kind, "bodies": asked, "pivot": move_pivot(bodies, asked), "translate": [0, 0, 0], "rotate": [0, 0, 0], "copy": False}
    elif kind == "surface":
        d = {"kind": kind, "region": [], "floodDeg": DEFAULT_FLOOD_DEG, "paint": False, "fit": dict(DEFAULT_SURFACE_FIT), "shape": "freeform", "constrain": {"mode": "auto"}}
    elif kind == "network":
        d = {"kind": kind, **empty_network_draft()}
    elif kind == "trim":
        tools = [{"kind": "body", "id": b["id"]} for b in bodies if b.get("surface")]
        d = {"kind": kind, "tools": tools, "tolerance": trim_tolerance_for(tools, results or {}), "toleranceTyped": False, "overlap": DEFAULT_SPLIT_OVERLAP}
    else:
        raise ValueError(f"no feature of kind {kind}")
    given = {k: v for k, v in (init or {}).items() if not (kind == "moveBody" and k == "bodies")}
    return {**d, **given}


# ---- the Create key ---------------------------------------------------------------------------


def moves_nothing(p):
    return all(abs(v) < 1e-9 for v in p["translate"]) and all(abs(fmod(v, 360)) < 1e-9 for v in p["rotate"])


def network_ready(d):
    return len(d["curves"]) > 0 and len(d["cells"]) > 0


def feature_draft_ready(d):
    k = d["kind"]
    has = lambda key: d.get(key) is not None  # noqa: E731
    if k == "shell":
        return has("body") and d["thickness"] > 0
    if k == "fillet":
        var = d.get("variable") or []
        return has("body") and ((len(d["edges"]) > 0 and d["radius"] > 0) or (len(d["edges"]) == 0 and len(var) > 0)) and all(v["radius"][0] > 0 and v["radius"][1] > 0 for v in var)
    if k == "chamfer":
        return has("body") and len(d["edges"]) > 0 and d["distance"] > 0 and (d["mode"] != "twoDistances" or d["distance2"] > 0) and (d["mode"] != "distanceAngle" or 0 < d["angleDeg"] < 90)
    if k == "hole":
        return has("body") and has("axis") and d["radius"] > 0 and (d["depth"] is None or d["depth"] > 0)
    if k == "thread":
        return has("body") and has("face") and thread_problem(d) is None and (bool(d["fullLength"]) or (d["length"] > 0 and d["start"] >= 0))
    if k == "extract":
        return has("element") or has("section")
    if k in ("cutPlane", "mirror"):
        return has("body") and has("plane")
    if k == "boolean":
        return has("body") and has("tool") and d["body"] != d["tool"] and d["body"] not in (d.get("moreTools") or [])
    if k == "sheet":
        return has("sketchId") and abs(d["to"] - d["from"]) > 1e-9
    if k == "split":
        return has("body") and len(d["tools"]) > (1 if d["keep"] == "between" else 0) and d["body"] not in d["tools"] and d["tolerance"] > 0 and 0 < d["overlap"] <= 1
    if k == "thicken":
        return has("sheet") and d["thickness"] > 0
    if k == "loft":
        return len(d["sketches"]) >= 2
    if k == "sweep":
        return has("profile") and (len(d["route"]["points"]) >= 2 if d.get("route") else (has("path") and d["profile"] != d["path"]))
    if k == "pattern":
        return has("body") and has("axis") and d["count"] >= 2 and d["step"] > 0 and (d["mode"] == "circular" or d.get("axis2") is None or d["count2"] < 2 or d["step2"] > 0)
    if k == "surface":
        return len(d["region"]) >= SURFACE_MIN_REGION
    if k == "network":
        return network_ready(d)
    if k == "trim":
        return len(d["tools"]) > 0 and d["tolerance"] > 0 and 0 < d["overlap"] <= 1
    if k == "draft":
        angles = [d["angleDeg"]] + [g["angleDeg"] for g in (d.get("groups") or [])]
        return has("body") and has("neutral") and len(d["faces"]) > 0 and all(1e-9 < abs(a) < 89 for a in angles) and all(len(g["faces"]) > 0 for g in (d.get("groups") or []))
    if k == "moveFace":
        return has("body") and len(d["faces"]) > 0 and abs(d["offset"]) > 1e-6
    if k == "deleteFace":
        return has("body") and len(d["faces"]) > 0
    if k == "offsetBody":
        return has("body") and abs(d["distance"]) > 1e-6
    if k == "import":
        return has("file")
    if k == "moveBody":
        return len(d["bodies"]) > 0 and all(math.isfinite(v) for v in d["pivot"] + d["translate"] + d["rotate"]) and (bool(d["copy"]) or not moves_nothing(d))
    return False


def extrude_draft_ready(d):
    e = d["extent"]
    return (
        (d.get("face") is not None or (d.get("sketchId") is not None and len(d["regions"]) > 0))
        and (e["kind"] != "toPlane" or bool(e.get("plane")))
        and (e["kind"] != "toFace" or bool(e.get("face")))
        and (e["kind"] != "toBody" or e["body"] >= 0)
        and (e["kind"] != "betweenPlanes" or (bool(e.get("a")) and bool(e.get("b"))))
    )


def revolve_draft_ready(d):
    return d.get("sketchId") is not None and len(d["regions"]) > 0 and d.get("axis") is not None and 0 < d["angleDeg"] <= revolve_max_deg(d.get("pitch"))


def revolve_angle(deg, pitch):
    return min(revolve_max_deg(pitch), max(0.1, js_round(abs(deg) * 10) / 10))


def round_face_length(face):
    r = face.get("radius") or 0
    return js_round((face["area"] / (2 * math.pi * r)) * 1000) / 1000 if r > 0 else 10


def fillet_mode_switch(d, mode):
    if mode == d.get("mode"):
        return {}
    varying = d.get("variable") or []
    if mode == "variable" and not varying and d["edges"]:
        return {"mode": mode, "edges": [], "variable": [{"edge": e, "radius": [d["radius"], d["radius"]]} for e in d["edges"]]}
    if mode == "constant" and not d["edges"] and varying:
        return {"mode": mode, "edges": [v["edge"] for v in varying], "variable": None, "radius": varying[0]["radius"][0], "radiusTyped": True}
    return {"mode": mode}


def _fp(x):
    return x["fingerprint"]


def feature_of_draft(d, i, name):
    """The feature a ready draft makes (featureOfDraft), or None."""
    k = d["kind"]
    if k == "network":
        if not d["curves"]:
            return None
        data = {key: d[key] for key in ("nodes", "curves", "cells", "spans", "fit")}
        from ._js import clone
        return {"id": i, "kind": "network", "name": name, **clone(data), "visible": True}
    if not feature_draft_ready(d):
        return None
    head = {"id": i, "kind": k, "name": name}
    if k == "shell":
        return {**head, "body": d["body"], "faces": [_fp(f) for f in d["faces"]], "thickness": d["thickness"], "visible": True}
    if k == "fillet":
        out = {**head, "body": d["body"], "edges": [_fp(e) for e in d["edges"]], "radius": d["radius"], "chain": d["chain"]}
        if d.get("skipFailing"):
            out["skipFailing"] = True
        if d.get("variable"):
            out["variable"] = [{"edge": _fp(v["edge"]), "radius": v["radius"]} for v in d["variable"]]
        out["visible"] = True
        return out
    if k == "chamfer":
        out = {**head, "body": d["body"], "edges": [_fp(e) for e in d["edges"]], "distance": d["distance"], "chain": d["chain"]}
        if d.get("skipFailing"):
            out["skipFailing"] = True
        if d["mode"] == "twoDistances":
            out.update({"mode": d["mode"], "distance2": d["distance2"]})
        elif d["mode"] == "distanceAngle":
            out.update({"mode": d["mode"], "angleDeg": d["angleDeg"]})
        if d["mode"] != "equal" and d.get("flip"):
            out["flip"] = True
        out["visible"] = True
        return out
    if k == "hole":
        out = {**head, "body": d["body"], "axis": d["axis"], "radius": d["radius"], "depth": d["depth"]}
        if d.get("insert"):
            out["insert"] = d["insert"]
        out["visible"] = True
        return out
    if k == "thread":
        return {**head, "body": d["body"], "face": _fp(d["face"]), "standard": d["standard"], "diameter": d["diameter"], "pitch": d["pitch"], "leftHanded": d["leftHanded"], "length": None if d["fullLength"] else d["length"], "start": 0 if d["fullLength"] else d["start"], "flip": d["flip"], "offset": d["offset"], "chamfer": d["chamfer"], "visible": True}
    if k == "extract":
        src = {"section": d["section"]} if d.get("section") is not None else {"element": d["element"]}
        return {**head, **src, "thickness": d["thickness"], "op": d["op"], "visible": True}
    if k == "cutPlane":
        return {**head, "body": d["body"], "plane": d["plane"], "keep": d["keep"], "visible": True}
    if k == "mirror":
        return {**head, "body": d["body"], "plane": d["plane"], "join": d["join"], "visible": True}
    if k == "boolean":
        tools = []
        for t in [d["tool"]] + list(d.get("moreTools") or []):
            if t not in tools:
                tools.append(t)
        out = {**head, "op": d["op"], "body": d["body"], "tool": tools[0] if len(tools) == 1 else tools}
        if d.get("keep"):
            out["keep"] = True
        out["visible"] = True
        return out
    if k == "sheet":
        return {**head, "sketchId": d["sketchId"], "from": d["from"], "to": d["to"], "visible": True}
    if k == "split":
        out = {**head, "body": d["body"], "tools": list(d["tools"]), "keep": d["keep"], "tolerance": d["tolerance"], "overlap": d["overlap"]}
        if d.get("within") is not None:
            out["within"] = d["within"]
        out["visible"] = True
        return out
    if k == "loft":
        return {**head, "sketches": list(d["sketches"]), "ruled": d["ruled"], "op": d["op"], "visible": True}
    if k == "sweep":
        way = {"route": d["route"]} if d.get("route") else {"path": d["path"]}
        return {**head, "profile": d["profile"], **way, "op": d["op"], "visible": True}
    if k == "thicken":
        return {**head, "sheet": d["sheet"], "thickness": d["thickness"], "side": d["side"], "op": d["op"], "visible": True}
    if k == "pattern":
        out = {**head, "body": d["body"], "mode": d["mode"], "axis": d["axis"], "count": d["count"], "step": d["step"]}
        if d["mode"] == "linear" and d.get("axis2") and d["count2"] >= 2:
            out.update({"axis2": d["axis2"], "count2": d["count2"], "step2": d["step2"]})
        out["visible"] = True
        return out
    if k == "surface":
        out = {**head, "region": d["region"], "fit": {**d["fit"], "net": dict(d["fit"]["net"]) if d["fit"].get("net") else None}, "shape": d["shape"], "constrain": dict(d["constrain"])}
        if d.get("regionBox"):
            out["regionBox"] = d["regionBox"]
        if d.get("regionStale"):
            out["regionStale"] = d["regionStale"]
        out["visible"] = True
        return out
    if k == "trim":
        return {**head, "tools": [dict(t) for t in d["tools"]], "tolerance": d["tolerance"], "overlap": d["overlap"], "visible": True}
    if k == "draft":
        out = {**head, "body": d["body"], "neutral": d["neutral"], "faces": [_fp(f) for f in d["faces"]], "angleDeg": d["angleDeg"]}
        if d.get("groups"):
            out["groups"] = [{"faces": [_fp(f) for f in g["faces"]], "angleDeg": g["angleDeg"]} for g in d["groups"]]
        out["visible"] = True
        return out
    if k == "moveFace":
        return {**head, "body": d["body"], "faces": [_fp(f) for f in d["faces"]], "offset": d["offset"], "visible": True}
    if k == "deleteFace":
        return {**head, "body": d["body"], "faces": [_fp(f) for f in d["faces"]], "visible": True}
    if k == "offsetBody":
        return {**head, "body": d["body"], "distance": d["distance"], "keep": d["keep"], "visible": True}
    if k == "import":
        return {**head, "file": dict(d["file"]), "visible": True}
    if k == "moveBody":
        return {**head, "bodies": list(d["bodies"]), "pivot": list(d["pivot"]), "translate": list(d["translate"]), "rotate": list(d["rotate"]), "copy": d["copy"], "visible": True}
    return None


def key_parameter_of(f):
    """The one number a row shows beside a feature, with its unit."""
    k = f["kind"]
    L = "mm"
    if k == "extrude":
        e = f["extent"]
        if e["kind"] == "distance":
            return {"value": abs(e["to"] - e["from"]), "unit": L}
        if e["kind"] == "symmetric":
            return {"value": e["total"], "unit": L}
        return None
    if k == "revolve":
        return {"value": f["angleDeg"], "unit": "°"}
    if k in ("shell", "thicken"):
        return {"value": f["thickness"], "unit": L}
    if k == "fillet":
        return {"value": f["radius"], "unit": L} if f["edges"] else None
    if k == "chamfer":
        return {"value": f["distance"], "unit": L}
    if k == "hole":
        return {"value": 2 * f["radius"], "unit": L}
    if k == "extract":
        return {"value": f["thickness"], "unit": L} if f.get("section") is None and f["thickness"] > 0 else None
    if k == "draft":
        return {"value": f["angleDeg"], "unit": "°"}
    if k == "moveFace":
        return {"value": f["offset"], "unit": L}
    if k == "offsetBody":
        return {"value": f["distance"], "unit": L}
    return None


def _sign(x):
    return 0 if x == 0 else (1 if x > 0 else -1)


def with_key_parameter(f, value):
    positive = abs(value)
    k = f["kind"]
    if k == "extrude":
        e = f["extent"]
        if e["kind"] == "distance":
            return {**f, "extent": {**e, "to": e["from"] + _sign((e["to"] - e["from"]) or 1) * positive}}
        if e["kind"] == "symmetric":
            return {**f, "extent": {**e, "total": positive}}
        return f
    if k == "revolve":
        return {**f, "angleDeg": min(revolve_max_deg(f.get("pitch")), max(1, positive))}
    if k in ("shell", "thicken"):
        return {**f, "thickness": positive} if positive > 0 else f
    if k == "fillet":
        return {**f, "radius": positive} if positive > 0 and f["edges"] else f
    if k == "chamfer":
        return {**f, "distance": positive} if positive > 0 else f
    if k == "hole":
        return {**f, "radius": positive / 2} if positive > 0 else f
    if k == "extract":
        return {**f, "thickness": positive} if positive > 0 and f.get("section") is None else f
    if k == "draft":
        return {**f, "angleDeg": value} if 0 < positive < 89 else f
    if k == "moveFace":
        return {**f, "offset": value} if positive > 1e-6 else f
    if k == "offsetBody":
        return {**f, "distance": value} if positive > 1e-6 else f
    return f
