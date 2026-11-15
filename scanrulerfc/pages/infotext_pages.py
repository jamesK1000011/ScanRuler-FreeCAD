# SPDX-License-Identifier: AGPL-3.0-only
# The (i) texts of ScanRuler's Surface Deviation, Wall Thickness, 2D Measure, Mesh
# Tools and Reverse engineer panels, word for word, read in millimetres, from
# ScanRuler by Stefan Hermann (CNC Kitchen), github.com/CNCKitchen/ScanRuler (the
# TSX named in each entry). Written by tools/gen_infotext_pages.py; do not edit by hand.

INFO = {'deviation': {'What the deviation is measured from': {'source': 'src/ui/DeviationPanel.tsx',
                                                       'paragraphs': ['Both choices paint the same map onto '
                                                                      'the scan — a signed distance, warm '
                                                                      'where there is too much material and '
                                                                      'cool where there is too little. They '
                                                                      'differ in what the zero of that scale '
                                                                      'is.',
                                                                      'A <b>reference model</b> is the whole '
                                                                      'nominal part. It answers "is this the '
                                                                      'shape it was drawn as", and needs the '
                                                                      'CAD file loaded and best-fitted onto '
                                                                      'the scan first.',
                                                                      'A <b>fitted element</b> is one plane, '
                                                                      'cylinder or sphere you measured on '
                                                                      'this scan in the 3D Measure '
                                                                      'workspace. It answers "is this face '
                                                                      'flat, is this bore round, does this '
                                                                      'surface sit where the datum says" — '
                                                                      'and since it was measured on the scan '
                                                                      "it is already in the scan's frame, so "
                                                                      'there is no reference file and no '
                                                                      'alignment.']},
               'Best fit': {'source': 'src/ui/DeviationPanel.tsx',
                            'paragraphs': ['Brings the scan onto the reference before anything is measured. '
                                           'Rotation and translation only — no scale, so a scanner scale '
                                           'error stays visible in the map instead of being quietly absorbed '
                                           'by the alignment.',
                                           '<b>Align automatically</b> searches for the pose on its own and '
                                           'is what you want almost always. <b>Align by picking points</b> '
                                           'is the fallback for a part it gets wrong — usually one symmetric '
                                           'enough to match the wrong way round.']},
               'Local fine fit': {'source': 'src/ui/DeviationPanel.tsx',
                                  'paragraphs': ['An optional second step, once the global fit is in — most '
                                                 'parts do not need it.',
                                                 'Scan spray, print supports, risers, fixturing and any '
                                                 'geometry the reference does not have all pull on the '
                                                 'whole-scan fit, and no number of passes will shake them '
                                                 'loose. Mark the surfaces that really are the part and the '
                                                 'fit is computed on those alone.',
                                                 'Only the alignment narrows: the map that follows is still '
                                                 'measured everywhere on the scan.']},
               'Volume error': {'source': 'src/ui/VolumeSection.tsx',
                                'paragraphs': ['The scan and the reference compared as solids rather than '
                                               'surfaces: on a grid of small cells, each cell inside one and '
                                               'not the other is an error, and touching cells make a region. '
                                               '<b>Excess</b> is material the reference has and the part has '
                                               'not, <b>missing</b> the other way round — a boss not '
                                               'modelled, a pocket not cut, wherever it is, behind a wall or '
                                               'inside a cavity too.',
                                               'Where the scan has a hole, the reference stands in for it. '
                                               'What the scan still does not say is <b>unsure</b>, never '
                                               "called an error. Within the tolerance of the scan's surface "
                                               "a difference is the scan's noise and not counted, and "
                                               'nothing thinner than about two cells is seen: the surface '
                                               'map stays the tool for fine offsets.']},
               'Colour scale': {'source': 'src/ui/DeviationPanel.tsx',
                                'paragraphs': ['How the measured deviation is painted onto the scan. Zero '
                                               'always sits at the centre of the scale, on green; anything '
                                               'past either end is drawn in a dark cap so it cannot be '
                                               'mistaken for the limit itself.',
                                               '<b>Positive is outside the reference</b> — material the '
                                               'reference does not have, painted warm. <b>Negative is inside '
                                               'it</b> — material the reference has and the scan does not, '
                                               'painted cool. Both ends of the scale say so beside the map.',
                                               'The slider is logarithmic, so the same control serves a 0.02 '
                                               'mm print and a 5 mm warp. <b>Bands</b> replaces the '
                                               'continuous ramp with discrete steps, which is easier to read '
                                               'off a screenshot or a printed report.',
                                               'Showing and hiding what is on the stage changes nothing that '
                                               'was measured — it only changes what you are looking at.']},
               'Animated deformation': {'source': 'src/ui/DeviationPanel.tsx',
                                        'paragraphs': ['Plays the map as motion, the way an FE package '
                                                       'animates a deformed shape: the part moves from the '
                                                       'shape it should have to the shape it was measured '
                                                       'at, with the deviation multiplied by the '
                                                       '<b>scale</b>, and back again, on a loop.',
                                                       'Each point moves along the line its deviation was '
                                                       'measured on — straight off the reference surface — '
                                                       'so a warp, a twist or a wall leaning in shows as the '
                                                       'part bending that way.',
                                                       'What is exaggerated is how the part as a whole has '
                                                       'deformed. The motion is smoothed over about a '
                                                       'hundredth of the part’s size, so the scanner’s noise '
                                                       'and the edges of holes stay at their true size and '
                                                       'ride along instead of being blown up into fur. A '
                                                       'reading past the end of the <b>colour scale</b> '
                                                       'moves only as far as the end, and points with no '
                                                       'reading, the grey ones, stay where they are — widen '
                                                       'the range to let more of the part move.',
                                                       'The scale starts where the end of the colour scale '
                                                       'moves by about a twentieth of the part, and follows '
                                                       'the range until you set one. At <b>1×</b> the part '
                                                       'moves exactly as far as it is out.',
                                                       'Only the picture moves. The colours, the figures, '
                                                       'the hover reading and the pins are the part as '
                                                       'measured, and so is an exported scan.']},
               'Surface must face the element': {'source': 'src/ui/DeviationPanel.tsx',
                                                 'paragraphs': ['An element is a surface with a side to it, '
                                                                'and only the scan surface lying on that '
                                                                'side is the surface being measured. A plane '
                                                                'fitted on the top of a 10 mm plate reaches '
                                                                'the underside of it too — and would report '
                                                                'it as ten millimetres of missing material.',
                                                                'With this on, a scan point whose own normal '
                                                                "points away from the element's is left out, "
                                                                'so the far side of a wall and the back of a '
                                                                'rib stay grey.']},
               'Reference must face the same way': {'source': 'src/ui/DeviationPanel.tsx',
                                                    'paragraphs': ['The nearest reference surface is not '
                                                                   'always the one a point came off. Across '
                                                                   'a thin wall, a point sunk more than half '
                                                                   "the wall's thickness is nearer the far "
                                                                   'side of the wall than its own — and '
                                                                   'reads too small, or with the wrong sign '
                                                                   'once it is through.',
                                                                   'With this on, reference surface facing '
                                                                   'away from the scan at that point is '
                                                                   'stepped over, and the point is measured '
                                                                   'against the nearest surface that faces '
                                                                   'its way. A point with no such surface '
                                                                   'anywhere near is left grey.',
                                                                   'Everywhere else the reading is the plain '
                                                                   'closest point, as before. Which way the '
                                                                   'scan faces is read off its own normals. '
                                                                   'Changing this measures the map again.']},
               'Hide pins behind the part': {'source': 'src/ui/ProbeList.tsx',
                                             'paragraphs': ['With this on, a pin whose spot is on the far '
                                                            'side of the part, or behind a feature of it, is '
                                                            'put away until the part turns to show it — so a '
                                                            'part carrying many pins shows only the numbers '
                                                            'of the face you are looking at.',
                                                            'Off, every pin shows through the part, wherever '
                                                            'its spot is.']},
               'Scan and reference': {'source': 'src/ui/DeviationPanel.tsx',
                                      'paragraphs': ['The part as scanned, and the nominal CAD part it '
                                                     'should match. Drop either one anywhere in the window. '
                                                     'Nothing is uploaded.',
                                                     'The scan is an <b>STL</b>, <b>PLY</b> or <b>OBJ</b> in '
                                                     'millimetres. The reference takes those too, and also a '
                                                     '<b>STEP</b> file straight from CAD — its exact '
                                                     'surfaces are tessellated here, finely enough that the '
                                                     'conversion sits well below anything the scan can '
                                                     'resolve.']}},
 'thickness': {'The scan': {'source': 'src/ui/ThicknessPanel.tsx',
                            'paragraphs': ['The part as scanned — an <b>STL</b>, <b>PLY</b> or <b>OBJ</b> in '
                                           'millimetres. Nothing else is needed here: wall thickness is a '
                                           'property of the part itself, so there is no reference model and '
                                           'no alignment step.',
                                           'Drop it anywhere in the window. Nothing is uploaded.']},
               'How thickness is measured': {'source': 'src/ui/ThicknessPanel.tsx',
                                             'paragraphs': ['<b>Ray along the normal</b> fires a ray '
                                                            'straight into the material at each point and '
                                                            'takes how far it travels before it comes out '
                                                            'the far side. Simple, and it is what most tools '
                                                            'mean by wall thickness.',
                                                            '<b>Sphere across the wall</b> places a sphere '
                                                            'halfway along that ray and grows it until it '
                                                            'touches. It can never read longer than the ray '
                                                            'and usually reads shorter, because it is not '
                                                            "tied to the ray's direction: it finds a wedge "
                                                            'square across, and the width of a block rather '
                                                            'than the diagonal its corner points down.',
                                                            'Neither is wrong — the ray answers “how far '
                                                            'through here”, the sphere answers “how much '
                                                            'material is actually there”.']},
               'Rays': {'source': 'src/ui/ThicknessPanel.tsx',
                        'paragraphs': ['A single ray along the normal reads the wall square-on, which '
                                       'over-reads wherever the surface is not parallel to the one behind it '
                                       '— a chamfer, a tapered rib, the inside of a corner.',
                                       'Spreading extra rays through a cone around the normal and keeping '
                                       'the shortest finds the true way across instead. More rays cost '
                                       'measurement time.']},
               'Far surface must face back': {'source': 'src/ui/ThicknessPanel.tsx',
                                              'paragraphs': ['A surface nearly edge-on to the ray is a rib '
                                                             'the ray is running alongside, or the rim of an '
                                                             'open scan — not the far side of a wall.',
                                                             'With this on, such a hit is stepped over and '
                                                             'the search carries on behind it, so the wall '
                                                             'reported is the one a caliper would find.']},
               'Colour scale': {'source': 'src/ui/ThicknessPanel.tsx',
                                'paragraphs': ['Red is thin, blue is thick. Both ends default to the spread '
                                               'of this part, so the first map you see uses the full range '
                                               'of colour on the walls it actually found.',
                                               'Anything past either end is drawn in a dark cap, so a wall '
                                               'beyond the scale cannot be mistaken for one sitting exactly '
                                               'on it.',
                                               'Moving the ends only re-paints — nothing here is '
                                               're-measured, and nothing above changes.']},
               'Hide pins behind the part': {'source': 'src/ui/ProbeList.tsx',
                                             'paragraphs': ['With this on, a pin whose spot is on the far '
                                                            'side of the part, or behind a feature of it, is '
                                                            'put away until the part turns to show it — so a '
                                                            'part carrying many pins shows only the numbers '
                                                            'of the face you are looking at.',
                                                            'Off, every pin shows through the part, wherever '
                                                            'its spot is.']}},
 'flat': {'What is measured': {'source': 'src/ui/FlatPanel.tsx',
                               'paragraphs': ['A flatbed scan of the part — a <b>PNG</b> or <b>JPEG</b> '
                                              'straight from the scanner. Scan at the highest optical '
                                              'resolution you have; the pixels are the measurement.',
                                              'Drop it anywhere in the window. Nothing is uploaded.',
                                              'Or a <b>section</b>: the 3D scan cut with a plane in the 3D '
                                              'Measure workspace. Its edges lie on the sheet at true size '
                                              'already, so there is nothing to calibrate, and they are '
                                              "snapped to, fitted and measured exactly like an image's. One "
                                              'source is on the sheet at a time; each keeps its own '
                                              'elements, dimensions and alignment, and finds them again when '
                                              'it comes back.']},
          'Calibration': {'source': 'src/ui/FlatPanel.tsx',
                          'paragraphs': ['Every length this workspace reports is pixels divided by this '
                                         "scale. The file's own dpi is only <b>nominal</b> — scanner "
                                         'transports are off by real fractions of a percent — so measure the '
                                         'scale off something true: scan a gauge block, calliper-measured '
                                         'part or gauge pin along with the part.',
                                         '<b>Known distance</b> takes two picks across the reference and its '
                                         'true length. <b> Known diameter</b> takes three or more picks '
                                         "around a circle's edge and its true diameter.",
                                         'Scanners err differently along the two axes. Calibrating X and Y '
                                         'separately needs a reference laid along each axis in turn.']},
          'Elements': {'source': 'src/ui/FlatPanel.tsx',
                       'paragraphs': ['Every measurement here starts with an element — a point, a line, a '
                                      'circle, an arc or a spline. Dimensions are then measured between '
                                      'them, never between raw pixels.',
                                      'An element is <b>picked</b>, by clicking the points it runs through — '
                                      'with <b>Snap to edge</b> on, every click and drag lands on the '
                                      'nearest detected edge at subpixel — or on the center of a circle, an '
                                      'arc or a point when one is within reach — and <b>Alt</b> inverts that '
                                      'for one pick; any pin can be dragged afterwards; <b>fitted to an '
                                      'edge</b> from one click on it, the way a fit from a click works on '
                                      'the scan — the line or circle grows along the detected edge from the '
                                      'point you clicked and stops where the edge bends away, at a corner or '
                                      'into a fillet, so a click on one side of a part takes that side and a '
                                      "click on a hole's rim takes the hole; <b>fitted to an edge "
                                      'region</b>, by clicking a detected edge to take all of it or dragging '
                                      'a box over it and letting every edge point inside feed the fit; or '
                                      '<b>constructed</b> from elements you already have — a midpoint, a '
                                      "circle's center, the intersection of two lines, the circle through "
                                      "the centers of a bolt pattern. A construction's sources are clicked "
                                      'on the sheet or chosen in the box.',
                                      'Which of those a kind offers appears as <i>Created</i> once you '
                                      'choose it.',
                                      'The kind stays in hand after <b>Create</b>, ready for the next one, '
                                      'as a sketch tool does — <b>Cancel</b> or <b>Esc</b> puts it down; on '
                                      'a box with picks in it, <b> Esc</b> first empties the box.',
                                      'A <b>spline</b> is the free curve a CAD sketch draws through fit '
                                      'points — a cam profile, an outline no arc fits. Click its points in '
                                      'order along the edge (they snap like any pick), click on the curve to '
                                      'insert a point there, and drag the <b> tangent handle</b> at any '
                                      'point to bend the curve through it the way you would in CAD; click a '
                                      'handle to let it go automatic again. Click the first point again to '
                                      'close the curve on itself, and it leaves the tool as a real spline in '
                                      'the SVG and the STEP file.',
                                      '<b>Count</b> is a tally rather than a fit: click the features one '
                                      'after another — the teeth of a gear, the holes in a flange — and each '
                                      'click wears the next number, pinned where you clicked.',
                                      '<b>Text</b> pins a free note to the sheet — a remark, a part number — '
                                      'wherever you click; drag it to move it, click it to change what it '
                                      'says.',
                                      '<b>Enter</b> or a <b>middle click</b> creates whatever is pending; '
                                      '<b>Esc</b> discards it.']},
          'Dimensions': {'source': 'src/ui/FlatDimensionSection.tsx',
                         'paragraphs': ['Measurements between elements: point–point and point–line '
                                        'distances, the width between two near-parallel lines, the angle '
                                        'between two lines. Values follow the elements — re-fit or '
                                        'recalibrate and every dimension updates.',
                                        'Distances and angles between elements never change under an '
                                        'alignment.',
                                        'Fill a slot from its dropdown, or click the element on the sheet — '
                                        'a circle or an arc by its edge or by the cross at its center, which '
                                        'is the point it measures from.',
                                        '<b>Add dimension</b> leaves the box open for the next one of the '
                                        'same type, its slots empty; <b>Cancel</b> or <b>Esc</b> closes '
                                        'it.']},
          'Alignment': {'source': 'src/ui/FlatPanel.tsx',
                        'paragraphs': ['Aligns the sheet to the part instead of to the scanner glass: the '
                                       'first pick is the <b>origin</b>, the second sets <b>+X</b>. The '
                                       'sheet turns so that +X runs to the right of the screen, and '
                                       'coordinates and line angles read from the origin along it from then '
                                       'on. Distances and angles between elements never change under an '
                                       'alignment.',
                                       'Both picks snap to detected edges like any other pick — put the '
                                       'origin on a corner or a circle center, run X along a reference edge. '
                                       'The grid shows where the axes lie.',
                                       '<b>Rotate 90°</b> turns the sheet on the stage a quarter turn at a '
                                       'time on top of that — the image or the section as it is looked at, '
                                       'not the frame. Coordinates, the grid and every measurement stay '
                                       'where they are on the part.',
                                       '<b>Mirror</b> flips the sheet on the stage left-to-right or '
                                       'top-to-bottom, as it is shown. A flatbed scan is the part seen '
                                       'through the glass; mirrored, it is the part seen from above, the way '
                                       'a drawing shows it. Nothing measured moves — distances, diameters '
                                       'and angles between elements are what they were — and an alignment '
                                       'reads right-handed as shown, +X to the right and +Y up the screen, '
                                       'so coordinates and line angles compare with a drawing. The drawing '
                                       'exports come out mirrored the same way.']},
          'Section edges': {'source': 'src/ui/FlatPanel.tsx',
                            'paragraphs': ['The polylines the cutting plane produced through the scan, drawn '
                                           'in teal over the sheet. They are what picks snap to and what an '
                                           'edge-region fit consumes — no detector runs, the cut is the '
                                           'edge.',
                                           "The chains are as fine as the scan's triangles: coarse on a "
                                           'decimated mesh, subpixel-dense on a fine one. Chains shorter '
                                           'than a millimetre are dropped.']},
          'Edge detection': {'source': 'src/ui/FlatPanel.tsx',
                             'paragraphs': ['The image is swept once for edges — where brightness turns over '
                                            '— and each edge comes out as a chain of subpixel points, drawn '
                                            'in teal over the scan. Fits will consume these chains; the '
                                            'overlay shows what they would have to work with.',
                                            'Sensitivity decides how faint an edge still counts. Push it up '
                                            'if a real edge is missing, down if noise and paper texture come '
                                            'up as edges.']}},
 'mesh': {'The scan': {'source': 'plugins/mesh-tools/ui/MeshPanel.tsx',
                       'paragraphs': ['The part as scanned — an <b>STL</b>, <b>PLY</b> or <b>OBJ</b> in '
                                      'millimetres. Align it first in 3D Measure if it should land in CAD on '
                                      'its datums: a reduced mesh is made from the scan where it stands, and '
                                      'exported there.',
                                      '<b>Remove islands</b>, <b>Delete marked</b>, <b>Flip normals</b>, '
                                      '<b>Cut</b>, <b>Mirror</b>, <b>Fill holes</b>, <b>Smooth</b>, '
                                      '<b>Densify</b>, <b>Shrink/expand</b>, <b>Boolean</b> and '
                                      '<b>Shell/hollow</b> edit a copy of the scan, shown here in its place; '
                                      'every other workspace goes on measuring the scan as it was until '
                                      '<b>Use for analysis</b> takes the copy into use. <b>Reduce mesh</b> '
                                      'makes a light mesh beside it — of the copy, when there is one — which '
                                      '<b>Apply</b> makes the edited copy, <b>Wrap</b> a closed skin round '
                                      'it the same way, and <b>Trim to scan</b> a piece cut to fit its '
                                      'break.']},
          'Mesh tools': {'source': 'plugins/mesh-tools/ui/MeshPanel.tsx',
                         'paragraphs': ['Tools that work on the mesh itself rather than measure it. The '
                                        'edits are made on a copy of the scan — each one step of the undo '
                                        'history, kept in a saved project — and reach the other workspaces '
                                        'only when the copy is taken into use.']},
          'Reducing a scan for CAD': {'source': 'plugins/mesh-tools/ui/tools/ReduceTool.tsx',
                                      'paragraphs': ['A scan is millions of triangles, and CAD chokes on it. '
                                                     'This makes a light mesh to model over instead: edges '
                                                     'collapsed wherever the surface lets them go, so a flat '
                                                     'face ends as a few large triangles and a fillet keeps '
                                                     'the ones it needs. The scan itself stays as it is.',
                                                     'The result is a preview. <b>Reduce again</b> starts '
                                                     'over from the mesh as it stands, not from the result, '
                                                     'so a result that came out too coarse costs nothing. '
                                                     '<b>Apply</b> makes it the edited copy, one step of the '
                                                     'undo history, from where <b>Use for analysis</b> takes '
                                                     'it into every workspace.',
                                                     'The <b>tolerance</b> decides how far it may stray. The '
                                                     'result is not trusted but measured, both ways — every '
                                                     'scan point to the reduced mesh, and the reduced mesh '
                                                     'back to the scan — and wherever it strays past the '
                                                     'tolerance the scan is pinned there and reduced again, '
                                                     'until 99.9 % of each side lies within it.',
                                                     '<b>Accuracy</b> in the view bar colours the scan by '
                                                     'how far the reduced mesh strays from it: green where '
                                                     'it lies on it, a dark cap past the tolerance.']},
          'Removing islands': {'source': 'plugins/mesh-tools/ui/tools/IslandsTool.tsx',
                               'paragraphs': ['Scans come with islands: stray patches of the turntable, a '
                                              'fleck of dust, spray floating off the part — each a piece of '
                                              'surface joined to nothing else. They throw every reading of '
                                              "the whole part: the automatic alignment's directions, a best "
                                              'fit that reaches for them, a reduced mesh that carries them '
                                              'along.',
                                              'Every piece smaller across than the size below is an island, '
                                              'and is marked on the part: tinted orange and ringed, the ring '
                                              'showing faintly through the part for one behind it or inside '
                                              'it. Nothing is deleted until you have looked and said so. A '
                                              'size rather than "keep the largest", because a scan is often '
                                              'several real pieces — the two balls of a ball bar and the rod '
                                              'between them all stay.',
                                              'They are deleted from the edited copy; the other workspaces '
                                              'measure what is left once the copy is taken into use. '
                                              '<b>Ctrl+Z</b> puts the islands back.']},
          'Deleting marked surface': {'source': 'plugins/mesh-tools/ui/tools/DeleteTool.tsx',
                                      'paragraphs': ['What the scanner saw that is not the part: the clamp '
                                                     'that held it, the fixture it sat in, a patch of the '
                                                     'table, a finger. Mark it on the part with a '
                                                     '<b>window</b>, a <b>brush</b> or a <b>lasso</b> — '
                                                     'marked surface turns orange — and delete it. A '
                                                     'triangle goes when all three of its corners are '
                                                     'marked, exactly the triangles shown in orange.',
                                                     'It is deleted from the edited copy. The hole it leaves '
                                                     'stays open — close it with <b>Fill holes</b> if the '
                                                     'part should be closed there. <b>Ctrl+Z</b> puts the '
                                                     'surface back.']},
          'Flipping normals': {'source': 'plugins/mesh-tools/ui/tools/FlipTool.tsx',
                               'paragraphs': ['Which side of a surface is its outside is set by the order of '
                                              "each triangle's corners. A part exported inside-out faces in "
                                              'everywhere, and a scan stitched from patches can have some of '
                                              'them facing in — and the thickness map, the alignment, '
                                              '<b>Shrink/expand</b>, <b>Shell/hollow</b> and <b>Boolean</b> '
                                              'all go by which way the surface faces.',
                                              'A part that plainly encloses its volume inside-out is turned '
                                              'the right way out when it is opened; an open scan, a sheet, '
                                              'or one with patches facing both ways is left as it was wound. '
                                              "<b>Backfaces</b>, in the menu over the view bar's Scan key, "
                                              'colours the inside of every triangle, so surface facing the '
                                              'wrong way shows.',
                                              '<b>Flip all</b> turns every triangle over. <b>Flip marked</b> '
                                              'turns over the surface you mark with a <b>window</b>, a '
                                              '<b>brush</b> or a <b>lasso</b> — a triangle when all three of '
                                              'its corners are marked, exactly the triangles shown in amber. '
                                              'Nothing moves. It flips the edited copy; <b>Ctrl+Z</b> turns '
                                              'it back.']},
          'Cutting the scan': {'source': 'plugins/mesh-tools/ui/tools/CutTool.tsx',
                               'paragraphs': ['The scan cut with a plane and one side of it taken off: the '
                                              'turntable or the table the part stood on, a flat bottom for a '
                                              'part that is to be printed, one half of a part to model on '
                                              'its own. While the tool is in hand the part is shown cut '
                                              'where the plane is, the side that goes already taken away and '
                                              'the cut closed as it will be closed.',
                                              "The plane is taken across one of the scan's <b>coordinate "
                                              "planes</b> — after a datum alignment, the datum's, so "
                                              '<b>Z</b> 0 is the face the part was set on and <b>Z</b> 0.5 '
                                              'half a unit above it — or across an <b>element</b> with a '
                                              "direction: a plane's normal, the axis of a cylinder, cone or "
                                              'line. It starts through the middle of the part; type where it '
                                              'should be.',
                                              '<b>Close flat</b> fills the cut face wherever the plane goes '
                                              'all the way round the part, so a closed part stays closed. '
                                              'Where the scan is open across the plane the rim stays open, '
                                              'and the result says so. The cut is made on the edited copy; '
                                              '<b>Ctrl+Z</b> puts it back.']},
          'Close flat': {'source': 'plugins/mesh-tools/ui/tools/CutTool.tsx',
                         'paragraphs': ['Close the part with a flat face where the plane goes all the way '
                                        'round it — a ring where it crosses a bore, a disc where it crosses '
                                        'a solid. Off, the cut is left open, as a scan of a surface would '
                                        'be.']},
          'Mirroring the scan': {'source': 'plugins/mesh-tools/ui/tools/MirrorTool.tsx',
                                 'paragraphs': ['The scan reflected across a plane. <b>Whole part</b> '
                                                'reflects all of it: the left-hand version of a right-hand '
                                                'bracket, a part scanned from its mirror image. The mirror '
                                                'image is drawn see-through over the part while the tool is '
                                                'in hand.',
                                                '<b>Symmetric</b> keeps one side of the part and reflects it '
                                                'onto the other, which it replaces: a symmetric part scanned '
                                                'well on one side only, or damaged on one side. The two '
                                                'halves join along the plane, so a closed part stays closed. '
                                                'A face lying in the plane, such as the cap of a part '
                                                'already cut there, is dropped. The side that is replaced is '
                                                'cut away on screen and the mirror image drawn in its place.',
                                                'The plane is taken as <b>Cut</b> takes it: across one of '
                                                "the scan's <b>coordinate planes</b>, or across an "
                                                '<b>element</b> with a direction. It starts through the '
                                                'middle of the part; type where it should be. The mirror is '
                                                'made on the edited copy; <b>Ctrl+Z</b> puts it back.']},
          'Filling holes': {'source': 'plugins/mesh-tools/ui/tools/HolesTool.tsx',
                            'paragraphs': ['A scanner leaves holes where it could not see: the bottom of a '
                                           'blind bore, the inside of a sharp corner, a shiny spot, the pin '
                                           'the part stood on. Every rim smaller across than the size below '
                                           'is a hole, marked on the part in orange and ringed; larger rims '
                                           "— the scan's own open border, a hole too big to guess across — "
                                           'are drawn faint and left open.',
                                           'Each hole is closed with the patch across it that bends least, '
                                           'given points as dense as the scan around it, and smoothed: '
                                           "<b>Curved</b> carries the surface's curvature across the hole, "
                                           'so a patch on a ball bulges with the ball; <b>Flat</b> lays the '
                                           'tightest patch across the rim, flat wherever the rim is. The '
                                           "scan's own points stay where they are.",
                                           'A filled patch is a guess at what the scanner did not see — the '
                                           'deviation and thickness maps read it like any other surface. '
                                           '<b>Ctrl+Z</b> opens the holes again.']},
          'Smoothing the scan': {'source': 'plugins/mesh-tools/ui/tools/SmoothTool.tsx',
                                 'paragraphs': ["A scanner's scatter is bumps across the surface: it makes a "
                                                'flat face read as orange peel, a reduction keep triangles '
                                                'for it, a thickness map speckle. Smoothing moves every '
                                                'point onto a surface fitted to the scan around it — a '
                                                'gently curved patch <b>Smooth bumps up to</b> across. A '
                                                'bump smaller than the patch is averaged away; a face, a '
                                                'bore or a fillet larger than it is what the patch fits, and '
                                                'stays where it was, so the part is not shrunk. Points move '
                                                "along the surface's normal only.",
                                                'No point ever moves further than <b>Move at most</b> from '
                                                'where the scanner put it. It starts well past the scatter '
                                                'of a good scan, to hold back only a fit that has run off; '
                                                "set it lower to be sure of what the part's shape can lose.",
                                                '<b>Keep sharp edges</b> fits each side of an edge where the '
                                                'surface turns by more than 30° on its own, so the faces are '
                                                'smoothed right up to the edge and the edge itself is left '
                                                'as scanned: a machined edge is detail, not noise. Smoothing '
                                                'changes the edited copy; <b>Ctrl+Z</b> puts it back.',
                                                '<b>Marked region</b> smooths only the surface you mark with '
                                                'a window, the brush or a lasso — a face that came out '
                                                'rough, leaving a textured one as it is. Each point moves by '
                                                'less the nearer it is to the edge of the region, nothing at '
                                                'the edge itself, so the smoothed patch runs into the scan '
                                                'around it without a step.']},
          'Densifying': {'source': 'plugins/mesh-tools/ui/tools/DensifyTool.tsx',
                         'paragraphs': ['An STL exported from CAD is cut into as few triangles as hold its '
                                        'shape: a flat face is a fan of long, thin triangles from its edges, '
                                        'with no point inside it. A fit, a segmentation or a section looking '
                                        'for points on that face finds none — the noise the checks read on '
                                        'it is the bend between facets.',
                                        '<b>Densify</b> cuts every edge longer than the length below at its '
                                        'middle, again and again, until none is. Each new point lies on the '
                                        'facet it was cut from, so the surface stays exactly where it was, '
                                        'and the mesh stays as closed as it was. A scan needs none of this: '
                                        'its points are dense already.',
                                        'Read radii afterwards off the rim points, which lie on the circle '
                                        "CAD drew: a facet's middle lies inside it by the sagitta. "
                                        '<b>Ctrl+Z</b> takes the step back.']},
          'Shrinking or expanding the surface': {'source': 'plugins/mesh-tools/ui/tools/OffsetTool.tsx',
                                                 'paragraphs': ['Every point of the surface moved along its '
                                                                'normal by the same distance: out to '
                                                                '<b>expand</b>, in to <b>shrink</b>. Not a '
                                                                'scale — a 20 mm ball expanded by 0.5 mm is '
                                                                '21 mm across, and a bore in the part comes '
                                                                'out 1 mm narrower, where scaling would '
                                                                'widen it. For the thickness a scanning '
                                                                'spray added, a clearance on a mating part, '
                                                                'a print that came out a little fat.',
                                                                'Each point moves so that every face around '
                                                                'it ends the distance from where it was — '
                                                                'even thickness, as a CAD offset has it. On '
                                                                'a sharp edge the point moves further, '
                                                                'square to neither face, so both faces end '
                                                                'the distance out and the edge stays sharp. '
                                                                'Where the surface would fold over itself — '
                                                                'a dent shrunk past its depth, a spike of '
                                                                'scatter — the points are eased until it '
                                                                'does not.',
                                                                '<b>Marked region</b> moves only the surface '
                                                                'you mark with a window, the brush or a '
                                                                'lasso, as a step — like a face pushed. '
                                                                'Where the face beside it runs along the '
                                                                'move — marked up to a machined edge — that '
                                                                'face is stretched or shortened with it and '
                                                                'the edge stays sharp; elsewhere a wall '
                                                                'joins the step to the surface around it. '
                                                                'The edit is made on the edited copy; '
                                                                '<b>Ctrl+Z</b> puts it back.']},
          'A boolean with a solid': {'source': 'plugins/mesh-tools/ui/tools/BooleanTool.tsx',
                                     'paragraphs': ['The mesh and a solid body made one: the solid '
                                                    '<b>subtracted</b> from the mesh, <b>added</b> to it, or '
                                                    'the two cut down to what they share (<b>intersect</b>). '
                                                    'Every solid on offer is drawn on the part while the '
                                                    'tool is in hand, and faintly through it, so its whole '
                                                    'length is in view; nothing is in hand as the tool opens '
                                                    '— click each one to use, or tick it in the list '
                                                    '(<b>Select all</b> takes every one), and click it again '
                                                    'to take it out. Those in hand take the colour of what '
                                                    'will happen to them — red what goes, green what is '
                                                    'added, blue what is kept. Several go as one, their '
                                                    'union: every bore of a flange taken out in one edit, '
                                                    'the part trimmed to what either of two boxes holds. The '
                                                    'tool is put away once the operation is done.',
                                                    'The solids are the cylinders, cones and spheres shown '
                                                    'in 3D Measure — each as it is drawn there, at its '
                                                    '<b>Assumed Ø</b> and out as far as it was extended — '
                                                    'and the bodies modelled in the Reverse engineer '
                                                    'workspace. A bore the scanner could not see to the '
                                                    'bottom of, which the scanning software closed part way '
                                                    'down, is cut out the way it was made: fit a cylinder to '
                                                    'the wall the scan does show, extend it down past the '
                                                    'bottom of the bore and up out through the surface, and '
                                                    "subtract it here — give it the bore's design Ø as its "
                                                    'Assumed Ø if that is what it is to come out at.',
                                                    'A boolean needs the mesh closed: close its holes with '
                                                    '<b>Fill holes</b> first. The surface the solid brings — '
                                                    "a bore's wall and floor — has no scan under it and is "
                                                    'grey in the <b>Deviation</b> view. <b>Ctrl+Z</b> puts '
                                                    'the mesh back.']},
          'Trimming a body to the scanned break': {'source': 'plugins/mesh-tools/ui/tools/TrimTool.tsx',
                                                   'paragraphs': ['For a part with a piece broken off: scan '
                                                                  'what is left, model the missing piece as '
                                                                  'a body in the Reverse engineer workspace '
                                                                  "— to the part's nominal shape, and a few "
                                                                  'millimetres too long at the break, so it '
                                                                  'reaches into the material that is still '
                                                                  'there — and cut it here with the scanned '
                                                                  'fracture. What comes back is the piece '
                                                                  'that fits, to print and glue in. The '
                                                                  'fracture is far too rough to model; it '
                                                                  'does not have to be.',
                                                                  'Click the body on the part. The '
                                                                  '<b>break</b> is found where the scan lies '
                                                                  'deeper inside the body than the '
                                                                  '<b>depth</b> — the fracture does, the '
                                                                  "part's own skins only dip into a body "
                                                                  'modelled a little larger than the part — '
                                                                  'and marked on the part in teal. Put it '
                                                                  'right with the marking tools if it caught '
                                                                  'something else, or mark it by hand; '
                                                                  '<b>Find again</b> marks it as found.',
                                                                  'The break is carried on past the body at '
                                                                  'its edges, thickened into a thin sheet, '
                                                                  'and the body cut with it: the side the '
                                                                  'missing piece is on is kept (<b>Keep the '
                                                                  'other side</b> turns that round). The '
                                                                  "body's own faces are never cut by "
                                                                  'anything but the break, so where the '
                                                                  'model and the part differ a little, a '
                                                                  'small step at the joint is all it shows.',
                                                                  "<b>Offset from break</b> sets the piece's "
                                                                  'mating face back from the fracture: 0 '
                                                                  'cuts on it, a tenth or two of a '
                                                                  'millimetre leaves room for glue. The '
                                                                  'piece is shown over the scan ghosted, its '
                                                                  'mating face in teal, and is not saved '
                                                                  'with the project — it is made again with '
                                                                  'a click.']},
          'Hollowing a part, or thickening a surface': {'source': 'plugins/mesh-tools/ui/tools/ShellTool.tsx',
                                                        'paragraphs': ['A <b>closed</b> part is hollowed: '
                                                                       'its outside stays as scanned, and an '
                                                                       'inner wall the thickness in from it '
                                                                       'all round seals a cavity — what a '
                                                                       'resin print is hollowed with. The '
                                                                       "inner wall is built from the part's "
                                                                       'distance field, not by moving the '
                                                                       'scan in: where the part is thinner '
                                                                       'than twice the wall it simply stays '
                                                                       'solid, and the wall never comes '
                                                                       'nearer the outside than the '
                                                                       'thickness. It is smoother and '
                                                                       'lighter than the scan, needing none '
                                                                       'of its detail. The cavity is sealed; '
                                                                       'open it with <b>Boolean</b> or '
                                                                       '<b>Cut</b> if it should drain.',
                                                                       'An <b>open</b> surface — one side of '
                                                                       'a part, a sheet — is thickened into '
                                                                       'a solid: a second skin the thickness '
                                                                       'from it, <b>inward</b> (the scanned '
                                                                       'surface stays the outside), '
                                                                       '<b>outward</b> or half to <b>both '
                                                                       'sides</b>, and a wall round every '
                                                                       'rim joining the two.',
                                                                       'A part closed but for a few small '
                                                                       'holes — no larger than Fill holes '
                                                                       'would fill — is asked to have them '
                                                                       'filled first, so it can be hollowed; '
                                                                       'thickened as it is, it would come '
                                                                       'out with a wall round every hole. '
                                                                       '<b>Cut</b> shows the inside without '
                                                                       'cutting. <b>Ctrl+Z</b> puts the part '
                                                                       'back.']},
          'Wrapping a part in one closed skin': {'source': 'plugins/mesh-tools/ui/tools/WrapTool.tsx',
                                                 'paragraphs': ['One closed skin round the part, for a mesh '
                                                                'that is a mess inside: an assembly exported '
                                                                'as one file, channels and bosses inside a '
                                                                'casting, shells that overlap or face the '
                                                                'wrong way, a scan with cracks. Everything '
                                                                'inside goes, and the skin is easy to print '
                                                                'or slice.',
                                                                'Think of a ball rolled all over the part '
                                                                'from outside: the wrap is where it stopped. '
                                                                'It lies on the part wherever the ball '
                                                                'touched it, and bridges every opening the '
                                                                'ball could not get through — every slot, '
                                                                'hole or crack narrower than <b>Close gaps '
                                                                'under</b>. Keep that small: a groove '
                                                                'narrower than it is closed over too.',
                                                                'An open sheet has no inside, so it wraps to '
                                                                'nothing: <b>Grow by</b> half the thickness '
                                                                'it should have, and it comes out a solid '
                                                                'that thick. Grown, the whole wrap stands '
                                                                'that far off the part.',
                                                                'The result is a preview, the bridges in '
                                                                'amber. <b>Apply</b> makes it the edited '
                                                                'copy, one step of the undo history.']},
          'The edited copy': {'source': 'plugins/mesh-tools/ui/EditedCopy.tsx',
                              'paragraphs': ['The tools edit a copy of the scan, shown here in its place. '
                                             'Every other workspace — the elements, the deviation and '
                                             'thickness maps, Reverse engineer — goes on measuring the scan '
                                             'as it was, so nothing is fitted again until you say so.',
                                             '<b>Use for analysis</b> makes the copy the scan every '
                                             'workspace measures: the elements are fitted again on it and '
                                             'the maps measured again. <b>Discard</b> throws the copy away. '
                                             'Both are one step of the undo history, and a saved project '
                                             'keeps the copy. <b>Export mesh</b> saves the copy as it '
                                             'stands, as an STL or a 3MF, in the pose the scan is shown in.',
                                             '<b>Deviation</b>, in the view bar under the part, colours the '
                                             'copy by how far it is from the scan in use — what smoothing or '
                                             'an expansion moved, where a patch stands off the surface. '
                                             'Surface an edit made where the scan had none — a filled hole, '
                                             "a cut's cap, a hollow's inner wall — has nothing to measure "
                                             'against and is grey.']}},
 'reverse': {'Reverse engineering': {'source': 'plugins/reverse/ui/ReversePanel.tsx',
                                     'paragraphs': ['Turn the scan into a <b>solid body</b> CAD opens as '
                                                    'one: sketch on a section, a fitted plane or a '
                                                    "coordinate plane, extrude or revolve the sketch's "
                                                    'regions, and export the bodies as STEP.',
                                                    "The view bar's keys: <b>Curvature</b> colours the scan "
                                                    'by how sharply it bends — flats green, convex rounds '
                                                    'towards red, hollows towards blue, sharp edges dark; a '
                                                    'surface region should end where a flat meets a round or '
                                                    'blend. <b>Deviation</b> colours the scan by its '
                                                    'distance from the bodies at the range set in the '
                                                    'feature boxes — outside up the ramp, inside down it — '
                                                    'and violet where the scan lies deep inside them: a '
                                                    'hole, pocket or slot the bodies lack. The two maps take '
                                                    'turns, and a feature being set up takes the map over '
                                                    'with its ghost. Hiding the <b>bodies</b> leaves the '
                                                    "deviation map on, still read against them; a body's own "
                                                    'eye takes it out of both. <b>Transparent</b> with the '
                                                    'scan solid shows where each stands proud of the other. '
                                                    '<b>Overlaps</b> hatch shared volume red — turn it off '
                                                    'for intentional overlaps such as a slicer modifier; it '
                                                    'is saved with the project. Tangent edges (where a round '
                                                    'meets a flat) can be drawn, dimmed or left out and '
                                                    "unpickable; a round face's seam and the cut a join "
                                                    'leaves across one surface are never drawn. Note pins '
                                                    'can be hidden; the notes stay, and placing or opening '
                                                    'one shows them.',
                                                    'The body is built in the frame the part stands in now — '
                                                    'align the part onto its fitted planes first, in the 3D '
                                                    'Measure workspace, so the model is square.',
                                                    'Modelling runs on <b>Open CASCADE Technology</b> '
                                                    '(LGPL-2.1 with the Open CASCADE exception), compiled to '
                                                    'WebAssembly by occt-wasm and loaded as a separate file '
                                                    'when this workspace is first opened. Everything stays '
                                                    'in this browser.']},
             'Features': {'source': 'plugins/reverse/ui/ReversePanel.tsx',
                          'paragraphs': ['<b>Sketch</b> on a plane: the slice the plane cuts through the '
                                         'scan is fitted with lines and arcs, corners are inferred and the '
                                         'profile closed. The sketch then shows on the part. <b>Extrude</b> '
                                         "picks the sketch's regions in the viewport and pulls them by a "
                                         'distance, to a plane, between two planes or symmetrically; '
                                         "<b>Revolve</b> turns them about a line, a cylinder's axis or a "
                                         'sketch line. Both show the body as a ghost with grips to drag '
                                         'while they are set up.',
                                         'Every extrude or revolve makes a <b>new body</b>, or <b>joins</b> '
                                         'or <b>cuts</b> one made before. Features rebuild in order whenever '
                                         'one changes; one whose plane or sketch has gone says so and the '
                                         'rest still build.',
                                         '<b>Extract</b> makes a measured plane, cylinder, cone or sphere a '
                                         'body at its extents, extended as in 3D Measure — a boss or a pin '
                                         "without a sketch — or a shadow section a block through the part's "
                                         'thickness. <b>Import STEP</b> brings a bought-in or mating part, '
                                         'or the CAD model to check against, as a body per solid, named as '
                                         "the file names them. <b>Shell</b>'s wall comes from the Thickness "
                                         'map when one was measured; open no faces for a closed hollow. '
                                         '<b>Fillet</b> reads its radius off the scan across the first edge. '
                                         '<b>Draft</b>: click the flat face that stays, then the faces to '
                                         'lean.',
                                         '<b>Move face</b> moves a flat face along its normal and a round '
                                         'one in radius; faces picked together move as a whole — a '
                                         "cylinder's wall and its ends. <b>Snap to scan</b> moves one face "
                                         'onto the scan where you click. <b>Delete face</b> takes the rest '
                                         'of a round or hole with the face clicked, and runs the faces round '
                                         'it on to close the gap. <b>Thread</b> takes ISO metric, UNC, UNF, '
                                         'a 45° form that prints without supports, or your own diameter and '
                                         'pitch, with a clearance offset for printing.',
                                         '<b>Combine</b> also trims a sheet by a solid or sews two sheets '
                                         'before Thicken. <b>Sheet</b> takes an open chain too. <b>Split</b> '
                                         'keeps the fragments lying on the scan. <b>Sweep</b> carries a '
                                         'region along lines and arcs — a bent bar, a handle. <b>Move '
                                         'body</b> takes the bodies selected, Ctrl- or Shift-clicked in the '
                                         'list, or clicked on the part; drag the gizmo or type the moves, '
                                         'and tick Copy to leave the body where it is. <b>Offset body</b> is '
                                         'kept as a body of its own — a keep-out, or a pocket with '
                                         'clearance. <b>Fit surface</b>, <b>Patch network</b> and '
                                         '<b>Trim</b> fit freeform patches to the scan — a network is '
                                         'tangent across every curve not marked a crease — and close them '
                                         'with measured shapes into a solid; <b>Thicken</b> gives a thin '
                                         'skin its wall where a shell will not go.',
                                         '<b>Compare in Deviation</b> takes the visible bodies in as the '
                                         'reference part with no best fit, as they already stand in the '
                                         "scan's frame."]},
             'The feature list': {'source': 'plugins/reverse/ui/ReversePanel.tsx',
                                  'paragraphs': ['The part is built from the top down. The <b>rollback '
                                                 'bar</b> under the list is dragged up to go back in its '
                                                 'history: the features below it are set aside, the part '
                                                 'stands as it stood there, and whatever is made next goes '
                                                 'in at the bar — a fillet before the shell, a cut before '
                                                 'the pattern. Drag it back down, or press <b>To end</b>, '
                                                 'and the rest is built again on top of what was added.',
                                                 'A feature below the bar that loses what it stood on is '
                                                 'marked in its row, as any feature that fails or builds '
                                                 'with a warning is: the name red or amber, a ⚠. Open it to '
                                                 'read what went wrong.',
                                                 '<b>Play</b> builds the part up again step by step for the '
                                                 'camera: the bar goes to the top and moves down one feature '
                                                 'at a time, each held a moment once it is built, and '
                                                 'returns where it was at the end. <b>Space</b> holds it or '
                                                 'carries it on, the <b>arrow keys</b> step it, '
                                                 '<b>Escape</b> ends it. The caption in the viewport names '
                                                 'each step.']}}}
