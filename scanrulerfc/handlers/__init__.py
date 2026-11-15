# SPDX-License-Identifier: AGPL-3.0-only
"""ScanRuler for FreeCAD's tool handlers: {tool name: fn(ctx, args)}, one
module per family. ctx is the session the call runs in: Agent Link's, or
the add-on's own runner's (scanrulerfc.runner.Context): its doc,
family_state, out_dir, body(), bodies(), unique(), snapshot(). No handler
imports Agent Link; the tools' declarations (names, descriptions, schemas)
are data, in scanrulerfc/data/tools.json. The handler is the one place an
answer is shaped, for the agent and for the add-on's own panels."""
import importlib

from . import _bind

# The families, in the order Agent Link lists them.
MODULES = ("scan", "elements", "align", "dimensions", "sections", "meshtools", "flat", "deviation", "thickness", "noise", "thread", "wear", "catalog", "manual", "pack", "fitcomp", "cad", "snapshot", "reverse")


def module(name):
    return importlib.import_module(f"{__name__}.{name}")


def all_handlers():
    """{tool name: fn(ctx, args)} of every family."""
    out = {}
    for m in MODULES:
        out.update(module(m).HANDLERS)
    return out


def bound(ctx, family=None):
    """{tool name: fn(args)} for one context: one family's (a module or its
    name), or every family's."""
    mods = [module(m) for m in MODULES] if family is None else [module(family) if isinstance(family, str) else family]
    out = {}
    for m in mods:
        out.update(_bind.bound(ctx, m.bind))
    return out
