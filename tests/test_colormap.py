# SPDX-License-Identifier: AGPL-3.0-only
# The nine colour maps, ported from ScanRuler by Stefan Hermann (CNC
# Kitchen): ramp values against the original's own tables, read here from
# its colormapData.ts and colormap.ts by a small parser when a ScanRuler
# checkout is at hand (SCANRULER_SRC, or a scanruler folder beside this repo).
import math
import os
import re
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from scanrulerfc import colormap as CM  # noqa: E402

SRC = os.environ.get("SCANRULER_SRC") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scanruler")
DATA = os.path.join(SRC, "src/core/field/colormapData.ts")
CODE = os.path.join(SRC, "src/core/field/colormap.ts")
POS = (0.0, 0.25, 0.5, 0.75, 1.0)


def ts_tables():
    """{id: [[r, g, b], …]} for all nine maps, from the TypeScript."""
    with open(DATA, encoding="utf-8") as f:
        data = f.read()
    with open(CODE, encoding="utf-8") as f:
        code = f.read()
    out = {}
    for name, body in re.findall(r"export const (\w+) = table\(`([^`]*)`\)", data):
        s = re.sub(r"\s+", "", body)
        b = [int(s[i:i + 2], 16) for i in range(0, len(s), 2)]
        out[name.lower()] = [b[i:i + 3] for i in range(0, len(b), 3)]
    jet = [int(x) for x in re.search(r"const JET = Uint8Array\.from\(\[([^\]]*)\]", code).group(1).split(",")]
    out["jet"] = [jet[i:i + 3] for i in range(0, len(jet), 3)]
    return out


def ts_caps():
    with open(CODE, encoding="utf-8") as f:
        code = f.read()
    named = {"BLUE": [0, 0, 255], "RED": [220, 0, 0], "GREEN": [0, 190, 0]}
    caps = {}
    for mid, under, over in re.findall(r"id: '(\w+)',.*?under: (\[[^\]]*\]|\w+),\s*over: (\[[^\]]*\]|\w+)", code, re.S):
        def val(x):
            return named[x] if x in named else [int(v) for v in x.strip("[]").split(",")]
        caps[mid] = (tuple(val(under)), tuple(val(over)))
    return caps


def ts_ramp(stops, t):
    """rampColor, as the TypeScript does it (Math.round: halves up)."""
    last = len(stops) - 1
    u = min(1.0, max(0.0, t)) * last
    i = min(last - 1, math.floor(u))
    f = u - i
    return [math.floor(stops[i][c] + (stops[i + 1][c] - stops[i][c]) * f + 0.5) for c in range(3)]


class TestAgainstOriginal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.exists(DATA):
            raise unittest.SkipTest("no ScanRuler checkout to read the original tables from")
        cls.tables = ts_tables()
        cls.caps = ts_caps()

    def test_nine_maps_in_order(self):
        self.assertEqual(CM.COLORMAP_IDS, ("jet", "viridis", "magma", "plasma", "inferno", "cividis", "mako", "rocket", "turbo"))
        self.assertEqual(set(self.tables), set(CM.COLORMAP_IDS))

    def test_tables_byte_for_byte(self):
        for mid in CM.COLORMAP_IDS:
            self.assertEqual(CM.colormap_by_id(mid).stops.tolist(), self.tables[mid], mid)

    def test_ramp_at_quarters(self):
        for mid in CM.COLORMAP_IDS:
            for t in POS:
                self.assertEqual(CM.ramp(mid, t).tolist(), ts_ramp(self.tables[mid], t), f"{mid} at {t}")

    def test_ramp_between_stops(self):
        ts = np.linspace(0, 1, 997)
        for mid in CM.COLORMAP_IDS:
            got = CM.ramp(mid, ts).tolist()
            self.assertEqual(got, [ts_ramp(self.tables[mid], t) for t in ts], mid)

    def test_caps(self):
        for mid in CM.COLORMAP_IDS:
            m = CM.colormap_by_id(mid)
            self.assertEqual((m.under, m.over), self.caps[mid], mid)


class TestColormap(unittest.TestCase):
    def test_known_values(self):
        self.assertEqual(CM.ramp("jet", 0.5).tolist(), [0, 200, 0])
        self.assertEqual(CM.ramp("viridis", 0).tolist(), [68, 1, 84])
        self.assertEqual(CM.ramp("viridis", 1).tolist(), [253, 231, 37])
        self.assertEqual(CM.UNMEASURED_RGB, (126, 131, 138))

    def test_unknown_is_jet(self):
        self.assertEqual(CM.colormap_by_id("nope").id, "jet")
        self.assertEqual(CM.DEFAULT, "jet")

    def test_palette(self):
        self.assertEqual(CM.PALETTE[0], "#1877c0")
        self.assertEqual(len(CM.PALETTE), 8)
        self.assertEqual(CM.hex_rgb(CM.palette_color(8)), (24, 119, 192))

    def test_bands(self):
        self.assertEqual(CM.quantize(0.0, 4), 0.125)
        self.assertEqual(CM.quantize(0.26, 4), 0.375)
        self.assertEqual(CM.quantize(1.0, 4), 0.875)
        self.assertEqual(CM.quantize(0.3, None), 0.3)
        self.assertEqual(CM.quantize(0.3, 1), 0.3)
        v = np.linspace(-1, 1, 101)
        rgb = CM.map_values(v, -1, 1, "viridis", bands=5)
        self.assertEqual(len({tuple(c) for c in rgb.tolist()}), 5)

    def test_map_values_outcomes(self):
        m = CM.colormap_by_id("turbo")
        rgb = CM.map_values([-3, -1, 0, 1, 3, 9, float("nan")], -1, 1, "turbo", valid_min=-5, valid_max=5).tolist()
        self.assertEqual(rgb[0], list(m.under))
        self.assertEqual(rgb[1], CM.ramp("turbo", 0).tolist())
        self.assertEqual(rgb[3], CM.ramp("turbo", 1).tolist())
        self.assertEqual(rgb[4], list(m.over))
        self.assertEqual(rgb[5], list(CM.UNMEASURED_RGB))
        self.assertEqual(rgb[6], list(CM.UNMEASURED_RGB))
        self.assertEqual(CM.map_values([1], 0, 1).dtype, np.uint8)

    def test_reversed_thickness(self):
        jet = CM.colormap_by_id("jet")
        rgb = CM.map_values([0.5, 1, 4, 9], 1, 4, reversed_=True, valid_min=0).tolist()
        self.assertEqual(rgb[1], [255, 0, 0])  # thin is hot
        self.assertEqual(rgb[2], [0, 0, 255])
        self.assertEqual(rgb[0], list(jet.over))
        self.assertEqual(rgb[3], list(jet.under))

    def test_legend_stops(self):
        s = CM.legend_stops("jet")
        self.assertEqual(len(s), 65)
        self.assertEqual(s[0], (0.0, (0, 0, 255)))
        b = CM.legend_stops("jet", 4)
        self.assertEqual(len(b), 4)
        self.assertEqual(b[0][:2], (0.0, 0.25))


if __name__ == "__main__":
    unittest.main()
