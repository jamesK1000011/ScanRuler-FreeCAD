# SPDX-License-Identifier: AGPL-3.0-only
# Ported from ScanRuler by Stefan Hermann (CNC Kitchen),
# github.com/CNCKitchen/ScanRuler: the settings the original's gear key
# opens, as far as they are ScanRuler's own in FreeCAD. Its theme and mouse
# controls are FreeCAD's own preferences here, so the dialog points there.
#
# FIELDS is pure (the tests read it); show() is the thin Qt dialog that
# ScanRuler_Settings opens, its values in FreeCAD's parameters under
# BaseApp/Preferences/Mod/ScanRuler.

PARAM_ROOT = "User parameter:BaseApp/Preferences/Mod/ScanRuler"
TITLE = "ScanRuler Settings"
FREECAD_NOTE = "Theme, mouse controls and units are FreeCAD's own: Edit ▸ Preferences."

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


def show(parent=None):
    """The dialog; OK writes the values. Returns True when OK was pressed."""
    from PySide import QtWidgets

    dlg = QtWidgets.QDialog(parent)
    dlg.setWindowTitle(TITLE)
    lay = QtWidgets.QVBoxLayout(dlg)
    now = read()
    boxes = {}
    groups = {}
    for title, grp, name, _default, label, tip in FIELDS:
        if title not in groups:
            gb = QtWidgets.QGroupBox(title)
            groups[title] = QtWidgets.QVBoxLayout(gb)
            lay.addWidget(gb)
        cb = QtWidgets.QCheckBox(label)
        cb.setToolTip(tip)
        cb.setChecked(now[(grp, name)])
        groups[title].addWidget(cb)
        boxes[(grp, name)] = cb
    note = QtWidgets.QLabel(FREECAD_NOTE)
    note.setWordWrap(True)
    lay.addWidget(note)
    buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
    buttons.accepted.connect(dlg.accept)
    buttons.rejected.connect(dlg.reject)
    lay.addWidget(buttons)
    if not dlg.exec():
        return False
    write({k: cb.isChecked() for k, cb in boxes.items()})
    _tell_snapshot_store()
    return True


def _tell_snapshot_store():
    """The snapshot store read its setting at start: tell it the new one."""
    from .snapshot import store

    store.STORE.save = read()[("Snapshot", "SaveBesideProject")]
