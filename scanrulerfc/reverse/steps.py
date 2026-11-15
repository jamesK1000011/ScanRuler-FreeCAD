# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/core/buildSteps.ts
# SPDX-License-Identifier: AGPL-3.0-only
#
# The features resolved for the build: each a BuildStep of plain geometry,
# its sketches lifted into the part and its planes and axes found, and what
# resolving reads beside the feature list. The original's types are
# declarations; here a step is a dict, its kind one of STEP_KINDS, its
# fields as the original names them (resolve.py makes them):
#
#   extrude   id name sketchId profiles regions [regionsByPlace] [regionPick]
#             dir origin from to [until] draftDeg [along] op [target]
#             [onFace] [faceProfile]; from/to a number or a plane {origin, normal}
#   revolve   id name sketchId profiles regions [regionsByPlace] [regionPick]
#             origin dir angleRad pitch leftHanded op [target] [onFace]
#             [axisInSketch axisLine]
#   shell, fillet, chamfer, hole, thread, extract, cutPlane, mirror, boolean,
#   draft, moveFace, deleteFace, offsetBody, import, moveBody, sheet, split,
#   loft, sweep, thicken, pattern, surface, network, trim, sketch: the
#             feature's own numbers, picks travelling as fingerprints with
#             the queries they were given by (edgesWhere, facesWhere)
#   failed    id name message [body]: a feature that could not be resolved,
#             reported in its place while the build carries on
#
# The context a resolution reads: {sections: [{id, frame, name?, kind?,
# cut?}], elements: [{id, name?, fit?, extend?, assumed?}], modelCenter}.

STEP_KINDS = ("extrude", "revolve", "shell", "fillet", "chamfer", "hole", "thread", "extract", "cutPlane", "mirror", "boolean", "draft", "moveFace", "deleteFace",
              "offsetBody", "import", "moveBody", "sheet", "split", "loft", "sweep", "thicken", "pattern", "surface", "network", "trim", "sketch", "failed")

SOLID_STEPS = ("extrude", "revolve")
BODY_STEPS = ("shell", "fillet", "chamfer", "hole", "thread", "cutPlane", "mirror", "boolean", "split", "pattern", "draft", "moveFace", "deleteFace", "offsetBody")

SURFACE_MIN_REGION = 16
