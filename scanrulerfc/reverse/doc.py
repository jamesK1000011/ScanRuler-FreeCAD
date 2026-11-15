# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/app/projectSection.ts, state/reDrafts.ts (bodyColor), src/state/palette.ts
# SPDX-License-Identifier: AGPL-3.0-only
#
# The Reverse engineer workspace in a FreeCAD document: one container,
# ScanRulerReverse (Label "Reverse engineer"), whose PartJson is the
# original's `reverse` part exactly as a .scanruler holds it, and under it a
# ReverseBody for every body the build leaves. The features live in the
# container's list, as in the original: no PartDesign Body, no Sketcher.
#
#   container   Part::FeaturePython with a group. execute() parses PartJson,
#               evaluates the parameters, resolves the features against the
#               scan, builds (build.py, the prefix cache kept per container
#               in memory) and sets Results, Status and its own Shape (the
#               visible solid bodies as one compound). It raises only when
#               nothing can build; a feature that fails says so in Results.
#   body        Part::FeaturePython: Source (the container), BodyId (a float,
#               so island ids hold), Surface. execute() copies its shape
#               from the container's build. Matched by BodyId, so a name, a
#               colour or a link from outside survives a rebuild.
#
# Every edit is one transaction: edit(container, verb, name, change) opens
# "Reverse: <verb> <name>", writes PartJson, recomputes, adds and removes
# the bodies to match, and commits; undo puts PartJson and the bodies back.
# One edit is one build however often FreeCAD re-runs the container in it
# (_SETTLED); Results and Status are Output and NoRecompute.
# FreeCAD is imported where a document is touched, so this module imports
# anywhere.

import json

from .features import body_maker, island_of

CONTAINER = "ScanRulerReverse"
BODY = "ReverseBody"
LABEL = "Reverse engineer"
CREDIT = "Reverse engineer — ScanRuler by Stefan Hermann (CNC Kitchen), ported to FreeCAD"
PALETTE = ["#1877c0", "#e8590c", "#2e7d46", "#b5179e", "#c99a0a", "#0f9b9b", "#b3361c", "#6d4bbd"]

# FreeCAD's property attributes (App::PropertyType).
_READ_ONLY, _TRANSIENT, _OUTPUT, _NO_RECOMPUTE = 1, 2, 8, 16

# The Builder of each container, by document and object name: the prefix
# cache an undo or an edit further down rebuilds from.
_BUILDERS = {}
# Where the scan's sections and elements come from (scan_context.bind sets
# it): fn(doc) -> {sections, elements, modelCenter, scan}.
CONTEXT = {"of": None}
# While an edit runs, by container: the inputs its build was made from (None
# until it is made). FreeCAD runs the container again in the same edit
# however it is written: its Group puts it after its bodies in the
# dependency graph, so every body recompute re-runs it, and adding or
# removing a body touches it. Those runs find the inputs unchanged and keep
# the build, so one edit is one build; outside an edit every run builds.
_SETTLED = {}


def _inputs(obj):
    return tuple(str(getattr(obj, n, "")) for n in ("PartJson", "ScanRef", "Regions", "StepFiles"))


def body_color(i):
    """reDrafts bodyColor: by the feature that made the body, a further
    piece a colour further along."""
    return PALETTE[(body_maker(i) + 5 + 3 * island_of(i)) % len(PALETTE)]


def rgb(hex_color):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def transaction_label(verb, name=None):
    return f"Reverse: {verb}{f' {name}' if name else ''}"


def status_of(results):
    n = sum(1 for r in results if r.get("status") == "failed")
    return "ok" if n == 0 else f"{n} failed"


def body_plan(have, want):
    """Which body objects to add and which to remove: {add, remove, keep},
    ids in the build's order."""
    have = list(have)
    want = list(want)
    return {"add": [i for i in want if i not in have], "remove": [i for i in have if i not in want], "keep": [i for i in want if i in have]}


def empty_part():
    """A part with no features, as the original writes one."""
    from .part_file import PART_VERSION

    return {"version": PART_VERSION, "features": [], "nextFeatureId": 1, "nextOfKind": {}}


def part_of(text):
    """The part a PartJson holds, checked and migrated to the current
    version (part_file.py); an empty part for an empty string."""
    if not text:
        return empty_part()
    from .part_file import PART_VERSION, feature_from_json, loads, migrate_features, validate_reverse_part

    p = validate_reverse_part(loads(text))
    version = p.get("version") if p.get("version") is not None else 1
    if version != PART_VERSION:
        p = {**p, "version": PART_VERSION, "features": migrate_features([feature_from_json(f) for f in p["features"]], version)}
    return p


def built_features(part):
    """The features a build takes: those above the rollback bar (rolledTo,
    a count, absent when every feature is built)."""
    feats = part.get("features") or []
    rolled = part.get("rolledTo")
    return feats if rolled is None else feats[:max(0, min(len(feats), rolled))]


def use_scan(builder, scan):
    """The scan (V, F) the builder reads, handed over only when it is
    another: a new scan lets the kept states go (build_sheets set_scan)."""
    if not hasattr(builder, "set_scan"):
        return
    was = getattr(builder, "_scan_source", None)
    if scan is None and was is None:
        return
    if scan is not None and was is not None and scan[0] is was[0] and scan[1] is was[1]:
        return
    builder._scan_source = scan
    builder.set_scan(*(scan or (None, None)))


def build_part(part, builder, ctx=None):
    """Parameters evaluated, features resolved and built: the build's
    answer with the parameter readings."""
    from .parameters import apply_parameters, evaluate_parameters
    from .regions import find_regions
    from .resolve import resolve_features

    table = evaluate_parameters(part.get("parameters") or [])
    applied = apply_parameters(built_features(part), table["scope"])
    feats = applied["features"]
    ctx = ctx or {"sections": [], "elements": [], "modelCenter": [0, 0, 0]}
    use_scan(builder, ctx.get("scan"))
    steps = resolve_features(feats, ctx, lambda f: find_regions(f["sketch"]))
    sketches = {f["id"]: f["sketch"] for f in feats if f["kind"] == "sketch"}
    out = builder.build(steps, sketches.get, reuse=True)
    return {**out, "parameters": table["readings"]}


# ---- in a document (FreeCAD) ---------------------------------------------------------------------


def _key(obj):
    return (obj.Document.Name, obj.Name)


def builder_of(obj):
    from .build import Builder
    from .kernel import Kernel

    b = _BUILDERS.get(_key(obj))
    if b is None:
        b = _BUILDERS[_key(obj)] = Builder(Kernel())
    return b


class Container:
    """The proxy of a ScanRulerReverse container."""

    def __init__(self, obj):
        obj.Proxy = self
        self.setup(obj)

    def setup(self, obj):
        have = obj.PropertiesList
        for name, kind, doc, mode in (
            ("PartJson", "App::PropertyString", "The Reverse engineer part: the original's `reverse` JSON", 0),
            ("Regions", "App::PropertyFileIncluded", "Fit surface regions, packed", 0),
            ("StepFiles", "App::PropertyFileIncluded", "The imported STEP files (reverse-steps.json)", 0),
            ("ScanRef", "App::PropertyString", "The scan state the frames refer to", 0),
            ("Results", "App::PropertyString", "What the last build said of each feature", _OUTPUT | _TRANSIENT | _NO_RECOMPUTE),
            ("Status", "App::PropertyString", "ok, or how many features failed", _OUTPUT | _NO_RECOMPUTE),
            ("Credit", "App::PropertyString", "Whose engine this is", _READ_ONLY),
        ):
            if name not in have:
                obj.addProperty(kind, name, "Reverse", doc, mode)
        # The build's own answers: written in execute, they must not touch
        # the container for another recompute (older documents too).
        for name in ("Results", "Status"):
            try:
                obj.setPropertyStatus(name, ["Output", "NoRecompute"])
            except Exception:  # noqa: BLE001 — a FreeCAD without the call: the mode above stands
                pass
        if "Group" not in have:
            try:
                obj.addExtension("App::GroupExtensionPython")
            except TypeError:  # FreeCAD before 1.0 takes the extension's proxy too
                obj.addExtension("App::GroupExtensionPython", None)
        obj.Credit = CREDIT

    def onDocumentRestored(self, obj):
        self.setup(obj)

    def execute(self, obj):
        import Part

        k = _key(obj)
        if k in _SETTLED and _SETTLED[k] == _inputs(obj):
            return  # this edit's build stands: its bodies or its Group re-ran it
        try:
            part = part_of(obj.PartJson)
        except Exception as e:  # noqa: BLE001 — nothing can build: the one case that raises
            raise RuntimeError(f"The Reverse engineer part cannot be read: {e}") from e
        ctx = CONTEXT["of"](obj.Document) if CONTEXT["of"] else None
        builder_of(obj).step_files = step_texts(obj)
        out = build_part(part, builder_of(obj), ctx)
        obj.Results = json.dumps(out["results"])
        obj.Status = status_of(out["results"])
        hidden = set(part.get("hiddenBodies") or [])
        solids = [builder_of(obj).body(b["id"]) for b in out["bodies"] if not b["surface"] and b["id"] not in hidden]
        obj.Shape = Part.makeCompound([s for s in solids if s is not None])
        if k in _SETTLED:
            _SETTLED[k] = _inputs(obj)

    def dumps(self):
        return None

    def loads(self, state):
        return None

    __getstate__ = dumps
    __setstate__ = loads


class Body:
    """The proxy of a ReverseBody."""

    def __init__(self, obj):
        obj.Proxy = self
        for name, kind, doc in (("Source", "App::PropertyLink", "The Reverse engineer container"), ("BodyId", "App::PropertyFloat", "The body's id in the build (maker id, + n/1024 for a piece)"),
                                ("Surface", "App::PropertyBool", "A sheet, never exported alone")):
            if name not in obj.PropertiesList:
                obj.addProperty(kind, name, "Reverse", doc)

    def execute(self, obj):
        import Part

        src = obj.Source
        shape = builder_of(src).body(obj.BodyId) if src else None
        obj.Shape = shape.copy() if shape is not None else Part.Shape()

    def dumps(self):
        return None

    def loads(self, state):
        return None

    __getstate__ = dumps
    __setstate__ = loads


def make_container(doc, part=None):
    """A new container in `doc`, with `part` (an empty part by default)."""
    obj = doc.addObject("Part::FeaturePython", CONTAINER)
    Container(obj)
    obj.Label = LABEL
    from .part_file import dumps

    obj.PartJson = dumps(part or empty_part())
    if getattr(obj, "ViewObject", None) is not None:
        obj.ViewObject.Proxy = 0
    return obj


def find_container(doc):
    return next((o for o in doc.Objects if o.Name.startswith(CONTAINER) and hasattr(o, "PartJson")), None)


def bodies_of(container):
    return [o for o in container.Group if hasattr(o, "BodyId")]


def sync_bodies(container):
    """The container's bodies made to match the last build, by BodyId."""
    doc = container.Document
    built = builder_of(container).briefs()
    part = part_of(container.PartJson)
    styles = part.get("bodyStyles") or {}
    have = {o.BodyId: o for o in bodies_of(container)}
    plan = body_plan(have, [b["id"] for b in built])
    for i in plan["remove"]:
        o = have[i]
        container.removeObject(o)
        doc.removeObject(o.Name)
    for b in built:
        if b["id"] not in plan["add"]:
            continue
        o = doc.addObject("Part::FeaturePython", BODY)
        Body(o)
        o.Source = container
        o.BodyId = b["id"]
        o.Surface = b["surface"]
        o.Label = (styles.get(str(b["id"])) or {}).get("name") or b["name"]
        container.addObject(o)
        view = getattr(o, "ViewObject", None)
        if view is not None:
            view.Proxy = 0
            view.ShapeColor = rgb((styles.get(str(b["id"])) or {}).get("color") or body_color(b["id"]))
    return plan


def edit(container, verb, name, change):
    """One edit, one undo step: `change(part)` returns the part as it is to
    be (or None to leave it); PartJson written, the document recomputed,
    the bodies matched. Inside a transaction the caller opened (the
    runner's, Agent Link's) the edit is part of that one; otherwise it opens
    its own. Returns the build's results."""
    from .part_file import dumps

    doc = container.Document
    own = not getattr(doc, "HasPendingTransaction", False)
    if own:
        doc.openTransaction(transaction_label(verb, name))
    key = _key(container)
    _SETTLED[key] = None
    try:
        part = part_of(container.PartJson)
        new = change(part)
        if new is not None:
            container.PartJson = dumps(new)
        container.touch()
        doc.recompute()
        sync_bodies(container)
        # A body added to or taken from the Group touches the container
        # again, and the bodies' recompute re-runs it: the build is done
        # (_SETTLED), so only the bodies take their shapes.
        if hasattr(container, "purgeTouched"):
            container.purgeTouched()
        doc.recompute()
    except Exception:
        if own:
            doc.abortTransaction()
        raise
    finally:
        _SETTLED.pop(key, None)
    if own:
        doc.commitTransaction()
    return json.loads(container.Results or "[]")


def import_part(doc, part, members=None, name=None):
    """A .scanruler project's Reverse engineer part (part_file.read_scanruler:
    validated, its STEP texts' member in `members`) into doc's container,
    made if missing: PartJson the part (migrated on read, part_of), the STEP
    texts in StepFiles, one build. Returns the build's results."""
    import os
    import tempfile

    c = find_container(doc) or make_container(doc)
    data = (members or {}).get(part.get("stepFiles")) if isinstance(part.get("stepFiles"), str) else None

    def change(_was):
        if data:
            folder = tempfile.mkdtemp(prefix="scanruler-reverse-")
            path = os.path.join(folder, "reverse-steps.json")
            with open(path, "wb") as f:
                f.write(data if isinstance(data, (bytes, bytearray)) else str(data).encode("utf-8"))
            c.StepFiles = path
        return part

    return edit(c, "load", name, change)


def step_texts(container):
    """The STEP texts the container holds (StepFiles: reverse-steps.json,
    {key: text}), or {}."""
    path = str(getattr(container, "StepFiles", "") or "")
    if not path:
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)} if isinstance(data, dict) else {}


def put_step_file(container, key, text):
    """A STEP text kept in the container beside the ones it holds — call it
    inside an edit, so it is that edit's undo step."""
    import os
    import tempfile

    held = step_texts(container)
    if held.get(key) == text:
        return
    held[key] = text
    folder = tempfile.mkdtemp(prefix="scanruler-reverse-")
    path = os.path.join(folder, "reverse-steps.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(held, f)
    container.StepFiles = path


def forget(container):
    """Let go of a container's build (its document closed)."""
    _BUILDERS.pop(_key(container), None)
