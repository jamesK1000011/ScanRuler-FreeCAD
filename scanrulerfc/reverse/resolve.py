# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/core/resolve.ts (and drawnFit from src/core/elements/assumed.ts, shadowPrimitive from shadowPieces.ts)
# SPDX-License-Identifier: AGPL-3.0-only
#
# The feature list resolved for the build: planes and axes found from what
# they refer to, a hole's axis, and every feature turned into the BuildStep
# the builder plays, in order (steps.py). A step is a dict whose keys come
# in the order the original's object literal has them, and a key the
# original leaves undefined is left out: the prefix cache hashes the steps
# (buildtypes.step_keys) and the hash has to be the original's.

import math

from ._js import js_hypot, js_round, num_str, to_fixed
from .features import FULL_TURN_DEG, MIN_SWEEP_RAD, constrain_refs, movable_face, revolve_max_deg, thread_problem, tools_of
from .frames import WORLD_AXES, radial_frame, sketch_frame_on, world_axis_dir, world_plane_name
from .move import move_matrix
from .profiles import lift_point, loft_problem, loft_profile, picked_profiles, route_sweep_geometry, sketch_pieces, sweep_geometry
from .steps import SURFACE_MIN_REGION
from .vec import add_scaled, cross, dot, normalize, scale

_NO = object()
UP_MIN_SHARE = 0.1
MM_PER_INCH = 25.4


def _obj(*pairs):
    """An object literal: the pairs in order, those whose value is absent
    (the original's undefined) left out."""
    return {k: v for k, v in pairs if v is not _NO}


def fmt_len(mm, units="mm", mm_decimals=3, bare=False):
    """src/core/units.ts fmtLen: "12.700 mm" / "0.5000 in"."""
    places = max(3, mm_decimals + 1) if units == "in" else mm_decimals
    text = to_fixed(mm / (MM_PER_INCH if units == "in" else 1), places)
    if float(text) == 0:
        text = to_fixed(0, places)
    return text if bare else f"{text} {units}"


def resolve_plane_frame(ref, ctx, seed_u=None):
    """The frame a plane reference stands for now, or None when the thing it
    names is gone."""
    k = ref["kind"]
    if k in ("fitted", "bodyFace"):
        frame = ref["frame"]
        return {**frame, "basisU": seed_u, "basisV": cross(frame["normal"], seed_u)} if seed_u else frame

    def off(frame):
        if frame and k != "world" and ref.get("offset"):
            return {**frame, "origin": add_scaled(frame["origin"], frame["normal"], ref["offset"])}
        return frame

    if k == "radial":
        line = resolve_axis(ref["axis"], None, ctx)
        d = line and normalize(line["dir"])
        if not line or not d:
            return None
        return off(radial_frame({"origin": add_scaled(line["origin"], d, -dot(line["origin"], d)), "dir": d}, ref["angleDeg"]))

    def seed(normal):
        u = up_u(ref.get("up"), normal)
        return u if u is not None else seed_u

    if k == "section":
        sec = next((s for s in ctx["sections"] if s["id"] == ref["id"]), None)
        frame = sec and sec.get("frame")
        return off(sketch_frame_on(frame, seed(frame["normal"]))) if frame else None
    if k == "world":
        d = world_axis_dir(ref["axis"])
        offset = ref["offset"]
        ok = isinstance(offset, (int, float)) and not isinstance(offset, bool) and math.isfinite(offset)
        return sketch_frame_on({"origin": scale(d, offset if ok else 0), "normal": d}, seed(d))
    el = next((e for e in ctx["elements"] if e["id"] == ref["id"]), None)
    fit = el and el.get("fit")
    if not fit or fit["kind"] != "plane":
        return None
    return off(sketch_frame_on({"origin": fit["center"], "normal": fit["normal"]}, seed(fit["normal"])))


def up_u(up, normal):
    n = normalize(normal) if up else None
    if not up or not n:
        return None
    u = cross(world_axis_dir(up), n)
    return None if js_hypot(u[0], u[1], u[2]) < UP_MIN_SHARE else normalize(u)


def world_plane_key(axis, offset):
    return f"world:{axis}:{num_str(js_round(offset * 1000) / 1000)}"


def coordinate_plane_offers(centre, at_zero):
    out = []
    if at_zero:
        for axis in WORLD_AXES:
            out.append({"key": world_plane_key(axis, 0), "label": world_plane_name(axis), "ref": {"kind": "world", "axis": axis, "offset": 0}})
    if centre:
        for axis in WORLD_AXES:
            offset = centre[0 if axis == "x" else 1 if axis == "y" else 2]
            out.append({"key": world_plane_key(axis, offset), "label": f"{world_plane_name(axis)} through the centre", "ref": {"kind": "world", "axis": axis, "offset": offset}})
    return out


def _resolve_plane(ref, ctx):
    frame = resolve_plane_frame(ref, ctx)
    return frame and {"origin": frame["origin"], "normal": frame["normal"]}


def resolve_axis(ref, sketch, ctx):
    """The axis a revolve turns about {origin, dir}, or None."""
    if ref["kind"] == "world":
        return {"origin": [0, 0, 0], "dir": world_axis_dir(ref["axis"])}
    if ref["kind"] == "sketchLine":
        if not sketch:
            return None
        line = next((e for e in sketch["sketch"]["entities"] if e["id"] == ref["entity"]), None)
        if not line or line["kind"] != "line":
            return None
        a = lift_point(sketch["frame"], line["a"])
        b = lift_point(sketch["frame"], line["b"])
        d = normalize([b[0] - a[0], b[1] - a[1], b[2] - a[2]])
        return d and {"origin": a, "dir": d}
    el = next((e for e in ctx["elements"] if e["id"] == ref["id"]), None)
    fit = el and el.get("fit")
    if not fit:
        return None
    if fit["kind"] == "line":
        return {"origin": fit["center"], "dir": fit["dir"]}
    if fit["kind"] in ("cylinder", "cone"):
        return {"origin": fit["center"], "dir": fit["axis"]}
    if fit["kind"] == "circle":
        return {"origin": fit["center"], "dir": fit["normal"]}
    return None


def describe_plane_ref(ref, ctx, units="mm"):
    k = ref["kind"]
    offset = ref.get("offset")
    off = f", {'+' if offset > 0 else '−'}{fmt_len(abs(offset), units, 2)} off it" if k not in ("world", "fitted") and offset else ""

    def name_of(items, i, gone):
        x = next((s for s in items if s["id"] == i), None)
        return x["name"] if x is not None and x.get("name") is not None else gone

    if k == "section":
        return name_of(ctx["sections"], ref["id"], "deleted section") + off
    if k == "plane":
        return name_of(ctx["elements"], ref["id"], "deleted plane") + off
    if k == "fitted":
        return ref["label"] if ref.get("label") is not None else "a fitted plane"
    if k == "bodyFace":
        return "a face of the body" + off
    if k == "radial":
        a = ref["axis"]
        axis = f"the {a['axis'].upper()} axis" if a["kind"] == "world" else name_of(ctx["elements"], a["id"], "a deleted axis")
        return f"the plane through {axis} at {num_str(js_round(ref['angleDeg'] * 1000) / 1000)}°" + off
    name = "YZ" if ref["axis"] == "x" else "XZ" if ref["axis"] == "y" else "XY"
    at = to_fixed(ref["offset"], 2) if units == "mm" else fmt_len(ref["offset"], units, 2, bare=True)
    return f"{name} plane at {ref['axis'].upper()} = {at}"


def _placed_on_part(f):
    return f["plane"]["kind"] == "bodyFace" or any(e.get("projected") and e.get("source") for e in f["sketch"]["entities"])


# ---- elements as bodies --------------------------------------------------------------------

MIN_SIZE = 1e-3


def drawn_fit(fit, assumed, extend):
    """The element as it is drawn and exported: at its assumed diameter and
    out as far as it was extended (src/core/elements)."""
    if assumed is not None and fit["kind"] in ("sphere", "cylinder", "circle") and math.isfinite(assumed) and assumed > 0:
        radius = assumed / 2
        if radius != fit["radius"]:
            fit = {**fit, "radius": radius}
    if not extend or fit["kind"] not in ("cylinder", "plane") or extend.get("kind") != fit["kind"]:
        return fit
    if fit["kind"] == "cylinder":
        ln = max(fit["length"] + extend["start"] + extend["end"], MIN_SIZE)
        if ln == fit["length"] and extend["start"] == extend["end"]:
            return fit
        return {**fit, "length": ln, "center": add_scaled(fit["center"], fit["axis"], (extend["end"] - extend["start"]) / 2)}
    eu = max(fit["extentU"] + (extend["uMin"] + extend["uMax"]) / 2, MIN_SIZE / 2)
    ev = max(fit["extentV"] + (extend["vMin"] + extend["vMax"]) / 2, MIN_SIZE / 2)
    center = add_scaled(fit["center"], fit["basisU"], (extend["uMax"] - extend["uMin"]) / 2)
    center = add_scaled(center, fit["basisV"], (extend["vMax"] - extend["vMin"]) / 2)
    return {**fit, "extentU": eu, "extentV": ev, "center": center}


def _primitive_of(fit, thickness):
    if not fit:
        return "The element this body is taken from is gone."
    k = fit["kind"]
    if k == "plane":
        if not (thickness > 0):
            return "A slab needs a thickness."
        return {"kind": "slab", "origin": fit["center"], "normal": fit["normal"], "basisU": fit["basisU"], "basisV": fit["basisV"], "extentU": fit["extentU"], "extentV": fit["extentV"], "thickness": thickness}
    if k == "cylinder":
        return {"kind": "cylinder", "origin": fit["center"], "axis": fit["axis"], "radius": fit["radius"], "length": fit["length"]}
    if k == "cone":
        return {"kind": "cone", "origin": fit["center"], "axis": fit["axis"], "radius1": fit["radius1"], "radius2": fit["radius2"], "length": fit["length"]}
    if k == "sphere":
        return {"kind": "sphere", "center": fit["center"], "radius": fit["radius"]}
    if k == "torus":
        return {"kind": "torus", "center": fit["center"], "axis": fit["axis"], "majorRadius": fit["majorRadius"], "minorRadius": fit["minorRadius"]}
    return f"A {k} has no volume to make a body of."


MIN_THICKNESS_MM = 1e-3


def shadow_primitive(sec):
    """shadowPieces.ts shadowPrimitive: a shadow section as the prism it
    draws, or why there is none. The shadow's regions are read off its
    shape by src/core/section/shadow.ts shadowRegions, which this port has
    not got: a shape that carries them (`regions`, each {outer: {pieces},
    holes: [{pieces}]}) stands; one without is refused in words."""
    if not sec:
        return "The section this body is taken from is gone."
    name = sec.get("name")
    if sec.get("kind") != "shadow":
        return f"{name if name is not None else 'That section'} is a cut — only a shadow section stands as a body."
    sh = (sec.get("cut") or {}).get("shadow")
    if not sh:
        return f"{name if name is not None else 'The shadow'} is still being taken — the body is built once it is."
    regions = sh.get("regions")
    if regions is None:
        return f"{name if name is not None else 'The shadow'}'s outline is not read in this port yet (src/core/section/shadow.ts)."
    if not regions:
        return f"{name if name is not None else 'The shadow'} has no outline."
    if not (sh["extent"]["max"] - sh["extent"]["min"] > MIN_THICKNESS_MM):
        return f"{name if name is not None else 'The shadow'} has no thickness to stand through."
    frame = sh["frame"]

    def mid_of(p):
        if p["kind"] == "line":
            return [(p["from"][0] + p["to"][0]) / 2, (p["from"][1] + p["to"][1]) / 2]
        a = math.atan2(p["from"][1] - p["center"][1], p["from"][0] - p["center"][0]) + p["sweep"] / 2
        return [p["center"][0] + p["radius"] * math.cos(a), p["center"][1] + p["radius"] * math.sin(a)]

    def loop_in(pieces):
        out = []
        for p in pieces:
            if p["kind"] == "circle":
                out.append({"kind": "circle", "center": lift_point(frame, p["center"]), "normal": frame["normal"], "radius": p["radius"]})
            elif p["kind"] == "line":
                out.append({"kind": "line", "a": lift_point(frame, p["from"]), "b": lift_point(frame, p["to"])})
            else:
                out.append({"kind": "arc", "a": lift_point(frame, p["from"]), "m": lift_point(frame, mid_of(p)), "b": lift_point(frame, p["to"])})
        return out

    profiles = [{"outer": loop_in(r["outer"]["pieces"]), "holes": [loop_in(h["pieces"]) for h in r["holes"]]} for r in regions]
    return {"kind": "prism", "profiles": profiles, "dir": frame["normal"], "from": sh["extent"]["min"], "to": sh["extent"]["max"]}


def resolve_hole_axis(axis, ctx):
    """Where a hole's axis runs {origin, dir, radius, oneWay?}, or why it
    cannot."""
    if axis["kind"] == "point":
        if axis["face"]["kind"] != "plane":
            return "A hole is drilled into a flat face — the face picked is not one."
        return {"origin": axis["at"], "dir": scale(axis["face"]["dir"], -1), "radius": None, "oneWay": True}
    if axis["kind"] == "face":
        f = axis["face"]
        if f["kind"] != "cylinder" or not f.get("center"):
            return "The face the hole follows is not a cylinder."
        return {"origin": f["center"], "dir": f["dir"], "radius": f.get("radius")}
    el = next((e for e in ctx["elements"] if e["id"] == axis["id"]), None)
    fit = el and el.get("fit")
    if not fit:
        return "The element the hole follows is gone."
    if fit["kind"] == "cylinder":
        return {"origin": fit["center"], "dir": fit["axis"], "radius": fit["radius"]}
    if fit["kind"] == "circle":
        return {"origin": fit["center"], "dir": fit["normal"], "radius": fit["radius"]}
    if fit["kind"] == "line":
        return {"origin": fit["center"], "dir": fit["dir"], "radius": None}
    return f"A {fit['kind']} has no axis to drill along."


def _queries_of(f):
    return [("edgesWhere", f["edgesWhere"] if f.get("edgesWhere") else _NO), ("facesWhere", f["facesWhere"] if f.get("facesWhere") else _NO)]


def _by_place_of(f):
    still = [k for k in (f.get("regionsByPlace") or []) if k in f["regions"]]
    pick = f.get("regionPick")
    given = pick["given"] if pick and len(pick["keys"]) == len(f["regions"]) and all(k in f["regions"] for k in pick["keys"]) else _NO
    return [("regionsByPlace", still if still else _NO), ("regionPick", given)]


def _pattern_grid(f):
    c2 = f.get("count2")
    return f["mode"] == "linear" and f.get("axis2") is not None and (1 if c2 is None else c2) >= 2


def _g(f, k):
    return f[k] if k in f else _NO


def _finite(*xs):
    return all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in xs)


def resolve_features(features, ctx, regions_of):
    """The feature list as build steps. `ctx`: {sections, elements,
    modelCenter}; `regions_of(sketch feature)` the sketch's regions."""
    sketches = {}
    steps = []

    def failed(f, message):
        steps.append({"kind": "failed", "id": f["id"], "name": f["name"], "message": message})

    def absent(f, i, gone):
        at = next((k for k, x in enumerate(features) if x["id"] == i), -1)
        s = features[at] if at >= 0 else None
        if not s or s["kind"] != "sketch":
            return gone
        named = f"Sketch {num_str(i)} ({s['name']})"
        what = f["kind"] if f["kind"] in ("extrude", "revolve", "loft", "sweep", "sheet") else "feature"
        if s.get("suppressed"):
            return f"{named} is suppressed — build it again (reverse.feature.update {{ set: {{ suppressed: false }} }}), or take it out of this {what}."
        if at > next(k for k, x in enumerate(features) if x is f):
            return (f"{named} stands after this {what} — a feature takes only the sketches above it. Move it above: add the {what} again below the sketch, "
                    f"or roll back to before the {what} (reverse.feature.rollback {{ after }}) and make the sketch there.")
        return gone

    no_names = {"sections": [], "elements": []}

    def on_face_of(sk):
        plane = sk["plane"]
        return {"body": plane["body"], "face": plane["face"], "frame": sk["frame"], **({"offset": plane["offset"]} if plane.get("offset") else {})}

    for f in features:
        if f.get("suppressed"):
            continue
        k = f["kind"]
        if k == "sketch":
            sketches[f["id"]] = f
            if _placed_on_part(f):
                frm = []
                for e in f["sketch"]["entities"]:
                    src = e.get("source")
                    if e.get("projected") and src and "sketch" in src and src["sketch"] not in frm:
                        frm.append(src["sketch"])
                sources = [{"id": i, "frame": sketches[i]["frame"]} for i in frm if i in sketches and i != f["id"]]
                steps.append(_obj(("kind", "sketch"), ("id", f["id"]), ("name", f["name"]), ("frame", f["frame"]),
                                  ("onFace", on_face_of(f) if f["plane"]["kind"] == "bodyFace" else _NO), ("sources", sources)))
            continue
        if k == "shell":
            if not (f["thickness"] > 0):
                failed(f, "The wall needs a thickness.")
            else:
                steps.append(_obj(("kind", "shell"), ("id", f["id"]), ("name", f["name"]), ("body", f["body"]), ("faces", f["faces"]), *_queries_of(f), ("thickness", f["thickness"])))
            continue
        if k == "fillet":
            variable = f.get("variable") or []
            if not f["edges"] and not variable:
                failed(f, "Pick the edges to round.")
            elif f["edges"] and not (f["radius"] > 0):
                failed(f, "The fillet needs a radius.")
            elif any(not (v["radius"][0] > 0 and v["radius"][1] > 0) for v in variable):
                failed(f, "An edge rounded at a varying radius needs both its radii.")
            else:
                steps.append(_obj(("kind", "fillet"), ("id", f["id"]), ("name", f["name"]), ("body", f["body"]), ("edges", f["edges"]), *_queries_of(f), ("radius", f["radius"]),
                                  ("chain", f["chain"]), ("skipFailing", True if f.get("skipFailing") else _NO), ("variable", variable if variable else _NO)))
            continue
        if k == "chamfer":
            mode = f.get("mode")
            if not f["edges"]:
                failed(f, "Pick the edges to chamfer.")
            elif not (f["distance"] > 0):
                failed(f, "The chamfer needs a distance.")
            elif mode == "twoDistances" and not ((f.get("distance2") or 0) > 0):
                failed(f, "The chamfer needs its second distance.")
            elif mode == "distanceAngle" and not (0 < (f.get("angleDeg") or 0) < 90):
                failed(f, "The chamfer’s angle is between 0° and 90°.")
            else:
                sided = [("mode", mode), ("distance2", f["distance2"])] if mode == "twoDistances" else [("mode", mode), ("angleDeg", f["angleDeg"])] if mode == "distanceAngle" else None
                more = sided + [("flip", True if f.get("flip") else _NO)] if sided else []
                steps.append(_obj(("kind", "chamfer"), ("id", f["id"]), ("name", f["name"]), ("body", f["body"]), ("edges", f["edges"]), *_queries_of(f), ("distance", f["distance"]),
                                  ("chain", f["chain"]), ("skipFailing", True if f.get("skipFailing") else _NO), *more))
            continue
        if k == "hole":
            axis = resolve_hole_axis(f["axis"], ctx)
            if isinstance(axis, str):
                failed(f, axis)
            elif not (f["radius"] > 0):
                failed(f, "The hole needs a radius.")
            else:
                steps.append(_obj(("kind", "hole"), ("id", f["id"]), ("name", f["name"]), ("body", f["body"]), ("origin", axis["origin"]), ("dir", axis["dir"]), ("radius", f["radius"]),
                                  ("depth", f["depth"]), ("oneWay", True if axis.get("oneWay") else _NO)))
            continue
        if k == "thread":
            if f["face"]["kind"] != "cylinder":
                why = "A thread is cut on a round face — the face picked is not one."
            else:
                why = thread_problem(f)
                if why is None:
                    if f["length"] is not None and not (f["length"] > 0):
                        why = "The thread needs a length."
                    elif f["length"] is not None and not (f["start"] >= 0):
                        why = "The thread has to start on the face — zero or more in from its end."
            if why:
                failed(f, why)
            else:
                steps.append({"kind": "thread", "id": f["id"], "name": f["name"], "body": f["body"], "face": f["face"], "standard": f["standard"], "diameter": f["diameter"], "pitch": f["pitch"],
                              "leftHanded": f["leftHanded"], "length": f["length"], "start": f["start"], "flip": f["flip"], "offset": f["offset"],
                              "chamfer": f["chamfer"] if f.get("chamfer") is not None else False})
            continue
        if k == "extract":
            if f.get("section") is not None:
                primitive = shadow_primitive(next((s for s in ctx["sections"] if s["id"] == f["section"]), None))
            else:
                element = next((e for e in ctx["elements"] if e["id"] == f.get("element")), None)
                fit = element.get("fit") if element else None
                primitive = _primitive_of(fit and drawn_fit(fit, element.get("assumed"), element.get("extend")), f.get("thickness"))
            if isinstance(primitive, str):
                failed(f, primitive)
            else:
                steps.append(_obj(("kind", "extract"), ("id", f["id"]), ("name", f["name"]), ("primitive", primitive), ("op", f["op"]), ("target", _g(f, "target"))))
            continue
        if k == "cutPlane":
            plane = _resolve_plane(f["plane"], ctx)
            if not plane:
                failed(f, f"The plane this cut is made at is gone ({describe_plane_ref(f['plane'], no_names)}).")
            else:
                steps.append({"kind": "cutPlane", "id": f["id"], "name": f["name"], "body": f["body"], "plane": plane, "keep": f["keep"]})
            continue
        if k == "mirror":
            if f["plane"]["kind"] == "face":
                steps.append({"kind": "mirror", "id": f["id"], "name": f["name"], "body": f["body"], "plane": {"face": f["plane"]["face"]}, "join": f["join"]})
                continue
            plane = _resolve_plane(f["plane"], ctx)
            if not plane:
                failed(f, f"The plane this mirror is about is gone ({describe_plane_ref(f['plane'], no_names)}).")
            else:
                steps.append({"kind": "mirror", "id": f["id"], "name": f["name"], "body": f["body"], "plane": plane, "join": f["join"]})
            continue
        if k == "draft":
            def rad(deg):
                return (deg * math.pi) / 180

            def bad(deg):
                return not (abs(deg) > 1e-9) or abs(deg) >= 89

            groups = f.get("groups")
            more = [("groups", [{"faces": g["faces"], "angleRad": rad(g["angleDeg"])} for g in groups])] if groups else []
            if not f["faces"] or (groups and any(not g["faces"] for g in groups)):
                failed(f, "Pick the faces to draft.")
            elif bad(f["angleDeg"]) or (groups and any(bad(g["angleDeg"]) for g in groups)):
                failed(f, "The draft needs an angle, under 89°.")
            elif f["neutral"]["kind"] == "face":
                steps.append(_obj(("kind", "draft"), ("id", f["id"]), ("name", f["name"]), ("body", f["body"]), ("neutral", {"face": f["neutral"]["face"]}), ("faces", f["faces"]),
                                  *_queries_of(f), ("angleRad", rad(f["angleDeg"])), *more))
            else:
                plane = _resolve_plane(f["neutral"], ctx)
                if not plane:
                    failed(f, f"The neutral plane of this draft is gone ({describe_plane_ref(f['neutral'], no_names)}).")
                else:
                    steps.append(_obj(("kind", "draft"), ("id", f["id"]), ("name", f["name"]), ("body", f["body"]), ("neutral", plane), ("faces", f["faces"]),
                                      *_queries_of(f), ("angleRad", rad(f["angleDeg"])), *more))
            continue
        if k == "moveFace":
            if not f["faces"]:
                failed(f, "No face is picked to move.")
            elif any(not movable_face(x) for x in f["faces"]):
                failed(f, "Only a flat or a cylindrical face can be moved.")
            elif not (abs(f["offset"]) > 1e-9):
                failed(f, "The face has nowhere to move — the offset is zero.")
            else:
                steps.append(_obj(("kind", "moveFace"), ("id", f["id"]), ("name", f["name"]), ("body", f["body"]), ("faces", f["faces"]), *_queries_of(f), ("offset", f["offset"])))
            continue
        if k == "deleteFace":
            if not f["faces"]:
                failed(f, "Pick the faces to delete.")
            else:
                steps.append(_obj(("kind", "deleteFace"), ("id", f["id"]), ("name", f["name"]), ("body", f["body"]), ("faces", f["faces"]), *_queries_of(f)))
            continue
        if k == "import":
            steps.append({"kind": "import", "id": f["id"], "name": f["name"], "file": f["file"]["key"]})
            continue
        if k == "moveBody":
            numbers = [*f["pivot"], *f["translate"], *f["rotate"]]
            if not f["bodies"]:
                failed(f, "No body is picked to move.")
            elif not _finite(*numbers):
                failed(f, "The move needs a number for every distance and angle.")
            else:
                steps.append({"kind": "moveBody", "id": f["id"], "name": f["name"], "bodies": list(f["bodies"]), "matrix": move_matrix(f), "copy": f["copy"]})
            continue
        if k == "offsetBody":
            if not (abs(f["distance"]) > 1e-9):
                failed(f, "The offset needs a distance — out, or in with a negative one.")
            else:
                steps.append({"kind": "offsetBody", "id": f["id"], "name": f["name"], "body": f["body"], "distance": f["distance"], "keep": f["keep"]})
            continue
        if k == "boolean":
            if f["body"] in tools_of(f):
                failed(f, "A body cannot be combined with itself.")
            else:
                steps.append(_obj(("kind", "boolean"), ("id", f["id"]), ("name", f["name"]), ("op", f["op"]), ("body", f["body"]), ("tool", f["tool"]), ("keep", True if f.get("keep") else _NO)))
            continue
        if k == "sheet":
            sketch = sketches.get(f["sketchId"])
            if not sketch:
                failed(f, absent(f, f["sketchId"], "The sketch this sheet is drawn from is gone."))
                continue
            pieces = sketch_pieces(sketch)
            if not pieces:
                failed(f, "The sketch has no pieces to make a sheet of.")
            elif abs(f["to"] - f["from"]) < 1e-9:
                failed(f, "The sheet has no height.")
            else:
                steps.append({"kind": "sheet", "id": f["id"], "name": f["name"], "sketchId": f["sketchId"], "pieces": pieces, "dir": sketch["frame"]["normal"], "from": f["from"], "to": f["to"]})
            continue
        if k == "trim":
            bodies = [t["id"] for t in f["tools"] if t["kind"] == "body"]
            primitives = []
            lost = None
            for t in f["tools"]:
                if t["kind"] != "element":
                    continue
                el = next((e for e in ctx["elements"] if e["id"] == t["id"]), None)
                fit = el and el.get("fit")
                if not fit:
                    lost = "An element this trim cuts with is gone."
                    break
                if fit["kind"] == "plane":
                    primitives.append({"kind": "plane", "origin": fit["center"], "normal": fit["normal"], "basisU": fit["basisU"], "basisV": fit["basisV"]})
                else:
                    p = _primitive_of(fit, 1)
                    if isinstance(p, str) or p["kind"] == "slab":
                        lost = f"A {fit['kind']} cannot cut space for a trim."
                        break
                    primitives.append(p)
            if lost:
                failed(f, lost)
            elif not bodies and not primitives:
                failed(f, "The trim has no surfaces to close.")
            elif not (f["tolerance"] > 0) or not (0 < f["overlap"] <= 1):
                failed(f, "The trim needs a tolerance above zero and an overlap between 0 and 1.")
            else:
                steps.append({"kind": "trim", "id": f["id"], "name": f["name"], "bodies": bodies, "primitives": primitives, "tolerance": f["tolerance"], "overlap": f["overlap"]})
            continue
        if k == "surface":
            stale = f.get("regionStale")
            if len(f["region"]) < SURFACE_MIN_REGION:
                failed(f, f"The region holds {len(f['region'])} points; a surface needs at least {SURFACE_MIN_REGION}.")
            elif stale:
                said = f": {stale}" if isinstance(stale, str) else " yet"
                failed(f, f"The box its region is read in moved with the parameters, and the points in it were not read again{said} — reverse.feature.update {{ set: {{ region: {{ box }} }} }} reads them.")
            else:
                at = next(i for i, x in enumerate(features) if x is f)
                ref_surfaces = [{"id": o["id"], "name": o["name"]} for o in features[:at] if o["kind"] == "surface" and (o.get("shape") or "freeform") != "freeform"]
                box = f.get("regionBox")
                steps.append(_obj(("kind", "surface"), ("id", f["id"]), ("name", f["name"]), ("region", f["region"]), ("fit", f["fit"]), ("shape", f.get("shape") or "freeform"),
                                  ("constrain", f["constrain"] if f.get("constrain") is not None else {"mode": "auto"}), ("refs", constrain_refs(ctx["elements"])),
                                  ("refSurfaces", ref_surfaces), ("facing", box["normal"] if box and box.get("normal") else _NO)))
            continue
        if k == "network":
            if not f["curves"]:
                failed(f, "Place a patch: click its corners on the scan.")
            else:
                steps.append(_obj(("kind", "network"), ("id", f["id"]), ("name", f["name"]), ("nodes", f["nodes"]), ("curves", f["curves"]), ("cells", f["cells"]),
                                  ("spans", _g(f, "spans")), ("fit", f["fit"])))
            continue
        if k == "split":
            if not f["tools"]:
                failed(f, "Pick a sheet or a body to split with.")
            elif f["body"] in f["tools"]:
                failed(f, "A body cannot split itself.")
            elif f["keep"] == "between" and len(f["tools"]) < 2:
                failed(f, "Keeping what lies between the sheets takes two sheets or more — the skins the wall lies between.")
            else:
                steps.append(_obj(("kind", "split"), ("id", f["id"]), ("name", f["name"]), ("body", f["body"]), ("tools", f["tools"]), ("keep", f["keep"]), ("tolerance", f["tolerance"]),
                                  ("overlap", f["overlap"]), ("within", f["within"] if f.get("within") is not None else _NO)))
            continue
        if k == "loft":
            if len(f["sketches"]) < 2:
                failed(f, "A loft needs two or more sketches.")
                continue
            profiles = []
            through = []
            reason = None
            for i in f["sketches"]:
                sketch = sketches.get(i)
                if not sketch:
                    reason = absent(f, i, "A sketch this loft runs through is gone.")
                    break
                profile = loft_profile(sketch, regions_of(sketch))
                if isinstance(profile, str):
                    reason = profile
                    break
                profiles.append(profile)
                through.append(sketch)
            if reason is None:
                reason = loft_problem(through, profiles)
            if reason:
                failed(f, reason)
            else:
                steps.append(_obj(("kind", "loft"), ("id", f["id"]), ("name", f["name"]), ("profiles", profiles), ("sketches", f["sketches"]), ("sketchNames", [s["name"] for s in through]),
                                  ("ruled", f["ruled"]), ("op", f["op"]), ("target", _g(f, "target"))))
            continue
        if k == "sweep":
            profile_sketch = sketches.get(f["profile"])
            if f.get("route"):
                swept = absent(f, f["profile"], "The sketch of the profile is gone.") if not profile_sketch else route_sweep_geometry(profile_sketch, regions_of(profile_sketch), f["route"])
                if isinstance(swept, str):
                    failed(f, swept)
                else:
                    steps.append(_obj(("kind", "sweep"), ("id", f["id"]), ("name", f["name"]), *swept.items(), ("sketches", [f["profile"]]), ("route", f["route"]), ("op", f["op"]),
                                      ("target", _g(f, "target"))))
                continue
            path = f.get("path")
            path_sketch = None if path is None else sketches.get(path)
            if f["profile"] == path:
                swept = "The profile and the path are one sketch — draw them in two."
            elif not profile_sketch:
                swept = absent(f, f["profile"], "The sketch of the profile is gone.")
            elif not path_sketch:
                swept = absent(f, path if path is not None else f["profile"], "The sketch of the path is gone.")
            else:
                swept = sweep_geometry(profile_sketch, regions_of(profile_sketch), path_sketch)
            if isinstance(swept, str):
                failed(f, swept)
            else:
                steps.append(_obj(("kind", "sweep"), ("id", f["id"]), ("name", f["name"]), *swept.items(), ("sketches", [f["profile"], path]), ("op", f["op"]), ("target", _g(f, "target"))))
            continue
        if k == "thicken":
            if not (f["thickness"] > 0):
                failed(f, "The sheet needs a thickness.")
            else:
                steps.append(_obj(("kind", "thicken"), ("id", f["id"]), ("name", f["name"]), ("sheet", f["sheet"]), ("thickness", f["thickness"]), ("side", f["side"]), ("op", f["op"]),
                                  ("target", _g(f, "target"))))
            continue
        if k == "pattern":
            axis = resolve_axis(f["axis"], None, ctx)
            grid = _pattern_grid(f)
            axis2 = resolve_axis(f["axis2"], None, ctx) if grid else None
            if not axis or (grid and not axis2):
                failed(f, "The axis this pattern runs about is gone.")
            elif not (f["count"] >= 2):
                failed(f, "A pattern needs a count of two or more.")
            elif not (f["step"] > 0):
                failed(f, "The pattern needs an angle." if f["mode"] == "circular" else "The pattern needs a spacing.")
            elif grid and not ((f.get("step2") or 0) > 0):
                failed(f, "The second direction needs a spacing.")
            elif grid and abs(dot(axis["dir"], axis2["dir"])) > 1 - 1e-9:
                failed(f, "The two directions of the grid run the same way.")
            else:
                steps.append(_obj(("kind", "pattern"), ("id", f["id"]), ("name", f["name"]), ("body", f["body"]), ("mode", f["mode"]), ("origin", axis["origin"]), ("dir", axis["dir"]),
                                  ("count", f["count"]), ("step", f["step"]),
                                  ("grid", {"dir": axis2["dir"], "count": f["count2"], "step": f["step2"]} if grid else _NO)))
            continue
        _extrude_or_revolve(f, ctx, sketches, steps, regions_of, absent, on_face_of)
    return steps


def _extrude_or_revolve(f, ctx, sketches, steps, regions_of, absent, on_face_of):
    face_profile = f.get("face") if f["kind"] == "extrude" else None
    sketch = None if face_profile else sketches.get(f["sketchId"])
    if not sketch and not face_profile:
        steps.append({"kind": "failed", "id": f["id"], "name": f["name"], "message": absent(f, f["sketchId"], "The sketch this feature builds on is gone.")})
        return
    on_face = [("onFace", on_face_of(sketch))] if sketch and sketch["plane"]["kind"] == "bodyFace" else []
    profiles = picked_profiles(f, sketch, regions_of) if sketch else []
    if isinstance(profiles, str):
        steps.append({"kind": "failed", "id": f["id"], "name": f["name"], "message": profiles})
        return
    if f["kind"] == "extrude":
        if abs(f.get("draftDeg") or 0) >= 89:
            steps.append({"kind": "failed", "id": f["id"], "name": f["name"], "message": "The taper has to stay under 89° — the sides would lie down flat."})
            return
        d = face_profile["face"]["dir"] if face_profile else sketch["frame"]["normal"]
        origin = face_profile["face"]["centroid"] if face_profile else sketch["frame"]["origin"]
        direction = f.get("direction")
        along = normalize(direction) if direction else None
        if direction and (not along or abs(dot(along, normalize(d) or d)) < math.sin(MIN_SWEEP_RAD)):
            runs = "along the sketch plane" if along else "nowhere"
            steps.append({"kind": "failed", "id": f["id"], "name": f["name"],
                          "message": f"The direction runs {runs} — the extrusion would have no thickness; it has to leave the plane at {num_str((MIN_SWEEP_RAD * 180) / math.pi)}° at least."})
            return

        def limit(ref):
            p = _resolve_plane(ref, ctx)
            return p if p else f"The plane this extrusion reaches to is gone ({describe_plane_ref(ref, {'sections': [], 'elements': []})})."

        e = f["extent"]
        until = _NO
        ek = e["kind"]
        if ek == "toFace":
            frm = to = e["from"]
            until = {"kind": "face", "body": e["body"], "face": e["face"]}
        elif ek == "toBody":
            frm = to = e["from"]
            until = {"kind": "body", "body": e["body"], "reverse": bool(e.get("reverse"))}
        elif ek in ("toNext", "toLast"):
            frm = to = e["from"]
            until = {"kind": "next" if ek == "toNext" else "last", "reverse": bool(e.get("reverse")), "against": "all" if f.get("target") is None else [f["target"]], "cutting": f["op"] == "cut"}
        elif ek == "distance":
            frm, to = e["from"], e["to"]
        elif ek == "symmetric":
            frm, to = -e["total"] / 2, e["total"] / 2
        elif ek == "toPlane":
            p = limit(e["plane"])
            if isinstance(p, str):
                steps.append({"kind": "failed", "id": f["id"], "name": f["name"], "message": p})
                return
            frm, to = e["from"], p
        else:
            a = limit(e["a"])
            b = limit(e["b"])
            if isinstance(a, str) or isinstance(b, str):
                steps.append({"kind": "failed", "id": f["id"], "name": f["name"], "message": a if isinstance(a, str) else b})
                return
            frm, to = a, b
        steps.append(_obj(("kind", "extrude"), ("id", f["id"]), ("name", f["name"]), ("sketchId", _g(f, "sketchId")), ("profiles", profiles), ("regions", f["regions"]), *_by_place_of(f),
                          ("dir", d), ("origin", origin), ("from", frm), ("to", to), ("until", until), ("draftDeg", f.get("draftDeg") or 0), ("along", along if along else _NO),
                          ("op", f["op"]), ("target", _g(f, "target")), *on_face, ("faceProfile", face_profile if face_profile else _NO)))
        return
    axis = resolve_axis(f["axis"], sketch, ctx)
    if not axis:
        steps.append({"kind": "failed", "id": f["id"], "name": f["name"], "message": "The axis this revolve turns about is gone."})
        return
    pitch = f["pitch"] if _finite(f.get("pitch")) else 0
    if not (f["angleDeg"] > 0):
        steps.append({"kind": "failed", "id": f["id"], "name": f["name"], "message": "The revolve needs an angle."})
        return
    if pitch == 0 and f["angleDeg"] > FULL_TURN_DEG + 1e-9:
        steps.append({"kind": "failed", "id": f["id"], "name": f["name"], "message": f"A revolve turns {FULL_TURN_DEG}° at most — give it a pitch to coil on past a full turn."})
        return
    angle_deg = min(f["angleDeg"], revolve_max_deg(pitch))
    in_sketch = [("axisInSketch", True), ("axisLine", f["axis"]["entity"])] if f["axis"]["kind"] == "sketchLine" else []
    steps.append(_obj(("kind", "revolve"), ("id", f["id"]), ("name", f["name"]), ("sketchId", f["sketchId"]), ("profiles", profiles), ("regions", f["regions"]), *_by_place_of(f),
                      ("origin", axis["origin"]), ("dir", axis["dir"]), ("angleRad", (angle_deg * math.pi) / 180), ("pitch", pitch),
                      ("leftHanded", pitch != 0 and bool(f.get("leftHanded"))), ("op", f["op"]), ("target", _g(f, "target")), *on_face, *in_sketch))
