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
WORKBENCH = "ScanRulerWorkbench"
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


def history_mark(doc):
    """Where the document stands in FreeCAD's undo history: (UndoCount,
    RedoCount), or None. An undo or a redo (Edit › Undo, Agent Link's
    history_undo / history_redo) moves it without a ScanRuler call, so
    scanstate's version stays: the panel read the Reverse engineer's
    features before the undo and kept them (window review round 3, sr-b
    8056 / 8061: Features 0 after the undo of a clear, 9 after its redo).
    The dock draws again when this moves too."""
    if doc is None:
        return None
    try:
        return (int(doc.UndoCount), int(doc.RedoCount))
    except Exception:  # noqa: BLE001 — a closed document or a stand-in: no history to follow
        return None


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


def _nb(text):
    """A phrase that never breaks across lines."""
    return text.replace(" ", "&nbsp;")


def header_html(h):
    """The header label's rich text: the project and scan, the agent's dot
    and word, and the save state on a line of its own, each phrase kept
    whole, so a narrow panel (354 px) wraps between them, never inside."""
    first = ["<b>%s</b>" % h["title"]]
    if h["agent"]:
        first.append("<span style='color:%s'>●</span>&nbsp;%s" % (h["agent_dot"], _nb(h["agent"])))
    lines = [" &nbsp; ".join(first)]
    if h["save"]:
        lines.append(_nb(h["save"]))
    if h.get("error"):
        lines.append("<span style='color:%s'>⚠ %s</span>" % (statusbar.COLOURS["ERROR"], h["error"]))
    return "<br>".join(lines)


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


def press(page, key_id, page_ui, run=None, native=None):
    """A page key that runs a tool (the page's call_for), run through the
    workbench's runner: {"tool", "args", "ok", "answer"}, or None for a key
    that only opens something in the panel. A key whose job is FreeCAD's
    (Move / rotate by numbers: Std_Placement on the scan) runs FreeCAD's
    command (commands.run_native) and answers None. Pure but for the
    runner and the command."""
    spec = C.native_key(key_id)
    if spec is not None:
        (native or C.run_native)(spec)
        return None
    call = getattr(page, "call_for", None)
    got = call(key_id, page_ui) if call is not None else None
    if got is None:
        return None
    tool, args = got
    res = (run or C.runner())(tool, args)
    if res is None:  # no runner set: the command said so
        return None
    ok, out = res
    got = {"tool": tool, "args": args, "ok": ok, "answer": out}
    after = getattr(page, "after_press", None)
    if after is not None:
        after(key_id, got)  # a box that made its feature closes
    return got


def box_to_show(was, now):
    """Whether a feature box just opened (or another took its place): the
    dock scrolls it into view, as the person sees nothing happen when it
    opens below the fold. Not on each refresh of the same box."""
    return now is not None and now != was


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


def follow_width(w):
    """w takes the panel's width and asks for none of its own: its size
    policy Ignored across (its height as it was). A QScrollArea's size hint
    is its page's, up to 36 lines wide (about 640 px on the Mac), and a
    wrapped label's is its text on one long line: as hints they set the
    dock's width when FreeCAD lays the docks out, and the 3D view was left
    a strip. Their minimum widths stay small (keys, six-letter lists,
    wrapped labels), so the panel fits 354 px with nothing cut."""
    from PySide import QtWidgets

    p = w.sizePolicy()
    w.setSizePolicy(QtWidgets.QSizePolicy.Ignored, p.verticalPolicy())
    return w


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
        from .pages import kit

        # FreeCAD's theme paints the page, text and keys; translucent cards,
        # restyled when the theme changes (theme.follow); CNC Kitchen blue
        # as the accent.
        from . import theme

        self.widget.setObjectName(kit.PAGE)
        theme.follow(self.widget)

        lay.setSpacing(kit.SPACING)  # dense: a whole section fits without scrolling
        lay.setContentsMargins(kit.MARGIN, kit.MARGIN, kit.MARGIN, kit.MARGIN)
        self.head = QtWidgets.QLabel()
        self.head.setWordWrap(True)
        follow_width(self.head)
        lay.addWidget(self.head)
        # "Unsaved changes" on a line of its own (header_html), so a narrow
        # panel never breaks it in two.
        self.stack = QtWidgets.QStackedWidget()
        self.slots = {}
        for wid in ORDER:
            holder = QtWidgets.QScrollArea()
            holder.setWidgetResizable(True)
            # Up and down only: the page follows the panel's width and its
            # grids and rows reflow (pages/kit.reflow).
            holder.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
            holder.setMinimumWidth(0)
            follow_width(holder)
            self.slots[wid] = holder
            self.stack.addWidget(holder)
        follow_width(self.stack)
        lay.addWidget(self.stack, 1)
        foot = QtWidgets.QLabel(W.CREDIT)
        foot.setWordWrap(True)
        follow_width(foot)
        lay.addWidget(foot)
        self.widget.setToolTip(W.WORKBENCH_TIP)
        self.timer = QtCore.QTimer(self.widget)
        self.timer.setInterval(REFRESH_MS)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        C.set_ui(self.handle)
        install_shortcut(lambda: self.handle("snapshot"))
        _dock["live"] = self
        self.refresh(force=True)

    def reveal(self):
        """Bring this widget into view where it already stands: the tab that
        holds it turned to, the dock that holds it shown. True if it shows."""
        from PySide import QtWidgets

        w = self.widget
        p = w.parentWidget()
        while p is not None:
            if isinstance(p, QtWidgets.QTabWidget):
                for i in range(p.count()):
                    page = p.widget(i)
                    if page is w or page.isAncestorOf(w):
                        p.setCurrentIndex(i)
            elif isinstance(p, QtWidgets.QDockWidget):
                p.show()
                p.raise_()
            p = p.parentWidget()
        return w.isVisible()

    def _state(self):
        from . import scanstate as S

        session, agent = self.session_fn()
        if session is None:
            return S.fresh(), agent, None
        return S.state(session), agent, getattr(session, "doc", None)

    def tick(self):
        if not self.widget.isVisible():
            return
        st, _a, doc = self._state()
        if (poll(st) != self._seen or reverse.editor_version() != getattr(self, "_box_seen", None)
                or history_mark(doc) != getattr(self, "_history_seen", None)):
            self.refresh()

    def refresh(self, force=False):
        st, agent, doc = self._state()
        seen = poll(st)
        self._box_seen = reverse.editor_version()  # the feature box's numbers and ghost line
        self._history_seen = history_mark(doc)  # an undo or a redo draws the panel again
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
        self.head.setText(header_html({**m["header"], "error": self.error}))
        statusbar.feed(st, error=self.error)
        page = PAGES[self.current]
        self.slots[self.current].setWidget(page.widget(m["page"], on_key=self.key, on_field=self.field))
        self.stack.setCurrentWidget(self.slots[self.current])
        box = reverse.box_key() if self.current == "reverse" else None
        if box_to_show(getattr(self, "_box_shown", None), box):
            self._bring_into_view(self.slots[self.current], reverse.EDITOR_SECTION)
        self._box_shown = box

    def _bring_into_view(self, holder, section_id):
        """A section of the page scrolled into view, once the page is laid
        out (on the next turn of Qt's loop)."""
        from PySide import QtCore, QtWidgets

        from .pages import kit

        page = holder.widget()
        target = page.findChild(QtWidgets.QWidget, kit.section_object_name(section_id)) if page is not None else None
        if target is None:
            C._say(f"ScanRuler: the {section_id} box opened but its group was not found to scroll to.", warn=True)
            return

        def bring():
            try:
                holder.ensureWidgetVisible(target, 0, kit.MARGIN)
            except RuntimeError:  # the page was drawn again meanwhile: the next refresh scrolls
                pass

        QtCore.QTimer.singleShot(0, bring)

    def key(self, section_id, key_id):
        page_ui = self.ui.setdefault(self.current, {})
        page_ui["pressed"] = (section_id, key_id)
        got = press(PAGES[self.current], key_id, page_ui)
        if got is not None:
            page_ui["last"] = got
            self.error = None if got["ok"] else got["answer"].get("error", {}).get("message")
        self.refresh(force=True)

    def field(self, section_id, field_id, value):
        """A field of the page changed: the page's on_field, where it has one."""
        fn = getattr(PAGES[self.current], "on_field", None)
        if fn is not None:
            fn(section_id, field_id, value)
            self.refresh(force=True)

    def handle(self, key, *args):
        if key == "snapshot":
            # The camera key (ScanRuler_Snapshot: the view bar's camera and
            # the View menu's Snapshot) and Alt+Shift+S: the shot is taken
            # here. Until 16 Nov 2026 nothing took it — the key only reached
            # ui_action, which noted it as a group to open — so no shot was
            # ever kept and scan_snapshot_latest could only say there was none.
            self.error = snapshot_key(self.current)
            self.refresh(force=True)
            return True
        self.current, self.ui = ui_action(key, args, self.ui, self.current)
        if key.startswith("reverse:"):
            kind = key.split(":", 1)[1]
            if kind in reverse.READY_KINDS:
                reverse.open_kind(kind, self.ui.get("reverse"))  # the toolbar's key opens the box, as the panel's does
        if key == "view" and args and args[0] in ("ViewSplit", "ViewColourPlot"):
            why = split_view_key(args[0], bool(args[1]) if len(args) > 1 else True, lambda: self.session_fn()[0], self.current)
            if args[0] == "ViewSplit":
                self.error = why  # in the panel's header until the next press
        self.refresh(force=True)
        return True


def snapshot_key(workspace=None, take=None):
    """The camera key's press: one frame of FreeCAD's window kept as a shot
    with the workspace it was taken in, and its card opened for the note and
    the marks (snapshot/card.take_shot; scan_snapshot_list and
    scan_snapshot_latest then give it to the agent, and Agent Link's next
    answer carries the notice of it). None, or why no shot could be taken,
    for the panel's header."""
    try:
        if take is None:
            from .snapshot import card

            take = card.take_shot
        take(workspace=workspace)
        return None
    except Exception as e:  # noqa: BLE001 — a key never raises into FreeCAD's command loop
        return f"The screenshot could not be taken ({type(e).__name__}: {e})."


# The Alt+Shift+S shortcut on FreeCAD's window, kept so Qt does not let it
# go, and the press it stands for: the newest dock's.
_shortcut = {"key": None, "press": None}


def install_shortcut(press, install=None):
    """Alt+Shift+S on FreeCAD's main window presses the camera key (the
    tools' descriptions and the key's tip name it; until 16 Nov 2026 it was
    never installed). Once a window: a dock made again (ScanRuler's own, or
    its tab under Agent Link) only takes the press over. True when the
    shortcut is there."""
    _shortcut["press"] = press
    if _shortcut["key"] is not None:
        return True
    try:
        if install is None:
            from .snapshot import card

            install = card.install
        _shortcut["key"] = install(press=lambda: _shortcut["press"] and _shortcut["press"]())
    except Exception as e:  # noqa: BLE001 — no window, or a Qt without the shortcut: the camera key still works
        C._say(f"ScanRuler: the screenshot shortcut could not be set ({type(e).__name__}: {e}); the camera key takes the shot.", warn=True)
        _shortcut["key"] = None
    return _shortcut["key"] is not None


SPLIT_WORKSPACE = "deviation"


def split_wrong_workspace(workspace):
    """Why the Split view does not open in this workspace, or None."""
    if workspace is None or workspace == SPLIT_WORKSPACE:
        return None
    return f"Split view needs a scan and a reference in {W.workspace(SPLIT_WORKSPACE)['label']}."


# Set while the Split view key is handled: a press that comes back from
# inside it (the key let up through its action's signal) is dropped.
_split_busy = {"on": False}


def split_view_key(key, on, session_fn, workspace=None):
    """The Split view key (and Colour plot, which recolours an open split
    view): the split viewer opened, closed or refreshed. What went wrong, or
    None. A key that could not open it is let up again, once, and the
    reason said once per press."""
    from . import split_view

    colour_plot = lambda: C._state["view"].get("ViewColourPlot", True)  # noqa: E731
    if key == "ViewColourPlot":
        sv = split_view._live["split"]
        return sv.show() if sv is not None and sv.open else None
    if _split_busy["on"]:
        return None

    def let_up():
        C._state["view"]["ViewSplit"] = False
        try:
            C.set_checked("ScanRuler_ViewSplit", False)
        except Exception:  # noqa: BLE001 — no window: the state is enough
            pass

    _split_busy["on"] = True
    try:
        why = split_wrong_workspace(workspace) if on else None
        why = why or split_view.toggle(on, session_fn, colour_plot)
        if why:
            # The Report view, where a cmd_run's caller looks.
            C._say(f"ScanRuler: {why}" if why.startswith("Split view") else f"ScanRuler: Split view: {why}")
        if why and on:
            let_up()
    finally:
        _split_busy["on"] = False
    if split_view._live["split"] is not None:
        split_view._live["split"].on_closed = let_up  # its tab closed: the next press opens it
    return why


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
    # The page's foot credits Stefan Hermann (CNC Kitchen) itself, so Agent
    # Link hides its own credit line while this tab is in front (one credit,
    # not two). Said here too for an Agent Link that reads it off the widget.
    d.widget.own_credit = True
    return d.widget


def hosted_tab_wanted(hooks):
    """Whether ScanRuler's page is a tab of Agent Link's panel: only for an
    Agent Link that cannot place an add-on's own dock (no "panel_layout"
    service: headless, or before panel layouts). Otherwise the page is
    its own dock, "ScanRuler", beside Model and Tasks."""
    service = getattr(hooks, "service", None)
    return service is None or service("panel_layout") is None


def register_tab(hooks):
    """Agent Link's hooks module, handed in by agentlink_families."""
    if not hosted_tab_wanted(hooks):
        return
    if not any(t.get("title") == TAB_TITLE for t in hooks.TABS):
        # The tab only while ScanRuler is the workbench in front, and with
        # own_credit: its page carries Stefan Hermann's (CNC Kitchen) credit
        # line, so Agent Link hides its own while the tab is up. Older Agent
        # Links take fewer arguments.
        for kw in ({"workbench": WORKBENCH, "own_credit": True}, {"workbench": WORKBENCH}, {}):
            try:
                hooks.register_tab(TAB_TITLE, make_tab, TAB_ORDER, **kw)
                return
            except TypeError:
                continue


_dock = {}


def live():
    """The Dock the workbench's keys go to (the last one made), or None."""
    return _dock.get("live")


def _hosted_tab():
    """Whether Agent Link's panel has the ScanRuler tab (an older Agent
    Link); else the page is ScanRuler's own dock."""
    try:
        hooks = importlib.import_module("agentlink.hooks")
        return any(t.get("title") == TAB_TITLE for t in hooks.TABS)
    except Exception:  # noqa: BLE001
        return False


def _agentlink_caller():
    """Agent Link's "panel_caller" service (its clicks shown and logged as
    the agent's are), or None alone."""
    import scanrulerfc

    if not scanrulerfc._hosted:
        return None
    try:
        return importlib.import_module("agentlink.hooks").service("panel_caller")
    except Exception:  # noqa: BLE001
        return None


def open_panel(mw=None):
    """The ScanRuler page in view before a key or workspace switch reaches
    it. Under Agent Link its panel's ScanRuler tab: the panel opened where
    Agent Link opens it, if it is not yet (its tab is made with it, and
    the keys go to it from then on). Alone, or if that tab cannot show, the
    ScanRuler dock of its own. Before, a switch with Agent Link loaded but
    its panel closed went to no panel at all and showed nothing. Nothing
    without a QApplication (FreeCADCmd, tests)."""
    from PySide import QtWidgets

    if QtWidgets.QApplication.instance() is None:
        return None
    import scanrulerfc

    if scanrulerfc._hosted and _hosted_tab():
        try:
            show = importlib.import_module("agentlink.panel").show
            try:
                show(tab=TAB_TITLE)  # the tab in front, even outside the workbench
            except TypeError:  # an Agent Link before tabs per workbench
                show()
        except Exception:  # noqa: BLE001 — no Agent Link panel here: the dock of its own
            pass
    d = live()
    if d is not None:
        try:
            if d.reveal():
                return d
        except RuntimeError:  # its widget was deleted with a closed panel
            _dock.pop("live", None)
    show_dock(mw)
    return live()


def show_dock(mw=None):
    """The dock of its own (no Agent Link), placed where the panel layout
    setting puts it (layout.py: a Combo View tab by default, the right side, or a
    slide-out over the 3D view)."""
    from PySide import QtWidgets

    from . import layout

    if mw is None:
        import FreeCADGui

        mw = FreeCADGui.getMainWindow()
    if "dock" in _dock:
        dw = _dock["dock"]
        C.set_ui(_dock["model"].handle)  # the keys come back to it from a closed panel's tab
        _dock["live"] = _dock["model"]
    else:
        dw = QtWidgets.QDockWidget(DOCK_TITLE, mw)
        dw.setObjectName(DOCK_OBJECT)
        # Under Agent Link the keys run through it (shown and logged as
        # the agent's), and the page reads its session.
        caller = _agentlink_caller()
        if caller is not None:
            from . import runner

            runner.set_hosted(caller._call)
        d = Dock(panel=caller)
        dw.setWidget(d.widget)
        _dock.update(dock=dw, model=d)
    p = layout.placer()
    p.show(DOCK_OBJECT, dw, WORKBENCH, DOCK_TITLE)
    p.reveal(DOCK_OBJECT)
    return dw
