# SPDX-License-Identifier: AGPL-3.0-only
# Window pass 5 (round 8) of ScanRuler's 2D sheet in FreeCAD (ScanRuler by
# Stefan Hermann, CNC Kitchen): the picture sheet never loaded (01-059,
# 01-074: the flat calls after call 48 read the plate's section), the Disc
# was drawn over the plate (01-070), labels covered each other on the
# sheet, and the panel's keys were squashed. No FreeCAD here: stand-ins.
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

from test_scene import Played  # noqa: E402
from test_window_pass3 import sheet_png, texture_coin  # noqa: E402

from scanrulerfc import echo_words as EW  # noqa: E402
from scanrulerfc import scene as SC  # noqa: E402
from scanrulerfc import scene_coin as SCC  # noqa: E402

FLAT_TOOLS = ("flat_open_image", "flat_calibrate", "flat_detect_edges", "flat_edges", "flat_fit", "flat_dimension_add", "flat_report",
              "flat_export", "flat_objects", "flat_profile", "flat_note_add", "flat_edit", "flat_remove", "flat_set_alignment",
              "flat_render", "flat_curvature")


class PictureSheet(unittest.TestCase):
    """The flat model's calls 11 to 60 in short: a section on the sheet,
    then the picture in its place, measured and calibrated."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.png = os.path.join(self.dir, "flat-test.png")
        sheet_png(self.png)
        self.p = Played()
        self.p.call("section_cut", {"across": "XY", "name": "Mid"})
        self.p.call("flat_fit", {"kind": "line", "box": {"min": [-19, 14], "max": [19, 16]}, "name": "Top"})

    def test_a_missing_image_says_the_section_stays(self):
        got, out = self.p.run("flat_open_image", {"path": os.path.join(self.dir, "no-such-image.png")})
        self.assertFalse(got)
        self.assertIn("still shows section Mid", str(out))
        _plan, e = self.p.call("flat_edges")
        self.assertEqual(e["sheet"]["kind"], "section")
        self.assertIn("on section Mid", EW.words("flat_edges", {}, e))

    def test_the_picture_replaces_the_section(self):
        plan, o = self.p.call("flat_open_image", {"path": self.png})
        self.assertEqual(o["sheet"], {"kind": "image", "name": "flat-test.png", "units": "mm", "scale": "UNCALIBRATED — nominal 254 dpi from file metadata"})
        self.assertEqual(o["replaced"], "section Mid")
        self.assertEqual(o["flat"]["elements"], [])
        self.assertIn("in place of section Mid", EW.words("flat_open_image", {"path": self.png}, o))
        self.assertEqual(plan["flat"]["kind"], "image")
        # Call 49: the disc (2 pi x 8) and the rectangle, in mm.
        _plan, e = self.p.call("flat_edges", {"limit": 2})
        disc, rect = e["chains"]
        self.assertAlmostEqual(disc["length"], 50.3, delta=0.4)
        self.assertTrue(np.allclose(disc["bounds"]["min"], [4, 7], atol=0.2) and np.allclose(disc["bounds"]["max"], [20, 23], atol=0.2))
        self.assertTrue(np.allclose(rect["bounds"]["min"], [25, 10], atol=0.2))
        self.assertIn("on flat-test.png", EW.words("flat_edges", {"limit": 2}, e))
        # Calls 50 to 52: the parts on the picture, read by number.
        _plan, ob = self.p.call("flat_objects")
        self.assertEqual(ob["count"], 2)
        _plan, pr = self.p.call("flat_profile", {"object": 1})
        self.assertAlmostEqual(pr["sides"][0]["max"], 8.0, delta=0.05)
        # Calls 53 to 60.
        plan, d = self.p.call("flat_fit", {"kind": "circle", "box": {"min": [3, 6], "max": [21, 24]}, "name": "Disc"})
        self.assertEqual(d["element"]["id"], 1)
        self.assertTrue(np.allclose(d["element"]["fit"]["center"], [12, 15], atol=0.02))
        self.p.call("flat_fit", {"kind": "line", "box": {"min": [26, 15.5], "max": [34, 16.5]}, "name": "Upper"})
        self.p.call("flat_fit", {"kind": "line", "box": {"min": [26, 9.5], "max": [34, 10.5]}, "name": "Lower"})
        self.p.call("flat_dimension_add", {"refs": ["Upper", "Lower"], "name": "Height"})
        self.p.call("flat_note_add", {"text": "disc", "at": [4, 26]})
        _plan, c = self.p.call("flat_calibrate", {"mode": "diameter", "points": [[20, 15], [12, 23], [4, 15]], "mm": 32})
        self.assertEqual(c["sheet"]["scale"], "CALIBRATED, 5.0000 px/mm")
        plan, r = self.p.call("flat_report")
        self.assertIn("Scale: CALIBRATED, 5.0000 px/mm", r["text"])
        self.assertIn("31.99", r["text"])
        self.assertIn("Upper → Lower", r["text"])
        self.assertIn("12.0", r["text"])
        w = EW.words("flat_report", {}, r)
        self.assertIn("on flat-test.png", w)
        self.assertIn("CALIBRATED", w)
        # Item 2, the frame: the Disc is drawn where the picture's disc is,
        # on the picture's texture (80 x 60 mm at 5 px/mm, origin bottom-left,
        # y up), and the found edges with it.
        fl = plan["flat"]
        self.assertTrue(np.allclose(fl["corners"][2], [80, 60, 0]))
        disc_item = next(i for i in fl["items"] if i.get("name") == "Disc")
        ring = disc_item["lines"][0]
        self.assertTrue(np.allclose((ring.min(0)[:2] + ring.max(0)[:2]) / 2, [24, 30], atol=0.1))
        self.assertAlmostEqual(float(np.ptp(ring[:, 0])), 32.0, delta=0.1)
        edges = next(i for i in fl["items"] if i["kind"] == "edges")
        longest = max(edges["lines"], key=len)
        self.assertTrue(np.allclose(longest.min(0)[:2], [8, 14], atol=0.5) and np.allclose(longest.max(0)[:2], [40, 46], atol=0.5))
        note = next(i for i in fl["items"] if i["kind"] == "flatNote")
        self.assertTrue(np.allclose(note["at"][:2], [8, 52]))
        b = SCC.Builder(texture_coin(), 13, 2.0, (1600, 1200))
        b.build(plan)
        self.assertEqual(b.texture, [400, 300])  # the picture's pixels over the 80 x 60 mm sheet

    def test_every_flat_answer_names_its_sheet(self):
        self.p.call("flat_open_image", {"path": self.png})
        seen = set()
        for tool, args in (("flat_edges", {}), ("flat_detect_edges", {}), ("flat_objects", {}), ("flat_profile", {"object": 1}),
                           ("flat_fit", {"kind": "circle", "box": {"min": [3, 6], "max": [21, 24]}, "name": "Disc"}),
                           ("flat_fit", {"kind": "point", "points": [[30, 13]], "snap": False, "name": "P"}),
                           ("flat_dimension_add", {"refs": ["Disc", "P"], "name": "D"}), ("flat_curvature", {"element": "Disc"}),
                           ("flat_note_add", {"text": "n", "at": [1, 1]}), ("flat_edit", {"note": 1, "text": "m"}),
                           ("flat_set_alignment", {"origin": [0, 0], "xAxis": [1, 0]}),
                           ("flat_report", {}), ("flat_export", {"format": "svg", "path": os.path.join(self.dir, "s")}),
                           ("flat_remove", {"notes": [1]}),
                           ("flat_calibrate", {"mode": "diameter", "points": [[20, 15], [12, 23], [4, 15]], "mm": 32})):
            _plan, out = self.p.call(tool, args)
            self.assertEqual((tool, out["sheet"]["kind"], out["sheet"]["name"]), (tool, "image", "flat-test.png"))
            seen.add(tool)
        # flat_render needs Agent Link's renderer (not here); its answer goes through the same wrap.
        self.assertEqual(seen | {"flat_open_image", "flat_render"}, set(FLAT_TOOLS))


class Labels(unittest.TestCase):
    FRAME = {"origin": [0, 0, 0], "basisU": [1, 0, 0], "basisV": [0, 1, 0]}

    def test_labels_on_one_place_are_set_apart(self):
        # "Sparse" and "Mid" (two sections at one offset), "Bore centre"
        # under "Bore to left 20.000 mm": 01-012 to 01-054.
        shapes = [{"text": "Mid", "at": np.array([-20.0, -15.0, 0])}, {"text": "Sparse", "at": np.array([-20.0, -15.0, 0])},
                  {"text": "Bore to left 20.000 mm", "at": np.array([-10.0, 0.0, 0])}, {"text": "Bore centre", "at": np.array([0.2, 0.3, 0])},
                  {"text": None, "at": None}]
        per, font, margin = 0.06, 26.0, 7.8
        got = SC.spread_labels(shapes, self.FRAME, per, font, margin)
        self.assertEqual(got["count"], 4)
        self.assertEqual(got["overlapping"], 0)
        self.assertGreaterEqual(got["moved"], 2)
        bx = [SC.label_box(s["text"], s["at"][:2], per, font, margin) for s in shapes[:4]]
        for i in range(4):
            for j in range(i):
                a, b = bx[i], bx[j]
                self.assertFalse(a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3], (shapes[i]["text"], shapes[j]["text"]))
        self.assertTrue(np.allclose(shapes[0]["at"], [-20, -15, 0]))  # the first stays

    def test_per_px_follows_the_framed_box(self):
        per = SC.sheet_per_px((np.array([-20.0, -15, 0]), np.array([20.0, 15, 0])), (1600, 1200))
        self.assertAlmostEqual(per, float(np.linalg.norm([44, 34, 4])) / 1200, places=6)  # padded 2 mm on every side, as frame_sheet
        self.assertIsNone(SC.sheet_per_px((np.zeros(3), np.ones(3)), None))

    def test_the_section_sheet_labels_in_the_facts(self):
        p = Played()
        p.call("section_cut", {"across": "XY", "name": "Sparse"})
        p.call("section_cut", {"across": "XY", "name": "Mid"})
        p.call("flat_fit", {"kind": "line", "box": {"min": [-19, 14], "max": [19, 16]}, "name": "Top"})
        plan, _ = p.call("flat_fit", {"kind": "line", "box": {"min": [-19, -16], "max": [19, -14]}, "name": "Bottom"})
        b = SCC.Builder(texture_coin(), 21, 2.0, (1600, 1200))
        b.build(plan)
        f = SCC.facts(plan, b, 1200, None)["flat"]
        self.assertEqual(f["labels"]["overlapping"], 0, f["labels"])
        self.assertGreater(f["labels"]["count"], 0)


class Keys(unittest.TestCase):
    def fake(self):
        widgets = mock.MagicMock(name="QtWidgets")
        pyside = types.ModuleType("PySide")
        pyside.QtWidgets = widgets
        return {"PySide": pyside, "PySide.QtWidgets": widgets}

    def test_a_key_keeps_its_words(self):
        from scanrulerfc.pages import kit

        class Size:
            def __init__(self, w, h):
                self.w, self.h = w, h

            def width(self):
                return self.w

            def height(self):
                return self.h

        b = mock.MagicMock()
        b.sizeHint.return_value = Size(41, 26)
        with mock.patch.dict(sys.modules, self.fake()):
            kit.key_size(b)
        b.setMinimumWidth.assert_called_with(kit.KEY_MIN_W)
        b.setMinimumHeight.assert_called_with(26)
        b.sizeHint.return_value = Size(120, 26)
        with mock.patch.dict(sys.modules, self.fake()):
            kit.key_size(b)
        b.setMinimumWidth.assert_called_with(120)

    def test_the_page_height_is_set_from_its_layout(self):
        from scanrulerfc.pages import kit

        lay = mock.MagicMock()
        lay.hasHeightForWidth.return_value = True
        lay.totalHeightForWidth.return_value = 900
        lay.totalMinimumSize.return_value.height.return_value = 700
        root = mock.MagicMock()
        root.layout.return_value = lay
        root.minimumHeight.return_value = 0
        root.height.return_value = 640
        low = mock.MagicMock()
        low.isVisible.return_value = True
        low.height.return_value = 6
        low.sizeHint.return_value.height.return_value = 26
        root._grids = [[None, [low], 4, 2]]
        self.addCleanup(kit.LAST_LAYOUT.clear)  # the panel's facts of other tests stay as they were
        got = kit.fit_height(root, 300)
        root.setMinimumHeight.assert_called_with(900)
        self.assertEqual((got["minHeight"], got["squashed"], got["columns"]), (900, 1, [2]))
        self.assertEqual(kit.LAST_LAYOUT["minHeight"], 900)


if __name__ == "__main__":
    unittest.main()
