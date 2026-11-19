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
    version moves (the dock follows), as the add-on's own runner does.

    The state is written into the FreeCAD document (docstate.mark: the
    ScanRulerState object, the scan's mesh object) on the thread FreeCAD's
    documents live on only. A heavy tool that Agent Link runs as a job
    (its jobs.py: a worker thread named "agentlink-job-<tool>") answers
    off that thread, where a document write would reach the window's
    views from the wrong thread: scanstate.touched hands its write to the
    GUI thread when a window is up, and otherwise leaves it for the next
    ScanRuler call off a job (docstate.on_gui_thread; mark writes whenever
    the state differs from what it wrote last), so nothing is lost but
    the moment."""

    @functools.wraps(fn)
    def run(*a):
        S.before(session)  # a move made on the scan in FreeCAD, carried in first
        out = fn(*a)
        # The arguments and the answer go along for the window's drawing of
        # this call's results (scene_coin; nothing is drawn without a window).
        S.touched(session, tool, args=a[0] if a and isinstance(a[0], dict) else None, answer=out)
        return out

    return run


def home_short(fn):
    """fn, with paths under the home folder shown as ~/... in its answer and
    in its refusals (red team 3, R3-12: transcripts are shared). A ~/...
    path given back to a tool is read as the same file (paths.resolve)."""
    from .. import guard

    @functools.wraps(fn)
    def run(*a):
        try:
            out = fn(*a)
        except (errors.ToolError, AgentToolError) as e:
            raise AgentToolError(e.code, guard.tilde(e.message)) from e
        except ValueError as e:  # Agent Link answers a bare ValueError invalid_input with its text: the same, paths short
            raise AgentToolError("invalid_input", guard.tilde(str(e))) from e
        return guard.tilde(out)

    return run


def tools(group, module, session):
    return hooks.tools_from_data(DATA, group, {k: home_short(refusing(touching(fn, session, k))) for k, fn in handlers.bound(session, module).items()}, WHO)
