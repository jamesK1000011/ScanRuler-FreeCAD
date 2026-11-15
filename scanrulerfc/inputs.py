# SPDX-License-Identifier: AGPL-3.0-only
"""Arguments checked against a tool's inputSchema (data/tools.json) before
the add-on's own runner calls it, refused as Agent Link's server refuses
them: code invalid_input and the same words, so a panel or the agent reads
one refusal whichever runs the tool. A copy of what the check needs from
Agent Link's agentlink/protocol.py (check_input), not an import: this
module loads without Agent Link."""
import json
import math

from .errors import ToolError

# The same thing by another common name: taken as the field the tool has,
# when that one is not given.
SYNONYMS = {
    "centre": ("center",), "center": ("centre",), "colour": ("color",), "color": ("colour",),
    "body": ("object", "part"), "object": ("body",), "part": ("body", "object"),
    "bodies": ("objects", "parts"), "objects": ("bodies",), "parts": ("bodies", "objects"),
    "file": ("path",), "filename": ("path", "file"), "path": ("file",),
}

_PY = {"string": (str,), "number": (int, float), "integer": (int,), "boolean": (bool,), "array": (list,), "object": (dict,)}


def check(schema, args):
    """Unknown keys and missing required ones refused by name; each given
    field checked (and coerced) against its type and enum. Changes args."""
    if not isinstance(args, dict):
        raise ToolError("invalid_input", "arguments: an object.")
    props = schema.get("properties", {})
    for k in [k for k in args if k not in props]:
        alt = next((s for s in SYNONYMS.get(k, ()) if s in props and s not in args), None)
        if alt is not None:
            args[alt] = args.pop(k)
    unknown = [k for k in args if k not in props]
    if unknown and schema.get("additionalProperties") is False:
        raise ToolError("invalid_input", f"input.{unknown[0]}: not a known field — the fields here: {', '.join(props) or 'none'}")
    for k in schema.get("required", []):
        if k not in args:
            raise ToolError("invalid_input", f"input.{k}: required.")
    for k, v in list(args.items()):
        spec = props.get(k)
        if isinstance(spec, dict) and v is not None:
            args[k] = _typed(f"input.{k}", spec, v)


def _typed(where, spec, v):
    t = spec.get("type")
    if isinstance(t, str) and t in _PY:
        ok = isinstance(v, _PY[t]) and not (t in ("number", "integer") and isinstance(v, bool))
        if ok and isinstance(v, float) and not math.isfinite(v):
            ok = False
        if not ok and isinstance(v, str):
            text = v.strip()
            try:
                if t == "number":
                    v, ok = float(text), True
                    if not math.isfinite(v):
                        ok = False
                elif t == "integer" and text.lstrip("-").isdigit():
                    v, ok = int(text), True
                elif t == "boolean" and text.lower() in ("true", "false"):
                    v, ok = text.lower() == "true", True
                elif t in ("array", "object"):
                    parsed = json.loads(text)
                    if isinstance(parsed, _PY[t]):
                        v, ok = parsed, True
            except ValueError:
                pass
        if not ok and t == "number" and isinstance(v, int) and not isinstance(v, bool):
            ok = True
        if not ok and t == "integer" and isinstance(v, float) and v.is_integer():
            v, ok = int(v), True
        if not ok:
            raise ToolError("invalid_input", f"{where}: {_said(t)}, not {_kind(v)}.")
    if "enum" in spec and v not in spec["enum"]:
        lowered = {str(e).lower(): e for e in spec["enum"]}
        if isinstance(v, str) and v.lower() in lowered:
            return lowered[v.lower()]
        raise ToolError("invalid_input", f"{where}: one of {', '.join(map(str, spec['enum']))} — not {v!r}.")
    return v


def _said(t):
    return {"string": "text", "number": "a number", "integer": "a whole number", "boolean": "true or false", "array": "a list", "object": "an object"}[t]


def _kind(v):
    if isinstance(v, bool):
        return "true/false"
    return {str: "text", int: "a number", float: "a number", list: "a list", dict: "an object"}.get(type(v), type(v).__name__)
