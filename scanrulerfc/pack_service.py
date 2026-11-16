# SPDX-License-Identifier: AGPL-3.0-only
"""ScanRuler's library pack (Stefan Hermann's, CNC Kitchen: the
library-pack plugin, ported as pack_core and handlers/pack.py) as a
service: whoever owns a Library Pack command (Workshop Documents, through
Agent Link's hooks.service("library_pack")) hands it its library_pack
arguments, and it runs pack_setup, pack_plan and pack_write on them. Each
add-on works alone; with both installed this one makes the pack, and
Documents leaves its own library_pack tool unlisted so the agent sees the
pack_* tools only. agentlink_families provides it; nothing here imports
Agent Link.

Documents' arguments, mapped: bodies; name -> title; description ->
summary; license -> licence; author; credits [{title, author, url,
license, changes}] -> upstream (each credited part, modified when it names
changes; left out, the provenance catalog_provenance kept is used);
formats -> includeStep (STL is always in; Documents' formats have no 3MF,
so none is written); path (or out) -> where the zip goes. tolerance is
Documents' own meshing and is not used here."""
import os

from . import CREDIT
from .errors import ToolError


def setup_args(a):
    """Documents' library_pack arguments as pack_setup's."""
    out = {"include3mf": False}
    if a.get("bodies") is not None:
        out["bodies"] = list(a["bodies"])
    if a.get("name"):
        out["title"] = a["name"]
    if a.get("description") is not None:
        out["summary"] = a["description"]
    if a.get("license") is not None:
        out["licence"] = a["license"]
    if a.get("author") is not None:
        out["author"] = a["author"]
    formats = a.get("formats")
    if formats is not None:
        if not formats or any(f not in ("step", "stl") for f in formats):
            raise ToolError("invalid_input", "formats: step, stl or both.")
        out["includeStep"] = "step" in formats
    credits = a.get("credits")
    if credits is not None:
        if not isinstance(credits, list) or not all(isinstance(c, dict) for c in credits):
            raise ToolError("invalid_input", "credits: [{ title, author, url, license, changes }] for each remixed part.")
        out["upstream"] = [{"part": c.get("title") or c.get("url") or f"part {i + 1}", **({"title": c["title"]} if c.get("title") else {}),
                            **({"author": c["author"]} if c.get("author") else {}), **({"url": c["url"]} if c.get("url") else {}),
                            "licence": c.get("license"), "modified": bool(c.get("changes", True))}
                           for i, c in enumerate(credits)]
    return out


def answer(written, plan, licence, bodies):
    """pack_write's answer in library_pack's shape (pack, files, license,
    parts, bytes), with ScanRuler's own fields beside it."""
    contents = written["contents"]
    parts = []
    for b in bodies:
        stem = "".join(c if c.isalnum() or c in "-_." else "_" for c in b).strip("_") or "part"
        parts.append({"body": b, "files": [os.path.basename(n) for n in contents if n.startswith(f"models/{stem}.")]})
    out = {"pack": written["file"]["path"], "files": contents, "license": licence, "parts": parts, "bytes": written["file"]["bytes"],
           "by": "ScanRuler", "credit": CREDIT, "credited": written.get("credited", plan.get("credited", [])),
           "leftOut": written.get("leftOut", []), "scrubbed": written.get("scrubbed", [])}
    if written.get("note"):
        out["note"] = written["note"]
    return out


def _tools(session):
    from .handlers import pack

    return pack.bind(session)


class LibraryPack:
    NAME = "ScanRuler"
    credit = CREDIT

    def __init__(self, tools=None):
        self._tools = tools or _tools  # fn(session) -> {pack_setup, pack_plan, pack_write}

    def pack(self, session, a):
        """The pack of Documents' library_pack arguments; a refusal raises
        ToolError (code, message) in ScanRuler's words."""
        t = self._tools(session)
        setup = t["pack_setup"](setup_args(a))
        plan = t["pack_plan"]({})
        path = a.get("path") or a.get("out")
        written = t["pack_write"]({"path": path} if path else {})
        bodies = plan.get("bodies") or setup.get("bodies") or []
        return answer(written, plan, plan.get("licence") or setup.get("settings", {}).get("licence"), bodies)
