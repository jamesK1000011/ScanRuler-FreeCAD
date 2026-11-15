# SPDX-License-Identifier: AGPL-3.0-only
# Screenshot for the agent, ported from ScanRuler by Stefan Hermann (CNC
# Kitchen): the store, the mark-up model and the snapshot_* handlers on fake
# pictures; drawing and the card under offscreen Qt where Qt is installed.
import datetime as dt
import os
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from scanrulerfc.snapshot import handlers as H  # noqa: E402
from scanrulerfc.snapshot import marks as MK  # noqa: E402
from scanrulerfc.snapshot.store import KEEP, Shot, ShotMark, ShotStore, file_name  # noqa: E402

FAKE = b"\x89PNG fake"


def shot(i=0, **kw):
    return Shot(FAKE + bytes([i]), 1000, 500, kw.pop("workspace", "Surface Deviation"), **kw)


class TestStore(unittest.TestCase):
    def test_keep_eight_newest_first(self):
        st = ShotStore(save=False)
        made = [st.add(shot(i)) for i in range(11)]
        self.assertEqual(KEEP, 8)
        self.assertEqual(len(st.shots), 8)
        self.assertEqual([s.id for s in st.shots], [s.id for s in reversed(made)][:8])
        self.assertEqual(st.open, made[-1].id)

    def test_remove_and_clear(self):
        st = ShotStore(save=False)
        a, b = st.add(shot(1)), st.add(shot(2))
        st.set_editing(b.id)
        st.remove(b.id)
        self.assertEqual((st.latest().id, st.open, st.editing), (a.id, None, None))
        st.clear()
        self.assertIsNone(st.latest())

    def test_file_name_and_save(self):
        s = shot(at=dt.datetime(2026, 11, 14, 21, 36, 5, 123456))
        self.assertEqual(file_name(s), "scanruler-2026-11-14_21-36-05-123.png")
        self.assertEqual(file_name(s, True), "scanruler-2026-11-14_21-36-05-123-marked.png")
        st = ShotStore(save=True)
        st.add(s)
        with tempfile.TemporaryDirectory() as d:
            p = st.save_beside(s, d)
            self.assertEqual(p, os.path.join(d, "shots", file_name(s)))
            with open(p, "rb") as f:
                self.assertEqual(f.read(), s.png)
            self.assertEqual(s.path, p)

    def test_mark_round_trip(self):
        m = ShotMark("pin", [10, 20], "#e5262b", 1, "here")
        self.assertEqual(ShotMark.from_dict(m.to_dict()), m)
        with self.assertRaises(ValueError):
            ShotMark("blob", [0, 0], "#fff")


class TestMarkUp(unittest.TestCase):
    def test_tools_keys_colours(self):
        self.assertEqual([k for _t, _l, k in MK.TOOLS], ["P", "A", "B", "C", "D"])
        self.assertEqual(MK.COLOURS, ("#e5262b", "#f2b705", "#1877c0"))
        mu = MK.MarkUp()
        self.assertEqual(mu.tool, "pin")
        for key, tool in (("a", "arrow"), ("B", "box"), ("c", "circle"), ("d", "pen"), ("p", "pin")):
            self.assertTrue(mu.key(key))
            self.assertEqual(mu.tool, tool)
        self.assertFalse(mu.key("x"))

    def test_draw_number_undo(self):
        mu = MK.MarkUp()
        mu.press(10, 10)
        mu.press(20, 20)
        self.assertEqual([p.n for p in mu.pins()], [1, 2])
        mu.set_tool("arrow")
        mu.set_colour(MK.COLOURS[2])
        mu.press(0, 0)
        mu.move(50, 40)
        self.assertEqual(len(mu.visible()), 3)
        mu.release(100, 80)
        self.assertEqual(mu.marks[-1].to_dict(), {"kind": "arrow", "pts": [0, 0, 100, 80], "color": "#1877c0"})
        mu.set_tool("pen")
        mu.press(1, 1)
        mu.move(2, 2)
        mu.release(3, 3)
        self.assertEqual(mu.marks[-1].pts, [1, 1, 1, 1, 2, 2, 3, 3])
        mu.set_tool("box")
        mu.press(5, 5)
        self.assertIsNone(mu.release(5, 5))  # a click is not a box
        self.assertEqual(len(mu.marks), 4)
        self.assertTrue(mu.key("z", ctrl=True))
        self.assertEqual(mu.marks[-1].kind, "arrow")
        mu.undo()
        mu.comment(2, "gap")
        self.assertEqual(mu.pins()[1].comment, "gap")
        mu.remove_pin(1)
        mu.set_tool("pin")
        mu.press(7, 7)
        self.assertEqual([p.n for p in mu.pins()], [2, 3])
        mu.undo()
        mu.undo()
        self.assertIsNone(mu.undo())

    def test_serialise_and_done(self):
        mu = MK.MarkUp(note="look")
        mu.press(250, 125)
        mu.comment(1, "the numerals")
        back = MK.MarkUp.from_dict(mu.to_dict())
        self.assertEqual(back.to_dict(), mu.to_dict())
        st = ShotStore(save=False)
        s = st.add(shot())
        st.set_editing(s.id)
        mu.done(st, s.id)
        self.assertEqual((len(s.marks), s.note, st.editing), (1, "look", None))
        self.assertEqual(MK.pins_of(s), [{"n": 1, "comment": "the numerals", "x": 250, "y": 125, "at": "25% across, 25% down"}])
        self.assertEqual(MK.stroke_for(1000), 2)
        self.assertEqual(MK.stroke_for(3360), 8)


class TestHandlers(unittest.TestCase):
    def setUp(self):
        self.st = ShotStore(save=False)
        self.ctx = {"shots": self.st}

    def test_empty(self):
        self.assertEqual(H.snapshot_list(self.ctx, {}), {"shots": []})
        with self.assertRaises(H.SnapshotError) as e:
            H.snapshot_latest(self.ctx, {})
        self.assertEqual(e.exception.code, "not_found")

    def test_list_latest(self):
        a = self.st.add(shot(1))
        b = self.st.add(shot(2, note="the gap"))
        rows = H.snapshot_list(self.ctx, {})["shots"]
        self.assertEqual([r["id"] for r in rows], [b.id, a.id])
        self.assertEqual(rows[0]["note"], "the gap")
        self.assertIsNone(rows[1]["note"])
        self.assertNotIn("_png", rows[0])
        got = H.snapshot_latest(self.ctx, {})
        self.assertEqual((got["id"], got["of"], got["picture"], got["_png"]), (b.id, 2, "as taken", b.png))
        self.assertEqual(H.snapshot_latest(self.ctx, {"index": 1})["id"], a.id)
        self.assertEqual(H.snapshot_latest(self.ctx, {"id": a.id})["index"], 1)
        with self.assertRaises(H.SnapshotError) as e:
            H.snapshot_latest(self.ctx, {"index": 5})
        self.assertEqual(e.exception.message, "There are 2 screenshots: index 0 to 1.")
        with self.assertRaises(H.SnapshotError):
            H.snapshot_latest(self.ctx, {"id": "gone"})

    def test_wait_times_out(self):
        t0 = time.monotonic()
        out = H.snapshot_wait(self.ctx, {"timeout": 0.05})
        self.assertFalse(out["came"])
        self.assertLess(time.monotonic() - t0, 2)

    def test_wait_wakes_on_shot(self):
        res = {}
        th = threading.Thread(target=lambda: res.update(H.snapshot_wait(self.ctx, {"timeout": 5})))
        th.start()
        time.sleep(0.05)
        s = self.st.add(shot())
        th.join(3)
        self.assertTrue(res["came"])
        self.assertEqual(res["id"], s.id)
        self.assertEqual(res["next"], "snapshot_latest shows it.")

    def test_wait_holds_while_marking_up(self):
        s = self.st.add(shot())
        res = {}
        th = threading.Thread(target=lambda: res.update(H.snapshot_wait(self.ctx, {"timeout": 5})))
        th.start()
        time.sleep(0.05)
        self.st.set_editing(s.id)
        self.st.set_marks(s.id, [ShotMark("pin", [1, 1], "#e5262b", 1)])
        time.sleep(0.1)
        self.assertEqual(res, {})
        self.st.set_editing(None)
        th.join(3)
        self.assertTrue(res["came"])
        self.assertEqual(res["marks"], 1)

    def test_notice_once(self):
        H._told["stamp"] = None
        self.assertIsNone(H.notice(self.ctx))
        self.st.add(shot(note="x"))
        line = H.notice(self.ctx)
        self.assertIn("snapshot_latest shows it", line)
        self.assertIsNone(H.notice(self.ctx))

    def test_no_tool_takes_a_shot(self):
        self.assertEqual(sorted(H.HANDLERS), ["snapshot_latest", "snapshot_list", "snapshot_wait"])


def _qt():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    for name in ("PySide6", "PySide2", "PySide"):
        try:
            mod = __import__(name, fromlist=["QtCore", "QtGui", "QtWidgets"])
            return mod
        except Exception:
            continue
    return None


QT = _qt()


@unittest.skipIf(QT is None, "Qt not installed")
class TestQt(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QT.QtWidgets.QApplication.instance() or QT.QtWidgets.QApplication([])

    def _png(self, w=400, h=200):
        img = QT.QtGui.QImage(w, h, QT.QtGui.QImage.Format_ARGB32)
        img.fill(QT.QtGui.QColor("#ffffff"))
        buf = QT.QtCore.QBuffer()
        buf.open(QT.QtCore.QIODevice.WriteOnly)
        img.save(buf, "PNG")
        return bytes(buf.data())

    def test_composite_draws(self):
        s = Shot(self._png(), 400, 200)
        s.marks = [ShotMark("box", [10, 10, 100, 100], "#e5262b"), ShotMark("pin", [200, 100], "#1877c0", 1, "here"),
                   ShotMark("arrow", [0, 0, 50, 50], "#f2b705"), ShotMark("circle", [300, 20, 380, 90], "#1877c0"),
                   ShotMark("pen", [5, 150, 50, 160, 90, 190], "#e5262b")]
        png, marked = MK.composite(s)
        self.assertTrue(marked)
        img = QT.QtGui.QImage()
        self.assertTrue(img.loadFromData(png))
        self.assertNotEqual(img.pixelColor(10, 50).name(), "#ffffff")
        self.assertEqual(MK.composite(s, original=True), (s.png, False))

    def test_card_builds(self):
        from scanrulerfc.snapshot import card as C
        st = ShotStore(save=False)
        s = st.add(Shot(self._png(), 400, 200, "Wall Thickness"))
        c = C.open_card(st, s.id)
        labels = [b.text() for b in c.findChildren(QT.QtWidgets.QPushButton) if b.text()]
        self.assertEqual(labels, ["Mark up", "Save PNG", "Copy", "Discard"])
        c.discard()
        self.assertIsNone(st.latest())


if __name__ == "__main__":
    unittest.main()
