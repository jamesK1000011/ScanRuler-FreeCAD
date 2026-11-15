# SPDX-License-Identifier: AGPL-3.0-only
# Agent Link's thickness tools: declared in data/tools.json, answered by
# handlers/thickness.py. Loaded by Agent Link only (through agentlink_families).
from . import _bridge
from ..handlers import thickness as H

GROUP = "thickness"
INFO = "Wall thickness over the whole scan (ScanRuler, ported): rays through the scan's own surface, statistics and thin spots."


def tools(session):
    return _bridge.tools(GROUP, H, session)
