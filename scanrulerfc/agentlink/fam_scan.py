# SPDX-License-Identifier: AGPL-3.0-only
# Agent Link's scan tools: declared in data/tools.json, answered by
# handlers/scan.py. Loaded by Agent Link only (through agentlink_families).
from . import _bridge
from ..handlers import scan as H

GROUP = "scan"
INFO = "The 3D scan measured (ScanRuler, ported): open it and read what it holds."


def tools(session):
    return _bridge.tools(GROUP, H, session)
