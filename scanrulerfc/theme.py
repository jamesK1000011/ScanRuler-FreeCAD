# SPDX-License-Identifier: AGPL-3.0-only
# The ScanRuler panel's colours, from the active FreeCAD theme: its own copy
# of the add-ons' theme rule (no shared import). Text and surfaces come from
# the palette of the widget the panel stands in (its dock or Agent Link's
# tab, which FreeCAD's theme stylesheet has polished); the theme accent from
# User parameter:BaseApp/Preferences/Themes ThemeAccentColor1..3, else the
# palette's highlight; CNC Kitchen blue (#1877c0, Stefan Hermann's ScanRuler
# accent) stays on primary keys and links. Concrete colours, never
# palette(...) in the sheet: Qt resolves those against the application's
# palette, which on the Mac is not the light theme's (the panel stayed a
# near-black slab with grey key text in FreeCAD Light and Studio Light).
# Styles only the panel (by object name), never QApplication.

from . import workspaces as W

PARAM = "User parameter:BaseApp/Preferences/Themes"
OK, WARN, BAD = "#2e7d46", "#c98a00", "#b3361c"  # read on light and dark surfaces
ROLES = ("window", "window_text", "base", "text", "button", "button_text", "highlight", "mid",
         "disabled_button_text", "disabled_window_text")
TEXT_MIN = 4.5  # WCAG AA for body text
DISABLED_MIN = 1.6  # still legible, plainly dimmer than an enabled key


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


def is_dark(h):
    return luminance(h) < 0.18


def readable(fg, bg, need=TEXT_MIN, snap=False):
    """fg if it reads on bg, else fg pushed toward black or white until it
    does; snap: straight to the theme's plain ink instead (a palette whose
    text fails its own window is not the theme's: grey keys read disabled)."""
    if contrast(fg, bg) >= need:
        return fg
    end = "#ffffff" if is_dark(bg) else "#000000"
    if snap:
        ink = "#f0f0f0" if is_dark(bg) else "#1a1a1a"
        return ink if contrast(ink, bg) >= need else end
    for i in range(1, 21):
        c = mix(fg, end, i / 20)
        if contrast(c, bg) >= need:
            return c
    return end


def surface(window, dark_step=0.06, light_step=0.035):
    """A card a shade off the window: lighter in a dark theme, darker in a light one."""
    return mix(window, "#ffffff", dark_step) if is_dark(window) else mix(window, "#000000", light_step)


def dim(fg, bg, given=None):
    """A disabled key's text: the palette's Disabled colour when it reads as
    dimmer yet legible, else fg half way to bg."""
    full = contrast(fg, bg)
    if given and DISABLED_MIN <= contrast(given, bg) < full * 0.75:
        return given
    for t in (0.5, 0.4, 0.6, 0.3):
        c = mix(fg, bg, t)
        if DISABLED_MIN <= contrast(c, bg) < full * 0.75:
            return c
    return mix(fg, bg, 0.5)


# --- roles (pure) ----------------------------------------------------------------

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


def colours(pal, params=None):
    """Every colour the panel uses, from a palette as {role: '#rrggbb'}
    (ROLES; missing ones derived). Each text colour is checked against the
    surface it stands on, so a theme whose palette text does not read on its
    window (or a mismatched one) still gives readable labels and keys."""
    win = pal["window"]
    dark = is_dark(win)
    card = surface(win)
    text = readable(readable(pal.get("window_text") or ("#ffffff" if dark else "#000000"), card, snap=True), win, snap=True)
    page_text = readable(text, win, snap=True)
    button = pal.get("button")
    if not button or is_dark(button) != dark:  # a key the other way round from its window is not the theme's
        button = mix(card, "#ffffff", 0.06) if dark else mix(win, "#ffffff", 0.5)
    button_text = readable(pal.get("button_text") or text, button, snap=True)
    muted = mix(text, card, 0.4)
    if contrast(muted, card) < TEXT_MIN:
        muted = readable(muted, card)
    border = pal.get("mid") or mix(card, text, 0.25)
    if contrast(border, card) < 1.3:
        border = mix(card, text, 0.25)
    a = accents(params)
    theme_accent = a[0] or pal.get("highlight") or W.ACCENT
    link = readable(W.ACCENT, card)
    return {"dark": dark, "window": win, "card": card, "text": text, "page_text": page_text, "muted": muted,
            "border": border, "button": button, "button_text": button_text,
            "button_border": mix(button, button_text, 0.3),
            "disabled_button": mix(button, card, 0.5),
            "disabled_text": dim(button_text, mix(button, card, 0.5), pal.get("disabled_button_text")),
            "disabled_label": dim(text, card, pal.get("disabled_window_text")),
            "primary": W.ACCENT, "primary_text": readable("#ffffff", W.ACCENT),
            "link": link, "accent": theme_accent, "ok": OK, "warn": WARN, "bad": BAD}


def sheet(name, c):
    """The panel's stylesheet: the widget named name and what is in it, only."""
    p = f"#{name}"
    return "\n".join((
        f"{p}, {p} QStackedWidget, {p} QScrollArea, {p} QScrollArea > QWidget > QWidget"
        f" {{ background: {c['window']}; color: {c['page_text']}; }}",
        f"{p} QGroupBox {{ background: {c['card']}; color: {c['text']}; border: 1px solid {c['border']};"
        " border-radius: 4px; margin-top: 0px; }",
        f"{p} QLabel {{ background: transparent; color: {c['text']}; }}",
        f"{p} QLabel:disabled {{ color: {c['disabled_label']}; }}",
        f"{p} > QLabel {{ color: {c['page_text']}; }}",
        f"{p} QCheckBox {{ color: {c['text']}; }}",
        # Colours only: the theme keeps its own key shape (borders, radius, padding).
        f"{p} QPushButton {{ background: {c['button']}; color: {c['button_text']}; border-color: {c['button_border']}; }}",
        f"{p} QPushButton:hover {{ border-color: {c['accent']}; }}",
        f"{p} QPushButton:checked {{ border: 1px solid {c['accent']}; background: {mix(c['button'], c['accent'], 0.2)}; }}",
        f"{p} QPushButton:disabled {{ background: {c['disabled_button']}; color: {c['disabled_text']};"
        f" border-color: {mix(c['disabled_button'], c['disabled_text'], 0.25)}; }}",
        f"{p} QPushButton[primary=\"true\"] {{ background: {c['primary']}; color: {c['primary_text']}; border-color: {c['primary']}; }}",
        f"{p} QPushButton[primary=\"true\"]:disabled {{ background: {c['disabled_button']}; color: {c['disabled_text']};"
        f" border-color: {c['border']}; }}",
        f"{p} QToolButton {{ background: transparent; color: {c['muted']}; border: 1px solid {c['muted']}; border-radius: 7px;"
        " font-size: 9px; font-weight: bold; }",
        f"{p} QToolButton:hover {{ color: {c['link']}; border-color: {c['link']}; }}",
        f"{p} a {{ color: {c['link']}; }}",
    ))


# --- Qt --------------------------------------------------------------------------

# Used only when no palette can be read (a stand-in Qt): FreeCAD Dark's.
FALLBACK = {"window": "#2b2b2b", "window_text": "#dcdcdc", "button": "#3c3c3c", "button_text": "#e0e0e0"}


def _valid(pal):
    return isinstance(pal, dict) and all(isinstance(v, str) and len(v) == 7 and v[0] == "#" for v in pal.values())

def read_palette(widget):
    """{role: '#rrggbb'} from the palette of the widget the panel stands in
    (the theme polished it; the panel's own palette carries its own sheet),
    else FreeCAD's main window, else the widget's own."""
    from PySide import QtGui

    src = None
    try:
        src = widget.parentWidget()
    except Exception:  # noqa: BLE001 — a stand-in
        src = None
    if src is None:
        try:
            import FreeCADGui

            src = FreeCADGui.getMainWindow()
        except Exception:  # noqa: BLE001 — no GUI
            src = None
    pal = (src or widget).palette()
    P = QtGui.QPalette

    def c(role, group=None):
        r = getattr(P, role)
        col = pal.color(group, r) if group is not None else pal.color(r)
        return col.name()

    return {"window": c("Window"), "window_text": c("WindowText"), "base": c("Base"), "text": c("Text"),
            "button": c("Button"), "button_text": c("ButtonText"), "highlight": c("Highlight"), "mid": c("Mid"),
            "disabled_button_text": c("ButtonText", P.Disabled), "disabled_window_text": c("WindowText", P.Disabled)}


def apply(widget, params=None):
    """Style widget (by object name) from the theme; call again on
    PaletteChange or StyleChange. True if the sheet changed."""
    # setStyleSheet sends the widget a PaletteChange of its own: a change met
    # while applying is ignored and an unchanged sheet is not set again
    # (Texturizer's GUI pass saw FreeCAD crash on the recursion).
    if getattr(widget, "_scanruler_styling", False):
        return False
    try:
        pal = read_palette(widget)
    except Exception:  # noqa: BLE001 — no palette to read
        pal = None
    css = sheet(str(widget.objectName()), colours(pal if _valid(pal) else FALLBACK, params))
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
