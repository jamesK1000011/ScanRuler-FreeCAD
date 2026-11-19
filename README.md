<!-- SPDX-License-Identifier: AGPL-3.0-only -->
# ScanRuler for FreeCAD

> An independent port: not an official CNC Kitchen or FreeCAD project, and not endorsed by the FreeCAD project association (FPA), whose trademark FreeCAD is.

- [What it is](#what-it-is)
- [What you need](#what-you-need)
- [Install](#install)
- [First steps](#first-steps)
- [Screenshots](#screenshots)
- [The workbench](#the-workbench)
- [What is ported](#what-is-ported)
- [Troubleshooting](#troubleshooting)
- [Uninstall](#uninstall), [Privacy](#privacy), [Tests](#tests)
- [Credits and licence](#credits-and-licence)

How it plugs into Agent Link, with a diagram: [docs/workflow/](https://github.com/jamesK1000011/ScanRuler-FreeCAD/blob/main/docs/workflow/README.md).

## What it is

ScanRuler for FreeCAD measures 3D scans in FreeCAD.
A 3D scan is a mesh: many small triangles that a scanner or photos make of a real part.
With this add-on you can measure the scan, fit planes, holes and other shapes to it,
compare it with a CAD part (a deviation map), check wall thickness, and rebuild the part as a CAD model (reverse engineering).

It is ported to FreeCAD from **ScanRuler by CNC Kitchen** (https://github.com/CNCKitchen/ScanRuler; see NOTICE.md).
Licensed AGPL-3.0-only, the same as ScanRuler.

It works alone, as a FreeCAD workbench (a set of toolbars and menus for one kind of work).
With [Agent Link for FreeCAD](https://github.com/jamesK1000011/AgentLink-FreeCAD), an AI agent can use all of its tools for you, in the background.
Checks such as deviation and wall thickness tell you if a part is feasible. They are never a sign-off.

Repository: https://github.com/jamesK1000011/ScanRuler-FreeCAD (until 14 Nov 2026 it lived in the `freecad/ScanRulerFC` folder of a ScanRuler fork; its history came with it).

## What you need

- FreeCAD 1.0 or newer (1.1 recommended), on macOS, Linux or Windows.
- numpy, which comes with FreeCAD. scipy, when FreeCAD has it, makes a
  few steps faster (large-reference deviation searches, symmetry, mesh grids,
  flatbed parts); they run without it.
- Nothing else: no other add-on, no account, no network.
- Optional: [Agent Link for FreeCAD](https://github.com/jamesK1000011/AgentLink-FreeCAD) and an MCP client (for example Claude Desktop), so that an agent can use the tools.

## Install

Pick one, not two.

### With Agent Link's Claude Desktop extension (easiest)

1. Install [Agent Link for FreeCAD](https://github.com/jamesK1000011/AgentLink-FreeCAD#install) with its Claude Desktop extension.
2. Start a new chat.

The extension installs this add-on for you into FreeCAD's `Mod` folder as `ScanRulerFC`,
at the commit its tests passed with.

### Addon Manager (custom repository, until it is listed)

1. In FreeCAD, open **Edit ▸ Preferences ▸ Addon Manager**.
2. Under *Custom repositories*, add `https://github.com/jamesK1000011/ScanRuler-FreeCAD`, branch `main`.
3. Open **Tools ▸ Addon manager**. Find **ScanRuler for FreeCAD**. Click **Install**.
4. Restart FreeCAD.

### By hand

1. Download a release from [Releases](https://github.com/jamesK1000011/ScanRuler-FreeCAD/releases)
   (or the current [main as a zip](https://github.com/jamesK1000011/ScanRuler-FreeCAD/archive/refs/heads/main.zip)).
2. Unzip it into FreeCAD's `Mod` folder. To find the folder, type `FreeCAD.getUserAppDataDir()` in FreeCAD's Python console.
3. Rename the folder to `ScanRulerFC`.
4. Restart FreeCAD.

A `git clone` into `Mod/ScanRulerFC` works too.

Then pick **ScanRuler** from the workbench list and use **ScanRuler ▸ Open Scan…**.

## First steps

**With an agent** (Agent Link installed). Start a new chat and try these prompts:

1. "Open the scan bracket.stl and tell me how big it is."

   The agent opens the scan. The ScanRuler tab of the Agent Link panel shows it.
   The agent tells you the size in millimetres.

2. "Fit a cylinder to the big hole and tell me its diameter."

   The agent fits a cylinder to the hole. The fitted shape shows on the scan, and the agent gives the diameter.

3. "Compare the scan with my CAD part bracket.step and show me where it is off."

   The agent aligns the scan to the part and measures the deviation.
   You see the scan coloured by how far each point is from the part, and the worst spots.

**Without an agent.** Pick the **ScanRuler** workbench, use **ScanRuler ▸ Open Scan…**,
and use the keys of the 3D Measure workspace.

## Screenshots

<!-- screenshots: no screenshots are in the repository yet. Take these and add them under docs/images/:
- FreeCAD with the ScanRuler workbench, a scan coloured by its deviation map, the ScanRuler panel beside the model tree
- the ScanRuler workspaces toolbar and the 3D Measure page
- a wall thickness colour map
- the Reverse Engineer page with a section fitted and made into a sketch
- the ScanRuler tab in the Agent Link panel
-->

No screenshots yet.

## The workbench

It is a **ScanRuler workbench** of its own, laid out as the original: the
workspace tabs (3D Measure, Surface Deviation, Wall Thickness, 2D Measure,
Mesh Tools, Reverse Engineer) as the "ScanRuler Workspaces" toolbar, each
workspace's keys as its toolbars (only the open workspace's show), the view
bar in the bottom toolbar area, the ScanRuler panel beside the Combo View
(under Agent Link, its panel's ScanRuler tab) and the status strip (READY,
element and dimension counts, "ScanRuler · CNC Kitchen"). Names follow
FreeCAD's design guide (Title Case). The ScanRuler menu holds Open Scan…,
Import ScanRuler Project…, Snapshot and About. What FreeCAD already does
is FreeCAD's: its New, Open and Save carry ScanRuler's state (the scan,
its alignment, elements, dimensions, sections and the workspaces' results
are kept in the FreeCAD document, in a hidden "ScanRuler state" object,
with the scan and the reference as mesh objects); Move / Rotate by Numbers
is FreeCAD's Placement dialog on the scan (the elements move with it); the
Section key is FreeCAD's clipping plane; the view bar's show, Transparent
and Mesh keys set the objects' own Visibility, Transparency and Display
Mode; the settings are a page of Edit ▸ Preferences. A key that cannot run
yet says why in the status bar. Colour maps start on `jet`, as the
original's do. Import ScanRuler Project… reads a `.scanruler` project from
the original browser app (its scan, fitted elements and sections, and its
Reverse engineer part, which needs FreeCAD's Part kernel). It needs no
other add-on.

It also adds its tools to **Agent Link**, the FreeCAD add-on that lets an agent
drive FreeCAD. Agent Link finds it at run time by convention, not by name:
it loads any package on the path that holds an `agentlink_families` module
(here `scanrulerfc.agentlink_families`). Put this folder in FreeCAD's `Mod`
folder next to Agent Link, or on `PYTHONPATH`. Agent Link is a separate
add-on under its own licence and never imports this one by name. Against an
older Agent Link, hooks it lacks (pictures, wall readers, guides) are
skipped and the tools still load. Under Agent Link the panel is the
"ScanRuler" tab of Agent Link's panel, the workbench's keys run as the
agent's calls do, and the panel follows the agent to the workspace of the
last tool it ran.

The tool names are ScanRuler's own (`scan_open`, `element_fit`,
`deviation_align` …), so ScanRuler's guides read the same here.
Everything is in millimetres.

## What is ported

- **scan, elements, align, dimensions** (3D Measure): `scan_open`, `scan_info`, `scan_nearest`, `scan_query`, `scan_segment`, `scan_qa` (the check before modelling), `scan_fit_surface` (plane, bilinear or quadric with curvature), `scan_draft` (draft against a pull), `scan_pattern` (rotational repeats), `scan_heightmap` (heights along an axis, with levels); `element_fit` (plane, sphere, cylinder, cone, torus, circle, point; ScanRuler's patch → LMedS → region growing → clipped Gaussian fit), `element_fit_marked`, `element_construct` (28 methods), `element_list`, `element_rename`, `element_remove`, `element_set_visible`; `align_auto` (read off the scan), `align_datum` (3-2-1), `align_symmetry`, `align_clear`, `scan_scale`; `dimension_add` (sizes and GD&T), `dimension_set_limit`, `dimension_set_basic`, `dimension_remove`, `report_get`, `export_csv`.
- **deviation** — `deviation_open_reference` (STEP, IGES, BREP tessellated
  finely; STL, PLY, OBJ, OFF, 3MF; or a solid in the document),
  `deviation_align` (auto, points, local: ScanRuler's prealign, Horn's
  absolute orientation and point-to-plane ICP; the scan's vertices are moved
  onto the reference), `deviation_measure`, `deviation_settings`,
  `deviation_set_target`, `deviation_hotspots`, `deviation_volume`,
  `deviation_export` (coloured PLY, CSV, NPY, the text report).
- **thickness** — `thickness_measure`, `thickness_settings`.

The maths is numpy only (`dev_*.py`, `wall_thickness.py`): nearest points
and rays go through a two-level tree of triangle leaves, every query of a
pass at once. The deviation map is also read on the reference (`on: "reference"`). Not
ported yet: closing a scan's holes with the reference before the volume
error (an open scan reads `unsure` there instead).
- **Sections** (`sections` group): `section_cut`, `section_get`,
  `section_list`, `section_remove`, `section_fit` (ScanRuler's
  `reverse_section_fit`: lines and arcs with residuals) and
  `section_to_sketch`, which writes the fitted profile as a Sketcher sketch in
  a PartDesign body, ready for `pd_pad`.
- **Mesh Tools** (`meshtools` group, ScanRuler's Mesh Tools plugin):
  `mesh_inspect`, `mesh_remove_islands`, `mesh_delete_marked`,
  `mesh_flip_normals`, `mesh_cut`, `mesh_cut_preview`, `mesh_mirror`,
  `mesh_fill_holes`, `mesh_smooth`, `mesh_offset`, `mesh_reduce` (FreeCAD's
  `Mesh.decimate`, measured as ScanRuler measures it), `mesh_apply_reduced`,
  `mesh_discard`, `mesh_use_edited`, `mesh_discard_edited`, `mesh_undo`,
  `mesh_densify`, `mesh_boolean` (with solids: elements or document
  objects; needs FreeCAD), `mesh_trim` (a repair piece cut to the scanned
  break; needs FreeCAD), `mesh_shell`, `mesh_wrap`, `mesh_apply_wrap`,
  `mesh_export` (the edited copy, the reduced mesh, the trimmed piece or the
  wrap), `mesh_parts`. Edits go on a copy until `mesh_use_edited`.
  These are ScanRuler's scan-grade edits; Agent Link's `meshobj_*` tools are
  FreeCAD's own mesh operations on document meshes. The two meet in the
  document: `mesh_export { to: "document" }` puts the edited scan there, and
  `scan_open { object }` takes a document mesh in to measure.
- **2D measure** (`flat` group): `flat_open_image`, `flat_calibrate`,
  `flat_detect_edges`, `flat_edges`, `flat_fit`, `flat_dimension_add`,
  `flat_report`, `flat_export` (DXF, SVG), `flat_curvature` (the curvature
  comb read as straight, arc and transition stretches; `comb: true` draws it,
  on the part in the section's plane). The sheet is an image or the section
  cut last.

Up to date with ScanRuler 0.11.2 where it bears on measuring: form
tolerances read the minimum zone (`min_zone.py`), a section laid on a bottom
face cuts, DXF text stays on one line, a fit's guide moves and scales with
the part, and Mesh Tools refuses the scan's vertex numbers on a copy that has
moved on.

- **Into the document** (`scan-cad`): `element_to_document` puts the fitted
  planes, cylinders, cones, spheres and tori into the FreeCAD document as
  Part geometry (solids or surfaces), lines, circles and points as reference
  edges and vertices, and can write them as STEP — ScanRuler's `files.step`,
  where PartDesign can take them as references.

### ScanRuler's plugins

- **Scanner noise** (`scan-noise`): `scan_noise` (this scan's noise, as the
  scan check reads it), `scanner` (your scanners in `scanners.json`, exported
  and imported whole). The noise to plan with — the larger of the scanner's
  usual and this scan's — is what the thread, wear and print-fit tools read.
- **Thread match** (`scan-thread`): `scan_thread` names a thread from a
  fitted bore or boss — ISO metric, UNC, UNF, UNEF, NPT, G/R pipe, Tr, ACME
  and the 45° print form — or says which sizes tie and the one hand
  measurement that settles them.
- **Wear repair** (`wear`): `wear_setup`, `wear_diff`, `wear_rebuild`
  (against the mirrored other half or the aligned reference),
  `wear_prewarp` (a model moved against a print of it, with the stop rule).
- **Print fit from a scan** (`fit-scan`): `fit_scan_setup`,
  `fit_scan_features`, `fit_scan_measure` (scale, contour and hole offsets,
  elephant foot; can become Agent Link's fit calibration),
  `fit_scan_export` (Bambu Studio, OrcaSlicer, PrusaSlicer keys, or your own
  key map; a pre-compensated STL).
- **Parts catalog** (`catalog`): `catalog_part` (a screw, nut, washer or
  bearing from measured sizes), `catalog_links`, `catalog_provenance`. The
  library searches and downloads stay in scanruler-mcp.
- **Assembly manual** (`manual`): `manual_plan`, `manual_check` (each
  part's way in swept against the parts there; the words linted),
  `manual_render` (one HTML page with a picture per step). The line-art
  sheets and themes wait for a GUI.
- **Library pack** (`pack`): `pack_setup`, `pack_plan` (upstream licences
  checked), `pack_write` (a zip, every file scrubbed of personal details).
- **Snapshot** (`snapshot`): the camera key (Alt+Shift+S) takes a picture
  of the window for the person to mark up and note; `scan_snapshot_list`,
  `scan_snapshot_latest` and `scan_snapshot_wait` let the agent read them. Only the
  person takes a shot.
- **Reverse engineer** (`reverse`, a deferred group: listed only when a
  session asks for it): the Reverse engineer engine of ScanRuler by Stefan
  Hermann (CNC Kitchen), ported to FreeCAD under `scanrulerfc/reverse/`.
  The feature list lives in one `ScanRulerReverse` container in the
  document, one undo step an edit, its bodies built on FreeCAD's Part
  kernel. Tools: `reverse_feature_add`, `reverse_feature_update`,
  `reverse_feature_remove`, `reverse_feature_move`,
  `reverse_feature_suppress`, `reverse_feature_rollback`,
  `reverse_feature_clear`, `reverse_feature_list`,
  `reverse_feature_schema`, `reverse_build`, `reverse_build_stop`,
  `reverse_parameter_add`, `reverse_parameter_set`,
  `reverse_parameter_rename`, `reverse_parameter_remove`,
  `reverse_parameter_list`, `reverse_body_names`, `reverse_body_describe`,
  `reverse_body_check`, `reverse_body_clearance`, `reverse_body_set`,
  `reverse_import_step`. The engine builds every feature kind, sheet,
  split, loft, sweep, fit surface, patch network, trim and thicken
  included (a split within its sheets' regions and splitting a sheet
  refuse, not ported yet); the scan's sections and measured planes and
  axes are references. On the Reverse engineer page the keys of the kinds
  the page has turned on run these tools; sketch editing is still coming.
- **More model formats**: glTF/GLB, Collada, VRML 2 and 3DS open as the scan
  or the reference through Agent Link's readers. FBX does not: export it as
  glTF.

Not ported, because FreeCAD or Agent Link already does it: generation,
FEA, CAM, mass, materials, fits and hardware, slicing and printer hand-off,
part review, setups, BumpMesh texturing (`texture_prepare`,
`texture_check`). Flatbed parts: `flat_objects` (parts parted from the background, with area, holes, caliper widths) and `flat_profile` (a knurl's or gear's teeth counted round a centre or along an axis).
Not ported yet: patent kit (TechDraw does most of it),
and the electronics pages (KiCad's own tools and KiCad StepUp cover the
board).

## Troubleshooting

**A key does nothing.**
A key that cannot run yet says why in the status bar. Most keys need a scan: use **ScanRuler ▸ Open Scan…** first.

**The agent does not have the ScanRuler tools.**
- Most clients read the tool list when a chat starts. After an install or an update, **start a new chat**.
- In Agent Link, `session_state` shows an add-on that did not load under `leftOut`, with the error.
  Update it (`agentlink_update` with the Claude extension, or the Addon Manager), then restart FreeCAD.
- The Reverse engineer tools are a deferred group: they are listed only when the session asks for them.
  Ask the agent to turn on the `reverse` group (`tool_groups`).

**The volume error says `unsure`.**
The scan has holes. Closing them with the reference is not ported yet.

**Where are my files?**
Beside the open document. When the document is not saved yet, in `~/ScanRuler` (exports, `scanners.json`, reports).

**The window or FreeCAD is stuck.**
See the troubleshooting of [Agent Link for FreeCAD](https://github.com/jamesK1000011/AgentLink-FreeCAD#troubleshooting) (`job_status`, `dialog_answer`, `app_force_restart`).

## Uninstall

- **Addon Manager**: Tools ▸ Addon manager ▸ ScanRuler for FreeCAD ▸
  Uninstall, then restart FreeCAD.
- **By hand, or installed by the Agent Link extension**: delete the folder
  from FreeCAD's `Mod` folder (`ScanRulerFC` when the extension put it
  there), and restart FreeCAD.
- **Your files** are yours to keep or delete: what the tools write goes
  beside the open document, or to `~/ScanRuler` when it has not been saved
  (exports, `scanners.json`, reports).

## Privacy

ScanRuler for FreeCAD has no telemetry and makes no network connection. Your
scans, projects and reports stay on your computer, where you save them.
Snapshots are taken only when you press the camera key. Library packs
(`pack_write`) are scrubbed of personal details (paths, names, printer
addresses and serials) before they are written. With Agent Link, what the
agent reads goes to the AI provider your MCP client uses, under that
provider's terms.

## Tests

`python -m unittest discover -s tests` with Agent Link
(github.com/jamesK1000011/AgentLink-FreeCAD) and this folder on `PYTHONPATH`.
The tests that need FreeCAD skip without it; the ones that need Agent Link
skip without it, and the rest run alone. CI (`.github/workflows/ci.yml`)
runs them on the newest FreeCAD and on 1.1 and 1.0, with Agent Link checked
out beside it.

## Credits and licence

- **ScanRuler by Stefan Hermann (CNC Kitchen)**,
  https://github.com/CNCKitchen/ScanRuler: the measuring, fitting,
  alignment, deviation, wall thickness, sections, mesh tools, 2D measuring,
  reverse engineering and plugins ported here, and the window's layout,
  panels, key labels, tooltips, colour maps and icons the workbench follows.
  Each ported file names the ScanRuler source it comes from. See
  `NOTICE.md`.
- Fonts: Barlow, Barlow Semi Condensed and B612 Mono, SIL Open Font License 1.1
  (`scanrulerfc/fonts/`).

AGPL-3.0-only (`LICENSE`), as ScanRuler is. The full source of this port is
this repository; a changed copy you give to others, or let others use over a
network, must offer its source under the same licence. Every file's licence
is stated in its SPDX header or in `REUSE.toml`; the licence texts are in
`LICENSES/` (the privacy check under `.github/privacy/` is Agent Link's,
LGPL-2.1-or-later). CNC Kitchen's commercial licences for ScanRuler do not
cover this port. Please report problems here, not to ScanRuler.
