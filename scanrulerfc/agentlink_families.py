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
from scanrulerfc import echo_words as _EW
from scanrulerfc import workspaces as _W
from scanrulerfc.reverse import handlers as _R

NAMES = ["fam_scan", "fam_elements", "fam_align", "fam_dimensions", "fam_sections", "fam_meshtools", "fam_flat", "fam_deviation", "fam_thickness", "fam_noise", "fam_thread", "fam_wear", "fam_catalog", "fam_manual", "fam_pack", "fam_fitcomp", "fam_cad", "fam_snapshot", "fam_reverse"]

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

# --- the live echo in the window (design 7.1), from the workbench's tables --
WB = "ScanRulerWorkbench"
# The workbench to bring up for a tool, by prefix. wear_, catalog_, pack_
# and manual_ switch nothing.
#
# fit_scan_ is ScanRuler's own: Agent Link takes the longest declared key
# that its name starts with (echo._longest, no "_" boundary), and the
# Workshop add-on declares "fit" (its fit tool) for the Make bench, so
# fit_scan_setup / _features / _measure / _export brought Make up with
# "No setups yet" (window review round 6, sr-a 4007-4010). The longer key
# here wins over "fit".
WORKBENCHES = {p: WB for p in ("scan_", "element_", "dimension_", "align_", "section_", "deviation_", "thickness_", "flat_", "mesh_", "report_get", "export_csv",
                               "fit_scan_")}
WORKBENCHES.update(_R.ECHO["WORKBENCHES"])
# The snapshot tools only read the person's shots: no bench comes up for
# them, though they start scan_ (an empty bench switches nothing).
WORKBENCHES["scan_snapshot_"] = ""
# The Activity list's area, by prefix: the workspace tabs' names.
AREAS = dict(_W.AREAS)
# The key a tool lights, for every tool a key stands for; command_for(tool,
# args) for the ones whose key hangs on an argument (element_fit's kind).
COMMANDS = {k["tool"]: _W.command_for(k["tool"]) for k in _W.keys() + [_W.SNAPSHOT] if k.get("tool")}
COMMANDS.update(_R.ECHO["COMMANDS"])
COMMANDS.update(_EW.COMMANDS)
# The Reverse engineer's Create feature keys hang on reverse_feature_add's
# feature kind (workspaces.command_for asks reverse.handlers.command_for);
# a fit from marked points and a construction light the element key of
# their kind (echo_words.command_for).
command_for = _EW.command_for
# Read-only tools that still show something.
SHOWN = ("element_list", "report_get", "deviation_stats", "deviation_hotspots", "thickness_stats", "scan_info", "scan_query",
         "scan_nearest", "mesh_inspect", "section_list", "flat_objects") + tuple(_R.ECHO["SHOWN"])
# Tools that light no key at all, whatever their prefix matches.
NO_BUTTON = tuple(_R.ECHO["NO_BUTTON"])
# The reads that bring the ScanRuler workbench up and light their key, as
# a changing call does: every ScanRuler tool but the snapshot reads. They
# change ScanRuler's state or show a result (the panel turns to their
# workspace, the 3D view draws it), not the FreeCAD model, so their
# tools.json "changes" stays false and they open no undo step. Window
# review round 3: scan_open, scan_info, scan_qa and the Mesh Tools stayed
# in the Mesh workbench with a stale Mesh Info task open.
OPENS = _EW.OPENS
# The words of each call with what it measured, from its own answer
# (echo_words.words(name, args, body) -> str or None): Agent Link's
# PHRASES reach only the top of an answer, where most of these tools keep
# no figure. PHRASES has what the top holds today; WORDS is for an Agent
# Link that reads it (docs/hardening/sr4-findings.md says what it needs).
PHRASES = dict(_EW.PHRASES)
WORDS = _EW.words
# What to select after a call (echo_words.selects(name, args, body, doc)
# -> object names or None): the scan's own mesh object after scan_open,
# not the hidden mesh it was read from; the reference after
# deviation_open_reference. For an Agent Link that reads it.
SELECTS_FOR = _EW.selects


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
    try:
        from agentlink import paths

        lent.AGENTLINK_STATE = getattr(paths, "agentlink_state", None)
    except ImportError:
        pass
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
    # Documents asks hooks.service("manual_maker")), the line that tells the
    # agent of a new screenshot (hooks.service("notice")), the library pack
    # for whoever owns a Library Pack command (Documents asks
    # hooks.service("library_pack") and, when it is offered, leaves its own
    # library_pack tool unlisted), and the add-on told it runs under Agent
    # Link (its own dock stays away).
    scanrulerfc._hosted = True
    from agentlink import hooks

    from .manual_maker import ManualMaker
    from .pack_service import LibraryPack
    from .snapshot.handlers import notice

    if hasattr(hooks, "provide"):
        hooks.provide("manual_maker", ManualMaker())
        hooks.provide("notice", notice)
        hooks.provide("library_pack", LibraryPack())


def _tab():
    # The dock as the "ScanRuler" tab of Agent Link's panel.
    from agentlink import hooks

    from . import dock

    dock.register_tab(hooks)


def _echo():
    # The echo's tables for these tools, through declare(): WORKBENCHES,
    # AREAS, SHOWN, COMMANDS and command_for (asked before COMMANDS, so a
    # tool whose key depends on its arguments, e.g. element_fit by kind,
    # lights the right one). Nothing goes into Agent Link's own table.
    from agentlink import echo

    echo.declare(sys.modules[__name__])


for _name, _call in (("lent readers", _lend), ("pictures", _render), ("wall readers", _wall), ("thread scan readers", _thread), ("services", _register), ("panel tab", _tab), ("echo", _echo)):
    _hook(_name, _call)


def _reverse_health():
    # The Reverse engineer's failed features in Agent Link's shared health
    # check (health.register): a feature that fails to build fails no
    # FreeCAD object, so nothing else would turn a reverse_ call's health
    # red. The reading is reverse/doc.py's and imports no Agent Link.
    from agentlink import health

    from .reverse import doc as _D

    health.register("scanruler_reverse", _D.health_reading)


_hook("reverse health", _reverse_health)


def _own_state():
    # ScanRuler's state is settled per document by ScanRuler itself
    # (scanstate.settle: written into the document it belongs to on
    # leaving, set aside, read back from the document on arriving). An
    # Agent Link that keeps every family's state per document
    # (agentlink/docstates.py) is told so, and carries the "scanruler" key
    # along untouched instead of setting it aside too. It would do the
    # same unasked on finding scanstate's book on the session
    # (_scanruler_documents); saying it leaves nothing to a naming
    # convention. An Agent Link from before has no such call and no such
    # keeping: nothing to say.
    from agentlink import hooks

    from .scanstate import KEY

    own = getattr(hooks, "own_document_state", None)
    if own is not None:
        own(KEY)


_hook("state per document", _own_state)
