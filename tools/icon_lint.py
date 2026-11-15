# SPDX-License-Identifier: AGPL-3.0-only
# icons-src/lint.py's rules for this add-on's icons, with ScanRuler's palette
# in place of Tango (the icons are ScanRuler's pictures in CNC Kitchen blue)
# and its 1.5-unit stroke on the 24-unit grid in place of a 2 px one.
#   python3 tools/icon_lint.py scanrulerfc/icons
import glob
import re
import sys
import xml.etree.ElementTree as ET

ALLOWED = {"6b7280", "1877c0", "d9e8f5", "ffffff"}
bad = 0
for f in sorted(sum((glob.glob(d + "/*.svg") for d in sys.argv[1:]), [])):
    s = open(f, encoding="utf-8").read()
    errs = []
    try:
        r = ET.fromstring(s.split("?>", 1)[-1])
    except ET.ParseError as e:
        errs.append(f"xml {e}")
        r = None
    if r is not None and r.get("viewBox") != "0 0 64 64":
        errs.append("viewBox")
    hexes = {h.lower() for h in re.findall(r"#([0-9a-fA-F]{6})\b", s)}
    if hexes - ALLOWED:
        errs.append(f"off-palette {hexes - ALLOWED}")
    if re.search(r"<text|<image|xlink:href|data:", s):
        errs.append("text/image")
    if not re.search(r'stroke-width="(1\.5|2)"', s):
        errs.append("no base stroke")
    if "<title>" not in s:
        errs.append("no title")
    if errs:
        print("FAIL " + f.split("/")[-1], *errs)
    bad += bool(errs)
print(f"{bad} failing")
sys.exit(bad)
