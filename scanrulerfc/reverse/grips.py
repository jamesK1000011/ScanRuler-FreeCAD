# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/state/reGripSlice.ts, state/reDrafts.ts (gripFieldValue, gripSlotPath), state/reFeatureHelpers.ts (gripSlotPaths), app/useReverseWorkspace.ts (the grips a draft wears), ui/reLength.ts (readField)
# SPDX-License-Identifier: AGPL-3.0-only
#
# The grips of a feature being set up and what they do to it: which grips a
# feature wears (grips_of), what a drag of one makes of it (Drag), the number
# the field on a grip shows (field_value) and what a number or an expression
# typed there makes of it (set_value, read_field). Everything works on the
# feature record the editor holds (reverse/editor.py) — the fields
# reverse_feature_add takes — and hands back a new record; nothing here
# draws or touches FreeCAD.

import math
import re

from .features import extent_ends_on_part, revolve_max_deg
from .parameters import unlink_slot
from .preview import (MAX_TAPER_DEG, drag_extrude_extent, drag_length, drag_revolve_angle, drag_taper, edge_grip, extrude_grips, extrude_grips_at, face_grip,
                      is_move_grip_side, move_grip, move_grip_slot, move_grips, revolve_grip, taper_grip, taper_span)
from .units import MM_PER_INCH
from .vec import normalize

LENGTH_UNIT = "mm"
ANGLE_UNIT = "°"
SIGNED_NUMBER = re.compile(r"^[+-]?\s*(\d+\.?\d*|\.\d+)(e[+-]?\d+)?$", re.IGNORECASE)


def _hundredths(v):
    return math.floor(v * 100 + 0.5) / 100


# ---- which grips ------------------------------------------------------------------------------


def _sketch(features, sketch_id):
    return next((f for f in features if f.get("kind") == "sketch" and f.get("id") == sketch_id), None)


def grips_of(f, features=(), ctx=None):
    """The grips a feature being set up wears: arrows on an extrude's faces
    and its far edge, a ring about a revolve's axis, an arrow on a fillet's
    first edge, a shell's opened face or a moved face, a Move's gizmo.
    `features` are the part's (for the sketch); `ctx` the scan's context
    (for an axis on the scan). Empty when there is nothing to hold."""
    if not f:
        return []
    k = f.get("kind")
    if k in ("fillet", "chamfer") and f.get("edges"):
        g = edge_grip(_fp(f["edges"][0]))
        return [g] if g else []
    if k == "shell" and f.get("faces"):
        return [face_grip(_fp(f["faces"][0]))]
    if k == "moveFace" and f.get("faces"):
        return [move_grip(_fp(f["faces"][0]), f.get("offset") or 0)]
    if k == "moveBody" and f.get("bodies") and f.get("pivot") is not None:
        return move_grips({"pivot": f["pivot"], "translate": f.get("translate") or [0, 0, 0], "rotate": f.get("rotate") or [0, 0, 0]})
    if k == "extrude" and f.get("face"):
        fp = _fp(f["face"].get("face") or f["face"])
        return extrude_grips_at(fp["centroid"], f.get("direction") or normalize(fp["dir"]) or [0, 0, 1], f["extent"])
    if k not in ("extrude", "revolve") or f.get("sketchId") is None:
        return []
    sk = _sketch(features, f["sketchId"])
    if not sk or not sk.get("frame"):
        return []
    from .regions import find_regions

    keys = f.get("regions") or []
    regions = [r for r in find_regions(sk["sketch"]) if r["key"] in keys]
    if k == "extrude":
        # Swept askew, the arrows go the way it is swept; the taper's grip
        # stands on a side square to the plane, so it stays away.
        taper = None if f.get("direction") else taper_grip(sk["frame"], regions, f["extent"], -(f.get("draftDeg") or 0))
        return extrude_grips(sk["frame"], regions, f["extent"], f.get("direction")) + ([taper] if taper else [])
    if not f.get("axis"):
        return []
    from .resolve import resolve_axis

    try:
        axis = resolve_axis(f["axis"], sk, ctx or {"sections": [], "elements": [], "modelCenter": [0, 0, 0]})
    except (KeyError, TypeError, ValueError):
        axis = None
    ring = revolve_grip(sk["frame"], regions, axis) if axis else None
    return [ring] if ring else []


def _fp(x):
    return x.get("fingerprint", x) if isinstance(x, dict) else x


# ---- the number a grip drags --------------------------------------------------------------------


def slot_path(f, side):
    """gripSlotPath: the slot a grip's number is — the one an expression typed
    on the grip is kept under."""
    if side == "taper":
        return "taper"
    if side in ("extrudeFrom", "extrudeTo"):
        if (f.get("extent") or {}).get("kind") == "symmetric":
            return "extent.total"
        return "extent.from" if side == "extrudeFrom" else "extent.to"
    if side == "turn":
        return "angleDeg"
    if side == "radius":
        return "distance" if f.get("kind") == "chamfer" else "radius"
    if side == "thickness":
        return "thickness"
    if side == "move":
        return "offset"
    if is_move_grip_side(side):
        field, axis = move_grip_slot(side)
        return f"{field}.{'xyz'[axis]}"
    return None


def slot_paths(f, side):
    """gripSlotPaths: the slots a drag of the grip, or a number typed on it,
    writes — the expression behind each is let go."""
    if side == "turn":
        return ["angleDeg", "turns", "height"]
    if side == "radius":
        return ["radius", "distance"]
    p = slot_path(f, side)
    return [p] if p else []


def _unlink(f, paths):
    for p in paths:
        f = unlink_slot(f, p)
    return f


def _base(f, side):
    k = f.get("kind")
    if k == "extrude" and side == "taper":
        d = f.get("draftDeg") or 0
        return (0 if d == 0 else -d), ANGLE_UNIT
    if k == "extrude" and side in ("extrudeFrom", "extrudeTo"):
        e = f["extent"]
        if e["kind"] == "distance":
            return (e["from"] if side == "extrudeFrom" else e["to"]), LENGTH_UNIT
        if e["kind"] == "symmetric":
            return e["total"], LENGTH_UNIT
        if extent_ends_on_part(e) and side == "extrudeFrom":
            return e["from"], LENGTH_UNIT
        return None
    if k == "revolve" and side == "turn":
        return f["angleDeg"], ANGLE_UNIT
    if side == "radius" and k == "fillet":
        return f["radius"], LENGTH_UNIT
    if side == "radius" and k == "chamfer":
        return f["distance"], LENGTH_UNIT
    if side == "thickness" and k == "shell":
        return f["thickness"], LENGTH_UNIT
    if side == "move" and k == "moveFace":
        return f.get("offset") or 0, LENGTH_UNIT
    if k == "moveBody" and is_move_grip_side(side):
        field, axis = move_grip_slot(side)
        return (f.get(field) or [0, 0, 0])[axis], (LENGTH_UNIT if field == "translate" else ANGLE_UNIT)
    return None


def field_value(f, side):
    """gripFieldValue: {value, unit, expr?} the field on a grip shows, or None
    while the grip's number is not a number of its own (an extrude reaching
    to a plane). A length is in millimetres here; the view shows it in the
    units shown (display_value)."""
    if not f or not side:
        return None
    b = _base(f, side)
    if b is None:
        return None
    out = {"value": b[0], "unit": b[1]}
    path = slot_path(f, side)
    expr = (f.get("exprs") or {}).get(path) if path else None
    if expr is not None:
        out["expr"] = expr
    return out


def is_angle_side(side):
    return side == "taper" or side == "turn" or side.startswith("turn")


# ---- a drag -------------------------------------------------------------------------------------


class Drag:
    """gripDrag: a drag of one grip, from 'start' to 'end'. move(f, delta)
    hands back the record as the drag has it — delta millimetres pulled out
    along an arrow (negative in) or degrees turned about a ring, since the
    drag began. Whole hundredths of a millimetre and tenths of a degree, as
    a dragged number is read off the field."""

    def __init__(self, f, side):
        self.side = side
        self.start = None
        k = f.get("kind")
        if k == "moveBody" and is_move_grip_side(side):
            field, axis = move_grip_slot(side)
            self.start = ("length", (f.get(field) or [0, 0, 0])[axis])
        elif k == "extrude" and side == "taper":
            span = taper_span(f["extent"])
            if span:
                self.start = ("taper", -(f.get("draftDeg") or 0), abs(span["end"] - span["start"]))
        elif k == "extrude":
            self.start = ("extent", dict(f["extent"]))
        elif k == "revolve" and side == "turn":
            self.start = ("angle", f["angleDeg"])
        elif k == "moveFace" and side == "move":
            self.start = ("length", f.get("offset") or 0)
        elif side in ("radius", "thickness"):
            cur = f.get("radius") if k == "fillet" else f.get("distance") if k == "chamfer" else f.get("thickness") if k == "shell" else None
            if cur is not None:
                self.start = ("length", cur)

    def move(self, f, delta):
        s, side, k = self.start, self.side, f.get("kind")
        if s is None:
            return f
        if k == "moveBody":
            field, axis = move_grip_slot(side)
            nxt = list(f.get(field) or [0, 0, 0])
            nxt[axis] = _hundredths(s[1] + delta) if field == "translate" else math.floor(s[1] + delta + 0.5)
            return _unlink({**f, field: nxt}, [slot_path(f, side)])
        if s[0] == "taper":
            taper = drag_taper(s[1], s[2], delta)
            return _unlink({**f, "draftDeg": 0 if taper == 0 else -taper}, ["taper"])
        if s[0] == "extent":
            nxt = drag_extrude_extent(s[1], side, delta)
            if nxt["kind"] == "distance":
                nxt = {**nxt, "from": _hundredths(nxt["from"]), "to": _hundredths(nxt["to"])}
            elif nxt["kind"] == "symmetric":
                nxt = {**nxt, "total": _hundredths(nxt["total"])}
            elif extent_ends_on_part(nxt):
                nxt = {**nxt, "from": _hundredths(nxt["from"])}
            return _unlink({**f, "extent": nxt}, slot_paths(f, side))
        if s[0] == "angle":
            return _unlink({**f, "angleDeg": drag_revolve_angle(s[1], delta, revolve_max_deg(f.get("pitch") or 0))}, slot_paths(f, side))
        if k == "moveFace":
            # Signed: the arrow pulls the face out and pushes it in.
            return _unlink({**f, "offset": _hundredths(s[1] + delta)}, ["offset"])
        v = _hundredths(drag_length(s[1], delta))
        if k == "fillet":
            return _unlink({**f, "radius": v}, ["radius"])
        if k == "chamfer":
            return _unlink({**f, "distance": v}, ["distance"])
        if k == "shell":
            return _unlink({**f, "thickness": v}, ["thickness"])
        return f


def set_value(f, side, value):
    """setGripValue: a number typed on the grip, standing on its own (the
    expression behind it, if any, let go). The record unchanged for a value
    that is not a number or a grip with no number there."""
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        return f
    k = f.get("kind")
    if k == "extrude" and side == "taper":
        v = max(-MAX_TAPER_DEG, min(MAX_TAPER_DEG, value))
        return _unlink({**f, "draftDeg": 0 if v == 0 else -v}, ["taper"])
    if k == "extrude" and side in ("extrudeFrom", "extrudeTo"):
        e = f["extent"]
        if e["kind"] == "distance":
            nxt = {**e, "from": value} if side == "extrudeFrom" else {**e, "to": value}
        elif e["kind"] == "symmetric":
            nxt = {**e, "total": abs(value)}
        elif extent_ends_on_part(e) and side == "extrudeFrom":
            nxt = {**e, "from": value}
        else:
            return f
        return _unlink({**f, "extent": nxt}, slot_paths(f, side))
    if k == "revolve" and side == "turn":
        return _unlink({**f, "angleDeg": min(abs(value), revolve_max_deg(f.get("pitch") or 0))}, slot_paths(f, side))
    if side == "radius" and k == "fillet":
        return _unlink({**f, "radius": abs(value)}, ["radius"])
    if side == "radius" and k == "chamfer":
        return _unlink({**f, "distance": abs(value)}, ["distance"])
    if side == "thickness" and k == "shell":
        return _unlink({**f, "thickness": abs(value)}, ["thickness"])
    if side == "move" and k == "moveFace":
        return _unlink({**f, "offset": value}, ["offset"])
    if k == "moveBody" and is_move_grip_side(side):
        field, axis = move_grip_slot(side)
        nxt = list(f.get(field) or [0, 0, 0])
        nxt[axis] = value
        return _unlink({**f, field: nxt}, [slot_path(f, side)])
    return f


def with_expr(f, path, expr):
    """setDraftExpr: an expression kept beside the number under its slot."""
    if not path or not expr:
        return f
    return {**f, "exprs": {**(f.get("exprs") or {}), path: expr}}


# ---- what is typed --------------------------------------------------------------------------------


def display_value(value, unit, units="mm"):
    """A length in the units shown (mm or in); an angle as it is."""
    return value / MM_PER_INCH if unit == LENGTH_UNIT and units == "in" else value


def unit_word(unit, units="mm"):
    return units if unit == LENGTH_UNIT else unit


def field_text(field, units="mm"):
    """What the field on a grip shows: the expression as it is written, or
    the number to two decimals in millimetres, one more in inches."""
    if field.get("expr") is not None:
        return field["expr"]
    places = 3 if field["unit"] == LENGTH_UNIT and units == "in" else 2
    v = round(display_value(field["value"], field["unit"], units), places)
    return format(v, "g") if abs(v) < 1e15 else str(v)


def read_field(text, kind, scope, units="mm"):
    """readField: what a field takes from the text typed — {ok, value, expr}
    or {ok: False, error}. A plain number is read in the units shown (a
    length in inches turned to millimetres) and kept as a number; anything
    else is an expression over the parameters, kept as typed."""
    from .expression import evaluate_for

    t = (text or "").strip()
    if not t:
        return {"ok": False, "error": "nothing typed"}
    r = evaluate_for(t, kind, scope or (lambda name: None))
    if not r["ok"]:
        return {"ok": False, "error": r["error"]}
    plain = bool(SIGNED_NUMBER.match(t))
    if kind == "length" and units == "in" and plain:
        return {"ok": True, "value": r["value"] * MM_PER_INCH, "expr": None}
    return {"ok": True, "value": r["value"], "expr": None if plain else t}
