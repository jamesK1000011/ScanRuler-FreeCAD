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
