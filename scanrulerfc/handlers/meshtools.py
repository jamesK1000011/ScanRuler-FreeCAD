# SPDX-License-Identifier: AGPL-3.0-only
# Ported from ScanRuler by CNC Kitchen, the Mesh Tools plugin (Stefan
# Hermann's): plugins/mesh-tools/app/meshCommands.ts (mesh.inspect,
# mesh.remove_islands, mesh.delete_marked, mesh.flip_normals, mesh.cut,
# mesh.cut_preview, mesh.mirror, mesh.fill_holes, mesh.smooth, mesh.offset,
# mesh.reduce, mesh.apply_reduced, mesh.use_edited, mesh.discard_edited,
# mesh.export, mesh.discard), plugins/mesh-tools/core/cutPlane.ts and
# plugins/mesh-tools/guides/mesh-tools.md.
#
# Every edit goes onto an edited copy, made by the first edit; the measuring
# tools keep reading the scan until mesh_use_edited takes the copy into use.
# The arrays before each change are kept, so mesh_undo takes it back.

import functools
import math
import os

import numpy as np

from .. import mesh_core as M
from .. import scanstate as S
from .. import section_core as SC
from ..errors import ToolError
from . import _bind
from .sections import cut_section, element_cut_axis, element_named

LIST = 40
DEFAULT_TRIANGLE_LIMIT = 50_000
UNDO_DEPTH = 20


def obj(props, required=()):
    return {"type": "object", "properties": props, "required": list(required), "additionalProperties": False}


def r(v, nd=4):
    return None if v is None else round(float(v), nd)


# The Mesh Tools maths (mesh_core, meshtools/*) refuses in the words of
# ScanRuler's panel, which names its keys; an agent is told the tool as well.
TOOL_WORDS = (
    ("Fill holes", "Fill holes (mesh_fill_holes)"),
    ("Decimate it first.", "Reduce it first: mesh_reduce, then mesh_apply_reduced."),
    ("Smooth on a marked region", "mesh_smooth { region }"),
    ("Grow by", "grow"),
    ("flip the side back", "pass flip: false"),
    ("flip the side.", "pass flip: true."),
    ("flip the side to keep", "pass the other keep (plus / minus)"),
    ("keep the other side", "pass the other keep (plus / minus)"),
)


def said(message):
    """A Mesh Tools refusal with the tools its panel words stand for."""
    text = str(message)
    for words, tool in TOOL_WORDS:
        if tool not in text:
            text = text.replace(words, tool)
    return text


def mt_state(session):
    st = S.state(session)
    mine = st.setdefault("meshToolsState", {"base": None, "copy": None, "edits": [], "pending": [], "reduced": None, "undo": [], "piece": None, "wrap": None})
    if st["scan"] is not mine["base"] and not any(u["scan"] is st["scan"] for u in mine["undo"]):
        # Another scan was opened: its copy and edits went with the old one.
        mine.update({"base": st["scan"], "copy": None, "edits": [], "pending": [], "reduced": None, "undo": [], "piece": None, "wrap": None})
    return mine


def working(session):
    scan = S.scan_of(session)
    ms = mt_state(session)
    if ms["copy"] is not None:
        return ms["copy"][0], ms["copy"][1], "edited copy"
    return scan.V, scan.F, "scan"


def push_undo(session, label):
    st, ms = S.state(session), mt_state(session)
    ms["undo"].append({"label": label, "scan": st["scan"], "copy": ms["copy"], "edits": list(ms["edits"]), "pending": list(ms["pending"]), "reduced": ms["reduced"]})
    del ms["undo"][:-UNDO_DEPTH]


def recut_sections(session):
    """The sections cut again on the scan now in use, as ScanRuler does when
    an edited copy is taken into use."""
    st = S.state(session)
    ss = st.setdefault("sectionState", {"scan": None, "sections": [], "next": 1})
    ss["scan"] = scan = st["scan"]
    for sec in ss["sections"]:
        pts, offs, nrm = cut_section(scan, sec["frame"])
        sec.update({"points": pts, "offsets": offs, "normals": nrm})


def mesh_out(session):
    V, F, which = working(session)
    ms = mt_state(session)
    d = M.describe(V, F)
    return {"working": which, **d, "volume": r(d["volume"], 3), "edits": list(ms["pending"] if ms["copy"] is not None else ms["edits"])}


def plane_at(session, plane, offset, keep, auto=False):
    """cutPlane.ts cutPlaneOf: across a coordinate axis through the origin
    (the offset its coordinate), or across an element with a direction; the
    normal turned to point to the side that goes."""
    S.scan_of(session)  # refuses when no scan is open
    axis_name = SC.parse_plane_name(plane) if isinstance(plane, str) else None
    if axis_name:
        axis = SC.world_cut_axis(axis_name)
        name = SC.PLANE_NAME[axis_name]
    else:
        e = element_named(session, plane)
        axis = element_cut_axis(e)
        name = e.get("name") if isinstance(e, dict) else getattr(e, "name", str(plane))
        if axis is None:
            raise ToolError("invalid_input", f"{name} has no direction to cut across — take a plane, a cylinder, a cone, a line or a circle.")
    d = axis["dir"] / np.linalg.norm(axis["dir"])
    if auto:
        # The middle of the mesh worked on (the edited copy once there is
        # one), as every other default here is read: after a cut the scan's
        # own middle is no longer the part's.
        W = working(session)[0]
        centre = (W.min(axis=0) + W.max(axis=0)) / 2
        offset = M.middle_offset(float((centre - axis["origin"]) @ d), 2 * M.diagonal(W))
    frame = SC.section_frame_along(axis, offset)
    label = f"{name}, {axis_name.upper()} {offset:g} mm" if axis_name else (name if offset == 0 else f"{name} {'+' if offset > 0 else '−'}{abs(offset):g} mm")
    normal = -frame["normal"] if keep == "plus" else frame["normal"]
    return frame["origin"], normal, offset, label


def region_vertices(session, region):
    V, F, which = working(session)
    if region == "marked":
        raise ToolError("invalid_input", "\"marked\" is the person's marking on screen, which FreeCAD has none of here — name the region with a box, a sphere or vertices.")
    if which == "edited copy" and isinstance(region, dict) and region.get("vertices") is not None:
        scan = S.scan_of(session)
        if len(V) != len(scan.V) or len(F) != len(scan.F):
            # Numbers read off the scan (scan_segment, an element's region)
            # name other points on a copy whose vertices have moved on: it
            # would change other parts of the copy (ScanRuler 0.10.1).
            raise ToolError("invalid_input", "region.vertices: the edited copy's vertices are numbered differently from the scan's now — name the region with a box or a sphere, or take vertex numbers off the copy (mesh_inspect).")
    try:
        vs = M.select_vertices(V, F, region)
    except M.MeshError as e:
        raise ToolError("invalid_input", str(e))
    if len(vs) == 0:
        raise ToolError("invalid_input", f"The region holds no vertex of the {which}{' facing that way' if region.get('facing') else ''} — scan_info gives the scan's bounds.")
    return vs


def bind(session):
    """{tool name: fn(args)} for one session (Agent Link's, or the
    add-on's own runner's context)."""
    def edit(label, job):
        V, F, _ = working(session)
        try:
            V2, F2, _vmap, report = job(V, F)
        except M.MeshError as e:
            raise ToolError("failed", said(e))
        push_undo(session, label)
        ms = mt_state(session)
        ms["copy"] = (np.asarray(V2, dtype=float), np.asarray(F2, dtype=np.int64))
        ms["pending"].append(label)
        return {"edit": {"text": label}, "report": report, "mesh": mesh_out(session)}

    def sizes():
        V, F, _ = working(session)
        return M.diagonal(V), M.mean_edge_length(V, F)

    def mesh_parts(a):
        ms = mt_state(session)
        scan = S.scan_of(session)
        red, wrap, piece = ms["reduced"], ms.get("wrap"), ms.get("piece")
        return {"scan": {"name": scan.name, "triangles": int(len(scan.F)), "edits": ms["edits"]}, "edited": None if ms["copy"] is None else {"triangles": int(len(ms["copy"][1])), "edits": ms["pending"]}, "reduced": None if red is None else red["report"],
                # The previews beside the mesh that mesh_wrap and mesh_trim leave (mesh_export { part: "wrap" | "piece" }).
                "wrap": None if wrap is None else {"triangles": int(len(wrap["F"]))}, "piece": None if piece is None else {"name": piece.get("name"), "triangles": int(len(piece["F"]))},
                "undo": ms["undo"][-1]["label"] if ms["undo"] else None}

    def mesh_inspect(a):
        V, F, which = working(session)
        diag = M.diagonal(V)
        isl = a.get("pieceSize", M.default_min_piece(diag))
        hol = a.get("holeSize", M.default_hole_size(diag))
        survey, _mask, centres = M.survey_pieces(V, F, isl)
        hs, hc = M.survey_holes(V, F, hol)
        d = M.describe(V, F)
        return {"working": which, **d, "volume": r(d["volume"], 3),
                "islands": {"size": isl, **{k: r(v) if isinstance(v, float) else v for k, v in survey.items()}, "centres": [[r(x) for x in c] for c in centres[:LIST]]},
                "holes": {"size": hol, **{k: r(v) if isinstance(v, float) else v for k, v in hs.items()}, "centres": [[r(x) for x in c] for c in hc[:LIST]]}}

    def mesh_remove_islands(a):
        size = a.get("size", M.default_min_piece(sizes()[0]))

        def job(V, F):
            survey, mask, _ = M.survey_pieces(V, F, size)
            if survey["islands"] == 0:
                raise M.MeshError(f"No piece of the mesh is smaller than {size:g} mm across — its {survey['pieces']} piece{'' if survey['pieces'] == 1 else 's'} {'is' if survey['pieces'] == 1 else 'are'} all larger (the smallest {survey['smallestKept']:.4g} mm): nothing to remove. "
                                  "A larger size takes a larger piece; mesh_inspect { pieceSize } counts them first.")
            if survey["islands"] == survey["pieces"]:
                raise M.MeshError(f"Every piece of the mesh is smaller than {size:g} mm across (the largest {survey['largestIsland']:.4g} mm) — nothing would be left. Give a size under the part's own.")
            V2, F2, vm = M.without_triangles(V, F, mask)
            return V2, F2, vm, survey

        return edit("remove islands", job)

    def mesh_delete_marked(a):
        vs = region_vertices(session, a["region"])

        def job(V, F):
            mask = M.marked_triangles(F, vs, len(V))
            if not mask.any():
                raise M.MeshError("No triangle has all three corners in the region.")
            if mask.all():
                raise M.MeshError("The whole scan is marked — nothing would be left.")
            V2, F2, vm = M.without_triangles(V, F, mask)
            return V2, F2, vm, {"triangles": int(mask.sum())}

        return edit("delete surface", job)

    def mesh_flip_normals(a):
        vs = region_vertices(session, a["region"]) if a.get("region") is not None else None

        def job(V, F):
            mask = None
            if vs is not None:
                mask = M.marked_triangles(F, vs, len(V))
                if not mask.any():
                    raise M.MeshError("No triangle has all three corners in the region.")
            V2, F2, vm, n = M.flip_triangles(V, F, mask)
            return V2, F2, vm, {"triangles": n}

        return edit("flip the normals of a region" if vs is not None else "flip the normals", job)

    def mesh_cut(a):
        o, n, off, label = plane_at(session, a["plane"], float(a["offset"]), a["keep"])

        def job(V, F):
            try:
                return M.cut_mesh(V, F, o, n, a.get("cap", True))
            except M.MeshError as e:
                # Where the mesh lies along the plane's own direction, as offsets.
                along = (V - o) @ (-n if a["keep"] == "plus" else n)
                raise M.MeshError(f"{e} At {label} the mesh runs from offset {off + float(along.min()):.4g} to {off + float(along.max()):.4g} mm: give an offset between them (mesh_cut_preview tries one without cutting).")

        return edit(f"cut at {label}", job)

    def mesh_cut_preview(a):
        V, F, _ = working(session)
        o, n, off, label = plane_at(session, a["plane"], float(a["offset"]), a.get("keep", "plus"))
        p = M.cut_preview(V, F, o, n)
        return {"plane": label, **p}

    def mesh_mirror(a):
        auto = a.get("offset") is None
        o, n, off, label = plane_at(session, a["plane"], float(a.get("offset") or 0.0), a.get("keep", "plus"), auto=auto)
        mode = a.get("mode", "whole")
        return edit(f"{'make symmetric about' if mode == 'symmetric' else 'mirror across'} {label}", lambda V, F: M.mirror_mesh(V, F, o, n, mode))

    def mesh_fill_holes(a):
        size = a.get("size", M.default_hole_size(sizes()[0]))
        V, F, which = working(session)
        survey, _centres = M.survey_holes(V, F, size)
        if survey["rims"] == 0:
            raise ToolError("invalid_state", f"The {which} has no open rim: there is no hole to fill (mesh_inspect: open 0).")
        if survey["holes"] == 0:
            raise ToolError("invalid_input", f"size: no open rim of the {which} is smaller than {size:g} mm across — the smallest is {survey['smallestOpen']:.4g} mm. Pass a size above that"
                            f"{' (at picks among the holes under size; it does not lift the limit)' if a.get('at') else ''}; mesh_inspect {{ holeSize }} lists each hole's middle.")
        return edit("fill a hole" if a.get("at") else "fill holes", lambda V, F: M.fill_holes(V, F, size, a.get("patch", "curved"), a.get("at")))

    def mesh_smooth(a):
        diag, edge = sizes()
        size = a.get("size", M.default_smooth_size(diag, edge))
        limit = a.get("limit", M.default_smooth_limit(diag))
        vs = region_vertices(session, a["region"]) if a.get("region") is not None else None
        return edit("smooth a region" if vs is not None else "smooth", lambda V, F: M.smooth_mesh(V, F, size, limit, a.get("keepEdges", True), vs))

    def mesh_offset(a):
        if a.get("region") is not None:
            raise ToolError("invalid_input", "region: moving a marked region as a step is not ported to ScanRuler for FreeCAD yet — leave region out and the whole mesh moves.")
        d = float(a["distance"]) * (1 if a["direction"] == "expand" else -1)
        return edit(f"{a['direction']} by {a['distance']} mm", lambda V, F: M.offset_mesh(V, F, d))

    def mesh_reduce(a):
        import Mesh

        V, F, which = working(session)
        tol = a.get("tolerance", M.default_tolerance(M.diagonal(V)))
        cap = a.get("maxTriangles", DEFAULT_TRIANGLE_LIMIT)
        # FreeCAD's own quadric decimation (Mesh.decimate) in place of the
        # meshoptimizer simplifier ScanRuler runs; measured afterwards as
        # ScanRuler measures it, both ways.
        m = Mesh.Mesh()
        m.addFacets([[tuple(V[i]) for i in t] for t in F.tolist()])
        m.decimate(float(tol), 1.0)
        capped = False
        if m.CountFacets > cap:
            m.decimate(int(cap))
            capped = True
        pts, tris = m.Topology
        RV = np.array([[p.x, p.y, p.z] for p in pts], dtype=float)
        RF = np.array(tris, dtype=np.int64)
        there = surface_distances(V, RV, RF)
        back = surface_distances(RV, V, F)
        report = {"settings": {"tolerance": tol, "maxTriangles": cap}, "inputTriangles": int(len(F)), "triangles": int(len(RF)), "vertices": int(len(RV)),
                  "measured": int(len(there)), "within": int((there <= tol).sum()), "p999": r(np.quantile(there, 0.999)), "max": r(there.max()), "rms": r(math.sqrt((there ** 2).mean())),
                  "backP999": r(np.quantile(back, 0.999)), "backMax": r(back.max()), "held": bool(np.quantile(there, 0.999) <= tol and np.quantile(back, 0.999) <= tol), "capped": capped, "method": "FreeCAD Mesh.decimate"}
        mt_state(session)["reduced"] = {"V": RV, "F": RF, "report": report, "from": which}
        return {"reduced": report}

    def mesh_apply_reduced(a):
        ms = mt_state(session)
        red = ms["reduced"]
        if red is None:
            raise ToolError("invalid_state", "There is no reduced mesh — mesh_reduce makes one.")
        out = edit("apply the reduction", lambda V, F: (red["V"], red["F"], None, red["report"]))
        ms["reduced"] = None
        return out

    def mesh_discard(a):
        ms = mt_state(session)
        what = a["what"]
        if what not in ("reduced", "wrap"):
            raise ToolError("invalid_input", "what: \"reduced\" (mesh_reduce's preview) or \"wrap\" (mesh_wrap's).")
        if ms.get(what) is None:
            raise ToolError("invalid_state", f"There is no {'reduced mesh' if what == 'reduced' else 'wrap'} to discard — {'mesh_reduce' if what == 'reduced' else 'mesh_wrap'} makes one; mesh_parts says what is on hand.")
        ms[what] = None
        return {"discarded": what, what: None}

    def mesh_use_edited(a):
        st, ms = S.state(session), mt_state(session)
        if ms["copy"] is None:
            raise ToolError("invalid_state", "There is no edited copy — the first edit makes one.")
        push_undo(session, "use the edited mesh for analysis")
        old = st["scan"]
        new = S.Scan(old.name, ms["copy"][0], ms["copy"][1], old.units, old.path)
        st["scan"] = new
        ms.update({"base": new, "copy": None, "edits": ms["edits"] + ms["pending"], "pending": []})
        recut_sections(session)
        return {"scan": {"name": new.name, "triangles": int(len(new.F)), "edits": ms["edits"]}, "note": "Every tool measures the edited mesh now; the sections were cut again on it. Elements fitted before keep their fits — fit them again where it matters."}

    def mesh_discard_edited(a):
        ms = mt_state(session)
        if ms["copy"] is None:
            raise ToolError("invalid_state", "There is no edited copy — the first edit makes one.")
        push_undo(session, "discard the edits")
        ms.update({"copy": None, "pending": []})
        return {"mesh": mesh_out(session)}

    def mesh_undo(a):
        st, ms = S.state(session), mt_state(session)
        if not ms["undo"]:
            raise ToolError("invalid_state", "No mesh edit to take back.")
        u = ms["undo"].pop()
        changed = st["scan"] is not u["scan"]
        st["scan"] = u["scan"]
        ms.update({"base": u["scan"], "copy": u["copy"], "edits": u["edits"], "pending": u["pending"], "reduced": u["reduced"]})
        if changed:
            recut_sections(session)
        return {"undone": u["label"], "mesh": mesh_out(session)}

    def mesh_export(a):
        import Mesh

        ms = mt_state(session)
        part = a["part"]
        if part == "edited":
            if ms["copy"] is None:
                raise ToolError("invalid_state", "There is no edited copy — the first edit makes one.")
            V, F = ms["copy"]
        elif part == "reduced":
            if ms["reduced"] is None:
                raise ToolError("invalid_state", "There is no reduced mesh — mesh_reduce makes one.")
            V, F = ms["reduced"]["V"], ms["reduced"]["F"]
        elif part == "piece":
            if ms.get("piece") is None:
                raise ToolError("invalid_state", "There is no trimmed piece — mesh_trim makes one.")
            V, F = ms["piece"]["V"], ms["piece"]["F"]
        elif part == "wrap":
            if ms.get("wrap") is None:
                raise ToolError("invalid_state", "There is no wrap — mesh_wrap makes one.")
            V, F = ms["wrap"]["V"], ms["wrap"]["F"]
        else:
            raise ToolError("invalid_input", "part: edited, reduced, piece or wrap.")
        scan = S.scan_of(session)
        if a.get("to") == "document":
            if session.doc is None:
                raise ToolError("invalid_state", "No document open: doc_new first.")
            m = Mesh.Mesh()
            m.addFacets([[tuple(V[i]) for i in t] for t in F.tolist()])
            o = session.doc.addObject("Mesh::Feature", "Mesh")
            o.Label = session.unique(f"{os.path.splitext(scan.name)[0]} {part}")
            o.Mesh = m
            session.doc.recompute()
            session.snapshot("mesh_export")
            return {"object": o.Label, "triangles": int(len(F)), "status": f"{part} mesh put in the document: Agent Link's meshobj tools, slicing and export work on it."}
        fmt = a.get("format", "stl")
        path = a.get("path") or os.path.join(session.out_dir, f"{os.path.splitext(scan.name)[0]}-{part}.{fmt}")
        if not path.lower().endswith("." + fmt):
            path += "." + fmt
        m = Mesh.Mesh()
        m.addFacets([[tuple(V[i]) for i in t] for t in F.tolist()])
        try:
            m.write(path)
        except Exception as e:
            raise ToolError("failed", f"{path}: could not be written — {e}")
        return {"file": {"path": path, "name": os.path.basename(path), "bytes": os.path.getsize(path)}, "format": fmt, "triangles": int(len(F)), "status": f"{part} mesh written in millimetres"}

    def surface_distances(P, V, F):
        return point_mesh_distances(P, V, F)

    return {
        "mesh_parts": mesh_parts,
        "mesh_inspect": mesh_inspect,
        "mesh_remove_islands": mesh_remove_islands,
        "mesh_delete_marked": mesh_delete_marked,
        "mesh_flip_normals": mesh_flip_normals,
        "mesh_cut": mesh_cut,
        "mesh_cut_preview": mesh_cut_preview,
        "mesh_mirror": mesh_mirror,
        "mesh_fill_holes": mesh_fill_holes,
        "mesh_smooth": mesh_smooth,
        "mesh_offset": mesh_offset,
        "mesh_reduce": mesh_reduce,
        "mesh_apply_reduced": mesh_apply_reduced,
        "mesh_discard": mesh_discard,
        "mesh_use_edited": mesh_use_edited,
        "mesh_discard_edited": mesh_discard_edited,
        "mesh_undo": mesh_undo,
        "mesh_export": mesh_export,
        # Densify, Boolean, Trim to scan, Shell and Wrap (scanrulerfc/meshtools),
        # on the same Mesh Tools state; imported here, as they import this module.
        **_added(session),
    }


def _added(session):
    from ..meshtools import handlers as ADDED

    return {n: functools.partial(ADDED.HANDLERS[n], session) for n in ADDED.NAMES}


def point_mesh_distances(P, V, F, sample=4000):
    """Each point's distance to the nearest triangle (a sample of at most
    `sample` points), by a grid over the triangles' boxes."""
    P = np.asarray(P, dtype=float)
    if len(P) > sample:
        P = P[np.linspace(0, len(P) - 1, sample).astype(int)]
    T = V[F]
    lo, hi = T.min(axis=1), T.max(axis=1)
    cell = max(float(np.median(np.linalg.norm(hi - lo, axis=1))) * 2, 1e-6)
    grid = {}
    a = np.floor(lo / cell).astype(int)
    b = np.floor(hi / cell).astype(int)
    for t in range(len(T)):
        for i in range(a[t, 0], b[t, 0] + 1):
            for j in range(a[t, 1], b[t, 1] + 1):
                for k in range(a[t, 2], b[t, 2] + 1):
                    grid.setdefault((i, j, k), []).append(t)
    out = np.empty(len(P))
    for n, p in enumerate(P):
        c = np.floor(p / cell).astype(int)
        cand = []
        ring = 1
        while not cand and ring < 64:
            for i in range(c[0] - ring, c[0] + ring + 1):
                for j in range(c[1] - ring, c[1] + ring + 1):
                    for k in range(c[2] - ring, c[2] + ring + 1):
                        cand += grid.get((i, j, k), [])
            ring *= 2
        out[n] = _point_triangles(p, T[np.unique(cand)]).min() if cand else math.inf
    return out


def _point_triangles(p, T):
    """Distance from p to each triangle (Eberly's closest point, vectorised
    over regions by projecting and clamping)."""
    A, B, C = T[:, 0], T[:, 1], T[:, 2]
    ab, ac, ap = B - A, C - A, p - A
    d1, d2 = (ab * ap).sum(1), (ac * ap).sum(1)
    bp = p - B
    d3, d4 = (ab * bp).sum(1), (ac * bp).sum(1)
    cp = p - C
    d5, d6 = (ab * cp).sum(1), (ac * cp).sum(1)
    va = d3 * d6 - d5 * d4
    vb = d5 * d2 - d1 * d6
    vc = d1 * d4 - d3 * d2
    den = va + vb + vc
    with np.errstate(divide="ignore", invalid="ignore"):
        v = np.where(den != 0, vb / den, 0)
        w = np.where(den != 0, vc / den, 0)
    Q = A + ab * v[:, None] + ac * w[:, None]

    def seg(X, Y):
        d = Y - X
        L = (d * d).sum(1)
        t = np.clip(np.where(L > 0, ((p - X) * d).sum(1) / np.where(L > 0, L, 1), 0), 0, 1)
        return X + d * t[:, None]

    inside = (va >= 0) & (vb >= 0) & (vc >= 0) & (den > 0)
    cands = [np.where(inside[:, None], Q, A), seg(A, B), seg(B, C), seg(C, A)]
    return np.min([np.linalg.norm(c - p, axis=1) for c in cands], axis=0)


NAMES = ("mesh_parts", "mesh_inspect", "mesh_remove_islands", "mesh_delete_marked", "mesh_flip_normals", "mesh_cut", "mesh_cut_preview", "mesh_mirror", "mesh_fill_holes", "mesh_smooth", "mesh_offset", "mesh_reduce", "mesh_apply_reduced", "mesh_discard", "mesh_use_edited", "mesh_discard_edited", "mesh_undo", "mesh_export",
         "mesh_densify", "mesh_boolean", "mesh_trim", "mesh_shell", "mesh_wrap", "mesh_apply_wrap")
HANDLERS = _bind.table(bind, NAMES)
