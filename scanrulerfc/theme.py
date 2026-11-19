# SPDX-License-Identifier: AGPL-3.0-only
# The ScanRuler panel's look under the active FreeCAD theme: its own copy of
# the add-ons' theme rule (no shared import).
#
# The theme paints the panel. FreeCAD Light, Studio Light and FreeCAD Dark
# change the look through a stylesheet, not through QPalette: on the Mac the
# palette stays the system's dark one under a light theme, so a colour read
# from palette() (or palette(...) in a sheet) left the page near-black while
# every other dock was light. So the sheet sets no page background and no
# text colour: the page is transparent over what the theme paints behind it,
# labels and keys take the theme's text and QPushButton style. Section cards
# are a translucent overlay with a translucent mid-grey border, which reads
# as a card on light and dark alike.
#
# Where light or dark matters (the card's overlay, CNC Kitchen blue as a fill
# or an outline, the link tint), it is detected from what the theme actually
# rendered: the first ancestor of the panel that paints an opaque pixel of
# its own (QWidget.render without children), else the stylesheet name in
# BaseApp/Preferences/MainWindow/StyleSheet, else unknown (theme-neutral
# overlay; the palette is never trusted for it). CNC Kitchen blue (#1877c0,
# Stefan Hermann's ScanRuler accent) stays on primary keys and links. Styles
# only the panel (by object name), never QApplication.

from . import workspaces as W

PARAM = "User parameter:BaseApp/Preferences/Themes"
STYLE_PARAM = "User parameter:BaseApp/Preferences/MainWindow"
OK, WARN, BAD = "#2e7d46", "#c98a00", "#b3361c"  # read on light and dark surfaces
TEXT_MIN = 4.5  # WCAG AA for body text
DISABLED_MIN = 1.6  # still legible, plainly dimmer than an enabled key

# Theme-neutral pieces: a mid grey reads against near-white and near-black.
BORDER = "rgba(127, 127, 127, 0.35)"
CARD = {None: "rgba(127, 127, 127, 0.08)",   # light or dark not known
        True: "rgba(255, 255, 255, 0.06)",   # dark: 6% toward white, the card as it was (425b61c)
        False: "rgba(0, 0, 0, 0.035)"}       # light: 3.5% toward black, as it was
DISABLED_TEXT = "rgba(127, 127, 127, 0.85)"
DISABLED_BORDER = "rgba(127, 127, 127, 0.25)"
DOT_BORDER = "rgba(127, 127, 127, 0.6)"
# What CARD composites to, for the link's contrast check.
CARD_OVER = {None: ("#7f7f7f", 0.08), True: ("#ffffff", 0.06), False: ("#000000", 0.035)}


# --- colour maths (pure) --------------------------------------------------------

def rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def hexof(c):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(v)))) for v in c)


def luminance(h):
    def ch(v):
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (ch(v) for v in rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def mix(a, b, t):
    """a moved t of the way to b."""
    return hexof(x + (y - x) * t for x, y in zip(rgb(a), rgb(b)))


def over(rgba, bg):
    """'rgba(r, g, b, a)' composited on bg (#rrggbb)."""
    r, g, b, a = (float(v) for v in rgba[rgba.index("(") + 1:rgba.index(")")].split(","))
    return mix(bg, hexof((r, g, b)), a)


def is_dark(h):
    return luminance(h) < 0.18


def readable(fg, bg, need=TEXT_MIN):
    """fg if it reads on bg, else fg pushed toward black or white until it does."""
    if contrast(fg, bg) >= need:
        return fg
    end = "#ffffff" if is_dark(bg) else "#000000"
    for i in range(1, 21):
        c = mix(fg, end, i / 20)
        if contrast(c, bg) >= need:
            return c
    return end


def text_on(colour, seen=None, need=TEXT_MIN):
    """colour made readable on what the theme shows behind the panel (seen:
    theme.detect's answer; the card's colour when known, else the window's).
    A light or dark theme that is not known: colour as it is. A status
    colour (red, green) keeps its hue, only lighter on dark, darker on light."""
    c = colours(seen)
    bg = c.get("card") or c.get("window")
    return readable(colour, bg, need) if bg else colour


# --- the theme accent (FreeCAD parameter) -----------------------------------------

def _hex_param(v):
    """FreeCAD stores a colour as unsigned 0xRRGGBBAA; 0 means unset."""
    if not isinstance(v, int) or isinstance(v, bool) or v <= 0:
        return None
    return "#%06x" % ((v >> 8) & 0xFFFFFF)


def accents(params=None):
    """[accent1, accent2, accent3] as #rrggbb, None where unset. params: a
    ParameterGrp (default FreeCAD's) or a dict {name: unsigned int}."""
    if params is None:
        try:
            import FreeCAD

            params = FreeCAD.ParamGet(PARAM)
        except ImportError:
            return [None, None, None]
    out = []
    for i in (1, 2, 3):
        name = f"ThemeAccentColor{i}"
        v = params.get(name) if isinstance(params, dict) else params.GetUnsigned(name, 0)
        out.append(_hex_param(v))
    return out


# --- light or dark (pure parts) ----------------------------------------------------

def dark_by_name(name):
    """True/False from a stylesheet or preference pack name that says Dark or
    Light, else None."""
    n = (name or "").lower()
    if "dark" in n and "light" not in n:
        return True
    if "light" in n and "dark" not in n:
        return False
    return None


def seen_from(window=None, name=None):
    """{dark, window, via}: a rendered window colour wins, then a name."""
    if isinstance(window, str) and len(window) == 7 and window[0] == "#":
        return {"dark": is_dark(window), "window": window, "via": "render"}
    d = dark_by_name(name)
    return {"dark": d, "window": None, "via": "name" if d is not None else None}


def colours(seen=None, params=None):
    """What the sheet needs, from what was seen of the theme ({dark: True,
    False or None, window: '#rrggbb' or None}; seen_from / detect). Only the
    card's overlay, the primary key's treatment and the link tint depend on
    light or dark; nothing is a background or text colour read from a palette."""
    seen = seen or {}
    dark = seen.get("dark")
    dark = dark if dark in (True, False) else None
    window = seen.get("window") or {True: "#2b2b2b", False: "#efefef", None: None}[dark]
    a = accents(params)
    theme_accent = a[0] or W.ACCENT
    if dark:
        card = mix(window, *CARD_OVER[True])
        link = readable(W.ACCENT, card)  # lightened only as far as a link needs
    else:
        card = mix(window, *CARD_OVER[dark]) if window else None
        # #1877c0 reads at 4.7:1 on white; on a known light card it is
        # darkened only as far as 4.5:1 needs.
        link = readable(W.ACCENT, card) if card and dark is False else W.ACCENT
    return {"dark": dark, "window": window, "card_bg": CARD[dark], "card": card, "border": BORDER,
            "disabled_text": DISABLED_TEXT, "disabled_border": DISABLED_BORDER, "dot_border": DOT_BORDER,
            "primary": W.ACCENT, "primary_text": readable("#ffffff", W.ACCENT),
            "link": link, "accent": theme_accent, "ok": OK, "warn": WARN, "bad": BAD}


def sheet(name, c):
    """The panel's stylesheet: the widget named name and what is in it, only.
    No background on the page and no text colour anywhere but links, the
    (i) dots' hover and disabled text: the theme's stylesheet paints those."""
    p = f"#{name}"
    lines = [
        # Containers see through to the theme's own painting behind the panel
        # (a scroll area's viewport would otherwise fill from the palette).
        f"{p} QStackedWidget, {p} QScrollArea, {p} QScrollArea > QWidget, {p} QScrollArea > QWidget > QWidget"
        " { background: transparent; }",
        # Section cards are QFrames marked card="true" (pages/kit.py), not
        # QGroupBoxes: FreeCAD's theme sheets make a group box reserve a
        # title band even with no title. The card's inner spacing is its
        # layout's contents margins alone (kit.GROUP_MARGINS), so the caps
        # header sits at the card's top edge.
        f"{p} QFrame[card=\"true\"] {{ background: {c['card_bg']}; border: 1px solid {c['border']};"
        " border-radius: 4px; margin: 0px; padding: 0px; }",
        f"{p} QLabel {{ background: transparent; }}",
        f"{p} QLabel:disabled {{ color: {c['disabled_text']}; }}",
        # Keys: the theme's QPushButton style; only a checked, hovered or
        # disabled key is marked, and the primary key in CNC Kitchen blue.
        f"{p} QPushButton:hover {{ border-color: {c['accent']}; }}",
        f"{p} QPushButton:checked {{ border: 1px solid {c['accent']}; }}",
        f"{p} QPushButton:disabled {{ color: {c['disabled_text']}; border-color: {c['disabled_border']}; }}",
    ]
    if c["dark"]:
        # Dark themes as before: the blue key with white text.
        lines.append(f"{p} QPushButton[primary=\"true\"]:enabled {{ background: {c['primary']}; color: {c['primary_text']};"
                     f" border: 1px solid {c['primary']}; }}")
    else:
        # Light or unknown: a blue outline on the theme's own key.
        lines.append(f"{p} QPushButton[primary=\"true\"]:enabled {{ border: 1px solid {c['primary']}; }}")
    lines += [
        f"{p} QToolButton {{ background: transparent; border: 1px solid {c['dot_border']}; border-radius: 7px;"
        " font-size: 9px; font-weight: bold; }",
        f"{p} QToolButton:hover {{ color: {c['link']}; border-color: {c['link']}; }}",
        f"{p} a {{ color: {c['link']}; }}",
    ]
    return "\n".join(lines)


# --- Qt --------------------------------------------------------------------------

def _no_flags(QtWidgets):
    """QWidget.RenderFlags() with nothing set (no children, no window
    background): only what a widget paints of its own."""
    W_ = QtWidgets.QWidget
    rf = getattr(W_, "RenderFlag", None)
    if rf is not None:
        try:
            return rf(0)
        except Exception:  # noqa: BLE001 — PySide2's RenderFlags
            pass
    return W_.RenderFlags()


def painted(widget):
    """'#rrggbb' of the pixel widget paints of its own at its centre (its
    stylesheet background, its paintEvent; no children, no palette window
    fill), or None where it paints nothing opaque there."""
    from PySide import QtCore, QtGui, QtWidgets

    r = widget.rect()
    if r.width() < 1 or r.height() < 1:
        return None
    img = QtGui.QImage(1, 1, QtGui.QImage.Format_ARGB32)
    img.fill(QtCore.Qt.transparent)
    x, y = r.width() // 2, r.height() // 2
    widget.render(img, QtCore.QPoint(0, 0), QtGui.QRegion(x, y, 1, 1), _no_flags(QtWidgets))
    col = img.pixelColor(0, 0)
    return col.name() if col.alpha() == 255 else None


def ancestors(widget):
    """The panel's ancestors, nearest first, ending at FreeCAD's main window."""
    out, p = [], None
    try:
        p = widget.parentWidget()
    except Exception:  # noqa: BLE001 — a stand-in
        p = None
    while p is not None:
        out.append(p)
        p = p.parentWidget()
    try:
        import FreeCADGui

        mw = FreeCADGui.getMainWindow()
        if mw is not None and all(mw is not a for a in out):
            out.append(mw)
    except Exception:  # noqa: BLE001 — no GUI
        pass
    return out


def style_name():
    try:
        import FreeCAD

        return FreeCAD.ParamGet(STYLE_PARAM).GetString("StyleSheet", "")
    except Exception:  # noqa: BLE001 — no FreeCAD
        return ""


def detect(widget):
    """{dark, window, via}: the colour the theme renders behind the panel
    (the nearest ancestor that paints an opaque pixel of its own), else the
    stylesheet's name, else unknown."""
    for a in ancestors(widget):
        try:
            c = painted(a)
        except Exception:  # noqa: BLE001 — cannot render (closed, stand-in)
            c = None
        if c:
            return seen_from(window=c)
    return seen_from(name=style_name())


def apply(widget, params=None):
    """Style widget (by object name) for the theme; call again on
    PaletteChange or StyleChange. True if the sheet changed."""
    # setStyleSheet sends the widget a change of its own: a change met while
    # applying is ignored and an unchanged sheet is not set again
    # (Texturizer's GUI pass saw FreeCAD crash on the recursion).
    if getattr(widget, "_scanruler_styling", False):
        return False
    try:
        seen = detect(widget)
    except Exception:  # noqa: BLE001 — nothing to see
        seen = None
    widget._scanruler_seen = seen
    css = sheet(str(widget.objectName()), colours(seen, params))
    if css == widget.styleSheet():
        return False
    widget._scanruler_styling = True
    try:
        widget.setStyleSheet(css)
    finally:
        widget._scanruler_styling = False
    return True


def follow(widget, params=None):
    """Style widget now and again whenever the theme changes (PaletteChange
    or StyleChange, or the panel moved into another dock or tab), a turn of
    the event loop later so its parent is re-polished first. The filter is
    kept on the widget."""
    from PySide import QtCore

    def restyle():
        try:
            apply(widget, params)
        except RuntimeError:  # the panel was closed before the turn came
            pass

    class _Follow(QtCore.QObject):
        def eventFilter(self, obj, ev):  # noqa: N802 (Qt)
            if ev.type() in (QtCore.QEvent.PaletteChange, QtCore.QEvent.StyleChange, QtCore.QEvent.ParentChange):
                if not getattr(widget, "_scanruler_styling", False):
                    QtCore.QTimer.singleShot(0, restyle)
            return False

    widget._scanruler_theme = _Follow(widget)
    widget.installEventFilter(widget._scanruler_theme)
    apply(widget, params)
    return widget._scanruler_theme


def mute(widget, opacity=0.65):
    """Secondary text: the theme's own text colour, drawn see-through (a
    QGraphicsOpacityEffect; a sheet cannot fade an inherited colour)."""
    from PySide import QtWidgets

    eff = QtWidgets.QGraphicsOpacityEffect(widget)
    eff.setOpacity(opacity)
    widget.setGraphicsEffect(eff)
    return eff
