# SPDX-License-Identifier: AGPL-3.0-only
# Ported from ScanRuler by Stefan Hermann (CNC Kitchen),
# github.com/CNCKitchen/ScanRuler: what each key of the original's top bar,
# panels and view bar does, as FreeCAD commands (design sections 1, 2.8, 2.9).
#
# One command per key in workspaces.py. A key that runs a tool hands it to
# the runner the host sets (`set_runner`): Agent Link's hosted family, or
# scanrulerfc's own handlers once the add-on stands alone, so the same code
# runs either way. A key that opens something in the panel hands its key to
# the panel (`set_ui`). A workspace key switches the workspace: the page and
# the toolbars, as a tab click does in the original. FreeCAD and Qt are
# imported only when a command runs, so the tables and the tests load
# without them. No Agent Link import.

import os

from . import workspaces as W

ICONS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")


def icon_path(name):
    return os.path.join(ICONS, name + ".svg")


# --- hooks -------------------------------------------------------------------

def _no_runner(tool, args):
    _say(f"ScanRuler: {tool} needs a runner (scanrulerfc.commands.set_runner) — none is set yet.")
    return None


def _no_ui(key, *args):
    _tell("ScanRuler: the ScanRuler panel could not open, so this has nothing to show in yet.")
    return None


STATUS_MS = 8000
NEED_SCAN = "Open a scan first: ScanRuler ▸ Open Scan…"
# The workspaces whose keys all work on the scan: a key there with no scan
# open says so (2D Measure reads a flatbed image, Reverse Engineer can start
# from a sketch or a STEP file).
SCAN_WORKSPACES = ("elements", "deviation", "thickness", "mesh")


_hooks = {"runner": _no_runner, "ui": _no_ui, "placeholder": True}
_state = {"workspace": W.DEFAULT_WORKSPACE, "view": {}}


def set_runner(fn):
    """fn(tool, args) -> answer. Set at registration by the host."""
    _hooks["runner"] = fn or _no_runner
    _hooks["placeholder"] = fn is None


def runner():
    return _hooks["runner"]


def has_runner():
    return not _hooks["placeholder"]


def set_ui(fn):
    """fn(key, *args): the panel's side of a key that opens something in it,
    and of workspace and view switches."""
    _hooks["ui"] = fn or _no_ui


def current_workspace():
    return _state["workspace"]


def _say(msg):
    try:
        import FreeCAD

        FreeCAD.Console.PrintMessage(msg + "\n")
    except ImportError:
        pass


def _tell(msg):
    """Say it where the person looks: the status bar, and the Report view."""
    _say(msg)
    try:
        _gui().getMainWindow().statusBar().showMessage(msg, STATUS_MS)
    except Exception:  # no window (FreeCADCmd, tests): the Report view has it
        pass


def human(message, code=None):
    """A tool's refusal as a person reads it: one that sends an agent to
    scan_open names the menu item instead."""
    if code == "no_scan" or "scan_open" in (message or ""):
        return NEED_SCAN
    return message


def report(label, res):
    """A key's run said in the status bar: done, or why not. `res` is the
    runner's (ok, answer); anything else (no runner: it said so) is left."""
    if not (isinstance(res, tuple) and len(res) == 2):
        return
    ok, out = res
    if ok:
        _tell(f"ScanRuler: {label} done.")
        return
    err = (out or {}).get("error", {}) if isinstance(out, dict) else {}
    _tell("ScanRuler: " + human(err.get("message") or "it did not run.", err.get("code")))


def _to_panel(key, *args):
    """Bring the ScanRuler page into view (dock.open_panel), then hand it
    the key."""
    try:
        from . import dock

        dock.open_panel()
    except ImportError:  # no Qt here: the hook says what it can
        pass
    except Exception as e:  # noqa: BLE001 — a panel that fails to open must not take the key with it
        _say(f"ScanRuler: the panel did not open: {e}")
    return _hooks["ui"](key, *args)


def scan_is_open():
    """True or False when it can tell whether a scan is open where the keys
    run, None when it cannot (under Agent Link before its panel is up)."""
    try:
        from . import dock

        d = dock.live()
        if d is not None:
            return d._state()[0].get("scan") is not None
        import scanrulerfc

        if scanrulerfc._hosted:
            return None
        import FreeCAD

        doc = getattr(FreeCAD, "ActiveDocument", None)
        if doc is None:
            return False
        from . import runner as R
        from . import scanstate as S

        return S.state(R.context_for(doc)).get("scan") is not None
    except Exception:  # noqa: BLE001 — unknown: say nothing rather than something wrong
        return None


def _gui():
    import FreeCADGui

    return FreeCADGui


def _main_window():
    try:
        return _gui().getMainWindow()
    except Exception:  # noqa: BLE001 — no window (FreeCADCmd, tests): a dialog of its own
        return None


# --- workspace switching -----------------------------------------------------

def toolbar_names(ws):
    return [W.toolbar_name(ws, title) for title, _ in W.TOOLBARS[ws]]


def switch_workspace(ws):
    """Show the workspace's toolbars and hide the others', check its key,
    show its label beside its icon, and turn the panel's page."""
    W.workspace(ws)  # KeyError on an unknown id
    _state["workspace"] = ws
    _remember_toolbars(ws)
    try:
        mw = _gui().getMainWindow()
        from PySide import QtWidgets  # FreeCAD's shim, Qt5 or Qt6

        apply_toolbars(mw)
        _apply_later(mw)
        _restyle_switcher(mw, QtWidgets)
    except ImportError:
        pass
    _to_panel("workspace", ws)
    return ws


# --- the workspace toolbars, kept switched -------------------------------------
# On FreeCAD 1.1 (macOS) writing the saved visibility and hiding the toolbar
# once was not enough: the toolbar row stayed the same in every workspace,
# because FreeCAD's ToolBarManager shows its toolbars again after the
# switch (its restore, a workbench (re)activation). So the switch is
# applied three ways: at once, again after FreeCAD's restore has run
# (REAPPLY_MS), and whenever one of another workspace's toolbars comes back
# while ScanRuler is the active workbench (each toolbar's visibilityChanged).
# The decisions are pure (toolbar_plan, rehide); only apply_toolbars touches Qt.

REAPPLY_MS = (250, 700)
WORKBENCH_NAME = "ScanRulerWorkbench"


def _toolbar_owners():
    return {name: wid for wid in W.TOOLBARS for name in toolbar_names(wid)}


def toolbar_owner(name, title=None):
    """The workspace a QToolBar belongs to, by its object name, or by its
    title should FreeCAD have named it otherwise; None for any other."""
    owners = _toolbar_owners()
    return owners.get(name) or owners.get(title)


def toolbar_plan(ws, present, active=True):
    """{toolbar: visible} for the workspace toolbars among `present` ((object
    name, title) pairs): the workspace's shown, the others hidden. Nothing
    while ScanRuler is not the active workbench: FreeCAD hides them all then,
    and showing one would put it in another workbench."""
    if not active:
        return {}
    out = {}
    for name, title in present:
        owner = toolbar_owner(name, title)
        if owner is not None:
            out[name] = owner == ws
    return out


def rehide(name, title, visible, ws, active):
    """True when a toolbar that just showed belongs to another workspace and
    must be hidden again."""
    owner = toolbar_owner(name, title)
    return bool(visible and active and owner is not None and owner != ws)


def scanruler_active():
    """True when ScanRuler is FreeCAD's active workbench (True when it
    cannot tell: the switch came from one of its keys)."""
    try:
        wb = _gui().activeWorkbench()
    except Exception:  # noqa: BLE001 — no FreeCADGui here
        return True
    if wb is None:
        return False
    try:
        return wb.name() == WORKBENCH_NAME
    except Exception:  # noqa: BLE001 — an older binding: the class name is the registered name
        return type(wb).__name__ == WORKBENCH_NAME


def apply_toolbars(mw):
    """Show and hide the workspace toolbars as toolbar_plan says, and watch
    each so FreeCAD cannot bring another workspace's back."""
    from PySide import QtWidgets

    bars = [tb for tb in mw.findChildren(QtWidgets.QToolBar) if toolbar_owner(tb.objectName(), tb.windowTitle())]
    plan = toolbar_plan(_state["workspace"], [(tb.objectName(), tb.windowTitle()) for tb in bars], scanruler_active())
    for tb in bars:
        _watch(tb)
        want = plan.get(tb.objectName())
        if want is not None and tb.isVisible() != want:
            tb.setVisible(want)
    _watch_workbench(mw)


def _apply_later(mw):
    from PySide import QtCore

    for ms in REAPPLY_MS:
        QtCore.QTimer.singleShot(ms, lambda m=mw: _safe_apply(m))


def _safe_apply(mw):
    try:
        apply_toolbars(mw)
    except RuntimeError:  # the window is going away
        pass


def _watch(tb):
    if tb.property("scanruler_watched"):
        return
    tb.setProperty("scanruler_watched", True)

    def changed(visible, tb=tb):
        if rehide(tb.objectName(), tb.windowTitle(), visible, _state["workspace"], scanruler_active()):
            from PySide import QtCore

            QtCore.QTimer.singleShot(0, lambda: _safe_hide(tb))

    tb.visibilityChanged.connect(changed)


def _safe_hide(tb):
    try:
        if rehide(tb.objectName(), tb.windowTitle(), tb.isVisible(), _state["workspace"], scanruler_active()):
            tb.setVisible(False)
    except RuntimeError:  # deleted
        pass


def _watch_workbench(mw):
    """Re-apply after FreeCAD (re)activates a workbench: its toolbar setup
    runs after the workbench's own Activated."""
    if mw.property("scanruler_wb_watched"):
        return
    mw.setProperty("scanruler_wb_watched", True)
    from PySide import QtCore

    def activated(name=None):
        if name in (None, WORKBENCH_NAME):
            _apply_later(mw)

    try:
        mw.workbenchActivated.connect(activated)
    except AttributeError:  # the signal is Gui::MainWindow's, not on the QMainWindow wrapper
        try:
            QtCore.QObject.connect(mw, QtCore.SIGNAL("workbenchActivated(QString)"), activated)
        except Exception:  # noqa: BLE001 — the timers and visibilityChanged still hold the switch
            pass


TOOLBAR_PREFS = "User parameter:BaseApp/MainWindow/Toolbars"


def _remember_toolbars(ws):
    """FreeCAD's ToolBarManager puts each toolbar back as its parameter
    under BaseApp/MainWindow/Toolbars says, 100 ms after any of them
    changes (and a workbench switch saves them all): hidden only by Qt, the
    other workspaces' toolbars came straight back. So the switch is written
    there too, and FreeCAD's own restore shows what the switch shows."""
    try:
        import FreeCAD

        p = FreeCAD.ParamGet(TOOLBAR_PREFS)
        for name, owner in _toolbar_owners().items():
            p.SetBool(name, owner == ws)
    except Exception:  # noqa: BLE001 — no FreeCAD (tests) or no parameter: Qt's hide still stands
        pass


def _actions(name):
    try:
        cmd = _gui().Command.get(name)
        a = cmd.getAction() if cmd else []
        return a if isinstance(a, list) else [a]
    except Exception:  # an older FreeCAD without Command.get: only the look is lost
        return []


def _restyle_switcher(mw, QtWidgets):
    """The active workspace's key shows its caps label beside the icon, the
    others only their icon, as the original's tab strip does."""
    from PySide import QtCore

    tb = mw.findChild(QtWidgets.QToolBar, W.WORKSPACE_TOOLBAR)
    for w in W.WORKSPACES:
        on = w["id"] == _state["workspace"]
        for a in _actions(w["command"]):
            a.setCheckable(True)
            a.setChecked(on)
            # The original's tab strip sets its labels in caps (styles.css
            # .modeswitch): kept for the open workspace's key, its look.
            label = W.title_case(w["label"])
            a.setIconText(label.upper() if on else label)
            btn = tb.widgetForAction(a) if tb is not None else None
            if btn is not None:
                btn.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon if on else QtCore.Qt.ToolButtonIconOnly)


# --- command classes ---------------------------------------------------------

class _Base:
    spec = None

    def GetResources(self):
        s = self.spec
        return {"Pixmap": icon_path(s["icon"]), "MenuText": W.title_case(s["label"]), "ToolTip": W.sentence(s["tip"])}

    def IsActive(self):
        return True


class WorkspaceCommand(_Base):
    def __init__(self, ws):
        self.spec = W.workspace(ws)
        self.ws = ws

    def GetResources(self):
        r = super().GetResources()
        r["Checkable"] = self.ws == _state["workspace"]
        return r

    def Activated(self, checked=None):
        switch_workspace(self.ws)


class KeyCommand(_Base):
    """A panel key: runs its tool through the runner, or opens its box."""

    def __init__(self, spec):
        self.spec = spec

    def IsActive(self):
        # Reverse engineer's keys wait for its own engine (tool None).
        return self.spec["tool"] is not None or not self.spec["key"].startswith("reverse:")

    def Activated(self, checked=None):
        s = self.spec
        ws = _owner(s["command"])
        if ws and ws != _state["workspace"]:
            switch_workspace(ws)
        if ws in SCAN_WORKSPACES and scan_is_open() is False:
            _tell(NEED_SCAN)
            if s["run"]:
                return None
        if s["run"]:
            res = _hooks["runner"](s["tool"], dict(s["args"]))
            report(W.title_case(s["label"]), res)
            return res
        return _to_panel(s["key"], dict(s["args"]))


class ViewCommand(_Base):
    """A view bar switch: checkable, as the original's pressed keys."""

    def __init__(self, spec):
        self.spec = spec

    def GetResources(self):
        r = super().GetResources()
        r["Checkable"] = bool(_state["view"].get(self.spec["key"], self.spec["key"] in _VIEW_ON))
        return r

    def IsActive(self):
        ws = self.spec.get("ws")  # a group shows in its workspaces; its menu follows it
        return ws is None or _state["workspace"] in ws

    def Activated(self, checked=None):
        on = bool(checked) if checked is not None else not _state["view"].get(self.spec["key"], False)
        native = self.spec.get("native")
        if native == CLIP_COMMAND:
            on = toggle_section()
            for a in _actions(self.spec["command"]):
                a.setChecked(on)
        elif native:
            try:
                _gui().runCommand(native)
            except Exception as e:  # noqa: BLE001 — FreeCAD's command; say why it did not run
                _say(f"ScanRuler: {native}: {e}")
        _state["view"][self.spec["key"]] = on
        return _to_panel("view", self.spec["key"], on)


# --- Section view: FreeCAD's clipping plane, toggled -----------------------------
# Std_ToggleClipPlane only opens FreeCAD's Clipping dialog (a dock named
# "Clipping" in the left dock area); pressed again it does nothing, and the
# new dock made the main window taller each time. So the key looks for that
# dock: a visible one is closed through its dialog's reject() (which removes
# the clip planes and deletes the dock, as its own Close button does), else
# the command opens one. The window's size is taken before and put back
# after FreeCAD's layout has settled (KEEP_SIZE_MS); if the window still
# cannot shrink, the Clipping dock is tabbed onto the dock it stacked under,
# in the same dock area, so their minimum heights stop adding up.

CLIP_COMMAND = "Std_ToggleClipPlane"
CLIP_DOCK = "Clipping"
KEEP_SIZE_MS = (0, 150, 400)


def section_action(docks):
    """"close" when one of the (object name, visible) docks is a visible
    Clipping dock, else "open"."""
    return "close" if any(n == CLIP_DOCK and v for n, v in docks) else "open"


def size_to_restore(before, after, maximized):
    """The (width, height) to put the window back to, or None: none when it
    is maximised or full screen (the screen sets its size) or unchanged."""
    if maximized or before is None or tuple(before) == tuple(after):
        return None
    return tuple(before)


def toggle_section():
    """Open or close FreeCAD's clipping plane; True when it is now open."""
    try:
        from PySide import QtWidgets

        mw = _gui().getMainWindow()
    except ImportError:  # no window: the command alone
        try:
            _gui().runCommand(CLIP_COMMAND)
        except Exception as e:  # noqa: BLE001
            _say(f"ScanRuler: {CLIP_COMMAND}: {e}")
        return True
    docks = [d for d in mw.findChildren(QtWidgets.QDockWidget) if d.objectName() == CLIP_DOCK]
    action = section_action([(d.objectName(), d.isVisible()) for d in docks])
    before = (mw.width(), mw.height())
    maxed = mw.isMaximized() or mw.isFullScreen()
    if action == "close":
        for d in docks:
            if d.isVisible():
                w = d.widget()
                if w is not None and hasattr(w, "reject"):
                    w.reject()  # Gui::Dialog::Clipping::reject: planes off, dock deleted
                else:
                    d.close()
                    d.deleteLater()
    else:
        try:
            _gui().runCommand(CLIP_COMMAND)
        except Exception as e:  # noqa: BLE001
            _say(f"ScanRuler: {CLIP_COMMAND}: {e}")
            return False
    _keep_size(mw, before, maxed)
    return action == "open"


def _keep_size(mw, before, maxed):
    from PySide import QtCore

    for i, ms in enumerate(KEEP_SIZE_MS):
        QtCore.QTimer.singleShot(ms, lambda m=mw, last=i == len(KEEP_SIZE_MS) - 1: _restore_size(m, before, maxed, last))


def _restore_size(mw, before, maxed, last):
    try:
        want = size_to_restore(before, (mw.width(), mw.height()), maxed)
        if want is None:
            return
        mw.resize(*want)
        if last and size_to_restore(before, (mw.width(), mw.height()), maxed) is not None:
            _tab_clipping(mw)
            mw.resize(*want)
    except RuntimeError:  # the window is going away
        pass


def _tab_clipping(mw):
    """Tab the Clipping dock onto another visible dock of its own area."""
    from PySide import QtWidgets

    clip = next((d for d in mw.findChildren(QtWidgets.QDockWidget) if d.objectName() == CLIP_DOCK and d.isVisible()), None)
    if clip is None or clip.isFloating():
        return
    area = mw.dockWidgetArea(clip)
    for d in mw.findChildren(QtWidgets.QDockWidget):
        if d is not clip and d.isVisible() and not d.isFloating() and mw.dockWidgetArea(d) == area:
            mw.tabifyDockWidget(d, clip)
            clip.raise_()
            return


class ViewGroupCommand:
    """A view bar group with its ▴ menu (FreeCAD's drop-down button)."""

    def __init__(self, group):
        self.group = group

    def GetCommands(self):
        return tuple([self.group["command"]] + [m["command"] for m in self.group["menu"]])

    def GetDefaultCommand(self):
        return 0

    def GetResources(self):
        g = self.group
        return {"Pixmap": icon_path(g["icon"]), "MenuText": W.title_case(g["label"]) + " Options",
                "ToolTip": group_tip(g), "DropDownMenu": True}

    def IsActive(self):
        return True


def group_name(g):
    return g["command"] + "Group"


def group_tip(g):
    """The ▴ button's own tooltip, not its first switch's: what its menu holds."""
    return W.sentence(f"{W.title_case(g['label'])} display options: " + ", ".join(m["label"].lower() for m in g["menu"]))


class NewCommand(_Base):
    spec = W.PROJECT[0]

    def Activated(self, checked=None):
        import FreeCAD

        FreeCAD.newDocument()
        _hooks["ui"]("new")


class SaveCommand(_Base):
    spec = W.PROJECT[1]

    def Activated(self, checked=None):
        _hooks["ui"]("save")  # the panel writes ScanRuler's state into the document first
        _gui().runCommand("Std_Save")


class LoadCommand(_Base):
    spec = W.PROJECT[2]

    def Activated(self, checked=None):
        from PySide import QtWidgets

        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            _gui().getMainWindow(), "Open Project", "",
            "Projects (*.FCStd *.scanruler);;FreeCAD document (*.FCStd);;ScanRuler project (*.scanruler)")
        if path:
            return load(path)


def load(path):
    """A .FCStd opens as the FreeCAD document it is; a .scanruler project, so
    the original's users bring their work across, is read through the tools
    (project_import: the scan, elements and sections it can), and the panel
    is told what came across. Its Reverse engineer part opens in the
    document's container (reverse/doc.py)."""
    if path.lower().endswith(".fcstd"):
        import FreeCAD

        return FreeCAD.openDocument(path)
    if path.lower().endswith(".scanruler"):
        from .errors import ToolError
        from .project_import import load as load_project

        try:
            got = load_project(path, _hooks["runner"])
        except ToolError as e:
            _say(f"ScanRuler: {e.message}")
            return None
        left = got["notLoaded"] + [f"{x['tool']}: {x['message']}" for x in got["errors"]]
        _say(f"ScanRuler: {got['project']} — scan {got['scan'] or 'not opened'}, {got['elements']} elements, "
             f"{got['sections']} sections" + (f", {got['reverse']['features']} Reverse engineer features" if got.get("reverse") else "") + "."
             + (" Not loaded: " + " ".join(left) if left else ""))
        _hooks["ui"]("load-scanruler", got)
        return got
    raise ValueError(f"{os.path.basename(path)}: Load takes {' or '.join(W.LOAD_SUFFIXES)}.")


SCAN_FILTER = ("Scans (*.stl *.ply *.obj *.off *.3mf *.glb *.gltf *.dae *.wrl *.3ds);;"
               "STL (*.stl);;PLY (*.ply);;OBJ (*.obj);;OFF (*.off);;3MF (*.3mf);;All files (*)")


class OpenScanCommand(_Base):
    spec = W.OPEN_SCAN

    def Activated(self, checked=None):
        from PySide import QtWidgets

        path, _ = QtWidgets.QFileDialog.getOpenFileName(_gui().getMainWindow(), "Open Scan", "", SCAN_FILTER)
        if path:
            return open_scan(path)


def open_scan(path):
    """scan_open through the runner, said in the status bar, and the page
    of the workspace in front brought up to measure it."""
    _to_panel("workspace", _state["workspace"])
    res = _hooks["runner"]("scan_open", {"path": path})
    if isinstance(res, tuple) and len(res) == 2 and res[0]:
        _tell(f"ScanRuler: {os.path.basename(path)} opened.")
    else:
        report("Open Scan", res)
    return res


class SettingsCommand(_Base):
    """ScanRuler's own settings dialog (settings.py). Not FreeCAD's
    Preferences: showPreferences("ScanRuler") opened its General page, as
    no page of that group is registered."""

    spec = W.SETTINGS

    def Activated(self, checked=None):
        from . import settings

        return settings.show(_main_window())


class SnapshotCommand(KeyCommand):
    def __init__(self):
        super().__init__(W.SNAPSHOT)

    def Activated(self, checked=None):
        return _hooks["ui"]("snapshot")


def about_text():
    """The About box's rich text: version, licence, and whose work it is."""
    import scanrulerfc

    return ABOUT_TEXT.format(version=scanrulerfc.VERSION)


ABOUT_TEXT = (
    "<p><b>ScanRuler for FreeCAD</b> {version}</p>"
    "<p>ScanRuler by Stefan Hermann (CNC Kitchen), ported to FreeCAD.</p>"
    "<p>Original: <a href='https://github.com/CNCKitchen/ScanRuler'>github.com/CNCKitchen/ScanRuler</a> · "
    "<a href='https://www.cnckitchen.com'>cnckitchen.com</a></p>"
    "<p>Licence: AGPL-3.0-only. The ScanRuler and CNC Kitchen names are used only to say where this "
    "work comes from; CNC Kitchen does not endorse this port (see NOTICE.md).</p>"
    "<p>Files never leave your computer.</p>"
)


class AboutCommand(_Base):
    spec = W.ABOUT

    def Activated(self, checked=None):
        from PySide import QtCore, QtWidgets

        box = QtWidgets.QMessageBox(_main_window())
        box.setWindowTitle("About ScanRuler")
        box.setTextFormat(QtCore.Qt.RichText)
        box.setText(about_text())
        box.setStandardButtons(QtWidgets.QMessageBox.Ok)
        try:
            from PySide import QtGui

            box.setIconPixmap(QtGui.QIcon(icon_path("ScanRulerWorkbench")).pixmap(64, 64))
        except Exception:  # noqa: BLE001 — the box shows without its picture
            pass
        return box.exec()


def plain_menu_roles(names=None):
    """No macOS menu role on ScanRuler's items: Qt's text heuristic moves
    an item called "About …" or "Settings…" into the application menu,
    where FreeCAD's own About and Preferences answer it. Set each action's
    role to NoRole (FreeCAD does this itself only in newer builds)."""
    try:
        from PySide import QtGui, QtWidgets

        Action = getattr(QtGui, "QAction", None) or QtWidgets.QAction  # Qt6 moved it to QtGui
        no_role = getattr(getattr(Action, "MenuRole", Action), "NoRole")
    except (ImportError, AttributeError):
        return 0
    n = 0
    for name in names or (W.SETTINGS["command"], W.ABOUT["command"], W.OPEN_SCAN["command"]) + tuple(p["command"] for p in W.PROJECT):
        for a in _actions(name):
            try:
                a.setMenuRole(no_role)
                n += 1
            except Exception:  # noqa: BLE001
                pass
    return n


# --- the registry ------------------------------------------------------------

_VIEW_ON = {"ViewScan", "ViewElements", "ViewReference", "ViewBodies", "ViewScanBackfaces", "ViewScanColours",
            "ViewRefBackfaces", "ViewLabels", "ViewColourPlot"}  # the original's defaults (`normal: true`, shown)
_OWNER = {k["command"]: wid for wid in W.TOOLBARS for k in W.keys(wid)}


def _owner(cmd):
    return _OWNER.get(cmd)


def build():
    """Every command object by name. Pure: no FreeCAD needed."""
    out = {}
    for w in W.WORKSPACES:
        out[w["command"]] = WorkspaceCommand(w["id"])
    for k in W.keys():
        out.setdefault(k["command"], KeyCommand(k))
    for g in W.VIEW_BAR:
        out[g["command"]] = ViewCommand(g)
        for m in g["menu"]:
            out[m["command"]] = ViewCommand(m)
        if g["menu"]:
            out[group_name(g)] = ViewGroupCommand(g)
    out.update({"ScanRuler_New": NewCommand(), "ScanRuler_Save": SaveCommand(), "ScanRuler_Load": LoadCommand(),
                "ScanRuler_OpenScan": OpenScanCommand(), "ScanRuler_Settings": SettingsCommand(), "ScanRuler_Snapshot": SnapshotCommand(),
                "ScanRuler_About": AboutCommand()})
    return out


_registered = {}


def register(gui=None, run=None, ui=None):
    """Add every command to FreeCAD (once). `run` and `ui` set the hooks."""
    if run is not None:
        set_runner(run)
    if ui is not None:
        set_ui(ui)
    gui = gui or _gui()
    for name, cmd in build().items():
        if name not in _registered:
            gui.addCommand(name, cmd)
            _registered[name] = cmd
    return dict(_registered)
