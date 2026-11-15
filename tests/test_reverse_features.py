# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/tests/reFeatureDraft.test.ts
# SPDX-License-Identifier: AGPL-3.0-only
#
# The boxes of the features on a body: what opens with what, the Create
# key's test, and the feature a draft becomes. The original drives these
# through its zustand store; here the store's pure parts are called
# directly. Its cases on picking in the 3D view, the editor reopening, the
# snap and the projection tools need the store and a build, and wait for
# the panel (build order step 13).
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from scanrulerfc.reverse.features import (  # noqa: E402
    DEFAULT_WALL_MM, dependents_of, extrude_draft_ready, feature_draft_ready, feature_of_draft, name_for, revolve_draft_ready, start_extrude,
    start_feature, start_revolve, step_file_key, trim_tolerance_for,
)
from scanrulerfc.reverse.sketch import add_rectangle, empty_sketch  # noqa: E402


def face(h, d):
    return {"hash": h, "fingerprint": {"kind": "plane", "centroid": [0, 0, 5], "dir": d, "area": 100, "origin": 2}}


BODIES = [{"id": 2, "name": "Extrude 1", "visible": True, "volume": 1, "faces": 6, "closed": True, "triangles": 12}]
XY = {"origin": [0, 0, 0], "normal": [0, 0, 1], "basisU": [1, 0, 0], "basisV": [0, 1, 0]}


class Drafts(unittest.TestCase):
    def test_shell_opens_on_last_body_ready_with_no_face(self):
        d = start_feature("shell", BODIES)
        self.assertEqual((d["kind"], d["body"], d["thickness"], len(d["faces"])), ("shell", 2, DEFAULT_WALL_MM, 0))
        self.assertTrue(feature_draft_ready(d))
        d = {**d, "faces": [face(7, [0, 0, 1])]}
        self.assertTrue(feature_draft_ready(d))
        f = feature_of_draft(d, 3, "Shell 1")
        self.assertEqual(f["faces"], [face(7, [0, 0, 1])["fingerprint"]])

    def test_every_kind_once_ready(self):
        self.assertIsNone(feature_of_draft({"kind": "hole", "body": 2, "axis": None, "radius": 3, "depth": None}, 5, "Hole 1"))
        hole = feature_of_draft({"kind": "hole", "body": 2, "axis": {"kind": "element", "id": 4}, "radius": 3, "depth": None}, 5, "Hole 1")
        self.assertTrue(hole["kind"] == "hole" and hole["radius"] == 3 and hole["depth"] is None)
        cut = feature_of_draft({"kind": "cutPlane", "body": 2, "plane": {"kind": "world", "axis": "x", "offset": 1}, "keep": -1}, 6, "Cut 1")
        self.assertTrue(cut["kind"] == "cutPlane" and cut["keep"] == -1)
        self.assertIsNone(feature_of_draft({"kind": "boolean", "op": "join", "body": 2, "tool": 2, "keep": False}, 7, "Combine 1"))
        combine = feature_of_draft({"kind": "boolean", "op": "cut", "body": 2, "tool": 5, "keep": False}, 7, "Combine 1")
        self.assertTrue(combine["kind"] == "boolean" and combine["tool"] == 5 and "keep" not in combine)
        kept = feature_of_draft({"kind": "boolean", "op": "join", "body": 2, "tool": 5, "keep": True}, 7, "Combine 1")
        self.assertTrue(kept["keep"])
        extract = feature_of_draft({"kind": "extract", "element": 4, "section": None, "thickness": 2, "op": "new"}, 8, "Body 1")
        self.assertTrue(extract["kind"] == "extract" and "target" not in extract)
        mirror = feature_of_draft({"kind": "mirror", "body": 2, "plane": {"kind": "face", "face": face(1, [1, 0, 0])["fingerprint"]}, "join": False, "symmetry": {"status": "idle"}}, 9, "Mirror 1")
        self.assertTrue(mirror["kind"] == "mirror" and mirror["plane"]["kind"] == "face" and not mirror["join"])

    def test_built_on_cannot_be_removed(self):
        features = [
            {"id": 1, "kind": "sketch", "name": "Sketch 1", "plane": {"kind": "world", "axis": "z", "offset": 0}, "frame": XY, "sketch": empty_sketch(), "visible": True},
            {"id": 2, "kind": "extrude", "name": "Extrude 1", "sketchId": 1, "regions": [], "extent": {"kind": "distance", "from": 0, "to": 10}, "op": "new", "visible": True},
            {"id": 3, "kind": "shell", "name": "Shell 1", "body": 2, "faces": [], "thickness": 1, "visible": True},
        ]
        self.assertEqual([f["id"] for f in dependents_of(2, features)], [3])
        self.assertEqual(dependents_of(3, features), [])

    def test_trim_opens_with_surfaces_and_their_tolerance(self):
        bodies = BODIES + [
            {"id": 5, "name": "Surface 1", "surface": True},
            {"id": 6, "name": "Surface 2", "surface": True},
        ]
        results = {5: {"id": 5, "status": "ok", "surface": {"rms": 0.03}}, 6: {"id": 6, "status": "ok", "surface": {"rms": 0.01}}}
        d = start_feature("trim", bodies, results=results)
        self.assertEqual(d["tools"], [{"kind": "body", "id": 5}, {"kind": "body", "id": 6}])
        self.assertEqual(d["tolerance"], 0.09)
        self.assertTrue(feature_draft_ready(d))
        self.assertEqual(trim_tolerance_for([{"kind": "element", "id": 9}], {}), 0.3)
        self.assertEqual(trim_tolerance_for([{"kind": "body", "id": 6}], results), 0.05)
        self.assertEqual(trim_tolerance_for([{"kind": "body", "id": 5}], {5: {"surface": {"rms": 1}}}), 0.5)
        f = feature_of_draft(d, 7, "Trim 1")
        self.assertTrue(f["kind"] == "trim" and len(f["tools"]) == 2 and f["overlap"] == 0.5)
        self.assertFalse(feature_draft_ready({**d, "tools": []}))


class ExtrudeRevolve(unittest.TestCase):
    """reSolidSlice.ts's starting drafts and the two Create keys."""

    def test_defaults_and_ready(self):
        sk = empty_sketch()
        add_rectangle(sk, [0, 0], [10, 5])
        features = [{"id": 1, "kind": "sketch", "name": "Sketch 1", "plane": {"kind": "world", "axis": "z", "offset": 0}, "frame": XY, "sketch": sk, "visible": True}]
        e = start_extrude(features)
        self.assertEqual((e["sketchId"], len(e["regions"]), e["extent"], e["draftDeg"], e["op"]), (1, 1, {"kind": "distance", "from": 0, "to": 10}, 0, "join"))
        self.assertTrue(extrude_draft_ready(e))
        self.assertFalse(extrude_draft_ready({**e, "extent": {"kind": "toPlane", "from": 0, "plane": None}}))
        r = start_revolve(features)
        self.assertEqual((r["angleDeg"], r["pitch"], r["leftHanded"], r["op"]), (360, 0, False, "join"))
        self.assertFalse(revolve_draft_ready(r))
        self.assertTrue(revolve_draft_ready({**r, "axis": {"kind": "world", "axis": "x"}}))
        self.assertFalse(revolve_draft_ready({**r, "axis": {"kind": "world", "axis": "x"}, "angleDeg": 720}))
        self.assertTrue(revolve_draft_ready({**r, "axis": {"kind": "world", "axis": "x"}, "angleDeg": 720, "pitch": 2}))

    def test_names_and_step_keys(self):
        name, counters = name_for({"extrude": 2}, "extrude")
        self.assertEqual((name, counters), ("Extrude 3", {"extrude": 3}))
        # cyrb53 of the text, as the original's (checked against Node).
        self.assertEqual(step_file_key("ISO-10303-21;"), "d-ibqbrc6lfc")


if __name__ == "__main__":
    unittest.main()
