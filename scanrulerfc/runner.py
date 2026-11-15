# SPDX-License-Identifier: AGPL-3.0-only
"""ScanRuler for FreeCAD's own runner: runner(tool, args) -> (ok, result),
the way its panels and commands call a tool without Agent Link. It calls
the same handler Agent Link's family binds (scanrulerfc/handlers) in a
context of its own for the document, one undo transaction per changing
call (data/tools.json "changes"), and answers in the shape Agent Link's
panel._call does: the tool's answer as JSON data (NaN as null), or
{"error": {"code", "message"}} with ok False. Under Agent Link the panels
get panel._call instead. No Agent Link import here."""
import json
import math
import os

from . import errors, handlers

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
_DECLARED = {}


def declared():
    """data/tools.json's entries: {tool name: its declaration}."""
    if not _DECLARED:
        with open(os.path.join(DATA, "tools.json"), encoding="utf-8") as f:
            _DECLARED.update(json.load(f)["entries"])
    return _DECLARED


def changes(tool):
    return bool(declared().get(tool, {}).get("changes"))


PASSIVE = ("App::DocumentObjectGroup", "Spreadsheet::Sheet", "App::Part", "Assembly::AssemblyObject", "Assembly::JointGroup")


def _solid(o):
    try:
        return hasattr(o, "Shape") and not o.Shape.isNull() and bool(o.Shape.Solids)
    except Exception:
        return False


def bodies_in(doc):
    """The parts a person would name: shown solids nothing else is built
    from (a PartDesign Body, not its features), as Agent Link counts them."""
    out = []
    for o in getattr(doc, "Objects", None) or []:
        if not _solid(o):
            continue
        if any(getattr(p, "TypeId", "") not in PASSIVE and _solid(p) for p in getattr(o, "InList", [])):
            continue
        try:
            parent = o.getParentGeoFeatureGroup()
        except Exception:
            parent = None
        if parent is not None and getattr(parent, "TypeId", "") == "PartDesign::Body":
            continue
        if getattr(o, "Visibility", True) is False:
            continue
        out.append(o)
    return out


class Context:
    """What a handler is given alone: the document (None: no document,
    for the tools that need none), each family's state while the document
    is open, the folder files go to (beside the saved document, else
    ~/ScanRuler). snapshot() keeps nothing: Agent Link's step log is
    Agent Link's."""

    def __init__(self, doc=None, out_dir=None):
        self.doc = doc
        self.family_state = {}
        self._out = out_dir

    @property
    def out_dir(self):
        d = self._out
        if not d:
            fn = getattr(self.doc, "FileName", "") or ""
            d = os.path.dirname(fn) if fn else os.path.expanduser("~/ScanRuler")
        os.makedirs(d, exist_ok=True)
        return d

    def bodies(self):
        return bodies_in(self.doc)

    def body(self, ref):
        if ref is not None:
            for o in getattr(self.doc, "Objects", None) or []:
                if _solid(o) and (o.Label == ref or o.Name == ref or o.Label.lower() == str(ref).lower()):
                    return o
        bs = self.bodies()
        if not bs:
            raise errors.ToolError("not_found", "No body in the document: make one first.")
        if ref is None:
            if len(bs) == 1:
                return bs[0]
            raise errors.ToolError("invalid_input", f"body: say which — {', '.join(o.Label for o in bs)}.")
        raise errors.ToolError("not_found", f"body {ref!r}: not here — the bodies: {', '.join(o.Label for o in bs)}.")

    def unique(self, label, own=None):
        """label, or "label 2" … when another object has it."""
        taken = {o.Label for o in (getattr(self.doc, "Objects", None) or []) if o is not own}
        if label not in taken:
            return label
        n = 2
        while f"{label} {n}" in taken:
            n += 1
        return f"{label} {n}"

    def snapshot(self, tool):
        pass


_CONTEXTS = {}


def context_for(doc):
    """One context per open document, so its families' state lasts."""
    key = id(doc)
    c = _CONTEXTS.get(key)
    if c is None or c.doc is not doc:
        c = _CONTEXTS[key] = Context(doc)
    return c


def _active_doc():
    import FreeCAD

    return FreeCAD.ActiveDocument or FreeCAD.newDocument("ScanRuler")


def _finite(o):
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: _finite(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_finite(v) for v in o]
    return o


def plain(out):
    """An answer as JSON reads it back (what Agent Link's panel._call gives)."""
    try:
        text = json.dumps(out, ensure_ascii=False, allow_nan=False, default=str)
    except ValueError:
        text = json.dumps(_finite(out), ensure_ascii=False, allow_nan=False, default=str)
    return json.loads(text)


def answer(fn, args):
    """(ok, result) of fn(args): JSON data, a refusal {"error": {code, message}}."""
    try:
        out = fn(args)
    except errors.REFUSED as e:
        return False, {"error": {"code": e.code, "message": e.message}}
    except Exception as e:  # noqa: BLE001 — a panel shows a failure, never a crash
        return False, {"error": {"code": "failed", "message": f"{type(e).__name__}: {e}"}}
    return True, plain(out)


def local(doc_fn=None, table=None, ctx=None):
    """runner(tool, args) -> (ok, result) over this add-on's handlers, in
    the document doc_fn() gives (the active one by default), or in ctx."""
    table = table or handlers.all_handlers()

    def run(tool, args=None):
        args = dict(args or {})
        fn = table.get(tool)
        if fn is None:
            return False, {"error": {"code": "not_found", "message": f"{tool}: not a tool of ScanRuler for FreeCAD."}}
        c = ctx if ctx is not None else context_for((doc_fn or _active_doc)())
        doc = c.doc
        if not changes(tool) or doc is None:
            return answer(lambda a: fn(c, a), args)
        doc.openTransaction(tool)
        ok, out = answer(lambda a: fn(c, a), args)
        if ok:
            doc.commitTransaction()
        else:
            doc.abortTransaction()
        return ok, out

    return run
