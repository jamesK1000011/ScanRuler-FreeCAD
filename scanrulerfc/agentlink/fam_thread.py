# SPDX-License-Identifier: AGPL-3.0-only
# Agent Link's scan-thread tools: declared in data/tools.json, answered by
# handlers/thread.py. Loaded by Agent Link only (through agentlink_families).
from . import _bridge
from ..handlers import thread as H

GROUP = "scan-thread"
INFO = "Thread match on the scan (ScanRuler, ported): ISO metric, UNC/UNF/UNEF, NPT, G/R pipe, Tr, ACME and the 45° print form named from a fitted bore or boss."


def tools(session):
    return _bridge.tools(GROUP, H, session)
