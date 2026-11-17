# SPDX-License-Identifier: AGPL-3.0-only
# ScanRuler for FreeCAD's tools as Agent Link's window echo shows them
# (agentlink/echo.py declare(); the family module agentlink_families hands
# these on): which reads bring the ScanRuler workbench up and light their
# key, the keys for the tools whose key hangs on an argument, the words of
# each call with what it measured, and what to select after it.
#
# Window review round 3 (125 pictures of the ScanRuler tools in FreeCAD):
# scan_open, scan_info, scan_qa and the Mesh Tools stayed in the Mesh
# workbench (they change ScanRuler's state, not the FreeCAD model, so the
# echo took them for reads, and a read never switches the bench); captions
# were the tool's name, with no measured value ("Scan nearest", "Wear
# diff"); the hidden mesh scan_open read from stayed selected.
#
# Pure Python and the add-on's own data: no FreeCAD, no Agent Link.

import json
import os

from . import workspaces as W

WB = "ScanRulerWorkbench"
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "tools.json")


def _entries():
    with open(DATA, encoding="utf-8") as f:
        return json.load(f)["entries"]


# Reads that bring the ScanRuler workbench up and light their key, as a
# changing call does (Agent Link's OPENS): every tool of the workbench that
# changes ScanRuler's state or shows a result — all its reads but the
# snapshot tools, which only read the person's shots (no bench comes up
# for those; agentlink_families.WORKBENCHES). Their tools.json "changes"
# stays false: they change no FreeCAD object, so no undo step is opened.
OPENS = tuple(sorted(n for n, e in _entries().items()
                     if e.get("workbench") == WB and not e.get("changes") and not n.startswith("scan_snapshot_")))

# Keys for tools the workspace tables give none (workspaces.command_for):
# Open Scan… (the ScanRuler menu's), and the element keys by kind for the
# fits from marked points and the constructions.
COMMANDS = {"scan_open": "ScanRuler_OpenScan"}
BY_KIND = ("element_fit_marked", "element_construct")


def command_for(name, args):
    """The key a call lights: the workspace tables' (element_fit by kind,
    reverse_feature_add by feature), the element key of its kind for a fit
    from marked points or a construction, else None."""
    a = args if isinstance(args, dict) else {}
    if name in BY_KIND and a.get("kind"):
        return W.command_for("element_fit", {"kind": a["kind"]})
    return W.command_for(name, a)


# ---- words -------------------------------------------------------------------------------------------


def _n(x, nd=3):
    """A number as the panel writes it: rounded, no trailing zeros past the point."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    if isinstance(x, int):
        return f"{x:,}"
    s = f"{x:.{nd}f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def _mm(x, nd=3):
    s = _n(x, nd)
    return f"{s} mm" if s is not None else None


def _d(b, *path):
    for k in path:
        if not isinstance(b, dict):
            return None
        b = b.get(k)
    return b


def _element(el):
    """'Top (plane)', 'Bore (cylinder Ø 12.000 mm)'."""
    if not isinstance(el, dict):
        return None
    name, kind = el.get("name"), el.get("kind")
    fit = el.get("fit") or {}
    size = None
    if isinstance(fit.get("radius"), (int, float)) and kind in ("cylinder", "sphere", "circle"):
        size = f"Ø {_n(2 * fit['radius'])} mm"
    elif kind == "plane" and isinstance(fit.get("formError"), (int, float)):
        size = f"flat to {_n(fit['formError'], 4)} mm"
    elif isinstance(fit.get("sigma"), (int, float)):
        size = f"σ {_n(fit['sigma'], 4)} mm"
    inner = f"{kind}, {size}" if size else kind
    return f"{name} ({inner})" if name and inner else name


def _dimension(dm):
    if not isinstance(dm, dict):
        return None
    shown = dm.get("display") or (_mm(dm.get("value")) if dm.get("unit") == "mm" else _n(dm.get("value")))
    v = dm.get("verdict")
    verdict = "" if not isinstance(v, dict) else (", in tolerance" if v.get("pass") else ", out of tolerance")
    return f"{dm.get('name')} = {shown}{verdict}" if shown else dm.get("name")


def _dev(body):
    dv = body.get("deviation") if isinstance(body, dict) else None
    if not isinstance(dv, dict):
        return None
    st = dv.get("stats") or {}
    bits = []
    if isinstance(_d(dv, "align", "rms"), (int, float)):
        bits.append(f"fit RMS {_mm(dv['align']['rms'], 4)}")
    if isinstance(st.get("rms"), (int, float)):
        bits.append(f"RMS {_mm(st['rms'], 4)}")
    if isinstance(st.get("withinTolerancePct"), (int, float)):
        tol = _d(dv, "settings", "tolerance")
        bits.append(f"{_n(st['withinTolerancePct'], 1)} % within ±{_n(tol)} mm" if tol is not None else f"{_n(st['withinTolerancePct'], 1)} % in tolerance")
    rng = _d(dv, "settings", "range")
    if isinstance(rng, (int, float)) and dv.get("map") == "ready":
        bits.append(f"map ±{_n(rng)} mm")
    return ", ".join(bits) or None


def _count(v, one, many=None):
    if isinstance(v, list):
        v = len(v)
    if not isinstance(v, int) or isinstance(v, bool):
        return None
    return f"{v:,} {one if v == 1 else (many or one + 's')}"


def _file(b):
    f = b.get("file") if isinstance(b, dict) else None
    if isinstance(f, dict) and f.get("name"):
        return f["name"]
    p = b.get("path") if isinstance(b, dict) else None
    return os.path.basename(p) if isinstance(p, str) and p else None


def _mesh(b):
    m = b.get("mesh") if isinstance(b, dict) else None
    if isinstance(m, dict) and isinstance(m.get("triangles"), int):
        return f"{m.get('working', 'mesh')} {m['triangles']:,} triangles"
    return None


def _join(head, *tail):
    tail = [t for t in tail if t]
    return f"{head}: {', '.join(tail)}" if tail else head


def words(name, args=None, body=None):
    """What a ScanRuler call did, with what it measured, in the window's
    caption ("Fitted Bore (cylinder Ø 12.000 mm)", "Nearest scan point
    0.412 mm away"), or None to leave the words to Agent Link. Read from
    the call's own answer, never from an earlier one. Plain Python."""
    if not isinstance(body, dict):
        return None
    a = args if isinstance(args, dict) else {}
    b = body
    name = str(name or "")
    try:
        return _words(name, a, b)
    except Exception:  # noqa: BLE001 — words never stop a call
        return None


def _words(name, a, b):
    if name == "scan_open":
        o = b.get("opened") or {}
        return _join(f"Opened {o.get('file') or 'the scan'}", _count(o.get("triangles"), "triangle"), _count(len(b.get("warnings") or []) or None, "warning"))
    if name == "scan_info":
        s = b.get("scan") or {}
        size = s.get("box", {}).get("size") if isinstance(s.get("box"), dict) else None
        return _join(f"Scan {s.get('file') or ''}".strip(), _count(s.get("triangles"), "triangle"),
                     " × ".join(_n(x, 1) for x in size) + " mm" if isinstance(size, list) and len(size) == 3 else None) if s else "No scan open"
    if name == "scan_qa":
        return _join("Checked the scan", _count(_d(b, "rims", "count"), "open rim"),
                     f"noise {_mm(_d(b, 'noise', 'median'), 4)}" if _d(b, "noise", "median") is not None else None)
    if name == "scan_nearest":
        return _join("Nearest scan point", f"vertex {b.get('vertex')}" if b.get("vertex") is not None else None,
                     f"{_mm(b.get('distance'))} away" if isinstance(b.get("distance"), (int, float)) else None)
    if name == "scan_query":
        if b.get("marked"):
            return f"Marked {_count(_d(b, 'marked', 'points'), 'scan point')}"
        return _join("Read the scan", _count(b.get("matched"), "point") + " matched" if isinstance(b.get("matched"), int) else None)
    if name == "scan_segment":
        return _join("Segmented the scan", _count(b.get("found"), "flat or round region"), f"marked {_count(_d(b, 'marked', 'points'), 'point')}" if b.get("marked") else None)
    if name == "scan_draft":
        return _join("Draft map", _count(b.get("walls"), "wall point"), _count(b.get("found"), "patch", "patches"))
    if name == "scan_heightmap":
        lo, hi = b.get("min"), b.get("max")
        rng = f"{_n(lo)} to {_n(hi)} mm" if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) else None
        return _join(f"{str(b.get('of') or 'height').capitalize()} map along {b.get('along') or b.get('axis') or 'its plane'}", rng, _count(b.get("levels"), "level"))
    if name == "scan_outline":
        return _join("Outline traced", _count(b.get("loops"), "loop"), f"to {_mm(b.get('tolerance'))}" if b.get("tolerance") is not None else None)
    if name == "scan_fit_surface":
        best = b.get("best")
        rms = _d(b, "models", best, "rms") if best else None
        return _join("Fitted a surface", f"{best}" if best else None, f"RMS {_mm(rms, 4)}" if rms is not None else None, _count(b.get("points"), "point"))
    if name == "scan_scale":
        head = "Would scale the scan" if b.get("dryRun") else "Scaled the scan"
        return _join(head, f"× {_n(b.get('factor'), 6)}" if b.get("factor") is not None else None,
                     f"{_mm(_d(b, 'size', 'before'))} → {_mm(_d(b, 'size', 'after'))} across" if isinstance(b.get("size"), dict) else None)
    if name in ("element_fit", "element_fit_marked", "element_construct"):
        verb = "Constructed" if name == "element_construct" else "Fitted"
        return f"{verb} {_element(b.get('element')) or 'an element'}"
    if name == "element_rename":
        return f"Renamed to {_d(b, 'element', 'name')}" if _d(b, "element", "name") else None
    if name == "element_remove":
        gone = [r.get("name") for r in b.get("removed") or [] if isinstance(r, dict)]
        return _join("Removed " + (", ".join(gone) if gone else "the element"), _count(len(b.get("dimensionsRemoved") or []) or None, "dimension") + " with it" if b.get("dimensionsRemoved") else None)
    if name == "element_list":
        return _join("Elements", _count(b.get("elements"), "element"))
    if name in ("dimension_add", "dimension_set_basic", "dimension_set_limit"):
        verb = {"dimension_add": "Dimension", "dimension_set_basic": "Basic size set", "dimension_set_limit": "Limit set"}[name]
        return _join(verb, _dimension(b.get("dimension")))
    if name == "dimension_remove":
        gone = b.get("removed")
        return f"Removed dimension {gone.get('name') if isinstance(gone, dict) else a.get('dimension') or ''}".strip()
    if name == "report_get":
        return _join("Report", _count(b.get("dimensions"), "dimension"), _count(b.get("elements"), "element"))
    if name == "section_cut":
        s = b.get("section") or {}
        return _join(f"Cut section {s.get('name') or ''}".strip(), f"{s.get('across')}{' at ' + _mm(s.get('offset')) if s.get('offset') is not None else ''}" if s.get("across") else None,
                     _count(s.get("chains") if isinstance(s.get("chains"), (list, int)) else None, "chain"))
    if name == "section_list":
        return _join("Sections", _count(b.get("sections"), "section"))
    if name == "section_fit":
        return _join(f"Fitted section {_d(b, 'section', 'name') or ''}".strip(), _count(b.get("chains"), "chain"))
    if name == "section_get":
        return _join(f"Section {_d(b, 'section', 'name') or ''}".strip(), _count(b.get("chains"), "chain"))
    if name == "section_remove":
        return _join("Removed the section", _count(b.get("sections"), "section") + " left" if isinstance(b.get("sections"), list) else None)
    if name in ("align_auto", "align_symmetry", "align_datum"):
        ap = b.get("applied") or {}
        head = {"align_auto": "Auto-aligned the scan to its own axes", "align_symmetry": "Centred on the mirror plane", "align_datum": "Aligned the scan to its datums"}[name]
        rms = _d(b, "symmetry", "rms")
        return _join(head, f"turned {_n(ap.get('rotationDeg'), 2)}°" if ap.get("rotationDeg") is not None else None,
                     f"moved {_mm(ap.get('moveMm'))}" if ap.get("moveMm") is not None else None,
                     f"mirror RMS {_mm(rms, 4)}" if rms is not None else None)
    if name == "align_clear":
        return "Alignment cleared: the scan stands as it was read"
    if name.startswith("deviation_"):
        verb = {"deviation_open_reference": "Reference opened", "deviation_align": "Aligned the scan to the reference",
                "deviation_measure": "Deviation measured", "deviation_set_target": "Deviation against " + str(a.get("element") or "the element"),
                "deviation_settings": "Deviation settings", "deviation_hotspots": "Hot spots", "deviation_volume": "Volume errors",
                "deviation_export": "Deviation exported"}.get(name, "Deviation")
        if name == "deviation_open_reference":
            ref = _d(b, "deviation", "reference") or {}
            return _join(f"{verb}: {ref.get('fileName')}" if ref.get("fileName") else verb, _count(ref.get("triangles"), "triangle"))
        if name == "deviation_hotspots":
            spots = b.get("hotspots") if isinstance(b.get("hotspots"), list) else b.get("patches")
            return _join(verb, _count(spots, "hot spot"))
        if name == "deviation_volume":
            ex, mi = _d(b, "excess", "volume"), _d(b, "missing", "volume")
            return _join(verb, f"excess {_n(ex, 1)} mm³" if ex is not None else None, f"missing {_n(mi, 1)} mm³" if mi is not None else None, _count(b.get("regions"), "region"))
        if name == "deviation_export":
            return _join(verb, _file(b), f"{_n(b.get('withinTolerancePct'), 1)} % within ±{_n(b.get('tolerance'))} mm" if b.get("withinTolerancePct") is not None else None)
        return _join(verb, _dev(b))
    if name.startswith("thickness_"):
        s = _d(b, "thickness", "stats") or {}
        return _join("Wall thickness" if name == "thickness_measure" else "Wall thickness settings",
                     f"{_mm(s.get('min'))} to {_mm(s.get('max'))}" if s.get("min") is not None and s.get("max") is not None else None,
                     f"{_n(s.get('belowLimitPct'), 1)} % under the limit" if s.get("belowLimitPct") is not None else None,
                     _count(_d(b, "thinSpots", "count"), "thin spot"))
    if name == "wear_diff":
        rows = [r for r in b.get("regions") or [] if isinstance(r, dict)]
        bits = [f"{r.get('name')} lost {_mm(r.get('lost'))}, added {_mm(r.get('added'))}" for r in rows[:2]]
        return _join("Wear", *bits) if bits else "Wear: no worn region read"
    if name.startswith("mesh_"):
        edit = _d(b, "edit", "text")
        if name == "mesh_undo":
            return _join(f"Undid {b.get('undone')}" if b.get("undone") else "Undid the last mesh edit", _mesh(b))
        if name == "mesh_use_edited":
            return _join("The edited mesh is the scan now", _count(_d(b, "scan", "triangles"), "triangle"))
        if name == "mesh_discard_edited":
            return _join("Edits discarded", _mesh(b))
        if name == "mesh_parts":
            ed = b.get("edited") or {}
            return _join("Mesh parts", f"scan {_count(_d(b, 'scan', 'triangles'), 'triangle')}", f"edited copy {_count(ed.get('triangles'), 'triangle')}" if ed else "no edited copy")
        if name == "mesh_export":
            return _join("Exported the mesh", _file(b))
        if name == "mesh_reduce":
            r = b.get("reduced") or {}
            return _join("Reduced (preview)", _count(r.get("triangles"), "triangle"), f"worst {_mm(r.get('maxDeviation') or r.get('worst'))}" if (r.get("maxDeviation") or r.get("worst")) is not None else None)
        if name == "mesh_cut_preview":
            return _join(f"Cut preview at {b.get('plane')}" if b.get("plane") else "Cut preview", "cuts the mesh" if b.get("cuts") else "does not cut the mesh" if "cuts" in b else None)
        if name == "mesh_inspect":
            return _join("Inspected the mesh", _mesh(b) or (_count(b.get("triangles"), "triangle") if isinstance(b.get("triangles"), int) else None),
                         _count(b.get("open"), "open edge") if isinstance(b.get("open"), int) else None)
        if name == "mesh_wrap":
            return _join("Wrapped (preview beside the mesh)", _count(_d(b, "wrap", "triangles") or b.get("triangles"), "triangle"))
        if edit:
            return _join(edit[:1].upper() + edit[1:], _mesh(b))
        return None
    if isinstance(b.get("file"), dict):
        return _join(name.replace("_", " ").capitalize(), _file(b))
    return None


# ---- what to select ----------------------------------------------------------------------------------


def selects(name, args, body, doc):
    """The names of the document objects to select after a call, or None
    to leave it to Agent Link: after a call that opens or replaces the
    scan, the scan's own mesh object — not the mesh it was read from,
    which scan_open hides (window review round 3, sr-a 0008: the hidden
    original stayed selected); after deviation_open_reference, the
    reference."""
    try:
        from . import docstate
    except ImportError:
        return None
    role = None
    if name in ("scan_open", "mesh_use_edited", "scan_scale"):
        role = "scan"
    elif name == "deviation_open_reference":
        role = "reference"
    if role is None or doc is None:
        return None
    try:
        o = docstate.role_object(doc, role)
    except Exception:  # noqa: BLE001
        return None
    return [o.Name] if o is not None else None


# Words Agent Link reads today (PHRASES: activity templates filled from the
# call's arguments and the top of its answer; a nested figure cannot be
# reached), for the tools whose answer carries its figure at the top.
# words() above gives the rest once Agent Link reads it (WORDS).
PHRASES = {
    "scan_nearest": ["Nearest scan point: vertex {vertex}, {distance} mm away"],
    "scan_query": ["Marked {matched} scan points if {marked}", "Read {matched} scan points"],
    "scan_segment": ["Segmented the scan: {found} flat or round regions"],
    "scan_draft": ["Draft map: {walls} wall points in {found} patches"],
    "scan_heightmap": ["Height map along {along}: {min} to {max} mm if {of=height}", "Map along {along}: {min} to {max}"],
    "align_auto": ["Auto-aligned the scan to its own axes ({method}, standing on its {base}): not a fit to a reference"],
    "align_clear": ["Alignment cleared: the scan stands as it was read"],
    "scan_scale": ["Would scale the scan by {factor} if {dryRun}", "Scaled the scan by {factor}"],
    "deviation_export": ["Deviation exported: {withinTolerancePct} % within ±{tolerance} mm"],
    "mesh_undo": ["Undid {undone}"],
}
