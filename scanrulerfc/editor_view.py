# SPDX-License-Identifier: AGPL-3.0-only
# Ported from ScanRuler by Stefan Hermann (CNC Kitchen),
# github.com/CNCKitchen/ScanRuler: src/viewer/extendGrips.ts (a plugin's
# grips: arrows and rings held at a size on the screen, dragged along their
# line or round their axis, the number field on the grip in the hand) and
# plugins/reverse/viewer/reScene.ts (setBodyPreview, setBodyPreviewStretch:
# the ghost of a feature being set up).
#
# The Reverse engineer's feature editor in FreeCAD's 3D view: the ghost of
# the feature being set up, its grips and the field on the grip in the hand,
# drawn with Coin nodes added to the view's scene graph (as Agent Link's
# Pins and Stage are) and taken away when the editor closes. The editor's
# state is reverse/editor.py; this draws it and hands it the drags.
#
# Picking leaves the person's navigation alone: the view's event callbacks
# only look, and a press is taken (setHandled) only on a grip. While the
# cursor is over a grip the view's events go to the scene graph
# (redirectToSceneGraph), so the navigation style does not start an orbit
# under the hand — the original's claimDrag — and they go back the moment
# the cursor leaves the grip or the drag ends.
#
# The top half is pure (screen maths, the grips' geometry, the field's
# place); the Overlay takes the coin module, the Qt module and the view as
# arguments, so the tests drive it with stand-ins and never with whatever
# pivy or PySide is importable.

import math
import time

from .reverse import ghost as GH
from .reverse import grips as G
from .reverse.move import matrix4_of
from .reverse.preview import prism_stretch
from .reverse.vec import add_scaled, cross, dot, normalize, sub

# How near a grip the cursor has to be to take it, in screen pixels.
PICK_PX = 8
# A press let go within this many pixels is a click, not a drag of the view.
CLICK_PX = 4
# How far the number field stands off its arrow's tip, in pixels.
FIELD_GAP_PX = 6
# The ghost is built again once the hand has rested this long on a drag.
GHOST_REST_S = 0.25
TICK_MS = 50
RING_SEGMENTS = 64
GRIP_LIT = "#ffb000"
# The ghost: see-through for a tool body, solid for a body as a feature on
# it would leave it (reScene's opacity 0.45).
GHOST_TRANSPARENCY = 0.55


def rgb(hex_color):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


# ---- screen maths (pure) -------------------------------------------------------------------------


def perpendicular_to(d):
    """A unit vector square to d."""
    ref = [1, 0, 0] if abs(d[0]) < 0.9 else [0, 1, 0]
    return normalize(cross(d, ref))


def param_along(origin, d, ray_o, ray_d):
    """Where the pointer's ray comes nearest a grip's line, in millimetres
    from origin along d (both unit). None when the two run within a few
    degrees of parallel: looking down the arrow, holding still is the honest
    answer."""
    b = dot(d, ray_d)
    denom = 1 - b * b
    if abs(denom) < 1e-3:
        return None
    w = sub(origin, ray_o)
    return (b * dot(w, ray_d) - dot(w, d)) / denom


def angle_around(pivot, axis, b1, b2, ray_o, ray_d):
    """Where the pointer is round a ring's axis, radians in the (b1, b2)
    basis; None with the ring seen edge on."""
    denom = dot(ray_d, axis)
    if abs(denom) < 0.1:
        return None
    t = dot(sub(pivot, ray_o), axis) / denom
    w = sub(add_scaled(ray_o, ray_d, t), pivot)
    if dot(w, w) < 1e-24:
        return None
    return math.atan2(dot(w, b2), dot(w, b1))


def short_step(a, last):
    """The step from last to a, taken the short way round."""
    s = a - last
    if s > math.pi:
        s -= 2 * math.pi
    elif s < -math.pi:
        s += 2 * math.pi
    return s


def grip_shape(g, mm_per_px):
    """A grip's geometry in millimetres at the view's zoom: an arrow's base
    and tip, or a ring's centre, axis and radius."""
    scale = mm_per_px if g.get("pixels") else 1.0
    d = normalize(g["dir"]) or [0, 0, 1]
    if g["shape"] == "ring":
        return {"side": g["side"], "shape": "ring", "centre": list(g["position"]), "axis": d, "radius": g["size"] * scale, "color": g.get("color")}
    base = add_scaled(g["position"], d, (g.get("standoff") or 0) * scale)
    return {"side": g["side"], "shape": "arrow", "base": base, "tip": add_scaled(base, d, g["size"] * scale), "dir": d, "length": g["size"] * scale, "color": g.get("color")}


def ring_points(centre, axis, radius, n=RING_SEGMENTS):
    b1 = perpendicular_to(axis) or [1, 0, 0]
    b2 = cross(axis, b1)
    return [add_scaled(add_scaled(centre, b1, radius * math.cos(2 * math.pi * i / n)), b2, radius * math.sin(2 * math.pi * i / n)) for i in range(n + 1)]


def _seg_dist(p, a, b):
    ax, ay = b[0] - a[0], b[1] - a[1]
    ll = ax * ax + ay * ay
    t = 0.0 if ll < 1e-12 else max(0.0, min(1.0, ((p[0] - a[0]) * ax + (p[1] - a[1]) * ay) / ll))
    x, y = a[0] + ax * t - p[0], a[1] + ay * t - p[1]
    return math.hypot(x, y)


def grip_at(screen, x, y, tol=PICK_PX):
    """The side of the grip nearest the pointer within tol pixels, or None.
    `screen`: [{side, points: [(x, y), …]}], each grip's line on the screen
    (an arrow's base and tip, a ring's loop)."""
    best, side = tol, None
    for g in screen:
        pts = g["points"]
        for i in range(max(1, len(pts) - 1)):
            dd = _seg_dist((x, y), pts[i], pts[min(i + 1, len(pts) - 1)])
            if dd <= best:
                best, side = dd, g["side"]
    return side


def field_place(anchor, along, size, gap=FIELD_GAP_PX):
    """Where the field's top-left corner goes (Qt's pixels, y down), standing
    off an arrow's tip the way the tip points on the screen so it covers none
    of the arrow — or centred on a ring's middle (along None). `along` is the
    arrow's direction on the screen, y down; `size` the field's (w, h)."""
    w, h = size
    if along is None:
        return anchor[0] - w / 2, anchor[1] - h / 2
    x, y = along[0], -along[1]  # up is positive, as the original reads it
    m = max(abs(x), abs(y))
    if m < 0.2:
        x, y = 1.0, 0.0
    else:
        x, y = x / m, y / m
    n = math.hypot(along[0], along[1]) or 1.0
    ax, ay = anchor[0] + along[0] / n * gap, anchor[1] + along[1] / n * gap
    cx, cy = 0.5 - x / 2, 0.5 + y / 2
    return ax - cx * w, ay - cy * h


def stretch_key(record):
    """What a straight extrude's ghost is built from but its numbers: a ghost
    built from the same can be stretched to new numbers at once."""
    r = {k: v for k, v in (record or {}).items() if k not in ("name", "extent", "exprs")}
    return repr(r)


def prism_frame(record, features):
    """(origin, normal) a straight extrude's numbers run along: its sketch's
    plane, or the face it pulls."""
    if not record or record.get("kind") != "extrude":
        return None
    if record.get("face"):
        fp = record["face"].get("face") or record["face"]
        fp = fp.get("fingerprint", fp)
        n = normalize(fp["dir"])
        return (fp["centroid"], n) if n else None
    sk = next((f for f in features if f.get("kind") == "sketch" and f.get("id") == record.get("sketchId")), None)
    if not sk or not sk.get("frame"):
        return None
    return sk["frame"]["origin"], sk["frame"]["normal"]


# ---- FreeCAD's view, read through whichever names its version has ---------------------------------------


def _call(view, names, *args):
    for n in names:
        fn = getattr(view, n, None)
        if fn is not None:
            return fn(*args)
    raise AttributeError(names[0])


def project(view, p, vector):
    """A point of the part on the view, in its viewport's pixels (y up)."""
    got = _call(view, ("getPointOnViewport", "getPointOnScreen"), vector(*p))
    return float(got[0]), float(got[1])


def pick_ray(view, x, y):
    """The pointer's ray at viewport pixels (x, y): (origin, unit direction)."""
    near, far = _call(view, ("projectPointToLine",), int(x), int(y))
    o = [near.x, near.y, near.z]
    d = normalize([far.x - near.x, far.y - near.y, far.z - near.z])
    if d is None:
        v = view.getViewDirection()
        d = normalize([v.x, v.y, v.z]) or [0, 0, -1]
    return o, d


def mm_per_pixel(view, at, vector):
    """Millimetres one viewport pixel spans at a point of the part."""
    v = view.getViewDirection()
    u = perpendicular_to(normalize([v.x, v.y, v.z]) or [0, 0, 1])
    a = project(view, at, vector)
    b = project(view, add_scaled(at, u, 1.0), vector)
    px = math.hypot(b[0] - a[0], b[1] - a[1])
    return 1.0 / px if px > 1e-9 else 1.0


def object_at(view, x, y):
    """What lies under viewport pixels (x, y): {doc, object, element, point},
    or None. Read through the view's own pick, which selects nothing."""
    try:
        info = view.getObjectInfo((int(x), int(y)))
    except Exception:  # noqa: BLE001
        return None
    if not info or "x" not in info:
        return None
    return {"doc": info.get("Document"), "object": info.get("Object"), "element": info.get("Component") or "",
            "point": [float(info["x"]), float(info["y"]), float(info["z"])]}


def redirect(view, on):
    """The view's events to the scene graph (True) or back to the navigation
    style; quietly nothing where the view has no such call."""
    for n in ("redirectToSceneGraph", "setRedirectToSceneGraph"):
        fn = getattr(view, n, None)
        if fn is not None:
            try:
                fn(bool(on))
                return True
            except Exception:  # noqa: BLE001
                return False
    return False


def view_widget(view, qt):
    """The Qt widget the 3D view draws in (its graphics view's viewport),
    which the field is put on; None where it cannot be found."""
    try:
        gv = view.graphicsView()
        return gv.viewport() if hasattr(gv, "viewport") else gv
    except Exception:  # noqa: BLE001 — an older view: no field, the panel's numbers still work
        return None


# ---- the overlay ------------------------------------------------------------------------------------


class Field:
    """The number field on the grip in the hand: a line edit and its unit,
    floating on the 3D view. Enter commits, Escape closes."""

    def __init__(self, qt, parent, on_commit, on_close):
        QtWidgets, QtCore, QtGui = qt.QtWidgets, qt.QtCore, qt.QtGui
        self.frame = QtWidgets.QFrame(parent)
        self.frame.setObjectName("ScanRulerGripField")
        lay = QtWidgets.QHBoxLayout(self.frame)
        lay.setContentsMargins(4, 1, 4, 1)
        lay.setSpacing(3)
        self.edit = QtWidgets.QLineEdit()
        self.edit.setMaximumWidth(90)
        self.edit.setToolTip("The number this grip drags — type a value and press Enter; Escape closes the field")
        self.unit = QtWidgets.QLabel()
        lay.addWidget(self.edit)
        lay.addWidget(self.unit)
        self.frame.setAutoFillBackground(True)
        self.edit.returnPressed.connect(lambda: on_commit(self.edit.text().strip()))
        shortcut = getattr(QtGui, "QShortcut", None) or QtWidgets.QShortcut  # Qt 6 moved it to QtGui
        self.escape = shortcut(QtGui.QKeySequence(QtCore.Qt.Key_Escape), self.edit)
        self.escape.setContext(QtCore.Qt.WidgetShortcut)
        self.escape.activated.connect(on_close)
        self.frame.hide()
        self.shown = None

    def show(self, text, unit, place, read_only, tip=None):
        if not self.edit.hasFocus() and self.edit.text() != text:
            self.edit.setText(text)
        self.unit.setText(unit)
        self.edit.setReadOnly(read_only)
        if tip:
            self.edit.setToolTip(tip)
        self.frame.adjustSize()
        x, y = place(self.frame.width(), self.frame.height())
        self.frame.move(int(round(x)), int(round(y)))
        self.frame.show()
        self.frame.raise_()
        self.shown = text

    def focus(self):
        self.edit.setFocus()
        self.edit.selectAll()

    def hide(self):
        self.frame.hide()
        self.shown = None

    def remove(self):
        self.frame.hide()
        self.frame.deleteLater()


class Overlay:
    """The editor drawn in one 3D view. `coin` is pivy's coin module, `qt`
    a module with QtWidgets, QtCore and QtGui (or None: no field), `view`
    FreeCAD's 3D view, `vector` FreeCAD.Vector. `env` gives what the view
    reads off the document: store() (reverse/handlers DocStore), features(),
    bodies(), units(), scope() (the parameters' values) and hide(ids, on)
    for the bodies a ghost stands in for."""

    def __init__(self, editor, view, coin, qt=None, vector=None, env=None):
        self.editor, self.view, self.coin, self.qt = editor, view, coin, qt
        self.vector = vector or (lambda x, y, z: _Vec(x, y, z))
        self.env = env or {}
        self.root = coin.SoSeparator()
        self.root.setName("ScanRulerEditor")
        self.ghost_sep = coin.SoSeparator()
        self.grip_sep = coin.SoAnnotation()
        self.root.addChild(self.ghost_sep)
        self.root.addChild(self.grip_sep)
        self.stretch_node = None
        self.ghost_drawn = None
        self.ghost_base = None
        self.hidden = []
        self.shapes = []
        self.screen = []
        self.lit = None
        self.held = None
        self.pressed_at = None
        self.redirected = False
        self.drawn = None
        self.changed_at = 0.0
        self.callbacks = []
        self.attached = None
        self.dpr = 1.0
        self.field = None
        self._field_tried = False
        self.attach()

    # ---- the view
    def attach(self):
        sg = self.view.getSceneGraph()
        sg.addChild(self.root)
        self.attached = sg
        c = self.coin
        for t in (c.SoLocation2Event, c.SoMouseButtonEvent):
            cb = self.view.addEventCallbackPivy(t.getClassTypeId(), self.on_event)
            self.callbacks.append((t, cb))

    def detach(self):
        for t, cb in self.callbacks:
            try:
                self.view.removeEventCallbackPivy(t.getClassTypeId(), cb)
            except Exception:  # noqa: BLE001 — the view may be gone already
                pass
        self.callbacks = []
        if self.redirected:
            redirect(self.view, False)
            self.redirected = False
        if self.attached is not None:
            try:
                self.attached.removeChild(self.root)
            except Exception:  # noqa: BLE001
                pass
            self.attached = None
        self._hide_bodies([])
        if self.field is not None:
            self.field.remove()
            self.field = None

    def _field(self):
        if self.field is None and not self._field_tried and self.qt is not None:
            self._field_tried = True
            w = view_widget(self.view, self.qt)
            if w is not None:
                self.field = Field(self.qt, w, self.commit_field, self.editor.close_field)
                try:
                    self.dpr = float(w.devicePixelRatioF())
                except Exception:  # noqa: BLE001
                    self.dpr = 1.0
        return self.field

    # ---- one tick: the grips at the zoom, the field, the ghost
    def tick(self, now=None):
        ed = self.editor
        if not ed.open:
            return
        now = time.monotonic() if now is None else now
        feats = self.env.get("features", lambda: [])()
        grips = ed.grips(feats, self.env.get("context", lambda: None)())
        centre = grips[0]["position"] if grips else None
        mmpp = mm_per_pixel(self.view, centre, self.vector) if centre is not None else 1.0
        key = (ed.version, round(mmpp, 9), self.lit, self.held is not None)
        if key != self.drawn:
            self.drawn = key
            self.shapes = [grip_shape(g, mmpp * self.dpr) for g in grips]
            self.draw_grips()
            self.place_field()
        self.ghost_step(now, feats)

    def ghost_step(self, now, feats):
        ed = self.editor
        if not ed.needs_ghost():
            return
        # A straight extrude dragged: the ghost that is up stretched to the
        # new numbers at once, the kernel's answer awaited for the rest.
        prism = ed.prism()
        base = self.ghost_base
        if prism and base and base[0] == stretch_key(ed.record):
            frame = prism_frame(ed.record, feats)
            m = prism_stretch(frame[0], frame[1], base[1], base[2], prism[0], prism[1]) if frame else None
            if m and self.stretch_node is not None:
                self.stretch_node.matrix.setValue(self.coin.SbMatrix(*matrix4_of(m)))
        if ed.dragging and now - self.changed_at < GHOST_REST_S:
            return
        self.build_ghost(feats)

    def build_ghost(self, feats=None):
        ed = self.editor
        store = self.env.get("store", lambda: None)()
        if store is None:
            ed.set_ghost({"status": "failed", "message": "No document is open."})
        else:
            answer = GH.ghost(store, ed.record, ed.editing)
            ed.set_ghost(GH.dressed(answer, ed.record, ed.next_id, self.env.get("bodies", lambda: [])()))
        prism = ed.prism()
        self.ghost_base = (stretch_key(ed.record), prism[0], prism[1]) if prism and ed.ghost.get("status") == "ok" else None
        self.draw_ghost()

    # ---- drawing
    def draw_ghost(self):
        c = self.coin
        self.ghost_sep.removeAllChildren()
        self.stretch_node = None
        g = self.editor.ghost if self.editor.open else None
        if not g or g.get("status") != "ok" or not g["mesh"]["indices"]:
            self._hide_bodies([])
            return
        holder = c.SoAnnotation() if g.get("through") else c.SoSeparator()
        holder.addChild(self._unpickable())
        # A box that picks on the body (a fillet's edges, a shell's faces)
        # leaves the body in sight, the ghost see-through over it: a body
        # FreeCAD hides cannot be clicked, where the original's could.
        from .reverse.picks import PICKS

        solid = g.get("solid") and (self.editor.record or {}).get("kind") not in PICKS
        self.stretch_node = c.SoMatrixTransform()
        holder.addChild(self.stretch_node)
        mat = c.SoMaterial()
        mat.diffuseColor.setValue(*rgb(g["color"]))
        mat.transparency.setValue(0.0 if solid else GHOST_TRANSPARENCY)
        holder.addChild(mat)
        hints = c.SoShapeHints()
        hints.vertexOrdering.setValue(c.SoShapeHints.COUNTERCLOCKWISE)
        hints.shapeType.setValue(c.SoShapeHints.UNKNOWN_SHAPE_TYPE)
        holder.addChild(hints)
        m = g["mesh"]
        p = m["positions"]
        coords = c.SoCoordinate3()
        coords.point.setValues(0, len(p) // 3, [p[i:i + 3] for i in range(0, len(p) - 2, 3)])
        holder.addChild(coords)
        if "normals" in m:
            nn = m["normals"]
            normals = c.SoNormal()
            normals.vector.setValues(0, len(nn) // 3, [nn[i:i + 3] for i in range(0, len(nn) - 2, 3)])
            holder.addChild(normals)
            binding = c.SoNormalBinding()
            binding.value.setValue(c.SoNormalBinding.PER_VERTEX_INDEXED)
            holder.addChild(binding)
        ix = m["indices"]
        faces = c.SoIndexedFaceSet()
        flat = []
        for i in range(0, len(ix) - 2, 3):
            flat += [ix[i], ix[i + 1], ix[i + 2], -1]
        faces.coordIndex.setValues(0, len(flat), flat)
        if "normals" in m:
            faces.normalIndex.setValues(0, len(flat), flat)
        holder.addChild(faces)
        self.ghost_sep.addChild(holder)
        self._hide_bodies((g.get("replaces") or []) if solid else [])

    def _unpickable(self):
        """The ghost and the grips are not the part: a click goes through
        them to what is under them (the grips are hit on the screen)."""
        c = self.coin
        ps = c.SoPickStyle()
        ps.style.setValue(c.SoPickStyle.UNPICKABLE)
        return ps

    def _hide_bodies(self, ids):
        fn = self.env.get("hide")
        if fn is None or list(ids) == self.hidden:
            return
        if self.hidden:
            fn(self.hidden, False)
        self.hidden = list(ids)
        if self.hidden:
            fn(self.hidden, True)

    def _color(self, s):
        if s["side"] in (self.lit, self.held and self.held["side"]):
            return rgb(GRIP_LIT)
        if s.get("color"):
            return rgb(s["color"])
        g = self.editor.ghost or {}
        return rgb(g.get("color") or "#1877c0")

    def draw_grips(self):
        c = self.coin
        self.grip_sep.removeAllChildren()
        self.screen = []
        light = c.SoLightModel()
        light.model.setValue(c.SoLightModel.BASE_COLOR)
        self.grip_sep.addChild(light)
        self.grip_sep.addChild(self._unpickable())
        for s in self.shapes:
            sep = c.SoSeparator()
            col = c.SoBaseColor()
            col.rgb.setValue(*self._color(s))
            sep.addChild(col)
            style = c.SoDrawStyle()
            style.lineWidth.setValue(3)
            sep.addChild(style)
            if s["shape"] == "ring":
                pts = ring_points(s["centre"], s["axis"], s["radius"])
            else:
                shaft_end = add_scaled(s["base"], s["dir"], s["length"] * 0.7)
                pts = [s["base"], shaft_end]
            coords = c.SoCoordinate3()
            coords.point.setValues(0, len(pts), pts)
            sep.addChild(coords)
            line = c.SoLineSet()
            line.numVertices.setValue(len(pts))
            sep.addChild(line)
            if s["shape"] == "arrow":
                head = c.SoTransform()
                head.translation.setValue(*add_scaled(s["base"], s["dir"], s["length"] * 0.85))
                head.rotation.setValue(c.SbRotation(c.SbVec3f(0, 1, 0), c.SbVec3f(*s["dir"])))
                sep.addChild(head)
                cone = c.SoCone()
                cone.height.setValue(s["length"] * 0.3)
                cone.bottomRadius.setValue(s["length"] * 0.12)
                sep.addChild(cone)
            self.grip_sep.addChild(sep)
            try:
                self.screen.append({"side": s["side"], "points": [project(self.view, q, self.vector) for q in (pts[::4] if s["shape"] == "ring" else [s["base"], s["tip"]])]})
            except Exception:  # noqa: BLE001 — a grip off the view cannot be taken
                pass

    def place_field(self):
        ed = self.editor
        f = ed.field_value()
        shape = next((s for s in self.shapes if s["side"] == ed.field), None)
        field = self._field() if f and shape else self.field
        if field is None:
            return
        if not f or not shape:
            field.hide()
            return
        units = self.env.get("units", lambda: "mm")()
        try:
            height = float(self.view.getSize()[1])
        except Exception:  # noqa: BLE001
            height = 0.0
        dpr = self.dpr or 1.0

        def qt_point(p):
            x, y = project(self.view, p, self.vector)
            return x / dpr, (height - y) / dpr

        if shape["shape"] == "ring":
            anchor, along = qt_point(shape["centre"]), None
        else:
            tip, base = qt_point(shape["tip"]), qt_point(shape["base"])
            anchor, along = tip, (tip[0] - base[0], tip[1] - base[1])
        tip_text = f"{f['expr']} = {G.field_text({**f, 'expr': None}, units)} {G.unit_word(f['unit'], units)}" if f.get("expr") else None
        field.show(G.field_text(f, units), G.unit_word(f["unit"], units), lambda w, h: field_place(anchor, along, (w, h)), ed.dragging, tip_text)

    # ---- the hand
    def on_event(self, cb):
        c = self.coin
        ev = cb.getEvent()
        x, y = ev.getPosition().getValue()
        if ev.isOfType(c.SoMouseButtonEvent.getClassTypeId()):
            modified = ev.wasShiftDown() or ev.wasCtrlDown()
            if c.SoMouseButtonEvent.isButtonPressEvent(ev, c.SoMouseButtonEvent.BUTTON1):
                if self.press(x, y, modified):
                    cb.setHandled()
                elif not modified:
                    # Watched only: the navigation keeps the press, and a
                    # release close by is a click on the part.
                    self.pressed_at = (x, y)
            elif c.SoMouseButtonEvent.isButtonReleaseEvent(ev, c.SoMouseButtonEvent.BUTTON1):
                if self.release(x, y):
                    cb.setHandled()
                elif self.pressed_at is not None:
                    was, self.pressed_at = self.pressed_at, None
                    if math.hypot(x - was[0], y - was[1]) <= CLICK_PX * (self.dpr or 1.0) and self.click(x, y):
                        cb.setHandled()
            return
        if self.motion(x, y):
            cb.setHandled()

    def motion(self, x, y):
        """The pointer moved: a held grip dragged, else the grip under it lit
        and the view's events kept from the navigation while one is."""
        if self.held is not None:
            self.drag_to(x, y)
            return True
        side = grip_at(self.screen, x, y, PICK_PX * (self.dpr or 1.0))
        if side != self.lit:
            self.lit = side
            self.drawn = None
            self.tick()
        want = side is not None
        if want != self.redirected:
            redirect(self.view, want)
            self.redirected = want
        return False

    def press(self, x, y, modified=False):
        if modified or self.lit is None or not self.editor.open:
            return False
        s = next((g for g in self.shapes if g["side"] == self.lit), None)
        if s is None:
            return False
        o, d = pick_ray(self.view, x, y)
        if s["shape"] == "ring":
            b1 = perpendicular_to(s["axis"]) or [1, 0, 0]
            b2 = cross(s["axis"], b1)
            a = angle_around(s["centre"], s["axis"], b1, b2, o, d)
            if a is None:
                return False
            self.held = {"side": s["side"], "ring": (s["centre"], s["axis"], b1, b2), "last": a, "turned": 0.0}
        else:
            t = param_along(s["base"], s["dir"], o, d)
            if t is None:
                return False
            self.held = {"side": s["side"], "line": (s["base"], s["dir"]), "start": t}
        self.editor.grip_drag(s["side"], 0, "start")
        self.changed_at = time.monotonic()
        return True

    def drag_to(self, x, y):
        h = self.held
        o, d = pick_ray(self.view, x, y)
        if "ring" in h:
            centre, axis, b1, b2 = h["ring"]
            a = angle_around(centre, axis, b1, b2, o, d)
            if a is None:
                return
            h["turned"] += short_step(a, h["last"])
            h["last"] = a
            delta = h["turned"] * 180 / math.pi
        else:
            t = param_along(h["line"][0], h["line"][1], o, d)
            if t is None:
                return
            delta = t - h["start"]
        self.editor.grip_drag(h["side"], delta, "move")
        self.changed_at = time.monotonic()
        self.tick()

    def release(self, x, y):
        if self.held is None:
            return False
        self.held = None
        self.editor.grip_drag(None, 0, "end")
        self.drawn = None
        self.tick()
        if self.field is not None and self.editor.field:
            self.field.focus()  # the hand let go: the number can be typed straight over
        if grip_at(self.screen, x, y, PICK_PX * (self.dpr or 1.0)) is None:
            self.lit = None
            if self.redirected:
                redirect(self.view, False)
                self.redirected = False
        return True

    def click(self, x, y):
        """A click on the part, for the box: a pick on a body, an extrude's
        end. FreeCAD's selection is put back as it was after it, so a click
        for the box never selects anything."""
        ed = self.editor
        if not ed.wants_clicks():
            return False
        hit = object_at(self.view, x, y)
        if hit is None:
            return False
        body = self.env.get("body_of", lambda d, o: None)(hit["doc"], hit["object"])
        store = self.env.get("store", lambda: None)()
        builder = store.builder if store is not None else None
        restore = self.env.get("keep_selection", lambda: None)()
        changed = ed.click_part(hit["point"], body, builder, self.env.get("features", lambda: [])())
        if restore is not None:
            self.env.get("later", lambda fn: fn())(restore)
        return changed

    def commit_field(self, text):
        scope = self.env.get("scope", lambda: None)()
        self.editor.commit_field(text, scope, self.env.get("units", lambda: "mm")())


class _Vec:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


# ---- in FreeCAD ------------------------------------------------------------------------------------

_live = {"overlay": None, "timer": None}


def _env():
    """What the overlay reads off the open document, in FreeCAD."""
    import FreeCAD

    from .reverse import doc as D
    from .reverse import handlers as R

    def store():
        doc = FreeCAD.ActiveDocument
        if doc is None:
            return None
        return R.DocStore(session_for(doc))

    def part():
        s = store()
        return s.part() if s is not None else {"features": []}

    def bodies():
        s = store()
        try:
            return R.handlers(store=s)["reverse_body_names"]({}).get("bodies") or [] if s is not None else []
        except Exception:  # noqa: BLE001
            return []

    def scope():
        from .reverse.parameters import evaluate_parameters

        return evaluate_parameters(part().get("parameters") or [])["scope"]

    def context():
        s = store()
        try:
            return s.context() if s is not None else None
        except Exception:  # noqa: BLE001
            return None

    def hide(ids, on):
        doc = FreeCAD.ActiveDocument
        c = D.find_container(doc) if doc is not None else None
        if c is None:
            return
        for b in D.bodies_of(c):
            if getattr(b, "BodyId", None) in ids and getattr(b, "ViewObject", None) is not None:
                try:
                    if on:
                        _live.setdefault("was", {})[b.Name] = b.ViewObject.Visibility
                        b.ViewObject.Visibility = False
                    else:
                        b.ViewObject.Visibility = _live.get("was", {}).pop(b.Name, True)
                except Exception:  # noqa: BLE001
                    pass

    def body_of(doc_name, obj_name):
        """The body id of a ReverseBody clicked, or None (the scan, another object)."""
        try:
            o = FreeCAD.getDocument(doc_name).getObject(obj_name)
        except Exception:  # noqa: BLE001
            return None
        if o is None or getattr(o, "Proxy", None).__class__.__name__ != "Body" or not hasattr(o, "BodyId"):
            return None
        v = o.BodyId
        return int(v) if float(v).is_integer() else v

    def keep_selection():
        import FreeCADGui

        was = [(s.DocumentName, s.ObjectName, list(s.SubElementNames)) for s in FreeCADGui.Selection.getSelectionEx("", 0)]

        def restore():
            now = [(s.DocumentName, s.ObjectName, list(s.SubElementNames)) for s in FreeCADGui.Selection.getSelectionEx("", 0)]
            if now == was:
                return
            FreeCADGui.Selection.clearSelection()
            for d, o, subs in was:
                for sub in subs or [""]:
                    FreeCADGui.Selection.addSelection(d, o, sub)

        return restore

    def later(fn):
        from PySide import QtCore

        QtCore.QTimer.singleShot(0, fn)  # after FreeCAD's own handling of the release

    return {"store": store, "features": lambda: part().get("features") or [], "bodies": bodies, "units": lambda: "mm", "scope": scope, "context": context,
            "hide": hide, "body_of": body_of, "keep_selection": keep_selection, "later": later}


def session_for(doc):
    """The session the panel reads: Agent Link's while it runs, else the
    workbench's own context for the document."""
    try:
        from . import dock

        session, _agent = dock._session_from()
        if session is not None and getattr(session, "doc", None) is doc:
            return session
    except Exception:  # noqa: BLE001
        pass
    from . import runner

    return runner.context_for(doc)


def show(editor):
    """The editor drawn in the active 3D view, from now until it closes."""
    try:
        import FreeCAD
        import FreeCADGui
        from pivy import coin
        import PySide as qt

        gd = FreeCADGui.ActiveDocument
        view = gd.activeView() if gd is not None else None
    except Exception:  # noqa: BLE001 — no GUI (headless, a test): the panel's box works alone
        return None
    if view is None or not hasattr(view, "getSceneGraph"):
        return None
    ov = _live["overlay"]
    if ov is not None and ov.view is not view:
        ov.detach()
        ov = None
    if ov is None:
        ov = _live["overlay"] = Overlay(editor, view, coin, qt, FreeCAD.Vector, _env())
    if _live["timer"] is None:
        t = _live["timer"] = qt.QtCore.QTimer()
        t.setInterval(TICK_MS)
        t.timeout.connect(_tick)
    _live["timer"].start()
    ov.drawn = None
    return ov


def _tick():
    ov = _live["overlay"]
    if ov is None:
        return
    if not ov.editor.open:
        hide()
        return
    try:
        ov.tick()
    except Exception as e:  # noqa: BLE001 — a view gone or a build that threw: the editor closes rather than loop on it
        try:
            import FreeCAD

            FreeCAD.Console.PrintWarning(f"ScanRuler: the feature editor's view stopped: {e}\n")
        except ImportError:
            pass
        hide()


def hide():
    ov = _live["overlay"]
    if _live["timer"] is not None:
        _live["timer"].stop()
    if ov is not None:
        ov.detach()
        _live["overlay"] = None
