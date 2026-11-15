# Tests for scanrulerfc/reverse/where.py, the stored-query port of ScanRuler's plugins/reverse/core/where.ts (CNC Kitchen, Stefan Hermann)
# SPDX-License-Identifier: AGPL-3.0-only
#
# The original tests its queries through the headless commands and the
# kernel (rePicksSurvive); here they run on hand-made descriptor lists: a
# 20 x 10 x 5 block with a bore of radius 2 through its top, as the
# kernel's descriptors would give it, its faces made by feature 2 and the
# bore by feature 4. Each term of a query, a query kept and run again on
# the block lengthened (its faces renumbered), the picks that still stand,
# the refusals, and sharp read off the surfaces.
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from scanrulerfc.reverse.topo import match_tolerance  # noqa: E402
from scanrulerfc.reverse.where import (WhereError, is_where, live_picks, run_stored_where, sharp_by_surfaces, stored_where, unwrapped,  # noqa: E402
                                       where_indices, where_words)

BODY = {"name": "Block"}


def block(length=20, order=None):
    """Faces: 0 bottom, 1 top, 2 front (y 0), 3 back, 4 left (x 0), 5
    right, 6 the bore; edges: the twelve lines and the bore's two rims."""
    L, W, H = length, 10, 5
    planes = [([L / 2, W / 2, 0], [0, 0, -1], L * W), ([L / 2, W / 2, H], [0, 0, 1], L * W), ([L / 2, 0, H / 2], [0, -1, 0], L * H),
              ([L / 2, W, H / 2], [0, 1, 0], L * H), ([0, W / 2, H / 2], [-1, 0, 0], W * H), ([L, W / 2, H / 2], [1, 0, 0], W * H)]
    faces = [{"hash": 100 + i, "fingerprint": {"kind": "plane", "centroid": c, "dir": d, "area": a, "origin": 2}} for i, (c, d, a) in enumerate(planes)]
    faces.append({"hash": 106, "fingerprint": {"kind": "cylinder", "centroid": [5, 5, H / 2], "dir": [0, 0, 1], "area": 2 * math.pi * 2 * H, "radius": 2, "center": [5, 5, 0], "origin": 4}})
    corners = [[x, y, z] for z in (0, H) for y in (0, W) for x in (0, L)]

    def line(i, j, f1, f2):
        a, b = corners[i], corners[j]
        d = [b[k] - a[k] for k in range(3)]
        ln = math.hypot(*d)
        u = [x / ln for x in d]
        fp = {"kind": "line", "mid": [(a[k] + b[k]) / 2 for k in range(3)], "dir": u, "length": ln,
              "faces": [{"kind": "plane", "dir": planes[f1][1]}, {"kind": "plane", "dir": planes[f2][1]}], "origin": 2}
        return {"fingerprint": fp, "faces": [100 + f1, 100 + f2], "ends": [a, b], "endTangents": [u, u], "polyline": [*a, *b]}

    edges = [line(0, 1, 0, 2), line(2, 3, 0, 3), line(0, 2, 0, 4), line(1, 3, 0, 5), line(4, 5, 1, 2), line(6, 7, 1, 3), line(4, 6, 1, 4), line(5, 7, 1, 5),
             line(0, 4, 2, 4), line(1, 5, 2, 5), line(2, 6, 3, 4), line(3, 7, 3, 5)]
    for z, f in ((0, 0), (H, 1)):
        poly = []
        for k in range(33):
            t = 2 * math.pi * k / 32
            poly += [5 + 2 * math.cos(t), 5 + 2 * math.sin(t), z]
        edges.append({"fingerprint": {"kind": "circle", "mid": [3, 5, z], "dir": [0, 0, 1], "length": 4 * math.pi, "radius": 2,
                                      "faces": [{"kind": "plane", "dir": planes[f][1]}, {"kind": "cylinder", "dir": [0, 0, 1]}], "origin": 4},
                      "faces": [100 + f, 106], "ends": [[7, 5, z], [7, 5, z]], "endTangents": [[0, 1, 0], [0, 1, 0]], "polyline": poly})
    for i, e in enumerate(edges):
        e["hash"] = 200 + i
    if order:
        faces = [faces[i] for i in order]
    return {"faces": faces, "edges": edges}


NAMES = {"Extrude": 2, "Hole": 4}
ASK = {"featureId": lambda ref: ref if isinstance(ref, int) else NAMES[ref], "sharp": lambda deg: (lambda i: True)}


def edges(where, t=None):
    return where_indices(where, t or block(), BODY, "edge", ASK)


def faces(where, t=None):
    return where_indices(where, t or block(), BODY, "face", ASK)


class Terms(unittest.TestCase):
    def test_kind_box_near_and_made_by(self):
        self.assertEqual(faces({"kind": "cylinder"}), [6])
        self.assertEqual(faces({"madeBy": "Hole"}), [6])
        self.assertEqual(faces({"between": [[0, 0, 1]]}), [1, 6])
        self.assertEqual(faces({"box": {"min": [-1, -1, 4], "max": [21, 11, 6]}}), [1])
        self.assertEqual(faces({"near": {"at": [0, 5, 2.5], "radius": 0.5}}), [4])
        self.assertEqual(edges({"kind": "circle"}), [12, 13])
        self.assertEqual(edges({"kind": "line", "minLength": 15}), [0, 1, 4, 5])
        self.assertEqual(edges({"kind": "line", "maxLength": 6}), [8, 9, 10, 11])

    def test_through_radius_and_sides(self):
        self.assertEqual(edges({"through": {"at": [7, 0, 5]}}), [4])
        self.assertEqual(edges({"through": {"at": [5, 3, 5]}}), [13])
        self.assertEqual(edges({"diameter": 4}), [12, 13])
        self.assertEqual(edges({"radius": 3}), [])
        self.assertEqual(edges({"faces": [1, 2]}), [4])
        self.assertEqual(edges({"sides": {"madeBy": ["Extrude", "Hole"]}}), [12, 13])

    def test_loops_coaxial_and_exclude(self):
        self.assertEqual(edges({"faces": [1], "loop": "outer"}), [4, 5, 6, 7])
        self.assertEqual(edges({"faces": [1], "loop": "inner"}), [13])
        self.assertEqual(faces({"coaxial": {"at": [5, 5, 0], "dir": [0, 0, 1]}}), [6])
        self.assertEqual(edges({"coaxial": {"at": [5, 5, 0], "dir": [0, 0, -1]}}), [12, 13])
        self.assertEqual(edges({"kind": "circle", "exclude": [12]}), [13])
        self.assertEqual(edges({"kind": "line", "exclude": {"minLength": 7}}), [8, 9, 10, 11])

    def test_sharp_asked_of_the_caller(self):
        ask = {**ASK, "sharp": lambda deg: (lambda i: i != 13)}
        self.assertEqual(where_indices({"kind": "circle", "sharp": True}, block(), BODY, "edge", ask), [12])
        with self.assertRaisesRegex(WhereError, "there is none for it here"):
            where_indices({"sharpDeg": 2}, block(), BODY, "edge", {**ASK, "sharp": lambda deg: None})

    def test_refusals(self):
        with self.assertRaisesRegex(WhereError, "through picks edges"):
            faces({"through": {"at": [0, 0, 0]}})
        with self.assertRaisesRegex(WhereError, "sides picks edges"):
            faces({"sides": {"madeBy": [2, 4]}})
        with self.assertRaisesRegex(WhereError, "loop reads one face"):
            edges({"faces": [1, 2], "loop": "outer"})
        with self.assertRaisesRegex(WhereError, "is a cylinder"):
            edges({"faces": [6], "loop": "outer"})
        with self.assertRaises(WhereError) as no_face:
            edges({"faces": [9]})
        self.assertEqual(no_face.exception.code, "not_found")
        with self.assertRaisesRegex(WhereError, "sides.madeBy names two features"):
            edges({"sides": {"madeBy": [2]}})

    def test_wrapped(self):
        self.assertEqual(unwrapped({"where": {"kind": "circle"}, "optional": True}, "edge"), {"optional": True, "kind": "circle"})
        self.assertEqual(edges({"where": {"where": {"kind": "circle"}}}), [12, 13])
        with self.assertRaisesRegex(WhereError, "kind stands both in where and beside it"):
            unwrapped({"kind": "line", "where": {"kind": "circle"}}, "edge")
        with self.assertRaisesRegex(WhereError, 'where in it is "x", no query'):
            unwrapped({"where": "x"}, "face")
        self.assertTrue(is_where({"kind": "plane"}))
        self.assertFalse(is_where({"kind": "plane", "centroid": [0, 0, 0]}))


class Kept(unittest.TestCase):
    def test_stored_and_run_again_on_the_part_rebuilt(self):
        t = block()
        kept = stored_where({"faces": [1], "loop": "outer", "madeBy": "Extrude", "exclude": [4]}, t, "edge", ASK["featureId"])
        self.assertEqual(kept["madeBy"], 2)
        self.assertEqual(kept["faces"], [t["faces"][1]["fingerprint"]])
        self.assertEqual(kept["exclude"], {"prints": [t["edges"][4]["fingerprint"]]})
        self.assertEqual(where_words(kept), '{ loop: "outer", madeBy: 2, faces: 1, exclude }')
        # Lengthened to 26 and its faces listed in another order: the top is
        # found again by its fingerprint, the excluded edge too.
        longer = block(26, order=[6, 5, 4, 3, 2, 1, 0])
        tol = match_tolerance(30)
        self.assertEqual(run_stored_where(kept, longer, BODY, "edge", ASK["sharp"], tol), [5, 6, 7])
        # A face it names that is gone: the query cannot be read there.
        flat = {"faces": [f for f in longer["faces"] if f["fingerprint"]["dir"] != [0, 0, 1]], "edges": longer["edges"]}
        self.assertIsNone(run_stored_where(kept, flat, BODY, "edge", ASK["sharp"], tol))
        # A term refused there is no answer either, not a failure.
        self.assertIsNone(run_stored_where({"through": {"at": [0, 0, 0]}}, longer, BODY, "face", ASK["sharp"], tol))

    def test_live_picks(self):
        a, b, c = ({"kind": "line", "n": i} for i in range(3))
        picks = [{"where": {"kind": "line"}, "found": [a, b]}, {"where": {"kind": "circle"}, "found": [c]}]
        self.assertEqual(live_picks([a, b, c], picks), {"live": picks, "rest": []})
        self.assertEqual(live_picks([a, c], picks), {"live": [picks[1]], "rest": [a]})
        self.assertEqual(live_picks([a, b], None), {"live": [], "rest": [a, b]})
        near = live_picks([{"kind": "line", "n": 0.5}, b], picks[:1], same=lambda f, p: abs(f["n"] - p["n"]) < 1)
        self.assertEqual(near["live"], picks[:1])

    def test_sharp_by_surfaces(self):
        t = block()
        top_rim = t["edges"][13]

        def normals(h, points):
            return [[0, 0, 1] if h == 101 else [1, 0, 0] for _ in points]

        self.assertTrue(sharp_by_surfaces(top_rim, normals))
        self.assertFalse(sharp_by_surfaces(top_rim, lambda h, points: [[0, 0, 1] for _ in points]))
        self.assertFalse(sharp_by_surfaces({**top_rim, "faces": [106, 106]}, normals))
        self.assertTrue(sharp_by_surfaces({**top_rim, "faces": [101]}, normals))


if __name__ == "__main__":
    unittest.main()
