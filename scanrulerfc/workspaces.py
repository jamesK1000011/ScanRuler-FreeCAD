# SPDX-License-Identifier: AGPL-3.0-only
# Ported from ScanRuler by Stefan Hermann (CNC Kitchen),
# github.com/CNCKitchen/ScanRuler: src/ui/TopBar.tsx (CORE_TABS, the project
# keys), src/ui/Panel.tsx, AlignmentSection.tsx, DimensionSection.tsx,
# ToleranceSection.tsx, DeviationPanel.tsx, VolumeSection.tsx,
# ThicknessPanel.tsx, FlatPanel.tsx, ViewBar.tsx,
# plugins/mesh-tools/plugin.ts and ui/MeshPanel.tsx (TOOLS),
# plugins/mesh-tools/app/useMeshPlugin.tsx (the Deviation key),
# plugins/reverse/plugin.ts, ui/ReversePanel.tsx (the feature keys) and
# app/useReversePlugin.tsx (the Bodies key), plugins/snapshot/ui/ShotButton.tsx.
#
# The workbench as data: the six workspaces in the original's order with its
# labels and tooltips, each workspace's toolbars with the keys in the order
# of its panel's grid, the view bar's groups, and which tool belongs to which
# workspace. Every string is copied from the TSX (tests/test_workspaces.py
# reads the TSX again and holds these to it). Pure Python: no FreeCAD, Qt or
# Agent Link import, so it loads anywhere.
#
# A key either runs a tool (`run`: True, through the runner the host sets,
# with `args`) or opens something in the panel (`run`: False: a draft box, a
# tool's section, a picker), which the page does; `tool` is the tool the key
# stands for either way, so a tool the agent runs can light its key. `icon`
# names an SVG in scanrulerfc/icons/, drawn from the original's own icon of
# that name. `tip_from` says where a tooltip came from: "title" (the key's own
# title attribute), "label" (the key has none, so its label stands), or
# "moved" (the original's words name a web-only thing; the port says the
# FreeCAD equivalent).

import re

from . import CREDIT  # noqa: F401 — the one credit line, kept in scanrulerfc/__init__.py
WORKBENCH_MENU = "ScanRuler"
WORKBENCH_TIP = "ScanRuler by Stefan Hermann (CNC Kitchen), ported to FreeCAD"
STATUS_CREDIT = "ScanRuler · CNC Kitchen"
ACCENT = "#1877c0"  # CNC Kitchen blue, the original's --accent and palette[0]

# --- workspaces --------------------------------------------------------------
# (id, command, label, tooltip, icon, original order)
WORKSPACES = (
    {"id": "elements", "command": "ScanRuler_Ws3DMeasure", "label": "3D Measure", "tip": "Fit spheres, cylinders and planes, and measure between them", "icon": "wsMeasure", "order": 1},
    {"id": "deviation", "command": "ScanRuler_WsDeviation", "label": "Surface Deviation", "tip": "Best-fit the scan to a nominal part and map the difference", "icon": "compare", "order": 2},
    {"id": "thickness", "command": "ScanRuler_WsThickness", "label": "Wall Thickness", "tip": "Map the part’s wall thickness", "icon": "wsThickness", "order": 3},
    {"id": "flat", "command": "ScanRuler_Ws2DMeasure", "label": "2D Measure", "tip": "Measure a flatbed scan the way a measuring microscope would", "icon": "wsFlat", "order": 4},
    {"id": "mesh", "command": "ScanRuler_WsMeshTools", "label": "Mesh Tools", "tip": "Clean up, edit and reduce a scan", "icon": "wsMesh", "order": 10},
    {"id": "reverse", "command": "ScanRuler_WsReverse", "label": "Reverse engineer", "tip": "Build a solid STEP body over the scan", "icon": "extract", "order": 11},
)
DEFAULT_WORKSPACE = "elements"
WORKSPACE_TOOLBAR = "ScanRuler Workspaces"
VIEW_TOOLBAR = "ScanRuler View"

# --- FreeCAD's design guide: how a string shows -------------------------------
# The tables keep the original's words (tests/test_workspaces.py holds them
# to the TSX); what FreeCAD shows follows its design guide: Title Case for
# command names, menu items and group titles, a tooltip a full sentence.
SMALL_WORDS = frozenset("a an and as at but by for from if in into nor of on onto or per the to via vs with".split())


def _cap_word(w):
    """One word capitalised, words that already carry capitals (ScanRuler,
    STEP, 2D) and numbers left as they are."""
    if not w or any(c.isupper() for c in w[1:]) or not w[0].isalpha():
        return w
    return w[0].upper() + w[1:]


def title_case(s):
    """"Align by picking points…" -> "Align by Picking Points…": every word
    capitalised but the small ones inside; the first and last always, and
    each part of "Auto-align" or "Shrink/expand"."""
    words = s.split(" ")
    idx = [i for i, w in enumerate(words) if w.strip("…./-")]
    out = []
    for i, w in enumerate(words):
        core = w.rstrip("….:")
        edge = bool(idx) and i in (idx[0], idx[-1])
        if core.lower() in SMALL_WORDS and not edge:
            out.append(w)
            continue
        out.append(re.sub(r"[^\s/\-]+", lambda m: _cap_word(m.group(0)), w))
    return " ".join(out)


def sentence(s):
    """A tooltip as a full sentence: capital first, a full stop last."""
    s = s.strip()
    if not s:
        return s
    s = s[0].upper() + s[1:]
    return s if s[-1] in ".?!" else s.rstrip("…") + "."


def _k(command, label, tip, icon, tool=None, run=False, args=None, tip_from="title", key=None):
    return {"command": command, "label": label, "tip": tip, "icon": icon, "tool": tool, "run": run,
            "args": dict(args or {}), "tip_from": tip_from, "key": key or command[len("ScanRuler_"):]}


def _lk(command, label, icon, tool=None, run=False, args=None):
    """A key whose original has no title: the label stays the original's, and
    the tooltip says what it does (TIPS), as FreeCAD's design guide asks;
    repeating the label told nothing (GUI pass on the Mac)."""
    return _k(command, label, TIPS.get(command, label), icon, tool, run, args, "label")


_FIT = "Fit {} to the part of the scan you pick."
_FLAT = "Fit {} to the edges you pick on the flat scan."


def _a(noun):
    return ("an " if noun[0] in "aeiou" else "a ") + noun
TIPS = {
    "ScanRuler_AutoAlign": "Turn the scan square to its main planes and axes automatically.",
    "ScanRuler_AlignPart": "Align the scan to datums you pick: a plane, an axis, a point.",
    "ScanRuler_MoveRotate": "Move or rotate the scan by numbers you type.",
    "ScanRuler_ScalePart": "Scale the scan to its true size from lengths you measured.",
    "ScanRuler_ElementPoint": "Place a point on the scan.",
    "ScanRuler_ElementLine": _FIT.format(_a("line")),
    "ScanRuler_ElementPlane": _FIT.format(_a("plane")),
    "ScanRuler_ElementSphere": _FIT.format(_a("sphere")),
    "ScanRuler_ElementCylinder": _FIT.format(_a("cylinder")),
    "ScanRuler_ElementCone": _FIT.format(_a("cone")),
    "ScanRuler_ElementCircle": _FIT.format(_a("circle")),
    "ScanRuler_ElementTorus": _FIT.format(_a("torus")),
    "ScanRuler_NewDimension": "Measure between elements: a distance, an angle or a diameter.",
    "ScanRuler_NewTolerance": "Check a form or position tolerance on an element, such as parallelism.",
    "ScanRuler_AlignAutomatically": "Best-fit the scan onto the nominal part automatically.",
    "ScanRuler_AlignByPoints": "Align the scan to the nominal part by picking matching points on both.",
    "ScanRuler_MarkFitSurface": "Mark the surfaces the best fit should use; the rest are left out.",
    "ScanRuler_FindVolumeErrors": "Find where the scan has material missing or added against the nominal part.",
    "ScanRuler_MeasureAgain": "Measure the wall thickness again with the settings now.",
    "ScanRuler_CopyReport": "Copy the measuring report as text.",
    "ScanRuler_FlatPoint": "Place a point on the flat scan.",
    "ScanRuler_FlatLine": _FLAT.format(_a("line")),
    "ScanRuler_FlatCircle": _FLAT.format(_a("circle")),
    "ScanRuler_FlatArc": _FLAT.format(_a("arc")),
    "ScanRuler_FlatSpline": _FLAT.format(_a("spline")),
    "ScanRuler_FlatCount": "Count the shapes of one kind on the flat scan.",
    "ScanRuler_FlatText": "Add a text note to the 2D sheet.",
    "ScanRuler_FlatNewDimension": "Measure between elements on the 2D sheet.",
}


_KINDS = (("point", "Point", "elPoint"), ("line", "Line", "elLine"), ("plane", "Plane", "elPlane"),
          ("sphere", "Sphere", "elSphere"), ("cylinder", "Cylinder", "elCylinder"), ("cone", "Cone", "elCone"),
          ("circle", "Circle", "elCircle"), ("torus", "Torus", "elTorus"))

_MESH = (  # MeshPanel.tsx TOOLS, in order: (id, command suffix, label, title, icon, tool)
    ("reduce", "MeshReduce", "Reduce mesh", "Make a light copy of the scan to model over in CAD", "reduceMesh", "mesh_reduce"),
    ("islands", "MeshRemoveIslands", "Remove islands", "Find and delete small loose bits floating off the scan", "islands", "mesh_remove_islands"),
    ("delete", "MeshDeleteMarked", "Delete marked", "Mark surface by hand and delete it from the scan", "deleteSurface", "mesh_delete_marked"),
    ("flip", "MeshFlipNormals", "Flip normals", "Turn the surface, or a marked patch, to face the other way", "flipNormals", "mesh_flip_normals"),
    ("cut", "MeshCut", "Cut", "Cut the scan with a plane and remove one side", "cutPlane", "mesh_cut"),
    ("mirror", "MeshMirror", "Mirror", "Mirror the scan across a plane, or make it symmetric", "mirror", "mesh_mirror"),
    ("fill", "MeshFillHoles", "Fill holes", "Patch holes the scanner left, up to a size you set", "fillHoles", "mesh_fill_holes"),
    ("smooth", "MeshSmooth", "Smooth", "Smooth out scanner noise, keeping sharp edges", "smoothMesh", "mesh_smooth"),
    ("densify", "MeshDensify", "Densify", "Split long triangles so a CAD export has points to fit on", "densify", "mesh_densify"),
    ("offset", "MeshOffset", "Shrink/expand", "Grow or shrink the surface by a distance (not a scale)", "offsetSurface", "mesh_offset"),
    ("boolean", "MeshBoolean", "Boolean", "Subtract, add or intersect a solid body with the scan", "combine", "mesh_boolean"),
    ("trim", "MeshTrim", "Trim to scan", "Cut a repair piece to fit the scanned break", "trimToScan", "mesh_trim"),
    ("shell", "MeshShell", "Shell/hollow", "Hollow a closed part, or thicken an open surface", "shellSolid", "mesh_shell"),
    ("wrap", "MeshWrap", "Wrap", "Wrap the part in one closed, printable skin", "wrapSkin", "mesh_wrap"),
)

_REVERSE = (  # ReversePanel.tsx feature keys, in order: (id, label, title, icon)
    ("extrude", "Extrude", "Extrude a sketch's regions — pick them in the viewport", "extrude"),
    ("revolve", "Revolve", "Revolve a sketch's regions about an axis", "revolve"),
    ("extract", "Extract", "Turn a measured shape or shadow section into a body", "extract"),
    ("import", "Import STEP", "Bring in a STEP file as bodies", "importStep"),
    ("shell", "Shell", "Hollow the body; click faces to leave open", "shell"),
    ("fillet", "Fillet", "Round edges; the radius is read off the scan", "fillet"),
    ("chamfer", "Chamfer", "Chamfer edges of the body — click them", "chamfer"),
    ("draft", "Draft", "Add draft: tilt faces about a neutral plane", "draft"),
    ("moveFace", "Move face", "Push or pull faces by a distance, or snap one to the scan", "moveFace"),
    ("deleteFace", "Delete face", "Remove a round, chamfer, hole or boss and heal the gap", "deleteFace"),
    ("hole", "Hole", "Drill a hole along a cylinder, circle or round face", "hole"),
    ("thread", "Thread", "Model a screw thread on a round face", "thread"),
    ("cutPlane", "Cut by plane", "Cut the body at a plane and keep one side", "cutPlane"),
    ("mirror", "Mirror", "Mirror the body about a plane, joined with the source", "mirror"),
    ("boolean", "Combine", "Join, cut or intersect bodies, or trim and sew sheets", "combine"),
    ("sheet", "Sheet", "Extrude a sketch as a surface, to split a body with", "sheet"),
    ("split", "Split", "Split a body or sheet, keeping the pieces on the scan", "split"),
    ("loft", "Loft", "Blend a solid through two or more sketches", "loft"),
    ("sweep", "Sweep", "Sweep a profile along a path from another sketch", "sweep"),
    ("pattern", "Pattern", "Copy the body round an axis, in a line or a grid", "pattern"),
    ("moveBody", "Move body", "Move or turn bodies, or copies of them", "moveBody"),
    ("offsetBody", "Offset body", "Grow or shrink a body all round, as a new body", "offsetBody"),
    ("surface", "Fit surface", "Fit a smooth freeform surface to part of the scan", "surface"),
    ("network", "Patch network", "Draw curves on the scan and fill them with fitted patches", "surface"),
    ("trim", "Trim", "Close fitted surfaces and shapes into a solid", "trim"),
    ("thicken", "Thicken", "Give a sheet or surface a wall thickness", "shell"),
)

# The keys whose engine step is still to come: Import STEP
# (reverse_import_step) and the kinds reverse/build.py LATER names.
REVERSE_LATER = ("import", "sheet", "split", "loft", "sweep", "surface", "network", "trim", "thicken")


def _cap(s):
    return s[0].upper() + s[1:]


# --- per-workspace toolbars: (toolbar title, [keys]) in the panel's order ----
TOOLBARS = {
    "elements": (
        ("Alignment", [
            _lk("ScanRuler_AutoAlign", "Auto-align", "alignSheet", "align_auto", True),
            _lk("ScanRuler_AlignPart", "Align part", "pickPoints", "align_datum"),
            _lk("ScanRuler_MoveRotate", "Move / rotate by numbers", "rotateCcw"),
            _lk("ScanRuler_ScalePart", "Scale part", "dimLength", "scan_scale"),
        ]),
        ("Create element", [_lk("ScanRuler_Element" + _cap(k), lab, ic, "element_fit", args={"kind": k}) for k, lab, ic in _KINDS]
            + [_k("ScanRuler_Section", "Section", "Cut the scan with a plane to measure in 2D", "section", "section_cut")]),
        ("Dimensions", [
            _lk("ScanRuler_NewDimension", "New dimension", "dimDistance", "dimension_add"),
            _lk("ScanRuler_NewTolerance", "New tolerance", "parallel", "dimension_add"),
        ]),
    ),
    "deviation": (
        ("Best fit", [
            _lk("ScanRuler_AlignAutomatically", "Align automatically", "compare", "deviation_align", True),
            _lk("ScanRuler_AlignByPoints", "Align by picking points…", "pickPoints", "deviation_align"),
            _lk("ScanRuler_MarkFitSurface", "Mark surface to fit on…", "markBrush", "deviation_align"),
            _lk("ScanRuler_FindVolumeErrors", "Find volume errors", "weight", "deviation_volume", True),
        ]),
    ),
    "thickness": (
        ("Measurement", [
            _lk("ScanRuler_MeasureAgain", "Measure again", "wsThickness", "thickness_measure", True),
            _lk("ScanRuler_CopyReport", "Copy report", "share", "report_get"),
        ]),
    ),
    "flat": (
        ("Create element", [_lk("ScanRuler_Flat" + _cap(k), lab, ic, "flat_fit", args={"kind": k})
                            for k, lab, ic in (("point", "Point", "elPoint"), ("line", "Line", "line"), ("circle", "Circle", "circle"),
                                               ("arc", "Arc", "arc"), ("spline", "Spline", "spline"))]
            + [_lk("ScanRuler_FlatCount", "Count", "count", "flat_fit"), _lk("ScanRuler_FlatText", "Text", "note", "flat_note_add")]),
        ("Dimensions", [_lk("ScanRuler_FlatNewDimension", "New dimension", "dimDistance", "flat_dimension_add")]),
    ),
    "mesh": (
        ("Tools", [_k("ScanRuler_" + c, lab, tip, ic, tool, key="mesh:" + i) for i, c, lab, tip, ic, tool in _MESH]),
    ),
    # Reverse engineer: ScanRuler's own feature engine, ported
    # (scanrulerfc/reverse/). A key stands for reverse_feature_add when this
    # port builds its kind; the rest stand inactive (tool None) until their
    # build step lands (REVERSE_LATER).
    "reverse": (
        ("Create feature", [_k("ScanRuler_Re" + _cap(i), lab, tip, ic, None if i in REVERSE_LATER else "reverse_feature_add", key="reverse:" + i)
                            for i, lab, tip, ic in _REVERSE]),
    ),
}


def toolbar_name(ws, title):
    """The QToolBar's object name and title, in Title Case: unique across
    workspaces ("Create Element" is in both Measure workspaces)."""
    return f"ScanRuler {title_case(workspace(ws)['label'])}: {title_case(title)}"


# --- the project keys (TopBar.tsx's), in the ScanRuler menu ----------------
# The original's top bar also has undo and redo; FreeCAD's own Edit menu and
# toolbar carry those, and its File toolbar New, Open and Save, so these stay
# off the toolbars and say they act on the ScanRuler project.
PROJECT = (
    _k("ScanRuler_New", "New project", "Start a new ScanRuler project in a new FreeCAD document (asks if there are unsaved changes)",
       "newProject", tip_from="moved"),
    # The original: "Save everything as one .scanruler file". The FreeCAD
    # document is the project here.
    _k("ScanRuler_Save", "Save project", "Save the ScanRuler project: its scan, elements and results go in the FreeCAD document (.FCStd)",
       "save", tip_from="moved"),
    _k("ScanRuler_Load", "Open project…", "Open a ScanRuler project (.scanruler) or a FreeCAD document (.FCStd) holding one",
       "load", tip_from="moved"),
)
OPEN_SCAN = _k("ScanRuler_OpenScan", "Open scan…", "Open a scan (STL, PLY, OBJ, OFF or 3MF) to measure", "load",
               "scan_open", tip_from="moved")
SETTINGS = _k("ScanRuler_Settings", "Settings…", "Open ScanRuler's settings; theme and mouse controls are FreeCAD's own preferences",
              "settings", tip_from="moved")
# The original's camera key: "Screenshot this tab (⌥⇧S / Alt+Shift+S)".
SNAPSHOT = _k("ScanRuler_Snapshot", "Snapshot", "Screenshot the 3D view", "camera", "scan_snapshot_latest", tip_from="moved")
ABOUT = _k("ScanRuler_About", "About ScanRuler", "Show ScanRuler's version, licence and credits", "wsMeasure", tip_from="moved")
LOAD_SUFFIXES = (".FCStd", ".scanruler")

# --- the view bar (ViewBar.tsx and the plugins' keys), in bar order ----------
# `ws`: the workspaces it shows in (None: all). `menu`: the ▴ menu's switches.
ALL = None
VIEW_BAR = (
    {"group": "Scan", **_k("ScanRuler_ViewScan", "Scan", "Show or hide the scan (display options in the menu)", "scan"), "ws": ALL, "menu": [
        _k("ScanRuler_ViewScanTransparent", "Transparent", "Make the scan see-through", "transparent"),
        _k("ScanRuler_ViewScanMesh", "Mesh", "Show the scan’s triangle edges", "mesh"),
        _k("ScanRuler_ViewScanBackfaces", "Backfaces", "Colour back faces, to spot holes and flipped normals", "backfaces"),
        _k("ScanRuler_ViewScanColours", "Colours", "Show the scan’s captured colours, or plain", "scanColours"),
    ]},
    {"group": "Reference", **_k("ScanRuler_ViewReference", "Reference", "Show or hide the reference", "model"), "ws": ("deviation",), "menu": [
        _k("ScanRuler_ViewRefTransparent", "Transparent", "Draw the reference transparent while it is solid", "transparent"),
        _k("ScanRuler_ViewRefMesh", "Mesh", "Show the reference’s triangle edges", "mesh"),
        _k("ScanRuler_ViewRefBackfaces", "Backfaces", "Colour the reference’s back faces", "backfaces"),
    ]},
    {"group": "Elements", **_k("ScanRuler_ViewElements", "Elements", "Show or hide all elements, dimensions and sections", "elCylinder"), "ws": ("elements",), "menu": [
        _k("ScanRuler_ViewLabels", "Labels", "Show name tags and readouts on the part", "labels"),
    ]},
    {"group": "Bodies", **_k("ScanRuler_ViewBodies", "Bodies", "Show or hide all bodies", "combine"), "ws": ("reverse",), "menu": [
        _k("ScanRuler_ViewBodiesTransparent", "Transparent", "See-through bodies", "transparent"),
        _k("ScanRuler_ViewOverlaps", "Overlaps", "Hatch where bodies overlap in red", "opIntersect"),
        _k("ScanRuler_ViewTangentEdges", "Tangent edges", "How edges between rounds and flats are drawn", "tangentEdges"),
    ]},
    {"group": "Split view", **_k("ScanRuler_ViewSplit", "Split view", "Scan and reference side by side, moving together", "splitView"), "ws": ("deviation",), "menu": []},
    {"group": "Colour plot", **_k("ScanRuler_ViewColourPlot", "Colour plot", "Colour the scan by deviation (results are kept when off)", "colourPlot"), "ws": ("deviation",), "menu": []},
    {"group": "On reference", **_k("ScanRuler_ViewOnReference", "On reference", "Show the map on the reference instead", "colourPlot"), "ws": ("deviation",), "menu": []},
    {"group": "Deviation", **_k("ScanRuler_ViewCopyDeviation", "Deviation", "Colour the edited copy by how far it moved from the scan", "compare"), "ws": ("mesh",), "menu": []},
    # The original's own cut view; FreeCAD's clipping plane, laid where
    # ScanRuler lays it (design 2.8).
    {"group": "Section", **_k("ScanRuler_ViewSection", "Section", "Cut the parts open at a plane to look inside", "sectionView"), "ws": ALL, "menu": [], "native": "Std_ToggleClipPlane"},
)
VIEW_TAIL = ("Std_ViewFitAll", "ScanRuler_Snapshot")

# --- which workspace a tool belongs to (design 7.1 AREAS), by prefix ---------
AREAS = {
    "scan_": "Scan",
    "element_": "3D Measure", "dimension_": "3D Measure", "align_": "3D Measure", "section_": "3D Measure",
    "deviation_": "Surface Deviation",
    "thickness_": "Wall Thickness",
    "flat_": "2D Measure",
    "mesh_": "Mesh Tools",
    "reverse_": "Reverse engineer",
    "scan_snapshot_": "Snapshot",
}
# "Scan" and "Snapshot" are not tabs (the view bar's first group and every page's Model
# slot): a scan_ tool leaves the workspace where it is.
_BY_LABEL = {w["label"]: w["id"] for w in WORKSPACES}


def workspace(wid):
    for w in WORKSPACES:
        if w["id"] == wid:
            return w
    raise KeyError(wid)


def area_of(tool):
    """The AREAS label of a tool name, or None."""
    best = None
    for pre, area in AREAS.items():
        if tool.startswith(pre) and (best is None or len(pre) > len(best[0])):
            best = (pre, area)
    return best[1] if best else None


def workspace_for_tool(tool, current=DEFAULT_WORKSPACE):
    """The workspace id the panel turns to after `tool` ran: its area's, or
    the current one for the Scan area and tools of no area."""
    return _BY_LABEL.get(area_of(tool) or "", current)


def keys(ws=None):
    """Every toolbar key, in order: of one workspace, or of all."""
    out = []
    for wid, bars in TOOLBARS.items():
        if ws is None or wid == ws:
            for _title, ks in bars:
                out.extend(ks)
    return out


def view_keys():
    out = []
    for g in VIEW_BAR:
        out.append(g)
        out.extend(g["menu"])
    return out


def all_commands():
    """Every ScanRuler_* command the workbench registers, by name, each once."""
    out = {}
    for w in WORKSPACES:
        out[w["command"]] = {"command": w["command"], "label": w["label"], "tip": w["tip"], "icon": w["icon"], "workspace": w["id"]}
    for k in keys() + view_keys() + list(PROJECT) + [OPEN_SCAN, SETTINGS, SNAPSHOT, ABOUT]:
        out.setdefault(k["command"], k)
    return out


def icon_names():
    return sorted({c["icon"] for c in all_commands().values()})


def command_for(tool, args=None):
    """The key a tool run lights (design 7.1 COMMANDS): a running key first,
    then any key standing for the tool; element_fit by its kind,
    reverse_feature_add by its feature's kind."""
    args = args or {}
    if tool == "reverse_feature_add":
        from .reverse.handlers import command_for as reverse_command

        return reverse_command(tool, args)
    best = None
    for k in keys():
        if k["tool"] != tool:
            continue
        if k["args"] and any(args.get(a) != v for a, v in k["args"].items()):
            continue
        if k["run"]:
            return k["command"]
        best = best or k["command"]
    return best
