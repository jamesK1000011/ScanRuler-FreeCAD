# SPDX-License-Identifier: AGPL-3.0-only
# The 3D Measure page model against ScanRuler's TSX (ScanRuler by Stefan
# Hermann, CNC Kitchen): the sections in the original's order, its headers
# and (i) texts word for word, its options and defaults, and the rows,
# readings and key states built from scanstate. Qt's part is skipped here.
import importlib.util
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.dirname(HERE), HERE]

import synth  # noqa: E402
import tsxsource as T  # noqa: E402
from scanrulerfc import model as M  # noqa: E402
from scanrulerfc import workspaces as W  # noqa: E402
from scanrulerfc.pages import fonts as FO  # noqa: E402
from scanrulerfc.pages import infotext as IT  # noqa: E402
from scanrulerfc.pages import measure3d as P  # noqa: E402
from scanrulerfc.scanstate import Scan, fresh  # noqa: E402

NEED = unittest.skipUnless(T.available(), "ScanRuler's source is not here")
HAS_QT = importlib.util.find_spec("PySide") is not None or importlib.util.find_spec("PySide6") is not None


def sphere_fit(c, r=5.0):
    return {"kind": "sphere", "center": list(c), "radius": r, "sigma": 0.01, "usedPoints": 100, "regionSize": 100}


def measured_state():
    V, F = synth.sphere()
    st = fresh()
    st["scan"] = Scan("ball.stl", V, F)
    src = {"type": "fitted", "settings": {"sigma": 3}, "seeds": [0]}
    a = M._add(st, "sphere", sphere_fit((0, 0, 0)), src)
    b = M._add(st, "sphere", sphere_fit((10, 0, 0), 4.0), src)
    M.dimension_add(st, {"refs": [a["id"], b["id"]]})
    return st


def sec(model, sid):
    return next(s for s in model["sections"] if s["id"] == sid)


class Order(unittest.TestCase):
    def test_sections_in_the_originals_order(self):
        m = P.build(fresh())
        self.assertEqual([(s["number"], s["id"]) for s in m["sections"]],
                         [("1", "model"), ("2", "alignment"), ("3", "create_element"), ("—", "discarded"), ("4", "draft"),
                          ("5", "section_editor"), ("6", "elements"), ("7", "sections"), ("8", "create_dimensions"),
                          ("9", "dimensions"), ("10", "gdt"), ("11", "plugins"), ("12", "export")])
        self.assertEqual(m["footer"], W.CREDIT)
        self.assertIn("Stefan Hermann (CNC Kitchen)", m["footer"])

    @NEED
    def test_headers_follow_the_panel_in_order(self):
        panel = T.norm(T.read("src/ui/Panel.tsx"))
        marks = ['"panel"> <div className="group"> <div className="sec-head"> Model', "<AlignmentSection", "Create element <InfoDot",
                 "<DraftEditor", "<SectionEditor", "<span>Elements</span>", "<span>Sections</span>", "<DimensionSection",
                 "<ToleranceSection", '<PanelSections slot="measure"', "STEP as <InfoDot"]
        pos = [panel.index(T.norm(x)) for x in marks]
        self.assertEqual(pos, sorted(pos))

    @NEED
    def test_header_strings(self):
        m = P.build(fresh())
        where = {"model": "src/ui/Panel.tsx", "alignment": "src/ui/AlignmentSection.tsx", "create_element": "src/ui/Panel.tsx",
                 "elements": "src/ui/Panel.tsx", "sections": "src/ui/Panel.tsx", "create_dimensions": "src/ui/DimensionSection.tsx",
                 "dimensions": "src/ui/DimensionSection.tsx", "gdt": "src/ui/ToleranceSection.tsx", "section_editor": "src/ui/SectionEditor.tsx"}
        for sid, rel in where.items():
            with self.subTest(sid):
                self.assertTrue(T.text_in(rel, sec(m, sid)["header"].replace("&", "&amp;")))
                self.assertEqual(sec(m, sid)["caption"], sec(m, sid)["header"].upper())
        kids = sec(m, "plugins")["children"]
        self.assertEqual([k["header"] for k in kids], ["Scanner noise", "Thread"])
        self.assertTrue(T.text_in("plugins/scanner-profiles/ui/ScannerSection.tsx", "Scanner noise <InfoDot"))
        self.assertTrue(T.text_in("plugins/thread-match/ui/ThreadSection.tsx", 'Thread <InfoDot title="Naming a scanned thread"'))
        src = T.read("plugins/scanner-profiles/plugin.ts") + T.read("plugins/thread-match/plugin.ts")
        self.assertLess(int(re.search(r"scanner-profiles', slot: 'measure', order: (\d+)", src).group(1)),
                        int(re.search(r"thread-match', slot: 'measure', order: (\d+)", src).group(1)))


@NEED
class Texts(unittest.TestCase):
    def test_info_texts_verbatim(self):
        for title, entry in IT.INFO.items():
            with self.subTest(title):
                self.assertEqual(entry["paragraphs"], T.infodot(entry["source"], title))

    def test_every_info_on_the_page_is_copied(self):
        m = P.build(measured_state(), {"draft": {"kind": "sphere"}})
        infos = [s["info"] for s in m["sections"] if s["info"]] + [k["info"] for k in sec(m, "plugins")["children"]]
        infos += [f["info"] for s in m["sections"] for f in s["fields"] if f["info"]]
        self.assertEqual(set(infos), set(IT.INFO))

    def test_options_and_defaults(self):
        panel = T.read("src/ui/Panel.tsx")
        for v, lab in P.STEP_OPTIONS + P.CLOUD_OPTIONS:
            self.assertTrue(T.text_in("src/ui/Panel.tsx", f'<option value="{v}">{lab.replace("&", "&amp;")}</option>'), lab)
        self.assertIn("stepStyle", panel)
        store = T.read("src/state/store.ts")
        # Unset (nothing remembered yet), the store falls back to these.
        self.assertIn(f"? 'surfaces' : '{P.STEP_DEFAULT}'", store)
        self.assertIn(f"? 'xyz' : '{P.CLOUD_DEFAULT}'", store)
        self.assertIn(f"settings: {{ method: 'gaussian', sigma: {P.SIGMA_DEFAULT} }}", store)
        labels = dict(re.findall(r"^  (\d): '([^']*)',", T.read("src/core/summary.ts"), re.M))
        self.assertEqual({str(k): v for k, v in P.SIGMA_LABELS.items()}, labels)
        self.assertIn("([3, 2, 1, 0] as SigmaPreset[])", T.read("src/ui/DraftEditor.tsx"))
        self.assertEqual(P.SIGMA_ORDER, (3, 2, 1, 0))
        dim = T.read("src/ui/DimensionSection.tsx")
        self.assertEqual(re.findall(r'<option value="(center|gap|span)">([^<]*)</option>', dim), list(P.MEASURE_OPTIONS))
        draft = T.read("src/ui/DraftEditor.tsx")
        for v, lab in P.SURFACE_OPTIONS + P.SEARCH_OPTIONS + P.METHOD_OPTIONS:
            self.assertIn(f'<option value="{v}">{lab}</option>', draft)

    def test_constants(self):
        self.assertIn(f"SCAN_FORMATS = '{P.SCAN_FORMATS}'", T.read("src/core/formats.ts"))
        pal = re.search(r"PALETTE = \[(.*?)\]", T.read("src/state/palette.ts")).group(1)
        self.assertEqual(tuple(re.findall(r"'(#\w+)'", pal)), P.PALETTE)
        self.assertIn(f'dotColor="{P.SCAN_DOT}"', T.read("src/ui/Panel.tsx"))
        kinds = re.findall(r"\{ id: '(\w+)', label: '(\w+)', noun: '(\w+)' \}", T.read("src/core/elements/kinds.ts"))
        self.assertEqual(tuple(kinds), P.KINDS)
        tol = T.read("src/core/tolerances.ts")
        for name in P.TOLERANCES:
            self.assertIn(f"'{name}'", tol)
        for h in (P.HINT_NO_SCAN, P.HINT_DISCARDED, P.HINT_SECTIONS):
            self.assertTrue(T.text_in("src/ui/Panel.tsx", h), h[:30])
        self.assertTrue(T.text_in("src/ui/DimensionSection.tsx", P.HINT_NO_ELEMENT))
        for tip in P.EXPORT_TIPS.values():
            self.assertTrue(T.text_in("src/ui/Panel.tsx", f'title="{tip}"'))
        for lab in ("Copy summary", "Export STEP", "Export mesh", "Export cloud", "Restore", "Forget", "Replace…", "Open…"):
            self.assertTrue(any(T.text_in(f, lab) for f in ("src/ui/Panel.tsx", "src/ui/ModelSlot.tsx", "src/ui/ExportMeshButton.tsx")), lab)


class Model(unittest.TestCase):
    def test_empty(self):
        m = P.build(fresh())
        slot = sec(m, "model")["slot"]
        self.assertEqual((slot["name"], slot["detail"], slot["button"]["label"]), ("No scan loaded", P.SCAN_FORMATS, "Open…"))
        self.assertEqual(sec(m, "model")["hint"], "Drop it anywhere in the window.")
        self.assertTrue(all(not k["enabled"] for k in sec(m, "create_element")["keys"]))
        self.assertTrue(all(not k["enabled"] for k in sec(m, "alignment")["keys"]))
        self.assertEqual([k["label"] for k in sec(m, "create_element")["keys"]],
                         ["Point", "Line", "Plane", "Sphere", "Cylinder", "Cone", "Circle", "Torus", "Section"])
        self.assertFalse(sec(m, "export")["visible"])
        self.assertFalse(sec(m, "elements")["visible"])
        self.assertFalse(sec(m, "create_dimensions")["keys"][0]["enabled"])

    def test_measured(self):
        m = P.build(measured_state())
        slot = sec(m, "model")["slot"]
        self.assertEqual(slot["name"], "ball.stl")
        self.assertTrue(slot["detail"].endswith(" triangles"))
        self.assertEqual(slot["button"]["label"], "Replace…")
        self.assertIsNone(sec(m, "model")["hint"])
        els = sec(m, "elements")
        self.assertEqual([(r["name"], r["reading"], r["color"]) for r in els["rows"]],
                         [("Sphere 1", "Ø 10.000 mm", "#1877c0"), ("Sphere 2", "Ø 8.000 mm", "#e8590c")])
        self.assertEqual((els["count"], els["show_all"]["label"]), (2, "Hide all"))
        self.assertTrue(all(k["enabled"] for k in sec(m, "create_element")["keys"]))
        dims = sec(m, "dimensions")
        self.assertTrue(dims["visible"])
        self.assertEqual(dims["rows"][0]["value"], "10.000 mm")
        self.assertEqual(sec(m, "create_dimensions")["count"], 1)
        self.assertTrue(sec(m, "create_dimensions")["keys"][0]["enabled"])
        self.assertTrue(sec(m, "gdt")["keys"][0]["enabled"])
        ex = sec(m, "export")
        self.assertTrue(ex["visible"])
        self.assertEqual([f["value"] for f in ex["fields"]], ["solids", "ply"])
        self.assertTrue(all(k["enabled"] for k in ex["keys"]))

    def test_open_boxes_stand_the_rows_down(self):
        st = measured_state()
        m = P.build(st, {"draft": {"kind": "cylinder"}})
        ks = {k["id"]: k for k in sec(m, "create_element")["keys"]}
        self.assertTrue(ks["cylinder"]["pressed"])
        d = sec(m, "draft")
        self.assertTrue(d["visible"])
        self.assertEqual(d["header"], "New cylinder")
        self.assertEqual([f["label"] for f in d["fields"]], ["Surface", "Method", "Used points"])
        self.assertEqual(d["fields"][2]["value"], 3)
        self.assertEqual([o["label"] for o in d["fields"][2]["options"]], ["3 sigma", "2 sigma", "1 sigma", "All points"])
        self.assertEqual(d["keys"][0]["label"], "Create cylinder")
        self.assertFalse(sec(m, "create_dimensions")["keys"][0]["enabled"])
        m = P.build(st, {"draft": {"kind": "sphere", "editId": 1}})
        self.assertEqual(sec(m, "draft")["header"], "Edit Sphere 1")
        self.assertFalse(any(k["enabled"] for k in sec(m, "create_element")["keys"][:8]))
        m = P.build(st, {"dim_draft": {"refs": []}})
        self.assertFalse(any(k["enabled"] for k in sec(m, "create_element")["keys"]))
        m = P.build(st, {"section_draft": {}})
        self.assertFalse(sec(m, "create_element")["visible"])
        self.assertEqual(sec(m, "section_editor")["header"], "New section")
        m = P.build(st, {"discarded": {"kind": "torus", "points": 1234}})
        dsc = sec(m, "discarded")
        self.assertTrue(dsc["visible"])
        self.assertEqual((dsc["header"], dsc["reading"]), ("Discarded round", "1,234 points"))
        m = P.build(st, {"busy": True})
        self.assertFalse(any(k["enabled"] for k in sec(m, "alignment")["keys"]))

    def test_readings(self):
        self.assertEqual(P.format_primary({"kind": "cone", "halfAngle": 15.0}), "∠ 30.00°")
        self.assertEqual(P.format_primary({"kind": "torus", "minorRadius": 2.5}), "R 2.500 mm")
        self.assertEqual(P.format_primary({"kind": "plane", "sigma": 0.01234, "usedPoints": 9}), "σ 0.0123 mm")
        self.assertEqual(P.format_primary({"kind": "plane", "sigma": 0.0, "usedPoints": 0}), "")
        self.assertEqual(P.format_primary({"kind": "point", "center": [1, 2.25, -3]}), "(1.0, 2.3, -3.0)")
        self.assertEqual(P.format_primary({"kind": "line"}), "")
        self.assertEqual(P.format_primary({"kind": "circle", "radius": 1}, "in"), "Ø 0.0787 in")

    @unittest.skipUnless(HAS_QT, "Qt is not here")
    def test_widget(self):
        P.widget(P.build(measured_state()))


class Fonts(unittest.TestCase):
    def test_files_and_licences(self):
        for f in FO.files():
            self.assertTrue(os.path.isfile(f), f)
        for _fs, lic in FO.FAMILIES.values():
            with open(os.path.join(FO.FONTS, lic), encoding="utf-8") as fh:
                self.assertIn("SIL Open Font License", fh.read())
        self.assertEqual(sorted(os.listdir(FO.FONTS)), sorted(os.path.basename(f) for f in FO.files()))

    @NEED
    def test_same_bytes_as_the_original(self):
        for f in FO.files():
            with open(f, "rb") as a, open(os.path.join(T.ROOT, "public", "fonts", os.path.basename(f)), "rb") as b:
                self.assertEqual(a.read(), b.read())

    @unittest.skipUnless(HAS_QT, "Qt is not here")
    def test_load(self):
        self.assertEqual(set(FO.load()), set(FO.FAMILIES))


if __name__ == "__main__":
    unittest.main()
