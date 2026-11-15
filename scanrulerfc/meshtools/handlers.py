# SPDX-License-Identifier: AGPL-3.0-only
# Ported from ScanRuler by CNC Kitchen (Stefan Hermann):
# plugins/mesh-tools/app/meshCommands.ts (mesh.densify, mesh.boolean,
# mesh.shell, mesh.wrap, mesh.apply_wrap, mesh.trim) and
# plugins/mesh-tools/app/meshToolsSession.ts (their status lines).
#
# The handlers fn(ctx, args) for the Mesh Tools ScanRuler for FreeCAD lacked.
# Like the other mesh_* tools they work on the edited copy (made by the first
# edit) and keep the arrays before each change for mesh_undo; the wrap and
# the trimmed piece are made beside the mesh, as in ScanRuler. The session's
# Mesh Tools state is the one handlers/meshtools.py keeps (fam_meshtools.py
# before the decoupling); its helpers are taken from there.

import numpy as np

from .. import mesh_core as M
from .. import scanstate as S
from . import boolean as BO
from . import densify as DE
from . import shell as SH
from . import solids as SO
from . import trim as TR
from . import wrap as WR

try:
    from ..errors import ToolError
except ImportError:
    try:
        from agentlink.protocol import ToolError
    except ImportError:
        class ToolError(Exception):
            """A refusal: code (invalid_input, not_found, invalid_state,
            unavailable, failed) and message, as Agent Link's tool-data
            format reads one."""

            def __init__(self, code, message):
                super().__init__(message)
                self.code, self.message = code, message

try:
    from ..handlers.meshtools import mesh_out, mt_state, push_undo, region_vertices, working
except ImportError:
    try:
        from ..fam_meshtools import mesh_out, mt_state, push_undo, region_vertices, working
    except ImportError:
        UNDO_DEPTH = 20

        def mt_state(session):
            st = S.state(session)
            mine = st.setdefault("meshToolsState", {"base": None, "copy": None, "edits": [], "pending": [], "reduced": None, "undo": []})
            if st["scan"] is not mine["base"] and not any(u["scan"] is st["scan"] for u in mine["undo"]):
                mine.update({"base": st["scan"], "copy": None, "edits": [], "pending": [], "reduced": None, "undo": []})
            return mine

        def working(session):
            scan = S.state(session)["scan"]
            if scan is None:
                raise ToolError("invalid_state", "No scan open: scan_open { path } opens one.")
            ms = mt_state(session)
            if ms["copy"] is not None:
                return ms["copy"][0], ms["copy"][1], "edited copy"
            return scan.V, scan.F, "scan"

        def push_undo(session, label):
            st, ms = S.state(session), mt_state(session)
            ms["undo"].append({"label": label, "scan": st["scan"], "copy": ms["copy"], "edits": list(ms["edits"]), "pending": list(ms["pending"]), "reduced": ms["reduced"]})
            del ms["undo"][:-UNDO_DEPTH]

        def mesh_out(session):
            V, F, which = working(session)
            ms = mt_state(session)
            d = M.describe(V, F)
            vol = d["volume"]
            return {"working": which, **d, "volume": None if vol is None else round(vol, 3), "edits": list(ms["pending"] if ms["copy"] is not None else ms["edits"])}

        def region_vertices(session, region):
            V, F, which = working(session)
            try:
                vs = M.select_vertices(V, F, region)
            except M.MeshError as e:
                raise ToolError("invalid_input", str(e))
            if len(vs) == 0:
                raise ToolError("invalid_input", f"The region holds no vertex of the {which}.")
            return vs


def r(v, nd=4):
    return None if v is None else round(float(v), nd)


def _rounded(d):
    return {k: (r(v) if isinstance(v, float) else _rounded(v) if isinstance(v, dict) else v) for k, v in d.items()}


def _edit(session, label, job, kind):
    V, F, _ = working(session)
    try:
        V2, F2, _vmap, report, status = job(V, F)
    except BO.NeedsKernel as e:
        raise ToolError("unavailable", str(e))
    except M.MeshError as e:
        raise ToolError("failed", str(e))
    push_undo(session, label)
    ms = mt_state(session)
    ms["copy"] = (np.asarray(V2, dtype=float), np.asarray(F2, dtype=np.int64))
    ms["pending"].append(label)
    return {"edit": {"text": label, "kind": kind, **_rounded(report)}, "status": status, "mesh": mesh_out(session)}


def _closedness_refusal(V, F, why):
    c = M.closedness(F, len(V))
    if c["open"] > 0 or c["bad"] > 0:
        raise ToolError("invalid_state", f"The mesh is not closed — {c['open']} open edges, {c['bad']} shared by more than two triangles. {why}")


# ---- the solids on offer (booleanSolids.ts) ----------------------------------------------

def _get(x, *keys):
    for k in keys:
        v = x.get(k) if isinstance(x, dict) else getattr(x, k, None)
        if v is not None:
            return v
    return None


def solid_named(session, ref):
    """A solid on offer by key or name: a cylinder, cone or sphere measured
    in 3D Measure (an element, by id or name, at its assumed Ø), or a body
    in the FreeCAD document (by Name or Label). (key, name, V, F)."""
    els = S.state(session).get("elements") or []
    want = str(ref).strip().lower()
    hits = []
    for e in els:
        fit = _get(e, "fit")
        if not fit or _get(fit, "kind") not in SO.SOLID_KINDS or _get(e, "visible") is False:
            continue
        eid, name = _get(e, "id"), _get(e, "name")
        if (isinstance(ref, int) and not isinstance(ref, bool) and eid == ref) or str(eid) == want.replace("element:", "") or (isinstance(name, str) and name.strip().lower() == want):
            hits.append(e)
    if len(hits) > 1:
        raise ToolError("invalid_input", f"{len(hits)} solids are named {ref!r} — name it by its key.")
    if hits:
        e = hits[0]
        fit = dict(_get(e, "fit"))
        mesh = SO.element_solid(SO.drawn_fit(fit, _get(e, "assumed")))
        if mesh is None:
            raise ToolError("invalid_input", f"{_get(e, 'name')} has no volume to make a solid of.")
        return f"element:{_get(e, 'id')}", _get(e, "name"), mesh[0], mesh[1]
    doc = getattr(session, "doc", None)
    if doc is not None:
        objs = [o for o in doc.Objects if o.Name.lower() == want or o.Label.strip().lower() == want]
        if len(objs) > 1:
            raise ToolError("invalid_input", f"{len(objs)} objects are labelled {ref!r} — name it by its Name.")
        if objs:
            o = objs[0]
            if hasattr(o, "Mesh") and o.Mesh is not None and getattr(o.Mesh, "CountFacets", 0):
                pts, tris = o.Mesh.Topology
            elif getattr(o, "Shape", None) is not None and o.Shape.Solids:
                pts, tris = o.Shape.tessellate(SO.BOOLEAN_CHORD_MM)
            else:
                raise ToolError("invalid_input", f"{o.Label} is not a solid body.")
            V = np.array([[p.x, p.y, p.z] for p in pts], dtype=float).reshape(-1, 3)
            return f"body:{o.Name}", o.Label, V, np.array(tris, dtype=np.int64).reshape(-1, 3)
    raise ToolError("not_found", f"There is no solid {ref!r} on offer — a cylinder, cone or sphere measured (element_list), or a solid body in the document.")


# ---- the handlers ----------------------------------------------------------------------

def mesh_densify(session, a):
    V, F, _ = working(session)
    max_edge = float(a.get("maxEdge") or DE.densify_edge_for(M.diagonal(V)))

    def job(V, F):
        V2, F2, vm, rep = DE.densify_mesh(V, F, max_edge)
        return V2, F2, vm, rep, DE.status(rep)

    return _edit(session, "densify", job, "densify")


def mesh_boolean(session, a):
    op = a["op"]
    if op not in ("subtract", "add", "intersect"):
        raise ToolError("invalid_input", "op: subtract, add or intersect.")
    found, seen = [], set()
    for ref in a["solids"]:
        key, name, V, F = solid_named(session, ref)
        if key not in seen:
            seen.add(key)
            found.append((V, F, name))
    W, WF, _ = working(session)
    _closedness_refusal(W, WF, "A boolean needs it closed: close it with mesh_fill_holes first.")
    names = SO.names_of([n for _, _, n in found])

    def job(V, F):
        V2, F2, vm, rep = BO.boolean_mesh(V, F, found, op)
        change = rep["volumeAfter"] - rep["volumeBefore"]
        did = f"Took {names} out of the mesh" if op == "subtract" else f"Added {names} to the mesh" if op == "add" else f"Kept what the mesh and {names} share"
        status = f"{did} — {'+' if change >= 0 else '−'}{abs(change):.1f} mm³, {rep['added']:,} triangles of surface {'it' if len(found) == 1 else 'they'} made."
        return V2, F2, vm, {**rep, "solid": names, "volume": change}, status

    return _edit(session, f"{op} {names}", job, "boolean")


def mesh_shell(session, a):
    V, F, _ = working(session)
    diag = M.diagonal(V)
    thickness = float(a.get("thickness") or SH.default_wall_thickness(diag))
    side = a.get("side", "in")
    mode = a.get("mode")
    c = M.closedness(F, len(V))
    calls, holes = "hollow", 0
    if c["open"] > 0:
        hole_size = M.default_hole_size(diag)
        survey, _ = M.survey_holes(V, F, hole_size)
        holes = survey["holes"]
        calls = SH.shell_mode_of(c["open"], survey["rims"], holes)
    if mode == "hollow" and calls != "hollow":
        tail = f": fill its {holes} hole{'' if holes == 1 else 's'} with mesh_fill_holes first" if calls == "holes" else ""
        raise ToolError("invalid_state", f"The mesh is open — {c['open']} open edges — and only a closed part can be hollowed{tail}.")
    if mode == "thicken" and calls == "hollow":
        raise ToolError("invalid_state", "The mesh is closed — hollow it; only an open surface is thickened.")
    if not mode and calls == "holes":
        raise ToolError("invalid_state", f"The part is closed but for {holes} hole{'' if holes == 1 else 's'} smaller than {M.default_hole_size(diag):g} mm — fill {'it' if holes == 1 else 'them'} with mesh_fill_holes to hollow it, or pass mode: \"thicken\" to thicken it as it is, with a wall round every hole.")
    doing = mode or ("hollow" if calls == "hollow" else "thicken")

    def job(V, F):
        if doing == "hollow":
            V2, F2, vm, rep = SH.hollow_mesh(V, F, thickness)
            return V2, F2, vm, {**rep, "mode": "hollow"}, SH.hollow_status(rep)
        V2, F2, vm, rep = SH.thicken_mesh(V, F, thickness, side)
        return V2, F2, vm, {**rep, "mode": "thicken"}, SH.thicken_status(rep)

    return _edit(session, doing, job, "shell")


def _wrap_out(rep):
    return _rounded(rep)


def mesh_wrap(session, a):
    V, F, which = working(session)
    gap = float(a["gap"])
    grow = float(a.get("grow", 0.0))
    edges = a.get("edges", "sharp")
    try:
        WV, WF, bridge, rep = WR.wrap_mesh(V, F, gap, grow, edges, a.get("tolerance"))
    except M.MeshError as e:
        raise ToolError("failed", str(e))
    d = M.describe(V, F)
    rep = {**rep, "fromTriangles": int(len(F)), "volumeBefore": d["volume"], "from": which}
    mt_state(session)["wrap"] = {"V": WV, "F": WF, "bridge": bridge, "report": rep}
    out = {"wrap": _wrap_out(rep)}
    if a.get("preview", True) is False:
        return {**out, **mesh_apply_wrap(session, {})}
    status = f"Wrapped — {rep['shells']} shell{'' if rep['shells'] == 1 else 's'}, {rep['triangles']:,} triangles, {rep['bridgedArea']:.1f} mm² bridged. A preview beside the mesh: mesh_apply_wrap makes it the edited copy."
    return {**out, "status": status}


def mesh_apply_wrap(session, a):
    w = mt_state(session).get("wrap")
    if w is None:
        raise ToolError("invalid_state", "There is no wrap — mesh_wrap makes one.")
    out = _edit(session, "apply the wrap", lambda V, F: (w["V"], w["F"], None, {"triangles": int(len(w["F"]))}, "The wrap is the edited copy."), "wrap")
    mt_state(session)["wrap"] = None
    return out


def mesh_trim(session, a):
    key, name, BV, BF = solid_named(session, a["body"])
    marked = region_vertices(session, a["region"]) if a.get("region") is not None else None
    offset = float(a.get("offset", 0.0))
    depth = float(a.get("depth", TR.DEFAULT_BREAK_DEPTH))
    flip = bool(a.get("flip", False))
    V, F, _ = working(session)
    try:
        body = TR.prepare_body(BV, BF, name)
        PV, PF, mating, gap, rep = TR.trim_to_scan(V, F, body, depth, offset, flip, marked)
    except BO.NeedsKernel as e:
        raise ToolError("unavailable", str(e))
    except M.MeshError as e:
        raise ToolError("failed", str(e))
    mt_state(session)["piece"] = {"V": PV, "F": PF, "mating": mating, "gap": gap, "report": rep, "name": name, "solid": key}
    dropped = f", {rep['dropped']} piece{'' if rep['dropped'] == 1 else 's'} on the other side of the break dropped" if rep["dropped"] else ""
    status = (f"Trimmed {name} to the break — {rep['volume']:.1f} mm³, its mating face {rep['matingArea']:.1f} mm²"
              f"{f', {offset:g} mm off the break' if offset > 0 else ', on the break'}{dropped}.")
    return {"piece": {"name": name, "solid": key, "triangles": int(len(PF)), **_rounded(rep)}, "status": status}


def _ctx(fn):
    def call(ctx, args):
        return fn(ctx, args or {})

    call.__name__ = fn.__name__
    return call


HANDLERS = {fn.__name__: _ctx(fn) for fn in (mesh_densify, mesh_boolean, mesh_trim, mesh_shell, mesh_wrap, mesh_apply_wrap)}
NAMES = tuple(HANDLERS)
