# SPDX-License-Identifier: AGPL-3.0-only
# Mesh Tools that ScanRuler for FreeCAD lacked headless: Densify, Boolean,
# Trim to scan, Shell (hollow or thicken) and Wrap — ported from ScanRuler by
# CNC Kitchen (Stefan Hermann), plugins/mesh-tools. Each tool is a pure
# module on numpy vertex and face arrays; handlers.py binds them to the
# session as the other mesh_* tools are, and tools.json is their entry in
# Agent Link's tool-data format.
