# SPDX-License-Identifier: AGPL-3.0-only
# Ported from ScanRuler by CNC Kitchen: src/commands/core/dimension.ts,
# src/commands/core/session.ts (report.get), src/core/summary.ts
#
# Dimensions and tolerances between elements, held to limits for a verdict,
# and the report of everything measured.

import os

from .. import model as M
from .. import scanstate as S
from ..errors import ToolError
from ..schema import guarded
from . import _bind


def bind(session):
    """{tool name: fn(args)} for one session (Agent Link's, or the
    add-on's own runner's context)."""
    def st():
        return S.state(session)

    def report(a):
        s = st()
        if a.get("format", "json") == "text":
            return {"format": "text", "workspace": "measure", "text": M.report_text(s)}
        return {"format": "json", "report": M.report_json(s)}

    def export_csv(a):
        s = st()
        M.require_scan(s)
        path = a.get("path") or os.path.join(session.out_dir, os.path.splitext(s["scan"].name)[0] + "-measurements.csv")
        d = os.path.dirname(os.path.abspath(path))
        if not os.path.isdir(d):
            raise ToolError("not_found", f"path: the folder {d} does not exist — give a path in a folder that does, or leave path out for the session's output folder.")
        return M.export_csv(s, path)

    return {
        "dimension_add": guarded(lambda a: M.dimension_add(st(), a)),
        "dimension_set_limit": guarded(lambda a: M.dimension_set_limit(st(), a["dimension"], a["limit"])),
        "dimension_set_basic": guarded(lambda a: M.dimension_set_basic(st(), a["dimension"], a["basic"])),
        "dimension_remove": guarded(lambda a: M.dimension_remove(st(), a["dimension"])),
        "report_get": guarded(report),
        "export_csv": guarded(export_csv),
    }


NAMES = ("dimension_add", "dimension_set_limit", "dimension_set_basic", "dimension_remove", "report_get", "export_csv")
HANDLERS = _bind.table(bind, NAMES)
