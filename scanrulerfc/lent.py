# SPDX-License-Identifier: AGPL-3.0-only
"""What a host lends the handlers. Agent Link's family layer
(agentlink_families) sets these when Agent Link loads this add-on; alone
they are None and the tools that need them refuse as unavailable."""
from .errors import ToolError

# Agent Link's picture maker (agentlink.render), as a loader called when a
# picture is drawn (flat_render, pack_write, manual_render, scan_heightmap's
# picture): fn() -> the module.
RENDER = None


def render():
    if RENDER is None:
        raise ToolError("unavailable", "Pictures need Agent Link's renderer: install Agent Link (the FreeCAD add-on) beside ScanRuler for FreeCAD.")
    return RENDER()


# Agent Link's paths.agentlink_state(real, out_dir): what of Agent Link's
# own state (settings, logs, approvals) a path is, or None. Lent by
# agentlink_families; alone None. pack_setup keeps that state out of a pack.
AGENTLINK_STATE = None
