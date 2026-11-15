# SPDX-License-Identifier: AGPL-3.0-only
# Ported from ScanRuler by Stefan Hermann (CNC Kitchen),
# github.com/CNCKitchen/ScanRuler: the sidebar of src/app/App.tsx (one panel
# per workspace), the project half of src/ui/TopBar.tsx (project name, file
# chip, "Agent: …", "Unsaved changes") and the "§ IMPRINT" corner of
# src/ui/StatusStrip.tsx, where the credit now stands.
#
# The "ScanRuler" dock (design 2.0, 2.9, 7.2). `dock_model(st, …)` is pure:
# the workspace in front (following the agent: the last tool's area through
# workspaces.workspace_for_tool), the header strings and that workspace's
# page model. `Dock` is the thin Qt part: a header line, a QStackedWidget
# with one page per workspace, the credit at the foot, refreshed by a 100 ms
# QTimer while it is visible whenever scanstate's version moves. It is
# shown two ways: as its own QDockWidget beside the Combo View (`show_dock`)
# or as the "ScanRuler" tab of Agent Link's panel (`make_tab`, for
# agentlink.hooks.register_tab). Either way it answers the workbench's keys
# through commands.set_ui.

import importlib

from . import commands as C
from . import statusbar
from . import workspaces as W
from .pages import deviation, flat2d, measure3d, meshtools, reverse, thickness

DOCK_TITLE = "ScanRuler"
DOCK_OBJECT = "ScanRulerDock"
TAB_TITLE = "ScanRuler"
TAB_ORDER = 70  # design 2.0
REFRESH_MS = 100
UNTITLED = "Untitled project"
AGENT_TEXT = {"connected": "Agent: connected", "refused": "Agent: turned away", "listening": "Agent: listening"}
AGENT_DOT = {"connected": "#2e7d46", "refused": "#b3361c", "listening": "#8b9099"}
SAVE_TEXT = {True: "Unsaved changes", False: "No unsaved changes"}
CHECKPOINT_TEXT = "Local checkpoint saved"

PAGES = {"elements": measure3d, "deviation": deviation, "thickness": thickness, "flat": flat2d, "mesh": meshtools,
         "reverse": reverse}
ORDER = tuple(w["id"] for w in W.WORKSPACES)


# --- pure ---------------------------------------------------------------------

def poll(st):
    """(version, last_tool) of the session: scanstate's counters (design
    7.2), kept on the module or, per session, in the state dict."""
    from . import scanstate as S

    version = st.get("version", getattr(S, "version", None))
    last = st.get("last_tool", getattr(S, "last_tool", None))
    return version, last


def header(st, project=None, agent=None, dirty=None, checkpoint=False):
    """The dock's header line: "project · scan file", the agent dot and
    text (None when no link is on) and the save state."""
    scan = st.get("scan")
    name = project or UNTITLED
    line = f"{name} · {scan.name}" if scan is not None and getattr(scan, "name", None) else name
    out = {"title": line, "project": name, "file": getattr(scan, "name", None),
           "agent": AGENT_TEXT.get(agent) if agent else None, "agent_dot": AGENT_DOT.get(agent) if agent else None,
           "save": SAVE_TEXT[bool(dirty)] if dirty is not None else None,
           "checkpoint": CHECKPOINT_TEXT if checkpoint else None}
    return out


def workspace_of(st, current=W.DEFAULT_WORKSPACE):
    _v, last = poll(st)
    return W.workspace_for_tool(last, current) if last else current


def dock_model(st, ui=None, current=W.DEFAULT_WORKSPACE, project=None, agent=None, dirty=None, checkpoint=False, follow=True):
    """The dock as data: the workspace in front, its header, the page model
    and the credit. `ui` holds each page's own state by workspace id."""
    ws = workspace_of(st, current) if follow else current
    page_ui = (ui or {}).get(ws)
    return {"workspace": ws, "label": W.workspace(ws)["label"], "header": header(st, project, agent, dirty, checkpoint),
            "page": PAGES[ws].build(st, page_ui), "footer": W.CREDIT}


def press(page, key_id, page_ui, run=None):
    """A page key that runs a tool (the page's call_for), run through the
    workbench's runner: {"tool", "args", "ok", "answer"}, or None for a key
    that only opens something in the panel. Pure but for the runner."""
    call = getattr(page, "call_for", None)
    got = call(key_id, page_ui) if call is not None else None
    if got is None:
        return None
    tool, args = got
    res = (run or C.runner())(tool, args)
    if res is None:  # no runner set: the command said so
        return None
    ok, out = res
    return {"tool": tool, "args": args, "ok": ok, "answer": out}


def ui_action(key, args, ui, current):
    """What a workbench key asks of the panel (commands.set_ui's fn), as a
    change to the panel's state: (workspace, ui). Pure."""
    ui = {k: dict(v) for k, v in (ui or {}).items()}
    if key == "workspace":
        return (args[0] if args and args[0] in PAGES else current), ui
    if key.startswith("mesh:"):
        tool = key.split(":", 1)[1]
        tool = "holes" if tool == "fill" else tool
        mesh = ui.setdefault("mesh", {})
        mesh["tool"] = None if mesh.get("tool", meshtools.DEFAULT_TOOL) == tool else tool
        return "mesh", ui
    if key.startswith("reverse:"):
        return "reverse", ui
    ui.setdefault(current, {})["open"] = key
    return current, ui


# --- Qt -----------------------------------------------------------------------

def _session_from(panel=None):
    """Agent Link's session: the link's, or the panel's own."""
    # Read by name: this module never imports Agent Link (only the family
    # layer does); agentlink_state is there only when Agent Link runs.
    try:
        link = importlib.import_module("agentlink_state").link
        if link is not None and getattr(link, "session", None) is not None:
            return link.session, ("connected" if getattr(link, "going", False) else "listening")
    except ImportError:
        pass
    own = getattr(panel, "_own", None)
    return (own[0] if own else None), None


class Dock:
    """The dock's widget tree; `widget` is what goes in a QDockWidget or a tab."""

    def __init__(self, panel=None, session_fn=None, parent=None):
        from PySide import QtCore, QtWidgets

        self.panel = panel
        self.session_fn = session_fn or (lambda: _session_from(panel))
        self.current = C.current_workspace()
        self.ui = {}
        self.error = None
        self._seen = None
        self.widget = QtWidgets.QWidget(parent)
        lay = QtWidgets.QVBoxLayout(self.widget)
        self.head = QtWidgets.QLabel()
        self.head.setWordWrap(True)
        lay.addWidget(self.head)
        self.stack = QtWidgets.QStackedWidget()
        self.slots = {}
        for wid in ORDER:
            holder = QtWidgets.QScrollArea()
            holder.setWidgetResizable(True)
            self.slots[wid] = holder
            self.stack.addWidget(holder)
        lay.addWidget(self.stack, 1)
        foot = QtWidgets.QLabel(W.CREDIT)
        foot.setWordWrap(True)
        lay.addWidget(foot)
        self.widget.setToolTip(W.WORKBENCH_TIP)
        self.timer = QtCore.QTimer(self.widget)
        self.timer.setInterval(REFRESH_MS)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        C.set_ui(self.handle)
        self.refresh(force=True)

    def _state(self):
        from . import scanstate as S

        session, agent = self.session_fn()
        if session is None:
            return S.fresh(), agent, None
        return S.state(session), agent, getattr(session, "doc", None)

    def tick(self):
        if not self.widget.isVisible():
            return
        st, _a, _d = self._state()
        if poll(st) != self._seen:
            self.refresh()

    def refresh(self, force=False):
        st, agent, doc = self._state()
        seen = poll(st)
        follow = seen != self._seen and seen[1] is not None
        self._seen = seen
        dirty = doc.isTouched() if doc is not None and hasattr(doc, "isTouched") else None
        project = getattr(doc, "Label", None)
        m = dock_model(st, self.ui, self.current, project, agent, dirty, follow=follow)
        if m["workspace"] != self.current and not force:
            self.current = m["workspace"]
            try:
                C.switch_workspace(self.current)  # the toolbars follow, as a tab click would
            except Exception:
                pass
        self.current = m["workspace"]
        h = m["header"]
        bits = ["<b>%s</b>" % h["title"]]
        if h["agent"]:
            bits.append("<span style='color:%s'>●</span> %s" % (h["agent_dot"], h["agent"]))
        if h["save"]:
            bits.append(h["save"])
        self.head.setText(" &nbsp; ".join(bits))
        statusbar.feed(st, error=self.error)
        page = PAGES[self.current]
        self.slots[self.current].setWidget(page.widget(m["page"], on_key=self.key))
        self.stack.setCurrentWidget(self.slots[self.current])

    def key(self, section_id, key_id):
        page_ui = self.ui.setdefault(self.current, {})
        page_ui["pressed"] = (section_id, key_id)
        got = press(PAGES[self.current], key_id, page_ui)
        if got is not None:
            page_ui["last"] = got
            self.error = None if got["ok"] else got["answer"].get("error", {}).get("message")
        self.refresh(force=True)

    def handle(self, key, *args):
        self.current, self.ui = ui_action(key, args, self.ui, self.current)
        self.refresh(force=True)
        return True


def make_tab(panel):
    """The "ScanRuler" tab of Agent Link's panel: register_tab(TAB_TITLE,
    make_tab, TAB_ORDER)."""
    from . import runner

    call = getattr(panel, "_call", None)
    if call is not None:
        runner.set_hosted(call)  # the workbench's keys now run as the agent's do
    d = Dock(panel)
    d.widget._scanruler_dock = d  # kept alive with its widget
    d.widget.fill = d.refresh  # the panel calls fill() each time the tab comes up
    return d.widget


def register_tab(hooks):
    """Agent Link's hooks module, handed in by agentlink_families."""
    if not any(t.get("title") == TAB_TITLE for t in hooks.TABS):
        hooks.register_tab(TAB_TITLE, make_tab, TAB_ORDER)


_dock = {}


def show_dock(mw=None):
    """The dock of its own, tabbed beside the Combo View (no Agent Link)."""
    from PySide import QtCore, QtWidgets

    if mw is None:
        import FreeCADGui

        mw = FreeCADGui.getMainWindow()
    if "dock" in _dock:
        _dock["dock"].show()
        return _dock["dock"]
    dw = QtWidgets.QDockWidget(DOCK_TITLE, mw)
    dw.setObjectName(DOCK_OBJECT)
    d = Dock()
    dw.setWidget(d.widget)
    mw.addDockWidget(QtCore.Qt.LeftDockWidgetArea, dw)
    combo = mw.findChild(QtWidgets.QDockWidget, "Combo View")
    if combo is not None:
        mw.tabifyDockWidget(combo, dw)
    dw.raise_()
    _dock.update(dock=dw, model=d)
    return dw
