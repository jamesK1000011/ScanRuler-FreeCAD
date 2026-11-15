# SPDX-License-Identifier: AGPL-3.0-only
# Agent Link's pack tools: declared in data/tools.json, answered by
# handlers/pack.py. Loaded by Agent Link only (through agentlink_families).
from . import _bridge
from ..handlers import pack as H

GROUP = "pack"
INFO = "Library pack (ScanRuler, ported): a part bundled for sharing — models, renders, README, LICENSE — upstream licences checked, personal details scrubbed."


def tools(session):
    return _bridge.tools(GROUP, H, session)
