# SPDX-License-Identifier: AGPL-3.0-only
# The ScanRuler panel under the theme (scanrulerfc/theme.py): FreeCAD Light
# and Studio Light paint by stylesheet, not by QPalette (the Mac's palette
# stays dark), so the sheet paints no page background and sets no text
# colour; cards are a translucent overlay and border that read on light and
# dark; light or dark is detected from what the theme renders behind the
# panel, else the stylesheet's name; dark themes look as they did (425b61c);
# disabled keys read disabled; a style change restyles the panel.
import os
import re
import sys
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from scanrulerfc import theme as T  # noqa: E402
from scanrulerfc import workspaces as W  # noqa: E402

# What each theme renders behind the panel, and its keys (for the checks).
THEMES = {
    "FreeCAD Light": {"window": "#efefef", "text": "#000000", "button": "#f5f5f5", "button_text": "#000000"},
    "Studio Light": {"window": "#f6f7f9", "text": "#1c1e21", "button": "#e9ebee", "button_text": "#1c1e21"},
    "FreeCAD Dark": {"window": "#2b2b2b", "text": "#dcdcdc", "button": "#3c3c3c", "button_text": "#e0e0e0"},
    "Studio Dark": {"window": "#1f2125", "text": "#e6e7e9", "button": "#2c2f34", "button_text": "#e6e7e9"},
}
DARK = ("FreeCAD Dark", "Studio Dark")


def rules(css):
    """{selector: {property: value}} from the sheet."""
    out = {}
    for sel, body in re.findall(r"([^{}]+)\{([^}]*)\}", css):
        props = dict((k.strip(), v.strip()) for k, v in (d.split(":", 1) for d in body.split(";") if ":" in d))
        out[sel.strip()] = props
    return out


def find(r, tail):
    return next(v for k, v in r.items() if k.endswith(tail))


def css_for(seen):
    return T.sheet("P", T.colours(seen, {}))


SEENS = [None, {"dark": None}] + [T.seen_from(window=t["window"]) for t in THEMES.values()]


class ThemePaints(unittest.TestCase):
    def test_no_palette_painted_background_or_text(self):
        """No palette(...), no rule on the page itself, no opaque background
        but the dark theme's blue primary key, no text colour on labels,
        check boxes or enabled keys."""
        for seen in SEENS:
            with self.subTest(seen=seen):
                css = css_for(seen)
                self.assertNotIn("palette(", css)
                r = rules(css)
                self.assertNotIn("#P", r)
                for sel, props in r.items():
                    bg = props.get("background", "")
                    if bg.startswith("#"):
                        self.assertIn('primary="true"]:enabled', sel)
                    if sel in ("#P QLabel", "#P QCheckBox", "#P QPushButton", "#P QGroupBox"):
                        self.assertNotIn("color", props, sel)
                self.assertFalse(any(k.endswith(" QPushButton") for k in r), "enabled keys left to the theme")
                self.assertNotIn("QCheckBox", css)
                self.assertEqual(find(r, "QScrollArea > QWidget > QWidget")["background"], "transparent")

    def test_card_is_translucent_and_reads_on_light_and_dark(self):
        for seen in SEENS:
            r = rules(css_for(seen))
            card = find(r, " QGroupBox")
            self.assertTrue(card["background"].startswith("rgba("), card)
            self.assertIn(T.BORDER, card["border"])
        # Unknown: one neutral overlay and border, visible on both ends.
        r = rules(css_for(None))
        for t in THEMES.values():
            win = t["window"]
            card = T.over(find(r, " QGroupBox")["background"], win)
            border = T.over(T.BORDER, card)
            self.assertNotEqual(card, win)
            self.assertGreater(T.contrast(border, card), 1.1, win)
            self.assertLess(T.contrast(card, win), 1.25, win)

    def test_card_offset_matches_the_theme(self):
        for name, t in THEMES.items():
            c = T.colours(T.seen_from(window=t["window"]), {})
            card = T.over(c["card_bg"], t["window"])
            if name in DARK:
                self.assertGreater(T.luminance(card), T.luminance(t["window"]), name)
            else:
                self.assertLess(T.luminance(card), T.luminance(t["window"]), name)
            self.assertLess(T.contrast(card, t["window"]), 1.25, name)


class Detection(unittest.TestCase):
    def test_rendered_colour_decides(self):
        for name, t in THEMES.items():
            s = T.seen_from(window=t["window"])
            self.assertEqual(s["dark"], name in DARK, name)
            self.assertEqual(s["via"], "render")

    def test_rendered_colour_beats_the_name(self):
        self.assertFalse(T.seen_from(window="#efefef", name="FreeCAD Dark.qss")["dark"])

    def test_name_when_nothing_rendered(self):
        self.assertTrue(T.seen_from(name="FreeCAD Dark.qss")["dark"])
        self.assertFalse(T.seen_from(name="Studio Light.qss")["dark"])
        for n in ("", "FreeCAD.qss", None, "Dark and Light.qss"):
            self.assertIsNone(T.seen_from(name=n)["dark"], n)

    def test_unknown_is_theme_neutral(self):
        c = T.colours(None, {})
        self.assertIsNone(c["dark"])
        self.assertEqual(c["card_bg"], T.CARD[None])
        self.assertEqual(c["link"], W.ACCENT)
        self.assertNotIn("background: " + W.ACCENT, css_for(None))


class DarkUnchanged(unittest.TestCase):
    def test_dark_look_as_in_425b61c(self):
        """Card 6% toward white, a mid-grey border near the old palette mid,
        the blue primary key with white text, the link lightened as far as
        it needs: as the palette-based sheet drew them."""
        for name in DARK:
            win = THEMES[name]["window"]
            c = T.colours(T.seen_from(window=win), {})
            old_card = T.mix(win, "#ffffff", 0.06)
            self.assertEqual(T.over(c["card_bg"], win), old_card, name)
            self.assertEqual(c["card"], old_card)
            self.assertEqual(c["link"], T.readable(W.ACCENT, old_card))
            self.assertGreaterEqual(T.contrast(c["link"], old_card), 4.5)
            r = rules(T.sheet("P", c))
            primary = find(r, 'QPushButton[primary="true"]:enabled')
            self.assertEqual(primary["background"], W.ACCENT)
            self.assertGreaterEqual(T.contrast(primary["color"], W.ACCENT), 4.5)
        # FreeCAD Dark's mid was #555555: the translucent border lands close.
        card = T.mix("#2b2b2b", "#ffffff", 0.06)
        self.assertLess(T.contrast(T.over(T.BORDER, card), "#555555"), 1.15)

    def test_light_primary_is_an_outline(self):
        for seen in (None, T.seen_from(window="#efefef")):
            primary = find(rules(css_for(seen)), 'QPushButton[primary="true"]:enabled')
            self.assertNotIn("background", primary)
            self.assertIn(W.ACCENT, primary["border"])
            self.assertNotIn("color", primary)

    def test_light_link_reads(self):
        for name, t in THEMES.items():
            if name in DARK:
                continue
            c = T.colours(T.seen_from(window=t["window"]), {})
            self.assertGreaterEqual(T.contrast(c["link"], c["card"]), 4.5, name)
            self.assertGreaterEqual(T.contrast(c["link"], t["window"]), 4.5, name)
            self.assertLess(T.contrast(c["link"], W.ACCENT), 1.3, name)  # still Stefan's blue
        self.assertEqual(T.colours(None, {})["link"], W.ACCENT)
        self.assertGreaterEqual(T.contrast(W.ACCENT, "#ffffff"), 4.5)


class DisabledKeys(unittest.TestCase):
    def test_disabled_reads_disabled_on_light_and_dark(self):
        """The theme's key and its text against the sheet's disabled grey:
        legible, and plainly dimmer than an enabled key."""
        for seen in SEENS:
            r = rules(css_for(seen))
            off = find(r, " QPushButton:disabled")
            self.assertTrue(off["color"].startswith("rgba("))
            self.assertTrue(off["border-color"].startswith("rgba("))
            self.assertNotIn("background", off)
        for name, t in THEMES.items():
            on = T.contrast(t["button_text"], t["button"])
            dim = T.over(T.DISABLED_TEXT, t["button"])
            self.assertGreaterEqual(T.contrast(dim, t["button"]), T.DISABLED_MIN, name)
            self.assertLess(T.contrast(dim, t["button"]), on * 0.5, name)

    def test_primary_blue_only_while_enabled(self):
        for seen in SEENS:
            css = css_for(seen)
            for line in css.splitlines():
                if W.ACCENT in line and "primary" in line:
                    self.assertIn(":enabled", line)


class Accent(unittest.TestCase):
    def test_only_fixed_colour_is_cnc_kitchen_blue(self):
        for seen in SEENS:
            for line in css_for(seen).splitlines():
                if W.ACCENT in line:
                    self.assertTrue(any(k in line for k in ("primary", " a ", ":hover", ":checked")), line)
            for c in set(re.findall(r"#[0-9a-fA-F]{6}\b", css_for(seen))) - {"#ffffff"}:  # white: the dark primary's text
                self.assertLess(T.contrast(c, W.ACCENT), 2.0, c)  # blue, or the link's tint of it

    def test_theme_accent_from_freecad(self):
        self.assertEqual(T.colours(None, {"ThemeAccentColor1": 0xCC3366FF})["accent"], "#cc3366")
        self.assertEqual(T.colours(None, {})["accent"], W.ACCENT)


# --- stand-in Qt -------------------------------------------------------------------

class FakeWidget:
    """A widget that paints `paints` (#rrggbb) of its own, or nothing (None)."""

    def __init__(self, parent=None, paints=None, name="ScanRulerPage"):
        self.parent, self.paints, self.name, self.sheet, self.filters = parent, paints, name, "", []

    def parentWidget(self):
        return self.parent

    def objectName(self):
        return self.name

    def styleSheet(self):
        return self.sheet

    def setStyleSheet(self, css):
        self.sheet = css

    def installEventFilter(self, f):
        self.filters.append(f)

    def rect(self):
        return types.SimpleNamespace(width=lambda: 100, height=lambda: 80)

    def render(self, img, *_a):
        img.px = (self.paints, 255) if self.paints else ("#000000", 0)


class FakeImage:
    Format_ARGB32 = 5

    def __init__(self, *_a):
        self.px = ("#000000", 0)

    def fill(self, _c):
        pass

    def pixelColor(self, _x, _y):
        h, a = self.px
        return types.SimpleNamespace(name=lambda: h, alpha=lambda: a)


def fake_qt():
    later = []

    class QObject:
        def __init__(self, parent=None):
            pass

    widgets = types.SimpleNamespace(QWidget=types.SimpleNamespace(RenderFlag=lambda v: v))
    gui = types.SimpleNamespace(QImage=FakeImage, QRegion=lambda *a: a)
    core = types.SimpleNamespace(
        QObject=QObject, QPoint=lambda *a: a, Qt=types.SimpleNamespace(transparent=0),
        QEvent=types.SimpleNamespace(PaletteChange=39, StyleChange=100, ParentChange=21),
        QTimer=types.SimpleNamespace(singleShot=lambda ms, fn: later.append(fn)))
    pyside = types.ModuleType("PySide")
    pyside.QtGui, pyside.QtCore, pyside.QtWidgets = gui, core, widgets
    return {"PySide": pyside, "PySide.QtGui": gui, "PySide.QtCore": core, "PySide.QtWidgets": widgets}, later


class Detect(unittest.TestCase):
    def test_nearest_painting_ancestor(self):
        """A see-through tab page over a light dock under a dark main window:
        the light dock is what shows behind the panel."""
        mods, _ = fake_qt()
        main = FakeWidget(paints="#202020", name="main")
        dock = FakeWidget(main, paints="#efefef", name="dock")
        tab = FakeWidget(dock, paints=None, name="tab")
        w = FakeWidget(tab)
        with mock.patch.dict(sys.modules, mods):
            s = T.detect(w)
        self.assertEqual(s, {"dark": False, "window": "#efefef", "via": "render"})

    def test_name_when_nothing_paints(self):
        mods, _ = fake_qt()
        w = FakeWidget(FakeWidget(paints=None))
        with mock.patch.dict(sys.modules, mods), mock.patch.object(T, "style_name", lambda: "FreeCAD Dark.qss"):
            s = T.detect(w)
        self.assertEqual((s["dark"], s["via"]), (True, "name"))


class Restyle(unittest.TestCase):
    def test_style_change_restyles(self):
        mods, later = fake_qt()
        dock = FakeWidget(paints="#2b2b2b", name="dock")
        w = FakeWidget(dock)
        with mock.patch.dict(sys.modules, mods):
            f = T.follow(w, {})
            dark = w.sheet
            self.assertIn("background: " + W.ACCENT, dark)
            # Applying FreeCAD Light: the dock re-polished, the panel told.
            dock.paints = "#efefef"
            f.eventFilter(w, types.SimpleNamespace(type=lambda: 100))
            self.assertEqual(w.sheet, dark)  # a turn of the loop later
            for fn in later:
                fn()
        self.assertNotEqual(w.sheet, dark)
        self.assertNotIn("background: " + W.ACCENT, w.sheet)
        self.assertIn(T.CARD[False], w.sheet)

    def test_unchanged_sheet_not_set_again(self):
        mods, _ = fake_qt()
        w = FakeWidget(FakeWidget(paints="#f6f7f9"))
        with mock.patch.dict(sys.modules, mods):
            self.assertTrue(T.apply(w, {}))
            self.assertFalse(T.apply(w, {}))

    def test_render_failure_is_theme_neutral(self):
        mods, _ = fake_qt()
        parent = FakeWidget()
        parent.render = mock.MagicMock(side_effect=RuntimeError)
        w = FakeWidget(parent)
        with mock.patch.dict(sys.modules, mods), mock.patch.object(T, "style_name", lambda: ""):
            T.apply(w, {})
        self.assertIn(T.CARD[None], w.sheet)


if __name__ == "__main__":
    unittest.main()
