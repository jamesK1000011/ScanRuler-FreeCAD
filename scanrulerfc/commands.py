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

        for wid in W.TOOLBARS:
            for name in toolbar_names(wid):
                tb = mw.findChild(QtWidgets.QToolBar, name)
                if tb is not None:
                    tb.setVisible(wid == ws)
        _restyle_switcher(mw, QtWidgets)
    except ImportError:
        pass
    _to_panel("workspace", ws)
    return ws


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
        for wid in W.TOOLBARS:
            for name in toolbar_names(wid):
                p.SetBool(name, wid == ws)
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
        _state["view"][self.spec["key"]] = on
        native = self.spec.get("native")
        if native:
            try:
                _gui().runCommand(native)
            except Exception as e:  # the clipping plane is FreeCAD's; say why it did not open
                _say(f"ScanRuler: {native}: {e}")
        return _to_panel("view", self.spec["key"], on)


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
