# SPDX-License-Identifier: AGPL-3.0-only
# Ported from ScanRuler by Stefan Hermann (CNC Kitchen),
# github.com/CNCKitchen/ScanRuler: plugins/snapshot/.
#
# Screenshot for the agent. The person presses the camera key (or
# Alt+Shift+S); one frame of the FreeCAD window comes up in a card with a
# note, Mark up, Save PNG, Copy and Discard. Up to 8 shots are kept in
# memory, never in the project; with "Save shots beside the project" on (the
# default) each is written, marks drawn in, to shots/ beside the document.
# The agent reads them with scan_snapshot_list, scan_snapshot_latest and
# scan_snapshot_wait. Only the person takes a shot: no tool takes one.
#
# store.py and marks.py are plain Python; card.py is thin Qt over them and
# imports Qt only when it is used.

from .marks import COLOURS, TOOLS, MarkUp  # noqa: F401
from .store import KEEP, STORE, Shot, ShotMark, ShotStore  # noqa: F401
