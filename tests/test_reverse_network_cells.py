# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/tests/reNetworkCells.test.ts
# SPDX-License-Identifier: AGPL-3.0-only
#
# A patch network's cells and their map onto the square: a 2 x 2 network on
# a sheet reads into four four-sided cells and nothing else closed; a curve
# taken out opens a cell, named where; a strip round 270 degrees of a
# cylinder (one cell that folds back over itself) maps one-to-one, as a
# saddle does; a scan hole inside a cell is closed by a fan; a cell of two
# sides and one of seven are refused by name.
import math
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

from network_meshes import grid_network, grid_scan, network  # noqa: E402
from scanrulerfc.reverse.network import trace_network  # noqa: E402
from scanrulerfc.reverse.network_cells import read_cells  # noqa: E402
from scanrulerfc.reverse.network_map import cell_mesh, map_cell  # noqa: E402
from scanrulerfc.reverse.scan_path import ScanPaths  # noqa: E402


def cells_of(scan, f):
    t = trace_network(scan, f["nodes"], f["curves"])
    return t, read_cells(scan, t["nodes"], t["curves"], [c["seed"] for c in f["cells"]])


def mapped(scan, traced, cell):
    if cell["status"] != "ok":
        raise AssertionError(cell["message"])
    at = {n["id"]: n["at"] for n in traced["nodes"]}
    mesh = cell_mesh(scan, cell["triangles"], cell["holes"], [at[c] for c in cell["corners"]])
    if isinstance(mesh, str):
        raise AssertionError(mesh)
    return map_cell(mesh)


def sheet(u, v):
    return [100 * u, 80 * v, 3 * math.sin(2 * u) * math.cos(v)]


class PatchNetworkCells(unittest.TestCase):
    def test_reads_a_2x2_network_on_a_sheet_into_four_four_sided_cells(self):
        scan = ScanPaths(*grid_scan(120, 96, sheet))
        f = grid_network(1, 2, 2, sheet, 1, [0.15, 0.85, 0.15, 0.85])
        _, cells = cells_of(scan, f)
        self.assertEqual([c["status"] for c in cells["cells"]], ["ok"] * 4)
        for c in cells["cells"]:
            self.assertEqual(len(c["sides"]), 4)
        counts = [len(c["triangles"]) for c in cells["cells"]]
        for n in counts:
            self.assertLess(abs(n / counts[0] - 1), 0.05)
        self.assertEqual(cells["unfilled"], [])

    def test_offers_the_cells_no_seed_fills_and_names_where_a_cell_is_open(self):
        scan = ScanPaths(*grid_scan(120, 96, sheet))
        f = grid_network(1, 2, 2, sheet, 0, [0.15, 0.85, 0.15, 0.85])
        two = dict(f, cells=f["cells"][:2])
        self.assertEqual(len(cells_of(scan, two)[1]["unfilled"]), 2)
        opened = dict(f, curves=[c for c in f["curves"] if not (c["from"] == 1 and c["to"] == 4)])
        reading = cells_of(scan, opened)[1]["cells"][0]
        self.assertEqual(reading["status"], "refused")
        self.assertRegex(reading["message"], r"^not closed — open at \(")

    def test_maps_a_strip_round_270_degrees_of_a_cylinder_one_to_one(self):
        r = 20
        scan = ScanPaths(*grid_scan(180, 40, lambda u, v: [r * math.cos(2 * math.pi * u), r * math.sin(2 * math.pi * u), 40 * v], wrap=True, noise=0.01))

        def on(deg, z):
            return [r * math.cos((deg * math.pi) / 180), r * math.sin((deg * math.pi) / 180), z]

        f = network(2, {1: on(0, 5), 2: on(270, 5), 3: on(270, 35), 4: on(0, 35)},
                    [{"from": 1, "to": 2, "via": [on(90, 5), on(180, 5)]}, {"from": 2, "to": 3}, {"from": 3, "to": 4, "via": [on(180, 35), on(90, 35)]}, {"from": 4, "to": 1}],
                    [on(135, 20)])
        traced, cells = cells_of(scan, f)
        cell = cells["cells"][0]
        self.assertEqual(cell["status"], "ok")
        mp = mapped(scan, traced, cell)
        self.assertNotIsInstance(mp, str)
        mesh, uv = mp["mesh"], mp["uv"]
        symmetries = [lambda a, b: (a, b), lambda a, b: (1 - a, b), lambda a, b: (a, 1 - b), lambda a, b: (1 - a, 1 - b),
                      lambda a, b: (b, a), lambda a, b: (1 - b, a), lambda a, b: (b, 1 - a), lambda a, b: (1 - b, 1 - a)]
        P = mesh["positions"].reshape(-1, 3)
        deg = [(math.atan2(p[1], p[0]) * 180) / math.pi for p in P]
        deg = [d + 360 if d < -45 else d for d in deg]
        worst = []
        for s in symmetries:
            w = 0.0
            for i in range(mesh["scanVertex"].shape[0]):
                a, b = s(uv[i * 2], uv[i * 2 + 1])
                w = max(w, abs(a - deg[i] / 270), abs(b - (P[i][2] - 5) / 30))
            worst.append(w)
        self.assertLess(min(worst), 0.04)

    def test_maps_a_saddle_and_closes_a_scan_hole_inside_a_cell_with_a_fan(self):
        def saddle(u, v):
            return [60 * u - 30, 60 * v - 30, ((60 * u - 30) ** 2 - (60 * v - 30) ** 2) / 60]

        scan = ScanPaths(*grid_scan(90, 90, saddle, hole=lambda u, v: math.hypot(u - 0.5, v - 0.5) < 0.08))
        f = grid_network(3, 1, 1, saddle, 1, [0.2, 0.8, 0.2, 0.8])
        f["cells"] = [{"seed": saddle(0.3, 0.3)}]
        traced, cells = cells_of(scan, f)
        cell = cells["cells"][0]
        self.assertEqual(cell["status"], "ok")
        self.assertEqual(len(cell["holes"]), 1)
        mp = mapped(scan, traced, cell)
        self.assertNotIsInstance(mp, str)
        middle = list(mp["mesh"]["scanVertex"]).index(-1)
        self.assertGreater(middle, 0)
        self.assertAlmostEqual(mp["uv"][middle * 2], 0.5, delta=0.05)
        self.assertAlmostEqual(mp["uv"][middle * 2 + 1], 0.5, delta=0.05)

    def test_refuses_a_cell_of_two_sides_and_one_of_seven_by_name(self):
        scan = ScanPaths(*grid_scan(100, 100, lambda u, v: [100 * u, 100 * v, 0]))
        lens = network(4, {1: [30, 50, 0], 2: [70, 50, 0]}, [{"from": 1, "to": 2, "via": [[50, 65, 0]]}, {"from": 2, "to": 1, "via": [[50, 35, 0]]}], [[50, 50, 0]])
        two = cells_of(scan, lens)[1]["cells"][0]
        self.assertEqual(two["status"] == "refused" and two["message"], "two sides")
        corners = {k + 1: [50 + 30 * math.cos((2 * math.pi * k) / 7), 50 + 30 * math.sin((2 * math.pi * k) / 7), 0] for k in range(7)}
        seven = network(5, corners, [{"from": k + 1, "to": ((k + 1) % 7) + 1} for k in range(7)], [[50, 50, 0]])
        reading = cells_of(scan, seven)[1]["cells"][0]
        self.assertEqual(reading["status"] == "refused" and reading["message"], "7 sides — split it with a curve")


if __name__ == "__main__":
    unittest.main()
