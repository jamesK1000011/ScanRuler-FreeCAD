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
    _say(f"ScanRuler: the panel is not open ({key}).")
    return None


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


def _gui():
    import FreeCADGui

    return FreeCADGui


# --- workspace switching -----------------------------------------------------

def toolbar_names(ws):
    return [W.toolbar_name(ws, title) for title, _ in W.TOOLBARS[ws]]


def switch_workspace(ws):
    """Show the workspace's toolbars and hide the others', check its key,
    show its label beside its icon, and turn the panel's page."""
    W.workspace(ws)  # KeyError on an unknown id
    _state["workspace"] = ws
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
    _hooks["ui"]("workspace", ws)
    return ws


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
            a.setIconText(w["label"].upper() if on else w["label"])
            btn = tb.widgetForAction(a) if tb is not None else None
            if btn is not None:
                btn.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon if on else QtCore.Qt.ToolButtonIconOnly)


# --- command classes ---------------------------------------------------------

class _Base:
    spec = None

    def GetResources(self):
        s = self.spec
        return {"Pixmap": icon_path(s["icon"]), "MenuText": s["label"], "ToolTip": s["tip"]}

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
        if s["run"]:
            return _hooks["runner"](s["tool"], dict(s["args"]))
        return _hooks["ui"](s["key"], dict(s["args"]))


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
        return _hooks["ui"]("view", self.spec["key"], on)


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
        return {"Pixmap": icon_path(g["icon"]), "MenuText": g["label"], "ToolTip": g["tip"], "DropDownMenu": True}

    def IsActive(self):
        return True


def group_name(g):
    return g["command"] + "Group"


class NewCommand(_Base):
    spec = W.PROJECT[2]

    def Activated(self, checked=None):
        import FreeCAD

        FreeCAD.newDocument()
        _hooks["ui"]("new")


class SaveCommand(_Base):
    spec = W.PROJECT[3]

    def Activated(self, checked=None):
        _hooks["ui"]("save")  # the panel writes ScanRuler's state into the document first
        _gui().runCommand("Std_Save")


class LoadCommand(_Base):
    spec = W.PROJECT[4]

    def Activated(self, checked=None):
        from PySide import QtWidgets

        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            _gui().getMainWindow(), "Load", "",
            "Projects (*.FCStd *.scanruler);;FreeCAD document (*.FCStd);;ScanRuler project (*.scanruler)")
        if path:
            return load(path)


def load(path):
    """A .FCStd opens as the FreeCAD document it is; a .scanruler project, so
    the original's users bring their work across, is read through the tools
    (project_import: the scan, elements and sections it can), and the panel
    is told what came across."""
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
             f"{got['sections']} sections." + (" Not loaded: " + " ".join(left) if left else ""))
        _hooks["ui"]("load-scanruler", got)
        return got
    raise ValueError(f"{os.path.basename(path)}: Load takes {' or '.join(W.LOAD_SUFFIXES)}.")


class SettingsCommand(_Base):
    spec = W.SETTINGS

    def Activated(self, checked=None):
        try:
            _gui().showPreferences("ScanRuler")
        except Exception:  # the page is not registered yet: open Preferences where they are
            _gui().showPreferences()


class SnapshotCommand(KeyCommand):
    def __init__(self):
        super().__init__(W.SNAPSHOT)

    def Activated(self, checked=None):
        return _hooks["ui"]("snapshot")


ABOUT_TEXT = (
    "<p><b>ScanRuler for FreeCAD</b></p>"
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
        from PySide import QtWidgets

        QtWidgets.QMessageBox.about(_gui().getMainWindow(), "About ScanRuler", ABOUT_TEXT)


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
                "ScanRuler_Settings": SettingsCommand(), "ScanRuler_Snapshot": SnapshotCommand(),
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
