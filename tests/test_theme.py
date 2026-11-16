# SPDX-License-Identifier: AGPL-3.0-only
# The ScanRuler panel follows the theme (scanrulerfc/theme.py): stand-in
# light and dark palettes, the sheet's text on its surfaces at 4.5:1 or
# better, no near-black surface under a light palette, enabled keys plainly
# brighter than disabled ones, the dark look kept, and a PaletteChange
# restyling the panel.
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

PALETTES = {
    "FreeCAD Light": {"window": "#efefef", "window_text": "#000000", "base": "#ffffff", "text": "#000000",
                      "button": "#f5f5f5", "button_text": "#000000", "highlight": "#3d7fd6", "mid": "#b8b8b8",
                      "disabled_button_text": "#a0a0a0", "disabled_window_text": "#a0a0a0"},
    "Studio Light": {"window": "#f6f7f9", "window_text": "#1c1e21", "base": "#ffffff", "text": "#1c1e21",
                     "button": "#e9ebee", "button_text": "#1c1e21", "highlight": "#2f6fdb", "mid": "#c7cbd1",
                     "disabled_button_text": "#9aa0a6", "disabled_window_text": "#9aa0a6"},
    # The Mac's dark system palette's text left under a light theme's window:
    # the grey key text the live pass saw.
    "Light, mismatched text": {"window": "#ececec", "window_text": "#dddddd", "button": "#3a3a3a", "button_text": "#c8c8c8",
                               "highlight": "#0a84ff"},
    "FreeCAD Dark": {"window": "#2b2b2b", "window_text": "#dcdcdc", "base": "#1e1e1e", "text": "#dcdcdc",
                     "button": "#3c3c3c", "button_text": "#e0e0e0", "highlight": "#3d7fd6", "mid": "#555555",
                     "disabled_button_text": "#7a7a7a", "disabled_window_text": "#7a7a7a"},
    "Studio Dark": {"window": "#1f2125", "window_text": "#e6e7e9", "base": "#17191c", "text": "#e6e7e9",
                    "button": "#2c2f34", "button_text": "#e6e7e9", "highlight": "#4c8dff", "mid": "#44484f",
                    "disabled_button_text": "#6b7078", "disabled_window_text": "#6b7078"},
}
LIGHT = ("FreeCAD Light", "Studio Light", "Light, mismatched text")


def rules(css):
    """{selector: {property: value}} from the sheet."""
    out = {}
    for sel, body in re.findall(r"([^{}]+)\{([^}]*)\}", css):
        props = dict((k.strip(), v.strip()) for k, v in (d.split(":", 1) for d in body.split(";") if ":" in d))
        out[sel.strip()] = props
    return out


def find(r, tail):
    return next(v for k, v in r.items() if k.endswith(tail))


class Contrast(unittest.TestCase):
    def test_text_reads_on_every_surface(self):
        for name, pal in PALETTES.items():
            with self.subTest(theme=name):
                r = rules(T.sheet("P", T.colours(pal, {})))
                page = find(r, "QScrollArea > QWidget > QWidget")
                card = find(r, " QGroupBox")
                label = find(r, " QLabel")
                key = find(r, " QPushButton")
                primary = find(r, 'QPushButton[primary="true"]')
                for fg, bg, what in ((page["color"], page["background"], "page text"),
                                     (label["color"], card["background"], "label on a card"),
                                     (label["color"], page["background"], "label on the page"),
                                     (find(r, "#P > QLabel")["color"], page["background"], "header"),
                                     (key["color"], key["background"], "key"),
                                     (primary["color"], primary["background"], "primary key"),
                                     (find(r, " a")["color"], card["background"], "link")):
                    self.assertGreaterEqual(T.contrast(fg, bg), 4.5, f"{what}: {fg} on {bg}")

    def test_disabled_keys_read_disabled_and_enabled_ones_enabled(self):
        for name, pal in PALETTES.items():
            with self.subTest(theme=name):
                r = rules(T.sheet("P", T.colours(pal, {})))
                on, off = find(r, " QPushButton"), find(r, " QPushButton:disabled")
                c_on, c_off = T.contrast(on["color"], on["background"]), T.contrast(off["color"], off["background"])
                self.assertGreaterEqual(c_off, T.DISABLED_MIN)
                self.assertLess(c_off, c_on * 0.75)
                self.assertGreaterEqual(c_on, 4.5)

    def test_no_near_black_surface_under_a_light_palette(self):
        for name in LIGHT:
            with self.subTest(theme=name):
                r = rules(T.sheet("P", T.colours(PALETTES[name], {})))
                for sel, props in r.items():
                    bg = props.get("background")
                    if bg and bg.startswith("#") and "primary" not in sel:
                        self.assertGreater(T.luminance(bg), 0.4, f"{sel}: {bg}")

    def test_card_offset_from_the_window(self):
        for name, pal in PALETTES.items():
            c = T.colours(pal, {})
            if c["dark"]:
                self.assertGreater(T.luminance(c["card"]), T.luminance(c["window"]), name)
            else:
                self.assertLess(T.luminance(c["card"]), T.luminance(c["window"]), name)
            self.assertLess(T.contrast(c["card"], c["window"]), 1.25, name)

    def test_dark_look_kept(self):
        """Under a dark theme the page is the theme's window, its text the
        theme's, and CNC Kitchen blue stays on primary keys."""
        for name in ("FreeCAD Dark", "Studio Dark"):
            pal = PALETTES[name]
            c = T.colours(pal, {})
            self.assertEqual(c["window"], pal["window"])
            self.assertEqual(c["text"], pal["window_text"])
            self.assertEqual(c["button_text"], pal["button_text"])
            self.assertEqual(c["primary"], W.ACCENT)

    def test_only_fixed_colour_is_cnc_kitchen_blue(self):
        css = T.sheet("P", T.colours(PALETTES["FreeCAD Light"], {}))
        self.assertNotIn("palette(", css)
        for line in css.splitlines():
            if W.ACCENT in line:
                self.assertIn("primary", line)

    def test_theme_accent_from_freecad(self):
        c = T.colours(PALETTES["FreeCAD Light"], {"ThemeAccentColor1": 0xCC3366FF})
        self.assertEqual(c["accent"], "#cc3366")
        self.assertEqual(T.colours(PALETTES["FreeCAD Light"], {})["accent"], "#3d7fd6")  # highlight


class FakeColor:
    def __init__(self, h):
        self.h = h

    def name(self):
        return self.h


class FakePalette:
    Disabled = "disabled"

    def __init__(self, pal):
        self.pal = pal

    def color(self, a, b=None):
        group, role = (a, b) if b is not None else (None, a)
        key = {"Window": "window", "WindowText": "window_text", "Base": "base", "Text": "text", "Button": "button",
               "ButtonText": "button_text", "Highlight": "highlight", "Mid": "mid"}[role]
        if group == "disabled":
            key = "disabled_" + key
        return FakeColor(self.pal.get(key) or self.pal.get(key.replace("disabled_", "")) or "#808080")


class FakeWidget:
    def __init__(self, parent):
        self.parent, self.sheet, self.filters = parent, "", []

    def parentWidget(self):
        return self.parent

    def objectName(self):
        return "ScanRulerPage"

    def styleSheet(self):
        return self.sheet

    def setStyleSheet(self, css):
        self.sheet = css

    def installEventFilter(self, f):
        self.filters.append(f)


def fake_qt():
    gui = types.SimpleNamespace(QPalette=types.SimpleNamespace(
        Disabled="disabled", Window="Window", WindowText="WindowText", Base="Base", Text="Text", Button="Button",
        ButtonText="ButtonText", Highlight="Highlight", Mid="Mid"))
    later = []

    class QObject:
        def __init__(self, parent=None):
            pass

    core = types.SimpleNamespace(
        QObject=QObject,
        QEvent=types.SimpleNamespace(PaletteChange=39, StyleChange=100, ParentChange=21),
        QTimer=types.SimpleNamespace(singleShot=lambda ms, fn: later.append(fn)))
    pyside = types.ModuleType("PySide")
    pyside.QtGui, pyside.QtCore = gui, core
    return {"PySide": pyside, "PySide.QtGui": gui, "PySide.QtCore": core}, later


class Restyle(unittest.TestCase):
    def test_palette_change_restyles(self):
        mods, later = fake_qt()
        parent = types.SimpleNamespace(palette=lambda: FakePalette(parent.pal), pal=PALETTES["FreeCAD Dark"])
        w = FakeWidget(parent)
        with mock.patch.dict(sys.modules, mods):
            f = T.follow(w, {})
            dark = w.sheet
            self.assertIn(PALETTES["FreeCAD Dark"]["window"], dark)
            # Applying FreeCAD Light: the parent re-polished, the panel told.
            parent.pal = PALETTES["FreeCAD Light"]
            f.eventFilter(w, types.SimpleNamespace(type=lambda: 39))
            self.assertEqual(w.sheet, dark)  # a turn of the loop later
            for fn in later:
                fn()
        self.assertNotEqual(w.sheet, dark)
        self.assertIn(PALETTES["FreeCAD Light"]["window"], w.sheet)

    def test_unchanged_sheet_not_set_again(self):
        mods, _later = fake_qt()
        parent = types.SimpleNamespace(palette=lambda: FakePalette(PALETTES["Studio Light"]))
        w = FakeWidget(parent)
        with mock.patch.dict(sys.modules, mods):
            self.assertTrue(T.apply(w, {}))
            self.assertFalse(T.apply(w, {}))

    def test_no_readable_palette_falls_back(self):
        mods, _later = fake_qt()
        w = FakeWidget(types.SimpleNamespace(palette=mock.MagicMock()))
        with mock.patch.dict(sys.modules, mods):
            T.apply(w, {})
        self.assertIn(T.FALLBACK["window"], w.sheet)


if __name__ == "__main__":
    unittest.main()
