# SPDX-License-Identifier: AGPL-3.0-only
# Agent Link's sections tools: declared in data/tools.json, answered by
# handlers/sections.py. Loaded by Agent Link only (through agentlink_families).
from . import _bridge
from ..handlers import sections as H

GROUP = "sections"
INFO = "Sections of the scan (ScanRuler, ported): cut it with a plane, read the polylines, fit lines and arcs, write the profile as a sketch."


def tools(session):
    return _bridge.tools(GROUP, H, session)
