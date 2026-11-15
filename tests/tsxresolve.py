# SPDX-License-Identifier: AGPL-3.0-only
# InfoDot texts of ScanRuler's TSX (ScanRuler by Stefan Hermann, CNC Kitchen,
# github.com/CNCKitchen/ScanRuler) with their JSX expressions read the way
# the port shows them: millimetres (the `inches ?` branch not taken), the
# reference-model side of a Deviation panel (`onElement ?` not taken), and
# `len.word()` as "mm". Used by tools/gen_infotext_pages.py and by the page
# tests, so both read the original the same way. Read only.
import re

import tsxsource as T

_STR = r"'(?:[^'\\]|\\.)*'|`[^`]*`"
_TERN = re.compile(r"\{\s*!?(inches|inch|onElement|imperial)\s*\?\s*(%s)\s*:\s*(%s)\s*\}" % (_STR, _STR), re.S)
_INNER_TERN = re.compile(r"\$\{\s*(inches|onElement)\s*\?\s*(%s)\s*:\s*(%s)\s*\}" % (_STR, _STR), re.S)


def _unq(s):
    return s[1:-1]


def _locals(src):
    """A component's own millimetre constants: `const x = inch ? 'a' : 'b'`,
    `const ex = len.units === 'in' ? {…} : {k: v, …}`, `const w = len.word()`."""
    out = {}
    for name, _a, b in re.findall(r"const (\w+) = (?:inch|inches) \? (%s) : (%s)" % (_STR, _STR), src):
        out[name] = _unq(b)
    for name, body in re.findall(r"const (\w+) = len\.units === 'in' \? \{[^}]*\} : \{([^}]*)\}", src):
        for k, v in re.findall(r"(\w+):\s*([\d.]+)", body):
            out[f"{name}.{k}"] = v
    for name in re.findall(r"const (\w+) = len\.word\(\)", src):
        out[name] = "mm"
    if re.search(r"\bSHARE\b", src) and "meshFormat" in src:
        held = float(re.search(r"HELD_SHARE = ([\d.]+)", T.read("plugins/mesh-tools/core/reduce.ts")).group(1))
        out["SHARE"] = f"{held * 100:.1f} %"
    return out


def resolve(src):
    for name, v in _locals(src).items():
        src = src.replace("{%s}" % name, v)
    src = src.replace("${len.word()}", "mm").replace("{len.word()}", "mm")
    src = _INNER_TERN.sub(lambda m: _unq(m.group(3)), src)
    src = _TERN.sub(lambda m: _unq(m.group(3)), src)
    return src


def _paras(body):
    return [T.norm(p) for p in re.findall(r"<p>(.*?)</p>", body, re.S)]


def infodot(rel, title):
    """The paragraphs of the InfoDot with this title, expressions resolved."""
    src = resolve(T.read(rel))
    m = re.search(r'<InfoDot title="%s">(.*?)</InfoDot>' % re.escape(title), src, re.S)
    if not m:
        raise KeyError(f"{rel}: no InfoDot {title!r}")
    return _paras(m.group(1))


def infodot_branch(rel, expr_title, which):
    """An InfoDot whose title is a `{onElement ? 'A' : 'B'}` expression: the
    paragraphs of branch `which` (0 or 1) of its body's own ternary."""
    src = T.read(rel)
    m = re.search(r"<InfoDot title=\{%s\}>(.*?)</InfoDot>" % re.escape(expr_title), src, re.S)
    if not m:
        raise KeyError(f"{rel}: no InfoDot {expr_title!r}")
    body = m.group(1)
    a, _, b = body.partition(") : (")
    return _paras(resolve(a if which == 0 else b))
