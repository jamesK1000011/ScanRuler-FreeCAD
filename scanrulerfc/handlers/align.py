# SPDX-License-Identifier: AGPL-3.0-only
# Ported from ScanRuler by CNC Kitchen: src/commands/core/align.ts,
# src/commands/core/scanScale.ts
#
# The part's coordinate system — a 3-2-1 datum alignment and the way back —
# and the scan's true size. The scan's vertices and everything measured on
# them move together; the transform is kept, so it can be cleared.

import time

from .. import model as M
from .. import scanstate as S
from ..schema import guarded
from . import _bind


def timed(st, fn):
    """fn(args), its answer given timing { ms, object, mesh } when the call
    moved or scaled the scan: ms the tool's own work as timed here, object
    the part of it spent writing the scan's mesh object in the FreeCAD
    document (its Placement, and its mesh when the size changed), mesh
    "rebuilt" (a scale: every vertex written again) or "kept". What is not
    in ms: the state kept in the document, written after the answer is
    made (scan_info's kept says what that cost), and whatever the host
    does round the call (Agent Link's around row).

    Found live (run 3): scan_scale took 4.4 and 4.9 s on 219,600 triangles
    and align_auto 7.7 s, with nothing in the answers to say where."""

    def run(a):
        scan = st().get("scan")
        was = getattr(scan, "wrote", None)
        t0 = time.perf_counter()
        out = fn(a)
        scan = st().get("scan")
        now = getattr(scan, "wrote", None)
        if isinstance(out, dict) and now is not None and now is not was:
            out["timing"] = {"ms": int(round((time.perf_counter() - t0) * 1000)), "object": now["ms"], "mesh": now["mesh"]}
        return out

    return run


def bind(session):
    """{tool name: fn(args)} for one session (Agent Link's, or the
    add-on's own runner's context)."""
    def st():
        return S.state(session)

    return {
        "align_datum": guarded(timed(st, lambda a: M.align_datum(st(), a))),
        "align_auto": guarded(timed(st, lambda a: M.align_auto(st(), a))),
        "align_symmetry": guarded(timed(st, lambda a: M.align_symmetry(st()))),
        "align_clear": guarded(timed(st, lambda a: M.align_clear(st()))),
        "scan_scale": guarded(timed(st, lambda a: M.scan_scale(st(), a))),
    }


NAMES = ("align_datum", "align_auto", "align_symmetry", "align_clear", "scan_scale")
HANDLERS = _bind.table(bind, NAMES)
