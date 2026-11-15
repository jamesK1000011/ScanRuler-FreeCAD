<!-- SPDX-License-Identifier: AGPL-3.0-only -->
# Changelog

All notable changes to ScanRuler for FreeCAD, a port of ScanRuler by Stefan
Hermann (CNC Kitchen). The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/). The dated versions below were
never tagged: the first tagged release is being prepared.

## [Unreleased]

The ScanRuler workbench as FreeCAD's design guide asks it, Reverse engineer
built to the end of ScanRuler's feature list, and the add-on ready for the
Addon Manager.

- Fixes from a live run in FreeCAD 1.1.3: a fillet's or chamfer's edge
  clicked in the 3D view is picked (and let go on a second click) also when
  the pick lands on the Reverse engineer container's compound or the
  navigation takes the press; a miss says why in the Report view. A feature
  box that opens is scrolled into view in the panel. Split view is pressable
  in every workspace and says why it does not open outside Surface
  Deviation, in the Report view and the panel's header. The status strip is
  added without Qt's "Index out of range" warnings. An older document's
  bodies drop their link back to the container on open, so it recomputes
  clean without a save. The pick hints end with a full stop, and "Unsaved
  changes" has its own line in the header.
- Surface Deviation's Split view, ported from ScanRuler by Stefan Hermann (CNC
  Kitchen): the key opens a two-pane 3D viewer with the scan on the left,
  coloured by its deviation map while Colour plot is on, and the reference on
  the right, their cameras linked both ways. It needs a scan and a reference.
- Reverse engineer: a fillet's, chamfer's, shell's, moved face's or deleted
  face's edges and faces are clicked on the part, and an extrude's end is
  clicked through a point, as in ScanRuler; a click selects nothing in
  FreeCAD.
- Patch networks sew on FreeCAD 1.1.3: a seam left open is sewn again at a
  looser tolerance relative to the model, and open edges are read by
  sameness rather than hash codes.
- Reverse engineer's feature editor, ported from ScanRuler by Stefan Hermann
  (CNC Kitchen): a Create feature key opens the feature's box (its numbers,
  the preview line, Create or Save changes, Cancel) instead of making the
  feature at once, and a feature with numbers reopens from the list's Edit.
  In the 3D view the ghost of what it would make (a tool body see-through,
  red and drawn through for a cut; a body as a fillet or shell would leave
  it, solid in its place), and grips: arrows on an extrude's faces and far
  edge, a ring about a revolve's axis, an arrow on a fillet's, chamfer's,
  shell's or moved face's first pick, a Move's gizmo. A dragged grip opens
  a field on it that takes a number or an expression over the parameters. A
  press away from the grips stays with FreeCAD's navigation.
- Release preparation: Addon Manager metadata with the bug tracker and
  readme links, the workbench's description, numpy (and scipy, optional)
  declared, and FreeCAD 1.0 as the minimum CI runs; a README with what you
  need, install, uninstall, privacy, and credits and licence; every file's
  licence in its header or in `REUSE.toml`, with the LGPL text for the
  shared privacy check.
- GUI pass, round 4 (FreeCAD 1.1.3, macOS). The workspace toolbars swap
  live: the switch is applied to the toolbars themselves, again after
  FreeCAD's own restore and workbench activation, and a toolbar of another
  workspace that FreeCAD shows again is hidden. Section View toggles: a
  second press closes FreeCAD's Clipping dock (its own Close), and the
  main window keeps its size. Panel buttons in Title Case and each section
  a group box with a Title Case title; the credit once, at the panel's
  foot. Mesh Tools' keys are off without a scan and say "Open a scan
  first.", as 3D Measure's are. Reverse engineer's sketch plane, notes and
  features still to come are left off the page instead of saying they are
  coming. Triangle limit is a whole number.
- The workbench as FreeCAD's design guide asks, from the GUI pass on
  FreeCAD 1.1.3: command names, menus and toolbar titles in Title Case,
  every tooltip its own full sentence. A workspace switch shows its panel
  (under Agent Link, its panel's ScanRuler tab) and keeps only its own
  toolbars, written where FreeCAD's toolbar restore reads them. A key that
  cannot run says why in the status bar ("Open a scan first: ScanRuler ▸
  Open Scan…"); Open Scan… is in the ScanRuler menu. Settings… opens
  ScanRuler's own settings dialog, About a box with the version, licence
  and the credit to Stefan Hermann (CNC Kitchen); neither is taken over by
  macOS's application menu. Undo, Redo, New, Save and Load are off the
  toolbars: FreeCAD has its own, and the project's New, Save and Open are
  in the ScanRuler menu.
- Reverse engineer, build steps 10 and 11, ported from ScanRuler by Stefan
  Hermann (CNC Kitchen): Sheet, Loft (a smooth loft whose skin crosses
  itself is refused, naming its sections), Sweep, Thicken (the wall along
  the sheet's edge said), Split (keep the largest, the smallest, what lies
  on the scan, or what lies between sheets; a fitted sheet short of the
  body is carried on to reach it), Fit surface (freeform, plane,
  cylinder), Trim and patch network bodies. Left out, refusing in words: a
  split within its sheets' regions, splitting or combining a sheet, and
  the fold check before a thicken (the kernel's own refusal stands).
- The scan's sections and measured elements are references of a Reverse
  engineer part: a sketch on a section's or a measured plane, a cut or a
  revolve by them; the split, the surface, the trim and the network read
  the scan open in the session that edits the document.
- `reverse_import_step`: a STEP file brought in as bodies of their own, the
  text kept with the part in the container.
- Trim to scan keeps a hollow's inner wall, as the original does: FreeCAD's
  mesh difference dropped a sealed shell the break never meets, or handed
  it back as a piece of its own.

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

- Trim to scan works in real FreeCAD (1.0, 1.1, newest): FreeCAD's mesh difference returns the cut gridded apart at T-junctions and wound inside out; each patch is now faced outward and joined at its seams before pieces are sorted.
