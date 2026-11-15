# SPDX-License-Identifier: AGPL-3.0-only
# Ported from ScanRuler by Stefan Hermann (CNC Kitchen),
# github.com/CNCKitchen/ScanRuler: plugins/snapshot/app/marks.ts and
# ui/ShotEditor.tsx (the tools, keys and colours).
#
# The person's marks on a shot: the mark-up model the editor drives (tool,
# colour, numbered pins with comments, arrows, boxes, circles, pen strokes,
# undo), and the drawing of them onto the picture the agent gets, each line
# thick enough to read on a picture of the whole window. Drawing uses Qt's
# QPainter when Qt is there; without it the picture stays as taken.

import math

from .store import ShotMark

TOOLS = (("pin", "Pin", "P"), ("arrow", "Arrow", "A"), ("box", "Box", "B"), ("circle", "Circle", "C"), ("pen", "Pen", "D"))
COLOURS = ("#e5262b", "#f2b705", "#1877c0")
DONE_HINT = "Done keeps the marks with the shot and tells the agent. The shot underneath is kept as taken."


def stroke_for(width):
    """Line width for a picture this wide."""
    return max(2, int(math.floor(width / 420 + 0.5)))


def tool_for_key(key):
    k = key.upper()
    return next((t for t, _l, kk in TOOLS if kk == k), None)


class MarkUp:
    """What the mark-up view holds while the person draws: the marks so far
    (starting from the shot's), the tool and colour, a draft being dragged,
    and the note. Done hands back marks and note; nothing touches the shot
    before that."""

    def __init__(self, marks=(), note="", tool="pin", colour=COLOURS[0]):
        self.marks = [m if isinstance(m, ShotMark) else ShotMark.from_dict(m) for m in marks]
        self.note = note
        self.tool = tool
        self.colour = colour
        self.draft = None

    # -- choosing

    def set_tool(self, tool):
        if tool not in [t for t, _l, _k in TOOLS]:
            raise ValueError(f"tool {tool!r}")
        self.tool = tool

    def key(self, key, ctrl=False):
        """A key press in the view: Ctrl/Cmd+Z undoes, P A B C D pick a tool.
        True when the key was used."""
        if ctrl and key.lower() == "z":
            self.undo()
            return True
        t = tool_for_key(key)
        if t:
            self.tool = t
            return True
        return False

    def set_colour(self, c):
        self.colour = c

    # -- drawing

    def pins(self):
        return [m for m in self.marks if m.kind == "pin"]

    def next_pin(self):
        return max((m.n or 0 for m in self.pins()), default=0) + 1

    def press(self, x, y):
        """Pointer down at (x, y), in shot pixels. A pin lands at once."""
        if self.tool == "pin":
            m = ShotMark("pin", [x, y], self.colour, self.next_pin(), "")
            self.marks.append(m)
            return m
        self.draft = ShotMark(self.tool, [x, y, x, y], self.colour)
        return self.draft

    def move(self, x, y):
        d = self.draft
        if not d:
            return
        if d.kind == "pen":
            d.pts.extend([float(x), float(y)])
        else:
            d.pts[2], d.pts[3] = float(x), float(y)

    def release(self, x=None, y=None):
        d = self.draft
        self.draft = None
        if not d:
            return None
        if x is not None:
            if d.kind == "pen":
                d.pts.extend([float(x), float(y)])
            else:
                d.pts[2], d.pts[3] = float(x), float(y)
        if d.kind == "pen" and len(d.pts) < 4:
            return None
        if d.kind != "pen" and abs(d.pts[2] - d.pts[0]) < 1 and abs(d.pts[3] - d.pts[1]) < 1:
            return None
        self.marks.append(d)
        return d

    def add(self, mark):
        self.marks.append(mark if isinstance(mark, ShotMark) else ShotMark.from_dict(mark))

    def comment(self, n, text):
        for m in self.pins():
            if m.n == n:
                m.comment = text

    def remove_pin(self, n):
        self.marks = [m for m in self.marks if not (m.kind == "pin" and m.n == n)]

    def undo(self):
        if self.marks:
            return self.marks.pop()
        return None

    def visible(self):
        return self.marks + ([self.draft] if self.draft else [])

    # -- out

    def to_dict(self):
        return {"marks": [m.to_dict() for m in self.marks], "note": self.note, "tool": self.tool, "colour": self.colour}

    @classmethod
    def from_dict(cls, d):
        return cls(d.get("marks", ()), d.get("note", ""), d.get("tool", "pin"), d.get("colour", COLOURS[0]))

    def done(self, store, shot_id):
        """Keep the marks and note with the shot (which wakes scan_snapshot_wait)."""
        store.set_marks(shot_id, self.marks)
        store.note(shot_id, self.note)
        if store.editing == shot_id:
            store.set_editing(None)


def pins_of(shot):
    """The numbered pins and their comments, where they are in the picture,
    in pixels and as a share of its width and height."""
    out = []
    for m in shot.marks:
        if m.kind != "pin":
            continue
        x, y = m.pts[0], m.pts[1]
        out.append({"n": m.n, "comment": m.comment or "", "x": int(math.floor(x + 0.5)), "y": int(math.floor(y + 0.5)),
                    "at": f"{int(math.floor(x / shot.width * 100 + 0.5))}% across, {int(math.floor(y / shot.height * 100 + 0.5))}% down"})
    return out


# ---------------------------------------------------------------- Qt

def qt():
    """(QtCore, QtGui) from FreeCAD's PySide shim, PySide6 or PySide2; None
    without Qt."""
    for name in ("PySide", "PySide6", "PySide2"):
        try:
            mod = __import__(name, fromlist=["QtCore", "QtGui"])
            return mod.QtCore, mod.QtGui
        except Exception:
            continue
    return None


def draw_marks(painter, marks, width):
    """Draw `marks` with a QPainter already on the picture, in its pixels."""
    QtCore, QtGui = qt()
    lw = stroke_for(width)
    P = QtCore.QPointF
    for m in marks:
        col = QtGui.QColor(m.color)
        pen = QtGui.QPen(col, lw)
        pen.setCapStyle(QtCore.Qt.RoundCap)
        pen.setJoinStyle(QtCore.Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(QtCore.Qt.NoBrush)
        p = m.pts
        if m.kind == "pen" and len(p) >= 4:
            path = QtGui.QPainterPath(P(p[0], p[1]))
            for i in range(2, len(p) - 1, 2):
                path.lineTo(P(p[i], p[i + 1]))
            painter.drawPath(path)
        elif m.kind == "box" and len(p) >= 4:
            painter.drawRect(QtCore.QRectF(min(p[0], p[2]), min(p[1], p[3]), abs(p[2] - p[0]), abs(p[3] - p[1])))
        elif m.kind == "circle" and len(p) >= 4:
            painter.drawEllipse(P((p[0] + p[2]) / 2, (p[1] + p[3]) / 2), abs(p[2] - p[0]) / 2 or 1, abs(p[3] - p[1]) / 2 or 1)
        elif m.kind == "arrow" and len(p) >= 4:
            x0, y0, x1, y1 = p[:4]
            a = math.atan2(y1 - y0, x1 - x0)
            h = lw * 6
            painter.drawLine(P(x0, y0), P(x1 - math.cos(a) * h * 0.6, y1 - math.sin(a) * h * 0.6))
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(col)
            painter.drawPolygon(QtGui.QPolygonF([P(x1, y1), P(x1 - math.cos(a - 0.45) * h, y1 - math.sin(a - 0.45) * h),
                                                 P(x1 - math.cos(a + 0.45) * h, y1 - math.sin(a + 0.45) * h)]))
        elif m.kind == "pin" and len(p) >= 2:
            r = lw * 6
            painter.setBrush(col)
            painter.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), max(1, lw * 0.6)))
            painter.drawEllipse(P(p[0], p[1]), r, r)
            f = QtGui.QFont()
            f.setBold(True)
            f.setPixelSize(max(1, int(round(r * 1.15))))
            painter.setFont(f)
            painter.drawText(QtCore.QRectF(p[0] - r, p[1] - r, 2 * r, 2 * r), QtCore.Qt.AlignCenter, str(m.n or ""))
            if m.comment:
                size = max(1, int(round(r * 0.95)))
                f2 = QtGui.QFont()
                f2.setWeight(QtGui.QFont.DemiBold)
                f2.setPixelSize(size)
                painter.setFont(f2)
                text = m.comment if len(m.comment) <= 80 else m.comment[:79] + "…"
                w = QtGui.QFontMetricsF(f2).horizontalAdvance(text) + size if hasattr(QtGui.QFontMetricsF, "horizontalAdvance") else QtGui.QFontMetricsF(f2).width(text) + size
                x = min(p[0] + r * 1.4, width - w - 4)
                y = p[1] - size * 0.8
                painter.setBrush(QtGui.QColor(255, 255, 255, 240))
                painter.setPen(QtGui.QPen(col, max(1, lw * 0.5)))
                painter.drawRect(QtCore.QRectF(x, y, w, size * 1.6))
                painter.setPen(QtGui.QColor("#111111"))
                painter.drawText(QtCore.QRectF(x + size / 2, y, w, size * 1.6), QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft, text)


def composite(shot, original=False):
    """(png bytes, marked) — the shot with its marks drawn in when it has
    any and Qt is there; else the shot as taken."""
    if original or not shot.marks:
        return shot.png, False
    q = qt()
    if q is None:
        return shot.png, False
    QtCore, QtGui = q
    img = QtGui.QImage()
    if not img.loadFromData(shot.png):
        return shot.png, False
    img = img.convertToFormat(QtGui.QImage.Format_ARGB32)
    painter = QtGui.QPainter(img)
    try:
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        draw_marks(painter, shot.marks, shot.width)
    finally:
        painter.end()
    buf = QtCore.QBuffer()
    buf.open(QtCore.QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data()), True
