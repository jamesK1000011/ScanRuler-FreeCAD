# SPDX-License-Identifier: AGPL-3.0-only
# Ported from ScanRuler by Stefan Hermann (CNC Kitchen),
# github.com/CNCKitchen/ScanRuler: plugins/snapshot/state/shotStore.ts and
# app/capture.ts (file names).
#
# The screenshots the person took, newest first, kept in memory only (never
# in the project) until FreeCAD closes or they are discarded. An agent reads
# them only when asked to look. Every change wakes whoever waits on the
# store (snapshot_wait), through a threading.Event each.

import datetime as _dt
import itertools
import os
import threading

KEEP = 8
MARK_KINDS = ("pin", "arrow", "box", "circle", "pen")

_ids = itertools.count(1)


class ShotMark:
    """A mark the person drew on a shot, in the shot's own pixels. `pts` are
    x, y pairs: a pin's point; an arrow's tail then head; a box's or a
    circle's two corners; a pen's whole stroke."""

    __slots__ = ("kind", "pts", "color", "n", "comment")

    def __init__(self, kind, pts, color, n=None, comment=None):
        if kind not in MARK_KINDS:
            raise ValueError(f"mark kind {kind!r}: one of {', '.join(MARK_KINDS)}")
        self.kind = kind
        self.pts = [float(p) for p in pts]
        self.color = color
        self.n = n
        self.comment = comment

    def to_dict(self):
        d = {"kind": self.kind, "pts": list(self.pts), "color": self.color}
        if self.n is not None:
            d["n"] = self.n
        if self.comment is not None:
            d["comment"] = self.comment
        return d

    @classmethod
    def from_dict(cls, d):
        return cls(d["kind"], d["pts"], d["color"], d.get("n"), d.get("comment"))

    def __eq__(self, other):
        return isinstance(other, ShotMark) and self.to_dict() == other.to_dict()

    def __repr__(self):
        return f"ShotMark({self.to_dict()!r})"


class Shot:
    __slots__ = ("id", "at", "png", "width", "height", "note", "workspace", "marks", "path")

    def __init__(self, png, width, height, workspace=None, at=None, id=None, note="", marks=None):
        self.id = id or f"shot-{next(_ids)}"
        self.at = at or _dt.datetime.now().astimezone()
        self.png = png
        self.width = int(width)
        self.height = int(height)
        self.note = note
        self.workspace = workspace
        self.marks = list(marks or [])
        self.path = None

    def stamp(self):
        return f"{self.id}:{len(self.marks)}:{self.note}"


def file_name(shot, marked=False):
    """scanruler-2026-11-14_21-36-05-123.png, the original's name, in local time."""
    d = shot.at
    base = f"scanruler-{d:%Y-%m-%d_%H-%M-%S}-{d.microsecond // 1000:03d}"
    return base + ("-marked.png" if marked else ".png")


def _bool_pref(default=True):
    try:
        import FreeCAD  # noqa: F401
        p = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Mod/ScanRuler/Snapshot")
        return bool(p.GetBool("SaveBesideProject", default))
    except Exception:
        return default


class ShotStore:
    def __init__(self, keep=KEEP, save=None):
        self.keep = keep
        self.shots = []
        self.open = None
        self.editing = None
        self.save = _bool_pref() if save is None else save
        self._lock = threading.RLock()
        self._waiters = set()

    # -- change, and wake the waiters

    def _changed(self):
        for e in list(self._waiters):
            e.set()

    def add(self, shot):
        with self._lock:
            self.shots = [shot] + self.shots[: self.keep - 1]
            self.open = shot.id
        self._changed()
        return shot

    def get(self, id_):
        return next((s for s in self.shots if s.id == id_), None)

    def note(self, id_, note):
        with self._lock:
            s = self.get(id_)
            if s:
                s.note = note.strip()
        self._changed()

    def set_marks(self, id_, marks):
        with self._lock:
            s = self.get(id_)
            if s:
                s.marks = list(marks)
        self._changed()

    def saved(self, id_, path):
        s = self.get(id_)
        if s:
            s.path = path

    def set_save(self, on):
        self.save = bool(on)
        try:
            import FreeCAD
            FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Mod/ScanRuler/Snapshot").SetBool("SaveBesideProject", self.save)
        except Exception:
            pass

    def set_editing(self, id_):
        self.editing = id_
        self._changed()

    def remove(self, id_):
        with self._lock:
            self.shots = [s for s in self.shots if s.id != id_]
            if self.open == id_:
                self.open = None
            if self.editing == id_:
                self.editing = None
        self._changed()

    def clear(self):
        with self._lock:
            self.shots = []
            self.open = self.editing = None
        self._changed()

    def latest(self):
        return self.shots[0] if self.shots else None

    # -- waiting

    def wait_next(self, timeout):
        """Block until the newest shot is new, or its marks or note changed,
        and it is not open in the mark-up view; the shot, or None after
        `timeout` seconds."""
        import time
        before = self.shots[0].stamp() if self.shots else ""
        ev = threading.Event()
        self._waiters.add(ev)
        try:
            end = time.monotonic() + timeout
            while True:
                top = self.shots[0] if self.shots else None
                if top and top.stamp() != before and self.editing != top.id:
                    return top
                left = end - time.monotonic()
                if left <= 0:
                    return None
                ev.wait(left)
                ev.clear()
        finally:
            self._waiters.discard(ev)

    # -- saving beside the project

    def save_beside(self, shot, folder, png=None):
        """Write the shot (marks drawn in, when `png` carries them) to
        <folder>/shots/ and remember where."""
        d = os.path.join(folder, "shots")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, file_name(shot))
        with open(path, "wb") as f:
            f.write(png if png is not None else shot.png)
        self.saved(shot.id, path)
        return path


STORE = ShotStore()
