# SPDX-License-Identifier: AGPL-3.0-only
# Library pack: a finished part bundled for sharing — its bodies as STL,
# 3MF and STEP, renders, files the person adds (the sliced 3MF, photos,
# the assembly manual), a README with attribution, a LICENSE — each upstream
# part's licence checked against the pack's, and personal details taken out
# of every file first. A zip with the person's files; they upload it
# themselves. ScanRuler's library-pack plugin, for Agent Link. Ported from
# ScanRuler by CNC Kitchen: plugins/library-pack/app/packCommands.ts.

import datetime
import io
import json
import os
import zipfile

import numpy as np

from .. import lent
from .. import pack_core as P
from .. import scanstate as S
from ..errors import ToolError
from . import _bind

VIEWS = ["iso", "iso-rear-left", "front", "top", "right", "iso-front-left"]


def obj(props, required=()):
    return {"type": "object", "properties": props, "required": list(required), "additionalProperties": False}


def pstate(session):
    st = S.state(session)
    return st.setdefault("pack", {"settings": dict(P.DEFAULT_PACK), "bodies": None, "files": [], "upstream": None})


# Files that hold printer keys: never in a pack (red team 3, R3-8).
NEVER_PACK = {"printers.json", ".agentlink-printers.json"}


def _pack_file(session, f):
    """f when it may go in a pack, else a refusal (red team 3, R3-8): a
    file in the session's folder, not hidden and not in a hidden folder,
    not a printer file, not Agent Link's own state. There is no file
    picker for the pack yet, so a file from anywhere else is refused: the
    person copies it into the session's folder first."""
    from .. import guard

    shown = guard.tilde(f)
    if not isinstance(f, str) or not os.path.isfile(f):
        raise ToolError("not_found", f"No such file: {shown}.")
    real = os.path.realpath(f)
    if os.path.basename(f).casefold() in NEVER_PACK or os.path.basename(real).casefold() in NEVER_PACK:
        raise ToolError("invalid_input", f"files: {shown} holds printer keys. It never goes in a pack.")
    out = os.path.realpath(session.out_dir) if getattr(session, "out_dir", None) else None
    if not out or out == "/" or not real.startswith(out.rstrip("/") + "/"):
        raise ToolError("invalid_input", f"files: {shown} is not in the session's folder ({guard.tilde(out or 'none')}). "
                                         "Only files in that folder go in a pack: the person copies the file there first.")
    hidden = [x for x in os.path.relpath(real, out).split(os.sep) if x.startswith(".")]
    if hidden or os.path.basename(f).startswith("."):
        raise ToolError("invalid_input", f"files: {shown} is hidden ({(hidden or [os.path.basename(f)])[0]}). Hidden files never go in a pack.")
    state = lent.AGENTLINK_STATE(real, out) if lent.AGENTLINK_STATE else None
    if state:
        raise ToolError("invalid_input", f"files: {shown} is Agent Link's own state ({state}). It never goes in a pack.")
    return f


def _safe(name):
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in name).strip("_") or "part"


def bind(session):
    """{tool name: fn(args)} for one session (Agent Link's, or the
    add-on's own runner's context)."""
    def provenance_upstream():
        try:
            with open(os.path.join(session.out_dir, "provenance.json"), encoding="utf-8") as f:
                files = json.load(f).get("files", [])
        except (OSError, ValueError):
            return []
        return [{"part": r["file"], "source": r.get("source"), "url": r.get("page"), "licence": r.get("licence"), "author": r.get("author"),
                 "title": r.get("title"), **({"redistribute": r["shareable"]} if "shareable" in r else {})} for r in files]

    def upstream_of(ps):
        return ps["upstream"] if ps["upstream"] is not None else provenance_upstream()

    def bodies_of(ps):
        if ps["bodies"] is not None:
            return [session.body(b) for b in ps["bodies"]]
        return session.bodies()

    def pack_setup(a):
        ps = pstate(session)
        s = ps["settings"]
        for k in ("title", "author", "summary", "printSettings", "includeStep", "include3mf", "renders"):
            if a.get(k) is not None:
                s[k] = a[k]
        if a.get("licence") is not None:
            lid = P.read_licence(a["licence"])
            if not lid:
                raise ToolError("invalid_input", f"licence {a['licence']!r}: one of {', '.join(P.LICENCES)}.")
            s["licence"] = lid
        if a.get("bodies") is not None:
            for b in a["bodies"]:
                session.body(b)
            ps["bodies"] = a["bodies"]
        if a.get("files") is not None:
            ps["files"] = [_pack_file(session, f) for f in a["files"]]
        if a.get("upstream") is not None:
            ps["upstream"] = a["upstream"]
        return {"settings": s, "bodies": ps["bodies"] or [o.Label for o in session.bodies()], "files": ps["files"], "upstream": upstream_of(ps),
                "licences": {k: v["short"] for k, v in P.LICENCES.items()},
                "note": "upstream comes from catalog_provenance until set here: the parts this design took from others, with their licences."}

    def pack_plan(a):
        ps = pstate(session)
        pl = P.plan(ps["settings"], upstream_of(ps))
        return {**pl, "bodies": [o.Label for o in bodies_of(ps)], "files": ps["files"],
                "note": "A guide from each licence's terms as commonly read, not legal advice: the person confirms each upstream licence."}

    def pack_write(a):
        R = lent.render()

        ps = pstate(session)
        s = ps["settings"]
        pl = P.plan(s, upstream_of(ps))
        if not pl["ok"]:
            raise ToolError("invalid_state", "The pack can't go out yet: " + "; ".join(pl["problems"] + [f"{b['part']}: {b['why']}" for b in pl["blocked"]]))
        bodies = bodies_of(ps)
        if not bodies:
            raise ToolError("invalid_state", "No body to pack.")
        left = {x.get("body") for x in pl["leftOut"] if x.get("body")}
        bodies = [o for o in bodies if o.Label not in left]
        entries = {}
        import tempfile

        import Mesh

        tmp = tempfile.mkdtemp()
        for o in bodies:
            stem = _safe(o.Label)
            for ext, on in (("stl", True), ("3mf", s.get("include3mf", True))):
                if on:
                    p = os.path.join(tmp, f"{stem}.{ext}")
                    Mesh.export([o], p)
                    with open(p, "rb") as f:
                        entries[f"models/{stem}.{ext}"] = f.read()
            if s.get("includeStep", True):
                p = os.path.join(tmp, f"{stem}.step")
                o.Shape.exportStep(p)
                with open(p, "rb") as f:
                    entries[f"models/{stem}.step"] = f.read()
        n = max(0, min(6, int(s.get("renders", 4))))
        layers = [R.body_layer(o, i) for i, o in enumerate(bodies)]
        for v in VIEWS[:n]:
            img, _mm, drawn = R.draw(layers, v, 1200, 900)[:3]
            if drawn:
                bg = np.all(np.abs(img - R.BG) < 1e-6, axis=2)
                img = img.copy()
                img[bg] = (0.96, 0.96, 0.97)
                entries[f"images/{v}.png"] = R.png(img)
        for f in ps["files"]:
            _pack_file(session, f)  # checked again: the folder can have changed since pack_setup
            with open(f, "rb") as fh:
                entries[f"files/{os.path.basename(f)}"] = fh.read()
        users, changes = set(), []
        from .. import guard

        for k in list(entries):
            try:
                entries[k], ch = P.scrub_file(k, entries[k], users)
            except guard.TooLarge as e:
                raise ToolError("invalid_input", f"{k}: {e}") from None
            changes += ch
        year = datetime.date.today().year
        entries["LICENSE"] = P.licence_file(s["licence"], s["author"], year).encode()
        scrubbed = {}
        for c in changes:
            scrubbed[c["what"]] = scrubbed.get(c["what"], 0) + c["count"]
        entries["README.md"] = P.readme(s, pl, sorted(entries), scrubbed).encode()
        path = a.get("path") or os.path.join(session.out_dir, f"{_safe(s['title'])}.zip")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for k in sorted(entries):
                z.writestr(k, entries[k])
        with open(path, "wb") as f:
            f.write(buf.getvalue())
        return {"file": {"path": path, "name": os.path.basename(path), "bytes": os.path.getsize(path)}, "contents": sorted(entries),
                "scrubbed": [{"what": w, "count": c} for w, c in scrubbed.items()], "credited": pl["credited"], "leftOut": pl["leftOut"],
                "note": "Read README.md before uploading; the upload is the person's to do."}

    return {
        "pack_setup": pack_setup,
        "pack_plan": pack_plan,
        "pack_write": pack_write,
    }


NAMES = ("pack_setup", "pack_plan", "pack_write")
HANDLERS = _bind.table(bind, NAMES)
