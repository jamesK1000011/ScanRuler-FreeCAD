# SPDX-License-Identifier: AGPL-3.0-only
# Window review round 6 of ScanRuler's results in FreeCAD's 3D view
# (ScanRuler by Stefan Hermann, CNC Kitchen): the new and old overlay
# colours swapped, labels about 6 px tall, a legend with no title or
# numbers, fit_scan_* bringing the Make bench up, sections left behind by
# an alignment, the panel one call behind. No FreeCAD here: stand-ins.
import os
import sys
import types
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

from test_editor_view import walk  # noqa: E402
from test_scene import Doc, Gui, Obj, Played, View3D, stand_in_coin  # noqa: E402

from scanrulerfc import dock as DK  # noqa: E402
from scanrulerfc import legend as L  # noqa: E402
from scanrulerfc import scanstate as S  # noqa: E402
from scanrulerfc import scene as SC  # noqa: E402
from scanrulerfc import scene_coin as SCC  # noqa: E402


def packed(rgb):
    """What Coin keeps of an SbColor (SbColor4f::getPackedValue: each
    channel times 255, shifted into 32 bits), read back as '#rrggbb'."""
    r, g, b, a = (int(c * 255 + 0.5) for c in (*rgb, 1.0))
    v = ((r << 24) | (g << 16) | (b << 8) | a) & 0xFFFFFFFF
    return "#%06x" % (v >> 8)


def texts(root):
    return [n.string.getValue() if hasattr(n.string, "getValue") else n.string for n in walk(root) if type(n).__name__ == "SoText2"]


class Colours(unittest.TestCase):
    def test_new_orange_old_blue_in_coin_range(self):
        self.assertEqual(SC.hex_of(SC.NEW), "#e8590c")
        self.assertEqual(SC.hex_of(SC.ELEMENT), "#1877c0")  # CNC Kitchen blue, ScanRuler's accent
        for c in (SC.ELEMENT, SC.NEW, SC.DIMENSION, SC.SECTION, SC.MARKED, SC.GHOST):
            self.assertTrue(all(0.0 <= x <= 1.0 for x in c), c)
        # What Coin draws is what was meant: no channel overflows.
        self.assertEqual(packed(SC.NEW), "#e8590c")
        self.assertEqual(packed(SC.ELEMENT), "#1877c0")

    def test_the_old_0_255_values_came_out_swapped(self):
        # The round-6 cause: 0..255 handed to Coin; orange read as blue, blue as orange.
        self.assertEqual(packed((232, 89, 12)), "#58aff4")
        self.assertEqual(packed((24, 119, 192)), "#febf40")

    def test_built_new_element_is_orange_the_old_one_blue(self):
        p = Played()
        p.call("element_fit", {"kind": "plane", "at": {"point": [20, 15, 20]}, "name": "Top"})
        sc, _ = p.call("element_fit", {"kind": "plane", "at": {"point": [20, 15, 0]}, "name": "Bottom"})
        by = {e["name"]: SC.hex_of(e["colour"]) for e in sc["elements"]}
        self.assertEqual(by, {"Top": "#1877c0", "Bottom": "#e8590c"})
        root = SCC.Builder(stand_in_coin()).build(sc)
        cols = [n.rgb.getValue() for n in walk(root) if type(n).__name__ == "SoBaseColor"]
        self.assertTrue(cols)
        for c in cols:
            self.assertTrue(all(0.0 <= x <= 1.0 for x in c), c)

    def test_segment_colours_in_coin_range(self):
        p = Played()
        sc, _ = p.call("scan_segment", {})
        if sc["map"] is not None:
            self.assertLessEqual(float(np.max(sc["map"]["rgb"])), 1.0)


class Labels(unittest.TestCase):
    def test_label_size_scales_with_the_view_and_the_screen(self):
        self.assertEqual(SCC.label_px(1704, 2.0), 16.0)  # an 852 px tall view on a Retina Mac
        self.assertEqual(SCC.label_px(700, 1.0), 13.0)
        self.assertEqual(SCC.label_px(400, 2.0), 12.0)   # never under 12
        self.assertEqual(SCC.label_px(4000, 1.0), 22.0)  # never over 22
        self.assertEqual(SCC.label_px(None, 2.0), SCC.FONT_SIZE)

    def test_font_size_is_device_pixels_and_new_is_larger(self):
        b = SCC.Builder(stand_in_coin(), 14.0, 2.0)
        self.assertEqual(b.font_size(), 28.0)
        self.assertEqual(b.font_size(new=True), 32.0)
        root = b.shape({"lines": [np.zeros((2, 3)), np.ones((2, 3))], "text": "Bore Ø 12.000 mm ✓", "at": [0, 0, 0], "new": True})
        fonts = [n.size.getValue() for n in walk(root) if type(n).__name__ == "SoFont"]
        self.assertEqual(fonts, [32.0])
        self.assertEqual(texts(root), ["Bore dia  12.000 mm OK"])

    def test_text_scale_reads_the_main_window_and_view(self):
        class MW:
            def devicePixelRatioF(self):  # noqa: N802
                return 2.0

        class G:
            def getMainWindow(self):  # noqa: N802
                return MW()

        class V:
            def getSize(self):  # noqa: N802
                return (2400, 1500)

        self.assertEqual(SCC.text_scale(G(), [V()]), (14.0, 2.0, 1500))
        self.assertEqual(SCC.text_scale(object(), []), (SCC.FONT_SIZE, 1.0, None))


class Legend(unittest.TestCase):
    def test_title_numbers_card_and_font(self):
        m = L.model("deviation", -1, 1, values=np.linspace(-1, 1, 50), stats={"tolerance": 0.1})
        m["caption"] = "DEVIATION · MM"
        root = L.coin_nodes(m, coin=stand_in_coin(), font_size=26)
        words = texts(root)
        self.assertIn("DEVIATION, MM", words)
        for v in ("-1.000", "+0.000", "+1.000"):
            self.assertIn(v, words)
        self.assertTrue(all(all(ord(ch) < 128 for ch in w) for w in words))
        fonts = [n for n in walk(root) if type(n).__name__ == "SoFont"]
        self.assertEqual(fonts[0].size, 26.0)
        # The card is the first quad: drawn under everything else.
        first = next(n for n in root.children if type(n).__name__ == "SoSeparator")
        self.assertEqual(first.children[0].rgb, tuple(c / 255.0 for c in L.CARD_RGB))
        self.assertEqual(L.text_rows(m), {"title": "DEVIATION, MM", "min": "-1.000", "mid": "+0.000", "max": "+1.000", "ticks": 9})

    def test_stat_lines(self):
        rows = [{"wide": False}] * 5 + [{"wide": True}]
        self.assertEqual(L.stat_lines(rows), 4)
        self.assertEqual(L.stat_lines([]), 0)

    def test_facts_name_the_legend_and_colours(self):
        p = Played()
        p.call("element_fit", {"kind": "plane", "at": {"point": [20, 15, 20]}, "name": "Top"})
        sc, _ = p.call("thickness_measure", {"maxThickness": 50})
        b = SCC.Builder(stand_in_coin(), 14.0, 2.0)
        f = SCC.facts(sc, b, 1500)
        self.assertEqual(f["colours"]["new"], "#e8590c")
        self.assertEqual(f["colours"]["element"], "#1877c0")
        self.assertEqual((f["labelPx"], f["fontSize"], f["dpr"]), (14.0, 28.0, 2.0))
        self.assertTrue(f["legend"]["title"].startswith("WALL THICKNESS"))
        self.assertIsNotNone(f["legend"]["min"])
        self.assertIsNotNone(f["legend"]["max"])

    def test_window_show_gives_facts(self):
        p = Played()
        p.ctx.doc = Doc(Obj("ScanRulerScan", "scan"))
        w = SCC.Window(Gui([View3D()]), stand_in_coin())
        p.run("element_fit", {"kind": "plane", "at": {"point": [20, 15, 20]}, "name": "Top"})
        got = w.show(p.ctx, "element_fit", {}, {"element": {"name": "Top"}})
        self.assertEqual(got["facts"]["drawn"]["elements"], [{"name": "Top", "colour": "#e8590c"}])


class Benches(unittest.TestCase):
    def test_fit_scan_stays_on_scanruler_against_workshops_fit(self):
        import scanrulerfc.agentlink_families as F

        def longest(name, pairs):  # Agent Link's echo._longest: no "_" boundary
            best, got = -1, None
            for k, v in pairs:
                if name.startswith(k) and len(k) > best:
                    best, got = len(k), v
            return got

        pairs = list(F.WORKBENCHES.items()) + [("fit", "WorkshopMakeWorkbench"), ("setup", "WorkshopMakeWorkbench")]
        for t in ("fit_scan_setup", "fit_scan_features", "fit_scan_measure", "fit_scan_export"):
            self.assertEqual(longest(t, pairs), "ScanRulerWorkbench", t)
        self.assertEqual(longest("fit", pairs), "WorkshopMakeWorkbench")


class SectionsFollow(unittest.TestCase):
    def first_point(self, p):
        sec = S.state(p.ctx)["sectionState"]["sections"][0]
        return np.asarray(sec["points"], dtype=float)[0].copy(), sec

    def test_align_moves_the_section_with_the_scan(self):
        p = Played()
        p.run("section_cut", {"across": "XY", "offset": 10, "name": "Mid"})
        before, _ = self.first_point(p)
        scan = S.state(p.ctx)["scan"]
        v0 = np.asarray(scan.V, dtype=float)[0].copy()
        sc, out = p.call("align_datum", {"origin": {"point": [5, 5, 5]}})
        self.assertEqual(out["sections"], 1)
        shift = np.asarray(scan.V, dtype=float)[0] - v0
        after, sec = self.first_point(p)
        np.testing.assert_allclose(after - before, shift, atol=1e-9)
        np.testing.assert_allclose(np.asarray(sec["frame"]["origin"])[2], 10 - 5, atol=1e-9)
        # The window draws it where it now is.
        np.testing.assert_allclose(sc["sections"][0]["lines"][0][0], after, atol=1e-9)
        _, out = p.call("align_clear", {})
        self.assertEqual(out["sections"], 1)
        np.testing.assert_allclose(self.first_point(p)[0], before, atol=1e-9)

    def test_rotation_turns_the_frame(self):
        p = Played()
        p.run("section_cut", {"across": "XY", "offset": 10, "name": "Mid"})
        p.run("element_fit", {"kind": "plane", "at": {"point": [40, 15, 10]}, "name": "Side"})
        p.call("align_datum", {"primary": {"element": "Side"}})
        _, sec = self.first_point(p)
        n = np.asarray(sec["frame"]["normal"], dtype=float)
        self.assertAlmostEqual(float(np.linalg.norm(n)), 1.0, places=9)
        self.assertLess(abs(float(n[2])), 0.5)  # z turned away with the side plane levelled on z

    def test_scale_scales_the_section(self):
        p = Played()
        p.run("section_cut", {"across": "XY", "offset": 10, "name": "Mid"})
        before, _ = self.first_point(p)
        _, out = p.call("scan_scale", {"factor": 2})
        self.assertEqual(out["sections"], 1)
        after, sec = self.first_point(p)
        np.testing.assert_allclose(after, before * 2, atol=1e-9)


class PanelAfterCall(unittest.TestCase):
    class FakeDock:
        def __init__(self):
            self.refreshed = 0
            self._seen = (7, "mesh_remove_islands")
            self.current = "mesh"
            self.widget = types.SimpleNamespace(isVisible=lambda: True)

        def refresh(self, force=False):
            self.refreshed += 1

    def test_refreshed_now_and_on_the_next_turn_once(self):
        d = self.FakeDock()
        queued = []
        got = DK.after_call(d, later=queued.append)
        self.assertEqual(got, {"shown": True, "version": 7, "workspace": "mesh"})
        self.assertEqual(d.refreshed, 1)
        DK.after_call(d, later=queued.append)  # a second call before the turn: one turn queued
        self.assertEqual(len(queued), 1)
        queued[0]()
        self.assertEqual(d.refreshed, 3)

    def test_no_panel_none_hidden_panel_said(self):
        self.assertIsNone(DK.after_call(None) if DK.live() is None else None)
        d = self.FakeDock()
        d.widget = types.SimpleNamespace(isVisible=lambda: False)
        self.assertEqual(DK.after_call(d, later=lambda f: None), {"shown": False})
        self.assertEqual(d.refreshed, 0)

    def test_answer_gets_view3d_facts_with_a_window(self):
        fake = types.ModuleType("FreeCAD")
        fake.GuiUp = True
        old_fc, old = sys.modules.get("FreeCAD"), SCC.after_call
        sys.modules["FreeCAD"] = fake
        SCC.after_call = lambda *a: {"facts": {"colours": {"new": "#e8590c"}}}
        try:
            p = Played()
            ok, out = p.run("scan_nearest", {"at": {"point": [20, 15, 25]}})
        finally:
            SCC.after_call = old
            if old_fc is None:
                sys.modules.pop("FreeCAD", None)
            else:
                sys.modules["FreeCAD"] = old_fc
        self.assertTrue(ok)
        self.assertEqual(out["view3d"]["colours"]["new"], "#e8590c")

    def test_headless_answer_unchanged(self):
        p = Played()
        ok, out = p.run("scan_nearest", {"at": {"point": [20, 15, 25]}})
        self.assertTrue(ok)
        self.assertNotIn("view3d", out)


if __name__ == "__main__":
    unittest.main()
