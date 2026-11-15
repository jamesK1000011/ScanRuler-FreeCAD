# SPDX-License-Identifier: AGPL-3.0-only
# The (i) texts of ScanRuler's 3D Measure panel, word for word, from ScanRuler by
# Stefan Hermann (CNC Kitchen), github.com/CNCKitchen/ScanRuler (the TSX named in
# each entry). Written by tools/gen_infotext.py; do not edit by hand.

INFO = {'The scan': {'source': 'src/ui/Panel.tsx',
              'paragraphs': ['The part as measured — an <b>STL</b>, <b>PLY</b> or <b>OBJ</b> from your '
                             'scanner. Drop it anywhere in the window, or use the button.',
                             'Units are assumed to be millimetres. Nothing is uploaded: the file is read and '
                             'the whole measurement runs in this browser.']},
 'Alignment': {'source': 'src/ui/AlignmentSection.tsx',
               'paragraphs': ['Where X, Y, Z and the zero point sit on the part. Until it is set the scan '
                              'lies in whatever pose the scanner left it in, so heights, offsets and '
                              'anything measured against an axis mean nothing.',
                              '<b>Auto-align</b> reads the pose off the scan itself: the directions most of '
                              'its faces are square to, the axis its round walls run along, and the side it '
                              'stood on — an open scan is open where it sat, and a flat rim it ends in '
                              'counts as the face that is missing. It opens the same three steps filled in, '
                              'previewed on the part — change which side is down or which way X runs, or '
                              'replace a step, before anything is applied. A part with no flat faces and no '
                              'round walls gets its principal axes, which is a guess.',
                              '<b>Align part</b> places it in up to three steps — set a face on a coordinate '
                              'plane, run an edge or a bore along an axis, put the zero point on a corner. '
                              'Each step takes a measured element — the accurate choice, it averages '
                              'thousands of scan points — or points clicked straight on the scan, and the '
                              'viewport previews every choice against the coordinate planes before anything '
                              'is applied.',
                              '<b>Use symmetry</b>, in the Align part box, settles the pose on the part’s '
                              'own mirror plane: the plane is searched for on the scan — or taken from a '
                              'symmetry plane already measured — the axis nearest its normal is turned onto '
                              'it, and the zero point is put on it. The plane is then a coordinate plane of '
                              'the part, which is what a sketch on the middle and a Mirror want. With no '
                              'pose set up yet it starts from Auto-align’s.',
                              '<b>Move / rotate by numbers</b> applies a transform you already know instead. '
                              'Both are baked into the part, and <b>Reset alignment</b> puts it back.',
                              '<b>Scale part</b> makes the scan its true size — for a photogrammetry scan, '
                              'which has none of its own — from a length measured on it and the same length '
                              'taken on the real part.']},
 'Elements': {'source': 'src/ui/Panel.tsx',
              'paragraphs': ['Every measurement here starts with an element — a plane, a cylinder, a sphere, '
                             'a circle, a point or a line. Dimensions are then measured between them, never '
                             'between raw triangles.',
                             'An element is either <b>fitted</b> to the scan, by clicking the feature and '
                             'letting the tool find the surface; <b>picked</b> straight off the mesh, for a '
                             'single point; or <b>constructed</b> from elements you already have — an axis '
                             'through two circles, a midpoint between two points, a plane offset from '
                             'another.',
                             'Which of those a kind offers appears as <i>Created</i> once you choose it.',
                             'The kind stays in hand after <b>Create</b>, ready for the next one, as a '
                             'sketch tool does — <b>Cancel</b> or <b>Esc</b> puts it down; on a box with '
                             'picks in it, <b> Esc</b> first empties the box.',
                             '<b>Section</b> is not an element but a cut: the scan sliced with a plane taken '
                             "across an element's direction, to be measured on the sheet of the 2D Measure "
                             'workspace.']},
 'Which surface is fitted': {'source': 'src/ui/DraftEditor.tsx',
                             'paragraphs': ['<b>Found from a click:</b> click once on the feature and the '
                                            'patch grows outward across the scan on its own, stopping where '
                                            'the surface stops being flat or round enough to belong. Fast, '
                                            'and right most of the time.',
                                            '<b>Marked by hand:</b> take exactly the triangles you want — '
                                            'with a window, a round brush or a lasso, the same three tools '
                                            'the deviation workspace marks a local fine fit with. Use it '
                                            'when a click runs off across a fillet, when noise breaks the '
                                            'feature into unconnected patches, or when only part of a face '
                                            'is worth trusting.',
                                            'Nothing is armed until you pick one of them: while a tool is '
                                            'live it takes both plain drags — left marks, right rubs out — '
                                            'and <b>Navigate</b> or Esc hands them back to the camera. '
                                            'Shift-drag orbits either way.']},
 'Used points': {'source': 'src/ui/DraftEditor.tsx',
                 'paragraphs': ['Every element is a Gaussian best fit — the plane, cylinder or sphere that '
                                'minimises the squared distance to the points taken from the scan.',
                                'This is the outlier cut-off. Points further from that first fit than the '
                                'chosen multiple of the standard deviation are dropped and the fit is '
                                'repeated, so scan noise, a stray edge triangle or a speck of spray cannot '
                                'drag the result. Tighter cut-offs give a cleaner element from fewer points; '
                                '<i>all points</i> keeps everything.',
                                'The setting belongs to this element: changing it re-fits this one from the '
                                'points it was built on, and every other element keeps the cut-off it was '
                                'measured with. Re-open an element to change its own. The last choice is '
                                'what the next new element starts with.']},
 'Sections': {'source': 'src/ui/SectionEditor.tsx',
              'paragraphs': ['A section is the scan cut with a plane. It becomes a <b>source in the 2D '
                             'Measure workspace</b>, listed there beside the flatbed image: the cut’s edges '
                             'lie on the sheet at true size, ready to be snapped to, fitted and measured '
                             'exactly like a scan image’s edges.',
                             'The plane is taken <b>across an element’s direction</b> — a plane’s normal, '
                             'the axis of a cylinder, cone or line, a circle’s normal — or across one of the '
                             'scan’s <b> coordinate axes</b>: while nothing is chosen, the XY, YZ and XZ '
                             'planes are offered through the part’s centre, and clicking one takes it. The '
                             'plane is moved along its direction by the offset. Zero cuts through the '
                             'element’s own centre — for a face that is the face itself, so offset into the '
                             'part to cut through its walls — and for a coordinate plane the offset is the '
                             'plane’s coordinate on that axis.',
                             'The gizmo on the plane <b>slides</b> it by the arrow and <b>tilts</b> it by '
                             'the two rings, each about one of the sheet’s own axes through the point the '
                             'gizmo sits on. A tilted plane is recorded with its tilt off what it was taken '
                             'across; <b>Square</b> turns it back. A <b>click on the scan</b> slides the '
                             'plane, direction and tilt kept, to pass through the point clicked.',
                             'The plane is fixed when the section is created. Re-fitting or deleting the '
                             'element it was cut along leaves the section where it is; a datum alignment '
                             'moves it with the part.',
                             'A <b>shadow</b> is the whole scan projected along the plane’s normal onto it — '
                             'the outline the part casts, its widest extent with every indentation filled, '
                             'where a cut is only what one plane passes through. It is what a '
                             'straight-walled bin, a foam cutout or a pocket for the part is drawn from: on '
                             'the 2D sheet, then out as DXF. The outline is read as lines and arcs, the way '
                             'a sketch is drawn, to the <b>tolerance</b>, and always lies outside the part: '
                             'at least the <b>play</b> and at most the play plus twice the tolerance outside '
                             'its exact silhouette. A positive play is clearance; a negative one, a press '
                             'fit. Where two lines meet turning by less than <b>Round below</b> (30° by '
                             'default) the corner is rounded by an arc tangent to both, so a faceted curve '
                             'comes out smooth; a sharper corner stays sharp, and 0 keeps them all.']},
 'Dimensions': {'source': 'src/ui/DimensionSection.tsx',
                'paragraphs': ['What you actually read off the part: distances, diameters and angles '
                               'measured between the elements you have created.',
                               'Fill a slot from the dropdown, or click the element straight in the viewport '
                               '— the dimension type switches to match what you pick, so a click on two '
                               'circles becomes a centre distance without you choosing it.',
                               'Between two spheres you can also measure the surface gap or the outer span '
                               'instead of centre to centre — a ball-bar length is centre to centre.',
                               '<b>Add dimension</b> leaves the box open for the next one of the same type, '
                               'its slots empty; <b>Cancel</b> or <b>Esc</b> closes it.',
                               'One box is open at a time: while an element kind is in hand, put it down '
                               'first with <b> Cancel</b> or <b>Esc</b>.']},
 'Geometric tolerances': {'source': 'src/ui/ToleranceSection.tsx',
                          'paragraphs': ["What a drawing's feature control frames ask for: how flat, round, "
                                         'cylindrical or spherical a feature is on its own, how parallel, '
                                         'square or angled it lies to a datum, and how well it shares the '
                                         "datum's axis.",
                                         'Each reads the elements you have fitted — a face by its measured '
                                         'surface, a bore or a pin by its axis, a ball by its centre — and '
                                         'is the width of the narrowest zone that still holds the feature, '
                                         'the number to compare against the frame. Datums are elements too: '
                                         'pick the one the drawing names.',
                                         'Type a limit and the reading is judged against it, here, on the '
                                         'pin and in the copied summary.']},
 'Scanner noise': {'source': 'plugins/scanner-profiles/ui/ScannerSection.tsx',
                   'paragraphs': ['How noisy a scan is sets how small a difference can be trusted: nothing '
                                  'finer than about three times it. Wear repair, Calibrate from a scan and '
                                  "Thread go by the larger of the scanner's usual noise and this scan's.",
                                  "<b>Measure noise</b> reads this scan's with the scan check — best on a "
                                  "flat, matte part. <b>Save as scanner</b> keeps the reading as a scanner's "
                                  'usual noise, for every project.',
                                  'Scanners are kept in this browser; the one named is kept with the '
                                  "project. 2D Measure's scanner profiles are a flatbed's scale, not this."]},
 'Naming a scanned thread': {'source': 'plugins/thread-match/ui/ThreadSection.tsx',
                             'paragraphs': ['Fit a <b>cylinder</b> in the threaded bore or on the boss, then '
                                            '<b>Identify</b>: the pitch, the diameter, the flank angle and '
                                            'the taper are read off the scan and matched against ISO metric, '
                                            'UNC, UNF, UNEF, NPT, G and R pipe threads, trapezoidal, ACME '
                                            'and the 3D-printing 45° form.',
                                            'When two sizes fit the scan equally well, it says so and names '
                                            'the one measurement — over ten crests, across the crests, or '
                                            'with a thread gauge — that tells them apart, with what each '
                                            'would read.',
                                            'A scan reads diameters a little small; a match within tolerance '
                                            'is normal.']},
 'What the STEP file contains': {'source': 'src/ui/Panel.tsx',
                                 'paragraphs': ['<b>Solids & faces:</b> each element as geometry CAD can '
                                                'build on — a plane as a bounded planar face with real '
                                                'edges, a cylinder and a sphere as closed solid bodies, each '
                                                'its own named body in the tree. Sketch on them, offset '
                                                'them, cut with them.',
                                                '<b>Construction surfaces:</b> the same geometry as trimmed '
                                                'analytic surfaces and curves in one set, with no topology — '
                                                'the form metrology packages hand measured datums over in. '
                                                'Unmistakably reference geometry rather than a part, and the '
                                                'safer choice for an importer that chokes on bodies.',
                                                'Points and lines are points and lines either way. Whatever '
                                                'an element has been extended to is what gets written, and a '
                                                'sphere, cylinder or circle given an assumed Ø when it was '
                                                'created is written at that Ø — everything else as measured.',
                                                "What was measured on a section's sheet in 2D Measure — its "
                                                'points, lines, circles and arcs — comes too, as curves '
                                                'lying in the cutting plane, in a group named after the '
                                                'section. Cut a section through a bore, fit its circle on '
                                                'the sheet, and CAD gets a circle in space to sketch on.']},
 'What the point cloud contains': {'source': 'src/ui/Panel.tsx',
                                   'paragraphs': ['Every vertex of the scan with its normal, where the part '
                                                  'now stands — any alignment or move you applied comes with '
                                                  'it — for the reverse-engineering tools that model over '
                                                  'points rather than triangles. Millimetres, like '
                                                  'everything here.',
                                                  '<b>PLY:</b> binary and compact, read by Geomagic, '
                                                  'CloudCompare, MeshLab, ReCap and most others. Points '
                                                  'only, no faces — a reader that wants a cloud gets a '
                                                  'cloud.',
                                                  '<b>XYZ text:</b> one point per line, x y z nx ny nz — the '
                                                  'universal fallback, the same file ASC readers take. '
                                                  'Autodesk ReCap turns either into an RCP for AutoCAD and '
                                                  'Inventor.']}}
