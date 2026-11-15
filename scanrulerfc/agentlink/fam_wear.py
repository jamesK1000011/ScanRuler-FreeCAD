# SPDX-License-Identifier: AGPL-3.0-only
# Agent Link's wear tools: declared in data/tools.json, answered by
# handlers/wear.py. Loaded by Agent Link only (through agentlink_families).
from . import _bridge
from ..handlers import wear as H

GROUP = "wear"
INFO = "Wear repair (ScanRuler, ported): tag worn and kept regions, read the wear against the mirrored other half or the aligned reference, rebuild it, and pre-warp a model from a print of it."


def tools(session):
    return _bridge.tools(GROUP, H, session)
