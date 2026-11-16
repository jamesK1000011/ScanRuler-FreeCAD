# ScanRuler-FreeCAD hardening pass: reverse, meshtools, flat (62 tools)

> **Merge note (16 Nov 2026).** This pass and the other ScanRuler pass (scanruler-measure-findings.md) were merged into one
> checkout. Both fixed the document write from a job's thread, differently; the merged rule is one:
> nothing writes the document from a worker thread; with a window up the write (the state, and the scan
> object's Placement after a best fit) is queued to the GUI thread, and without a window it is left for
> the next ScanRuler call on the document's thread (`docstate.on_gui_thread`, `docstate.mark`,
> `docstate.flush_pose`). Where the text below says otherwise, the merged rule holds. Every writer of
> its `path` in both passes' families declares `writes`. Still unrun on FreeCAD.

Checkout: ScanRuler-FreeCAD at 1f51d6b. ScanRuler is Stefan Hermann's (CNC Kitchen); every credit
line (each entry's `source`, the files' headers, CREDIT) is untouched.

**Nothing here ran on FreeCAD.** FreeCAD is not installed where this pass ran. What did run: the
add-on's plain-Python tests (935 passed, 0 failed, in four pieces: one whole-suite run was killed
by the machine, not by a test), and the mesh and 2D handlers themselves in plain Python on a
12-triangle box and a synthetic PNG (they are numpy; that is where the models' numbers come from).
The Reverse engineer's geometry needs FreeCAD's Part: only its argument shapes, ids, refusals and
parameters ran, on the add-on's stand-in kernel. FreeCAD source read: tag 1.1.0 (the Mac runs
1.1.3). FreeCAD tests added are unrun.

Patch: scanruler-reverse.patch (18 files; no new files, so FILES is unchanged).
Models: scanruler-meshtools-model.json (64 calls), scanruler-flat-model.json (64),
scanruler-reverse-model.json (57). Every one of the 62 tools is called at least once; every call
was checked against its input schema.

## Counts

- Tools checked: 62 (reverse 22, meshtools 24, flat 16). Descriptions rewritten: 62.
  `workbench`, `words` on all 62; `commands` on the 19 that have a ScanRuler command of their own
  (checked in scanrulerfc/workspaces.py; no FreeCAD command is claimed: the tools work on the
  ScanRuler scan, not on a document mesh, and Agent Link's meshobj tools already hold the Mesh_ ones).
- Bugs fixed: 17 (list below). Refusals reworded to say the next step: 30 or so.
- Declared heavy: 9 more (mesh_inspect, mesh_cut, mesh_cut_preview, mesh_smooth, mesh_offset,
  mesh_reduce, flat_open_image, flat_calibrate, flat_detect_edges), beside mesh_shell, mesh_wrap,
  mesh_trim which were.

## Cross-cutting findings (read these first)

1. **Document writes from a job's thread (fixed, in a shared file).** Every ScanRuler tool call ends
   in `scanstate.touched` -> `docstate.mark`, which writes the ScanRulerState object and the scan's
   Mesh::Feature into the FreeCAD document whenever the state changed. Agent Link runs a heavy
   `changes: false` tool as a job on a worker thread (agentlink/jobs.py start(): `threading.Thread`,
   named "agentlink-job-<tool>"), and its own rule for a job is "changes nothing and touches neither
   Qt nor the 3D view". So mesh_shell, mesh_wrap, mesh_trim — and the other agent's deviation_*,
   thickness_measure, scan_segment, section_fit — wrote document objects from a worker thread.
   Fix: scanrulerfc/agentlink/_bridge.py skips the write when on a job thread
   (`scanstate.touched(..., write=False)`); the next ScanRuler call off a job writes it (mark writes
   whenever the state's signature differs). **These two files are shared with the other ScanRuler
   agent's families: expect a merge conflict if they touched them.** Not fixed: `S.before`
   (pull_pose) still runs on the job thread; it reads, and writes only when the person moved the
   scan object since the last call. Cost left as it is: mark re-encodes (zip + npz) the whole state,
   the edited copy included, after every state-changing call — on a scan of millions of triangles
   that is seconds a call (not measured).
2. **All mesh and 2D tools are `changes: false`** (their state is the session's, not the document's),
   so they carry no health and FreeCAD's undo does not touch them: every description now says so and
   names mesh_undo. Two of them did change the document and are now declared so, with `reads` for
   the calls that do not: `mesh_export { to: "document" }` (adds a Mesh::Feature) and
   `flat_curvature { comb: true }` (adds a Part::Feature). Before, those ran without a transaction or
   health and could be sent to a job thread. Checked against agentlink/protocol.py Tool.changes_for
   with the schema defaults added (`to: "file"`, `comb: false`).
3. **`writes` was declared by no tool of this add-on**, so Agent Link's path guard checked
   mesh_export, flat_export and flat_render paths as files to read: nothing stopped a write into
   ~/Library or of a .plist / .command (agentlink/paths.py check(), NEVER_WRITE_EXT). Declared now.
   The other agent's writers (export_csv, scan_heightmap's picture, pack_write, manual_render …)
   need the same; not mine to touch.
4. **The "shape lost at recompute" lesson, for reverse.** The engine is built right for it: the
   container and each body are Part::FeaturePython objects whose execute() takes the shape from the
   build, so nothing written is lost. Two real holes: (a) a body's execute() read an unbuilt builder
   when a recompute reached it before its container had built in this session — a reopened document
   and `recompute { force: true }`, or anything that touches a body: the body wrote an EMPTY shape
   over the one the file held (bodies run before their container: its Group puts it after them).
   Fixed: Body.execute calls restored_build first. FreeCAD test added, unrun: this is the riskiest
   change, and the reverse model ends with the check (save, close, open, forced recompute,
   object_list). (b) The other direction is by design and now stated in the descriptions: a cut, a
   fillet or a placement written into a ReverseBody by another tool is lost at the next build.
   Workshop's hw_hole / thread_cut "written shape would not stay" guard should refuse a ReverseBody
   too (it is a Part::FeaturePython with a proxy): wish for the Workshop side.
5. **Edge and face numbers.** The reverse tools never store an index: an index is turned into a
   fingerprint at the call and the build finds it again by geometry. The trap is which body the
   index counts on (the body as built now), and for reverse_feature_update that body already carries
   the feature's own work. Descriptions and a reply note say so, with the rollback road. The indices
   are 0-based and are not FreeCAD's Face1 / Edge1: said in reverse_body_describe.
6. **The scratch document** (reverse/kernel.py Scratch: Part::Extrusion with TaperAngle,
   PartDesign::Draft, PartDesign::Chamfer, Part::Fillet with radius pairs) was checked for both
   lessons. Inputs go in as plain Part::Feature (they keep the shape written); results are read
   after the scratch document's own recompute and copied. `FreeCAD.newDocument(name, hidden=True,
   temp=True)` exists in 1.1 (src/App/ApplicationPy.cpp) and puts the active document back for a
   temp document (src/App/Application.cpp). `import PartDesign` loads the App module, no workbench
   and no window: it does not wait on a start-up dialog. Not verified live: a nested recompute of
   the scratch document from inside the container's execute(), and PartDesign::Draft's face names on
   a BaseFeature in 1.1.3.
7. **mesh_reduce's tolerance is not millimetres to FreeCAD.** Mesh.decimate(tol, 1.0) hands tol to
   Simplify::simplify_mesh as a bound on the quadric error of a triangle, used only to decide when to
   stop (src/Mod/Mesh/App/Core/Simplify.h); collapses are governed by the algorithm's own threshold
   schedule. The tool measures the result afterwards and says `held`; the description and the guide
   no longer promise "within tolerance". Not fixed (an iteration until it holds would be a feature).
8. **Sparse (CAD-style) meshes.** A meshed box is 8 vertices: mesh_trim finds no break, flat_fit's
   edge methods find 3 points on a section's side, mesh_smooth has nothing to fit. The refusals now
   say mesh_densify (then mesh_use_edited and section_cut again). The models densify first.
9. **Health reading added** (reverse/doc.py health_reading, registered from agentlink_families as
   the brief allows): a failed feature fails no FreeCAD object, so the shared check stayed green
   while the part was wrong. Red now, after a reverse_ tool only, with the first three failures.
   agentlink_families.py is shared with the other agent: the addition is at the end of the file.
10. **Three tests pinned every tool's description to an old commit** (tests/test_reverse_wiring.py
    twice, tests/test_wiring.py once). One already failed at 1f51d6b (six tools of the other agent's
    families had changed). They now hold what the pass's rules hold: no tool lost, no input lost, no
    new required input, group unchanged. The other agent will have had to touch the same tests.

## Size limits and timings

Measured in a Linux container on this pass with plain Python and numpy — NOT on the Mac, and
without FreeCAD. The descriptions give them with that caveat.

| tool | measured | source-derived limit |
|---|---|---|
| mesh_smooth | 39 s at 131,072 triangles; 3 s at 8,800 | a patch fitted per vertex in Python, 2 passes |
| mesh_wrap | 2 s on 12 triangles, 363 s on 86,068 (same gap, 230,000 grid points) | grid at most 6,000,000 points (wrap.py MAX_GRID_POINTS) |
| mesh_cut | 5 s at 131k, 16 s at 524k | clips each crossed triangle in Python |
| mesh_inspect | 1.8 s at 131k, 13 s at 524k | |
| mesh_offset | 1.5 s at 131k, 10 s at 524k | |
| mesh_reduce | Python part about 12 s at 524k (facet list 4.6 s, two distance checks 3.6 s each); FreeCAD's decimation not measured | |
| mesh_export | facet list 4.6 s at 524k; the write not measured | |
| mesh_boolean | 2 s at 131k with a 400-triangle cutter | |
| mesh_shell | 2.5 s at 131k; 5 to 7 s with a dense result | 12,000,000 grid points (shell.py MAX_POINTS) |
| mesh_trim | 0.7 s at 131k | surface search can refuse past about 4.2 million triangles (grid.py MAX_FILED / 8) |
| mesh_densify | 0.4 s for 131k -> 524k | refused past 20,000,000 triangles |
| mesh_fill_holes | 1.2 s at 131k, one 8 mm hole | 250,000 patch points |
| mesh_mirror, mesh_remove_islands | under 1 s at 131k | |
| flat_open_image / detect / calibrate | edges 0.6 s at 4 Mpx, 4.2 s at 16 Mpx | about ten float64 arrays the size of the image: 1.3 GB at 16 Mpx; no guard on the Qt reader (the zlib reader refuses past 268 Mpx) |
| flat_objects | 1.1 s at 16 Mpx | |
| reverse (all) | not measured: the kernel is FreeCAD's | builds cannot be stopped (reverse_build_stop is refused) |

## reverse (22)

Checked against: reverse/handlers.py, doc.py, build.py, features.py, part_file.py, kernel.py
(Scratch and the Part calls it names), FreeCAD 1.1 source: src/App/Application.cpp,
src/App/ApplicationPy.cpp, src/Mod/PartDesign/App/FeatureDressUp.cpp, FeatureDraft.cpp,
src/Gui/ViewProviderGeometryObjectPyImp.cpp (ShapeColor still reads and writes in 1.1).
The 2,259-line kernel was NOT audited call by call: it has its own FreeCAD tests in CI.

- reverse_feature_add — fixed: an added sketch was answered `status: "rolledBack"` (a sketch has no build row; "rolledBack" now only below the bar; rows carry name and kind). Fixed: `tool`, `bodies`, `sheet`, `target` take a body's name as `body` does (a name in moveBody's `bodies` was dropped silently and the call refused as "not ready"). Refusals for a bad index and an unbuilt body say what to read next. Doubtful: the record shapes of kinds other than sketch, extrude, revolve, fillet, moveBody, import were not exercised. Description: yes.
- reverse_feature_update — fixed: `body` by name, a thread's `face`, `variable` edges and a draft's `groups` by index were stored as they came (only `edges` / `faces` were turned into fingerprints), so the build read a number as a fingerprint. Added: a `note` when picks came by index (they count on the body after this feature). Doubtful: live behaviour of a fillet re-picked that way. Description: yes.
- reverse_feature_remove — nothing wrong found. Description: yes.
- reverse_feature_move — nothing wrong found (moved_list's refusals already say the step). Description: yes.
- reverse_feature_suppress — nothing wrong found. Description: yes.
- reverse_feature_rollback — nothing wrong found; its use for re-picking is now described. Description: yes.
- reverse_feature_clear — nothing wrong found; says the STEP texts stay in the container (StepFiles is not cleared: source). Description: yes.
- reverse_feature_list — nothing wrong found. Description: yes.
- reverse_feature_schema — nothing wrong found; the description adds the allowed values the schema does not list (extent kinds, ops, a revolve's axis: read in features.py / resolve.py). Description: yes.
- reverse_build — nothing wrong found. Description: yes.
- reverse_build_stop — always refused by design; the refusal now says what to do instead. Description: yes.
- reverse_parameter_list — nothing wrong found. Description: yes.
- reverse_parameter_add — nothing wrong found. Description: yes (name rules and functions from parameters.py / expression.py).
- reverse_parameter_set — refusal lists the parameters there are. Description: yes.
- reverse_parameter_rename — nothing wrong found. Description: yes.
- reverse_parameter_remove — nothing wrong found. Description: yes.
- reverse_body_names — nothing wrong found. Description: yes (says the bodies are the build's output).
- reverse_body_describe — nothing wrong found; indices are 0-based and not FreeCAD's: said. Description: yes.
- reverse_body_check — fixed (find_body): a body is found by the name reverse_body_set gave it. Description: yes.
- reverse_body_clearance — same find_body fix. A kernel error here reaches the agent as Agent Link's generic "failed" (KernelError is not a refusal): left. Description: yes.
- reverse_body_set — fixed: the name and the colour were put only on a body object made after the call (sync_bodies styled added bodies only): an existing body kept its label and colour. Now applied to kept bodies inside the same edit, written only when they differ. FreeCAD test added, unrun. Description: yes.
- reverse_import_step — refusals say where a relative path is looked for and that only STEP comes in. Not verified: a large file's time. Description: yes.

Bugs fixed in reverse: 6 (the body emptied on recompute; styles not applied; body not found by its
given name; update's unresolved picks and names; names in tool / bodies / sheet; the sketch's
"rolledBack").

## meshtools (24)

Checked against: handlers/meshtools.py, meshtools/handlers.py, mesh_core.py, meshtools/*.py,
FreeCAD 1.1 source: src/Mod/Mesh/App/MeshPyImp.cpp (addFacets takes a list of three-point
sequences; decimate(float, float) and decimate(int); write() picks the format by extension: .stl is
binary, .3mf is there; Mesh(…) constructor), src/Mod/Mesh/App/Mesh.cpp, Core/Decimation.cpp,
Core/Simplify.h. Every handler but mesh_reduce, mesh_apply_reduced and mesh_export (which need
FreeCAD's Mesh module) ran in plain Python.

- mesh_parts — added: `wrap` and `piece` (the previews mesh_wrap and mesh_trim leave were listed nowhere). Description: yes.
- mesh_inspect — nothing wrong found; declared heavy. Description: yes.
- mesh_remove_islands — refusals give the sizes and the next step. Description: yes.
- mesh_delete_marked — nothing wrong found ("marked" is refused with the alternative already). Description: yes.
- mesh_flip_normals — nothing wrong found. Description: yes.
- mesh_cut — refusal now gives the offsets the mesh runs between; declared heavy. Description: yes.
- mesh_cut_preview — declared heavy (it does the cut's work). Description: yes.
- mesh_mirror — fixed: with offset left out the plane went through the middle of the scan in use, not of the edited copy (after a cut, the wrong place); every other default reads the mesh worked on. Note the middle is rounded to a 1-2-5 step of about a fiftieth of the diagonal (original behaviour, now said). Description: yes.
- mesh_fill_holes — refusals: no open rim (invalid_state), and no rim under size with the smallest rim's size; `at` does not lift the size limit (it read as if it did). Description: yes.
- mesh_smooth — nothing wrong found; declared heavy (the slowest edit). Description: yes.
- mesh_offset — nothing wrong found; nothing guards a shrink past half a wall: said, not fixed. Declared heavy. Description: yes.
- mesh_reduce — finding 7 above; declared heavy. NOT run. Doubtful live: whether `m.Topology` after decimate carries unreferenced points (harmless to the measures), and `held` on a curved part. Description: yes.
- mesh_apply_reduced — NOT run (needs a reduced mesh). Nothing wrong found by reading. Description: yes.
- mesh_discard — fixed: `what: "wrap"` was refused as "not ported" though mesh_wrap is ported and the schema offers it. Description: yes.
- mesh_use_edited — nothing wrong found. Description: yes.
- mesh_discard_edited — nothing wrong found. Description: yes.
- mesh_undo — nothing wrong found; says it is not FreeCAD's undo and there is no redo. Description: yes.
- mesh_export — fixed: declared a change for `to: "document"` (finding 2) and a writer (finding 3). NOT run. Doubtful live: the label "<scan name> <part>" when the scan's name has no extension. Description: yes.
- mesh_densify — nothing wrong found. Description: yes.
- mesh_boolean — fixed nothing in the maths; refusals name element_list / object_list. A document object matched by Name and another by Label is still refused as two ("the name wins" is Agent Link's rule; left). Description: yes.
- mesh_shell — nothing wrong found; the cavity is sealed, no drain: said. Description: yes.
- mesh_wrap — nothing wrong found in the maths; its cost grows with the input's triangles (table), which the old "any triangles do" hid; `tolerance` is accepted and unused: said. Description: yes.
- mesh_apply_wrap — nothing wrong found. Description: yes.
- mesh_trim — refusal on a sparse mesh now says mesh_densify. Description: yes.

The panel's words in the maths' refusals ("Fill holes", "Decimate it first", "Smooth on a marked
region", "flip the side") are left as Stefan Hermann's panel says them; the handlers add the tool
(handlers/meshtools.py `said`). Bugs fixed in meshtools: 5 (discard wrap, mirror's middle, export's
two declarations, parts not listing previews) plus the job-thread write.

## flat (16)

Checked against: handlers/flat.py, flat_core.py, flat_objects.py, curvature.py, geom2d (by use),
FreeCAD: Part.makeLine / makePolygon / Compound into a plain Part::Feature (keeps the shape
written). Every handler but flat_render (needs Agent Link's renderer) and the comb ran in plain
Python, the image through the add-on's own PNG reader (not Qt's QImage, which the Mac will use).

- flat_objects — nothing wrong found in the maths. Description: yes.
- flat_profile — fixed (with flat_calibrate / flat_open_image): `object` could read an outline left by another image or in the old units. Refusals say the next step. Description: yes.
- flat_open_image — fixed: an image of the same file name opened again kept the old elements, dimensions and notes ("in place of what was there" held only for another name); flat_objects' numbers are cleared too. Declared heavy. Doubtful live: the QImage path (Format_Grayscale8, constBits) on PySide6, and memory on a large scan (no guard). Description: yes.
- flat_calibrate — fixed: notes and the alignment's zero point stayed at their old coordinates while elements were scaled; flat_objects' outlines stayed in the old units. Reply adds units, scaledBy, note. Declared heavy. Description: yes.
- flat_detect_edges — nothing wrong found; declared heavy. Description: yes.
- flat_curvature — fixed: declared a change for `comb: true` (finding 2). The default "straight" threshold is 0.002 or four times the chain's scatter (the old description said nothing; a noisy outline reads all straight): said. Comb NOT run. Description: yes.
- flat_edges — nothing wrong found; chain numbers are not the list's order: said. Description: yes.
- flat_fit — an edge fit that fails now gives the point count and the way out (densify, or pick points). Seed methods refused as before. Description: yes.
- flat_dimension_add — refusal now lists each type's order (a line then a point was refused with "in that order" and no more). A line-line distance over 3° is added and reads invalid (original behaviour): said. Description: yes.
- flat_note_add — nothing wrong found; notes are not drawn by flat_render: said. Description: yes.
- flat_edit — nothing wrong found; when several of note / element / dimension are given the note wins: said. Description: yes.
- flat_remove — nothing wrong found. Description: yes.
- flat_set_alignment — nothing wrong found; only the report and the exports read in the aligned frame: said. Description: yes.
- flat_render — fixed: declared a writer; ".png" added when missing; the off-sheet refusal gives the sheet's extent. NOT run. Description: yes.
- flat_report — nothing wrong found; a file's own scale reads "UNCALIBRATED — nominal" though units are mm (original wording): said. Description: yes.
- flat_export — fixed: declared a writer; a path without its extension was written as given (mesh_export adds it); an unwritable path is a refusal, not a crash. Trap said: on an uncalibrated image the file's "millimetres" are pixels. Description: yes.

Bugs fixed in flat: 6 (same-name image keeps the old sheet; stale object outlines; notes and
alignment not scaled; export's extension; comb and writers undeclared).

## Tests

Changed: tests/test_reverse_wiring.py and tests/test_wiring.py (finding 10),
tests/test_reverse_import_step.py (the refusal keeps the original sentence and adds the next step).
Added (in existing files): tests/test_meshtools_added.py Hardened, HardenedData (7 plain tests);
tests/test_flat.py Hardened (4 plain); tests/test_reverse_handlers.py Hardened (4 plain);
tests/test_reverse_doc.py Hardened (2 plain) and HardenedInADocument (2 FreeCAD tests, unrun: the
reopened part through a forced recompute; a body wearing a name and colour given later).

## Could not do

- Run anything on FreeCAD: mesh_reduce, mesh_apply_reduced, mesh_export, flat_render, the comb, and
  all Reverse engineer geometry are unproven.
- Audit reverse/kernel.py's 250-odd operations call by call, or the record shapes of the 20 feature
  kinds the reverse model does not use.
- Guides for reverse and flat: no new files were added (FILES is not mine to regenerate); the
  workflows are in the descriptions. A reverse guide is worth writing once the model has run.
- A guard on image size in flat_open_image, and on shrink depth in mesh_offset: both would be new
  behaviour without a measured limit.

## Wishes for other owners

- Agent Link health.py: nothing needed. Workshop: refuse a ReverseBody in the "written shape would
  not stay" guard. The other ScanRuler agent: `writes` on their file-writing tools; check the
  _bridge.py / scanstate.py / agentlink_families.py / base-pinned test overlaps when merging.
