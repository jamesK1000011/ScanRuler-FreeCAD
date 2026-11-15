# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/tests/reStations.test.ts, reStationsOpenRun.test.ts, reStations15.test.ts
# SPDX-License-Identifier: AGPL-3.0-only
#
# The stations of a loft from the scan: a chain cut into another station's
# pieces kind for kind; a station read as a profile; a station fitted like
# another; a closed profile moved inward by a wall, its base line kept; the
# faults a station is checked for where it is made; a station refused on an
# open run, with the gaps it decided on. The wing lofted end to end runs
# through the kernel and the headless commands, and waits for them. Last,
# this port's own check that a parameter driving an inset moves the profile
# in again (parameters.ts insetAgain).
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from scanrulerfc.geom2d import FitError  # noqa: E402
from scanrulerfc.reverse._js import js_round, num_str  # noqa: E402
from scanrulerfc.reverse.chain_outline import join_chain_ends  # noqa: E402
from scanrulerfc.reverse.parameters import apply_parameters, evaluate_parameters  # noqa: E402
from scanrulerfc.reverse.sketch import add_constraint, add_entity, anchor_point, empty_sketch  # noqa: E402
from scanrulerfc.reverse.stations import (gaps_round, inset_keeps, inset_sketch, kinds_of_chain, like_station, run_facts_words, station_faults,  # noqa: E402
                                          station_loop)

DEG = math.pi / 180
KERNEL = "kernel (step 3) not ported"


def lcg(seed):
    s = [seed]

    def rand():
        s[0] = (s[0] * 1664525 + 1013904223) & 0xFFFFFFFF
        return (s[0] / 2 ** 32) * 2 - 1

    return rand


def wing_at(z):
    return {"R": 24 + 0.15 * z, "rise": 0.05 * z, "flare": (8 + 0.1 * z) * DEG, "t": 2, "base": -15}


def along(a, b, n):
    return [[a[0] + ((b[0] - a[0]) * i) / n, a[1] + ((b[1] - a[1]) * i) / n] for i in range(n)]


def wall_foot(r, rise, theta, base, side):
    top = [r * math.cos(theta), rise + r * math.sin(theta)]
    d = [math.sin(theta), -math.cos(theta)] if side == 1 else [-math.sin(theta), math.cos(theta)]
    k = (base - top[1]) / d[1]
    return top, [top[0] + d[0] * k, base]


def outer_run(z, frm=-13, noise=0.02):
    w = wing_at(z)
    r_top, r_foot = wall_foot(w["R"], w["rise"], w["flare"], w["base"], 1)
    l_top, l_foot = wall_foot(w["R"], w["rise"], math.pi - w["flare"], w["base"], -1)

    def k(y, a, b):
        f = (y - a[1]) / (b[1] - a[1])
        return [a[0] + (b[0] - a[0]) * f, y]

    pts = along(k(frm, r_foot, r_top), r_top, 60)
    for i in range(200):
        a = w["flare"] + ((math.pi - 2 * w["flare"]) * i) / 200
        pts.append([w["R"] * math.cos(a), w["rise"] + w["R"] * math.sin(a)])
    pts += along(l_top, k(frm, l_foot, l_top), 60) + [k(frm, l_foot, l_top)]
    rand = lcg(11)
    out = []
    for p in pts:
        x = p[0] + rand() * noise
        out.append([x, p[1] + rand() * noise])
    return out


def template_at(z):
    w = wing_at(z)
    r_top, r_foot = wall_foot(w["R"], w["rise"], w["flare"], -15, 1)
    l_top, l_foot = wall_foot(w["R"], w["rise"], math.pi - w["flare"], -15, -1)

    def at(a, b, y):
        return [a[0] + ((b[0] - a[0]) * (y - a[1])) / (b[1] - a[1]), y]

    r0 = at(r_foot, r_top, -13)
    l0 = at(l_foot, l_top, -13)
    run = outer_run(z)
    s = empty_sketch()
    wall_r = add_entity(s, {"kind": "line", "a": r0, "b": r_top, "points": run[0:60], "scatter": 0.02})
    arch = add_entity(s, {"kind": "arc", "c": [0, w["rise"]], "r": w["R"], "start": w["flare"], "sweep": math.pi - 2 * w["flare"], "points": run[60:260], "scatter": 0.02})
    wall_l = add_entity(s, {"kind": "line", "a": l_top, "b": l0, "points": run[260:], "scatter": 0.02})
    base = add_entity(s, {"kind": "line", "a": l0, "b": r0})
    add_constraint(s, {"kind": "coincident", "p": {"entity": wall_r, "at": "b"}, "q": {"entity": arch, "at": "a"}})
    add_constraint(s, {"kind": "coincident", "p": {"entity": arch, "at": "b"}, "q": {"entity": wall_l, "at": "a"}})
    add_constraint(s, {"kind": "coincident", "p": {"entity": wall_l, "at": "b"}, "q": {"entity": base, "at": "a"}})
    add_constraint(s, {"kind": "coincident", "p": {"entity": base, "at": "b"}, "q": {"entity": wall_r, "at": "a"}})
    add_constraint(s, {"kind": "tangent", "a": wall_r, "b": arch})
    add_constraint(s, {"kind": "tangent", "a": arch, "b": wall_l})
    add_constraint(s, {"kind": "horizontal", "entity": base})
    add_constraint(s, {"kind": "radius", "entity": arch, "value": w["R"]})
    return s


def loop_of(s):
    loop = station_loop(s, "Station")
    if isinstance(loop, str):
        raise AssertionError(loop)
    return loop


def line_gap(a, b):
    d = [b["b"][0] - b["a"][0], b["b"][1] - b["a"][1]]
    ln = math.hypot(d[0], d[1])
    return abs(((a["a"][0] - b["a"][0]) * d[1] - (a["a"][1] - b["a"][1]) * d[0]) / ln)


class Stations(unittest.TestCase):
    def test_chain_cut_into_given_pieces(self):
        cut = kinds_of_chain(outer_run(20), ["line", "arc", "line"])
        self.assertEqual([s["kind"] for s in cut["segments"]], ["line", "arc", "line"])
        self.assertLess(abs(cut["segments"][1]["fit"]["radius"] - wing_at(20)["R"]), 0.5)
        self.assertLess(abs(cut["segments"][0]["hi"] - 60), 6)
        self.assertLess(abs(cut["segments"][2]["lo"] - 260), 6)
        with self.assertRaisesRegex(FitError, "too few"):
            kinds_of_chain(outer_run(20)[:8], ["line", "arc", "arc", "line"])

    def test_station_read_as_profile(self):
        loop = loop_of(template_at(0))
        self.assertTrue(loop["closed"])
        self.assertEqual([[p["kind"], p["fitted"]] for p in loop["pieces"]], [["line", True], ["arc", True], ["line", True], ["line", False]])
        branch = template_at(0)
        add_entity(branch, {"kind": "line", "a": branch["entities"][0]["b"], "b": [0, 0]})
        self.assertRegex(station_loop(branch, "Wing 1"), "branches")
        spline = empty_sketch()
        add_entity(spline, {"kind": "spline", "pts": [[0, 0], [1, 1], [2, 0]]})
        self.assertRegex(station_loop(spline, "Wing 1"), "lines and arcs")

    def test_fitted_like_another(self):
        template = template_at(0)
        loop = loop_of(template)
        for run in (outer_run(30), outer_run(30)[::-1]):
            made = like_station(template, loop, run)
            if isinstance(made, str):
                raise AssertionError(made)
            sk = made["sketch"]
            self.assertEqual([[e["id"], e["kind"]] for e in sk["entities"]], [[e["id"], e["kind"]] for e in template["entities"]])
            self.assertLess(abs(sk["entities"][1]["r"] - wing_at(30)["R"]), 0.5)
            base = sk["entities"][3]
            self.assertAlmostEqual(base["a"][1], -13, 6)
            self.assertAlmostEqual(base["b"][1], -13, 6)
            wall_r = sk["entities"][0]
            self.assertTrue(any(abs(p[1] + 13) < 1e-6 for p in (wall_r["a"], wall_r["b"])))
            self.assertEqual(sorted(c["kind"] for c in sk["constraints"]), ["coincident"] * 4 + ["horizontal", "tangent", "tangent"])

    def test_moved_inward(self):
        template = template_at(0)
        loop = loop_of(template)
        self.assertEqual(inset_keeps(loop), [4])
        out = inset_sketch(template, loop, 2, set(inset_keeps(loop)))
        if isinstance(out, str):
            raise AssertionError(out)
        self.assertEqual(out["moved"], [1, 2, 3])
        wall_r, arch, wall_l, base = out["sketch"]["entities"]
        was_r, was_arch, was_l = template["entities"][:3]
        self.assertAlmostEqual(arch["r"], was_arch["r"] - 2, 9)
        self.assertAlmostEqual(line_gap(wall_r, was_r), 2, 9)
        self.assertAlmostEqual(line_gap(wall_l, was_l), 2, 9)
        self.assertNotIn("points", wall_r)
        p, q = anchor_point(wall_r, "b"), anchor_point(arch, "a")
        self.assertLess(math.hypot(p[0] - q[0], p[1] - q[1]), 1e-6)
        self.assertAlmostEqual(base["a"][1], -13, 9)
        tb = template["entities"][3]
        self.assertLess(abs(base["b"][0] - base["a"][0]), abs(tb["b"][0] - tb["a"][0]))
        radius = next(c for c in out["sketch"]["constraints"] if c["kind"] == "radius")
        self.assertAlmostEqual(radius["value"], was_arch["r"] - 2, 9)
        self.assertEqual(out["dropped"], [])

    def test_inset_refusals(self):
        opened = template_at(0)
        opened["entities"].pop()
        self.assertRegex(inset_sketch(opened, loop_of(opened), 2, set()), "open")
        template = template_at(0)
        self.assertRegex(inset_sketch(template, loop_of(template), 30, {4}), "close up|inside out")

    @unittest.skip(KERNEL)
    def test_moulded_wing_end_to_end(self):
        pass

    @unittest.skip(KERNEL)
    def test_twin_alone_with_inset(self):
        pass


# ---- reStationsOpenRun ------------------------------------------------------------------------


def square_along(s):
    t = ((s % 160) + 160) % 160
    if t <= 40:
        return [t, 0]
    if t <= 80:
        return [40, t - 40]
    if t <= 120:
        return [120 - t, 40]
    return [0, 160 - t]


def walk(s0, s1):
    out = []
    s = s0
    while s < s1:
        out.append(square_along(s))
        s += 0.5
    out.append(square_along(s1))
    return out


def broken():
    return [walk(13, 50), walk(58, 90), walk(109, 170)]


def square_template():
    def line(i, a, b):
        return {"id": i, "kind": "line", "a": a, "b": b, "points": [[0, 0]]}

    return {"entities": [line(1, [0, 0], [40, 0]), line(2, [40, 0], [40, 40]), line(3, [40, 40], [0, 40]), line(4, [0, 40], [0, 0])], "constraints": [], "nextId": 5}


class OpenRun(unittest.TestCase):
    def close_list(self, got, want):
        self.assertEqual(len(got), len(want))
        for g, w in zip(got, want):
            self.assertAlmostEqual(g, w, 6)

    def test_gaps_round(self):
        g = gaps_round(broken(), [0])
        self.assertEqual(g["bridged"], [])
        self.close_list(g["open"], [19, 8, 3])
        joined = join_chain_ends(broken(), 3.5)
        run = next(c for c in joined if 0 in c["from"])
        self.assertEqual(run["from"], [0, 2])
        g = gaps_round(broken(), run["from"], 3.5)
        self.close_list(g["bridged"], [3])
        self.close_list(g["open"], [19, 8])

    def test_refused_on_open_run(self):
        tmpl = square_template()
        loop = station_loop(tmpl, "Square")
        chains = broken()
        joined = join_chain_ends(chains, 3.5)
        w = joined[0]
        for c in joined[1:]:
            if len(c["chain"]) > len(w["chain"]):
                w = c
        self.assertRegex(like_station(tmpl, loop, w["chain"]), "closed outline fitted whole, and this run is open")
        words = run_facts_words(loop, {"run": w["chain"], "joined": w, "chains": chains, "runs": 1, "fit": {"closeGaps": 3.5}})
        a, b = square_along(50), square_along(109)
        ends = math.hypot(a[0] - b[0], a[1] - b[1])
        self.assertIn(f"The run’s ends stand {num_str(js_round(ends * 1000) / 1000)} mm apart", words)
        self.assertIn("closeGaps 3.5 bridged 1 gap (3 mm); still open: 19, 8 mm", words)
        self.assertRegex(words, r"closeGaps 19\.95 bridges them where they are holes in the scan; where they are the part’s own \(a gap between keys\), close the template with a drawn piece")
        plain = run_facts_words(loop, {"run": chains[2], "joined": {"chain": chains[2], "from": [2]}, "chains": chains, "runs": 1, "fit": {}})
        self.assertIn("no closeGaps given, none bridged; still open: 19, 8, 3 mm", plain)

    def test_within_split_a_closed_chain(self):
        loop = station_loop(square_template(), "Square")
        whole = walk(0, 160)
        run = walk(5, 150)
        words = run_facts_words(loop, {"run": run, "joined": {"chain": whole, "from": [0]}, "chains": [whole], "runs": 2, "fit": {"within": {"min": [-1, -1], "max": [41, 41]}}})
        self.assertRegex(words, r"^ The run’s ends stand \d+(\.\d+)? mm apart: its chain closed \(no closeGaps given, none bridged\), and within split it into 2 runs, the longest taken — fit the closed chain without it")

    def test_names_bridges_on_other_refusals(self):
        loop = station_loop(square_template(), "Square")
        opened = {"pieces": [{**p, "fitted": i < 3} for i, p in enumerate(loop["pieces"])], "closed": True}
        chains = broken()
        joined = join_chain_ends(chains, 3.5)
        w = next(c for c in joined if 0 in c["from"])
        self.assertEqual(run_facts_words(opened, {"run": w["chain"], "joined": w, "chains": chains, "runs": 1, "fit": {"closeGaps": 3.5}}),
                         " (closeGaps 3.5 bridged 1 gap (3 mm) — a bridge is a straight run across a hole, and the station’s pieces may not fall on it)")
        self.assertEqual(run_facts_words(opened, {"run": chains[1], "joined": {"chain": chains[1], "from": [1]}, "chains": chains, "runs": 1, "fit": {}}), "")


# ---- reStations15 -----------------------------------------------------------------------------


def station(pieces):
    s = {"entities": [], "constraints": [], "nextId": 41}
    for p in pieces:
        if p["kind"] == "line":
            e = {"id": p["id"], "kind": "line", "a": p["a"], "b": p["b"]}
            if not p.get("drawn"):
                e["points"] = [[0, 0]]
        else:
            e = {"id": p["id"], "kind": "arc", "c": p["c"], "r": p["r"], "start": p["start"] * DEG, "sweep": p["sweep"] * DEG, "points": [[0, 0]]}
        s["entities"].append(e)
    return s


def L(i, a, b, drawn=False):
    return {"id": i, "kind": "line", "a": a, "b": b, "drawn": drawn}


def A(i, c, r, start, sweep):
    return {"id": i, "kind": "arc", "c": c, "r": r, "start": start, "sweep": sweep}


def sound():
    return station([L(7, [29.5081, 2], [34.1744, -11.6253]), A(8, [36.7455, -10.7447], 2.7178, 198.905, 71.2241), L(9, [36.7517, -13.4625], [37.7577, -13.4602]),
                    A(10, [37.7476, -8.9843], 4.4759, 270.129, 88.26), L(11, [42.2217, -9.1101], [42.5342, 2]), L(40, [29.5081, 2], [42.5342, 2], True)])


def backwards():
    return station([L(7, [36.1393, 2], [35.5425, -9.9852]), A(8, [37.3741, -10.0764], 1.8339, 177.1493, 96.5961), L(9, [37.4939, -11.9064], [36.4499, -11.9747]),
                    A(10, [36.2013, -8.1773], 3.8055, 273.7454, 85.8917), L(11, [40.0068, -8.2014], [40.0714, 2]), L(40, [36.1393, 2], [40.0714, 2], True)])


def sliver_round():
    return station([L(7, [33.0088, 2], [33.0088, -10.3777]), A(8, [31.887, -10.3777], 1.1219, 0, 3.2907), L(9, [33.007, -10.3133], [33.3512, -16.3008]),
                    A(10, [42.3415, -15.7839], 9.0051, 183.2907, 174.8001), L(11, [51.3415, -16.0839], [51.9443, 2]), L(40, [33.0088, 2], [51.9443, 2], True)])


def entity(s, i):
    return next(e for e in s["entities"] if e["id"] == i)


class Round15(unittest.TestCase):
    def test_faults_against_template(self):
        template = sound()
        loop = loop_of(template)
        self.assertEqual(station_faults(template, loop, sound()), [])
        self.assertEqual(station_faults(template, loop, backwards()), ["piece 9 (a line) runs 1.046 mm backwards against the template’s piece 9"])
        pulled = sound()
        floor = entity(pulled, 9)
        floor["b"] = [floor["a"][0] + 0.0005, floor["a"][1]]
        self.assertEqual(station_faults(template, loop, pulled), ["piece 9 (a line) is 0.0005 mm long — under 0.05 mm"])
        self.assertEqual(station_faults(template, loop, sliver_round()), ["piece 8 (an arc) sweeps 3.3° — under 5°"])

    def test_piece_shorter_than_touch(self):
        s = sound()
        floor = entity(s, 9)
        floor["b"] = [floor["a"][0] + 0.0005, floor["a"][1]]
        said = station_loop(s, "Passage start station 2")
        self.assertRegex(said, r"^Passage start station 2's piece 9 \(a line\) is 0\.0005 mm long — shorter than the 0\.002 mm two ends meet within")
        self.assertNotRegex(said, "branches")

    def test_corner_met_far_past_the_run(self):
        t = empty_sketch()
        add_entity(t, {"kind": "line", "a": [0, 10], "b": [0, 0], "points": [[0, 0]]})
        add_entity(t, {"kind": "line", "a": [0, 0], "b": [10, -10], "points": [[0, 0]]})
        add_entity(t, {"kind": "line", "a": [10, -10], "b": [20, 10], "points": [[0, 0]]})
        add_entity(t, {"kind": "line", "a": [20, 10], "b": [0, 10]})
        loop = loop_of(t)
        flat = along([0, 10], [0, 0], 20) + along([0, 0], [10, -10], 20) + along([10, -10], [30, -9], 40) + [[30, -9]]
        self.assertRegex(like_station(t, loop, flat), r"^the corner of pieces 3 and 4 lands \d+(\.\d+)? mm past the run’s ends — over 2× the run’s extent \(\d+(\.\d+)? mm\).*Point it with within or facing\.$")
        up = along([0, 10], [0, 0], 20) + along([0, 0], [10, -10], 20) + along([10, -10], [19, 8], 40) + [[19, 8]]
        made = like_station(t, loop, up)
        if isinstance(made, str):
            raise AssertionError(made)
        self.assertEqual([e["id"] for e in made["sketch"]["entities"]], [1, 2, 3, 4])

    def test_folded_inset_refused(self):
        folded = backwards()
        self.assertRegex(inset_sketch(folded, loop_of(folded), -3, set(inset_keeps(loop_of(folded)))),
                         r"^the arc 8 would turn inside out at -3 mm — its sweep goes from 96\.6° to 200\.\d°, more than the corners it meets its neighbours at let it \(15°\): they cross past it\. "
                         r"The source folds back at the corner of pieces 8 and 9 \(it turns 180° there\) — fit that station again")
        outlet = sliver_round()
        self.assertRegex(inset_sketch(outlet, loop_of(outlet), -3, set(inset_keeps(loop_of(outlet)))),
                         r"^the arc 8 would turn inside out at -3 mm — its sweep goes from 3\.3° to \d+\.\d°.*folds back at the corner of pieces 7 and 8")

    def test_sound_station_moved_out(self):
        s = sound()
        loop = loop_of(s)
        out = inset_sketch(s, loop, -3, set(inset_keeps(loop)))
        if isinstance(out, str):
            raise AssertionError(out)

        def sweeps(k):
            return [e["sweep"] / DEG for e in k["entities"] if e["kind"] == "arc"]

        for got, want in zip(sweeps(out["sketch"]), sweeps(s)):
            self.assertLess(abs(got - want), 0.5)
        self.assertEqual(out["dropped"], [])


class InsetAgain(unittest.TestCase):
    def test_parameter_moves_profile_in_again(self):
        frame = {"origin": [0, 0, 0], "normal": [0, 0, 1], "basisU": [1, 0, 0], "basisV": [0, 1, 0]}
        outer = empty_sketch()
        corners = [[-10, -10], [10, -10], [10, 10], [-10, 10]]
        for i, p in enumerate(corners):
            add_entity(outer, {"kind": "line", "a": p, "b": corners[(i + 1) % 4]})
        inner = inset_sketch(outer, loop_of(outer), 1, set())["sketch"]

        def sk(i, name, sketch, **more):
            return {"id": i, "kind": "sketch", "name": name, "plane": {"kind": "world", "axis": "z", "offset": 0}, "frame": frame, "sketch": sketch, "visible": True, **more}

        features = [sk(1, "Outer", outer), sk(2, "Inner", inner, inset={"of": 1, "by": 1, "keep": []}, exprs={"inset": "wall"})]
        scope = evaluate_parameters([{"id": 1, "name": "wall", "kind": "length", "expression": "3"}])["scope"]
        out = apply_parameters(features, scope)
        self.assertEqual(out["errors"], {})
        moved = out["features"][1]
        self.assertEqual(moved["inset"]["by"], 3)
        us = [p[0] for e in moved["sketch"]["entities"] for p in (e["a"], e["b"])]
        self.assertAlmostEqual(max(us) - min(us), 14, 6)


if __name__ == "__main__":
    unittest.main()
