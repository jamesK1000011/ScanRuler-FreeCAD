# SPDX-License-Identifier: AGPL-3.0-only
# What Agent Link loads from this add-on: the tool families, each a module
# with GROUP, INFO and tools(session) (scanrulerfc/agentlink/, whose tools
# are data in data/tools.json bound to the handlers in handlers/). Agent
# Link finds this module by convention — a package on the path holding
# agentlink_families — and never names it, so the two stay apart (Agent
# Link LGPL, this add-on AGPL). This module and scanrulerfc/agentlink/ are
# the only ones that import Agent Link; it is never imported without it.
#
# Everything past the families hooks into Agent Link where this Agent Link
# has the hook. An older Agent Link lacks some (render.register_layer, the
# printability wall readers, thread scan readers, services): each is
# tried on its own and skipped when missing or failing, so importing this
# module never raises because of the Agent Link it runs in.

import importlib
import sys

import scanrulerfc

NAMES = ["fam_scan", "fam_elements", "fam_align", "fam_dimensions", "fam_sections", "fam_meshtools", "fam_flat", "fam_deviation", "fam_thickness", "fam_noise", "fam_thread", "fam_wear", "fam_catalog", "fam_manual", "fam_pack", "fam_fitcomp", "fam_cad"]

# Shown wherever these tools load (Agent Link's panel and tool groups): whose
# work they are and under which licence.
CREDIT = scanrulerfc.CREDIT
LICENSE = "AGPL-3.0-only"

# The families and hooks skipped on this Agent Link, and why: for diagnosis.
SKIPPED = []


def _family(n):
    try:
        return importlib.import_module(f"{__package__}.agentlink.{n}")
    except Exception as e:  # noqa: BLE001 — one family that cannot load must not take the others down
        SKIPPED.append((n, f"{type(e).__name__}: {e}"))
        print(f"ScanRulerFC: the {n} tools are not loaded ({type(e).__name__}: {e}).", file=sys.stderr)
        return None


FAMILIES = [f for f in (_family(n) for n in NAMES) if f is not None]


def _hook(name, call):
    try:
        call()
    except Exception as e:  # noqa: BLE001 — an older or different Agent Link: skip the hook, keep the tools
        SKIPPED.append((name, f"{type(e).__name__}: {e}"))
        print(f"ScanRulerFC: {name} not hooked into this Agent Link ({type(e).__name__}: {e}).", file=sys.stderr)


def _agent_refusals(fn):
    from .agentlink._bridge import refusing

    return refusing(fn)


def _lend():
    # What the handlers borrow from Agent Link, loaded when first used:
    # its picture maker, and its readers for glTF/GLB, Collada, VRML, 3DS.
    from . import lent, meshio

    lent.RENDER = lambda: importlib.import_module("agentlink.render")
    meshio.EXTRA = lambda: importlib.import_module("agentlink.meshformats")


def _render():
    # The scan, the reference and their maps in Agent Link's pictures.
    try:
        from agentlink import render
    except ImportError:  # an Agent Link without pictures
        return
    from . import render_layers as L

    # An older Agent Link may have pictures but not these hooks: register
    # what it takes and leave the rest.
    layer = getattr(render, "register_layer", None)
    add_map = getattr(render, "register_map", None)
    if layer is not None:
        layer("scan", _agent_refusals(L.scan_layer), "The open scan (grey).")
        layer("reference", _agent_refusals(L.reference_layer), "The deviation reference part (blue) — drawn when asked for by name, as it lies on the scan.")
    if add_map is None:
        return
    add_map("deviation", _agent_refusals(L.deviation_map), "The scan's deviation from the reference (ScanRuler), ±range: positive (red) excess material, negative (blue) material missing.")
    add_map("deviation-reference", _agent_refusals(L.deviation_reference_map), "The deviation read on the reference (ScanRuler's map on the reference), signed as the scan's map — positive (red) excess material, negative (blue) material missing — and what was not scanned (grey).")
    add_map("thickness", _agent_refusals(L.thickness_map), "The scan's wall thickness (ScanRuler), red thin.")


def _wall():
    # ScanRuler's wall thickness in Agent Link's printability check
    # (dfm_check, part_review): a reader of kind "wall" (Agent Link API 1;
    # Workshop's Make add-on asks it since 14 Nov 2026), or the wall readers
    # of an Agent Link from before the hooks.
    from .dfm_wall import read

    try:
        from agentlink import hooks
    except ImportError:
        hooks = None
    if hooks is not None and hasattr(hooks, "register_reader"):
        hooks.register_reader("wall", read)
        return
    try:
        from agentlink import printability
    except ImportError:
        return
    hook = getattr(printability, "WALL_READERS", None)
    if hook is not None and read not in hook:
        hook.append(read)


def _thread():
    # A scanned thread named through thread_identify { scan }: a reader of
    # kind "thread_scan" (Agent Link API 1; Workshop's Make add-on since
    # 14 Nov 2026), or the scan readers of an Agent Link from before.
    reader = _thread_reader()
    try:
        from agentlink import hooks
    except ImportError:
        hooks = None
    if hooks is not None and hasattr(hooks, "register_reader"):
        hooks.register_reader("thread_scan", reader)
        return
    try:
        from agentlink.families import thread
    except ImportError:
        return
    hook = getattr(thread, "SCAN_READERS", None)
    if hook is not None and reader not in hook:
        hook.append(reader)


_READER = []


def _thread_reader():
    """scan_thread for thread_identify, its refusals Agent Link's: one
    wrapped reader, so loading twice registers it once."""
    if not _READER:
        from .handlers.thread import read_for_agent_link

        _READER.append(_agent_refusals(read_for_agent_link))
    return _READER[0]


def _register():
    # ScanRuler's assembly manual for whoever owns a Manual tab (Workshop
    # Documents asks hooks.service("manual_maker")), and the add-on told it
    # runs under Agent Link (its own dock stays away).
    scanrulerfc._hosted = True
    from agentlink import hooks

    from .manual_maker import ManualMaker

    if hasattr(hooks, "provide"):
        hooks.provide("manual_maker", ManualMaker())


for _name, _call in (("lent readers", _lend), ("pictures", _render), ("wall readers", _wall), ("thread scan readers", _thread), ("services", _register)):
    _hook(_name, _call)
