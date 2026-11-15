# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/core/where.ts
# SPDX-License-Identifier: AGPL-3.0-only
#
# Faces and edges picked by a query (Where): every face or edge of a body
# that answers its terms: a box, a point it runs through, a kind, a size,
# the feature that made it, the faces either side. A feature given one
# keeps it (StoredWhere, beside the fingerprints of what it found), and the
# builder runs it again on the body as it stands before the feature, so a
# sketch redrawn under a round still rounds the edges the query names. The
# fingerprints are the fallback, for a query that finds nothing on the part
# as it stands. Run on plain FaceInfo / EdgeInfo descriptors (topo.py);
# what the commands read off the page (the feature a madeBy names, how
# faces meet along an edge) is asked of the caller (`ask`: {featureId,
# sharp}).

import math

from ._js import js_hypot, stringify
from .topo import match_edge, match_face

SHARP_DEG = 1
COAXIAL_ANGLE = math.pi / 180
COAXIAL_MM = 0.05
THROUGH_MM = 0.01


class WhereError(Exception):
    """A query refused: the original's CommandError, with its code
    (invalid_input or not_found)."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _invalid(text):
    raise WhereError("invalid_input", text)


def is_where(pick):
    return isinstance(pick, dict) and "mid" not in pick and "centroid" not in pick


def unwrapped(pick, what):
    """A pick given wrapped ({where: {...}}) as the query itself."""
    if not isinstance(pick, dict) or "where" not in pick:
        return pick
    where = pick["where"]
    rest = {k: v for k, v in pick.items() if k != "where"}
    written = "edges: [{ sides: { madeBy: [...] } }]" if what == "edge" else "faces: [{ madeBy: … }]"
    if not isinstance(where, dict):
        _invalid(f"A {what} pick is the query itself — {written} — and where in it is {stringify(where)}, no query.")
    twice = [k for k in rest if k in where]
    if twice:
        _invalid(f"A {what} pick is the query itself — {written} — and {', '.join(twice)} stand{'s' if len(twice) == 1 else ''} both in where and beside it: give each once, with no where.")
    return unwrapped({**rest, **where}, what)


def _off_line(p, at, d):
    ln = js_hypot(d[0], d[1], d[2]) or 1
    v = [p[0] - at[0], p[1] - at[1], p[2] - at[2]]
    c = [v[1] * d[2] - v[2] * d[1], v[2] * d[0] - v[0] * d[2], v[0] * d[1] - v[1] * d[0]]
    return js_hypot(c[0], c[1], c[2]) / ln


def _angle_between(a, b):
    la, lb = js_hypot(a[0], a[1], a[2]), js_hypot(b[0], b[1], b[2])
    if not (la > 0 and lb > 0):
        return math.pi
    return math.acos(max(-1, min(1, (a[0] * b[0] + a[1] * b[1] + a[2] * b[2]) / (la * lb))))


def _parallel(a, b):
    t = _angle_between(a, b)
    return min(t, math.pi - t) <= COAXIAL_ANGLE


def _face_coaxial(f, c):
    fp = f["fingerprint"]
    within = c.get("within", COAXIAL_MM) if c.get("within") is not None else COAXIAL_MM
    if not fp.get("center"):
        return False
    if fp["kind"] == "sphere":
        return _off_line(fp["center"], c["at"], c["dir"]) <= within
    if fp["kind"] not in ("cylinder", "cone", "torus"):
        return False
    return _parallel(fp["dir"], c["dir"]) and _off_line(fp["center"], c["at"], c["dir"]) <= within


def _edge_coaxial(e, c):
    fp = e["fingerprint"]
    if fp["kind"] != "circle" or fp.get("radius") is None or not _parallel(fp["dir"], c["dir"]):
        return False
    within = c["within"] if c.get("within") is not None else COAXIAL_MM
    points = [fp["mid"], e["ends"][0], e["ends"][1]]
    q = e["polyline"]
    n = len(q) // 3
    for k in (0.25, 0.5, 0.75):
        i = int(math.floor(k * (n - 1)))
        if n > 2:
            points.append([q[3 * i], q[3 * i + 1], q[3 * i + 2]])
    return all(abs(_off_line(p, c["at"], c["dir"]) - fp["radius"]) <= within for p in points)


def _edge_rounds_coaxial(e, rounds):
    faces = set(e["faces"])
    return e["fingerprint"]["kind"] != "line" and len(faces) == 2 and any(h in rounds for h in faces)


def _face_loops(t, face_index, body):
    face = t["faces"][face_index] if 0 <= face_index < len(t["faces"]) else None
    if not face:
        raise WhereError("not_found", f"{body['name']} has no face {face_index} — it has {len(t['faces'])}; reverse.body.describe lists them.")
    fp = face["fingerprint"]
    if fp["kind"] != "plane":
        _invalid(f"loop reads a flat face’s boundary — face {face_index} of {body['name']} is a {fp['kind']}.")
    edges = [i for i, e in enumerate(t["edges"]) if face["hash"] in e["faces"]]
    parent = list(range(len(edges)))

    def root(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    def near(a, b):
        return js_hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]) <= 1e-3

    for a in range(len(edges)):
        for b in range(a + 1, len(edges)):
            ea, eb = t["edges"][edges[a]]["ends"], t["edges"][edges[b]]["ends"]
            if any(near(p, q) for p in ea for q in eb):
                parent[root(a)] = root(b)
    loops = {}
    for k, i in enumerate(edges):
        loops.setdefault(root(k), []).append(i)
    n = fp["dir"]
    u = [0, -n[2], n[1]] if abs(n[0]) < 0.9 else [-n[2], 0, n[0]]
    ul = js_hypot(u[0], u[1], u[2]) or 1
    U = [u[0] / ul, u[1] / ul, u[2] / ul]
    V = [n[1] * U[2] - n[2] * U[1], n[2] * U[0] - n[0] * U[2], n[0] * U[1] - n[1] * U[0]]

    def extent(loop):
        box = [math.inf, -math.inf, math.inf, -math.inf]

        def take(p):
            a = p[0] * U[0] + p[1] * U[1] + p[2] * U[2]
            b = p[0] * V[0] + p[1] * V[1] + p[2] * V[2]
            box[0], box[1], box[2], box[3] = min(box[0], a), max(box[1], a), min(box[2], b), max(box[3], b)

        for i in loop:
            e = t["edges"][i]
            q = e["polyline"]
            for o in range(0, len(q) - 2, 3):
                take(q[o:o + 3])
            take(e["ends"][0])
            take(e["ends"][1])
            take(e["fingerprint"]["mid"])
        return (box[1] - box[0]) * (box[3] - box[2])

    ranked = sorted(({"l": lp, "size": extent(lp)} for lp in loops.values()), key=lambda r: -r["size"])
    return {"outer": ranked[0]["l"] if ranked else [], "inner": [i for r in ranked[1:] for i in r["l"]]}


def _sides_made_by(sides, t, ask):
    made = sides.get("madeBy") if isinstance(sides, dict) else None
    if not isinstance(made, list) or len(made) != 2 or not all(isinstance(r, (str, int, float)) and not isinstance(r, bool) for r in made):
        _invalid('sides.madeBy names two features: the edges between a face of the one and a face of the other ({ madeBy: ["Blade", "Dish"] }).')
    a, b = (ask["featureId"](r) for r in made)
    origin = {f["hash"]: f["fingerprint"]["origin"] for f in t["faces"]}

    def test(i):
        faces = list(dict.fromkeys(t["edges"][i]["faces"]))
        if len(faces) > 2 or not faces:
            return False
        p, q = (faces[0], faces[0]) if len(faces) == 1 else faces
        x, y = origin.get(p), origin.get(q)
        return (x == a and y == b) or (x == b and y == a)

    return test


def where_indices(given, t, body, what, ask):
    """The indices of a body's faces, or edges, a query names."""
    w = unwrapped(given, what)
    made_by = ask["featureId"](w["madeBy"]) if w.get("madeBy") is not None else None
    sides = sides_of(w, t["faces"], body)
    if what == "face":
        if w.get("sides"):
            _invalid("sides picks edges — those between faces two features made; for faces give madeBy.")
        hits = [i for i, f in enumerate(t["faces"]) if face_passes(f, w, made_by, sides)]
    else:
        in_loop = None
        if w.get("loop"):
            if len(w.get("faces") or []) != 1:
                _invalid("loop reads one face’s boundary — give that face alone in faces ({ faces: [i], loop: \"outer\" }).")
            loops = _face_loops(t, w["faces"][0], body)
            in_loop = set(loops["outer"] if w["loop"] == "outer" else loops["inner"])
        rounds = {f["hash"] for f in t["faces"] if _face_coaxial(f, w["coaxial"])} if w.get("coaxial") else None
        hits = [i for i, e in enumerate(t["edges"]) if (in_loop is None or i in in_loop) and edge_passes(e, w, made_by, sides, rounds)]
        if w.get("sides"):
            test = _sides_made_by(w["sides"], t, ask)
            hits = [i for i in hits if test(i)]
        if w.get("sharp") or w.get("sharpDeg") is not None:
            sharp = ask["sharp"](w["sharpDeg"] if w.get("sharpDeg") is not None else SHARP_DEG)
            if not sharp:
                _invalid(f"sharp reads how the faces meet off {body['name']}’s mesh, and there is none for it here — pick without sharp, by through or near.")
            hits = [i for i in hits if sharp(i)]
    if w.get("exclude") is not None:
        ex = w["exclude"]
        gone = set(ex if isinstance(ex, list) else where_indices(ex, t, body, what, ask))
        hits = [i for i in hits if i not in gone]
    return hits


def _in_box(p, w):
    box = w.get("box")
    if box and not all(box["min"][k] <= p[k] <= box["max"][k] for k in range(3)):
        return False
    near = w.get("near")
    return not near or js_hypot(p[0] - near["at"][0], p[1] - near["at"][1], p[2] - near["at"][2]) <= near["radius"]


def _off_polyline(e, p):
    q = e["polyline"]
    if len(q) < 6:
        return min(js_hypot(x[0] - p[0], x[1] - p[1], x[2] - p[2]) for x in e["ends"])
    best = math.inf
    i = 0
    while i + 5 < len(q):
        ax, ay, az = q[i], q[i + 1], q[i + 2]
        dx, dy, dz = q[i + 3] - ax, q[i + 4] - ay, q[i + 5] - az
        l2 = dx * dx + dy * dy + dz * dz
        t = max(0, min(1, ((p[0] - ax) * dx + (p[1] - ay) * dy + (p[2] - az) * dz) / l2)) if l2 > 0 else 0
        best = min(best, js_hypot(ax + t * dx - p[0], ay + t * dy - p[1], az + t * dz - p[2]))
        i += 3
    return best


def _off_edge(e, p):
    fp = e["fingerprint"]
    a, b = e["ends"]
    if fp["kind"] == "line":
        d = [b[0] - a[0], b[1] - a[1], b[2] - a[2]]
        l2 = d[0] * d[0] + d[1] * d[1] + d[2] * d[2]
        t = max(0, min(1, ((p[0] - a[0]) * d[0] + (p[1] - a[1]) * d[1] + (p[2] - a[2]) * d[2]) / l2)) if l2 > 0 else 0
        return js_hypot(a[0] + t * d[0] - p[0], a[1] + t * d[1] - p[1], a[2] + t * d[2] - p[2])
    coarse = _off_polyline(e, p)
    if fp["kind"] != "circle" or fp.get("radius") is None:
        return coarse
    r = fp["radius"]
    m = fp["mid"]
    n = fp["dir"]
    ln = js_hypot(n[0], n[1], n[2]) or 1
    ax = [n[0] / ln, n[1] / ln, n[2] / ln]
    if js_hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]) < 1e-6:
        c = [(m[0] + a[0]) / 2, (m[1] + a[1]) / 2, (m[2] + a[2]) / 2]
    else:
        k = [(a[0] + b[0]) / 2 - m[0], (a[1] + b[1]) / 2 - m[1], (a[2] + b[2]) / 2 - m[2]]
        lk = js_hypot(k[0], k[1], k[2]) or 1
        c = [m[0] + (r * k[0]) / lk, m[1] + (r * k[1]) / lk, m[2] + (r * k[2]) / lk]
    v = [p[0] - c[0], p[1] - c[1], p[2] - c[2]]
    h = v[0] * ax[0] + v[1] * ax[1] + v[2] * ax[2]
    rho = js_hypot(v[0] - h * ax[0], v[1] - h * ax[1], v[2] - h * ax[2])
    exact = js_hypot(rho - r, h)
    return exact if coarse < exact + 0.1 * r + 0.05 else coarse


def _size_passes(radius, w):
    want = w["radius"] if w.get("radius") is not None else (w["diameter"] / 2 if w.get("diameter") is not None else None)
    if want is None:
        return True
    if radius is None:
        return False
    within = w["sizeWithin"] if w.get("sizeWithin") is not None else max(0.05, 0.02 * want)
    return abs(radius - want) <= within


def sides_of(w, faces, body):
    """The faces a query's `faces` names, by hash; None with no such term."""
    if w.get("faces") is None:
        return None
    out = []
    for i in w["faces"]:
        if not isinstance(i, int) or not (0 <= i < len(faces)):
            raise WhereError("not_found", f"{body['name']} has no face {i} — it has {len(faces)}; reverse.body.describe lists them.")
        out.append(faces[i]["hash"])
    return out


def _within(w):
    return ((w["withinDeg"] if w.get("withinDeg") is not None else 10) * math.pi) / 180


def face_passes(f, w, made_by, sides=None):
    if w.get("through"):
        _invalid("through picks edges — the edge a point lies on; for a face give near, box or its fingerprint.")
    fp = f["fingerprint"]
    within = _within(w)
    if sides is not None and f["hash"] not in sides:
        return False
    if not _in_box(fp["centroid"], w):
        return False
    if w.get("kind") is not None and fp["kind"] != w["kind"]:
        return False
    if made_by is not None and fp["origin"] != made_by:
        return False
    if w.get("minArea") is not None and fp["area"] < w["minArea"]:
        return False
    if w.get("maxArea") is not None and fp["area"] > w["maxArea"]:
        return False
    if not _size_passes(fp.get("radius"), w):
        return False
    if w.get("between") and not any(_angle_between(fp["dir"], n) <= within for n in w["between"]):
        return False
    if w.get("coaxial") and not _face_coaxial(f, w["coaxial"]):
        return False
    return True


def edge_passes(e, w, made_by, sides=None, rounds=None):
    fp = e["fingerprint"]
    within = _within(w)
    if sides is not None and not all(h in e["faces"] for h in sides):
        return False
    if not _in_box(fp["mid"], w):
        return False
    through = w.get("through")
    if through and _off_edge(e, through["at"]) > (through["within"] if through.get("within") is not None else THROUGH_MM):
        return False
    if w.get("kind") is not None and fp["kind"] != w["kind"]:
        return False
    if made_by is not None and fp["origin"] != made_by:
        return False
    if w.get("minLength") is not None and fp["length"] < w["minLength"]:
        return False
    if w.get("maxLength") is not None and fp["length"] > w["maxLength"]:
        return False
    if not _size_passes(fp.get("radius"), w):
        return False
    if w.get("between") and not all(any(_angle_between(f["dir"], n) <= within for f in fp["faces"]) for n in w["between"]):
        return False
    if w.get("coaxial") and not _edge_coaxial(e, w["coaxial"]) and not (rounds is not None and _edge_rounds_coaxial(e, rounds)):
        return False
    return True


def sharp_by_surfaces(e, normals, deg=SHARP_DEG):
    """Whether an edge runs between faces meeting at more than `deg`,
    read off the faces' own surfaces (`normals(face hash, points)`, the
    kernel's faceNormals) at its middle and a quarter from each end."""
    tangent_cos = math.cos((deg * math.pi) / 180)
    faces = list(dict.fromkeys(e["faces"]))
    if len(e["faces"]) < 2 or len(faces) > 2:
        return True
    if len(faces) == 1:
        return False
    points = [e["fingerprint"]["mid"]]
    q = e["polyline"]
    n = len(q) // 3
    if n > 2:
        for k in (0.25, 0.75):
            i = int(math.floor(k * (n - 1) + 0.5))
            points.append([q[3 * i], q[3 * i + 1], q[3 * i + 2]])
    a = normals(faces[0], points)
    b = normals(faces[1], points)

    def lacks(x, i):
        return i >= len(x) or not x[i]

    return any(lacks(a, i) or lacks(b, i) or abs(a[i][0] * b[i][0] + a[i][1] * b[i][1] + a[i][2] * b[i][2]) < tangent_cos for i in range(len(points)))


# ---- queries a feature keeps ------------------------------------------------------------


def stored_where(given, t, what, feature_id):
    """A query made ready to keep, on the topology it was run on: features
    by id, indices by fingerprint."""
    w = unwrapped(given, what)
    rest = {k: v for k, v in w.items() if k not in ("madeBy", "sides", "faces", "exclude", "where")}

    def face(i):
        if not isinstance(i, int) or not (0 <= i < len(t["faces"])):
            raise WhereError("not_found", f"There is no face {i} — the body has {len(t['faces'])}; reverse.body.describe lists them.")
        return t["faces"][i]["fingerprint"]

    out = dict(rest)
    if w.get("madeBy") is not None:
        out["madeBy"] = feature_id(w["madeBy"])
    if w.get("sides"):
        out["sides"] = {"madeBy": [feature_id(r) for r in w["sides"]["madeBy"]]}
    if w.get("faces") is not None:
        out["faces"] = [face(i) for i in w["faces"]]
    ex = w.get("exclude")
    if isinstance(ex, list):
        prints = []
        for i in ex:
            if what == "face":
                prints.append(face(i))
            elif isinstance(i, int) and 0 <= i < len(t["edges"]):
                prints.append(t["edges"][i]["fingerprint"])
        out["exclude"] = {"prints": prints}
    elif ex is not None:
        out["exclude"] = stored_where(ex, t, what, feature_id)
    return out


def _where_on(s, t, what, tol):
    out = {k: v for k, v in s.items() if k not in ("faces", "exclude")}
    if s.get("faces") is not None:
        prints = [f["fingerprint"] for f in t["faces"]]
        at = [match_face(f, prints, tol) for f in s["faces"]]
        if any(i is None for i in at):
            return None
        out["faces"] = at
    ex = s.get("exclude")
    if ex and "prints" in ex:
        face_of = [f["fingerprint"] for f in t["faces"]]
        edge_of = [e["fingerprint"] for e in t["edges"]]
        found = [match_face(p, face_of, tol) if what == "face" else match_edge(p, edge_of, tol) for p in ex["prints"]]
        out["exclude"] = [i for i in found if i is not None]
    elif ex:
        inner = _where_on(ex, t, what, tol)
        if inner is None:
            return None
        out["exclude"] = inner
    return out


def run_stored_where(s, t, body, what, sharp, tol):
    """A kept query run on a body as it stands, by index; None where it
    cannot be read there."""
    w = _where_on(s, t, what, tol)
    if w is None:
        return None
    try:
        return where_indices(w, t, body, what, {"featureId": lambda ref: ref if isinstance(ref, (int, float)) and not isinstance(ref, bool) else math.nan, "sharp": sharp})
    except WhereError:
        return None


def _same_print(a, b):
    return stringify(a) == stringify(b)


def live_picks(prints, picks, same=_same_print):
    """The kept queries of a feature that still stand on its list of
    fingerprints, and the fingerprints left over: {live, rest}."""
    if not picks:
        return {"live": [], "rest": list(prints)}
    claimed = set()
    live = []
    for p in picks:
        mine = []
        for f in p["found"]:
            i = next((i for i, x in enumerate(prints) if i not in claimed and i not in mine and _same_print(f, x)), -1)
            if i < 0:
                i = next((i for i, x in enumerate(prints) if i not in claimed and i not in mine and same(f, x)), -1)
            if i < 0:
                break
            mine.append(i)
        if len(mine) < len(p["found"]):
            continue
        live.append(p)
        claimed.update(mine)
    return {"live": live, "rest": [x for i, x in enumerate(prints) if i not in claimed]}


def where_words(s):
    """A kept query in words: its terms, what it named by fingerprint
    counted."""
    terms = []
    for k, v in s.items():
        if k == "faces" and isinstance(v, list):
            terms.append(f"faces: {len(v)}")
        elif k == "exclude":
            terms.append("exclude")
        else:
            terms.append(f"{k}: {stringify(v)}")
    return f"{{ {', '.join(terms)} }}"
