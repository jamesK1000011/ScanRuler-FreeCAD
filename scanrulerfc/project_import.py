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
# Reverse engineer data waits for the engine port; anything else is named
# as not loaded. `load(path, run)` takes a runner(tool, args) -> (ok,
# result) and answers what it did.
import json
import os
import tempfile
import zipfile

from .errors import ToolError

APP = "ScanRuler"
SCHEMA = 1
MANIFEST = "project.json"
KINDS = ("plane", "sphere", "cylinder", "cone", "torus", "point", "circle")
REVERSE_LATER = "Reverse engineer data: coming with the engine port — not loaded."


def read_manifest(zf):
    try:
        m = json.loads(zf.read(MANIFEST).decode("utf-8"))
    except KeyError:
        raise ToolError("invalid_input", "Not a ScanRuler project file: it holds no project.json.")
    except ValueError as e:
        raise ToolError("invalid_input", f"Not a ScanRuler project file: project.json is not JSON ({e}).")
    if not isinstance(m, dict) or m.get("app") != APP or not isinstance(m.get("schemaVersion"), int):
        raise ToolError("invalid_input", "Not a ScanRuler project file.")
    if m["schemaVersion"] > SCHEMA:
        raise ToolError("invalid_input", "This project was saved by a newer version of ScanRuler than this port reads.")
    return m


def _element_call(e):
    src = e.get("source") or {}
    kind = e.get("kind")
    if kind not in KINDS:
        return None, f"{e.get('name') or kind}: a {kind} is not fitted here."
    if src.get("type") != "fitted":
        return None, f"{e.get('name') or kind}: {src.get('type') or 'this'} elements are not loaded yet."
    seeds = [int(v) for v in (src.get("seeds") or [])]
    if not seeds:
        return None, f"{e.get('name') or kind}: fitted on a marked region — fit it again (element_fit_marked)."
    args = {"kind": kind, "at": [{"vertex": v} for v in seeds] if len(seeds) > 1 else {"vertex": seeds[0]}}
    if e.get("name"):
        args["name"] = e["name"]
    return args, None


def _section_call(s):
    frame = s.get("frame") or {}
    if not (frame.get("origin") and frame.get("normal")):
        return None, f"{s.get('name') or 'A section'}: no plane in the file."
    args = {"across": {"origin": list(frame["origin"]), "normal": list(frame["normal"])}}
    if s.get("name"):
        args["name"] = s["name"]
    if s.get("kind") in ("cut", "shadow"):
        args["kind"] = s["kind"]
    return args, None


def load(path, run, folder=None):
    """Open the project's scan, elements and sections through run; answer
    {"project", "scan", "elements", "sections", "notLoaded", "errors"}."""
    try:
        zf = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as e:
        raise ToolError("invalid_input", f"{os.path.basename(path)}: not a ScanRuler project file ({e}).")
    out = {"project": None, "scan": None, "elements": 0, "sections": 0, "notLoaded": [], "errors": []}
    with zf:
        m = read_manifest(zf)
        out["project"] = m.get("name") or os.path.splitext(os.path.basename(path))[0]
        if m.get("reverse"):
            out["notLoaded"].append(REVERSE_LATER)
        scan = m.get("scan")
        members = zf.namelist()
        if not scan:
            return out
        member, name = scan.get("member"), os.path.basename(scan.get("fileName") or "scan.stl")
        if member not in members:
            raise ToolError("invalid_input", f"The project names a scan ({member}) it does not hold.")
        folder = folder or tempfile.mkdtemp(prefix="scanruler-")
        target = os.path.join(folder, name)
        with open(target, "wb") as f:
            f.write(zf.read(member))
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
