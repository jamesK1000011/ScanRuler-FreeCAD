# SPDX-License-Identifier: AGPL-3.0-only
# A diagnostic, not a check: why a patch network's seams do not sew on some
# FreeCAD (1.1.3 on macOS left seams open at gaps of 0.1-0.6 µm, under the
# 1e-3 mm sewing tolerance). It builds the two sphere networks of
# test_reverse_scan_builds.py (ported from ScanRuler by Stefan Hermann /
# CNC Kitchen), makes their patch faces as network_body does, and prints to
# stdout what each way of sewing them leaves open, and for each seam left
# open its two patch edges side by side. It always passes; skipped without
# FreeCAD. The output is kept short (about 4 kB) for a log.
import math
import os
import sys
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
if os.environ.get("FREECAD_LIB"):
    sys.path.append(os.environ["FREECAD_LIB"])
try:
    import FreeCAD
    import Part

    HAVE_FC = True
except ImportError:
    HAVE_FC = False

LIMIT = 4000
TOLS = (1e-6, 1e-3, 1e-1)


def _f(x, p=3):
    return f"{x:.{p}g}"


class Out:
    def __init__(self):
        self.lines = []

    def __call__(self, *a):
        self.lines.append(" ".join(str(x) for x in a))

    def flush(self):
        text = "\n".join(self.lines)
        if len(text) > LIMIT:
            text = text[:LIMIT - 20] + "\n…(cut)"
        print("\n=== SEW DIAG ===\n" + text + "\n=== END SEW DIAG ===", flush=True)


def _free(shape):
    """(free edges, edges shared by more than two faces) counted by isSame."""
    seen = []
    for f in shape.Faces:
        for e in f.Edges:
            if getattr(e, "Degenerated", False):
                continue
            for item in seen:
                if item[0].isSame(e):
                    item[1] += 1
                    break
            else:
                seen.append([e, 1])
    return sum(1 for x in seen if x[1] < 2), sum(1 for x in seen if x[1] > 2)


def _summary(shape):
    try:
        valid = shape.isValid()
    except Exception as e:  # noqa: BLE001
        valid = f"err {e}"
    free, multi = _free(shape)
    return f"{shape.ShapeType} shells={len(shape.Shells)} faces={len(shape.Faces)} free={free} multi={multi} valid={valid}"


def _ancestor_counts(shape):
    """Edges by how many faces ancestorsOfType gives, and by hash map."""
    by = {}
    for e in shape.Edges:
        if getattr(e, "Degenerated", False):
            continue
        try:
            n = len(shape.ancestorsOfType(e, Part.Face))
        except Exception:  # noqa: BLE001
            n = -1
        by[n] = by.get(n, 0) + 1
    return by


def _edge_near(face, q):
    best = None
    v = Part.Vertex(FreeCAD.Vector(*q))
    for e in face.Edges:
        if getattr(e, "Degenerated", False):
            continue
        d = e.distToShape(v)[0]
        if best is None or d < best[0]:
            best = (d, e)
    return best[1] if best else None


def _apart(a, b, n=33):
    """The most two edges run apart, sampled along the first."""
    worst = 0.0
    for i in range(n):
        p = a.valueAt(a.FirstParameter + (a.LastParameter - a.FirstParameter) * i / (n - 1))
        worst = max(worst, b.distToShape(Part.Vertex(p))[0])
    return worst


def _ends(e):
    return [e.Vertexes[0].Point, e.Vertexes[-1].Point]


@unittest.skipUnless(HAVE_FC, "a diagnostic for real FreeCAD")
class SewDiag(unittest.TestCase):
    def test_report(self):
        out = Out()
        try:
            self._report(out)
        except Exception as e:  # noqa: BLE001 — it reports, never fails
            import traceback

            out("EXCEPTION", repr(e))
            out(traceback.format_exc()[-800:])
        out.flush()

    def _report(self, out):
        from network_meshes import grid_network, sphere_scan
        from test_reverse_scan_builds import R, closed_network, on_sphere

        from scanrulerfc.reverse.build import Builder
        from scanrulerfc.reverse.kernel import Kernel
        from scanrulerfc.reverse.network_body import GRID_PER_SPAN, SEW_TOLERANCE, patch_grid, sew_tolerances, side_sampler
        from scanrulerfc.reverse.network_spline import curve_point

        out("FreeCAD", ".".join(FreeCAD.Version()[:4]), "OCC", getattr(Part, "OCC_VERSION", "?"))
        out("sewShape doc:", (Part.Shape.sewShape.__doc__ or "").strip().replace("\n", " ")[:160])
        for label, net in (("2x2", grid_network(1, 2, 2, on_sphere, 1)), ("closed", closed_network())):
            k = Kernel()
            b = Builder(k)
            b.set_scan(*sphere_scan(R, 0.02, 6))
            reading = b.network_reading(net)
            if "message" in reading:
                out(label, "no reading:", reading["message"])
                continue
            fit = reading["fit"]
            sampler = side_sampler(fit)
            faces = [k.surface_through(**{kk: g[kk] for kk in ("points", "rows", "cols")}) for g in
                     (patch_grid(p, GRID_PER_SPAN, sampler(p)) for p in fit["patches"])]
            gaps = []
            for s in fit["shared"]:
                f = fit["curves"][s["curve"]]
                g = 0.0
                for i in range(8):
                    q = curve_point(f["poles"], f["spans"], (i + 0.5) / 8)
                    g = max(g, k.distance_to_point(faces[s["patches"][0]], q) + k.distance_to_point(faces[s["patches"][1]], q))
                gaps.append(max(g, s["gap"]))
            first = max(SEW_TOLERANCE, 2 * max(gaps or [0]))
            diag = Part.Compound(faces).BoundBox.DiagonalLength
            out(f"[{label}] patches={len(faces)} seams={len(fit['shared'])} worstGap={_f(max(gaps or [0]))} first={_f(first)} ladder={[_f(t) for t in sew_tolerances(first, diag)]}")
            out(" face tol max:", _f(max(e.Tolerance for f in faces for e in f.Edges)), "vertex tol max:", _f(max(v.Tolerance for f in faces for v in f.Vertexes)))
            # Each way of sewing, at each tolerance.
            for t in TOLS:
                c = Part.Compound(faces)
                c.sewShape(t)
                out(f" sewShape({_f(t)}):", _summary(c))
            try:
                c = Part.Compound(faces)
                c.sewShape(1e-3)
                out(" ancestors per edge after sew(1e-3):", _ancestor_counts(c), "open_edges:", len(k.open_edges(c)))
            except Exception as e:  # noqa: BLE001
                out(" ancestors: err", e)
            try:
                sh = Part.Shell(faces)
                sh2 = sh.copy()
                sh2.fix(1e-3, 1e-3, 1e-3)
                out(" Shell(faces):", _summary(sh), "| fixed:", _summary(sh2))
            except Exception as e:  # noqa: BLE001
                out(" Shell(faces): err", e)
            try:
                fixed = []
                for f in faces:
                    g = f.copy()
                    g.fix(1e-3, 1e-3, 1e-3)
                    fixed.append(g)
                c = Part.Compound(fixed)
                c.sewShape(1e-3)
                out(" faces fixed then sewShape(1e-3):", _summary(c))
            except Exception as e:  # noqa: BLE001
                out(" fix then sew: err", e)
            try:
                from Part import ShapeFix  # noqa: F401

                for cls, meth in (("FaceConnect", "build"), ("FaceConnect", "add"), ("ShapeTolerance", "setTolerance")):
                    fn = getattr(getattr(ShapeFix, cls, None), meth, None)
                    out(f" ShapeFix.{cls}.{meth}:", ((fn.__doc__ or "").strip().replace(chr(10), " ")[:110]) if fn else "absent")
            except Exception as e:  # noqa: BLE001
                out(" Part.ShapeFix: none", type(e).__name__)
            # The kernel's own sewing, as network_body calls it: the route used.
            for t in (first, 1e-3):
                o = k.occt
                try:
                    got = o.sew(faces, t)
                    out(f" kernel sew({_f(t)}): route={o.last_sew.get('route')} {_summary(got)} tried={o.last_sew['tried']}"[:400])
                except Exception as e:  # noqa: BLE001
                    out(f" kernel sew({_f(t)}): err {e} tried={getattr(o, 'last_sew', {}).get('tried')}"[:400])
            # The seams left open by the sewing network_body does, side by side.
            c = Part.Compound(faces)
            c.sewShape(first)
            free = set()
            for f in c.Faces:
                for e in f.Edges:
                    if not getattr(e, "Degenerated", False) and len(c.ancestorsOfType(e, Part.Face)) < 2:
                        free.add(tuple(round(x, 3) for x in e.valueAt((e.FirstParameter + e.LastParameter) / 2)))
            shown = 0
            for n, s in enumerate(fit["shared"]):
                f = fit["curves"][s["curve"]]
                mid = curve_point(f["poles"], f["spans"], 0.5)
                a = _edge_near(faces[s["patches"][0]], mid)
                bb = _edge_near(faces[s["patches"][1]], mid)
                if a is None or bb is None:
                    continue
                open_here = any(math.dist(m, mid) < 1.0 for m in free)
                if not open_here or shown >= 3:
                    continue
                shown += 1
                ea, eb = _ends(a), _ends(bb)
                d_same = max((ea[0] - eb[0]).Length, (ea[1] - eb[1]).Length)
                d_cross = max((ea[0] - eb[1]).Length, (ea[1] - eb[0]).Length)
                out(f" seam curve {s['curve']} (patches {s['patches'][0]},{s['patches'][1]}) gap={_f(gaps[n])}:")
                out(f"  len {_f(a.Length, 8)} / {_f(bb.Length, 8)}; ends apart {_f(min(d_same, d_cross))}; edges apart {_f(_apart(a, bb))}; edge tol {_f(a.Tolerance)}/{_f(bb.Tolerance)}")
                out(f"  curves {type(a.Curve).__name__}/{type(bb.Curve).__name__} poles {getattr(a.Curve, 'NbPoles', '?')}/{getattr(bb.Curve, 'NbPoles', '?')}")
            out(f" open after sewShape(first): {len(free)} edge(s); shown {shown}")


if __name__ == "__main__":
    unittest.main()
