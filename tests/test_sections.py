# SPDX-License-Identifier: AGPL-3.0-only
# Sections, their fits and the sketch they become — ported from ScanRuler's
# tests/section.test.ts and the profile road, run through Agent Link.
import json
import math
import os
import sys
import tempfile
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
if os.environ.get("FREECAD_LIB"):
    sys.path.append(os.environ["FREECAD_LIB"])
try:
    import FreeCAD  # noqa: F401
    import agentlink  # noqa: F401

    HAVE = True
except ImportError:
    HAVE = False

from meshkit import box_mesh, cylinder_mesh, subdivide, write_stl  # noqa: E402
from scanrulerfc import section_core as SC  # noqa: E402
from scanrulerfc.chainsegment import profile_curves, segment_chain  # noqa: E402


def path_length(c):
    return float(np.linalg.norm(np.diff(c, axis=0), axis=1).sum())


def chains(cut):
    P, off, _ = cut
    return [P[off[i]:off[i + 1]] for i in range(len(off) - 1)]


def grid_plate(keep, size=(20, 10), step=0.5):
    """A flat plate of small triangles on z 0, the cells keep(cx, cy) says."""
    xs = np.arange(0, size[0] + 1e-9, step)
    ys = np.arange(0, size[1] + 1e-9, step)
    V = np.array([(x, y, 0.0) for x in xs for y in ys])
    at = lambda i, j: i * len(ys) + j  # noqa: E731
    F = []
    for i in range(len(xs) - 1):
        for j in range(len(ys) - 1):
            if keep(xs[i] + step / 2, ys[j] + step / 2):
                a, b, c, d = at(i, j), at(i + 1, j), at(i + 1, j + 1), at(i, j + 1)
                F += [(a, b, c), (a, c, d)]
    return V, np.array(F)


class Shadow(unittest.TestCase):
    """The shadow's loops (ScanRuler's core/section/shadow.ts), numpy only."""

    FRAME = {"origin": [0, 0, 0], "normal": [0, 0, 1], "basisU": [1, 0, 0], "basisV": [0, 1, 0]}

    def test_l_plate_hole_filled(self):
        from scanrulerfc import shadow_core as SH

        # An L, 20 x 10 less its 10 x 5 corner, with a 2 x 2 hole: the
        # shadow is the L's outline alone, the hole filled.
        V, F = grid_plate(lambda x, y: not (x > 10 and y > 5) and not (2 < x < 4 and 2 < y < 4))
        loops, cell = SH.shadow_loops(V, F, self.FRAME, 0.1)
        self.assertEqual(len(loops), 1)
        self.assertAlmostEqual(SH.area(loops[0]), 150, delta=150 * 0.01)
        self.assertEqual(len(loops[0]), 6)

    def test_two_islands_and_edge_on(self):
        from scanrulerfc import shadow_core as SH

        V, F = grid_plate(lambda x, y: x < 5 or x > 15)
        loops, _ = SH.shadow_loops(V, F, self.FRAME, 0.1)
        self.assertEqual(len(loops), 2)
        # Seen edge on (along y), a flat plate casts no shadow.
        side = {"origin": [0, 0, 0], "normal": [0, 1, 0], "basisU": [1, 0, 0], "basisV": [0, 0, 1]}
        self.assertEqual(SH.shadow_loops(V, F, side, 0.1)[0], [])


class Next(unittest.TestCase):
    def test_the_pad_call_names_the_labels_that_came_out(self):
        from scanrulerfc.handlers import sections as H

        self.assertEqual(H.pad_next("Body002", "MidProfile"), 'pd_pad { body: "Body002", sketch: "MidProfile", length } stands it up.')
        self.assertIn('"Gehäuse"', H.pad_next("Gehäuse", "Mid sketch"))


class Slice(unittest.TestCase):
    """ScanRuler's tests/section.test.ts, sliceMesh."""

    def test_box_loop(self):
        V, F = box_mesh(20, 20, 20, 8)
        cs = chains(SC.slice_mesh(V, F, [0, 0, 3.3], [0, 0, 1]))
        self.assertEqual(len(cs), 1)
        self.assertTrue(np.array_equal(cs[0][0], cs[0][-1]))
        self.assertTrue(np.allclose(cs[0][:, 2], 3.3))
        self.assertAlmostEqual(path_length(cs[0]), 80, places=4)

    def test_cylinder_circle(self):
        V, F = cylinder_mesh(10, 20, 96)
        cs = chains(SC.slice_mesh(V, F, [0, 0, 4], [0, 0, 1]))
        self.assertEqual(len(cs), 1)
        r = np.hypot(cs[0][:, 0], cs[0][:, 1])
        sag = 10 * (1 - math.cos(math.pi / 96))
        self.assertTrue(np.all(r <= 10 + 1e-5) and np.all(r >= 10 - sag - 1e-5))
        self.assertAlmostEqual(path_length(cs[0]), 96 * 2 * 10 * math.sin(math.pi / 96), places=2)

    def test_cylinder_along_axis(self):
        V, F = cylinder_mesh(10, 30, 96)
        cs = chains(SC.slice_mesh(V, F, [0, 0, 0], [0, 1, 0]))
        self.assertEqual(len(cs), 1)
        self.assertAlmostEqual(path_length(cs[0]), 100, places=3)

    def test_open_surface(self):
        V = np.array([[0, 0, 0], [20, 0, 0], [20, 0, 10], [0, 0, 10]], dtype=float)
        F = np.array([[0, 1, 2], [0, 2, 3]])
        cs = chains(SC.slice_mesh(V, F, [0, 0, 2], [0, 0, 1]))
        self.assertEqual(len(cs), 1)
        self.assertFalse(np.array_equal(cs[0][0], cs[0][-1]))
        self.assertAlmostEqual(path_length(cs[0]), 20, places=5)

    def test_misses_and_specks(self):
        V, F = box_mesh(20, 20, 20, 4)
        self.assertEqual(len(SC.slice_mesh(V, F, [0, 0, 50], [0, 0, 1])[1]) - 1, 0)
        self.assertEqual(len(SC.slice_mesh(V, F, [0, 0, 1], [0, 0, 1], min_length=100)[1]) - 1, 0)

    def test_vertex_on_plane(self):
        V, F = box_mesh(20, 20, 20, 4)
        cs = chains(SC.slice_mesh(V, F, [0, 0, 0], [0, 0, 1]))
        self.assertEqual(len(cs), 1)
        self.assertAlmostEqual(path_length(cs[0]), 80, places=4)

    def test_outward_normals(self):
        V, F = cylinder_mesh(10, 20, 96)
        P, off, N = SC.slice_mesh(V, F, [0, 0, 4], [0, 0, 1])
        radial = P[:, :2] / np.linalg.norm(P[:, :2], axis=1)[:, None]
        self.assertTrue(np.all((N[:, :2] * radial).sum(axis=1) > 0.99))

    def test_frames(self):
        self.assertEqual(SC.parse_plane_name("XY"), "z")
        self.assertEqual(SC.parse_plane_name("zx plane"), "y")
        self.assertIsNone(SC.parse_plane_name("XX"))
        f = SC.section_frame_along(SC.world_cut_axis("z", [5, 6, 7]), 4)
        self.assertTrue(np.allclose(f["origin"], [5, 6, 4]) and np.allclose(f["basisU"], [1, 0, 0]) and np.allclose(f["basisV"], [0, 1, 0]))
        s = SC.sketch_frame_on([3, 4, 20], [0, 0, 1])
        self.assertTrue(np.allclose(s["origin"], [0, 0, 20]) and np.allclose(s["basisU"], [1, 0, 0]))
        r = SC.radial_frame({"origin": [0, 0, 0], "dir": [0, 0, -1]}, 90)
        self.assertTrue(np.allclose(r["basisV"], [0, 0, 1]) and np.allclose(r["basisU"], [0, 1, 0]))
        self.assertTrue(np.allclose(np.cross(r["basisU"], r["basisV"]), r["normal"]))


def rounded_rect(w, h, r, step=0.1, noise=0.0, seed=1):
    def line(a, b):
        n = max(1, int(math.dist(a, b) / step))
        return [(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n) for i in range(n)]

    def arc(c, a0):
        n = max(1, int(r * math.pi / 2 / step))
        return [(c[0] + r * math.cos(math.radians(a0 + 90 * i / n)), c[1] + r * math.sin(math.radians(a0 + 90 * i / n))) for i in range(n)]

    p = line((w / 2, -h / 2 + r), (w / 2, h / 2 - r)) + (arc((w / 2 - r, h / 2 - r), 0) if r else [])
    p += line((w / 2 - r, h / 2), (-w / 2 + r, h / 2)) + (arc((-w / 2 + r, h / 2 - r), 90) if r else [])
    p += line((-w / 2, h / 2 - r), (-w / 2, -h / 2 + r)) + (arc((-w / 2 + r, -h / 2 + r), 180) if r else [])
    p += line((-w / 2 + r, -h / 2), (w / 2 - r, -h / 2)) + (arc((w / 2 - r, -h / 2 + r), 270) if r else [])
    P = np.array(p + [p[0]])
    P[:-1] += np.random.default_rng(seed).normal(0, noise, P[:-1].shape)
    P[-1] = P[0]
    return P


class Segment(unittest.TestCase):
    """plugins/reverse/core/segment.ts on clean and noisy outlines."""

    def test_rectangle(self):
        s = segment_chain(rounded_rect(40, 20, 0, noise=0.02))
        self.assertEqual([g["kind"] for g in s["segments"]], ["line"] * 4)
        self.assertEqual(sorted(round(g["fit"]["length"]) for g in s["segments"]), [20, 20, 40, 40])

    def test_rounded_rectangle(self):
        s = segment_chain(rounded_rect(40, 20, 3, noise=0.02))
        kinds = [g["kind"] for g in s["segments"]]
        self.assertEqual(sorted(kinds), ["arc"] * 4 + ["line"] * 4)
        for g in s["segments"]:
            if g["kind"] == "arc":
                self.assertAlmostEqual(g["fit"]["radius"], 3, delta=0.1)

    def test_circle(self):
        t = np.linspace(0, 2 * math.pi, 400)
        P = np.stack([12 * np.cos(t), 12 * np.sin(t)], axis=1)
        P[-1] = P[0]
        s = segment_chain(P)
        self.assertEqual(len(s["segments"]), 1)
        self.assertAlmostEqual(s["segments"][0]["fit"]["radius"], 12, places=3)
        curves, closed = profile_curves(s)
        self.assertTrue(closed)
        self.assertEqual(curves[0]["kind"], "circle")

    def test_profile_closes(self):
        s = segment_chain(rounded_rect(40, 20, 3, noise=0.01))
        curves, closed = profile_curves(s)
        self.assertTrue(closed)
        for i, c in enumerate(curves):
            nxt = curves[(i + 1) % len(curves)]
            self.assertLess(np.linalg.norm(c["t"] - nxt["s"]), 1e-9)

    def test_noisy_box_section(self):
        V, F = box_mesh(40, 20, 10, 16)
        V = V + np.random.default_rng(0).normal(0, 0.01, V.shape)
        P, off, _ = SC.slice_mesh(V, F, [0, 0, 0.3], [0, 0, 1])
        fr = SC.section_frame_along(SC.world_cut_axis("z"), 0.3)
        s = segment_chain(SC.project_cut(P, fr))
        self.assertEqual(sorted(round(g["fit"]["length"]) for g in s["segments"]), [20, 20, 40, 40])


@unittest.skipUnless(HAVE, "FreeCAD and Agent Link are not importable here")
class Tools(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from agentlink.tools import Session, build_server

        cls.dir = tempfile.mkdtemp()
        cls.session = Session(out_dir=cls.dir)
        cls.server = build_server(cls.session, lean=False)
        import Mesh

        m = Mesh.createBox(40, 20, 10)
        pts, tris = m.Topology
        V = np.array([[p.x, p.y, p.z] for p in pts])
        V, F = subdivide(V, np.array(tris), 1.5)
        V = V + np.random.default_rng(3).normal(0, 0.01, V.shape)
        cls.box = os.path.join(cls.dir, "box.stl")
        write_stl(cls.box, V, F)
        m = Mesh.createCylinder(8.0, 30.0, True, 0.5, 72)
        cls.cyl = os.path.join(cls.dir, "cyl.stl")
        m.write(cls.cyl)

    def call(self, name, args=None):
        r = self.server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args or {}}})["result"]
        return r.get("isError", False), json.loads(r["content"][0]["text"])

    def ok(self, name, args=None):
        err, o = self.call(name, args)
        self.assertFalse(err, f"{name}: {o}")
        return o

    def test_box_profile_to_pad(self):
        self.ok("scan_open", {"path": self.box, "discard": True})
        sec = self.ok("section_cut", {"across": "XY", "name": "Mid"})["section"]
        self.assertEqual(sec["chains"], 1)
        got = self.ok("section_get", {"section": "Mid"})
        b = got["chains"][0]["bounds"]
        self.assertAlmostEqual(b["max"][0] - b["min"][0], 40, delta=0.1)
        self.assertAlmostEqual(b["max"][1] - b["min"][1], 20, delta=0.1)
        self.assertTrue(got["chains"][0]["closed"])
        fit = self.ok("section_fit", {"section": sec["id"]})
        pieces = fit["chains"][0]["pieces"]
        self.assertEqual([p["kind"] for p in pieces], ["line"] * 4)
        self.assertEqual(sorted(round(p["length"]) for p in pieces), [20, 20, 40, 40])
        sk = self.ok("section_to_sketch", {"section": sec["id"], "name": "Profile"})
        # The next step names the Body and sketch as they came out (found
        # live: a new Body was "Body002", and pd_pad { body: "Body" } refused).
        self.assertEqual(sk["next"], f'pd_pad {{ body: "{sk["body"]}", sketch: "Profile", length }} stands it up.')
        self.assertEqual(sk["wires"], [{"closed": True, "edges": 4}])
        self.ok("pd_pad", {"body": sk["body"], "sketch": sk["sketch"], "length": 10})
        body = next(o for o in self.session.doc.Objects if o.Label == sk["body"])
        self.assertAlmostEqual(body.Shape.Volume, 40 * 20 * 10, delta=40 * 20 * 10 * 0.01)

    def test_cylinder_profile(self):
        self.ok("scan_open", {"path": self.cyl, "discard": True})
        info = self.ok("scan_info")["scan"]["box"]
        axis = int(np.argmax(info["size"]))
        plane = {0: "YZ", 1: "XZ", 2: "XY"}[axis]
        sec = self.ok("section_cut", {"across": plane})["section"]
        fit = self.ok("section_fit", {"section": sec["id"]})
        pieces = fit["chains"][0]["pieces"]
        self.assertEqual(len(pieces), 1)
        self.assertAlmostEqual(pieces[0]["radius"], 8, delta=0.05)
        sk = self.ok("section_to_sketch", {"section": sec["id"]})
        self.assertTrue(sk["wires"][0]["closed"])
        self.ok("pd_pad", {"body": sk["body"], "sketch": sk["sketch"], "length": 5})
        body = next(o for o in self.session.doc.Objects if o.Label == sk["body"])
        self.assertAlmostEqual(body.Shape.Volume, math.pi * 64 * 5, delta=math.pi * 64 * 5 * 0.02)

    def test_box_shadow_with_play(self):
        # The box seen from above with 1 mm of play: never inside it, between
        # the play and the play plus twice the tolerance outside; its four
        # sides as four lines; a sketch that pads.
        self.ok("scan_open", {"path": self.box, "discard": True})
        r = self.ok("section_cut", {"across": "XY", "kind": "shadow", "play": 1.0, "name": "Cutout"})
        print("\nshadow:", json.dumps(r))
        self.assertEqual(r["section"]["chains"], 1)
        self.assertEqual(r["section"]["kind"], "shadow")
        b = self.ok("section_get", {"section": "Cutout"})["chains"][0]["bounds"]
        w, h = b["max"][0] - b["min"][0], b["max"][1] - b["min"][1]
        self.assertGreater(w, 42 - 0.05)
        self.assertLess(w, 42 + 0.45)
        self.assertGreater(h, 22 - 0.05)
        self.assertLess(h, 22 + 0.45)
        fit = self.ok("section_fit", {"section": "Cutout"})
        kinds = [p["kind"] for p in fit["chains"][0]["pieces"]]
        if kinds != ["line"] * 4:
            got = self.ok("section_get", {"section": "Cutout", "limit": 60})
            print("shadow chain:", json.dumps(got["chains"][0]), json.dumps(fit["chains"][0]))
        self.assertEqual(kinds, ["line"] * 4)
        sk = self.ok("section_to_sketch", {"section": "Cutout", "name": "CutoutSketch"})
        self.assertTrue(sk["wires"][0]["closed"])
        self.ok("pd_pad", {"body": sk["body"], "sketch": sk["sketch"], "length": 5})

    def test_refusals(self):
        self.ok("scan_open", {"path": self.box, "discard": True})
        err, o = self.call("section_cut", {"across": "XY", "offset": 500})
        self.assertTrue(err)
        err, o = self.call("section_get", {"section": 99})
        self.assertTrue(err)
        self.assertEqual(o["error"]["code"], "not_found")


class Scatter(unittest.TestCase):
    """Found live (run 2, measure model call 53): section_fit answered
    "scatter 0.0469" for a chain of four exact straight lines, its points
    0.9375 mm apart. The figure was not measured: it is the least the fits
    take a chain's noise as, 5 % of the point spacing (viewChain's floor;
    0.05 x 0.9375 = 0.046875). The fits still work with it; the answer
    gives what was measured as scatter and the floor beside it."""

    def straight(self):
        # the live chain's kind: a 60 x 40 rectangle, a point every 0.9375 mm
        n = lambda L: int(round(L / 0.9375))  # noqa: E731
        side = lambda a, b, k: [np.array(a) + (np.array(b) - np.array(a)) * i / k for i in range(k)]  # noqa: E731
        c = [(0.0, 0.0), (60.0, 0.0), (60.0, 40.0), (0.0, 40.0)]
        pts = sum((side(c[i], c[(i + 1) % 4], n(60 if i % 2 == 0 else 40)) for i in range(4)), [])
        return np.array(pts + [pts[0]])

    def test_an_exact_chain_measures_no_scatter_and_the_floor_is_told_apart(self):
        from scanrulerfc import geom2d as G
        from scanrulerfc.handlers import sections as H

        chain = self.straight()
        measured, floor = G.chain_scatter(chain)
        self.assertLess(measured, 1e-9)
        self.assertAlmostEqual(floor, 0.046875, places=6)
        # what the fits work with is as it was (a port of viewChain: not changed)
        _pts, closed, spacing, used = G.view_chain(chain)
        self.assertTrue(closed)
        self.assertAlmostEqual(spacing, 0.9375, places=6)
        self.assertAlmostEqual(used, 0.046875, places=6)
        self.assertEqual(H.scatter_out(chain), {"scatter": 0.0, "scatterFloor": 0.0469})

    def test_a_noisy_chain_gives_its_own_scatter_alone(self):
        from scanrulerfc import geom2d as G
        from scanrulerfc.handlers import sections as H

        rng = np.random.default_rng(3)
        x = np.arange(0, 60, 0.5)
        chain = np.c_[x, rng.normal(0, 0.2, len(x))]
        measured, floor = G.chain_scatter(chain)
        self.assertGreater(measured, floor)
        self.assertAlmostEqual(measured, 0.2, delta=0.08)  # the noise put in
        self.assertEqual(H.scatter_out(chain), {"scatter": round(measured, 4)})
        self.assertAlmostEqual(G.view_chain(chain)[3], measured, places=12)

    def test_section_fit_answers_it_on_a_dense_block(self):
        # The tool itself, without FreeCAD: a densely meshed block cut at
        # mid height is four straight sides.
        import fakedoc
        from scanrulerfc import runner
        from scanrulerfc import scanstate as S

        fc = fakedoc.installed()
        fc.__enter__()
        self.addCleanup(fc.__exit__, None, None, None)
        V, F = box_mesh(60.0, 40.0, 20.0, n=40)
        ctx = runner.Context(doc=fakedoc.Doc("Block"), out_dir=tempfile.mkdtemp())
        run = runner.local(ctx=ctx)
        S.state(ctx)["scan"] = S.Scan("block.stl", np.asarray(V, float), np.asarray(F, np.int64))
        ok, out = run("section_cut", {"across": "XY", "name": "Mid"})
        self.assertTrue(ok, out)
        ok, out = run("section_fit", {"section": "Mid", "brief": True})
        self.assertTrue(ok, out)
        row = out["chains"][0]
        self.assertEqual([p["kind"] for p in row["pieces"]], ["line"] * 4)
        self.assertEqual(max(p["rms"] for p in row["pieces"]), 0.0)
        self.assertEqual(row["scatter"], 0.0)  # was the floor: 5 % of the spacing
        self.assertAlmostEqual(row["scatterFloor"], 0.05 * row["spacing"], delta=1e-4)
        self.assertAlmostEqual(row["tolerance"], 0.6 * row["spacing"], delta=1e-4)  # the fit's tolerance is as it was


def crossed_sheet(nx=40, nz=20, cell=0.5):
    """A flat sheet in the XZ plane, every cell cut by both its diagonals
    (a vertex in its middle): each grid vertex has eight edges, three to
    either side of a line of vertices. Centred on the origin."""
    V, at = [], {}
    for i in range(nx + 1):
        for k in range(nz + 1):
            at[i, k] = len(V)
            V.append([(i - nx / 2) * cell, 0.0, (k - nz / 2) * cell])
    F = []
    for i in range(nx):
        for k in range(nz):
            m = len(V)
            V.append([(i + 0.5 - nx / 2) * cell, 0.0, (k + 0.5 - nz / 2) * cell])
            a, b, c, d = at[i, k], at[i + 1, k], at[i + 1, k + 1], at[i, k + 1]
            F += [[a, b, m], [b, c, m], [c, d, m], [d, a, m]]
    return np.array(V, dtype=float), np.array(F, dtype=np.int64)


class APlaneWithinRoundingOfTheVertices(unittest.TestCase):
    """Found live (run 3, measure model call 55): section_fit on "Half",
    the cut through the fitted bore's axis, answered spacing 0.0, tolerance
    0.0 and scatterFloor 0.0 on chains of 303 and 464 points. The plane of
    a fitted axis passes the mesh's own vertices at about 1e-13 mm, not at
    0: slice_mesh took a vertex as on the plane only at exactly 0, so each
    of that vertex's edges was cut on its own — a cluster of points 1e-13
    mm apart for every vertex — and with more than half of a chain's gaps
    of that kind its median spacing read 0."""

    OFF = 3e-13

    def cut(self, x):
        V, F = crossed_sheet()
        P, off, _ = SC.slice_mesh(V, F, [x, 0, 0], [1, 0, 0], 1.0)
        self.assertEqual(len(off), 2)
        return P[:, [2, 1]]  # the chain along Z

    def test_the_cut_is_the_one_through_the_vertices(self):
        from scanrulerfc import geom2d as G

        exact, near = self.cut(0.0), self.cut(self.OFF)
        self.assertEqual(len(exact), 21)
        self.assertEqual(len(near), 21)  # 61 before: three points for every vertex
        self.assertGreater(float(np.hypot(*np.diff(near, axis=0).T).min()), 0.49)
        self.assertAlmostEqual(G.view_chain(near)[2], 0.5, places=9)
        # A plane that is really off the vertices is cut as before.
        self.assertEqual(len(self.cut(0.01)), 61)  # each vertex's three edges, 0.01 mm and more apart

    def test_the_snap_is_a_billionth_of_the_mesh_and_no_more(self):
        V, F = crossed_sheet()
        diag = float(np.linalg.norm(V.max(axis=0) - V.min(axis=0)))
        self.assertEqual(len(self.cut(0.5 * SC.PLANE_SNAP * diag)), 21)
        self.assertGreater(len(self.cut(50 * SC.PLANE_SNAP * diag)), 21)

    def test_a_chain_of_points_written_three_times_has_its_real_spacing(self):
        # What view_chain was handed before the cut was put right, and what
        # any chain with coinciding points still hands it.
        from scanrulerfc import geom2d as G
        from scanrulerfc.handlers import sections as H

        z = np.repeat(np.arange(0, 20.01, 0.5), 3) + np.tile([0.0, 1e-13, 2e-13], 41)
        chain = np.c_[z, np.zeros(len(z))]
        gaps = np.sort(np.abs(np.diff(z)))
        self.assertLess(gaps[len(gaps) >> 1], 1e-9)  # the median gap: what the spacing was read as
        _pts, _closed, spacing, used = G.view_chain(chain)
        self.assertAlmostEqual(spacing, 0.5, places=9)
        self.assertAlmostEqual(used, 0.025, places=9)
        cut = segment_chain(chain)
        self.assertAlmostEqual(cut["tolerance"], 0.3, places=9)  # 0.6 of the spacing; 0 before
        self.assertEqual(len(cut["segments"]), 1)
        self.assertEqual(H.scatter_out(chain), {"scatter": 0.0, "scatterFloor": 0.025})
        # Clusters a hundredth of a micrometre wide (the plane that far off
        # the vertices: more than the cut's own rounding takes in, and more
        # than a ten-millionth of the chain) are clusters still.
        z = np.repeat(np.arange(0, 20.01, 0.5), 4) + np.tile([0.0, 1e-5, 2e-5, 3e-5], 41)
        wide = np.c_[z, np.zeros(len(z))]
        self.assertGreater(1e-5, G.COINCIDENT * 20)
        self.assertAlmostEqual(G.view_chain(wide)[2], 0.5, places=3)
        self.assertAlmostEqual(segment_chain(wide)["tolerance"], 0.3, places=3)
        # A chain that really has short and long steps (1 to 50 here, as a
        # mesh's slivers beside its full edges) keeps its median.
        steps = np.tile([0.01, 0.5, 0.02, 0.4, 0.01], 20)
        mixed = np.c_[np.cumsum(steps), np.zeros(len(steps))]
        self.assertAlmostEqual(G.view_chain(mixed)[2], 0.02, places=9)
        # Evenly stepped chains read as they did.
        even = np.c_[np.arange(0, 20.01, 0.5), np.zeros(41)]
        self.assertAlmostEqual(G.view_chain(even)[2], 0.5, places=12)
        # Every point the same point: no spacing to read, 1 as before.
        self.assertEqual(G.view_chain(np.zeros((6, 2)))[2], 1.0)

    def test_a_floor_that_rounds_to_the_scatter_is_not_shown(self):
        from scanrulerfc.handlers import sections as H

        # 20 points 0.0004 mm apart: the floor is 0.00002, 0.0 as answered.
        tiny = np.c_[np.arange(20) * 0.0004, np.zeros(20)]
        self.assertEqual(H.scatter_out(tiny), {"scatter": 0.0})

    def test_section_fit_on_the_cut_through_a_row_of_vertices(self):
        import fakedoc
        from scanrulerfc import runner
        from scanrulerfc import scanstate as S

        fc = fakedoc.installed()
        fc.__enter__()
        self.addCleanup(fc.__exit__, None, None, None)
        V, F = crossed_sheet()
        ctx = runner.Context(doc=fakedoc.Doc("Sheet"), out_dir=tempfile.mkdtemp())
        run = runner.local(ctx=ctx)
        S.state(ctx)["scan"] = S.Scan("sheet.stl", V, F)
        ok, out = run("section_cut", {"across": "YZ", "offset": self.OFF, "name": "Half"})
        self.assertTrue(ok, out)
        ok, out = run("section_fit", {"section": "Half", "brief": True})
        self.assertTrue(ok, out)
        row = out["chains"][0]
        self.assertEqual(row["points"], 21)
        self.assertEqual(row["spacing"], 0.5)  # 0.0 live
        self.assertEqual(row["tolerance"], 0.3)  # 0.0 live
        self.assertEqual((row["scatter"], row["scatterFloor"]), (0.0, 0.025))
        self.assertEqual([p["kind"] for p in row["pieces"]], ["line"])


if __name__ == "__main__":
    unittest.main()
