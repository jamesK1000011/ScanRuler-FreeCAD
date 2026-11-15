# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/core/build.ts (Builder.preview, movePreview), app/useReverseWorkspace.ts (the ghost: its colour, the bodies it stands in for, a cut drawn through)
# SPDX-License-Identifier: AGPL-3.0-only
#
# The ghost of a feature being set up: the solid the feature would make,
# built on the part as it stands before it and meshed, without committing
# anything — the tool body of an extrude or a revolve before its boolean
# (see-through, red for a cut and drawn through the body it cuts), the body
# as a feature working on it would leave it (solid, in the body's place),
# the bodies a Move carries. The builder the document's container keeps is
# used for its prefix cache, and is put back as the committed part has it
# before returning, so nothing reads a preview as built.
#
# ghost(store, record, editing) answers {status: "ok", mesh, color,
# replaces, through, volume, closed} or {status: "failed", message}.
# A mesh is {positions, normals?, indices}: flat lists, in the part's
# coordinates.

import copy

from . import doc as D
from .buildtypes import mesh_deflection
from .features import KIND_LABELS
from .move import move_matrix, move_point
from .vec import length, sub

CUT_COLOR = "#e0564f"
ON_BODY = ("shell", "fillet", "chamfer", "hole", "thread", "cutPlane", "mirror", "boolean", "pattern", "draft", "moveFace", "deleteFace", "offsetBody")


def ghost_color(record, next_id, bodies=()):
    """ghostColor: red for a cut, a Move's first body's colour, a feature on
    a body that body's, else the colour the feature's own body will wear."""
    k = record.get("kind")
    if record.get("op") == "cut":
        return CUT_COLOR
    if k == "moveBody":
        first = (record.get("bodies") or [None])[0]
        if first is None:
            return D.body_color(next_id)
        style = next((b.get("style") or {} for b in bodies if b.get("id") == first), {})
        return style.get("color") or D.body_color(first)
    if k in ON_BODY and record.get("body") is not None:
        return D.body_color(record["body"])
    return D.body_color(record.get("id", next_id))


def replaced_bodies(record):
    """The bodies a ghost stands in for (put out of sight while it shows):
    the body a feature on a body works on, but not a moved face's (the scan
    under it is what is being clicked), a mirror kept apart or an offset
    kept beside; a combine's tool too unless kept; a Move's unless copied."""
    k = record.get("kind")
    if k == "moveBody":
        return [] if record.get("copy") else list(record.get("bodies") or [])
    if k not in ON_BODY or record.get("body") is None or k == "moveFace":
        return []
    if (k == "mirror" and not record.get("join")) or (k == "offsetBody" and record.get("keep")):
        return []
    if k == "boolean" and record.get("tool") is not None and not record.get("keep"):
        tools = record["tool"] if isinstance(record["tool"], list) else [record["tool"]]
        return [record["body"], *tools]
    return [record["body"]]


def _diagonal(k, shape):
    b = (getattr(k, "extent", None) or k.bounds)(shape)
    return length(sub(b["max"], b["min"]))


def mesh_of(k, shape):
    m = k.mesh(shape, mesh_deflection(_diagonal(k, shape)))
    out = {"positions": [float(v) for v in m["positions"]], "indices": [int(i) for i in m["indices"]]}
    if m.get("normals") is not None and len(m["normals"]) == len(out["positions"]):
        out["normals"] = [float(v) for v in m["normals"]]
    return out


def merge(meshes):
    """mergeMeshes: meshes as one, in their order."""
    out = {"positions": [], "indices": []}
    normals = all("normals" in m for m in meshes)
    if normals:
        out["normals"] = []
    for m in meshes:
        first = len(out["positions"]) // 3
        out["positions"] += m["positions"]
        out["indices"] += [i + first for i in m["indices"]]
        if normals:
            out["normals"] += m["normals"]
    return out


def moved_mesh(mesh, matrix):
    """A mesh carried by a move (row-major 3 x 4); its normals turned with it."""
    p = mesh["positions"]
    out = {"positions": [], "indices": list(mesh["indices"])}
    for i in range(0, len(p) - 2, 3):
        out["positions"] += move_point(matrix, p[i:i + 3])
    if "normals" in mesh:
        n = mesh["normals"]
        out["normals"] = []
        for i in range(0, len(n) - 2, 3):
            v = n[i:i + 3]
            out["normals"] += [matrix[r * 4] * v[0] + matrix[r * 4 + 1] * v[1] + matrix[r * 4 + 2] * v[2] for r in range(3)]
    return out


def _prefix(part, editing):
    """The features the ghost is built after: the ones built now, or, for a
    feature reopened, those before it (featuresToBuild)."""
    feats = D.built_features(part)
    if editing is None:
        return feats
    at = next((n for n, f in enumerate(part["features"]) if f["id"] == editing), None)
    return part["features"][:at] if at is not None else feats


def ghost(store, record, editing=None):
    """The ghost of `record` (a stored feature: its id, name and fields) on
    the store's part — see the head of this file."""
    from .build import StepFailed, primitive_solid
    from .parameters import apply_parameters, evaluate_parameters
    from .regions import find_regions
    from .resolve import resolve_features

    part = store.part()
    builder = store.builder
    if builder is None:
        return {"status": "failed", "message": "Nothing is built yet."}
    ctx = store.context()
    k = builder.kernel
    prefix = _prefix(part, editing)
    words = KIND_LABELS.get(record.get("kind"), "feature")
    try:
        D.build_part({**part, "features": prefix, "rolledTo": None}, builder, ctx)
        table = evaluate_parameters(part.get("parameters") or [])
        feats = apply_parameters(copy.deepcopy(prefix) + [copy.deepcopy(record)], table["scope"])["features"]
        steps = resolve_features(feats, ctx, lambda f: find_regions(f["sketch"]))
        step = steps[-1] if steps else None
        if step is None or step.get("id") != record["id"] or step["kind"] == "sketch":
            return {"status": "failed", "message": f"The {words.lower()} has nothing to show yet."}
        if step["kind"] == "failed":
            return {"status": "failed", "message": step["message"]}
        builder.steps_in_play = steps
        builder.step_warnings = []
        kind = step["kind"]
        sketches = {f["id"]: f["sketch"] for f in feats if f["kind"] == "sketch"}
        if kind == "moveBody":
            matrix = move_matrix({"pivot": record["pivot"], "translate": record.get("translate") or [0, 0, 0], "rotate": record.get("rotate") or [0, 0, 0]})
            meshes = []
            volume, closed = 0.0, True
            for i in dict.fromkeys(builder.resolve(b) for b in record.get("bodies") or []):
                body = builder.body_before(record["id"], i)
                if not body:
                    return {"status": "failed", "message": "A body this move takes is gone, or failed to build."}
                meshes.append(moved_mesh(mesh_of(k, body["shape"]), matrix))
                if body.get("surface"):
                    closed = False
                else:
                    volume += k.volume(body["shape"])
            if not meshes:
                return {"status": "failed", "message": "Pick the bodies to move."}
            return {"status": "ok", "mesh": merge(meshes), "volume": volume, "closed": closed}
        if kind in ("extrude", "revolve"):
            shape = builder.solid_of(step, sketches.get(step.get("sketchId")))
        elif kind == "extract":
            shape = primitive_solid(k, step["primitive"])
        elif kind in ON_BODY:
            shape = builder.apply_to_body(step)["shape"]
        else:
            return _played(builder, steps, sketches, record)
        closed = k.is_closed_solid(shape)
        return {"status": "ok", "mesh": mesh_of(k, shape), "volume": k.volume(shape) if closed else 0.0, "closed": closed}
    except StepFailed as e:
        return {"status": "failed", "message": str(e)}
    except Exception as e:  # noqa: BLE001 — a ghost that cannot build says why; the box stays open
        return {"status": "failed", "message": f"The {words.lower()} does not build: {e}"}
    finally:
        try:
            D.build_part(part, builder, ctx)  # the builder as the committed part has it
        except Exception:  # noqa: BLE001 — the container's own build says what went wrong
            pass


def _played(builder, steps, sketches, record):
    """A ghost for the kinds with no tool body of their own (a sheet, a loft,
    a sweep, a surface…): the step played on the prefix, and what it made
    or changed."""
    k = builder.kernel
    before = {i: b["shape"] for i, b in builder.bodies.items()}
    results = []
    builder.play(steps[-1], sketches.get, results)
    r = next((x for x in results if x["id"] == record["id"]), None)
    if r is None or r["status"] != "ok":
        return {"status": "failed", "message": (r or {}).get("message") or "The feature left nothing."}
    made = [b["shape"] for i, b in builder.bodies.items() if before.get(i) is not b["shape"]]
    if not made:
        return {"status": "failed", "message": "The feature left nothing."}
    meshes = [mesh_of(k, s) for s in made]
    closed = all(k.is_closed_solid(s) for s in made)
    return {"status": "ok", "mesh": merge(meshes), "volume": sum(k.volume(s) for s in made) if closed else 0.0, "closed": closed}


def dressed(answer, record, next_id, bodies=()):
    """The answer with how it is drawn: its colour, the bodies it stands in
    for, and through (a cut's tool drawn through the body it is inside)."""
    if answer.get("status") != "ok":
        return answer
    replaces = replaced_bodies(record)
    return {**answer, "color": ghost_color(record, next_id, bodies), "replaces": replaces,
            "through": not replaces and record.get("op") == "cut", "solid": bool(replaces)}
