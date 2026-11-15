# SPDX-License-Identifier: AGPL-3.0-only
# Copies the (i) texts of the 3D Measure page's headers out of ScanRuler's TSX
# (ScanRuler by Stefan Hermann, CNC Kitchen, github.com/CNCKitchen/ScanRuler)
# into scanrulerfc/pages/infotext.py, word for word, <b>/<i> kept for Qt's
# rich text. tests/test_measure3d_page.py reads the TSX again and compares.
#   python3 tools/gen_infotext.py [SCANRULER_SRC]
import os
import pprint
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tests"))
if len(sys.argv) > 1:
    os.environ["SCANRULER_SRC"] = sys.argv[1]
import tsxsource as T  # noqa: E402

SOURCES = (
    ("src/ui/Panel.tsx", "The scan"),
    ("src/ui/AlignmentSection.tsx", "Alignment"),
    ("src/ui/Panel.tsx", "Elements"),
    ("src/ui/DraftEditor.tsx", "Which surface is fitted"),
    ("src/ui/DraftEditor.tsx", "Used points"),
    ("src/ui/SectionEditor.tsx", "Sections"),
    ("src/ui/DimensionSection.tsx", "Dimensions"),
    ("src/ui/ToleranceSection.tsx", "Geometric tolerances"),
    ("plugins/scanner-profiles/ui/ScannerSection.tsx", "Scanner noise"),
    ("plugins/thread-match/ui/ThreadSection.tsx", "Naming a scanned thread"),
    ("src/ui/Panel.tsx", "What the STEP file contains"),
    ("src/ui/Panel.tsx", "What the point cloud contains"),
)


def main():
    out = {}
    for rel, title in SOURCES:
        out[title] = {"source": rel, "paragraphs": T.infodot(rel, title)}
    body = pprint.pformat(out, width=110, sort_dicts=False)
    with open(os.path.join(HERE, "scanrulerfc", "pages", "infotext.py"), "w", encoding="utf-8") as f:
        f.write("# SPDX-License-Identifier: AGPL-3.0-only\n"
                "# The (i) texts of ScanRuler's 3D Measure panel, word for word, from ScanRuler by\n"
                "# Stefan Hermann (CNC Kitchen), github.com/CNCKitchen/ScanRuler (the TSX named in\n"
                "# each entry). Written by tools/gen_infotext.py; do not edit by hand.\n\n"
                f"INFO = {body}\n")
    print(len(out), "texts")


if __name__ == "__main__":
    main()
