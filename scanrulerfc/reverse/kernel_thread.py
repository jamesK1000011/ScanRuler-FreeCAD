# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/core/kernelThread.ts, thread.ts (the tooth, the fill, the span)
# SPDX-License-Identifier: AGPL-3.0-only
#
# A screw thread cut on a full round face of a solid — a bolt's on a boss, a
# nut's in a bore — to its form's basic profile, every face of it moved into
# the material by the offset. The tooth's outline, drawn in a plane through
# the axis, is screwed along the axis from a pitch before the thread's span
# to a pitch past it; a band round the face over the span, less the screwed
# tooth, is what the solid loses. A face drawn wider or narrower than the
# thread is filled in or built up to it first; asked for a chamfer, the free
# ends are chamfered at 45° before the thread is cut through them. The tooth
# and span maths are plain; thread_tracked takes the kernel (kernel.py).

import math

from ._js import js_round, num_str
from .loops import polygon_loop
from .origins import compose_history
from .vec import add_scaled, cross, normalize

MAX_THREAD_TURNS = 400
POINT_FLAT = 1e-4
CREST_ON_FACE = 0.01
CHAMFER_PAST_ROOT = 0.1

V60 = {"tan": 1 / math.sqrt(3), "sec": 2 / math.sqrt(3), "depth": (5 / 8) * (math.sqrt(3) / 2), "crest": 1 / 8, "root": 1 / 4}
PRINT45 = {"tan": 1, "sec": math.sqrt(2), "depth": 0.3, "crest": 1 / 5, "root": 1 / 5}
FORMS = {"metric": V60, "unc": V60, "unf": V60, "print45": PRINT45}


def _mm(v):
    return f"{num_str(js_round(v * 1000) / 1000)} mm"


def thread_depth(pitch, standard):
    return FORMS[standard]["depth"] * pitch


def minor_diameter(diameter, pitch, standard):
    return diameter - 2 * thread_depth(pitch, standard)


def face_against_thread(t, internal, face_diameter):
    slack = thread_depth(t["pitch"], t["standard"])
    own = minor_diameter(t["diameter"], t["pitch"], t["standard"]) if internal else t["diameter"]
    return "wider" if face_diameter > own + slack else "narrower" if face_diameter < own - slack else None


def tooth_outline(t, internal, reach, face=None):
    """The tooth (outside) or the gap (inside) in (r, z) about the axis,
    with the crest and root radii and whether the crest comes to a point."""
    P = t["pitch"]
    c = t["offset"]
    R = t["diameter"] / 2
    f = FORMS[t["standard"]]
    tan, sec = f["tan"], f["sec"]
    h = f["depth"] * P
    shrink = c * tan - c * sec
    past = min(0.05 * P, reach / 2)
    if not internal:
        root = R - h - c
        root_half = ((1 - f["root"]) * P) / 2 + shrink
        crest_half = (f["crest"] * P) / 2 + shrink
        pointed = crest_half < POINT_FLAT * P
        apex = R - c + crest_half / tan
        crest = apex if pointed else R - c
        to_apex = pointed or (face is not None and crest >= face - CREST_ON_FACE * P)
        top = [[apex, 0]] if to_apex else [[crest, -crest_half], [crest, crest_half]]
        bend = root - past
        bend_half = root_half + past * tan
        base = root - reach
        return {"points": [[base, -bend_half], [bend, -bend_half], *top, [bend, bend_half], [base, bend_half]], "crest": crest, "root": root, "pointed": pointed}
    minor = R - h
    root = R + c
    root_half = ((1 - f["crest"]) * P) / 2 + shrink
    crest_half = (f["root"] * P) / 2 + shrink
    pointed = crest_half < POINT_FLAT * P
    apex = minor + c - crest_half / tan
    crest = apex if pointed else minor + c
    to_apex = pointed or (face is not None and crest <= face + CREST_ON_FACE * P)
    below = [[apex, 0]] if to_apex else [[crest, -crest_half]]
    above = [] if to_apex else [[crest, crest_half]]
    bend = root + past
    bend_half = root_half + past * tan
    outer = root + reach
    return {"points": [*below, [bend, -bend_half], [outer, -bend_half], [outer, bend_half], [bend, bend_half], *above], "crest": crest, "root": root, "pointed": pointed}


def fill_radius(t, internal, face_r):
    """The radius a face drawn off the thread's crests is filled or built
    to, or None when it lies on them."""
    o = tooth_outline(t, internal, 0)
    crest, pointed = o["crest"], o["pointed"]
    near = CREST_ON_FACE * t["pitch"]
    if (face_r <= crest + near) if internal else (face_r >= crest - near):
        return None
    if not pointed:
        return crest
    return max(crest - t["pitch"] / 4, crest / 2) if internal else crest + t["pitch"] / 4


def chamfer_radius(t, internal):
    root = tooth_outline(t, internal, 0)["root"]
    return root + CHAMFER_PAST_ROOT * t["pitch"] if internal else root - CHAMFER_PAST_ROOT * t["pitch"]


def thread_span(face, length, start, flip):
    """Where along the face's axis the thread runs, or None past its end."""
    if length is None:
        return {"from": face["lo"], "to": face["hi"]}
    slack = 1e-6
    if start < -slack or start + length > face["hi"] - face["lo"] + slack:
        return None
    return {"from": face["lo"] + start, "to": face["lo"] + start + length} if flip else {"from": face["hi"] - start - length, "to": face["hi"] - start}


def thread_note(t, internal, face_r, tooth, unfilled):
    notes = []
    against = face_against_thread(t, internal, 2 * face_r)
    face = f"Ø{_mm(2 * face_r)}"
    minor = f"minor Ø{_mm(minor_diameter(t['diameter'], t['pitch'], t['standard']))}"
    if unfilled:
        crests = minor if internal else f"Ø{_mm(t['diameter'])}"
        notes.append(f"The {'bore' if internal else 'boss'} is {face}, not the thread's {crests}, and it does not run between square ends: it is left as drawn and the crests lie on it.")
    elif not internal:
        if against == "wider":
            notes.append(f"The boss is {face}, wider than the thread's Ø{_mm(t['diameter'])}: what stood past the crests is cut away.")
        elif against == "narrower":
            notes.append(f"The boss is {face}, under the thread's Ø{_mm(t['diameter'])}: it is built up to it along the thread.")
    else:
        if against == "wider":
            notes.append(f"The bore is {face}, wider than the thread's {minor}: it is filled in to it along the thread.")
        elif against == "narrower":
            notes.append(f"The bore is {face}, narrower than the thread's {minor}: it is bored out to it along the thread.")
    if tooth["pointed"]:
        notes.append("At this offset the crests come to a point.")
    return " ".join(notes) if notes else None


def thread_tracked(kernel, solid, face_hash, t):
    """ReKernel.threadTracked (kernelThread.ts) on the kernel given."""
    from .kernel import KernelError, lone_solid, read_face, read_round, run, with_sub_shapes

    occt = kernel.occt

    def on(handles):
        handle = handles[0]
        f = read_face(occt, handle)
        if f["kind"] != "cylinder" or f.get("radius") is None or not f.get("center"):
            raise KernelError("a thread is cut on a round face — this one is not a cylinder.")
        center = f["center"]
        drawn = f["radius"]
        rd = read_round(occt, handle, f["dir"], center, "a thread is cut on a full cylinder")
        axis, lo, hi = rd["axis"], rd["lo"], rd["hi"]
        internal = not rd["convex"]
        span = thread_span({"lo": lo, "hi": hi}, t.get("length"), t.get("start", 0), t.get("flip", False))
        if not span:
            raise KernelError(f"the thread runs past the end of the face — {_mm(t.get('start', 0))} in and {_mm(t.get('length') or 0)} long, on a face {_mm(hi - lo)} long.")
        P = t["pitch"]
        wanted = fill_radius(t, internal, drawn)
        whole = 2 * math.pi * drawn * (hi - lo)
        square = abs(occt.getSurfaceArea(handle) - whole) <= 1e-6 * whole
        hull = None
        if wanted is not None and not square and internal:
            try:
                hull = kernel.delete_faces(solid, [face_hash])
            except KernelError:
                hull = None
        fill = wanted if wanted is not None and (square or hull is not None) else None
        face_r = fill if fill is not None else drawn
        root = tooth_outline(t, internal, 0)["root"]
        if wanted is not None and fill is None and ((drawn >= root) if internal else (drawn <= root)):
            what = f"bore is Ø{_mm(2 * drawn)}, past the thread's major Ø{_mm(2 * root)}" if internal else f"boss is Ø{_mm(2 * drawn)}, under the thread's minor Ø{_mm(2 * root)}"
            raise KernelError(f"the {what}, and it does not run between square ends, so it cannot be {'filled in' if internal else 'built up'} to the thread — draw it at the thread's size.")
        tooth = tooth_outline(t, internal, P / 2 if internal else min(P / 2, root / 2), face_r)
        margin = P / 2
        inner = min(face_r, tooth["crest"]) - margin if internal else tooth["root"]
        outer = tooth["root"] if internal else max(face_r, t["diameter"] / 2) + margin
        lead = P / 2
        radial = normalize(cross(axis, [1, 0, 0] if abs(axis[0]) < 0.9 else [0, 1, 0])) or [1, 0, 0]
        across = cross(axis, radial)

        def circle(r):
            return {"kind": "circle", "center": center, "normal": axis, "radius": r}

        shape = solid
        history = {}
        sleeve = None
        if fill is not None:
            section = kernel.face({"outer": [circle(max(drawn, fill))], "holes": [[circle(min(drawn, fill))]]})
            sleeve = kernel.extrude(section, axis, span["from"], span["to"])
            step = kernel.fuse_tracked(shape, sleeve)
            history = compose_history(history, step["history"])
            shape = step["shape"]

        def clear(at, way, near, far, reach):
            r_in = max(near, 1e-3)
            for along in (reach / 2, reach):
                for share in (0.1, 0.5, 0.9):
                    r = r_in + (far - r_in) * share
                    for turn in (0, 2 * math.pi / 3, 4 * math.pi / 3):
                        p = add_scaled(add_scaled(add_scaled(center, axis, at + way * along), radial, r * math.cos(turn)), across, r * math.sin(turn))
                        if kernel.contains_point(shape, p):
                            return False
            return True

        end_lo = abs(span["from"] - lo) < 1e-6
        end_hi = abs(span["to"] - hi) < 1e-6
        opened = fill is not None and ((drawn > outer + P / 20) if internal else (drawn < inner - P / 20))
        free_lo = (end_lo or opened) and clear(span["from"], -1, inner, outer, lead)
        free_hi = (end_hi or opened) and clear(span["to"], 1, inner, outer, lead)
        frm = span["from"] - lead if free_lo else span["from"]
        to = span["to"] + lead if free_hi else span["to"]
        edge = P / 8
        rc = chamfer_radius(t, internal)
        bore = min(face_r, tooth["crest"])
        c_far = max(bore - edge, bore / 2) if internal else max(face_r, t["diameter"] / 2) + edge
        c_near = rc + edge if internal else rc - edge
        chamfer_at = []
        if t.get("chamfer"):
            r_in, r_out = min(c_near, c_far), max(c_near, c_far)
            lo_open = clear(lo, -1, r_in, r_out, edge)
            hi_open = clear(hi, 1, r_in, r_out, edge)
            if end_lo and free_lo and lo_open:
                chamfer_at.append((lo, -1))
            if end_hi and free_hi and hi_open:
                chamfer_at.append((hi, 1))
            if not chamfer_at:
                short = "" if t.get("length") is None else "stops short of the face’s ends or "
                raise KernelError(f"there is no end to chamfer — a chamfer goes where the thread comes out of the body free, a bolt’s tip or a bore’s mouth, and this one {short}runs up to more of the body.")
            ln = hi - lo
            reach = rc - max(face_r, tooth["crest"]) if internal else min(face_r, tooth["crest"]) - rc
            deep = abs(c_far - rc)
            if len(chamfer_at) == 2 and 2 * reach >= ln:
                raise KernelError(f"the face is {_mm(ln)} long — too short for a chamfer at each end, each {_mm(reach)} deep.")
            if len(chamfer_at) == 1 and deep > ln and not (hi_open if chamfer_at[0][0] == lo else lo_open):
                raise KernelError(f"the face is {_mm(ln)} long — too short for a chamfer {_mm(deep)} deep.")

        def chamfer_ring(at, out):
            tri = [[c_near, -edge], [c_far, rc - c_far], [c_far, -edge]] if internal else [[c_near, -edge], [c_far, c_far - rc], [c_far, -edge]]
            section = kernel.face({"outer": polygon_loop([add_scaled(add_scaled(center, axis, at - out * s), radial, r) for r, s in tri]), "holes": []})
            return kernel.revolve(section, center, axis, 2 * math.pi)

        turns = math.ceil((to - frm) / P - 1e-9) + 2
        if turns > MAX_THREAD_TURNS:
            raise KernelError(f"the thread would take {round(turns)} turns — at most {MAX_THREAD_TURNS}; give it a coarser pitch or a shorter length.")

        def lift(q):
            return add_scaled(add_scaled(center, axis, frm - P + q[1]), radial, q[0])

        ring = kernel.face({"outer": [circle(outer)], "holes": [[circle(inner)]] if inner > 1e-3 else []})
        band = kernel.extrude(ring, axis, frm, to)
        screwed = kernel.screw({"outer": polygon_loop([lift(q) for q in tooth["points"]]), "holes": []}, center, axis, 2 * math.pi * turns, P, bool(t.get("leftHanded")), True)
        cutter = lone_solid(occt, occt.cut(band, screwed))
        for at, out in chamfer_at:
            step = kernel.cut_tracked(shape, chamfer_ring(at, out))
            history = compose_history(history, step["history"])
            shape = step["shape"]
        cut = kernel.cut_tracked(shape, cutter)
        history = compose_history(history, cut["history"])
        threaded = cut["shape"]
        if hull is not None and sleeve is not None:
            kept = kernel.common_tracked(cut["shape"], hull)
            if kernel.volume(cut["shape"]) - kernel.volume(kept["shape"]) <= kernel.volume(sleeve) + 1e-9:
                history = compose_history(history, kept["history"])
                threaded = kept["shape"]
        note = thread_note(t, internal, drawn, tooth, wanted is not None and fill is None)
        return {"shape": threaded, "history": history, **({"note": note} if note else {})}

    return run("Cutting the thread", lambda: with_sub_shapes(occt, solid, "face", [face_hash], on))
