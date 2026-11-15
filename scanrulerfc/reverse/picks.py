# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/viewer/bodyPicks.ts (an edge or a face of a body clicked for the open box), state/reSolidSlice.ts and reFeatureSlice.ts (a pick toggled in the box; an extrude's end put through a point clicked on the part)
# SPDX-License-Identifier: AGPL-3.0-only
#
# What a click on the part does to the open feature box: on a body, the
# edge (a fillet's, a chamfer's) or the face (a shell's, a moved or deleted
# face's) under it is found in the body's topology as built — by where the
# click landed, not by FreeCAD's element names — and toggled in the box's
# picks, as fingerprints the feature keeps; on an extrude's box, the end on
# the clicked side of the sketch plane is put through the point. Pure but
# for the builder's kernel, which measures a point's distance to a face.

import math

from .preview import extent_through_point
from .vec import dot, sub

# The box's pick list by kind: what a click on a body adds or takes away.
# (A draft's faces wait for its neutral face, which is not picked here yet.)
PICKS = {"fillet": "edges", "chamfer": "edges", "shell": "faces", "moveFace": "faces", "deleteFace": "faces"}
# What the box says of its picks, in the original's words (FeatureEditor.tsx).
NONE_PICKED = {
    "shell": "None — a closed hollow body. Click faces of the body to take them away",
    "fillet": "Click the edges of the body — a round runs on along the edges tangent to it. Click a picked edge again to let it go",
    "chamfer": "Click the edges of the body — a round runs on along the edges tangent to it. Click a picked edge again to let it go",
    "deleteFace": "Click a face of the round, the hole or the boss to take off",
    "moveFace": "Click the faces of the body to move — flat or round ones",
}


def picks_line(record):
    """The box's line on its picks: what to click, or how many are picked."""
    field = PICKS.get((record or {}).get("kind"))
    if field is None:
        return None
    n = len(record.get(field) or [])
    if n == 0:
        return NONE_PICKED[record["kind"]]
    word = field[:-1]
    return f"{n} {word}{'' if n == 1 else 's'} picked"
# How far from an edge a click still takes it, mm (the polyline's sag and a
# click's spread on the screen).
EDGE_REACH_MM = 2.0


def _seg_dist(p, a, b):
    ab = sub(b, a)
    ll = dot(ab, ab)
    t = 0.0 if ll < 1e-24 else max(0.0, min(1.0, dot(sub(p, a), ab) / ll))
    d = [a[i] + ab[i] * t - p[i] for i in range(3)]
    return math.sqrt(dot(d, d))


def nearest_edge(edges, p, reach=EDGE_REACH_MM):
    """The index of the edge whose polyline runs nearest p, within reach."""
    best, at = reach, None
    for n, e in enumerate(edges):
        pl = e.get("polyline") or []
        pts = [pl[i:i + 3] for i in range(0, len(pl) - 2, 3)] or [e["fingerprint"]["mid"]]
        for i in range(len(pts)):
            d = _seg_dist(p, pts[i], pts[min(i + 1, len(pts) - 1)])
            if d < best:
                best, at = d, n
    return at


def pick_on_body(builder, body_id, p, what):
    """The fingerprint of the edge or the face ("edges" or "faces") of a
    built body nearest a point clicked on it, or None."""
    body = builder.body_by_id(body_id)
    if body is None:
        return None
    topo = builder.topology(body, 1)
    if what == "edges":
        n = nearest_edge(topo["edges"], p)
        return topo["edges"][n]["fingerprint"] if n is not None else None
    k = builder.kernel
    faces = k.faces_of(body["shape"])
    if len(faces) != len(topo["faces"]):
        return None
    dist = [k.distance_to_point(f, list(p)) for f in faces]
    n = min(range(len(dist)), key=dist.__getitem__) if dist else None
    return topo["faces"][n]["fingerprint"] if n is not None else None


def _same(a, b):
    """Two fingerprints of one pick: the same kind, middle and size."""
    if a.get("kind") != b.get("kind"):
        return False
    at = "mid" if "mid" in a else "centroid"
    if at not in b:
        return False
    d = sub(a[at], b[at])
    size = "length" if at == "mid" else "area"
    return math.sqrt(dot(d, d)) < 1e-6 and abs((a.get(size) or 0) - (b.get(size) or 0)) < 1e-6 * max(1.0, abs(a.get(size) or 0))


def toggled(record, body_id, fp):
    """The box with a pick toggled: added, or taken away when it is there.
    A pick on another body starts the box's picks again on that body."""
    field = PICKS.get(record.get("kind"))
    if field is None or fp is None:
        return record
    have = [x.get("fingerprint", x) for x in record.get(field) or []]
    if record.get("body") != body_id:
        return {**record, "body": body_id, field: [fp]}
    kept = [x for x in have if not _same(x, fp)]
    return {**record, field: kept if len(kept) < len(have) else have + [fp]}


def sketch_frame_of(record, features):
    sk = next((f for f in features if f.get("kind") == "sketch" and f.get("id") == record.get("sketchId")), None)
    return sk.get("frame") if sk else None


def extent_clicked(record, features, p):
    """An extrude's box with the end on the clicked side of its sketch plane
    put through the point (To in front of the plane, From behind it), or
    None when the click gives the extent nothing."""
    if record.get("kind") != "extrude" or record.get("face") or not record.get("extent"):
        return None
    frame = sketch_frame_of(record, features)
    if not frame:
        return None
    h = dot(sub(list(p), frame["origin"]), frame["normal"])
    e = record["extent"]
    end = "to" if h >= 0 or e["kind"] not in ("distance",) else "from"
    if e["kind"] in ("toPlane", "toFace", "toBody", "toNext", "toLast"):
        end = "from"
    nxt = extent_through_point(e, end, h)
    if nxt is None:
        return None
    from .parameters import unlink_slot

    out = {**record, "extent": nxt}
    for path in ("extent.from", "extent.to", "extent.total"):
        out = unlink_slot(out, path)
    return out
