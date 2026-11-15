# SPDX-License-Identifier: AGPL-3.0-only
# Agent Link's catalog tools: declared in data/tools.json, answered by
# handlers/catalog.py. Loaded by Agent Link only (through agentlink_families).
from . import _bridge
from ..handlers import catalog as H

GROUP = "catalog"
INFO = "Parts catalog (ScanRuler, ported): name a screw, nut, washer or bearing from measured sizes; search pages for CAD; where each file came from."


def tools(session):
    return _bridge.tools(GROUP, H, session)
