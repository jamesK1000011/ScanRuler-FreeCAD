# SPDX-License-Identifier: AGPL-3.0-only
"""ScanRuler for FreeCAD: ScanRuler's scan measuring, ported from ScanRuler
by CNC Kitchen (https://github.com/CNCKitchen/ScanRuler). See NOTICE.md.

Nothing here needs Agent Link: only agentlink_families (and the
scanrulerfc.agentlink families it loads) imports it, and Agent Link alone
imports that module."""

# Shown wherever ScanRuler's work loads (Agent Link's panel and tool groups,
# this add-on's own panels): whose work it is.
CREDIT = "ScanRuler tools by Stefan Hermann (CNC Kitchen), ported to FreeCAD — github.com/CNCKitchen/ScanRuler"

# True once Agent Link has loaded this add-on (agentlink_families sets it):
# its panels then go in Agent Link's panel, else in its own dock.
_hosted = False
