# SPDX-License-Identifier: AGPL-3.0-only
# Agent Link's elements tools: declared in data/tools.json, answered by
# handlers/elements.py. Loaded by Agent Link only (through agentlink_families).
from . import _bridge
from ..handlers import elements as H

GROUP = "elements"
INFO = "Elements on the scan (ScanRuler, ported): fit planes, spheres, cylinders, cones, tori, circles and points; construct from others; rename, remove, show."


def tools(session):
    return _bridge.tools(GROUP, H, session)
