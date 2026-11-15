# SPDX-License-Identifier: AGPL-3.0-only
# Ported from ScanRuler by Stefan Hermann (CNC Kitchen),
# github.com/CNCKitchen/ScanRuler: src/ui/Panel.tsx, ModelSlot.tsx,
# AlignmentSection.tsx, DraftEditor.tsx, SectionEditor.tsx, ShowAllButton.tsx,
# DimensionSection.tsx, ToleranceSection.tsx, src/core/summary.ts
# (formatPrimary, SIGMA_LABELS), src/core/formats.ts (SCAN_FORMATS),
# src/state/elementModel.ts (elementColor) and the measure-slot sections of
# plugins/scanner-profiles and plugins/thread-match.
#
# The 3D Measure page (design 2.1), in two layers. `build(st, ui)` is the
# page as data: its sections in the original's order, each with its header,
# its (i) text word for word, its rows and readings, its keys with whether
# they can be pressed, its fields with their options and defaults. It reads
# scanstate's session dict and the panel's own state (`ui`: the box that is
# open, the export choices) and imports no Qt, so the tests check it
# headless. `widget(model)` is the thin Qt view drawn from it, behind lazy
# imports. The model's footer carries the credit, where the original's status
# strip carried "§ IMPRINT"; the dock draws it once, at its foot.

from .. import legend as L
from .. import workspaces as W
from .infotext import INFO

TITLE = "3D Measure"
SCAN_DOT = "#8b9099"
SCAN_FORMATS = "STL, PLY, OBJ, 3MF or STEP · mm"
PALETTE = ("#1877c0", "#e8590c", "#2e7d46", "#b5179e", "#c99a0a", "#0f9b9b", "#b3361c", "#6d4bbd")

KINDS = (("point", "Point", "point"), ("line", "Line", "line"), ("plane", "Plane", "plane"),
         ("sphere", "Sphere", "sphere"), ("cylinder", "Cylinder", "cylinder"), ("cone", "Cone", "cone"),
         ("circle", "Circle", "circle"), ("torus", "Torus", "round"))
NOUN = {k: n for k, _l, n in KINDS}
SIGMA_LABELS = {0: "All points", 3: "3 sigma", 2: "2 sigma", 1: "1 sigma"}
SIGMA_ORDER = (3, 2, 1, 0)
SIGMA_DEFAULT = 3
SURFACE_OPTIONS = (("auto", "Found from a click"), ("paint", "Marked by hand"))
SEARCH_OPTIONS = (("auto", "Whole scan"), ("paint", "Marked surface"))
METHOD_OPTIONS = (("gaussian", "Gaussian best-fit"),)
MEASURE_OPTIONS = (("center", "Center to center"), ("gap", "Surface gap (− radii)"), ("span", "Outer span (+ radii)"))
MEASURE_DEFAULT = "center"
STEP_OPTIONS = (("solids", "Solids & faces"), ("surfaces", "Construction surfaces"))
STEP_DEFAULT = "solids"
CLOUD_OPTIONS = (("ply", "PLY (binary, with normals)"), ("xyz", "XYZ text (x y z nx ny nz)"))
CLOUD_DEFAULT = "ply"
TOLERANCES = ("Flatness", "Cylindricity", "Circularity", "Sphericity", "Parallelism", "Perpendicularity",
              "Angularity", "Coaxiality")

HINT_NO_SCAN = "Drop it anywhere in the window."
HINT_DISCARDED = ("Its marked surface is kept until the next element is started — bring it back to carry "
                  "on where you were, marking and all.")
HINT_SECTIONS = ("Measure a section in the <b>2D Measure</b> workspace. What you fit on its sheet is drawn "
                 "on the cut here and goes into the STEP file with the section.")
HINT_NO_ELEMENT = "Create at least one element first, then measure between them."
SECTION_TIP = "Cut the scan with a plane to measure in 2D"
EXPORT_TIPS = {"step": "Export the elements as STEP geometry",
               "mesh": "Save the scan as STL or 3MF, alignment included",
               "cloud": "Save the scan as a point cloud with normals"}

# The page's sections in the original's order (design 2.1): (number, id).
ORDER = (("1", "model"), ("2", "alignment"), ("3", "create_element"), ("—", "discarded"), ("4", "draft"),
         ("5", "section_editor"), ("6", "elements"), ("7", "sections"), ("8", "create_dimensions"),
         ("9", "dimensions"), ("10", "gdt"), ("11", "plugins"), ("12", "export"))


# --- readings (summary.ts formatPrimary, units.ts fmtLen) ---------------------

def element_color(num):
    return PALETTE[(num - 1) % len(PALETTE)]


def format_primary(fit, units="mm"):
    k = fit.get("kind")
    if k in ("sphere", "cylinder", "circle"):
        return f"Ø {L.fmt_len(fit['radius'] * 2, units, 3)}"
    if k == "cone":
        return f"∠ {L.to_fixed(fit['halfAngle'] * 2, 2)}°"
    if k == "torus":
        return f"R {L.fmt_len(fit['minorRadius'], units, 3)}"
    if k == "plane":
        return f"σ {L.fmt_len(fit['sigma'], units, 4)}" if fit.get("usedPoints", 0) > 0 else ""
    if k == "point":
        return "(" + ", ".join(L.fmt_len(c, units, 1, bare=True) for c in fit["center"]) + ")"
    return ""


def _plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


# --- the model ----------------------------------------------------------------

def _key(id_, label, enabled, tip=None, pressed=False, primary=False):
    return {"id": id_, "label": label, "enabled": bool(enabled), "tip": tip or label, "pressed": bool(pressed), "primary": primary}


def _field(id_, label, options, value, enabled=True, info=None):
    return {"id": id_, "label": label, "options": [{"value": v, "label": t} for v, t in options], "value": value,
            "enabled": bool(enabled), "info": info, "info_text": list(INFO[info]["paragraphs"]) if info else None}


def _section(num, id_, header, info=None, visible=True, **more):
    out = {"number": num, "id": id_, "header": header, "caption": header.upper(), "info": info,
           "info_text": list(INFO[info]["paragraphs"]) if info else None, "visible": bool(visible),
           "rows": [], "keys": [], "fields": [], "hint": None, "count": None, "show_all": None}
    out.update(more)
    return out


def _show_all(rows, what):
    any_on = any(r["visible"] for r in rows)
    return {"label": "Hide all" if any_on else "Show all",
            "tip": f"Hide all {what} in the viewport" if any_on else f"Show all {what}"}


def _identity_pose(scan):
    if scan is None:
        return True
    try:
        import numpy as np

        return scan.k == 1.0 and np.allclose(scan.R, np.eye(3)) and not np.any(scan.t)
    except (AttributeError, ImportError):
        return True


def _dimension_rows(st, family, units):
    from .. import dimensions as D

    rows = []
    for d in st.get("dimensions", []):
        info = D.type_info(d["type"])
        if info["family"] != family:
            continue
        try:
            from .. import model as M

            desc = M.describe_dimension(st, d)
            value, title = desc.get("display"), desc.get("title")
            verdict = desc.get("verdict")
        except Exception as e:  # an element it reads is gone: the row says so, as the original's ⚠
            value, title, verdict = "⚠", str(e), None
        rows.append({"id": d["id"], "name": d["name"], "type": info["label"], "title": title, "value": value,
                     "verdict": verdict, "visible": d.get("visible", True)})
    return rows


def build(st, ui=None, units="mm"):
    """The 3D Measure page as data, from scanstate's session dict `st`
    (scanstate.fresh() shape) and the panel's own state `ui`."""
    ui = dict(ui or {})
    busy = bool(ui.get("busy"))
    scan = st.get("scan")
    file_name = getattr(scan, "name", None)
    elements = st.get("elements", [])
    draft = ui.get("draft")  # {"kind", "method", "sigma", "editId", "name"}
    dim_draft = ui.get("dim_draft")
    section_draft = ui.get("section_draft")
    align_draft = ui.get("align_draft")
    discarded = ui.get("discarded")  # {"kind", "points", "editId"}
    editing = draft is not None and draft.get("editId") is not None
    editor_open = draft is not None or dim_draft is not None or section_draft is not None or align_draft is not None
    fitted = [e for e in elements if e.get("fit")]
    sections_data = (st.get("sectionState") or {}).get("sections", [])

    out = []
    for num, sid in ORDER:
        if sid == "model":
            s = _section(num, sid, "Model", "The scan")
            s["slot"] = {"role": "Scan", "name": file_name or "No scan loaded",
                         "detail": f"{len(scan.F):,} triangles" if scan is not None else SCAN_FORMATS,
                         "dot": SCAN_DOT, "filled": scan is not None,
                         "button": _key("open-scan", "Replace…" if scan is not None else "Open…", not busy)}
            s["hint"] = None if scan is not None else HINT_NO_SCAN
        elif sid == "alignment":
            s = _section(num, sid, "Alignment", "Alignment")
            ok = bool(file_name) and not busy and align_draft is None
            s["keys"] = [_key(k["key"], k["label"], ok) for k in W.TOOLBARS["elements"][0][1]]
            if not _identity_pose(scan):
                s["keys"].append(_key("ResetAlignment", "Reset alignment", not busy))
        elif sid == "create_element":
            s = _section(num, sid, "Create element", "Elements", visible=section_draft is None)
            ok = bool(file_name) and not busy and not editing and dim_draft is None
            s["keys"] = [_key(k, lab, ok, pressed=bool(draft) and draft.get("kind") == k and not editing) for k, lab, _n in KINDS]
            s["keys"].append(_key("section", "Section", bool(file_name) and not busy and dim_draft is None, SECTION_TIP))
            s["grid"] = 3
        elif sid == "discarded":
            show = bool(discarded and discarded.get("points")) and not draft and not align_draft and not section_draft
            what = NOUN.get((discarded or {}).get("kind"), "element")
            if discarded and discarded.get("editId") is not None:
                el = next((e for e in elements if e["id"] == discarded["editId"]), None)
                what = f"edit of {el['name'] if el else 'element'}"
            s = _section(num, sid, f"Discarded {what}", visible=show)
            s["reading"] = f"{(discarded or {}).get('points', 0):,} points"
            s["hint"] = HINT_DISCARDED
            s["keys"] = [_key("restore-draft", "Restore", True), _key("forget-draft", "Forget", True)]
        elif sid == "draft":
            kind = (draft or {}).get("kind")
            edited = next((e for e in elements if draft and e["id"] == draft.get("editId")), None)
            noun = NOUN.get(kind, "element")
            s = _section(num, sid, f"Edit {edited['name']}" if edited else f"New {noun}", visible=draft is not None,
                         dot=element_color(edited["id"] if edited else st.get("next", 1)))
            s["fields"] = [
                _field("surface", "Surface", SURFACE_OPTIONS, (draft or {}).get("method", "auto"), not busy, "Which surface is fitted"),
                _field("method", "Method", METHOD_OPTIONS, "gaussian", False),
                _field("sigma", "Used points", [(k, SIGMA_LABELS[k]) for k in SIGMA_ORDER],
                       (draft or {}).get("sigma", SIGMA_DEFAULT), not busy, "Used points"),
            ]
            s["keys"] = [_key("confirm-draft", "Save changes" if edited else f"Create {noun}", not busy, primary=True),
                         _key("cancel-draft", "Cancel", True)]
        elif sid == "section_editor":
            edited = next((x for x in sections_data if section_draft and x["id"] == section_draft.get("editId")), None)
            s = _section(num, sid, f"Edit {edited['name']}" if edited else "New section", "Sections", visible=section_draft is not None)
        elif sid == "elements":
            rows = []
            for e in elements:
                fit = e.get("fit")
                rows.append({"id": e["id"], "name": e["name"], "color": element_color(e["id"]), "visible": e.get("visible", True),
                             "reading": format_primary(fit, units) if fit else "⚠", "warn": not fit,
                             "selected": bool(draft) and draft.get("editId") == e["id"], "tools": ("edit", "eye", "bin"),
                             "edit_enabled": not editor_open})
            s = _section(num, sid, "Elements", visible=bool(elements), rows=rows, count=len(elements),
                         show_all=_show_all(rows, "elements") if rows else None)
        elif sid == "sections":
            rows = []
            for x in sections_data:
                chains = max(len(x.get("offsets", [0])) - 1, 0)
                rows.append({"id": x["id"], "name": x["name"], "color": element_color(x["id"]), "visible": x.get("visible", True),
                             "reading": _plural(chains, "edge"), "warn": False, "tools": ("edit", "eye", "bin")})
            s = _section(num, sid, "Sections", visible=bool(sections_data), rows=rows, count=len(rows),
                         show_all=_show_all(rows, "sections") if rows else None, hint=HINT_SECTIONS)
        elif sid == "create_dimensions":
            from .. import dimensions as D

            own = [d for d in st.get("dimensions", []) if D.type_info(d["type"])["family"] == "dimension"]
            s = _section(num, sid, "Create dimensions", "Dimensions", count=len(own) or None)
            s["keys"] = [_key("new-dimension", "New dimension", bool(fitted) and dim_draft is None and draft is None)]
            s["hint"] = HINT_NO_ELEMENT if (not fitted and file_name) else None
            s["fields"] = [_field("measure", "Measure", MEASURE_OPTIONS, (dim_draft or {}).get("anchor", MEASURE_DEFAULT))]
        elif sid == "dimensions":
            rows = _dimension_rows(st, "dimension", units)
            s = _section(num, sid, "Dimensions", visible=bool(rows), rows=rows, show_all=_show_all(rows, "dimensions") if rows else None)
        elif sid == "gdt":
            rows = _dimension_rows(st, "tolerance", units)
            s = _section(num, sid, "GD&T", "Geometric tolerances", rows=rows, count=len(rows) or None,
                         show_all=_show_all(rows, "tolerances") if rows else None, list_label="Tolerances",
                         types=list(TOLERANCES), slots=("Feature", "Datum", "Datum axis"))
            s["keys"] = [_key("new-tolerance", "New tolerance", bool(fitted) and dim_draft is None and draft is None)]
        elif sid == "plugins":
            s = _section(num, sid, "", visible=True)
            s["children"] = [_section("11a", "scanner_noise", "Scanner noise", "Scanner noise"),
                             _section("11b", "thread", "Thread", "Naming a scanned thread")]
        elif sid == "export":
            s = _section(num, sid, "", visible=bool(file_name))
            s["fields"] = [_field("step-style", "STEP as", STEP_OPTIONS, ui.get("step_style", STEP_DEFAULT), info="What the STEP file contains"),
                           _field("cloud-format", "Point cloud as", CLOUD_OPTIONS, ui.get("cloud_format", CLOUD_DEFAULT), info="What the point cloud contains")]
            any_fit = bool(fitted)
            s["keys"] = [_key("copy-summary", "Copy summary", any_fit),
                         _key("export-step", "Export STEP", any_fit or bool(sections_data), EXPORT_TIPS["step"]),
                         _key("export-mesh", "Export mesh", not busy, EXPORT_TIPS["mesh"]),
                         _key("export-cloud", "Export cloud", not busy, EXPORT_TIPS["cloud"])]
        out.append(s)
    return {"title": TITLE, "workspace": "elements", "sections": out, "footer": W.CREDIT}


# --- the Qt view --------------------------------------------------------------

def widget(model, on_key=None, on_field=None, parent=None):
    """The page drawn by the one view every page shares (kit.widget)."""
    from . import kit as K

    return K.widget(model, on_key, on_field, parent)
