# SPDX-License-Identifier: AGPL-3.0-only
# Ported from ScanRuler by Stefan Hermann (CNC Kitchen),
# github.com/CNCKitchen/ScanRuler: src/viewer/ (what the browser app draws
# over the scan) and src/ui/MapLegend.tsx (the legend).
#
# ScanRuler's results drawn in FreeCAD's 3D view, after each ScanRuler call
# (scanstate.touched hands it here on the GUI thread; never without a
# window, so a headless run is the same as before): scene.plan() says what
# to show, this module builds it as Coin nodes and puts one node, named
# ScanRulerScene, into the scene graph of each 3D view of the session's
# document — the way Draft's trackers draw over the model. It is view
# state only: no document object, no property, no undo step, nothing
# saved; it goes with the window and is drawn again by the next call.
#
#   the colour map    the shown mesh coloured per vertex (SoMaterialBinding
#                     PER_VERTEX_INDEXED), drawn a hair in front of the scan
#                     (SoPolygonOffset), with the legend (legend.coin_nodes)
#                     in the view's corner; gone with the first call that
#                     does not show it
#   the edited copy   Mesh Tools' copy drawn in the scan's place; the scan
#                     object's own drawing switched off meanwhile (its
#                     SwitchNode, not its Visibility, so nothing is saved)
#   elements, dimensions, sections, markers
#                     lines, points and words on top of the model
#                     (SoAnnotation), what this call made in orange
#
# Nothing here can be picked (SoPickStyle UNPICKABLE): a click goes to the
# scan or the part under it, as before. The builder takes the coin module
# as an argument, so the tests drive it with stand-ins.

import numpy as np

from . import legend as L
from . import scene as SC

NODE_NAME = "ScanRulerScene"
LINE_PX = 2.0
NEW_LINE_PX = 3.5
POINT_PX = 6.0
FACE_TRANSPARENCY = 0.8
GHOST_TRANSPARENCY = 0.6
# The labels' size in the view's own (logical) pixels: a share of the 3D
# view's height, within LABEL_PX_MIN..LABEL_PX_MAX, and LABEL_NEW_PX more
# for what this call made. Coin's SoFont size is in the framebuffer's
# device pixels, so it is this times the screen's device pixel ratio
# (2 on a Retina Mac). Window review round 6: a fixed 13 came out about
# 6 px in a 1400 px window picture. Round 7: a 52nd of the view (16 px in
# an 824 px view) came out 11-12 px and thin in a 1400 px picture of a
# 1710 px window; a 40th (21 px there) is about 17 px in that picture.
LABEL_PX_SHARE = 1.0 / 40.0
LABEL_PX_MIN, LABEL_PX_MAX = 12.0, 28.0
LABEL_NEW_PX = 2.0
FONT_SIZE = 13.0  # the label size when the view's size is not known (stand-ins, an older FreeCAD)
# A label is bold, on a light backing: FreeCAD's SoTextLabel (an SoText2
# with a filled box behind it, registered by FreeCAD's GUI) where it is
# there, a plain SoText2 where not. Coin reads "family:style" font names;
# a face it cannot find falls back to its default one.
LABEL_FONT = "Arial:Bold"
LABEL_BACK_RGB = (0.97, 0.97, 0.96)
LABEL_FRAME = 0.3  # the backing's margin round the words, a share of the font size
# The legend's words: a share of the view's height too, smaller than the
# labels (the card holds up to 20 lines), in Coin's default monospaced
# face (its columns are laid out from the characters' count).
LEGEND_PX_SHARE = 1.0 / 56.0
LEGEND_PX_MIN, LEGEND_PX_MAX = 13.0, 18.0
LEGEND_PX = 13.0
# The edited copy's offset is one step; a preview over it two, so the
# preview stays in front of the copy and the part both.
PREVIEW_OFFSET = 2.0
TEXTURE_MAX = 2048  # the sheet image's texture, pixels a side at most


def label_px(view_height=None, dpr=1.0):
    """The labels' size in logical pixels for a 3D view view_height device
    pixels tall on a screen of device pixel ratio dpr."""
    try:
        h = float(view_height) / max(1.0, float(dpr or 1.0))
    except (TypeError, ValueError):
        return FONT_SIZE
    if not h > 0:
        return FONT_SIZE
    return float(min(LABEL_PX_MAX, max(LABEL_PX_MIN, round(h * LABEL_PX_SHARE))))


def legend_px(view_height=None, dpr=1.0):
    """The legend's font size in logical pixels for a view view_height
    device pixels tall."""
    try:
        h = float(view_height) / max(1.0, float(dpr or 1.0))
    except (TypeError, ValueError):
        return LEGEND_PX
    if not h > 0:
        return LEGEND_PX
    return float(min(LEGEND_PX_MAX, max(LEGEND_PX_MIN, round(h * LEGEND_PX_SHARE))))


def view_size(views):
    """(width, height) of the first view in device pixels
    (View3DInventor.getSize), or None."""
    for v in views:
        try:
            w, h = v.getSize()[:2]
            if int(w) > 0 and int(h) > 0:
                return int(w), int(h)
        except Exception:  # noqa: BLE001 — a view without getSize
            continue
    return None


def text_scale(gui, views):
    """(label px, device pixel ratio, view height in device px) for the
    views a scene goes into: the ratio from FreeCAD's main window (Qt),
    the height from the first view's render size (View3DInventor.getSize)."""
    dpr = 1.0
    try:
        mw = gui.getMainWindow()
        got = mw.devicePixelRatioF() if hasattr(mw, "devicePixelRatioF") else mw.devicePixelRatio()
        dpr = float(got) if float(got) > 0 else 1.0
    except Exception:  # noqa: BLE001 — a stand-in or no main window: 1
        dpr = 1.0
    height = None
    for v in views:
        try:
            height = int(v.getSize()[1])
            break
        except Exception:  # noqa: BLE001 — a view without getSize
            continue
    return (label_px(height, dpr) if height else FONT_SIZE), dpr, height


def _where(e):
    """' (file:line)' of the frame that raised, for the Report view."""
    try:
        import os
        import traceback

        fr = traceback.extract_tb(e.__traceback__)[-1]
        return f" ({os.path.basename(fr.filename)}:{fr.lineno})"
    except Exception:  # noqa: BLE001
        return ""


def _seq(x):
    """x, or an empty list for None: `x or []` fails on a numpy array."""
    return [] if x is None else x


class Builder:
    """Coin nodes for one plan, from a coin module (pivy's or a stand-in)."""

    def __init__(self, coin, label_px=FONT_SIZE, dpr=1.0, view=None):
        self.coin = coin
        self.label_px = float(label_px)
        self.dpr = float(dpr or 1.0)
        self.view = tuple(view) if view else None
        self.legend_layout = None   # card_layout of the legend drawn, for the facts
        self.label_node = None      # the type the labels were drawn with
        self.offsets = []           # the meshes drawn a hair toward the eye
        self.texture = None         # the sheet image's texture: [w, h] drawn, or why not
        self.labels = None          # the sheet's labels kept apart: scene.spread_labels' account

    def legend_font(self):
        """The legend's SoFont size, device pixels."""
        return legend_px(self.view[1] if self.view else None, self.dpr) * self.dpr

    def label(self, text, new=False):
        """A label's nodes: its font (bold) and its words on a light
        backing (SoTextLabel), or plain words where FreeCAD's node type
        is not there (stand-ins, an older FreeCAD)."""
        coin = self.coin
        font = coin.SoFont()
        font.size.setValue(self.font_size(new))
        try:
            font.name.setValue(LABEL_FONT)
        except Exception:  # noqa: BLE001 — a stand-in without the field
            pass
        words = None
        try:
            got = coin.SoType.fromName("SoTextLabel").createInstance()
            if got is not None and hasattr(got, "background"):
                got.background = True
                got.backgroundColor = LABEL_BACK_RGB
                got.frameSize = LABEL_FRAME * self.font_size(new)
                words = got
        except Exception:  # noqa: BLE001 — no SoType (a stand-in) or no such type
            words = None
        if words is None:
            words = coin.SoText2()
        self.label_node = type(words).__name__ if words is not None else None
        words.string.setValue(L.coin_text(text))
        return font, words

    def font_size(self, new=False):
        """A label's SoFont size, device pixels."""
        return (self.label_px + (LABEL_NEW_PX if new else 0.0)) * self.dpr

    def _colour(self, rgb):
        c = self.coin.SoBaseColor()
        c.rgb.setValue(*[float(x) for x in rgb[:3]])
        return c

    def mesh(self, V, F, rgb=None, colour=None, transparency=0.0, offset=False):
        """Triangles, in one colour or coloured per vertex. offset: drawn a
        hair toward the eye (True: one step; a number: that many), so an
        overlay wins over the surface it lies on instead of striping."""
        coin = self.coin
        sep = coin.SoSeparator()
        if offset:
            # A hair toward the eye, so the map wins over the scan it lies on.
            k = float(offset) if not isinstance(offset, bool) else 1.0
            po = coin.SoPolygonOffset()
            po.factor.setValue(-k)
            po.units.setValue(-k)
            sep.addChild(po)
        hints = coin.SoShapeHints()
        hints.vertexOrdering.setValue(coin.SoShapeHints.COUNTERCLOCKWISE)
        hints.shapeType.setValue(coin.SoShapeHints.UNKNOWN_SHAPE_TYPE)
        sep.addChild(hints)
        mat = coin.SoMaterial()
        V = np.asarray(V, dtype=float)
        F = np.asarray(F, dtype=np.int64)
        flat = np.hstack([F, -np.ones((len(F), 1), dtype=np.int64)]).reshape(-1).tolist()
        if rgb is not None:
            c = np.asarray(rgb, dtype=float)
            mat.diffuseColor.setValues(0, len(c), c.tolist())
            sep.addChild(mat)
            bind = coin.SoMaterialBinding()
            bind.value.setValue(coin.SoMaterialBinding.PER_VERTEX_INDEXED)
            sep.addChild(bind)
        else:
            mat.diffuseColor.setValue(*[float(x) for x in (colour or SC.EDITED)])
            if transparency:
                mat.transparency.setValue(float(transparency))
            sep.addChild(mat)
        coords = coin.SoCoordinate3()
        coords.point.setValues(0, len(V), V.tolist())
        sep.addChild(coords)
        faces = coin.SoIndexedFaceSet()
        faces.coordIndex.setValues(0, len(flat), flat)
        if rgb is not None:
            faces.materialIndex.setValues(0, len(flat), flat)
        sep.addChild(faces)
        return sep

    def shape(self, sh, lift=0.0):
        """One element, dimension, section or marker: its face (see-through,
        with the model's depth), then its lines, points and words on top."""
        coin = self.coin
        under, over = coin.SoSeparator(), coin.SoAnnotation()
        colour = sh.get("colour") or SC.ELEMENT
        face = sh.get("face")
        if face is not None and len(face) >= 3:
            mat = coin.SoMaterial()
            mat.diffuseColor.setValue(*[float(x) for x in colour])
            mat.transparency.setValue(FACE_TRANSPARENCY)
            under.addChild(mat)
            co = coin.SoCoordinate3()
            co.point.setValues(0, len(face), np.asarray(face, dtype=float).tolist())
            under.addChild(co)
            fs = coin.SoFaceSet()
            fs.numVertices.setValue(len(face))
            under.addChild(fs)
        style = coin.SoDrawStyle()
        style.lineWidth.setValue(NEW_LINE_PX if sh.get("new") else LINE_PX)
        style.pointSize.setValue(POINT_PX + (2 if sh.get("new") else 0))
        over.addChild(style)
        over.addChild(self._colour(colour))
        lines = [np.asarray(x, dtype=float) for x in _seq(sh.get("lines")) if len(x) >= 2]
        if lines:
            co = coin.SoCoordinate3()
            pts = np.vstack(lines)
            co.point.setValues(0, len(pts), pts.tolist())
            over.addChild(co)
            ls = coin.SoLineSet()
            ls.numVertices.setValues(0, len(lines), [len(x) for x in lines])
            over.addChild(ls)
        points = [np.asarray(p, dtype=float) for p in _seq(sh.get("points"))]
        if points:
            co = coin.SoCoordinate3()
            co.point.setValues(0, len(points), np.vstack(points).tolist())
            over.addChild(co)
            ps = coin.SoPointSet()
            ps.numPoints.setValue(len(points))
            over.addChild(ps)
        text = sh.get("text")
        at = sh.get("at")
        if text and at is not None:
            t = coin.SoSeparator()
            tr = coin.SoTranslation()
            tr.translation.setValue(*[float(x) + (lift if i == 2 else 0.0) for i, x in enumerate(np.asarray(at, dtype=float))])
            t.addChild(tr)
            font, words = self.label(text, bool(sh.get("new")))
            t.addChild(font)
            t.addChild(words)
            over.addChild(t)
        sep = coin.SoSeparator()
        if face is not None:
            sep.addChild(under)
        sep.addChild(over)
        return sep

    def image_texture(self, img, unit):
        """The sheet's image as a textured square on the XY plane, or None:
        SoTexture2 fed the grey rows (bottom row first, as OpenGL reads
        them, as flat_open_image keeps them), at most TEXTURE_MAX pixels a
        side (every n-th pixel past that), lit as it is (BASE_COLOR)."""
        coin = self.coin
        g = img.get("gray") if isinstance(img, dict) else None
        if g is None:
            self.texture = "no pixels"
            return None
        try:
            g = np.asarray(g, dtype=np.uint8)
            step = max(1, int(np.ceil(max(g.shape) / float(TEXTURE_MAX))))
            t = np.ascontiguousarray(g[::step, ::step])
            th, tw = t.shape
            sep = coin.SoSeparator()
            lm = coin.SoLightModel()
            lm.model.setValue(coin.SoLightModel.BASE_COLOR)
            sep.addChild(lm)
            mat = coin.SoBaseColor()
            mat.rgb.setValue(1.0, 1.0, 1.0)
            sep.addChild(mat)
            tex = coin.SoTexture2()
            tex.image.setValue(coin.SbVec2s(int(tw), int(th)), 1, t.tobytes())
            sep.addChild(tex)
            tc = coin.SoTextureCoordinate2()
            tc.point.setValues(0, 4, [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]])
            sep.addChild(tc)
            W, H = float(img["width"]) * unit[0], float(img["height"]) * unit[1]
            co = coin.SoCoordinate3()
            co.point.setValues(0, 4, [[0.0, 0.0, 0.0], [W, 0.0, 0.0], [W, H, 0.0], [0.0, H, 0.0]])
            sep.addChild(co)
            fs = coin.SoFaceSet()
            fs.numVertices.setValue(4)
            sep.addChild(fs)
            self.texture = [int(tw), int(th)]
            return sep
        except Exception as e:  # noqa: BLE001 — no texture (a stand-in, an older pivy): the edges and elements still show
            self.texture = f"{type(e).__name__}: {e}"
            return None

    def spread(self, plan):
        """The labels on the 2D sheet kept apart (scene.spread_labels), in
        the order: what this call made, then the sheet's own items, then
        the 3D groups drawn over it (a section's name stays where it was
        last). self.labels: what was done, for the facts. Never raises."""
        try:
            flat = plan["flat"]
            per = SC.sheet_per_px(flat["box"], self.view)
            if per is None:
                self.labels = {"why": "no view size"}
                return
            shapes = [sh for g in ("items",) for sh in _seq(flat.get(g))]
            shapes += [sh for g in ("sections", "elements", "dimensions", "items") for sh in _seq(plan.get(g))]
            shapes.sort(key=lambda sh: 0 if sh.get("new") else 1)  # stable: the rest keep their order
            font = self.font_size(True)
            self.labels = SC.spread_labels(shapes, flat["frame"], per, font, LABEL_FRAME * font)
        except Exception as e:  # noqa: BLE001 — the labels stay where they were
            self.labels = {"error": f"{type(e).__name__}: {e}{_where(e)}"}

    def sheet(self, flat):
        """The 2D sheet: its image (an image's sheet), then its border,
        edges, elements, dimensions, notes and zero point, all on top of
        the model (SoAnnotation): the flat workspace in the 3D view."""
        coin = self.coin
        over = coin.SoAnnotation()
        if flat.get("kind") == "image" and flat.get("image") is not None:
            tex = self.image_texture(flat["image"], flat.get("unit") or (1.0, 1.0))
            if tex is not None:
                over.addChild(tex)
        for sh in _seq(flat.get("items")):
            over.addChild(self.shape(sh))
        return over

    def build(self, plan, scan_size=10.0):
        """The whole scene as one node (named NODE_NAME), or None when there
        is nothing to draw."""
        coin = self.coin
        root = coin.SoSeparator()
        root.setName(NODE_NAME)
        pick = coin.SoPickStyle()
        pick.style.setValue(coin.SoPickStyle.UNPICKABLE)
        root.addChild(pick)
        drawn = 0
        layer = plan.get("map")
        if plan.get("mesh") is not None:
            V, F = plan["mesh"]
            # A hair toward the eye: the copy lies where the part it was
            # made from may still be shown (a Part solid the scan was
            # meshed from): window pass 3, 05-055 to 05-074, striped.
            root.addChild(self.mesh(V, F, colour=SC.EDITED, offset=True))
            self.offsets.append("editedCopy")
            drawn += 1
        elif layer is not None and plan.get("scanVF") is not None:
            V, F = plan["scanVF"]
            if len(layer["rgb"]) == len(V):
                root.addChild(self.mesh(V, F, rgb=layer["rgb"], offset=True))
                drawn += 1
        for name, V, F in _seq(plan.get("previews")):
            # In front of the mesh it lies on (a wrap of a box is the box
            # where its corners are sharp: 05-063 teal stripes).
            root.addChild(self.mesh(V, F, colour=SC.GHOST, transparency=GHOST_TRANSPARENCY, offset=PREVIEW_OFFSET))
            self.offsets.append(name)
            drawn += 1
        flat = plan.get("flat")
        if flat is not None:
            self.spread(plan)
            root.addChild(self.sheet(flat))
            drawn += 1
        lift = 0.0
        for group in ("sections", "elements", "dimensions", "items"):
            for sh in _seq(plan.get(group)):
                root.addChild(self.shape(sh, lift))
                drawn += 1
        if layer is not None and layer.get("legend") is not None and drawn:
            fs = self.legend_font()
            self.legend_layout = L.card_layout(layer["legend"], *(self.view or (None, None)), fs)
            root.addChild(L.coin_nodes(layer["legend"], coin=coin, font_size=fs, layout=self.legend_layout))
        return root if drawn else None


class Window:
    """The scene in a FreeCAD window: what is put into which view, and the
    scan object switched off while the edited copy stands in its place.
    gui: FreeCADGui (or a stand-in); coin: pivy's coin (or a stand-in)."""

    def __init__(self, gui, coin):
        self.gui, self.coin = gui, coin
        self.installed = {}   # doc name -> [(scene graph, node)]
        self.hidden = {}      # doc name -> (object name, its switch's child before)
        self.memos = {}       # (id(session), doc name) -> scene.plan's memo
        self.keys = {}        # doc name -> the key of what was built last

    def views(self, doc):
        gd = self.gui.getDocument(doc.Name)
        if gd is None:
            return []
        try:
            return list(gd.mdiViewsOfType("Gui::View3DInventor"))
        except Exception:  # noqa: BLE001 — an older FreeCAD: the active view only
            v = getattr(gd, "activeView", lambda: None)()
            return [v] if v is not None else []

    def clear(self, doc_name):
        for sg, node in self.installed.pop(doc_name, []):
            try:
                if sg.findChild(node) >= 0:
                    sg.removeChild(node)
            except (RuntimeError, ReferenceError):  # the view went
                pass

    def _scan_object(self, doc):
        from . import docstate

        try:
            return docstate.role_object(doc, "scan")
        except Exception:  # noqa: BLE001
            return None

    def scan_drawn(self, doc, show):
        """The scan object's own drawing on (show) or off. Off sets its
        switch to draw nothing and remembers what it drew; on puts that
        back unless the person changed it meanwhile. Its Visibility (saved
        with the document) is never touched. Returns what was done."""
        name = doc.Name
        o = self._scan_object(doc)
        was = self.hidden.get(name)
        if show:
            if was is None:
                return None
            self.hidden.pop(name, None)
            obj = doc.getObject(was[0])
            vo = getattr(obj, "ViewObject", None) if obj is not None else None
            if vo is None:
                return None
            sw = vo.SwitchNode
            if sw.whichChild.getValue() == -1 and getattr(vo, "Visibility", True):
                sw.whichChild.setValue(was[1])
                return "shown"
            return None
        vo = getattr(o, "ViewObject", None) if o is not None else None
        if vo is None:
            return None
        sw = vo.SwitchNode
        now = sw.whichChild.getValue()
        if was is not None and was[0] == o.Name and now == -1:
            return "hidden"
        if now == -1:
            return None  # hidden by the person: left so
        self.hidden[name] = (o.Name, now)
        sw.whichChild.setValue(-1)
        return "hidden"

    def show(self, session, tool, args=None, body=None):
        """The scene of this call drawn in every 3D view of the session's
        document. Returns a short account (for a live check)."""
        doc = getattr(session, "doc", None)
        if doc is None or not hasattr(doc, "Name"):
            return {"drawn": False, "why": "no document"}
        memo = self.memos.setdefault((id(session), doc.Name), {})
        plan = SC.plan(session, tool, args, body, memo)
        from . import scanstate as S

        scan = S.state(session).get("scan")
        if scan is not None:
            plan["scanVF"] = (np.asarray(scan.V, dtype=float), np.asarray(scan.F, dtype=np.int64))
        hide = bool(plan.get("scan") and plan["scan"].get("hide"))
        scan_was = self.scan_drawn(doc, not hide)
        self.clear(doc.Name)
        views = self.views(doc)
        px, dpr, height = text_scale(self.gui, views)
        builder = Builder(self.coin, px, dpr, view_size(views))
        node = builder.build(plan, SC.size_of(scan))
        put = []
        if node is not None:
            for v in views:
                try:
                    sg = v.getSceneGraph()
                    sg.addChild(node)
                    put.append((sg, node))
                except (RuntimeError, AttributeError):  # a view closing, or not a 3D view
                    continue
        self.installed[doc.Name] = put
        framed = frame_sheet(self.coin, views, plan.get("flat")) if put and plan.get("flat") else None
        layer = plan.get("map")
        return {"drawn": bool(put), "views": len(put), "map": layer["kind"] if layer else None, "framed": framed,
                "legend": bool(layer and layer.get("legend")), "editedCopy": plan.get("mesh") is not None, "scan": scan_was,
                "elements": len(plan["elements"]), "dimensions": len(plan["dimensions"]), "sections": len(plan["sections"]),
                "items": [i["kind"] for i in plan["items"]],
                "new": [x.get("name") for g in ("elements", "dimensions", "sections") for x in plan[g] if x.get("new")],
                "facts": facts(plan, builder, height, framed)}


def frame_sheet(coin, views, flat):
    """Each view turned square onto the 2D sheet (its u to the right, its v
    up) and framed on it, as the flat workspace shows the sheet: Coin's
    viewBoundingBox on the view's camera (FreeCAD's Fit selection does the
    same). Window pass 3, 02-062 and 02-064: after flat_curvature's comb the
    view stayed zoomed into the bore's corner through every later flat call.
    Returns what was done, for the facts: {"views", "box", "look"} or
    {"error"}. Never raises."""
    try:
        fr = flat["frame"]
        q = SC.camera_rotation(fr["basisU"], fr["basisV"])
        lo, hi = (np.asarray(x, dtype=float) for x in flat["box"])
        pad = 0.04 * float(np.linalg.norm(hi - lo)) or 1.0
        lo, hi = lo - pad, hi + pad
        done = 0
        for v in views:
            try:
                cam = v.getCameraNode()
                w, h = v.getSize()[:2] if callable(getattr(v, "getSize", None)) else (1, 1)
                cam.orientation.setValue(coin.SbRotation(*q))
                cam.viewBoundingBox(coin.SbBox3f(*[float(x) for x in lo], *[float(x) for x in hi]), float(w) / float(h) if h else 1.0, 1.0)
                done += 1
            except Exception:  # noqa: BLE001 — a view without a camera (closing): the others still turn
                continue
        look = SC.rotate_by(q, [0.0, 0.0, -1.0])
        return {"views": done, "box": [[round(float(x), 3) for x in lo], [round(float(x), 3) for x in hi]],
                "look": [round(float(x), 4) for x in look]}
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


def facts(plan, builder, height=None, framed=None):
    """What the window shows that a picture alone would otherwise have to
    tell, as plain data for the call's answer (window review round 6):
    the colours of what this call made and of the rest (hex), the label
    size (logical px, and the SoFont size in device px with the ratio), the
    legend's title and its low, middle and high values, and where the
    sections stand (the first one's first point, mm), so a move after an
    alignment shows."""
    out = {"colours": {"new": SC.hex_of(SC.NEW), "element": SC.hex_of(SC.ELEMENT), "dimension": SC.hex_of(SC.DIMENSION),
                       "section": SC.hex_of(SC.SECTION)},
           "labelPx": builder.label_px, "newLabelPx": builder.label_px + LABEL_NEW_PX, "fontSize": builder.font_size(), "dpr": builder.dpr}
    if height:
        out["viewHeight"] = height
    drawn = {g: [{"name": x.get("name"), "colour": SC.hex_of(x.get("colour") or SC.ELEMENT)} for x in _seq(plan.get(g))][:6]
             for g in ("elements", "dimensions", "sections") if _seq(plan.get(g))}
    if drawn:
        out["drawn"] = drawn
    layer = plan.get("map")
    if builder.view:
        out["viewSize"] = list(builder.view)
    if builder.label_node:
        out["labelNode"] = builder.label_node
        out["labelFont"] = LABEL_FONT
    if layer is not None and layer.get("legend") is not None:
        lg = layer["legend"]
        out["legend"] = dict(L.text_rows(lg), fontSize=builder.legend_font(),
                             tickTexts=[L.coin_text(t["text"]) for t in lg.get("ticks") or []],
                             tickDecimals=lg.get("tickDecimals"), low=lg.get("low"), high=lg.get("high"))
        lay = builder.legend_layout or L.card_layout(lg, *(builder.view or (None, None)), builder.legend_font())
        out["legend"]["box"] = L.box_facts(lay)
    if builder.offsets:
        out["inFront"] = list(builder.offsets)
    fl = plan.get("flat")
    if fl is not None:
        out["flat"] = dict(fl["counts"], sheet=fl["kind"], units=fl["units"],
                           corners=[[round(float(c), 3) for c in p] for p in fl["corners"]],
                           texture=builder.texture if fl["kind"] == "image" else None, labels=builder.labels,
                           new=[x.get("name") for x in fl["items"] if x.get("new")], framed=framed,
                           scanHidden=bool(plan.get("scan") and plan["scan"].get("hide")))
    secs = _seq(plan.get("sections"))
    if secs:
        first = [np.asarray(x, dtype=float) for x in _seq(secs[0].get("lines")) if len(x)]
        if first:
            out["sectionAt"] = {"name": secs[0].get("name"), "point": [round(float(c), 3) for c in first[0][0]]}
    return out


_WINDOW = []
# What the last call drew, per document: read by a live check
# (scanrulerfc.scene_coin.LAST in FreeCAD's Python console).
LAST = {}


def window():
    if not _WINDOW:
        import FreeCADGui
        from pivy import coin

        _WINDOW.append(Window(FreeCADGui, coin))
    return _WINDOW[0]


def after_call(session, tool, args=None, body=None):
    """After a ScanRuler call that went through: its results drawn in the
    window. Only with a window (FreeCAD.GuiUp) and on the GUI thread; a
    failure is reported in the Report view and never reaches the call."""
    try:
        import FreeCAD
    except ImportError:
        return None
    if not getattr(FreeCAD, "GuiUp", False):
        return None
    try:
        got = window().show(session, tool, args, body)
    except Exception as e:  # noqa: BLE001 — the view only: the call has answered
        try:
            FreeCAD.Console.PrintWarning(f"ScanRuler: the results of {tool} could not be drawn in the 3D view: {type(e).__name__}: {e}{_where(e)}\n")
        except Exception:  # noqa: BLE001
            pass
        return None
    doc = getattr(session, "doc", None)
    LAST[getattr(doc, "Name", "?")] = dict(got, tool=tool)
    return got
