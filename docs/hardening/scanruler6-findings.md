<!-- SPDX-License-Identifier: AGPL-3.0-only -->
# scanruler6 findings: scan_info area, the best fit's transform, a slow save

ScanRuler for FreeCAD: ScanRuler by Stefan Hermann (CNC Kitchen), ported.
Worked from the code, the stand-in document (tests/fakedoc.py) and the
FreeCAD 1.1.3 source. Nothing here ran in FreeCAD.

## 1. scan_info area far too large (9,049,056 mm² on a small block)

**Cause.** Not a unit fault. The area sum itself (scanstate.py, Scan.summary
and face_normals) is right. The scan's points came back from the document
in the wrong order:

- The state keeps the scan's triangles (F, as vertex numbers) and leaves the
  points to the scan's mesh object (docstate.py, _Enc.scan).
- The mesh object was built with `Mesh.Mesh((V.tolist(), F.tolist()))`
  (origin/main docstate.py, _mesh_of). In FreeCAD 1.1 that tuple form takes
  points only as `FreeCAD.Vector` (others are skipped without a word) and
  triangles only as tuples (a list is a TypeError): see FreeCAD
  src/Mod/Mesh/App/MeshPyImp.cpp, MeshPy::addFacets, the tuple branch.
  So it always failed and fell to the loose-triangle form, which numbers the
  points by where they first come up in the triangles.
- On reading the state back (docstate.py, read, scan_points), the old code
  only checked the point count, then put the old F on points in the new
  order. Every triangle then joins three unrelated points: a huge area.

With the stand-in mesh made to act like FreeCAD's, origin/main reads a
10 mm cube (600 mm²) back as 46,191 mm². The fixed code reads 600.

**Change (docstate.py, WIP finished and tested).**
- `_mesh_built` (near line 642): builds with Vector points and tuple
  triangles, `addFacets((points, faces), False)` (manifold check off, so
  no triangles are dropped). Points stay in the scan's order. Says whether
  the mesh holds the points in order (`ordered`).
- `Scan.in_object` (scanstate.py, line 76): the state leaves the points to
  the mesh object only when it is in order. Otherwise it keeps V0 itself.
- `points_in_order` (near line 405): on reading, maps the object's points
  back through its own triangles when the order differs ("mapped"), and
  refuses (scan reported missing) when they cannot be matched. So documents
  saved before this fix also read back right.

**How sure.** Test (tests/test_docstate_order.py: 10 mm cube 600 mm² after
reopen; an old loose-built document still reads 600 and gives a note).
The FreeCAD behaviour is from source reading.

**Check live.**
1. `scan_open { path: <a small block STL> }`, then `scan_info {}`: note
   `scan.area` (expected: the true area, for a 10 mm cube 600).
2. `doc_save`, close, reopen the document, `scan_info {}`: same `area`,
   same `vertices`, same `box`.
3. An old document saved before this fix: reopen, `scan_info {}`: right
   area; the Report View says the points "stand in another order ... read
   back through the triangles". After the next changing call, the state
   keeps the points itself.

## 2. "not kept in the document: state.deviation.align.transform (Rigid)"

**Cause.** docstate.py, _Enc.value: dev_rigid.Rigid was not a known type,
so it was dropped on every write. A reopened document held an alignment
with no motion.

**Change.** _Enc.value (near line 194) writes a Rigid as
`{"__rigid__": {"r": 3x3 list, "t": 3 list}}` (plain JSON numbers, full
precision). decode (near line 338) gives back a `Rigid`. signature (near
line 269) moves when r or t changes, so a changed fit is written.

**How sure.** Test: encode/decode and a write/reopen in the stand-in
document give a Rigid with exactly equal r and t, and no "not kept" note.

**Check live.** `deviation_align` on a scan with a reference; the Report
View shows no "not kept" line. `doc_save`, close, reopen; a `deviation_*`
call that needs the alignment works with no "run deviation_align" refusal.

## 3. doc_save slow after scan_scale

**Cause: not clear. Not fixed beyond item 1.** What the code shows:

- ScanRuler's own state is not written large or twice. Stand-in measure,
  218,700 triangles: state 1.27 MB (the triangles only), first write
  116 ms; after `scan_scale 2` the write is 13 ms and packs 1 array again;
  the points stay in the mesh object (`in_object` true), not in the state.
- No mesh is copied into a ScanRuler property. The state (a
  PropertyFileIncluded zip) holds no points while the mesh is in order.
- What scan_scale did change on origin/main: it rebuilt the mesh through
  the loose-triangle path (660,000 Python tuples for 220,000 triangles,
  and FreeCAD's point merge). That explains a slow scan_scale (4.4 to
  4.9 s live, run 3), not a slow save. The fix in item 1 replaces it.
- With FreeCAD older than the `addFacets(…, False)` form, or if the
  rebuilt mesh is not in order, `in_object` goes false and the state keeps
  V0 too (about 2.6 MB more at 110,000 vertices). That is bigger, but
  written once (packs keep it), so it should not make each save slow.

Guess: the save time is FreeCAD writing the mesh (MeshKernel.bms, every
save) and the thumbnail, or something on the Agent Link side of doc_save
(a checkpoint copy). Not from ScanRuler's state.

**What to measure live (dense scan, about 200,000 triangles).**
1. `scan_open { path }`, any changing call (`element_fit`), then
   `scan_info {}`: note `kept` (bytes, ms of the last state write).
2. `doc_save` twice with no change in between: note each call's time.
3. `scan_scale { factor: 2 }`: note `timing` (ms, object, mesh). Expected
   with this fix: `mesh: "rebuilt"`, `object` well under the old 4 s.
4. `scan_info {}`: `kept.bytes` about the same as in step 1 (no points
   added). If it grew by about 12 bytes x vertices, the rebuilt mesh was
   not in order: report it.
5. `doc_save`: compare with step 2. If it is slow only here, list the
   .FCStd members and sizes (`unzip -l` on the saved file) and compare
   MeshKernel.bms and scanruler-state.zip before and after the scale.
