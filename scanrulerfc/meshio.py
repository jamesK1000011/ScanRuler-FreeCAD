# SPDX-License-Identifier: AGPL-3.0-only
"""Reading a mesh file: STL, PLY, OBJ, OFF and 3MF through FreeCAD's Mesh
module; glTF/GLB, Collada, VRML and 3DS through Agent Link's readers when
Agent Link is installed (its family layer lends them: EXTRA)."""
import os

import numpy as np

# A loader of Agent Link's agentlink.meshformats (FORMATS, read(path,
# units)), lent by agentlink_families: fn() -> the module; None alone.
EXTRA = None


def extra():
    """The lent readers for more formats, or None."""
    if EXTRA is None:
        return None
    try:
        return EXTRA()
    except ImportError:  # an Agent Link without them
        return None


def extra_reads(path):
    """Whether the lent readers take this file."""
    mf = extra()
    return mf is not None and os.path.splitext(path)[1].lower().lstrip(".") in mf.FORMATS


def read(path, scale=1.0):
    """(V, F) of a mesh file through FreeCAD's Mesh module, V times scale."""
    from . import guard

    # A scan from the web: its size and triangles capped before and after
    # the read (red team 3, R3-6). guard.TooLarge is a ValueError.
    guard.scan_check(path)
    import Mesh

    from .scanstate import points_array

    pts, tris = Mesh.Mesh(path).Topology
    guard.triangles_check(len(tris), os.path.basename(path))
    return points_array(pts) * scale, np.array(tris, dtype=np.int64)
