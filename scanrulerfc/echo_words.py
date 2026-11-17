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
# Window pass 3 (17 Nov): most captions were still the tool's name
# (fit_scan_*, flat_*, mesh_trim, scan_noise, scan_pattern, wear_setup,
# element_set_visible, report_get), and flat_profile's was its help text
# (Agent Link read the answer's note). Every tool of this add-on now has
# words from its own answer; other tools (Agent Link's, other add-ons')
# get None here, so their own words stand.
#
# Pure Python and the add-on's own data: no FreeCAD, no Agent Link.

import json
import math
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

# The tools these words are for: this add-on's own, every one in tools.json.
OWN = frozenset(_entries())

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
    """'edited copy 10,036 triangles, 22,431 mm³' (and its open edges when
    there are any): the mesh as a Mesh Tools edit left it."""
    m = b.get("mesh") if isinstance(b, dict) else None
    if isinstance(m, dict) and isinstance(m.get("triangles"), int):
        out = f"{m.get('working', 'mesh')} {m['triangles']:,} triangles"
        if isinstance(m.get("volume"), (int, float)) and not isinstance(m.get("volume"), bool):
            out += f", {_vol(m['volume'])}"
        if isinstance(m.get("open"), int) and m["open"] > 0:
            out += f", {m['open']:,} open edges"
        return out
    return None


def _vol(v, nd=1):
    """'22,431.2 mm³'."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    s = f"{v:,.{nd}f}".rstrip("0").rstrip(".")
    return f"{s} mm³"


def _clause(text, most=90):
    """The first clause of an answer's own sentence ('Trimmed Stub to the
    break — 499.0 mm³, …' stays whole up to most characters)."""
    t = str(text or "").strip()
    if not t:
        return None
    for stop in (". ", "; "):
        i = t.find(stop)
        if 0 < i < most:
            t = t[:i]
            break
    t = t.rstrip(".")
    return t if len(t) <= most else t[: most - 1].rstrip() + "…"


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
    if name not in OWN:
        # Agent Link asks every add-on's words for every call: another
        # add-on's tools (and Agent Link's own) keep their own words.
        return None
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
        marked = _d(b, "element", "source", "markedPoints")
        return _join(f"{verb} {_element(b.get('element')) or 'an element'}", f"from {marked:,} marked points" if isinstance(marked, int) else None)
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
        r = b.get("report") if isinstance(b.get("report"), dict) else b
        ch = r.get("checks") if isinstance(r.get("checks"), dict) else None
        lines = len([x for x in str(b.get("text") or "").splitlines() if x.strip()]) if b.get("text") else None
        return _join("Measurement report", _count(r.get("elements"), "element"), _count(r.get("dimensions"), "dimension"),
                     f"{ch.get('pass', 0)} of {ch.get('checked', 0)} checks pass" if ch and ch.get("checked") else None,
                     f"{lines} lines of text" if lines else None)
    if name == "export_csv":
        return _join("Exported the measurements", _file(b), _count(b.get("rows"), "row"))
    if name == "element_set_visible":
        el = b.get("element") or {}
        return f"{'Showed' if el.get('visible') else 'Hid'} {el.get('name') or 'the element'}" if el else None
    if name == "element_unlink":
        el = b.get("element") or {}
        src = el.get("source") or {}
        return _join(f"Unlinked {el.get('name') or 'the element'}", f"now fixed coordinates ({src.get('method')})" if src.get("method") else "now fixed coordinates")
    if name == "element_to_document":
        made = b.get("made") if isinstance(b.get("made"), list) else []
        kinds = ", ".join(f"{m.get('name') or m.get('label')} {m.get('shape') or m.get('kind') or ''}".strip() for m in made[:4] if isinstance(m, dict))
        return _join(f"Made {len(made)} object{'' if len(made) == 1 else 's'} in {b.get('group') or 'the document'}", kinds or None, _file(b))
    if name == "section_to_sketch":
        fitted = b.get("fitted") if isinstance(b.get("fitted"), (dict, list)) else None
        if isinstance(fitted, list):
            lines = sum(int((c or {}).get("lines") or 0) for c in fitted if isinstance(c, dict))
            arcs = sum(int((c or {}).get("arcs") or 0) + int((c or {}).get("circles") or 0) for c in fitted if isinstance(c, dict))
        elif isinstance(fitted, dict):
            lines, arcs = int(fitted.get("lines") or 0), int(fitted.get("arcs") or 0) + int(fitted.get("circles") or 0)
        else:
            lines = arcs = None
        return _join(f"Sketch {b.get('sketch') or ''} in {b.get('body') or 'a body'}".replace("Sketch  in", "Sketch in"),
                     f"{lines} lines, {arcs} arcs or circles" if lines is not None else None, _count(b.get("wires"), "wire"))
    if name == "section_cut":
        s = b.get("section") or {}
        return _join(f"Cut section {s.get('name') or ''}".strip(), f"{s.get('across')}{' at ' + _mm(s.get('offset')) if s.get('offset') is not None else ''}" if s.get("across") else None,
                     _count(s.get("chains") if isinstance(s.get("chains"), (list, int)) else None, "chain"))
    if name == "section_list":
        return _join("Sections", _count(b.get("sections"), "section"))
    if name == "section_fit":
        kinds = {}
        for c in b.get("chains") or []:
            for pc in (c.get("pieces") or []) if isinstance(c, dict) else []:
                if isinstance(pc, dict) and pc.get("kind"):
                    kinds[pc["kind"]] = kinds.get(pc["kind"], 0) + 1
        return _join(f"Fitted section {_d(b, 'section', 'name') or ''}".strip(), _count(b.get("chains"), "chain"),
                     ", ".join(_count(v, k) for k, v in sorted(kinds.items())) or None)
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
            first = spots[0] if isinstance(spots, list) and spots and isinstance(spots[0], dict) else {}
            return _join(verb, _count(b["found"] if isinstance(b.get("found"), int) else spots, "hot spot"),
                         f"worst {_mm(first.get('extreme'))} {first.get('side') or ''}".rstrip() if first.get("extreme") is not None else None,
                         f"{_n(first.get('area'), 1)} mm²" if first.get("area") is not None else None)
        if name == "deviation_volume":
            ex, mi = _d(b, "excess", "volume"), _d(b, "missing", "volume")
            rows = [r for r in b.get("regions") or [] if isinstance(r, dict)]
            first = rows[0] if rows else {}
            return _join(verb, f"excess {_n(ex, 1)} mm³" if ex is not None else None, f"missing {_n(mi, 1)} mm³" if mi is not None else None,
                         _count(b["found"] if isinstance(b.get("found"), int) else rows, "region"),
                         f"largest {first.get('kind')} {_vol(first.get('volume'))}, {_mm(first.get('maxDepth'), 2)} deep" if first.get("volume") is not None else None)
        if name == "deviation_export":
            return _join(verb, _file(b), f"{_n(b.get('withinTolerancePct'), 1)} % within ±{_n(b.get('tolerance'))} mm" if b.get("withinTolerancePct") is not None else None)
        if name == "deviation_settings":
            se = _d(b, "deviation", "settings") or {}
            return _join(verb, f"colours ±{_mm(se.get('range'))}" if se.get("range") is not None else None,
                         f"tolerance ±{_mm(se.get('tolerance'))}" if se.get("tolerance") is not None else None,
                         f"search {_mm(se.get('maxDistance'))}" if se.get("maxDistance") is not None else None) if se else _join(verb, _dev(b))
        return _join(verb, _dev(b))
    if name == "thickness_settings":
        se = _d(b, "thickness", "settings") or b.get("settings") or {}
        return _join("Wall thickness settings", f"limit {_mm(se.get('limit'))}" if se.get("limit") is not None else None,
                     f"colours {_n(se.get('low'))} to {_mm(se.get('high'))}" if se.get("low") is not None and se.get("high") is not None else None,
                     f"{se.get('method')} up to {_mm(se.get('maxThickness'))}" if se.get("method") else None)
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
            w = b.get("wrap") or {}
            vol = _vol(w.get("volume"))
            if b.get("edit"):  # preview: false — applied at once
                return _join("Wrapped and applied", _mesh(b), f"wrap {vol}" if vol else None)
            return _join("Wrapped (a preview over the mesh)", _count(w.get("triangles") or b.get("triangles"), "triangle"), vol,
                         _count(w.get("shells"), "shell"))
        if name == "mesh_trim":
            pc = b.get("piece") or {}
            return _join(f"Trimmed {pc.get('name') or 'the piece'} to the break", _vol(pc.get("volume")),
                         f"mating face {_n(pc.get('matingArea'), 1)} mm²" if pc.get("matingArea") is not None else None) if pc else _clause(b.get("status"))
        if name == "mesh_discard":
            return _join(f"Discarded the {b.get('discarded') or a.get('what') or 'preview'}", _mesh(b))
        if name == "mesh_shell":
            ed = b.get("edit") or {}
            return _join(_cap(ed.get("text")) or "Hollowed", _count(ed.get("cavities"), "cavity", "cavities"), _mesh(b))
        if edit:
            return _join(edit[:1].upper() + edit[1:], _mesh(b))
        if b.get("status"):
            return _join(_clause(b["status"]), _mesh(b))
        return _generic(name, a, b)
    if name.startswith("flat_"):
        return _flat(name, a, b)
    if name.startswith("fit_scan_"):
        return _fit_scan(name, a, b)
    if name.startswith("wear_"):
        return _wear(name, a, b)
    if name.startswith("reverse_"):
        return _reverse(name, a, b)
    if name == "scan_noise":
        if b.get("sigmaMm") is not None:
            return _join("Scan noise", f"σ {_mm(b.get('sigmaMm'), 4)} (90 % under {_mm(b.get('p90'), 4)})" if b.get("p90") is not None else f"σ {_mm(b.get('sigmaMm'), 4)}",
                         f"point spacing {_mm(b.get('spacingMm'), 3)}" if b.get("spacingMm") is not None else None, _count(b.get("sampled"), "point") + " sampled" if isinstance(b.get("sampled"), int) else None)
        if b.get("added"):
            return _join("Kept a scanner", (b["added"] or {}).get("name") if isinstance(b.get("added"), dict) else None)
        if b.get("removed"):
            return f"Removed the scanner {b['removed']}"
        if "scanners" in b:
            return _join("Scanners", _count(b.get("scanners"), "scanner"), f"using {_d(b, 'using', 'name')}" if _d(b, "using", "name") else None)
        return _generic(name, a, b)
    if name == "scanner":
        return _join("Scanners", _count(b.get("scanners"), "scanner"), f"using {_d(b, 'using', 'name')}" if _d(b, "using", "name") else None,
                     f"exported {b['exported']}" if b.get("exported") is not None else None) if "scanners" in b or "exported" in b else _generic(name, a, b)
    if name == "scan_pattern":
        rows = [r for r in b.get("heights") or [] if isinstance(r, dict)]
        rep = [r for r in rows if isinstance(r.get("count"), int) and r["count"] > 1]
        if rep:
            best = max(rep, key=lambda r: r.get("score") or 0)
            return _join("Repeat found", f"{best['count']} × {_n(best.get('pitchDeg'), 2)}°" if best.get("pitchDeg") is not None else f"{best['count']} times",
                         f"score {_n(best.get('score'), 2)}" if best.get("score") is not None else None, f"at {len(rep)} of {len(rows)} heights")
        rings = [g for r in rows for g in (r.get("rings") or []) if isinstance(g, dict)]
        return _join("No repeat found", f"{len(rows)} heights read", f"a ring of radius {_mm(rings[0].get('radius'))}" if rings else None)
    if name == "scan_thread":
        return _join(f"Thread: {b.get('verdict') or 'read'}", (b.get("best") or {}).get("designation") if isinstance(b.get("best"), dict) else b.get("best"),
                     f"pitch {_mm(b.get('pitch'))}" if isinstance(b.get("pitch"), (int, float)) else None)
    if name == "scan_cloud":
        return _join("Wrote the point cloud", _file(b), _count(b.get("points"), "point"))
    if name.startswith("scan_snapshot_"):
        return _join({"scan_snapshot_latest": "Latest window shot", "scan_snapshot_list": "Window shots", "scan_snapshot_wait": "Waited for a window shot"}.get(name, "Window shot"),
                     _count(b.get("snapshots") or b.get("shots"), "shot") if (b.get("snapshots") or b.get("shots")) is not None else None,
                     _file(b), f"{b.get('width')} × {b.get('height')} px" if b.get("width") and b.get("height") else None,
                     _count(b.get("marks"), "mark") if isinstance(b.get("marks"), int) and b["marks"] else None)
    return _generic(name, a, b)


def _cap(t):
    t = str(t or "").strip()
    return t[:1].upper() + t[1:] if t else None


def _flat(name, a, b):
    """The 2D sheet's tools (ScanRuler's flat workspace)."""
    fl = b.get("flat") if isinstance(b.get("flat"), dict) else (b if "subject" in b and "elements" in b else None)
    el = b.get("element") if isinstance(b.get("element"), dict) else None
    note = b.get("note") if isinstance(b.get("note"), dict) else None
    if name == "flat_open_image":
        im = (fl or {}).get("image") or {}
        cal = (fl or {}).get("calibration") or {}
        ppm = cal.get("pxPerMm") or {}
        return _join(f"Opened the image {im.get('fileName') or a.get('path') or ''}".strip(), f"{im.get('width')} × {im.get('height')} px" if im.get("width") else None,
                     f"{_n(ppm.get('x'), 4)} px/mm from the file" if ppm.get("x") else "uncalibrated (pixels)", _count(_d(fl, "edges", "chains"), "edge chain"))
    if name == "flat_calibrate":
        c = b.get("calibration") or {}
        return _join("Calibrated the image", f"{_n(_d(c, 'pxPerMm', 'x'), 4)} px/mm ({_n(c.get('dpi'), 1)} dpi)" if _d(c, "pxPerMm", "x") else None,
                     f"places × {_n(b.get('scaledBy'), 4)}" if b.get("scaledBy") is not None else None, _count(b.get("chains"), "edge chain"))
    if name == "flat_detect_edges":
        return _join("Edges on the section" if b.get("note") and "section" in str(b.get("note")) else "Detected edges", _count(b.get("chains"), "chain"),
                     f"sensitivity {_n(a.get('sensitivity'), 2)}" if a.get("sensitivity") is not None else None)
    if name == "flat_edges":
        rows = [c for c in b.get("chains") or [] if isinstance(c, dict)]
        top = rows[0] if rows else None
        return _join("Edge chains", _count(b.get("total"), "chain"),
                     f"longest {_n(top.get('length'), 2)} {b.get('units') or 'mm'}{' closed' if top.get('closed') else ''}" if top else None)
    if name == "flat_objects":
        objs = [o for o in b.get("objects") or [] if isinstance(o, dict)]
        return _join("Parts on the image", _count(b.get("count"), "part"),
                     f"largest {_n(max(o.get('area') or 0 for o in objs), 2)} {b.get('units') or 'mm'}²" if objs else None, f"threshold {b.get('threshold')}" if b.get("threshold") is not None else None)
    if name == "flat_profile":
        ab = b.get("about") or {}
        sides = [x for x in b.get("sides") or [] if isinstance(x, dict)]
        sd = sides[0] if sides else {}
        u = b.get("units") or "mm"
        return _join(f"{_cap(ab.get('kind')) or 'Radial'} profile", f"{sd.get('peaks')} peaks" if sd.get("peaks") is not None else None,
                     f"{_n(sd.get('min'), 3)} to {_n(sd.get('max'), 3)} {u}" if sd.get("min") is not None else None,
                     f"pitch {_n(sd.get('pitch'), 2)}{'°' if sd.get('pitchUnit') == 'deg' else ' ' + u}" if sd.get("pitch") is not None else None,
                     f"{len(sides)} sides" if len(sides) > 1 else None)
    if name == "flat_curvature":
        if b.get("element"):
            st = [x for x in b.get("stretches") or [] if isinstance(x, dict)]
            arc = next((x for x in st if x.get("radius") is not None), None)
            return _join(f"Curvature of {b['element']}", _count(st, "stretch", "stretches"), f"radius {_mm(arc['radius'])}" if arc else None,
                         f"comb {_d(b, 'comb', 'object')}" if b.get("comb") else None)
        items = [x for x in b.get("items") or [] if isinstance(x, dict)]
        st = [x for it in items for x in it.get("stretches") or [] if isinstance(x, dict)]
        kinds = {}
        for x in st:
            kinds[x.get("kind")] = kinds.get(x.get("kind"), 0) + 1
        arc = next((x for x in st if x.get("radius") is not None), None)
        return _join(f"Curvature along {_count(items, 'chain')}", ", ".join(f"{v} {k}" for k, v in kinds.items() if k) or None,
                     f"radius {_mm(arc['radius'])}" if arc else None, f"comb {_d(b, 'comb', 'object')} ({_d(b, 'comb', 'teeth')} teeth)" if b.get("comb") else None)
    if name == "flat_fit":
        if not el:
            return None
        fit = el.get("fit") or {}
        k = el.get("kind")
        if k == "point" and fit.get("at"):
            val = f"at {_n(fit['at'][0], 3)}, {_n(fit['at'][1], 3)}"
        elif k in ("circle", "arc") and fit.get("radius") is not None:
            val = f"Ø {_n(2 * fit['radius'], 3)}" + (f", {_n(math.degrees(fit['sweep']), 1)}°" if k == "arc" and fit.get("sweep") is not None else "") + \
                  (f" at {_n(fit['center'][0], 3)}, {_n(fit['center'][1], 3)}" if fit.get("center") else "")
        elif k == "line" and fit.get("length") is not None:
            val = f"length {_n(fit['length'], 3)}" + (f" through {_n(fit['center'][0], 3)}, {_n(fit['center'][1], 3)}" if fit.get("center") else "")
        else:
            val = None
        return _join(f"Fitted 2D {k or 'element'} {el.get('name') or ''}".strip(), val, f"σ {_n(fit.get('sigma'), 4)}" if fit.get("sigma") is not None else None)
    if name == "flat_dimension_add":
        dims = [x for x in (fl or {}).get("dimensions") or [] if isinstance(x, dict)]
        want = a.get("name")
        i = next((n for n, x in enumerate(dims) if x.get("name") == want), None) if want else None
        i = len(dims) - 1 if i is None else i
        d = dims[i] if dims else None
        rows = _report_section(b.get("report"), "Dimensions")
        said = rows[i].split("—", 1)[-1].strip() if d and len(rows) == len(dims) else None
        val = f"{_n(d.get('value'), 3)} {(fl or {}).get('units') or ''}".strip() if d and d.get("value") is not None else None
        return _join(f"2D dimension {d.get('name') if d else ''}".strip(), said or val)
    if name == "flat_note_add":
        return _join("Added a note", f"\"{note.get('text')}\" at {_n(note['at'][0], 2)}, {_n(note['at'][1], 2)}" if note and note.get("at") else None)
    if name == "flat_edit":
        if note:
            return _join(f"Edited note {note.get('id')}", f"\"{note.get('text')}\"" if note.get("text") else None,
                         ("shown" if note.get("visible") else "hidden") if "visible" in note else None)
        what = a.get("element") if a.get("element") is not None else a.get("dimension")
        bits = []
        if a.get("name"):
            bits.append(f"now {a['name']}")
        if a.get("visible") is not None:
            bits.append("shown" if a["visible"] else "hidden")
        return _join(f"Edited {what}" if what is not None else "Edited the sheet", *bits)
    if name == "flat_remove":
        r = b.get("removed") or {}
        bits = [_count(r.get(k), one) for k, one in (("elements", "element"), ("dimensions", "dimension"), ("notes", "note")) if r.get(k)]
        return _join("Removed " + (", ".join(bits) if bits else "nothing"),
                     f"{', '.join(b['invalidDimensions'])} now invalid" if b.get("invalidDimensions") else None,
                     f"{_count(len((fl or {}).get('elements') or []), 'element')} left")
    if name == "flat_set_alignment":
        al = b.get("alignment")
        if a.get("clear") or not al:
            return "Cleared the sheet's alignment: image frame again"
        o = al.get("origin") or [0, 0]
        return _join("Aligned the sheet", f"origin {_n(o[0], 3)}, {_n(o[1], 3)}", f"X axis at {_n(al.get('angleDeg'), 2)}°")
    if name == "flat_report":
        t = str(b.get("text") or "")
        scale = next((ln.split(":", 1)[1].strip() for ln in t.splitlines() if ln.startswith("Scale:")), None)
        return _join("2D report", _count(len((fl or {}).get("elements") or []), "element"), _count(len((fl or {}).get("dimensions") or []), "dimension"),
                     _clause(scale, 50) if scale else None)
    if name == "flat_export":
        return _join(f"Exported the sheet as {str(b.get('format') or '').upper()}".strip(), _file(b), _count(b.get("elements"), "element"), _count(b.get("chains"), "chain"))
    if name == "flat_render":
        return _join("Drew the sheet", _file(b), f"{b.get('width')} × {b.get('height')} px" if b.get("width") else None,
                     f"{_n(_d(b, 'map', 'unitsPerPx'), 4)} {b.get('units') or 'mm'}/px" if _d(b, "map", "unitsPerPx") is not None else None)
    return _generic(name, a, b)


def _report_section(text, title):
    """The lines under a heading of a flat report ('Dimensions')."""
    out, inside = [], False
    for ln in str(text or "").splitlines():
        if ln.strip() == title:
            inside = True
            continue
        if inside:
            if not ln.strip():
                if out:
                    break
                continue
            if not ln.startswith(" "):
                break
            out.append(ln.strip())
    return out


def _fit_scan(name, a, b):
    """Print fit (ScanRuler's printer calibration from a scanned print)."""
    if name == "fit_scan_setup":
        s = b.get("settings") or {}
        return _join("Print fit setup", f"up {s.get('up')}" if s.get("up") else None, f"band {_mm(s.get('band'))}" if s.get("band") is not None else None,
                     f"slicer {s.get('slicer')}" if s.get("slicer") else None, _count(b.get("runs"), "run") + " so far" if isinstance(b.get("runs"), int) else None)
    if name == "fit_scan_features":
        circles = [c for c in b.get("circles") or [] if isinstance(c, dict)]
        holes = sum(1 for c in circles if c.get("hole") or c.get("kind") == "hole")
        return _join("Print fit features", _count(b.get("planes"), "plane"), _count(circles, "circle"),
                     f"{holes} hole{'' if holes == 1 else 's'}" if circles else None)
    if name == "fit_scan_measure":
        sc = b.get("scale") or {}
        bits = [f"scale {'/'.join(_n(_d(sc, k, 'value'), 4) or '-' for k in ('x', 'y', 'z'))}" if sc else None,
                f"contour {_mm(_d(b, 'contour', 'value'), 3)}" if _d(b, "contour", "value") is not None else None,
                f"hole {_mm(_d(b, 'hole', 'value'), 3)}" if _d(b, "hole", "value") is not None else None,
                f"χ²/dof {_n(b.get('fit'), 2)}{' (poor)' if b.get('poor') else ''}" if b.get("fit") is not None else None,
                _count(len(_d(b, "slicer", "changes") or []) if b.get("slicer") else None, "slicer change")]
        return _join(f"Print fit run {b.get('run')}" if b.get("run") else "Print fit measured", *bits)
    if name == "fit_scan_export":
        ch = b.get("changes")
        return _join("Exported the print fit", _file(b), _count(ch, "change") if isinstance(ch, list) else None,
                     "compensated STL" if b.get("applied") else None)
    return _generic(name, a, b)


def _wear(name, a, b):
    if name == "wear_setup":
        tags = [t for t in b.get("tags") or [] if isinstance(t, dict)]
        ref = b.get("reference") or {}
        s = b.get("settings") or {}
        return _join("Wear setup", (f"region{'s' if len(tags) != 1 else ''} " + ", ".join(str(t.get("name")) for t in tags[:4])) if tags else "no region",
                     f"reference {ref.get('name') or ref.get('source')}" if ref else "no reference yet",
                     f"tolerance {_mm(s.get('tolerance'))}" if s.get("tolerance") is not None else None)
    if name == "wear_rebuild":
        return _join("Rebuilt the worn surface", _file(b), _count(b.get("moved"), "point") + " moved" if isinstance(b.get("moved"), int) else None,
                     f"at most {_mm(b.get('largestMoveMm'))}" if b.get("largestMoveMm") is not None else None)
    if name == "wear_prewarp":
        return _join(f"Pre-warped target, run {b.get('run')}" if b.get("run") else "Pre-warped target", _file(b), f"RMS {_mm(b.get('rms'), 4)}" if b.get("rms") is not None else None,
                     "stop here" if b.get("stop") else ("print and scan again" if "stop" in b else None))
    return _generic(name, a, b)


def _bodies(b):
    rows = [x for x in b.get("bodies") or [] if isinstance(x, dict)]
    if not rows:
        return "no bodies" if "bodies" in b else None
    first = ", ".join(f"{x.get('name')} {_vol(x.get('volume'), 2)}" for x in rows[:2] if x.get("volume") is not None)
    return first + (f" and {len(rows) - 2} more" if len(rows) > 2 else "") if first else _count(rows, "body", "bodies")


def _reverse(name, a, b):
    """The Reverse engineer (ScanRuler's parametric feature tree)."""
    failed = [x for x in b.get("failed") or [] if isinstance(x, dict)]
    fail = f"{len(failed)} failed ({failed[0].get('name')})" if failed else None
    if name == "reverse_feature_add" or name == "reverse_import_step":
        added = [x for x in b.get("added") or [] if isinstance(x, dict)]
        names = ", ".join(str(x.get("name")) for x in added[:3])
        return _join(f"Added {names or 'a feature'}" if name == "reverse_feature_add" else f"Imported {names or 'the STEP file'}",
                     ", ".join(f"{x.get('status')}" for x in added[:1] if x.get("status")) or None, fail, _bodies(b))
    if name == "reverse_feature_suppress":
        on = a.get("suppressed", True)
        return _join(f"{'Suppressed' if on else 'Resumed'} {a.get('feature') or 'the feature'}", fail, _bodies(b))
    if name == "reverse_feature_clear":
        return _join("Cleared every feature and parameter", _bodies(b))
    if name == "reverse_feature_move":
        what = a.get("features") or a.get("feature")
        return _join(f"Moved {', '.join(map(str, what)) if isinstance(what, list) else what}" + (f" after {a.get('after')}" if a.get("after") is not None else " to the top"), fail, _bodies(b))
    if name == "reverse_feature_remove":
        return _join(f"Removed {_count(b.get('removed'), 'feature')}", fail, _bodies(b))
    if name == "reverse_feature_update":
        f = b.get("feature") or {}
        r = b.get("result") or {}
        return _join(f"Updated {f.get('name') or a.get('feature') or 'the feature'}", r.get("status"), fail, _bodies(b))
    if name == "reverse_feature_rollback":
        rb = b.get("rollback") or {}
        return _join("Rolled back" if rb.get("built") != rb.get("of") else "Rolled forward to the end", f"{rb.get('built')} of {rb.get('of')} built" if rb else None, _bodies(b))
    if name == "reverse_feature_list":
        rows = b.get("features")
        if rows is None:
            return _join(f"Feature {b.get('name') or a.get('feature')}", b.get("kind"), _d(b, "result", "status"))
        return _join("Features", _count(rows, "feature"), f"{_d(b, 'rollback', 'built')} of {_d(b, 'rollback', 'of')} built" if b.get("rollback") else None,
                     _count(b.get("parameters"), "parameter"))
    if name == "reverse_feature_schema":
        return _join(f"Fields of a {b.get('label') or b.get('kind') or 'feature'}", _count(len(b.get("fields") or {}), "field"))
    if name in ("reverse_build", "reverse_build_stop"):
        return _join("Rebuilt the part", _count(b.get("results"), "feature"), fail, _bodies(b))
    if name.startswith("reverse_parameter_"):
        q = b.get("parameter") if isinstance(b.get("parameter"), dict) else None
        if name == "reverse_parameter_list":
            return _join("Parameters", _count(b.get("parameters"), "parameter"))
        verb = {"reverse_parameter_add": "Added parameter", "reverse_parameter_set": "Set", "reverse_parameter_rename": "Renamed",
                "reverse_parameter_remove": "Removed parameter"}[name]
        who = (q or {}).get("name") or a.get("parameter") or a.get("name")
        val = f"= {_n(q.get('value'), 4)}" if q and q.get("value") is not None else None
        to = f"to {a.get('to')}" if name == "reverse_parameter_rename" and a.get("to") else None
        return _join(f"{verb} {who}".strip(), val, to, fail, _bodies(b))
    if name == "reverse_body_names":
        return _join("Bodies", _bodies(b))
    if name == "reverse_body_describe":
        bd = b.get("body") or {}
        return _join(f"Body {bd.get('name') or ''}".strip(), _count(b.get("faces"), "face"), _count(b.get("edges"), "edge"), _vol(bd.get("volume")))
    if name == "reverse_body_check":
        return _join(f"Checked {b.get('shownAs') or b.get('name') or 'the body'}", "closed" if b.get("closed") else "not closed", "valid" if b.get("valid") else "not valid",
                     _vol(b.get("volume")))
    if name == "reverse_body_set":
        bits = [f"now {a['name']}" if a.get("name") else None, f"colour {a['color']}" if a.get("color") else None,
                ("shown" if a["visible"] else "hidden") if a.get("visible") is not None else None]
        return _join(f"Set body {a.get('body')}", *bits)
    if name == "reverse_body_clearance":
        if b.get("overlap"):
            return _join("Bodies overlap", f"{_vol(b.get('overlap'), 2)} shared")
        return _join("Clearance", f"gap {_mm(b.get('gap'))}" if b.get("gap") is not None else None)
    return _generic(name, a, b)


# Each tool's words when no branch above reads its answer: the verb, then
# the answer's key values (_values).
HEADS = {
    "catalog_part": "Catalog parts", "catalog_links": "Catalog search links", "catalog_provenance": "File provenance",
    "manual_plan": "Assembly manual plan", "manual_check": "Checked the manual's steps", "manual_render": "Wrote the assembly manual",
    "pack_setup": "Pack setup", "pack_plan": "Pack plan", "pack_write": "Wrote the pack",
}


def _values(b):
    """A few key values of an answer: its file, counts of its lists and
    its volume, area, RMS or gap, in that order."""
    bits = [_file(b)]
    for k, one, many in (("parts", "part", None), ("links", "link", None), ("files", "file", None), ("steps", "step", None), ("pictures", "picture", None),
                         ("contents", "file", None), ("features", "feature", None), ("bodies", "body", "bodies"), ("elements", "element", None),
                         ("chains", "chain", None), ("results", "result", None), ("issues", "issue", None), ("problems", "problem", None)):
        v = b.get(k)
        if isinstance(v, (list, int)) and not isinstance(v, bool):
            bits.append(_count(v, one, many))
    for k, fmt in (("volume", _vol), ("rms", lambda x: f"RMS {_mm(x, 4)}"), ("gap", lambda x: f"gap {_mm(x)}"), ("count", lambda x: f"{x} found")):
        if isinstance(b.get(k), (int, float)) and not isinstance(b.get(k), bool):
            bits.append(fmt(b[k]))
    return [x for x in bits if x][:3]


def _generic(name, a, b):
    """Words for a tool no branch reads: its verb (HEADS, else its name in
    words) and the answer's key values; the answer's own status sentence
    where it has one. Never the tool's help: a note is not a result."""
    head = HEADS.get(name) or name.replace("_", " ").capitalize()
    if isinstance(b.get("status"), str) and b["status"].strip():
        return _join(_clause(b["status"]), *_values(b)[:2])
    return _join(head, *_values(b))


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
