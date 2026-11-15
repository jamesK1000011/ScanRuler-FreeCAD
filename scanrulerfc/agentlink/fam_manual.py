# SPDX-License-Identifier: AGPL-3.0-only
# Agent Link's manual tools: declared in data/tools.json, answered by
# handlers/manual.py. Loaded by Agent Link only (through agentlink_families).
from . import _bridge
from ..handlers import manual as H

GROUP = "manual"
INFO = "Assembly instructions (ScanRuler, ported): steps from bodies in their assembled places, each part's way in checked, the words linted, an HTML manual with a picture per step."


def tools(session):
    return _bridge.tools(GROUP, H, session)
