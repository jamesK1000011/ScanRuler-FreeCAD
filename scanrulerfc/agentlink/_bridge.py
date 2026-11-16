# SPDX-License-Identifier: AGPL-3.0-only
# The boundary: a family's handlers bound to Agent Link's session and given
# Agent Link as tools from data/tools.json (hooks.tools_from_data), each
# refusal (errors.ToolError) made Agent Link's ToolError with the same code
# and message. Loaded by Agent Link only.
import functools
import os

from agentlink import hooks
from agentlink.protocol import ToolError as AgentToolError

from .. import errors, handlers
from .. import scanstate as S

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
WHO = "ScanRuler for FreeCAD"

# Agent Link's refusals are refusals to the handlers too (its session.body).
if AgentToolError not in errors.REFUSED:
    errors.REFUSED = errors.REFUSED + (AgentToolError,)


def refusing(fn):
    """fn, its refusals Agent Link's."""

    @functools.wraps(fn)
    def run(*a):
        try:
            return fn(*a)
        except errors.ToolError as e:
            raise AgentToolError(e.code, e.message) from e

    return run


def touching(fn, session, tool):
    """fn, and after each call that goes through the session's scanstate
    version moves (the dock follows), as the add-on's own runner does."""

    @functools.wraps(fn)
    def run(*a):
        S.before(session)  # a move made on the scan in FreeCAD, carried in first
        out = fn(*a)
        S.touched(session, tool)
        return out

    return run


def tools(group, module, session):
    return hooks.tools_from_data(DATA, group, {k: refusing(touching(fn, session, k)) for k, fn in handlers.bound(session, module).items()}, WHO)
