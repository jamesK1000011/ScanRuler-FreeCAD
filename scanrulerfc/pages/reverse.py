# SPDX-License-Identifier: AGPL-3.0-only
# Ported from ScanRuler by Stefan Hermann (CNC Kitchen),
# github.com/CNCKitchen/ScanRuler: plugins/reverse/ui/ReversePanel.tsx,
# ParameterList.tsx, BodyList.tsx and NoteList.tsx.
#
# The Reverse engineer page (design 2.6), a stub until the original's
# feature engine is ported (design: scanruler-fc-reverse-engine): the
# original's section headers in order and the 26-key Create feature grid,
# four to a row, every key inactive and saying it is coming with the engine
# port. The keys' labels and titles are workspaces._REVERSE, which the
# workspace tests hold against the TSX.

from .. import workspaces as W
from . import kit as K
from .infotext_pages import INFO

TITLE = "Reverse engineer"
WORKSPACE = "reverse"
PAGE = "reverse"
PENDING = "coming with the engine port"
KERNEL_LINE = "FreeCAD {freecad} · OCCT {occt}"

ORDER = (("1", "model", "Model", "Reverse engineering"), ("2", "parameters", "Parameters", None),
         ("3", "create_feature", "Create feature", "Features"), ("4", "features", "Features", "The feature list"),
         ("5", "bodies", "Bodies", None), ("6", "notes", "Notes for the agent", None))


def kernel_line():
    """design 2.6: the original's "CAD kernel ready" line, as FreeCAD's own."""
    try:
        import FreeCAD
        import Part

        v = FreeCAD.Version()
        return KERNEL_LINE.format(freecad=".".join(v[:3]), occt=Part.OCC_VERSION)
    except Exception:
        return None


def build(st, ui=None, units="mm"):
    scan = st.get("scan")
    out = []
    for num, sid, header, info in ORDER:
        s = K.section(num, sid, header, info, K.info_of(INFO, PAGE, info))
        s["hint"] = PENDING
        if sid == "model":
            s["slot"] = K.scan_slot(scan)
            s["detail"] = kernel_line()
        elif sid == "parameters":
            s["header_fold"] = "▸"
            s["keys"] = [K.key("parameter-add", "+ Add", False, PENDING)]
        elif sid == "create_feature":
            s["fields"] = [K.select("sketch-plane-select", "Sketch on", [("", "Choose a plane…")], "", False)]
            s["keys"] = [dict(K.key(i, lab, False, f"{tip} — {PENDING}"), command="ScanRuler_Re" + i[0].upper() + i[1:])
                         for i, lab, tip, _ic in W._REVERSE]
            s["grid"] = 4
        elif sid == "features":
            s["keys"] = [K.key("play", "▷ Play", False, PENDING)]
        out.append(s)
    return K.page(TITLE, WORKSPACE, out)


def widget(model, on_key=None, on_field=None, parent=None):
    return K.widget(model, on_key, on_field, parent)
