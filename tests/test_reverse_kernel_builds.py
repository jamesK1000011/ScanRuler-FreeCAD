# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/core/build.ts (the builds of plugins/reverse/tests/reKit.ts's kind)
# SPDX-License-Identifier: AGPL-3.0-only
#
# The fixture feature lists (tests/reverse_fixtures/kernel_builds.json, made
# by tests/tools/make_reverse_kernel_fixtures.py): each is a valid record
# list that resolves to the build steps meant, here; on FreeCAD each builds
# to the volumes worked out by hand, within the design's bars (1e-6 on
# analytic solids, looser where a fixture says), with the statuses meant; a
# sheet (a surface body) to its area.
import json
import math
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
if os.environ.get("FREECAD_LIB"):
    sys.path.append(os.environ["FREECAD_LIB"])
try:
    import FreeCAD  # noqa: F401
    import Part  # noqa: F401

    HAVE_FC = True
except ImportError:
    HAVE_FC = False
NEEDS = "needs FreeCAD"

from scanrulerfc.reverse.parameters import apply_parameters, evaluate_parameters  # noqa: E402
from scanrulerfc.reverse.part_file import validate_feature_json  # noqa: E402
from scanrulerfc.reverse.regions import find_regions  # noqa: E402
from scanrulerfc.reverse.resolve import resolve_features  # noqa: E402

CTX = {"sections": [], "elements": [], "modelCenter": [0, 0, 0]}
REL = 1e-6

with open(os.path.join(HERE, "reverse_fixtures", "kernel_builds.json"), encoding="utf-8") as _f:
    FIXTURES = json.load(_f)["fixtures"]


def steps_of(fx):
    features = fx["features"]
    if fx.get("parameters"):
        features = apply_parameters(features, evaluate_parameters(fx["parameters"])["scope"])["features"]
    return features, resolve_features(features, CTX, lambda f: find_regions(f["sketch"]))


class Fixtures(unittest.TestCase):
    def test_every_record_is_valid(self):
        for fx in FIXTURES:
            for f in fx["features"]:
                with self.subTest(fixture=fx["name"], feature=f["id"]):
                    validate_feature_json(f)

    def test_they_resolve_to_the_steps_meant(self):
        for fx in FIXTURES:
            with self.subTest(fixture=fx["name"]):
                _, steps = steps_of(fx)
                failed = {s["id"]: s["message"] for s in steps if s["kind"] == "failed"}
                self.assertEqual(failed, {}, fx["name"])
                want = {f["id"] for f in fx["features"] if f["kind"] != "sketch" and not f.get("suppressed")}
                self.assertEqual({s["id"] for s in steps if s["kind"] != "sketch"}, want)

    def test_parameters_reach_the_step(self):
        fx = next(x for x in FIXTURES if x.get("parameters"))
        _, steps = steps_of(fx)
        self.assertEqual(steps[0]["to"], 12)

    def test_expectations_are_whole(self):
        for fx in FIXTURES:
            for b in fx["bodies"]:
                self.assertTrue(b["formula"], fx["name"])
                self.assertTrue(b.get("volume") is not None or b.get("between") or (b.get("surface") and b.get("area")), fx["name"])


@unittest.skipUnless(HAVE_FC, NEEDS)
class Builds(unittest.TestCase):
    def test_each_fixture_builds_to_its_volumes(self):
        from scanrulerfc.reverse.build import Builder
        from scanrulerfc.reverse.kernel import Kernel

        for fx in FIXTURES:
            with self.subTest(fixture=fx["name"]):
                features, steps = steps_of(fx)
                sketches = {f["id"]: f["sketch"] for f in features if f["kind"] == "sketch"}
                out = Builder(Kernel()).build(steps, sketches.get)
                status = {str(r["id"]): r["status"] for r in out["results"] if r["id"] not in sketches}
                self.assertEqual(status, fx["status"], [r for r in out["results"] if r["status"] == "failed"])
                bodies = {b["id"]: b for b in out["bodies"]}
                self.assertEqual(sorted(bodies), sorted(b["id"] for b in fx["bodies"]), fx["name"])
                for want in fx["bodies"]:
                    got = bodies[want["id"]]
                    if want.get("surface"):
                        # A sheet: a surface body, held to its area.
                        self.assertTrue(got["surface"] and not got["closed"], want)
                        self.assertAlmostEqual(got["area"], want["area"], delta=want.get("rel", REL) * want["area"], msg=want["formula"])
                        continue
                    self.assertTrue(got["closed"], want)
                    if want.get("between"):
                        lo, hi = want["between"]
                        self.assertTrue(lo < got["volume"] < hi, (got["volume"], want))
                    else:
                        self.assertAlmostEqual(got["volume"], want["volume"], delta=want.get("rel", REL) * max(1.0, want["volume"]), msg=want["formula"])
                    if "area" in want:
                        self.assertAlmostEqual(got["area"], want["area"], delta=REL * want["area"])
                    if "faces" in want:
                        self.assertEqual(got["faces"], want["faces"], want["formula"])
                    if "box" in want:
                        diag = math.dist(want["box"][0], want["box"][1])
                        for k, side in ((0, "min"), (1, "max")):
                            for i in range(3):
                                self.assertAlmostEqual(got["box"][side][i], want["box"][k][i], delta=1e-4 * diag)

    def test_lost_pick_names_the_fingerprint(self):
        from scanrulerfc.reverse.build import Builder
        from scanrulerfc.reverse.kernel import Kernel

        fx = next(x for x in FIXTURES if x["name"].startswith("a lost pick"))
        features, steps = steps_of(fx)
        out = Builder(Kernel()).build(steps, {f["id"]: f["sketch"] for f in features if f["kind"] == "sketch"}.get)
        r = next(r for r in out["results"] if r["id"] == 3)
        self.assertTrue(r["message"].startswith("The edge this fillet was on is gone (was: "), r["message"])

    def test_a_rebuild_takes_up_the_kept_steps(self):
        from scanrulerfc.reverse.build import Builder
        from scanrulerfc.reverse.kernel import Kernel

        fx = next(x for x in FIXTURES if x["name"] == "fillet one edge")
        features, steps = steps_of(fx)
        b = Builder(Kernel())
        sk = {f["id"]: f["sketch"] for f in features if f["kind"] == "sketch"}.get
        b.build(steps, sk, reuse=True)
        again = b.build(steps, sk, reuse=True)
        self.assertEqual(again["steps"]["restored"], len(steps))


if __name__ == "__main__":
    unittest.main()
