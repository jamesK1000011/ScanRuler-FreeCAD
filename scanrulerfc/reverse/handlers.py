# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/app/reCommands.ts, reFeatureCommands.ts, reParameterCommands.ts, reBodyCommands.ts
# SPDX-License-Identifier: AGPL-3.0-only
#
# The Reverse engineer's tools for agents: the original's reverse.a.b
# commands as reverse_a_b, their inputs and answers in the original's
# fields. Each change is one edit of the part (doc.py: one undo step,
# PartJson written, the bodies rebuilt); a read changes nothing. Their
# definitions are in data/tools.json (group reverse), in Agent Link's
# tool-data format; handlers(session) binds a handler to each name. A refusal is
# raised as Refusal (code, message), which Agent Link hands the agent as a
# refusal, never a crash. Nothing here imports Agent Link or FreeCAD: the
# document is reached through the session given, or a store handed in.
#
# The tools of the parts not ported yet (sketch editing, the scan's planes
# and sections, patch networks, STEP files, the reviews) are in LATER with
# the build step that brings each.

import copy
import json
import os

from .. import workspaces as _W
from ..errors import ToolError
from . import doc as D
from .features import KIND_LABELS, dependents_of, feature_of_draft, moved_list, name_for, start_extrude, start_feature, start_revolve
from .part_file import validate_feature_json

GROUP = "reverse"
INFO = "Reverse engineer (ScanRuler by Stefan Hermann / CNC Kitchen, ported): the feature list, its build and its bodies."
DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "tools.json")

# The original's commands still to come, by tool name: the build step of
# the port (design §7.1) that brings each.
LATER = {
    "reverse_feature_refit": 11, "reverse_sketch_edit": 7, "reverse_sketch_candidates": 7, "reverse_body_review": 13, "reverse_body_probe": 13,
    "reverse_body_section": 13, "reverse_body_volume_compare": 13, "reverse_body_fillet_read": 13, "reverse_body_fillet_try": 13,
    "reverse_body_selected_faces": 13, "reverse_body_face_triangles": 13, "reverse_body_compare_in_deviation": 13, "reverse_plane_describe": 13,
    "reverse_section_fit": 13, "reverse_section_outline": 13, "reverse_section_stack": 13, "reverse_thread_read": 13, "reverse_scan_tube_trace": 13,
    "reverse_network_create": 11, "reverse_network_edit": 11, "reverse_network_read": 11, "reverse_network_suggest_creases": 11,
    "reverse_import_step": 10, "reverse_export_step": 10, "reverse_export_stl": 10, "reverse_import_scanruler": 12,
}

# Echo (design §4.2): what Agent Link's activity line, workbench switch and
# command buttons do for these tools. Data for the merge to declare on the
# family module (agentlink/echo.py declare()).
# The workbench's Create feature keys (workspaces._REVERSE), by kind: every
# kind but sketch (made from "Sketch on") and coil (no key in the original).
GRID_COMMANDS = {k: "ScanRuler_Re" + k[0].upper() + k[1:] for k, *_ in _W._REVERSE}
ECHO = {
    "WORKBENCHES": {"reverse_": "ScanRulerWorkbench"},
    "AREAS": {"reverse": "Reverse engineer"},
    # Keys the workbench has for tools other than reverse_feature_add.
    "COMMANDS": {"reverse_import_step": "ScanRuler_ReImport"},
    "SHOWN": ("reverse_feature_list", "reverse_body_describe", "reverse_body_names", "reverse_parameter_list", "reverse_plane_describe", "reverse_body_check", "reverse_body_review"),
    "NO_BUTTON": ("reverse_feature_schema", "reverse_body_probe", "reverse_body_face_triangles", "reverse_body_selected_faces", "reverse_build_stop"),
}


def command_for(name, args):
    """The command a reverse_feature_add lights: its feature's grid key."""
    if name != "reverse_feature_add" or not isinstance(args, dict):
        return None
    f = args.get("feature") or ((args.get("features") or [None])[0])
    return GRID_COMMANDS.get(f.get("kind")) if isinstance(f, dict) else None


class Refusal(ToolError):
    """A tool's refusal: code (invalid_input, not_found, invalid_state,
    unavailable, failed) and the message the agent reads. The add-on's own
    ToolError, so its runner and Agent Link's family layer take it as
    every other family's refusal."""


def _invalid(message):
    raise Refusal("invalid_input", message)


# ---- where the part lives ---------------------------------------------------------------------


class MemoryStore:
    """The part in memory, built on the builder given: for tests, and for
    a build with no document."""

    def __init__(self, builder, part=None):
        self.builder = builder
        self._part = part or D.empty_part()
        self._last = {"results": [], "bodies": [], "steps": {}, "parameters": []}

    def part(self):
        return copy.deepcopy(self._part)

    def commit(self, verb, name, change):
        new = change(self.part())
        if new is not None:
            self._part = new
        return self.rebuild()

    def rebuild(self):
        self._last = D.build_part(self._part, self.builder)
        return self._last

    def last(self):
        return self._last


class DocStore:
    """The part in the session's document: the container doc.py makes, one
    undo step an edit (inside the session's own transaction when it opened
    one)."""

    def __init__(self, session):
        self.session = session

    def container(self, make=False):
        doc = getattr(self.session, "doc", None)
        if doc is None:
            raise Refusal("unavailable", "No FreeCAD document is open: the Reverse engineer builds its bodies in one.")
        c = D.find_container(doc)
        if c is None and make:
            c = D.make_container(doc)
        return c

    @property
    def builder(self):
        c = self.container()
        return D.builder_of(c) if c else None

    def part(self):
        c = self.container()
        return D.part_of(c.PartJson) if c else D.empty_part()

    def commit(self, verb, name, change):
        c = self.container(make=True)
        D.edit(c, verb, name, change)
        return self.last()

    def rebuild(self):
        return self.commit("build", None, lambda p: None)

    def last(self):
        c = self.container()
        if c is None:
            return {"results": [], "bodies": [], "steps": {}, "parameters": []}
        b = D.builder_of(c)
        return {"results": json.loads(c.Results or "[]"), "bodies": b.briefs(), "steps": b.last_steps, "parameters": []}


# ---- references ------------------------------------------------------------------------------------


def _key(name):
    return str(name).strip().lower()


def find_feature(part, ref, what="feature"):
    feats = part["features"]
    if isinstance(ref, bool) or ref is None:
        _invalid(f"Name the {what}: its id or its name.")
    if isinstance(ref, (int, float)):
        f = next((x for x in feats if x["id"] == ref), None)
    else:
        f = next((x for x in feats if _key(x["name"]) == _key(ref)), None)
    if f is None:
        raise Refusal("not_found", f"No feature is {'numbered' if isinstance(ref, (int, float)) else 'named'} {ref!r} — reverse_feature_list lists them.")
    return f


def find_body(store, ref):
    briefs = store.builder.briefs() if store.builder else []
    if isinstance(ref, (int, float)) and not isinstance(ref, bool):
        b = next((x for x in briefs if x["id"] == ref), None)
    else:
        b = next((x for x in briefs if _key(x["name"]) == _key(ref)), None)
    if b is None:
        raise Refusal("not_found", f"No body is {ref!r} — reverse_body_names lists them.")
    return b


def _free_name(name, taken):
    import re

    base = re.sub(r"\s+\d+$", "", name.strip())
    n = 2
    while _key(f"{base} {n}") in taken:
        n += 1
    return f"{base} {n}"


def require_free_name(part, name, self_id=None, also=()):
    if not isinstance(name, str) or not name.strip():
        return
    taken = {_key(f["name"]) for f in part["features"] if f["id"] != self_id} | {_key(x) for x in also}
    other = next((f for f in part["features"] if f["id"] != self_id and _key(f["name"]) == _key(name)), None)
    if other:
        _invalid(f"Feature {other['id']} is already named “{other['name']}” — the commands find features by name, so each needs its own: “{_free_name(name, taken)}”, say.")
    if _key(name) in {_key(x) for x in also}:
        _invalid(f"Two features in this batch are named “{name.strip()}” — give each its own (“{_free_name(name, taken)}”, say); nothing was added.")


# ---- features from what the agent gives ----------------------------------------------------------

PICK_FIELDS = ("edges", "faces")


def _picks(store, body, given, what):
    """Picks as the box holds them ({fingerprint}): a fingerprint as given,
    or an index into reverse_body_describe's `what` (edges or faces) of
    the body as built."""
    if not isinstance(given, list):
        _invalid(f"{what} is a list: indices from reverse_body_describe, or fingerprints.")
    topo = None
    out = []
    for p in given:
        if isinstance(p, int) and not isinstance(p, bool):
            if topo is None:
                b = store.builder.body_by_id(body) if store.builder and body is not None else None
                if b is None:
                    raise Refusal("invalid_state", f"Body {body} is not built: give the picks as fingerprints, or build it first.")
                topo = store.builder.topology(b, 1)
            row = topo[what]
            if not 0 <= p < len(row):
                _invalid(f"There is no {what[:-1]} {p} on body {body}: reverse_body_describe lists {len(row)}.")
            out.append({"fingerprint": row[p]["fingerprint"]})
        elif isinstance(p, dict):
            out.append({"fingerprint": p.get("fingerprint", p)})
        else:
            _invalid(f"A pick is an index from reverse_body_describe or a fingerprint, not {p!r}.")
    return out


def _wrap(store, kind, given):
    """The box's draft of a body feature from the record's fields."""
    init = dict(given)
    body = init.get("body")
    if isinstance(body, str):
        init["body"] = body = find_body(store, body)["id"]
    for field in PICK_FIELDS:
        if field in init:
            init[field] = _picks(store, body, init[field], field)
    if "face" in init and kind == "thread":
        init["face"] = _picks(store, body, [init["face"]], "faces")[0]
    if init.get("variable"):
        init["variable"] = [{**v, "edge": _picks(store, body, [v["edge"]], "edges")[0]} for v in init["variable"]]
    if kind == "draft" and init.get("groups"):
        init["groups"] = [{**g, "faces": _picks(store, body, g["faces"], "faces")} for g in init["groups"]]
    if kind == "thread" and "length" in init:
        init["fullLength"] = init["length"] is None
        if init["length"] is None:
            init.pop("length")
    if kind == "boolean" and isinstance(init.get("tool"), list):
        tools = init.pop("tool")
        init["tool"], init["moreTools"] = tools[0], tools[1:]
    return init


def _bodies_for_drafts(store):
    return [{"id": b["id"], "surface": b["surface"], "box": b["box"]} for b in (store.builder.briefs() if store.builder else [])]


def make_feature(store, part, given):
    """The record a feature.add makes of what is given: the kind's box
    opened, the fields given put in it, and the box's Create test passed."""
    if not isinstance(given, dict) or "kind" not in given:
        _invalid("A feature is an object with its kind — reverse_feature_schema { kind } gives each kind's fields.")
    kind = given["kind"]
    if kind not in KIND_LABELS:
        _invalid(f"No feature kind {kind!r}: {', '.join(sorted(KIND_LABELS))}.")
    i = part["nextFeatureId"]
    named, counters = name_for(part.get("nextOfKind") or {}, kind)
    name = given.get("name") or named
    fields = {k: v for k, v in given.items() if k not in ("kind", "name", "id")}
    if kind == "sketch":
        f = {"id": i, "kind": kind, "name": name, "visible": True, **fields}
        if "frame" not in f and isinstance(f.get("plane"), dict):
            from .resolve import resolve_plane_frame

            frame = resolve_plane_frame(f["plane"], {"sections": [], "elements": [], "modelCenter": [0, 0, 0]})
            if frame is None:
                _invalid("The plane this sketch is on is not found — a world plane ({kind: world, axis, offset}) needs no scan.")
            f["frame"] = frame
        f.setdefault("sketch", {"entities": [], "constraints": [], "nextId": 1})
    elif kind in ("extrude", "revolve"):
        start = start_extrude(part["features"], fields.get("sketchId"), fields.get("regions")) if kind == "extrude" else start_revolve(part["features"], fields.get("sketchId"), fields.get("regions"), fields.get("axis"))
        f = {"id": i, "kind": kind, "name": name, **start, **fields, "visible": True}
        if kind == "extrude" and not f.get("draftDeg"):
            f.pop("draftDeg", None)
        if kind == "revolve" and not f.get("pitch"):
            f.pop("pitch", None)
            f.pop("leftHanded", None)
        from .features import extrude_draft_ready, revolve_draft_ready

        if not (extrude_draft_ready(f) if kind == "extrude" else revolve_draft_ready(f)):
            _invalid(f"The {KIND_LABELS[kind].lower()} is not ready to make: it needs a sketch with a closed region (regions, or one region alone), an extent{' and an axis' if kind == 'revolve' else ''} — reverse_feature_schema {{ kind: {kind!r} }}.")
    else:
        try:
            d = start_feature(kind, _bodies_for_drafts(store), part["features"], _wrap(store, kind, fields))
        except Refusal:
            raise
        except (KeyError, TypeError, ValueError) as e:
            _invalid(f"The {KIND_LABELS[kind].lower()}'s fields do not fit its box ({type(e).__name__}: {e}) — reverse_feature_schema {{ kind: {kind!r} }}.")
        try:
            f = feature_of_draft(d, i, name)
        except (KeyError, TypeError) as e:
            _invalid(f"The {KIND_LABELS[kind].lower()} is missing {e} — reverse_feature_schema {{ kind: {kind!r} }}.")
        if f is None:
            _invalid(f"The {KIND_LABELS[kind].lower()} is not ready to make — its box's Create test fails: check its fields against reverse_feature_schema {{ kind: {kind!r} }}.")
        if fields.get("exprs"):
            f["exprs"] = fields["exprs"]
        if fields.get("suppressed"):
            f["suppressed"] = True
    try:
        validate_feature_json(f)
    except Exception as e:  # noqa: BLE001 — the project's own check
        _invalid(f"The feature is malformed: {e}")
    return f, counters


# ---- answers ---------------------------------------------------------------------------------------


def _result_out(r):
    return {k: r[k] for k in ("status", "message", "warning", "note", "bodies", "edges", "took") if k in r}


def build_answer(part, out, ids=None):
    names = {f["id"]: f["name"] for f in part["features"]}
    rows = [{"id": r["id"], "name": names.get(r["id"]), **_result_out(r)} for r in out["results"] if ids is None or r["id"] in ids]
    failed = [{"id": r["id"], "name": names.get(r["id"]), "message": r.get("message")} for r in out["results"] if r["status"] == "failed"]
    return {"results": rows, "failed": failed, "bodies": [_body_out(b) for b in out["bodies"]], "steps": {k: out["steps"][k] for k in ("recomputed", "restored", "of") if k in (out.get("steps") or {})}}


def _body_out(b):
    return {"id": b["id"], "name": b["name"], "volume": b["volume"], "closed": b["closed"], "surface": b["surface"], "faces": b["faces"], "box": b["box"]}


def feature_row(f, results, rolled):
    from .features import key_parameter_of

    row = {"id": f["id"], "name": f["name"], "kind": f["kind"]}
    if f.get("suppressed"):
        row["suppressed"] = True
    if rolled:
        row["rolledBack"] = True
    else:
        r = next((x for x in results if x["id"] == f["id"]), None)
        if r:
            row["status"] = r["status"]
            if r.get("message"):
                row["message"] = r["message"]
    try:
        kp = key_parameter_of(f)
        if kp:
            row["key"] = kp
    except Exception:  # noqa: BLE001 — a row without its key number
        pass
    if f.get("exprs"):
        row["exprs"] = f["exprs"]
    return row


# ---- the handlers -----------------------------------------------------------------------------------


def handlers(session=None, store=None):
    """The handler of every tool in tools.json, by name, on the session's
    document (or the store given)."""
    st = store or DocStore(session)

    def commit(verb, name, change, ids=None):
        out = st.commit(verb, name, change)
        return build_answer(st.part(), out, ids)

    def feature_add(a):
        given = a.get("features") if a.get("features") is not None else ([a["feature"]] if a.get("feature") is not None else None)
        if not given or (a.get("feature") is not None and a.get("features") is not None):
            _invalid("Give feature, or features — one of them.")
        part = st.part()
        names = []
        for g in given:
            if isinstance(g, dict):
                require_free_name(part, g.get("name"), None, names)
                if isinstance(g.get("name"), str) and g["name"].strip():
                    names.append(g["name"])
        after = find_feature(part, a["after"], "feature to add after")["id"] if a.get("after") is not None else None
        made = []

        def change(p):
            for g in given:
                f, counters = make_feature(st, p, g)
                feats = p["features"]
                bar = len(feats) if p.get("rolledTo") is None else p["rolledTo"]
                at = bar if after is None else next(n for n, x in enumerate(feats) if x["id"] == (made[-1] if made else after)) + 1
                feats.insert(at, f)
                if p.get("rolledTo") is not None and at <= p["rolledTo"]:
                    p["rolledTo"] += 1
                p["nextFeatureId"] = f["id"] + 1
                p["nextOfKind"] = counters
                made.append(f["id"])
            return p

        out = commit("add", given[-1].get("name") if isinstance(given[-1], dict) else None, change)
        rows = {r["id"]: r for r in out["results"]}
        return {"added": [{"id": i, **(rows.get(i) or {"status": "rolledBack"})} for i in made], "failed": out["failed"], "bodies": out["bodies"], "steps": out["steps"]}

    def feature_update(a):
        part = st.part()
        f = find_feature(part, a.get("feature"))
        sets = a.get("set")
        if not isinstance(sets, dict) or not sets:
            _invalid("Give set: the fields to change, as reverse_feature_add takes them.")
        if "kind" in sets and sets["kind"] != f["kind"]:
            _invalid("A feature keeps its kind — remove it and add the other kind.")
        if "id" in sets:
            _invalid("A feature keeps its id.")
        require_free_name(part, sets.get("name"), f["id"])

        def change(p):
            at = next(n for n, x in enumerate(p["features"]) if x["id"] == f["id"])
            old = p["features"][at]
            merged = {**old, **sets}
            for field in PICK_FIELDS:
                if field in sets:
                    merged[field] = [x["fingerprint"] for x in _picks(st, merged.get("body"), sets[field], field)]
            if "suppressed" in sets and not sets["suppressed"]:
                merged.pop("suppressed")
            try:
                validate_feature_json(merged)
            except Exception as e:  # noqa: BLE001
                _invalid(f"The feature would be malformed: {e}")
            p["features"][at] = merged
            return p

        out = commit("edit", f["name"], change)
        return {"feature": next(x for x in st.part()["features"] if x["id"] == f["id"]), "result": next((r for r in out["results"] if r["id"] == f["id"]), None), "failed": out["failed"], "bodies": out["bodies"], "steps": out["steps"]}

    def feature_remove(a):
        part = st.part()
        f = find_feature(part, a.get("feature"))
        deps = [d for d in dependents_of(f["id"], part["features"]) if d["id"] != f["id"]]
        if deps and not a.get("dependents"):
            raise Refusal("invalid_state", f"{', '.join(d['name'] for d in deps)} {'uses' if len(deps) == 1 else 'use'} what {f['name']} makes — remove {'it' if len(deps) == 1 else 'them'} too (dependents: true), or change {'it' if len(deps) == 1 else 'them'} first.")
        gone = {f["id"], *(d["id"] for d in deps)}

        def change(p):
            keep = [x for x in p["features"] if x["id"] not in gone]
            if p.get("rolledTo") is not None:
                p["rolledTo"] = sum(1 for x in p["features"][:p["rolledTo"]] if x["id"] not in gone)
            p["features"] = keep
            return p

        out = commit("remove", f["name"], change)
        return {"removed": sorted(gone), **out}

    def feature_move(a):
        part = st.part()
        ids = [find_feature(part, r)["id"] for r in (a.get("features") or [a.get("feature")])]
        after = find_feature(part, a["after"])["id"] if a.get("after") is not None else None
        moved = moved_list(part["features"], ids, after)
        if isinstance(moved, str):
            raise Refusal("invalid_state", moved)

        def change(p):
            p["features"] = moved
            return p

        return commit("move", part["features"][0]["name"] if len(ids) > 1 else find_feature(part, ids[0])["name"], change)

    def feature_suppress(a):
        part = st.part()
        f = find_feature(part, a.get("feature"))
        on = a.get("suppressed", True)

        def change(p):
            for x in p["features"]:
                if x["id"] == f["id"]:
                    if on:
                        x["suppressed"] = True
                    else:
                        x.pop("suppressed", None)
            return p

        return commit("suppress" if on else "unsuppress", f["name"], change)

    def feature_rollback(a):
        part = st.part()
        if a.get("after") is None:
            to = None if not a.get("top") else 0
        else:
            f = find_feature(part, a["after"])
            to = next(n for n, x in enumerate(part["features"]) if x["id"] == f["id"]) + 1

        def change(p):
            if to is None or to >= len(p["features"]):
                p.pop("rolledTo", None)
            else:
                p["rolledTo"] = to
            return p

        out = commit("roll back", None, change)
        p = st.part()
        return {"rollback": {"after": p["features"][p["rolledTo"] - 1]["id"] if p.get("rolledTo") else None, "built": p.get("rolledTo", len(p["features"])), "of": len(p["features"])}, **out}

    def feature_clear(a):
        if not a.get("confirm"):
            _invalid("This takes every feature and parameter away (one undo step): give confirm: true.")
        return commit("clear", None, lambda p: D.empty_part())

    def feature_list(a):
        part = st.part()
        results = st.last()["results"]
        bar = len(part["features"]) if part.get("rolledTo") is None else part["rolledTo"]
        if a.get("feature") is not None:
            f = find_feature(part, a["feature"])
            at = next(n for n, x in enumerate(part["features"]) if x["id"] == f["id"])
            if a.get("detail") == "brief":
                return feature_row(f, results, at >= bar)
            return {**f, **({"rolledBack": True} if at >= bar else {"result": next((r for r in results if r["id"] == f["id"]), None)})}
        full = a.get("detail") == "full"
        rows = [(f if full else feature_row(f, results, n >= bar)) for n, f in enumerate(part["features"])]
        return {"features": rows, "rollback": {"built": bar, "of": len(part["features"])}, "parameters": len(part.get("parameters") or [])}

    def feature_schema(a):
        kind = a.get("kind")
        if kind not in KIND_LABELS:
            _invalid(f"No feature kind {kind!r}: {', '.join(sorted(KIND_LABELS))}.")
        return schema_of(kind, st.part())

    def build(a):
        return build_answer(st.part(), st.rebuild())

    def build_stop(a):
        raise Refusal("unavailable", "Builds run in FreeCAD's own process here; the worker a build can be stopped in comes with build step 14 of the port.")

    # ---- parameters
    def _param(part, ref):
        ps = part.get("parameters") or []
        p = next((x for x in ps if (x["id"] == ref if isinstance(ref, (int, float)) and not isinstance(ref, bool) else x["name"] == ref)), None)
        if p is None:
            raise Refusal("not_found", f"No parameter is {ref!r} — reverse_parameter_list lists them.")
        return p

    def _readings(part):
        from .parameters import evaluate_parameters

        return evaluate_parameters(part.get("parameters") or [])["readings"]

    def parameter_list(a):
        part = st.part()
        rows = {r["id"]: r for r in _readings(part)}
        return {"parameters": [{**p, "value": rows[p["id"]]["value"], **({"error": rows[p["id"]]["error"]} if rows[p["id"]]["error"] else {})} for p in part.get("parameters") or []]}

    def parameter_add(a):
        from .parameters import PARAMETER_KINDS, name_problem

        part = st.part()
        name = (a.get("name") or "").strip()
        why = name_problem(name, part.get("parameters") or [])
        if why:
            _invalid(f"The parameter's name will not do: {why}.")
        kind = a.get("kind", "length")
        if kind not in [k["kind"] for k in PARAMETER_KINDS]:
            _invalid(f"A parameter is one of {', '.join(k['kind'] for k in PARAMETER_KINDS)}.")
        if not isinstance(a.get("expression"), (str, int, float)) or isinstance(a.get("expression"), bool):
            _invalid("Give its expression: a number, or a formula over the other parameters.")

        def change(p):
            pid = p.get("nextParameterId") or 1
            row = {"id": pid, "name": name, "kind": kind, "expression": str(a["expression"])}
            if a.get("comment"):
                row["comment"] = a["comment"]
            p["parameters"] = [*(p.get("parameters") or []), row]
            p["nextParameterId"] = pid + 1
            return p

        out = commit("add parameter", name, change)
        return {"parameter": parameter_list({})["parameters"][-1], **out}

    def parameter_set(a):
        part = st.part()
        q = _param(part, a.get("parameter"))

        def change(p):
            for x in p["parameters"]:
                if x["id"] == q["id"]:
                    if "expression" in a:
                        x["expression"] = str(a["expression"])
                    if "comment" in a:
                        x["comment"] = a["comment"]
            return p

        out = commit("set", q["name"], change)
        return {"parameter": next(x for x in parameter_list({})["parameters"] if x["id"] == q["id"]), **out}

    def parameter_rename(a):
        from .parameters import name_problem, rename_in_feature, rename_in_parameters

        part = st.part()
        q = _param(part, a.get("parameter"))
        to = (a.get("to") or "").strip()
        why = name_problem(to, part["parameters"], q["id"])
        if why:
            _invalid(f"The new name will not do: {why}.")

        def change(p):
            p["parameters"] = rename_in_parameters(p["parameters"], q["id"], to)
            p["features"] = [rename_in_feature(f, q["name"], to) for f in p["features"]]
            return p

        return commit("rename", q["name"], change)

    def parameter_remove(a):
        from .parameters import users_of

        part = st.part()
        q = _param(part, a.get("parameter"))
        users = users_of(q["name"], part["parameters"], part["features"])
        if users:
            raise Refusal("invalid_state", f"{q['name']} is read by {', '.join(u['name'] for u in users)} — change {'it' if len(users) == 1 else 'them'} first.")

        def change(p):
            p["parameters"] = [x for x in p["parameters"] if x["id"] != q["id"]]
            return p

        return commit("remove parameter", q["name"], change)

    # ---- bodies
    def _built(ref):
        b = find_body(st, ref)
        body = st.builder.body_by_id(b["id"])
        return b, body

    def body_names(a):
        part = st.part()
        styles = part.get("bodyStyles") or {}
        hidden = set(part.get("hiddenBodies") or [])
        return {"bodies": [{**_body_out(b), **({"style": styles[str(b["id"])]} if str(b["id"]) in styles else {}), "visible": b["id"] not in hidden}
                           for b in (st.builder.briefs() if st.builder else [])]}

    def body_describe(a):
        b, body = _built(a.get("body"))
        t = st.builder.topology(body, 1)
        faces = [{"index": n, **f["fingerprint"]} for n, f in enumerate(t["faces"])]
        edges = [{"index": n, **e["fingerprint"]} for n, e in enumerate(t["edges"])]
        out = {"body": _body_out(b), "faces": faces, "edges": edges}
        if a.get("detail") == "brief":
            out = {"body": out["body"], "faces": len(faces), "edges": len(edges)}
        return out

    def body_check(a):
        b, body = _built(a.get("body"))
        k = st.builder.kernel
        shape = body["shape"]
        return {"body": b["id"], "name": b["name"], "closed": k.is_closed_solid(shape), "valid": k.is_valid(shape), "solids": k.solid_count(shape),
                "shells": k.shells_per_solid(shape) if hasattr(k, "shells_per_solid") else None, "volume": b["volume"], "surface": b["surface"]}

    def body_clearance(a):
        x, bx = _built(a.get("a"))
        y, by = _built(a.get("b"))
        c = st.builder.kernel.clearance(bx["shape"], by["shape"])
        return {"a": x["id"], "b": y["id"], **c}

    def body_set(a):
        from .features import body_maker  # noqa: F401 — ids as the original keeps them

        b = find_body(st, a.get("body"))
        if not any(k in a for k in ("name", "color", "visible")):
            _invalid("Give name, color or visible.")
        color = None
        if "color" in a:
            color = _color_of(a["color"])
            if color is None:
                _invalid("A colour is #rgb, #rrggbb or a swatch's name.")

        def change(p):
            styles = dict(p.get("bodyStyles") or {})
            s = dict(styles.get(str(b["id"])) or {})
            if "name" in a:
                s["name"] = a["name"]
            if color:
                s["color"] = color
            if s:
                styles[str(b["id"])] = s
                p["bodyStyles"] = styles
            if "visible" in a:
                hidden = [i for i in (p.get("hiddenBodies") or []) if i != b["id"]]
                if not a["visible"]:
                    hidden.append(b["id"])
                if hidden:
                    p["hiddenBodies"] = hidden
                else:
                    p.pop("hiddenBodies", None)
            return p

        commit("set", b["name"], change)
        return body_names({})

    return {
        "reverse_feature_add": feature_add, "reverse_feature_update": feature_update, "reverse_feature_remove": feature_remove, "reverse_feature_move": feature_move,
        "reverse_feature_suppress": feature_suppress, "reverse_feature_rollback": feature_rollback, "reverse_feature_clear": feature_clear,
        "reverse_feature_list": feature_list, "reverse_feature_schema": feature_schema, "reverse_build": build, "reverse_build_stop": build_stop,
        "reverse_parameter_add": parameter_add, "reverse_parameter_set": parameter_set, "reverse_parameter_rename": parameter_rename,
        "reverse_parameter_remove": parameter_remove, "reverse_parameter_list": parameter_list,
        "reverse_body_describe": body_describe, "reverse_body_names": body_names, "reverse_body_check": body_check, "reverse_body_set": body_set,
        "reverse_body_clearance": body_clearance,
    }


SWATCHES = {"red": "#d64541", "orange": "#e8590c", "yellow": "#c99a0a", "green": "#2e7d46", "teal": "#0f9b9b", "blue": "#2f73c4", "purple": "#7c52b3"}


def _color_of(given):
    import re

    t = str(given).strip().lower()
    if t in SWATCHES:
        return SWATCHES[t]
    m = re.match(r"^#([0-9a-f]{3}|[0-9a-f]{6})$", t)
    if not m:
        return None
    return "#" + "".join(c * 2 for c in m.group(1)) if len(m.group(1)) == 3 else t


def schema_of(kind, part=None):
    """reverse_feature_schema: a kind's record as reverse_feature_add takes
    it — its fields with the box's defaults, and an example."""
    feats = (part or {}).get("features") or []
    if kind == "sketch":
        fields = {"plane": {"kind": "world", "axis": "z", "offset": 0}, "sketch": {"entities": [], "constraints": [], "nextId": 1}}
    elif kind == "extrude":
        fields = start_extrude(feats)
    elif kind == "revolve":
        fields = start_revolve(feats)
    else:
        d = start_feature(kind)
        fields = {k: v for k, v in d.items() if k not in ("kind", "radiusTyped", "estimate", "thicknessFrom", "symmetry", "snap", "reading", "fitting", "error", "lean", "history", "sized", "internal",
                                                      "paint", "floodDeg", "toleranceTyped", "placing", "future", "picked", "tool", "suggested", "nextId")}
    later = {"sheet", "split", "loft", "sweep", "thicken", "surface", "trim", "network"}
    return {"kind": kind, "label": KIND_LABELS[kind], "fields": fields, "picks": "edges and faces: indices from reverse_body_describe, or fingerprints",
            **({"builds": "not yet in this port (build steps 10 and 11)"} if kind in later else {})}


def tool_names():
    """The tools tools.json defines for this group."""
    with open(DATA, encoding="utf-8") as f:
        return [k for k, v in json.load(f)["entries"].items() if v["group"] == GROUP]
