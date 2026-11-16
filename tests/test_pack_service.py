# SPDX-License-Identifier: AGPL-3.0-only
# ScanRuler's library pack (Stefan Hermann, CNC Kitchen) as the
# library_pack service Workshop Documents asks for: Documents' arguments
# mapped onto pack_setup, then pack_plan and pack_write, the answer in
# library_pack's shape with by "ScanRuler" and the credit.
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from scanrulerfc import CREDIT  # noqa: E402
from scanrulerfc import pack_service as PS  # noqa: E402
from scanrulerfc.errors import ToolError  # noqa: E402


def fake_tools(calls, refuse=None):
    def tools(session):
        def setup(a):
            calls.append(("pack_setup", a))
            return {"settings": {"licence": "CC-BY-4.0"}, "bodies": a.get("bodies") or ["Bracket"]}

        def plan(a):
            calls.append(("pack_plan", a))
            return {"ok": True, "licence": "CC-BY-4.0", "credited": [{"part": "Hinge"}], "bodies": ["Bracket", "Lid cover"]}

        def write(a):
            calls.append(("pack_write", a))
            if refuse:
                raise refuse
            return {"file": {"path": a.get("path", "/out/Box.zip"), "name": "Box.zip", "bytes": 1234},
                    "contents": ["LICENSE", "README.md", "images/iso.png", "models/Bracket.step", "models/Bracket.stl", "models/Lid_cover.stl"],
                    "scrubbed": [{"what": "user name", "count": 1}], "credited": [{"part": "Hinge"}], "leftOut": [], "note": "Read README.md."}

        return {"pack_setup": setup, "pack_plan": plan, "pack_write": write}
    return tools


class Mapping(unittest.TestCase):
    def test_documents_arguments_become_pack_setups(self):
        got = PS.setup_args({"bodies": ["Bracket"], "name": "Box", "description": "A box.", "license": "CC-BY-4.0", "author": "maker",
                             "formats": ["stl"], "tolerance": 0.02,
                             "credits": [{"title": "Hinge", "author": "someone", "url": "https://x.example/h", "license": "CC-BY-4.0", "changes": "shortened"},
                                         {"title": "Knob", "license": "CC0-1.0", "changes": ""}]})
        self.assertEqual(got, {"include3mf": False, "bodies": ["Bracket"], "title": "Box", "summary": "A box.", "licence": "CC-BY-4.0", "author": "maker",
                               "includeStep": False,
                               "upstream": [{"part": "Hinge", "title": "Hinge", "author": "someone", "url": "https://x.example/h", "licence": "CC-BY-4.0", "modified": True},
                                            {"part": "Knob", "title": "Knob", "licence": "CC0-1.0", "modified": False}]})

    def test_no_credits_leaves_the_provenance(self):
        self.assertNotIn("upstream", PS.setup_args({"license": "MIT"}))

    def test_bad_arguments_refused(self):
        for a in ({"formats": []}, {"formats": ["obj"]}, {"credits": "Hinge"}):
            with self.assertRaises(ToolError):
                PS.setup_args(a)


class Pack(unittest.TestCase):
    def test_setup_plan_write_and_the_answer(self):
        calls = []
        out = PS.LibraryPack(fake_tools(calls)).pack(object(), {"license": "CC-BY-4.0", "author": "maker", "path": "/out/Box.zip"})
        self.assertEqual([c[0] for c in calls], ["pack_setup", "pack_plan", "pack_write"])
        self.assertEqual(calls[2][1], {"path": "/out/Box.zip"})
        self.assertEqual(out["by"], "ScanRuler")
        self.assertEqual(out["credit"], CREDIT)
        self.assertIn("Stefan Hermann (CNC Kitchen)", out["credit"])
        self.assertEqual((out["pack"], out["bytes"], out["license"]), ("/out/Box.zip", 1234, "CC-BY-4.0"))
        self.assertEqual(out["parts"], [{"body": "Bracket", "files": ["Bracket.step", "Bracket.stl"]}, {"body": "Lid cover", "files": ["Lid_cover.stl"]}])
        self.assertIn("models/Bracket.step", out["files"])
        self.assertEqual(out["credited"], [{"part": "Hinge"}])

    def test_out_is_the_path_too_and_none_is_scanrulers_default(self):
        calls = []
        PS.LibraryPack(fake_tools(calls)).pack(object(), {"license": "MIT", "out": "/o/p.zip"})
        self.assertEqual(calls[-1], ("pack_write", {"path": "/o/p.zip"}))
        calls.clear()
        PS.LibraryPack(fake_tools(calls)).pack(object(), {"license": "MIT"})
        self.assertEqual(calls[-1], ("pack_write", {}))

    def test_a_refusal_carries_code_and_message(self):
        no = ToolError("invalid_state", "The pack can't go out yet: Hinge: no-derivatives.")
        with self.assertRaises(ToolError) as c:
            PS.LibraryPack(fake_tools([], refuse=no)).pack(object(), {"license": "CC-BY-4.0"})
        self.assertEqual((c.exception.code, c.exception.message), ("invalid_state", "The pack can't go out yet: Hinge: no-derivatives."))

    def test_runs_scanrulers_own_pack_tools(self):
        self.assertTrue({"pack_setup", "pack_plan", "pack_write"} <= set(PS._tools(object())))

    def test_offered_by_the_family_layer(self):
        src = open(os.path.join(os.path.dirname(HERE), "scanrulerfc", "agentlink_families.py"), encoding="utf-8").read()
        self.assertIn('hooks.provide("library_pack", LibraryPack())', src)
        self.assertEqual(PS.LibraryPack.NAME, "ScanRuler")


if __name__ == "__main__":
    unittest.main()
