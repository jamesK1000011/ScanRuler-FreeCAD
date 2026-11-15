# SPDX-License-Identifier: AGPL-3.0-only
# Ported from ScanRuler by CNC Kitchen: src/commands/core/align.ts,
# src/commands/core/scanScale.ts
#
# The part's coordinate system — a 3-2-1 datum alignment and the way back —
# and the scan's true size. The scan's vertices and everything measured on
# them move together; the transform is kept, so it can be cleared.

from .. import model as M
from .. import scanstate as S
from ..schema import guarded
from . import _bind


def bind(session):
    """{tool name: fn(args)} for one session (Agent Link's, or the
    add-on's own runner's context)."""
    def st():
        return S.state(session)

    return {
        "align_datum": guarded(lambda a: M.align_datum(st(), a)),
        "align_auto": guarded(lambda a: M.align_auto(st(), a)),
        "align_symmetry": guarded(lambda a: M.align_symmetry(st())),
        "align_clear": guarded(lambda a: M.align_clear(st())),
        "scan_scale": guarded(lambda a: M.scan_scale(st(), a)),
    }


NAMES = ("align_datum", "align_auto", "align_symmetry", "align_clear", "scan_scale")
HANDLERS = _bind.table(bind, NAMES)
