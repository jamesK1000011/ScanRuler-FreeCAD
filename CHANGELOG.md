<!-- SPDX-License-Identifier: AGPL-3.0-only -->
# Changelog

## 0.4.0 — 2026-11-15

- The Reverse engineer engine, ported from ScanRuler by Stefan Hermann
  (CNC Kitchen): the feature list, parameters and their expressions, the
  sketch solver and regions, the patch network maths, and the build on
  FreeCAD's Part kernel, in a `ScanRulerReverse` container in the document
  (one undo step an edit, its bodies matched by id).
- 21 `reverse_*` tools in their own `reverse` group, deferred in Agent Link
  so a session that does not use them pays nothing: the feature list
  (add, update, remove, move, suppress, rollback, clear, list, schema), the
  build, the parameters and the bodies (names, describe, check, clearance,
  set). Agent Link's echo lights the Create feature key of the feature's
  kind.
- The Reverse engineer page: the feature keys of the kinds this port
  builds, Play and + Add run the tools; FEATURES, BODIES and PARAMETERS
  list what the tools read. The rest still say they are coming with the
  engine port.
- Load opens a `.scanruler` project's Reverse engineer part in the
  document's container; without FreeCAD it is named as not loaded.
- The snapshot tools are `scan_snapshot_list`, `scan_snapshot_latest` and
  `scan_snapshot_wait`: Agent Link's own `snapshot_list` and
  `snapshot_latest` kept the old names and left these out.

## 0.3.0 — 2026-11-14

- A ScanRuler workbench of its own, after ScanRuler by Stefan Hermann (CNC
  Kitchen): the workspace, project and view toolbars (the view bar in the
  bottom toolbar area), the ScanRuler panel with one page per workspace,
  the status strip, colour maps (`jet` to start) and legends, snapshot and
  mark-up, and About ScanRuler. Under Agent Link the panel is a tab of
  Agent Link's panel and the workbench's keys run through it.
- Load opens `.FCStd` and `.scanruler` projects (the scan, fitted elements
  and sections; reverse engineer data waits for the engine port). The
  Reverse engineer workspace is a stub until then.
- New tools: `mesh_densify`, `mesh_boolean`, `mesh_trim`, `mesh_shell`,
  `mesh_wrap`, `mesh_apply_wrap`, `snapshot_list`, `snapshot_latest`,
  `snapshot_wait`. `mesh_export` also writes the trimmed piece and the wrap.
- Without Agent Link, arguments are checked against each tool's schema and
  refused in the same words Agent Link uses.
- `deviation_volume` keeps its answer for the Volume error section.

## 0.2.0 — 2026-11-10

- ScanRuler's measuring and plugins as tools for Agent Link; stands without
  it since 14 Nov 2026 (its own runner and error type).

- Trim to scan says it isn't ready in FreeCAD yet: its cut with FreeCAD's mesh booleans doesn't give the original's result on a plain box (open issue). Boolean and every other mesh tool pass in real FreeCAD 1.0, 1.1 and newest.
