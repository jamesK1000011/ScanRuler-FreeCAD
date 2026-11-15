# SPDX-License-Identifier: AGPL-3.0-only
# Ported from ScanRuler by Stefan Hermann (CNC Kitchen),
# github.com/CNCKitchen/ScanRuler: the original's window — its workspace tabs,
# each workspace's keys, the project keys and the view bar — as a FreeCAD
# workbench (design section 1). InitGui.py adds it; it is built here so the
# tests can import it under stub FreeCAD modules.
#
# The original's tab strip becomes the "ScanRuler workspaces" toolbar, its
# per-workspace panels' key grids become toolbars of which only the active
# workspace's show, its top bar's New, Save and Load become the ScanRuler
# menu's project items (FreeCAD's own toolbars have undo, redo, New, Open and
# Save, so no second set stands beside them), and its floating view bar
# becomes the "ScanRuler View" toolbar in the bottom toolbar area: FreeCAD has
# no stable overlay API over the 3D view across 1.x (design 2.8). Names show
# as FreeCAD's design guide asks (workspaces.title_case).

from . import commands as C
from . import workspaces as W


def toolbars():
    """(object name, title, [commands]) for every toolbar, in the order
    Initialize appends them."""
    out = [(W.WORKSPACE_TOOLBAR, W.WORKSPACE_TOOLBAR, [w["command"] for w in W.WORKSPACES])]
    for wid, bars in W.TOOLBARS.items():
        for title, ks in bars:
            out.append((W.toolbar_name(wid, title), W.title_case(title), [k["command"] for k in ks]))
    view = [C.group_name(g) if g["menu"] else g["command"] for g in W.VIEW_BAR] + list(W.VIEW_TAIL)
    out.append((W.VIEW_TOOLBAR, W.VIEW_TOOLBAR, view))
    return out


def menus():
    """(menu path, [commands]) in order: Open Scan… and the project's New,
    Open and Save, Workspace ▸, one submenu per workspace, then Snapshot,
    Settings…, About ScanRuler."""
    out = [([W.WORKBENCH_MENU], [W.OPEN_SCAN["command"], "Separator"] + [p["command"] for p in W.PROJECT] + ["Separator"])]
    out.append(([W.WORKBENCH_MENU, "Workspace"], [w["command"] for w in W.WORKSPACES]))
    for w in W.WORKSPACES:
        cmds = []
        for _title, ks in W.TOOLBARS[w["id"]]:
            if cmds:
                cmds.append("Separator")
            cmds.extend(k["command"] for k in ks)
        out.append(([W.WORKBENCH_MENU, W.title_case(w["label"])], cmds))
    out.append(([W.WORKBENCH_MENU], ["Separator", W.SNAPSHOT["command"], W.SETTINGS["command"], W.ABOUT["command"]]))
    return out


PANEL_COMMAND = "ScanRuler_Panel"
PANEL_TOOLBAR = "ScanRuler Panel"


class PanelCommand:
    def GetResources(self):
        return {"Pixmap": C.icon_path("ScanRulerWorkbench"), "MenuText": "ScanRuler Panel",
                "ToolTip": "Show or hide ScanRuler's panel"}

    def IsActive(self):
        return True

    def Activated(self):
        from . import dock, layout

        layout.toggle_or(dock.open_panel)


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
            # Show or hide the panel (it slides out over the 3D view when
            # the panel layout is left-slide): its own bar after the
            # workspaces'; the view bar stays last.
            Gui.addCommand(PANEL_COMMAND, PanelCommand())
            for k, (name, _title, cmds) in enumerate(toolbars()):
                self.appendToolbar(name, cmds)
                if k == 0:
                    self.appendToolbar(PANEL_TOOLBAR, [PANEL_COMMAND])
            for path, cmds in menus():
                self.appendMenu(path, cmds)

        def Activated(self):
            C.plain_menu_roles()
            _bottom_view_bar(Gui)
            _own_panel(Gui)
            C.switch_workspace(C.current_workspace())

        def Deactivated(self):
            # The status strip is ScanRuler's: hidden in other workbenches.
            from . import statusbar

            statusbar.shown(False)

        def GetClassName(self):
            return "Gui::PythonWorkbench"

    return ScanRulerWorkbench


def _own_panel(Gui):
    """The ScanRuler dock where the panel layout puts it (beside Model and
    Tasks by default), alone or under Agent Link, and the status strip.
    Only an older Agent Link that hosts the page as a tab of its panel
    keeps it there."""
    import scanrulerfc

    from . import dock, statusbar

    if scanrulerfc._hosted and dock._hosted_tab():
        return

    try:
        mw = Gui.getMainWindow()
        statusbar.install(mw)
        statusbar.shown(True)
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
