# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/app/projectSection.ts, state/reDrafts.ts (bodyColor) (and the undo promises of plugins/reverse/tests/reUndo*.test.ts)
# SPDX-License-Identifier: AGPL-3.0-only
#
# The container and its bodies: the colours a body wears, the rollback bar,
# the part read and migrated, a whole build from a part; in a FreeCAD
# document, one transaction an edit, undo and redo putting PartJson and the
# bodies back, the container built once an edit and bodies matched by id.
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
if os.environ.get("FREECAD_LIB"):
    sys.path.append(os.environ["FREECAD_LIB"])
try:
    import FreeCAD  # noqa: F401
    import Part  # noqa: F401

    HAVE_FC = True
except ImportError:
    HAVE_FC = False

from reverse_fakekernel import FakeKernel  # noqa: E402
from scanrulerfc.reverse import doc as D  # noqa: E402
from scanrulerfc.reverse.build import Builder  # noqa: E402
from scanrulerfc.reverse.part_file import dumps  # noqa: E402
from scanrulerfc.reverse.regions import find_regions  # noqa: E402
from scanrulerfc.reverse.sketch import add_rectangle, empty_sketch  # noqa: E402

XY = {"origin": [0, 0, 0], "normal": [0, 0, 1], "basisU": [1, 0, 0], "basisV": [0, 1, 0]}


def cube_features(side=10, at=0, sid=1, eid=2):
    s = empty_sketch()
    add_rectangle(s, [at, 0], [at + side, side])
    sk = {"id": sid, "kind": "sketch", "name": f"Sketch {sid}", "plane": {"kind": "world", "axis": "z", "offset": 0}, "frame": XY, "sketch": s, "visible": True}
    ex = {"id": eid, "kind": "extrude", "name": f"Extrude {eid}", "sketchId": sid, "regions": [r["key"] for r in find_regions(s)], "extent": {"kind": "distance", "from": 0, "to": side}, "op": "new", "visible": True}
    return [sk, ex]


def part(features, **more):
    return {**D.empty_part(), "features": features, "nextFeatureId": max(f["id"] for f in features) + 1, **more}


class Pure(unittest.TestCase):
    def test_body_colours_are_the_originals(self):
        self.assertEqual(D.body_color(2), "#6d4bbd")
        self.assertEqual(D.body_color(2 + 1 / 1024), "#2e7d46")
        self.assertEqual(D.body_color(3), "#1877c0")
        self.assertEqual(D.rgb("#ff8000"), (1.0, 128 / 255, 0.0))

    def test_words(self):
        self.assertEqual(D.transaction_label("add", "Extrude 2"), "Reverse: add Extrude 2")
        self.assertEqual(D.transaction_label("build"), "Reverse: build")
        self.assertEqual(D.status_of([{"status": "ok"}, {"status": "failed"}]), "1 failed")
        self.assertEqual(D.status_of([]), "ok")

    def test_body_plan(self):
        self.assertEqual(D.body_plan([2, 3], [3, 4]), {"add": [4], "remove": [2], "keep": [3]})

    def test_rollback_bar_is_a_count(self):
        f = cube_features()
        self.assertEqual(D.built_features({"features": f}), f)
        self.assertEqual(D.built_features({"features": f, "rolledTo": 1}), f[:1])
        self.assertEqual(D.built_features({"features": f, "rolledTo": 0}), [])

    def test_part_read_and_migrated(self):
        self.assertEqual(D.part_of(""), D.empty_part())
        old = {"version": 2, "features": [*cube_features(), {"id": 3, "kind": "moveFace", "name": "Move face 3", "body": 2, "face": {"kind": "plane", "centroid": [10, 5, 5], "dir": [1, 0, 0], "area": 100, "origin": 2}, "offset": 1, "visible": True}],
               "nextFeatureId": 4, "nextOfKind": {}}
        p = D.part_of(dumps(old))
        self.assertEqual(p["version"], 3)
        self.assertEqual(len(p["features"][2]["faces"]), 1)
        self.assertNotIn("face", p["features"][2])

    def test_a_part_builds(self):
        out = D.build_part(part(cube_features()), Builder(FakeKernel()))
        self.assertEqual([r["status"] for r in out["results"]], ["ok"])
        self.assertEqual([round(b["volume"]) for b in out["bodies"]], [1000])
        rolled = D.build_part(part(cube_features(), rolledTo=1), Builder(FakeKernel()))
        self.assertEqual(rolled["bodies"], [])

    def test_parameters_are_read(self):
        f = cube_features()
        f[1]["exprs"] = {"extent.to": "h"}
        out = D.build_part(part(f, parameters=[{"id": 1, "name": "h", "kind": "length", "expression": "4"}], nextParameterId=2), Builder(FakeKernel()))
        self.assertEqual([round(b["volume"]) for b in out["bodies"]], [400])
        self.assertEqual(out["parameters"][0]["value"], 4)


@unittest.skipUnless(HAVE_FC, "needs FreeCAD")
class InADocument(unittest.TestCase):
    def setUp(self):
        self.doc = FreeCAD.newDocument("ReverseDocTest")
        self.doc.UndoMode = 1
        self.c = D.make_container(self.doc)
        self.doc.recompute()
        self.doc.clearUndos()

    def tearDown(self):
        D.forget(self.c)
        FreeCAD.closeDocument(self.doc.Name)

    def add(self, features):
        def change(p):
            return {**p, "features": [*p["features"], *features], "nextFeatureId": max(f["id"] for f in features) + 1}

        return D.edit(self.c, "add", features[-1]["name"], change)

    def test_an_edit_is_one_undo_step_and_undo_puts_it_back(self):
        results = self.add(cube_features())
        self.assertEqual([r["status"] for r in results], ["ok"])
        self.assertEqual(self.doc.UndoCount, 1)
        self.assertEqual(self.doc.UndoNames[0], "Reverse: add Extrude 2")
        bodies = D.bodies_of(self.c)
        self.assertEqual([b.BodyId for b in bodies], [2])
        self.assertAlmostEqual(bodies[0].Shape.Volume, 1000, places=6)
        self.assertAlmostEqual(self.c.Shape.Volume, 1000, places=6)
        self.assertEqual(self.c.Status, "ok")
        self.doc.undo()
        self.assertEqual(D.part_of(self.c.PartJson)["features"], [])
        self.assertEqual(D.bodies_of(self.c), [])
        self.doc.redo()
        self.assertEqual([b.BodyId for b in D.bodies_of(self.c)], [2])

    def test_bodies_matched_by_id_keep_their_label(self):
        self.add(cube_features())
        body = D.bodies_of(self.c)[0]
        body.Label = "Bracket"
        self.add(cube_features(side=5, at=20, sid=3, eid=4))
        by_id = {b.BodyId: b for b in D.bodies_of(self.c)}
        self.assertEqual(sorted(by_id), [2, 4])
        self.assertEqual(by_id[2].Label, "Bracket")

    def test_the_container_builds_once_an_edit(self):
        calls = []
        real = D.Container.execute

        def counted(proxy, obj):
            calls.append(obj.Name)
            return real(proxy, obj)

        D.Container.execute = counted
        try:
            self.add(cube_features())
        finally:
            D.Container.execute = real
        self.assertEqual(calls, [self.c.Name])

    def test_a_failing_feature_is_said_not_raised(self):
        def change(p):
            return {**p, "features": [*cube_features(), {"id": 3, "kind": "shell", "name": "Shell 3", "body": 99, "faces": [], "thickness": 1, "visible": True}], "nextFeatureId": 4}

        results = D.edit(self.c, "add", "Shell 3", change)
        self.assertEqual(self.c.Status, "1 failed")
        self.assertEqual(json.loads(self.c.Results)[-1]["status"], "failed")
        self.assertEqual(results[-1]["message"], "The body this feature works on is gone, or failed to build.")


if __name__ == "__main__":
    unittest.main()
