# SPDX-License-Identifier: AGPL-3.0-only
# The workbench's tables against ScanRuler's TSX (ScanRuler by Stefan
# Hermann, CNC Kitchen): the workspaces, each toolbar's keys in the panel's
# order with its strings, the view bar, and the AREAS map.
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.dirname(HERE), HERE]

import tsxsource as T  # noqa: E402
from scanrulerfc import workspaces as W  # noqa: E402

NEED = unittest.skipUnless(T.available(), "ScanRuler's source is not here")


def plugin_workspace(rel):
    src = T.read(rel)
    block = re.search(r"workspace: \{(.*?)\n  \}", src, re.S).group(1)
    get = lambda k: re.search(r"\b%s: '([^']*)'" % k, block).group(1)  # noqa: E731
    return {"id": get("id"), "label": get("label"), "tip": get("title"), "icon": get("icon"),
            "order": int(re.search(r"\border: (\d+)", block).group(1))}


@NEED
class Workspaces(unittest.TestCase):
    def test_six_in_the_original_order(self):
        core = T.object_rows("src/ui/TopBar.tsx", "CORE_TABS")
        want = [{"id": r["id"], "label": r["label"], "tip": r["title"], "icon": r["icon"]} for r in core]
        src = T.read("src/ui/TopBar.tsx")
        orders = [int(x) for x in re.findall(r"order: (\d+), group: 'measure'", src)]
        for w, o in zip(want, orders):
            w["order"] = o
        want += [plugin_workspace("plugins/mesh-tools/plugin.ts"), plugin_workspace("plugins/reverse/plugin.ts")]
        want.sort(key=lambda w: w["order"])
        got = [{k: w[k] for k in ("id", "label", "tip", "icon", "order")} for w in W.WORKSPACES]
        self.assertEqual(got, want)

    def test_command_names(self):
        self.assertEqual([w["command"] for w in W.WORKSPACES],
                         ["ScanRuler_Ws3DMeasure", "ScanRuler_WsDeviation", "ScanRuler_WsThickness",
                          "ScanRuler_Ws2DMeasure", "ScanRuler_WsMeshTools", "ScanRuler_WsReverse"])
        self.assertEqual(W.DEFAULT_WORKSPACE, W.WORKSPACES[0]["id"])


def labels(ws, title):
    return [k["label"] for t, ks in W.TOOLBARS[ws] if t == title for k in ks]


@NEED
class Toolbars(unittest.TestCase):
    def test_every_workspace_has_toolbars(self):
        self.assertEqual(list(W.TOOLBARS), [w["id"] for w in W.WORKSPACES])

    def test_alignment_keys_in_panel_order(self):
        src = T.norm(T.read("src/ui/AlignmentSection.tsx"))
        pos = [src.index("> " + lab + " </button>") for lab in labels("elements", "Alignment")]
        self.assertEqual(pos, sorted(pos))

    def test_create_element_is_the_kinds_then_section(self):
        kinds = re.findall(r"\{ id: '(\w+)', label: '(\w+)'", T.read("src/core/elements/kinds.ts"))
        self.assertEqual(labels("elements", "Create element"), [lab for _i, lab in kinds] + ["Section"])
        icons = dict(re.findall(r"^  (\w+): '(\w+)',", T.read("src/ui/Panel.tsx"), re.M))
        ks = W.TOOLBARS["elements"][1][1]
        self.assertEqual([k["icon"] for k in ks[:-1]], [icons[i] for i, _ in kinds])
        self.assertEqual(ks[-1]["tip"], "Cut the scan with a plane to measure in 2D")
        self.assertTrue(T.text_in("src/ui/Panel.tsx", 'title="%s"' % ks[-1]["tip"]))
        self.assertEqual([k["args"]["kind"] for k in ks[:-1]], [i for i, _ in kinds])

    def test_dimension_and_tolerance_keys(self):
        self.assertTrue(T.text_in("src/ui/DimensionSection.tsx", "> New dimension </button>"))
        self.assertTrue(T.text_in("src/ui/ToleranceSection.tsx", "> New tolerance </button>"))
        self.assertEqual(labels("elements", "Dimensions"), ["New dimension", "New tolerance"])

    def test_deviation_thickness_keys(self):
        dev = T.norm(T.read("src/ui/DeviationPanel.tsx")) + T.norm(T.read("src/ui/VolumeSection.tsx"))
        for lab in labels("deviation", "Best fit"):
            self.assertIn(lab, dev)
        th = T.norm(T.read("src/ui/ThicknessPanel.tsx"))
        self.assertIn("'Measure again'", th)
        self.assertIn('label="Copy report"', th)

    def test_flat_keys(self):
        lab = dict(re.findall(r"^  (\w+): '(\w+)',", T.read("src/core/flat/elements.ts"), re.M))
        src = T.read("src/ui/FlatPanel.tsx")
        order = re.search(r"FLAT_KINDS: FlatElementKind\[\] = \[(.*?)\]", src).group(1)
        kinds = re.findall(r"'(\w+)'", order)
        icons = dict(re.findall(r"(\w+): '(\w+)'", re.search(r"FLAT_KIND_ICON[^{]*\{(.*?)\}", src).group(1)))
        want = [lab[k] for k in kinds] + ["Count", "Text"]
        self.assertEqual(labels("flat", "Create element"), want)
        self.assertEqual([k["icon"] for k in W.TOOLBARS["flat"][0][1]], [icons[k] for k in kinds] + ["count", "note"])
        self.assertTrue(T.text_in("src/ui/FlatDimensionSection.tsx", "New dimension"))

    def test_mesh_tools_equal_meshpanel(self):
        rows = T.object_rows("plugins/mesh-tools/ui/MeshPanel.tsx", "TOOLS")
        got = [(k["label"], k["tip"], k["icon"]) for k in W.TOOLBARS["mesh"][0][1]]
        self.assertEqual(got, [(r["label"], r["title"], r["icon"]) for r in rows])

    def test_reverse_keys_equal_reversepanel(self):
        src = T.read("plugins/reverse/ui/ReversePanel.tsx")
        grid = src[src.index('data-test="feature-keys"'):]
        want = []
        for blk in re.findall(r"<(?:button data-test=\"feature-|StepFileKey ).*?</(?:button|StepFileKey)>", grid, re.S)[:26]:
            tip = re.search(r'title="([^"]*)"', blk).group(1)
            ic = re.search(r'<(?:Icon|KeyIcon) name="(\w+)"', blk)
            icon = ic.group(1) if ic else ("thread" if "<ThreadIcon" in blk else "sweep")
            want.append((re.search(r"<span>([^<]*)</span>", blk).group(1), tip, icon))
        got = [(k["label"], k["tip"], k["icon"]) for k in W.TOOLBARS["reverse"][0][1]]
        self.assertEqual(len(got), 26)
        self.assertEqual(got, want)

    def test_tips_are_the_originals(self):
        files = ["src/ui/Panel.tsx", "src/ui/AlignmentSection.tsx", "src/ui/DimensionSection.tsx", "src/ui/ToleranceSection.tsx",
                 "src/ui/DeviationPanel.tsx", "src/ui/VolumeSection.tsx", "src/ui/ThicknessPanel.tsx", "src/ui/FlatPanel.tsx",
                 "src/ui/FlatDimensionSection.tsx", "src/core/flat/elements.ts", "src/ui/TopBar.tsx", "src/ui/ViewBar.tsx",
                 "plugins/mesh-tools/ui/MeshPanel.tsx", "plugins/mesh-tools/app/useMeshPlugin.tsx",
                 "plugins/reverse/ui/ReversePanel.tsx", "plugins/reverse/app/useReversePlugin.tsx"]
        corpus = " ".join(T.norm(T.read(f)) for f in files)
        for k in W.keys() + W.view_keys():
            with self.subTest(k["command"]):
                self.assertIn(k["label"], corpus)
                if k["tip_from"] == "title":
                    self.assertIn(T.norm(k["tip"]), corpus)
                elif k["tip_from"] == "label":
                    # The original has no title: the port's says what it does.
                    self.assertEqual(k["tip"], W.TIPS[k["command"]])
        # Import, Open Scan, Snapshot and About say what they do in FreeCAD,
        # not the browser app's words; New, Save, Load and Settings are
        # FreeCAD's own.
        self.assertEqual({k["command"] for k in W.all_commands().values() if k.get("tip_from") == "moved"},
                         {"ScanRuler_ImportProject", "ScanRuler_OpenScan", "ScanRuler_Snapshot", "ScanRuler_About"})


@NEED
class ViewBar(unittest.TestCase):
    def test_groups_in_bar_order(self):
        self.assertEqual([g["group"] for g in W.VIEW_BAR],
                         ["Scan", "Reference", "Elements", "Bodies", "Split view", "Colour plot", "On reference", "Deviation", "Section"])
        vb = T.norm(T.read("src/ui/ViewBar.tsx"))
        core = ["Scan", "Reference", "Elements", "Split view", "Colour plot", "On reference", "Section"]
        pos = [vb.index(f'label="{g}"') if f'label="{g}"' in vb else vb.index(f"{g} </button>") if f"{g} </button>" in vb else vb.index(f"'{g}'") for g in core]
        self.assertEqual(pos, sorted(pos))

    def test_scan_menu(self):
        scan = W.VIEW_BAR[0]
        self.assertEqual([m["label"] for m in scan["menu"]], ["Transparent", "Mesh", "Backfaces", "Colours"])
        self.assertEqual(W.VIEW_TAIL, ("Std_ViewFitAll", "ScanRuler_Snapshot"))
        self.assertEqual(W.VIEW_BAR[-1]["native"], "Std_ToggleClipPlane")


class Areas(unittest.TestCase):
    def test_areas_map(self):
        self.assertEqual(W.area_of("element_fit"), "3D Measure")
        self.assertEqual(W.area_of("deviation_align"), "Surface Deviation")
        self.assertEqual(W.area_of("thickness_measure"), "Wall Thickness")
        self.assertEqual(W.area_of("flat_fit"), "2D Measure")
        self.assertEqual(W.area_of("mesh_fill_holes"), "Mesh Tools")
        self.assertEqual(W.area_of("scan_open"), "Scan")
        self.assertIsNone(W.area_of("wear_setup"))
        labels_ = {w["label"] for w in W.WORKSPACES}
        self.assertTrue(set(W.AREAS.values()) - {"Scan", "Snapshot"} <= labels_)

    def test_workspace_follows_the_tool(self):
        self.assertEqual(W.workspace_for_tool("mesh_smooth"), "mesh")
        self.assertEqual(W.workspace_for_tool("scan_open", "flat"), "flat")
        self.assertEqual(W.workspace_for_tool("catalog_part", "thickness"), "thickness")

    def test_every_key_tool_has_an_area(self):
        for k in W.keys():
            if k["tool"]:
                with self.subTest(k["command"]):
                    self.assertIsNotNone(W.area_of(k["tool"]) or k["tool"] == "report_get")

    def test_command_for(self):
        self.assertEqual(W.command_for("element_fit", {"kind": "sphere"}), "ScanRuler_ElementSphere")
        self.assertEqual(W.command_for("deviation_align"), "ScanRuler_AlignAutomatically")
        self.assertEqual(W.command_for("mesh_fill_holes"), "ScanRuler_MeshFillHoles")
        self.assertEqual(W.command_for("align_auto"), "ScanRuler_AutoAlign")
        self.assertIsNone(W.command_for("scan_query"))

    def test_unique_toolbar_names(self):
        names = [W.toolbar_name(ws, t) for ws, bars in W.TOOLBARS.items() for t, _ in bars]
        self.assertEqual(len(names), len(set(names)))


if __name__ == "__main__":
    unittest.main()
