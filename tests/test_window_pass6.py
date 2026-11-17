# SPDX-License-Identifier: AGPL-3.0-only
# Window pass 6 (round 9) of ScanRuler's panel in FreeCAD (ScanRuler by
# Stefan Hermann, CNC Kitchen): in a 332 px dock the Create Element keys
# lay over each other and the Scanner Profiles box covered its help text,
# while the panel's account read squashed 0. No Qt here: the layout
# arithmetic, the overlap check on plain rectangles, and the account read
# from stand-in widgets.
import os
import sys
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

from scanrulerfc.pages import flat2d  # noqa: E402
from scanrulerfc.pages import kit  # noqa: E402


class Size:
    def __init__(self, w, h):
        self.w, self.h = w, h

    def width(self):
        return self.w

    def height(self):
        return self.h


class Rect(Size):
    def __init__(self, x, y, w, h):
        super().__init__(w, h)
        self._x, self._y = x, y

    def x(self):
        return self._x

    def y(self):
        return self._y


class Stub:
    """A laid-out widget: geometry in its parent's coordinates."""

    def __init__(self, text, parent, rect, hint=(0, 0), wrap=False, hfw=0, shown=True):
        self._t, self._p, self._r, self._hint = text, parent, rect, hint
        self._wrap, self._hfw, self._shown = wrap, hfw, shown

    def text(self):
        return self._t

    def parentWidget(self):  # noqa: N802 (Qt)
        return self._p

    def geometry(self):
        return Rect(*self._r)

    def sizeHint(self):  # noqa: N802 (Qt)
        return Size(*self._hint)

    def isVisibleTo(self, _root):  # noqa: N802 (Qt)
        return self._shown

    def wordWrap(self):  # noqa: N802 (Qt)
        return self._wrap

    def heightForWidth(self, _w):  # noqa: N802 (Qt)
        return self._hfw


class Columns(unittest.TestCase):
    def test_a_short_width_takes_fewer_columns(self):
        # The 332 px dock: the page is about 309 px inside its scroll area.
        self.assertEqual(kit.columns_for(309, 4, 70), 2)  # under NARROW: two at most
        self.assertEqual(kit.columns_for(330, 4, 92), 3)
        self.assertEqual(kit.columns_for(330, 4, 125), 2)
        self.assertEqual(kit.columns_for(309, 4, 200), 1)
        self.assertEqual(kit.columns_for(600, 4, 92), 4)

    def test_whole_keys_fit_the_room(self):
        for width in range(120, 700, 7):
            for key_w in (64, 80, 92, 125, 180):
                cols = kit.columns_for(width, 4, key_w)
                room = width - 2 * kit.MARGIN - kit.GROUP_MARGINS[0] - kit.GROUP_MARGINS[2] - 16
                if cols > 1:
                    self.assertLessEqual(cols * key_w + (cols - 1) * kit.SPACING, room, (width, key_w))

    def test_the_grid_height_counts_every_row(self):
        n = len(flat2d.KINDS)  # Create Element: 7 keys
        self.assertEqual(kit.grid_rows(n, 4), 2)
        self.assertEqual(kit.grid_rows(n, 2), 4)
        self.assertEqual(kit.grid_rows(0, 2), 0)
        # Rows 22 px high: four of them need 100 px, not the 48 reckoned
        # for four columns (r8sr-1: rows 11 px apart).
        self.assertEqual(kit.grid_height(n, 4, 22), 48)
        self.assertEqual(kit.grid_height(n, 2, 22), 100)
        self.assertEqual(kit.grid_height(n, 1, 22, 4), 7 * 22 + 6 * 4)


class Overlap(unittest.TestCase):
    def test_rectangles(self):
        self.assertTrue(kit.overlap((0, 0, 125, 22), (0, 11, 125, 22)))
        self.assertFalse(kit.overlap((0, 0, 125, 22), (0, 22, 125, 22)))  # touching
        self.assertFalse(kit.overlap((0, 0, 125, 22), (129, 0, 125, 22)))
        self.assertTrue(kit.overlap((10, 10, 5, 5), (0, 0, 100, 100)))  # inside

    def test_only_siblings_are_compared(self):
        card, other = object(), object()
        items = [("Point", card, (0, 0, 125, 22)), ("Circle", card, (0, 11, 125, 22)),
                 ("Line", card, (129, 0, 125, 22)), ("Card", other, (0, 0, 300, 100)),
                 ("Empty", card, (0, 0, 0, 0))]
        self.assertEqual(kit.overlapping(items), [("Point", "Circle")])

    def test_short_of(self):
        self.assertTrue(kit.short_of((125, 11), (60, 22)))
        self.assertTrue(kit.short_of((50, 22), (60, 22)))
        self.assertFalse(kit.short_of((125, 22), (60, 22)))
        self.assertFalse(kit.short_of((10, 22), (-1, 22)))


class Account(unittest.TestCase):
    """measure() on the round-8 picture's geometry and on a settled one."""

    def page(self, pitch, combo_y):
        root = types.SimpleNamespace()
        card, prof = object(), object()
        keys = []
        for i, (_k, t) in enumerate(flat2d.KINDS):
            keys.append(Stub(t, card, (4 + (i % 2) * 129, 20 + (i // 2) * pitch, 125, 22), hint=(70, 22)))
        combo = Stub("Choose profile…", prof, (4, combo_y, 250, 22), hint=(120, 22))
        hint = Stub(flat2d.HINT_PROFILES, prof, (4, 44, 250, 26), wrap=True, hfw=42)
        root._grids = [[None, keys, 4, 2]]
        root._laid = [(k, "key") for k in keys] + [(combo, "field"), (hint, "text")]
        return root

    def test_the_round_8_picture_is_counted(self):
        got = kit.measure(self.page(pitch=11, combo_y=36))
        self.assertEqual(got["keys"], 7)
        self.assertEqual(got["squashed"], 0)  # each key keeps its own height …
        self.assertGreaterEqual(got["overlapping"], 5)  # … and lies over the next row
        self.assertEqual(got["clipped"], 1)  # the help text, 26 px of its 42
        self.assertIn(["Point", "Circle"], got["overlaps"])

    def test_a_settled_page_reads_clean(self):
        root = self.page(pitch=26, combo_y=18)
        root._laid[-1][0]._r = (4, 44, 250, 42)
        got = kit.measure(root)
        self.assertEqual((got["squashed"], got["clipped"], got["overlapping"]), (0, 0, 0))

    def test_a_hidden_widget_is_not_counted(self):
        root = self.page(pitch=11, combo_y=18)
        for k, _kind in root._laid:
            k._shown = False
        got = kit.measure(root)
        self.assertEqual((got["overlapping"], got["clipped"]), (0, 0))

    def test_a_squashed_key(self):
        root = self.page(pitch=26, combo_y=18)
        root._laid[-1][0]._r = (4, 44, 250, 42)
        root._laid[0][0]._r = (4, 20, 125, 11)
        self.assertEqual(kit.measure(root)["squashed"], 1)


class Settle(unittest.TestCase):
    """settle() with a stand-in page: reflow first, the minimum height from
    the fresh account, the page grown to it, then laid out and read."""

    def test_order_and_height(self):
        calls = []

        class Lay:
            def __init__(self, name):
                self.name = name

            def invalidate(self):
                calls.append(("invalidate", self.name))

            def activate(self):
                calls.append(("activate", self.name))

            def hasHeightForWidth(self):  # noqa: N802 (Qt)
                return True

            def totalHeightForWidth(self, w):  # noqa: N802 (Qt)
                calls.append(("hfw", w))
                return 900

            def totalMinimumSize(self):  # noqa: N802 (Qt)
                return Size(0, 700)

        class Card:
            def __init__(self):
                self.lay = Lay("card")

            def layout(self):
                return self.lay

            def updateGeometry(self):  # noqa: N802 (Qt)
                calls.append(("updateGeometry", "card"))

        class Root:
            def __init__(self):
                self.h, self.w, self.minh = 640, 309, 0
                self.lay = Lay("page")

            def layout(self):
                return self.lay

            def width(self):
                return self.w

            def height(self):
                return self.h

            def minimumHeight(self):  # noqa: N802 (Qt)
                return self.minh

            def setMinimumHeight(self, h):  # noqa: N802 (Qt)
                self.minh = h

            def resize(self, w, h):
                calls.append(("resize", w, h))
                self.w, self.h = w, h

        root = Root()
        root._grids, root._laid, root._layouts, root._cards = [], [], [Lay("grid")], [Card()]
        root._reflow_now = lambda w: calls.append(("reflow", w))
        self.addCleanup(kit.LAST_LAYOUT.clear)
        got = kit.settle(root, 309)
        self.assertEqual(calls[0], ("reflow", 309))
        self.assertLess(calls.index(("invalidate", "grid")), calls.index(("hfw", 309)))
        self.assertLess(calls.index(("hfw", 309)), calls.index(("resize", 309, 900)))
        self.assertEqual(calls[-1], ("activate", "card"))
        self.assertEqual((root.minh, root.h), (900, 900))
        self.assertEqual((got["minHeight"], got["height"], got["overlapping"]), (900, 900, 0))
        self.assertEqual(kit.LAST_LAYOUT["height"], 900)


if __name__ == "__main__":
    unittest.main()
