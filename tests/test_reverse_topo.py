# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/tests/reTopo.test.ts, reCoreUnits.test.ts, reFlushJoin.test.ts (their kernel-free cases)
# SPDX-License-Identifier: AGPL-3.0-only
#
# Fingerprints: an axis made canonical, the nearest face of a kind matched
# within the tolerance, a top edge told from the bottom one under it, the
# second look among a feature's own faces, the words a message names them
# by (in inches too), faces on one surface, the split edges between them,
# and a fingerprint carried through an alignment. Reading a body and the
# builder naming its faces wait for the kernel.
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from scanrulerfc.reverse._js import js_hypot  # noqa: E402
from scanrulerfc.reverse.topo import (canonical_dir, describe_edge, describe_edge_in, describe_face, describe_face_in, match_edge, match_face,  # noqa: E402
                                      match_tolerance, on_one_surface, read_topology, split_edges, tangent_chain, transform_edge_fingerprint,
                                      transform_fingerprint)

KERNEL = "kernel (step 3) not ported"


def plane(centroid, d, area=100, origin=1):
    return {"kind": "plane", "centroid": centroid, "dir": d, "area": area, "origin": origin}


def rigid_axis_angle(axis, angle):
    ln = js_hypot(*axis)
    half = angle / 2
    s = math.sin(half) / ln
    w, x, y, z = math.cos(half), axis[0] * s, axis[1] * s, axis[2] * s
    n = js_hypot(w, x, y, z)
    w, x, y, z = w / n, x / n, y / n, z / n
    return {"r": [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y), 2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x),
                  2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)], "t": [0.0, 0.0, 0.0]}


def r9(v):
    return [math.floor(x * 1e9 + 0.5) / 1e9 + 0 for x in v]


class Fingerprints(unittest.TestCase):
    def test_canonical(self):
        self.assertEqual(canonical_dir([0, 0, -1]), [0, 0, 1])
        self.assertEqual(canonical_dir([-0.6, 0.8, 0]), [0.6, -0.8, 0])
        self.assertEqual(canonical_dir([0, -3, 4]), [0, 0.6, -0.8])

    def test_nearest_face(self):
        tol = match_tolerance(50)
        top = plane([20, 10, 10], [0, 0, 1], 800)
        candidates = [plane([20, 10, 0], [0, 0, -1], 800), plane([21, 10, 10], [0, 0, 1], 840), plane([20, 10, 40], [0, 0, 1], 800)]
        self.assertEqual(match_face(top, candidates, tol), 1)
        self.assertIsNone(match_face({**top, "kind": "cylinder"}, candidates, tol))
        self.assertIsNone(match_face(top, [candidates[2]], tol))
        twins = [plane([20, 10, 10], [0, 0, 1], 800, 7), plane([20, 10, 10], [0, 0, 1], 800, 1)]
        self.assertEqual(match_face(top, twins, tol), 1)

    def test_top_edge_from_bottom(self):
        tol = match_tolerance(50)

        def line(mid, up):
            return {"kind": "line", "mid": mid, "dir": [1, 0, 0], "length": 40, "faces": [{"kind": "plane", "dir": [0, -1, 0]}, {"kind": "plane", "dir": [0, 0, up]}], "origin": 1}

        wanted = line([20, 0, 10], 1)
        self.assertEqual(match_edge(wanted, [line([20, 0, 0], -1), line([20, 0, 10], -1), line([20, 0, 10], 1)], tol), 2)
        self.assertIsNone(match_edge(wanted, [line([20, 0, 10], -1)], tol))

    def test_second_look(self):
        tol = match_tolerance(js_hypot(20, 20, 17))
        top = plane([10, 10, 7], [0, 0, 1], 400, 2)
        grown = [plane([10, 10, 0], [0, 0, -1], 400, 2), plane([10, 10, 17], [0, 0, 1], 400, 2), plane([10, 0, 8.5], [0, -1, 0], 340, 2)]
        self.assertEqual(match_face(top, grown, tol), 1)
        self.assertIsNone(match_face(top, [plane([10, 10, 17], [0, 0, 1], 400, 5)], tol))
        self.assertIsNone(match_face({**top, "origin": -1}, grown, tol))

        def upright(mid, ln, origin=2):
            return {"kind": "line", "mid": mid, "dir": [0, 0, 1], "length": ln, "faces": [{"kind": "plane", "dir": [0, -1, 0]}, {"kind": "plane", "dir": [-1, 0, 0]}], "origin": origin}

        side = upright([0, 0, 3.5], 7)
        self.assertEqual(match_edge(side, [upright([0, 0, 8.5], 17), upright([20, 0, 8.5], 17)], tol), 0)
        self.assertIsNone(match_edge(side, [upright([0, 0, 8.5], 17, 5)], tol))

    def test_words(self):
        self.assertEqual(describe_face({"kind": "cylinder", "centroid": [10, 10, 5], "dir": [0, 0, 1], "area": 94.2, "radius": 3, "origin": 2}), "cylinder Ø6.0 at (10.0, 10.0, 5.0)")
        self.assertEqual(describe_face(plane([20, 10, 10], [0, 0, 1], 800)), "plane 800 mm² at (20.0, 10.0, 10.0)")
        self.assertEqual(describe_edge({"kind": "circle", "mid": [7, 10, 10], "dir": [0, 0, 1], "length": 18.85, "radius": 3, "faces": [], "origin": 2}), "circle Ø6.0 at (7.0, 10.0, 10.0)")
        self.assertEqual(describe_edge({"kind": "line", "mid": [20, 0, 10], "dir": [1, 0, 0], "length": 40, "faces": [], "origin": 2}), "line 40.0 mm at (20.0, 0.0, 10.0)")

    def test_words_in_inches(self):
        cylinder = {"kind": "cylinder", "centroid": [25.4, 0, 12.7], "dir": [0, 0, 1], "area": 100, "radius": 6.35, "origin": 1}
        flat = {"kind": "plane", "centroid": [0, 0, 0], "dir": [0, 0, 1], "area": 645.16, "origin": 1}
        line = {"kind": "line", "mid": [25.4, 0, 0], "dir": [1, 0, 0], "length": 50.8, "faces": [], "origin": 1}
        self.assertEqual(describe_face_in("in")(cylinder), "cylinder Ø0.500 at (1.000, 0.000, 0.500)")
        self.assertEqual(describe_face_in("in")(flat), "plane 1.000 in² at (0.000, 0.000, 0.000)")
        self.assertEqual(describe_edge_in("in")(line), "line 2.000 in at (1.000, 0.000, 0.000)")
        self.assertEqual(describe_face(cylinder), "cylinder Ø12.7 at (25.4, 0.0, 12.7)")
        self.assertEqual(describe_face(flat), "plane 645 mm² at (0.0, 0.0, 0.0)")
        self.assertEqual(describe_edge(line), "line 50.8 mm at (25.4, 0.0, 0.0)")
        self.assertEqual([describe_face_in("mm")(flat)], [describe_face(flat)])

    def test_one_surface(self):
        def rnd(kind, center, d, radius=None):
            f = {"kind": kind, "centroid": center, "dir": d, "area": 50, "center": center, "origin": 1}
            if radius is not None:
                f["radius"] = radius
            return f

        self.assertTrue(on_one_surface(rnd("cylinder", [0, 0, 0], [0, 0, 1], 33.92), rnd("cylinder", [0, 0, 12], [0, 0, 1], 33.919999432)))
        self.assertFalse(on_one_surface(rnd("cylinder", [0, 0, 0], [0, 0, 1], 5), rnd("cylinder", [0, 0, 0], [0, 0, 1], 5.1)))
        self.assertFalse(on_one_surface(rnd("cylinder", [0, 0, 0], [0, 0, 1], 5), rnd("cylinder", [10, 0, 0], [0, 0, 1], 5)))
        self.assertFalse(on_one_surface(rnd("cylinder", [0, 0, 0], [0, 0, 1], 5), rnd("cylinder", [0, 0, 0], [0, 1, 0], 5)))
        self.assertTrue(on_one_surface(rnd("cone", [0, 0, 0], [0, 0, 1]), rnd("cone", [0, 0, 7], [0, 0, 1])))
        self.assertFalse(on_one_surface(rnd("cone", [0, 0, 0], [0, 0, 1]), rnd("cylinder", [0, 0, 0], [0, 0, 1], 5)))
        self.assertTrue(on_one_surface(plane([0, 0, 0], [0, 0, 1]), plane([30, 0, 0], [0, 0, 1])))

        def sphere(center, radius):
            return {"kind": "sphere", "centroid": center, "dir": [0, 0, 1], "area": 50, "center": center, "radius": radius, "origin": 1}

        self.assertTrue(on_one_surface(sphere([1, 2, 3], 4), sphere([1, 2, 3], 4)))
        self.assertFalse(on_one_surface(sphere([1, 2, 3], 4), sphere([1, 2, 5], 4)))
        torus = {"kind": "torus", "centroid": [0, 0, 0], "dir": [0, 0, 1], "area": 50, "origin": 1}
        self.assertFalse(on_one_surface(torus, torus))

    def test_split_edges(self):
        def face(h, kind, d, **more):
            return {"hash": h, "fingerprint": {"kind": kind, "centroid": [0, 0, 0], "dir": d, "area": 1, "origin": 1, **more}}

        splits = split_edges({
            "faces": [face(1, "plane", [0, 0, 1]), face(2, "plane", [0, 0, 1]), face(3, "plane", [1, 0, 0]), face(4, "cylinder", [0, 0, 1], radius=5, center=[0, 0, 0]),
                      face(5, "cylinder", [0, 0, 1], radius=5.0000044, center=[0, 0, 3]), face(6, "cylinder", [0, 0, 1], radius=6, center=[0, 0, 0]),
                      face(7, "cone", [0, 0, 1], center=[0, 0, 0]), face(8, "cone", [0, 0, 1], center=[0, 0, 2]), face(9, "sphere", [0, 0, 1], radius=3, center=[1, 1, 1]),
                      face(10, "sphere", [1, 0, 0], radius=3, center=[1, 1, 1])],
            "edges": [{"hash": h, "faces": f} for h, f in ((100, [1, 2]), (101, [1, 3]), (102, [4, 5]), (103, [4, 6]), (104, [7, 8]), (105, [9, 10]), (106, [4, 4]), (107, [1]))],
        })
        self.assertEqual(sorted(splits), [100, 102, 105])

    def test_moved_through_alignment(self):
        m = rigid_axis_angle([0, 0, 1], math.pi / 2)
        m["t"][0] += 5
        moved = transform_fingerprint({"kind": "plane", "centroid": [10, 0, 3], "dir": [0, -1, 0], "area": 12, "origin": 1}, m)
        self.assertEqual(r9(moved["centroid"]), [5, 10, 3])
        self.assertEqual(r9(moved["dir"]), [1, 0, 0])
        self.assertEqual((moved["area"], moved["origin"]), (12, 1))
        bore = {"kind": "cylinder", "centroid": [10, 0, 3], "dir": [0, 1, 0], "area": 12, "origin": 1, "radius": 2, "center": [10, 0, 0]}
        turned = transform_fingerprint(bore, m)
        self.assertEqual(r9(turned["dir"]), [1, 0, 0])
        self.assertEqual(r9(turned["center"]), [5, 10, 0])

    def test_edge_moved_through_alignment(self):
        m = rigid_axis_angle([0, 0, 1], math.pi / 2)
        m["t"][0] += 5
        edge = {"kind": "line", "mid": [10, 0, 3], "dir": [0, 1, 0], "length": 20, "faces": [{"kind": "plane", "dir": [0, -1, 0]}, {"kind": "cylinder", "dir": [0, 1, 0]}], "origin": 2}
        moved = transform_edge_fingerprint(edge, m)
        self.assertEqual(r9(moved["mid"]), [5, 10, 3])
        self.assertEqual(r9(moved["dir"]), [1, 0, 0])
        self.assertEqual(r9(moved["faces"][0]["dir"]), [1, 0, 0])
        self.assertEqual(r9(moved["faces"][1]["dir"]), [1, 0, 0])
        self.assertEqual(moved["length"], 20)
        self.assertEqual(match_edge(moved, [edge, moved], match_tolerance(100)), 1)

    @unittest.skip(KERNEL)
    def test_kernel_reads_a_box(self):
        pass

    @unittest.skip(KERNEL)
    def test_builder_names_faces(self):
        pass


class Descriptors(unittest.TestCase):
    """This port's own: the descriptor interface kernel.py will answer,
    played by a stand-in, and the tangent chain walked on what it gives."""

    def test_read_topology_from_descriptors(self):
        class Kernel:
            def describe_faces(self, shape):
                return [{"hash": 11, "kind": "plane", "centroid": [5, 5, 0], "dir": [0, 0, -1], "area": 100},
                        {"hash": 12, "kind": "cylinder", "centroid": [0, 5, 2], "dir": [0, 1, 0], "area": 40, "radius": 2, "center": [0, 0, 2], "fullTurn": False}]

            def describe_edges(self, shape, deflection):
                return [{"hash": 21, "kind": "line", "mid": [0, 5, 0], "dir": [0, 1, 0], "length": 10, "faceHashes": [11, 12], "polyline": [0, 0, 0, 0, 10, 0],
                         "ends": [[0, 0, 0], [0, 10, 0]], "endTangents": [[0, 1, 0], [0, 1, 0]]},
                        {"hash": 22, "kind": "line", "mid": [0, 15, 0], "dir": [0, 1, 0], "length": 10, "faceHashes": [11], "polyline": [],
                         "ends": [[0, 10, 0], [0, 20, 0]], "endTangents": [[0, 1, 0], [0, 1, 0]]}]

        t = read_topology(Kernel(), object(), {11: 2, 12: 5}, 0.01)
        self.assertEqual(t["faces"][1], {"hash": 12, "fingerprint": {"kind": "cylinder", "centroid": [0, 5, 2], "dir": [0, 1, 0], "area": 40, "origin": 5, "radius": 2, "center": [0, 0, 2]},
                                         "fullTurn": False})
        self.assertEqual(t["edges"][0]["fingerprint"]["origin"], 5)
        self.assertEqual(t["edges"][0]["fingerprint"]["faces"], [{"kind": "plane", "dir": [0, 0, -1]}, {"kind": "cylinder", "dir": [0, 1, 0]}])
        self.assertEqual(t["edges"][1]["fingerprint"]["origin"], 2)
        self.assertEqual(tangent_chain(t["edges"], [21]), [21, 22])
        self.assertEqual(tangent_chain(t["edges"], [21], {22}), [21])


if __name__ == "__main__":
    unittest.main()
