# SPDX-License-Identifier: AGPL-3.0-only
# Agent Link's scan-cad tools: declared in data/tools.json, answered by
# handlers/cad.py. Loaded by Agent Link only (through agentlink_families).
from . import _bridge
from ..handlers import cad as H

GROUP = "scan-cad"
INFO = "Scan elements into the FreeCAD document (ScanRuler, ported): fitted planes, cylinders, cones, spheres, tori, lines, circles and points as Part geometry; STEP."


def tools(session):
    return _bridge.tools(GROUP, H, session)
