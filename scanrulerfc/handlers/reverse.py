# SPDX-License-Identifier: AGPL-3.0-only
# The Reverse engineer's handlers in the families' registry: the tools of
# scanrulerfc/reverse/handlers.py (ScanRuler by Stefan Hermann / CNC
# Kitchen, ported), bound to the context's document. Their refusals are
# already the add-on's ToolError.
from ..reverse import handlers as R
from . import _bind


def bind(session):
    return R.handlers(session)


NAMES = tuple(R.tool_names())
HANDLERS = _bind.table(bind, NAMES)
