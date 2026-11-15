# SPDX-License-Identifier: AGPL-3.0-only
# Draws the workbench's icons from ScanRuler's own key pictures (ScanRuler by
# Stefan Hermann, CNC Kitchen, github.com/CNCKitchen/ScanRuler): the AGPL
# icon tables src/ui/icons.tsx, plugins/mesh-tools/ui/meshIcons.tsx and
# plugins/reverse/ui/reIcons.tsx, and the single pictures ThreadIcon.tsx,
# SweepFields.tsx (SweepIcon) and plugins/snapshot/ui/ShotButton.tsx (the
# camera). Never from docs/brand/: the ScanRuler and CNC Kitchen marks are
# trademarks and wait for Stefan's OK.
#
# Each picture keeps its 24-unit grid and 1.5-unit stroke, scaled onto the
# 64-pixel canvas FreeCAD icons use (icons-src conventions: 64x64 viewBox, a
# <title>, no text or images). The original's stylesheet classes become
# attributes, in the stylesheet's order: ink for what is there, CNC Kitchen
# blue #1877c0 for what the key does, dashed for what goes, dots for the scan.
#
#   python3 tools/gen_icons.py [SCANRULER_SRC]   writes scanrulerfc/icons/*.svg
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from scanrulerfc import workspaces as W  # noqa: E402

SRC = os.environ.get("SCANRULER_SRC") or os.path.join(os.path.dirname(HERE), "scanruler")
OUT = os.path.join(HERE, "scanrulerfc", "icons")

INK = "#6b7280"          # the original's --ink (#26282a) is for a light page; a mid grey holds on light and dark toolbars
ACCENT = "#1877c0"       # --accent, CNC Kitchen blue
ACCENT_SOFT = "#d9e8f5"  # --accent-soft
PALETTE = {INK, ACCENT, ACCENT_SOFT}

TABLES = ("src/ui/icons.tsx", "plugins/mesh-tools/ui/meshIcons.tsx", "plugins/reverse/ui/reIcons.tsx")
SINGLES = {
    "thread": ("plugins/reverse/ui/ThreadIcon.tsx", r"export function ThreadIcon"),
    "sweep": ("plugins/reverse/ui/SweepFields.tsx", r"export function SweepIcon"),
    "camera": ("plugins/snapshot/ui/ShotButton.tsx", r"function CameraIcon"),
}

# styles.css, svg.icon and its classes, in the stylesheet's order.
BASE = {"fill": "none", "stroke": INK, "stroke-width": "1.5", "stroke-linecap": "round", "stroke-linejoin": "round"}
CLASSES = (
    ("i-a", {"stroke": ACCENT}),
    ("i-f", {"stroke": ACCENT, "fill": ACCENT_SOFT}),
    ("i-g", {"fill": INK, "fill-opacity": ".13"}),
    ("i-gf", {"stroke": "none", "fill": INK, "fill-opacity": ".13"}),
    ("i-dt", {"stroke": "none", "fill": INK}),
    ("i-adt", {"stroke": "none", "fill": ACCENT}),
    ("i-th", {"stroke-width": "1.1"}),
    ("i-ft", {"opacity": ".5"}),
    ("i-ds", {"stroke-dasharray": "2 2.4"}),
    ("i-ax", {"stroke-dasharray": "3.2 1.6 0.6 1.6", "stroke-width": "1.1"}),
    ("i-as", {"stroke": ACCENT, "opacity": ".3"}),
)
SHAPES = {"path", "circle", "ellipse", "rect", "line", "polyline", "polygon", "g"}


def body_of(name):
    for rel in TABLES:
        with open(os.path.join(SRC, rel), encoding="utf-8") as f:
            src = f.read()
        m = re.search(r"\n  %s: \(\s*(.*?)\n  \),?\n" % re.escape(name), src, re.S)
        if m:
            return rel, m.group(1)
    if name in SINGLES:
        rel, start = SINGLES[name]
        with open(os.path.join(SRC, rel), encoding="utf-8") as f:
            src = f.read()
        i = re.search(start, src).start()
        m = re.search(r"<(svg|IconFrame)\b[^>]*>(.*?)</\1>", src[i:], re.S)
        return rel, m.group(2)
    raise KeyError(f"no icon {name!r} in ScanRuler's icon tables")


def kebab(a):
    return {"className": "class", "strokeWidth": "stroke-width", "strokeLinejoin": "stroke-linejoin",
            "strokeLinecap": "stroke-linecap", "strokeDasharray": "stroke-dasharray", "fillOpacity": "fill-opacity",
            "fillRule": "fill-rule", "clipRule": "clip-rule"}.get(a, a)


def convert(jsx):
    out = []
    for close, tag, attrs, selfclose in re.findall(r"<(/?)(\w*)((?:\s+[\w-]+=(?:\"[^\"]*\"|\{[^}]*\}))*)\s*(/?)>", jsx):
        if not tag:
            continue  # <> </>
        if tag not in SHAPES:
            raise ValueError(f"unexpected <{tag}>")
        if close:
            out.append(f"</{tag}>")
            continue
        at = {}
        for k, v in re.findall(r"([\w-]+)=(\"[^\"]*\"|\{[^}]*\})", attrs):
            if v.startswith("{"):
                v = v.strip("{}").strip("'\"")
            else:
                v = v[1:-1]
            at[kebab(k)] = v
        style = {}
        for cls, props in CLASSES:
            if cls in at.get("class", "").split():
                style.update(props)
        at.pop("class", None)
        for k, v in list(at.items()):
            if v == "currentColor":
                at[k] = INK
        merged = {**style, **{k: v for k, v in at.items() if k in BASE or k in ("opacity", "fill-opacity", "stroke-dasharray")}}
        geo = {k: v for k, v in at.items() if k not in merged}
        a = " ".join(f'{k}="{v}"' for k, v in list(geo.items()) + list(merged.items()))
        out.append(f"<{tag} {a}{' /' if selfclose else ''}>")
    return "\n".join(out)


def svg(name):
    rel, jsx = body_of(name)
    base = " ".join(f'{k}="{v}"' for k, v in BASE.items())
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f"<!-- SPDX-License-Identifier: AGPL-3.0-only. Drawn from ScanRuler's '{name}' key ({rel}),\n"
            "     ScanRuler by Stefan Hermann (CNC Kitchen), github.com/CNCKitchen/ScanRuler. -->\n"
            '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">\n'
            f"<title>{name}</title>\n"
            f'<g transform="scale(2.6666667)" {base}>\n{convert(jsx)}\n</g>\n</svg>\n')


def workbench_icon():
    """The workbench's own icon: ScanRuler's 3D Measure picture on a plain
    rounded tile in CNC Kitchen blue. Not the ScanRuler or CNC Kitchen mark."""
    _rel, jsx = body_of("wsMeasure")
    inner = convert(jsx).replace(INK, "#ffffff").replace(ACCENT_SOFT, ACCENT).replace(ACCENT, "#ffffff")
    base = " ".join(f'{k}="{v}"' for k, v in {**BASE, "stroke": "#ffffff"}.items())
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            "<!-- SPDX-License-Identifier: AGPL-3.0-only. The ScanRuler for FreeCAD workbench: ScanRuler's\n"
            "     3D Measure key (src/ui/icons.tsx) on CNC Kitchen blue, credit to Stefan Hermann (CNC Kitchen). -->\n"
            '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">\n'
            "<title>ScanRulerWorkbench</title>\n"
            f'<rect x="3" y="3" width="58" height="58" rx="10" fill="{ACCENT}" stroke="{ACCENT}" stroke-width="2" />\n'
            f'<g transform="translate(8 8) scale(2)" {base}>\n{inner}\n</g>\n</svg>\n')


def main():
    global SRC
    if len(sys.argv) > 1:
        SRC = sys.argv[1]
    os.makedirs(OUT, exist_ok=True)
    names = W.icon_names()
    for n in names:
        with open(os.path.join(OUT, n + ".svg"), "w", encoding="utf-8") as f:
            f.write(svg(n))
    with open(os.path.join(OUT, "ScanRulerWorkbench.svg"), "w", encoding="utf-8") as f:
        f.write(workbench_icon())
    print(len(names) + 1, "icons ->", OUT)


if __name__ == "__main__":
    main()
