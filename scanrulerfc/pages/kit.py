# SPDX-License-Identifier: AGPL-3.0-only
# Ported from ScanRuler by Stefan Hermann (CNC Kitchen),
# github.com/CNCKitchen/ScanRuler: the parts every sidebar page of the
# original is built from (src/ui/InfoDot.tsx, NumberField.tsx, ModelSlot.tsx,
# ScaleControls.tsx, ProbeList.tsx, the kindrow/moderow/checkrow forms).
#
# The page-model pieces shared by the Surface Deviation, Wall Thickness,
# 2D Measure, Mesh Tools and Reverse engineer pages (design 2.0), in the
# shape pages/measure3d.py set: a section is a dict with its number, id,
# header and caps caption, its (i) title and text, rows, keys, fields and
# hint. Fields here also carry a kind — select, number (with unit and "auto"),
# check, toggle (a pair of exclusive keys) or slider — so the one thin Qt
# view below draws every page. Pure Python above the Qt part.

from .. import legend as L
from .. import workspaces as W

SCAN_DOT = "#8b9099"
REFERENCE_DOT = "#7f8ba0"
SCAN_FORMATS = "STL, PLY or OBJ · mm"
BAND_CHOICES = (5, 7, 9, 11, 15, 21)  # deviationStore.ts BAND_CHOICES
HINT_DROP = "Drop it anywhere in the window."
PINS_HINT = "Hover the part for a live reading; click to pin one where you need a number."


def info_of(info, page, title):
    if not title:
        return None
    return list(info[page][title]["paragraphs"])


def key(id_, label, enabled=True, tip=None, pressed=False, primary=False):
    return {"id": id_, "label": label, "enabled": bool(enabled), "tip": tip or label, "pressed": bool(pressed), "primary": primary}


def section(num, id_, header, info=None, info_text=None, visible=True, **more):
    out = {"number": num, "id": id_, "header": header, "caption": header.upper(), "info": info, "info_text": info_text,
           "visible": bool(visible), "rows": [], "keys": [], "fields": [], "hint": None, "count": None, "show_all": None}
    out.update(more)
    return out


def select(id_, label, options, value, enabled=True, info=None, info_text=None):
    return {"id": id_, "kind": "select", "label": label, "options": [{"value": v, "label": t} for v, t in options],
            "value": value, "enabled": bool(enabled), "info": info, "info_text": info_text}


def number(id_, label, value, unit="mm", auto=None, step=None, minimum=None, enabled=True, hint=None, integer=False):
    """A number field; `integer` for a count (an integer spin box, no decimals)."""
    return {"id": id_, "kind": "number", "label": label, "value": value, "unit": unit, "auto": auto, "step": step,
            "min": minimum, "enabled": bool(enabled), "hint": hint, "info": None, "info_text": None, "integer": bool(integer)}


def check(id_, label, value, enabled=True, info=None, info_text=None):
    return {"id": id_, "kind": "check", "label": label, "value": bool(value), "enabled": bool(enabled), "info": info, "info_text": info_text}


def toggle(id_, label, options, value, enabled=True, tips=None):
    """A moderow: exclusive keys, `options` ((value, label), …)."""
    tips = tips or {}
    return {"id": id_, "kind": "toggle", "label": label, "value": value, "enabled": bool(enabled),
            "options": [{"value": v, "label": t, "tip": tips.get(v, t)} for v, t in options], "info": None, "info_text": None}


def slider(id_, label, value, lo, hi, log=False, enabled=True):
    return {"id": id_, "kind": "slider", "label": label, "value": value, "min": lo, "max": hi, "log": bool(log),
            "enabled": bool(enabled), "info": None, "info_text": None}


def bands_field(bands):
    """ScaleControls.tsx: Bands — Continuous, then "n bands"."""
    return select("bands", "Bands", [(0, "Continuous")] + [(b, f"{b} bands") for b in BAND_CHOICES], bands or 0)


def scan_slot(scan, busy=False, edited=False):
    name = getattr(scan, "name", None)
    tri = len(scan.F) if scan is not None else 0
    return {"role": "Scan", "name": name or "No scan loaded",
            "detail": f"{L.count(tri)} triangles" + (" · edited" if edited else "") if scan is not None else SCAN_FORMATS,
            "dot": SCAN_DOT, "filled": scan is not None,
            "button": key("open-scan", "Replace…" if scan is not None else "Open…", not busy)}


def pins(probes, info_text=None):
    """ProbeList.tsx: "Pinned readings" with its count, the hint while empty."""
    s = section("—", "pins", "Pinned readings", count=len(probes))
    s["rows"] = [{"id": i, "name": p.get("name", f"Pin {i + 1}"), "reading": p.get("reading", ""), "visible": True}
                 for i, p in enumerate(probes)]
    if probes:
        s["fields"] = [check("hide-pins", "Hide pins behind the part", True, info="Hide pins behind the part", info_text=info_text)]
        s["keys"] = [key("clear-pins", "Clear")]
    else:
        s["hint"] = PINS_HINT
    return s


def page(title, workspace, sections):
    return {"title": title, "workspace": workspace, "sections": sections, "footer": W.CREDIT}


# --- the Qt view --------------------------------------------------------------

def button_text(label):
    """A panel button's text: Title Case, as FreeCAD's design guide asks of
    buttons (the model keeps the original's words)."""
    return W.title_case(label)


def group_title(s):
    """A section's group title: its header in Title Case, the way FreeCAD
    titles a task panel's group boxes (the original's caps caption stays in
    the model)."""
    return W.title_case(s["header"]) if s.get("header") else ""


# Narrower than this, the page's key grids drop to two columns and a slot's
# or field's label stacks above its button or box (the panel stands beside
# the tree or slides out over the view, 300 px or less).
NARROW = 320
# A field's label goes above its box or list below this width, so the list
# gets the whole row ("Center to ce…" was cut in a 330 px dock).
FIELD_NARROW = 400
LONG_CHECK = 28
# Dense, so a whole section fits without scrolling beside the tree: the
# space between rows and groups, a page's margins, a group's inner margins
# (left, top, right, bottom: the header as far from the card's top edge as
# the rows are from its sides; no taller than the 6/4/6/4 cards were).
SPACING, MARGIN, GROUP_MARGINS = 4, 4, (4, 4, 4, 4)
# The dynamic property that marks a section card (a QFrame) for the sheet.
CARD = "card"
# Window pass 3 (01-012 to 02-096): the Create Element keys were squashed
# to a few pixels high and unreadable, and the Measure Against keys were
# cut. The scroll area gives its page the height the page's layout
# reckons for its width (heightForWidth) — reckoned before reflow put the
# keys in fewer columns, so more rows than it counted. A key keeps its own
# height and the width of its words (no less than KEY_MIN_W), and the
# page's minimum height is set again from its layout after every reflow
# (fit_height), so no layout can squash a key below its words.
KEY_MIN_W = 64
# What the last page laid out reported (fit_height): the panel's facts in a
# call's answer (dock.after_call) and a live check in FreeCAD's console.
LAST_LAYOUT = {}


PAGE = "ScanRulerPage"


def page_qss(seen=None):
    """The ScanRuler panel's stylesheet for what was seen of the theme
    ({dark: True/False/None, window: '#rrggbb' or None}, theme.detect): no
    page background and no text colour, so FreeCAD's theme stylesheet paints
    the page, labels and keys (a palette read stayed near-black under
    FreeCAD Light and Studio Light on the Mac); translucent cards; CNC
    Kitchen blue only on primary keys and links. The dock sets and refreshes
    it through theme.follow."""
    from .. import theme

    return theme.sheet(PAGE, theme.colours(seen, {}))


def head_row(s):
    """What the group's title row holds, in order: its title (Title Case),
    then its count and (i) key at the right, all on the one row; [] when
    there is nothing to show."""
    out = ["title"] if s.get("header") else []
    if s.get("info") or s.get("count") is not None:
        out.append("stretch")
        if s.get("count") is not None:
            out.append("count")
        if s.get("info"):
            out.append("info")
    return out


def columns_for(width, per, key_w=0):
    """How many columns a key grid of per columns gets in a page this wide;
    key_w (its widest key's natural width): no more columns than fit whole
    keys, so no label is cut ("Delete Fac" in a 350 px panel)."""
    per = max(1, int(per or 1))
    cols = min(per, 2) if 0 < width < NARROW else per
    if key_w > 0 and width > 0:
        # The page's and the group's margins and a scroll bar's width.
        room = width - 2 * MARGIN - GROUP_MARGINS[0] - GROUP_MARGINS[2] - 16
        cols = min(cols, max(1, int((room + SPACING) // (key_w + SPACING))))
    return cols


def stacked(width):
    """Whether a label stacks above its button or box in a page this wide."""
    return 0 < width < NARROW


def reflow(width, grids, rows, down, across, fields=()):
    """Lay the page out for width: each grid [layout, buttons, per, cols]
    re-placed when its column count changes; each row (a QBoxLayout) set to
    down (stacked) or across; each field row the same under FIELD_NARROW.
    What changed: (grids, rows)."""
    g = r = 0
    for item in grids:
        lay, buttons, per = item[0], item[1], item[2]
        key_w = 0
        for b in buttons:
            try:
                key_w = max(key_w, b.sizeHint().width())
            except Exception:  # noqa: BLE001 — a stand-in without a size
                pass
        cols = columns_for(width, per, key_w)
        if cols != item[3]:
            for b in buttons:
                lay.removeWidget(b)
            for i, b in enumerate(buttons):
                lay.addWidget(b, i // cols, i % cols)
            item[3] = cols
            g += 1
    for group, narrow in ((rows, stacked(width)), (fields, 0 < width < FIELD_NARROW)):
        want = down if narrow else across
        for row in group:
            if row.direction() != want:
                row.setDirection(want)
                r += 1
    return g, r


def key_size(b):
    """A key that keeps its words: its minimum width the words' (at least
    KEY_MIN_W), its height its own and fixed (no layout squashes it)."""
    from PySide import QtWidgets

    hint = b.sizeHint()
    b.setMinimumWidth(max(KEY_MIN_W, int(hint.width())))
    b.setMinimumHeight(int(hint.height()))
    p = b.sizePolicy()
    b.setSizePolicy(p.horizontalPolicy(), QtWidgets.QSizePolicy.Fixed)
    return b


def squashed(buttons):
    """How many of the keys are drawn lower or narrower than their words
    need (height under the size hint's, width under the minimum)."""
    n = 0
    for b in buttons:
        try:
            if b.isVisible() and (b.height() < b.sizeHint().height() or b.width() < b.minimumWidth()):
                n += 1
        except Exception:  # noqa: BLE001 — a key gone meanwhile
            continue
    return n


# --- the page's account, from its real geometry (round 9) ----------------------
# Window round 8 (r8sr-1/2, a 332 px dock at device pixel ratio 2): the
# Create Element keys lay over each other (rows 11 px apart, keys 22 px
# high) and the Scanner Profiles box covered its help text, while the
# account read squashed 0. A key kept its own height (its minimum), so it
# was never lower than its words: its card was. The card's height came
# from the page's height for its width, reckoned with the grid in four
# columns and the field row across — before reflow put them in two
# columns and stacked the row. Qt re-reckons a card only on a later turn
# of its loop (a grid's change marks the layouts above it "not active",
# not their cached heights), and the page was drawn again on every call.
# Now settle() reflows, drops every cached height, sets the page's
# minimum height from the fresh account and lays the cards out at once;
# the account then reads the geometry: a key or box under its size hint,
# a wrapped text cut short, and siblings that overlap.


def grid_rows(n, cols):
    """How many rows n keys take in cols columns."""
    cols = max(1, int(cols or 1))
    return (int(n) + cols - 1) // cols if n else 0


def grid_height(n, cols, key_h, spacing=SPACING):
    """The height a key grid needs: its rows of keys key_h high, spacing
    between them."""
    rows = grid_rows(n, cols)
    return rows * int(key_h) + max(0, rows - 1) * int(spacing) if rows else 0


def overlap(a, b):
    """Whether two rectangles (x, y, w, h) in one parent's coordinates
    share any area (touching edges do not)."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return min(ax + aw, bx + bw) > max(ax, bx) and min(ay + ah, by + bh) > max(ay, by)


def overlapping(items):
    """The pairs of items that overlap: items are (name, parent, rect),
    rect (x, y, w, h) in its parent's coordinates; only siblings (the same
    parent) are compared — a card holds its keys. A pair is (name, name)."""
    by_parent = {}
    for name, parent, rect in items:
        if rect[2] > 0 and rect[3] > 0:
            by_parent.setdefault(id(parent), []).append((name, rect))
    out = []
    for group in by_parent.values():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                if overlap(group[i][1], group[j][1]):
                    out.append((group[i][0], group[j][0]))
    return out


def short_of(size, need):
    """Whether a widget size (w, h) is under what it needs (w, h); a need of
    None or under 0 on an axis is not checked."""
    return any(n is not None and n >= 0 and s < n for s, n in zip(size, need))


def _own(obj, name, default=None):
    """An attribute set on this very object (a page's own lists), not one a
    stand-in makes up on reading."""
    try:
        return vars(obj).get(name, default)
    except TypeError:
        return getattr(obj, name, default)


def _rect(w):
    g = w.geometry()
    return (int(g.x()), int(g.y()), int(g.width()), int(g.height()))


def _shown(w, root):
    try:
        return bool(w.isVisibleTo(root)) if w is not root else True
    except Exception:  # noqa: BLE001 — a stand-in, or a widget gone
        try:
            return bool(w.isVisible())
        except Exception:  # noqa: BLE001
            return False


def _name(w):
    for get in ("text", "accessibleName", "objectName"):
        try:
            t = getattr(w, get)()
            if isinstance(t, str) and t:
                return t[:24]
        except Exception:  # noqa: BLE001
            continue
    return type(w).__name__


def measure(root):
    """The page's account from its geometry as laid out now (settle runs
    the layout first): keys (and boxes) under their size hint, wrapped
    texts cut, and overlapping siblings. Duck-typed: no Qt import."""
    keys = [b for grid in _own(root, "_grids", []) for b in grid[1]]
    laid = list(_own(root, "_laid", ()))
    seen, items, low, cut = set(), [], 0, 0
    for w, kind in laid:
        if id(w) in seen or not _shown(w, root):
            continue
        seen.add(id(w))
        try:
            r = _rect(w)
            items.append((_name(w), w.parentWidget(), r))
            if kind in ("key", "field"):
                h = w.sizeHint()
                if short_of((r[2], r[3]), (int(h.width()) if kind == "key" else -1, int(h.height()))):
                    low += 1
            elif kind == "text" and w.wordWrap() and r[2] > 0:
                if r[3] < int(w.heightForWidth(r[2])):
                    cut += 1
        except Exception:  # noqa: BLE001 — a widget gone meanwhile
            continue
    if not laid:  # a page drawn before round 9's register: the keys alone
        low = squashed(keys)
    pairs = overlapping(items)
    return {"keys": len(keys), "squashed": low, "clipped": cut, "overlapping": len(pairs),
            "overlaps": [list(p) for p in pairs[:3]]}


def settle(root, width=None):
    """Lay the page out now for width (its own by default), not on later
    turns of Qt's loop: keys sized from their size hints (as polished in
    the page), grids and rows reflowed, every cached height dropped, the
    page's minimum height set from the fresh account (the scroll area
    scrolls rather than squash), the page and its cards laid out, then the
    account read from the geometry (measure). Returns it (also LAST_LAYOUT)."""
    if _own(root, "_settling", False):
        return dict(LAST_LAYOUT)
    root._settling = True
    try:
        w = int(width if width else root.width())
        for grid in _own(root, "_grids", []):
            for b in grid[1]:
                key_size(b)
        for b, kind in _own(root, "_laid", ()):
            if kind == "key" and not any(b is k for g in _own(root, "_grids", []) for k in g[1]):
                key_size(b)
        f = _own(root, "_reflow_now", None)
        if f is not None:
            f(w)
        lay = root.layout()
        cards = list(_own(root, "_cards", ()))
        # Every cached height dropped: the rows' and grids' layouts, each
        # card's (its own top layout) and the page's items (activate
        # clears them; a card's updateGeometry its item's cache).
        for sub in _own(root, "_layouts", ()):
            sub.invalidate()
        for card in cards:
            cl = card.layout()
            if cl is not None:
                cl.invalidate()
            card.updateGeometry()
        lay.invalidate()
        lay.activate()
        need = lay.totalHeightForWidth(w) if lay.hasHeightForWidth() else -1
        need = max(int(need), int(lay.totalMinimumSize().height()))
        if root.minimumHeight() != need:
            root.setMinimumHeight(need)
        if int(root.height()) < need or (width and int(root.width()) != w):
            root.resize(w, max(int(root.height()), need))
        # Laid out at the page's size now, then each card inside (a parent
        # card before the cards it holds).
        lay.invalidate()
        lay.activate()
        for card in cards:
            cl = card.layout()
            if cl is not None:
                cl.activate()
        out = {"width": w, "minHeight": need, "height": int(root.height()),
               "columns": [grid[3] for grid in _own(root, "_grids", [])]}
        out.update(measure(root))
        LAST_LAYOUT.clear()
        LAST_LAYOUT.update(out)
        return out
    finally:
        root._settling = False


def fit_height(root, width=None):
    """The page's minimum height set to what its layout needs at its width
    now (after reflow), so the scroll area cannot give it less. Returns
    the layout's account (also LAST_LAYOUT). A page drawn by widget() is
    settled instead (settle: laid out at once, read from its geometry)."""
    if _own(root, "_reflow_now") is not None:
        return settle(root, width)
    lay = root.layout()
    w = int(width if width is not None else root.width())
    lay.activate()
    need = lay.totalHeightForWidth(w) if lay.hasHeightForWidth() else -1
    need = max(int(need), int(lay.totalMinimumSize().height()))
    if root.minimumHeight() != need:
        root.setMinimumHeight(need)
    keys = [b for grid in getattr(root, "_grids", []) for b in grid[1]]
    out = {"width": w, "minHeight": need, "height": int(root.height()), "keys": len(keys), "squashed": squashed(keys),
           "columns": [grid[3] for grid in getattr(root, "_grids", [])]}
    LAST_LAYOUT.clear()
    LAST_LAYOUT.update(out)
    return out


def section_object_name(section_id):
    """The Qt object name of a section's card (a QFrame)."""
    return f"ScanRulerSection_{section_id}"


def widget(model, on_key=None, on_field=None, parent=None):
    """A QWidget drawn from any page model (every page's, 3D Measure's too):
    a card (QFrame) per section titled as FreeCAD titles them, with an (i) key,
    slots, rows, fields of every kind, keys in their grid and hints. The
    credit is the dock's footer, once (dock.Dock), not each page's.
    on_key(section_id, key_id); on_field(section_id, field_id, value)."""
    import math

    from PySide import QtCore, QtWidgets

    if QtWidgets.QApplication.instance() is None:
        # A widget with no application aborts real FreeCAD's Qt: refuse first.
        raise RuntimeError("A ScanRuler page widget needs a QApplication (FreeCAD's GUI).")
    root = QtWidgets.QWidget(parent)
    lay = QtWidgets.QVBoxLayout(root)
    lay.setSpacing(SPACING)
    lay.setContentsMargins(MARGIN, MARGIN, MARGIN, MARGIN)
    # The page follows its panel's width (never wider): grids and rows
    # reflow on each resize (reflow), long labels wrap.
    root.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
    root.setMinimumWidth(0)
    grids, rows, fields = [], [], []
    # What settle and measure read: each laid-out widget with its kind
    # (key, field, text, card), the cards' and the rows' layouts.
    laid, layouts, cards = [], [], []

    def put(w, kind):
        laid.append((w, kind))
        return w

    def info_button(title, paras):
        dot = QtWidgets.QToolButton()
        dot.setText("i")
        dot.setFixedSize(14, 14)
        text = "<p><b>%s</b></p>" % title + "".join("<p>%s</p>" % p for p in paras or ())
        dot.setToolTip(text)
        dot.clicked.connect(lambda _=False, t=text, d=dot: QtWidgets.QToolTip.showText(d.mapToGlobal(QtCore.QPoint(0, 14)), t, d))
        return dot

    def header(s, box):
        """The group's title row: its title, then its count and (i) key."""
        parts = head_row(s)
        if not parts:
            return
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(SPACING)
        for part in parts:
            if part == "title":
                t = QtWidgets.QLabel("<b>%s</b>" % group_title(s))
                t.setWordWrap(True)
                row.addWidget(t, 1)
            elif part == "stretch":
                row.addStretch(1 if "title" not in parts else 0)
            elif part == "count":
                row.addWidget(label(str(s["count"])))
            else:
                row.addWidget(info_button(s["info"], s["info_text"]))
        layouts.append(row)
        box.addLayout(row)

    def emit(sid, fid, v):
        if on_field:
            on_field(sid, fid, v)

    def label(text):
        lab = QtWidgets.QLabel(text)
        lab.setWordWrap(True)
        return put(lab, "text")

    def field(s, fd, box):
        row = QtWidgets.QHBoxLayout()
        k = fd.get("kind", "select")
        if k == "check":
            long_ = len(fd["label"]) > LONG_CHECK
            # A long label wraps beside its box (a check box's own text
            # cannot), and a click on it ticks the box.
            w = QtWidgets.QCheckBox("" if long_ else fd["label"])
            w.setChecked(fd["value"])
            w.toggled.connect(lambda v, sid=s["id"], fid=fd["id"]: emit(sid, fid, bool(v)))
            row.addWidget(w)
            if long_:
                lab = label(fd["label"])
                lab.mousePressEvent = lambda _e, w=w: w.isEnabled() and w.toggle()
                row.addWidget(lab, 1)
        else:
            if fd["label"]:
                row.addWidget(label(fd["label"]), 1)
                fields.append(row)
            # No label (Scanner Profiles' box): the box has the whole row,
            # and no empty row stacks above it in a narrow panel.
            if k == "select":
                w = QtWidgets.QComboBox()
                w.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
                w.setMinimumContentsLength(8)
                vals = [o["value"] for o in fd["options"]]
                for o in fd["options"]:
                    w.addItem(o["label"], o["value"])
                w.setCurrentIndex(vals.index(fd["value"]) if fd["value"] in vals else 0)
                w.currentIndexChanged.connect(lambda i, sid=s["id"], fid=fd["id"], vals=vals: emit(sid, fid, vals[i]))
            elif k == "number":
                if fd.get("integer"):
                    w = QtWidgets.QSpinBox()
                    w.setRange(int(fd["min"]) if fd["min"] is not None else 0, 2**31 - 1)
                    w.setValue(int(fd["value"] or 0))
                else:
                    w = QtWidgets.QDoubleSpinBox()
                    w.setDecimals(3)
                    w.setRange(fd["min"] if fd["min"] is not None else -1e9, 1e9)
                    w.setValue(float(fd["value"] or 0))
                if fd["unit"]:
                    w.setSuffix(" " + fd["unit"] if fd["unit"] != "×" else "×")
                if fd["hint"]:
                    w.setToolTip(fd["hint"])
                w.editingFinished.connect(lambda sid=s["id"], fid=fd["id"], w=w: emit(sid, fid, w.value()))
            elif k == "slider":
                w = QtWidgets.QSlider(QtCore.Qt.Horizontal)
                w.setRange(0, 1000)
                lo, hi, v = fd["min"], fd["max"], fd["value"]
                if fd["log"]:
                    lo, hi, v = math.log10(lo), math.log10(hi), math.log10(max(v, 1e-12))
                w.setValue(int(round(1000 * (v - lo) / ((hi - lo) or 1))))

                def moved(i, sid=s["id"], fid=fd["id"], lo=lo, hi=hi, lg=fd["log"]):
                    x = lo + (hi - lo) * i / 1000
                    emit(sid, fid, float("%.2g" % (10 ** x)) if lg else x)

                w.valueChanged.connect(moved)
            else:  # toggle
                w = QtWidgets.QWidget()
                tl = QtWidgets.QHBoxLayout(w)
                tl.setContentsMargins(0, 0, 0, 0)
                group = QtWidgets.QButtonGroup(w)
                group.setExclusive(True)
                for o in fd["options"]:
                    b = QtWidgets.QPushButton(button_text(o["label"]))
                    b.setCheckable(True)
                    b.setChecked(o["value"] == fd["value"])
                    b.setToolTip(o["tip"])
                    b.clicked.connect(lambda _=False, sid=s["id"], fid=fd["id"], v=o["value"]: emit(sid, fid, v))
                    key_size(b)
                    put(b, "key")
                    group.addButton(b)
                    tl.addWidget(b)
                layouts.append(tl)
            row.addWidget(w, 0 if fd["label"] else 1)
        put(w, "field")
        w.setEnabled(fd["enabled"])
        if fd.get("info"):
            row.addWidget(info_button(fd["info"], fd["info_text"]))
        layouts.append(row)
        box.addLayout(row)

    def keys(s, box):
        grid = QtWidgets.QGridLayout()
        # The spacing columns_for counts (a style's own can be wider).
        grid.setSpacing(SPACING)
        per = s.get("grid") or 1
        made = []
        for i, k in enumerate(s["keys"]):
            b = QtWidgets.QPushButton(button_text(k["label"]))
            b.setToolTip(k["tip"])
            b.setEnabled(k["enabled"])
            b.setCheckable(k["pressed"])
            b.setChecked(k["pressed"])
            if k.get("primary"):
                # The accent from the page's stylesheet (page_qss), so a
                # disabled primary key still reads as disabled.
                b.setProperty("primary", True)
            if on_key:
                b.clicked.connect(lambda _=False, sid=s["id"], kid=k["id"]: on_key(sid, kid))
            key_size(b)
            put(b, "key")
            grid.addWidget(b, i // per, i % per)
            made.append(b)
        grids.append([grid, made, per, per])
        layouts.append(grid)
        box.addLayout(grid)

    def section_w(s, box):
        if not s["visible"]:
            return
        if s.get("header"):
            # The title on the group's own first row, with its (i) key (a
            # group box's title cannot hold a key): no row of its own.
            # A plain QFrame, not a QGroupBox: under FreeCAD's theme sheets a
            # group box reserves its title band (margin-top / padding-top and
            # ::title) even with no title, 20 px above the header on the Mac.
            group = QtWidgets.QFrame()
            group.setObjectName(section_object_name(s["id"]))  # the dock finds a box just opened by it
            group.setProperty(CARD, True)  # the card rule in the page's sheet (theme.sheet)
            group.setAccessibleName(group_title(s))
            box.addWidget(group)
            put(group, "card")
            cards.append(group)
            box = QtWidgets.QVBoxLayout(group)
            box.setSpacing(SPACING)
            box.setContentsMargins(*GROUP_MARGINS)
        header(s, box)
        for sl in s.get("slots") or ([s["slot"]] if s.get("slot") else []):
            if not isinstance(sl, dict):
                # GD&T's "slots" are the names a tolerance takes (Feature,
                # Datum …), not slot rows: 3D Measure failed to open on them.
                continue
            row = QtWidgets.QHBoxLayout()
            row.addWidget(label("<span style='color:%s'>●</span> <b>%s</b><br>%s" % (sl["dot"], sl["name"], sl["detail"])), 1)
            rows.append(row)
            b = QtWidgets.QPushButton(button_text(sl["button"]["label"]))
            b.setToolTip(sl["button"].get("tip") or "")
            b.setEnabled(sl["button"]["enabled"])
            if on_key:
                b.clicked.connect(lambda _=False, kid=sl["button"]["id"]: on_key(s["id"], kid))
            key_size(b)
            put(b, "key")
            row.addWidget(b)
            layouts.append(row)
            box.addLayout(row)
        for r in s["rows"]:
            reading = r.get("reading") or r.get("value") or ""
            box.addWidget(label("<span style='color:%s'>●</span> %s  <b>%s</b>" % (r.get("color", SCAN_DOT), r["name"], reading)))
        for fd in s["fields"]:
            field(s, fd, box)
        keys(s, box)
        if s.get("hint"):
            # Its own row under the keys and boxes, wrapped, never lower
            # than its lines (settle counts it in the page's height).
            h = QtWidgets.QLabel(s["hint"])
            h.setWordWrap(True)
            h.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Minimum)
            box.addWidget(put(h, "text"))
        for c in s.get("children", []):
            section_w(c, box)

    for s in model["sections"]:
        section_w(s, lay)
    lay.addStretch(1)
    down, across = QtWidgets.QBoxLayout.TopToBottom, QtWidgets.QBoxLayout.LeftToRight

    class Reflow(QtCore.QObject):
        def eventFilter(self, obj, ev):  # noqa: N802 (Qt)
            if ev.type() == QtCore.QEvent.Resize and not _own(obj, "_settling", False):
                # At once (settle), not on a later turn: the window picture
                # of the same call shows it laid out. Once more on the next
                # turn for what the theme's polish changes after.
                _settle_now(obj)
                QtCore.QTimer.singleShot(0, lambda o=obj: _settle_now(o))
            return False

    def _settle_now(o):
        try:
            settle(o)
        except RuntimeError:  # the page went meanwhile (a refresh)
            pass

    root._grids = grids
    root._laid, root._layouts, root._cards = laid, layouts, cards
    root._reflow_now = lambda w: reflow(w, grids, rows, down, across, fields)
    root._reflow = Reflow(root)  # kept with its page
    root.installEventFilter(root._reflow)
    return root
