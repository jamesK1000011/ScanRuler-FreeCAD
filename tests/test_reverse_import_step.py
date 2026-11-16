# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/app/reFeatureCommands.ts (importStep)
# SPDX-License-Identifier: AGPL-3.0-only
#
# reverse_import_step: a STEP file brought in as bodies of their own — an
# Import feature at the rollback bar, its text kept with the part. On the
# stand-in kernel the tool's own decisions; on FreeCAD a box written out
# and read back, in memory and in the document's container.
import os
import sys
import tempfile
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
if os.environ.get("FREECAD_LIB"):
    sys.path.append(os.environ["FREECAD_LIB"])
try:
    import FreeCAD
    import Part

    HAVE_FC = True
except ImportError:
    HAVE_FC = False

from reverse_fakekernel import FakeKernel  # noqa: E402
from scanrulerfc.reverse import handlers as H  # noqa: E402
from scanrulerfc.reverse.build import Builder  # noqa: E402


def write(text, name="part.step"):
    path = os.path.join(tempfile.mkdtemp(), name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


class Tool(unittest.TestCase):
    def setUp(self):
        self.store = H.MemoryStore(Builder(FakeKernel()))
        self.t = H.handlers(store=self.store)

    def test_a_file_of_two_boxes_is_two_bodies_of_one_import(self):
        out = self.t["reverse_import_step"]({"path": write("ISO-10303-21;\n0 0 0 10 10 10\n20 0 0 30 10 10\n", "Motor.STEP")})
        self.assertEqual(out["added"][0]["status"], "ok", out)
        self.assertEqual([round(b["volume"]) for b in out["bodies"]], [1000, 1000])
        f = self.store.part()["features"][0]
        self.assertEqual((f["kind"], f["name"], f["file"]["name"]), ("import", "Motor", "Motor.STEP"))
        self.assertIn(f["file"]["key"], self.store.builder.step_files)
        self.assertEqual(self.t["reverse_build"]({})["failed"], [])

    def test_refusals(self):
        with self.assertRaises(H.Refusal) as e:
            self.t["reverse_import_step"]({"path": write("solid box\nendsolid\n", "box.stl")})
        # The original's sentence, then what to do next (the hardening pass of 16 Nov 2026).
        self.assertTrue(e.exception.message.startswith("box.stl is not a STEP file — it does not begin as one (ISO-10303-21)."), e.exception.message)
        self.assertIn("export", e.exception.message)
        with self.assertRaises(H.Refusal) as e:
            self.t["reverse_import_step"]({"path": os.path.join(tempfile.mkdtemp(), "gone.step")})
        self.assertEqual(e.exception.code, "not_found")
        with self.assertRaises(H.Refusal):
            self.t["reverse_import_step"]({})


@unittest.skipUnless(HAVE_FC, "needs FreeCAD")
class InFreeCAD(unittest.TestCase):
    def box_step(self):
        path = os.path.join(tempfile.mkdtemp(), "box.step")
        Part.makeBox(10, 20, 30).exportStep(path)
        return path

    def test_read_back_in_memory(self):
        from scanrulerfc.reverse.kernel import Kernel

        store = H.MemoryStore(Builder(Kernel()))
        out = H.handlers(store=store)["reverse_import_step"]({"path": self.box_step()})
        self.assertEqual(out["added"][0]["status"], "ok", out)
        self.assertAlmostEqual(out["bodies"][0]["volume"], 6000, delta=6000 * 1e-6)

    def test_in_the_documents_container_the_text_stays_for_every_build(self):
        doc = FreeCAD.newDocument("ReverseImportStep")
        try:
            t = H.handlers(types.SimpleNamespace(doc=doc, family_state={}))
            out = t["reverse_import_step"]({"path": self.box_step(), "name": "Bought-in box"})
            self.assertEqual(out["added"][0]["status"], "ok", out)
            again = t["reverse_build"]({})
            self.assertEqual(again["failed"], [])
            self.assertAlmostEqual(again["bodies"][0]["volume"], 6000, delta=6000 * 1e-6)
            self.assertEqual(t["reverse_feature_list"]({})["features"][0]["name"], "Bought-in box")
        finally:
            FreeCAD.closeDocument(doc.Name)


if __name__ == "__main__":
    unittest.main()
