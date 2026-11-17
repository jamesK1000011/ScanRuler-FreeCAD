<!-- SPDX-License-Identifier: AGPL-3.0-only -->
# Changelog

All notable changes to ScanRuler for FreeCAD, a port of ScanRuler by Stefan
Hermann (CNC Kitchen). The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/). The dated versions below were
never tagged: the first tagged release is being prepared.

## [Unreleased]

- Window pass 3. Every ScanRuler tool's caption says what it did with its
  key values (the 2D sheet, print fit, scan noise, repeat, wear, Mesh
  Tools, the Reverse engineer, the report); flat_profile's caption was its
  help text. Agent Link's own tools keep their words. A flat_ call draws
  the 2D sheet in the 3D view: an image as a texture with its edges, or a
  section's sheet on its plane, with the fitted elements, dimensions with
  their values, notes and the zero point; the camera turns square onto the
  sheet and frames it (it stayed zoomed into a corner after a comb). With
  an image on the sheet the scan is put away and the panel's header names
  the image. Mesh Tools' edited copy and previews are drawn a hair toward
  the eye (they striped against the solid the scan came from).
  reverse_feature_clear says what the document still shows. view3d gains
  flat (sheet, counts, corners, texture, framed) and inFront.
- Window review round 7 of the 3D-view overlay. The legend card is laid
  out in the view's device pixels from the words it holds (it ran past the
  view's right edge while its words were drawn at a fixed pixel size): it
  stands against the right edge, under the navigation cube and above Agent
  Link's caption; the ends' words wrap, the figures take one or two
  columns as they fit, close ticks are thinned and a small view gets a
  smaller font. A tick's value gets more places when the ticks stand
  closer than three can tell (a ±0.001 mm scale read +0.001 on every
  tick). Labels are a 40th of the view's height (12 to 28 px), bold, on a
  light backing (FreeCAD's SoTextLabel). The answer's view3d facts give
  the legend's box against the view, its tick strings and the label node.
- Window review round 6 of the 3D-view overlay. Colours went to Coin as
  0..255, so Coin's 32-bit packing swapped them: what a call made showed
  blue and the rest orange; they are 0..1 now (new #e8590c, element
  #1877c0, CNC Kitchen blue), segment colours too. Labels scale with the
  view and the screen's pixel ratio (12 to 22 px, 2 more for the new one)
  and are plain ASCII. The legend has its title (what is mapped and its
  unit), every tick's value and its figures on a light card at the right
  edge, at a readable size. fit_scan_* keep the ScanRuler workbench (the
  Workshop's "fit" key no longer wins). Sections move and scale with the
  part (align_*, scan_scale, a move in FreeCAD), as ScanRuler's own do;
  align answers say how many moved. The panel is drawn again right after
  each call and once more on the next turn of Qt's loop. With a window, the
  answer carries view3d: the colours, label size, legend words, where the
  first section stands and the panel's version.

- Results drawn in FreeCAD's 3D view (window review round 3: the panel
  listed them, the view showed only the grey scan). After each ScanRuler
  call, with a window only, one overlay node in each 3D view of the
  document (scanrulerfc/scene.py, scene_coin.py) draws the fitted and
  constructed elements, the dimensions with their values, the sections,
  marked points, the nearest point, hot spots, an outline and a cut plane —
  what the call made in orange — and the call's colour map on the scan
  (deviation, wall thickness, draft, height, wear, segments) with its
  legend, gone with the first call that does not show it. Mesh Tools'
  edited copy is drawn in the scan's place while it stands, the scan
  object's own drawing switched off (its SwitchNode; its Visibility, which
  is saved, is left alone). View state only: no object, property or undo
  step; nothing changes headless. The window echo is told which reads
  bring the ScanRuler workbench up and light their key (OPENS: scan_open,
  scan_info, scan_qa, the Mesh Tools stayed in the Mesh workbench), the
  Open Scan… and element keys for scan_open, element_fit_marked and
  element_construct, words with the measured value (PHRASES today; WORDS
  and SELECTS_FOR for an Agent Link that reads them). The panel draws
  again on an undo or a redo (it kept the Reverse engineer's features from
  before). scan_segment and scan_outline no longer write RuntimeWarnings
  (NaN) to the Report view on a turned or CAD-tessellated block. Findings
  in docs/hardening/sr4-findings.md.

- The scan's mesh object holds its points in the scan's own order (built
  from Vector points and tuple triangles, the form FreeCAD 1.1 takes); a
  document read back puts the triangles on the right points again, also
  for documents saved before (scan_info read a small block as 9,049,056
  mm², found live, run 4). A best fit's transform (deviation.align
  transform and total) is kept in the document and read back. Findings in
  docs/hardening/scanruler6-findings.md.

- Hardening pass on the reverse, meshtools and flat tools (16 Nov 2026;
  nothing here ran on FreeCAD when written). Descriptions rewritten with
  inputs, traps, size limits and what the reply holds; `workbench`,
  `commands` and `words` added for Agent Link's tool index. Fixed:
  a Reverse engineer body emptied itself when a recompute reached it before
  its container had built in this session (a reopened document and
  `recompute { force: true }`); `reverse_body_set`'s name and colour were
  never put on an existing body's object, and the name could not be used to
  find the body; `reverse_feature_update` kept a body's name and picks by
  index as they came; an added sketch was reported `rolledBack`; a failed
  feature now turns Agent Link's health check red. `mesh_export { to:
  "document" }` and `flat_curvature { comb: true }` are declared as the
  document changes they are, and `mesh_export`, `flat_export`, `flat_render`
  as writers of their path; `mesh_discard { what: "wrap" }` was refused as
  not ported; `mesh_mirror` without offset took the scan's middle, not the
  edited copy's; `flat_calibrate` left notes, the alignment and
  `flat_objects`' outlines in the old units, and an image opened again under
  the same name kept the old elements; `flat_export` wrote a path without
  its extension as given. `mesh_inspect`, `mesh_cut`, `mesh_cut_preview`,
  `mesh_smooth`, `mesh_offset`, `mesh_reduce`, `flat_open_image`,
  `flat_calibrate` and `flat_detect_edges` are declared heavy.

- Hardening pass on the scan, elements, align, dimensions, sections,
  deviation, thickness, wear, fit-scan, scan-cad, scan-noise, scan-thread,
  snapshot, catalog, pack and manual tools (16 Nov 2026; nothing here ran on
  FreeCAD when written). Descriptions and refusals rewritten; `workbench`,
  `commands` and `words` added. Fixed: `fit_scan_measure { calibrate: true }`
  no longer needs a session `fit` (it answers `calibrated: false` and the
  `fit` call to make); `scan_snapshot_wait` no longer holds the window it
  waits on (on the GUI thread it answers at once with the `job_start` call
  that waits beside it); `scan_heightmap { of: "deviation" }` refused with a
  code the format does not have; the text report printed `np.float64(…)`;
  `element_to_document` with no document crashed; the reference-side
  deviation map ignored its cap on readings (its `spacing` now opens until
  the cap holds). `scan_cloud`, `scan_heightmap`, `export_csv`,
  `deviation_export`, `wear_rebuild`, `wear_prewarp`, `fit_scan_export`,
  `manual_render` and `pack_write` are declared writers of their path, and
  five more tools heavy.

- A tool that Agent Link runs as a job (on a worker thread) never writes
  the FreeCAD document from that thread: the ScanRuler state, and the scan
  object's Placement after `deviation_align`, are handed to the GUI thread
  when a window is up (they land a moment after the answer), and without a
  window are written by the next ScanRuler call (both passes' fixes, made
  one: `docstate.on_gui_thread`).

- The ScanRuler tab of Agent Link's panel is registered with
  `own_credit=True` (and its page widget says `own_credit`), as Agent
  Link's hooks.md describes: the page's foot already credits Stefan Hermann
  (CNC Kitchen), so Agent Link hides its own credit line while the tab is
  in front. An older Agent Link without the argument still gets the tab.
- Tests: the older-Agent-Link check puts ScanRuler's modules and Agent
  Link's registrations back as they were after importing fresh copies
  (left purged, nine later tests in the reverse editor, split view and
  wiring met module copies their stand-ins were not set on), and the
  shared-file check skips the Agent Link and Workshop checkouts CI places
  inside this repository.

## 0.5.0 — 2026-11-16

- scan_segment finds the faces of a sparse, CAD-style mesh. ScanRuler's
  vertex growing (kept as it was, and still run first) needs a dense scan:
  on a drum exported from CAD (572 triangles, 288 vertices, all on its two
  rims) it found 0 regions, every vertex sitting on a crease with a normal
  halfway between cap and side. When it finds nothing and half or more of
  the vertices sit on creases, the triangles are grouped instead
  (scanrulerfc/segment_sparse.py, written for this port): triangles in one
  plane make a plane, a smooth strip of faces square to one axis whose
  corners lie on a cylinder within maxRms makes a cylinder (`kind:
  "cylinder"` with axis, point, radius, length and `bore`). The drum now
  reads as one cylinder (r 20, sigma 0) and two caps meeting it at 90°.
  The answer says which ran (`method`: vertices or faces) and `why`;
  `method: "faces"` or `"vertices"` asks for one. Dense scans segment
  exactly as before.
- Reverse engineer's Fillet and Chamfer: a click on or just beside an edge
  takes the edge, though the view's pick found the face beside it: the
  edge nearest the click is taken within 8 pixels at the view's zoom
  (never under 2 mm), where it was 2 mm at any zoom. A miss now says how
  far it looked. (A live run's clicks on a box's top edges landed on the
  top face beside them and were not taken.)
- thickness_measure is about 15× faster on big scans: rays are cast in
  runs of 256 with origins close together, each run against only the
  triangle leaves its segments can reach, in place of ordering every leaf
  for every ray (a 124,000-triangle shell: 40 s → 2.4 s here, readings
  identical). A scan of more than `maxPoints` vertices (300,000 by
  default; 0 for all) is measured at that many, spread evenly, the others
  taking the thinnest reading among their neighbours; the answer's
  `thickness.sampled` and the report say how many were measured, and the
  statistics are over those.
- thickness_measure, deviation_measure, deviation_set_target,
  deviation_volume and scan_segment are declared heavy in tools.json
  (Agent Link's mechanism for add-on tools): Agent Link runs them as jobs,
  answering in line when they finish within its wait, and gives them a
  heavy job's deadline instead of a client's 80 s.
- layout.py in step with Agent Link's again (the panel's dock back to its
  start width once when it comes back too wide), and a test that fails
  when this copy of Agent Link's shared helpers differs from Agent Link's
  (tests/test_shared.py, skipped when Agent Link is not checked out beside
  this repository).
- A release test: package.xml, `scanrulerfc.VERSION` and the changelog's
  newest version agree, package.xml is dated, the changelog has an
  Unreleased section, the README's install links and the credit to Stefan
  Hermann (CNC Kitchen) are there.
- README: the by-hand install from a release or main as a zip.

- Boolean (mesh_boolean) and Trim to scan now cut with meshbool, a boolean
  written for this add-on in numpy alone, in place of FreeCAD's Mesh
  booleans. On a 140,698-triangle scan minus a 5,212-triangle cutter
  (an M18 shell test drive) Mesh.difference came back with 2,607 open
  edges and 7,417 bad ones, and the result was then turned inside out patch
  by patch (volume −133,160 mm³); with a Part solid as the cutter it removed
  515 mm³ of ~100,000. meshbool decides every crossing by one orientation
  sign computed once for each set of four points, so the edges two
  triangles share always agree; it splits only the triangles the other
  surface crosses (the rest keep their exact points and indices, in order)
  and keeps or drops each piece by its winding number. The same cut is now
  closed: 319,977.8 → 218,258.6 mm³ in about 3 s, subtract + intersect
  adding back to the scan exactly. Works without FreeCAD (no "unavailable"
  any more), needs no decimating, refuses rather than hands back a result
  that is not closed. A solid inside an App::Part container is now placed
  with the container's placement too.

- Section cards in the ScanRuler panel no longer open an empty band of
  about 20 px above their caps header (Model, Alignment, Create Element…)
  in FreeCAD Dark and Studio Light, seen on the Mac after the translucent
  cards. The cards were QGroupBoxes, and FreeCAD's theme sheets make a group
  box reserve its title band (margin-top / padding-top and ::title) even
  with no title; zeroing the box's margin and padding (da16591) did not
  remove it. Cards are now plain QFrames (object name
  ScanRulerSection_<id> kept, marked by a `card` property), styled by
  `#ScanRulerPage QFrame[card="true"]` with the same translucent background
  and border and no margin or padding of their own. Their inner margins
  (GROUP_MARGINS in scanrulerfc/pages/kit.py) are 4 px on every side: the
  header as far from the top edge as rows from the sides, and no taller
  than the cards were, so the panel needs no scroll bar at a width where it
  had none.
- The ScanRuler panel lets the theme paint it: under Studio Light and
  FreeCAD Light the page and cards stayed near-black, because those themes
  restyle by stylesheet while the Mac's QPalette stays dark, so any colour
  read from the palette was the dark one. The panel's sheet
  (scanrulerfc/theme.py) now sets no page background and no text colour:
  the page is see-through over the theme's own painting (inner scroll areas
  and the page stack transparent), labels and keys take the theme's text and
  QPushButton style. Section cards are a translucent overlay with a
  translucent mid-grey border (rgba(127,127,127,…)) that reads as a card on
  light and dark alike. Light or dark is detected from what the theme
  actually renders behind the panel (the nearest ancestor that paints an
  opaque pixel of its own, QWidget.render without children), else from a
  Dark/Light stylesheet name, else left unknown (the neutral overlay); the
  palette is never used for it. Dark themes look as before: the card 6%
  toward white, CNC Kitchen blue (#1877c0, Stefan Hermann's ScanRuler
  accent) filling primary keys with white text, links lightened as far as
  they need. Light and unknown: a blue outline on the theme's own primary
  key, links in #1877c0 (darkened on a known light card only as far as
  4.5:1 needs). Disabled keys and labels keep a translucent grey text and
  border, plainly dimmer than an enabled key on both. The snapshot card's
  credit is the theme's text faded (an opacity effect), no longer
  palette(mid).
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
