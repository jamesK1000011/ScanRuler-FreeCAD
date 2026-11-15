# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/core/build.ts (parity with its builds)
# SPDX-License-Identifier: AGPL-3.0-only
#
# The port held to the original's own builds: each fixture of
# reverse_fixtures/kernel_builds.json built here and compared with what
# ScanRuler's Builder made of it on occt-wasm (kernel_goldens.json, written
# by tests/tools/reverse_goldens.mjs where occt-wasm runs). The design's
# bars: volume and area 1e-6 on analytic solids, 1e-4 with fillets, shells
# and offsets; the box within 1e-4 of the diagonal; statuses identical.
# A face count or face origins that differ are said, not hidden: OCCT 8.0
# (the original) and FreeCAD's OCCT 7.8 may split or merge faces apart.
import json
import math
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

GOLDENS = os.path.join(HERE, "reverse_fixtures", "kernel_goldens.json")
LOOSE = ("fillet", "chamfer", "shell", "offset", "thread", "draft", "taper")


@unittest.skipUnless(HAVE_FC, "needs FreeCAD")
@unittest.skipUnless(os.path.exists(GOLDENS), "no goldens yet: run tests/tools/reverse_goldens.mjs where occt-wasm is installed")
class Parity(unittest.TestCase):
    def test_against_the_original(self):
        from scanrulerfc.reverse.build import Builder
        from scanrulerfc.reverse.kernel import Kernel
        from test_reverse_kernel_builds import FIXTURES, steps_of

        with open(GOLDENS, encoding="utf-8") as f:
            gold = {g["name"]: g for g in json.load(f)["goldens"]}
        drift = []
        for fx in FIXTURES:
            g = gold.get(fx["name"])
            if g is None:
                continue
            with self.subTest(fixture=fx["name"]):
                features, steps = steps_of(fx)
                sketches = {f["id"]: f["sketch"] for f in features if f["kind"] == "sketch"}
                out = Builder(Kernel()).build(steps, sketches.get)
                self.assertEqual([(r["id"], r["status"]) for r in out["results"]], [(r["id"], r["status"]) for r in g["results"]])
                bodies = {b["id"]: b for b in out["bodies"]}
                self.assertEqual(sorted(bodies), sorted(b["id"] for b in g["bodies"]))
                rel = 1e-4 if any(w in fx["name"] for w in LOOSE) else 1e-6
                for want in g["bodies"]:
                    got = bodies[want["id"]]
                    self.assertAlmostEqual(got["volume"], want["volume"], delta=rel * max(1, abs(want["volume"])))
                    if want.get("area") is not None:
                        self.assertAlmostEqual(got["area"], want["area"], delta=rel * max(1, want["area"]))
                    if want.get("box"):
                        diag = math.dist(want["box"]["min"], want["box"]["max"])
                        for side in ("min", "max"):
                            for i in range(3):
                                self.assertAlmostEqual(got["box"][side][i], want["box"][side][i], delta=1e-4 * diag)
                    if got["faces"] != want["faces"]:
                        drift.append(f"{fx['name']}: body {want['id']} has {got['faces']} faces, the original {want['faces']}")
        if drift:
            print("\nFace-count drift (flagged, not failed):\n  " + "\n  ".join(drift), file=sys.stderr)


if __name__ == "__main__":
    unittest.main()
