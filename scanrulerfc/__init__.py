# SPDX-License-Identifier: AGPL-3.0-only
"""ScanRuler for FreeCAD: ScanRuler's scan measuring, ported from ScanRuler
by CNC Kitchen (https://github.com/CNCKitchen/ScanRuler). See NOTICE.md.

Nothing here needs Agent Link: only agentlink_families (and the
scanrulerfc.agentlink families it loads) imports it, and Agent Link alone
imports that module."""

# The add-on's version, as package.xml has it.
VERSION = "0.3.0"

# Shown wherever ScanRuler's work loads (Agent Link's panel and tool groups,
# this add-on's own panels): whose work it is.
CREDIT = "ScanRuler tools by Stefan Hermann (CNC Kitchen), ported to FreeCAD — github.com/CNCKitchen/ScanRuler"

# True once Agent Link has loaded this add-on (agentlink_families sets it):
# its panels then go in Agent Link's panel, else in its own dock.
_hosted = False


def set_runner(fn):
    """The runner the workbench's commands and panels call tools through:
    fn(tool, args) -> (ok, result). Set at registration (workbench.py)."""
    from . import commands

    commands.set_runner(fn)


def __getattr__(name):
    # scanrulerfc.runner, loaded when first asked for: the module, which
    # called — scanrulerfc.runner() — gives the commands' runner (see
    # runner.py, end). A function of that name here would be replaced by
    # the module the first time it is imported.
    if name == "runner":
        import importlib

        return importlib.import_module(f"{__name__}.runner")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
