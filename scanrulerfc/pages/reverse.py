# SPDX-License-Identifier: AGPL-3.0-only
# Ported from ScanRuler by Stefan Hermann (CNC Kitchen),
# github.com/CNCKitchen/ScanRuler: plugins/reverse/ui/ReversePanel.tsx,
# ParameterList.tsx, BodyList.tsx and NoteList.tsx.
#
# The Reverse engineer page (design 2.6): the original's section headers in
# order and the 26-key Create feature grid, four to a row. The engine is
# ported (scanrulerfc/reverse/), so the keys whose tools are here call them
# through the workbench's runner, as a person's keys do: a feature key
# reverse_feature_add with its kind, "+ Add" reverse_parameter_add with the
# original's next free name, "▷ Play" reverse_build. The FEATURES, BODIES
# and PARAMETERS lists are read from reverse_feature_list,
# reverse_body_names and reverse_parameter_list. Keys whose engine step is
# still to come (workspaces.REVERSE_LATER) stay inactive
# and say they are coming with the engine port; so do the sketch plane and
# the notes. The keys' labels and titles are workspaces._REVERSE, which the
# workspace tests hold against the TSX.

from .. import workspaces as W
from . import kit as K
from .infotext_pages import INFO

TITLE = "Reverse engineer"
WORKSPACE = "reverse"
PAGE = "reverse"
PENDING = "coming with the engine port"
KERNEL_LINE = "FreeCAD {freecad} · OCCT {occt}"

ORDER = (("1", "model", "Model", "Reverse engineering"), ("2", "parameters", "Parameters", None),
         ("3", "create_feature", "Create feature", "Features"), ("4", "features", "Features", "The feature list"),
         ("5", "bodies", "Bodies", None), ("6", "notes", "Notes for the agent", None))

# The grid's keys whose features this port builds; Import STEP waits for
# reverse_import_step, the rest for their build step (W.REVERSE_LATER).
READY_KINDS = tuple(i for i, *_ in W._REVERSE if i not in W.REVERSE_LATER)
RUN_KEYS = {"play": "reverse_build", "parameter-add": "reverse_parameter_add", **{k: "reverse_feature_add" for k in READY_KINDS}}
READS = ("reverse_feature_list", "reverse_body_names", "reverse_parameter_list")


def kernel_line():
    """design 2.6: the original's "CAD kernel ready" line, as FreeCAD's own."""
    try:
        import FreeCAD
        import Part

        v = FreeCAD.Version()
        return KERNEL_LINE.format(freecad=".".join(v[:3]), occt=Part.OCC_VERSION)
    except Exception:
        return None


def reader(doc):
    """read(tool, args) -> (ok, answer) of a reverse read on doc, in the
    runner's answer shape. A read the page makes to draw itself is not a
    call: it leaves the panel's version and last tool alone."""
    from .. import handlers, runner

    ctx = runner.context_for(doc)
    table = handlers.module("reverse").HANDLERS
    return lambda tool, args=None: runner.answer(lambda a: table[tool](ctx, a), dict(args or {}))


def _default_read():
    try:
        import FreeCAD

        doc = FreeCAD.ActiveDocument
    except Exception:
        return None
    return reader(doc) if doc is not None else None


def lists(read):
    """{tool: answer or None} of the page's reads."""
    out = {}
    for t in READS:
        try:
            ok, got = read(t, {}) if read is not None else (False, None)
        except Exception:  # noqa: BLE001 — a page draws, whatever a read does
            ok, got = False, None
        out[t] = got if ok else None
    return out


def _feature_reading(r):
    if r.get("rolledBack"):
        return "rolled back"
    if r.get("suppressed"):
        return "suppressed"
    return r.get("message") or r.get("status") or ""


def _body_reading(b):
    if b.get("surface") or not b.get("closed"):
        return "sheet"
    return f"{b.get('volume', 0):.0f} mm³"


def free_parameter_name(params):
    """The original's addParameter name: p1, p2 … the first not taken."""
    taken = {p.get("name") for p in params or []}
    n = 1
    while f"p{n}" in taken:
        n += 1
    return f"p{n}"


def call_for(key_id, ui=None, read=None):
    """(tool, args) a key calls, or None for a key that only opens or picks
    something in the panel (or waits for the engine port)."""
    tool = RUN_KEYS.get(key_id)
    if tool is None:
        return None
    ui = dict(ui or {})
    if tool == "reverse_feature_add":
        return tool, {"feature": {**((ui.get("draft") or {}).get(key_id) or {}), "kind": key_id}}
    if tool == "reverse_parameter_add":
        got = lists(read if read is not None else _default_read())["reverse_parameter_list"]
        return tool, {"name": free_parameter_name((got or {}).get("parameters")), "expression": "0"}
    return tool, {}


def build(st, ui=None, units="mm", read=None):
    scan = st.get("scan")
    got = lists(read if read is not None else _default_read())
    feats, bodies, params = got["reverse_feature_list"], got["reverse_body_names"], got["reverse_parameter_list"]
    out = []
    for num, sid, header, info in ORDER:
        s = K.section(num, sid, header, info, K.info_of(INFO, PAGE, info))
        if sid == "model":
            s["slot"] = K.scan_slot(scan)
            s["detail"] = kernel_line()
        elif sid == "parameters":
            s["header_fold"] = "▸"
            s["count"] = len(params["parameters"]) if params else None
            s["rows"] = [{"id": p["id"], "name": p["name"], "reading": p.get("error") or p.get("expression", ""), "visible": True}
                         for p in (params or {}).get("parameters") or []]
            s["keys"] = [K.key("parameter-add", "+ Add", True, "Add a parameter")]
        elif sid == "create_feature":
            s["fields"] = [K.select("sketch-plane-select", "Sketch on", [("", "Choose a plane…")], "", False)]
            s["hint"] = f"Sketch on: {PENDING}"
            s["keys"] = [dict(K.key(i, lab, i in READY_KINDS, tip if i in READY_KINDS else f"{tip} — {PENDING}"), command="ScanRuler_Re" + i[0].upper() + i[1:])
                         for i, lab, tip, _ic in W._REVERSE]
            s["grid"] = 4
        elif sid == "features":
            rows = (feats or {}).get("features") or []
            s["count"] = len(rows)
            s["rows"] = [{"id": r["id"], "name": r["name"], "kind": r["kind"], "reading": _feature_reading(r),
                          "visible": not r.get("suppressed")} for r in rows]
            s["keys"] = [K.key("play", "▷ Play", True, "Build the feature list again")]
        elif sid == "bodies":
            rows = (bodies or {}).get("bodies") or []
            s["count"] = len(rows)
            s["rows"] = [{"id": b["id"], "name": b["name"], "reading": _body_reading(b), "visible": b.get("visible", True),
                          **({"color": b["style"]["color"]} if (b.get("style") or {}).get("color") else {})} for b in rows]
        elif sid == "notes":
            s["hint"] = PENDING
        out.append(s)
    return K.page(TITLE, WORKSPACE, out)


def widget(model, on_key=None, on_field=None, parent=None):
    return K.widget(model, on_key, on_field, parent)
