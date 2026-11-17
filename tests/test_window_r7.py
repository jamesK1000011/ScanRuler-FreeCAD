# SPDX-License-Identifier: AGPL-3.0-only
# Window review round 7 of ScanRuler's results in FreeCAD's 3D view
# (ScanRuler by Stefan Hermann, CNC Kitchen): the legend card ran past the
# view's right edge, its stats columns fell on each other, a ±0.001 mm
# deviation scale read +0.001 on every tick, and the labels were thin and
# about 11-12 px in a 1400 px picture. No FreeCAD here: stand-ins.
import os
import sys
import types
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

from test_editor_view import _Node, walk  # noqa: E402
from test_scene import Played, stand_in_coin  # noqa: E402

from scanrulerfc import legend as L  # noqa: E402
from scanrulerfc import scene_coin as SCC  # noqa: E402

# The live window of round 7: a 3D view 1622 x 1648 device px at ratio 2,
# in a 3420 px window pictured 1400 px wide.
LIVE_VIEW = (1622, 1648)
LIVE_DPR = 2.0
PICTURE = 1400.0 / 3420.0


def worn_deviation(rng=0.001):
    rs = np.random.default_rng(1)
    v = np.concatenate([rs.normal(0, 0.0002, 9500), rs.uniform(-1.0, -0.2, 500)])
    return L.model("deviation", -rng, rng, values=v, show_histogram=True, stats={"tolerance": 0.1})


def thickness():
    v = np.random.default_rng(2).uniform(10, 24.8, 5000)
    return L.model("thickness", 12, 20, values=v, show_histogram=True, stats={"limit": 1.0})


def boxes(lay):
    cw = L.CHAR_W * lay["font"]
    return [(w["x"], w["y"] - 0.25 * lay["font"], w["x"] + len(w["text"]) * cw, w["y"] + 0.75 * lay["font"], w["text"]) for w in lay["words"]]


class TickFormat(unittest.TestCase):
    def test_small_range_ticks_tell_apart(self):
        m = worn_deviation(0.001)
        texts = [t["text"] for t in m["ticks"]]
        self.assertEqual(len(set(texts)), 9, texts)
        self.assertEqual(m["tickDecimals"], 5)
        self.assertEqual(L.text_rows(m)["max"], "+0.00100")
        self.assertEqual(L.text_rows(m)["min"], "-0.00100")
        self.assertIn("+0.00025", [L.coin_text(t) for t in texts])

    def test_usual_ranges_keep_three_places(self):
        self.assertEqual(L.text_rows(L.model("deviation", -1, 1))["min"], "-1.000")
        self.assertEqual(L.text_rows(L.model("deviation", -0.1, 0.1))["mid"], "+0.000")
        self.assertEqual(thickness()["tickDecimals"], 3)
        self.assertEqual(L.text_rows(thickness())["max"], "20.000")

    def test_stats_rows_unchanged(self):
        m = worn_deviation()
        self.assertTrue(m["stats"][0]["value"].endswith(".000") or len(m["stats"][0]["value"].split(".")[1]) == 3)


class CardLayout(unittest.TestCase):
    def check(self, m, view, font):
        lay = L.card_layout(m, *view, font)
        vw, vh = view
        x0, y0, x1, y1 = lay["card"]
        self.assertTrue(lay["fits"], lay["card"])
        self.assertLessEqual(x1, vw)
        self.assertGreaterEqual(x0, 0)
        cw = L.CHAR_W * font
        for w in lay["words"]:
            self.assertLessEqual(w["x"] + len(w["text"]) * cw, x1 + 0.01, w["text"])  # no word past the card
            self.assertGreaterEqual(w["x"], x0)
            self.assertGreaterEqual(w["y"], y0)
            self.assertLessEqual(w["y"] + font, y1 + 0.01)
        b = boxes(lay)
        for i in range(len(b)):
            for j in range(i + 1, len(b)):
                p, q = b[i], b[j]
                apart = p[2] <= q[0] or q[2] <= p[0] or p[3] <= q[1] or q[3] <= p[1]
                self.assertTrue(apart, f"{p[4]!r} on {q[4]!r}")
        return lay

    def test_live_view_deviation(self):
        font = SCC.legend_px(LIVE_VIEW[1], LIVE_DPR) * LIVE_DPR
        lay = self.check(worn_deviation(), LIVE_VIEW, font)
        vh = LIVE_VIEW[1]
        self.assertLessEqual(lay["card"][3], vh * L.TOP_SHARE + 0.1)       # under the navigation cube
        self.assertGreaterEqual(lay["card"][1], vh * L.FLOOR_SHARE - 0.1)  # above the caption
        self.assertEqual(len(lay["shownTicks"]), 9)

    def test_live_view_thickness(self):
        font = SCC.legend_px(LIVE_VIEW[1], LIVE_DPR) * LIVE_DPR
        self.check(thickness(), LIVE_VIEW, font)

    def test_small_view_thins_ticks_and_still_fits(self):
        lay = self.check(worn_deviation(), (700, 420), 13)
        self.assertLess(len(lay["shownTicks"]), 9)
        self.assertEqual(lay["shownTicks"][0], "-0.00100")
        self.assertEqual(lay["shownTicks"][-1], "+0.00100")

    def test_too_small_for_the_font_draws_smaller(self):
        lay = L.card_layout(worn_deviation(), 700, 420, 26)
        self.assertTrue(lay["fits"])
        self.assertLess(lay["font"], 26)
        root = L.coin_nodes(worn_deviation(), coin=stand_in_coin(), font_size=26, view=(700, 420))
        self.assertEqual([n.size for n in walk(root) if type(n).__name__ == "SoFont"], [lay["font"]])

    def test_stats_second_column_clear_of_the_first(self):
        lay = L.card_layout(thickness(), *LIVE_VIEW, 30)
        stats = [w for w in lay["words"] if w["role"] == "stat"]
        cw = L.CHAR_W * 30
        by_line = {}
        for w in stats:
            by_line.setdefault(round(w["y"], 1), []).append(w)
        for ws in by_line.values():
            ws.sort(key=lambda w: w["x"])
            for a, b in zip(ws, ws[1:]):
                self.assertLessEqual(a["x"] + len(a["text"]) * cw, b["x"])

    def test_coin_nodes_inside_the_unit_square_card_first(self):
        m = worn_deviation()
        root = L.coin_nodes(m, coin=stand_in_coin(), font_size=30, view=LIVE_VIEW)
        first = next(n for n in root.children if type(n).__name__ == "SoSeparator")
        self.assertEqual(first.children[0].rgb, tuple(c / 255.0 for c in L.CARD_RGB))
        pts = [p for n in walk(root) if type(n).__name__ == "SoCoordinate3" for p in n.point.value]
        self.assertTrue(pts)
        self.assertTrue(all(0 <= x <= 1 and 0 <= y <= 1 for x, y, _z in pts))

    def test_box_facts(self):
        lay = L.card_layout(worn_deviation(), *LIVE_VIEW, 30)
        f = L.box_facts(lay)
        self.assertEqual(f["view"], [1622.0, 1648.0])
        self.assertTrue(f["fits"])
        self.assertLessEqual(f["textRight"], f["px"][2])
        self.assertLessEqual(f["share"][2], 1.0)
        self.assertEqual(len(f["shownTicks"]), 9)


class Labels(unittest.TestCase):
    def test_live_label_size_in_the_picture(self):
        px = SCC.label_px(LIVE_VIEW[1], LIVE_DPR)
        self.assertEqual(px, 21.0)
        b = SCC.Builder(stand_in_coin(), px, LIVE_DPR, LIVE_VIEW)
        self.assertTrue(16 <= b.font_size() * PICTURE <= 19)
        self.assertTrue(17 <= b.font_size(new=True) * PICTURE <= 20)

    def test_label_on_a_backing_when_freecad_has_the_node(self):
        coin = stand_in_coin()
        made = []

        class SoTextLabel(_Node):
            pass

        class T:
            def __init__(self, n):
                self.n = n

            def createInstance(self):  # noqa: N802
                if self.n != "SoTextLabel":
                    return None
                made.append(SoTextLabel())
                return made[-1]

        coin.SoType = types.SimpleNamespace(fromName=lambda n: T(n))
        b = SCC.Builder(coin, 21.0, 2.0)
        root = b.shape({"lines": [np.zeros((2, 3)), np.ones((2, 3))], "text": "Bore", "at": [0, 0, 0]})
        self.assertEqual(len(made), 1)
        lab = made[0]
        self.assertIs(lab.background, True)
        self.assertEqual(lab.backgroundColor, SCC.LABEL_BACK_RGB)
        self.assertAlmostEqual(lab.frameSize, SCC.LABEL_FRAME * 42.0)
        self.assertEqual(lab.string.value, "Bore")
        self.assertEqual(b.label_node, "SoTextLabel")
        fonts = [n for n in walk(root) if type(n).__name__ == "SoFont"]
        self.assertEqual(fonts[0].size.value, 42.0)

    def test_plain_words_without_the_node(self):
        b = SCC.Builder(stand_in_coin(), 21.0, 2.0)
        root = b.shape({"lines": [np.zeros((2, 3)), np.ones((2, 3))], "text": "Bore", "at": [0, 0, 0]})
        self.assertEqual(b.label_node, "SoText2")
        self.assertTrue(any(type(n).__name__ == "SoText2" for n in walk(root)))

    def test_bold_font_name_set_when_the_field_is_there(self):
        coin = stand_in_coin()

        class Font(_Node):
            def __init__(self, *a):
                super().__init__(*a)
                del self.name  # a field, as in pivy (the stand-in node keeps a plain name)

        coin.SoFont = Font
        b = SCC.Builder(coin, 21.0, 2.0)
        font, _w = b.label("Top")
        self.assertEqual(font.name.value, SCC.LABEL_FONT)


class Facts(unittest.TestCase):
    def test_facts_hold_the_legend_box_and_tick_strings(self):
        p = Played()
        p.call("element_fit", {"kind": "plane", "at": {"point": [20, 15, 20]}, "name": "Top"})
        sc, _ = p.call("thickness_measure", {"maxThickness": 50})
        b = SCC.Builder(stand_in_coin(), 21.0, 2.0, LIVE_VIEW)
        b.build(sc)
        f = SCC.facts(sc, b, LIVE_VIEW[1])
        self.assertEqual(f["viewSize"], list(LIVE_VIEW))
        self.assertEqual(f["labelNode"], "SoText2")
        lg = f["legend"]
        self.assertEqual(len(lg["tickTexts"]), 9)
        self.assertEqual(lg["fontSize"], SCC.legend_px(LIVE_VIEW[1], 2.0) * 2.0)
        self.assertTrue(lg["box"]["fits"])
        self.assertEqual(lg["box"]["view"], [1622.0, 1648.0])
        self.assertIn("tickDecimals", lg)


if __name__ == "__main__":
    unittest.main()
