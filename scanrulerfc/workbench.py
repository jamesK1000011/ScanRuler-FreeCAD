# SPDX-License-Identifier: AGPL-3.0-only
# Ported from ScanRuler by Stefan Hermann (CNC Kitchen),
# github.com/CNCKitchen/ScanRuler: the original's window — its workspace tabs,
# each workspace's keys, the project keys and the view bar — as a FreeCAD
# workbench (design section 1). InitGui.py adds it; it is built here so the
# tests can import it under stub FreeCAD modules.
#
# The original's tab strip becomes the "ScanRuler workspaces" toolbar, its
# per-workspace panels' key grids become toolbars of which only the active
# workspace's show, its top bar's undo, redo, New, Save and Load become the
# "ScanRuler project" toolbar, and its floating view bar becomes the
# "ScanRuler view" toolbar in the bottom toolbar area: FreeCAD has no stable
# overlay API over the 3D view across 1.x (design 2.8).

from . import commands as C
from . import workspaces as W


def toolbars():
    """(object name, title, [commands]) for every toolbar, in the order
    Initialize appends them."""
    out = [(W.WORKSPACE_TOOLBAR, W.WORKSPACE_TOOLBAR, [w["command"] for w in W.WORKSPACES])]
    out.append((W.PROJECT_TOOLBAR, W.PROJECT_TOOLBAR, [p["command"] for p in W.PROJECT]))
    for wid, bars in W.TOOLBARS.items():
        for title, ks in bars:
            out.append((W.toolbar_name(wid, title), title, [k["command"] for k in ks]))
    view = [C.group_name(g) if g["menu"] else g["command"] for g in W.VIEW_BAR] + list(W.VIEW_TAIL)
    out.append((W.VIEW_TOOLBAR, W.VIEW_TOOLBAR, view))
    return out


def menus():
    """(menu path, [commands]) in order: Workspace ▸, one submenu per
    workspace, then Snapshot, Settings…, About ScanRuler."""
    out = [([W.WORKBENCH_MENU, "Workspace"], [w["command"] for w in W.WORKSPACES])]
    for w in W.WORKSPACES:
        cmds = []
        for _title, ks in W.TOOLBARS[w["id"]]:
            if cmds:
                cmds.append("Separator")
            cmds.extend(k["command"] for k in ks)
        out.append(([W.WORKBENCH_MENU, w["label"]], cmds))
    out.append(([W.WORKBENCH_MENU], ["Separator", W.SNAPSHOT["command"], W.SETTINGS["command"], W.ABOUT["command"]]))
    return out


def make_class(Gui):
    """ScanRulerWorkbench on this FreeCADGui's Workbench base."""

    class ScanRulerWorkbench(Gui.Workbench):
        MenuText = W.WORKBENCH_MENU
        ToolTip = W.WORKBENCH_TIP
        Icon = C.icon_path("ScanRulerWorkbench")

        def Initialize(self):
            # Its runner set at registration: under Agent Link the hosted
            # family through panel._call, alone this add-on's handlers
            # (runner.gui chooses at each call).
            from . import runner

            C.register(Gui, run=runner.gui())
            # appendToolbar takes the title as the toolbar's object name too:
            # the per-workspace ones carry their workspace in it, as
            # "Create element" is in both Measure workspaces.
            for name, _title, cmds in toolbars():
                self.appendToolbar(name, cmds)
            for path, cmds in menus():
                self.appendMenu(path, cmds)

        def Activated(self):
            _bottom_view_bar(Gui)
            _own_panel(Gui)
            C.switch_workspace(C.current_workspace())

        def Deactivated(self):
            pass

        def GetClassName(self):
            return "Gui::PythonWorkbench"

    return ScanRulerWorkbench


def _own_panel(Gui):
    """Alone, the ScanRuler dock beside the Combo View and the status strip;
    under Agent Link the dock is its panel's ScanRuler tab instead."""
    import scanrulerfc

    if scanrulerfc._hosted:
        return
    from . import dock, statusbar

    try:
        mw = Gui.getMainWindow()
        statusbar.install(mw)
        dock.show_dock(mw)
    except ImportError:  # no window (FreeCADCmd, tests): nothing to show
        pass


def _bottom_view_bar(Gui):
    try:
        from PySide import QtCore, QtWidgets

        mw = Gui.getMainWindow()
        tb = mw.findChild(QtWidgets.QToolBar, W.VIEW_TOOLBAR)
        if tb is not None and mw.toolBarArea(tb) != QtCore.Qt.BottomToolBarArea:
            mw.addToolBar(QtCore.Qt.BottomToolBarArea, tb)
    except ImportError:
        pass


def add(Gui=None):
    """Add the workbench to FreeCAD; what InitGui.py calls."""
    if Gui is None:
        import FreeCADGui as Gui
    cls = make_class(Gui)
    Gui.addWorkbench(cls())
    return cls
