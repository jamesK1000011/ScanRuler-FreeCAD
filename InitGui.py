# SPDX-License-Identifier: AGPL-3.0-only
# ScanRuler for FreeCAD: the workbench. ScanRuler by Stefan Hermann (CNC
# Kitchen), github.com/CNCKitchen/ScanRuler, ported to FreeCAD. The workbench
# itself is built in scanrulerfc/workbench.py; FreeCAD runs this file at start.

import FreeCADGui

from scanrulerfc import workbench as _srfc_workbench

_srfc_workbench.add(FreeCADGui)
