# SPDX-License-Identifier: AGPL-3.0-only
# Agent Link's flat tools: declared in data/tools.json, answered by
# handlers/flat.py. Loaded by Agent Link only (through agentlink_families).
from . import _bridge
from ..handlers import flat as H

GROUP = "flat"
INFO = "The 2D sheet (ScanRuler, ported): a flatbed image or a section — calibrate, detect edges, fit lines and circles, dimension, report, DXF/SVG."


def tools(session):
    return _bridge.tools(GROUP, H, session)
