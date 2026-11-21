# SPDX-License-Identifier: AGPL-3.0-only
"""Compare exact full-field searches, without FreeCAD or private scan files.

    python scripts/benchmark_deviation.py --points 8192 --repeats 3

Optional --input is an NPZ with V/F reference arrays and scan/normals query
arrays. All query vertices are used; no input paths are included in results.
Timings exclude geometry loading, reference construction, and vertex normals.
The first accelerated pass includes its additional spatial-index construction.
"""
import argparse
import json
import platform
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scanrulerfc.dev_map import compute_deviation  # noqa: E402
from scanrulerfc.dev_rigid import identity  # noqa: E402
from scanrulerfc.dev_surface import NominalSurface  # noqa: E402
from scanrulerfc import dev_search_accel  # noqa: E402


def torus(major, minor, count):
    u = np.arange(major)[:, None] * (2 * np.pi / major)
    v = np.arange(minor)[None, :] * (2 * np.pi / minor)
    radius = 50 + 8 * np.cos(v)
    V = np.stack(np.broadcast_arrays(radius * np.cos(u), radius * np.sin(u), 8 * np.sin(v)), axis=-1).reshape(-1, 3)
    a = np.arange(major * minor).reshape(major, minor)
    b = np.roll(a, -1, axis=0)
    c = np.roll(b, -1, axis=1)
    d = np.roll(a, -1, axis=1)
    F = np.concatenate([np.stack([a, b, c], axis=-1).reshape(-1, 3), np.stack([a, c, d], axis=-1).reshape(-1, 3)])
    rng = np.random.default_rng(42)
    t = V[F[rng.integers(len(F), size=count)]]
    N = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    N /= np.linalg.norm(N, axis=1)[:, None]
    weights = rng.random((count, 3))
    weights /= weights.sum(axis=1)[:, None]
    P = np.einsum("ij,ijk->ik", weights, t) + N * rng.normal(0, .2, (count, 1))
    return V, F, P, N


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--points", type=int, default=8192)
    parser.add_argument("--major-segments", type=int, default=512)
    parser.add_argument("--minor-segments", type=int, default=256)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if min(args.points, args.repeats) < 1 or min(args.major_segments, args.minor_segments) < 3:
        parser.error("points/repeats must be positive and segment counts at least three")
    if args.input:
        with np.load(args.input, allow_pickle=False) as data:
            V, F, P, N = (data[k] for k in ("V", "F", "scan", "normals"))
    else:
        V, F, P, N = torus(args.major_segments, args.minor_segments, args.points)
    surface = NominalSurface(V, F)
    normal_search = surface._search
    reference = None
    runs = []
    for backend in ("original", "accelerated"):
        surface._search = surface._search_original if backend == "original" else normal_search
        for repeat in range(args.repeats):
            start = time.perf_counter()
            values = compute_deviation(surface, P, identity(), N, np.pi / 2)
            seconds = time.perf_counter() - start
            if reference is None:
                reference = values.copy()
            same_mask = np.array_equal(np.isfinite(reference), np.isfinite(values))
            mask = np.isfinite(reference) & np.isfinite(values)
            error = float(np.max(np.abs(reference[mask] - values[mask]))) if mask.any() else 0.
            if not same_mask or error > 1e-9:
                raise AssertionError(f"{backend}: measured mask differs or signed error {error:g} mm")
            runs.append({"backend": backend, "repeat": repeat + 1, "seconds": seconds,
                         "same_measured_mask": bool(same_mask), "max_signed_difference_mm": error})
            print(json.dumps(runs[-1]), flush=True)
    print(json.dumps({"python": platform.python_version(), "system": platform.system(),
                      "architecture": platform.machine(), "numpy": np.__version__,
                      "scipy_available": dev_search_accel._KDTree is not None,
                      "vertices": len(P), "reference_triangles": len(F), "runs": runs}, indent=2))


if __name__ == "__main__":
    main()
