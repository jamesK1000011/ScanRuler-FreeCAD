# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/core/build.ts (sheet, loft, sweep, thicken, split, surface, trim and network plays), diagnoseThicken.ts (wallSaid)
# SPDX-License-Identifier: AGPL-3.0-only
#
# The Builder's plays of build steps 10 and 11 of the port: the steps that
# make or take sheets, and the ones read off the scan.
#
#   sheet    a sketch's pieces swept along its normal: a surface body
#   loft     a solid through sketches' profiles, ruled or smooth; a smooth
#            one whose skin crosses itself is refused (loft_fold.py)
#   sweep    a profile swept along a path
#   thicken  a sheet made a solid: out, in or both ways; the skin keeps
#            the sheet's makers and the wall along its edge is said
#   split    a solid cut by sheets or solids: the largest, the smallest,
#            what lies on the scan, or what lies between the sheets; a
#            fitted surface short of the body is carried on to reach it
#   surface  a surface fitted through a region of the scan — freeform, or
#            a plane or cylinder held to the references
#   trim     a box round the scan cut by every tool, the faces on the scan
#            sewn: a solid when they close, a surface body otherwise
#   network  a patch network read off the scan and made a body
#
# Left out, refusing in words: a split within its sheets' regions (the
# region outlines of surfaceRegion.ts are not ported), a split or a Combine
# of a sheet (sheetPieces, sewSheet), the fold check before a thicken
# (faceOffsetLimits: the kernel's own refusal stands for it), the off-scan
# reports of a split and of a surface past its region (advice only).
#
# SheetPlays is a mixin of build.Builder: it calls the Builder's own
# bodies, picks and placement. Imports nothing from FreeCAD.

import math

from .buildtypes import SPLIT_SAMPLES, SURFACE_TRIANGLES, StepFailed, diagonal_of, halton, mesh_deflection, plain
from .loops import rectangle_loop
from .vec import add_scaled, cross, dot, length, normalize, sub

MEET_MM = 1e-3
MEET_SAMPLES = 64
WALL_SHORT = 0.02
LATER_SPLIT_WITHIN = "A split within its sheets' regions is not built in this FreeCAD port: the region outlines it cuts along are not ported. Split by the whole sheet, or trim the sheet first."
LATER_SHEET_SPLIT = "Splitting a sheet is not built in this FreeCAD port (the kernel's sheet pieces are not ported): split a solid with it, or Thicken it first."


def _r2(v):
    from ._js import num_str

    return num_str(round(v * 100) / 100)


def wall_said(wall, thickness):
    """diagnoseThicken wallSaid: the wall along a thickened sheet's edge, a
    note when it holds the thickness, a warning when it falls short."""
    if wall["least"] >= thickness * (1 - WALL_SHORT):
        return {"note": f"The wall along the sheet's edge is {_r2(wall['least'])} mm at its thinnest, measured at {wall['points']} points."}
    at = "(" + ", ".join(_r2(v) for v in wall["at"]) + ")"
    return {"warning": f"The wall along the sheet's edge comes to {_r2(wall['least'])} mm at {at}, under the {_r2(thickness)} mm asked (measured at {wall['points']} points): the kernel cut the wall short there, or the far skin comes back near it."}


def thicken_way(side):
    return "along its normal" if side == "out" else "against its normal" if side == "in" else "both ways"


class ScanSurface:
    """The scan as the split, the surface, the trim and the network read
    it: its points and triangles, and closest-point queries (the
    deviation's NominalSurface, made when first asked)."""

    def __init__(self, V, F):
        import numpy as np

        self.V = np.asarray(V, dtype=float).reshape(-1, 3)
        self.F = np.asarray(F, dtype=np.int64).reshape(-1, 3)
        self._near = None
        self._paths = None

    @property
    def near(self):
        if self._near is None:
            from ..dev_surface import NominalSurface

            self._near = NominalSurface(self.V, self.F)
        return self._near

    @property
    def paths(self):
        if self._paths is None:
            from .scan_path import ScanPaths

            self._paths = ScanPaths(self.V.reshape(-1), self.F.reshape(-1))
        return self._paths

    def within(self, points, tolerance):
        """Which of the points lie within the tolerance of the scan."""
        import numpy as np

        if not len(points):
            return np.zeros(0, dtype=bool)
        hit = self.near.closest(np.asarray(points, dtype=float).reshape(-1, 3), tolerance)
        return np.asarray(hit.face) >= 0


class SheetPlays:
    """build.ts's plays of the sheets and the scan's features."""

    def _later_init(self):
        self.scan = None
        self.fitted = {}
        self.smooth_lofts = set()

    def set_scan(self, V=None, F=None):
        """build.ts setScan: the scan the split, the surface, the trim and
        the network read — None for none. Steps built against another scan
        may not come out the same, so the kept states go."""
        self.scan = ScanSurface(V, F) if V is not None and F is not None and len(F) else None
        self._tree = {"children": {}, "state": None}
        self._states = 0

    # ---- reading against the scan
    def on_scan_share(self, shape, tolerance, leave_out=None):
        """build.ts onScanShare: the share of a shape's surface within the
        tolerance of the scan, by area — about SPLIT_SAMPLES Halton points
        spread over a coarse mesh of it. None with no scan."""
        if not self.scan:
            return None
        k = self.kernel
        m = k.mesh(shape, mesh_deflection(diagonal_of(k, shape)) * 4)
        p, ix = m["positions"], m["indices"]
        tris = len(ix) // 3
        every = max(1, tris // SPLIT_SAMPLES)
        areas = {}
        whole = 0.0
        for t in range(0, tris, every):
            a, b, c = ix[t * 3] * 3, ix[t * 3 + 1] * 3, ix[t * 3 + 2] * 3
            n = cross([p[b] - p[a], p[b + 1] - p[a + 1], p[b + 2] - p[a + 2]], [p[c] - p[a], p[c + 1] - p[a + 1], p[c + 2] - p[a + 2]])
            areas[t] = length(n) / 2
            whole += areas[t]
        if not whole > 0:
            return 0.0
        samples = []
        for t in range(0, tris, every):
            if not areas[t] > 0:
                continue
            a, b, c = ix[t * 3] * 3, ix[t * 3 + 1] * 3, ix[t * 3 + 2] * 3
            count = max(1, round(SPLIT_SAMPLES * areas[t] / whole))
            for i in range(count):
                u = 1 / 3 if count == 1 else halton(i + 1, 2)
                v = 1 / 3 if count == 1 else halton(i + 1, 3)
                if u + v > 1:
                    u, v = 1 - u, 1 - v
                w = 1 - u - v
                q = [w * p[a + j] + u * p[b + j] + v * p[c + j] for j in range(3)]
                samples.append((t, count, q, bool(leave_out and leave_out(q))))
        taken = [s for s in samples if not s[3]]
        hits = self.scan.within([s[2] for s in taken], tolerance)
        on = read = 0.0
        for (t, count, _, _), hit in zip(taken, hits):
            on += areas[t] * (1 if hit else 0) / count
            read += areas[t] / count
        return on / read if read > 0 else 0.0

    # ---- the plays
    def play_later(self, step, fail, results):
        """A step of build steps 10 and 11 played; False when the kind is
        not one of them."""
        k = self.kernel
        kind = step["kind"]
        if kind == "sheet":
            sheet = k.sheet(step["pieces"], step["dir"], step["from"], step["to"])
            if not k.is_surface(sheet):
                fail(step["id"], "The sheet did not come out as a surface.")
                return True
            self.bodies[step["id"]] = {"name": step["name"], "shape": sheet, "origins": {h: step["id"] for h in k.face_hashes(sheet)}, "surface": True}
            results.append({"id": step["id"], "status": "ok"})
            return True
        if kind in ("loft", "sweep"):
            solid = self.loft_of(step) if kind == "loft" else k.sweep(step["profile"], step["path"])
            if not k.is_closed_solid(solid):
                fail(step["id"], "The result is not a closed solid.")
                return True
            self.place(step, solid, fail, results)
            return True
        if kind == "thicken":
            self.play_thicken(step, fail, results)
            return True
        if kind == "surface":
            made = self.surface_of(step)
            if made.get("primitive"):
                self.fitted[step["id"]] = made["primitive"]
            body = {"name": step["name"], "shape": made["face"], "origins": {h: step["id"] for h in k.face_hashes(made["face"])}, "surface": True}
            if made.get("fit"):
                body["fit"] = made["fit"]
            self.bodies[step["id"]] = body
            results.append({"id": step["id"], "status": "ok", "surface": plain(made["report"])})
            return True
        if kind == "trim":
            self.play_trim(step, results)
            return True
        if kind == "network":
            made = self.network_of(step)
            if "message" in made:
                results.append({"id": step["id"], "status": "failed", "message": made["message"], "network": plain(made["report"])})
                return True
            self.bodies[step["id"]] = {"name": step["name"], "shape": made["shape"], "origins": {h: step["id"] for h in k.face_hashes(made["shape"])},
                                       "surface": not made["report"]["closed"], "patches": made["patches"]}
            refused = [c for c in made["report"]["cells"] if "refused" in c]
            out = {"id": step["id"], "status": "ok", "network": plain(made["report"])}
            if refused:
                out["note"] = f"{len(refused)} cell{'' if len(refused) == 1 else 's'} not filled: {'; '.join(c['refused'] for c in refused)}."
            results.append(out)
            return True
        return False

    # ---- loft
    def loft_of(self, step):
        """build.ts loftOf: a smooth loft whose skin crosses itself between
        its sections is refused — the kernel answers it valid."""
        from .loft_fold import loft_fold_refusal, sections_normal

        k = self.kernel
        solid = k.loft(step["profiles"], step.get("ruled"))
        if step.get("ruled"):
            self.smooth_lofts.discard(step["id"])
            return solid
        self.smooth_lofts.add(step["id"])
        fold = k.loft_fold(solid, normal=sections_normal(step["profiles"]))
        if not fold:
            return solid
        names = step.get("sketchNames") or []
        sections = [{"name": names[i] if i < len(names) else f"sketch {sid}", "profile": p} for i, (sid, p) in enumerate(zip(step["sketches"], step["profiles"]))]
        raise StepFailed(loft_fold_refusal(fold, sections))

    # ---- thicken
    def sheet_for(self, step):
        sheet = self.body_before(step["id"], step["sheet"])
        if not sheet:
            raise StepFailed("The sheet this thickens is gone, or failed to build.")
        if not sheet.get("surface"):
            raise StepFailed(f"{sheet['name']} is a solid, not a sheet — a thicken takes a sheet; a solid is grown or shrunk by an offset, or hollowed by a shell.")
        return sheet

    def thicken_of(self, step):
        sheet = self.sheet_for(step)
        if step["side"] == "both" and sheet.get("patches") and len(self.kernel.face_hashes(sheet["shape"])) > 1:
            return {"message": "A patch network’s sheet of several patches thickens one way at a time, Out or In: both ways, the kernel’s offset of it to the middle does not come back as the sheet."}
        try:
            return {"made": self.kernel.thicken_tracked(sheet["shape"], step["thickness"], step["side"]), "sheet": sheet}
        except Exception as e:  # noqa: BLE001 — the kernel's refusal, in its words
            import re

            said = re.sub(r"^[A-Z][a-z ]+: ", "", str(e)).rstrip(".")
            from ._js import num_str

            return {"message": f"The sheet does not thicken {thicken_way(step['side'])} by {num_str(round(step['thickness'] * 100) / 100)} mm: {said}; every face of it takes the thickness alone, so it fails at its edge or where its faces meet."}

    def play_thicken(self, step, fail, results):
        """build.ts playThicken: placed as a loft's solid is, the skin
        keeping the makers of the sheet's faces, the wall said."""
        got = self.thicken_of(step)
        if "message" in got:
            results.append({"id": step["id"], "status": "failed", "message": got["message"]})
            return
        made, sheet = got["made"], got["sheet"]
        frm = len(results)
        self.place(step, made["shape"], fail, results)
        r = next((x for x in results[frm:] if x["id"] == step["id"]), None)
        if not r or r["status"] != "ok":
            return
        for i in r.get("bodies") or []:
            b = self.bodies.get(i)
            if not b:
                continue
            for h, was in made["skin"].items():
                maker = sheet["origins"].get(was)
                if maker is not None and b["origins"].get(h) == step["id"]:
                    b["origins"][h] = maker
        if made.get("wall"):
            said = wall_said(made["wall"], step["thickness"])
            if "note" in said:
                r["note"] = said["note"]
            else:
                self.step_warnings.append(said["warning"])

    # ---- split
    def split_body(self, step, body):
        """build.ts applyToBody's split: the body cut by the tools, the
        fragments kept as the step says; the kept faces traced to the faces
        of the body they lie on."""
        k = self.kernel
        if body.get("surface"):
            raise StepFailed(LATER_SHEET_SPLIT)
        if step.get("within") is not None:
            raise StepFailed(LATER_SPLIT_WITHIN)
        tools = [b["shape"] for b in (self.body_by_id(i) for i in step["tools"]) if b]
        if len(tools) != len(step["tools"]):
            raise StepFailed("A sheet this split cuts with is gone, or failed to build.")
        between = step["keep"] == "between"
        target = body["shape"]
        if between:
            self.sheets_apart(step["tools"], tools, body)
        fragments = k.split(target, tools)
        crossed_words = f"The sheets cross inside {body['name']}: the corners they cut it into each have a face on every sheet, on different sides of them, so none is the wall between. Thicken one skin instead — fit it past the part's edge, trim it by Split or Combine, then Thicken."
        against = tools
        wall = self.between_fragments(fragments, tools) if between else None
        if wall and wall["crossed"]:
            raise StepFailed(crossed_words)
        if len(fragments) < 2 or (wall and not wall["kept"]):
            reaching = self.reaching_tools(step["tools"], target, body["name"])
            if reaching:
                if between:
                    self.sheets_apart(step["tools"], reaching, body, True)
                fragments = k.split(target, reaching)
                against = reaching
                wall = None
        if len(fragments) < 2:
            raise StepFailed("The sheet does not cut the body into parts — it has to cross the body from side to side.")
        if between:
            wall = wall or self.between_fragments(fragments, against)
            if wall["crossed"]:
                raise StepFailed(crossed_words)
            kept = wall["kept"]
        else:
            kept = self.keep_fragments(fragments, step)
        if not kept:
            raise StepFailed("No fragment lies on the scan within the tolerance — widen it, or keep the largest." if step["keep"] == "scan"
                             else "No fragment lies between the sheets — none has a face on every one of them. Each sheet has to cross the body from side to side, and the body to reach past them all." if between
                             else "No fragment to keep.")
        acc = kept[0] if len(kept) == 1 else k.fuse_all(kept)
        return {"shape": acc, "history": k.traced_history(body["shape"], acc)}

    def keep_fragments(self, fragments, step, sheet=False, leave_out=None):
        """build.ts keepFragments: those on the scan, or the largest or the
        smallest by volume (a sheet's by area)."""
        k = self.kernel
        if step["keep"] == "scan":
            if not self.scan:
                raise StepFailed("The scan is not here to keep the fragments on it — open the scan, or keep the largest.")
            kept = []
            for f in fragments:
                share = self.on_scan_share(f, step["tolerance"], leave_out)
                if share is not None and share >= step["overlap"]:
                    kept.append(f)
            return kept
        sizes = [k.surface_area(f) if sheet else k.volume(f) for f in fragments]
        if not sizes:
            return []
        pick = sizes.index(min(sizes)) if step["keep"] == "smallest" else sizes.index(max(sizes))
        return [fragments[pick]]

    def between_fragments(self, fragments, tools):
        """build.ts betweenFragments: the fragments with a face on every
        sheet, all on the same side of each; crossed when they lie on
        different sides (the sheets cross inside the body)."""
        k = self.kernel
        if len(tools) < 2:
            return {"kept": [], "crossed": False}
        kept, sides = [], set()
        for f in fragments:
            sag = mesh_deflection(diagonal_of(k, f))
            drawn = k.mesh(f, sag)
            p, ix = drawn["positions"], drawn["indices"]
            points = {}
            for t, h in enumerate(drawn.get("faceHash") or []):
                if h in points:
                    continue
                a, b, c = ix[t * 3] * 3, ix[t * 3 + 1] * 3, ix[t * 3 + 2] * 3
                points[h] = [(p[a + j] + p[b + j] + p[c + j]) / 3 for j in range(3)]
            near = 2 * sag + 1e-3
            on = [next(((h, at) for h, at in points.items() if k.distance_to_point(tool, at) <= near), None) for tool in tools]
            if not all(on):
                continue
            side = "".join("-" if dot(k.face_normals(f, h, [at])[0], k.sheet_normals(tool, [at])[0]) > 0 else "+" for tool, (h, at) in zip(tools, on))
            kept.append(f)
            sides.add(side)
        return {"kept": [], "crossed": True} if len(sides) > 1 else {"kept": kept, "crossed": False}

    def sheets_apart(self, ids, shapes, body, carried=False):
        """build.ts sheetsApart: no two sheets a split keeps between may
        cross inside the body — refused, saying where."""
        from ._js import to_fixed

        k = self.kernel
        deflection = mesh_deflection(self._diagonal(body))

        def sheet(i):
            b = self.body_by_id(i)
            return bool(b and b.get("surface"))

        def name(i):
            b = self.body_by_id(i)
            return b["name"] if b else f"body {i}"

        for i in range(len(shapes)):
            for j in range(i + 1, len(shapes)):
                if not sheet(ids[i]) or not sheet(ids[j]):
                    continue
                if k.distance_between(shapes[i], shapes[j]) > MEET_MM:
                    continue
                lines = k.crossing(shapes[i], shapes[j], deflection)
                total = sum(length(sub(ln[q:q + 3], ln[q - 3:q])) for ln in lines for q in range(3, len(ln) - 2, 3))
                step = total / MEET_SAMPLES
                at = None
                for ln in lines:
                    for q in range(3, len(ln) - 2, 3):
                        if at:
                            break
                        a = ln[q - 3:q]
                        d = sub(ln[q:q + 3], a)
                        parts = max(1, math.ceil(length(d) / max(step, 1e-9)))
                        for s in range(parts + 1):
                            pt = add_scaled(a, d, s / parts)
                            if k.contains_point(body["shape"], pt, 1e-6):
                                at = pt
                                break
                if not at:
                    continue
                where = ", ".join(to_fixed(v, 2) for v in at)
                reach = f", carried on to reach {body['name']}," if carried else ""
                raise StepFailed(f"{name(ids[i])} and {name(ids[j])}{reach} meet at ({where}), inside {body['name']} — the wall between them closes there, so no one solid lies between the two. Thicken one skin instead: fit it past the part's edge, trim it to shape by Split or Combine (both take a sheet), then Thicken.")

    def reaching_tools(self, ids, shape, into):
        """build.ts reachingTools: a split's fitted sheets carried on to reach
        over the body — a freeform along its slope at its edge, a fitted
        plane as that plane; None when none was carried on."""
        from .surface_fit import GRID_AREA_SLACK, GRID_RETRIES, grid_area, grid_of, reach_over, reaching_grid_of

        k = self.kernel
        box = k.extent(shape)
        diagonal = length(sub(box["max"], box["min"]))
        margin = 0.05 * diagonal + 1
        import numpy as np

        points = np.asarray(k.mesh(shape, mesh_deflection(diagonal) * 4)["positions"], dtype=float).reshape(-1, 3)
        tools, made = [], 0
        for i in ids:
            b = self.body_by_id(i)
            p = self.fitted_for(i, b, "reach")
            carried = None
            if b.get("fit"):
                reach = reach_over(b["fit"], points, margin)
                whole = not reach and k.surface_area(b["shape"]) * GRID_AREA_SLACK < grid_area(grid_of(b["fit"]))
                if reach or whole:
                    area = want = 0.0
                    for per_span in (None, *GRID_RETRIES):
                        grid = (reaching_grid_of(b["fit"], reach["u"], reach["v"]) if per_span is None else reaching_grid_of(b["fit"], reach["u"], reach["v"], per_span)) if reach else (grid_of(b["fit"]) if per_span is None else grid_of(b["fit"], per_span))
                        through = k.surface_through(np.asarray(grid["points"], dtype=float).reshape(-1).tolist(), grid["rows"], grid["cols"])
                        area = k.surface_area(through)
                        want = grid_area(grid)
                        if not area / want > GRID_AREA_SLACK:
                            carried = through
                            made += 1
                            break
                    if carried is None:
                        raise StepFailed(f"{b['name']} carried on to {into} comes out wild at every grid tried ({_area_words(area)} mm² against the {_area_words(want)} it should have) — fit it with an expandPct that reaches, or trim {into} to where the sheet is.")
            elif p and p["kind"] == "plane":
                reach = reach_over({"origin": p["origin"], "axisU": p["basisU"], "axisV": p["basisV"], "uRange": [0, 0], "vRange": [0, 0]}, points, margin)
                if reach:
                    corner = add_scaled(add_scaled(p["origin"], p["basisU"], reach["u"][0]), p["basisV"], reach["v"][0])
                    carried = k.face({"outer": rectangle_loop(corner, p["basisU"], p["basisV"], reach["u"][1] - reach["u"][0], reach["v"][1] - reach["v"][0]), "holes": []})
                    made += 1
            tools.append(carried if carried is not None else b["shape"])
        return tools if made else None

    def fitted_for(self, i, b, use):
        """build.ts fittedFor: the plane or cylinder a surface was fitted as,
        while its sheet still stands for it."""
        if not b or b.get("reshaped") == "joined" or (b.get("reshaped") and use == "trim"):
            return None
        return self.fitted.get(i)

    # ---- surface
    def surface_of(self, step):
        """build.ts surfaceOf: a surface fitted through the step's region of
        the scan, as a face, with the fit's report."""
        import numpy as np

        from .surface_fit import fit_surface_reported

        if not self.scan:
            raise StepFailed("The scan is not here to fit a surface through.")
        region = np.asarray(step["region"], dtype=np.int64)
        if len(region) and int(region.max()) >= len(self.scan.V):
            raise StepFailed("The region names a vertex the scan does not have — it was marked on another scan.")
        xyz = self.scan.V[region].astype(np.float32).astype(float)
        if step.get("shape") in ("plane", "cylinder"):
            return self.primitive_surface(step, xyz)
        got = fit_surface_reported(xyz.reshape(-1), step["fit"], step.get("facing"))
        fit = got["fit"]
        face = self.face_through(fit)
        report = {"rms": fit["rms"], "max": fit["max"], "net": fit["net"], "points": len(region), "worst": got["worst"]}
        if step["fit"].get("robust"):
            report["dropped"] = got["dropped"]
        if got.get("strays"):
            report["strays"] = got["strays"]
        return {"face": face, "report": report, "fit": fit}

    def face_through(self, fit):
        """build.ts faceThrough: the kernel's face through a fitted surface,
        held to it — its area within GRID_AREA_SLACK of the grid's, a denser
        grid tried when not — and to SURFACE_TRIANGLES at its chord."""
        import numpy as np

        from .surface_fit import GRID_AREA_SLACK, GRID_RETRIES, grid_area, grid_of, mesh_triangles

        k = self.kernel
        area = off = 0.0
        for per_span in (None, *GRID_RETRIES):
            grid = grid_of(fit) if per_span is None else grid_of(fit, per_span)
            pts = np.asarray(grid["points"], dtype=float).reshape(-1)
            face = k.surface_through(pts.tolist(), grid["rows"], grid["cols"])
            area = grid_area(grid)
            off = k.surface_area(face) / area
            if not off > GRID_AREA_SLACK:
                P = pts.reshape(-1, 3)
                chord = mesh_deflection(float(np.linalg.norm(P.max(axis=0) - P.min(axis=0))))
                triangles = mesh_triangles(fit, chord)
                if triangles > SURFACE_TRIANGLES:
                    from ._js import num_str

                    raise StepFailed(f"The surface would mesh to about {round(triangles / 1000)} k triangles at its {num_str(chord)} mm chord, more than {SURFACE_TRIANGLES // 1000} k — it bends too often for its size. Fit a coarser net, or smooth it more.")
                return face
        said = f"{round(off)} times" if off > 100 else f"{round((off - 1) * 100)} % more than"
        raise StepFailed(f"The kernel's surface through the fit does not follow it: {said} the fit's {round(area)} mm² of area, at every grid it was given. Fit another net, or keep the region to one surface.")

    def primitive_surface(self, step, xyz):
        """build.ts primitiveSurface: a plane or a cylinder through the
        region, held to the references — the step's own and the planes and
        cylinders the surfaces before it came out as — drawn as an exact
        face round where the points are."""
        from .autoconstrain import constrain_cylinder, constrain_plane, cylinder_patch, plane_patch

        k = self.kernel
        refs = list(step.get("refs") or [])
        for s in step.get("refSurfaces") or []:
            p = self.fitted.get(s["id"])
            if not p:
                continue
            if p["kind"] == "plane":
                refs.append({"key": f"surface:{s['id']}", "kind": "plane", "name": s["name"], "origin": p["origin"], "normal": p["normal"]})
            elif p["kind"] == "cylinder":
                refs.append({"key": f"surface:{s['id']}", "kind": "axis", "name": s["name"], "origin": p["origin"], "dir": p["axis"]})
        points = len(xyz)
        flat = xyz.reshape(-1)
        if step["shape"] == "plane":
            fit = constrain_plane(flat, refs, step["constrain"])
            if not fit:
                raise StepFailed("The region has no plane through it — its points lie in a line.")
            patch = plane_patch(flat, fit, step["fit"]["expandPct"])
            face = k.face({"outer": rectangle_loop(patch["corner"], patch["u"], patch["v"], patch["width"], patch["height"]), "holes": []})
            return {"face": face, "report": {"rms": fit["rms"], "max": fit["max"], "net": {"u": 0, "v": 0}, "points": points, "shape": "plane", "rmsFree": fit["rmsFree"], "relations": fit["relations"]},
                    "primitive": {"kind": "plane", "origin": fit["origin"], "normal": fit["normal"], "basisU": patch["u"], "basisV": patch["v"]}}
        fit = constrain_cylinder(flat, refs, step["constrain"])
        if not fit:
            raise StepFailed("No cylinder was found through the region — mark more of the round, or fit it as a freeform surface.")
        patch = cylinder_patch(flat, fit, step["fit"]["expandPct"])

        def on(angle):
            return add_scaled(add_scaled(fit["origin"], patch["u"], fit["radius"] * math.cos(angle)), patch["v"], fit["radius"] * math.sin(angle))

        if patch["full"]:
            pieces = [{"kind": "circle", "center": fit["origin"], "normal": fit["axis"], "radius": fit["radius"]}]
        else:
            pieces = [{"kind": "arc", "a": on(patch["start"]), "m": on(patch["start"] + patch["sweep"] / 2), "b": on(patch["start"] + patch["sweep"])}]
        face = k.sheet(pieces, fit["axis"], patch["from"], patch["to"])
        return {"face": face, "report": {"rms": fit["rms"], "max": fit["max"], "net": {"u": 0, "v": 0}, "points": points, "shape": "cylinder", "radius": fit["radius"], "rmsFree": fit["rmsFree"], "relations": fit["relations"]},
                "primitive": {"kind": "cylinder", "origin": fit["origin"], "axis": fit["axis"], "radius": fit["radius"], "length": patch["to"] - patch["from"]}}

    # ---- trim
    def trim_box(self, tools):
        """build.ts trimBox: round the scan, grown a tenth each way, or round
        the tools when there is no scan."""
        lo, hi = [math.inf] * 3, [-math.inf] * 3

        def take(p):
            for i in range(3):
                lo[i] = min(lo[i], p[i])
                hi[i] = max(hi[i], p[i])

        if self.scan is not None and len(self.scan.V):
            take(self.scan.V.min(axis=0).tolist())
            take(self.scan.V.max(axis=0).tolist())
        else:
            for t in tools:
                b = self.kernel.bounds(t)
                take(b["min"])
                take(b["max"])
        if not math.isfinite(lo[0]):
            raise StepFailed("Nothing to trim round — no scan and no tool has an extent.")
        grow = max(1, 0.1 * length(sub(hi, lo)))
        return {"min": [x - grow for x in lo], "max": [x + grow for x in hi]}

    def trim_primitive(self, p, diagonal):
        """build.ts trimPrimitive: a measured element as a trim tool reaching
        past the box."""
        from .build import cylinder_solid, primitive_solid

        k = self.kernel
        reach = diagonal * 1.5
        if p["kind"] == "plane":
            u = normalize(p["basisU"]) or [1, 0, 0]
            v = normalize(p["basisV"]) or [0, 1, 0]
            corner = add_scaled(add_scaled(p["origin"], u, -reach), v, -reach)
            return k.face({"outer": rectangle_loop(corner, u, v, 2 * reach, 2 * reach), "holes": []})
        if p["kind"] == "cylinder":
            return cylinder_solid(k, p["origin"], p["axis"], p["radius"], -reach, reach)
        if p["kind"] == "cone":
            slope = (p["radius2"] - p["radius1"]) / max(p["length"], 1e-6)
            frm, to = -reach, reach

            def r(t):
                return p["radius1"] + slope * (t + p["length"] / 2)

            if r(frm) < 1e-3:
                frm = -p["length"] / 2 - (p["radius1"] - 1e-3) / max(slope, 1e-9)
            if r(to) < 1e-3:
                to = p["length"] / 2 + (p["radius2"] - 1e-3) / max(-slope, 1e-9)
            frm, to = max(frm, -reach), min(to, reach)
            n = normalize(p["axis"]) or [0, 0, 1]
            return primitive_solid(k, {"kind": "cone", "origin": add_scaled(p["origin"], n, (frm + to) / 2), "axis": n, "radius1": r(frm), "radius2": r(to), "length": to - frm})
        return primitive_solid(k, p)

    def trim_of(self, step):
        """build.ts trimOf: a box round the scan split by every tool, the
        faces lying on the scan sewn — a solid when they close."""
        k = self.kernel
        if not self.scan:
            raise StepFailed("The scan is not here to trim against.")
        tools, whole = [], []
        for i in step["bodies"]:
            b = self.body_by_id(i)
            if not b:
                raise StepFailed("A surface this trim closes is gone, or failed to build.")
            p = self.fitted_for(i, b, "trim")
            if p:
                whole.append(p)
            else:
                tools.append(b["shape"])
        box = self.trim_box(tools)
        diagonal = length(sub(box["max"], box["min"]))
        for p in [*whole, *step["primitives"]]:
            tools.append(self.trim_primitive(p, diagonal))
        faces = k.split_faces(k.box(box["min"], box["max"]), tools)
        kept = []
        for f in faces:
            share = self.on_scan_share(f, step["tolerance"])
            if share is not None and share >= step["overlap"]:
                kept.append(f)
        if not kept:
            from ._js import num_str

            raise StepFailed(f"None of the {len(faces)} faces the tools cut lies on the scan within {num_str(step['tolerance'])} mm — widen the tolerance, or add the surfaces the part still lacks.")
        sewn = k.sew_faces(kept, step["tolerance"])
        closed = k.is_closed_solid(sewn)
        open_edges = [] if closed else [e["polyline"] for e in k.edges(sewn, mesh_deflection(diagonal_of(k, sewn))) if len(e["faceHashes"]) < 2]
        return {"shape": sewn, "report": {"faces": len(faces), "kept": len(kept), "closed": closed, "openEdges": open_edges}, "surface": not closed}

    def play_trim(self, step, results):
        """build.ts play's trim: the kept faces traced to their makers by
        where they lie — a point on each within the tolerance of a surface
        body's tessellation makes that surface's feature its maker; the
        faces of the measured elements are the trim's own."""
        import numpy as np

        from ..dev_surface import NominalSurface

        k = self.kernel
        made = self.trim_of(step)
        shape = made["shape"]
        sources = []
        for i in step["bodies"]:
            b = self.body_by_id(i)
            m = k.mesh(b["shape"], mesh_deflection(diagonal_of(k, b["shape"])))
            if m["indices"]:
                sources.append((i, NominalSurface(np.asarray(m["positions"], dtype=float).reshape(-1, 3), np.asarray(m["indices"], dtype=np.int64).reshape(-1, 3))))
        sag = mesh_deflection(diagonal_of(k, shape))
        drawn = k.mesh(shape, sag)
        p, ix = drawn["positions"], drawn["indices"]
        on_face = {}
        for t, h in enumerate(drawn.get("faceHash") or []):
            if h not in on_face:
                a, b, c = ix[t * 3] * 3, ix[t * 3 + 1] * 3, ix[t * 3 + 2] * 3
                on_face[h] = [(p[a + j] + p[b + j] + p[c + j]) / 3 for j in range(3)]
        own = {}
        for f in k.faces(shape):
            maker, best = step["id"], step["tolerance"] + sag
            at = on_face.get(f["hash"], f["centroid"])
            for i, surf in sources:
                hit = surf.closest(np.asarray([at], dtype=float), best)
                if int(hit.face[0]) >= 0 and float(hit.distance[0]) < best:
                    best, maker = float(hit.distance[0]), i
            own[f["hash"]] = maker
        self.bodies[step["id"]] = {"name": step["name"], "shape": shape, "origins": own, "surface": made["surface"]}
        results.append({"id": step["id"], "status": "ok", "trim": plain(made["report"])})

    # ---- network
    def network_reading(self, step):
        """build.ts networkReading: the network read off the scan, the bodies
        it rests on read as they stand; or why no cell could be filled."""
        from .network import read_network
        from .network_body import empty_report
        from .topo import match_edge, match_face, match_tolerance

        if not self.scan:
            raise StepFailed("The scan is not here to draw a patch network on.")
        builder = self

        def topology_of(i):
            b = builder.body_by_id(i)
            if not b:
                return None
            diagonal = builder._diagonal(b)
            return b, builder.topology(b, mesh_deflection(diagonal)), match_tolerance(diagonal)

        class Bodies:
            @staticmethod
            def edge(i, fp):
                t = topology_of(i)
                if not t:
                    return None
                at = match_edge(fp, [e["fingerprint"] for e in t[1]["edges"]], t[2])
                return None if at is None else t[1]["edges"][at]["polyline"]

            @staticmethod
            def normals(i, fp, points):
                t = topology_of(i)
                if not t:
                    return None
                at = match_face(fp, [f["fingerprint"] for f in t[1]["faces"]], t[2])
                return None if at is None else builder.kernel.face_normals(t[0]["shape"], t[1]["faces"][at]["hash"], points)

        reading = read_network(self.scan.paths, step, Bodies)
        if not reading.get("fit"):
            refused = next((o for o in reading["outcomes"] if "refused" in o), None)
            message = ("No cell is filled yet — click inside a region the curves close, or Fill all." if not step["cells"]
                       else f"No cell could be filled{': ' + refused['refused'] if refused else ''}.")
            return {"message": message, "report": empty_report(reading)}
        return reading

    def network_of(self, step):
        from .network_body import empty_report, network_body

        reading = self.network_reading(step)
        if "message" in reading:
            return reading
        try:
            made = network_body(self.kernel, reading)
        except (ValueError, StepFailed) as e:
            return {"message": str(e), "report": empty_report(reading)}
        return {"shape": made["shape"], "report": made["report"], "patches": made["faceOf"]}


def _area_words(a):
    from ._js import num_str

    return num_str(round(a))
