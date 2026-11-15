# SPDX-License-Identifier: AGPL-3.0-only
# Agent Link's meshtools tools: declared in data/tools.json, answered by
# handlers/meshtools.py. Loaded by Agent Link only (through agentlink_families).
from . import _bridge
from ..handlers import meshtools as H

GROUP = "meshtools"
INFO = "Mesh Tools (ScanRuler's plugin, ported): inspect, clean, cut, mirror, fill, smooth, offset, reduce and export the scan — edits on a copy until mesh_use_edited."


def tools(session):
    return _bridge.tools(GROUP, H, session)
