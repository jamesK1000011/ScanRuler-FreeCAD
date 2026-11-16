# SPDX-License-Identifier: AGPL-3.0-only
# A file a tool is given is found as Agent Link's export_file writes it: ~
# expanded, a relative name in the session's output folder (outDir), else
# the working folder (scanrulerfc/paths.py) — "rev_box.step" failed with
# "cannot be read" while export_file had written it to ~/AgentLink.
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

from scanrulerfc import handlers, paths  # noqa: E402


class Resolve(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.mkdtemp()
        self.ctx = types.SimpleNamespace(out_dir=self.out)

    def test_relative_in_the_out_folder(self):
        self.assertEqual(paths.resolve(self.ctx, "rev_box.step"), os.path.join(self.out, "rev_box.step"))
        self.assertEqual(paths.resolve(self.ctx, "sub/a.stl"), os.path.join(self.out, "sub", "a.stl"))

    def test_tilde_expanded(self):
        with mock.patch.dict(os.environ, {"HOME": "/home/someone"}):
            self.assertEqual(paths.resolve(self.ctx, "~/AgentLink/rev_box.step"), "/home/someone/AgentLink/rev_box.step")

    def test_absolute_kept(self):
        self.assertEqual(paths.resolve(self.ctx, "/tmp/x.stl"), "/tmp/x.stl")

    def test_no_out_folder_falls_back_to_cwd(self):
        self.assertEqual(paths.resolve(types.SimpleNamespace(), "x.stl"), os.path.join(os.getcwd(), "x.stl"))
        self.assertEqual(paths.resolve(types.SimpleNamespace(out_dir=None), "x.stl"), os.path.join(os.getcwd(), "x.stl"))

    def test_every_path_input(self):
        got = paths.resolve_args(self.ctx, {"path": "a.stl", "export": "b.json", "import": "c.json", "files": ["d.pdf", "/e.pdf"],
                                            "object": "Mesh"})
        self.assertEqual(got["path"], os.path.join(self.out, "a.stl"))
        self.assertEqual(got["export"], os.path.join(self.out, "b.json"))
        self.assertEqual(got["import"], os.path.join(self.out, "c.json"))
        self.assertEqual(got["files"], [os.path.join(self.out, "d.pdf"), "/e.pdf"])
        self.assertEqual(got["object"], "Mesh")
        self.assertEqual(paths.resolve_args(self.ctx, {"path": ""})["path"], "")

    def test_every_declared_path_input_is_a_key(self):
        """Each file input in data/tools.json is one paths.KEYS resolves."""
        import json

        with open(os.path.join(os.path.dirname(HERE), "scanrulerfc", "data", "tools.json"), encoding="utf-8") as f:
            data = json.load(f)
        found = set()

        def walk(o):
            if isinstance(o, dict):
                props = (o.get("inputSchema") or {}).get("properties") or {}
                found.update(k for k in props if k in ("path", "file", "files", "import", "export", "image", "out"))
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)

        walk(data)
        self.assertTrue(found)
        self.assertLessEqual(found, set(paths.KEYS))


class ThroughTheHandlers(unittest.TestCase):
    """reverse_import_step and scan_open, bound as Agent Link binds them
    (handlers.bound), take a name in the out folder and ~/…."""

    def setUp(self):
        self.out = tempfile.mkdtemp()
        self.ctx = types.SimpleNamespace(out_dir=self.out, doc=None, family_state={})

    def test_reverse_import_step_reads_from_the_out_folder(self):
        seen = []
        real = open

        def spy(p, *a, **k):
            if str(p).endswith(".step"):
                seen.append(p)
                raise FileNotFoundError(2, "No such file or directory")
            return real(p, *a, **k)

        fn = handlers.bound(self.ctx, "reverse")["reverse_import_step"]
        with mock.patch("builtins.open", spy):
            for given in ("rev_box.step", "~/AgentLink/rev_box.step"):
                try:
                    fn({"path": given})
                except Exception:  # noqa: BLE001 — no such file here: the path tried is what counts
                    pass
        self.assertEqual(seen[0], os.path.join(self.out, "rev_box.step"))
        self.assertEqual(seen[1], os.path.join(os.path.expanduser("~"), "AgentLink", "rev_box.step"))

    def test_scan_open_finds_a_relative_name(self):
        open(os.path.join(self.out, "ball.stl"), "w").close()
        from scanrulerfc import scanstate as S

        with mock.patch.object(S, "load", side_effect=ValueError("read")) as load:
            with self.assertRaises(Exception):
                handlers.bound(self.ctx, "scan")["scan_open"]({"path": "ball.stl"})
        self.assertEqual(load.call_args[0][0], os.path.join(self.out, "ball.stl"))

    def test_the_runner_resolves_too(self):
        """The add-on's own runner (handlers.all_handlers, fn(ctx, args))."""
        got = handlers.all_handlers()["scan_open"]
        with self.assertRaises(Exception) as e:
            got(self.ctx, {"path": "missing.stl"})
        self.assertIn(os.path.join(self.out, "missing.stl"), str(e.exception))


if __name__ == "__main__":
    unittest.main()
