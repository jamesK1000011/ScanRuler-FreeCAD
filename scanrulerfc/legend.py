# SPDX-License-Identifier: AGPL-3.0-only
# Ported from ScanRuler by Stefan Hermann (CNC Kitchen),
# github.com/CNCKitchen/ScanRuler: src/ui/MapLegend.tsx, src/core/field/
# stats.ts, src/App.tsx (the deviation and thickness legends),
# plugins/mesh-tools/app/useMeshPlugin.tsx (the reduce and copy legends),
# src/core/units.ts and src/ui/format.ts (how a figure is written).
#
# The scale beside a map, read the way an inspection report reads it: the
# ramp, the values it stands for, what its two ends mean, how much of the
# part sits at each value, and the figures under it. One instrument for
# every map; deviation, wall thickness and the mesh maps differ only in what
# they hand it. This module is the data alone, with the original's exact
# strings (`text`) and the way its stylesheet shows them (`caption`, upper
# case), so a Coin builder can draw it. `coin_nodes(model)` is that builder,
# behind a lazy pivy import.

import math
from decimal import ROUND_HALF_UP, Decimal

import numpy as np

from . import colormap as CM

MM_PER_INCH = 25.4
HIST_BINS = 60
MINUS = "−"

# What each end of a signed scale means, in words, per map.
ENDS = {
    "deviation": {"high": "outside the reference", "low": "inside the reference"},
    "deviation-element": {"high": "too much material", "low": "too little material"},
    "reduce": {"high": "mesh inside the scan", "low": "mesh outside the scan"},
    "copy": {"high": "copy outside the scan", "low": "copy inside the scan"},
}

CAP_TITLES = {"high": "Beyond the top of the scale", "low": "Beyond the bottom of the scale"}
LIMIT_TITLE = "Click to set the range of the scale"


# ---------------------------------------------------------------- figures

def to_fixed(x, decimals):
    """JavaScript's Number.prototype.toFixed: the exact value, halves away
    from zero."""
    x = float(x)
    if not math.isfinite(x):
        return "NaN" if x != x else ("Infinity" if x > 0 else "-Infinity")
    q = Decimal(1).scaleb(-decimals) if decimals else Decimal(1)
    d = Decimal(x).quantize(q, rounding=ROUND_HALF_UP)
    s = f"{d:f}"
    if s.startswith("-") and x == 0:
        s = s[1:]
    return s


def js_number(x):
    """String(x) for a plain number, the way JavaScript writes it."""
    x = float(x)
    if x == int(x) and abs(x) < 1e21:
        return str(int(x))
    return repr(x)


def to_display(mm, units="mm"):
    return mm / MM_PER_INCH if units == "in" else mm


def length_decimals(mm_decimals, units):
    return max(3, mm_decimals + 1) if units == "in" else mm_decimals


def unit_word(units="mm", power=1):
    return units + ("²" if power == 2 else "³" if power == 3 else "")


def fmt_len(mm, units="mm", mm_decimals=3, bare=False, signed=False):
    """'12.700 mm' / '0.5000 in', bare without the unit word; never '-0.000'."""
    text = to_fixed(to_display(mm, units), length_decimals(mm_decimals, units))
    if float(text) == 0:
        text = to_fixed(0, length_decimals(mm_decimals, units))
    elif signed and mm > 0:
        text = "+" + text
    return text if bare else f"{text} {unit_word(units)}"


def format_signed(mm, units="mm"):
    """A deviation: '+0.120' / '−0.120', with a true minus sign."""
    shown = to_display(mm, units)
    return ("+" if shown >= 0 else MINUS) + to_fixed(abs(shown), length_decimals(3, units))


def length_input_text(mm, units="mm"):
    """A length as a person would type it: '1', '0.05'."""
    if units == "mm":
        return js_number(mm)
    return js_number(float(to_fixed(to_display(mm, units), 6)))


def wall(mm, units="mm"):
    return fmt_len(mm, units, 3, bare=True)


def count(n):
    """toLocaleString('en-US') of a count: '12,345'."""
    return f"{int(n):,}"


def percent(part, whole, decimals=1):
    return f"{to_fixed(part / whole * 100, decimals)} %" if whole else "—"


# ---------------------------------------------------------------- statistics

def field_stats(values, valid_min, valid_max):
    """Statistics over the readings inside the valid window (NaN never is):
    measured, total, min, max, mean, rms (about zero), sigma (about mean)."""
    v = np.asarray(values, dtype=float).reshape(-1)
    with np.errstate(invalid="ignore"):
        m = v[(v >= valid_min) & (v <= valid_max)]
    n = len(m)
    if not n:
        return {"measured": 0, "total": len(v), "min": 0.0, "max": 0.0, "mean": 0.0, "rms": 0.0, "sigma": 0.0}
    mean = float(m.mean())
    sq = float((m * m).mean())
    return {"measured": n, "total": len(v), "min": float(m.min()), "max": float(m.max()), "mean": mean,
            "rms": math.sqrt(sq), "sigma": math.sqrt(max(0.0, sq - mean * mean))}


def deviation_stats(values, max_distance, tolerance):
    v = np.asarray(values, dtype=float).reshape(-1)
    with np.errstate(invalid="ignore"):
        within = int(np.count_nonzero((np.abs(v) <= max_distance) & (np.abs(v) <= tolerance)))
    return {**field_stats(v, -max_distance, max_distance), "within": within, "tolerance": tolerance}


def thickness_stats(values, limit):
    v = np.asarray(values, dtype=float).reshape(-1)
    with np.errstate(invalid="ignore"):
        below = int(np.count_nonzero(v < limit))
    return {**field_stats(v, 0, math.inf), "below": below, "limit": limit}


def histogram(values, low, high, valid_min=-math.inf, valid_max=math.inf, bins=HIST_BINS):
    """Counts across the colour scale, low to high; values past either end
    fold into the end bins, as the caps take them."""
    out = np.zeros(bins, dtype=np.int64)
    if not high > low:
        return {"bins": out.tolist(), "low": low, "high": high, "peak": 0}
    v = np.asarray(values, dtype=float).reshape(-1)
    with np.errstate(invalid="ignore"):
        v = v[(v >= valid_min) & (v <= valid_max)]
    b = np.clip(np.floor((v - low) * (bins / (high - low))), 0, bins - 1).astype(int)
    np.add.at(out, b, 1)
    return {"bins": out.tolist(), "low": low, "high": high, "peak": int(out.max()) if bins else 0}


def histogram_rows(hist, fmt):
    """Each bin as the legend reads it on hover: its stretch of the scale,
    its count and its share. The end bins read open-ended."""
    bins, low, high = hist["bins"], hist["low"], hist["high"]
    n = len(bins)
    step = (high - low) / n if n else 0
    total = sum(bins)
    peak = hist["peak"]
    rows = []
    for i, c in enumerate(bins):
        if i == 0:
            rng = f"under {fmt(low + step)}"
        elif i == n - 1:
            rng = f"{fmt(high - step)} and over"
        else:
            rng = f"{fmt(low + i * step)} – {fmt(low + (i + 1) * step)}"
        share = to_fixed(c / total * 100, 1) if total else "0.0"
        rows.append({"index": i, "count": c, "width": c / peak if peak else 0.0,
                     "lo": (i + 0.0) / n, "hi": (i + 1.0) / n,
                     "range": rng, "readout": f"{count(c)} pts · {share} %"})
    return rows


# ---------------------------------------------------------------- stats rows

def _row(label, value, wide=False):
    return {"label": label, "caption": label.upper(), "value": value, "wide": wide}


def deviation_rows(st, units="mm"):
    """MIN MAX MEAN RMS SIGMA ±tol MATCHED, as the original's card."""
    def mm(v):
        return format_signed(v, units)

    def w(v):
        return wall(v, units)
    return [
        _row("min", mm(st["min"])),
        _row("max", mm(st["max"])),
        _row("mean", mm(st["mean"])),
        _row("RMS", w(st["rms"])),
        _row("sigma", w(st["sigma"])),
        _row(f"±{w(st['tolerance'])}", percent(st["within"], st["measured"])),
        _row("matched", f"{count(st['measured'])} / {count(st['total'])}", True),
    ]


def thickness_rows(st, units="mm"):
    """MIN MAX MEAN SIGMA UNDER limit THIN PTS MEASURED."""
    def w(v):
        return wall(v, units)
    return [
        _row("min", w(st["min"])),
        _row("max", w(st["max"])),
        _row("mean", w(st["mean"])),
        _row("sigma", w(st["sigma"])),
        _row(f"under {length_input_text(st['limit'], units)}", percent(st["below"], st["measured"])),
        _row("thin pts", count(st["below"])),
        _row("measured", f"{count(st['measured'])} / {count(st['total'])}", True),
    ]


def reduce_rows(report, units="mm"):
    """A reduced mesh against the scan: ±tol share, 99.9 %, max, RMS."""
    return [
        _row(f"±{length_input_text(report['tolerance'], units)}", percent(report["within"], report["measured"], 2)),
        _row("99.9 %", wall(report["p999"], units)),
        _row("max", wall(report["max"], units)),
        _row("RMS", wall(report["rms"], units)),
    ]


def copy_rows(st, units="mm"):
    """An edited copy against the scan: MAX RMS, and ADDED when it added any."""
    rows = [_row("max", wall(st["max_abs"], units)), _row("RMS", wall(st["rms"], units))]
    if st.get("added", 0) > 0:
        rows.append(_row("added", percent(st["added"], st["added"] + st["measured"])))
    return rows


# ---------------------------------------------------------------- the model

def ticks(low, high, fmt, zero_at=None, n=CM.TICKS):
    """`n` ticks up the ramp, low to high; one at `zero_at` drawn bold green."""
    out = []
    for i in range(n):
        f = i / (n - 1)
        v = low + (high - low) * f
        out.append({"fraction": f, "value": v, "text": fmt(v),
                    "zero": zero_at is not None and abs(v - zero_at) < 1e-9,
                    "limit": "low" if i == 0 else "high" if i == n - 1 else None})
    return out


def model(kind, low, high, *, colormap=CM.DEFAULT, bands=None, units="mm", values=None,
          valid_min=None, valid_max=None, show_histogram=False, stats=None, source="reference",
          marks=None):
    """The legend for one map, as data.

    kind: 'deviation', 'thickness', 'reduce' or 'copy'. `stats` is what the
    card's rows are built from (deviation_stats, thickness_stats, or a
    report/copy dict); given `values` instead, deviation and thickness work
    it out (deviation needs `stats={'tolerance': t}`, thickness
    `stats={'limit': l}`, as hints)."""
    signed = kind != "thickness"
    reversed_ = kind == "thickness"
    if valid_min is None:
        valid_min = 0.0 if kind == "thickness" else -math.inf
    if valid_max is None:
        valid_max = math.inf

    def fmt(v):
        return format_signed(v, units) if signed else wall(v, units)

    head_words = [unit_word(units), "wall" if kind == "thickness" else None]
    head = " ".join(w for w in head_words if w)
    ends = None
    if kind == "deviation":
        ends = ENDS["deviation-element" if source == "element" else "deviation"]
    elif kind in ("reduce", "copy"):
        ends = ENDS[kind]
    ends_model = None
    if ends:
        ends_model = {e: {"sign": "+" if e == "high" else MINUS, "text": ends[e],
                          "caption": f"{'+' if e == 'high' else MINUS} {ends[e].upper()}"} for e in ("high", "low")}

    cap_lo, cap_hi = CM.scale_caps(colormap, reversed_)
    hist = None
    if values is not None and show_histogram and kind in ("deviation", "thickness"):
        hist = histogram(values, low, high, valid_min, valid_max)
        hist["rows"] = histogram_rows(hist, fmt)

    rows = None
    if kind == "deviation":
        st = stats
        if values is not None and (st is None or "measured" not in st):
            md = valid_max if math.isfinite(valid_max) else math.inf
            st = deviation_stats(values, md, (st or {}).get("tolerance", 0.1))
        rows = deviation_rows(st, units) if st else None
    elif kind == "thickness":
        st = stats
        if values is not None and (st is None or "measured" not in st):
            st = thickness_stats(values, (st or {}).get("limit", 1.0))
        rows = thickness_rows(st, units) if st else None
    elif kind == "reduce":
        rows = reduce_rows(stats, units) if stats else None
    elif kind == "copy":
        rows = copy_rows(stats, units) if stats else None

    def share(v):
        return (v - low) / ((high - low) or 1)

    shown = [dict(m, fraction=share(m["value"]),
                  to_fraction=None if m.get("to") is None else min(1.0, max(0.0, share(m["to"]))))
             for m in (marks or []) if 0 < share(m["value"]) < 1]

    return {
        "kind": kind,
        "head": head,
        "caption": head.upper(),
        "ends": ends_model,
        "colormap": CM.colormap_by_id(colormap).id,
        "bands": bands,
        "reversed": reversed_,
        "ramp": CM.legend_stops(colormap, bands, reversed_),
        "caps": {"high": {"rgb": tuple(cap_hi), "title": CAP_TITLES["high"]},
                 "low": {"rgb": tuple(cap_lo), "title": CAP_TITLES["low"]}},
        "ticks": ticks(low, high, fmt, 0 if signed else None),
        "limit_title": LIMIT_TITLE,
        "histogram": hist,
        "stats": rows,
        "marks": shown,
        "low": low,
        "high": high,
    }


# ---------------------------------------------------------------- Coin

# What SoText2 draws: Coin's own font may lack a glyph past ASCII, and a
# string it cannot read is drawn as nothing or as stray marks. The words in
# the window keep their meaning in plain ASCII (the model keeps the
# original's strings).
ASCII = {MINUS: "-", "\u00b7": ",", "\u00b0": " deg", "\u00d8": "dia ", "\u2713": "OK", "\u2717": "NG", "\u00b1": "+/-",
         "\u00d7": "x", "\u00b2": "2", "\u00b3": "3", "\u2026": "...", "\u00a0": " ", "\u2009": " ", "\u2014": "-", "\u2013": "-"}


def coin_text(s):
    """s as SoText2 can draw it: plain ASCII ("\u2212" to "-", "\u00b0" to " deg")."""
    out = []
    for ch in str(s):
        out.append(ch if ord(ch) < 128 else ASCII.get(ch, "?"))
    return "".join(out).replace(" , ", ", ")


# Where the legend stands in the 3D view, as shares of the view (its
# camera maps the unit square onto the whole view): against the right
# edge, clear of a part framed in the middle. Window review round 6: at
# x 0.80 it stood over the part's right side.
PLACE = {"x": 0.86, "y": 0.24, "w": 0.03, "h": 0.52}
CARD_RGB = (246, 246, 244)
TEXT_RGB = (30, 30, 30)
ZERO_RGB = (46, 125, 70)


def text_rows(m):
    """The words the legend draws, as data (the answer's facts and the
    tests): its title, the low, middle and high tick, and how many ticks."""
    t = m.get("ticks") or []
    mid = t[len(t) // 2]["text"] if t else None
    return {"title": coin_text(m.get("caption") or ""), "min": coin_text(t[0]["text"]) if t else None,
            "mid": coin_text(mid) if mid is not None else None, "max": coin_text(t[-1]["text"]) if t else None, "ticks": len(t)}


def stat_lines(stats):
    """How many lines the stats card takes (two figures a line, a wide
    one a line of its own), as coin_nodes lays them."""
    places = stat_places(stats)
    return (max(p[0] for p in places) + 1) if places else 0


def stat_places(stats):
    """(line, column) of each stats row: two figures a line, a wide one on
    a line of its own (it no longer lands on a half-filled line, over the
    figure before it)."""
    out, line, col = [], 0, 0
    for row in stats or []:
        if row["wide"]:
            if col:
                line, col = line + 1, 0
            out.append((line, 0))
            line += 1
            continue
        out.append((line, col))
        if col:
            line, col = line + 1, 0
        else:
            col = 1
    return out


def coin_nodes(m, x=None, y=None, w=None, h=None, coin=None, font_size=None):
    """The legend as a Coin overlay: an SoAnnotation holding an orthographic
    camera over the unit square, a light card behind it (the words read on
    any background), the ramp as quads (with its caps), the title above it
    (what is mapped, its unit), the value of every tick beside it (low,
    middle and high among them), histogram bars and the stats card. Draws
    in view_render pictures and saved images too, which a Qt overlay would
    not. coin: the module to build with (pivy's by default; the tests hand
    a stand-in). font_size: the words' size in the view's device pixels
    (SoFont); None leaves Coin's default (10, half of that on a Retina
    screen: window review round 6 could read none of them)."""
    x = PLACE["x"] if x is None else x
    y = PLACE["y"] if y is None else y
    w = PLACE["w"] if w is None else w
    h = PLACE["h"] if h is None else h
    if coin is None:
        from pivy import coin  # lazy: only inside FreeCAD's GUI

        if not coin.SoDB.isInitialized():  # outside FreeCAD's GUI (a test run): nodes need the database
            coin.SoDB.init()
    root = coin.SoAnnotation()
    cam = coin.SoOrthographicCamera()
    cam.viewportMapping = coin.SoCamera.LEAVE_ALONE
    cam.position = (0.5, 0.5, 1)
    cam.height = 1
    cam.nearDistance = 0.5
    cam.farDistance = 1.5
    root.addChild(cam)
    lm = coin.SoLightModel()
    lm.model = coin.SoLightModel.BASE_COLOR
    root.addChild(lm)
    if font_size:
        font = coin.SoFont()
        font.size = float(font_size)
        root.addChild(font)

    def quad(x0, y0, x1, y1, rgb):
        sep = coin.SoSeparator()
        mat = coin.SoBaseColor()
        mat.rgb = tuple(c / 255.0 for c in rgb)
        sep.addChild(mat)
        co = coin.SoCoordinate3()
        co.point.setValues(0, 4, [(x0, y0, 0), (x1, y0, 0), (x1, y1, 0), (x0, y1, 0)])
        sep.addChild(co)
        fs = coin.SoFaceSet()
        fs.numVertices = 4
        sep.addChild(fs)
        return sep

    def text(s, tx, ty, rgb=TEXT_RGB, right=False):
        sep = coin.SoSeparator()
        col = coin.SoBaseColor()
        col.rgb = tuple(c / 255.0 for c in rgb)
        sep.addChild(col)
        tr = coin.SoTranslation()
        tr.translation = (tx, ty, 0)
        sep.addChild(tr)
        t = coin.SoText2()
        t.string = coin_text(s)
        if right and getattr(coin.SoText2, "RIGHT", None) is not None:
            t.justification = coin.SoText2.RIGHT
        sep.addChild(t)
        return sep

    cap = 0.02
    stats = m.get("stats") or []
    rows = stat_lines(stats)
    wide_left = bool(stats or m.get("ends") or m.get("histogram"))
    left = x - 0.11 if wide_left else x - 0.015
    bottom = (y - cap - 0.075 - 0.03 * rows) if stats else (y - cap - 0.05 if m.get("ends") else y - cap - 0.02)
    # The card first: SoAnnotation draws in order, without the depth test.
    root.addChild(quad(left, bottom, 0.995, y + h + cap + 0.065, CARD_RGB))
    if m["bands"] and m["bands"] >= 2:
        for a, b, rgb in m["ramp"]:
            root.addChild(quad(x, y + a * h, x + w, y + b * h, rgb))
    else:
        r = m["ramp"]
        for (a, ca), (b, _cb) in zip(r, r[1:]):
            root.addChild(quad(x, y + a * h, x + w, y + b * h, ca))
    root.addChild(quad(x, y + h, x + w, y + h + cap, m["caps"]["high"]["rgb"]))
    root.addChild(quad(x, y - cap, x + w, y, m["caps"]["low"]["rgb"]))
    for t in m["ticks"]:
        root.addChild(text(t["text"], x + w + 0.008, y + t["fraction"] * h - 0.008,
                           ZERO_RGB if t["zero"] else TEXT_RGB))
    # The title: what is mapped and its unit, over the ramp, its right end
    # at the card's.
    root.addChild(text(m["caption"], 0.985, y + h + cap + 0.03, right=True))
    if m["ends"]:
        root.addChild(text(m["ends"]["high"]["caption"], x - 0.1, y + h + cap + 0.005))
        root.addChild(text(m["ends"]["low"]["caption"], x - 0.1, y - cap - 0.035))
    if m["histogram"]:
        hw = 0.06
        for row in m["histogram"]["rows"]:
            if row["count"]:
                root.addChild(quad(x - 0.004 - hw * row["width"], y + row["lo"] * h,
                                   x - 0.004, y + row["hi"] * h, (150, 150, 150)))
    if stats:
        for row, (line, col) in zip(stats, stat_places(stats)):
            root.addChild(text(f"{row['caption']}  {row['value']}", x - 0.1 + col * 0.1, y - cap - 0.07 - 0.03 * line))
    return root
