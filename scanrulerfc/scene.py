# SPDX-License-Identifier: AGPL-3.0-only
# Ported from ScanRuler by Stefan Hermann (CNC Kitchen),
# github.com/CNCKitchen/ScanRuler: src/viewer/ (the elements, dimensions,
# sections, markers and colour maps the browser app draws over the scan) and
# src/ui/MapLegend.tsx (the legend beside a map).
#
# What the 3D view shows of ScanRuler's results, as data: the fitted and
# constructed elements, the dimensions with their values, the sections, the
# marked points, the nearest point, hot spots, an outline, a cut plane, the
# colour map of the call (deviation, wall thickness, draft, height, wear,
# segments) with its legend, Mesh Tools' edited copy in place of the
# scan, and after a flat_ call the 2D sheet (flat_plan). ScanRuler keeps these in its state, not as FreeCAD objects (the
# document is not filled with a fit's every try; element_to_document makes
# objects of them on request), so the window draws them as an overlay of
# the 3D view: scene_coin.py builds the Coin nodes from what plan() gives.
#
# Window review round 3 (125 pictures of the ScanRuler tools in FreeCAD):
# the panel listed every result, the view showed only the grey scan.
#
# Pure: numpy and the add-on's own modules, no FreeCAD. Nothing here writes
# ScanRuler's state: every state key is read with .get(), never through the
# handlers' setdefault-style readers (dstate, tstate, mt_state), so drawing
# changes neither the state nor the copy of it kept in the document.

import math

import numpy as np

from . import colormap as CM
from . import scanstate as S


def rgb01(h):
    """'#1877c0' as RGB 0..1 (0.094, 0.467, 0.753): what Coin's colour
    fields take. colormap.hex_rgb gives 0..255; handed to Coin as it was
    (window review round 6), Coin packed the colour into 32 bits with each
    channel past 1 overflowing into its neighbour, and #1877c0 (blue) came
    out #febf40 (orange) and #e8590c (orange) came out #58aff4 (blue): new
    and old swapped in every picture."""
    return tuple(c / 255.0 for c in CM.hex_rgb(h))


def hex_of(rgb):
    """RGB 0..1 as '#rrggbb' (the answer's facts)."""
    return "#" + "".join(f"{int(round(max(0.0, min(1.0, float(c))) * 255)):02x}" for c in rgb[:3])


# Colours, RGB 0..1: the panel's own accents (colormap.PALETTE). Blue is
# CNC Kitchen blue, Stefan Hermann's ScanRuler accent (palette[0]): an
# element as it stands; what this call made is the palette's orange.
ELEMENT = rgb01(CM.PALETTE[0])               # blue #1877c0: an element as it stands
NEW = rgb01(CM.PALETTE[1])                   # orange #e8590c: what this call made or changed
DIMENSION = rgb01(CM.PALETTE[2])             # green: dimension lines and values
SECTION = rgb01(CM.PALETTE[3])               # magenta: section curves
MARKED = rgb01(CM.PALETTE[4])                # amber: marked points, nearest point, hot spots
GHOST = rgb01(CM.PALETTE[5])                 # teal: a preview beside the mesh (wrap, reduce)
EDITED = (0.78, 0.78, 0.74)                  # the edited copy: the scan's own grey
SEGMENT_GREY = tuple(c / 255.0 for c in CM.UNMEASURED_RGB)

CIRCLE_SEGMENTS = 48
MARKED_MOST = 20000      # marked points drawn at most (every n-th past that)
LABEL_LIFT = 0.012       # labels set off their anchor by this share of the scan's size

# The colour map a call shows, by tool (a name or a prefix): it stays while
# the calls after it belong to the same map (deviation_hotspots after
# deviation_measure), and goes with the first call that does not.
MAPS = (
    ("deviation_", "deviation"), ("fit_scan_measure", "deviation"),
    ("thickness_", "thickness"),
    ("wear_diff", "wear"),
    ("scan_draft", "draft"),
    ("scan_heightmap", "height"),
    ("scan_segment", "segments"),
)
# Calls that move the whole part: nothing is marked new after them.
MOVES_ALL = ("align_", "scan_scale", "deviation_align", "mesh_use_edited", "mesh_undo")
# Calls whose marked points are drawn (they set or use st["marked"]).
MARKS = ("scan_query", "scan_segment", "element_fit", "element_fit_marked", "mesh_delete_marked", "wear_setup")


def _seq(x):
    """x, or an empty list for None: `x or []` fails on a numpy array."""
    return [] if x is None else x


def _longest(name, pairs):
    best, got = -1, None
    for k, v in pairs:
        if name == k or (k.endswith("_") and name.startswith(k)):
            if len(k) > best:
                best, got = len(k), v
    return got


def map_kind(tool):
    """The colour map a call of this tool shows, or None."""
    return _longest(str(tool or ""), MAPS)


# ---- shapes -----------------------------------------------------------------------------------------


def _unit(v):
    v = np.asarray(v, dtype=float)
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else None


def _basis(n, u=None):
    n = _unit(n)
    if n is None:
        n = np.array([0.0, 0.0, 1.0])
    if u is not None and len(u) == 3:
        u = np.asarray(u, dtype=float) - n * float(np.dot(u, n))
        u = _unit(u)
    if u is None:
        u = _unit(np.cross(n, [1.0, 0.0, 0.0] if abs(n[0]) < 0.9 else [0.0, 1.0, 0.0]))
    return n, u, np.cross(n, u)


def circle(centre, normal, radius, n=CIRCLE_SEGMENTS):
    """A closed polyline: n + 1 points round centre, square to normal."""
    nn, u, v = _basis(normal)
    t = np.linspace(0.0, 2 * math.pi, n + 1)
    c = np.asarray(centre, dtype=float)
    return c + radius * (np.cos(t)[:, None] * u + np.sin(t)[:, None] * v)


def element_shape(fit, assumed=None):
    """An element's fit as lines, points and a face to draw, in world mm:
    {"lines": [polyline (k, 3)], "points": [(3,)], "face": (4, 3) or None,
    "at": where its label goes}. As element_to_document makes it, without
    FreeCAD: a plane is its patch, a cylinder its two rims and four lines
    along it, a sphere three great circles. None for a fit with nothing to
    draw."""
    if not isinstance(fit, dict) or fit.get("center") is None:
        return None
    k = fit.get("kind")
    c = np.asarray(fit["center"], dtype=float)
    out = {"lines": [], "points": [], "face": None, "at": c}
    if k == "point":
        out["points"].append(c)
        return out
    if k == "line":
        d = _unit(fit.get("dir", [0, 0, 1]))
        h = max(float(fit.get("length", 10.0)) / 2, 1e-6)
        out["lines"].append(np.array([c - d * h, c + d * h]))
        return out
    if k == "circle":
        r = float(assumed) / 2 if assumed else float(fit["radius"])
        out["lines"].append(circle(c, fit["normal"], r))
        out["points"].append(c)
        return out
    if k == "plane":
        n, u, v = _basis(fit["normal"], fit.get("basisU"))
        eu, ev = max(float(fit.get("extentU", 10)), 1e-6), max(float(fit.get("extentV", 10)), 1e-6)
        corners = np.array([c + su * eu * u + sv * ev * v for su, sv in ((-1, -1), (1, -1), (1, 1), (-1, 1))])
        out["lines"].append(np.vstack([corners, corners[:1]]))
        out["lines"].append(np.array([c, c + n * 0.25 * min(eu, ev)]))  # which way it faces
        out["face"] = corners
        return out
    axis = _unit(fit.get("axis", [0, 0, 1]))
    if axis is None:
        return None
    if k in ("cylinder", "cone"):
        L = max(float(fit.get("length", 1.0)), 1e-6)
        if k == "cylinder":
            r0 = r1 = float(assumed) / 2 if assumed else float(fit["radius"])
        else:
            r0, r1 = float(fit["radius1"]), float(fit["radius2"])
        a, b = c - axis * (L / 2), c + axis * (L / 2)
        ra, rb = circle(a, axis, r0), circle(b, axis, r1)
        out["lines"] += [ra, rb, np.array([a, b])]
        for i in range(0, CIRCLE_SEGMENTS, CIRCLE_SEGMENTS // 4):
            out["lines"].append(np.array([ra[i], rb[i]]))
        return out
    if k == "sphere":
        r = float(assumed) / 2 if assumed else float(fit["radius"])
        for n in np.eye(3):
            out["lines"].append(circle(c, n, r))
        out["points"].append(c)
        return out
    if k == "torus":
        R, r = float(fit["majorRadius"]), float(fit["minorRadius"])
        out["lines"] += [circle(c, axis, R - r), circle(c, axis, R + r), circle(c + axis * r, axis, R), circle(c - axis * r, axis, R)]
        return out
    return None


def _anchor(fit, toward=None):
    """Where a dimension line meets an element: a point's own place, the
    foot of `toward` on an axis or a plane, else the element's centre."""
    c = np.asarray(fit["center"], dtype=float)
    if toward is None:
        return c
    t = np.asarray(toward, dtype=float)
    k = fit["kind"]
    if k == "plane":
        n = _unit(fit["normal"])
        return t - n * float(np.dot(t - c, n)) if n is not None else c
    d = fit.get("axis") if k in ("cylinder", "cone", "torus") else fit.get("dir") if k == "line" else None
    if d is not None:
        d = _unit(d)
        return c + d * float(np.dot(t - c, d)) if d is not None else c
    return c


def dimension_shape(st, d):
    """A dimension as a line between its elements and its value as words:
    {"lines": [(2, 3)], "at": label point, "text": "Height 20.000 mm"}, or
    None when an element is gone or has no fit."""
    from . import model as M

    els = [next((e for e in st.get("elements", []) if e.get("id") == i), None) for i in d.get("refs", [])]
    if not els or any(e is None or not e.get("fit") for e in els):
        return None
    try:
        row = M.evaluate_dimension(st, d)
    except Exception:  # noqa: BLE001 — a dimension that cannot be read draws as its line only
        row = {"value": {}}
    v = row.get("value") or {}
    value = v.get("value") if not v.get("invalid") else "—"
    name = d.get("name") or v.get("label") or "Dimension"
    text = f"{name} {value}" if value else name
    if row.get("verdict"):
        text += " ✓" if row["verdict"].get("pass") else " ✗"
    f0 = els[0]["fit"]
    if len(els) == 1:
        c = np.asarray(f0["center"], dtype=float)
        r = f0.get("radius")
        if r is None:
            return {"lines": [], "at": c, "text": text}
        n = f0.get("axis")
        if n is None:
            n = f0.get("normal")
        if n is None:
            n = [0, 0, 1]
        _n, u, _v = _basis(n)
        return {"lines": [np.array([c - u * float(r), c + u * float(r)])], "at": c + u * float(r), "text": text}
    f1 = els[1]["fit"]
    # From the first element's centre to its foot on the second, then back
    # onto the first: a plane to a plane, an axis to an axis or a point to
    # a plane all draw square to what they measure.
    a = _anchor(f0)
    b = _anchor(f1, a)
    a = _anchor(f0, b)
    return {"lines": [np.array([a, b])], "at": (a + b) / 2, "text": text}


def section_shape(sec):
    """A section's chains as polylines (world mm), or None."""
    pts = sec.get("points")
    if pts is None:
        return None
    P = np.asarray(pts, dtype=float)
    if not len(P):
        return None
    if P.shape[1] == 2:
        from .section_core import lift

        P = np.array([lift(sec["frame"], p) for p in P])
    offs = [int(x) for x in np.asarray(sec.get("offsets", [0, len(P)])).reshape(-1)]
    lines = [P[a:b] for a, b in zip(offs, offs[1:]) if b - a >= 2]
    return {"lines": lines, "at": P[0]} if lines else None


# ---- maps ---------------------------------------------------------------------------------------


def _current(st, rec, scan):
    """rec (a workspace's state) belongs to the scan as it stands now."""
    return isinstance(rec, dict) and scan is not None and rec.get("scan") is scan and (rec.get("version") is None or rec.get("version") == scan.version)


def deviation_layer(st, scan):
    d = st.get("deviation")
    if not _current(st, d, scan):
        return None
    v = d["target"]["values"] if d.get("source") == "element" and d.get("target") else d.get("values")
    if v is None or len(v) != len(scan.V):
        return None
    rng = max(float(d.get("range") or 0), 1e-3)
    md = float(d.get("maxDistance") or math.inf)
    return {"kind": "deviation", "values": np.asarray(v, dtype=float), "low": -rng, "high": rng, "colormap": CM.DEFAULT,
            "bands": d.get("bands"), "valid": (-md, md), "reversed": False, "source": "element" if d.get("source") == "element" else "reference",
            "stats": {"tolerance": float(d.get("tolerance") or 0.1)}, "title": "DEVIATION", "key": ("deviation", id(v), rng, md, d.get("bands"))}


def thickness_layer(st, scan):
    t = st.get("thickness")
    if not isinstance(t, dict) or t.get("values") is None or t.get("scan") is not scan or t.get("V") is not scan.V:
        return None
    v = np.asarray(t["values"], dtype=float)
    if len(v) != len(scan.V):
        return None
    lo, hi = float(t.get("low", 0.0)), float(t.get("high", 3.0))
    return {"kind": "thickness", "values": v, "low": lo, "high": hi if hi > lo else lo + 1.0, "colormap": CM.DEFAULT, "bands": t.get("bands"),
            "valid": (0.0, math.inf), "reversed": True, "stats": {"limit": float(t.get("limit", 1.0))}, "title": "WALL THICKNESS",
            "key": ("thickness", id(t["values"]), lo, hi, t.get("bands"))}


def draft_layer(scan, args):
    """Each scan point's draft angle to the pull direction, degrees: 0 on a
    wall along the pull, positive where the wall opens toward it; grey
    off the walls (more than nearDeg from the pull's walls), as
    scan_draft reads them."""
    pull = (args or {}).get("pull")
    pull = _unit([0, 0, 1] if pull is None else pull)
    if pull is None:
        return None
    near = float((args or {}).get("nearDeg", 10))
    N = np.asarray(scan.graph().N, dtype=float)
    with np.errstate(invalid="ignore"):
        deg = np.degrees(np.arcsin(np.clip(N @ pull, -1.0, 1.0)))
    deg = np.where(np.isfinite(deg) & (np.abs(deg) <= near), deg, np.nan)
    return {"kind": "draft", "values": deg, "low": -near, "high": near, "colormap": CM.DEFAULT, "bands": None,
            "valid": (-near, near), "reversed": False, "unit": "°", "title": "DRAFT", "key": ("draft", scan.version, tuple(pull), near)}


def height_layer(scan, args, body):
    """The scan coloured by its height along the map's axis (or square to
    its plane), over the range scan_heightmap answered: where the height
    map's grid reads it from. A relief or deviation map is the deviation
    map's or none."""
    b = body if isinstance(body, dict) else {}
    if b.get("of", "height") != "height":
        return None
    V = np.asarray(scan.V, dtype=float)
    plane = b.get("plane")
    if isinstance(plane, dict) and plane.get("normal") is not None:
        n = _unit(plane["normal"])
        h = (V - np.asarray(plane.get("origin", [0, 0, 0]), dtype=float)) @ n
    else:
        k = "xyz".index(str(b.get("along", "z"))[-1]) if str(b.get("along", "z"))[-1:] in "xyz" else 2
        h = V[:, k]
    lo = b.get("min") if isinstance(b.get("min"), (int, float)) else float(np.nanmin(h)) if len(h) else 0.0
    hi = b.get("max") if isinstance(b.get("max"), (int, float)) else float(np.nanmax(h)) if len(h) else 1.0
    if not hi > lo:
        lo, hi = float(np.nanmin(h)), float(np.nanmax(h))
    if not hi > lo:
        hi = lo + 1.0
    return {"kind": "height", "values": h, "low": float(lo), "high": float(hi), "colormap": CM.DEFAULT, "bands": None,
            "valid": (-math.inf, math.inf), "reversed": False, "title": "HEIGHT", "key": ("height", scan.version, float(lo), float(hi), repr(plane), b.get("along"))}


def wear_layer(session, st, scan):
    """How far each point of the worn regions stands from the wear
    reference (signed, mm: negative lost, positive added), grey elsewhere —
    the readings wear_diff sums per region."""
    w = st.get("wear")
    if not isinstance(w, dict) or w.get("tags") is None or len(w.get("tags")) == 0 or w.get("reference") is None:
        return None
    from . import wear_core as W
    from .handlers.wear import reference_surface

    try:
        ref = reference_surface(session, w, scan)
    except Exception:  # noqa: BLE001 — no reference to read against: no map
        return None
    V = np.asarray(scan.V, dtype=float)
    worn = [t for t in w["tags"] if t.get("worn", True)] or w["tags"]
    inside = W.weight([t["region"] for t in worn], [], 0, V) >= 1
    vals = np.full(len(V), np.nan)
    idx = np.nonzero(inside)[0]
    s = w.get("settings") or {}
    if len(idx):
        ok, h = W._near(ref, V[idx], float(s.get("maxMm", 3.0)))
        vals[idx[ok]] = np.asarray(h.signed, dtype=float)[ok]
    fin = vals[np.isfinite(vals)]
    reach = max(float(np.abs(fin).max()) if len(fin) else 0.0, float(s.get("tolerance", 0.1)), 1e-3)
    return {"kind": "wear", "values": vals, "low": -reach, "high": reach, "colormap": CM.DEFAULT, "bands": None,
            "valid": (-math.inf, math.inf), "reversed": False, "source": "reference", "title": "WEAR",
            "stats": {"tolerance": float(s.get("tolerance", 0.1))}, "key": ("wear", scan.version, reach, len(idx))}


def segments_layer(st, scan):
    """The regions scan_segment found, each in its own colour, the rest grey."""
    cache = st.get("segCache")
    if not cache or not isinstance(cache, tuple) or len(cache) != 2 or cache[0][0] != scan.version:
        return None
    regions = _seq(cache[1].get("regions"))
    rgb = np.tile(np.asarray(SEGMENT_GREY, dtype=float), (len(scan.V), 1))
    for i, r in enumerate(regions):
        m = np.asarray(r.get("members", []), dtype=np.int64)
        m = m[(m >= 0) & (m < len(rgb))]
        rgb[m] = rgb01(CM.palette_color(i))  # 0..1, as the grey: 0..255 here saturated every region
    return {"kind": "segments", "rgb": rgb, "count": len(regions), "key": ("segments", id(cache), len(regions))}


def colours(layer):
    """A map layer's per-vertex colours, RGB 0..1 (n, 3)."""
    if layer.get("rgb") is not None:
        return np.asarray(layer["rgb"], dtype=float)
    lo_v, hi_v = layer.get("valid", (-math.inf, math.inf))
    rgb = CM.map_values(layer["values"], layer["low"], layer["high"], layer.get("colormap") or CM.DEFAULT, layer.get("bands"),
                        lo_v, hi_v, bool(layer.get("reversed")))
    return rgb.astype(float) / 255.0


def legend_model(layer, units="mm"):
    """The legend beside a map (legend.model), or None for segments."""
    from . import legend as L

    kind = layer["kind"]
    if kind == "segments":
        return None
    as_kind = {"deviation": "deviation", "thickness": "thickness", "wear": "deviation"}.get(kind, kind)
    vmin, vmax = layer.get("valid", (None, None))
    m = L.model(as_kind, layer["low"], layer["high"], colormap=layer.get("colormap") or CM.DEFAULT, bands=layer.get("bands"),
                units=units, values=layer.get("values") if kind in ("deviation", "thickness", "wear") else None,
                valid_min=vmin if math.isfinite(vmin or 0) else None, valid_max=vmax if math.isfinite(vmax or 0) else None,
                stats=layer.get("stats"), source=layer.get("source", "reference"))
    angle = layer.get("unit") == "°"
    title = layer.get("title") or kind.upper()
    m["caption"] = f"{title} · {'°' if angle else L.unit_word(units).upper()}"
    if angle:
        # The ticks of an angle map: degrees, not lengths.
        for t in m["ticks"]:
            t["text"] = f"{L.js_number(round(t['value'], 1))}°"
    return m


def map_layer(session, st, scan, tool, args, body, kind=None):
    kind = kind or map_kind(tool)
    if kind is None or scan is None:
        return None
    try:
        if kind == "deviation":
            return deviation_layer(st, scan)
        if kind == "thickness":
            return thickness_layer(st, scan)
        if kind == "draft":
            return draft_layer(scan, args)
        if kind == "height":
            return height_layer(scan, args, body)
        if kind == "wear":
            return wear_layer(session, st, scan)
        if kind == "segments":
            return segments_layer(st, scan)
    except Exception:  # noqa: BLE001 — a map that cannot be read is not drawn; the call has answered
        return None
    return None


# ---- the meshes Mesh Tools works on ---------------------------------------------------------------


def mesh_tools(st):
    """(copy, previews) of Mesh Tools for the scan now open: the edited
    copy (V, F) or None, and the previews made beside it ([(name, V, F)]:
    the wrap, the reduced mesh). Read as handlers/meshtools.mt_state reads
    it, without its resetting."""
    ms = st.get("meshToolsState")
    scan = st.get("scan")
    if not isinstance(ms, dict) or scan is None:
        return None, []
    if ms.get("base") is not scan and not any(u.get("scan") is scan for u in _seq(ms.get("undo"))):
        return None, []
    copy = ms.get("copy")
    previews = []
    for name in ("wrap", "reduced"):
        p = ms.get(name)
        if isinstance(p, dict) and p.get("V") is not None and p.get("F") is not None:
            previews.append((name, np.asarray(p["V"], dtype=float), np.asarray(p["F"], dtype=np.int64)))
    if copy is not None:
        copy = (np.asarray(copy[0], dtype=float), np.asarray(copy[1], dtype=np.int64))
    return copy, previews


# ---- what one call leaves to see -----------------------------------------------------------------


def _vec3(v):
    try:
        a = np.asarray(v, dtype=float).reshape(-1)
    except (TypeError, ValueError):
        return None
    return a if a.shape == (3,) and np.isfinite(a).all() else None


def _points_at(body, keys=("hotspots", "patches", "spots", "places")):
    out = []
    b = body if isinstance(body, dict) else {}
    for k in keys:
        for row in _seq(b.get(k)):
            if isinstance(row, dict):
                p = _vec3(row.get("at") if row.get("at") is not None else row.get("centroid"))
                if p is not None:
                    out.append(p)
    return out


def outline_lines(scan, body):
    """scan_outline's loops lifted into 3D: on its plane, or on the scan's
    face toward the eye for an axis (its box's top looking down -z)."""
    b = body if isinstance(body, dict) else {}
    loops = _seq(b.get("loops"))
    if not loops:
        return []
    plane = b.get("plane")
    if isinstance(plane, dict) and plane.get("u") is not None:
        O, U, Vv = (np.asarray(plane[k], dtype=float) for k in ("origin", "u", "v"))

        def lift(p):
            return O + p[0] * U + p[1] * Vv
    else:
        across = b.get("across") or ["x", "y"]
        ia, ib = "xyz".index(across[0]), "xyz".index(across[1])
        k = 3 - ia - ib
        axis = str(b.get("axis", "-z"))
        V = np.asarray(scan.V, dtype=float)
        h = float(V[:, k].max()) if axis.startswith("-") else float(V[:, k].min())

        def lift(p):
            q = np.zeros(3)
            q[ia], q[ib], q[k] = p[0], p[1], h
            return q
    out = []
    for lp in loops:
        if not isinstance(lp, dict):
            continue
        if lp.get("circle"):
            c = lp["circle"]
            t = np.linspace(0, 2 * math.pi, CIRCLE_SEGMENTS + 1)
            pts = [(c["center"][0] + c["radius"] * math.cos(a), c["center"][1] + c["radius"] * math.sin(a)) for a in t]
        else:
            pts = [tuple(p) for p in _seq(lp.get("points"))]
            if pts:
                pts.append(pts[0])
        if len(pts) >= 2:
            out.append(np.array([lift(p) for p in pts]))
    return out


def cut_plane(session, scan, args):
    """mesh_cut_preview's plane as a square over the scan's size, or None."""
    a = args if isinstance(args, dict) else {}
    try:
        from .handlers.meshtools import plane_at

        o, n, _off, _label = plane_at(session, a.get("plane"), float(a.get("offset", 0)), a.get("keep", "minus"))
    except Exception:  # noqa: BLE001 — no plane to draw
        return None
    V = np.asarray(scan.V, dtype=float)
    half = 0.6 * float(np.linalg.norm(V.max(0) - V.min(0))) if len(V) else 10.0
    n, u, v = _basis(n)
    c = np.asarray(o, dtype=float)
    corners = np.array([c + su * half * u + sv * half * v for su, sv in ((-1, -1), (1, -1), (1, 1), (-1, 1))])
    return {"lines": [np.vstack([corners, corners[:1]]), np.array([c, c - n * 0.2 * half])], "face": corners}


def transient(session, st, scan, tool, args, body):
    """What only this call shows: [{"kind", "lines", "points", "face", "colour", "text"}]."""
    out = []
    a = args if isinstance(args, dict) else {}
    b = body if isinstance(body, dict) else {}
    if tool == "scan_nearest":
        p = _vec3(b.get("point"))
        if p is not None:
            item = {"kind": "nearest", "points": [p], "lines": [], "colour": MARKED,
                    "text": f"{b.get('distance', 0):.3f} mm" if isinstance(b.get("distance"), (int, float)) else None, "at": p}
            at = (a.get("at") or {}).get("point") if isinstance(a.get("at"), dict) else None
            q = _vec3(at)
            if q is not None and float(np.linalg.norm(q - p)) > 1e-9:
                item["lines"].append(np.array([q, p]))
                item["points"].append(q)
            out.append(item)
    if tool.startswith("deviation_hotspots"):
        pts = _points_at(b)
        if pts:
            out.append({"kind": "hotspots", "points": pts, "lines": [], "colour": MARKED, "text": None})
    if tool == "scan_outline" and scan is not None:
        lines = outline_lines(scan, b)
        if lines:
            out.append({"kind": "outline", "points": [], "lines": lines, "colour": NEW, "text": None})
    if tool == "mesh_cut_preview" and scan is not None:
        c = cut_plane(session, scan, a)
        if c:
            out.append({"kind": "cut", "points": [], "colour": NEW, "text": b.get("plane") if isinstance(b.get("plane"), str) else None,
                        "at": c["face"][2], **c})
    if tool == "scan_fit_surface":
        fr = b.get("frame") or {}
        o, n = _vec3(fr.get("origin")), _vec3(fr.get("normal"))
        if o is not None and n is not None and scan is not None:
            size = 0.1 * float(np.linalg.norm(scan.V.max(0) - scan.V.min(0)))
            out.append({"kind": "frame", "points": [o], "lines": [np.array([o, o + n * size])], "colour": NEW, "text": b.get("best")})
    if tool in MARKS and scan is not None:
        m = st.get("marked")
        if isinstance(m, dict) and m.get("vertices") is not None:
            idx = np.asarray(m["vertices"], dtype=np.int64).reshape(-1)
            idx = idx[(idx >= 0) & (idx < len(scan.V))]
            if len(idx) > MARKED_MOST:
                idx = idx[:: len(idx) // MARKED_MOST + 1]
            if len(idx):
                out.append({"kind": "marked", "points": list(np.asarray(scan.V, dtype=float)[idx]), "lines": [], "colour": MARKED, "text": None})
    return out


# ---- the 2D sheet (the flat workspace) ------------------------------------------------------------
# Window review pass 3 (02-012 to 02-088): no flat_ call drew anything; the
# 3D view stayed on the mesh as the last 3D call left it. The sheet is
# drawn here as ScanRuler's 2D workspace shows it (src/ui/FlatPanel.tsx and
# the flat canvas): the image (or, for a section, the section's own cut on
# the part), the edges found on it, the fitted elements in the sheet's
# colours, the dimensions with their values, the notes and the alignment's
# zero point. A section's sheet lies on the section's plane; an image's on
# the world's XY plane, its bottom-left corner at the origin, in the
# sheet's units (mm once calibrated, else pixels). Everything is drawn on
# top of the model (an image of a part may lie where a model is), and the
# camera is turned square onto the sheet and framed on it (flat_frame).

FLAT_COLOURS = ("#e4572e", "#2e86ab", "#a23b72", "#f18f01", "#3b8132", "#6a4c93")  # handlers/flat.py COLORS
FLAT_EDGES = (0.07, 0.71, 0.65)        # the edges found, as flat_render draws them
FLAT_SHEET = (0.55, 0.57, 0.60)        # the sheet's border
FLAT_ARC_STEPS = 64
XY_FRAME = {"origin": [0.0, 0.0, 0.0], "basisU": [1.0, 0.0, 0.0], "basisV": [0.0, 1.0, 0.0], "normal": [0.0, 0.0, 1.0]}


def flat_frame(st):
    """The sheet in front and where it lies: {"kind": "section" | "image",
    "frame": {origin, basisU, basisV, normal}, "unit": (x, y) chain units to
    the sheet's, "units": "mm" | "px", "section": the section or None,
    "image": the image record or None}, or None when nothing is on the
    sheet. Read only (no handler's setdefault): drawing changes no state."""
    f = st.get("flatState") if isinstance(st, dict) else None
    if not isinstance(f, dict) or not isinstance(f.get("subject"), dict):
        return None
    subj = f["subject"]
    if subj.get("kind") == "section":
        ss = st.get("sectionState") or {}
        sec = next((x for x in ss.get("sections", []) if x.get("id") == subj.get("id")), None)
        if sec is None or not isinstance(sec.get("frame"), dict):
            return None
        return {"kind": "section", "frame": sec["frame"], "unit": (1.0, 1.0), "units": "mm", "section": sec, "image": None}
    img = f.get("image")
    if subj.get("kind") == "image" and isinstance(img, dict) and img.get("width"):
        p = f.get("pxPerMm")
        unit = (1.0 / float(p["x"]), 1.0 / float(p["y"])) if isinstance(p, dict) and p.get("x") and p.get("y") else (1.0, 1.0)
        return {"kind": "image", "frame": XY_FRAME, "unit": unit, "units": "mm" if unit != (1.0, 1.0) or isinstance(p, dict) else "px", "section": None, "image": img}
    return None


def _flat_colour(i):
    return rgb01(FLAT_COLOURS[i % len(FLAT_COLOURS)])


def flat_element_shape(fit, lift, size):
    """A 2D element's fit as 3D lines and points on the sheet, or None."""
    if not isinstance(fit, dict):
        return None
    k = fit.get("kind")
    out = {"lines": [], "points": [], "face": None}
    if k == "point" and fit.get("at") is not None:
        x, y = (float(v) for v in fit["at"][:2])
        d = 0.02 * size
        out["lines"] = [np.array([lift((x - d, y)), lift((x + d, y))]), np.array([lift((x, y - d)), lift((x, y + d))])]
        out["points"] = [lift((x, y))]
        out["at"] = lift((x + d, y + d))
        return out
    if fit.get("center") is None:
        return None
    c = np.asarray(fit["center"], dtype=float)[:2]
    if k == "line":
        d = np.asarray(fit.get("dir", [1, 0]), dtype=float)[:2]
        h = float(fit.get("length", 0.0)) / 2
        out["lines"] = [np.array([lift(c - d * h), lift(c + d * h)])]
        out["at"] = lift(c + d * h)
        return out
    if k in ("circle", "arc") and fit.get("radius") is not None:
        r = float(fit["radius"])
        a0, sw = (0.0, 2 * math.pi) if k == "circle" else (float(fit.get("start", 0.0)), float(fit.get("sweep", 2 * math.pi)))
        t = a0 + np.linspace(0.0, sw, FLAT_ARC_STEPS + 1)
        out["lines"] = [np.array([lift((c[0] + r * math.cos(a), c[1] + r * math.sin(a))) for a in t])]
        out["points"] = [lift(c)]
        mid = a0 + sw / 2 if k == "arc" else math.pi / 4
        out["at"] = lift((c[0] + r * math.cos(mid), c[1] + r * math.sin(mid)))
        return out
    return None


def _flat_dimension(f, d, lift, units):
    """A 2D dimension as its segment and value on the sheet, or None."""
    from . import flat_core as FC

    els = [next((e for e in f.get("elements", []) if e.get("id") == i), None) for i in d.get("refs", [])]
    if not els or any(e is None or not e.get("fit") for e in els):
        return {"lines": [], "points": [], "text": f"{d.get('name') or 'Dimension'} (invalid)", "at": None}
    try:
        v = FC.evaluate_dimension(d.get("type"), [e["fit"] for e in els], units)
    except Exception:  # noqa: BLE001 — a dimension that cannot be read is left out
        return None
    text = f"{d.get('name') or v.get('label') or 'Dimension'} {v.get('value') if not v.get('invalid') else '(invalid)'}"
    seg = v.get("segment")
    if seg is not None and len(seg) == 2:
        a, b = (np.asarray(x, dtype=float)[:2] for x in seg)
        return {"lines": [np.array([lift(a), lift(b)])], "points": [], "text": text, "at": lift((a + b) / 2)}
    cs = [FC.ref_point(e["fit"]) if FC.ref_point(e["fit"]) is not None else np.asarray(e["fit"].get("center", [0, 0]), dtype=float)[:2] for e in els]
    return {"lines": [], "points": [], "text": text, "at": lift(np.mean(cs, axis=0))}


def flat_plan(st, tool, args=None, body=None, memo=None):
    """What the view shows of the 2D sheet: {"kind", "units", "frame",
    "box" (two 3D corners), "corners" (the sheet's four, 3D), "image"
    (the image record, for its texture) or None, "items" [shapes as
    plan()'s, drawn on top], "counts"}, or None with nothing on the sheet."""
    sh = flat_frame(st)
    if sh is None:
        return None
    memo = memo if memo is not None else {}
    f = st["flatState"]
    fr = sh["frame"]
    o, u, v = (np.asarray(fr[k], dtype=float) for k in ("origin", "basisU", "basisV"))

    def lift(p):
        return o + float(p[0]) * u + float(p[1]) * v

    ux, uy = sh["unit"]
    chains = []
    if sh["kind"] == "image":
        for c in _seq(f.get("chains")):
            c = np.asarray(c, dtype=float)
            if len(c) >= 2:
                chains.append(c * np.array([ux, uy]))
        img = sh["image"]
        lo, hi = np.zeros(2), np.array([float(img["width"]) * ux, float(img["height"]) * uy])
    else:
        from .section_core import chains_of, project_cut

        sec = sh["section"]
        try:
            flat = project_cut(sec["points"], sec["frame"])
            chains = [np.asarray(c, dtype=float) for c in chains_of(flat, sec["offsets"]) if len(c) >= 2]
        except Exception:  # noqa: BLE001 — a section without its cut: its elements alone
            chains = []
        pts = np.vstack(chains) if chains else np.zeros((1, 2))
        pad = 0.05 * max(float(np.ptp(pts[:, 0])), float(np.ptp(pts[:, 1])), 1.0)
        lo, hi = pts.min(0) - pad, pts.max(0) + pad
    size = float(max(hi - lo)) or 1.0
    corners = np.array([lift(p) for p in ((lo[0], lo[1]), (hi[0], lo[1]), (hi[0], hi[1]), (lo[0], hi[1]))])
    items = []
    seen = memo.get("flat") or {}
    now = {}
    named = _named(body)
    note = body.get("note") if isinstance(body, dict) and isinstance(body.get("note"), dict) else None
    fresh = bool(memo.get("flatPrimed")) and memo.get("flatSubject") == repr(f.get("subject"))

    def is_new(key, val, name=None):
        now[key] = val
        return (fresh and seen.get(key) != val) or (name is not None and name in named)

    items.append({"kind": "sheet", "lines": [np.vstack([corners, corners[:1]])], "points": [], "face": None, "colour": FLAT_SHEET,
                  "text": None, "new": False})
    if sh["kind"] == "image" and chains:
        items.append({"kind": "edges", "lines": [np.array([lift(p) for p in c]) for c in chains], "points": [], "face": None,
                      "colour": FLAT_EDGES, "text": None, "new": False})
    shown = [e for e in f.get("elements", []) if e.get("visible", True) and e.get("fit")]
    for i, e in enumerate(shown):
        s = flat_element_shape(e["fit"], lift, size)
        if s is None:
            continue
        new = is_new(("e", e.get("id")), (e.get("name"), repr(e.get("fit"))), e.get("name"))
        s.update(kind="flatElement", colour=NEW if new else _flat_colour(i), text=e.get("name"), name=e.get("name"), new=new)
        items.append(s)
    for d in f.get("dimensions", []):
        if not d.get("visible", True):
            continue
        s = _flat_dimension(f, d, lift, sh["units"])
        if s is None:
            continue
        new = is_new(("d", d.get("id")), (s["text"],), d.get("name"))
        s.update(kind="flatDimension", colour=NEW if new else DIMENSION, name=d.get("name"), face=None, new=new)
        items.append(s)
    for n in f.get("notes", []):
        if not n.get("visible", True) or n.get("at") is None:
            continue
        at = lift(n["at"])
        new = is_new(("n", n.get("id")), (n.get("text"), tuple(n["at"]))) or (note is not None and note.get("id") == n.get("id"))
        items.append({"kind": "flatNote", "lines": [], "points": [at], "face": None, "colour": NEW if new else MARKED,
                      "text": n.get("text"), "at": at, "name": f"note {n.get('id')}", "new": new})
    al = f.get("alignment")
    if isinstance(al, dict) and al.get("origin") is not None:
        a0 = np.asarray(al["origin"], dtype=float)[:2]
        dx = np.array([math.cos(float(al.get("angle", 0.0))), math.sin(float(al.get("angle", 0.0)))])
        dy = np.array([-dx[1], dx[0]])
        L = 0.15 * size
        new = is_new(("a",), (tuple(a0), float(al.get("angle", 0.0))))
        items.append({"kind": "flatOrigin", "lines": [np.array([lift(a0), lift(a0 + dx * L)]), np.array([lift(a0), lift(a0 + dy * L * 0.6)])],
                      "points": [lift(a0)], "face": None, "colour": NEW if new else DIMENSION, "text": "origin", "at": lift(a0 + dx * L), "name": "origin", "new": new})
    memo["flat"] = now
    memo["flatPrimed"] = True
    memo["flatSubject"] = repr(f.get("subject"))
    return {"kind": sh["kind"], "units": sh["units"], "frame": {k: np.asarray(fr[k], dtype=float) for k in ("origin", "basisU", "basisV")},
            "box": (corners.min(0), corners.max(0)), "corners": corners, "image": sh["image"], "unit": sh["unit"], "items": items,
            "counts": {"elements": len(shown), "dimensions": sum(1 for d in f.get("dimensions", []) if d.get("visible", True)),
                       "notes": sum(1 for n in f.get("notes", []) if n.get("visible", True)), "chains": len(chains),
                       "aligned": isinstance(al, dict)}}


def camera_rotation(u, v):
    """The camera's orientation that looks square onto the plane of u, v
    (u to the right, v up, the eye on the side of u x v), as a quaternion
    (x, y, z, w): Coin's camera looks down its own -Z with +Y up."""
    u = _unit(u)
    v = np.asarray(v, dtype=float)
    if u is None:
        u = np.array([1.0, 0.0, 0.0])
    v = _unit(v - u * float(np.dot(v, u)))
    if v is None:
        v = _unit(np.cross([0.0, 0.0, 1.0], u)) if abs(u[2]) < 0.9 else np.array([0.0, 1.0, 0.0])
    n = np.cross(u, v)
    R = np.column_stack([u, v, n])  # the camera's axes in the world
    t = float(np.trace(R))
    if t > 0:
        s = math.sqrt(t + 1.0) * 2
        w, x, y, z = 0.25 * s, (R[2, 1] - R[1, 2]) / s, (R[0, 2] - R[2, 0]) / s, (R[1, 0] - R[0, 1]) / s
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = math.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2]) * 2
        w, x, y, z = (R[2, 1] - R[1, 2]) / s, 0.25 * s, (R[0, 1] + R[1, 0]) / s, (R[0, 2] + R[2, 0]) / s
    elif R[1, 1] > R[2, 2]:
        s = math.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2]) * 2
        w, x, y, z = (R[0, 2] - R[2, 0]) / s, (R[0, 1] + R[1, 0]) / s, 0.25 * s, (R[1, 2] + R[2, 1]) / s
    else:
        s = math.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1]) * 2
        w, x, y, z = (R[1, 0] - R[0, 1]) / s, (R[0, 2] + R[2, 0]) / s, (R[1, 2] + R[2, 1]) / s, 0.25 * s
    q = np.array([x, y, z, w])
    return tuple(float(c) for c in q / np.linalg.norm(q))


def rotate_by(q, p):
    """p turned by the quaternion q (x, y, z, w)."""
    x, y, z, w = q
    qv = np.array([x, y, z])
    p = np.asarray(p, dtype=float)
    return p + 2 * np.cross(qv, np.cross(qv, p) + w * p)


# ---- the whole scene ------------------------------------------------------------------------------


def _fit_key(e):
    return (e.get("name"), repr(e.get("fit")), e.get("assumed"))


def plan(session, tool, args=None, body=None, memo=None):
    """What the 3D view shows after a call of `tool` (its arguments and its
    answer): a dict

        scan        the scan object's state: None, or {"hide": bool} — hidden
                    while the edited copy stands in its place
        mesh        Mesh Tools' edited copy (V, F) shown in the scan's place
        previews    [(name, V, F)] shown beside it, see-through
        map         the colour map {kind, rgb (n, 3), key, legend} on the
                    shown mesh, or None
        elements, dimensions, sections, items
                    [{"lines", "points", "face", "colour", "text", "at"}]
        flat        after a flat_ call, the 2D sheet (flat_plan): drawn on
                    top, the camera turned square onto it and framed on it

    memo: a dict kept between calls for one session (what was drawn last):
    elements, dimensions and sections new or changed since are drawn in
    the colour of what this call made, and a map stays while the calls
    after it belong to it."""
    memo = memo if memo is not None else {}
    st = S.state(session) if not isinstance(session, dict) else session
    scan = st.get("scan")
    tool = str(tool or "")
    out = {"scan": None, "mesh": None, "previews": [], "map": None, "elements": [], "dimensions": [], "sections": [], "items": [], "flat": None}
    # A flat_ call shows the 2D sheet (the flat workspace): an image's sheet
    # alone, with the scan and its 3D results put away until the next 3D
    # call; a section's sheet on the section's plane of the part, without
    # the 3D elements and dimensions (they are the 3D Measure's).
    flat = None
    if tool.startswith("flat_"):
        try:
            flat = flat_plan(st, tool, args, body, memo)
        except Exception:  # noqa: BLE001 — a sheet that cannot be read is not drawn; the call has answered
            flat = None
    out["flat"] = flat
    if flat is not None and (scan is None or flat["kind"] == "image"):
        out["scan"] = {"hide": True} if scan is not None else None
        memo["map"] = None
        return out
    if scan is None:
        memo.clear()
        return out
    copy, previews = mesh_tools(st)
    out["mesh"], out["previews"] = copy, previews
    out["scan"] = {"hide": copy is not None}

    # the colour map: this call's, else the last one while this call is of its family
    kind = map_kind(tool)
    if kind is None and memo.get("map") and _family_of(tool) == memo["map"]:
        kind = memo["map"]
    layer = map_layer(session, st, scan, tool, args, body, kind) if copy is None else None
    if layer is not None:
        layer["rgb"] = colours(layer)
        layer["legend"] = legend_model(layer)
        memo["map"] = layer["kind"]
    else:
        memo["map"] = None
    out["map"] = layer

    # What this call made or changed is drawn in its own colour; a call
    # that moves the whole part (an alignment, a scale) changes every
    # element's place and marks none.
    moves_all = tool.startswith(MOVES_ALL)
    marking = bool(memo.get("primed")) and not moves_all
    named = set() if moves_all else _named(body)
    seen = memo.get("elements") or {}
    now = {}
    for e in (st.get("elements", []) if flat is None else []):
        if not e.get("visible", True) or not e.get("fit"):
            continue
        sh = element_shape(e["fit"], e.get("assumed"))
        if sh is None:
            continue
        key = _fit_key(e)
        now[e.get("id")] = key
        changed = (marking and seen.get(e.get("id")) != key) or e.get("name") in named
        sh.update(colour=NEW if changed else ELEMENT, text=e.get("name"), name=e.get("name"), new=changed)
        out["elements"].append(sh)
    if flat is None:
        memo["elements"] = now

    seen_d = memo.get("dimensions") or {}
    now_d = {}
    for d in (st.get("dimensions", []) if flat is None else []):
        if not d.get("visible", True):
            continue
        sh = dimension_shape(st, d)
        if sh is None:
            continue
        key = (sh["text"], tuple(np.round(np.asarray(sh["at"], dtype=float), 6)))
        now_d[d.get("id")] = key
        changed = (marking and seen_d.get(d.get("id")) != key) or d.get("name") in named
        sh.update(colour=NEW if changed else DIMENSION, name=d.get("name"), new=changed)
        out["dimensions"].append(sh)
    if flat is None:
        memo["dimensions"] = now_d

    ss = st.get("sectionState") or {}
    seen_s = memo.get("sections") or {}
    now_s = {}
    for sec in ss.get("sections", []) if ss.get("scan") is scan else []:
        if not sec.get("visible", True):
            continue
        sh = section_shape(sec)
        if sh is None:
            continue
        key = (sec.get("name"), id(sec.get("points")))
        now_s[sec.get("id")] = key
        changed = (marking and seen_s.get(sec.get("id")) != key) or sec.get("name") in named
        sh.update(colour=NEW if changed else SECTION, text=sec.get("name"), name=sec.get("name"), new=changed, points=[], face=None)
        out["sections"].append(sh)
    memo["sections"] = now_s
    memo["primed"] = True

    out["items"] = transient(session, st, scan, tool, args, body)
    return out


def _named(body):
    """The names of the element, dimension or section a call's answer is
    about (element_fit's element, dimension_add's dimension, section_cut's
    section): drawn as this call's even where nothing was drawn before."""
    b = body if isinstance(body, dict) else {}
    out = set()
    for k in ("element", "dimension", "section"):
        v = b.get(k)
        if isinstance(v, dict) and isinstance(v.get("name"), str):
            out.add(v["name"])
    return out


def _family_of(tool):
    for p, k in (("deviation_", "deviation"), ("fit_scan_", "deviation"), ("thickness_", "thickness"), ("wear_", "wear")):
        if tool.startswith(p):
            return k
    return None


def size_of(scan):
    """The scan's size (its box's diagonal, mm), for marker and label sizes."""
    V = np.asarray(scan.V, dtype=float) if scan is not None else np.zeros((0, 3))
    return float(np.linalg.norm(V.max(0) - V.min(0))) if len(V) else 10.0
