# SPDX-License-Identifier: AGPL-3.0-only
# Parts catalog: a standard part named from measured dimensions, a part's
# nominal dimensions by name, search pages for its CAD with what each
# source's terms allow, and where each file brought in came from.
# ScanRuler's catalog plugin, for Agent Link. Ported from ScanRuler by CNC
# Kitchen: plugins/catalog/app/catalogCommands.ts.
#
# The library searches and downloads (Sketchfab, Thingiverse, Cults3D, Poly
# Haven, KiCad) run in scanruler-mcp's extras on the person's computer, not
# in FreeCAD; a file they bring in comes into the document with import_file.

import datetime
import json
import os

from .. import catalog_core as C
from ..errors import ToolError
from . import _bind

PROVENANCE = "provenance.json"


def obj(props, required=()):
    return {"type": "object", "properties": props, "required": list(required), "additionalProperties": False}


def _part(p):
    return {"designation": p["designation"], "kind": p["kind"], "standard": p["standard"], "dims": p["dims"]}


def bind(session):
    """{tool name: fn(args)} for one session (Agent Link's, or the
    add-on's own runner's context)."""
    def catalog_part(a):
        if a.get("designation"):
            hits = C.lookup(a["designation"])
            if not hits:
                raise ToolError("not_found", f"No standard part named {a['designation']!r}: try a size (\"M5\", \"608\") or catalog_part with no arguments for the kinds.")
            return {"parts": [_part(p) for p in hits[: a.get("limit", 20)]], "units": "mm"}
        dims = a.get("dims")
        if dims:
            kind = a.get("kind")
            got = C.match(dims, kind, a.get("limit", 5))
            if not got:
                fits = [k["kind"] for k in C.KINDS if all(d in k["dims"] for d in dims)]
                raise ToolError("invalid_input", f"No kind has all of {sorted(dims)}{' as ' + kind if kind else ''}: kinds with them — {fits or 'none'}. catalog_part with no arguments lists each kind's dimensions.")
            best = got[0]
            out = {"matches": [{**_part(m["part"]), "agree": m["agree"], "worst": m["worst"]} for m in got], "units": "mm"}
            # A measured part 5% off its nearest nominal is not that part.
            if best["worst"] <= 0.05 and (len(got) < 2 or got[1]["score"] > 4 * best["score"] + 1e-6):
                out["named"] = best["part"]["designation"]
            elif best["worst"] <= 0.05:
                out["note"] = f"{best['part']['designation']} and {got[1]['part']['designation']} fit nearly as well: measure another dimension ({', '.join(d for d in best['part']['dims'] if d not in dims) or 'more carefully'})."
            else:
                out["note"] = f"Nothing within 5%: the nearest, {best['part']['designation']}, is {best['worst']:.0%} off on one dimension — not a standard part here, or a dimension misread."
            return out
        return {"kinds": C.KINDS, "parts": len(C.PARTS), "note": "dims: the sizes measured, by these names; kind narrows it."}

    def catalog_links(a):
        ids = a.get("sources")
        bad = [i for i in ids or [] if i not in [s["id"] for s in C.SOURCES]]
        if bad:
            raise ToolError("invalid_input", f"sources: {', '.join(s['id'] for s in C.SOURCES)}.")
        return {"links": C.links(a["query"], ids), "note": "Search pages for the person to open; nothing is fetched or downloaded from here. A file they download comes in with import_file; record where it came from with catalog_provenance."}

    def _prov_path():
        return os.path.join(session.out_dir, PROVENANCE)

    def _prov():
        try:
            with open(_prov_path(), encoding="utf-8") as f:
                return json.load(f).get("files", [])
        except (OSError, ValueError):
            return []

    def catalog_provenance(a):
        files = _prov()
        if a.get("action", "list") == "record":
            r = a.get("record") or {}
            if not r.get("file") or not r.get("source"):
                raise ToolError("invalid_input", "record: { file, source, page?, licence?, shareable? }.")
            r = {**r, "at": datetime.date.today().isoformat()}
            files = [x for x in files if x["file"] != r["file"]] + [r]
            with open(_prov_path(), "w", encoding="utf-8") as f:
                json.dump({"kind": "scanruler.provenance", "version": 1, "files": files}, f, indent=1)
        return {"files": files, "path": _prov_path(),
                "note": "Files whose licence does not let them be shared on stay out of anything you share (shareable: false)."}

    return {
        "catalog_part": catalog_part,
        "catalog_links": catalog_links,
        "catalog_provenance": catalog_provenance,
    }


NAMES = ("catalog_part", "catalog_links", "catalog_provenance")
HANDLERS = _bind.table(bind, NAMES)
