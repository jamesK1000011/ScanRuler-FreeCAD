# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/tests/rePreview.test.ts
# SPDX-License-Identifier: AGPL-3.0-only
#
# The manipulator a feature wears while it is set up: where an extrude's
# arrows and a revolve's ring sit, and what a drag on them does to the
# numbers — outward is always growth, whichever way the arrow points; the
# taper's arrow riding the ghost's far edge, and a coil's ring wound on past
# a full turn. Then the fillet's, shell's, moved face's and Move's grips.
import math
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

from scanrulerfc.reverse import preview as P  # noqa: E402
from scanrulerfc.reverse.features import MAX_COIL_DEG  # noqa: E402
from scanrulerfc.reverse.regions import find_regions  # noqa: E402
from scanrulerfc.reverse.sketch import add_rectangle, empty_sketch  # noqa: E402

XY = {"origin": [0, 0, 0], "normal": [0, 0, 1], "basisU": [1, 0, 0], "basisV": [0, 1, 0]}
# A frame standing at z = 5 with its normal down the part's Y axis.
TILTED = {"origin": [1, 2, 5], "normal": [0, 1, 0], "basisU": [1, 0, 0], "basisV": [0, 0, -1]}


def rectangle_regions(w, h, at=(0, 0)):
    s = empty_sketch()
    add_rectangle(s, list(at), [at[0] + w, at[1] + h])
    return find_regions(s)


def apply(m, p):
    """A row-major 3 x 4 on a point."""
    return [m[r * 4] * p[0] + m[r * 4 + 1] * p[1] + m[r * 4 + 2] * p[2] + m[r * 4 + 3] for r in range(3)]


class Centroid(unittest.TestCase):
    def test_rectangles(self):
        one = rectangle_regions(4, 2)
        c = P.regions_centroid(one)
        self.assertAlmostEqual(c[0], 2, 9)
        self.assertAlmostEqual(c[1], 1, 9)
        both = one + rectangle_regions(2, 2, (10, 0))
        self.assertAlmostEqual(P.regions_centroid(both)[0], (2 * 8 + 11 * 4) / 12, 9)

    def test_a_sliver_falls_back_to_the_vertex_mean(self):
        self.assertEqual(P._polygon_centroid2([[0, 0], [2, 0], [4, 0]]), [2, 0])
        self.assertEqual(P._polygon_centroid2([]), [0, 0])


class ExtrudeGrips(unittest.TestCase):
    regions = rectangle_regions(40, 20)

    def test_an_arrow_on_each_face_through_the_centroid_pointing_out(self):
        grips = P.extrude_grips(XY, self.regions, {"kind": "distance", "from": -2, "to": 10})
        self.assertEqual([g["side"] for g in grips], ["extrudeFrom", "extrudeTo"])
        frm, to = grips
        self.assertEqual(frm["position"], [20, 10, -2])
        self.assertEqual(frm["dir"], [0, 0, -1])
        self.assertEqual(to["position"], [20, 10, 10])
        self.assertEqual(to["dir"], [0, 0, 1])
        self.assertEqual(frm["shape"], "arrow")
        self.assertTrue(frm["pixels"])
        self.assertEqual(frm["size"], P.ARROW_PX)

    def test_follows_the_frame(self):
        frm, to = P.extrude_grips(TILTED, self.regions, {"kind": "distance", "from": 0, "to": 6})
        self.assertEqual(frm["position"], [21, 2, -5])
        self.assertEqual(to["position"], [21, 8, -5])
        self.assertEqual(to["dir"], [0, 1, 0])

    def test_backwards_distance_turns_the_arrows(self):
        frm, to = P.extrude_grips(XY, self.regions, {"kind": "distance", "from": 10, "to": -2})
        self.assertEqual((frm["position"][2], frm["dir"][2]), (10, 1))
        self.assertEqual((to["position"][2], to["dir"][2]), (-2, -1))

    def test_symmetric_to_plane_between_planes(self):
        self.assertEqual([g["position"][2] for g in P.extrude_grips(XY, self.regions, {"kind": "symmetric", "total": 8})], [-4, 4])
        self.assertEqual([g["side"] for g in P.extrude_grips(XY, self.regions, {"kind": "toPlane", "from": 1, "plane": {"kind": "plane", "id": 1}})], ["extrudeFrom"])
        self.assertEqual(P.extrude_grips(XY, self.regions, {"kind": "betweenPlanes", "a": {}, "b": {}}), [])
        self.assertEqual(P.extrude_grips(XY, [], {"kind": "distance", "from": 0, "to": 1}), [])


class DragExtrude(unittest.TestCase):
    def test_outward_is_growth(self):
        start = {"kind": "distance", "from": 0, "to": 10}
        self.assertEqual(P.drag_extrude_extent(start, "extrudeTo", 5), {"kind": "distance", "from": 0, "to": 15})
        self.assertEqual(P.drag_extrude_extent(start, "extrudeFrom", 5), {"kind": "distance", "from": -5, "to": 10})
        self.assertEqual(P.drag_extrude_extent(start, "extrudeTo", -12), {"kind": "distance", "from": 0, "to": -2})
        back = {"kind": "distance", "from": 10, "to": -2}
        self.assertEqual(P.drag_extrude_extent(back, "extrudeTo", 3), {"kind": "distance", "from": 10, "to": -5})
        self.assertEqual(P.drag_extrude_extent(back, "extrudeFrom", 3), {"kind": "distance", "from": 13, "to": -2})

    def test_symmetric_grows_by_twice_and_stays_positive(self):
        self.assertEqual(P.drag_extrude_extent({"kind": "symmetric", "total": 10}, "extrudeFrom", 2), {"kind": "symmetric", "total": 14})
        self.assertAlmostEqual(P.drag_extrude_extent({"kind": "symmetric", "total": 10}, "extrudeTo", -8)["total"], 0.01, 9)

    def test_to_plane_moves_its_start_only(self):
        tp = {"kind": "toPlane", "from": 1, "plane": {"kind": "plane", "id": 1}}
        self.assertEqual(P.drag_extrude_extent(tp, "extrudeFrom", 2), {**tp, "from": -1})
        self.assertEqual(P.drag_extrude_extent(tp, "extrudeTo", 2), tp)


class ThroughPoint(unittest.TestCase):
    def test_ends_through_points(self):
        start = {"kind": "distance", "from": 0, "to": 10}
        self.assertEqual(P.extent_through_point(start, "to", 24.638), {"kind": "distance", "from": 0, "to": 24.64})
        self.assertEqual(P.extent_through_point(start, "to", -8), {"kind": "distance", "from": 0, "to": -8})
        both = P.extent_through_point(P.extent_through_point(start, "to", 12), "from", -7.5)
        self.assertEqual(both, {"kind": "distance", "from": -7.5, "to": 12})
        self.assertIsNone(P.extent_through_point(start, "to", 0.001))
        self.assertIsNone(P.extent_through_point(start, "to", float("nan")))
        self.assertIsNone(P.extent_through_point({"kind": "toNext", "from": 0}, "to", 5))
        self.assertEqual(P.extent_through_point({"kind": "toNext", "from": 0}, "from", 5), {"kind": "toNext", "from": 5})
        self.assertEqual(P.extent_through_point({"kind": "symmetric", "total": 10}, "to", -6), {"kind": "symmetric", "total": 12})


class Stretch(unittest.TestCase):
    def test_heights_carried_nothing_across(self):
        m = P.prism_stretch(TILTED["origin"], TILTED["normal"], 0, 10, -5, 25)
        foot, top, mid = apply(m, [7, 2, -3]), apply(m, [7, 12, -3]), apply(m, [-1, 7, 4])
        for got, want in ((foot, [7, -3, -3]), (top, [7, 27, -3]), (mid, [-1, 12, 4])):
            for a, b in zip(got, want):
                self.assertAlmostEqual(a, b, 9)

    def test_turned_over_and_none_of_nothing(self):
        m = P.prism_stretch(XY["origin"], XY["normal"], 0, 10, 0, -4)
        self.assertAlmostEqual(apply(m, [1, 1, 10])[2], -4, 9)
        self.assertAlmostEqual(apply(m, [1, 1, 0])[2], 0, 9)
        self.assertIsNone(P.prism_stretch(XY["origin"], XY["normal"], 3, 3, 0, 5))


class Revolve(unittest.TestCase):
    def test_rings_the_axis_through_the_profile(self):
        ring = P.revolve_grip(XY, rectangle_regions(5, 10), {"origin": [0, 0, 0], "dir": [0, 1, 0]})
        self.assertEqual((ring["shape"], ring["side"]), ("ring", "turn"))
        self.assertEqual(ring["position"], [0, 5, 0])
        self.assertAlmostEqual(ring["size"], 2.5, 9)
        self.assertEqual(ring["dir"], [0, 1, 0])

    def test_none(self):
        regions = rectangle_regions(4, 4, (-2, -2))
        self.assertIsNone(P.revolve_grip(XY, [], {"origin": [0, 0, 0], "dir": [0, 1, 0]}))
        self.assertIsNone(P.revolve_grip(XY, regions, {"origin": [0, 0, 0], "dir": [0, 0, 0]}))
        self.assertIsNone(P.revolve_grip(XY, regions, {"origin": [0, 0, 0], "dir": [0, 1, 0]}))

    def test_angle_dragged(self):
        self.assertEqual(P.drag_revolve_angle(90, 45), 135)
        self.assertEqual(P.drag_revolve_angle(300, 90), 360)
        self.assertEqual(P.drag_revolve_angle(10, -30), 1)
        self.assertEqual(P.drag_revolve_angle(90, 0.04), 90)
        self.assertEqual(P.drag_revolve_angle(1080, 400, MAX_COIL_DEG), 1480)
        self.assertEqual(P.drag_revolve_angle(300, 90, MAX_COIL_DEG), 390)


class Taper(unittest.TestCase):
    def test_span(self):
        self.assertEqual(P.taper_span({"kind": "distance", "from": 0, "to": 10}), {"start": 0, "end": 10})
        self.assertEqual(P.taper_span({"kind": "distance", "from": -4, "to": 10}), {"start": 0, "end": 10})
        self.assertEqual(P.taper_span({"kind": "distance", "from": -12, "to": 10}), {"start": 0, "end": -12})
        self.assertEqual(P.taper_span({"kind": "distance", "from": 5, "to": 15}), {"start": 5, "end": 15})
        self.assertEqual(P.taper_span({"kind": "distance", "from": 0, "to": -8}), {"start": 0, "end": -8})
        self.assertEqual(P.taper_span({"kind": "symmetric", "total": 20}), {"start": 0, "end": 10})
        self.assertIsNone(P.taper_span({"kind": "toNext", "from": 0}))

    def test_rides_the_far_edge(self):
        g = P.taper_grip(XY, rectangle_regions(40, 20), {"kind": "distance", "from": 0, "to": 10}, 10)
        self.assertEqual((g["side"], g["shape"], g["dir"]), ("taper", "arrow", [1, 0, 0]))
        for a, b in zip(g["position"], [40 + 10 * math.tan(math.radians(10)), 10, 10]):
            self.assertAlmostEqual(a, b, 9)
        down = P.taper_grip(TILTED, rectangle_regions(4, 2), {"kind": "distance", "from": 0, "to": -6}, -20)
        for a, b in zip(down["position"], [1 + 4 - 6 * math.tan(math.radians(20)), 2 - 6, 5 - 1]):
            self.assertAlmostEqual(a, b, 9)
        self.assertIsNone(P.taper_grip(XY, [], {"kind": "distance", "from": 0, "to": 10}, 0))
        self.assertIsNone(P.taper_grip(XY, rectangle_regions(4, 2), {"kind": "toLast", "from": 0}, 0))

    def test_drag(self):
        self.assertEqual(P.drag_taper(0, 10, 10), 45)
        self.assertEqual(P.drag_taper(45, 10, -10), 0)
        self.assertEqual(P.drag_taper(0, 10, -10), -45)
        self.assertEqual(P.drag_taper(0, 10, 1e9), P.MAX_TAPER_DEG)
        self.assertEqual(P.drag_taper(12, 0, 5), 12)


class OnBody(unittest.TestCase):
    def test_edge_face_and_moved_face(self):
        e = P.edge_grip({"mid": [5, 0, 10], "faces": [{"dir": [0, 0, 1]}, {"dir": [0, -1, 0]}]})
        self.assertEqual((e["side"], e["position"]), ("radius", [5, 0, 10]))
        self.assertAlmostEqual(e["dir"][1], math.sqrt(0.5), 9)
        self.assertAlmostEqual(e["dir"][2], -math.sqrt(0.5), 9)
        self.assertIsNone(P.edge_grip({"mid": [0, 0, 0], "faces": [{"dir": [0, 0, 1]}]}))
        f = P.face_grip({"centroid": [1, 2, 3], "dir": [0, 0, 1]})
        self.assertEqual((f["side"], f["dir"]), ("thickness", [0, 0, -1]))
        m = P.move_grip({"centroid": [0, 0, 10], "dir": [0, 0, 1]}, 2.5)
        self.assertEqual((m["side"], m["position"], m["dir"]), ("move", [0, 0, 12.5], [0, 0, 1]))
        c = P.move_grip({"kind": "cylinder", "centroid": [0, 0, 5], "center": [0, 0, 5], "dir": [0, 0, 1], "radius": 3}, 1)
        self.assertAlmostEqual(math.hypot(c["position"][0], c["position"][1]), 4, 9)

    def test_the_move_gizmo(self):
        g = P.move_grips({"pivot": [1, 2, 3], "translate": [10, 0, 0], "rotate": [0, 0, 90]})
        self.assertEqual([x["side"] for x in g], ["moveX", "turnX", "moveY", "turnY", "moveZ", "turnZ"])
        self.assertTrue(all(x["position"] == [11, 2, 3] for x in g))
        turn_x = g[1]["dir"]  # the X ring rides on the Z turn
        self.assertAlmostEqual(turn_x[1], 1, 9)
        self.assertEqual(P.move_grip_slot("turnY"), ("rotate", 1))
        self.assertEqual(P.move_grip_slot("moveZ"), ("translate", 2))


if __name__ == "__main__":
    unittest.main()
