# SPDX-License-Identifier: AGPL-3.0-only
# Agent Link's dimensions tools: declared in data/tools.json, answered by
# handlers/dimensions.py. Loaded by Agent Link only (through agentlink_families).
from . import _bridge
from ..handlers import dimensions as H

GROUP = "dimensions"
INFO = "Dimensions and GD&T-like checks between elements (ScanRuler, ported), their limits and verdicts, and the measuring report."


def tools(session):
    return _bridge.tools(GROUP, H, session)
