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


class WhichThreadWrites(unittest.TestCase):
    """A heavy read may run on a worker thread (Agent Link's jobs): what it
    writes into the document afterwards goes to the GUI thread."""

    def test_runs_at_once_on_the_main_thread_and_never_on_a_worker(self):
        import threading

        ran = []
        self.assertTrue(D.on_gui_thread(lambda: ran.append("main")))
        got = []
        th = threading.Thread(target=lambda: got.append(D.on_gui_thread(lambda: ran.append("worker"))))
        th.start()
        th.join(3)
        # No window here to hand it to: not run on the worker, left for the next call.
        self.assertEqual((ran, got), (["main"], [None]))

    def test_without_a_window_a_job_leaves_the_state_for_the_next_call(self):
        import threading
        import unittest.mock

        ctx = types.SimpleNamespace(doc=None, family_state={})
        with unittest.mock.patch.object(D, "mark_doc") as mark:
            th = threading.Thread(target=lambda: S.touched(ctx, "deviation_measure"), name="agentlink-job-deviation_measure")
            th.start()
            th.join(3)
            self.assertEqual(mark.call_count, 0)
            self.assertEqual(S.state(ctx)["last_tool"], "deviation_measure")  # the dock still follows
            S.touched(ctx, "scan_info")
            self.assertEqual(mark.call_count, 1)

    def test_with_a_window_a_job_hands_the_state_to_the_gui_thread(self):
        import threading
        import unittest.mock

        ctx = types.SimpleNamespace(doc=None, family_state={})
        sent = []
        poster = types.SimpleNamespace(go=types.SimpleNamespace(emit=sent.append))
        with unittest.mock.patch.object(D, "mark_doc") as mark, unittest.mock.patch.object(D, "_gui_up", lambda: True), \
                unittest.mock.patch.object(D, "_poster", lambda: poster):
            th = threading.Thread(target=lambda: S.touched(ctx, "mesh_wrap"), name="agentlink-job-mesh_wrap")
            th.start()
            th.join(3)
            self.assertEqual((mark.call_count, len(sent)), (0, 1))
            sent[0]()
            self.assertEqual(mark.call_count, 1)

    def test_mark_itself_refuses_a_worker_thread(self):
        import threading

        fc = fakedoc.installed()
        fc.__enter__()
        self.addCleanup(fc.__exit__, None, None, None)
        D._SIGS.clear()
        doc = fakedoc.Doc("Job")
        ctx = types.SimpleNamespace(doc=doc, family_state={})
        S.state(ctx)["scan"] = box_scan()
        got = []
        th = threading.Thread(target=lambda: got.append(D.mark(ctx)))
        th.start()
        th.join(3)
        self.assertEqual(got, [False])
        self.assertIsNone(D.find_state(doc))
        self.assertTrue(D.mark(ctx))
        self.assertIsNotNone(D.find_state(doc))

    def test_without_a_window_a_best_fit_on_a_worker_moves_the_object_at_the_next_call(self):
        import threading

        fc = fakedoc.installed()
        fc.__enter__()
        self.addCleanup(fc.__exit__, None, None, None)
        D._SIGS.clear()
        doc = fakedoc.Doc("Fit")
        ctx = types.SimpleNamespace(doc=doc, family_state={})
        sc = box_scan()
        S.state(ctx)["scan"] = sc
        D.put_scan(doc, sc)
        before = sc.placed
        th = threading.Thread(target=lambda: sc.set_pose(1.0, rot_z(90), np.array([5.0, 0, 0])))
        th.start()
        th.join(3)
        self.assertIs(sc.placed, before)  # the object not moved from the worker
        self.assertTrue(sc.pose_waiting)
        self.assertFalse(D.pull_pose(S.state(ctx), doc))  # and no move read in between
        self.assertTrue(D.mark(ctx))  # the next call, on the document's thread
        self.assertFalse(sc.pose_waiting)
        np.testing.assert_allclose(sc.placed[1], [5.0, 0, 0], atol=1e-9)

    def test_a_worker_thread_hands_the_write_over_when_a_window_is_up(self):
        import threading
        import unittest.mock

        class Go:
            def __init__(self):
                self.sent = []

            def emit(self, fn):
                self.sent.append(fn)

        poster = types.SimpleNamespace(go=Go())
        ran, got = [], []
        with unittest.mock.patch.object(D, "_gui_up", lambda: True), unittest.mock.patch.object(D, "_poster", lambda: poster):
            th = threading.Thread(target=lambda: got.append(D.on_gui_thread(lambda: ran.append(1))))
            th.start()
            th.join(3)
            self.assertEqual((ran, got, len(poster.go.sent)), ([], [False], 1))  # queued, not run on the worker
            self.assertTrue(D.on_gui_thread(lambda: ran.append(2)))  # the GUI thread itself writes at once
        poster.go.sent[0]()
        self.assertEqual(ran, [2, 1])

    def test_a_best_fit_on_a_worker_moves_the_scan_object_on_the_gui_thread(self):
        import threading
        import unittest.mock

        fc = fakedoc.installed()
        fc.__enter__()
        self.addCleanup(fc.__exit__, None, None, None)
        doc = fakedoc.Doc("Fit")
        sc = box_scan()
        D.put_scan(doc, sc)
        sent = []
        poster = types.SimpleNamespace(go=types.SimpleNamespace(emit=sent.append))
        before = sc.placed
        with unittest.mock.patch.object(D, "_gui_up", lambda: True), unittest.mock.patch.object(D, "_poster", lambda: poster):
            th = threading.Thread(target=lambda: sc.set_pose(1.0, rot_z(90), np.array([5.0, 0, 0])))
            th.start()
            th.join(3)
        self.assertEqual(len(sent), 1)
        self.assertIs(sc.placed, before)  # the object not yet moved: pull_pose reads no move
        sent[0]()
        np.testing.assert_allclose(sc.placed[1], [5.0, 0, 0], atol=1e-9)


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
        ok, out = self.run("align_datum", {"primary": {"element": "Top"}})
        self.assertTrue(ok, out)
        ok, out = self.run("align_datum", {"primary": "Top"})  # a bare name: refused with the shape to give
        self.assertEqual((ok, out["error"]["code"]), (False, "invalid_input"))
        self.assertIn("{ element: name or id }", out["error"]["message"])
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

    def test_a_scale_keeps_the_alignment(self):
        # Found live (run 2, measure model call 102): align, scan_scale 2,
        # scan_scale 0.5, then align_clear was refused "in scan coordinates
        # already". The scaled mesh was put on the scan object after its
        # Placement, and FreeCAD's Mesh::Feature takes a new mesh's (empty)
        # placement as its own; the next call read the object standing at
        # the origin as a move made by the person and undid the alignment.
        ok, out = self.run("align_datum", {"primary": {"element": "Top"}, "origin": {"point": [20, 15, 10]}})
        self.assertTrue(ok, out)
        st = S.state(self.ctx)
        scan = D.role_object(self.doc, "scan")
        t0 = np.array(st["scan"].t)
        self.assertGreater(np.abs(t0).max(), 1.0)
        box0 = (st["scan"].V.min(axis=0), st["scan"].V.max(axis=0))
        ok, out = self.run("scan_scale", {"factor": 2})
        self.assertTrue(ok, out)
        np.testing.assert_allclose(D.placement_rt(scan.Placement.toMatrix().A)[1], 2 * t0, atol=1e-9)  # the object stands where the scan is
        ok, out = self.run("scan_scale", {"factor": 0.5})
        self.assertTrue(ok, out)
        np.testing.assert_allclose(out["scan"]["box"]["min"], box0[0], atol=1e-3)  # still aligned: the box it had
        np.testing.assert_allclose(out["scan"]["box"]["max"], box0[1], atol=1e-3)
        np.testing.assert_allclose(S.state(self.ctx)["scan"].t, t0, atol=1e-9)
        ok, out = self.run("align_clear", {})
        self.assertTrue(ok, out)  # there is an alignment to clear
        np.testing.assert_allclose(S.state(self.ctx)["scan"].t, [0, 0, 0], atol=1e-12)
        np.testing.assert_allclose(S.state(self.ctx)["scan"].V, S.state(self.ctx)["scan"].V0, atol=1e-9)

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


class StatePerDocument(unittest.TestCase):
    """Found live (run 2): the state was the session's, not the document's.
    After doc_new the earlier document's scan was still open (scan_open was
    refused, flat_edges answered its section sheet) and its state was
    written into the new document's file. The state belongs to the document
    it was made in: another document has its own (none, when new), and
    going back restores it."""

    def setUp(self):
        self.fc = fakedoc.installed()
        self.app = self.fc.__enter__()
        self.addCleanup(self.fc.__exit__, None, None, None)
        D._SIGS.clear()
        self.a = fakedoc.Doc("Worn")
        # One session that moves between documents, as Agent Link's does
        # (doc_new and doc_open set session.doc and leave family_state).
        self.ctx = runner.Context(doc=self.a, out_dir=tempfile.mkdtemp())
        self.run = runner.local(ctx=self.ctx)
        S.state(self.ctx)["scan"] = box_scan()
        ok, out = self.run("element_fit", {"kind": "plane", "at": {"point": [0, 0, 10]}, "name": "Top"})
        self.assertTrue(ok, out)

    def test_a_new_document_starts_with_no_scan_and_gets_none_written(self):
        b = fakedoc.Doc("Fresh")
        self.ctx.doc = b
        ok, out = self.run("scan_info", {})
        self.assertTrue(ok, out)
        self.assertIsNone(out["scan"])  # no scan open here
        ok, out = self.run("flat_edges", {})
        self.assertFalse(ok)  # and no 2D sheet of the other document's
        self.assertEqual(out["error"]["code"], "invalid_state")
        ok, out = self.run("element_list", {})
        self.assertTrue(ok, out)
        self.assertEqual(out["elements"], [])
        self.assertIsNone(D.find_state(b))  # nothing of the other document written into this one
        self.assertEqual([o.Name for o in b.Objects], [])
        self.assertIsNotNone(D.find_state(self.a))

    def test_switching_back_restores_the_documents_own_state(self):
        first = S.state(self.ctx)
        b = fakedoc.Doc("Fresh")
        self.ctx.doc = b
        S.state(self.ctx)["scan"] = S.Scan("other.stl", first["scan"].V0 * 2.0, first["scan"].F)
        ok, out = self.run("scan_info", {})
        self.assertTrue(ok, out)
        self.assertEqual(out["scan"]["file"], "other.stl")
        self.assertEqual(out["elements"], 0)
        self.ctx.doc = self.a
        back = S.state(self.ctx)
        self.assertIs(back, first)  # the very state, not a copy read back
        ok, out = self.run("scan_info", {})
        self.assertEqual((out["scan"]["file"], out["elements"]), ("box.stl", 1))
        self.ctx.doc = b
        ok, out = self.run("scan_info", {})
        self.assertEqual((out["scan"]["file"], out["elements"]), ("other.stl", 0))
        # each document's file holds its own scan
        self.assertEqual(D.role_object(self.a, "scan").Label, "box.stl")
        self.assertEqual(D.role_object(b, "scan").Label, "other.stl")

    def test_what_a_job_left_unwritten_is_written_into_its_own_document_on_leaving(self):
        import threading

        st = S.state(self.ctx)
        rev = D.find_state(self.a).Revision
        # a heavy read on a worker thread changes the state; with no window
        # its write waits for the next call on the document's thread
        def job():
            st["thickness"] = {"stats": {"min": 10.0}}
            S.touched(self.ctx, "thickness_measure")

        th = threading.Thread(target=job, name="agentlink-job-thickness_measure")
        th.start()
        th.join(3)
        self.assertEqual(D.find_state(self.a).Revision, rev)  # not from the worker
        b = fakedoc.Doc("Fresh")
        self.ctx.doc = b
        self.run("element_list", {})  # the next call is in another document
        self.assertEqual(D.find_state(self.a).Revision, rev + 1)  # written where it belongs
        self.assertIsNone(D.find_state(b))
        again = runner.Context(doc=self.a)  # and a session reading that document finds it
        self.assertEqual(S.state(again)["thickness"]["stats"]["min"], 10.0)

    def test_a_write_handed_to_the_gui_thread_lands_in_its_own_document(self):
        import threading
        import unittest.mock

        st = S.state(self.ctx)
        rev = D.find_state(self.a).Revision
        sent = []
        poster = types.SimpleNamespace(go=types.SimpleNamespace(emit=sent.append))
        with unittest.mock.patch.object(D, "_gui_up", lambda: True), unittest.mock.patch.object(D, "_poster", lambda: poster):
            def job():
                st["thickness"] = {"stats": {"min": 10.0}}
                S.touched(self.ctx, "thickness_measure")

            th = threading.Thread(target=job, name="agentlink-job-thickness_measure")
            th.start()
            th.join(3)
        self.assertEqual(len(sent), 1)
        b = fakedoc.Doc("Fresh")
        self.ctx.doc = b  # the session moved on before the GUI thread ran the write
        sent[0]()
        self.assertEqual(D.find_state(self.a).Revision, rev + 1)
        self.assertIsNone(D.find_state(b))

    def test_a_document_reopened_under_the_same_name_reads_its_file_not_the_old_session(self):
        b = fakedoc.Doc("Fresh")
        self.ctx.doc = b
        self.run("element_list", {})
        # "Worn" closed and another document made under its name
        self.app.listDocuments = lambda: {"Fresh": b}
        self.ctx.doc = self.a
        self.ctx.doc = b
        S.state(self.ctx)
        other = fakedoc.Doc("Worn")
        self.app.listDocuments = lambda: {"Fresh": b, "Worn": other}
        self.ctx.doc = other
        st = S.state(self.ctx)
        self.assertIsNone(st["scan"])
        self.assertEqual(st["elements"], [])

    def test_a_closed_documents_state_is_let_go(self):
        b = fakedoc.Doc("Fresh")
        self.app.listDocuments = lambda: {"Worn": self.a, "Fresh": b}
        self.ctx.doc = b
        S.state(self.ctx)
        self.assertIn("Worn", getattr(self.ctx, S._BOOK)["parked"])
        self.app.listDocuments = lambda: {"Fresh": b}  # Worn closed
        c = fakedoc.Doc("Third")
        self.app.listDocuments = lambda: {"Fresh": b, "Third": c}
        self.ctx.doc = c
        S.state(self.ctx)
        self.assertNotIn("Worn", getattr(self.ctx, S._BOOK)["parked"])

    def test_mark_never_writes_one_documents_state_into_another(self):
        b = fakedoc.Doc("Fresh")
        self.ctx.doc = b  # moved, and mark is the first thing to run (a queued write of the old code)
        self.assertFalse(D.mark(self.ctx))
        self.assertIsNone(D.find_state(b))


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


class WhatAWriteCosts(unittest.TestCase):
    """Found live (run 2): once the scan had 219,600 triangles every call
    that changed the state took 1.2 to 1.6 s — a rename, a limit, a
    dimension removed — because the whole state was compressed again and
    copied into the document each time. A write now follows what changed:
    an array as it was at the last write goes in from its packed bytes."""

    def state(self):
        sc = box_scan()
        return {"scan": sc, "elements": [{"id": 1, "name": "Top", "region": np.arange(500, dtype=np.int64)}],
                "deviation": {"values": np.linspace(0.0, 1.0, 4000)}}

    def packed(self, st, packs):
        """(bytes, how often an array was compressed) for one encode."""
        import unittest.mock

        with unittest.mock.patch.object(D, "pack_array", wraps=D.pack_array) as p:
            data, _dropped = D.encode(st, packs=packs)
        return data, p.call_count

    def test_an_unchanged_array_is_not_packed_again(self):
        st, packs = self.state(), D.Packs()
        _data, n = self.packed(st, packs)
        # the scan's R, t, F and V0, the region and the readings
        self.assertEqual((n, packs.keep_used()), (6, (6, 6)))
        st["elements"][0]["name"] = "Lid"  # what a rename changes: no array
        data, n = self.packed(st, packs)
        self.assertEqual((n, packs.keep_used()), (0, (6, 0)))
        got, _notes = D.decode(data)  # and the bytes written are the whole state all the same
        self.assertEqual(got["elements"][0]["name"], "Lid")
        np.testing.assert_array_equal(got["elements"][0]["region"], st["elements"][0]["region"])
        np.testing.assert_allclose(got["deviation"]["values"], st["deviation"]["values"])
        np.testing.assert_allclose(got["scan"].V, st["scan"].V)
        np.testing.assert_array_equal(got["scan"].F, st["scan"].F)

    def test_only_what_changed_is_packed_and_a_change_in_place_counts(self):
        st, packs = self.state(), D.Packs()
        self.packed(st, packs)
        packs.keep_used()
        st["deviation"]["values"][7] = 99.0  # the same array object, another content
        data, n = self.packed(st, packs)
        self.assertEqual((n, packs.keep_used()), (1, (6, 1)))
        self.assertEqual(D.decode(data)[0]["deviation"]["values"][7], 99.0)
        st["deviation"]["values"] = st["deviation"]["values"].copy()  # another object, the same content
        _data, n = self.packed(st, packs)
        self.assertEqual(n, 0)

    def test_only_the_last_writes_arrays_are_kept(self):
        st, packs = self.state(), D.Packs()
        self.packed(st, packs)
        packs.keep_used()
        self.assertEqual(len(packs.kept), 6)
        del st["deviation"]
        st["elements"] = []
        self.packed(st, packs)
        packs.keep_used()
        self.assertEqual(len(packs.kept), 4)  # the scan's own: nothing of what the state let go

    def test_the_earlier_format_is_still_read(self):
        # Format 1 (state.json and numpy's arrays.npz), as every document
        # saved before 16 Nov 2026 holds it.
        import io
        import json
        import zipfile

        st = self.state()
        e = D._Enc()
        body = e.value(st, "state")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("state.json", json.dumps({"format": 1, "state": body, "dropped": []}))
            arr = io.BytesIO()
            np.savez_compressed(arr, **e.arrays)
            z.writestr("arrays.npz", arr.getvalue())
        got, notes = D.decode(buf.getvalue())
        self.assertEqual(notes, {"dropped": [], "missing": []})
        np.testing.assert_allclose(got["scan"].V, st["scan"].V)
        np.testing.assert_array_equal(got["elements"][0]["region"], st["elements"][0]["region"])

    def test_a_newer_format_says_what_to_do(self):
        import io
        import json
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("state.json", json.dumps({"format": D.FORMAT + 1, "state": {}}))
        with self.assertRaises(ValueError) as cm:
            D.decode(buf.getvalue())
        self.assertIn("update the add-on", str(cm.exception))

    def test_an_array_of_objects_is_left_out_and_said(self):
        # It could only be pickled, and nothing is unpickled on the way
        # back: one such array used to make the whole state unreadable.
        st = {"scan": None, "elements": [], "odd": np.array([{"a": 1}, None], dtype=object), "fine": np.arange(3)}
        data, dropped = D.encode(st)
        self.assertEqual(dropped, ["state.odd (an array of objects)"])
        got, notes = D.decode(data)
        self.assertNotIn("odd", got)
        np.testing.assert_array_equal(got["fine"], [0, 1, 2])

    def test_in_a_document_a_rename_packs_nothing_and_scan_info_says_so(self):
        fc = fakedoc.installed()
        fc.__enter__()
        self.addCleanup(fc.__exit__, None, None, None)
        D._SIGS.clear()
        D._KEPT.clear()
        doc = fakedoc.Doc("Dense")
        ctx = runner.Context(doc=doc, out_dir=tempfile.mkdtemp())
        run = runner.local(ctx=ctx)
        self.assertIsNone(D.last_write(doc))
        S.state(ctx)["scan"] = box_scan()
        ok, out = run("element_fit", {"kind": "plane", "at": {"point": [0, 0, 10]}, "name": "Top"})
        self.assertTrue(ok, out)
        first = D.last_write(doc)
        self.assertGreater(first["packedAgain"], 0)
        self.assertEqual(first["bytes"], os.path.getsize(D.find_state(doc).State))
        ok, out = run("element_rename", {"element": "Top", "name": "Lid"})
        self.assertTrue(ok, out)
        ok, out = run("scan_info", {})
        self.assertTrue(ok, out)
        kept = out["kept"]
        self.assertEqual((kept["packedAgain"], kept["arrays"]), (0, first["arrays"]))
        self.assertEqual(set(kept), {"bytes", "ms", "arrays", "packedAgain"})
        # what the document holds reads back whole in a new session
        st = S.state(runner.Context(doc=doc))
        self.assertEqual([e["name"] for e in st["elements"]], ["Lid"])
        np.testing.assert_allclose(st["scan"].V, S.state(ctx)["scan"].V, atol=1e-9)
        # another document has its own record, and none before its first write
        other = fakedoc.Doc("Other")
        self.assertIsNone(D.last_write(other))
        ctx.doc = other
        ok, out = run("scan_info", {})
        self.assertNotIn("kept", out)

    def test_a_write_that_fails_keeps_what_the_file_there_was_packed_from(self):
        fc = fakedoc.installed()
        fc.__enter__()
        self.addCleanup(fc.__exit__, None, None, None)
        D._KEPT.clear()
        doc = fakedoc.Doc("Dense")
        st = self.state()
        D.write(doc, st)
        before = dict(D._KEPT["Dense"]["packs"].kept)
        o = D.find_state(doc)

        class Refuses(type(o)):
            def __setattr__(self, name, value):
                if name == "State":
                    raise OSError("no room")
                super().__setattr__(name, value)

        object.__setattr__(o, "__class__", Refuses)  # the property refuses the next file
        st["deviation"]["values"] = st["deviation"]["values"] + 1.0
        with self.assertRaises(OSError):
            D.write(doc, st)
        self.assertEqual(D._KEPT["Dense"]["packs"].kept, before)
        self.assertEqual(D._KEPT["Dense"]["packs"].used, {})


class BesideAgentLinksOwnKeeping(unittest.TestCase):
    """Agent Link keeps every family's state per document too
    (agentlink/docstates.py, since 16 Nov 2026). ScanRuler settles its own
    (scanstate.settle) and says so; the two must not both set the state
    aside, and a document reopened from a copy must get the state that
    copy holds. Runs where Agent Link is importable."""

    def setUp(self):
        try:
            from agentlink import docstates, hooks
        except Exception:  # noqa: BLE001
            self.skipTest("Agent Link is not on the path")
        if not hasattr(hooks, "own_document_state"):
            self.skipTest("an Agent Link from before it kept state per document")
        self.docstates, self.hooks = docstates, hooks
        self.fc = fakedoc.installed()
        self.app = self.fc.__enter__()
        self.addCleanup(self.fc.__exit__, None, None, None)
        self.open = {}
        self.app.listDocuments = lambda: dict(self.open)
        was, own = docstates.open_documents, set(docstates.OWN)
        docstates.open_documents = lambda: dict(self.open)
        self.addCleanup(setattr, docstates, "open_documents", was)
        self.addCleanup(lambda: (docstates.OWN.clear(), docstates.OWN.update(own)))
        D._SIGS.clear()
        D._KEPT.clear()

        class Session:
            """A session as Agent Link's is for this: doc and family_state
            are properties that settle its book."""

            def __init__(self, doc, out):
                self._doc, self.out_dir = doc, out

            doc = property(lambda s: s._doc, lambda s, d: (setattr(s, "_doc", d), docstates.settle(s, d))[0])
            family_state = property(lambda s: docstates.settle(s, s._doc), lambda s, v: docstates.put(s, s._doc, v))

            def snapshot(self, tool):
                pass

        self.Session = Session

    def new(self, name):
        d = self.open[name] = fakedoc.Doc(name)
        return d

    def session(self, doc):
        s = self.Session(doc, tempfile.mkdtemp())
        return s, runner.local(ctx=s)

    def test_scanruler_tells_agent_link_it_settles_its_own(self):
        import importlib.util

        src = open(os.path.join(os.path.dirname(HERE), "scanrulerfc", "agentlink_families.py"), encoding="utf-8").read()
        self.assertIn('_hook("state per document", _own_state)', src)
        # the call itself, as the module makes it
        self.docstates.OWN.clear()
        own = getattr(self.hooks, "own_document_state")
        own(S.KEY)
        self.assertIn("scanruler", self.docstates.OWN)
        self.assertIsNotNone(importlib.util.find_spec("scanrulerfc.agentlink_families"))

    def both_ways(self, told):
        if told:
            self.hooks.own_document_state(S.KEY)
        else:
            self.docstates.OWN.clear()  # an Agent Link that goes by the book on the session
        a, b = self.new("Worn"), self.new("Fresh")
        s, run = self.session(a)
        s.family_state["safetynet"] = {"checkpoints": ["cp1"]}  # another family's, kept by Agent Link
        S.state(s)["scan"] = box_scan()
        ok, out = run("element_fit", {"kind": "plane", "at": {"point": [0, 0, 10]}, "name": "Top"})
        self.assertTrue(ok, out)
        first = S.state(s)
        s.doc = b
        ok, out = run("scan_info", {})
        self.assertIsNone(out["scan"])  # the new document has no scan
        self.assertNotIn("safetynet", s.family_state)  # nor the other family's state
        self.assertIsNone(D.find_state(b))  # and nothing written into it
        s.doc = a
        self.assertIs(S.state(s), first)  # the very state back, once
        self.assertEqual(s.family_state["safetynet"], {"checkpoints": ["cp1"]})
        # set aside by one of them only: Agent Link's parked dicts never hold ScanRuler's key
        book = s.__dict__["_agentlink_document_states"]
        self.assertTrue(all(S.KEY not in st for _d, st in book["parked"].values()))
        s.doc = b
        s.doc = a  # there and back with no ScanRuler call in between
        self.assertIs(S.state(s), first)

    def test_one_of_them_sets_the_state_aside_when_told(self):
        self.both_ways(True)

    def test_and_when_agent_link_goes_by_the_book_on_the_session(self):
        self.both_ways(False)

    def test_a_document_reopened_from_a_copy_gets_the_state_that_copy_holds(self):
        # A checkpoint restored from its saved copy (Workshop's SafetyNet:
        # close, open the copy under the same name, put the kept
        # family_state back). The kept dict still holds ScanRuler's state
        # as it was after the later calls; the copy holds the earlier one.
        self.hooks.own_document_state(S.KEY)
        a = self.new("Worn")
        s, run = self.session(a)
        S.state(s)["scan"] = box_scan()
        ok, out = run("element_fit", {"kind": "plane", "at": {"point": [0, 0, 10]}, "name": "Top"})
        self.assertTrue(ok, out)
        # the copy: a document holding what a's file held at this moment
        copy = fakedoc.Doc("Worn")
        for o in a.Objects:
            c = copy.addObject(o.TypeId, o.Name)
            for k, v in o.__dict__.items():
                if k not in ("Document", "TypeId", "Name", "ViewObject", "_files"):
                    c.__dict__[k] = v
            c._files.update(o._files)
        state_file = D.find_state(a).State
        kept_bytes = open(state_file, "rb").read()
        keep = os.path.join(tempfile.mkdtemp(), "scanruler-state.zip")
        with open(keep, "wb") as f:
            f.write(kept_bytes)
        D.find_state(copy).__dict__["State"] = keep
        ok, out = run("element_rename", {"element": "Top", "name": "Later"})  # after the checkpoint
        self.assertTrue(ok, out)
        kept = s.family_state
        self.open["Worn"] = copy  # closed, and the copy opened under its name
        s.doc = copy
        s.family_state = kept
        ok, out = run("element_list", {})
        self.assertTrue(ok, out)
        self.assertEqual([e["name"] for e in out["elements"]], ["Top"])  # the copy's state, not the later one
        self.assertEqual(open(D.find_state(copy).State, "rb").read(), kept_bytes)  # and nothing later written over it


if __name__ == "__main__":
    unittest.main()
