# SPDX-License-Identifier: AGPL-3.0-only
# Ported from ScanRuler by Stefan Hermann (CNC Kitchen),
# github.com/CNCKitchen/ScanRuler: src/ui/FlatPanel.tsx,
# FlatDimensionSection.tsx, src/core/flat/elements.ts (FLAT_KIND_LABELS) and
# the defaults of src/state/flatStore.ts.
#
# The 2D Measure page (design 2.4) as data. Its nine sections stand in
# FlatPanel.tsx's order, which differs from the design table's numbering:
# Source (or Image), Calibration and Scanner profiles (an image only),
# Create element, Elements, Dimensions, the export keys, Alignment, and
# Section edges (a section) or Edge detection (an image). `build(st, ui)`
# reads the "flatState" block fam_flat keeps and the sections of
# "sectionState"; `widget(model)` is the thin Qt view.

from . import kit as K
from .infotext_pages import INFO

TITLE = "2D Measure"
WORKSPACE = "flat"
PAGE = "flat"

KINDS = (("point", "Point"), ("line", "Line"), ("circle", "Circle"), ("arc", "Arc"), ("spline", "Spline"),
         ("count", "Count"), ("text", "Text"))
# flatStore.ts initial state
DEFAULTS = {"splitAxes": False, "edgeSensitivity": 0.5, "showEdges": True, "snapToEdge": True, "showGrid": True}
IMAGE_FORMATS = "PNG or JPEG"
HINT_PROFILES = ("A measured calibration describes the scanner at one resolution, not the image — save it once, "
                 "apply it to every scan from that scanner.")
HINT_NO_DPI = "The file declares no physical resolution — sizes are pixels until calibrated."
HINT_NO_ELEMENTS = "Create at least two elements first, then measure between them."
HINT_EXPORT = ("The sheet as a drawing at true scale, aligned and turned as shown. SVG for a vector editor or a print "
               "at 1:1; DXF for CAD, the origin on the alignment and the edges thinned to a sketch's worth.")
TURN_TIPS = (("rotate-ccw", "Rotate 90°", "Turn the sheet a quarter turn counter-clockwise"),
             ("rotate-cw", "Rotate 90°", "Turn the sheet a quarter turn clockwise"),
             ("mirror-x", "Mirror", "Mirror the sheet left to right"),
             ("mirror-y", "Mirror", "Mirror the sheet top-to-bottom (vertically), as it is shown"))

ORDER = (("1", "source"), ("2", "calibration"), ("3", "scanner_profiles"), ("4", "create_element"), ("5", "elements"),
         ("6", "dimensions"), ("7", "export"), ("8", "alignment"), ("9", "edges"))


def _i(title):
    return K.info_of(INFO, PAGE, title)


def build(st, ui=None, units="mm"):
    ui = dict(ui or {})
    f = st.get("flatState") or {}
    s_ = dict(DEFAULTS)
    s_.update({k: v for k, v in ui.items() if k in DEFAULTS})
    if "sensitivity" in f:
        s_["edgeSensitivity"] = f["sensitivity"]
    sections = (st.get("sectionState") or {}).get("sections", [])
    subject = f.get("subject") or {}
    on_section = subject.get("kind") == "section"
    image_name = subject.get("name") if subject.get("kind") == "image" else ui.get("image_name")
    has_sheet = on_section or bool(image_name)
    calibrating = ui.get("calibrating")
    elements = f.get("elements", [])
    dims = f.get("dimensions", [])
    notes = f.get("notes", [])
    measured = bool(elements or dims or notes)
    chains = f.get("chains")
    out = []
    for num, sid in ORDER:
        if sid == "source":
            s = K.section(num, sid, "Source" if sections else "Image", "What is measured", _i("What is measured"))
            if sections:
                opts = [("image", f"Image — {image_name}" if image_name else "Flatbed image")]
                opts += [(f"section:{x['id']}", x["name"]) for x in sections]
                cur = f"section:{subject.get('id')}" if on_section else "image"
                s["fields"] = [K.select("flat-source", "Measure", opts, cur)]
            if not on_section:
                s["slot"] = {"role": "Image", "name": image_name or "No image loaded",
                             "detail": IMAGE_FORMATS if not image_name else "", "dot": K.SCAN_DOT, "filled": bool(image_name),
                             "button": K.key("open-image", "Replace…" if image_name else "Open…", True)}
                s["hint"] = None if image_name else K.HINT_DROP
        elif sid == "calibration":
            s = K.section(num, sid, "Calibration", "Calibration", _i("Calibration"), visible=bool(image_name) and not on_section)
            s["keys"] = [K.key("cal-distance", "Calibrate on a known distance", calibrating is None),
                         K.key("cal-diameter", "Calibrate on a known diameter", calibrating is None)]
            s["fields"] = [K.check("flat-cal-split", "Calibrate X and Y separately", s_["splitAxes"])]
            s["hint"] = None if f.get("pxPerMm") else HINT_NO_DPI
        elif sid == "scanner_profiles":
            s = K.section(num, sid, "Scanner profiles", visible=bool(image_name) and not on_section)
            s["hint"] = HINT_PROFILES
            s["fields"] = [K.select("flat-profile-select", "", [("", "Choose profile…")] + [(p, p) for p in ui.get("profiles", [])], "")]
        elif sid == "create_element":
            s = K.section(num, sid, "Create element", "Elements", _i("Elements"), visible=has_sheet)
            draft = ui.get("draft") or {}
            ok = calibrating is None and draft.get("editId") is None
            s["keys"] = [K.key(k, lab, ok, pressed=draft.get("kind") == k and draft.get("editId") is None) for k, lab in KINDS]
            s["grid"] = 4
        elif sid == "elements":
            rows = [{"id": e.get("id"), "name": e.get("name", ""), "reading": e.get("reading", ""), "visible": e.get("visible", True)}
                    for e in elements]
            s = K.section(num, sid, "Elements", visible=bool(rows), rows=rows, count=len(rows))
        elif sid == "dimensions":
            s = K.section(num, sid, "Create dimensions", "Dimensions", _i("Dimensions"), visible=has_sheet, count=len(dims) or None)
            s["keys"] = [K.key("flat-new-dimension", "New dimension", len(elements) >= 2)]
            s["hint"] = None if len(elements) >= 2 else HINT_NO_ELEMENTS
            s["rows"] = [{"id": d.get("id"), "name": d.get("name", ""), "reading": d.get("reading", ""), "visible": d.get("visible", True)}
                         for d in dims]
        elif sid == "export":
            s = K.section("—", sid, "", visible=has_sheet and (measured or bool(chains)))
            s["number"] = num
            s["keys"] = [K.key("copy-report", "Copy report", measured), K.key("flat-export-csv", "Export CSV", measured),
                         K.key("flat-export-svg", "Export SVG", has_sheet, "Save the sheet as a 1:1 SVG"),
                         K.key("flat-export-dxf", "Export DXF", has_sheet, "Save the sheet as a DXF for CAD, in millimetres")]
            s["grid"] = 2
            s["hint"] = HINT_EXPORT
        elif sid == "alignment":
            datum = f.get("alignment")
            s = K.section(num, sid, "Alignment", "Alignment", _i("Alignment"), visible=has_sheet)
            s["keys"] = [K.key("flat-datum", "Re-set alignment" if datum else "Set alignment", calibrating is None)]
            if datum:
                s["keys"].append(K.key("flat-datum-clear", "Clear"))
                s["fields"] = [K.check("flat-datum-grid", "Show grid", s_["showGrid"])]
            s["keys"] += [K.key(i, lab, True, tip) for i, lab, tip in TURN_TIPS]
        elif sid == "edges":
            n = len(chains) if chains else 0
            if on_section:
                s = K.section(num, sid, "Section edges", "Section edges", _i("Section edges"), visible=True)
                s["hint"] = f"{n:,} edge chains from the cut." if chains is not None else "Cutting the scan…"
                s["fields"] = [K.check("flat-edge-show", "Show section edges", s_["showEdges"])]
            else:
                s = K.section(num, sid, "Edge detection", "Edge detection", _i("Edge detection"), visible=bool(image_name))
                s["hint"] = f"{n:,} edge chains found." if chains is not None else "No edges detected yet."
                s["fields"] = [K.slider("flat-edge-sensitivity", "Sensitivity", s_["edgeSensitivity"], 0, 1),
                               K.check("flat-edge-show", "Show detected edges", s_["showEdges"])]
        out.append(s)
    return K.page(TITLE, WORKSPACE, out)


def widget(model, on_key=None, on_field=None, parent=None):
    return K.widget(model, on_key, on_field, parent)
