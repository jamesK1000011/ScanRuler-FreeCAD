# SPDX-License-Identifier: AGPL-3.0-only
# The Surface Deviation, Wall Thickness, 2D Measure, Mesh Tools and Reverse
# engineer page models, the dock model and the status bar model, against
# ScanRuler's TSX and stores (ScanRuler by Stefan Hermann, CNC Kitchen):
# section order, headers, (i) texts word for word, labels and defaults,
# re-parsed from the original. Qt's parts are not run here.
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.dirname(HERE), HERE]

import synth  # noqa: E402
import tsxresolve as R  # noqa: E402
import tsxsource as T  # noqa: E402
from scanrulerfc import dock as DK  # noqa: E402
from scanrulerfc import statusbar as SB  # noqa: E402
from scanrulerfc import workspaces as W  # noqa: E402
from scanrulerfc.pages import deviation as DV  # noqa: E402
from scanrulerfc.pages import flat2d as FL  # noqa: E402
from scanrulerfc.pages import infotext_pages as IP  # noqa: E402
from scanrulerfc.pages import meshtools as MT  # noqa: E402
from scanrulerfc.pages import reverse as RV  # noqa: E402
from scanrulerfc.pages import thickness as TH  # noqa: E402
from scanrulerfc.scanstate import Scan, fresh  # noqa: E402

NEED = unittest.skipUnless(T.available(), "ScanRuler's source is not here")
MTUI = "plugins/mesh-tools/ui/"


def sec(model, sid):
    return next(s for s in model["sections"] if s["id"] == sid)


def fld(s, fid):
    return next(f for f in s["fields"] if f["id"] == fid)


def scanned():
    V, F = synth.sphere()
    st = fresh()
    st["scan"] = Scan("ball.stl", V, F)
    return st


def store_defaults(rel):
    """`key: value,` lines of a zustand store's initial state (after `create<`)."""
    src = T.read(rel)
    body = src[src.index("create<"):]
    if "...CLEARED" in body:  # the reset values the initial state spreads in
        body += src[src.index("const CLEARED"):src.index("create<")]
    out = {}
    for k, v in re.findall(r"^  (\w+): ([^,\n(]+?),?\s*(?://.*)?$", body, re.M):
        out.setdefault(k, v.strip())
    return out


def js(v):
    v = v.split(" as ")[0].strip()
    if v in ("true", "false"):
        return v == "true"
    if v == "null":
        return None
    if v.startswith("'"):
        return v.strip("'")
    try:
        return float(v.replace("_", ""))
    except ValueError:
        return v


def const(rel, name):
    return js(re.search(r"export const %s = ([^\n]+)" % name, T.read(rel)).group(1))


class InfoTexts(unittest.TestCase):
    @NEED
    def test_every_text_is_the_originals(self):
        for page, rows in IP.INFO.items():
            for title, v in rows.items():
                with self.subTest(page=page, title=title):
                    if title == "Scan and reference":
                        want = R.infodot_branch(v["source"], "onElement ? 'The scan' : 'Scan and reference'", 1)
                    else:
                        want = R.infodot(v["source"], title)
                    self.assertEqual(v["paragraphs"], want)
                    self.assertTrue(want)
                    self.assertFalse(any("{" in p or "}" in p for p in want), "an expression left unread")

    @NEED
    def test_static_texts_need_no_reading(self):
        # Where the original has no expression the resolver changes nothing.
        self.assertEqual(IP.INFO["deviation"]["Best fit"]["paragraphs"], T.infodot("src/ui/DeviationPanel.tsx", "Best fit"))
        self.assertEqual(IP.INFO["thickness"]["Rays"]["paragraphs"], T.infodot("src/ui/ThicknessPanel.tsx", "Rays"))

    def test_millimetres(self):
        p = " ".join(IP.INFO["deviation"]["Colour scale"]["paragraphs"])
        self.assertIn("a 0.02 mm print and a 5 mm warp", p)
        self.assertIn("straight off the reference surface", " ".join(IP.INFO["deviation"]["Animated deformation"]["paragraphs"]))


class Deviation(unittest.TestCase):
    def test_order_and_footer(self):
        m = DV.build(fresh())
        self.assertEqual([s["id"] for s in m["sections"]],
                         ["source", "models", "best_fit", "local_fit", "volume", "colour_scale", "deformation", "measured", "pins", "tail"])
        self.assertEqual(m["footer"], W.CREDIT)
        self.assertEqual(m["workspace"], "deviation")

    @NEED
    def test_headers_in_the_panels_order(self):
        src = T.norm(R.resolve(T.read("src/ui/DeviationPanel.tsx")))
        marks = ["Measure against <InfoDot", "Best fit <InfoDot", "Local fine fit <InfoDot", "<VolumeSection", "Colour scale <InfoDot",
                 "Deformation <InfoDot", "What counts as measured</div>", "<ProbeList", "Copy report"]
        pos = [src.index(x) for x in marks]
        self.assertEqual(pos, sorted(pos))
        self.assertTrue(T.text_in("src/ui/VolumeSection.tsx", "Volume error <InfoDot"))

    @NEED
    def test_defaults_are_the_stores(self):
        d = store_defaults("src/state/deviationStore.ts")
        for k in ("localMaxDistance", "maxDistance", "tolerance", "showHistogram", "animate", "animScale", "rangeAuto", "animScaleAuto", "source"):
            with self.subTest(k):
                self.assertEqual(DV.DEFAULTS[k], js(d[k]))
        self.assertEqual(d["range"], "MAX_AUTO_RANGE")
        self.assertEqual(DV.DEFAULTS["range"], const("src/core/deviation/deviation.ts", "MAX_AUTO_RANGE"))
        self.assertEqual(DV.DEFAULTS["mapFacingDeg"], const("src/core/deviation/deviation.ts", "DEFAULT_MAP_FACING_DEG"))
        self.assertEqual(DV.DEFAULTS["targetFacingDeg"], const("src/core/deviation/elementField.ts", "DEFAULT_FACING_DEG"))
        self.assertEqual(DV.MIN_LOCAL_POINTS, const("src/core/deviation/align.ts", "MIN_LOCAL_POINTS"))
        self.assertEqual(list(DV.K.BAND_CHOICES), [int(x) for x in re.findall(r"\d+", re.search(r"BAND_CHOICES = \[([^\]]*)\]",
                                                                                                    T.read("src/state/deviationStore.ts")).group(1))])

    @NEED
    def test_strings(self):
        rel = "src/ui/DeviationPanel.tsx"
        for v, lab, what in DV.SOURCES:
            self.assertTrue(T.text_in(rel, f"{{ id: '{v}', label: '{lab}', what: '{what}' }}"))
        for s in ("Align automatically", "Align by picking points…", "Mark surface to fit on…", "Fit on marked surface",
                  "Put the marking tools away", "Back to the global fit", "Measure deviation", "Animate the deformation",
                  "Stop the animation", "Reference must face the same way", "Surface must face the element"):
            self.assertTrue(T.text_in(rel, s), s)
        for s in (DV.RANGE_HINT, DV.FACING_HINT, DV.TARGET_FACING_HINT, DV.EXPORT_MESH_TIP, DV.EXPORT_MESH_TIP_ELEMENT, DV.ALIGN_TIP_STOP):
            self.assertTrue(T.text_in(rel, s), s)
        self.assertTrue(T.text_in("src/ui/ScaleControls.tsx", "Histogram beside the scale"))
        vol = T.norm(T.read("src/ui/VolumeSection.tsx"))
        self.assertIn(T.norm(DV.volume_hint(0.1)).replace("±0.1 mm", "±{typed(tolerance)}"), vol)

    def test_fields_and_visibility(self):
        st = scanned()
        m = DV.build(st)
        self.assertEqual(fld(sec(m, "source"), "source")["value"], "reference")
        self.assertFalse(sec(m, "colour_scale")["visible"])
        self.assertFalse(sec(m, "best_fit")["keys"][0]["enabled"])  # no reference yet
        st["deviation"] = {"reference": {"name": "nominal.step", "F": st["scan"].F}, "align": {"source": "global"}, "values": [0.0]}
        m = DV.build(st)
        self.assertTrue(sec(m, "colour_scale")["visible"])
        self.assertEqual(fld(sec(m, "colour_scale"), "range-value")["value"], 1.0)
        self.assertEqual(fld(sec(m, "colour_scale"), "bands")["options"][0]["label"], "Continuous")
        self.assertEqual(fld(sec(m, "measured"), "map-facing-deg")["value"], 90.0)
        self.assertEqual(fld(sec(m, "measured"), "tolerance")["value"], 0.1)
        self.assertEqual(fld(sec(m, "deformation"), "anim-scale")["value"], 10.0)
        self.assertEqual([x["role"] for x in sec(m, "models")["slots"]], ["Scan", "Reference"])
        self.assertEqual(sec(m, "models")["slots"][1]["name"], "nominal.step")
        el = DV.build(st, {"source": "element"})
        self.assertEqual(sec(el, "models")["header"], "Model")
        self.assertFalse(sec(el, "best_fit")["visible"])


class Thickness(unittest.TestCase):
    def test_order(self):
        m = TH.build(fresh())
        self.assertEqual([s["id"] for s in m["sections"]], ["model", "measurement", "colour_scale", "minimum_wall", "pins", "tail"])
        self.assertEqual(sec(m, "model")["hint"], "Drop it anywhere in the window.")

    @NEED
    def test_defaults_are_the_stores(self):
        d = store_defaults("src/state/thicknessStore.ts")
        for k in ("method", "maxThickness", "maxThicknessAuto", "coneRays", "low", "high", "scaleAuto", "limit", "showHistogram"):
            with self.subTest(k):
                self.assertEqual(TH.DEFAULTS[k], js(d[k]))
        self.assertEqual(TH.DEFAULTS["coneAngleDeg"], const("src/core/thickness/thickness.ts", "DEFAULT_CONE_ANGLE_DEG"))
        self.assertEqual(TH.DEFAULTS["normalDeviationDeg"], const("src/core/thickness/thickness.ts", "DEFAULT_NORMAL_DEVIATION_DEG"))
        src = T.read("src/state/thicknessStore.ts")
        self.assertEqual([(r, lab) for r, lab in TH.CONE_CHOICES],
                         [(int(r), lab) for r, lab in re.findall(r"\{ rays: (\d+), label: '([^']*)' \}", src)])

    @NEED
    def test_strings_and_order(self):
        rel = "src/ui/ThicknessPanel.tsx"
        src = T.norm(T.read(rel))
        marks = ["Model <InfoDot", "Measurement</div>", "Colour scale <InfoDot", "Minimum wall</div>", "<ProbeList", "Copy report"]
        pos = [src.index(x) for x in marks]
        self.assertEqual(pos, sorted(pos))
        for v, lab in TH.METHODS:
            self.assertTrue(T.text_in(rel, f'<option value="{v}">{lab}</option>'))
        for s in (TH.HINT_MEASURE, TH.MAX_HINT, TH.CONE_HINT, TH.NORMALS_HINT, TH.LOW_HINT, TH.HIGH_HINT, "Measure again",
                  "Measure wall thickness", "Far surface must face back", "Thinner than", "Max. opening angle"):
            self.assertTrue(T.text_in(rel, s), s)
        self.assertTrue(T.text_in("src/ui/ProbeList.tsx", f"hint = '{TH.K.PINS_HINT}'"))

    def test_states(self):
        st = scanned()
        m = TH.build(st)
        self.assertEqual(sec(m, "measurement")["keys"][0]["label"], "Measure wall thickness")
        self.assertEqual([f["id"] for f in sec(m, "measurement")["fields"]],
                         ["thickness-method", "thickness-max", "thickness-rays", "thickness-facing", "thickness-normal-deviation"])
        st["thickness"] = {"values": [1.0]}
        m = TH.build(st)
        self.assertEqual(sec(m, "measurement")["keys"][0]["label"], "Measure again")
        self.assertTrue(fld(sec(m, "colour_scale"), "toggle-thickness-histogram")["value"])
        self.assertEqual(fld(sec(m, "minimum_wall"), "thickness-limit")["value"], 1.0)
        self.assertEqual(sec(m, "pins")["hint"], TH.K.PINS_HINT)
        sph = TH.build(st, {"method": "sphere"})
        self.assertNotIn("thickness-rays", [f["id"] for f in sec(sph, "measurement")["fields"]])


class Flat(unittest.TestCase):
    def test_nine_sections(self):
        m = FL.build(fresh())
        self.assertEqual([(s["number"], s["id"]) for s in m["sections"]],
                         [("1", "source"), ("2", "calibration"), ("3", "scanner_profiles"), ("4", "create_element"),
                          ("5", "elements"), ("6", "dimensions"), ("7", "export"), ("8", "alignment"), ("9", "edges")])
        self.assertEqual(sec(m, "source")["header"], "Image")

    @NEED
    def test_order_follows_the_panel(self):
        src = T.norm(T.read("src/ui/FlatPanel.tsx"))
        marks = ["'Source' : 'Image'", "Calibration <InfoDot", "Scanner profiles</div>", "Create element <InfoDot",
                 "<span>Elements</span>", "<FlatDimensionSection", "Export CSV", "Alignment <InfoDot", "Section edges <InfoDot",
                 "Edge detection <InfoDot"]
        pos = [src.index(T.norm(x)) for x in marks]
        self.assertEqual(pos, sorted(pos))

    @NEED
    def test_strings_and_defaults(self):
        rel = "src/ui/FlatPanel.tsx"
        labels = dict(re.findall(r"(\w+): '([^']*)'", re.search(r"FLAT_KIND_LABELS[^{]*\{(.*?)\}", T.read("src/core/flat/elements.ts"), re.S).group(1)))
        self.assertEqual([lab for _k, lab in FL.KINDS[:5]], [labels[k] for k in re.findall(r"'(\w+)'", re.search(r"FLAT_KINDS[^=]*= \[([^\]]*)\]", T.read(rel)).group(1))])
        for s in ("<span>Count</span>", "<span>Text</span>", "Calibrate on a known distance", "Calibrate on a known diameter",
                  "Calibrate X and Y separately", "Choose profile…", FL.HINT_PROFILES, FL.HINT_NO_DPI, FL.HINT_EXPORT, "Show grid",
                  "Show section edges", "Show detected edges", "<span>Sensitivity</span>", "Set alignment", "Export SVG", "Export DXF"):
            self.assertTrue(T.text_in(rel, s), s)
        for _i, _l, tip in FL.TURN_TIPS:
            self.assertTrue(T.text_in(rel, f'title="{tip}"'), tip)
        self.assertTrue(T.text_in("src/ui/FlatDimensionSection.tsx", FL.HINT_NO_ELEMENTS))
        d = store_defaults("src/state/flatStore.ts")
        for k in ("edgeSensitivity", "showEdges", "snapToEdge", "splitAxes"):
            self.assertEqual(FL.DEFAULTS[k], js(d[k]), k)
        self.assertEqual(FL.DEFAULTS["showGrid"], js(store_defaults("src/state/flatStore.ts")["showGrid"]))

    def test_image_and_section(self):
        st = fresh()
        st["flatSubject"] = st.setdefault("flatState", {})["subject"] = {"kind": "image", "name": "gasket.png"}
        m = FL.build(st)
        self.assertTrue(sec(m, "calibration")["visible"])
        self.assertEqual(sec(m, "edges")["header"], "Edge detection")
        self.assertEqual(sec(m, "edges")["hint"], "No edges detected yet.")
        self.assertEqual([k["label"] for k in sec(m, "create_element")["keys"]], ["Point", "Line", "Circle", "Arc", "Spline", "Count", "Text"])
        self.assertEqual(sec(m, "create_element")["grid"], 4)
        st["sectionState"] = {"sections": [{"id": 1, "name": "Section 1"}]}
        st["flatState"]["subject"] = {"kind": "section", "id": 1}
        st["flatState"]["chains"] = [[0, 1]] * 3
        m = FL.build(st)
        self.assertEqual(sec(m, "source")["header"], "Source")
        self.assertFalse(sec(m, "calibration")["visible"])
        self.assertEqual(sec(m, "edges")["header"], "Section edges")
        self.assertEqual(sec(m, "edges")["hint"], "3 edge chains from the cut.")
        self.assertEqual(fld(sec(m, "source"), "flat-source")["value"], "section:1")


class Mesh(unittest.TestCase):
    def test_order_and_grid(self):
        m = MT.build(scanned())
        self.assertEqual([s["id"] for s in m["sections"]], ["model", "tools", "tool", "edited_copy", "in_use"])
        keys = sec(m, "tools")["keys"]
        self.assertEqual(len(keys), 14)
        self.assertEqual(sec(m, "tools")["grid"], 3)
        self.assertTrue(keys[0]["pressed"])  # the store starts on Reduce mesh
        self.assertEqual(sec(m, "tool")["header"], "Reduce mesh")

    @NEED
    def test_grid_is_the_panels(self):
        src = T.read(MTUI + "MeshPanel.tsx")
        block = re.search(r"const TOOLS[^=]*=\s*\[(.*?)\n\]", src, re.S).group(1)
        rows = re.findall(r"id: '(\w+)',.*?label: '([^']*)',\s*title: '([^']*)'", block, re.S)
        self.assertEqual([(i, lab, tip) for i, lab, tip in MT.TOOLS], rows)
        self.assertEqual(MT.DEFAULT_TOOL, js(store_defaults(MTUI.replace("ui/", "state/meshStore.ts"))["tool"]))
        self.assertTrue(T.text_in(MTUI + "MeshPanel.tsx", MT.HINT_NO_TOOL))

    @NEED
    def test_defaults_are_the_stores(self):
        d = store_defaults("plugins/mesh-tools/state/meshStore.ts")
        for k, v in MT.DEFAULTS.items():
            with self.subTest(k):
                if d[k] == "DEFAULT_TRIANGLE_LIMIT":
                    self.assertEqual(v, const("plugins/mesh-tools/state/meshStore.ts", "DEFAULT_TRIANGLE_LIMIT"))
                elif d[k] == "DEFAULT_BREAK_DEPTH":
                    self.assertEqual(v, const("plugins/mesh-tools/core/breakSurface.ts", "DEFAULT_BREAK_DEPTH"))
                else:
                    self.assertEqual(v, js(d[k]))

    @NEED
    def test_each_tool_section(self):
        files = {"reduce": "ReduceTool", "islands": "IslandsTool", "delete": "DeleteTool", "flip": "FlipTool", "cut": "CutTool",
                 "mirror": "MirrorTool", "holes": "HolesTool", "smooth": "SmoothTool", "densify": "DensifyTool", "offset": "OffsetTool",
                 "boolean": "BooleanTool", "trim": "TrimTool", "shell": "ShellTool", "wrap": "WrapTool"}
        for tool, f in files.items():
            rel = f"{MTUI}tools/{f}.tsx"
            src = T.norm(T.read(rel))
            s = MT.tool_section(tool, dict(MT.DEFAULTS))
            with self.subTest(tool):
                self.assertIn(T.norm(f'{s["header"]} <InfoDot title="{s["info"]}"'), src)
                self.assertTrue(s["info_text"])
                for fd in s["fields"]:
                    if fd["label"] and fd["label"] not in ("X", "Y", "Z"):
                        self.assertTrue(re.search(r'label="%s"|<span>%s</span>|\'%s\'' % ((re.escape(fd["label"]),) * 3), src), fd["label"])
                    for o in fd.get("options") or []:
                        if fd["kind"] == "toggle" and "side" not in o["label"]:
                            self.assertIn(o["label"], src, (fd["id"], o["label"]))
                for k in s["keys"]:
                    self.assertIn(k["label"], src, k["label"])

    def test_field_defaults(self):
        holes = MT.tool_section("holes", dict(MT.DEFAULTS))
        self.assertEqual(fld(holes, "hole-size")["value"], 5.0)
        self.assertTrue(fld(holes, "hole-size")["auto"])
        self.assertEqual(fld(holes, "fill-mode")["value"], "curved")
        self.assertEqual([o["label"] for o in fld(holes, "fill-mode")["options"]], ["Curved", "Flat"])
        cut = MT.tool_section("cut", dict(MT.DEFAULTS))
        self.assertEqual(fld(cut, "cut-ref")["value"], "z")
        self.assertEqual([o["label"] for o in fld(cut, "cut-ref")["options"]], ["YZ plane", "XZ plane", "XY plane"])
        self.assertEqual([o["label"] for o in fld(cut, "cut-keep")["options"]], ["+Z side", "−Z side"])
        self.assertEqual([o["label"] for o in fld(MT.tool_section("shell", dict(MT.DEFAULTS)), "shell-side")["options"]],
                         ["Inward", "Outward", "Both sides"])

    @NEED
    def test_edited_copy(self):
        st = scanned()
        st["meshToolsState"] = {"copy": (st["scan"].V, st["scan"].F[:10]), "pending": ["Filled 3 holes under 5 mm"], "edits": []}
        m = MT.build(st)
        s = sec(m, "edited_copy")
        self.assertTrue(s["visible"])
        self.assertEqual(s["caption"], "EDITED COPY")
        self.assertEqual(s["rows"][0]["reading"], f"10 · scan in use {len(st['scan'].F):,}")
        self.assertEqual([k["label"] for k in s["keys"]], ["Discard", "Export mesh", "Use for analysis"])
        self.assertTrue(s["keys"][2]["primary"])
        rel = MTUI + "EditedCopy.tsx"
        self.assertTrue(T.text_in(rel, "Edited copy <InfoDot"))
        self.assertTrue(T.text_in(rel, MT.HINT_COPY))
        for tip in MT.COPY_TIPS.values():
            self.assertTrue(T.text_in(rel, tip), tip)
        self.assertTrue(T.text_in(MTUI + "MeshPanel.tsx", MT.HINT_IN_USE))
        self.assertTrue(T.text_in(MTUI + "MeshPanel.tsx", "<span>In use for analysis</span>"))

    def test_no_tool(self):
        m = MT.build(scanned(), {"tool": None})
        self.assertEqual(sec(m, "tools")["hint"], MT.HINT_NO_TOOL)
        self.assertFalse(sec(m, "tool")["visible"])


class Reverse(unittest.TestCase):
    def test_stub(self):
        m = RV.build(fresh())
        self.assertEqual([s["header"] for s in m["sections"]],
                         ["Model", "Parameters", "Create feature", "Features", "Bodies", "Notes for the agent"])
        keys = sec(m, "create_feature")["keys"]
        self.assertEqual(len(keys), 26)
        self.assertEqual(sec(m, "create_feature")["grid"], 4)
        self.assertFalse(any(k["enabled"] for k in keys))
        self.assertTrue(all(k["tip"].endswith("coming with the engine port") for k in keys))
        self.assertTrue(all(s["hint"] == "coming with the engine port" for s in m["sections"]))
        self.assertEqual(keys[0]["command"], "ScanRuler_ReExtrude")

    @NEED
    def test_headers_and_keys_are_the_panels(self):
        rel = "plugins/reverse/ui/ReversePanel.tsx"
        src = T.norm(T.read(rel))
        marks = ["Model <InfoDot", "<ParameterList", "Create feature <InfoDot", 'Features <InfoDot title="The feature list"', "<BodyList", "<NoteList"]
        pos = [src.index(x) for x in marks]
        self.assertEqual(pos, sorted(pos))
        self.assertEqual([k["label"] for k in sec(RV.build(fresh()), "create_feature")["keys"]],
                         re.findall(r"<span>([^<{]+)</span>", T.read(rel)[T.read(rel).index('data-test="feature-keys"'):])[:26])
        self.assertTrue(T.text_in("plugins/reverse/ui/ParameterList.tsx", "Parameters"))
        self.assertTrue(T.text_in("plugins/reverse/ui/BodyList.tsx", "<span>Bodies</span>"))
        self.assertTrue(T.text_in("plugins/reverse/ui/NoteList.tsx", "Notes for the agent"))
        self.assertTrue(T.text_in(rel, 'placeholder="Choose a plane…"'))


class Dock(unittest.TestCase):
    def test_page_follows_the_last_tool(self):
        cases = {"element_fit": "elements", "dimension_add": "elements", "align_auto": "elements", "section_cut": "elements",
                 "deviation_align": "deviation", "thickness_measure": "thickness", "flat_fit": "flat", "mesh_fill_holes": "mesh",
                 "scan_open": "thickness", "report_get": "thickness"}
        for tool, ws in cases.items():
            with self.subTest(tool):
                st = scanned()
                st["last_tool"], st["version"] = tool, 1
                m = DK.dock_model(st, current="thickness")
                self.assertEqual(m["workspace"], ws)
                self.assertEqual(m["page"]["workspace"], ws)
                self.assertEqual(m["label"], W.workspace(ws)["label"])
        m = DK.dock_model(fresh())
        self.assertEqual(m["workspace"], "elements")
        self.assertEqual(m["footer"], W.CREDIT)

    def test_every_workspace_has_a_page(self):
        self.assertEqual(set(DK.PAGES), {w["id"] for w in W.WORKSPACES})
        for wid in DK.PAGES:
            m = DK.dock_model(scanned(), current=wid, follow=False)
            self.assertEqual(m["page"]["workspace"], wid)
            self.assertEqual(m["page"]["footer"], W.CREDIT)

    def test_header_strings(self):
        h = DK.header(scanned(), "Bracket", "connected", True, True)
        self.assertEqual(h["title"], "Bracket · ball.stl")
        self.assertEqual(h["agent"], "Agent: connected")
        self.assertEqual(h["save"], "Unsaved changes")
        self.assertEqual(h["checkpoint"], "Local checkpoint saved")
        h = DK.header(fresh(), None, "listening", False)
        self.assertEqual(h["title"], "Untitled project")
        self.assertEqual(h["agent"], "Agent: listening")
        self.assertEqual(h["save"], "No unsaved changes")
        self.assertIsNone(DK.header(fresh())["agent"])
        self.assertEqual(DK.header(fresh(), agent="refused")["agent"], "Agent: turned away")

    @NEED
    def test_header_strings_are_the_originals(self):
        top = T.read("src/ui/TopBar.tsx")
        self.assertIn(f"const placeholder = '{DK.UNTITLED}'", top)
        for s in ("'connected'", "'turned away'", "'listening'", "Agent: {agent.status", "'Unsaved changes'", "'No unsaved changes'"):
            self.assertIn(s, top)
        self.assertIn(f"status: '{DK.CHECKPOINT_TEXT}'", T.read("src/app/useRecovery.ts"))

    def test_ui_keys(self):
        ws, ui = DK.ui_action("workspace", ("flat",), {}, "elements")
        self.assertEqual(ws, "flat")
        ws, ui = DK.ui_action("mesh:fill", (), {}, "elements")
        self.assertEqual((ws, ui["mesh"]["tool"]), ("mesh", "holes"))
        _ws, ui = DK.ui_action("mesh:fill", (), ui, "mesh")
        self.assertIsNone(ui["mesh"]["tool"])  # its key again puts it away
        ws, ui = DK.ui_action("AlignPart", ({},), {}, "elements")
        self.assertEqual(ui["elements"]["open"], "AlignPart")
        self.assertEqual(DK.ui_action("reverse:extrude", (), {}, "elements")[0], "reverse")
        self.assertEqual((DK.TAB_TITLE, DK.TAB_ORDER, DK.REFRESH_MS), ("ScanRuler", 70, 100))

    def test_registers_as_an_agent_link_tab(self):
        class Hooks:
            TABS = []

            @classmethod
            def register_tab(cls, title, factory, order=50):
                cls.TABS.append({"title": title, "factory": factory, "order": order})

        DK.register_tab(Hooks)
        DK.register_tab(Hooks)
        self.assertEqual([(t["title"], t["factory"], t["order"]) for t in Hooks.TABS], [("ScanRuler", DK.make_tab, 70)])

    def test_with_agent_link(self):
        try:
            from agentlink import hooks
        except ImportError:
            self.skipTest("Agent Link is not on the path")
        saved = hooks.saved()
        try:
            DK.register_tab(hooks)
            self.assertEqual(sum(t["title"] == "ScanRuler" for t in hooks.TABS), 1)
        finally:
            hooks.restore(saved)


class StatusBar(unittest.TestCase):
    def test_strings(self):
        st = fresh()
        m = SB.model(st)
        self.assertEqual((m["state"], m["state_text"], m["counts"], m["credit"]), ("READY", "● READY", None, "ScanRuler · CNC Kitchen"))
        self.assertEqual(SB.model(st, busy=True, percent=40)["state_text"], "● WORKING 40%")
        self.assertEqual(SB.model(st, busy=True)["state_text"], "● WORKING")
        self.assertEqual(SB.model(st, error="no scan")["state_text"], "● ERROR")
        st["elements"] = [{"fit": {"kind": "plane"}}, {"fit": None}]
        st["dimensions"] = [{}]
        self.assertEqual(SB.model(st)["counts"], "ELEMENTS 1 of 2 · DIM 1")
        st["elements"] = [{"fit": {"kind": "plane"}}]
        self.assertEqual(SB.model(st)["counts"], "ELEMENTS 1 · DIM 1")

    @NEED
    def test_the_originals(self):
        src = T.read("src/ui/StatusStrip.tsx")
        for s in ("'ERROR'", "'WORKING'", "'READY'", "ELEMENTS <b>", "` of ${elements.length}`", "· DIM{' '}"):
            self.assertIn(s, src)


if __name__ == "__main__":
    unittest.main()
