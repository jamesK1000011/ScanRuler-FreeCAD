# ScanRuler-FreeCAD hardening: scan, elements, align, dimensions, sections, deviation, thickness, wear, fit-scan, scan-cad, scan-noise, scan-thread, snapshot, catalog, pack, manual

> **Merge note (16 Nov 2026).** This pass and the other ScanRuler pass (scanruler-reverse-findings.md) were merged into one
> checkout. Both fixed the document write from a job's thread, differently; the merged rule is one:
> nothing writes the document from a worker thread; with a window up the write (the state, and the scan
> object's Placement after a best fit) is queued to the GUI thread, and without a window it is left for
> the next ScanRuler call on the document's thread (`docstate.on_gui_thread`, `docstate.mark`,
> `docstate.flush_pose`). Where the text below says otherwise, the merged rule holds. Every writer of
> its `path` in both passes' families declares `writes`. Still unrun on FreeCAD.

16 Nov 2026. Checkout: ScanRuler-FreeCAD (Stefan Hermann's / CNC Kitchen's ScanRuler ported to FreeCAD, AGPL). Every `source` credit line in data/tools.json is untouched; a test now asserts each entry still names Stefan Hermann.

**Nothing here ran on FreeCAD.** FreeCAD is not installed in this container. What did run: the add-on's plain-Python tests, and the handlers themselves in plain Python on a numpy-built mesh of the test model's part (FreeCAD-only steps left out). Times below are from that container (2 shared cores), not the Mac.

Not touched: the reverse, meshtools and flat families (handler files and tools.json entries), FILES, CHANGELOG.md, Agent Link.

## Counts

- Tools checked: 71 of 71 in these 16 groups. Descriptions rewritten: 71. `workbench` / `commands` / `words` added: 71 (workbench left off catalog, pack, manual and snapshot, which belong to no workbench).
- Bugs fixed in code: 8 (below). Data fixes: 9 tools now declare `writes`, 5 more declare `heavy`.
- Refusals reworded to say what to do next: about 35 sites in 8 files.
- Tests: 17 new, 3 stale tests rewritten.

## Bugs fixed (proven from source or by running the plain-Python handlers)

1. **Document written from a worker thread.** Agent Link runs a heavy read as a job on a worker thread (agentlink/jobs.py), and every other call on the GUI thread (agentlink/gui_link.py header). After a heavy ScanRuler read, `scanstate.touched` → `docstate.mark` added objects and wrote the state property from that worker thread, and `deviation_align` set the scan object's Placement from it mid-call (`Scan.set_pose` → `on_pose`). Fixed in docstate.py: `on_gui_thread(fn)` runs at once on the GUI thread or with no window, and from a worker queues fn to the GUI thread through a Qt queued signal, not waited for (the GUI thread may be the one waiting on the job). Both write sites go through it. **Riskiest change.** Proven on stand-ins only. Side effect to know: after a job, the state lands in the document a moment after the answer, not before it.
2. **`fit_scan_measure { calibrate: true }` crashed on a good run under Agent Link.** It called `session.fit(...)`; no session in Agent Link or Workshop has `fit` (grep of both repos; only the test's stand-in did). Now: where the session has none, the run still answers, with `calibrated: false` and `calibrateNext` giving the exact `fit { action: "calibrate", hole, shaft }` call.
3. **`scan_snapshot_wait` froze the window it waits on.** A plain call runs on the GUI thread and blocked it for up to 600 s; the person's camera key lives in that window, so no shot could come, the client drops the call at about 80 s, and the watchdog may stop FreeCAD. Now on the GUI thread of a FreeCAD with a window it does not wait: `came: false, waited: 0` and `next` with the `job_start { …, wait: false }` call that waits beside the window. Off the GUI thread it waits as before.
4. **Nine tools that write their `path` did not say so** (scan_cloud, scan_heightmap, export_csv, deviation_export, wear_rebuild, wear_prewarp, fit_scan_export, manual_render, pack_write). Agent Link's path guard (agentlink/paths.py `check`) then treated the path as one to read: no home-or-session-folder rule, no hidden-folder rule, no refusal of script extensions or of an existing .FCStd. `"writes": true` added.
5. **`scan_heightmap { of: "deviation" }` refused with code `internal`**, which is not one of the format's codes, and said nothing to do. Now `failed`, naming deviation_align / deviation_set_target.
6. **The text report printed `np.float64(…)`** for a constructed element's numbers (numpy 2's repr). Plain numbers now.
7. **`element_to_document` with no document** raised AttributeError (the add-on's own runner allows doc None). Now refused (invalid_state) naming doc_new; `import Part` moved to where it is used so the refusal comes first.

8. **The reference-side map ignored its own cap on readings.** on_reference.wanted_spacing sizes the pieces to keep 200,000 readings at most, counting on pieces of about spacing²/8; long thin triangles (a CAD tessellation's fans and bore strips) are halved far more often. On the test part `deviation_hotspots { on: "reference" }` made 1,835,008 readings and took 1,419 s. New `on_reference.cut_within` opens the spacing until the cap holds (160,768 readings at 1.7 mm on the same part; the full read was not timed again — by proportion about two minutes here). The answer's `spacing` is the one used. Coarser than before on such parts: say if the old density mattered.

Also: tests/test_wiring.py `test_only_the_added_tools_differ_from_before_the_gui` compared descriptions with commit 4bb0eff and was already failing wherever Agent Link is importable (scan_segment, deviation_*, thickness_* had changed in a3c80f0). Rewritten to what must hold: no tool gone, none changed group or read/change, no input removed. The two like it in tests/test_reverse_wiring.py (Registry and Family dumps) failed the same way at HEAD and got the same rewrite. **The other ScanRuler agent will hit these tests: expect merge conflicts there.**

Test runs here: every test file run on its own in plain Python, all passing (FreeCAD ones skip); the files I touched also pass with Agent Link on the path. One failure left that is not mine and is there at HEAD too: with Agent Link importable and tests/test_wiring.py run before it in one process, tests/test_decoupled.py `test_family_layer_says_hosted_and_provides_the_manual_maker` finds `scanrulerfc._hosted` False (an order effect between the two files; alone it passes). The whole suite in one process did not finish here (tests/test_meshtools_added.py alone takes two minutes on this machine and the run was cut off), so the per-file run is what stands.

## Heavy: what is declared, and why

Agent Link sends a heavy read to a job; past 45 s the call answers with a job id. Times at 68,000 vertices / 137,000 triangles, plain Python in the container:

| Tool | Time | Heavy |
|---|---|---|
| thickness_measure | 70 s (all points); about 20 s at maxPoints 20,000 | already |
| deviation_align | 32 s auto, 9 s from points | already |
| deviation_measure | 6.5 s | already |
| deviation_set_target | 0.06 s | already (left) |
| scan_segment | 1.2 s | already (left) |
| section_fit | 0.07 s for 400 points | already (left) |
| deviation_volume | 2.6 s (60 mm part, 0.24 mm cell) | already |
| manual_render | not measured (needs FreeCAD) | already |
| **scan_qa** | 9 s | **added** |
| **scan_heightmap** | 5 s first call, 1.5 s after | **added** |
| **deviation_hotspots** | under 0.1 s on scan; `on: reference` 1,419 s before fix 8, not timed after | **added** |
| **deviation_export** | at once for side scan; side reference is the same slow reading | **added** |
| **manual_check** | not measured; source: 17 OCC booleans per placed part against everything in place | **added** |

Not declared heavy, with reasons: scan_open and scan_scale touch the scan's document object directly (GUI thread only), so their descriptions state the limit instead (2,000,000 triangles warning; time not measured). element_fit and the other changing tools cannot be jobs. scan_outline 0.6 s, scan_draft 0.3 s, scan_pattern 0.3 s, scan_thread 0.25 s, wear_diff 1.4 s, fit_scan_measure 0.1 s, align_auto and align_symmetry 0.7 s. pack_write: not measured.

## Per tool

"1.1 source" is the FreeCAD 1.1.0 checkout (the Mac runs 1.1.3; nothing found here that a point release would change, but that is not verified). "Sim" means the handler ran in plain Python on the test part and answered what the model file expects. Every description was rewritten.

### scan
- **scan_open** — checked against docstate.py's use of Mesh::Feature, Placement and App::PropertyFileIncluded; `object` matches type Mesh::Feature exactly, by label or name. Not run. Doubtful: reading time of a large file and of `Mesh.Topology` on a large mesh (not measured); the state is re-encoded into the document on every changing call, cost grows with the scan (not measured).
- **scan_nearest** — sim. Snaps to a vertex, not to a triangle: stated.
- **scan_query** — sim. Found while testing: a box 0.2 mm thick over a top face also takes a pocket's wall vertices; stated as a gotcha.
- **scan_segment** — sim. On a densified CAD mesh a round wall comes back as its facets; stated.
- **scan_fit_surface** — sim. Refusals reworded.
- **scan_qa** — sim. Now heavy.
- **scan_draft** — sim. **Doubtful:** patches are linked by the median point spacing; on an unevenly sampled mesh (densified CAD) the flat walls did not gather at all and the bore split into rings. Stated in the description; not changed (it is ScanRuler's method, right for real scans).
- **scan_pattern** — sim (count 1 on a block). Refusals reworded.
- **scan_heightmap** — sim for height, levels and deviation. Now heavy and writes. Picture path not run.
- **scan_outline** — sim.
- **scan_cloud** — sim. Now writes.
- **scan_info** — sim.

### elements
- **element_fit** — sim for plane and cylinder. Fit refusals keep ScanRuler's own words and add what an agent does next.
- **element_fit_marked** — sim.
- **element_construct** — sim for point-three-planes, point-line-plane, line-plane-plane, plane-symmetry.
- **element_rename, element_unlink, element_set_visible, element_list** — sim.
- **element_remove** — sim. The old description did not say there is no way back; the new one does.

### align
- **align_datum** — sim. Origin refusal now says what was given and what it takes. Doubtful live: the scan object's Placement following (docstate `_placement` builds a FreeCAD.Matrix; not run).
- **align_auto, align_symmetry, align_clear** — sim.
- **scan_scale** — sim. Doubtful live: the scan's Mesh::Feature is rebuilt at the new size on the GUI thread; time not measured.

### dimensions
- **dimension_add** — sim for six types. The old description did not say `limit` needs `kind`; a call without it fails the schema. Stated: form tolerances are read over every point of the region, including those the sigma cut-off dropped.
- **dimension_set_limit, dimension_set_basic, dimension_remove, report_get** — sim.
- **export_csv** — sim. Now writes.

### sections
- **section_cut** — sim for cuts. The shadow uses `Part.Face.makeOffset2D(by, 2, False, False, False)` and `Wire.discretize(Distance=)`: both checked against 1.1 source (TopoShapePyImp.cpp takes them positionally; a face in gives faces out). Not run.
- **section_get, section_list, section_remove, section_fit** — sim.
- **section_to_sketch** — checked against 1.1 source: `Rotation(x, y, z, "ZXY")`, `Part.ArcOfCircle(circle, a0, a1)` with a0 < a1 always (chainsegment.profile_curves), `Sketcher.Constraint("Coincident", g1, p1, g2, p2)`, MapMode Deactivated. Not run. Stated: the Placement is inside the Body's own coordinates, so a moved Body puts the sketch off the scan.

### deviation
- **deviation_open_reference** — `MeshPart.meshFromShape(Shape=, LinearDeflection=, AngularDeflection=, Relative=)` is used as elsewhere in Agent Link; MeshPart's source is not in the sparse checkout, so **not verified against source**. Doubtful: a body inside a moved container is read in its own coordinates; tessellation time of a large curved part not measured.
- **deviation_align** — sim for points and auto. Writes the scan object's Placement: now through the GUI-thread hand-over.
- **deviation_measure, deviation_set_target, deviation_settings** — sim. **Doubtful:** on a scan with no noise the automatic colour range came out ±1.2e-13 mm (suggest_range on a map that is almost all zero). Real scans have noise; left alone, stated in the descriptions.
- **deviation_hotspots** — sim on scan and, once, on reference (coveredPct 100, mostMissing -1.0 at the pocket; 1,419 s, fix 8). Now heavy.
- **deviation_volume** — sim: one region, kind excess, 93 mm³ for the 100 mm³ pocket. **Naming trap, not a bug:** here "excess" is material the reference has and the part lacks (tests/test_volume_maths.py confirms), the opposite of the map's and hotspots' "excess". The new description says so in capitals; the model file checks it.
- **deviation_export** — sim for the report. Now heavy and writes.

### thickness
- **thickness_measure** — sim. Stated: the automatic maxThickness is a fifth of the diagonal, so a 20 mm plate on a 75 mm part read as unmeasured until maxThickness was raised.
- **thickness_settings** — sim.

### scan-noise, scan-thread
- **scan_noise** — sim (the CAD refusal). The reading itself needs a noisy scan.
- **scanner** — sim for add, list, remove. Refusals reworded.
- **scan_thread** — sim (plain wall: verdict none). Names thread_cut, which exists.

### wear
- **wear_setup** — sim. Stated: `reset: true` wins over values given in the same call (it is applied after them).
- **wear_diff** — sim.
- **wear_rebuild, wear_prewarp** — sim. Now write.

### fit-scan
- **fit_scan_setup, fit_scan_features, fit_scan_export** — sim (json).
- **fit_scan_measure** — sim, with the calibrate fix.

### scan-cad
- **element_to_document** — checked against 1.1 source: Part.makeCylinder / makeCone / makeSphere / makeTorus / makeCircle / makePolygon, Face1 of each as the lateral surface, exportStep. Not run. Stated: plain shapes that do not follow the element; a second call makes a second set.

### snapshot
- **scan_snapshot_list, scan_snapshot_latest** — sim (empty store).
- **scan_snapshot_wait** — fixed (above). Live check needed: the `job_start { wait: false }` route.

### catalog, pack, manual
- **catalog_part, catalog_links, catalog_provenance** — sim.
- **pack_setup** — sim. **pack_plan** — read. **pack_write** — `Mesh.export([obj], path)` and `Shape.exportStep` as used elsewhere; not run. Now writes.
- **manual_plan** — sim (empty plan). **manual_check** — read; now heavy. **manual_render** — read; now writes.

## Wishes for Agent Link (not mine to change)

- `job_status { wait }` and the 45 s wait of a job both block the GUI thread. For scan_snapshot_wait that means only `job_start { wait: false }` plus an unwaited `job_status` leaves the window free.
- agentlink_families.py SHOWN names `deviation_stats` and `thickness_stats`, which do not exist (harmless).
- docs/hardening/inventory.json has no `export_file`, which scanrulerfc/paths.py's comment mentions (a comment only).

## For the main session

- Regenerate FILES? Not needed: no file added or removed.
- CHANGELOG.md left alone to avoid colliding with the other ScanRuler agent. Suggested Unreleased lines: document writes after a job go to the GUI thread; fit_scan_measure calibrate no longer needs a session fit; scan_snapshot_wait no longer holds the window; nine tools declare writes, five more heavy; descriptions and refusals rewritten.
- Shared files I edited that the other agent may also touch: scanrulerfc/data/tools.json (only my 71 entries), scanrulerfc/model.py, scanrulerfc/scanstate.py, scanrulerfc/docstate.py, scanrulerfc/on_reference.py, tests/test_wiring.py, tests/test_reverse_wiring.py (two dump tests only).
