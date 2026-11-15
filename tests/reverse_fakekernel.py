# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/core/kernel.ts (a stand-in for the ReKernel the Builder calls)
# SPDX-License-Identifier: AGPL-3.0-only
# A stand-in for the kernel (scanrulerfc/reverse/kernel.py) that knows boxes
# and nothing else, so the Builder's own decisions — the guard and its
# retries, islands, the prefix cache, the failure flow — are tested where
# FreeCAD is not. A shape is pieces, each an axis-aligned box with its
# faces' hashes; volumes are exact for a box and for two boxes overlapping.
# `script` bends one operation to test a decision: {"fuse": fn(kernel,
# volume) -> volume}, applied to every fuse's result.
import itertools

_ids = itertools.count(1000)


def _vol(b):
    return max(0.0, b[1][0] - b[0][0]) * max(0.0, b[1][1] - b[0][1]) * max(0.0, b[1][2] - b[0][2])


def _overlap(a, b):
    lo = [max(a[0][i], b[0][i]) for i in range(3)]
    hi = [min(a[1][i], b[1][i]) for i in range(3)]
    return (lo, hi) if all(hi[i] > lo[i] for i in range(3)) else None


class Piece:
    def __init__(self, box, volume=None, faces=None):
        self.box = box
        self.volume = _vol(box) if volume is None else volume
        self.faces = faces if faces is not None else [next(_ids) for _ in range(6)]


class Shape:
    def __init__(self, pieces):
        self.pieces = pieces


class Sheet:
    """A flat sheet across space: the plane coordinate `axis` = `at`."""

    def __init__(self, axis, at):
        self.axis, self.at = axis, at
        self.pieces = []
        self.faces = [next(_ids)]


class FakeKernel:
    coarse_fuzz = 1e-3

    def __init__(self, script=None):
        self.script = script or {}
        self.fuzz = 0.0
        self.splitting = False
        self.calls = []

    # ---- the switches
    def keeping_splits(self, fn):
        was, self.splitting = self.splitting, True
        try:
            return fn()
        finally:
            self.splitting = was

    def fuzzy_booleans(self, fn, mm=1e-4):
        was, self.fuzz = self.fuzz, mm
        try:
            return fn()
        finally:
            self.fuzz = was

    # ---- making
    def face(self, profile):
        pts = [p["a"] for p in profile["outer"]]
        return {"lo": [min(p[0] for p in pts), min(p[1] for p in pts)], "hi": [max(p[0] for p in pts), max(p[1] for p in pts)], "z": pts[0][2]}

    def extrude(self, face, d, frm, to, draft_deg=0):
        self.calls.append("extrude")
        z0, lo, hi = face["z"], min(frm, to), max(frm, to)
        s = 1 if d[2] > 0 else -1
        a, b = z0 + s * lo, z0 + s * hi
        return Shape([Piece(([face["lo"][0], face["lo"][1], min(a, b)], [face["hi"][0], face["hi"][1], max(a, b)]))])

    def fuse_all(self, shapes):
        acc = shapes[0]
        for s in shapes[1:]:
            acc = self.fuse_tracked(acc, s)["shape"]
        return acc

    def sheet(self, pieces, d, frm, to):
        """A line drawn across the sketch swept along Z: the plane it stands
        in (x = a line's x, or y = its y)."""
        a, b = pieces[0]["a"], pieces[0]["b"]
        return Sheet(0, a[0]) if abs(a[0] - b[0]) < 1e-9 else Sheet(1, a[1])

    def split(self, shape, tools):
        self.calls.append("split")
        pieces = list(shape.pieces)
        for t in tools:
            out = []
            for p in pieces:
                ax, at = t.axis, t.at
                if p.box[0][ax] < at < p.box[1][ax]:
                    hi1, lo2 = list(p.box[1]), list(p.box[0])
                    hi1[ax] = lo2[ax] = at
                    out += [Piece((list(p.box[0]), hi1)), Piece((lo2, list(p.box[1])))]
                else:
                    out.append(p)
            pieces = out
        return [Shape([p]) for p in pieces]

    def traced_history(self, before, after):
        return {}

    def thicken_tracked(self, sheet, thickness, way):
        lo, hi = [0.0, 0.0, 0.0], [10.0, 10.0, 10.0]
        a, b = (sheet.at, sheet.at + thickness) if way == "out" else (sheet.at - thickness, sheet.at) if way == "in" else (sheet.at - thickness / 2, sheet.at + thickness / 2)
        lo[sheet.axis], hi[sheet.axis] = a, b
        piece = Piece((lo, hi))
        return {"shape": Shape([piece]), "history": {}, "skin": {piece.faces[0]: sheet.faces[0]}, "wall": {"least": thickness, "at": [0, 0, 0], "points": 48}}

    # ---- booleans
    def fuse_tracked(self, a, b):
        self.calls.append("fuse")
        pa, pb = a.pieces[0], b.pieces[0]
        ov = _overlap(pa.box, pb.box)
        v = pa.volume + pb.volume - (_vol(ov) if ov else 0)
        if "fuse" in self.script:
            v = self.script["fuse"](self, v)
        lo = [min(pa.box[0][i], pb.box[0][i]) for i in range(3)]
        hi = [max(pa.box[1][i], pb.box[1][i]) for i in range(3)]
        touching = ov is not None or all(pa.box[0][i] <= pb.box[1][i] and pb.box[0][i] <= pa.box[1][i] for i in range(3))
        if not touching:
            return {"shape": Shape([pa, pb]), "history": {}}
        return {"shape": Shape([Piece((lo, hi), v, pa.faces + pb.faces)]), "history": {}}

    def cut_tracked(self, a, b):
        self.calls.append("cut")
        out = []
        for p in a.pieces:
            ov = _overlap(p.box, b.pieces[0].box)
            if not ov:
                out.append(p)
                continue
            # A slab right across the piece in two directions parts it.
            across = [i for i in range(3) if ov[0][i] <= p.box[0][i] and ov[1][i] >= p.box[1][i]]
            if len(across) == 2:
                ax = ({0, 1, 2} - set(across)).pop()
                if ov[0][ax] > p.box[0][ax] and ov[1][ax] < p.box[1][ax]:
                    lo1, hi1 = list(p.box[0]), list(p.box[1])
                    hi1[ax] = ov[0][ax]
                    lo2, hi2 = list(p.box[0]), list(p.box[1])
                    lo2[ax] = ov[1][ax]
                    out += [Piece((lo1, hi1), None, p.faces[:3] + [next(_ids)]), Piece((lo2, hi2), None, p.faces[3:] + [next(_ids)])]
                    continue
            out.append(Piece(p.box, p.volume - _vol(ov), p.faces + [next(_ids)]))
        return {"shape": Shape(out), "history": {}}

    def common_tracked(self, a, b):
        ov = _overlap(a.pieces[0].box, b.pieces[0].box)
        return {"shape": Shape([Piece(ov)] if ov else []), "history": {}}

    def cut(self, a, b):
        return self.cut_tracked(a, b)["shape"]

    def half_space(self, origin, normal, around=None):
        big = 1e6
        lo, hi = [-big] * 3, [big] * 3
        for i in range(3):
            if normal[i] > 0.5:
                lo[i] = origin[i]
            elif normal[i] < -0.5:
                hi[i] = origin[i]
        return Shape([Piece((lo, hi))])

    # ---- reading
    def is_closed_solid(self, s):
        return bool(s.pieces) and all(p.volume > 1e-9 for p in s.pieces)

    def is_valid(self, s):
        return True

    def is_surface(self, s):
        return isinstance(s, Sheet)

    def solid_count(self, s):
        return len(s.pieces)

    def solids(self, s):
        return [Shape([p]) for p in s.pieces]

    def volume(self, s):
        return sum(p.volume for p in s.pieces)

    def face_hashes(self, s):
        return list(s.faces) if isinstance(s, Sheet) else [h for p in s.pieces for h in p.faces]

    def face_count(self, s):
        return len(self.face_hashes(s))

    def bounds(self, s):
        if isinstance(s, Sheet):
            lo, hi = [-1e3] * 3, [1e3] * 3
            lo[s.axis] = hi[s.axis] = s.at
            return {"min": lo, "max": hi}
        return {"min": [min(p.box[0][i] for p in s.pieces) for i in range(3)], "max": [max(p.box[1][i] for p in s.pieces) for i in range(3)]}

    extent = bounds

    def surface_area(self, s):
        return 0.0

    def centroid(self, s):
        b = self.bounds(s)
        return [(b["min"][i] + b["max"][i]) / 2 for i in range(3)]

    def contains_point(self, s, p, tolerance=1e-6):
        return any(all(q.box[0][i] - tolerance <= p[i] <= q.box[1][i] + tolerance for i in range(3)) for q in s.pieces)

    def mesh(self, s, deflection, angle=0.15):
        # One triangle in each piece's top face, a point on its surface.
        positions, indices = [], []
        for n, p in enumerate(s.pieces):
            (x0, y0, _), (x1, y1, z1) = p.box
            positions += [x0, y0, z1, x1, y0, z1, x0, y1, z1]
            indices += [3 * n, 3 * n + 1, 3 * n + 2]
        return {"positions": positions, "indices": indices}

    def faces(self, s):
        return self.describe_faces(s)

    def describe_faces(self, s):
        out = []
        for p in s.pieces:
            c = [(p.box[0][i] + p.box[1][i]) / 2 for i in range(3)]
            for n, h in enumerate(p.faces):
                d = [0, 0, 0]
                d[n % 3] = 1 if n < 3 else -1
                out.append({"hash": h, "kind": "plane", "centroid": c, "dir": d, "area": 1.0})
        return out

    def describe_edges(self, s, deflection):
        return []
