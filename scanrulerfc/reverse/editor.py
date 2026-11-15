# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/ui/FeatureEditor.tsx, ExtrudeEditor.tsx, RevolveEditor.tsx (the box: its numbers, Create and Save changes, Cancel), state/reGripSlice.ts (a grip's drag and its field)
# SPDX-License-Identifier: AGPL-3.0-only
#
# The Reverse engineer's feature editor as state: the feature being set up
# (a new one from a Create feature key, or one reopened from the list), its
# numbers as the box shows them (reverse/parameters.py slots), the grip in
# the hand and the field on it, the ghost of what it would make, and the
# tool call its Create (or Save changes) key makes. Pure: the panel page
# (pages/reverse.py) draws the numbers and keys, the 3D view
# (editor_view.py) draws the ghost, the grips and the field, and both call
# in here. Nothing is committed until create(): the tool call it hands back
# goes through the workbench's runner as any key's does.

import copy

from . import grips as G
from .features import KIND_LABELS, name_for, start_extrude, start_feature, start_revolve
from .parameters import slots_of, unlink_slot, with_slot

NEW = "new"
EDIT = "edit"


def _pick_list(v):
    return [x.get("fingerprint", x) if isinstance(x, dict) else x for x in v]


def _fields_of_draft(d):
    """A box's draft as reverse_feature_add takes it: its picks as
    fingerprints, its idle readings left out."""
    out = {}
    for key, v in d.items():
        if key in ("estimate", "symmetry", "reading", "fitting", "error", "radiusTyped", "thicknessFrom"):
            continue
        out[key] = _pick_list(v) if key in ("edges", "faces") and isinstance(v, list) else v
    return out


def start_record(kind, part, bodies=()):
    """The feature a Create feature key opens: the kind's box as it opens
    (the last sketch's one region, 0 to 10 mm; the last solid body…), with
    the id and name it will get."""
    feats = part.get("features") or []
    i = part.get("nextFeatureId") or 1
    name, _ = name_for(part.get("nextOfKind") or {}, kind)
    if kind == "extrude":
        fields = start_extrude(feats)
    elif kind == "revolve":
        fields = start_revolve(feats)
    else:
        fields = _fields_of_draft(start_feature(kind, list(bodies), feats))
        fields.pop("kind", None)
    return {"id": i, "kind": kind, "name": name, **fields}


class Editor:
    """One open feature editor, or none (record None). `version` moves on
    every change, so a view redraws only when it has to."""

    def __init__(self):
        self.listeners = []
        self.close()

    # ---- open and close
    def close(self):
        self.record = None
        self.was = None
        self.mode = None
        self.field = None
        self.drag = None
        self.error = None
        self.ghost = None
        self.ghost_of = None
        self.stretch = None
        self.version = getattr(self, "version", 0) + 1
        self._told()

    def open_new(self, kind, part, bodies=()):
        self.close()
        self.record = start_record(kind, part, bodies)
        self.mode = NEW
        self.next_id = self.record["id"]
        self._changed()
        return self.record

    def open_edit(self, feature):
        self.close()
        self.record = copy.deepcopy(feature)
        self.was = copy.deepcopy(feature)
        self.mode = EDIT
        self.next_id = feature["id"]
        self._changed()
        return self.record

    @property
    def open(self):
        return self.record is not None

    @property
    def editing(self):
        return self.record["id"] if self.mode == EDIT else None

    def listen(self, fn):
        if fn not in self.listeners:
            self.listeners.append(fn)

    def unlisten(self, fn):
        if fn in self.listeners:
            self.listeners.remove(fn)

    def _told(self):
        for fn in list(getattr(self, "listeners", [])):
            try:
                fn(self)
            except Exception:  # noqa: BLE001 — one view's fault stays its own
                pass

    def _changed(self, error=None):
        self.error = error
        self.version += 1
        self._told()

    def _put(self, record):
        if record != self.record:
            self.record = record
            self._changed()

    # ---- the box's numbers
    def title(self):
        if not self.open:
            return None
        return self.record.get("name") or KIND_LABELS.get(self.record["kind"], self.record["kind"])

    def create_label(self):
        """Create extrude, or Save changes for a feature reopened (the box's
        own words; a Move says what it does)."""
        if self.mode == EDIT:
            return "Save changes"
        k = self.record["kind"]
        if k == "moveBody":
            return f"{'Copy' if self.record.get('copy') else 'Move'} the {'bodies' if len(self.record.get('bodies') or []) > 1 else 'body'}"
        return f"Create {KIND_LABELS.get(k, k).lower()}"

    def slots(self):
        """The box's numbers: [{path, label, kind, value, expr?}], a length
        in millimetres."""
        if not self.open:
            return []
        out = []
        exprs = self.record.get("exprs") or {}
        for s in slots_of(self.record):
            try:
                v = s["get"](self.record)
            except (KeyError, TypeError, ZeroDivisionError):
                continue
            row = {"path": s["path"], "label": s["label"], "kind": s["kind"], "value": v}
            if s["path"] in exprs:
                row["expr"] = exprs[s["path"]]
            out.append(row)
        return out

    def set_slot(self, path, text, scope=None, units="mm"):
        """A number typed into the box: a number or an expression over the
        parameters (kept under the slot). False, with error set, when it
        does not read."""
        slot = next((s for s in slots_of(self.record) if s["path"] == path), None) if self.open else None
        if slot is None:
            return False
        r = G.read_field(str(text), slot["kind"], scope, units)
        if not r["ok"]:
            self._changed(f"{text}: {r['error']}")
            return False
        self._put(with_slot(unlink_slot(self.record, path), path, r["value"], r["expr"]))
        return True

    def set_fields(self, **fields):
        """Fields of the record changed outright (an op, an extent's kind)."""
        if self.open:
            self._put({**self.record, **fields})

    # ---- grips
    def grips(self, features=(), ctx=None):
        try:
            return G.grips_of(self.record, features, ctx) if self.open else []
        except (KeyError, TypeError, ValueError, IndexError):
            return []

    def grip_drag(self, side, delta, phase):
        """A grip dragged: 'start' takes hold (the field opens on it, read
        only while the hand is on it), 'move' with how far it has come,
        'end' lets go (the field takes typing)."""
        if not self.open:
            return
        if phase == "start":
            self.drag = G.Drag(self.record, side)
            self.field = side
            self._changed()
        elif phase == "move" and self.drag is not None and self.drag.side == side:
            self._put(self.drag.move(self.record, delta))
        elif phase == "end":
            self.drag = None
            self._changed()

    @property
    def dragging(self):
        return self.drag is not None

    def field_value(self):
        return G.field_value(self.record, self.field) if self.open and self.field else None

    def commit_field(self, text, scope=None, units="mm"):
        """onGripFieldCommit: the field's text entered — a number, or an
        expression kept beside it under the grip's slot."""
        side = self.field
        if not self.open or not side:
            return False
        r = G.read_field(text, "angle" if G.is_angle_side(side) else "length", scope, units)
        if not r["ok"]:
            self._changed(f"{text}: {r['error']}")
            return False
        nxt = G.set_value(self.record, side, r["value"])
        if r["expr"] is not None:
            nxt = G.with_expr(nxt, G.slot_path(nxt, side), r["expr"])
        self._put(nxt)
        return True

    def close_field(self):
        if self.field is not None:
            self.field = None
            self._changed()

    # ---- the ghost
    def needs_ghost(self):
        return self.open and self.ghost_of != self.version_key()

    def version_key(self):
        """What the ghost is built from: the record without its name."""
        return repr({k: v for k, v in (self.record or {}).items() if k != "name"})

    def set_ghost(self, answer):
        self.ghost = answer
        self.ghost_of = self.version_key()
        self.stretch = None
        self.version += 1
        self._told()

    def prism(self):
        """A straight extrude between two numbers: (origin, normal, from, to)
        its ghost can be stretched between, or None (a taper, a sweep askew,
        an end found on the part)."""
        r = self.record
        if not r or r.get("kind") != "extrude" or r.get("draftDeg") or r.get("direction"):
            return None
        e = r.get("extent") or {}
        if e.get("kind") == "distance":
            return e["from"], e["to"]
        if e.get("kind") == "symmetric":
            return -e["total"] / 2, e["total"] / 2
        return None

    # ---- Create and Cancel
    def create(self):
        """(tool, args) the Create key calls: reverse_feature_add with the
        fields, or reverse_feature_update with the fields that changed."""
        if not self.open:
            return None
        r = self.record
        if self.mode == NEW:
            fields = {k: v for k, v in r.items() if k not in ("id", "name", "visible")}
            return "reverse_feature_add", {"feature": fields}
        sets = {k: v for k, v in r.items() if k not in ("id", "kind") and self.was.get(k) != v}
        if "exprs" in self.was and "exprs" not in r:
            sets["exprs"] = {}
        if not sets:
            return None
        return "reverse_feature_update", {"feature": r["id"], "set": sets}


EDITOR = Editor()
