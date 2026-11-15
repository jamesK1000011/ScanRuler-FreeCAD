# SPDX-License-Identifier: AGPL-3.0-only
# Ported from ScanRuler by CNC Kitchen: src/commands/core/element.ts
#
# Elements: fitted on the scan, constructed from others, renamed, removed,
# shown and hidden.

from .. import model as M
from .. import scanstate as S
from .. import symmetry as SYM
from ..schema import guarded
from . import _bind


def bind(session):
    """{tool name: fn(args)} for one session (Agent Link's, or the
    add-on's own runner's context)."""
    def st():
        return S.state(session)


    return {
        "element_fit": guarded(lambda a: M.element_fit(st(), a)),
        "element_fit_marked": guarded(lambda a: M.element_fit_marked(st(), a)),
        "element_construct": guarded(lambda a: M.element_construct(st(), a, SYM.find_symmetry)),
        "element_rename": guarded(lambda a: M.element_rename(st(), a["element"], a["name"])),
        "element_unlink": guarded(lambda a: M.element_unlink(st(), a["element"])),
        "element_remove": guarded(lambda a: M.element_remove(st(), a["element"])),
        "element_set_visible": guarded(lambda a: M.element_set_visible(st(), a)),
        "element_list": guarded(lambda a: {"elements": [M.describe_element(e) for e in st()["elements"]]}),
    }


NAMES = ("element_fit", "element_fit_marked", "element_construct", "element_rename", "element_unlink", "element_remove", "element_set_visible", "element_list")
HANDLERS = _bind.table(bind, NAMES)
