# SPDX-License-Identifier: AGPL-3.0-only
# Agent Link's snapshot tools: declared in data/tools.json, answered by
# handlers/snapshot.py. Loaded by Agent Link only (through agentlink_families).
from . import _bridge
from ..handlers import snapshot as H

GROUP = "snapshot"
INFO = "Screenshots the person took in ScanRuler (ScanRuler, ported): list them, see the newest with its marks, pins and note, or wait for the next. Only the person takes one."


def tools(session):
    return _bridge.tools(GROUP, H, session)
