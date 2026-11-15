# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/core/build.ts, booleanGuard.ts (and the decisions plugins/reverse/tests/reBooleanGuard.test.ts, reBuild*.test.ts make of them)
# SPDX-License-Identifier: AGPL-3.0-only
#
# The Builder's own decisions, on a kernel of boxes (reverse_fakekernel.py):
# the guard's verdict on given volumes, a boolean played again the kernel's
# other ways and accepted with a warning, refused when no way stands,
# islands made bodies of their own, the prefix cache taking up the steps it
# holds, and the failure flow (a failed step says why, the build carries on,
# what used its body fails in turn). Every step kind has a play.
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

from reverse_fakekernel import FakeKernel  # noqa: E402
from scanrulerfc.reverse.build import DISPATCH, LATER, Builder, copy_motions, reference_faces, volume_refusal  # noqa: E402
from scanrulerfc.reverse.features import island_id  # noqa: E402
from scanrulerfc.reverse.loops import rectangle_loop  # noqa: E402
from scanrulerfc.reverse.steps import STEP_KINDS  # noqa: E402


def rect(x0, y0, x1, y1, z=0.0):
    return {"outer": rectangle_loop([x0, y0, z], [1, 0, 0], [0, 1, 0], x1 - x0, y1 - y0), "holes": []}


def extrude(i, prof, frm, to, op="new", target=None):
    s = {"kind": "extrude", "id": i, "name": f"Extrude {i}", "profiles": [prof], "regions": [], "dir": [0, 0, 1], "origin": [0, 0, 0], "from": frm, "to": to, "draftDeg": 0, "op": op}
    if target is not None:
        s["target"] = target
    return s


class Guard(unittest.TestCase):
    def test_join(self):
        self.assertIsNone(volume_refusal({"kind": "join", "parts": [100, 50], "result": 120}))
        self.assertEqual(volume_refusal({"kind": "join", "parts": [100, 50], "result": 90}), "the join lost volume — 90 mm³, less than the largest part alone, 100 mm³")
        self.assertEqual(volume_refusal({"kind": "join", "parts": [100, 50], "result": 151}), "the join made volume — 151 mm³, more than its parts together, 150 mm³")
        # Within the slack (0.2 %).
        self.assertIsNone(volume_refusal({"kind": "join", "parts": [100, 50], "result": 99.9}))

    def test_cut(self):
        self.assertIsNone(volume_refusal({"kind": "cut", "body": 100, "result": 60}))
        self.assertEqual(volume_refusal({"kind": "cut", "body": 100, "result": 101}), "the cut gained volume — 101 mm³ from 100 mm³")
        self.assertEqual(volume_refusal({"kind": "cut", "body": 100, "result": -1}), "the cut left less than nothing")

    def test_combine_identity(self):
        self.assertIsNone(volume_refusal({"kind": "union", "body": 1000, "tool": 1000, "common": 500, "result": 1500}))
        self.assertEqual(volume_refusal({"kind": "union", "body": 1000, "tool": 1000, "common": 500, "result": 1400}),
                         "the join is 1400 mm³ where the two bodies less what they share come to 1500 mm³")
        self.assertIsNone(volume_refusal({"kind": "union", "body": 1000, "tool": 1000, "result": 1400}))
        self.assertEqual(volume_refusal({"kind": "subtract", "body": 1000, "tool": 300, "result": 600}),
                         "the cut took more than the tool holds — 600 mm³ left of 1000 mm³ by a tool of 300 mm³")
        self.assertEqual(volume_refusal({"kind": "subtract", "body": 1000, "tool": 300, "common": 200, "result": 750}),
                         "the cut left 750 mm³ where the body less what it shares with the tool comes to 800 mm³")
        self.assertEqual(volume_refusal({"kind": "intersect", "body": 1000, "tool": 300, "result": 301}),
                         "what the bodies share came to 301 mm³, more than the smaller holds, 300 mm³")
        self.assertEqual(volume_refusal({"kind": "join", "parts": [1 / 3], "result": 0.1}),
                         "the join lost volume — 0.1 mm³, less than the largest part alone, 0.333333 mm³")


class Dispatch(unittest.TestCase):
    def test_every_step_kind_has_a_play(self):
        self.assertEqual(set(DISPATCH), set(STEP_KINDS))
        self.assertEqual({k for k, v in DISPATCH.items() if v == "later"}, set(LATER))
        self.assertTrue(all(n > 6 for n in LATER.values()))

    def test_a_later_kind_fails_in_its_place_and_the_build_goes_on(self):
        b = Builder(FakeKernel())
        out = b.build([{"kind": "loft", "id": 1, "name": "Loft 1"}, extrude(2, rect(0, 0, 10, 10), 0, 10)])
        self.assertEqual([r["status"] for r in out["results"]], ["failed", "ok"])
        self.assertIn("build step 10", out["results"][0]["message"])


class Retries(unittest.TestCase):
    def test_join_played_again_stands_with_a_warning(self):
        # Exact, the join loses half; with its faces kept as cut, it is right.
        k = FakeKernel({"fuse": lambda k, v: v if k.splitting or k.fuzz > 0 else v / 2})
        out = Builder(k).build([extrude(1, rect(0, 0, 10, 10), 0, 10), extrude(2, rect(5, 0, 15, 10), 0, 10, "join")])
        r = out["results"][1]
        self.assertEqual(r["status"], "ok", r)
        self.assertIn("played again the kernel's other way: the first result the join lost volume", r["warning"])
        self.assertEqual([round(x["volume"]) for x in out["bodies"]], [1500])

    def test_no_way_stands_refuses_saying_why(self):
        k = FakeKernel({"fuse": lambda k, v: v / 2})
        out = Builder(k).build([extrude(1, rect(0, 0, 10, 10), 0, 10), extrude(2, rect(5, 0, 15, 10), 0, 10, "join")])
        r = out["results"][1]
        self.assertEqual(r["status"], "failed")
        self.assertTrue(r["message"].startswith("Joining cannot stand: the join lost volume — 750 mm³"), r["message"])
        # The body stands as it was before the failed join.
        self.assertEqual([round(x["volume"]) for x in out["bodies"]], [1000])

    def test_retry_order_is_splits_then_fuzzy_then_coarse(self):
        # Open (no volume) every way but the coarse fuzzy one: each way is
        # tried in turn, and the first that closes is held to the guard.
        seen = []

        def fuse(k, v):
            seen.append(("split" if k.splitting else "exact") if k.fuzz == 0 else k.fuzz)
            return v if k.fuzz == 1e-3 else 0

        out = Builder(FakeKernel({"fuse": fuse})).build([extrude(1, rect(0, 0, 10, 10), 0, 10), extrude(2, rect(5, 0, 15, 10), 0, 10, "join")])
        self.assertEqual(out["results"][1]["status"], "ok")
        self.assertIn("the first result left no closed solid", out["results"][1]["warning"])
        self.assertEqual(seen, ["exact", "split", 1e-4, 1e-3])

    def test_a_retry_that_closes_but_is_still_wrong_is_refused(self):
        # As the original: the first way that closes is the one judged.
        k = FakeKernel({"fuse": lambda k, v: v if k.fuzz > 0 else v / 2})
        out = Builder(k).build([extrude(1, rect(0, 0, 10, 10), 0, 10), extrude(2, rect(5, 0, 15, 10), 0, 10, "join")])
        self.assertEqual(out["results"][1]["status"], "failed")


class Islands(unittest.TestCase):
    def test_a_cut_through_the_waist_leaves_two_bodies(self):
        steps = [extrude(1, rect(0, 0, 30, 10), 0, 10), extrude(2, rect(10, -1, 20, 11), -1, 11, "cut")]
        b = Builder(FakeKernel())
        out = b.build(steps)
        self.assertEqual(out["results"][1]["status"], "ok")
        self.assertEqual(sorted(out["results"][1]["bodies"]), [1, 2])
        self.assertIn("leaves Extrude 1 in 2 pieces", out["results"][1]["warning"])
        self.assertEqual(sorted(round(x["volume"]) for x in out["bodies"]), [1000, 1000])

    def test_a_new_feature_apart_takes_island_ids(self):
        k = FakeKernel()
        b = Builder(k)
        s = extrude(1, rect(0, 0, 10, 10), 0, 10)
        b.build([s])
        two = k.fuse_tracked(b.body(1), k.extrude(k.face(rect(50, 0, 60, 10)), [0, 0, 1], 0, 10))["shape"]
        ids = b.settle(b.fresh_id(5), "Apart", two, {}, 5)
        self.assertEqual(ids, [5, island_id(5, 1)])

    def test_a_cut_that_meets_nothing_fails(self):
        out = Builder(FakeKernel()).build([extrude(1, rect(0, 0, 10, 10), 0, 10), extrude(2, rect(50, 50, 60, 60), 0, 10, "cut")])
        self.assertEqual(out["results"][1], {"id": 2, "status": "failed", "message": "The cut meets no body — there is nothing for it to take out."})

    def test_a_join_on_a_target_it_misses_is_refused(self):
        out = Builder(FakeKernel()).build([extrude(1, rect(0, 0, 10, 10), 0, 10), extrude(2, rect(50, 50, 60, 60), 0, 10, "join", target=1)])
        self.assertIn("meets nothing of Extrude 1", out["results"][1]["message"])


class PrefixCache(unittest.TestCase):
    def test_the_same_steps_are_taken_up_and_a_change_plays_from_it(self):
        k = FakeKernel()
        b = Builder(k)
        steps = [extrude(1, rect(0, 0, 10, 10), 0, 10), extrude(2, rect(5, 0, 15, 10), 0, 10, "join"), extrude(3, rect(2, 2, 4, 4), -1, 11, "cut")]
        first = b.build(steps, reuse=True)
        self.assertEqual((first["steps"]["recomputed"], first["steps"]["restored"]), (3, 0))
        calls = len(k.calls)
        again = b.build(steps, reuse=True)
        self.assertEqual((again["steps"]["recomputed"], again["steps"]["restored"]), (0, 3))
        self.assertEqual(len(k.calls), calls)
        self.assertEqual(again["results"], first["results"])
        steps[2] = extrude(3, rect(2, 2, 5, 5), -1, 11, "cut")
        third = b.build(steps, reuse=True)
        self.assertEqual((third["steps"]["recomputed"], third["steps"]["restored"]), (1, 2))
        self.assertEqual(round(third["bodies"][0]["volume"]), 1500 - 90)

    def test_without_reuse_every_step_plays(self):
        b = Builder(FakeKernel())
        steps = [extrude(1, rect(0, 0, 10, 10), 0, 10)]
        b.build(steps, reuse=True)
        self.assertEqual(b.build(steps)["steps"]["recomputed"], 1)


class FailureFlow(unittest.TestCase):
    def test_a_lost_pick_fails_loudly_and_independents_stand(self):
        lost = {"kind": "line", "mid": [10, 10, 5], "dir": [0, 0, 1], "length": 10, "faces": [], "origin": 1}
        steps = [
            extrude(1, rect(0, 0, 10, 10), 0, 10),
            {"kind": "fillet", "id": 2, "name": "Fillet 1", "body": 1, "edges": [lost], "radius": 1, "chain": False},
            extrude(3, rect(50, 0, 60, 10), 0, 10),
            {"kind": "shell", "id": 4, "name": "Shell 1", "body": 99, "faces": [], "thickness": 1},
            {"kind": "failed", "id": 5, "name": "Hole 1", "message": "The hole needs a radius."},
        ]
        out = Builder(FakeKernel()).build(steps)
        rs = {r["id"]: r for r in out["results"]}
        self.assertEqual(rs[2]["status"], "failed")
        self.assertTrue(rs[2]["message"].startswith("The edge this fillet was on is gone (was: "), rs[2]["message"])
        self.assertEqual(rs[3]["status"], "ok")
        self.assertEqual(rs[4]["message"], "The body this feature works on is gone, or failed to build.")
        self.assertEqual(rs[5], {"id": 5, "status": "failed", "message": "The hole needs a radius."})
        self.assertEqual(sorted(x["id"] for x in out["bodies"]), [1, 3])

    def test_a_dependent_of_a_failed_feature_fails_in_turn(self):
        steps = [
            extrude(1, rect(0, 0, 10, 10), 0, 0),
            {"kind": "cutPlane", "id": 2, "name": "Cut 1", "body": 1, "plane": {"origin": [5, 0, 0], "normal": [1, 0, 0]}, "keep": 1},
        ]
        out = Builder(FakeKernel()).build(steps)
        self.assertEqual(out["results"][0]["message"], "The extrusion has no length.")
        self.assertEqual(out["results"][1]["message"], "The body this feature works on is gone, or failed to build.")


class Pure(unittest.TestCase):
    def test_copy_motions(self):
        lin = copy_motions({"mode": "linear", "dir": [1, 0, 0], "count": 3, "step": 20, "origin": [0, 0, 0]})
        self.assertEqual([m["t"] for m in lin], [[20, 0, 0], [40, 0, 0]])
        grid = copy_motions({"mode": "linear", "dir": [1, 0, 0], "count": 2, "step": 5, "origin": [0, 0, 0], "grid": {"dir": [0, 1, 0], "count": 2, "step": 7}})
        self.assertEqual([m["t"] for m in grid], [[5, 0, 0], [0, 7, 0], [5, 7, 0]])
        circ = copy_motions({"mode": "circular", "dir": [0, 0, 1], "count": 4, "step": 360, "origin": [10, 0, 0]})
        self.assertEqual(len(circ), 3)
        # A quarter turn about (10, 0, 0) takes the origin of the world to (10, -10, 0).
        r, t = circ[0]["r"], circ[0]["t"]
        self.assertAlmostEqual(t[0], 10)
        self.assertAlmostEqual(t[1], -10)
        self.assertAlmostEqual(r[1], -1)

    def test_reference_faces(self):
        # Three edges round one face: it is the reference of each; flipped, the other.
        self.assertEqual(reference_faces([(1, 2), (1, 3), (4, 1)], False), [1, 1, 1])
        self.assertEqual(reference_faces([(1, 2), (1, 3), (4, 1)], True), [2, 3, 4])


if __name__ == "__main__":
    unittest.main()
