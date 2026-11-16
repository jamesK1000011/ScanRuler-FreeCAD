# SPDX-License-Identifier: AGPL-3.0-only
# Ported from ScanRuler by Stefan Hermann (CNC Kitchen),
# github.com/CNCKitchen/ScanRuler: src/ui/ViewBar.tsx (the Scan, Reference
# and Bodies keys and their Transparent and Mesh switches).
#
# Those keys, as FreeCAD's own view properties of the document objects
# they stand for: no state of ScanRuler's beside them. The scan and the
# reference are Mesh::Features (docstate.py), the bodies the Reverse
# engineer container's ReverseBody objects (reverse/doc.py).
#
#   Visibility    shown or hidden (the tree's space bar, Std_ToggleVisibility)
#   Transparency  see-through at TRANSPARENT %, or 0 (Std_ToggleTransparency)
#   DisplayMode   "Flat Lines" draws the triangle edges, "Shaded" not
#                 (Std_DrawStyle per object, the property view's Display Mode)
#
# A key is on when any of its objects is; a press sets them all one way.
# Pure but for the objects handed in: the tests use stand-ins.

TRANSPARENT = 60  # the original's see-through scan and bodies: opacity 0.4
EDGES, PLAIN = "Flat Lines", "Shaded"
PROPS = ("Visibility", "Transparency", "DisplayMode")


def objects(doc, role):
    """The document objects a role stands for: "scan", "reference" or
    "bodies" (every ReverseBody of the Reverse engineer container)."""
    if doc is None:
        return []
    if role in ("scan", "reference"):
        from . import docstate

        o = docstate.role_object(doc, role)
        return [o] if o is not None else []
    if role == "bodies":
        from .reverse import doc as RD

        c = RD.find_container(doc)
        return list(RD.bodies_of(c)) if c is not None else []
    raise KeyError(role)


def _view(o):
    return getattr(o, "ViewObject", None)


def value(o, prop):
    """One object's reading of prop as on (True) or off."""
    v = _view(o)
    if prop == "Visibility":
        return bool(v.Visibility if v is not None else getattr(o, "Visibility", True))
    if v is None:
        return False
    if prop == "Transparency":
        return int(getattr(v, "Transparency", 0) or 0) > 0
    if prop == "DisplayMode":
        return getattr(v, "DisplayMode", PLAIN) in (EDGES, "Wireframe")
    raise KeyError(prop)


def is_on(objs, prop):
    """None when there is no object to read (the key cannot show anything)."""
    if not objs:
        return None
    return any(value(o, prop) for o in objs)


def put(o, prop, on):
    v = _view(o)
    if prop == "Visibility":
        if v is not None:
            v.Visibility = bool(on)
        else:
            o.Visibility = bool(on)
        return
    if v is None:  # FreeCADCmd: no view to set
        return
    if prop == "Transparency":
        v.Transparency = TRANSPARENT if on else 0
    elif prop == "DisplayMode":
        v.DisplayMode = EDGES if on else PLAIN
    else:
        raise KeyError(prop)


def toggle(doc, role, prop, on=None):
    """Set the role's objects' prop on or off (on None: the other way from
    how it reads now). Returns the new reading, or None with nothing to set."""
    objs = objects(doc, role)
    now = is_on(objs, prop)
    if now is None:
        return None
    want = (not now) if on is None else bool(on)
    for o in objs:
        put(o, prop, want)
    return want
