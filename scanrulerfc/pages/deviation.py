# SPDX-License-Identifier: AGPL-3.0-only
# Ported from ScanRuler by Stefan Hermann (CNC Kitchen),
# github.com/CNCKitchen/ScanRuler: src/ui/DeviationPanel.tsx,
# VolumeSection.tsx, ScaleControls.tsx, ProbeList.tsx and the defaults of
# src/state/deviationStore.ts.
#
# The Surface Deviation page (design 2.2) as data, in the original's order:
# Measure against, Models, Best fit, Local fine fit, Volume error, Colour
# scale, Deformation, What counts as measured, Pinned readings and the tail
# keys. `build(st, ui)` reads scanstate's session dict (the "deviation"
# block fam_deviation keeps) and the panel's own state; `widget(model)` is
# the thin Qt view (pages/kit.py).

from .. import legend as L
from . import kit as K
from .infotext_pages import INFO

TITLE = "Surface Deviation"
WORKSPACE = "deviation"
PAGE = "deviation"

SOURCES = (("reference", "Reference model", "the nominal CAD part, best-fitted onto the scan"),
           ("element", "Fitted element", "a plane, cylinder or sphere measured on this scan"))
# deviationStore.ts initial state (MAX_AUTO_RANGE = 1, DEFAULT_MAP_FACING_DEG
# = 90, elementField DEFAULT_FACING_DEG = 60).
DEFAULTS = {"source": "reference", "localMaxDistance": 1.0, "range": 1.0, "rangeAuto": True, "maxDistance": 3.0,
            "maxDistanceAuto": True, "bands": None, "tolerance": 0.1, "showHistogram": False, "animate": False,
            "animScale": 10.0, "animScaleAuto": True, "targetFacingDeg": 60.0, "mapFacingDeg": 90.0}
MIN_DEFLECTION_SCALE = 1  # core/deviation/deflection.ts
MAX_DEFLECTION_SCALE = 10_000
REFERENCE_FORMATS = "STL, PLY, OBJ or STEP · mm"
RANGE_SLIDER = (10 ** -3, 10 ** 1.4)  # the log slider's ends, mm
ALIGN_TIP_STOP = "Stop the fit and keep the alignment so far (Esc)"
EXPORT_MESH_TIP = "Save the scan as STL or 3MF, best fit included"
EXPORT_MESH_TIP_ELEMENT = "Save the scan as an STL or a 3MF where it now stands"
HINT_MARK = ("Drag on the scan to mark the surface to fit on — at least {n} points. Right-drag rubs out, "
             "Shift-drag still orbits.")
MIN_LOCAL_POINTS = 50  # core/deviation/align.ts
RANGE_HINT = ("Half-width of the colour scale. Zero always sits at the centre, on green; positive is outside the "
              "reference, negative inside it, and anything past either end is drawn in a dark cap.")
FACING_HINT = ("How far the reference surface may be from facing the way the scan does and still be measured against. "
               "90° steps over only surface facing away. Tighter also re-reads the steep sides of edges the scan has "
               "rounded over, against the face beside the nearest one.")
TARGET_FACING_HINT = ("How far the scan may be from facing the way the element faces and still count. Wide enough to "
                      "keep a genuinely warped surface, tight enough to leave the other side of a wall out.")

ORDER = (("1", "source"), ("2", "models"), ("3", "best_fit"), ("4", "local_fit"), ("5", "volume"),
         ("6", "colour_scale"), ("7", "deformation"), ("—", "measured"), ("—", "pins"), ("—", "tail"))


def _i(title):
    return K.info_of(INFO, PAGE, title)


def volume_hint(tolerance, units="mm"):
    return ("Material the model has too much of or lacks — a boss not modelled, a pocket not cut — as volumes. Takes "
            f"some seconds on a large scan; uses the tolerance ±{L.length_input_text(tolerance, units)} {L.unit_word(units)}.")


def settings(st, ui=None):
    """The page's settings: the session's deviation block over the store's
    defaults, then the panel's own (ui) over both."""
    out = dict(DEFAULTS)
    d = st.get("deviation") or {}
    for k in ("source", "range", "rangeAuto", "maxDistance", "maxDistanceAuto", "bands", "tolerance"):
        if k in d:
            out[k] = d[k]
    if "facingDeg" in d:
        out["mapFacingDeg"] = d["facingDeg"]
    out.update({k: v for k, v in (ui or {}).items() if k in DEFAULTS})
    return out


def build(st, ui=None, units="mm"):
    ui = dict(ui or {})
    s_ = settings(st, ui)
    d = st.get("deviation") or {}
    busy = bool(ui.get("busy"))
    marking = bool(ui.get("marking"))
    scan = st.get("scan")
    ref = d.get("reference")
    on_element = s_["source"] == "element"
    aligned = d.get("align") is not None
    has_map = d.get("values") is not None
    ready = scan is not None and ref is not None
    out = []
    for num, sid in ORDER:
        if sid == "source":
            s = K.section(num, sid, "Measure against", "What the deviation is measured from", _i("What the deviation is measured from"))
            s["fields"] = [K.toggle("source", "", [(v, t) for v, t, _w in SOURCES], s_["source"], not busy,
                                    {v: f"Measure the scan against {w}" for v, _t, w in SOURCES})]
        elif sid == "models":
            if on_element:
                s = K.section(num, sid, "Model", "The scan", None)
            else:
                s = K.section(num, sid, "Models", "Scan and reference", _i("Scan and reference"))
            slots = [K.scan_slot(scan, busy)]
            if not on_element:
                slots.append({"role": "Reference", "name": ref["name"] if ref else "No reference loaded",
                              "detail": f"{L.count(len(ref['F']))} triangles" if ref else REFERENCE_FORMATS,
                              "dot": K.REFERENCE_DOT, "filled": ref is not None,
                              "button": K.key("open-reference", "Replace…" if ref is not None else "Open…", not busy)})
            s["slots"] = slots
        elif sid == "best_fit":
            s = K.section(num, sid, "Best fit", "Best fit", _i("Best fit"), visible=not on_element)
            running = ui.get("align_status") == "running"
            s["keys"] = [K.key("align-auto", "Aligning…" if running else "Align automatically", ready and not busy, primary=True)]
            if running and not marking:
                s["keys"].append(K.key("align-stop", "Stop aligning", True, ALIGN_TIP_STOP))
            else:
                s["keys"].append(K.key("align-points", "Align by picking points…", ready and not busy))
            if aligned and not has_map:
                s["keys"].append(K.key("measure-deviation", "Measure deviation", not busy, primary=True))
        elif sid == "local_fit":
            s = K.section(num, sid, "Local fine fit", "Local fine fit", _i("Local fine fit"), visible=not on_element and aligned)
            if not marking:
                s["keys"] = [K.key("local-start", "Mark surface to fit on…", not busy)]
            else:
                enough = int(ui.get("marked_points", 0)) >= MIN_LOCAL_POINTS
                s["fields"] = [K.number("local-max-distance", "Max search distance", s_["localMaxDistance"], step=0.1, minimum=0.0001)]
                s["keys"] = [K.key("local-fit", "Fit on marked surface", not busy and enough, primary=True),
                             K.key("mark-done", "Put the marking tools away", True, "Close this step and clear the marking (Esc)")]
                if not enough:
                    s["hint"] = HINT_MARK.format(n=MIN_LOCAL_POINTS)
            if d.get("align") and (d["align"] or {}).get("source") == "local":
                s["keys"].append(K.key("local-revert", "Back to the global fit", not busy))
        elif sid == "volume":
            s = K.section(num, sid, "Volume error", "Volume error", _i("Volume error"), visible=not on_element and aligned)
            vol = ui.get("volume") or d.get("volumeResult")
            s["keys"] = [K.key("volume-measure", "Find volume errors again" if vol else "Find volume errors", not busy, primary=True)]
            s["hint"] = None if vol else volume_hint(s_["tolerance"], units)
        elif sid == "colour_scale":
            s = K.section(num, sid, "Colour scale", "Colour scale", _i("Colour scale"), visible=has_map)
            s["fields"] = [K.slider("range-slider", "", s_["range"], *RANGE_SLIDER, log=True),
                           K.number("range-value", "Range ±", s_["range"], auto=s_["rangeAuto"], step=0.01, minimum=0.0001, hint=RANGE_HINT),
                           K.bands_field(s_["bands"]),
                           K.check("toggle-histogram", "Histogram beside the scale", s_["showHistogram"])]
        elif sid == "deformation":
            s = K.section(num, sid, "Deformation", "Animated deformation", _i("Animated deformation"), visible=has_map)
            s["keys"] = [K.key("animate-deformation", "Stop the animation" if s_["animate"] else "Animate the deformation",
                               not marking, pressed=s_["animate"])]
            s["fields"] = [K.slider("anim-scale-slider", "", s_["animScale"], MIN_DEFLECTION_SCALE, 1000, log=True),
                           K.number("anim-scale", "Scale", s_["animScale"], unit="×", auto=s_["animScaleAuto"], step=1,
                                    minimum=MIN_DEFLECTION_SCALE)]
        elif sid == "measured":
            s = K.section(num, sid, "What counts as measured", visible=has_map)
            f = [K.number("max-distance", "Max search distance", s_["maxDistance"], auto=s_["maxDistanceAuto"], step=0.1, minimum=0.0001)]
            if on_element:
                on = s_["targetFacingDeg"] is not None
                f.append(K.check("toggle-facing", "Surface must face the element", on, info="Surface must face the element",
                                 info_text=_i("Surface must face the element")))
                if on:
                    f.append(K.number("facing-deg", "Max. deviation of normals", s_["targetFacingDeg"], unit="°", step=5, minimum=1, hint=TARGET_FACING_HINT))
            else:
                on = s_["mapFacingDeg"] is not None
                f.append(K.check("toggle-map-facing", "Reference must face the same way", on, not busy,
                                 info="Reference must face the same way", info_text=_i("Reference must face the same way")))
                if on:
                    f.append(K.number("map-facing-deg", "Max. deviation of normals", s_["mapFacingDeg"], unit="°", step=5, minimum=1,
                                      enabled=not busy, hint=FACING_HINT))
            f.append(K.number("tolerance", "Tolerance ±", s_["tolerance"], step=0.01, minimum=0.0001))
            s["fields"] = f
        elif sid == "pins":
            s = K.pins(ui.get("probes") or [], _i("Hide pins behind the part"))
            s["visible"] = has_map
        elif sid == "tail":
            s = K.section(num, sid, "", visible=scan is not None)
            s["keys"] = ([K.key("copy-report", "Copy report", True)] if has_map else []) + [
                K.key("export-mesh", "Export mesh", not busy, EXPORT_MESH_TIP_ELEMENT if on_element else EXPORT_MESH_TIP)]
        out.append(s)
    return K.page(TITLE, WORKSPACE, out)


def widget(model, on_key=None, on_field=None, parent=None):
    return K.widget(model, on_key, on_field, parent)
