# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/core/buildTypes.ts
# SPDX-License-Identifier: AGPL-3.0-only
#
# What the builder hands back and keeps, and the pure helpers beside it:
# stepKeys, the key each build step is built from, which the prefix cache
# matches a kept build's first steps by (so it is the original's string,
# byte for byte: JSON as JavaScript writes it, a non-finite number as
# "#Infinity", a typed array as a list, a map and a set tagged); the box
# test, the Halton spread the split samples by, the mesh deflections, and
# the matching of each wanted fingerprint to a different candidate. The
# result records (FeatureResult, BuiltBody, Snapshot and the rest) are
# build.py's and come with it.

import math

from ._js import UNDEFINED, js_hypot, num_str, stringify

SPLIT_SAMPLES = 1500
SURFACE_TRIANGLES = 300_000


def _plain(v):
    """A value as the original's replacer hands it to JSON."""
    if v is None or v is True or v is False or isinstance(v, str) or v is UNDEFINED:
        return v
    if isinstance(v, (int, float)):
        return v if math.isfinite(v) else f"#{num_str(v)}"
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    if isinstance(v, (set, frozenset)):
        return ["#set", *[_plain(x) for x in v]]
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    if hasattr(v, "tolist"):
        return _plain(v.tolist())
    raise TypeError(f"cannot key {type(v).__name__}")


def key_of(value):
    """A value as one string, telling apart what JSON alone would not."""
    return stringify(_plain(value))


def sketches_read(step):
    """The sketches a step reads beside its own fields, by id."""
    k = step["kind"]
    if k == "sketch":
        return [step["id"], *[s["id"] for s in step["sources"]]]
    if k in ("extrude", "revolve", "sheet"):
        return [step["sketchId"]] if "sketchId" in step else [UNDEFINED]
    if k in ("loft", "sweep"):
        return step["sketches"]
    return []


def step_keys(steps, sketch_of):
    """What each step of a build is built from, as one string a step: the
    step and the sketches it reads."""
    def read(i):
        s = sketch_of(i) if i is not UNDEFINED else None
        return [None if i is UNDEFINED else i, s if s is not None else None]

    return [key_of([step, [read(i) for i in sketches_read(step)]]) for step in steps]


def boxes_meet(a, b):
    margin = 1e-4
    for i in range(3):
        if a["max"][i] < b["min"][i] - margin or b["max"][i] < a["min"][i] - margin:
            return False
    return True


class StepFailed(Exception):
    """A step that cannot be made, in the words its row says."""


def halton(i, base):
    """The i-th point of the van der Corput sequence in a base."""
    f = 1
    r = 0
    while i > 0:
        f /= base
        r += f * (i % base)
        i = i // base
    return r


def mesh_box(positions):
    """The box round a mesh's flat XYZ positions, or None for none."""
    lo = [math.inf] * 3
    hi = [-math.inf] * 3
    for i in range(0, len(positions) - 2, 3):
        for k in range(3):
            x = float(positions[i + k])
            lo[k] = min(lo[k], x)
            hi[k] = max(hi[k], x)
    return {"min": lo, "max": hi} if math.isfinite(lo[0]) else None


def diagonal_of(kernel, shape):
    b = kernel.extent(shape)
    return js_hypot(b["max"][0] - b["min"][0], b["max"][1] - b["min"][1], b["max"][2] - b["min"][2])


def mesh_deflection(diagonal):
    return min(0.05, max(0.005, diagonal * 5e-4))


def surface_mesh_deflection(diagonal):
    return max(0.005, diagonal * 5e-4)


def body_brief(b):
    return {k: v for k, v in b.items() if k not in ("mesh", "topology")}


def pick_each(wanted, candidates, tol, match, describe):
    """Match every wanted fingerprint to a different candidate, in order:
    {hashes} or {lost: words}."""
    taken = set()
    hashes = []
    for w in wanted:
        opened = [i for i in range(len(candidates)) if i not in taken]
        j = match(w, [candidates[i]["fingerprint"] for i in opened], tol)
        if j is None:
            return {"lost": describe(w)}
        taken.add(opened[j])
        hashes.append(candidates[opened[j]]["hash"])
    return {"hashes": hashes}
