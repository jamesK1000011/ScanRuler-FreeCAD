# SPDX-License-Identifier: AGPL-3.0-only
# Red team 3 (19 Nov 2026), the fixes in this add-on: ZIP, zlib and scan
# caps (R3-6), the pack's files and its scrub of a bare "key" (R3-8), text
# from files cleaned (R3-11), paths under home as ~/... (R3-12), and the
# project's temporary folder removed (R3-13). Plain Python; the boundary
# test needs Agent Link importable (PYTHONPATH) and is skipped otherwise.
import io
import json
import os
import struct
import sys
import tempfile
import unittest
import zipfile
import zlib
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

from scanrulerfc import guard  # noqa: E402
from scanrulerfc.errors import ToolError  # noqa: E402

try:
    import agentlink  # noqa: F401

    HAVE_HUB = True
except ImportError:
    HAVE_HUB = False

HIDDEN = "Bracket​‮\U000E0041\x07 name"


def _zip(members, method=zipfile.ZIP_DEFLATED):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", method) as z:
        for n, b in members.items():
            z.writestr(n, b)
    return buf.getvalue()


def _project(folder, manifest, scan=b"solid x\nendsolid x\n"):
    path = os.path.join(folder, "p.scanruler")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("project.json", json.dumps(manifest))
        if scan is not None:
            z.writestr("scan.stl", scan)
    return path


MANIFEST = {"app": "ScanRuler", "schemaVersion": 1, "name": HIDDEN,
            "scan": {"fileName": "bracket.stl", "member": "scan.stl", "units": "mm", "elements": [], "sections": []}}


class ZipCaps(unittest.TestCase):
    """R3-6: one helper for every ZIP read."""

    def test_a_member_packed_too_tightly_is_refused_before_it_is_read(self):
        data = _zip({"big.bin": b"\0" * (3 * 1024 * 1024)})
        with zipfile.ZipFile(io.BytesIO(data)) as z, self.assertRaises(guard.TooLarge) as c:
            guard.zip_check(z, "bomb.zip")
        self.assertIn("ZIP bomb", str(c.exception))

    def test_the_total_and_the_member_count_are_capped(self):
        data = _zip({f"m{i}.txt": b"x" * 100 for i in range(5)})
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            with mock.patch.object(guard, "MAX_MEMBERS", 4), self.assertRaises(guard.TooLarge):
                guard.zip_check(z)
            with self.assertRaises(guard.TooLarge):
                guard.zip_check(z, total=300)
            self.assertEqual(len(guard.zip_members(z)), 5)

    def test_a_member_is_read_in_chunks_to_a_byte_limit(self):
        data = _zip({"a.bin": b"y" * 5000})
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            self.assertEqual(len(guard.zip_read(z, "a.bin", limit=5000)), 5000)
            with self.assertRaises(guard.TooLarge):
                guard.zip_read(z, "a.bin", limit=4999)

    def test_zlib_is_inflated_to_a_limit(self):
        packed = zlib.compress(b"\0" * 100_000)
        self.assertEqual(len(guard.inflate(packed, 100_000)), 100_000)
        with self.assertRaises(guard.TooLarge):
            guard.inflate(packed, 99_999)

    def test_a_project_that_is_a_bomb_is_refused(self):
        from scanrulerfc import project_import as P

        d = tempfile.mkdtemp()
        path = _project(d, MANIFEST, scan=b"\0" * (3 * 1024 * 1024))
        with self.assertRaises(ToolError) as c:
            P.load(path, lambda t, a: (True, {}), doc_fn=lambda: None)
        self.assertEqual(c.exception.code, "invalid_input")
        self.assertIn("ZIP bomb", c.exception.message)

    def test_the_state_in_a_document_is_inflated_to_a_limit(self):
        import numpy as np

        from scanrulerfc import docstate

        data, _ = docstate.encode({"big": np.zeros(200_000)})
        self.assertEqual(docstate.decode(data)[0]["big"].shape, (200_000,))
        with mock.patch.object(guard, "MAX_TOTAL", 100_000), self.assertRaises(guard.TooLarge):
            docstate.decode(data)

    def test_a_pack_reads_a_zip_in_a_zip_but_not_deeper(self):
        from scanrulerfc import pack_core as P

        inner = _zip({"settings.config": b"api_key = K\n"})
        out, ch = P.scrub_file("a.zip", _zip({"in.3mf": inner}))
        got = zipfile.ZipFile(io.BytesIO(zipfile.ZipFile(io.BytesIO(out)).read("in.3mf"))).read("settings.config")
        self.assertNotIn(b"K", got)
        with self.assertRaises(guard.TooLarge):
            P.scrub_file("a.zip", _zip({"b.zip": _zip({"c.zip": inner})}))
        with self.assertRaises(guard.TooLarge):
            P.scrub_file("a.3mf", _zip({"big.bin": b"\0" * (3 * 1024 * 1024)}))


class ScanCaps(unittest.TestCase):
    """R3-6: scan files capped in size and triangles."""

    def _stl(self, n):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "s.stl")
        with open(p, "wb") as f:
            f.write(b"\0" * 80 + struct.pack("<I", n) + b"\0" * 50 * n)
        return p

    def test_a_binary_stl_that_says_too_many_triangles(self):
        p = self._stl(11)
        guard.scan_check(p)
        with mock.patch.object(guard, "MAX_TRIANGLES", 10), self.assertRaises(guard.TooLarge):
            guard.scan_check(p)
        with mock.patch.object(guard, "MAX_TRIANGLES", 10), self.assertRaises(guard.TooLarge):
            guard.triangles_check(11, "s.stl")

    def test_a_file_too_large(self):
        p = self._stl(2)
        with mock.patch.object(guard, "MAX_SCAN_BYTES", 100), self.assertRaises(guard.TooLarge):
            guard.scan_check(p)

    def test_a_3mf_bomb(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "s.3mf")
        with open(p, "wb") as f:
            f.write(_zip({"3D/3dmodel.model": b"\0" * (3 * 1024 * 1024)}))
        with self.assertRaises(guard.TooLarge):
            guard.scan_check(p)

    def test_the_readers_check_first(self):
        from scanrulerfc import meshio

        p = self._stl(11)
        with mock.patch.object(guard, "MAX_SCAN_BYTES", 100), self.assertRaises(guard.TooLarge):
            meshio.read(p)  # refused before FreeCAD's Mesh module is asked


class PackFiles(unittest.TestCase):
    """R3-8: what pack_setup { files } takes, and the scrub of key fields."""

    def setUp(self):
        from scanrulerfc import lent

        self.out = tempfile.mkdtemp()
        self.session = type("S", (), {"out_dir": self.out})()
        self._lent = lent.AGENTLINK_STATE
        lent.AGENTLINK_STATE = None

    def tearDown(self):
        from scanrulerfc import lent

        lent.AGENTLINK_STATE = self._lent

    def _file(self, *parts):
        p = os.path.join(*parts)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write("x")
        return p

    def test_files_in_the_session_folder_go_in(self):
        from scanrulerfc.handlers import pack

        p = self._file(self.out, "photos", "a.jpg")
        self.assertEqual(pack._pack_file(self.session, p), p)

    def test_outside_hidden_printer_and_state_files_are_refused(self):
        from scanrulerfc import lent
        from scanrulerfc.handlers import pack

        bad = [self._file(tempfile.mkdtemp(), "notes.txt"),
               self._file(self.out, ".secret", "a.txt"),
               self._file(self.out, ".env.txt"),
               self._file(self.out, "printers.json"),
               self._file(self.out, "sub", ".agentlink-printers.json")]
        for p in bad:
            with self.assertRaises(ToolError, msg=p) as c:
                pack._pack_file(self.session, p)
            self.assertEqual(c.exception.code, "invalid_input")
        state = self._file(self.out, "settings.json")
        lent.AGENTLINK_STATE = lambda real, out: "settings.json" if real.endswith("settings.json") else None
        with self.assertRaises(ToolError):
            pack._pack_file(self.session, state)
        with self.assertRaises(ToolError) as c:
            pack._pack_file(self.session, os.path.join(self.out, "none.txt"))
        self.assertEqual(c.exception.code, "not_found")

    def test_a_link_out_of_the_session_folder_is_refused(self):
        from scanrulerfc.handlers import pack

        target = self._file(tempfile.mkdtemp(), "id.txt")
        link = os.path.join(self.out, "id.txt")
        os.symlink(target, link)
        with self.assertRaises(ToolError):
            pack._pack_file(self.session, link)

    def test_a_bare_key_field_is_emptied(self):
        from scanrulerfc import pack_core as P

        text = ('{"name": "mk4", "key": "ABCDEF", "apiKey": "G1", "token": "T1", "keyboard": "us"}\n'
                "password = pw1\nsecret: s1\nlayer_height = 0.2\n")
        out = P.scrub_file("printers.json", text.encode())[0].decode()
        for bad in ("ABCDEF", "G1", "T1", "pw1", "s1"):
            self.assertNotIn(bad, out)
        self.assertIn('"keyboard": "us"', out)
        self.assertIn("layer_height = 0.2", out)
        xml = '<metadata key="layer_height" value="0.2"/><metadata key="key" value="SECRETV"/>'
        out = P.scrub_file("a.config", xml.encode())[0].decode()
        self.assertNotIn("SECRETV", out)
        self.assertIn('key="layer_height" value="0.2"', out)


class FileText(unittest.TestCase):
    """R3-11: text from files reaches the agent clean and capped."""

    def test_format_tag_and_control_characters_go(self):
        self.assertEqual(guard.text(HIDDEN), "Bracket name")
        self.assertEqual(len(guard.text("x" * 500, 50)), 51)

    def test_project_and_element_names_are_cleaned(self):
        from scanrulerfc import project_import as P

        d = tempfile.mkdtemp()
        man = json.loads(json.dumps(MANIFEST))
        man["scan"]["elements"] = [{"kind": "plane", "name": "Top​⁦", "source": {"type": "fitted", "seeds": [1]}},
                                   {"kind": "evil‮" + "x" * 100, "name": None, "source": {}}]
        man["scan"]["fileName"] = "sc​an.stl"
        calls = []
        got = P.load(_project(d, man), lambda t, a: calls.append((t, a)) or (True, {}), folder=d, doc_fn=lambda: None)
        self.assertEqual(got["project"], "Bracket name")
        self.assertEqual(got["scan"], "scan.stl")
        self.assertEqual(calls[1][1]["name"], "Top")
        self.assertTrue(all("‮" not in x and len(x) < 120 for x in got["notLoaded"]))


class HomeShort(unittest.TestCase):
    """R3-12: paths under home as ~/... ."""

    def test_tilde(self):
        h = os.path.expanduser("~")
        got = guard.tilde({"file": {"path": os.path.join(h, "AgentLink", "a.ply")}, "n": 3, "l": [h + "/x", "/tmp/y", h + "er/z"]})
        self.assertEqual(got, {"file": {"path": "~/AgentLink/a.ply"}, "n": 3, "l": ["~/x", "/tmp/y", h + "er/z"]})

    @unittest.skipUnless(HAVE_HUB, "Agent Link is not importable here")
    def test_answers_and_refusals_at_the_boundary(self):
        from agentlink.protocol import ToolError as AgentToolError

        from scanrulerfc.agentlink import _bridge

        h = os.path.expanduser("~")
        ok = _bridge.home_short(lambda a: {"file": {"path": h + "/AgentLink/s-cloud.ply"}})
        self.assertEqual(ok({}), {"file": {"path": "~/AgentLink/s-cloud.ply"}})

        def bad(a):
            raise ToolError("not_found", f"path {h}/scans/a.stl: no such file")

        with self.assertRaises(AgentToolError) as c:
            _bridge.home_short(bad)({})
        self.assertEqual((c.exception.code, c.exception.message), ("not_found", "path ~/scans/a.stl: no such file"))

        def val(a):
            raise ValueError(f"{h}/a.stl: no triangles read.")

        with self.assertRaises(AgentToolError) as c:
            _bridge.home_short(val)({})
        self.assertEqual((c.exception.code, c.exception.message), ("invalid_input", "~/a.stl: no triangles read."))

    def test_a_short_path_is_read_as_the_same_file(self):
        from scanrulerfc import paths

        self.assertEqual(paths.resolve(None, "~/AgentLink/a.stl"), os.path.join(os.path.expanduser("~"), "AgentLink", "a.stl"))


class TempFolder(unittest.TestCase):
    """R3-13: the project's copy of the scan does not stay."""

    def test_the_temporary_folder_is_removed(self):
        from scanrulerfc import project_import as P

        made = []
        real = tempfile.mkdtemp

        def mkdtemp(*a, **k):
            made.append(real(*a, **k))
            return made[-1]

        path = _project(tempfile.mkdtemp(), MANIFEST)
        seen = []
        with mock.patch.object(P.tempfile, "mkdtemp", mkdtemp):
            P.load(path, lambda t, a: seen.append(os.path.isfile(a["path"])) or (True, {}), doc_fn=lambda: None)
        self.assertEqual(seen, [True])  # there while scan_open reads it
        self.assertEqual(len(made), 1)
        self.assertFalse(os.path.exists(made[0]))

    def test_removed_after_a_refusal_too(self):
        from scanrulerfc import project_import as P

        made = []
        real = tempfile.mkdtemp

        def mkdtemp(*a, **k):
            made.append(real(*a, **k))
            return made[-1]

        def boom(t, a):
            raise RuntimeError("scan_open failed")

        path = _project(tempfile.mkdtemp(), MANIFEST)
        with mock.patch.object(P.tempfile, "mkdtemp", mkdtemp), self.assertRaises(RuntimeError):
            P.load(path, boom, doc_fn=lambda: None)
        self.assertFalse(os.path.exists(made[0]))


if __name__ == "__main__":
    unittest.main()
