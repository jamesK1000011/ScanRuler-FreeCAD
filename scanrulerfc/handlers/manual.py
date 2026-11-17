# SPDX-License-Identifier: AGPL-3.0-only
# Assembly instructions from bodies modelled in their assembled places:
# the steps, each part's way in checked against the parts already there,
# the words linted to a style, and the manual written as an HTML page with
# a picture per step. ScanRuler's assembly-manual plugin, for Agent Link.
# Ported from ScanRuler by CNC Kitchen: plugins/assembly-manual/app/
# asmCommands.ts (settings, parts, step, check, text, style, render, save).
#
# Agent Link's asm_* tools make FreeCAD assemblies with joints; this reads
# the bodies where they sit and writes how to put them together.

import json
import os

import numpy as np

from .. import errors, lent
from .. import manual_core as MC
from .. import scanstate as S
from ..errors import ToolError
from . import _bind

FACES_MAX = 5000
SAMPLES = 16
CLEAR = 2.0
GREY = (0.78, 0.78, 0.80)


def obj(props, required=()):
    return {"type": "object", "properties": props, "required": list(required), "additionalProperties": False}


def mstate(session):
    st = S.state(session)
    if "manual" not in st:
        st["manual"] = json.loads(json.dumps(MC.DEFAULT))
    return st["manual"]


def _unit(v):
    v = np.asarray(v, float)
    n = np.linalg.norm(v)
    if not n > 0:
        raise ToolError("invalid_input", "move: a direction, not a zero vector.")
    return v / n


def bind(session):
    """{tool name: fn(args)} for one session (Agent Link's, or the
    add-on's own runner's context)."""
    def shape_of(part):
        if not part.get("body"):
            return None
        try:
            o = session.body(part["body"])
        except errors.REFUSED:  # the host's refusal too (Agent Link's session.body)
            raise ToolError("not_found", f"Part {part['name']!r}: no body {part['body']!r} in the document.")
        return o.Shape.copy()

    def walk(plan):
        """Each step with what is in place before it (in its own
        sub-assembly or the main one) and each placement's shape and way
        in. Yields (index, step, before shapes, [(placement, shape, move,
        travel)])."""
        parts = {p["name"]: p for p in plan["parts"]}
        groups = {None: []}
        sub_parts = {}
        for i, st in enumerate(plan["steps"]):
            key = st.get("sub")
            groups.setdefault(key, [])
            before = list(groups[key])
            places = []
            for pl in st.get("place", []):
                nm = pl["part"]
                if nm in sub_parts:
                    shapes = [s for _n, s in sub_parts[nm]]
                    import Part

                    sh = Part.makeCompound(shapes) if shapes else None
                else:
                    if nm not in parts:
                        raise ToolError("invalid_input", f"Step {i + 1}: {nm!r} is not a part (manual_plan parts) or a sub-assembly built before it.")
                    sh = shape_of(parts[nm])
                move = _unit(pl.get("move", [0, 0, -1]))
                travel = pl.get("travel")
                if travel is None and sh is not None:
                    bb = sh.BoundBox
                    corners = np.array([[x, y, z] for x in (bb.XMin, bb.XMax) for y in (bb.YMin, bb.YMax) for z in (bb.ZMin, bb.ZMax)])
                    p = corners @ move
                    travel = float(p.max() - p.min()) + CLEAR
                places.append((pl, sh, move, float(travel or 10.0)))
                if sh is not None:
                    groups[key].append((nm, sh))
            yield i, st, before, places
            if key:
                sub_parts[key] = groups[key]

    def manual_plan(a):
        m = mstate(session)
        if a.get("import"):
            try:
                with open(a["import"], encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, ValueError) as e:
                raise ToolError("invalid_input", f"import {a['import']!r}: {e}")
            if data.get("kind") != "scanruler.manual":
                raise ToolError("invalid_input", "Not a manual file (kind scanruler.manual): manual_plan { export } writes one.")
            m.clear()
            m.update(json.loads(json.dumps(MC.DEFAULT)))
            for k in ("settings", "style", "parts", "steps"):
                if k in data:
                    m[k] = data[k] if k in ("parts", "steps") else {**m[k], **data[k]}
        if a.get("settings"):
            m["settings"].update(a["settings"])
        if a.get("style"):
            st = a["style"]
            if st.get("name") and st["name"] not in MC.STYLES:
                raise ToolError("invalid_input", f"style name: {', '.join(MC.STYLES)}.")
            m["style"].update({k: v for k, v in st.items() if k != "words"})
            m["style"]["words"].update(st.get("words") or {})
        if a.get("fromBodies"):
            have = {p.get("body") for p in m["parts"]}
            for o in session.bodies():
                if o.Label not in have:
                    m["parts"].append({"name": o.Label, "body": o.Label, "kind": "part"})
        for p in a.get("parts") or []:
            if not p.get("name"):
                raise ToolError("invalid_input", "A part needs a name.")
            m["parts"] = [x for x in m["parts"] if x["name"] != p["name"]] + [{"kind": "part", **p}]
        for nm in a.get("removeParts") or []:
            m["parts"] = [x for x in m["parts"] if x["name"] != nm]
        if a.get("steps") is not None:
            m["steps"] = [{"id": s.get("id") or f"s{k + 1}", **s} for k, s in enumerate(a["steps"])]
        for s in a.get("step") or []:
            at = s.pop("at", None) if isinstance(s, dict) else None
            row = {"id": s.get("id") or f"s{len(m['steps']) + 1}", **s}
            same = [k for k, x in enumerate(m["steps"]) if x["id"] == row["id"]]
            if same:
                m["steps"][same[0]] = row
            elif at is not None:
                m["steps"].insert(max(0, int(at) - 1), row)
            else:
                m["steps"].append(row)
        out = dict(m)
        problems, unplaced = MC.check_plan(m)
        if problems:
            out["problems"] = problems
        if unplaced:
            out["unplaced"] = unplaced
        if a.get("export"):
            path = a["export"] if os.path.isabs(a["export"]) else os.path.join(session.out_dir, a["export"])
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"kind": "scanruler.manual", "version": 1, **m}, f, indent=1)
            out["exported"] = path
        return out

    def manual_check(a):
        m = mstate(session)
        if not m["steps"]:
            raise ToolError("invalid_state", "No steps: manual_plan { steps } first.")
        report = []
        for i, st, before, places in walk(m):
            row = {"step": i + 1, "parts": []}
            there = [s for _n, s in before]
            for pl, sh, move, travel in places:
                r = {"part": pl["part"]}
                if sh is None:
                    r["checked"] = False
                    r["why"] = "hardware without a body"
                elif len(sh.Faces) > FACES_MAX:
                    r["checked"] = False
                    r["why"] = f"{len(sh.Faces)} faces (a mesh brought in as a body): rebuild it from features to check it"
                elif there:
                    import Part

                    other = Part.makeCompound(there)
                    vol = max(sh.Volume, 1e-9)

                    def overlap_at(t, sh=sh, move=move, other=other, vol=vol):
                        moved = sh.copy()
                        moved.translate(tuple(-move * t))  # back along its way in
                        try:
                            return moved.common(other).Volume > 1e-4 * vol
                        except Exception:
                            return False

                    how, hit_at = MC.way_in(overlap_at, travel, SAMPLES)
                    if how == "clear":
                        r["clear"] = True
                    elif how == "overlaps":
                        r["overlapsInPlace"] = True
                        r["note"] = "Overlaps a part already there where it sits: an interference fit, or the model is wrong (two bodies in the same place). The way in was not swept."
                    else:
                        r["blockedShortBy"] = round(hit_at, 2)
                        r["note"] = f"Runs into a part already there {hit_at:.1f} mm short of its place: another way in, or an earlier step for this part."
                else:
                    r["clear"] = True
                r["move"] = [round(float(x), 3) for x in move]
                r["travel"] = round(travel, 2)
                if sh is not None:
                    there.append(sh)
                row["parts"].append(r)
            lintf = MC.lint(st.get("text") or "", m["style"])
            if lintf:
                row["lint"] = lintf
            report.append(row)
        problems, unplaced = MC.check_plan(m)
        blocked = sum(1 for r in report for p in r["parts"] if "blockedShortBy" in p or p.get("overlapsInPlace"))
        out = {"steps": report, "blocked": blocked, "lintFindings": sum(len(r.get("lint", [])) for r in report)}
        if problems:
            out["problems"] = problems
        if unplaced:
            out["unplaced"] = unplaced
        return out

    def manual_render(a):
        R = lent.render()

        m = mstate(session)
        if not m["steps"]:
            raise ToolError("invalid_state", "No steps: manual_plan { steps } first.")
        w, h = int(a.get("width", 900)), int(a.get("height", 640))
        explode = float(m["settings"].get("explode", 1.0))
        colours, pictures = {}, {}
        k = 0

        def layer(sh, colour, name):
            pts, tris = sh.tessellate(0.1)
            if not tris:
                return None
            return {"name": name, "V": np.array([[p.x, p.y, p.z] for p in pts], float), "F": np.array(tris, np.int64).reshape(-1, 3), "color": colour, "creases": True}

        def arrow(frm, to, colour, size):
            import FreeCAD
            import Part

            d = np.asarray(to) - np.asarray(frm)
            L = float(np.linalg.norm(d))
            if L < 1e-6:
                return None
            u = FreeCAD.Vector(*(d / L))
            r = max(0.15, 0.012 * size)
            head = min(L * 0.35, 6 * r)
            shaft = Part.makeCylinder(r, L - head, FreeCAD.Vector(*frm), u)
            cone = Part.makeCone(2.6 * r, 0, head, FreeCAD.Vector(*(np.asarray(frm) + d / L * (L - head))), u)
            return layer(shaft.fuse(cone), colour, "arrow")

        for i, st, before, places in walk(m):
            layers = [layer(s, GREY, n) for n, s in before]
            size = 1.0
            for pl, sh, move, travel in places:
                if sh is None:
                    continue
                size = max(size, sh.BoundBox.DiagonalLength)
                c = R.PALETTE[k % len(R.PALETTE)]
                k += 1
                colours[pl["part"]] = c
                off = -move * travel * explode
                moved = sh.copy()
                moved.translate(tuple(off))
                layers.append(layer(moved, c, pl["part"]))
                ctr = np.array(tuple(sh.BoundBox.Center))
                if explode > 0:
                    layers.append(arrow(ctr + off, ctr + 0.15 * off, c, size))
            layers = [x for x in layers if x is not None]
            if not layers:
                continue
            view = st.get("view") or m["settings"].get("view", "iso")
            if view not in R.VIEWS:
                raise ToolError("invalid_input", f"Step {i + 1} view: {', '.join(R.VIEWS)}.")
            img, _mm, drawn = R.draw(layers, view, w, h)[:3]
            if drawn:
                bg = np.all(np.abs(img - R.BG) < 1e-6, axis=2)
                img = img.copy()
                img[bg] = (0.96, 0.96, 0.97)
                pictures[i] = R.png(img)
        page = MC.html_manual(m, pictures, colours)
        stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in m["settings"]["title"]).strip("_") or "manual"
        path = a.get("path") or os.path.join(session.out_dir, f"{stem}.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(page)
        lint = {f"step {r + 1}": MC.lint(s.get("text") or "", m["style"]) for r, s in enumerate(m["steps"])}
        lint = {k2: v for k2, v in lint.items() if v}
        return {"file": {"path": path, "name": os.path.basename(path), "bytes": os.path.getsize(path)}, "steps": len(m["steps"]), "pictures": len(pictures),
                **({"lint": lint} if lint else {}),
                "note": "One HTML page with its pictures inside: open it in a browser, print it to PDF. manual_check first if the ways in are not checked."}

    return {
        "manual_plan": manual_plan,
        "manual_check": manual_check,
        "manual_render": manual_render,
    }


NAMES = ("manual_plan", "manual_check", "manual_render")
HANDLERS = _bind.table(bind, NAMES)
