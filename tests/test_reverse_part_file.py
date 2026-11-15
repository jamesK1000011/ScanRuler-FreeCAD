# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/tests/reMirrorMigrate.test.ts, reProjectFile.test.ts, reProjectHostile.test.ts, rePatternStep.test.ts
# SPDX-License-Identifier: AGPL-3.0-only
#
# The Reverse engineer part of a project file: the records byte for byte
# as the original writes them, the migrations to part version 3, what a
# saved part opens as, and what a hostile file cannot make of it. The
# original runs these through its store and project manifest; here the
# store is the state dict part_file.py reads and writes. Cases that build
# bodies (the pattern's copies, hidden bodies after a build, the snapshot
# key) need the kernel and wait for build order step 5.
import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from scanrulerfc.reverse import part_file as P  # noqa: E402
from scanrulerfc.reverse.features import pattern_pitch  # noqa: E402
from scanrulerfc.reverse.regions import find_regions  # noqa: E402
from scanrulerfc.reverse.sketch import add_rectangle, empty_sketch  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
XY = {"origin": [0, 0, 0], "normal": [0, 0, 1], "basisU": [1, 0, 0], "basisV": [0, 1, 0]}


def rectangle_sketch(i, w, h, at=(0, 0)):
    sketch = empty_sketch()
    add_rectangle(sketch, list(at), [at[0] + w, at[1] + h])
    return {"id": i, "kind": "sketch", "name": f"Sketch {i}", "plane": {"kind": "world", "axis": "z", "offset": 0}, "frame": XY, "sketch": sketch, "visible": True}


def extrude_all(i, sketch, frm, to, op="new"):
    return {"id": i, "kind": "extrude", "name": f"Extrude {i}", "sketchId": sketch["id"], "regions": [r["key"] for r in find_regions(sketch["sketch"])], "extent": {"kind": "distance", "from": frm, "to": to}, "op": op, "visible": True}


def state(**kw):
    return {**P.empty_state(), **kw}


class ByteForByte(unittest.TestCase):
    def test_round_trip_is_the_originals_text(self):
        # Written by Node's JSON.stringify: numbers as JavaScript spells
        # them, index-like keys first in numeric order.
        with open(os.path.join(HERE, "reverse_fixtures", "part_roundtrip.json"), encoding="utf-8") as f:
            text = f.read()
        part = P.validate_reverse_part(P.loads(text))
        self.assertEqual(P.dumps(part), text)
        s = P.reverse_part_state(part)
        self.assertEqual([f["kind"] for f in s["features"]], ["sketch"])
        self.assertEqual([f["kind"] for f in s["rolledBack"]], ["surface"])
        again = P.collect_reverse_part({**s, "elementsShown": True})
        self.assertEqual(P.dumps(again), text)


class MirrorMigrate(unittest.TestCase):
    def setUp(self):
        s = rectangle_sketch(1, 10, 10)
        self.before = [
            s,
            extrude_all(2, s, 0, 10),
            {"id": 3, "kind": "mirror", "name": "Mirror 1", "body": 2, "plane": {"kind": "world", "axis": "x", "offset": 20}, "join": False, "visible": True},
            {"id": 4, "kind": "fillet", "name": "Fillet 1", "body": 2, "edges": [], "radius": 1, "chain": False, "visible": True},
            {"id": 5, "kind": "moveBody", "name": "Move 1", "bodies": [2, 7], "pivot": [0, 0, 0], "translate": [1, 0, 0], "rotate": [0, 0, 0], "copy": False, "visible": True},
        ]

    def test_copy_named_by_mirror_id(self):
        after = P.migrate_features(self.before, 2)
        self.assertEqual(after[2]["body"], 2)
        self.assertEqual(after[3]["body"], 3)
        self.assertEqual(after[4]["bodies"], [3, 7])
        self.assertEqual(after[:2], self.before[:2])

    def test_joined_and_current_left_alone(self):
        joined = [{**f, "join": True} if f["kind"] == "mirror" else f for f in self.before]
        self.assertEqual(P.migrate_features(joined, 2), joined)
        self.assertEqual(P.migrate_features(self.before, P.PART_VERSION), self.before)


class PatternStep(unittest.TestCase):
    def test_pitch_and_old_step(self):
        self.assertAlmostEqual(pattern_pitch(90, 4), 30, 12)
        self.assertAlmostEqual(pattern_pitch(360, 14), 25.714285714, 8)
        s = rectangle_sketch(1, 2, 2, (19, -1))
        pattern = {"id": 3, "kind": "pattern", "name": "Pattern 1", "body": 2, "mode": "circular", "axis": {"kind": "world", "axis": "z"}, "count": 3, "step": 77.142, "visible": True}
        migrated = [P.migrate_feature(f, 1) for f in [s, extrude_all(2, s, 0, 2), pattern]]
        self.assertAlmostEqual(migrated[2]["step"], 51.428, 12)
        # Where the copies then stand needs a build (kernel): not here.


class ProjectFile(unittest.TestCase):
    def test_saved_by_reference_and_back(self):
        frame = {"origin": [0, 0, 10], "normal": [0, 0, 1], "basisU": [1, 0, 0], "basisV": [0, 1, 0]}
        st = state(
            features=[
                {"id": 1, "kind": "sketch", "name": "Sketch 1", "plane": {"kind": "fitted", "frame": frame}, "frame": frame, "sketch": {"entities": [{"id": 1, "kind": "line", "a": [0, 0], "b": [10, 0]}], "constraints": [{"id": 2, "kind": "horizontal", "entity": 1, "inferred": True}], "nextId": 3}, "visible": True},
                {"id": 2, "kind": "extrude", "name": "Extrude 1", "sketchId": 1, "regions": ["r:1"], "extent": {"kind": "toPlane", "from": 0, "plane": {"kind": "plane", "id": 9}}, "op": "new", "visible": True},
                {"id": 3, "kind": "fillet", "name": "Fillet 1", "body": 2, "edges": [{"kind": "line", "mid": [5, 0, 10], "dir": [1, 0, 0], "length": 10, "faces": [{"kind": "plane", "dir": [0, -1, 0]}, {"kind": "plane", "dir": [0, 0, 1]}], "origin": 2}], "radius": 1.5, "chain": True, "visible": False},
                P.feature_from_json({"id": 4, "kind": "surface", "name": "Surface 1", "region": [7, 8, 9, 10], "fit": {"net": None, "degree": 3, "expandPct": 35, "smoothness": 0.01}, "visible": True}),
            ],
            nextFeatureId=5, nextOfKind={"sketch": 1, "extrude": 1, "fillet": 1, "surface": 1}, scanSeeThrough=False, bodiesSeeThrough=True, elementsShown=False,
        )
        self.assertIsNone(P.collect_reverse_part(P.empty_state()))
        part = P.collect_reverse_part(st)
        self.assertEqual(len(part["features"]), 4)
        self.assertEqual(P.loads(P.dumps(part))["features"][3]["region"], [7, 8, 9, 10])
        back = P.prepare(P.loads(P.dumps(part)))
        self.assertEqual([f["kind"] for f in back["features"]], ["sketch", "extrude", "fillet", "surface"])
        self.assertEqual(list(back["features"][3]["region"]), [7, 8, 9, 10])
        self.assertEqual(back["features"][3]["region"].typecode, "I")
        self.assertTrue(len(back["features"][2]["edges"][0]["faces"]) == 2 and back["features"][2]["visible"] is False)
        self.assertEqual(back["features"][1]["extent"]["plane"]["kind"], "plane")
        self.assertEqual(back["nextFeatureId"], 5)
        self.assertEqual(back["nextOfKind"], {"sketch": 1, "extrude": 1, "fillet": 1, "surface": 1})
        self.assertEqual((back["scanSeeThrough"], back["bodiesSeeThrough"], back["elementsShown"]), (False, True, False))
        # The rollback bar travels.
        rolled = P.collect_reverse_part({**back, "features": back["features"][:2], "rolledBack": back["features"][2:]})
        self.assertEqual([f["kind"] for f in rolled["features"]], ["sketch", "extrude", "fillet", "surface"])
        self.assertEqual(rolled["rolledTo"], 2)
        again = P.prepare(P.loads(P.dumps(rolled)))
        self.assertEqual([f["kind"] for f in again["features"]], ["sketch", "extrude"])
        self.assertEqual([f["kind"] for f in again["rolledBack"]], ["fillet", "surface"])
        self.assertIsNone(P.prepare(None))

    def test_old_opaque_key(self):
        part = {"features": [], "nextFeatureId": 1, "nextOfKind": {}, "elementsShown": True}
        s = P.reverse_part_state({**part, "bodyOpaque": False})
        self.assertEqual((s["scanSeeThrough"], s["bodiesSeeThrough"]), (False, True))
        s = P.reverse_part_state({**part, "bodyOpaque": True})
        self.assertEqual((s["scanSeeThrough"], s["bodiesSeeThrough"]), (None, False))
        sk = {"id": 1, "kind": "sketch", "name": "Sketch 1", "plane": {"kind": "fitted", "frame": XY}, "frame": XY, "sketch": empty_sketch(), "visible": True}
        saved = P.collect_reverse_part(state(features=[sk]))
        self.assertNotIn("scanSeeThrough", saved)
        self.assertIs(saved["bodiesSeeThrough"], False)

    def test_overlaps_switch(self):
        sk = {"id": 1, "kind": "sketch", "name": "Sketch 1", "plane": {"kind": "fitted", "frame": XY}, "frame": XY, "sketch": empty_sketch(), "visible": True}
        off = P.loads(P.dumps(P.collect_reverse_part(state(features=[sk], overlapsShown=False))))
        self.assertIs(off["overlapsShown"], False)
        self.assertIs(P.empty_state()["overlapsShown"], True)
        self.assertIs(P.prepare(off)["overlapsShown"], False)
        self.assertNotIn("overlapsShown", P.collect_reverse_part(state(features=[sk], overlapsShown=True)))

    def test_move_face_with_one_face(self):
        top = {"kind": "plane", "centroid": [20, 10, 10], "dir": [0, 0, 1], "area": 800, "origin": 2}
        s = P.prepare({"features": [{"id": 3, "kind": "moveFace", "name": "Move face 1", "body": 2, "face": top, "offset": 0.5, "visible": True}], "nextFeatureId": 4, "nextOfKind": {"moveFace": 1}, "bodyOpaque": False, "elementsShown": True})
        f = s["features"][0]
        self.assertEqual(f["faces"], [top])
        self.assertNotIn("face", f)

    def test_parameters_saved_and_read_back(self):
        st = state(
            parameters=[{"id": 1, "name": "width", "kind": "length", "expression": "40"}, {"id": 2, "name": "height", "kind": "length", "expression": "width / 2", "comment": "the boss"}],
            nextParameterId=3,
            features=[
                {"id": 1, "kind": "sketch", "name": "Sketch 1", "plane": {"kind": "world", "axis": "z", "offset": 0}, "frame": XY, "sketch": {"entities": [{"id": 1, "kind": "line", "a": [0, 0], "b": [40, 0]}], "constraints": [{"id": 2, "kind": "length", "entity": 1, "value": 40, "expr": "width"}], "nextId": 3}, "visible": True},
                {"id": 2, "kind": "extrude", "name": "Extrude 1", "sketchId": 1, "regions": ["r:1"], "extent": {"kind": "distance", "from": 0, "to": 20}, "op": "new", "exprs": {"extent.to": "height"}, "visible": True},
            ],
            nextFeatureId=3, nextOfKind={"sketch": 1, "extrude": 1},
        )
        part = P.collect_reverse_part(st)
        self.assertEqual(len(part["parameters"]), 2)
        self.assertEqual(part["nextParameterId"], 3)
        s = P.prepare(P.loads(P.dumps(part)))
        self.assertEqual(s["parameters"], st["parameters"])
        self.assertEqual(s["nextParameterId"], 3)
        self.assertEqual([r["value"] for r in s["parameterTable"]["readings"]], [40, 20])
        self.assertEqual(s["features"][1]["exprs"], {"extent.to": "height"})
        c = s["features"][0]["sketch"]["constraints"][0]
        self.assertEqual((c["value"], c["expr"]), (40, "width"))
        # (The store's setParameter rebuilding the extrude is the store's: not here.)
        bad = P.prepare({**part, "parameters": [{"id": 1, "name": "width", "kind": "length", "expression": "nothing"}]})
        r = bad["parameterTable"]["readings"][0]
        self.assertEqual((r["value"], r["error"]), (None, "there is no parameter “nothing”"))
        self.assertEqual(bad["features"][1]["extent"]["to"], 20)
        none = P.prepare({k: v for k, v in part.items() if k not in ("parameters", "nextParameterId")})
        self.assertEqual((none["parameters"], none["nextParameterId"]), ([], 1))
        counted = P.prepare({k: v for k, v in part.items() if k != "nextParameterId"})
        self.assertEqual(counted["nextParameterId"], 3)

    def test_malformed_parameters_refused(self):
        base = {"features": [], "nextFeatureId": 1, "nextOfKind": {}, "bodyOpaque": True, "elementsShown": True}
        with self.assertRaisesRegex(P.MalformedProject, "Malformed"):
            P.prepare({**base, "parameters": "none"})
        with self.assertRaisesRegex(P.MalformedProject, "parameter.kind"):
            P.prepare({**base, "parameters": [{"id": 1, "name": "a", "kind": "weight", "expression": "1"}]})
        with self.assertRaisesRegex(P.MalformedProject, "parameter.name"):
            P.prepare({**base, "parameters": [{"id": 1, "name": "a", "kind": "length", "expression": "1"}, {"id": 2, "name": "a", "kind": "length", "expression": "2"}]})
        with self.assertRaisesRegex(P.MalformedProject, "Malformed"):
            P.prepare({**base, "parameters": [{"id": 1, "name": "a", "kind": "length"}]})

    def test_malformed_part_refused(self):
        with self.assertRaisesRegex(P.MalformedProject, "reverse engineer entry"):
            P.prepare({"features": "none"})
        with self.assertRaisesRegex(P.MalformedProject, "Malformed"):
            P.prepare({"features": [], "nextFeatureId": 1, "nextOfKind": {}, "rolledTo": 3})


IMPORT = {"id": 1, "kind": "import", "name": "Import 1", "file": {"key": "k1", "name": "a.step", "size": 13}}


class Hostile(unittest.TestCase):
    def test_captured_twice_reads_the_same(self):
        st = state(features=[IMPORT], stepFiles={"k1": "ISO-10303-21;"})
        a = P.write_members(st)
        b = P.write_members(st)
        self.assertEqual((P.dumps(a[0]), a[1]), (P.dumps(b[0]), b[1]))
        self.assertEqual(a[1], {P.STEP_MEMBER: b'{"k1":"ISO-10303-21;"}'})
        self.assertEqual(P.prepare(a[0], a[1])["stepFiles"], {"k1": "ISO-10303-21;"})

    def test_key_like_an_object_property(self):
        f = {**IMPORT, "file": {"key": "constructor", "name": "a.step", "size": 1}}
        part, members = P.write_members(state(features=[f], stepFiles={}))
        self.assertEqual(members, {})
        self.assertNotIn("stepFiles", part)

    def test_ids_never_handed_out_twice(self):
        def part(next_id, **extra):
            return {"version": 3, "features": [{"id": 7, "kind": "import", "name": "Import 1", "file": {"key": "k", "name": "a.step", "size": 1}, "visible": True}], "nextFeatureId": next_id, "nextOfKind": {}, "elementsShown": True, **extra}

        for bad in (7, 3, -3, 0.5, 0):
            s = P.prepare(part(bad, parameters=[{"id": 4, "name": "a", "kind": "number", "expression": "1"}], nextParameterId=2))
            self.assertEqual((s["nextFeatureId"], s["nextParameterId"]), (8, 5))
        self.assertEqual(P.prepare(part(20))["nextFeatureId"], 20)
        with self.assertRaises(P.MalformedProject):
            P.prepare(part(8, nextOfKind={"extrude": 0.5}))


class Archive(unittest.TestCase):
    def test_reads_a_scanruler_archive(self):
        st = state(features=[IMPORT], stepFiles={"k1": "ISO-10303-21;"})
        part, members = P.write_members(st)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "a.scanruler")
            with zipfile.ZipFile(path, "w") as z:
                z.writestr(P.PROJECT_MEMBER, P.dumps({"appVersion": "0.1.0", "workspace": "reverse", P.KEY: part}))
                for name, data in members.items():
                    z.writestr(name, data)
            got, got_members = P.read_scanruler(path)
        self.assertEqual(P.dumps(got), P.dumps(part))
        self.assertEqual(P.prepare(got, got_members)["stepFiles"], {"k1": "ISO-10303-21;"})


if __name__ == "__main__":
    unittest.main()
