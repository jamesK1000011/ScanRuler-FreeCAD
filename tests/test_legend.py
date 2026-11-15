# SPDX-License-Identifier: AGPL-3.0-only
# The colour legend and stats card, ported from ScanRuler by Stefan Hermann
# (CNC Kitchen): the original's exact strings.
import math
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from scanrulerfc import legend as L  # noqa: E402

try:
    import pivy  # noqa: F401
    HAVE_PIVY = True
except ImportError:
    HAVE_PIVY = False


class TestFigures(unittest.TestCase):
    def test_to_fixed_like_js(self):
        self.assertEqual(L.to_fixed(0.0625, 3), "0.063")  # JS halves up; Python would give 0.062
        self.assertEqual(L.to_fixed(-0.0, 3), "0.000")
        self.assertEqual(L.to_fixed(1.5, 0), "2")

    def test_signed(self):
        self.assertEqual(L.format_signed(0.12), "+0.120")
        self.assertEqual(L.format_signed(-0.12), "−0.120")
        self.assertEqual(L.format_signed(0), "+0.000")
        self.assertEqual(L.format_signed(25.4, "in"), "+1.0000")

    def test_wall_and_input(self):
        self.assertEqual(L.wall(1.23456), "1.235")
        self.assertEqual(L.wall(-0.0001), "0.000")
        self.assertEqual(L.length_input_text(1.0), "1")
        self.assertEqual(L.length_input_text(0.05), "0.05")
        self.assertEqual(L.length_input_text(12.7, "in"), "0.5")
        self.assertEqual(L.count(1234567), "1,234,567")


class TestDeviation(unittest.TestCase):
    def setUp(self):
        self.v = np.array([-0.3, -0.05, 0.0, 0.05, 0.2, 5.0, np.nan])
        self.m = L.model("deviation", -0.4, 0.4, values=self.v, valid_min=-2, valid_max=2,
                         stats={"tolerance": 0.1}, show_histogram=True)

    def test_head_and_ends(self):
        self.assertEqual(self.m["head"], "mm")
        self.assertEqual(self.m["caption"], "MM")
        self.assertEqual(self.m["ends"]["high"]["caption"], "+ OUTSIDE THE REFERENCE")
        self.assertEqual(self.m["ends"]["low"]["caption"], "− INSIDE THE REFERENCE")
        el = L.model("deviation", -1, 1, source="element")
        self.assertEqual(el["ends"]["high"]["text"], "too much material")
        self.assertEqual(el["ends"]["low"]["text"], "too little material")

    def test_ticks(self):
        t = self.m["ticks"]
        self.assertEqual(len(t), 9)
        self.assertEqual([x["text"] for x in t], ["−0.400", "−0.300", "−0.200", "−0.100", "+0.000", "+0.100", "+0.200", "+0.300", "+0.400"])
        self.assertEqual([x["zero"] for x in t].index(True), 4)
        self.assertEqual(sum(x["zero"] for x in t), 1)
        self.assertEqual((t[0]["limit"], t[-1]["limit"]), ("low", "high"))
        self.assertEqual(self.m["limit_title"], "Click to set the range of the scale")

    def test_stats_rows(self):
        rows = self.m["stats"]
        self.assertEqual([r["caption"] for r in rows], ["MIN", "MAX", "MEAN", "RMS", "SIGMA", "±0.100", "MATCHED"])
        self.assertEqual(rows[0]["value"], "−0.300")
        self.assertEqual(rows[1]["value"], "+0.200")
        self.assertEqual(rows[5]["value"], "60.0 %")  # 3 of 5 within ±0.1
        self.assertEqual(rows[6]["value"], "5 / 7")
        self.assertTrue(rows[6]["wide"])
        self.assertFalse(rows[0]["wide"])

    def test_histogram(self):
        h = self.m["histogram"]
        self.assertEqual(len(h["bins"]), 60)
        self.assertEqual(sum(h["bins"]), 5)
        rows = h["rows"]
        self.assertEqual(rows[0]["range"], "under −0.387")
        self.assertEqual(rows[-1]["range"], "+0.387 and over")
        self.assertEqual(rows[1]["range"], "−0.387 – −0.373")
        self.assertEqual(rows[-1]["readout"], "0 pts · 0.0 %")
        self.assertEqual(L.model("deviation", -1, 1, values=self.v)["histogram"], None)

    def test_caps_titles(self):
        self.assertEqual(self.m["caps"]["high"]["title"], "Beyond the top of the scale")
        self.assertEqual(self.m["caps"]["low"]["title"], "Beyond the bottom of the scale")
        self.assertEqual(self.m["caps"]["high"]["rgb"], (130, 0, 0))


class TestThickness(unittest.TestCase):
    def test_rows_and_head(self):
        v = np.array([0.5, 0.8, 1.2, 2.0, np.nan, np.nan])
        m = L.model("thickness", 0.5, 2.0, values=v, stats={"limit": 1})
        self.assertEqual(m["caption"], "MM WALL")
        self.assertIsNone(m["ends"])
        self.assertTrue(m["reversed"])
        self.assertEqual([r["caption"] for r in m["stats"]], ["MIN", "MAX", "MEAN", "SIGMA", "UNDER 1", "THIN PTS", "MEASURED"])
        vals = [r["value"] for r in m["stats"]]
        self.assertEqual(vals[0], "0.500")
        self.assertEqual(vals[1], "2.000")
        self.assertEqual(vals[4], "50.0 %")
        self.assertEqual(vals[5], "2")
        self.assertEqual(vals[6], "4 / 6")
        self.assertFalse(any(t["zero"] for t in m["ticks"]))
        self.assertEqual(m["ticks"][0]["text"], "0.500")


class TestMesh(unittest.TestCase):
    def test_reduce(self):
        m = L.model("reduce", -0.05, 0.05, stats={"tolerance": 0.05, "within": 999, "measured": 1000, "p999": 0.0412, "max": 0.08, "rms": 0.011})
        self.assertEqual(m["ends"]["high"]["caption"], "+ MESH INSIDE THE SCAN")
        self.assertEqual([(r["caption"], r["value"]) for r in m["stats"]],
                         [("±0.05", "99.90 %"), ("99.9 %", "0.041"), ("MAX", "0.080"), ("RMS", "0.011")])

    def test_copy(self):
        m = L.model("copy", -0.2, 0.2, stats={"max_abs": 0.15, "rms": 0.02, "added": 10, "measured": 90})
        self.assertEqual(m["ends"]["high"]["caption"], "+ COPY OUTSIDE THE SCAN")
        self.assertEqual(m["ends"]["low"]["caption"], "− COPY INSIDE THE SCAN")
        self.assertEqual([r["caption"] for r in m["stats"]], ["MAX", "RMS", "ADDED"])
        self.assertEqual(m["stats"][2]["value"], "10.0 %")
        m2 = L.model("copy", -0.2, 0.2, stats={"max_abs": 0.15, "rms": 0.02, "added": 0, "measured": 90})
        self.assertEqual([r["caption"] for r in m2["stats"]], ["MAX", "RMS"])


class TestMarks(unittest.TestCase):
    def test_marks_inside_only(self):
        m = L.model("deviation", -1, 1, marks=[{"value": 0.5, "label": "a", "to": 2}, {"value": 1, "label": "end"}])
        self.assertEqual(len(m["marks"]), 1)
        self.assertEqual(m["marks"][0]["fraction"], 0.75)
        self.assertEqual(m["marks"][0]["to_fraction"], 1.0)


@unittest.skipUnless(HAVE_PIVY, "pivy not installed")
class TestCoin(unittest.TestCase):
    def test_nodes(self):
        m = L.model("deviation", -1, 1, values=np.linspace(-1, 1, 50), show_histogram=True, stats={"tolerance": 0.1})
        root = L.coin_nodes(m)
        self.assertGreater(root.getNumChildren(), 70)


if __name__ == "__main__":
    unittest.main()
