# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/core/preview.ts
# SPDX-License-Identifier: AGPL-3.0-only
#
# What a feature being set up shows in the 3D view besides its ghost body:
# the grips that drag its numbers. An extrude wears an arrow on each face
# the distance sets — pull the far one and the body grows — and one on the
# far edge that leans the sides; a revolve wears a ring about its axis whose
# turn is the angle. Geometry only, in the part's coordinates: the view
# (scanrulerfc/editor_view.py) draws it.
#
# A grip is a dict: side, shape ("arrow" or "ring"), position, dir, size
# (an arrow's length or a ring's radius: millimetres, or pixels on the
# screen with pixels: True), standoff (how far along dir an arrow stands off
# position, in the units of size) and color (its own, where it is not the
# feature's).

import math

from .features import FULL_TURN_DEG
from .move import moved_pivot, ring_axes
from .profiles import lift_point
from .vec import add_scaled, cross, dot, length, normalize, sub

MOVE_GRIP_SIDES = ("moveX", "moveY", "moveZ", "turnX", "turnY", "turnZ")
FEATURE_SIDES = ("extrudeFrom", "extrudeTo", "taper", "turn", "radius", "thickness", "move") + MOVE_GRIP_SIDES

# The app's own red, green and blue, as the view's axis triad wears them.
MOVE_AXIS_COLORS = ("#e5534b", "#2e7d46", "#1877c0")

# The steepest taper the box and the grip take, degrees either way.
MAX_TAPER_DEG = 85
# How long a feature's arrow is on the screen, in pixels, at any zoom.
ARROW_PX = 44
# The Move gizmo's rings on the screen, in pixels, at any zoom.
MOVE_GIZMO_PX = 90


def move_grip_slot(side):
    """Which of a Move's six numbers a gizmo grip drags: (field, axis)."""
    return ("translate" if side.startswith("move") else "rotate"), (0 if side.endswith("X") else 1 if side.endswith("Y") else 2)


def is_move_grip_side(side):
    return side in MOVE_GRIP_SIDES


def is_feature_side(side):
    return side in FEATURE_SIDES


def _arrow(side, position, d, size=ARROW_PX):
    return {"side": side, "shape": "arrow", "position": list(position), "dir": list(d), "size": size, "pixels": True}


def _polygon_centroid2(poly):
    a = cx = cy = 0.0
    n = len(poly)
    for i in range(n):
        x0, y0 = poly[i][0], poly[i][1]
        x1, y1 = poly[(i + 1) % n][0], poly[(i + 1) % n][1]
        f = x0 * y1 - x1 * y0
        a += f
        cx += (x0 + x1) * f
        cy += (y0 + y1) * f
    if abs(a) < 1e-12:
        if n == 0:
            return [0.0, 0.0]
        return [sum(p[0] for p in poly) / n, sum(p[1] for p in poly) / n]
    return [cx / (3 * a), cy / (3 * a)]


def regions_centroid(regions):
    """Where the picked profiles sit on the sheet: the area-weighted middle of
    their outer loops, or the sheet origin with nothing picked."""
    x = y = w = 0.0
    for r in regions:
        cx, cy = _polygon_centroid2(r["outer"]["polygon"])
        a = max(abs(r["area"]), 1e-9)
        x += cx * a
        y += cy * a
        w += a
    return [x / w, y / w] if w > 0 else [0.0, 0.0]


def extrude_grips(frame, regions, extent, along=None):
    """An arrow on the start face pointing back along the normal and one on
    the end face pointing forward, each through the profiles' centroid."""
    if not regions:
        return []
    return extrude_grips_at(lift_point(frame, regions_centroid(regions)), along or frame["normal"], extent)


def extrude_grips_at(centre, normal, extent):
    """The grips of an extrude through a given centre along a given normal —
    a face pulled straight has no regions, only its centroid and normal."""
    n = list(normal)
    back = [-n[0], -n[1], -n[2]]

    def arrow(side, offset, d):
        return _arrow(side, add_scaled(centre, n, offset), d)

    k = extent["kind"]
    if k == "distance":
        # The lower face wears the back-pointing arrow whichever number it
        # is, so pulling an arrow outward always grows the body.
        if extent["to"] >= extent["from"]:
            return [arrow("extrudeFrom", extent["from"], back), arrow("extrudeTo", extent["to"], n)]
        return [arrow("extrudeFrom", extent["from"], n), arrow("extrudeTo", extent["to"], back)]
    if k == "symmetric":
        return [arrow("extrudeFrom", -extent["total"] / 2, back), arrow("extrudeTo", extent["total"] / 2, n)]
    if k in ("toPlane", "toFace", "toBody"):
        return [arrow("extrudeFrom", extent["from"], back)]
    if k in ("toNext", "toLast"):
        # The start's arrow points away from where the body goes.
        return [arrow("extrudeFrom", extent["from"], n if extent.get("reverse") else back)]
    return []


def taper_span(extent):
    """Where an extrude's taper leans from and the end it leans furthest to,
    as offsets along the normal; None for an extent with an end found on the
    part."""
    if extent["kind"] == "symmetric":
        return {"start": 0, "end": extent["total"] / 2}
    if extent["kind"] != "distance":
        return None
    lo = min(extent["from"], extent["to"])
    hi = max(extent["from"], extent["to"])
    start = min(max(0, lo), hi)
    # The far end; of two as far, To.
    end = extent["to"] if abs(extent["to"] - start) >= abs(extent["from"] - start) else extent["from"]
    return {"start": start, "end": end}


def taper_grip(frame, regions, extent, taper_deg):
    """The taper grip: an arrow on the far edge of the body, pointing out of
    it — pull it out and the sides lean out. It stands where the outline
    reaches furthest along the sheet's X, half way along the side there,
    carried to the far end and out by the lean. None with no profile, or an
    extent with no far end to stand on."""
    span = taper_span(extent)
    if not span or not regions:
        return None
    run = abs(span["end"] - span["start"])
    if not run > 1e-6:
        return None
    xs = [p[0] for r in regions for p in r["outer"]["polygon"]]
    if not xs:
        return None
    top = max(xs)
    tol = 1e-6 * max(1, abs(top))
    ys = [p[1] for r in regions for p in r["outer"]["polygon"] if p[0] >= top - tol]
    edge = lift_point(frame, [top, (min(ys) + max(ys)) / 2])
    lean = math.tan(taper_deg * math.pi / 180)
    position = add_scaled(add_scaled(edge, frame["normal"], span["end"]), frame["basisU"], run * lean)
    return _arrow("taper", position, frame["basisU"], ARROW_PX * 0.8)


def _round10(v):
    return math.floor(v * 10 + 0.5) / 10


def drag_taper(start_deg, run, delta):
    """The taper a drag of the taper grip makes: delta millimetres pulled out
    along the arrow, run the extrude's length from where the taper starts.
    Degrees, positive leaning out, to a tenth, within MAX_TAPER_DEG."""
    if not run > 1e-9:
        return start_deg
    out = run * math.tan(start_deg * math.pi / 180) + delta
    deg = _round10(math.atan2(out, run) * 180 / math.pi)
    return 0 if deg == 0 else max(-MAX_TAPER_DEG, min(MAX_TAPER_DEG, deg))


def drag_extrude_extent(start, side, delta):
    """The extent an extrude grip's drag makes: delta millimetres pulled along
    the arrow since the drag began. Outward is always growth."""
    k = start["kind"]
    if k == "distance":
        forward = start["to"] >= start["from"]
        if side == "extrudeTo":
            return {**start, "to": start["to"] + (delta if forward else -delta)}
        if side == "extrudeFrom":
            return {**start, "from": start["from"] - (delta if forward else -delta)}
        return start
    if k == "symmetric":
        # Either arrow pulled out by d grows the whole by 2d.
        return {**start, "total": max(start["total"] + 2 * delta, 0.01)}
    if k in ("toPlane", "toFace", "toBody"):
        return {**start, "from": start["from"] - delta} if side == "extrudeFrom" else start
    if k in ("toNext", "toLast"):
        return {**start, "from": start["from"] - (-delta if start.get("reverse") else delta)} if side == "extrudeFrom" else start
    return start


def extent_through_point(extent, end, height):
    """The extent once one of its ends ("from" or "to") is put through a
    point clicked on the part, height over the sketch plane along its
    normal. None when the point gives the extent nothing."""
    if not math.isfinite(height):
        return None
    h = math.floor(height * 100 + 0.5) / 100
    k = extent["kind"]
    if k == "distance":
        nxt = {**extent, "to": h} if end == "to" else {**extent, "from": h}
        return None if abs(nxt["to"] - nxt["from"]) < 1e-9 else nxt
    if k == "symmetric":
        return None if abs(h) < 1e-9 else {**extent, "total": abs(h) * 2}
    if k in ("toPlane", "toFace", "toBody", "toNext", "toLast"):
        return {**extent, "from": h} if end == "from" else None
    return None


def prism_stretch(origin, normal, from0, to0, from1, to1):
    """A straight extrude's ghost stretched instead of built again: the
    affine map carrying a prism from from0..to0 along normal onto from1..to1,
    as a row-major 3 x 4 (move.py's form). None for a prism of no height."""
    span = to0 - from0
    if abs(span) < 1e-9:
        return None
    s = (to1 - from1) / span
    shift = from1 - s * from0 - (s - 1) * dot(origin, normal)
    m = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0]
    for r in range(3):
        for c in range(3):
            m[r * 4 + c] += (s - 1) * normal[r] * normal[c]
        m[r * 4 + 3] = shift * normal[r]
    return m


def revolve_grip(frame, regions, axis):
    """A ring about the axis through the plane of the profiles' centroid, as
    wide as the centroid's distance from the axis. None when the centroid
    lies on the axis."""
    if not regions:
        return None
    centre = lift_point(frame, regions_centroid(regions))
    d = normalize(axis["dir"])
    if not d:
        return None
    foot = add_scaled(axis["origin"], d, dot(sub(centre, axis["origin"]), d))
    radius = length(sub(centre, foot))
    if radius < 1e-6:
        return None
    return {"side": "turn", "shape": "ring", "position": foot, "dir": d, "size": radius}


def drag_length(start, delta):
    """A length dragged, kept positive."""
    return max(start + delta, 0.01)


def edge_grip(edge):
    """A fillet's or a chamfer's grip: an arrow at the middle of its first
    edge, into the body along the bisector of the two faces' normals."""
    faces = edge.get("faces") or []
    if len(faces) < 2:
        return None
    b = normalize([faces[0]["dir"][i] + faces[1]["dir"][i] for i in range(3)])
    if not b:
        return None
    return _arrow("radius", edge["mid"], [-b[0], -b[1], -b[2]])


def face_grip(face):
    """A shell's grip: an arrow on the first opened face, into the body."""
    d = face["dir"]
    return _arrow("thickness", face["centroid"], [-d[0], -d[1], -d[2]])


def move_grip(face, offset):
    """A moved face's grip: on a flat face an arrow where it stands now, out
    along its normal; on a round face an arrow out from the axis at the
    radius it will have."""
    if face.get("kind") == "cylinder" and face.get("radius") is not None:
        axis = normalize(face["dir"]) or [0, 0, 1]
        ref = [1, 0, 0] if abs(axis[0]) < 0.6 else [0, 1, 0] if abs(axis[1]) < 0.6 else [0, 0, 1]
        out = normalize(cross(axis, ref)) or [1, 0, 0]
        return _arrow("move", add_scaled(face.get("center") or face["centroid"], out, face["radius"] + offset), out)
    return _arrow("move", add_scaled(face["centroid"], face["dir"], offset), face["dir"])


def move_grips(placement, radius=MOVE_GIZMO_PX):
    """A Move's gizmo where the moved bodies' middle stands: an arrow along X,
    Y and Z standing off just outside the rings, and a ring for each angle."""
    at = moved_pivot(placement)
    rings = ring_axes(placement["rotate"])
    axes = ([1, 0, 0], [0, 1, 0], [0, 0, 1])
    out = []
    for i in range(3):
        out.append({**_arrow(MOVE_GRIP_SIDES[i], at, axes[i], radius / 3), "standoff": radius * 1.08, "color": MOVE_AXIS_COLORS[i]})
        out.append({"side": MOVE_GRIP_SIDES[i + 3], "shape": "ring", "position": list(at), "dir": rings[i], "size": radius, "pixels": True, "color": MOVE_AXIS_COLORS[i]})
    return out


def drag_revolve_angle(start_deg, delta_deg, max_deg=FULL_TURN_DEG):
    """The angle a revolve grip's drag makes, kept positive and within max."""
    return min(max_deg, max(1, _round10(start_deg + delta_deg)))
