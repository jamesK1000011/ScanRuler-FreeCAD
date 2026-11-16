<!-- SPDX-License-Identifier: AGPL-3.0-only -->
# Changelog

All notable changes to ScanRuler for FreeCAD, a port of ScanRuler by Stefan
Hermann (CNC Kitchen). The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/). The dated versions below were
never tagged: the first tagged release is being prepared.

## [Unreleased]

- The ScanRuler panel follows FreeCAD Light and Studio Light: it no longer
  stays a near-black slab with grey key text that read as disabled. Its
  sheet held `palette(window)` and `palette(window-text)`, which Qt
  resolves against the application's palette, not the light theme's; the
  colours are now worked out in scanrulerfc/theme.py (ScanRuler's own copy
  of the add-ons' theme rule) from the palette of the dock or Agent Link tab
  the panel stands in: the page on the theme's window, section cards a
  shade off it (lighter in dark themes, darker in light), text and keys from
  WindowText and Button/ButtonText, each checked at 4.5:1 or better on its
  surface (a palette whose text fails its own window snaps to plain ink),
  disabled keys from the palette's Disabled group and plainly dimmer, (i)
  dots in a muted ring, the theme accent (ThemeAccentColor1, else the
  highlight) on a checked or hovered key, and CNC Kitchen blue (#1877c0,
  Stefan Hermann's ScanRuler accent) kept on primary keys and links,
  lightened in dark themes only as far as a link needs to read. Colours
  only on keys: the theme keeps their shape. Restyled on PaletteChange,
  StyleChange and a move into another dock or tab; the dark look is the
  theme's window and text as before. With no scan, 3D Measure's
  Alignment, Create element, Create dimensions and GD&T keys are disabled
  and read so; Open…, the Reverse engineer's Create feature keys, + Add
  and Play are enabled and read so.
- A file path given to any ScanRuler tool (reverse_import_step, scan_open,
  deviation_open_reference, flat_open_image, manual_plan's import and
  export, pack_setup's files, every export's path) is taken as Agent
  Link's export_file takes one: ~ expanded, a relative name in the
  session's output folder (Agent Link's outDir, ~/AgentLink by default;
  the add-on's own runner's folder alone), else the working folder.
  "rev_box.step" and "~/AgentLink/rev_box.step" failed with "cannot be
  read" (scanrulerfc/paths.py, applied where the handlers are bound).
- The 2D sheet's SVG labels name Helvetica only, so Qt no longer warns of a missing "Sans-serif" in the Report view.
- Feature editor grips read on any body: a white fill (an axis grip keeps
  its own colour) inside a near-black rim drawn under it, lit amber on
  hover and while held, no longer the ghost's own colour; sizes unchanged.
- A fillet's or chamfer's picked edges are drawn along their whole run
  (a thick line in the original editor's pick green, #3cb371, over a dark
  rim, above the body), from the body's topology as built; a pick let go
  or the box closed takes its line away.
- A click for the box leaves FreeCAD's selection as it was on every route:
  the selection is read at the press, before FreeCAD selects on the press
  or the release, so the swallowed press and release (231481b, 98355c0)
  no longer leave the last picked edge selected; a miss puts it back too,
  and Create or Cancel takes out any element the box's clicks left
  selected.

The ScanRuler workbench as FreeCAD's design guide asks it, Reverse engineer
built to the end of ScanRuler's feature list, and the add-on ready for the
Addon Manager.

- Library Pack as a service: Agent Link's `library_pack` hook service
  (scanrulerfc/pack_service.py) takes Workshop Documents' `library_pack`
  arguments (bodies, name, description, license, author, credits,
  formats, path) and runs ScanRuler's own pack_setup, pack_plan and
  pack_write (Stefan Hermann's library-pack plugin, CNC Kitchen), answering
  with the files written, `by: "ScanRuler"` and the credit. Each add-on
  packs alone; with both installed, ScanRuler's makes it.
- The ScanRuler panel fits 354 px again with a scan open: its scroll
  areas, header and credit ask for no width of their own (a scroll area's
  size hint is its page's, about 640 px on the Mac, and set the dock's
  width), lists shrink to eight letters and every label wraps. The
  "ScanRuler state" object is off the model tree (ShowInTree, set on each
  write), so it is not deleted by accident.
- What FreeCAD already owns is FreeCAD's. ScanRuler's state (the scan
  and its alignment, elements, dimensions, sections, the workspaces'
  results) is kept in the FreeCAD document, in a hidden "ScanRuler state"
  object written on each change and read when the document opens, with
  the scan and a file reference as mesh objects: FreeCAD's New, Open and
  Save carry the project, and ScanRuler's New Project, Save Project and
  Open Project… are gone. Import ScanRuler Project… brings in a
  `.scanruler` from the browser app. Move / Rotate by Numbers runs
  FreeCAD's Placement dialog on the scan object; a move made there (or
  with the transform dragger) carries the elements with the scan before the
  next tool runs. The view bar's Scan, Reference and Bodies keys and their
  Transparent and Mesh switches show and set the objects' own Visibility,
  Transparency and Display Mode ("Flat Lines"), with no state of their own;
  Elements runs `element_set_visible`; Section is FreeCAD's clipping plane
  and reads whether its dialog is open. `reverse_body_set` with `visible`
  shows or hides the body object too. Settings… is a ScanRuler page in
  Edit ▸ Preferences. Stefan Hermann's own view keys (Backfaces, Colours,
  Labels, Overlaps, Tangent Edges, Split View, Colour Plot, On Reference,
  Deviation), the snapshot key and every workspace and tool stay.
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
- On a Retina Mac a click the navigation swallowed is put at the right
  place in the 3D view (Qt's logical points scaled to Coin's device pixels
  on both axes). A refused Split view press says why once and no longer
  presses itself again through its action's signal (a RecursionError).
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
