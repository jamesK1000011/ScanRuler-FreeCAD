# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/tests/reBuildReuse.test.ts, reLoftChecks.test.ts, reDraftCrease.test.ts, reRevolvePoleStep.test.ts, reCoreUnits.test.ts, reCompare.test.ts (their kernel-free cases)
# SPDX-License-Identifier: AGPL-3.0-only
#
# The feature list resolved into build steps, and the steps' keys: the
# keys byte for byte as the original makes them (goldens written by the
# original engine itself, run under Node, for lists of every kind of step),
# steps told apart where JSON alone would not, and a sketch's change
# changing only the step that reads it; a loft's sections and a sweep's
# start checked before the kernel; a sketch the feature cannot have named;
# a profile no longer closed named by its open ends; near-tangent joins
# mended or left; an arc run to the revolve's axis turned to start there; a
# plane's name. The cases that build in the kernel wait for it.
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from scanrulerfc.reverse._js import parse  # noqa: E402
from scanrulerfc.reverse.buildtypes import halton, step_keys  # noqa: E402
from scanrulerfc.reverse.profiles import loft_profile, mend_near_tangent, mend_poles, sweep_geometry  # noqa: E402
from scanrulerfc.reverse.regions import find_regions  # noqa: E402
from scanrulerfc.reverse.resolve import describe_plane_ref, resolve_features  # noqa: E402
from scanrulerfc.reverse.sketch import add_entity, add_rectangle, clone_sketch, empty_sketch  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
KERNEL = "kernel (step 3) not ported"
XY = {"origin": [0, 0, 0], "normal": [0, 0, 1], "basisU": [1, 0, 0], "basisV": [0, 1, 0]}
CTX = {"sections": [], "elements": [], "modelCenter": [0, 0, 0]}


def regions_of(f):
    return find_regions(f["sketch"])


def sketch_of(i, draw):
    s = empty_sketch()
    draw(s)
    return {"id": i, "kind": "sketch", "name": f"Sketch {i}", "plane": {"kind": "world", "axis": "z", "offset": 0}, "frame": XY, "sketch": s, "visible": True}


def sketch_at(i, name, z, draw):
    s = sketch_of(i, draw)
    return {**s, "name": name, "plane": {"kind": "world", "axis": "z", "offset": z}, "frame": {**s["frame"], "origin": [0, 0, z]}}


def square(i, name, z, side):
    return sketch_at(i, name, z, lambda s: add_rectangle(s, [-side / 2, -side / 2], [side / 2, side / 2]))


def extrude_all(i, sketch, frm, to, op="new", target=None):
    f = {"id": i, "kind": "extrude", "name": f"Extrude {i}", "sketchId": sketch["id"], "regions": [r["key"] for r in find_regions(sketch["sketch"])],
         "extent": {"kind": "distance", "from": frm, "to": to}, "op": op, "visible": True}
    if target is not None:
        f["target"] = target
    return f


def loft(i, sketches):
    return {"id": i, "kind": "loft", "name": f"Loft {i}", "sketches": sketches, "ruled": False, "op": "new", "visible": True}


def failures(features):
    return [{"id": s["id"], "message": s["message"]} for s in resolve_features(features, CTX, regions_of) if s["kind"] == "failed"]


class StepKeys(unittest.TestCase):
    def test_keys_are_the_originals(self):
        with open(os.path.join(HERE, "reverse_fixtures", "step_keys_goldens.json"), encoding="utf-8") as fh:
            gold = parse(fh.read())
        for name in ("plateWithHole", "extents", "bodyOps", "loftSweep"):
            features = gold[name]["features"]
            steps = resolve_features(features, gold["ctx"], regions_of)
            self.assertEqual([s["kind"] for s in steps], gold[name]["kinds"], name)
            by_id = {f["id"]: f["sketch"] for f in features if f["kind"] == "sketch"}
            self.assertEqual(step_keys(steps, by_id.get), gold[name]["keys"], name)

        def hole(depth):
            return step_keys([{"kind": "hole", "id": 1, "name": "Hole", "body": 1, "origin": [0, 0, 0], "dir": [0, 0, 1], "radius": 1, "depth": depth}], lambda i: None)[0]

        self.assertEqual([hole(math.inf), hole(-math.inf), hole(math.nan), hole(-0.0)], gold["special"])

    def test_tells_steps_apart_and_reads_sketches(self):
        def at(to):
            return step_keys([{"kind": "hole", "id": 1, "name": "Hole", "body": 1, "origin": [0, 0, 0], "dir": [0, 0, 1], "radius": 1, "depth": to}], lambda i: None)[0]

        self.assertNotEqual(at(math.inf), at(-math.inf))
        self.assertNotEqual(at(math.inf), at(math.nan))

        def region(r):
            return step_keys([{"kind": "surface", "id": 1, "name": "S", "region": r, "fit": {}, "shape": "freeform", "constrain": "auto", "refs": [], "refSurfaces": []}], lambda i: None)[0]

        self.assertNotEqual(region([1, 2, 3]), region([1, 2, 4]))
        self.assertEqual(region([1, 2, 3]), region([1, 2, 3]))
        plate = sketch_of(1, lambda s: add_rectangle(s, [0, 0], [40, 20]))
        circle = sketch_of(3, lambda s: add_entity(s, {"kind": "circle", "c": [20, 10], "r": 3}))
        features = [plate, extrude_all(2, plate, 0, 5), circle, extrude_all(4, circle, -1, 6, "cut", 2)]
        steps = resolve_features(features, CTX, regions_of)
        by_id = {f["id"]: f["sketch"] for f in features if f["kind"] == "sketch"}
        keys = step_keys(steps, by_id.get)

        def draw(s):
            add_entity(s, {"kind": "circle", "c": [20, 10], "r": 3})
            add_entity(s, {"kind": "point", "p": [0, 0]})

        moved = sketch_of(3, draw)
        other = step_keys(steps, lambda i: moved["sketch"] if i == 3 else by_id.get(i))
        self.assertEqual(other[0], keys[0])
        self.assertNotEqual(other[1], keys[1])

    def test_halton(self):
        self.assertEqual([halton(i, 2) for i in range(1, 5)], [0.5, 0.25, 0.75, 0.125])


class LoftChecks(unittest.TestCase):
    def test_section_crossing_itself(self):
        def bow_draw(s):
            corners = [[0, 0], [10, 10], [10, 0], [0, 10]]
            for i, p in enumerate(corners):
                add_entity(s, {"kind": "line", "a": p, "b": corners[(i + 1) % 4]})

        bow = sketch_at(1, "Bow", 0, bow_draw)
        self.assertRegex(loft_profile(bow, find_regions(bow["sketch"])),
                         r"^Bow's pieces close 2 regions \(areas 25, 25 mm²\) — the profile crosses itself or is cut across, and the loft would take the largest alone\.")
        self.assertRegex(loft_profile(bow, find_regions(bow["sketch"]), "the sweep"), "the sweep would take the largest alone")

        def ring_draw(s):
            add_rectangle(s, [-10, -10], [10, 10])
            add_entity(s, {"kind": "circle", "c": [0, 0], "r": 4})

        ring = sketch_at(2, "Ring", 0, ring_draw)
        profile = loft_profile(ring, find_regions(ring["sketch"]))
        self.assertEqual(len(profile["holes"]), 1)

    def test_sliver_and_run_off(self):
        def sliver_draw(s):
            corners = [[-5, -5], [-4.99, -5], [5, -5], [5, 5], [-5, 5]]
            for i, p in enumerate(corners):
                add_entity(s, {"kind": "line", "a": p, "b": corners[(i + 1) % len(corners)]})

        sliver = sketch_at(2, "Mid", 10, sliver_draw)
        got = failures([square(1, "Low", 0, 10), sliver, square(3, "High", 20, 10), loft(4, [1, 2, 3])])
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["id"], 4)
        self.assertRegex(got[0]["message"], r"^Mid's piece 1 \(a line\) is 0\.01 mm long — under 0\.05 mm: no piece of a section")
        self.assertRegex(failures([square(1, "Low", 0, 10), square(2, "Mid", 10, 100), square(3, "High", 20, 10), loft(4, [1, 2, 3])])[0]["message"],
                         r"^Mid spans 141\.4 mm across, its neighbours 14\.1 and 14\.1 mm — a piece of it runs far off")
        self.assertRegex(failures([square(1, "Low", 0, 10), square(2, "Mid", 10, 11), square(3, "High", 20, 100), loft(4, [1, 2, 3])])[0]["message"], r"^High spans 141\.4 mm across")
        self.assertEqual(failures([square(1, "Low", 0, 10), square(2, "Mid", 10, 20), square(3, "High", 20, 40), loft(4, [1, 2, 3])]), [])
        self.assertEqual(failures([square(1, "Low", 0, 5), square(2, "High", 10, 100), loft(4, [1, 2])]), [])

    def test_sketch_the_feature_cannot_have(self):
        low = square(1, "Low", 0, 10)
        high = square(2, "Top", 20, 10)
        self.assertRegex(failures([low, loft(3, [1, 2]), high])[0]["message"],
                         r"^Sketch 2 \(Top\) stands after this loft — a feature takes only the sketches above it\. Move it above:")
        self.assertRegex(failures([low, {**high, "suppressed": True}, loft(3, [1, 2])])[0]["message"], r"^Sketch 2 \(Top\) is suppressed — build it again")
        self.assertRegex(failures([extrude_all(3, high, 0, 5), high])[0]["message"], r"^Sketch 2 \(Top\) stands after this extrude")
        sweep = {"id": 3, "kind": "sweep", "name": "Sweep", "profile": 1, "path": 2, "op": "new", "visible": True}
        self.assertRegex(failures([low, sweep, high])[0]["message"], r"^Sketch 2 \(Top\) stands after this sweep")
        self.assertEqual(failures([low, loft(3, [1, 9])])[0]["message"], "A sketch this loft runs through is gone.")

    def test_sweep_refused_for_where_it_starts(self):
        profile = square(1, "Ring section", 0, 4)
        along = sketch_at(2, "Path", 0, lambda s: add_entity(s, {"kind": "line", "a": [0, 0], "b": [10, 0]}))
        self.assertEqual(sweep_geometry(profile, find_regions(profile["sketch"]), along),
                         "Ring section's plane stands 90.0° off square to the path where it starts — Path starts at (0, 0, 0) and leaves along (1, 0, 0); sketch the profile on a plane "
                         'through that point square to that way — the plane { kind: "world", axis: "x", offset: 0 } is square to it there.')
        slant = sketch_at(2, "Path", 0, lambda s: add_entity(s, {"kind": "line", "a": [0, 0], "b": [10, 5]}))
        self.assertRegex(sweep_geometry(profile, find_regions(profile["sketch"]), slant), r"leaves along \(0\.894, 0\.447, 0\); .* no coordinate plane is square to it there")

    def test_profile_no_longer_closed(self):
        before = sketch_of(1, lambda s: add_rectangle(s, [0, 0], [20, 10]))
        extrude = extrude_all(2, before, 0, 5)
        after = {**before, "sketch": clone_sketch(before["sketch"])}
        side = after["sketch"]["entities"][1]
        out = [math.copysign(1, side["b"][0] - 10) if side["b"][0] != 10 else 0, math.copysign(1, side["b"][1] - 5) if side["b"][1] != 5 else 0]
        side["b"] = [side["b"][0] + (out[0] * 0.099) / math.sqrt(2), side["b"][1] + (out[1] * 0.099) / math.sqrt(2)]
        self.assertRegex(failures([after, extrude])[0]["message"],
                         r"^The picked profiles are no longer closed — the sketch changed under them\. Its open ends: piece \d end [ab] is 0\.099 mm from piece \d end [ab] — put the ends together")

    @unittest.skip(KERNEL)
    def test_join_left_no_closed_solid(self):
        pass

    @unittest.skip("the headless reverse.feature.add command (fam_reverse.py) is not ported")
    def test_sketch_answer_lists_near_misses(self):
        pass


# ---- reDraftCrease: the rumble pak's body plan ----------------------------------------------

DEG = math.pi / 180
Y0 = 29.0358
R = 6.2409
CX = -32.5091
CY = 22.193969020137104


def on_circle(c, r, a):
    return [c[0] + r * math.cos(a), c[1] + r * math.sin(a)]


def line_rear(k1t, k1b, k2t, k2b, front=None):
    if front is None:
        front = [{"kind": "line", "a": [3, -Y0], "b": [3, Y0], "id": 40}]
    s = math.atan2(Y0 - 28.433978168653738, 3 + 32.61454494501266)
    t0 = math.pi / 2 + s + k1t
    t1 = math.pi + k2t
    b0 = math.pi - k2b
    b1 = (3 * math.pi) / 2 - s - k1b
    ct = [CX, CY]
    cb = [CX, -CY]
    return [*front,
            {"kind": "line", "a": [3, Y0], "b": on_circle(ct, R, t0), "id": 41},
            {"kind": "arc", "c": ct, "r": R, "start": t0, "sweep": t1 - t0, "id": 52},
            {"kind": "line", "a": on_circle(ct, R, t1), "b": on_circle(cb, R, b0), "id": 42},
            {"kind": "arc", "c": cb, "r": R, "start": b0, "sweep": b1 - b0, "id": 58},
            {"kind": "line", "a": on_circle(cb, R, b1), "b": [3, -Y0], "id": 43}]


def kinked_front(kink, at):
    bulge = kink / (1 / (at + Y0) + 1 / (Y0 - at))
    m = [3 + bulge, at]
    return [{"kind": "line", "a": [3, -Y0], "b": m, "id": 44}, {"kind": "line", "a": m, "b": [3, Y0], "id": 45}]


def r615_rear(crease):
    RR = 615
    rc = [-39.15 + RR, 0]

    def placed(phi):
        d = -R * math.cos(phi) + math.sqrt(R * R * math.cos(phi) ** 2 - R * R + RR * RR)
        c = [rc[0] - math.sqrt(d * d - CY * CY), CY]
        ray = math.atan2(c[1] - rc[1], c[0] - rc[0])
        cross = on_circle(c, R, ray - phi)
        n1 = [cross[0] - c[0], cross[1] - c[1]]
        n2 = [cross[0] - rc[0], cross[1] - rc[1]]
        off = math.atan2(abs(n1[0] * n2[1] - n1[1] * n2[0]), n1[0] * n2[0] + n1[1] * n2[1])
        return c, ray, cross, off

    lo, hi = 0, 0.3
    for _ in range(80):
        mid = (lo + hi) / 2
        if placed(mid)[3] < crease:
            lo = mid
        else:
            hi = mid
    phi = (lo + hi) / 2
    c, ray, cross, _ = placed(phi)
    w = [3 - c[0], Y0 - c[1]]
    a0 = math.atan2(w[1], w[0]) + math.acos(R / math.hypot(w[0], w[1]))
    a1 = ray - phi
    top = on_circle(c, R, a0)
    rear_at = math.atan2(cross[1] - rc[1], cross[0] - rc[0])
    cb = [c[0], -c[1]]
    return [{"kind": "line", "a": [3, -Y0], "b": [3, Y0], "id": 40},
            {"kind": "line", "a": [3, Y0], "b": top, "id": 41},
            {"kind": "arc", "c": c, "r": R, "start": a0, "sweep": a1 - a0, "id": 52},
            {"kind": "arc", "c": rc, "r": RR, "start": rear_at, "sweep": 2 * (math.pi - rear_at), "id": 42},
            {"kind": "arc", "c": cb, "r": R, "start": 2 * math.pi - a1, "sweep": a1 - a0, "id": 58},
            {"kind": "line", "a": [top[0], -top[1]], "b": [3, -Y0], "id": 43}]


def mend_of(entities):
    sketch = {"entities": [{**e, "fixed": True} for e in entities], "constraints": [], "nextId": 100}
    regions = find_regions(sketch)
    sk = {"id": 1, "kind": "sketch", "name": "Body plan sk", "plane": {"kind": "world", "axis": "z", "offset": -12},
          "frame": {"origin": [0, 0, -12], "normal": [0, 0, 1], "basisU": [1, 0, 0], "basisV": [0, 1, 0]}, "visible": False, "sketch": sketch}
    ex = {"id": 2, "kind": "extrude", "name": "Body plan", "sketchId": 1, "regions": [regions[0]["key"]], "extent": {"from": 0, "kind": "distance", "to": 10}, "draftDeg": -3.2, "op": "new", "visible": True}
    steps = resolve_features([sk, ex], CTX, regions_of)
    return mend_near_tangent(next(s for s in steps if s["kind"] == "extrude")["profiles"])


class DraftCrease(unittest.TestCase):
    @unittest.skip(KERNEL)
    def test_made_tangent_and_builds_at_the_tangent_volume(self):
        pass

    def test_leaves_a_real_corner(self):
        for drawn in (line_rear(1 * DEG, 0, 0, 0), line_rear(0, 0, 0, 0, kinked_front(1 * DEG, Y0 - 4)), r615_rear(1 * DEG)):
            out = mend_of(drawn)
            self.assertEqual(out["mends"], [])
            self.assertEqual(out["left"], [])
            self.assertEqual(len(out["profiles"][0]["outer"]), len(drawn))

    def test_names_a_join_too_far_off_to_mend(self):
        out = mend_of(line_rear(0, 0, 0, 0, kinked_front(0.06 * DEG, 0)))
        self.assertEqual(out["mends"], [])
        self.assertEqual([sorted([j["from"], j["to"]]) for j in out["left"]], [[44, 45]])

    @unittest.skip(KERNEL)
    def test_draft_feature_names_the_join(self):
        pass


class RevolvePole(unittest.TestCase):
    def test_off_centre_arc_turned_to_start_on_the_axis(self):
        r0 = 5
        for d in (0.5, 0.05):
            for up in (1, -1):
                r = r0 - d
                h = math.sqrt(r * r - d * d)
                base, pole, o = [r0, 0, 0], [0, 0, up * h], [0, 0, 0]
                t = math.atan2(up * h, -d) / 2
                mid = [d + r * math.cos(t), 0, r * math.sin(t)]
                to_pole = [{"kind": "line", "a": o, "b": base}, {"kind": "arc", "a": base, "m": mid, "b": pole}, {"kind": "line", "a": pole, "b": o}]
                from_pole = [{"kind": "line", "a": o, "b": pole}, {"kind": "arc", "a": pole, "m": mid, "b": base}, {"kind": "line", "a": base, "b": o}]
                for loop in (to_pole, from_pole):
                    mended = mend_poles([{"outer": loop, "holes": []}], [0, 0, 0], [0, 0, 1])
                    self.assertEqual(mended["profiles"][0]["outer"][1]["a"], pole)

    @unittest.skip(KERNEL)
    def test_comes_back_whole_from_step(self):
        pass


class PlaneNames(unittest.TestCase):
    def test_offset_in_inches(self):
        ctx = {"sections": [{"id": 3, "name": "Section 1"}], "elements": []}
        self.assertEqual(describe_plane_ref({"kind": "section", "id": 3, "offset": 12.7}, ctx, "in"), "Section 1, +0.500 in off it")
        self.assertEqual(describe_plane_ref({"kind": "section", "id": 3, "offset": -25.4}, ctx, "in"), "Section 1, −1.000 in off it")
        self.assertEqual(describe_plane_ref({"kind": "world", "axis": "z", "offset": 25.4}, ctx, "in"), "XY plane at Z = 1.000")
        self.assertEqual(describe_plane_ref({"kind": "section", "id": 3, "offset": 12.7}, ctx), "Section 1, +12.70 mm off it")
        self.assertEqual(describe_plane_ref({"kind": "world", "axis": "z", "offset": 25.4}, ctx), "XY plane at Z = 25.40")

    def test_symmetry_plane_by_its_label(self):
        ref = {"kind": "fitted", "frame": {"origin": [0, 0, 3], "normal": [0, 0, 1], "basisU": [1, 0, 0], "basisV": [0, 1, 0]}, "label": "the scan’s symmetry plane"}
        self.assertEqual(describe_plane_ref(ref, {"sections": [], "elements": []}), "the scan’s symmetry plane")


if __name__ == "__main__":
    unittest.main()
