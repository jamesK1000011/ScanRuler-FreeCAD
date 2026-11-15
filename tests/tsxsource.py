# SPDX-License-Identifier: AGPL-3.0-only
# Reads strings out of ScanRuler's TSX (ScanRuler by Stefan Hermann, CNC
# Kitchen, github.com/CNCKitchen/ScanRuler), so the tests can hold the port's
# copied strings against the original's. Read only; plain regular expressions.
import html
import os
import re

# The original's checkout: SCANRULER_SRC, or a "scanruler" folder beside this repository.
ROOT = os.environ.get("SCANRULER_SRC") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scanruler")


def available():
    return os.path.isdir(os.path.join(ROOT, "src", "ui"))


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def norm(s):
    s = s.replace("{' '}", " ")
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def infodot(rel, title):
    """The paragraphs of the InfoDot with this title, <b>/<i> kept."""
    src = read(rel)
    m = re.search(r'<InfoDot title="%s">(.*?)</InfoDot>' % re.escape(title), src, re.S)
    if not m:
        raise KeyError(f"{rel}: no InfoDot {title!r}")
    return [norm(p) for p in re.findall(r"<p>(.*?)</p>", m.group(1), re.S)]


def text_in(rel, s):
    """Whether s appears in the file as written (entities decoded, spaces collapsed)."""
    return norm(s) in norm(read(rel))


def object_rows(rel, const):
    """The `{ id: …, label: '…', title: '…', icon: … }` rows of an array constant."""
    src = read(rel)
    m = re.search(r"const %s\b[^=]*=\s*\[(.*?)\n\]" % re.escape(const), src, re.S)
    if not m:
        raise KeyError(f"{rel}: no {const}")
    rows = []
    for body in re.findall(r"\{(.*?)\}\s*,?\s*(?=\{|$)", m.group(1), re.S):
        row = {}
        for k, v in re.findall(r"(\w+):\s*'((?:[^'\\]|\\.)*)'", body):
            row[k] = v
        im = re.search(r"name=\"(\w+)\"", body)
        if im:
            row["icon"] = im.group(1)
        if row:
            rows.append(row)
    return rows


def icon_body(rel, name):
    """The JSX children of icon `name` in an icon table (`name: ( <>…</> ),`)."""
    src = read(rel)
    m = re.search(r"\n  %s: \(\s*(.*?)\n  \),?\n" % re.escape(name), src, re.S)
    if not m:
        raise KeyError(f"{rel}: no icon {name}")
    return m.group(1)
