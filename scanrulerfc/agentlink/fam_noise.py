# SPDX-License-Identifier: AGPL-3.0-only
# Agent Link's scan-noise tools: declared in data/tools.json, answered by
# handlers/noise.py. Loaded by Agent Link only (through agentlink_families).
from . import _bridge
from ..handlers import noise as H

GROUP = "scan-noise"
INFO = "Scanner noise (ScanRuler, ported): this scan's noise, your scanners' usual noise, and the noise to plan with."


def tools(session):
    return _bridge.tools(GROUP, H, session)
