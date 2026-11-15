# SPDX-License-Identifier: AGPL-3.0-only
# Ported from ScanRuler by Stefan Hermann (CNC Kitchen),
# github.com/CNCKitchen/ScanRuler: src/ui/ThicknessPanel.tsx,
# ScaleControls.tsx, ProbeList.tsx and the defaults of
# src/state/thicknessStore.ts (CONE_CHOICES) and src/core/thickness/thickness.ts.
#
# The Wall Thickness page (design 2.3) as data, in the original's order:
# Model, Measurement, Colour scale, Minimum wall, Pinned readings, Copy
# report. `build(st, ui)` reads the "thickness" block fam_thickness keeps in
# scanstate's session dict; `widget(model)` is the thin Qt view.

from . import kit as K
from .infotext_pages import INFO

TITLE = "Wall Thickness"
WORKSPACE = "thickness"
PAGE = "thickness"

METHODS = (("ray", "Ray along the normal"), ("sphere", "Sphere across the wall"))
CONE_CHOICES = ((0, "Single ray — fast"), (6, "6-ray cone — tighter"), (12, "12-ray cone — tightest"))
# thicknessStore.ts initial state; DEFAULT_CONE_ANGLE_DEG 30 and
# DEFAULT_NORMAL_DEVIATION_DEG 60 from core/thickness/thickness.ts.
DEFAULTS = {"method": "ray", "maxThickness": 10.0, "maxThicknessAuto": True, "coneRays": 0, "coneAngleDeg": 30.0,
            "normalDeviationDeg": 60.0, "low": 0.0, "high": 3.0, "scaleAuto": True, "bands": None, "limit": 1.0,
            "showHistogram": True}
HINT_MEASURE = "Everything above shapes the search, so changing it means measuring again."
MAX_HINT = "Where the search stops. Nothing thicker than this is measured."
CONE_HINT = "How far off the normal the cone of rays may look for a shorter way across the wall."
NORMALS_HINT = ("How far the surface a ray lands on may be from squarely facing it and still count as the other side "
                "of the wall. Anything beyond this is stepped over.")
LOW_HINT = "Wall thickness at the bottom of the scale — the red end. Anything thinner is drawn in a dark red cap."
HIGH_HINT = "Wall thickness at the top of the scale — the blue end. Anything thicker is drawn in a dark blue cap."

ORDER = (("1", "model"), ("2", "measurement"), ("3", "colour_scale"), ("4", "minimum_wall"), ("5", "pins"), ("—", "tail"))


def _i(title):
    return K.info_of(INFO, PAGE, title)


def settings(st, ui=None):
    out = dict(DEFAULTS)
    t = st.get("thickness") or {}
    out.update({k: t[k] for k in DEFAULTS if k in t})
    out.update({k: v for k, v in (ui or {}).items() if k in DEFAULTS})
    return out


def build(st, ui=None, units="mm"):
    ui = dict(ui or {})
    s_ = settings(st, ui)
    t = st.get("thickness") or {}
    scan = st.get("scan")
    status = ui.get("status") or ("ready" if t.get("values") is not None else "idle")
    busy = bool(ui.get("busy")) or status == "running"
    ready = status == "ready"
    out = []
    for num, sid in ORDER:
        if sid == "model":
            s = K.section(num, sid, "Model", "The scan", _i("The scan"))
            s["slot"] = K.scan_slot(scan, busy)
            s["hint"] = None if scan is not None else K.HINT_DROP
        elif sid == "measurement":
            s = K.section(num, sid, "Measurement")
            f = [K.select("thickness-method", "Method", METHODS, s_["method"], not busy, "How thickness is measured", _i("How thickness is measured")),
                 K.number("thickness-max", "Max. thickness", s_["maxThickness"], auto=s_["maxThicknessAuto"], step=1, minimum=0.001,
                          enabled=not busy, hint=MAX_HINT)]
            if s_["method"] == "ray":
                f.append(K.select("thickness-rays", "Rays", CONE_CHOICES, s_["coneRays"], not busy, "Rays", _i("Rays")))
                if s_["coneRays"] > 0:
                    f.append(K.number("thickness-cone-angle", "Max. opening angle", s_["coneAngleDeg"], unit="°", step=5, minimum=0,
                                      enabled=not busy, hint=CONE_HINT))
            on = s_["normalDeviationDeg"] is not None
            f.append(K.check("thickness-facing", "Far surface must face back", on, not busy, "Far surface must face back",
                             _i("Far surface must face back")))
            if on:
                f.append(K.number("thickness-normal-deviation", "Max. deviation of normals", s_["normalDeviationDeg"], unit="°",
                                  step=5, minimum=0, enabled=not busy, hint=NORMALS_HINT))
            s["fields"] = f
            label = "Measuring…" if status == "running" else "Measure again" if ready else "Measure wall thickness"
            s["keys"] = [K.key("measure-thickness", label, scan is not None and not busy, primary=True)]
            s["hint"] = HINT_MEASURE
        elif sid == "colour_scale":
            s = K.section(num, sid, "Colour scale", "Colour scale", _i("Colour scale"), visible=ready)
            s["fields"] = [K.number("thickness-low", "Thin end", s_["low"], auto=s_["scaleAuto"], step=0.1, minimum=0, hint=LOW_HINT),
                           K.number("thickness-high", "Thick end", s_["high"], auto=s_["scaleAuto"], step=0.1, minimum=0.001, hint=HIGH_HINT),
                           K.bands_field(s_["bands"]),
                           K.check("toggle-thickness-histogram", "Histogram beside the scale", s_["showHistogram"])]
        elif sid == "minimum_wall":
            s = K.section(num, sid, "Minimum wall", visible=ready)
            s["fields"] = [K.number("thickness-limit", "Thinner than", s_["limit"], step=0.1, minimum=0.0001)]
        elif sid == "pins":
            s = K.pins(ui.get("probes") or [], _i("Hide pins behind the part"))
            s["number"] = num
            s["visible"] = ready
        elif sid == "tail":
            s = K.section(num, sid, "", visible=ready)
            s["keys"] = [K.key("copy-report", "Copy report", True)]
        out.append(s)
    return K.page(TITLE, WORKSPACE, out)


def widget(model, on_key=None, on_field=None, parent=None):
    return K.widget(model, on_key, on_field, parent)
