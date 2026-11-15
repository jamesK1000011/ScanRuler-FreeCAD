# SPDX-License-Identifier: AGPL-3.0-only
# A click on the part for the open feature box (ScanRuler by Stefan Hermann /
# CNC Kitchen, bodyPicks.ts and the box's pick toggles, ported): the edge
# nearest the click found in the body's topology and toggled in a fillet's
# edges, the face under it in a shell's faces, a pick on another body
# starting the picks again there, and an extrude's end put through the
# point on the side of the sketch plane it was clicked. On a stand-in
# builder: a 10 mm cube's top edges and two of its faces.
import os
import sys
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

from test_reverse_editor import Part  # noqa: E402
from scanrulerfc.reverse import picks as K  # noqa: E402
from scanrulerfc.reverse.editor import Editor  # noqa: E402

FRONT = {"kind": "line", "mid": [5, 0, 10], "dir": [1, 0, 0], "length": 10, "faces": [{"kind": "plane", "dir": [0, 0, 1]}, {"kind": "plane", "dir": [0, -1, 0]}], "origin": 2}
BACK = {**FRONT, "mid": [5, 10, 10], "faces": [{"kind": "plane", "dir": [0, 0, 1]}, {"kind": "plane", "dir": [0, 1, 0]}]}
TOP = {"kind": "plane", "centroid": [5, 5, 10], "dir": [0, 0, 1], "area": 100, "origin": 2}
SIDE = {"kind": "plane", "centroid": [5, 0, 5], "dir": [0, -1, 0], "area": 100, "origin": 2}


class Builder:
    """Body 2 a cube: its top front and back edges, its top and front faces
    (a face here is the plane z = 10 or y = 0)."""

    def __init__(self):
        self.kernel = types.SimpleNamespace(faces_of=lambda shape: ["top", "side"], distance_to_point=lambda f, p: abs(p[2] - 10) if f == "top" else abs(p[1]))

    def body_by_id(self, i):
        return {"shape": "cube"} if i in (2, 3) else None

    def topology(self, body, deflection):
        return {"edges": [{"fingerprint": FRONT, "polyline": [0, 0, 10, 10, 0, 10]}, {"fingerprint": BACK, "polyline": [0, 10, 10, 10, 10, 10]}],
                "faces": [{"fingerprint": TOP}, {"fingerprint": SIDE}]}


class Picks(unittest.TestCase):
    def setUp(self):
        self.b = Builder()

    def test_the_edge_and_the_face_under_the_click(self):
        self.assertEqual(K.pick_on_body(self.b, 2, [3, 0.4, 9.8], "edges"), FRONT)
        self.assertEqual(K.pick_on_body(self.b, 2, [3, 9.5, 10], "edges"), BACK)
        self.assertIsNone(K.pick_on_body(self.b, 2, [5, 5, 10], "edges"))  # the middle of the top: no edge in reach
        self.assertEqual(K.pick_on_body(self.b, 2, [5, 5, 10], "faces"), TOP)
        self.assertEqual(K.pick_on_body(self.b, 2, [5, 0, 3], "faces"), SIDE)
        self.assertIsNone(K.pick_on_body(self.b, 9, [5, 0, 3], "faces"))

    def test_toggled_and_moved_to_another_body(self):
        f = {"kind": "fillet", "body": 2, "edges": [], "radius": 1}
        f = K.toggled(f, 2, FRONT)
        f = K.toggled(f, 2, BACK)
        self.assertEqual(f["edges"], [FRONT, BACK])
        f = K.toggled(f, 2, dict(FRONT))
        self.assertEqual(f["edges"], [BACK])
        f = K.toggled(f, 3, FRONT)
        self.assertEqual((f["body"], f["edges"]), (3, [FRONT]))
        self.assertIs(K.toggled({"kind": "extrude"}, 2, FRONT)["kind"], "extrude")

    def test_the_editor_takes_the_click(self):
        ed = Editor()
        ed.open_new("shell", {"features": [], "nextFeatureId": 2}, [{"id": 2, "surface": False, "box": None}])
        self.assertTrue(ed.wants_clicks())
        self.assertTrue(ed.click_part([5, 5, 10], 2, self.b))
        self.assertEqual(ed.record["faces"], [TOP])
        self.assertEqual([g["side"] for g in ed.grips()], ["thickness"])
        self.assertFalse(ed.click_part([5, 5, 10], None, self.b))  # the scan, not a body
        self.assertEqual(K.picks_line(ed.record), "1 face picked")
        self.assertTrue(K.picks_line({"kind": "fillet", "edges": []}).startswith("Click the edges of the body"))
        self.assertIsNone(K.picks_line({"kind": "extrude"}))
        # Each hint a whole sentence, its full stop too.
        self.assertTrue(all(t.endswith(".") for t in K.NONE_PICKED.values()))


class ExtrudeEnd(unittest.TestCase):
    def setUp(self):
        self.p = Part()
        self.ed = Editor()
        self.ed.open_new("extrude", self.p.store.part())
        self.feats = self.p.store.part()["features"]

    def test_in_front_sets_to_behind_sets_from(self):
        self.assertTrue(self.ed.wants_clicks())
        self.assertTrue(self.ed.click_part([3, 3, 24.638], features=self.feats))
        self.assertEqual(self.ed.record["extent"], {"kind": "distance", "from": 0, "to": 24.64})
        self.assertTrue(self.ed.click_part([3, 3, -7.5], features=self.feats))
        self.assertEqual(self.ed.record["extent"], {"kind": "distance", "from": -7.5, "to": 24.64})
        self.assertFalse(self.ed.click_part([3, 3, -7.5], features=self.feats))  # nothing changes

    def test_symmetric_and_typed_expressions(self):
        self.ed.set_fields(extent={"kind": "symmetric", "total": 10}, exprs={"extent.total": "h"})
        self.assertTrue(self.ed.click_part([0, 0, -6], features=self.feats))
        self.assertEqual(self.ed.record["extent"], {"kind": "symmetric", "total": 12})
        self.assertNotIn("exprs", self.ed.record)


if __name__ == "__main__":
    unittest.main()
