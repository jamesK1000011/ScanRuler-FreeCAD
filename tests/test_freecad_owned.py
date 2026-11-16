# SPDX-License-Identifier: AGPL-3.0-only
# ScanRuler's global features that FreeCAD already owns, given to FreeCAD
# (ScanRuler by Stefan Hermann, CNC Kitchen, ported): the state lives in the
# document so FreeCAD's New, Open and Save carry it; Move / rotate by
# numbers is Std_Placement on the scan object, the elements following; the
# view bar's show, Transparent and Mesh keys are the objects' own
# Visibility, Transparency and DisplayMode; Section is Std_ToggleClipPlane;
# the settings a Preferences page. On a stand-in document (fakedoc.py).
import os
import sys
import tempfile
import types
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.dirname(HERE), HERE]

import fakedoc  # noqa: E402
from meshkit import box_mesh  # noqa: E402

from scanrulerfc import commands as C  # noqa: E402
from scanrulerfc import docstate as D  # noqa: E402
from scanrulerfc import runner  # noqa: E402
from scanrulerfc import scanstate as S  # noqa: E402
from scanrulerfc import viewprops as VP  # noqa: E402
from scanrulerfc import workspaces as W  # noqa: E402


def rot_z(deg):
    a = np.radians(deg)
    return np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1.0]])


def box_scan():
    V, F = box_mesh(40.0, 30.0, 20.0, n=10)
    return S.Scan("box.stl", np.asarray(V, float), np.asarray(F, np.int64))


class Codec(unittest.TestCase):
    def test_round_trip(self):
        sc = box_scan()
        sc.set_pose(2.0, rot_z(30), np.array([1.0, 2.0, 3.0]))
        st = {"scan": sc, "elements": [{"id": 1, "name": "Top", "fit": {"center": np.array([0.0, 0, 10])}, "tags": {"a", "b"},
                                        "pair": (1, 2), "off": float("nan")}],
              "deviation": {"scan": sc, "values": np.arange(4.0)}, "version": 9, "last_tool": "x", "weird": object()}
        data, dropped = D.encode(st)
        self.assertEqual(dropped, ["state.weird (object)"])
        got, notes = D.decode(data)
        self.assertEqual(notes, {"dropped": ["state.weird (object)"], "missing": []})
        g = got["scan"]
        self.assertEqual((g.name, g.k), ("box.stl", 2.0))
        np.testing.assert_allclose(g.V, sc.V)
        self.assertIs(got["deviation"]["scan"], g)  # one scan, referred to twice
        el = got["elements"][0]
        self.assertEqual((el["tags"], el["pair"]), ({"a", "b"}, (1, 2)))
        self.assertTrue(np.isnan(el["off"]))
        np.testing.assert_allclose(el["fit"]["center"], [0, 0, 10])
        self.assertNotIn("version", got)  # counters are the session's, not the document's

    def test_signature_moves_on_change(self):
        st = {"scan": box_scan(), "elements": []}
        a = D.signature(st)
        self.assertEqual(a, D.signature(st))
        st["elements"].append({"id": 1})
        self.assertNotEqual(a, D.signature(st))

    def test_points_read_placed_or_not(self):
        P = np.array([[0.0, 0, 0], [10, 0, 0], [0, 5, 0]])
        R, t = rot_z(90), np.array([5.0, 0, 0])
        box = [P.min(0).tolist(), P.max(0).tolist()]
        np.testing.assert_allclose(D.points_from_object(P, (R, t), box), P)
        np.testing.assert_allclose(D.points_from_object(P @ R.T + t, (R, t), box), P, atol=1e-12)


class InTheDocument(unittest.TestCase):
    """mark writes the state on change; a reopened document reads it; the
    scan is a mesh object whose Placement is the alignment."""

    def setUp(self):
        self.fc = fakedoc.installed()
        self.app = self.fc.__enter__()
        self.addCleanup(self.fc.__exit__, None, None, None)
        D._SIGS.clear()
        self.doc = fakedoc.Doc("Bracket")
        self.ctx = runner.Context(doc=self.doc, out_dir=tempfile.mkdtemp())
        self.run = runner.local(ctx=self.ctx)
        S.state(self.ctx)["scan"] = box_scan()
        ok, out = self.run("element_fit", {"kind": "plane", "at": {"point": [0, 0, 10]}, "name": "Top"})
        self.assertTrue(ok, out)

    def test_written_on_change_with_the_scan_as_a_mesh(self):
        state = D.find_state(self.doc)
        self.assertIsNotNone(state)
        self.assertEqual(state.Credit, D.CREDIT)
        self.assertFalse(state.ViewObject.ShowInTree)  # hidden from the tree
        self.assertFalse(state.ViewObject.Visibility)
        scan = D.role_object(self.doc, "scan")
        self.assertEqual((scan.TypeId, scan.Label), ("Mesh::Feature", "box.stl"))
        rev = state.Revision
        self.run("element_list", {})  # nothing changed: nothing written
        self.assertEqual(state.Revision, rev)
        self.run("element_rename", {"element": "Top", "name": "Lid"})
        self.assertEqual(state.Revision, rev + 1)

    def test_off_the_tree_even_when_its_view_does_not_list_it(self):
        # Live check: "ScanRuler state" showed in the tree; ShowInTree is
        # set whether or not the view lists it, and again on each write.
        state = D.find_state(self.doc)
        state.ViewObject.PropertiesList = ["Visibility"]
        state.ViewObject.ShowInTree = True
        self.run("element_rename", {"element": "Top", "name": "Lid"})
        self.assertFalse(state.ViewObject.ShowInTree)
        self.assertFalse(D.hide_from_tree(types.SimpleNamespace(ViewObject=None)))

    def test_reopened_document_reads_it_back(self):
        self.run("align_datum", {"primary": "Top"})
        before = S.state(self.ctx)
        again = runner.Context(doc=self.doc)  # a new session on the saved document
        st = S.state(again)
        self.assertEqual([e["name"] for e in st["elements"]], ["Top"])
        np.testing.assert_allclose(st["scan"].V, before["scan"].V, atol=1e-9)
        np.testing.assert_allclose(st["scan"].R, before["scan"].R)
        self.assertEqual(st["scan"].object, D.role_object(self.doc, "scan").Name)

    def test_a_move_made_in_freecad_carries_the_elements(self):
        # Std_Placement / Std_TransformManip on the scan object: the next
        # call reads the move in, and the elements go with the scan.
        scan = D.role_object(self.doc, "scan")
        top = S.state(self.ctx)["elements"][0]["fit"]
        z0 = np.asarray(top.get("origin", top.get("center")), float)[2]
        scan.Placement = fakedoc.placement(np.eye(3), [0, 0, 5.0])
        ok, out = self.run("element_list", {})
        self.assertTrue(ok, out)
        st = S.state(self.ctx)
        np.testing.assert_allclose(st["scan"].t, [0, 0, 5.0])
        fit = st["elements"][0]["fit"]
        self.assertAlmostEqual(np.asarray(fit.get("origin", fit.get("center")), float)[2], z0 + 5.0, places=6)
        # and the alignment's own moves are put on the object
        self.run("align_clear", {})
        np.testing.assert_allclose(D.placement_rt(scan.Placement.toMatrix().A)[1], [0, 0, 0], atol=1e-12)

    def test_a_reference_file_becomes_a_mesh_a_body_stays_itself(self):
        V, F = box_mesh(10.0, 10.0, 10.0, n=2)
        st = S.state(self.ctx)
        st["deviation"] = {"reference": {"name": "nominal.step", "kind": "cad", "V": np.asarray(V, float), "F": np.asarray(F)}}
        D.sync_objects(self.doc, st)
        ref = D.role_object(self.doc, "reference")
        self.assertEqual((ref.TypeId, ref.Label), ("Mesh::Feature", "nominal.step"))
        body = self.doc.addObject("Part::Feature", "Body")
        st["deviation"]["reference"] = {"name": "Body", "kind": "body", "object": body.Name, "V": np.asarray(V, float), "F": np.asarray(F)}
        D.sync_objects(self.doc, st)
        self.assertIs(D.role_object(self.doc, "reference"), body)


class ViewProps(unittest.TestCase):
    """Show, Transparent and Mesh: the objects' own properties."""

    def setUp(self):
        self.fc = fakedoc.installed()
        self.app = self.fc.__enter__()
        self.addCleanup(self.fc.__exit__, None, None, None)
        self.doc = fakedoc.Doc()
        sc = box_scan()
        D.put_scan(self.doc, sc)
        self.obj = D.role_object(self.doc, "scan")
        self.app.ActiveDocument = self.doc

    def test_toggle_sets_freecads_properties(self):
        v = self.obj.ViewObject
        self.assertTrue(VP.toggle(self.doc, "scan", "DisplayMode"))
        self.assertEqual(v.DisplayMode, "Flat Lines")
        self.assertFalse(VP.toggle(self.doc, "scan", "DisplayMode"))
        self.assertEqual(v.DisplayMode, "Shaded")
        self.assertTrue(VP.toggle(self.doc, "scan", "Transparency"))
        self.assertEqual(v.Transparency, VP.TRANSPARENT)
        self.assertFalse(VP.toggle(self.doc, "scan", "Visibility"))
        self.assertFalse(v.Visibility)
        self.assertIsNone(VP.toggle(self.doc, "reference", "Visibility"))  # none in the document

    def test_view_keys_read_and_set_the_object(self):
        cmds = C.build()
        saved = dict(C._state["view"])
        self.addCleanup(lambda: (C._state["view"].clear(), C._state["view"].update(saved)))
        seen = []
        C.set_ui(lambda key, *a: seen.append((key,) + a))
        self.addCleanup(C.set_ui, None)
        self.assertTrue(cmds["ScanRuler_ViewScan"].reading())
        self.obj.ViewObject.DisplayMode = "Flat Lines"  # set in FreeCAD's property view
        self.assertTrue(cmds["ScanRuler_ViewScanMesh"].GetResources()["Checkable"])
        cmds["ScanRuler_ViewScanMesh"].Activated(False)
        self.assertEqual(self.obj.ViewObject.DisplayMode, "Shaded")
        cmds["ScanRuler_ViewScanTransparent"].Activated()
        self.assertEqual(self.obj.ViewObject.Transparency, VP.TRANSPARENT)
        cmds["ScanRuler_ViewScan"].Activated()
        self.assertFalse(self.obj.ViewObject.Visibility)
        for k in ("ViewScan", "ViewScanMesh", "ViewScanTransparent"):
            self.assertNotIn(k, C._state["view"])  # no state of ScanRuler's beside FreeCAD's
        self.assertEqual(seen[-1], ("view", "ViewScan", False))

    def test_every_owned_key_acts_on_a_property(self):
        acts = {k["key"]: k["acts"] for k in W.view_keys() if k.get("acts")}
        self.assertEqual(acts, {"ViewScan": ("scan", "Visibility"), "ViewScanTransparent": ("scan", "Transparency"),
                                "ViewScanMesh": ("scan", "DisplayMode"), "ViewReference": ("reference", "Visibility"),
                                "ViewRefTransparent": ("reference", "Transparency"), "ViewRefMesh": ("reference", "DisplayMode"),
                                "ViewBodies": ("bodies", "Visibility"), "ViewBodiesTransparent": ("bodies", "Transparency")})
        own = {k["key"] for k in W.view_keys() if not k.get("acts") and not k.get("native") and not k.get("tool")}
        self.assertEqual(own, {"ViewScanBackfaces", "ViewScanColours", "ViewRefBackfaces", "ViewLabels", "ViewOverlaps", "ViewTangentEdges",
                               "ViewSplit", "ViewColourPlot", "ViewOnReference", "ViewCopyDeviation"})


class Bodies(unittest.TestCase):
    def test_bodies_key_and_body_set_use_visibility(self):
        from scanrulerfc.reverse import doc as RD

        doc = fakedoc.Doc()
        c = doc.addObject("Part::FeaturePython", RD.CONTAINER)
        c.PartJson = "{}"
        for i in (1, 2):
            b = doc.addObject("Part::FeaturePython", RD.BODY)
            b.BodyId = float(i)
            c.Group.append(b)
        self.assertEqual(len(VP.objects(doc, "bodies")), 2)
        self.assertFalse(VP.toggle(doc, "bodies", "Visibility"))
        self.assertFalse(any(b.ViewObject.Visibility for b in c.Group))
        self.assertEqual(RD.show_bodies(c, [2], True), 1)
        self.assertEqual([b.ViewObject.Visibility for b in c.Group], [False, True])


class MoveRotateIsStdPlacement(unittest.TestCase):
    def test_key_selects_the_scan_and_runs_std_placement(self):
        spec = C.native_key("MoveRotate")
        self.assertEqual((spec["native"], spec["on"]), ("Std_Placement", "scan"))
        with fakedoc.installed() as app:
            doc = fakedoc.Doc()
            D.put_scan(doc, box_scan())
            app.ActiveDocument = doc
            ran, selected = [], []
            gui = types.ModuleType("FreeCADGui")
            gui.runCommand = ran.append
            gui.Selection = types.SimpleNamespace(clearSelection=selected.clear, addSelection=selected.append)
            sys.modules["FreeCADGui"] = gui
            try:
                self.assertTrue(C.build()["ScanRuler_MoveRotate"].Activated())
                # the panel's key goes the same way
                from scanrulerfc import dock

                self.assertIsNone(dock.press(None, "MoveRotate", {}))
            finally:
                sys.modules.pop("FreeCADGui", None)
            self.assertEqual(ran, ["Std_Placement", "Std_Placement"])
            self.assertEqual([o.Name for o in selected], [D.role_object(doc, "scan").Name])

    def test_without_a_scan_it_says_so(self):
        told = []
        real, C._tell = C._tell, told.append
        try:
            with fakedoc.installed() as app:
                app.ActiveDocument = fakedoc.Doc()
                self.assertFalse(C.run_native(C.native_key("MoveRotate")))
        finally:
            C._tell = real
        self.assertEqual(told, [C.NEED_SCAN])


class SectionAndElements(unittest.TestCase):
    def test_section_reads_freecad_and_keeps_nothing(self):
        g = next(g for g in W.VIEW_BAR if g["key"] == "ViewSection")
        self.assertEqual(g["native"], "Std_ToggleClipPlane")
        self.assertFalse(C.section_open())  # no window here: not open
        self.assertNotIn("ViewSection", C._state["view"])

    def test_elements_key_runs_the_tool(self):
        calls = []
        C.set_runner(lambda tool, args: calls.append((tool, args)) or (True, {}))
        C.set_ui(lambda *a: None)
        real = C._scan_state
        C._scan_state = lambda: {"elements": [{"visible": True}]}
        try:
            C.build()["ScanRuler_ViewElements"].Activated()
        finally:
            C._scan_state = real
            C.set_runner(None)
            C.set_ui(None)
        self.assertEqual(calls, [("element_set_visible", {"all": True, "visible": False})])
        self.assertNotIn("ViewElements", C._state["view"])


if __name__ == "__main__":
    unittest.main()
