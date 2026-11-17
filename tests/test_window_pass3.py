# SPDX-License-Identifier: AGPL-3.0-only
# Window pass 3 of ScanRuler's tools in FreeCAD (ScanRuler by Stefan
# Hermann, CNC Kitchen): most captions named the tool with no value, and
# flat_profile's caption was its help text; no flat_ call drew the 2D sheet;
# after the comb of flat_curvature the view stayed zoomed into one corner;
# the edited copy and a wrap preview striped against the solid they lie on;
# a cube stayed in view after reverse_feature_clear. No FreeCAD here:
# stand-ins for coin, the views and the document.
import json
import os
import sys
import tempfile
import types
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

from meshkit import write_png  # noqa: E402
from test_editor_view import _Node, walk  # noqa: E402
from test_scene import Played, stand_in_coin  # noqa: E402

from scanrulerfc import dock as DK  # noqa: E402
from scanrulerfc import echo_words as EW  # noqa: E402
from scanrulerfc import scene as SC  # noqa: E402
from scanrulerfc import scene_coin as SCC  # noqa: E402
from scanrulerfc.reverse import handlers as RH  # noqa: E402


def sheet_png(path):
    """flat-test.png of the flat model: 400 x 300 px at 10 px/mm, a disc of
    radius 8 at [12, 15] mm and a 10 x 6 mm rectangle at x 25..35, y 10..16."""
    H, W = 300, 400
    yy, xx = np.mgrid[0:H, 0:W]
    x, y = (xx + 0.5) / 10, (H - yy - 0.5) / 10
    img = np.full((H, W), 255, np.uint8)
    img[((x - 12) ** 2 + (y - 15) ** 2 <= 64) | ((x >= 25) & (x <= 35) & (y >= 10) & (y <= 16))] = 0
    write_png(path, img, ppm=10000)


def texture_coin():
    """A stand-in coin with what an image's texture and a camera need."""
    coin = stand_in_coin()
    for n in ("SoTexture2", "SoTextureCoordinate2"):
        setattr(coin, n, type(n, (_Node,), {}))
    coin.SbVec2s = lambda w, h: ("SbVec2s", w, h)
    coin.SbRotation = lambda *q: ("SbRotation", q)
    coin.SbBox3f = lambda *v: ("SbBox3f", v)
    return coin


class Camera:
    def __init__(self):
        self.orientation = _Node().orientation
        self.boxes = []

    def viewBoundingBox(self, box, aspect, slack):  # noqa: N802
        self.boxes.append((box, aspect, slack))


class View:
    def __init__(self):
        self.cam = Camera()

    def getCameraNode(self):  # noqa: N802
        return self.cam

    def getSize(self):  # noqa: N802
        return (1600, 1200)


# ---- 1. the words: what each call did, with its key values ------------------------------------------

class Words(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.png = os.path.join(self.dir, "flat-test.png")
        sheet_png(self.png)

    def words(self, p, tool, args=None):
        _plan, out = p.call(tool, args)
        return EW.words(tool, args or {}, out)

    def test_flat_on_a_section(self):
        p = Played()
        p.call("section_cut", {"across": "XY", "name": "Mid"})
        self.assertIn("1 chain, longest 140 mm closed", self.words(p, "flat_edges"))
        self.assertIn("1 chain", self.words(p, "flat_detect_edges"))
        w = self.words(p, "flat_fit", {"kind": "line", "box": {"min": [-19, 14], "max": [19, 16]}, "name": "Top"})
        self.assertIn("Top", w)
        self.assertIn("length 38", w)
        self.words(p, "flat_fit", {"kind": "line", "box": {"min": [-19, -16], "max": [19, -14]}, "name": "Bottom"})
        self.assertIn("30.000 mm", self.words(p, "flat_dimension_add", {"refs": ["Top", "Bottom"], "name": "Width"}))
        w = self.words(p, "flat_profile", {"chains": [0]})
        self.assertNotIn("Radial: radius against angle", w)  # 02-040: the help, not the result
        self.assertRegex(w, r"\d+ peaks, [\d.]+ to [\d.]+ mm")
        self.assertIn("straight", self.words(p, "flat_curvature", {"chains": [0]}))
        self.assertIn('"Ø10 bore" at -4, 7', self.words(p, "flat_note_add", {"text": "Ø10 bore", "at": [-4, 7]}))
        self.assertIn("origin -20, -15", self.words(p, "flat_set_alignment", {"origin": [-20, -15], "xAxis": [20, -15]}))
        w = self.words(p, "flat_report")
        self.assertIn("2 elements, 1 dimension", w)
        self.assertIn("millimetres", w)
        self.assertIn("now Upper", self.words(p, "flat_edit", {"element": "Top", "name": "Upper"}))
        self.assertIn("Mid.svg, 2 elements, 1 chain", self.words(p, "flat_export", {"format": "svg"}))
        w = self.words(p, "flat_remove", {"elements": ["Upper"], "notes": [1]})
        self.assertIn("Removed 1 element, 1 note", w)
        self.assertIn("Width now invalid", w)
        self.assertIn("Cleared", self.words(p, "flat_set_alignment", {"clear": True}))

    def test_flat_on_an_image(self):
        p = Played()
        w = self.words(p, "flat_open_image", {"path": self.png})
        self.assertIn("flat-test.png: 400 × 300 px, 10 px/mm", w)
        self.assertIn("Ø 15.99", self.words(p, "flat_fit", {"kind": "circle", "box": {"min": [3, 6], "max": [21, 24]}, "name": "Disc"}))
        self.assertIn("2 parts", self.words(p, "flat_objects"))
        w = self.words(p, "flat_calibrate", {"mode": "diameter", "points": [[20, 15], [12, 23], [4, 15]], "mm": 32})
        self.assertIn("5 px/mm (127 dpi)", w)
        self.assertIn("CALIBRATED, 5.0000 px/mm", self.words(p, "flat_report"))

    def test_measure_words(self):
        p = Played()
        p.call("element_fit", {"kind": "plane", "at": {"point": [20, 15, 20]}, "name": "Top"})
        p.call("element_fit", {"kind": "plane", "at": {"point": [20, 15, 0]}, "name": "Bottom"})
        p.call("dimension_add", {"refs": ["Top", "Bottom"], "name": "Height"})
        self.assertEqual(self.words(p, "element_set_visible", {"element": "Top", "visible": False}), "Hid Top")
        self.assertEqual(self.words(p, "report_get"), "Measurement report: 2 elements, 1 dimension")

    def test_answers_seen_live(self):
        # Answers as the handlers give them (fitcomp, noise, scan, wear,
        # meshtools, reverse): the words carry their values.
        cases = [
            ("fit_scan_setup", {}, {"settings": {"up": "+z", "band": 1.0, "slicer": "bambustudio"}, "keymaps": [{}, {}, {}], "runs": 0}, ["up +z", "band 1 mm", "bambustudio"]),
            ("fit_scan_features", {}, {"planes": [{}] * 6, "circles": [{"kind": "hole"}], "note": "In the build frame (up as set)."}, ["6 planes", "1 circle", "1 hole"]),
            ("fit_scan_measure", {}, {"run": 1, "fit": 0.4, "poor": False, "scale": {k: {"value": 1.0} for k in "xyz"}, "contour": {"value": 0.002},
                                      "hole": {"value": -0.004}, "slicer": {"changes": []}}, ["run 1", "scale 1/1/1", "contour 0.002 mm", "0 slicer changes"]),
            ("fit_scan_export", {}, {"file": {"name": "fit-run.json"}, "changes": []}, ["fit-run.json", "0 changes"]),
            ("scan_noise", {}, {"sigmaMm": 0.0245, "p90": 0.04, "spacingMm": 0.5, "sampled": 2000}, ["σ 0.0245 mm", "spacing 0.5 mm"]),
            ("scan_pattern", {"axis": "z"}, {"heights": [{"at": 2, "count": 1, "rings": [{"radius": 5.997}]}] * 6}, ["No repeat", "6 heights", "5.997 mm"]),
            ("wear_setup", {}, {"settings": {"tolerance": 0.1}, "tags": [{"name": "pocket"}], "reference": {"source": "deviation", "name": "Block"}},
             ["pocket", "reference Block", "0.1 mm"]),
            ("mesh_trim", {"body": "Stub"}, {"piece": {"name": "Stub", "volume": 499.0, "matingArea": 100.0}, "status": "Trimmed Stub to the break — 499.0 mm³"},
             ["Trimmed Stub", "499 mm³", "100 mm²"]),
            ("mesh_wrap", {"gap": 4, "preview": False}, {"wrap": {"volume": 29468.0}, "edit": {"text": "apply the wrap"},
                                                         "mesh": {"working": "edited copy", "triangles": 26752, "volume": 29468.0}}, ["applied", "26,752", "29,468 mm³"]),
            ("mesh_wrap", {"gap": 4}, {"wrap": {"triangles": 25548, "volume": 24000.0, "shells": 1}, "status": "Wrapped — 1 shell"}, ["preview", "25,548", "24,000 mm³"]),
            ("mesh_boolean", {"op": "subtract"}, {"edit": {"text": "subtract Pin"}, "mesh": {"working": "edited copy", "triangles": 10036, "volume": 22431.2, "open": 0}},
             ["Subtract Pin", "10,036 triangles", "22,431.2 mm³"]),
            ("element_unlink", {"element": "Mid"}, {"element": {"name": "Mid", "source": {"method": "line-coords"}}}, ["Unlinked Mid", "line-coords"]),
            ("element_to_document", {}, {"group": "Scan elements", "made": [{"name": "Top"}, {"name": "Bore"}, {"name": "Corner"}, {"name": "Mirror"}],
                                         "file": {"name": "worn-elements.step"}}, ["4 objects", "Scan elements", "worn-elements.step"]),
            ("reverse_feature_suppress", {"feature": "Round", "suppressed": False}, {"results": [], "failed": [], "bodies": [{"name": "Block", "volume": 22274.69}]},
             ["Resumed Round", "22,274.69 mm³"]),
            ("reverse_feature_suppress", {"feature": "Round"}, {"results": [], "failed": [], "bodies": [{"name": "Block", "volume": 22429.2}]}, ["Suppressed Round"]),
            ("reverse_feature_move", {"features": ["Peg sketch", "Peg"], "after": "Round"}, {"results": [], "failed": [], "bodies": []}, ["Peg sketch, Peg after Round"]),
            ("reverse_body_set", {"body": "Peg", "name": "Dowel", "color": "teal"}, {"bodies": []}, ["now Dowel", "teal"]),
            ("reverse_body_clearance", {}, {"a": 2, "b": 7, "gap": 0, "overlap": 480.69}, ["overlap", "480.69 mm³"]),
            ("reverse_feature_clear", {"confirm": True}, {"results": [], "bodies": [], "steps": {}}, ["Cleared", "no bodies"]),
        ]
        for tool, args, body, want in cases:
            with self.subTest(tool=tool):
                w = EW.words(tool, args, body)
                self.assertIsNotNone(w)
                for x in want:
                    self.assertIn(x, w)

    def test_every_tool_says_something(self):
        # Every ScanRuler tool gives its own words (never None, so Agent
        # Link's fallback, the tool's name or its help, never shows) for an
        # answer with a value in it, and they are not the tool's help text.
        with open(EW.DATA, encoding="utf-8") as f:
            entries = json.load(f)["entries"]
        body = {"file": {"name": "out.stl"}, "count": 3, "note": "Radial: radius against angle about the centre."}
        quiet = {"element_rename", "element_set_visible", "flat_fit", "mesh_trim"}  # their words need their own answer's key
        for name in sorted(EW.OWN):
            with self.subTest(tool=name):
                w = EW.words(name, {}, body)
                if name in quiet:
                    continue
                self.assertIsNotNone(w)
                self.assertNotIn("Radial: radius", w)
                self.assertNotIn(entries[name]["description"][:40], w)

    def test_other_tools_are_left_alone(self):
        # Agent Link asks every add-on for every call: part_boolean, export
        # and the Mesh workbench's tools keep their own words.
        for name in ("part_boolean", "export", "meshobj_boundary", "doc_save", "texture_apply"):
            self.assertIsNone(EW.words(name, {}, {"file": {"name": "x.step"}, "status": "done"}))


# ---- 2. the 2D sheet drawn in the 3D view ------------------------------------------------------------

class Sheet(unittest.TestCase):
    def test_section_sheet(self):
        p = Played()
        p.call("element_fit", {"kind": "plane", "at": {"point": [20, 15, 20]}, "name": "Top3D"})
        p.call("section_cut", {"across": "XY", "name": "Mid"})
        plan, _ = p.call("flat_fit", {"kind": "line", "box": {"min": [-19, 14], "max": [19, 16]}, "name": "Top"})
        fl = plan["flat"]
        self.assertEqual(fl["kind"], "section")
        # The sheet lies on the section's plane, z 10, over the 40 x 30 box.
        self.assertTrue(np.allclose(fl["corners"][:, 2], 10.0))
        self.assertLess(fl["corners"][:, 0].min(), 0.0)
        self.assertGreater(fl["corners"][:, 0].max(), 40.0)
        # The 3D Measure's elements are not drawn on the 2D sheet; the section is.
        self.assertEqual(plan["elements"], [])
        self.assertEqual(len(plan["sections"]), 1)
        top = next(i for i in fl["items"] if i.get("name") == "Top")
        self.assertTrue(top["new"])
        line = top["lines"][0]
        self.assertTrue(np.allclose(line[:, 1], 30.0))  # y 15 on the sheet: the part's back edge, y 30
        p.call("flat_fit", {"kind": "line", "box": {"min": [-19, -16], "max": [19, -14]}, "name": "Bottom"})
        plan, _ = p.call("flat_dimension_add", {"refs": ["Top", "Bottom"], "name": "Width"})
        dim = next(i for i in plan["flat"]["items"] if i["kind"] == "flatDimension")
        self.assertIn("Width 30.000", dim["text"])
        self.assertTrue(dim["new"])
        self.assertFalse(next(i for i in plan["flat"]["items"] if i.get("name") == "Top")["new"])
        plan, _ = p.call("flat_note_add", {"text": "Ø10 bore", "at": [-4, 7]})
        note = next(i for i in plan["flat"]["items"] if i["kind"] == "flatNote")
        self.assertTrue(np.allclose(note["at"], [16, 22, 10]))
        plan, _ = p.call("flat_set_alignment", {"origin": [-20, -15], "xAxis": [20, -15]})
        self.assertTrue(any(i["kind"] == "flatOrigin" and i["new"] for i in plan["flat"]["items"]))
        # A 3D call after: the 3D results again, no sheet.
        plan, _ = p.call("element_list")
        self.assertIsNone(plan["flat"])
        self.assertEqual(len(plan["elements"]), 1)

    def test_image_sheet_hides_the_scan(self):
        d = tempfile.mkdtemp()
        png = os.path.join(d, "flat-test.png")
        sheet_png(png)
        p = Played()
        p.call("element_fit", {"kind": "plane", "at": {"point": [20, 15, 20]}, "name": "Top3D"})
        plan, _ = p.call("flat_open_image", {"path": png})
        fl = plan["flat"]
        self.assertEqual(fl["kind"], "image")
        self.assertEqual(plan["scan"], {"hide": True})
        self.assertEqual(plan["elements"], [])
        self.assertTrue(np.allclose(fl["corners"], [[0, 0, 0], [40, 0, 0], [40, 30, 0], [0, 30, 0]]))
        self.assertEqual(fl["counts"]["chains"], 6)
        plan, _ = p.call("flat_calibrate", {"mode": "diameter", "points": [[20, 15], [12, 23], [4, 15]], "mm": 32})
        self.assertTrue(np.allclose(plan["flat"]["corners"][2], [80, 60, 0]))  # 5 px/mm now
        plan, _ = p.call("element_list")
        self.assertEqual(plan["scan"], {"hide": False})

    def test_image_texture_and_framing(self):
        d = tempfile.mkdtemp()
        png = os.path.join(d, "flat-test.png")
        sheet_png(png)
        p = Played()
        plan, _ = p.call("flat_open_image", {"path": png})
        coin = texture_coin()
        b = SCC.Builder(coin, 13, 2.0, (1600, 1200))
        root = b.build(plan)
        self.assertIsNotNone(root)
        texs = [n for n in walk(root) if type(n).__name__ == "SoTexture2"]
        self.assertEqual(len(texs), 1)
        size, comps, data = texs[0].image.value
        self.assertEqual((size[1], size[2], comps), (400, 300, 1))
        self.assertEqual(len(data), 400 * 300)
        # Bottom row first (OpenGL's order): the disc reaches y 7..23 mm, so
        # row 0 (y 0.05 mm) is white and row 150 (y 15 mm) crosses the disc.
        g = np.frombuffer(data, np.uint8).reshape(300, 400)
        self.assertEqual(int(g[0].min()), 255)
        self.assertEqual(int(g[150, 120]), 0)
        self.assertEqual(b.texture, [400, 300])
        # The camera turned to look down -Z (x right, y up) and framed on the sheet.
        v = View()
        got = SCC.frame_sheet(coin, [v], plan["flat"])
        self.assertEqual(got["views"], 1)
        self.assertEqual(got["look"], [0.0, 0.0, -1.0])
        self.assertEqual(v.cam.orientation.value[0], "SbRotation")
        box = v.cam.boxes[0][0][1]
        self.assertLess(box[0], 0.0)
        self.assertGreater(box[3], 40.0)
        f = SCC.facts(plan, b, 1200, got)["flat"]
        self.assertEqual((f["sheet"], f["texture"], f["scanHidden"]), ("image", [400, 300], True))

    def test_section_sheet_framed_square_on(self):
        p = Played()
        p.call("section_cut", {"across": "XZ", "name": "Front"})
        plan, _ = p.call("flat_edges")
        coin = texture_coin()
        v = View()
        got = SCC.frame_sheet(coin, [v], plan["flat"])
        fr = plan["flat"]["frame"]
        n = np.cross(fr["basisU"], fr["basisV"])
        self.assertTrue(np.allclose(got["look"], -n, atol=1e-4))

    def test_no_texture_on_a_stand_in(self):
        # A coin without SoTexture2: the edges and elements are still drawn,
        # and the facts say why there is no texture.
        d = tempfile.mkdtemp()
        png = os.path.join(d, "flat-test.png")
        sheet_png(png)
        p = Played()
        plan, _ = p.call("flat_open_image", {"path": png})
        b = SCC.Builder(stand_in_coin(), 13, 2.0, (1600, 1200))
        root = b.build(plan)
        self.assertIsNotNone(root)
        self.assertIn("SoTexture2", b.texture)
        self.assertTrue(any(type(n).__name__ == "SoLineSet" for n in walk(root)))

    def test_camera_rotation(self):
        for u, v in (([1, 0, 0], [0, 1, 0]), ([0, 1, 0], [0, 0, 1]), ([0.6, 0.8, 0], [0, 0, 1]), ([-1, 0, 0], [0, 1, 0])):
            q = SC.camera_rotation(u, v)
            self.assertAlmostEqual(float(np.linalg.norm(q)), 1.0)
            self.assertTrue(np.allclose(SC.rotate_by(q, [1, 0, 0]), u, atol=1e-9))
            self.assertTrue(np.allclose(SC.rotate_by(q, [0, 1, 0]), v, atol=1e-9))

    def test_header_names_the_image(self):
        st = {"scan": types.SimpleNamespace(name="Plate mesh"), "flatState": {"subject": {"kind": "image", "name": "flat-test.png"}}}
        self.assertEqual(DK.header(st, "ScanFlatModel", workspace="flat")["title"], "ScanFlatModel · flat-test.png")
        self.assertEqual(DK.header(st, "ScanFlatModel", workspace="measure")["title"], "ScanFlatModel · Plate mesh")


# ---- 3. overlays in front of the surface they lie on ---------------------------------------------------

class InFront(unittest.TestCase):
    def test_edited_copy_and_preview_offset(self):
        V = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], float)
        F = np.array([[0, 1, 2]])
        plan = {"mesh": (V, F), "previews": [("wrap", V, F)], "map": None, "elements": [], "dimensions": [], "sections": [], "items": []}
        b = SCC.Builder(stand_in_coin(), 13, 1.0)
        root = b.build(plan)
        offs = [n for n in walk(root) if type(n).__name__ == "SoPolygonOffset"]
        self.assertEqual([o.factor.value for o in offs], [-1.0, -SCC.PREVIEW_OFFSET])
        self.assertEqual(b.offsets, ["editedCopy", "wrap"])
        self.assertEqual(SCC.facts(plan, b)["inFront"], ["editedCopy", "wrap"])


# ---- 4. what the document shows after reverse_feature_clear ------------------------------------------

class AfterClear(unittest.TestCase):
    def test_shown_after_clear(self):
        class Shape:
            def __init__(self, null=False):
                self.null = null

            def isNull(self):  # noqa: N802
                return self.null

        def obj(label, type_id, shown=True, proxy=None, null=False):
            return types.SimpleNamespace(Label=label, TypeId=type_id, Visibility=shown, Shape=Shape(null), Proxy=proxy)

        BodyProxy = type("Body", (), {"__module__": "scanrulerfc.reverse.doc"})
        doc = types.SimpleNamespace(Objects=[obj("Reverse engineer", "Part::FeaturePython"), obj("Gauge", "Part::Box"),
                                             obj("Hidden", "Part::Box", shown=False), obj("Empty", "Part::Feature", null=True),
                                             obj("Block", "Part::FeaturePython", proxy=BodyProxy())])
        self.assertEqual(RH.shown_after_clear(doc), ["Gauge (Part::Box)", "Block (a Reverse engineer body: not cleared)"])
        self.assertIsNone(RH.shown_after_clear(None))


if __name__ == "__main__":
    unittest.main()
