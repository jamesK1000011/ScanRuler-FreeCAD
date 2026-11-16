# SPDX-License-Identifier: AGPL-3.0-only
# Wear repair: a worn, dented or damaged part brought back to what it
# should be — its own other half mirrored, or the reference aligned in
# deviation (the CAD, a twin's scan, a catalog download) — and a model
# pre-warped against a print of it. ScanRuler's wear-repair plugin, for
# Agent Link.
# Ported from ScanRuler by CNC Kitchen: plugins/wear-repair/app/
# wearCommands.ts, state/wearStore.ts. Settings, tags and reference are one
# tool here (wear_setup), as Agent Link keeps its tool count down.

import os

import numpy as np

from .. import noise_core as N
from .. import scanstate as S
from .. import wear_core as W
from ..errors import ToolError
from . import _bind, noise
from . import deviation as D

DEFAULTS = {"tolerance": 0.05, "blendMm": 1.0, "maxMm": 2.0, "mode": "add"}
AXES = {"x": [1.0, 0, 0], "y": [0, 1.0, 0], "z": [0, 0, 1.0]}


def obj(props, required=()):
    return {"type": "object", "properties": props, "required": list(required), "additionalProperties": False}


def wstate(session):
    st = S.state(session)
    w = st.setdefault("wear", {"settings": dict(DEFAULTS), "tags": [], "reference": None, "runs": []})
    return w


def _check_region(r):
    if not isinstance(r, dict) or r.get("kind") not in ("box", "sphere"):
        raise ToolError("invalid_input", "region: { kind: box, min, max } or { kind: sphere, center, radius }.")
    if r["kind"] == "box":
        if any(a > b for a, b in zip(r["min"], r["max"])):
            raise ToolError("invalid_input", "A box's min must not exceed its max.")
    elif not r.get("radius", 0) > 0:
        raise ToolError("invalid_input", "A sphere's radius must be over 0.")
    return r


def reference_surface(session, w, scan):
    ref = w["reference"]
    if not ref:
        raise ToolError("invalid_state", "No reference chosen — wear_setup { reference: { source: mirror, plane } } (the part's own other half) or { source: deviation } (the CAD or a twin).")
    if ref["source"] == "mirror":
        V, F = W.mirror(scan.V, scan.F, ref["point"], ref["normal"])
        return W.surface(V, F)
    d = D.dstate(session)
    if d["reference"] is None or not d["align"]:
        raise ToolError("invalid_state", "The deviation reference is not open and aligned: deviation_open_reference, then deviation_align.")
    return d["reference"]["surface"]


def _noise(session):
    n = noise.plan_now(session)
    return n, (N.answer(n) if n else None)


def _stem(name):
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in os.path.splitext(name or "part")[0])


def bind(session):
    """{tool name: fn(args)} for one session (Agent Link's, or the
    add-on's own runner's context)."""
    def wear_setup(a):
        w = wstate(session)
        s = w["settings"]
        for k in ("tolerance", "blendMm", "maxMm", "mode"):
            if a.get(k) is not None:
                s[k] = a[k]
        if a.get("reset"):
            w["settings"] = s = dict(DEFAULTS)
        for t in a.get("tag") or []:
            act = t.get("action", "set")
            if act == "set":
                if not t.get("name") or not t.get("region"):
                    raise ToolError("invalid_input", "A tag to set needs a name and a region.")
                w["tags"] = [x for x in w["tags"] if x["name"] != t["name"]] + [{"name": t["name"], "kind": t.get("kind", "worn"), "region": _check_region(t["region"])}]
            elif act == "remove":
                before = len(w["tags"])
                w["tags"] = [x for x in w["tags"] if x["name"] != t.get("name")]
                if len(w["tags"]) == before:
                    raise ToolError("not_found", f"tag remove: no region {t.get('name')!r} — the regions: {', '.join(x['name'] for x in w['tags']) or 'none'}.")
            elif act == "clear":
                w["tags"] = []
        ref = a.get("reference")
        if ref:
            if ref["source"] == "mirror":
                n = AXES.get(ref.get("plane")) if ref.get("plane") else ref.get("normal")
                if not n or not np.linalg.norm(n) > 0:
                    raise ToolError("invalid_input", "mirror needs plane (x, y or z: run align_symmetry first so the mirror plane is one of them) or a normal.")
                w["reference"] = {"source": "mirror", "point": ref.get("point", [0.0, 0.0, 0.0]), "normal": list(map(float, n))}
            else:
                d = D.dstate(session)
                if d["reference"] is None or not d["align"]:
                    raise ToolError("invalid_state", "reference { source: deviation } is the deviation reference as the scan is aligned to it, and there is none yet: deviation_open_reference, then deviation_align, then wear_setup again.")
                w["reference"] = {"source": "deviation", "name": d["reference"]["name"]}
        return {"settings": s, "tags": w["tags"], "reference": w["reference"]}

    def _worn(w, names):
        worn = [t for t in w["tags"] if t["kind"] == "worn" and (not names or t["name"] in names)]
        if not worn:
            raise ToolError("invalid_state", "No region tagged worn — wear_setup { tag: [{ name, region }] } first.")
        return worn

    def wear_diff(a):
        w = wstate(session)
        scan = S.scan_of(session)
        worn = _worn(w, a.get("names"))
        ref = reference_surface(session, w, scan)
        s = w["settings"]
        spread = W.scatter(scan.V, ref, [t["region"] for t in worn], s["maxMm"])
        plan, answer = _noise(session)
        floor = W.tolerance_floor(spread, plan)
        note = W.scatter_note(spread, s["tolerance"], plan, answer["from"] if answer else None)
        out = {"reference": w["reference"], "tolerance": s["tolerance"]}
        if spread:
            out["scatter"] = spread["mm"]
        if answer:
            out["scanNoise"] = answer
        if floor:
            out["floor"] = floor
        if note:
            out["note"] = note
        out["regions"] = W.diff(scan.V, ref, worn, s["tolerance"], s["maxMm"])
        return out

    def wear_rebuild(a):
        w = wstate(session)
        scan = S.scan_of(session)
        worn = _worn(w, a.get("names"))
        ref = reference_surface(session, w, scan)
        s = w["settings"]
        before = W.diff(scan.V, ref, worn, s["tolerance"], s["maxMm"])
        keep = [t["region"] for t in w["tags"] if t["kind"] == "keep"]
        V2, moved, largest = W.rebuild(scan.V, ref, [t["region"] for t in worn], keep, s["blendMm"], s["maxMm"], a.get("mode") or s["mode"])
        after = W.diff(V2, ref, worn, s["tolerance"], s["maxMm"])
        path = a.get("path") or os.path.join(session.out_dir, f"{_stem(scan.name)}-repaired.stl")
        W.write_stl(path, V2, scan.F)

        def brief(rows):
            return [{k: r[k] for k in ("name", "lost", "added", "pointsLost")} for r in rows]

        return {"file": {"path": path, "name": os.path.basename(path), "bytes": os.path.getsize(path)}, "moved": moved, "largestMoveMm": largest,
                "before": brief(before), "after": brief(after),
                "note": "In the frame the part is measured in now. A worn or dented surface comes back; a piece broken off, with no scan surface there, does not — model it from the reference.",
                "next": "scan_open the file (discard: true) and wear_diff to read the repair; import_file brings it into the document as a body."}

    def wear_prewarp(a):
        w = wstate(session)
        scan = S.scan_of(session)
        d = D.dstate(session)
        if d["reference"] is None or not d["align"]:
            raise ToolError("invalid_state", "Open the target as the reference part (deviation_open_reference) and a scan of a print of it as the scan, then deviation_align.")
        if a.get("fresh"):
            w["runs"] = []
        ref = d["reference"]
        printed = W.surface(scan.V, scan.F)
        V2, res = W.prewarp(ref["V"], ref["F"], printed, a.get("gain", 1.0), round(a.get("smooth", 2)), w["settings"]["maxMm"])
        run = {"n": len(w["runs"]) + 1, "rms": res["rms"]}
        w["runs"].append(run)
        verdict = W.stop_rule(w["runs"], w["settings"]["tolerance"])
        path = a.get("path") or os.path.join(session.out_dir, f"{_stem(ref['name'])}-prewarp-{run['n']}.stl")
        W.write_stl(path, V2, ref["F"])
        return {"file": {"path": path, "name": os.path.basename(path), "bytes": os.path.getsize(path)}, "run": run["n"], "rms": res["rms"], "largest": res["largest"],
                **({"unread": res["unread"]} if res["unread"] else {}), "runs": [{"run": r["n"], "rms": r["rms"]} for r in w["runs"]],
                "stop": verdict["stop"], "why": verdict["why"],
                "note": "In the target's own frame, to print next. Starting the print is the person's call."}

    return {
        "wear_setup": wear_setup,
        "wear_diff": wear_diff,
        "wear_rebuild": wear_rebuild,
        "wear_prewarp": wear_prewarp,
    }


NAMES = ("wear_setup", "wear_diff", "wear_rebuild", "wear_prewarp")
HANDLERS = _bind.table(bind, NAMES)
