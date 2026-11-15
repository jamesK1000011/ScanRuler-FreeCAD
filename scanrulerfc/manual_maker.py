# SPDX-License-Identifier: AGPL-3.0-only
"""ScanRuler's assembly manual as a service: whoever owns a Manual tab
(Workshop Documents, through Agent Link's hooks.service("manual_maker"))
hands it the steps a person ticked, and it runs manual_plan then
manual_render through that tab's runner (so the calls are shown and logged
like the agent's). agentlink_families provides it; nothing here imports
Agent Link."""
from . import CREDIT


def plan_steps(rows):
    """Rows [{title, bodies, note}] as manual_plan's steps: each places its
    bodies (parts named as the bodies), the note its words, the title kept
    beside them; a row with no bodies is left out."""
    out = []
    for k, r in enumerate(rows):
        bodies = list(r.get("bodies") or [])
        if not bodies:
            continue
        title, note = r.get("title") or "", r.get("note") or ""
        st = {"id": f"s{k + 1}", "place": [{"part": b} for b in bodies], "text": note or title}
        if note and title:
            st["notes"] = title
        out.append(st)
    return out


class ManualMaker:
    credit = CREDIT

    def make(self, runner, rows, title=""):
        """(ok, {"file", "steps", "credit", "lint"}): the manual of rows, or
        (False, the refusal {"error": {code, message}})."""
        steps = plan_steps(rows)
        if not steps:
            return False, {"error": {"code": "invalid_input", "message": "No step places a part: tick the parts that go on in each step."}}
        args = {"fromBodies": True, "steps": steps}
        if title:
            args["settings"] = {"title": title}
        ok, out = runner("manual_plan", args)
        if not ok:
            return ok, out
        ok, out = runner("manual_render", {})
        if not ok:
            return ok, out
        return True, {"file": out.get("file"), "steps": out.get("steps", 0), "credit": self.credit, "lint": out.get("lint") or {}}
