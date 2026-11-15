# SPDX-License-Identifier: AGPL-3.0-only
# Ported from ScanRuler by Stefan Hermann (CNC Kitchen),
# github.com/CNCKitchen/ScanRuler: plugins/mesh-tools/ui/MeshPanel.tsx,
# EditedCopy.tsx, ui/tools/*.tsx and the defaults of
# plugins/mesh-tools/state/meshStore.ts (DEFAULT_TRIANGLE_LIMIT) and
# core/breakSurface.ts (DEFAULT_BREAK_DEPTH).
#
# The Mesh Tools page (design 2.5) as data: Model, Tools (the 14 keys in
# MeshPanel.tsx order, three to a row), the section of the tool in hand
# with its own fields and defaults, Edited copy and In use for analysis.
# `build(st, ui)` reads "meshToolsState" (fam_meshtools); a tool's
# settings are the panel's (ui["mesh"]) over the store's defaults.

from .. import legend as L
from .. import workspaces as W
from . import kit as K
from .infotext_pages import INFO

TITLE = "Mesh Tools"
WORKSPACE = "mesh"
PAGE = "mesh"

# MeshPanel.tsx TOOLS: (id, label, title). workspaces._MESH carries the same
# rows with their commands; its "fill" is the original's "holes".
TOOLS = tuple(("holes" if i == "fill" else i, lab, tip) for i, _c, lab, tip, _ic, _t in W._MESH)
COMMAND = {("holes" if i == "fill" else i): "ScanRuler_" + c for i, c, _l, _t, _ic, _tool in W._MESH}
DEFAULT_TOOL = "reduce"  # meshStore.ts `tool: 'reduce'`
NEED_SCAN = "Open a scan first."
HINT_NO_TOOL = "Pick a tool. <b>Escape</b>, or its key again, puts the one in hand away."
HINT_COPY = ("Not in use yet — every other workspace measures the scan as it was. <b>Deviation</b> in the view bar "
             "shows how far the copy is from it.")
HINT_IN_USE = ("Edits taken into use: every workspace measures the scan as these left it. Ctrl+Z steps back through "
               "them; a saved project keeps the scan as it now is.")
COPY_TIPS = {"discard": "Throw the copy and its edits away — Ctrl+Z brings them back",
             "export": "Save the copy as STL or 3MF, alignment included",
             "use": "Make the copy the scan every workspace measures"}

# meshStore.ts initial state
DEFAULTS = {"tolerance": 0.05, "toleranceAuto": True, "maxTriangles": 50_000, "pieceSize": 2.0, "pieceSizeAuto": True,
            "cutRef": "z", "cutOffset": 0.0, "cutKeep": "plus", "cutCap": True, "mirrorRef": "x", "mirrorOffset": 0.0,
            "mirrorMode": "whole", "mirrorKeep": "plus", "holeSize": 5.0, "holeSizeAuto": True, "fillMode": "curved",
            "smoothScope": "all", "smoothSize": 2.0, "smoothSizeAuto": True, "smoothLimit": 0.2, "smoothLimitAuto": True,
            "smoothEdges": True, "densifyEdge": 1.0, "densifyEdgeAuto": True, "offsetScope": "all", "offsetDirection": "expand",
            "offsetDistance": 0.1, "shellThickness": 2.0, "shellThicknessAuto": True, "shellSide": "in", "wrapGap": 1.0,
            "wrapGapAuto": True, "wrapGrow": 0.0, "wrapEdges": "sharp", "boolOp": "subtract", "trimOffset": 0.0,
            "trimDepth": 0.3, "trimFlip": False}
PLANES = (("x", "YZ plane"), ("y", "XZ plane"), ("z", "XY plane"))  # core/section/frame.ts worldPlaneName
SCOPES = (("all", "Whole part"), ("marked", "Marked region"))
INFO_TITLE = {"reduce": "Reducing a scan for CAD", "islands": "Removing islands", "delete": "Deleting marked surface",
              "flip": "Flipping normals", "cut": "Cutting the scan", "mirror": "Mirroring the scan", "holes": "Filling holes",
              "smooth": "Smoothing the scan", "densify": "Densifying", "offset": "Shrinking or expanding the surface",
              "boolean": "A boolean with a solid", "trim": "Trimming a body to the scanned break",
              "shell": "Hollowing a part, or thickening a surface", "wrap": "Wrapping a part in one closed skin"}
HEADER = {"offset": "Shrink / expand", "shell": "Shell / hollow"}  # the tools' own sec-heads; the rest are their key labels

ORDER = (("1", "model"), ("2", "tools"), ("3", "tool"), ("4", "edited_copy"), ("—", "in_use"))


def _i(title):
    return K.info_of(INFO, PAGE, title)


def _side(axis, ref):
    a = ref.upper() if ref in ("x", "y", "z") else ""
    return (("plus", f"+{a} side"), ("minus", f"−{a} side"))


def tool_section(tool, m, ready=True, busy=False):
    """The section of one tool: header, (i), fields and keys, as its TSX has them."""
    label = dict((i, lab) for i, lab, _t in TOOLS)[tool]
    s = K.section("3", "tool", HEADER.get(tool, label), INFO_TITLE[tool], _i(INFO_TITLE[tool]), tool=tool)
    go = ready and not busy
    n, t, tg, ck, sel = K.number, K.toggle, K.key, K.check, K.select
    if tool == "reduce":
        s["fields"] = [n("tolerance", "Tolerance", m["tolerance"], auto=m["toleranceAuto"]),
                       n("triangle-limit", "Triangle limit", m["maxTriangles"], unit="", integer=True)]
        s["keys"] = [tg("reduce", "Reduce", go, primary=True)]
    elif tool == "islands":
        s["fields"] = [n("piece-size", "Smaller than", m["pieceSize"], auto=m["pieceSizeAuto"])]
        s["keys"] = [tg("remove-islands", "Remove", go, primary=True)]
    elif tool == "delete":
        s["keys"] = [tg("delete-marked", "Delete marked surface…", go, primary=True)]
    elif tool == "flip":
        s["keys"] = [tg("flip-all", "Flip all", go, primary=True), tg("flip-marked", "Flip marked", go)]
    elif tool == "cut":
        s["fields"] = [sel("cut-ref", "Cut across", PLANES, m["cutRef"], not busy),
                       n("cut-offset", m["cutRef"].upper() if m["cutRef"] in ("x", "y", "z") else "Offset", m["cutOffset"]),
                       t("cut-keep", "Keep", _side("cut", m["cutRef"]), m["cutKeep"], not busy,
                         {"plus": "Keep the side the arrow points to", "minus": "Keep the other side"}),
                       ck("cut-cap", "Close flat", m["cutCap"], info="Close flat", info_text=_i("Close flat"))]
        s["keys"] = [tg("cut", "Cut", go, primary=True)]
    elif tool == "mirror":
        f = [t("mirror-mode", "Mirror", (("whole", "Whole part"), ("symmetric", "Symmetric")), m["mirrorMode"], not busy,
               {"whole": "Mirror the whole part across the plane", "symmetric": "Keep one side and mirror it onto the other"}),
             sel("mirror-ref", "Across", PLANES, m["mirrorRef"], not busy),
             n("mirror-offset", m["mirrorRef"].upper() if m["mirrorRef"] in ("x", "y", "z") else "Offset", m["mirrorOffset"])]
        if m["mirrorMode"] == "symmetric":
            f.append(t("mirror-keep", "Keep", _side("mirror", m["mirrorRef"]), m["mirrorKeep"], not busy))
        s["fields"] = f
        s["keys"] = [tg("mirror", "Make symmetric" if m["mirrorMode"] == "symmetric" else "Mirror", go, primary=True)]
    elif tool == "holes":
        s["fields"] = [n("hole-size", "Holes up to", m["holeSize"], auto=m["holeSizeAuto"]),
                       t("fill-mode", "Patch", (("curved", "Curved"), ("flat", "Flat")), m["fillMode"], not busy,
                         {"curved": "Carry the surface’s curvature across the hole",
                          "flat": "The tightest patch across the rim — flat where the rim is"})]
        s["keys"] = [tg("fill", "Fill", go, primary=True)]
    elif tool == "smooth":
        s["fields"] = [t("smooth-scope", "Smooth", SCOPES, m["smoothScope"], not busy),
                       n("smooth-size", "Smooth bumps up to", m["smoothSize"], auto=m["smoothSizeAuto"]),
                       n("smooth-limit", "Move at most", m["smoothLimit"], auto=m["smoothLimitAuto"]),
                       ck("smooth-edges", "Keep sharp edges", m["smoothEdges"])]
        s["keys"] = [tg("smooth", "Smooth the marked region" if m["smoothScope"] == "marked" else "Smooth", go, primary=True)]
    elif tool == "densify":
        s["fields"] = [n("densify-edge", "Longest edge", m["densifyEdge"], auto=m["densifyEdgeAuto"])]
        s["keys"] = [tg("densify", "Densify", go, primary=True)]
    elif tool == "offset":
        s["fields"] = [t("offset-scope", "Move", SCOPES, m["offsetScope"], not busy),
                       t("offset-direction", "Direction", (("expand", "Expand"), ("shrink", "Shrink")), m["offsetDirection"], not busy),
                       n("offset-distance", "Distance", m["offsetDistance"])]
        s["keys"] = [tg("offset", "Expand" if m["offsetDirection"] == "expand" else "Shrink", go, primary=True)]
    elif tool == "boolean":
        s["fields"] = [t("boolean-op", "", (("subtract", "Subtract"), ("add", "Add"), ("intersect", "Intersect")), m["boolOp"], not busy,
                         {"subtract": "Subtract the solid from the mesh", "add": "Add the solid to the mesh",
                          "intersect": "Keep only where the mesh and solid overlap"})]
        s["keys"] = [tg("select-all", "Select all", not busy), tg("unselect-all", "Unselect all", not busy),
                     tg("boolean", "Perform operation", go, primary=True)]
    elif tool == "trim":
        s["fields"] = [n("trim-offset", "Offset from break", m["trimOffset"]),
                       ck("trim-flip", "Keep the other side", m["trimFlip"]),
                       n("trim-depth", "Depth", m["trimDepth"])]
        s["keys"] = [tg("trim", "Trim to the break", go, primary=True)]
    elif tool == "shell":
        s["fields"] = [n("shell-thickness", "Thickness", m["shellThickness"], auto=m["shellThicknessAuto"]),
                       t("shell-side", "", (("in", "Inward"), ("out", "Outward"), ("both", "Both sides")), m["shellSide"], not busy,
                         {"in": "Wall grows inward; the scan stays the outside", "out": "Wall grows outward; the scan becomes the inside",
                          "both": "Wall grows both ways, centred on the scan"})]
        s["keys"] = [tg("shell", "Shell", go, primary=True)]
    elif tool == "wrap":
        s["fields"] = [n("wrap-gap", "Close gaps under", m["wrapGap"], auto=m["wrapGapAuto"]),
                       n("wrap-grow", "Grow by", m["wrapGrow"]),
                       t("wrap-edges", "", (("sharp", "Sharp"), ("smooth", "Smooth")), m["wrapEdges"], not busy,
                         {"sharp": "Rebuild sharp edges and corners, for machined parts",
                          "smooth": "Leave edges slightly rounded, for organic shapes"})]
        s["keys"] = [tg("wrap", "Wrap", go, primary=True)]
    return s


# The run keys of the tools scanrulerfc/meshtools adds, and the tool each calls.
RUN_KEYS = {"densify": "mesh_densify", "boolean": "mesh_boolean", "trim": "mesh_trim", "shell": "mesh_shell", "wrap": "mesh_wrap"}


def call_for(key_id, ui=None):
    """(tool, args) a run key calls with the section's fields, or None for a
    key that opens or picks something in the panel. Fields left on auto are
    left out, so the tool picks its own start value, as the original does."""
    tool = RUN_KEYS.get(key_id)
    if tool is None:
        return None
    ui = dict(ui or {})
    m = dict(DEFAULTS)
    m.update(ui.get("mesh") or {})
    if key_id == "densify":
        args = {} if m["densifyEdgeAuto"] else {"maxEdge": m["densifyEdge"]}
    elif key_id == "boolean":
        args = {"op": m["boolOp"]}
        if ui.get("solids"):
            args["solids"] = list(ui["solids"])
    elif key_id == "trim":
        args = {"offset": m["trimOffset"], "depth": m["trimDepth"], "flip": bool(m["trimFlip"])}
        if ui.get("body") is not None:
            args["body"] = ui["body"]
    elif key_id == "shell":
        args = {"side": m["shellSide"]}
        if not m["shellThicknessAuto"]:
            args["thickness"] = m["shellThickness"]
    else:
        args = {"gap": m["wrapGap"], "grow": m["wrapGrow"], "edges": m["wrapEdges"]}
    return tool, args


def build(st, ui=None, units="mm"):
    ui = dict(ui or {})
    ms = st.get("meshToolsState") or {}
    m = dict(DEFAULTS)
    m.update(ui.get("mesh") or {})
    tool = ui.get("tool", DEFAULT_TOOL)
    scan = st.get("scan")
    busy = bool(ui.get("busy"))
    copy = ms.get("copy")
    edits = ms.get("edits") or []
    out = []
    for num, sid in ORDER:
        if sid == "model":
            s = K.section(num, sid, "Model", "The scan", _i("The scan"))
            s["slot"] = K.scan_slot(scan, busy, edited=bool(edits))
            s["hint"] = None if scan is not None else K.HINT_DROP
        elif sid == "tools":
            s = K.section(num, sid, "Tools", "Mesh tools", _i("Mesh tools"), grid=3)
            # Like 3D Measure's keys: none works without a scan, so none can
            # be pressed, and each says why (GUI pass, round 4).
            ready = scan is not None and not busy
            s["keys"] = [dict(K.key(i, lab, ready, tip if scan is not None else f"{tip}. {NEED_SCAN}", pressed=tool == i),
                              command=COMMAND[i]) for i, lab, tip in TOOLS]
            s["hint"] = NEED_SCAN if scan is None else (HINT_NO_TOOL if tool is None else None)
        elif sid == "tool":
            if tool is None:
                s = K.section(num, sid, "", visible=False)
            else:
                s = tool_section(tool, m, scan is not None, busy)
        elif sid == "edited_copy":
            s = K.section(num, sid, "Edited copy", "The edited copy", _i("The edited copy"), visible=copy is not None)
            if copy is not None:
                s["rows"] = [{"id": "triangles", "name": "Triangles",
                              "reading": f"{L.count(len(copy[1]))} · scan in use {L.count(len(scan.F) if scan is not None else 0)}"}]
                s["rows"] += [{"id": f"edit{i}", "name": e if isinstance(e, str) else e.get("text", ""), "reading": ""}
                              for i, e in enumerate(ms.get("pending") or [])]
            s["hint"] = HINT_COPY
            s["keys"] = [K.key("discard-edited", "Discard", not busy, COPY_TIPS["discard"]),
                         K.key("export-edited", "Export mesh", not busy, COPY_TIPS["export"]),
                         K.key("use-edited", "Use for analysis", not busy, COPY_TIPS["use"], primary=True)]
            s["grid"] = 3
        elif sid == "in_use":
            s = K.section(num, sid, "In use for analysis", visible=bool(edits), count=len(edits))
            s["rows"] = [{"id": f"edit{i}", "name": e if isinstance(e, str) else e.get("text", ""), "reading": ""} for i, e in enumerate(edits)]
            s["hint"] = HINT_IN_USE
        out.append(s)
    return K.page(TITLE, WORKSPACE, out)


def widget(model, on_key=None, on_field=None, parent=None):
    return K.widget(model, on_key, on_field, parent)
