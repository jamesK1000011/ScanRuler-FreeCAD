# SPDX-License-Identifier: AGPL-3.0-only
# Ported from ScanRuler by Stefan Hermann (CNC Kitchen),
# github.com/CNCKitchen/ScanRuler: src/core/project/manifest.ts (what a
# .scanruler project carries).
#
# Load for a .scanruler project, so the original's users bring their work
# across (design 10, question 2). A project is a zip: project.json (the
# manifest) first, then the model files (scan.<ext>, reference.<ext>, …).
# What this port can take goes through the tools, as a person's keys do:
# the scan through scan_open, each fitted element from its seed vertices
# through element_fit, each section from its plane through section_cut.
# The Reverse engineer part (the manifest's `reverse` key and its STEP
# member) goes through reverse/part_file.py into the document's
# ScanRulerReverse container (reverse/doc.py), after the scan, so its
# plane and axis references find their elements; without FreeCAD it is
# named as not loaded. Anything else is named as not loaded too.
# `load(path, run)` takes a runner(tool, args) -> (ok, result) and answers
# what it did.
import json
import os
import shutil
import tempfile
import zipfile

from . import guard
from .errors import ToolError

APP = "ScanRuler"
SCHEMA = 1
MANIFEST = "project.json"
KINDS = ("plane", "sphere", "cylinder", "cone", "torus", "point", "circle")
REVERSE_LATER = "Reverse engineer data: needs FreeCAD's Part kernel to build — not loaded."


def read_manifest(zf):
    try:
        m = json.loads(guard.zip_read(zf, MANIFEST, "project.json", 64 * 1024 * 1024).decode("utf-8"))
    except guard.TooLarge as e:
        raise ToolError("invalid_input", str(e))
    except KeyError:
        raise ToolError("invalid_input", "Not a ScanRuler project file: it holds no project.json.")
    except ValueError as e:
        raise ToolError("invalid_input", f"Not a ScanRuler project file: project.json is not JSON ({e}).")
    if not isinstance(m, dict) or m.get("app") != APP or not isinstance(m.get("schemaVersion"), int):
        raise ToolError("invalid_input", "Not a ScanRuler project file.")
    if m["schemaVersion"] > SCHEMA:
        raise ToolError("invalid_input", "This project was saved by a newer version of ScanRuler than this port reads.")
    return m


def _name(x):
    """A name from the project file, cleaned for the agent (red team 3,
    R3-11), or None."""
    n = x.get("name")
    return guard.text(n, 120) or None if isinstance(n, str) else None


def _element_call(e):
    e = {**e, "name": _name(e)}
    src = e.get("source") or {}
    kind = e.get("kind")
    if kind not in KINDS:
        kind = guard.text(kind, 40)
        return None, f"{e.get('name') or kind}: a {kind} is not fitted here."
    if src.get("type") != "fitted":
        return None, f"{e.get('name') or kind}: {guard.text(src.get('type'), 40) or 'this'} elements are not loaded yet."
    seeds = [int(v) for v in (src.get("seeds") or [])]
    if not seeds:
        return None, f"{e.get('name') or kind}: fitted on a marked region — fit it again (element_fit_marked)."
    args = {"kind": kind, "at": [{"vertex": v} for v in seeds] if len(seeds) > 1 else {"vertex": seeds[0]}}
    if e.get("name"):
        args["name"] = e["name"]
    return args, None


def _section_call(s):
    s = {**s, "name": _name(s)}
    frame = s.get("frame") or {}
    if not (frame.get("origin") and frame.get("normal")):
        return None, f"{s.get('name') or 'A section'}: no plane in the file."
    args = {"across": {"origin": list(frame["origin"]), "normal": list(frame["normal"])}}
    if s.get("name"):
        args["name"] = s["name"]
    if s.get("kind") in ("cut", "shadow"):
        args["kind"] = s["kind"]
    return args, None


def _freecad_doc():
    """The active FreeCAD document (a new one if none), or None without
    FreeCAD and its Part kernel."""
    try:
        import FreeCAD
        import Part  # noqa: F401 — the kernel the part builds on
    except ImportError:
        return None
    return FreeCAD.ActiveDocument or FreeCAD.newDocument("ScanRuler")


def _reverse(path, doc_fn, out):
    """The Reverse engineer part into the document's container: out
    ["reverse"] {features, failed}, or why not in notLoaded / errors."""
    from .reverse import doc as RD
    from .reverse import part_file as PF

    doc = (doc_fn or _freecad_doc)()
    if doc is None:
        out["notLoaded"].append(REVERSE_LATER)
        return
    try:
        part, members = PF.read_scanruler(path)
        if part is None:
            return
        results = RD.import_part(doc, part, members, out["project"])
    except Exception as e:  # noqa: BLE001 — the rest of the project stands
        out["errors"].append({"tool": "reverse", "code": "failed", "message": f"Reverse engineer data: {e}"})
        return
    out["reverse"] = {"features": len(part.get("features") or []), "failed": sum(1 for r in results if r.get("status") == "failed")}


def load(path, run, folder=None, doc_fn=None):
    """Open the project's scan, elements and sections through run, then its
    Reverse engineer part in doc_fn()'s document (the active one by
    default); answer {"project", "scan", "elements", "sections", "reverse",
    "notLoaded", "errors"}."""
    out = _load(path, run, folder)
    if out.pop("_reverse", False):
        _reverse(path, doc_fn, out)
    return out


def _load(path, run, folder=None):
    """_load_in with the scan's copy in a temporary folder of its own when
    no folder is given; that folder is removed after the call (red team 3,
    R3-13: copies of private scans stayed in the temporary folder)."""
    if folder is not None:
        return _load_in(path, run, folder)
    tmp = tempfile.mkdtemp(prefix="scanruler-")
    try:
        return _load_in(path, run, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _load_in(path, run, folder):
    try:
        zf = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as e:
        raise ToolError("invalid_input", f"{guard.text(os.path.basename(path), 80)}: not a ScanRuler project file ({e}).")
    out = {"project": None, "scan": None, "elements": 0, "sections": 0, "reverse": None, "notLoaded": [], "errors": []}
    with zf:
        # A project from the web: refused before it is unpacked when it is
        # a ZIP bomb (red team 3, R3-6).
        try:
            guard.zip_check(zf, os.path.basename(path))
        except guard.TooLarge as e:
            raise ToolError("invalid_input", guard.text(str(e), 300))
        m = read_manifest(zf)
        # The name is text from the file: cleaned before the agent reads it (R3-11).
        out["project"] = guard.text(m.get("name") if isinstance(m.get("name"), str) and m.get("name") else os.path.splitext(os.path.basename(path))[0], 120)
        out["_reverse"] = bool(m.get("reverse"))
        scan = m.get("scan")
        members = zf.namelist()
        if not scan:
            return out
        member, name = scan.get("member"), guard.text(os.path.basename(str(scan.get("fileName") or "scan.stl")), 120)
        if name in ("", ".", ".."):
            name = "scan.stl"
        if member not in members:
            raise ToolError("invalid_input", f"The project names a scan ({guard.text(member, 80)}) it does not hold.")
        target = os.path.join(folder, name)
        try:
            data = guard.zip_read(zf, member, "the project's scan", guard.MAX_SCAN_BYTES)
        except guard.TooLarge as e:
            raise ToolError("invalid_input", str(e))
        with open(target, "wb") as f:
            f.write(data)
    args = {"path": target, "discard": True}
    if scan.get("units") in ("mm", "cm", "m", "in"):
        args["units"] = scan["units"]
    ok, got = run("scan_open", args)
    if not ok:
        out["errors"].append({"tool": "scan_open", **got["error"]})
        return out
    out["scan"] = name
    if scan.get("appliedAlignment"):
        out["notLoaded"].append("The alignment the scan was moved by: align it again (align_datum or align_auto).")
    for kind, items, make in (("elements", scan.get("elements") or [], _element_call), ("sections", scan.get("sections") or [], _section_call)):
        tool = "element_fit" if kind == "elements" else "section_cut"
        for item in items:
            a, why = make(item)
            if a is None:
                out["notLoaded"].append(why)
                continue
            ok, got = run(tool, a)
            if ok:
                out[kind] += 1
            else:
                out["errors"].append({"tool": tool, "name": a.get("name"), **got["error"]})
    if scan.get("dimensions"):
        out["notLoaded"].append(f"{len(scan['dimensions'])} dimensions: add them again on the loaded elements (dimension_add).")
    for stem, what in (("reference", "The deviation reference: open it again (deviation_open_reference)."),
                       ("image", "The 2D Measure image: open it again in 2D Measure.")):
        if any(n.startswith(stem + ".") for n in members):
            out["notLoaded"].append(what)
    return out
