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
# still to come (workspaces.REVERSE_LATER), the sketch plane and the notes
# are left off the page until they work, rather than shown as placeholders
# (GUI pass, round 4). The keys' labels and titles are workspaces._REVERSE, which the
# workspace tests hold against the TSX.
#
# A Create feature key opens the feature's box (reverse/editor.py), as the
# original's does: its numbers (FeatureEditor.tsx, ExtrudeEditor.tsx), the
# ghost's line, Create (or Save changes) and Cancel, while the 3D view shows
# the ghost, the grips and the field on the grip in the hand
# (editor_view.py). Create runs reverse_feature_add, Save changes
# reverse_feature_update; a feature with numbers is reopened from the
# feature list's Edit choice.

from .. import workspaces as W
from . import kit as K
from .infotext_pages import INFO

TITLE = "Reverse Engineer"
WORKSPACE = "reverse"
PAGE = "reverse"
KERNEL_LINE = "FreeCAD {freecad} · OCCT {occt}"

ORDER = (("1", "model", "Model", "Reverse engineering"), ("2", "parameters", "Parameters", None),
         ("3", "create_feature", "Create feature", "Features"), ("4", "features", "Features", "The feature list"),
         ("5", "bodies", "Bodies", None), ("6", "notes", "Notes for the agent", None))

# The grid's keys whose features this port builds; Import STEP waits for
# reverse_import_step, the rest for their build step (W.REVERSE_LATER).
READY_KINDS = tuple(i for i, *_ in W._REVERSE if i not in W.REVERSE_LATER)
RUN_KEYS = {"play": "reverse_build", "parameter-add": "reverse_parameter_add"}
EDITOR_KEYS = ("editor-create", "editor-cancel")
EDITOR_SECTION = "editor"
EDIT_FIELD = "edit"
NO_EDIT = 0
UNIT_OF = {"length": "mm", "angle": "°", "integer": "", "number": ""}
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


def _editor():
    from ..reverse.editor import EDITOR

    return EDITOR


def _env():
    """What the editor reads off the document in FreeCAD (editor_view), or
    None where FreeCAD is not."""
    try:
        from .. import editor_view

        return editor_view._env()
    except ImportError:
        return None


def editor_version():
    """Moves whenever the box changes, so the panel draws it again."""
    return _editor().version


def box_key():
    """Which box is open (its kind, its name, the feature it edits), or
    None: the dock scrolls a box into view when this changes to another."""
    ed = _editor()
    if not ed.open:
        return None
    r = ed.record or {}
    return (r.get("kind"), ed.title(), getattr(ed, "editing", None))


def open_kind(kind, ui=None, env=None):
    """A Create feature key: the kind's box opened on the part (the fields
    the panel's ui keeps for it laid over the box's defaults), drawn in the
    3D view."""
    env = env if env is not None else _env()
    store = env["store"]() if env else None
    part = store.part() if store is not None else {"features": [], "nextFeatureId": 1, "nextOfKind": {}}
    bodies = env["bodies"]() if env else []
    ed = _editor()
    ed.open_new(kind, part, bodies)
    draft = ((ui or {}).get("draft") or {}).get(kind)
    if draft:
        ed.set_fields(**{k: v for k, v in draft.items() if k not in ("kind", "id")})
    _show(ed)
    return ed


def open_feature(feature_id, env=None):
    """A feature reopened from the list: its box with its numbers."""
    env = env if env is not None else _env()
    store = env["store"]() if env else None
    part = store.part() if store is not None else {"features": []}
    f = next((x for x in part.get("features") or [] if x["id"] == feature_id), None)
    if f is None:
        return None
    ed = _editor()
    ed.open_edit(f)
    _show(ed)
    return ed


def _show(ed):
    try:
        from .. import editor_view

        editor_view.show(ed)
    except ImportError:
        pass


def call_for(key_id, ui=None, read=None, env=None):
    """(tool, args) a key calls, or None for a key that only opens or picks
    something in the panel (or waits for the engine port). A Create feature
    key opens its box; the box's Create calls the tool."""
    ui = dict(ui or {})
    if key_id in READY_KINDS:
        open_kind(key_id, ui, env)
        return None
    if key_id == "editor-create":
        return _editor().create()
    if key_id == "editor-cancel":
        _editor().close()
        return None
    tool = RUN_KEYS.get(key_id)
    if tool is None:
        return None
    if tool == "reverse_parameter_add":
        got = lists(read if read is not None else _default_read())["reverse_parameter_list"]
        return tool, {"name": free_parameter_name((got or {}).get("parameters")), "expression": "0"}
    return tool, {}


def after_press(key_id, got):
    """A key's run done: the box closes once its Create has made the feature
    (left open, saying why, when it was refused)."""
    if key_id != "editor-create" or got is None:
        return
    ed = _editor()
    if got.get("ok"):
        ed.close()
    else:
        ed._changed(((got.get("answer") or {}).get("error") or {}).get("message") or "Not made.")


def on_field(section_id, field_id, value, env=None):
    """A number typed into the box, or a feature chosen to edit."""
    if section_id == EDITOR_SECTION:
        env = env if env is not None else _env()
        scope = env["scope"]() if env else None
        _editor().set_slot(field_id, _plain(value), scope)
    elif section_id == "features" and field_id == EDIT_FIELD and value not in (None, NO_EDIT):
        open_feature(value, env)


def _plain(v):
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return repr(v) if isinstance(v, float) else str(v)


def preview_line(ed, units="mm"):
    """PreviewLine: what the ghost says under the box's numbers."""
    from ..reverse.units import fmt_vol

    if ed.error:
        return "⚠ " + ed.error
    g = ed.ghost
    if g is None:
        return "Building the preview…"
    if g.get("status") == "failed":
        return "⚠ " + g["message"]
    vol = fmt_vol(g.get("volume") or 0, units)
    return f"Preview: {vol}{'' if g.get('closed') else ' · ⚠ not a closed solid'} — drag the grips in the viewport, or type below."


def editor_section(ed, units="mm"):
    """The open box as a section: its numbers, the ghost's line, Create (or
    Save changes) and Cancel. None while no box is open."""
    if not ed.open:
        return None
    s = K.section("", EDITOR_SECTION, ed.title())
    s["fields"] = [dict(K.number(r["path"], r["label"], r["value"], UNIT_OF.get(r["kind"], ""), integer=r["kind"] == "integer",
                                 hint=f"{r['expr']} (an expression over the parameters)" if r.get("expr") else None))
                   for r in ed.slots()]
    from ..reverse.picks import picks_line

    picked = picks_line(ed.record)
    s["hint"] = f"{picked}\n{preview_line(ed, units)}" if picked else preview_line(ed, units)
    s["keys"] = [K.key("editor-create", ed.create_label(), ed.create() is not None, "Enter does the same", primary=True),
                 K.key("editor-cancel", "Cancel", True, "Close the box; nothing is made")]
    return s


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
            # Only the features this port builds: the sketch plane and the
            # kinds still to come are left out, not shown as placeholders.
            s["keys"] = [dict(K.key(i, lab, True, tip), command="ScanRuler_Re" + i[0].upper() + i[1:])
                         for i, lab, tip, _ic in W._REVERSE if i in READY_KINDS]
            s["grid"] = 4
        elif sid == "features":
            rows = (feats or {}).get("features") or []
            s["count"] = len(rows)
            s["rows"] = [{"id": r["id"], "name": r["name"], "kind": r["kind"], "reading": _feature_reading(r),
                          "visible": not r.get("suppressed")} for r in rows]
            s["keys"] = [K.key("play", "▷ Play", True, "Build the feature list again")]
            editable = [r for r in rows if r.get("key") or r["kind"] in EDITABLE]
            if editable:
                s["fields"] = [K.select(EDIT_FIELD, "Edit", [(NO_EDIT, "—")] + [(r["id"], r["name"]) for r in editable], NO_EDIT)]
        elif sid == "bodies":
            rows = (bodies or {}).get("bodies") or []
            s["count"] = len(rows)
            s["rows"] = [{"id": b["id"], "name": b["name"], "reading": _body_reading(b), "visible": b.get("visible", True),
                          **({"color": b["style"]["color"]} if (b.get("style") or {}).get("color") else {})} for b in rows]
        elif sid == "notes":
            s["visible"] = False  # its notes come with the engine port: hidden until then
        out.append(s)
        if sid == "create_feature":
            box = editor_section(_editor(), units)
            if box is not None:
                out.append(box)
    return K.page(TITLE, WORKSPACE, out)


# The kinds whose box has numbers to reopen it for (parameters.slots_of).
EDITABLE = ("extrude", "revolve", "shell", "fillet", "chamfer", "hole", "thread", "extract", "thicken", "draft", "moveFace", "offsetBody", "moveBody",
            "pattern", "cutPlane", "mirror")


def widget(model, on_key=None, on_field=None, parent=None):
    return K.widget(model, on_key, on_field, parent)
