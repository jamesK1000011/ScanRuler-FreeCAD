# SPDX-License-Identifier: AGPL-3.0-only
# Ported from ScanRuler by Stefan Hermann (CNC Kitchen),
# github.com/CNCKitchen/ScanRuler: the parts every sidebar page of the
# original is built from (src/ui/InfoDot.tsx, NumberField.tsx, ModelSlot.tsx,
# ScaleControls.tsx, ProbeList.tsx, the kindrow/moderow/checkrow forms).
#
# The page-model pieces shared by the Surface Deviation, Wall Thickness,
# 2D Measure, Mesh Tools and Reverse engineer pages (design 2.0), in the
# shape pages/measure3d.py set: a section is a dict with its number, id,
# header and caps caption, its (i) title and text, rows, keys, fields and
# hint. Fields here also carry a kind — select, number (with unit and "auto"),
# check, toggle (a pair of exclusive keys) or slider — so the one thin Qt
# view below draws every page. Pure Python above the Qt part.

from .. import legend as L
from .. import workspaces as W

SCAN_DOT = "#8b9099"
REFERENCE_DOT = "#7f8ba0"
SCAN_FORMATS = "STL, PLY or OBJ · mm"
BAND_CHOICES = (5, 7, 9, 11, 15, 21)  # deviationStore.ts BAND_CHOICES
HINT_DROP = "Drop it anywhere in the window."
PINS_HINT = "Hover the part for a live reading; click to pin one where you need a number."


def info_of(info, page, title):
    if not title:
        return None
    return list(info[page][title]["paragraphs"])


def key(id_, label, enabled=True, tip=None, pressed=False, primary=False):
    return {"id": id_, "label": label, "enabled": bool(enabled), "tip": tip or label, "pressed": bool(pressed), "primary": primary}


def section(num, id_, header, info=None, info_text=None, visible=True, **more):
    out = {"number": num, "id": id_, "header": header, "caption": header.upper(), "info": info, "info_text": info_text,
           "visible": bool(visible), "rows": [], "keys": [], "fields": [], "hint": None, "count": None, "show_all": None}
    out.update(more)
    return out


def select(id_, label, options, value, enabled=True, info=None, info_text=None):
    return {"id": id_, "kind": "select", "label": label, "options": [{"value": v, "label": t} for v, t in options],
            "value": value, "enabled": bool(enabled), "info": info, "info_text": info_text}


def number(id_, label, value, unit="mm", auto=None, step=None, minimum=None, enabled=True, hint=None, integer=False):
    """A number field; `integer` for a count (an integer spin box, no decimals)."""
    return {"id": id_, "kind": "number", "label": label, "value": value, "unit": unit, "auto": auto, "step": step,
            "min": minimum, "enabled": bool(enabled), "hint": hint, "info": None, "info_text": None, "integer": bool(integer)}


def check(id_, label, value, enabled=True, info=None, info_text=None):
    return {"id": id_, "kind": "check", "label": label, "value": bool(value), "enabled": bool(enabled), "info": info, "info_text": info_text}


def toggle(id_, label, options, value, enabled=True, tips=None):
    """A moderow: exclusive keys, `options` ((value, label), …)."""
    tips = tips or {}
    return {"id": id_, "kind": "toggle", "label": label, "value": value, "enabled": bool(enabled),
            "options": [{"value": v, "label": t, "tip": tips.get(v, t)} for v, t in options], "info": None, "info_text": None}


def slider(id_, label, value, lo, hi, log=False, enabled=True):
    return {"id": id_, "kind": "slider", "label": label, "value": value, "min": lo, "max": hi, "log": bool(log),
            "enabled": bool(enabled), "info": None, "info_text": None}


def bands_field(bands):
    """ScaleControls.tsx: Bands — Continuous, then "n bands"."""
    return select("bands", "Bands", [(0, "Continuous")] + [(b, f"{b} bands") for b in BAND_CHOICES], bands or 0)


def scan_slot(scan, busy=False, edited=False):
    name = getattr(scan, "name", None)
    tri = len(scan.F) if scan is not None else 0
    return {"role": "Scan", "name": name or "No scan loaded",
            "detail": f"{L.count(tri)} triangles" + (" · edited" if edited else "") if scan is not None else SCAN_FORMATS,
            "dot": SCAN_DOT, "filled": scan is not None,
            "button": key("open-scan", "Replace…" if scan is not None else "Open…", not busy)}


def pins(probes, info_text=None):
    """ProbeList.tsx: "Pinned readings" with its count, the hint while empty."""
    s = section("—", "pins", "Pinned readings", count=len(probes))
    s["rows"] = [{"id": i, "name": p.get("name", f"Pin {i + 1}"), "reading": p.get("reading", ""), "visible": True}
                 for i, p in enumerate(probes)]
    if probes:
        s["fields"] = [check("hide-pins", "Hide pins behind the part", True, info="Hide pins behind the part", info_text=info_text)]
        s["keys"] = [key("clear-pins", "Clear")]
    else:
        s["hint"] = PINS_HINT
    return s


def page(title, workspace, sections):
    return {"title": title, "workspace": workspace, "sections": sections, "footer": W.CREDIT}


# --- the Qt view --------------------------------------------------------------

def button_text(label):
    """A panel button's text: Title Case, as FreeCAD's design guide asks of
    buttons (the model keeps the original's words)."""
    return W.title_case(label)


def group_title(s):
    """A section's group title: its header in Title Case, the way FreeCAD
    titles a task panel's group boxes (the original's caps caption stays in
    the model)."""
    return W.title_case(s["header"]) if s.get("header") else ""


def widget(model, on_key=None, on_field=None, parent=None):
    """A QWidget drawn from any page model (every page's, 3D Measure's too):
    a group box per section titled as FreeCAD titles them, with an (i) key,
    slots, rows, fields of every kind, keys in their grid and hints. The
    credit is the dock's footer, once (dock.Dock), not each page's.
    on_key(section_id, key_id); on_field(section_id, field_id, value)."""
    import math

    from PySide import QtCore, QtWidgets

    if QtWidgets.QApplication.instance() is None:
        # A widget with no application aborts real FreeCAD's Qt: refuse first.
        raise RuntimeError("A ScanRuler page widget needs a QApplication (FreeCAD's GUI).")
    root = QtWidgets.QWidget(parent)
    lay = QtWidgets.QVBoxLayout(root)

    def info_button(title, paras):
        dot = QtWidgets.QToolButton()
        dot.setText("i")
        dot.setFixedSize(14, 14)
        text = "<p><b>%s</b></p>" % title + "".join("<p>%s</p>" % p for p in paras or ())
        dot.setToolTip(text)
        dot.clicked.connect(lambda _=False, t=text, d=dot: QtWidgets.QToolTip.showText(d.mapToGlobal(QtCore.QPoint(0, 14)), t, d))
        return dot

    def header(s, box):
        """The group's (i) key and count, at the top of its box."""
        if not (s.get("info") or s.get("count") is not None):
            return
        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        if s.get("count") is not None:
            row.addWidget(QtWidgets.QLabel(str(s["count"])))
        if s.get("info"):
            row.addWidget(info_button(s["info"], s["info_text"]))
        box.addLayout(row)

    def emit(sid, fid, v):
        if on_field:
            on_field(sid, fid, v)

    def field(s, fd, box):
        row = QtWidgets.QHBoxLayout()
        k = fd.get("kind", "select")
        if k == "check":
            w = QtWidgets.QCheckBox(fd["label"])
            w.setChecked(fd["value"])
            w.toggled.connect(lambda v, sid=s["id"], fid=fd["id"]: emit(sid, fid, bool(v)))
            row.addWidget(w)
        else:
            row.addWidget(QtWidgets.QLabel(fd["label"]))
            if k == "select":
                w = QtWidgets.QComboBox()
                vals = [o["value"] for o in fd["options"]]
                for o in fd["options"]:
                    w.addItem(o["label"], o["value"])
                w.setCurrentIndex(vals.index(fd["value"]) if fd["value"] in vals else 0)
                w.currentIndexChanged.connect(lambda i, sid=s["id"], fid=fd["id"], vals=vals: emit(sid, fid, vals[i]))
            elif k == "number":
                if fd.get("integer"):
                    w = QtWidgets.QSpinBox()
                    w.setRange(int(fd["min"]) if fd["min"] is not None else 0, 2**31 - 1)
                    w.setValue(int(fd["value"] or 0))
                else:
                    w = QtWidgets.QDoubleSpinBox()
                    w.setDecimals(3)
                    w.setRange(fd["min"] if fd["min"] is not None else -1e9, 1e9)
                    w.setValue(float(fd["value"] or 0))
                if fd["unit"]:
                    w.setSuffix(" " + fd["unit"] if fd["unit"] != "×" else "×")
                if fd["hint"]:
                    w.setToolTip(fd["hint"])
                w.editingFinished.connect(lambda sid=s["id"], fid=fd["id"], w=w: emit(sid, fid, w.value()))
            elif k == "slider":
                w = QtWidgets.QSlider(QtCore.Qt.Horizontal)
                w.setRange(0, 1000)
                lo, hi, v = fd["min"], fd["max"], fd["value"]
                if fd["log"]:
                    lo, hi, v = math.log10(lo), math.log10(hi), math.log10(max(v, 1e-12))
                w.setValue(int(round(1000 * (v - lo) / ((hi - lo) or 1))))

                def moved(i, sid=s["id"], fid=fd["id"], lo=lo, hi=hi, lg=fd["log"]):
                    x = lo + (hi - lo) * i / 1000
                    emit(sid, fid, float("%.2g" % (10 ** x)) if lg else x)

                w.valueChanged.connect(moved)
            else:  # toggle
                w = QtWidgets.QWidget()
                tl = QtWidgets.QHBoxLayout(w)
                tl.setContentsMargins(0, 0, 0, 0)
                group = QtWidgets.QButtonGroup(w)
                group.setExclusive(True)
                for o in fd["options"]:
                    b = QtWidgets.QPushButton(button_text(o["label"]))
                    b.setCheckable(True)
                    b.setChecked(o["value"] == fd["value"])
                    b.setToolTip(o["tip"])
                    b.clicked.connect(lambda _=False, sid=s["id"], fid=fd["id"], v=o["value"]: emit(sid, fid, v))
                    group.addButton(b)
                    tl.addWidget(b)
            row.addWidget(w)
        w.setEnabled(fd["enabled"])
        if fd.get("info"):
            row.addWidget(info_button(fd["info"], fd["info_text"]))
        box.addLayout(row)

    def keys(s, box):
        grid = QtWidgets.QGridLayout()
        per = s.get("grid") or 1
        for i, k in enumerate(s["keys"]):
            b = QtWidgets.QPushButton(button_text(k["label"]))
            b.setToolTip(k["tip"])
            b.setEnabled(k["enabled"])
            b.setCheckable(k["pressed"])
            b.setChecked(k["pressed"])
            if k.get("primary"):
                b.setStyleSheet("QPushButton{background:%s;color:white}" % W.ACCENT)
            if on_key:
                b.clicked.connect(lambda _=False, sid=s["id"], kid=k["id"]: on_key(sid, kid))
            grid.addWidget(b, i // per, i % per)
        box.addLayout(grid)

    def section_w(s, box):
        if not s["visible"]:
            return
        if s.get("header"):
            group = QtWidgets.QGroupBox(group_title(s))
            box.addWidget(group)
            box = QtWidgets.QVBoxLayout(group)
        header(s, box)
        for sl in s.get("slots") or ([s["slot"]] if s.get("slot") else []):
            if not isinstance(sl, dict):
                # GD&T's "slots" are the names a tolerance takes (Feature,
                # Datum …), not slot rows: 3D Measure failed to open on them.
                continue
            row = QtWidgets.QHBoxLayout()
            row.addWidget(QtWidgets.QLabel("<span style='color:%s'>●</span> <b>%s</b><br>%s" % (sl["dot"], sl["name"], sl["detail"])))
            b = QtWidgets.QPushButton(button_text(sl["button"]["label"]))
            b.setToolTip(sl["button"].get("tip") or "")
            b.setEnabled(sl["button"]["enabled"])
            if on_key:
                b.clicked.connect(lambda _=False, kid=sl["button"]["id"]: on_key(s["id"], kid))
            row.addWidget(b)
            box.addLayout(row)
        for r in s["rows"]:
            reading = r.get("reading") or r.get("value") or ""
            box.addWidget(QtWidgets.QLabel("<span style='color:%s'>●</span> %s  <b>%s</b>" % (r.get("color", SCAN_DOT), r["name"], reading)))
        for fd in s["fields"]:
            field(s, fd, box)
        keys(s, box)
        if s.get("hint"):
            h = QtWidgets.QLabel(s["hint"])
            h.setWordWrap(True)
            box.addWidget(h)
        for c in s.get("children", []):
            section_w(c, box)

    for s in model["sections"]:
        section_w(s, lay)
    lay.addStretch(1)
    return root
