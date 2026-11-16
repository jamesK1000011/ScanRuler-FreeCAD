# SPDX-License-Identifier: AGPL-3.0-only
# Ported from ScanRuler by Stefan Hermann (CNC Kitchen),
# github.com/CNCKitchen/ScanRuler: the settings the original's gear key
# opens, as far as they are ScanRuler's own in FreeCAD. Its theme and mouse
# controls are FreeCAD's own preferences here.
#
# The settings are a page of FreeCAD's Preferences (Edit ▸ Preferences ▸
# ScanRuler), no dialog or command of ScanRuler's: register() adds
# PreferencePage at start. FIELDS is pure (the tests read it); the values
# are FreeCAD's parameters under BaseApp/Preferences/Mod/ScanRuler.

PARAM_ROOT = "User parameter:BaseApp/Preferences/Mod/ScanRuler"
TITLE = "ScanRuler"
GROUP = "ScanRuler"  # the Preferences dialog's group (its icon list)
FREECAD_NOTE = "Theme, mouse controls and units are FreeCAD's own, on its other pages."

# (group title, parameter group, parameter, default, check box label, tooltip)
FIELDS = (
    ("Snapshots", "Snapshot", "SaveBesideProject", True, "Save snapshots beside the project file",
     "Each snapshot is also saved as a PNG file in the folder of the saved FreeCAD document."),
)


def read(param_get=None):
    """{(group, name): value} as FreeCAD's parameters hold them now."""
    out = {}
    for _title, grp, name, default, _label, _tip in FIELDS:
        try:
            p = (param_get or _param_get())(f"{PARAM_ROOT}/{grp}")
            out[(grp, name)] = bool(p.GetBool(name, default))
        except Exception:  # noqa: BLE001 — no FreeCAD: the default
            out[(grp, name)] = default
    return out


def write(values, param_get=None):
    for (grp, name), value in values.items():
        (param_get or _param_get())(f"{PARAM_ROOT}/{grp}").SetBool(name, bool(value))


def _param_get():
    import FreeCAD

    return FreeCAD.ParamGet


class PreferencePage:
    """ScanRuler's page of FreeCAD's Preferences: FreeCAD makes it with a
    parent, shows `form`, and calls loadSettings and saveSettings."""

    def __init__(self, parent=None):
        from PySide import QtWidgets

        self.form = QtWidgets.QWidget(parent)
        self.form.setWindowTitle(TITLE)
        lay = QtWidgets.QVBoxLayout(self.form)
        self.boxes = {}
        groups = {}
        for title, grp, name, _default, label, tip in FIELDS:
            if title not in groups:
                gb = QtWidgets.QGroupBox(title)
                groups[title] = QtWidgets.QVBoxLayout(gb)
                lay.addWidget(gb)
            cb = QtWidgets.QCheckBox(label)
            cb.setToolTip(tip)
            groups[title].addWidget(cb)
            self.boxes[(grp, name)] = cb
        note = QtWidgets.QLabel(FREECAD_NOTE)
        note.setWordWrap(True)
        lay.addWidget(note)
        lay.addStretch(1)

    def loadSettings(self):
        for k, v in read().items():
            self.boxes[k].setChecked(v)

    def saveSettings(self):
        write({k: cb.isChecked() for k, cb in self.boxes.items()})
        _tell_snapshot_store()


def register(gui):
    """The page added to FreeCAD's Preferences, once per start. False where
    this FreeCAD cannot take a Python page."""
    add = getattr(gui, "addPreferencePage", None)
    if add is None:
        return False
    try:
        add(PreferencePage, GROUP)
    except Exception:  # noqa: BLE001 — the defaults hold without the page
        return False
    return True


def _tell_snapshot_store():
    """The snapshot store read its setting at start: tell it the new one."""
    from .snapshot import store

    store.STORE.save = read()[("Snapshot", "SaveBesideProject")]
