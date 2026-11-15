# SPDX-License-Identifier: AGPL-3.0-only
# Ported from ScanRuler by Stefan Hermann (CNC Kitchen),
# github.com/CNCKitchen/ScanRuler: plugins/snapshot/app/shotCommands.ts.
#
# The agent's side of the camera key: it reads the shots the person took,
# with their marks, numbered pins and comments and their note, and can wait
# for the next one. It cannot take one: only the person's press starts a
# shot. Pure functions, fn(ctx, args): ctx may carry {"shots": ShotStore};
# without it they read the add-on's own store. A picture rides as "_png",
# the way Agent Link hands a picture to the agent.

from ..errors import ToolError
from .marks import composite, pins_of
from .store import STORE, file_name

WAIT_DEFAULT = 120
WAIT_MAX = 600


class SnapshotError(ToolError):
    """A refusal of the snapshot tools: the add-on's ToolError, so the
    runner and Agent Link's family layer pass it on with its code."""


def _store(ctx):
    if isinstance(ctx, dict) and ctx.get("shots") is not None:
        return ctx["shots"]
    return getattr(ctx, "shots", None) or STORE


def about(s, index):
    out = {"index": index, "id": s.id, "at": s.at.isoformat(timespec="milliseconds"), "workspace": s.workspace,
           "note": s.note or None, "width": s.width, "height": s.height, "marks": len(s.marks), "pins": pins_of(s)}
    if s.path:
        out["savedTo"] = s.path
    return out


def scan_snapshot_list(ctx, args=None):
    """The shots, newest first, without pictures."""
    st = _store(ctx)
    return {"shots": [about(s, i) for i, s in enumerate(st.shots)]}


def scan_snapshot_latest(ctx, args=None):
    """The newest shot (or `index` 1, 2…, or `id`) as a picture with its
    marks (`original: true` without), its time, workspace, note, pins and
    saved path."""
    args = args or {}
    st = _store(ctx)
    shots = list(st.shots)
    if not shots:
        raise SnapshotError("not_found", "No screenshot yet. Ask the person to press the camera key (ScanRuler toolbar, or Alt+Shift+S) in FreeCAD.")
    sid = args.get("id")
    if sid:
        at = next((i for i, s in enumerate(shots) if s.id == sid), -1)
    else:
        at = int(args.get("index", 0) or 0)
    if not 0 <= at < len(shots):
        if sid:
            raise SnapshotError("not_found", f"No screenshot {sid} — it may have been discarded.")
        n = len(shots)
        raise SnapshotError("not_found", f"There {'is 1 screenshot' if n == 1 else f'are {n} screenshots'}: index 0 to {n - 1}.")
    s = shots[at]
    png, marked = composite(s, bool(args.get("original")))
    return {**about(s, at), "of": len(shots), "picture": "with the marks" if marked else "as taken",
            "file": file_name(s, marked), "_png": png}


def scan_snapshot_wait(ctx, args=None):
    """Wait (120 s by default, 600 at most) for the next shot or finished
    mark-up, then answer what scan_snapshot_list says of it."""
    args = args or {}
    t = args.get("timeout", args.get("timeoutSeconds", WAIT_DEFAULT))
    try:
        t = float(t)
    except (TypeError, ValueError):
        raise SnapshotError("invalid_input", "timeout: seconds, 1 to 600.")
    t = max(0.0, min(float(WAIT_MAX), t))
    got = _store(ctx).wait_next(t)
    if got is None:
        return {"came": False, "note": f"No screenshot in {t:g} s."}
    return {"came": True, **about(got, 0), "next": "scan_snapshot_latest shows it."}


_told = {"stamp": None}


def notice(ctx=None):
    """Once per new shot, note or finished mark-up: the line that rides on
    the agent's next answer. None when there is nothing new."""
    st = _store(ctx)
    top = st.latest()
    if not top or st.editing == top.id or _told["stamp"] == top.stamp():
        return None
    _told["stamp"] = top.stamp()
    pins = sum(1 for m in top.marks if m.kind == "pin")
    bits = [f"in {top.workspace}" if top.workspace else None, f'note: "{top.note}"' if top.note else None,
            f"{len(top.marks)} marks, {pins} pins" if top.marks else None]
    extra = "; ".join(b for b in bits if b)
    return f"The person took a screenshot{f' ({extra})' if extra else ''} — scan_snapshot_latest shows it."


HANDLERS = {"scan_snapshot_list": scan_snapshot_list, "scan_snapshot_latest": scan_snapshot_latest, "scan_snapshot_wait": scan_snapshot_wait}
