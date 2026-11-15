# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): the scan's sections and measured elements as plugins/reverse/core/resolve.ts reads them
# SPDX-License-Identifier: AGPL-3.0-only
#
# The scan's planes and axes as references of a Reverse engineer part: the
# scan family's state read into the resolution's context in the original's
# plain fields, a sketch placed on a section's or a measured plane, a cut
# by a measured plane, and the scan handed to the Builder once per scan.
import os
import sys
import types
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

from meshkit import box_mesh  # noqa: E402
from reverse_fakekernel import FakeKernel  # noqa: E402
from scanrulerfc import scanstate as S  # noqa: E402
from scanrulerfc.reverse import doc as D  # noqa: E402
from scanrulerfc.reverse import handlers as H  # noqa: E402
from scanrulerfc.reverse import scan_context as C  # noqa: E402
from scanrulerfc.reverse.build import Builder  # noqa: E402
from scanrulerfc.reverse.sketch import add_rectangle, empty_sketch  # noqa: E402


def session_with_scan():
    V, F = box_mesh(10, 10, 10, 4, center=(5, 5, 5))
    s = types.SimpleNamespace(family_state={}, doc=None)
    st = S.state(s)
    st["scan"] = S.Scan("part.stl", V, F)
    st["elements"] = [{"id": 1, "name": "Plane 1", "kind": "plane", "visible": True, "source": {"type": "picked"},
                       "fit": {"kind": "plane", "center": np.array([5.0, 5.0, 3.0]), "normal": np.array([0.0, 0.0, 1.0]), "rms": np.float64(0.01), "region": np.arange(9)}}]
    frame = {"origin": np.array([0.0, 0.0, 4.0]), "normal": np.array([0.0, 0.0, 1.0]), "basisU": np.array([1.0, 0.0, 0.0]), "basisV": np.array([0.0, 1.0, 0.0])}
    st["sectionState"] = {"scan": st["scan"], "sections": [{"id": 1, "name": "Section 1", "kind": "cut", "frame": frame, "points": np.zeros((3, 2))}], "next": 2}
    return s


class Context(unittest.TestCase):
    def test_the_scan_family_state_in_plain_fields(self):
        ctx = C.of_session(session_with_scan())
        self.assertEqual(ctx["sections"], [{"id": 1, "name": "Section 1", "kind": "cut", "frame": {"origin": [0.0, 0.0, 4.0], "normal": [0.0, 0.0, 1.0], "basisU": [1.0, 0.0, 0.0], "basisV": [0.0, 1.0, 0.0]}}])
        el = ctx["elements"][0]
        self.assertEqual(el["fit"], {"kind": "plane", "center": [5.0, 5.0, 3.0], "normal": [0.0, 0.0, 1.0], "rms": 0.01})
        self.assertEqual(ctx["modelCenter"], [5.0, 5.0, 5.0])
        self.assertEqual(ctx["scan"][0].shape[1], 3)
        self.assertEqual(C.of_session(None), C.empty())
        self.assertEqual(C.of_session(types.SimpleNamespace(family_state=None)), C.empty())

    def test_a_section_cut_on_another_scan_is_not_offered(self):
        s = session_with_scan()
        S.state(s)["sectionState"]["scan"] = object()
        self.assertEqual(C.of_session(s)["sections"], [])

    def test_bind_sets_where_the_container_reads(self):
        s = session_with_scan()
        doc = types.SimpleNamespace(Name="Part")
        was = D.CONTEXT["of"]
        try:
            C.bind(doc, s)
            self.assertIs(D.CONTEXT["of"], C.of_document)
            self.assertEqual(D.CONTEXT["of"](doc)["elements"][0]["name"], "Plane 1")
            self.assertEqual(D.CONTEXT["of"](types.SimpleNamespace(Name="Other")), C.empty())
        finally:
            D.CONTEXT["of"] = was


class AsReferences(unittest.TestCase):
    def setUp(self):
        self.ctx = C.of_session(session_with_scan())
        self.store = H.MemoryStore(Builder(FakeKernel()), ctx=self.ctx)
        self.t = H.handlers(store=self.store)

    def test_a_sketch_on_a_section_and_on_a_measured_plane(self):
        s = empty_sketch()
        add_rectangle(s, [0, 0], [10, 10])
        self.t["reverse_feature_add"]({"feature": {"kind": "sketch", "plane": {"kind": "section", "id": 1}, "sketch": s}})
        self.t["reverse_feature_add"]({"feature": {"kind": "sketch", "plane": {"kind": "element", "id": 1, "offset": 1}, "sketch": s}})
        frames = [f["frame"] for f in self.store.part()["features"]]
        self.assertEqual([f["origin"][2] for f in frames], [4, 4])
        with self.assertRaises(H.Refusal) as e:
            H.handlers(store=H.MemoryStore(Builder(FakeKernel())))["reverse_feature_add"]({"feature": {"kind": "sketch", "plane": {"kind": "element", "id": 1}, "sketch": s}})
        self.assertIn("on the scan open now", e.exception.message)

    def test_a_cut_by_a_measured_plane(self):
        s = empty_sketch()
        add_rectangle(s, [0, 0], [10, 10])
        self.t["reverse_feature_add"]({"feature": {"kind": "sketch", "plane": {"kind": "world", "axis": "z", "offset": 0}, "sketch": s}})
        self.t["reverse_feature_add"]({"feature": {"kind": "extrude", "sketchId": 1, "extent": {"kind": "distance", "from": 0, "to": 10}, "op": "new"}})
        out = self.t["reverse_feature_add"]({"feature": {"kind": "cutPlane", "body": 2, "plane": {"kind": "element", "id": 1, "offset": 0}, "keep": 1}})
        self.assertEqual(out["added"][0]["status"], "ok", out)
        self.assertEqual([round(b["volume"]) for b in out["bodies"]], [700])

    def test_the_scan_is_handed_to_the_builder_once(self):
        b = self.store.builder
        self.store.rebuild()
        self.assertIsNotNone(b.scan)
        held = b.scan
        D.build_part(D.empty_part(), b, self.ctx)
        self.assertIs(b.scan, held)
        D.build_part(D.empty_part(), b, {**self.ctx, "scan": None})
        self.assertIsNone(b.scan)


if __name__ == "__main__":
    unittest.main()
