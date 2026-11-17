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


def format_signed(mm, units="mm", decimals=None):
    """A deviation: '+0.120' / '−0.120', with a true minus sign. decimals:
    the places shown (the unit's own by default)."""
    shown = to_display(mm, units)
    d = length_decimals(3, units) if decimals is None else decimals
    return ("+" if shown >= 0 else MINUS) + to_fixed(abs(shown), d)


def length_input_text(mm, units="mm"):
    """A length as a person would type it: '1', '0.05'."""
    if units == "mm":
        return js_number(mm)
    return js_number(float(to_fixed(to_display(mm, units), 6)))


def wall(mm, units="mm", decimals=None):
    if decimals is None:
        return fmt_len(mm, units, 3, bare=True)
    text = to_fixed(to_display(mm, units), decimals)
    return to_fixed(0, decimals) if float(text) == 0 else text


TICK_DECIMALS_MAX = 6


def tick_decimals(low, high, units="mm", n=None):
    """The places a tick's value is written with: the unit's own (3 in mm),
    more when the ticks stand closer than that can tell apart, so each
    tick reads within a twentieth of a step of its value. Window review
    round 7: a ±0.001 mm deviation scale read +0.001, +0.001, +0.001, +0.000,
    ... at 3 places."""
    n = CM.TICKS if n is None else n
    base = length_decimals(3, units)
    lo, hi = to_display(low, units), to_display(high, units)
    step = abs(hi - lo) / max(1, n - 1)
    if not (step > 0 and math.isfinite(step)):
        return base
    vals = [lo + (hi - lo) * i / (n - 1) for i in range(n)]
    d = base
    while d < TICK_DECIMALS_MAX and max(abs(float(to_fixed(v, d)) - v) for v in vals) > step * 0.05:
        d += 1
    return d


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

    places = tick_decimals(low, high, units)

    def tick_fmt(v):
        return format_signed(v, units, places) if signed else wall(v, units, places)

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
        "ticks": ticks(low, high, tick_fmt, 0 if signed else None),
        "tickDecimals": places,
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


# Where the legend stands in the 3D view. Its words are SoText2, drawn at
# a size in the view's device pixels whatever the view's size, so the card
# is laid out in device pixels too, from the words it holds: wide enough
# for its longest line, against the view's right edge, under the corner
# where the navigation cube stands and above the bottom right corner where
# Agent Link's caption stands. Window review round 7: laid out as shares
# of the view, the card ended at the view's edge while its words ran past
# it, and the stats' second column fell on the first.
CARD_RGB = (246, 246, 244)
TEXT_RGB = (30, 30, 30)
ZERO_RGB = (46, 125, 70)
HIST_RGB = (150, 150, 150)
CHAR_W = 0.75        # a character's advance, a share of the font size (round 7 pictures: Coin's default face 0.70-0.73)
MIN_CHARS = 14       # the card's narrowest, in characters
LINE_H = 1.45        # a line's height, a share of the font size
TOP_SHARE = 0.86     # the card's top, a share of the view's height (the navigation cube above it)
FLOOR_SHARE = 0.17   # the card's lowest edge when there is room (Agent Link's caption below it)
RAMP_SHARE = 0.5     # the ramp's height at most, a share of the view's height
DEFAULT_VIEW = (1600.0, 1000.0)  # device px, when the view's size is not known (stand-ins)
DEFAULT_FONT = 26.0


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


def stat_text(row):
    return coin_text(f"{row['caption']} {row['value']}")


def card_layout(m, view_w=None, view_h=None, font_px=None):
    """_card_layout at font_px, or at a smaller font (down to 0.6 of it,
    in steps of a tenth) when the card would not fit in a small view; the
    answer's `font` is the size the words are drawn at."""
    fs = float(font_px or DEFAULT_FONT)
    lay = _card_layout(m, view_w, view_h, fs)
    k = 1.0
    while not lay["fits"] and k > 0.65:
        k -= 0.1
        lay = _card_layout(m, view_w, view_h, fs * k)
    return lay


def wrap(text, chars):
    """text in lines of at most `chars` characters, broken between words
    (a word longer than that stands on a line of its own)."""
    lines, cur = [], ""
    for word in str(text).split():
        if cur and len(cur) + 1 + len(word) > chars:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}" if cur else word
    if cur:
        lines.append(cur)
    return lines or [""]


def _card_layout(m, view_w=None, view_h=None, font_px=None):
    """Where every part of the legend stands, in the view's device pixels
    (x right, y up, from the view's bottom left corner): the card, the
    ramp, the caps, each word (its left end and baseline) and the
    histogram's bars. Widths come from the words: CHAR_W of the font size a
    character, an upper bound for Coin's monospaced face. The card is as
    wide as the title, the ramp with its ticks, or the widest single
    figure (MIN_CHARS at least); the ends' words and a wide figure wrap to
    that; the stats take two columns when two fit, else one. Ticks too
    close to read are thinned (every 2nd, 4th, ...); the ends always stay.
    `fits` says the card lies inside the view."""
    vw, vh = float(view_w or DEFAULT_VIEW[0]), float(view_h or DEFAULT_VIEW[1])
    fs = float(font_px or DEFAULT_FONT)
    cw, lh, pad = CHAR_W * fs, LINE_H * fs, 0.7 * fs
    margin = max(8.0, 0.015 * min(vw, vh))
    title = coin_text(m.get("caption") or "")
    ends = m.get("ends")
    ticks_ = m.get("ticks") or []
    tick_t = [coin_text(t["text"]) for t in ticks_]
    hist = m.get("histogram")
    ramp_w, gap = 1.1 * fs, 0.5 * fs
    hist_w = 3.0 * fs if hist else 0.0
    ramp_block = hist_w + (gap if hist else 0.0) + ramp_w + gap + max((len(t) for t in tick_t), default=0) * cw
    stats = m.get("stats") or []
    texts = [stat_text(r) for r in stats]
    narrow = [t for t, r in zip(texts, stats) if not r["wide"]]
    chars = max(MIN_CHARS, len(title), math.ceil(ramp_block / cw), max((len(t) for t in narrow), default=0))
    # The stats: two columns when two fit in `chars`, else one; a wide row
    # on its own line(s), wrapped.
    col_gap = 2
    half = (narrow[0::2], narrow[1::2])
    col0 = max((len(t) for t in half[0]), default=0)
    col1 = max((len(t) for t in half[1]), default=0)
    two = bool(half[1]) and col0 + col_gap + col1 <= chars
    stat_cells = []  # (text, line, column)
    line = col = 0
    for t, r in zip(texts, stats):
        if r["wide"]:
            if col:
                line, col = line + 1, 0
            for part in wrap(t, chars):
                stat_cells.append((part, line, 0))
                line += 1
            continue
        stat_cells.append((t, line, col))
        if two and col == 0:
            col = 1
        else:
            line, col = line + 1, 0
    n_stats = line + (1 if col else 0)
    high_l = wrap(coin_text(ends["high"]["caption"]), chars) if ends else []
    low_l = wrap(coin_text(ends["low"]["caption"]), chars) if ends else []
    card_w = chars * cw + 2 * pad
    above = 1 + len(high_l)
    below = len(low_l) + n_stats
    cap = 0.5 * fs
    stat_gap = 0.4 * lh if stats else 0.0
    fixed = 2 * pad + lh * (above + below) + 2 * cap + stat_gap
    top = min(vh - margin, vh * TOP_SHARE)
    ramp_h = min(top - vh * FLOOR_SHARE - fixed, vh * RAMP_SHARE)
    ramp_h = max(ramp_h, min(4 * lh, top - margin - fixed))
    ramp_h = max(ramp_h, 2 * lh)
    card_h = fixed + ramp_h
    if top - card_h < margin:
        top = max(top, vh - margin)  # a short view: up into the cube's corner rather than off the bottom
    x1 = vw - margin
    x0 = x1 - card_w
    y1 = top
    y0 = y1 - card_h
    rx0 = x0 + pad + hist_w + (gap if hist else 0.0)
    rx1 = rx0 + ramp_w
    rt = y1 - pad - lh * above - cap
    rb = rt - ramp_h
    n = len(ticks_)
    every = 1
    while n > 2 and every < n - 1 and ramp_h / max(1, n - 1) * every < 1.1 * lh:
        every *= 2
    shown = [i for i in range(n) if i % every == 0 or i == n - 1]
    if n > 1 and every > 1 and len(shown) >= 2 and (shown[-1] - shown[-2]) * ramp_h / (n - 1) < 1.1 * lh:
        shown.pop(-2)  # the top end stays; the one under it goes
    base = 0.8 * fs + 0.2 * lh  # a line's baseline under its top
    words = [{"text": title, "x": x0 + pad, "y": y1 - pad - base, "role": "title"}]
    for i, t in enumerate(high_l):
        words.append({"text": t, "x": x0 + pad, "y": y1 - pad - lh * (1 + i) - base, "role": "high"})
    for i in shown:
        t = ticks_[i]
        words.append({"text": tick_t[i], "x": rx1 + gap, "y": rb + t["fraction"] * ramp_h - 0.35 * fs,
                      "role": "zero" if t.get("zero") else "tick"})
    line_y = rb - cap
    for i, t in enumerate(low_l):
        words.append({"text": t, "x": x0 + pad, "y": line_y - lh * i - base, "role": "low"})
    line_y -= lh * len(low_l) + stat_gap
    for t, ln, c in stat_cells:
        words.append({"text": t, "x": x0 + pad + c * (col0 + col_gap) * cw, "y": line_y - ln * lh - base, "role": "stat"})
    bars = []
    if hist:
        for row in hist.get("rows") or []:
            if row["count"]:
                right = rx0 - 0.2 * fs
                bars.append((right - hist_w * row["width"], rb + row["lo"] * ramp_h, right, rb + row["hi"] * ramp_h))
    rnd = lambda v: round(float(v), 1)  # noqa: E731
    return {"view": [rnd(vw), rnd(vh)], "font": fs, "card": [rnd(x0), rnd(y0), rnd(x1), rnd(y1)],
            "ramp": [rnd(rx0), rnd(rb), rnd(rx1), rnd(rt)], "cap": cap, "words": words, "bars": bars,
            "shownTicks": [tick_t[i] for i in shown], "every": every, "chars": chars, "statColumns": 2 if two else 1,
            "fits": bool(x0 >= 0 and y0 >= 0 and x1 <= vw and y1 <= vh)}


def box_facts(lay):
    """The card against the view, for the call's answer: its pixel rect,
    the view's size, whether it fits, the tick strings drawn."""
    vw, vh = lay["view"]
    x0, y0, x1, y1 = lay["card"]
    return {"px": lay["card"], "view": lay["view"], "share": [round(x0 / vw, 3), round(y0 / vh, 3), round(x1 / vw, 3), round(y1 / vh, 3)],
            "fits": lay["fits"], "fontSize": lay["font"], "shownTicks": lay["shownTicks"],
            "textRight": round(max(w["x"] + len(w["text"]) * CHAR_W * lay["font"] for w in lay["words"]), 1) if lay["words"] else None}


def coin_nodes(m, coin=None, font_size=None, view=None, layout=None):
    """The legend as a Coin overlay: an SoAnnotation holding an orthographic
    camera over the unit square (the whole view), a light card behind it
    (the words read on any background), the ramp as quads (with its caps),
    the title above it (what is mapped, its unit), the value of the ticks
    beside it (low, middle and high among them), histogram bars and the
    stats card, all where card_layout puts them. Draws in view_render
    pictures and saved images too, which a Qt overlay would not. coin: the
    module to build with (pivy's by default; the tests hand a stand-in).
    font_size: the words' size in the view's device pixels (SoFont). view:
    (width, height) of the view in device pixels. layout: card_layout's
    answer, when the caller has it already."""
    lay = layout or card_layout(m, *(view or (None, None)), font_size)
    vw, vh = lay["view"]
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
    if font_size or layout is not None:
        font = coin.SoFont()
        font.size = float(lay["font"])  # card_layout's: font_size, or less in a small view
        root.addChild(font)

    def quad(px0, py0, px1, py1, rgb):
        x0, y0, x1, y1 = px0 / vw, py0 / vh, px1 / vw, py1 / vh
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

    def text(s, px, py, rgb=TEXT_RGB):
        sep = coin.SoSeparator()
        col = coin.SoBaseColor()
        col.rgb = tuple(c / 255.0 for c in rgb)
        sep.addChild(col)
        tr = coin.SoTranslation()
        tr.translation = (px / vw, py / vh, 0)
        sep.addChild(tr)
        t = coin.SoText2()
        t.string = coin_text(s)
        sep.addChild(t)
        return sep

    # The card first: SoAnnotation draws in order, without the depth test.
    root.addChild(quad(*lay["card"], CARD_RGB))
    rx0, rb, rx1, rt = lay["ramp"]
    h = rt - rb
    if m["bands"] and m["bands"] >= 2:
        for a, b, rgb in m["ramp"]:
            root.addChild(quad(rx0, rb + a * h, rx1, rb + b * h, rgb))
    else:
        r = m["ramp"]
        for (a, ca), (b, _cb) in zip(r, r[1:]):
            root.addChild(quad(rx0, rb + a * h, rx1, rb + b * h, ca))
    cap = lay["cap"]
    root.addChild(quad(rx0, rt, rx1, rt + cap, m["caps"]["high"]["rgb"]))
    root.addChild(quad(rx0, rb - cap, rx1, rb, m["caps"]["low"]["rgb"]))
    for bar in lay["bars"]:
        root.addChild(quad(*bar, HIST_RGB))
    for w in lay["words"]:
        root.addChild(text(w["text"], w["x"], w["y"], ZERO_RGB if w["role"] == "zero" else TEXT_RGB))
    return root
