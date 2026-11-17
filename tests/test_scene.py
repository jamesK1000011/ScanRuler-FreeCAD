# SPDX-License-Identifier: AGPL-3.0-only
# ScanRuler's results in FreeCAD's 3D view (scanrulerfc/scene.py,
# scene_coin.py), the window echo's tables (echo_words.py), the NaN-free
# maths of segment.py and heightmap_core.covered, and the panel drawn again
# on an undo (dock.history_mark). Window review round 3: the panel listed
# every result while the view showed only the grey scan; no map had a
# colour or a legend; Mesh Tools' edits were not shown; RuntimeWarnings in
# the Report view. No FreeCAD here: stand-ins for coin and the window.
import copy
import math
import os
import sys
import types
import unittest
import warnings

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

import synth  # noqa: E402
from test_editor_view import _Field, _Node, walk  # noqa: E402

from scanrulerfc import dock as DK  # noqa: E402
from scanrulerfc import echo_words as EW  # noqa: E402
from scanrulerfc import runner  # noqa: E402
from scanrulerfc import scanstate as S  # noqa: E402
from scanrulerfc import scene as SC  # noqa: E402
from scanrulerfc import scene_coin as SCC  # noqa: E402


def rotated(P, deg):
    a = math.radians(deg)
    R = np.array([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]])
    return P @ R.T


def box_session(deg=0.0):
    P, F = synth.box(size=(40, 30, 20), sigma=0.0)
    ctx = runner.Context(None, "/tmp")
    S.state(ctx)["scan"] = S.Scan("box.stl", rotated(P, deg) if deg else P, F)
    return ctx, runner.local(ctx=ctx)


class Played:
    """A session, its runner and the scene's memo, one call at a time."""

    def __init__(self, deg=0.0):
        self.ctx, self.run = box_session(deg)
        self.memo = {}

    def call(self, tool, args=None, ok=True):
        got, out = self.run(tool, dict(args or {}))
        if ok:
            assert got, f"{tool}: {out}"
        return SC.plan(self.ctx, tool, args, out, self.memo), out


def stand_in_coin():
    coin = types.ModuleType("coin_stand_in")
    for n in ("SoSeparator", "SoAnnotation", "SoShapeHints", "SoMaterial", "SoMaterialBinding", "SoCoordinate3", "SoIndexedFaceSet",
              "SoBaseColor", "SoDrawStyle", "SoLineSet", "SoPointSet", "SoFaceSet", "SoTranslation", "SoFont", "SoText2",
              "SoPickStyle", "SoPolygonOffset", "SoOrthographicCamera", "SoLightModel", "SoCamera"):
        setattr(coin, n, type(n, (_Node,), {}))
    coin.SoShapeHints.COUNTERCLOCKWISE, coin.SoShapeHints.UNKNOWN_SHAPE_TYPE = 1, 0
    coin.SoMaterialBinding.PER_VERTEX_INDEXED = 5
    coin.SoPickStyle.UNPICKABLE = 2
    coin.SoCamera.LEAVE_ALONE = 4
    coin.SoLightModel.BASE_COLOR = 0
    return coin


class Graph(_Node):
    """A view's scene graph."""

    def findChild(self, c):  # noqa: N802
        return self.children.index(c) if c in self.children else -1


class View3D:
    def __init__(self):
        self.sg = Graph()

    def getSceneGraph(self):  # noqa: N802
        return self.sg


class Switch:
    def __init__(self, child=0):
        self.whichChild = _Field()
        self.whichChild.setValue(child)


class ViewObject:
    def __init__(self):
        self.Visibility = True
        self.SwitchNode = Switch(0)


class Obj:
    def __init__(self, name, role=None):
        self.Name = self.Label = name
        self.ViewObject = ViewObject()
        if role:
            self.ScanRulerRole = role


class Doc:
    def __init__(self, *objs):
        self.Name = "Part"
        self.Objects = list(objs)

    def getObject(self, n):  # noqa: N802
        return next((o for o in self.Objects if o.Name == n), None)

    def openTransaction(self, name):  # noqa: N802
        pass

    def commitTransaction(self):  # noqa: N802
        pass

    def abortTransaction(self):  # noqa: N802
        pass


class GuiDoc:
    def __init__(self, views):
        self.views = views

    def mdiViewsOfType(self, t):  # noqa: N802
        return list(self.views) if t == "Gui::View3DInventor" else []


class Gui:
    def __init__(self, views):
        self.gd = GuiDoc(views)

    def getDocument(self, name):  # noqa: N802
        return self.gd


# ---- what the view shows -----------------------------------------------------------------------


class Shapes(unittest.TestCase):
    def test_plane_is_its_patch_with_a_face(self):
        sh = SC.element_shape({"kind": "plane", "center": [0, 0, 5], "normal": [0, 0, 1], "extentU": 10, "extentV": 4})
        rect = sh["lines"][0]
        self.assertEqual(len(rect), 5)
        np.testing.assert_allclose(rect[0], rect[-1])
        np.testing.assert_allclose(rect[:, 2], 5)
        self.assertAlmostEqual(np.ptp(rect[:, 0]) * np.ptp(rect[:, 1]), 20 * 8)
        self.assertEqual(sh["face"].shape, (4, 3))

    def test_cylinder_rims_at_its_radius_and_ends(self):
        sh = SC.element_shape({"kind": "cylinder", "center": [1, 2, 3], "axis": [0, 0, 1], "radius": 6, "length": 10})
        ra, rb = sh["lines"][0], sh["lines"][1]
        np.testing.assert_allclose(np.linalg.norm(ra[:, :2] - [1, 2], axis=1), 6, atol=1e-9)
        np.testing.assert_allclose(ra[:, 2], -2)
        np.testing.assert_allclose(rb[:, 2], 8)
        assumed = SC.element_shape({"kind": "cylinder", "center": [0, 0, 0], "axis": [0, 0, 1], "radius": 6, "length": 10}, assumed=10)
        np.testing.assert_allclose(np.linalg.norm(assumed["lines"][0][:, :2], axis=1), 5, atol=1e-9)

    def test_every_kind_draws_or_says_none(self):
        fits = [{"kind": "point", "center": [0, 0, 0]}, {"kind": "line", "center": [0, 0, 0], "dir": [1, 0, 0], "length": 4},
                {"kind": "circle", "center": [0, 0, 0], "normal": [0, 0, 1], "radius": 2},
                {"kind": "sphere", "center": [0, 0, 0], "radius": 3},
                {"kind": "cone", "center": [0, 0, 0], "axis": [0, 0, 1], "radius1": 2, "radius2": 1, "length": 3},
                {"kind": "torus", "center": [0, 0, 0], "axis": [0, 0, 1], "majorRadius": 5, "minorRadius": 1}]
        for f in fits:
            sh = SC.element_shape(f)
            self.assertTrue(sh["lines"] or sh["points"], f["kind"])
            for ln in sh["lines"]:
                self.assertTrue(np.isfinite(ln).all())
        self.assertIsNone(SC.element_shape({"kind": "plane"}))
        self.assertIsNone(SC.element_shape(None))


class Plans(unittest.TestCase):
    def test_fits_dimensions_sections_drawn_and_the_new_one_marked(self):
        p = Played()
        sc, _ = p.call("element_fit", {"kind": "plane", "at": {"point": [20, 15, 20]}, "name": "Top"})
        self.assertEqual([(e["name"], e["new"]) for e in sc["elements"]], [("Top", True)])
        self.assertEqual(sc["elements"][0]["colour"], SC.NEW)
        sc, _ = p.call("element_fit", {"kind": "plane", "at": {"point": [20, 15, 0]}, "name": "Bottom"})
        self.assertEqual([(e["name"], e["new"]) for e in sc["elements"]], [("Top", False), ("Bottom", True)])
        self.assertEqual(sc["elements"][0]["colour"], SC.ELEMENT)
        sc, _ = p.call("dimension_add", {"refs": ["Top", "Bottom"], "type": "dist-plane-plane", "name": "Height"})
        (dm,) = sc["dimensions"]
        self.assertEqual(dm["text"], "Height 20.000 mm")
        self.assertTrue(dm["new"])
        a, b = dm["lines"][0]
        self.assertAlmostEqual(float(np.linalg.norm(a - b)), 20.0, places=6)
        self.assertEqual(sorted([a[2], b[2]]), [0.0, 20.0])
        sc, _ = p.call("section_cut", {"across": "XY", "offset": 10, "name": "Mid"})
        (sec,) = sc["sections"]
        self.assertTrue(sec["new"])
        np.testing.assert_allclose(np.vstack(sec["lines"])[:, 2], 10, atol=1e-9)
        sc, _ = p.call("element_set_visible", {"element": "Top", "visible": False})
        self.assertEqual([e["name"] for e in sc["elements"]], ["Bottom"])

    def test_an_alignment_marks_nothing_new(self):
        p = Played()
        p.call("element_fit", {"kind": "plane", "at": {"point": [20, 15, 20]}, "name": "Top"})
        sc, _ = p.call("align_auto")
        self.assertFalse(any(e["new"] for e in sc["elements"]))

    def test_marked_points_and_nearest_only_for_their_call(self):
        p = Played()
        sc, _ = p.call("scan_query", {"box": {"min": [-1, -1, 19], "max": [41, 31, 21]}, "mark": True})
        (m,) = [i for i in sc["items"] if i["kind"] == "marked"]
        self.assertEqual(len(m["points"]), 1411)
        sc, _ = p.call("scan_nearest", {"at": {"point": [20, 15, 25]}})
        (n,) = sc["items"]
        self.assertEqual(n["kind"], "nearest")
        np.testing.assert_allclose(n["points"][0], [20, 15, 20])
        self.assertEqual(n["text"], "5.000 mm")
        self.assertEqual(len(n["lines"]), 1)  # from the point asked for to the one found
        sc, _ = p.call("scan_info")
        self.assertEqual(sc["items"], [])

    def test_map_with_legend_kept_by_its_family_and_gone_after(self):
        p = Played()
        st = S.state(p.ctx)
        scan = st["scan"]
        values = np.linspace(-2, 2, len(scan.V))
        st["deviation"] = {"reference": None, "align": None, "scan": scan, "version": scan.version, "values": values, "source": "reference",
                           "target": None, "range": 1.0, "maxDistance": 3.0, "bands": None, "tolerance": 0.1}
        sc = SC.plan(p.ctx, "deviation_measure", {}, {}, p.memo)
        lay = sc["map"]
        self.assertEqual(lay["kind"], "deviation")
        self.assertEqual(lay["rgb"].shape, (len(scan.V), 3))
        self.assertTrue(((lay["rgb"] >= 0) & (lay["rgb"] <= 1)).all())
        self.assertEqual(lay["legend"]["caption"], "DEVIATION · MM")
        self.assertEqual(lay["legend"]["ticks"][0]["text"], "−1.000")
        # the colours are the panel's: jet, blue low, red high, the caps past ±range
        np.testing.assert_allclose(lay["rgb"][len(values) // 2], np.array([0, 200, 0]) / 255, atol=0.02)
        self.assertEqual(SC.plan(p.ctx, "deviation_hotspots", {}, {}, p.memo)["map"]["kind"], "deviation")
        self.assertIsNone(SC.plan(p.ctx, "element_list", {}, {}, p.memo)["map"])
        # a map of another scan (or of this one before a move) is not drawn
        st["deviation"]["version"] = scan.version + 1
        self.assertIsNone(SC.plan(p.ctx, "deviation_measure", {}, {}, p.memo)["map"])

    def test_thickness_draft_height_and_segments_maps(self):
        p = Played()
        sc, _ = p.call("thickness_measure", {"maxThickness": 50})
        self.assertEqual(sc["map"]["kind"], "thickness")
        self.assertTrue(sc["map"]["legend"]["reversed"])
        sc, _ = p.call("scan_draft", {"pull": [0, 0, 1]})
        lay = sc["map"]
        self.assertEqual(lay["kind"], "draft")
        walls = np.isfinite(lay["values"])
        self.assertGreater(walls.sum(), 0)
        np.testing.assert_allclose(lay["values"][walls], 0, atol=1e-6)  # a box's walls stand along the pull
        self.assertEqual(lay["legend"]["ticks"][-1]["text"], "10°")
        sc, out = p.call("scan_heightmap", {"axis": "-z"})
        self.assertEqual(sc["map"]["kind"], "height")
        sc, out = p.call("scan_segment", {})
        self.assertEqual(sc["map"]["kind"], "segments")
        self.assertIsNone(sc["map"]["legend"])
        self.assertEqual(sc["map"]["count"], out["found"])
        self.assertGreater(len({tuple(c) for c in sc["map"]["rgb"].round(3)}), 2)

    def test_outline_and_cut_plane(self):
        p = Played()
        sc, _ = p.call("scan_outline", {"axis": "-z"})
        (o,) = sc["items"]
        ln = o["lines"][0]
        np.testing.assert_allclose(ln[:, 2], 20)  # on the face toward the eye
        self.assertAlmostEqual(np.ptp(ln[:, 0]), 40, places=3)
        sc, _ = p.call("mesh_cut_preview", {"plane": "XY", "offset": 15})
        (c,) = sc["items"]
        np.testing.assert_allclose(c["face"][:, 2], 15)

    def test_edited_copy_in_place_of_the_scan_till_used(self):
        p = Played()
        sc, _ = p.call("mesh_cut", {"plane": "XY", "offset": 15, "keep": "minus"})
        V, F = sc["mesh"]
        self.assertTrue(sc["scan"]["hide"])
        self.assertLessEqual(V[:, 2].max(), 15 + 1e-9)
        self.assertIsNone(sc["map"])  # a map of the scan is not laid on the copy
        sc, _ = p.call("mesh_use_edited")
        self.assertIsNone(sc["mesh"])
        self.assertFalse(sc["scan"]["hide"])
        sc, _ = p.call("mesh_flip_normals")
        self.assertTrue(sc["scan"]["hide"])
        sc, _ = p.call("mesh_discard_edited")
        self.assertFalse(sc["scan"]["hide"])

    def test_drawing_leaves_the_state_as_it_was(self):
        from scanrulerfc import docstate

        p = Played()
        p.call("element_fit", {"kind": "plane", "at": {"point": [20, 15, 20]}, "name": "Top"})
        st = S.state(p.ctx)
        before = docstate.signature(st)
        keys = set(st)
        for tool in ("deviation_measure", "thickness_settings", "wear_diff", "mesh_parts", "scan_draft", "scan_segment"):
            SC.plan(p.ctx, tool, {"pull": [0, 0, 1]}, {}, p.memo)
        self.assertEqual(set(st), keys)
        self.assertEqual(docstate.signature(st), before)

    def test_no_scan_nothing(self):
        ctx = runner.Context(None, "/tmp")
        sc = SC.plan(ctx, "scan_info", {}, {}, {})
        self.assertIsNone(sc["scan"])
        self.assertEqual(sc["elements"], [])


# ---- the Coin nodes and the window ------------------------------------------------------------------


class Coin(unittest.TestCase):
    def setUp(self):
        self.coin = stand_in_coin()

    def test_nothing_to_draw_is_none(self):
        self.assertIsNone(SCC.Builder(self.coin).build({"elements": [], "items": []}))

    def test_scene_unpickable_named_with_map_and_legend(self):
        p = Played()
        p.call("element_fit", {"kind": "plane", "at": {"point": [20, 15, 20]}, "name": "Top"})
        sc, _ = p.call("thickness_measure", {"maxThickness": 50})
        scan = S.state(p.ctx)["scan"]
        sc["scanVF"] = (scan.V, scan.F)
        root = SCC.Builder(self.coin).build(sc)
        self.assertEqual(root.name, SCC.NODE_NAME)
        self.assertEqual(root.children[0].style.getValue(), self.coin.SoPickStyle.UNPICKABLE)
        nodes = list(walk(root))
        binds = [n for n in nodes if type(n).__name__ == "SoMaterialBinding"]
        self.assertEqual(binds[0].value.getValue(), 5)
        mats = [n for n in nodes if type(n).__name__ == "SoMaterial" and isinstance(n.diffuseColor.getValue(), list)]
        self.assertEqual(len(mats[0].diffuseColor.getValue()), len(scan.V))
        self.assertTrue(any(type(n).__name__ == "SoPolygonOffset" for n in nodes))
        texts = [n.string.getValue() if hasattr(n.string, "getValue") else n.string for n in nodes if type(n).__name__ == "SoText2"]
        self.assertIn("Top", texts)
        self.assertTrue(any("WALL THICKNESS" in str(t) for t in texts))  # the legend's caption
        self.assertTrue(any(type(n).__name__ == "SoOrthographicCamera" for n in nodes))

    def test_window_puts_one_node_per_view_and_swaps_it(self):
        p = Played()
        scan_obj = Obj("ScanRulerScan", "scan")
        p.ctx.doc = Doc(scan_obj)
        views = [View3D(), View3D()]
        w = SCC.Window(Gui(views), self.coin)
        got = w.show(p.ctx, "element_fit", {}, {})
        self.assertFalse(got["drawn"])  # nothing yet
        p.run("element_fit", {"kind": "plane", "at": {"point": [20, 15, 20]}, "name": "Top"})
        got = w.show(p.ctx, "element_fit", {}, {})
        self.assertEqual((got["drawn"], got["views"], got["elements"], got["new"]), (True, 2, 1, ["Top"]))
        first = views[0].sg.children[0]
        w.show(p.ctx, "element_list", {}, {})
        self.assertEqual(len(views[0].sg.children), 1)
        self.assertIsNot(views[0].sg.children[0], first)

    def test_edited_copy_switches_the_scan_off_and_back(self):
        p = Played()
        scan_obj = Obj("ScanRulerScan", "scan")
        p.ctx.doc = Doc(scan_obj)
        w = SCC.Window(Gui([View3D()]), self.coin)
        p.run("mesh_cut", {"plane": "XY", "offset": 15, "keep": "minus"})
        got = w.show(p.ctx, "mesh_cut", {}, {})
        self.assertEqual((got["editedCopy"], got["scan"]), (True, "hidden"))
        self.assertEqual(scan_obj.ViewObject.SwitchNode.whichChild.getValue(), -1)
        self.assertTrue(scan_obj.ViewObject.Visibility)  # what is saved is left alone
        p.run("mesh_discard_edited", {})
        got = w.show(p.ctx, "mesh_discard_edited", {}, {})
        self.assertEqual(got["scan"], "shown")
        self.assertEqual(scan_obj.ViewObject.SwitchNode.whichChild.getValue(), 0)

    def test_a_scan_the_person_hid_stays_hidden(self):
        p = Played()
        scan_obj = Obj("ScanRulerScan", "scan")
        scan_obj.ViewObject.SwitchNode.whichChild.setValue(-1)
        p.ctx.doc = Doc(scan_obj)
        w = SCC.Window(Gui([View3D()]), self.coin)
        p.run("mesh_cut", {"plane": "XY", "offset": 15, "keep": "minus"})
        w.show(p.ctx, "mesh_cut", {}, {})
        p.run("mesh_discard_edited", {})
        self.assertIsNone(w.show(p.ctx, "mesh_discard_edited", {}, {})["scan"])
        self.assertEqual(scan_obj.ViewObject.SwitchNode.whichChild.getValue(), -1)


class Touched(unittest.TestCase):
    def test_headless_draws_nothing(self):
        calls = []
        old = SCC.after_call
        SCC.after_call = lambda *a, **k: calls.append(a)
        try:
            p = Played()
            p.run("element_fit", {"kind": "plane", "at": {"point": [20, 15, 20]}, "name": "Top"})
        finally:
            SCC.after_call = old
        self.assertEqual(calls, [])

    def test_with_a_window_the_call_is_drawn_with_its_answer(self):
        calls = []
        fake = types.ModuleType("FreeCAD")
        fake.GuiUp = True
        old_fc, old = sys.modules.get("FreeCAD"), SCC.after_call
        sys.modules["FreeCAD"] = fake
        SCC.after_call = lambda *a: calls.append(a)
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
        (c,) = calls
        self.assertEqual(c[1], "scan_nearest")
        self.assertEqual(c[2], {"at": {"point": [20, 15, 25]}})
        self.assertEqual(c[3]["distance"], 5.0)


# ---- the echo's tables -----------------------------------------------------------------------------


class Echo(unittest.TestCase):
    def test_reads_that_bring_the_bench_up(self):
        for n in ("scan_open", "scan_info", "scan_qa", "mesh_smooth", "mesh_cut", "deviation_align", "section_cut", "element_list"):
            self.assertIn(n, EW.OPENS)
        for n in ("scan_snapshot_list", "scan_snapshot_latest", "element_fit", "catalog_part", "manual_plan"):
            self.assertNotIn(n, EW.OPENS)

    def test_keys(self):
        self.assertEqual(EW.command_for("element_construct", {"kind": "plane"}), "ScanRuler_ElementPlane")
        self.assertEqual(EW.command_for("element_fit_marked", {"kind": "cylinder"}), "ScanRuler_ElementCylinder")
        self.assertEqual(EW.command_for("element_fit", {"kind": "point"}), "ScanRuler_ElementPoint")
        self.assertEqual(EW.command_for("align_auto", {}), "ScanRuler_AutoAlign")
        self.assertEqual(EW.COMMANDS["scan_open"], "ScanRuler_OpenScan")

    def test_words_carry_the_measured_value(self):
        p = Played()
        cases = [("scan_nearest", {"at": {"point": [20, 15, 25]}}, "5 mm away"),
                 ("scan_query", {"box": {"min": [-1, -1, 19], "max": [41, 31, 21]}, "mark": True}, "Marked 1,411 scan points"),
                 ("element_fit", {"kind": "plane", "at": {"point": [20, 15, 20]}, "name": "Top"}, "Fitted Top (plane"),
                 ("element_fit", {"kind": "plane", "at": {"point": [20, 15, 0]}, "name": "Bottom"}, "Bottom"),
                 ("dimension_add", {"refs": ["Top", "Bottom"], "type": "dist-plane-plane", "name": "Height"}, "Height = 20.000 mm"),
                 ("section_cut", {"across": "XY", "offset": 10, "name": "Mid"}, "Cut section Mid: XY plane at 10 mm"),
                 ("scan_segment", {}, "6 flat or round regions"),
                 ("scan_heightmap", {"axis": "-z"}, "Height map along z: 20 to 20 mm"),
                 ("thickness_measure", {"maxThickness": 50}, "Wall thickness: "),
                 ("align_auto", {}, "moved 25 mm"),
                 ("mesh_cut", {"plane": "XY", "offset": 15, "keep": "minus"}, "Cut at XY plane, Z 15 mm: edited copy"),
                 ("mesh_undo", {}, "Undid cut at XY plane")]
        for tool, args, want in cases:
            ok, out = p.run(tool, args)
            self.assertTrue(ok, f"{tool}: {out}")
            self.assertIn(want, EW.words(tool, args, out) or "", tool)
        self.assertIsNone(EW.words("scan_open", {}, "not an answer"))

    def test_selects_the_scan_object_not_the_mesh_it_came_from(self):
        from scanrulerfc import docstate

        doc = Doc(Obj("WornScan"), Obj("ScanRulerScan", "scan"))
        old = docstate.find_state
        docstate.find_state = lambda d: None
        try:
            self.assertEqual(EW.selects("scan_open", {"object": "WornScan"}, {}, doc), ["ScanRulerScan"])
            self.assertIsNone(EW.selects("element_fit", {}, {}, doc))
        finally:
            docstate.find_state = old

    def test_phrases_name_only_top_level_fields(self):
        import re

        for tool, ts in EW.PHRASES.items():
            for t in ts:
                for f in re.findall(r"\{([^}]*)\}", t):
                    self.assertRegex(f, r"^\w+(=[\w.-]+)?$", f"{tool}: {t}")


# ---- maths that wrote RuntimeWarnings to the Report view ------------------------------------------


class NoNaN(unittest.TestCase):
    def test_outline_and_segments_of_a_turned_block_warn_nothing(self):
        # A block turned 37° about Z: its walls stand edge-on to the -z look
        # (outline: inf - inf in heightmap_core.covered) and its flat faces'
        # unit normals dot a rounding over 1 (segment: sqrt of a negative).
        ctx, run = box_session(37)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            for tool, args in (("scan_outline", {"axis": "-z"}), ("scan_segment", {}), ("scan_heightmap", {"axis": "-z"})):
                ok, out = run(tool, args)
                self.assertTrue(ok, f"{tool}: {out}")
        self.assertEqual(out["hit"], out["valued"])

    def test_segments_unchanged(self):
        ctx, run = box_session(37)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ok, out = run("scan_segment", {})
        self.assertEqual(out["found"], 6)
        self.assertEqual(sorted(r["vertices"] for r in out["regions"]), [551, 551, 741, 741, 1131, 1131])

    def test_covered_edge_on_triangle(self):
        from scanrulerfc import heightmap_core as HM

        ctx, run = box_session(37)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            ok, out = run("scan_outline", {"axis": "-z"})
        self.assertTrue(ok, out)
        (lp,) = out["loops"]
        self.assertAlmostEqual(lp["area"], 1200, delta=15)


# ---- the panel follows an undo ------------------------------------------------------------------------


class History(unittest.TestCase):
    def test_mark_moves_on_undo_and_redo(self):
        doc = types.SimpleNamespace(UndoCount=3, RedoCount=0)
        m0 = DK.history_mark(doc)
        doc.UndoCount, doc.RedoCount = 2, 1
        self.assertNotEqual(DK.history_mark(doc), m0)
        self.assertIsNone(DK.history_mark(None))
        self.assertIsNone(DK.history_mark(object()))
