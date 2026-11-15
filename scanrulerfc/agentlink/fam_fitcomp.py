# SPDX-License-Identifier: AGPL-3.0-only
# Agent Link's fit-scan tools: declared in data/tools.json, answered by
# handlers/fitcomp.py. Loaded by Agent Link only (through agentlink_families).
from . import _bridge
from ..handlers import fitcomp as H

GROUP = "fit-scan"
INFO = "Print fit from a scan (ScanRuler, ported): scale, contour and hole offsets and elephant foot read off a scanned print; slicer changes; a compensated model."


def tools(session):
    return _bridge.tools(GROUP, H, session)
