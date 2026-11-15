# SPDX-License-Identifier: AGPL-3.0-only
# Ported from ScanRuler by Stefan Hermann (CNC Kitchen),
# github.com/CNCKitchen/ScanRuler: plugins/snapshot/ui/ShotButton.tsx,
# ui/ShotEditor.tsx and app/capture.ts.
#
# The shot card and the mark-up view, thin Qt over store.py and marks.py.
# A press of the camera key (or Alt+Shift+S) grabs one frame of FreeCAD's
# main window, panels included, and opens the card: a note, Mark up, Save
# PNG, Copy and Discard, with the original's words. Qt is imported only when
# something here is used, so the add-on loads headless.

import datetime as _dt
import os

from . import marks as MK
from .store import STORE, Shot, file_name

CREDIT = "ScanRuler by Stefan Hermann (CNC Kitchen), ported to FreeCAD"
SHORTCUT = "Alt+Shift+S"
BUTTON_TIP = "Screenshot FreeCAD (⌥⇧S / Alt+Shift+S)"
NOTE_PLACEHOLDER = "What to look at — “the Patent panel’s numerals are off”"
TOLD_HINT = "The agent is told about it with its next answer, and can look with snapshot_latest."
SAVE_LABEL = "Save shots beside the project"

_cls = {}
_open = {}


def _qt():
    for name in ("PySide", "PySide6", "PySide2"):
        try:
            mod = __import__(name, fromlist=["QtCore", "QtGui", "QtWidgets"])
            return mod.QtCore, mod.QtGui, mod.QtWidgets
        except Exception:
            continue
    raise ImportError("Qt is not available")


def marks_hint(shot):
    n = len(shot.marks)
    p = sum(1 for m in shot.marks if m.kind == "pin")
    return f"{n} mark{'' if n == 1 else 's'}, {p} pin{'' if p == 1 else 's'}" if n else ""


def card_aside(shot):
    t = shot.at.strftime("%H:%M:%S")
    return f"{shot.workspace} · {t}" if shot.workspace else t


def _png_of(image):
    QtCore, _QtGui, _W = _qt()
    buf = QtCore.QBuffer()
    buf.open(QtCore.QIODevice.WriteOnly)
    image.save(buf, "PNG")
    return bytes(buf.data())


def _doc_folder():
    try:
        import FreeCAD
        d = FreeCAD.ActiveDocument
        if d is not None and d.FileName:
            return os.path.dirname(d.FileName)
    except Exception:
        pass
    return None


def take_shot(store=STORE, workspace=None, window=None, show=True):
    """The person's press: grab the window, keep the shot, save it beside
    the project when that is on, and open its card. Never called by a tool."""
    _QtCore, _QtGui, QtW = _qt()
    if window is None:
        import FreeCADGui
        window = FreeCADGui.getMainWindow()
    pix = window.grab()
    img = pix.toImage()
    shot = Shot(_png_of(img), img.width(), img.height(), workspace, at=_dt.datetime.now().astimezone())
    store.add(shot)
    save_if_on(store, shot)
    if show:
        open_card(store, shot.id, parent=window)
    return shot


def save_if_on(store, shot):
    folder = _doc_folder()
    if store.save and folder:
        png, _marked = MK.composite(shot)
        try:
            return store.save_beside(shot, folder, png)
        except OSError:
            return None
    return None


def _classes():
    if _cls:
        return _cls
    QtCore, QtGui, QtW = _qt()

    class Canvas(QtW.QWidget):
        """The shot, fitted to the view, with the marks over it; the pointer
        draws through the MarkUp model in the shot's own pixels."""

        def __init__(self, shot, model, changed, parent=None):
            super().__init__(parent)
            self.shot, self.model, self.changed = shot, model, changed
            self.image = QtGui.QImage()
            self.image.loadFromData(shot.png)
            self.setMinimumSize(320, 200)
            self.setFocusPolicy(QtCore.Qt.StrongFocus)

        def _scale(self):
            return min(self.width() / max(1, self.shot.width), self.height() / max(1, self.shot.height), 1.0)

        def _at(self, e):
            s = self._scale()
            p = e.position() if hasattr(e, "position") else e.pos()
            return p.x() / s, p.y() / s

        def paintEvent(self, _e):
            s = self._scale()
            g = QtGui.QPainter(self)
            g.setRenderHint(QtGui.QPainter.Antialiasing)
            g.scale(s, s)
            g.drawImage(0, 0, self.image)
            MK.draw_marks(g, self.model.visible(), self.shot.width)
            g.end()

        def mousePressEvent(self, e):
            self.model.press(*self._at(e))
            self.changed()

        def mouseMoveEvent(self, e):
            self.model.move(*self._at(e))
            self.update()

        def mouseReleaseEvent(self, e):
            self.model.release(*self._at(e))
            self.changed()

        def keyPressEvent(self, e):
            ctrl = bool(e.modifiers() & (QtCore.Qt.ControlModifier | QtCore.Qt.MetaModifier))
            if self.model.key(e.text() or "", ctrl):
                self.changed()
            else:
                super().keyPressEvent(e)

    class MarkUpDialog(QtW.QDialog):
        def __init__(self, store, shot, parent=None):
            super().__init__(parent)
            self.store, self.shot = store, shot
            self.model = MK.MarkUp(shot.marks, shot.note)
            self.setWindowTitle("Mark up the screenshot")
            store.set_editing(shot.id)
            lay = QtW.QHBoxLayout(self)
            self.canvas = Canvas(shot, self.model, self.refresh, self)
            lay.addWidget(self.canvas, 1)
            side = QtW.QVBoxLayout()
            lay.addLayout(side)
            side.addWidget(QtW.QLabel("MARK UP"))
            row = QtW.QHBoxLayout()
            self.tool_buttons = {}
            for tid, label, key in MK.TOOLS:
                b = QtW.QPushButton(label)
                b.setCheckable(True)
                b.setToolTip(f"{label} ({key})")
                b.clicked.connect(lambda _c=False, t=tid: (self.model.set_tool(t), self.refresh()))
                row.addWidget(b)
                self.tool_buttons[tid] = b
            side.addLayout(row)
            crow = QtW.QHBoxLayout()
            for c in MK.COLOURS:
                b = QtW.QPushButton()
                b.setFixedSize(22, 22)
                b.setToolTip(c)
                b.setStyleSheet(f"background:{c}")
                b.clicked.connect(lambda _c=False, col=c: self.model.set_colour(col))
                crow.addWidget(b)
            self.undo = QtW.QPushButton("Undo")
            self.undo.setToolTip("Undo (⌘Z)")
            self.undo.clicked.connect(lambda: (self.model.undo(), self.refresh()))
            crow.addWidget(self.undo)
            side.addLayout(crow)
            self.pins = QtW.QVBoxLayout()
            side.addLayout(self.pins)
            side.addWidget(QtW.QLabel("NOTE"))
            self.note = QtW.QPlainTextEdit(shot.note)
            side.addWidget(self.note)
            brow = QtW.QHBoxLayout()
            done = QtW.QPushButton("Done")
            done.setDefault(True)
            done.clicked.connect(self.done_)
            cancel = QtW.QPushButton("Cancel")
            cancel.clicked.connect(self.reject)
            brow.addWidget(done)
            brow.addWidget(cancel)
            side.addLayout(brow)
            hint = QtW.QLabel(MK.DONE_HINT)
            hint.setWordWrap(True)
            side.addWidget(hint)
            side.addStretch(1)
            self.resize(1100, 700)
            self.refresh()

        def refresh(self):
            for t, b in self.tool_buttons.items():
                b.setChecked(t == self.model.tool)
            self.undo.setEnabled(bool(self.model.marks))
            while self.pins.count():
                w = self.pins.takeAt(0).widget()
                if w:
                    w.deleteLater()
            for p in self.model.pins():
                ed = QtW.QLineEdit(p.comment or "")
                ed.setPlaceholderText(f"Pin {p.n}")
                ed.textChanged.connect(lambda text, n=p.n: (self.model.comment(n, text), self.canvas.update()))
                self.pins.addWidget(ed)
            self.canvas.update()

        def done_(self):
            self.model.note = self.note.toPlainText().strip()
            self.model.done(self.store, self.shot.id)
            save_if_on(self.store, self.shot)
            self.accept()

        def reject(self):
            if self.store.editing == self.shot.id:
                self.store.set_editing(None)
            super().reject()

    class ShotCard(QtW.QDialog):
        """Non-modal card for the shot just taken."""

        def __init__(self, store, shot, parent=None):
            super().__init__(parent)
            self.store, self.shot = store, shot
            self.setWindowTitle("Screenshot")
            self.setModal(False)
            lay = QtW.QVBoxLayout(self)
            head = QtW.QHBoxLayout()
            head.addWidget(QtW.QLabel("Screenshot"))
            head.addStretch(1)
            head.addWidget(QtW.QLabel(card_aside(shot)))
            lay.addLayout(head)
            thumb = QtW.QPushButton()
            thumb.setToolTip("Mark it up")
            img = QtGui.QImage()
            img.loadFromData(shot.png)
            pm = QtGui.QPixmap.fromImage(img).scaledToWidth(320, QtCore.Qt.SmoothTransformation)
            thumb.setIcon(QtGui.QIcon(pm))
            thumb.setIconSize(pm.size())
            thumb.clicked.connect(self.mark_up)
            lay.addWidget(thumb)
            self.marks = QtW.QLabel(marks_hint(shot))
            lay.addWidget(self.marks)
            self.note = QtW.QPlainTextEdit(shot.note)
            self.note.setPlaceholderText(NOTE_PLACEHOLDER)
            self.note.setFixedHeight(54)
            lay.addWidget(self.note)
            told = QtW.QLabel(TOLD_HINT)
            told.setWordWrap(True)
            lay.addWidget(told)
            self.saved = QtW.QLabel(f"Saved to {shot.path}" if shot.path else "")
            lay.addWidget(self.saved)
            save = QtW.QCheckBox(SAVE_LABEL)
            save.setChecked(store.save)
            save.toggled.connect(store.set_save)
            lay.addWidget(save)
            row = QtW.QHBoxLayout()
            for label, fn in (("Mark up", self.mark_up), ("Save PNG", self.save_png), ("Copy", self.copy), ("Discard", self.discard)):
                b = QtW.QPushButton(label)
                b.clicked.connect(fn)
                row.addWidget(b)
                if label == "Copy":
                    self.copy_button = b
            lay.addLayout(row)
            credit = QtW.QLabel(CREDIT)
            credit.setStyleSheet("color: palette(mid); font-size: 10px")
            lay.addWidget(credit)

        def _keep_note(self):
            text = self.note.toPlainText().strip()
            if text != self.shot.note:
                self.store.note(self.shot.id, text)

        def closeEvent(self, e):
            self._keep_note()
            _open.pop(self.shot.id, None)
            super().closeEvent(e)

        def mark_up(self):
            self._keep_note()
            dlg = MarkUpDialog(self.store, self.shot, self)
            (getattr(dlg, "exec", None) or dlg.exec_)()
            self.marks.setText(marks_hint(self.shot))
            self.note.setPlainText(self.shot.note)
            if self.shot.path:
                self.saved.setText(f"Saved to {self.shot.path}")

        def save_png(self):
            png, marked = MK.composite(self.shot)
            path, _f = QtW.QFileDialog.getSaveFileName(self, "Save PNG", file_name(self.shot, marked), "PNG (*.png)")
            if path:
                with open(path, "wb") as f:
                    f.write(png)

        def copy(self):
            png, _m = MK.composite(self.shot)
            img = QtGui.QImage()
            ok = img.loadFromData(png)
            if ok:
                QtW.QApplication.clipboard().setImage(img)
            self.copy_button.setText("Copied" if ok else "Copy failed")
            QtCore.QTimer.singleShot(1500, lambda: self.copy_button.setText("Copy"))

        def discard(self):
            self.store.remove(self.shot.id)
            _open.pop(self.shot.id, None)
            self.close()

    _cls.update(Canvas=Canvas, MarkUpDialog=MarkUpDialog, ShotCard=ShotCard)
    return _cls


def open_card(store=STORE, shot_id=None, parent=None):
    """The card for a shot (the newest by default): right-click on the
    camera key reopens it."""
    shot = store.get(shot_id) if shot_id else store.latest()
    if shot is None:
        return None
    card = _open.get(shot.id)
    if card is None:
        card = _classes()["ShotCard"](store, shot, parent)
        _open[shot.id] = card
    card.show()
    card.raise_()
    return card


def install(window=None, store=STORE, workspace=lambda: None):
    """Alt+Shift+S on the main window takes a shot."""
    _QtCore, QtGui, QtW = _qt()
    if window is None:
        import FreeCADGui
        window = FreeCADGui.getMainWindow()
    QShortcut = getattr(QtGui, "QShortcut", None) or QtW.QShortcut
    sc = QShortcut(QtGui.QKeySequence(SHORTCUT), window)
    sc.activated.connect(lambda: take_shot(store, workspace(), window))
    return sc
