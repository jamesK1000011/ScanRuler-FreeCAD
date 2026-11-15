# SPDX-License-Identifier: AGPL-3.0-only
# Agent Link's deviation tools: declared in data/tools.json, answered by
# handlers/deviation.py. Loaded by Agent Link only (through agentlink_families).
from . import _bridge
from ..handlers import deviation as H

GROUP = "deviation"
INFO = "The scan against a reference part (ScanRuler, ported): open the reference, best-fit the scan onto it, map, read patches and volumes, export."


def tools(session):
    return _bridge.tools(GROUP, H, session)
