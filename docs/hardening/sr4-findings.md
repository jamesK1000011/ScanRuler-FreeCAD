<!-- SPDX-License-Identifier: AGPL-3.0-only -->
# sr4 findings: ScanRuler's results in the FreeCAD window

ScanRuler for FreeCAD: ScanRuler by Stefan Hermann (CNC Kitchen), ported.
Input: Agent Link's window review round 3 of the ScanRuler tools (125
pictures, 20 GOOD / 64 MINOR / 41 BAD; ring in 11, result selected in about
10 of 85 changing calls). Worked from the code, stand-ins (tests/fakedoc.py,
a stand-in coin module and window in tests/test_scene.py) and the FreeCAD
1.1.3 source. Nothing here ran in FreeCAD: every "how sure" below is from
code reading and tests, and each item ends with the live check that settles
it. The live checks use Agent Link's own tools (no Python console needed),
except where a console line is marked optional.

Tests: `tests/test_scene.py` (28 tests). Whole suite, split in two halves:
538 passed / 105 skipped and 516 passed / 83 skipped (the skips need
FreeCAD).

## 1. Results never drawn in the 3D view

**Cause.** ScanRuler keeps its results in its state (elements, dimensions,
sections, marks, maps), not as FreeCAD objects; the add-on had no code that
drew them in a 3D view. The only Coin drawing was the Reverse engineer's
editor (editor_view.py), the split view (split_view.py) and an unused
legend builder (legend.py `coin_nodes`). Agent Link's echo selects FreeCAD
objects only, so it had nothing to select either. No design note in this
repository's docs/ planned it (docs/ holds only hardening notes).

**Decision.** Drawn as an overlay of the 3D view, not as document objects:
the document is not filled with a fit's every try, nothing is saved or put
on the undo stack, and headless runs are untouched. `element_to_document`
stays the way to make FreeCAD objects of elements.

**Change.**
- `scanrulerfc/scene.py` (new, pure): `plan(session, tool, args, body, memo)`
  says what to draw — elements (`element_shape`: a plane's patch and its
  normal, a cylinder's rims and four lines, a sphere's three great circles,
  cone, torus, circle, line, point; assumed diameters honoured), dimensions
  (`dimension_shape`: a line square between the two elements and "Name
  value", ✓/✗ against a limit), sections (`section_shape`: the cut chains),
  and what only this call shows (`transient`: marked points after
  scan_query / scan_segment / element_fit…, the nearest point with a line
  from the point asked for, deviation hot spots, scan_outline's loops on
  the scan's face toward the eye, mesh_cut_preview's plane, a fitted
  surface's normal). What this call made or changed is orange (`NEW`), the
  rest in the panel's colours; an alignment or a scale marks nothing new.
  It reads the state with `.get()` only, never through `dstate`, `tstate`
  or `mt_state` (they set defaults or reset): a test checks the state and
  its document signature are unchanged after drawing.
- `scanrulerfc/scene_coin.py` (new): `Builder` makes the Coin nodes (lines,
  points, labels in an `SoAnnotation` so they show over the part; plane
  faces see-through), all under one `SoSeparator` named `ScanRulerScene`
  with `SoPickStyle UNPICKABLE` (clicks still reach the scan). `Window`
  puts one such node into the scene graph of every `Gui::View3DInventor`
  of the session's document (`mdiViewsOfType`) and takes the last one out
  first. `after_call` does nothing without `FreeCAD.GuiUp`.
- `scanrulerfc/scanstate.py:155` `touched(session, tool, write, args,
  answer)`: after the state is written into the document, on the GUI
  thread (`docstate.on_gui_thread`; a job's call is drawn when the GUI
  thread runs the queued write), calls `scene_coin.after_call`. Without a
  window nothing is computed for it. `agentlink/_bridge.py:57` and
  `runner.py:204` hand the call's arguments and answer along.

**How sure.** The planning is tested on real handler answers (box scan:
fits, dimension 20.000 mm drawn 20 mm long, section at z = 10, nearest
point, 1,411 marked points, outline at z = 20, cut plane at z = 15). The
Coin part is tested on stand-ins only; the pivy calls are the ones
split_view.py and legend.py already use, plus `SoPickStyle`,
`SoPolygonOffset`, `SoAnnotation`, `SoFont`, `SoText2`, `SoPointSet`,
`SoLineSet`, `SoFaceSet`, all in FreeCAD 1.1.3's pivy. Medium-high.

**Live check** (ScanMeasureModel with WornScan, as in sr-a):
1. `scan_open { object: "WornScan", discard: true }`, then `element_fit
   { kind: "plane", at: { point: <top> }, name: "Top" }` and
   `window_snapshot`: an orange rectangle on the top face with "Top" by it.
2. `element_fit` Bottom, `dimension_add { refs: ["Top","Bottom"], type:
   "dist-plane-plane", name: "Height" }`, `window_snapshot`: Top and Bottom
   blue, a green-then-orange line between them labelled "Height 20.000 mm".
3. `section_cut { across: "XY", offset: 10, name: "Mid" }`: a magenta
   loop round the part at z = 10. `scan_nearest { at: { point } }`: an
   amber point and a line to it with "x.xxx mm".
4. `report_read`: no "ScanRuler: the results of … could not be drawn".
5. Click the scan in the window: it is still the scan that gets picked.
6. Optional console line: `import scanrulerfc.scene_coin as s;
   s.LAST` gives per document {drawn, views, map, legend, editedCopy,
   elements, dimensions, sections, items, new}.

## 2. No colour map and no legend

**Cause.** Same as 1: the maps (deviation, thickness) were drawn only in
Agent Link's offscreen pictures (render_layers.py, `view_render`); nothing
coloured the scan in the window and `legend.coin_nodes` was never called.
Draft, height, wear and segments had no per-vertex values anywhere.

**FreeCAD 1.1.3 options read** (src/Mod/Mesh/Gui/ViewProvider.cpp):
`ViewProviderMesh::tryColorPerVertexOrFace` colours a mesh from the first
`App::PropertyColorList` on its *document object* (518-552) when the view
property `Coloring` is on; `highlightSegments(colors)` (2406) colours by
mesh segments. Both write the document object (a property, or segments),
which is saved and changes the model's state: not used. Instead the scan's
own triangles are drawn again with per-vertex colours (`SoMaterialBinding
PER_VERTEX_INDEXED`) a hair in front of it (`SoPolygonOffset -1, -1`), and
the legend is legend.py's own Coin builder (an `SoAnnotation` with an
orthographic camera in the view's corner; it shows in window pictures).

**Change.** scene.py: `deviation_layer` (the map of the scan as it stands:
`d["scan"] is scan` and the same pose version, else none), `thickness_layer`,
`draft_layer` (each vertex normal's angle to the pull, degrees, grey off
the walls past nearDeg), `height_layer` (height along the map's axis or
square to its plane, over the range scan_heightmap answered; a relief or
deviation height map is not coloured), `wear_layer` (signed distance to the
wear reference inside the worn regions, read as wear_diff reads it),
`segments_layer` (each region of scan_segment's cache in the panel's
palette). `colours` uses colormap.map_values (jet, bands, caps, grey
unmeasured) exactly as the panel; `legend_model` uses legend.model with a
caption "DEVIATION · MM", "WALL THICKNESS · MM", "DRAFT · °" (ticks in
degrees). The map stays while the next calls belong to it (any deviation_,
fit_scan_, thickness_ or wear_ call after its map) and goes with the first
call that does not; it is never laid on the edited copy. legend.py
`coin_nodes(..., coin=None)` takes a coin module (tests).

**How sure.** Values and colours tested (a deviation ramp's middle is the
panel's green 0,200,0; draft 0° on a box's walls). Whether the polygon
offset wins cleanly over the scan's own Flat Lines offset in FreeCAD's
renderer: not proven. Medium.

**Live check.** `thickness_measure`, then `window_snapshot`: the scan in
jet (red thin), a legend at the right with "WALL THICKNESS · MM" and nine
ticks. `thickness_settings { limit: 12 }`: still coloured. `element_list`:
map and legend gone. `deviation_open_reference`, `deviation_align`,
`window_snapshot`: deviation colours, legend "DEVIATION · MM", "+ OUTSIDE
THE REFERENCE" / "− INSIDE THE REFERENCE". If the scan's grey shows through
in stripes (z-fighting), set the scan's Display Mode to Shaded and look
again; report which.

## 3. Mesh-tool edits not shown

**Cause.** Mesh Tools edits a copy kept in the state only
(handlers/meshtools.py `mt_state(...)["copy"]`, `meshtools/handlers.py:36`
`_edit`); the scan object in the document is replaced only when the copy is
taken into use (`mesh_use_edited` → a new Scan → docstate.sync_objects →
put_scan). Until then the window showed the original. mesh_apply_wrap makes
the wrap the edited copy, not the scan, so 7065 was right to say "in use"
for the copy and wrong to show the old block.

**Change.** scene.py `mesh_tools(st)` reads the copy and the previews
(wrap, reduced) without resetting anything; scene_coin draws the copy in
the scan's place in the scan's grey and switches the scan object's own
drawing off (`Window.scan_drawn`: `ViewObject.SwitchNode.whichChild = -1`,
the old child remembered and put back once the copy goes — after
mesh_use_edited, mesh_discard_edited or an undo — unless the person changed
it meanwhile). The object's `Visibility` (saved with the document) is never
touched. Previews are drawn see-through in teal beside it.

**How sure.** Tested with stand-ins (switch off, back on, a scan the person
hid stays hidden). FreeCAD resets the switch when the display mode or
Visibility changes (src/Gui/ViewProvider.cpp hide/show 479-500); the next
ScanRuler call switches it off again. Medium-high.

**Live check.** ScanMeshModel: `mesh_cut { plane: "XY", offset: 15, keep:
"minus" }`, `window_snapshot`: the block cut at z = 15, no full-height
block behind it. `object_get { object: "ScanRulerScan" }`: Visibility still
true. `mesh_discard_edited`, `window_snapshot`: the original block back.
`mesh_wrap`, `mesh_apply_wrap`, `window_snapshot`: the wrap's shape, not
the 12-triangle block.

## 4. Workbench, words, button and selection

**Causes.**
- The ScanRuler tools change ScanRuler's state, not the FreeCAD model, so
  data/tools.json marks 98 of them `changes: false`. Agent Link's echo
  brings a bench up only for a changing call or a declared `OPENS` read
  (agentlink/echo.py `switches_bench`, 438-444), and lights a key only then
  (`cmd = command_for(...) if switch`). None were declared, so scan_open,
  scan_info, scan_qa and every Mesh Tool stayed in the Mesh workbench (left
  there by meshobj_from_shape) and lit nothing.
- Captions: Agent Link's words come from `activity.did` templates filled
  from the arguments and the *top level* of the answer only
  (agentlink/activity.py `_FIELD = \{(\w+)\}`, `_fill` 110-137). Most
  ScanRuler answers keep their figures one level down (`element.fit`,
  `dimension.display`, `deviation.stats.rms`, `mesh.triangles`), so the
  words were the tool's name.
- Stale or missing captions on 12 + 4 calls: every one of them is a
  `heavy` tool (deviation_align, _measure, _set_target, _volume, _export,
  thickness_measure, scan_segment, scan_heightmap, mesh_cut, _cut_preview,
  _smooth, _reduce, _shell, _wrap, _trim). Inside a `batch`, Agent Link
  runs a heavy read as a job straight from the batch loop
  (agentlink/tools.py 2186-2245: `_jobs.start(tt, …)` and `_jobs.wait_for`)
  and never through `server.call`, which is what `echo.wrap` (echo.py
  3293-3317) wraps: no `before`, no `after`, so the last call's words stay
  up (or none, after a document switch). This is Agent Link's, not
  ScanRuler's.
- The hidden original stayed selected after scan_open: the echo selects
  what the arguments name (`object: "WornScan"`; echo.py `before`, `_select`
  of ARG_KEYS, and `_read_shown`), and scan_open hides that mesh on purpose
  (handlers/scan.py:68) because the scan is shown by its own object.

**Change (scanrulerfc/echo_words.py, new; agentlink_families.py 61-91).**
- `OPENS`: all 86 reads data/tools.json gives the ScanRuler workbench, but the snapshot reads
  (computed from data/tools.json). Their `changes` stays false: no undo
  step is opened for a state-only call.
- `COMMANDS["scan_open"] = "ScanRuler_OpenScan"`; `command_for` gives
  element_fit_marked and element_construct the element key of their kind
  (`ScanRuler_ElementPlane` …), the rest as before.
- `PHRASES` for the tools whose answer has its figure at the top today
  (scan_nearest "… vertex 2601, 5 mm away", scan_query, scan_segment,
  scan_draft, scan_heightmap, align_auto, align_clear, scan_scale,
  deviation_export, mesh_undo).
- `WORDS = echo_words.words(name, args, body)`: words with the measured
  value for every tool family ("Fitted Top (plane, flat to 0.0412 mm)",
  "Dimension: Height = 20.000 mm, in tolerance", "Aligned the scan to the
  reference: fit RMS 0.0213 mm, …", "Cut at XY plane, Z 15 mm: edited copy
  6,738 triangles", "Wall thickness: 1.9 mm to 4.2 mm, 12 % under the
  limit, 3 thin spots"). Read from the call's own answer only.
- `SELECTS_FOR = echo_words.selects(name, args, body, doc)`: the scan's own
  mesh object after scan_open / mesh_use_edited / scan_scale, the
  reference after deviation_open_reference.

**How sure.** OPENS, COMMANDS, command_for and PHRASES use hooks the Agent
Link at d385404 reads: high. WORDS and SELECTS_FOR do nothing until Agent
Link reads them (below). The heavy-read cause is from reading tools.py and
matches all 16 pictures; the fix is Agent Link's.

**Live check.** In one `batch`: meshobj_from_shape, scan_open { object },
scan_info, scan_qa, mesh_smooth. After each, `session_state`: the active
workbench is ScanRuler for scan_open on (not Mesh), and the echo trace has
`button: ["ScanRuler_OpenScan", …]` for scan_open, `["ScanRuler_MeshSmooth",
…]` for mesh_smooth. Then outside a batch `scan_nearest`: `window_snapshot`
shows "Nearest scan point: vertex …, … mm away". Inside a batch,
`deviation_volume` (heavy): the caption still says the call before it —
until Agent Link adds the job echo below.

## 5. RuntimeWarnings (NaN) in the Report view

**Causes.**
- `scanrulerfc/heightmap_core.py` `covered` (452/453 before): a triangle
  seen edge-on (its projection a line, `den` 0) was divided by 0 inside
  `np.errstate(ignore)`, then `s + t` and `t * (…)` ran outside it: inf −
  inf and inf × 0 → "invalid value encountered in add / multiply". Any wall
  that stands at a slant square to the view does it (a block turned about
  Z; a worn block's chamfers), so scan_outline (and scan_heightmap's
  callers of `covered`) warned.
- `scanrulerfc/segment.py:98` (before): `sqrt(rough / seed_limit)` on
  every vertex. On a flat face the unit normals' dot comes out a rounding
  over 1, so `rough` is −2e-16: sqrt of a negative → NaN, and the cast of
  NaN to int64 → "invalid value encountered in sqrt / cast". Only seeds
  (`ok`) are ever sorted by that key.

**Change.** covered (heightmap_core.py 448-460): `flat = |den| > 1e-12`
first, divide by `where(flat, den, 1)`, s and t −1 where not flat, so no
infinity is made; the cells covered are the same. segment.py 98-105: the
key from `np.where(ok, clip(rough, 0, seed_limit), seed_limit)`; a hair
under 0 is flat (bucket 0), as meant.

**How sure.** Reproduced before the change with warnings as errors (block
turned 37° about Z; 12-triangle CAD block turned 30° and 45°):
scan_outline failed on "invalid value encountered in add", scan_segment on
"in sqrt". After: none. scan_segment finds the same 6 regions with the
same vertex counts; the outline's area is unchanged. Tests:
`NoNaN` in tests/test_scene.py. High.

**Live check.** ScanMeasureModel: `scan_segment`, `scan_heightmap { axis:
"-z" }`, `scan_outline { axis: "-z" }`, then `report_read`: no
"RuntimeWarning" and no "invalid value encountered".

## 6. align_auto offset, and the panel after undo / redo

**align_auto (4017).** The transform *is* applied to the shown mesh:
`model.align_auto` (model.py:752) → `apply_rigid` → `transform_all` →
`Scan.set_pose` → `on_pose` → `docstate.attach_scan.write`
(docstate.py:748-768) sets the scan object's Placement (on a job thread it
waits for the GUI thread, `flush_pose`). The offset is what auto-align is
for: it reads a coordinate system off the scan alone — base on its largest
flat face at z = 0, long side along X, zero *under the middle* of the base
(its tools.json description) — and does not fit the scan to any reference.
The Block made by part_primitive keeps its corner at the origin, so the
scan, centred, stands half a block off in X and Y: what the picture shows.
A best fit to the reference is deviation_align. Nothing to fix in the
maths; the words now say it: "Auto-aligned the scan to its own axes
(planes, standing on its face): not a fit to a reference" (PHRASES), and
WORDS adds "turned 0.x°, moved y mm". Auto-align has no RMS (it is no
fit); `square.axes[].tiltDeg` says how square it came out.
How sure: high from code; the half-block offset matches.
**Live check.** After `align_auto`, `object_get { object: "ScanRulerScan" }`:
its Placement equals the answer's `applied` (rotation and translation, as a
first alignment). `scan_info`: box min z = 0 and the box centred on X and Y.
Then `deviation_open_reference { body: "Block" }`, `deviation_align`,
`window_snapshot`: scan and Block overlap.

**Panel after undo / redo (8056 / 8061).** The ScanRuler panel draws again
only when scanstate's version or last tool moves (dock.py `tick`, `poll`),
which only a ScanRuler call does. Agent Link's history_undo / history_redo
(and Edit › Undo) change the document, so the Reverse engineer's features
changed while the panel kept what it read before: 0 after the undo of a
clear, then (refreshed by a ScanRuler read in between) 9 after its redo —
"one step behind". Change: `dock.history_mark(doc)` = (UndoCount,
RedoCount); `tick` draws again when it moves (dock.py:55, 288-294, 300).
How sure: high for the cause; the fix is tested for the mark only.
**Live check.** `reverse_feature_clear`, `history_undo`, `window_snapshot`
of the ScanRuler panel (`window_snapshot { part: "ScanRuler" }`): Features 9.
`history_redo`: Features 0.

## Not changed here

- 6079 / 6117: a second ScanMeasureModel tab after deviation_export, and
  6136 doc_switch not bringing its document to the front: deviation_export
  writes a file and touches no window (handlers/deviation.py `export`);
  both look like Agent Link's document handling. Live check: after
  `deviation_export`, `window_snapshot` and count the document tabs.
- 10 (panel section not following wear_setup, fit_scan_*): not in this
  round's list.
- The stale Mesh Info task left by meshobj_from_shape: Agent Link's (below).

## What Agent Link must add (exact names)

1. **Echo for a heavy read inside a batch** (cause of the 16 stale or
   missing captions). agentlink/tools.py, the batch loop's `if heavy_read:`
   branch (2186-2245): call the echo around the job as `server.call` does.
   Suggested: `echo.wrap` (echo.py:3293) keeps its Echo on the server
   (`server.echo = echo`); the branch calls `server.echo.before(tt, hargs)`
   before `_jobs.start(tt, dict(hargs), s)` and, when the job is done,
   `server.echo.after(tt, hargs, {"content": [{"type": "text", "text":
   json.dumps(hbody)}], "isError": not hok})`.
2. **WORDS** in `echo.declare(fam)` (echo.py:722): keep callables from
   `getattr(fam, "WORDS", None)` in a list `WORDS_FNS`; in `Echo._after`
   take the first non-empty `fn(name, args, body)` and say it in place of
   `read_words(what, result)` (reads) and `change_words(what, body)`
   (changes), and in the Activity row's "what". Or, instead, let
   activity.py `_FIELD` take dotted paths (`{deviation.stats.rms}`) so
   PHRASES can reach a nested figure.
3. **SELECTS_FOR** in `echo.declare`: callables `fn(name, args, body, doc)
   -> [object names] | None` in `SELECT_FNS`; in `Echo._after`, for reads
   (`_read_shown`) and changes, select what the first one names instead of
   what the arguments name. Texturizer's `SELECTS` ({tool: answer key},
   texturizer/fam_texture.py:62) is the dict form of the same hook; neither
   is read by declare() today.
4. **Never select a hidden object** in `_select` / `_add_sel` (echo.py
   1779-1860): skip objects whose `ViewObject.Visibility` is False (scan_open
   hid WornScan on purpose; it stayed selected).
5. **Close the task the echo opened** when the next call brings another
   bench up: the Mesh Info task from meshobj_ calls stayed open over the
   ScanRuler calls (sr-b 6131, 7008-7042). In `Echo.before`, when `wb` is
   switched and `FreeCADGui.Control.activeDialog()` is a dialog the echo
   itself opened, `FreeCADGui.Control.closeDialog()`.
