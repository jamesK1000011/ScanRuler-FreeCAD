# SPDX-License-Identifier: AGPL-3.0-only
# Ported from ScanRuler by Stefan Hermann (CNC Kitchen),
# github.com/CNCKitchen/ScanRuler: src/ui/StatusStrip.tsx.
#
# The status strip (design 2.9) as permanent widgets of FreeCAD's status
# bar: "● READY" / "● WORKING n%" / "● ERROR" on the left, "ELEMENTS n · DIM
# n" beside it (with "of m" while some elements have no fit), and the credit
# "ScanRuler · CNC Kitchen" on the right, where the original's "§ IMPRINT"
# sat. The last message goes through statusBar().showMessage(). `model()` is
# pure; `install()` is the thin Qt part.

from . import workspaces as W

LAMP = "●"
COLOURS = {"READY": "#2e7d46", "WORKING": W.ACCENT, "ERROR": "#b3361c"}


def state_text(busy=False, error=None, percent=None):
    state = "ERROR" if error else "WORKING" if busy else "READY"
    tail = f" {percent}%" if state == "WORKING" and percent is not None else ""
    return state, f"{LAMP} {state}{tail}"


def counts_text(st):
    """None while there are no elements, as the original hides it."""
    elements = st.get("elements", [])
    if not elements:
        return None
    done = sum(1 for e in elements if e.get("fit"))
    of = f" of {len(elements)}" if done != len(elements) else ""
    return f"ELEMENTS {done}{of} · DIM {len(st.get('dimensions', []))}"


def model(st, busy=False, error=None, percent=None, message=None):
    state, text = state_text(busy, error, percent)
    return {"state": state, "state_text": text, "colour": COLOURS[state], "counts": counts_text(st),
            "credit": W.STATUS_CREDIT, "message": f"⚠ {error}" if error else message}


class StatusBar:
    """The three permanent widgets, made once per main window."""

    def __init__(self, bar):
        from PySide import QtWidgets

        self.bar = bar
        self.state = QtWidgets.QLabel()
        self.counts = QtWidgets.QLabel()
        self.credit = QtWidgets.QLabel(W.STATUS_CREDIT)
        self.credit.setToolTip(W.CREDIT)
        bar.insertPermanentWidget(0, self.state)
        bar.insertPermanentWidget(1, self.counts)
        bar.addPermanentWidget(self.credit)
        self._last = None

    def show(self, m):
        if m == self._last:
            return
        self._last = m
        self.state.setText("<span style='color:%s'>%s</span>%s" % (m["colour"], LAMP, m["state_text"][len(LAMP):]))
        self.counts.setText(m["counts"] or "")
        self.counts.setVisible(bool(m["counts"]))
        if m["message"]:
            self.bar.showMessage(m["message"])

    def remove(self):
        for w in (self.state, self.counts, self.credit):
            self.bar.removeWidget(w)
            w.deleteLater()


_installed = {}


def install(mw=None):
    """The status widgets on FreeCAD's main window (once)."""
    if mw is None:
        import FreeCADGui

        mw = FreeCADGui.getMainWindow()
    key = id(mw)
    if key not in _installed:
        _installed[key] = StatusBar(mw.statusBar())
    return _installed[key]
