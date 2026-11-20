# SPDX-License-Identifier: AGPL-3.0-only
# Ported from ScanRuler by CNC Kitchen: src/core/deviation/icp.ts,
# src/core/deviation/align.ts, src/core/deviation/deviation.ts (scanNormalsSign)
#
# Point-to-plane ICP pulling a thinned sample of the scan onto the reference,
# and the three best fits built on it: automatic (the identity and the 24
# principal-axis attitudes screened, wound both ways, the best few run on,
# the winner refined), from picked pairs (Horn's closed form, then ICP), and
# local (the fit in hand refined on marked surface only, gated so a patch
# cannot snap onto a neighbouring feature). Poses are compared on a capped
# mean over every sample, so a fit cannot score better by letting go of the
# part. The arithmetic is ScanRuler's; each pass pairs every sample at once
# through numpy instead of one at a time. Added here: the fine fit's passes
# on a thinned share first, a stop when the rms holds, and, where two poses
# screen almost alike, each refined and read before one is taken (or none).

import math

import numpy as np

from . import dev_rigid as R


class AlignError(Exception):
    pass


# ---- samples ----


def sample_scan(positions, normals, wanted, seed=0x5EED):
    """An evenly thinned sample: a deterministic stride with a random phase,
    so repeat runs on the same scan give the same answer."""
    positions = np.asarray(positions, dtype=float).reshape(-1, 3)
    total = len(positions)
    count = min(int(wanted), total)
    if count <= 0:
        return {"xyz": np.zeros((0, 3)), "normals": None, "count": 0}
    stride = total / count
    phase = R.mulberry32(seed)()
    v = np.minimum(total - 1, np.floor((np.arange(count) + phase) * stride).astype(np.int64))
    return {"xyz": positions[v].copy(), "normals": None if normals is None else np.asarray(normals, dtype=float)[v].copy(), "count": count}


def _thinned(s, every):
    return {"xyz": s["xyz"][::every], "normals": None if s["normals"] is None else s["normals"][::every], "count": len(s["xyz"][::every])}


def _flipped(s):
    return s if s["normals"] is None else {**s, "normals": -s["normals"]}


# ---- pairing ----


def pair_all(surface, samples, transform, max_pair, facing_search, min_dot, score_cap, hint=None):
    """Every sample paired with the reference under `transform`: the sample
    in the reference frame, its closest point and pseudonormal there, the
    distance, what it adds to the pose score, whether it may drive the
    step, and the triangle each found (the next pass's hint)."""
    xyz = samples["xyz"]
    n = len(xyz)
    q = transform.apply(xyz)
    sn = transform.rotate(samples["normals"]) if samples["normals"] is not None else None
    hit = surface.closest(q, max_pair, hint=hint)
    faces = hit.face.copy()
    paired = hit.found.copy()
    cp, cn, dist = hit.point, hit.normal, hit.distance
    if facing_search and sn is not None:
        # Nearest surface first; only a sample whose nearest surface faces
        # back at it pays for the facing-aware search.
        redo = paired & (np.einsum("ij,ij->i", sn, cn) < min_dot)
        if redo.any():
            idx = np.nonzero(redo)[0]
            h2 = surface.closest(q[idx], max_pair, facing=sn[idx], min_dot=min_dot)
            paired[idx] = h2.found
            cp[idx], cn[idx], dist[idx] = h2.point, h2.normal, h2.distance
    score = np.full(n, float(score_cap))
    ok = paired & ~(dist > max_pair)
    if sn is not None:
        ok &= ~(np.einsum("ij,ij->i", sn, cn) < min_dot)
    score[ok] = np.minimum(dist[ok], score_cap)
    return q, cp, cn, dist, score, ok, faces


# ---- ICP ----


# A pass whose rms differs from the last one's by no more than this share
# (or by the motion tolerance) is steady; STEADY_PASSES of them in a row end
# the fit as converged. Without it a pose that only creeps (a plate sliding
# in its own plane, a rejection cut that trades the same few points back and
# forth) ran every pass: 70 passes, 106 s, "not converged" on the Mac.
RMS_STEADY = 1e-4
STEADY_PASSES = 2
SCORE_SLACK = 0.01


def icp(surface, samples, initial, max_iterations=60, reject_median_factor=3.0, min_normal_dot=0.0, facing_search=False, max_pair_distance=math.inf, score_cap=None, tolerance=None, on_iteration=None, rms_steady=RMS_STEADY):
    """Point-to-plane ICP fitting samples (scan frame) onto surface
    (reference frame) from `initial`. The increment is taken about the
    correspondences' centroid, so the 6x6 solve stays well conditioned for a
    part far from the origin. Each pass starts its closest-point search
    from the triangle the sample found on the last pass (a bound only: the
    pairs are the same). Converged: the step moves less than the
    tolerance, or the rms holds steady (rms_steady, None for off)."""
    facing_search = facing_search is True and samples["normals"] is not None and min_normal_dot > 0 and math.isfinite(max_pair_distance)
    diag = surface.bbox_diagonal
    tolerance = diag * 1e-7 if tolerance is None else tolerance
    score_cap = diag * 0.05 if score_cap is None else score_cap

    transform = initial.copy()
    best = initial.copy()
    best_score = math.inf
    best_rms = math.inf
    best_mean = math.inf
    best_matched = 0
    iterations = 0
    converged = False
    n = samples["count"]
    hint = None
    last = None
    last_rms = math.inf
    steady = 0

    for it in range(max_iterations):
        iterations = it + 1
        q, cp, cn, dist, pscore, ok, hint = pair_all(surface, samples, transform, max_pair_distance, facing_search, min_normal_dot, score_cap, hint)
        # Truncated mean over every sample, not just the survivors of the cut.
        score = float(pscore.sum()) / n
        found = int(ok.sum())
        if found < 3:
            break
        head = np.sort(dist[ok])
        median = head[found >> 1]
        cutoff = max(median * reject_median_factor, diag * 1e-5)
        ok = ok & ~(dist > cutoff)
        matched = int(ok.sum())
        if matched < 6:
            break
        Q, CP, CN = q[ok], cp[ok], cn[ok]
        c = Q.mean(axis=0)
        mean_distance = float(dist[ok].sum()) / matched
        r = np.einsum("ij,ij->i", Q - CP, CN)
        J = np.hstack([np.cross(Q - c, CN), CN])
        ata = J.T @ J
        atb = -(J.T @ r)
        rms = math.sqrt(float((r * r).sum()) / matched)
        if on_iteration:
            on_iteration(iterations, mean_distance, transform)
        if score < best_score:
            best_score, best_rms, best_mean, best_matched = score, rms, mean_distance, matched
            best = transform.copy()
        last = (transform.copy(), score, rms, mean_distance, matched)
        if rms_steady is not None:
            steady = steady + 1 if abs(rms - last_rms) <= max(rms * rms_steady, tolerance) else 0
            last_rms = rms
            if steady >= STEADY_PASSES:
                converged = True
                break
        # A touch of Levenberg damping: a plate free to slide in its own
        # plane would otherwise answer with an arbitrary slide along it.
        lam = (np.trace(ata) / 6) * 1e-9 + 1e-12
        ata = ata + np.eye(6) * lam
        try:
            step = np.linalg.solve(ata, atb)
        except np.linalg.LinAlgError:
            break
        if not np.isfinite(step).all():
            break
        omega, tau = step[:3], step[3:]
        angle = float(np.linalg.norm(omega))
        shift = float(np.linalg.norm(tau))
        max_angle, max_shift = 0.35, diag * 0.5
        scale = min(1.0, max_angle / angle if angle > max_angle else 1.0, max_shift / shift if shift > max_shift else 1.0)
        if scale < 1:
            omega, tau = omega * scale, tau * scale
        local = R.from_twist(omega, tau)
        delta = R.Rigid(local.r, c + local.t - local.r @ c)
        transform = R.reorthonormalize(R.compose(delta, transform))
        moved = float(np.linalg.norm(omega)) * diag * 0.5 + float(np.linalg.norm(tau))
        if moved < tolerance:
            converged = True
            break

    # The pose it settled on, when it settled and scores within SCORE_SLACK
    # of the best seen: the score (a truncated mean) is too coarse to choose
    # between poses a few micrometres apart, and the passes after the first
    # good one still close in (a 4-pair fit, 0.0085 mm off at the best
    # score, 0.0018 mm settled).
    if converged and last is not None and last[1] <= best_score + max(best_score * SCORE_SLACK, tolerance):
        best, best_score, best_rms, best_mean, best_matched = last[0], last[1], last[2], last[3], last[4]

    return {
        "transform": best,
        "iterations": iterations,
        "rms": best_rms if math.isfinite(best_rms) else 0.0,
        "meanDistance": best_mean if math.isfinite(best_mean) else 0.0,
        "score": best_score,
        "matched": best_matched,
        "sampled": n,
        "converged": converged,
    }


# ---- which way the scan is wound ----


def scan_normals_sign(surface, positions, normals, transform, vertices=None, near=None):
    """1 when the scan's normals point out of the material, -1 into it: the
    sign of their agreement with the surface each lies nearest, a vote
    weighted by 1 / (1 + (d / near)^2)."""
    positions = np.asarray(positions, dtype=float).reshape(-1, 3)
    normals = np.asarray(normals, dtype=float).reshape(-1, 3)
    idx = np.arange(len(positions)) if vertices is None else np.asarray(vertices, dtype=np.int64)
    step = max(1, len(idx) // 2000)
    idx = idx[::step]
    if len(idx) == 0:
        return 1
    hit = surface.closest(transform.apply(positions[idx]))
    f = hit.found
    if not f.any():
        return 1
    d = hit.distance[f]
    agree = np.einsum("ij,ij->i", transform.rotate(normals[idx][f]), hit.normal[f])
    scale = near
    if scale is None:
        srt = np.sort(d)
        scale = max(srt[len(srt) // 5], surface.bbox_diagonal * 1e-5)
    total = float((agree / (1 + (d / scale) ** 2)).sum())
    return -1 if total < 0 else 1


def _outward(surface, samples, pose):
    if samples["normals"] is None or samples["count"] == 0:
        return samples
    return samples if scan_normals_sign(surface, samples["xyz"], samples["normals"], pose) == 1 else _flipped(samples)


# ---- the fits ----

SCREEN_ITERATIONS = 6
SCREEN_REACH = 0.1
COARSE_ITERATIONS = 20
SHORTLIST = 5
FINE_ITERATIONS = 70
AMBIGUITY_MARGIN = 1.25
MIN_LOCAL_POINTS = 50
FLAT_SELECTION = 0.05


# The fine fit runs its passes on a thinned share of the samples (every
# k-th, about THIN_SAMPLES of them), then settles on all of them in a few
# FULL_PASSES from there: the same pose, the cost of the passes cut by the
# share thinned away.
THIN_SAMPLES = 6000
FULL_PASSES = 12


def _fine_icp(surface, samples, start, progress, label):
    def note(stage):
        return (lambda i, d, m: progress(f"{label} — pass {i}{stage}, mean deviation {d:.4f} mm…")) if progress else None

    kw = dict(reject_median_factor=3, min_normal_dot=0.3)
    every = samples["count"] // THIN_SAMPLES
    if every < 2:
        return icp(surface, samples, start, max_iterations=FINE_ITERATIONS, on_iteration=note(""), **kw)
    thin = icp(surface, _thinned(samples, every), start, max_iterations=FINE_ITERATIONS, on_iteration=note(" (thinned)"), **kw)
    full = icp(surface, samples, thin["transform"] if thin["matched"] else start, max_iterations=FULL_PASSES, on_iteration=note(" (all samples)"), **kw)
    full["iterations"] += thin["iterations"]
    return full


def _fine(surface, given, start, source, ambiguous, progress=None, orient=True):
    samples = _outward(surface, given, start) if orient else given
    r = _fine_icp(surface, samples, start, progress, "Aligning")
    if r["matched"] == 0:
        raise AlignError(
            "No scan point found reference surface facing its way, so the scan was left where it was. Check that the scan and the reference are the same part, or pick a few point pairs to start from."
        )
    return {"transform": r["transform"], "source": source, "rms": r["rms"], "meanDistance": r["meanDistance"], "iterations": r["iterations"], "matched": r["matched"], "sampled": r["sampled"], "ambiguous": ambiguous, **_quality(r)}


MIN_MATCHED_SHARE = 0.5


def _quality(r):
    """Whether ICP settled and the share of the samples that drove the
    final pose: plain bool and float."""
    share = float(r["matched"]) / r["sampled"] if r["sampled"] else 0.0
    return {"converged": bool(r["converged"]), "matchedShare": share}


def quality_warnings(res):
    """What an agent must hear about a best fit before trusting its map."""
    out = []
    share = res.get("matchedShare")
    if share is not None and share < MIN_MATCHED_SHARE:
        out.append(f"Only {share * 100:.0f} % of the sampled scan points found the reference within reach when the fit ended (under {MIN_MATCHED_SHARE * 100:.0f} %): the pose rests on a minority of the scan. Check the scan and the reference are the same part in the same units, or start from point pairs (mode points).")
    if res.get("tied"):
        out.append(f"{res['tied']} poses fitted equally well (the part turns onto itself, or nearly). The one that leaves the scan turned as it was opened ({res['tieTurnDeg']:.0f}°) was taken. If the scan was not opened in the reference's orientation, give three point pairs (mode points).")
    if res.get("converged") is False:
        out.append(f"The best fit had not settled after {res.get('iterations')} passes: the pose is the best one seen, not a converged one. Run deviation_align again, or start from point pairs (mode points).")
    return out


def auto_align(surface, positions, normals, coarse_samples=4000, fine_samples=25_000, progress=None):
    """Best fit with no help: the identity (two files exported in one frame)
    and the 24 principal-axis attitudes, each screened wound both ways; the
    best few run on; the winner refined on more points."""
    coarse = sample_scan(positions, normals, coarse_samples)
    scan_frame = R.principal_frame(coarse["xyz"])
    nominal_frame = R.principal_frame(surface.positions)
    candidates = [R.identity()] + R.prealign_candidates(scan_frame, nominal_frame)
    turned = _flipped(coarse) if coarse["normals"] is not None else None
    windings = [(coarse, coarse), (turned, _thinned(turned, 4))] if turned is not None else [(coarse, coarse)]
    screened = []
    # A screen pairs no further than SCREEN_REACH of the diagonal: past the
    # score's own cap (5 %) a pair adds the same to the score found or not,
    # and the search for it in a far pose is what made a screen slow (42 s
    # of 50 on a 167,000-triangle reference).
    reach = surface.bbox_diagonal * SCREEN_REACH
    for i, cand in enumerate(candidates):
        if progress:
            progress(f"Aligning — screening start {i + 1} of {len(candidates)}…")
        for samples, screen in windings:
            r = icp(surface, screen, cand, max_iterations=SCREEN_ITERATIONS, reject_median_factor=2.5, min_normal_dot=0, max_pair_distance=reach)
            screened.append({**r, "samples": samples})
    screened.sort(key=lambda r: r["score"])
    scored = []
    for i, s in enumerate(screened[:SHORTLIST]):
        if progress:
            progress(f"Aligning — trying start {i + 1} of {SHORTLIST}…")
        r = icp(surface, s["samples"], s["transform"], max_iterations=COARSE_ITERATIONS, reject_median_factor=2.5, min_normal_dot=0)
        scored.append({**r, "samples": s["samples"]})
    scored.sort(key=lambda r: r["score"])
    winner = scored[0]
    radius = float(np.linalg.norm(coarse["xyz"] - scan_frame["centroid"], axis=1).max()) if coarse["count"] else 0.0
    # Any start on the shortlist, not only the runner-up (often the
    # winner's own pose, wound the other way), that scored almost as well
    # and sits apart from the winner.
    ambiguous = any(
        s["score"] < winner["score"] * AMBIGUITY_MARGIN + surface.bbox_diagonal * RMS_FLOOR and R.disagreement(winner["transform"], s["transform"], scan_frame["centroid"], radius) > surface.bbox_diagonal * 0.01
        for s in scored[1:]
    )
    if progress:
        progress("Aligning — refining…")
    sampled = sample_scan(positions, normals, fine_samples)

    def fine_of(s):
        samples = sampled if s["samples"] is coarse else _flipped(sampled)
        return _fine(surface, samples, s["transform"], "auto", False, progress, orient=False), samples

    if not ambiguous:
        return fine_of(winner)[0]
    return _settle_ambiguous(surface, scored, winner, fine_of, scan_frame["centroid"], radius, progress)


# ---- two poses that fit almost as well ----

# Rivals refined when the screen is ambiguous, and how far apart two
# refined poses must read before one is taken over the other.
MAX_RIVALS = 4
FACING_GAP = 0.05
SHARE_GAP = 0.02
RMS_RATIO = 1.1
RMS_FLOOR = 1e-5


def facing_check(surface, samples, transform, reach):
    """How one-sided the pairs are under a pose: of the samples within
    reach of the reference, the share whose normal agrees with the
    reference's there (dot > 0) or, if fewer, the share that disagrees.
    Near 1 when every surface of the scan lies on a surface of the
    reference facing the same way (as wound); lower when the pose lays the
    scan's outside on the reference's inside somewhere, as an open part
    turned over does. Also the share of the samples within reach."""
    if samples["normals"] is None or samples["count"] == 0:
        return {"facing": None, "within": 0.0}
    q = transform.apply(samples["xyz"])
    hit = surface.closest(q, reach)
    f = hit.found
    if not f.any():
        return {"facing": None, "within": 0.0}
    agree = float((np.einsum("ij,ij->i", transform.rotate(samples["normals"][f]), hit.normal[f]) > 0).mean())
    return {"facing": max(agree, 1 - agree), "within": float(f.mean())}


def _better(a, b, rms_floor=0.0):
    """Whether refined pose a reads clearly better than b, and on what:
    the facing check first, then the matched share, then the rms (two
    rms closer than rms_floor, mm, are the same: on a scan with no noise
    both are rounding)."""
    fa, fb = a["check"]["facing"], b["check"]["facing"]
    if fa is not None and fb is not None and abs(fa - fb) > FACING_GAP:
        return fa > fb, "facing"
    if abs(a["matchedShare"] - b["matchedShare"]) > SHARE_GAP:
        return a["matchedShare"] > b["matchedShare"], "matchedShare"
    ra, rb = a["rms"], b["rms"]
    if max(ra, rb) > RMS_RATIO * min(ra, rb) + rms_floor:
        return ra < rb, "rms"
    return None, None


def _settle_ambiguous(surface, scored, winner, fine_of, centre, radius, progress):
    """The screen found a second pose almost as good (a part near a
    symmetry). Each distinct rival is refined in full and read on its
    facing check, matched share and rms; the clear best is taken. When
    none reads clearly better, nothing is moved: three point pairs decide."""
    reach = surface.bbox_diagonal * 0.02
    floor = surface.bbox_diagonal * RMS_FLOOR
    apart = surface.bbox_diagonal * 0.01
    rivals = []
    for s in scored:
        if s["score"] >= winner["score"] * AMBIGUITY_MARGIN + floor:
            continue
        if any(R.disagreement(s["transform"], o["transform"], centre, radius) <= apart for o in rivals):
            continue
        rivals.append(s)
        if len(rivals) == MAX_RIVALS:
            break
    done = []
    for i, s in enumerate(rivals):
        if progress:
            progress(f"Aligning — two poses fit almost as well: refining pose {i + 1} of {len(rivals)}…")
        try:
            res, samples = fine_of(s)
        except AlignError:
            continue
        res["check"] = facing_check(surface, samples, res["transform"], reach)
        done.append(res)
    # Refined poses that came together are one pose.
    distinct = []
    for res in done:
        if not any(R.disagreement(res["transform"], o["transform"], centre, radius) <= apart for o in distinct):
            distinct.append(res)
    if not distinct:
        raise AlignError(AMBIGUOUS_REFUSAL)
    best = distinct[0]
    for res in distinct[1:]:
        won, _ = _better(res, best, floor)
        if won:
            best = res
    tied = [best] + [res for res in distinct if res is not best and not _better(best, res, floor)[0]]
    tie_turn = None
    if len(tied) > 1:
        # No pose reads clearly best: a part that turns onto itself (a
        # plain box, a tray) or a scan that sees too little. Where exactly
        # one of them leaves the scan turned as it was opened (under
        # TIE_TURN_DEG), it is taken: the scan was placed like the
        # reference, and a turn of it would be the flip. Else nothing moves.
        turns = [math.degrees(R.rotation_angle(res["transform"])) for res in tied]
        near = [i for i, a in enumerate(turns) if a < TIE_TURN_DEG]
        if len(near) != 1:
            raise AlignError(AMBIGUOUS_REFUSAL)
        best, tie_turn = tied[near[0]], turns[near[0]]
    out = {k: v for k, v in best.items() if k != "check"}
    out["ambiguous"] = False
    out["poses"] = len(distinct)
    out["chosenOn"] = sorted({_better(best, r, floor)[1] or "nearest the scan's own turn" for r in distinct if r is not best})
    out["facing"] = best["check"]["facing"]
    if tie_turn is not None:
        out["tied"] = len(tied)
        out["tieTurnDeg"] = tie_turn
    return out


TIE_TURN_DEG = 45.0


AMBIGUOUS_REFUSAL = (
    "Two or more poses fit the scan almost equally well (the part is near a symmetry, or the scan sees too little of it): "
    "none was clearly better on matched share, rms or which way its surfaces face, and none leaves the scan turned as it was opened — "
    "so the scan was left where it was, not fitted the wrong way round. Give three point pairs: deviation_align { mode: \"points\", pairs: [{ scan, reference }, ...] }, "
    "three or more places on the scan and the same places on the reference, not in a line, at least one on a feature that breaks the symmetry "
    "(scan_nearest reads a place on the scan)."
)


def align_from_pairs(surface, positions, normals, pairs, fine_samples=25_000, vertices=None, progress=None):
    """Best fit started from hand-picked pairs [(scan, reference), ...]."""
    if len(pairs) < 3:
        raise AlignError("Pick at least three point pairs — two cannot fix a rotation.")
    solved = R.absolute_orientation([p[0] for p in pairs], [p[1] for p in pairs])
    if not solved:
        raise AlignError("Could not solve the picked points.")
    if solved["conditioning"] < 0.02:
        raise AlignError("The picked points are nearly in a line — add one away from that line, so the rotation about it is fixed.")
    positions = np.asarray(positions, dtype=float).reshape(-1, 3)
    sel = np.asarray(vertices, dtype=np.int64) if vertices is not None and len(vertices) > 0 else None
    if sel is not None and len(sel) < MIN_LOCAL_POINTS:
        raise AlignError(f"Select more surface — a fit needs at least {MIN_LOCAL_POINTS} selected points, and this selection has {len(sel)}. Clear the selection to fit on the whole scan.")
    src_p = positions if sel is None else positions[sel]
    src_n = None if normals is None else (normals if sel is None else np.asarray(normals)[sel])
    samples = sample_scan(src_p, src_n, fine_samples)
    out = _fine(surface, samples, solved["transform"], "points", False, progress)
    out["pairRms"] = solved["rms"]
    if sel is not None:
        out["selected"] = int(len(sel))
    return out


def _normal_spread(normals):
    if normals is None or len(normals) == 0:
        return 1.0
    m = normals.T @ normals / len(normals)
    return float(np.linalg.eigvalsh(m)[1])


def align_local(surface, positions, normals, vertices, start, max_distance, fine_samples=25_000, progress=None):
    """Fine tuning on marked surface only, from a fit that roughly holds;
    pairs past max_distance refused outright."""
    vertices = np.asarray(vertices, dtype=np.int64)
    if len(vertices) < MIN_LOCAL_POINTS:
        raise AlignError(f"Mark more surface — a local fit needs at least {MIN_LOCAL_POINTS} marked points, and this selection has {len(vertices)}.")
    if not (max_distance > 0):
        raise AlignError("The maximum search distance must be greater than zero.")
    positions = np.asarray(positions, dtype=float).reshape(-1, 3)
    samples = sample_scan(positions[vertices], None if normals is None else np.asarray(normals)[vertices], fine_samples)
    r = icp(
        surface,
        samples,
        start,
        max_iterations=FINE_ITERATIONS,
        reject_median_factor=3,
        min_normal_dot=0.5,
        facing_search=True,
        max_pair_distance=max_distance,
        score_cap=max_distance,
        on_iteration=(lambda i, d, m: progress(f"Fine fit — pass {i}, mean deviation {d:.4f} mm…")) if progress else None,
    )
    if r["matched"] == 0:
        raise AlignError(f"No marked point found reference surface within {max_distance} mm. Raise the maximum search distance, or run the global best fit first.")
    return {
        "transform": r["transform"],
        "source": "local",
        "rms": r["rms"],
        "meanDistance": r["meanDistance"],
        "iterations": r["iterations"],
        "matched": r["matched"],
        "sampled": r["sampled"],
        "ambiguous": False,
        **_quality(r),
        "selected": int(len(vertices)),
        "searchDistance": max_distance,
        "underconstrained": _normal_spread(samples["normals"]) < FLAT_SELECTION,
    }
