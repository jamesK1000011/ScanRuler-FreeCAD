# SPDX-License-Identifier: AGPL-3.0-only
# Copies the (i) texts of the Surface Deviation, Wall Thickness, 2D Measure,
# Mesh Tools and Reverse engineer pages out of ScanRuler's TSX (ScanRuler by
# Stefan Hermann, CNC Kitchen, github.com/CNCKitchen/ScanRuler) into
# scanrulerfc/pages/infotext_pages.py, word for word, <b>/<i> kept for Qt's
# rich text, read in millimetres (tests/tsxresolve.py). The page tests read
# the TSX again and compare.
#   python3 tools/gen_infotext_pages.py [SCANRULER_SRC]
import os
import pprint
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tests"))
if len(sys.argv) > 1:
    os.environ["SCANRULER_SRC"] = sys.argv[1]
import tsxresolve as R  # noqa: E402

MT = "plugins/mesh-tools/ui/"
SOURCES = {
    "deviation": (
        ("src/ui/DeviationPanel.tsx", "What the deviation is measured from"),
        ("src/ui/DeviationPanel.tsx", "Best fit"),
        ("src/ui/DeviationPanel.tsx", "Local fine fit"),
        ("src/ui/VolumeSection.tsx", "Volume error"),
        ("src/ui/DeviationPanel.tsx", "Colour scale"),
        ("src/ui/DeviationPanel.tsx", "Animated deformation"),
        ("src/ui/DeviationPanel.tsx", "Surface must face the element"),
        ("src/ui/DeviationPanel.tsx", "Reference must face the same way"),
        ("src/ui/ProbeList.tsx", "Hide pins behind the part"),
    ),
    "thickness": (
        ("src/ui/ThicknessPanel.tsx", "The scan"),
        ("src/ui/ThicknessPanel.tsx", "How thickness is measured"),
        ("src/ui/ThicknessPanel.tsx", "Rays"),
        ("src/ui/ThicknessPanel.tsx", "Far surface must face back"),
        ("src/ui/ThicknessPanel.tsx", "Colour scale"),
        ("src/ui/ProbeList.tsx", "Hide pins behind the part"),
    ),
    "flat": (
        ("src/ui/FlatPanel.tsx", "What is measured"),
        ("src/ui/FlatPanel.tsx", "Calibration"),
        ("src/ui/FlatPanel.tsx", "Elements"),
        ("src/ui/FlatDimensionSection.tsx", "Dimensions"),
        ("src/ui/FlatPanel.tsx", "Alignment"),
        ("src/ui/FlatPanel.tsx", "Section edges"),
        ("src/ui/FlatPanel.tsx", "Edge detection"),
    ),
    "mesh": (
        (MT + "MeshPanel.tsx", "The scan"),
        (MT + "MeshPanel.tsx", "Mesh tools"),
        (MT + "tools/ReduceTool.tsx", "Reducing a scan for CAD"),
        (MT + "tools/IslandsTool.tsx", "Removing islands"),
        (MT + "tools/DeleteTool.tsx", "Deleting marked surface"),
        (MT + "tools/FlipTool.tsx", "Flipping normals"),
        (MT + "tools/CutTool.tsx", "Cutting the scan"),
        (MT + "tools/CutTool.tsx", "Close flat"),
        (MT + "tools/MirrorTool.tsx", "Mirroring the scan"),
        (MT + "tools/HolesTool.tsx", "Filling holes"),
        (MT + "tools/SmoothTool.tsx", "Smoothing the scan"),
        (MT + "tools/DensifyTool.tsx", "Densifying"),
        (MT + "tools/OffsetTool.tsx", "Shrinking or expanding the surface"),
        (MT + "tools/BooleanTool.tsx", "A boolean with a solid"),
        (MT + "tools/TrimTool.tsx", "Trimming a body to the scanned break"),
        (MT + "tools/ShellTool.tsx", "Hollowing a part, or thickening a surface"),
        (MT + "tools/WrapTool.tsx", "Wrapping a part in one closed skin"),
        (MT + "EditedCopy.tsx", "The edited copy"),
    ),
    "reverse": (
        ("plugins/reverse/ui/ReversePanel.tsx", "Reverse engineering"),
        ("plugins/reverse/ui/ReversePanel.tsx", "Features"),
        ("plugins/reverse/ui/ReversePanel.tsx", "The feature list"),
    ),
}
# The Deviation page's Models header: its title is an expression.
BRANCHES = {"deviation": (("src/ui/DeviationPanel.tsx", "onElement ? 'The scan' : 'Scan and reference'", 1, "Scan and reference"),)}


def collect():
    out = {}
    for page, rows in SOURCES.items():
        d = out.setdefault(page, {})
        for rel, title in rows:
            d[title] = {"source": rel, "paragraphs": R.infodot(rel, title)}
        for rel, expr, which, title in BRANCHES.get(page, ()):
            d[title] = {"source": rel, "paragraphs": R.infodot_branch(rel, expr, which)}
    return out


def main():
    out = collect()
    body = pprint.pformat(out, width=110, sort_dicts=False)
    with open(os.path.join(HERE, "scanrulerfc", "pages", "infotext_pages.py"), "w", encoding="utf-8") as f:
        f.write("# SPDX-License-Identifier: AGPL-3.0-only\n"
                "# The (i) texts of ScanRuler's Surface Deviation, Wall Thickness, 2D Measure, Mesh\n"
                "# Tools and Reverse engineer panels, word for word, read in millimetres, from\n"
                "# ScanRuler by Stefan Hermann (CNC Kitchen), github.com/CNCKitchen/ScanRuler (the\n"
                "# TSX named in each entry). Written by tools/gen_infotext_pages.py; do not edit by hand.\n\n"
                f"INFO = {body}\n")
    print(sum(len(v) for v in out.values()), "texts")


if __name__ == "__main__":
    main()
