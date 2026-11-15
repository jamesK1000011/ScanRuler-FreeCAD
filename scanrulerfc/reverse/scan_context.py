# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): what plugins/reverse/app hands core/resolve.ts and the Builder from the scan (its sections, its measured elements, the model's centre, the scan itself)
# SPDX-License-Identifier: AGPL-3.0-only
#
# The scan's side of a Reverse engineer build. A feature list names the
# scan's planes and axes — a sketch on a section's plane or a measured
# plane, a revolve about a measured axis, a cut by a measured plane, a trim
# by measured elements — and reads the scan itself (a split that keeps what
# lies on it, a fitted surface, a trim, a patch network). Here those come
# from the scan family's state of the session that edits the document:
# context_of(state) is the resolution's context {sections, elements,
# modelCenter} with the scan beside it, in the original's plain fields.
# bind(doc, session) records which session edits a document, and
# doc.CONTEXT["of"] is set to read it when the container builds.

from . import doc as D
from .buildtypes import plain as _plain

_SESSIONS = {}


def empty():
    return {"sections": [], "elements": [], "modelCenter": [0, 0, 0], "scan": None}


def context_of(st):
    """The context a build reads, from the scan family's state (scanstate
    .state(session)): the sections cut on the scan open now, with their
    frames; the measured elements with their fits (the points they were
    fitted to left behind); the centre of the scan's box; the scan's
    points and triangles, or None with no scan."""
    if not st:
        return empty()
    scan = st.get("scan")
    sec = st.get("sectionState") or {}
    sections = []
    if scan is not None and sec.get("scan") is scan:
        for s in sec.get("sections") or []:
            if s.get("frame") is None:
                continue
            sections.append({"id": s["id"], "name": s.get("name"), "kind": s.get("kind", "cut"), "frame": _plain({k: s["frame"][k] for k in ("origin", "normal", "basisU", "basisV")})})
    elements = []
    for e in st.get("elements") or []:
        el = {"id": e["id"], "name": e.get("name"), "kind": e.get("kind"), "fit": _plain({k: v for k, v in (e.get("fit") or {}).items() if k != "region"}) or None}
        for k in ("assumed", "extend"):
            if e.get(k) is not None:
                el[k] = _plain(e[k])
        elements.append(el)
    if scan is None or not len(scan.V):
        return {"sections": sections, "elements": elements, "modelCenter": [0, 0, 0], "scan": None}
    centre = _plain((scan.V.min(axis=0) + scan.V.max(axis=0)) / 2)
    return {"sections": sections, "elements": elements, "modelCenter": centre, "scan": (scan.V, scan.F)}


def of_session(session):
    from .. import scanstate as S

    if session is None or getattr(session, "family_state", None) is None:
        return empty()
    return context_of(S.state(session))


def of_document(doc):
    """doc.CONTEXT["of"]: the context of the session that last edited the
    document, or an empty one."""
    return of_session(_SESSIONS.get(getattr(doc, "Name", None)))


def bind(doc, session):
    """The session that edits this document: its scan is the build's."""
    name = getattr(doc, "Name", None)
    if name is not None and session is not None:
        _SESSIONS[name] = session
    D.CONTEXT["of"] = of_document
