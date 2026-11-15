# SPDX-License-Identifier: AGPL-3.0-only
# Agent Link's align tools: declared in data/tools.json, answered by
# handlers/align.py. Loaded by Agent Link only (through agentlink_families).
from . import _bridge
from ..handlers import align as H

GROUP = "align"
INFO = "The part's frame and size (ScanRuler, ported): auto-align, datum alignment, symmetry, reset, scaling a scan to its true size."


def tools(session):
    return _bridge.tools(GROUP, H, session)
