# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): src/core/fit/sparse.ts (what plugins/reverse/core/networkMap.ts and networkFit.ts solve with)
# SPDX-License-Identifier: AGPL-3.0-only
#
# Sparse linear algebra for systems too large for a dense Cholesky: a matrix
# in compressed rows (CSR), assembled from triplets with their duplicates
# summed, the conjugate gradient method for symmetric positive-definite
# systems preconditioned by the diagonal (Jacobi), and BiCGSTAB for a
# system that is not symmetric.
#
# In numpy, with the original's sums in its order: duplicates summed in
# the order they came, a row's products summed left to right, the dot
# products summed in index order (a cumulative sum, not numpy's pairwise
# one). So the iterations and the solutions are the original's.

import math

import numpy as np


def _dot(a, b):
    if a.shape[0] == 0:
        return 0.0
    return float(np.cumsum(a * b)[-1])


class CsrMatrix:
    """A square matrix in compressed rows: row i's entries are cols/vals in
    [row_ptr[i], row_ptr[i + 1]), their columns ascending and each once."""

    __slots__ = ("n", "row_ptr", "cols", "vals", "_rows", "_slot", "_width")

    def __init__(self, n, row_ptr, cols, vals):
        self.n = n
        self.row_ptr = row_ptr
        self.cols = cols
        self.vals = vals
        lens = np.diff(row_ptr)
        self._rows = np.repeat(np.arange(n), lens)
        self._slot = np.arange(cols.shape[0]) - row_ptr[self._rows] if cols.shape[0] else np.zeros(0, dtype=np.int64)
        self._width = int(lens.max()) if n > 0 and cols.shape[0] else 0

    def multiply(self, x, out=None):
        """out = A x, each row's products summed left to right."""
        prod = self.vals * x[self.cols]
        pad = np.zeros((self.n, max(1, self._width)))
        pad[self._rows, self._slot] = prod
        s = np.zeros(self.n)
        for k in range(self._width):
            s += pad[:, k]
        if out is None:
            return s
        out[:] = s
        return out

    def diagonal(self):
        d = np.zeros(self.n)
        on = self.cols == self._rows
        d[self._rows[on]] = self.vals[on]
        return d


class Triplets:
    """Entries gathered in any order, a position given more than once summed."""

    def __init__(self, n, capacity=16):
        self.n = n
        self.rows = []
        self.cols = []
        self.vals = []

    @property
    def size(self):
        return len(self.rows)

    def add(self, i, j, v):
        if v == 0:
            return
        self.rows.append(i)
        self.cols.append(j)
        self.vals.append(v)

    def add_many(self, i, j, v):
        """Many entries at once, in order (numpy arrays); zeros dropped."""
        v = np.asarray(v, dtype=float)
        keep = v != 0
        self.rows.extend(np.asarray(i)[keep].tolist())
        self.cols.extend(np.asarray(j)[keep].tolist())
        self.vals.extend(v[keep].tolist())

    def add_outer(self, idx, w, v):
        for a in range(len(idx)):
            va = v * w[a]
            if va == 0:
                continue
            for b in range(len(idx)):
                self.add(idx[a], idx[b], va * w[b])

    def to_csr(self):
        return csr_from_triplets(self.n, self.rows, self.cols, self.vals)


def csr_from_triplets(n, rows, cols, vals):
    """A CSR matrix of the triplets, duplicates summed in their order."""
    rows = np.asarray(rows, dtype=np.int64)
    cols = np.asarray(cols, dtype=np.int64)
    vals = np.asarray(vals, dtype=float)
    if rows.shape[0] == 0:
        return CsrMatrix(n, np.zeros(n + 1, dtype=np.int64), np.zeros(0, dtype=np.int64), np.zeros(0))
    key = rows * n + cols
    uniq, inv = np.unique(key, return_inverse=True)
    sums = np.bincount(inv, weights=vals, minlength=uniq.shape[0])
    r = uniq // n
    c = uniq - r * n
    counts = np.bincount(r, minlength=n)
    row_ptr = np.zeros(n + 1, dtype=np.int64)
    np.cumsum(counts, out=row_ptr[1:])
    return CsrMatrix(n, row_ptr, c, sums)


class LinearOperator:
    """An operator: its size, its product with a vector (apply(x) -> A x)
    and its diagonal for the preconditioner where known."""

    def __init__(self, n, apply, diagonal=None):
        self.n = n
        self.apply = apply
        self.diagonal = diagonal


def _operator(a):
    if isinstance(a, CsrMatrix):
        return LinearOperator(a.n, a.multiply, a.diagonal())
    return a


def _result(x, iterations, residual, tolerance):
    return {"x": x, "iterations": iterations, "residual": residual, "converged": residual <= tolerance}


def conjugate_gradient(a, b, x0=None, tolerance=1e-10, max_iterations=None, precondition=True):
    """Solve A x = b for a symmetric positive-definite A by preconditioned
    conjugate gradient. A zero right-hand side gives zero at once."""
    op = _operator(a)
    n = op.n
    if max_iterations is None:
        max_iterations = max(100, 10 * n)
    b = np.asarray(b, dtype=float)
    x = np.array(x0, dtype=float) if x0 is not None else np.zeros(n)
    inv = np.ones(n)
    if precondition and op.diagonal is not None:
        d = np.asarray(op.diagonal, dtype=float)
        with np.errstate(divide="ignore"):
            inv = np.where(d > 0, 1 / d, 1.0)
    b_norm = math.sqrt(_dot(b, b))
    if not b_norm > 0:
        return _result(np.zeros(n), 0, 0.0, tolerance)
    q = op.apply(x)
    r = b - q
    rr = _dot(r, r)
    z = inv * r
    p = z.copy()
    rz = _dot(r, z)
    goal = tolerance * b_norm
    iterations = 0
    while math.sqrt(rr) > goal and iterations < max_iterations:
        q = op.apply(p)
        pq = _dot(p, q)
        if not pq > 0:
            break
        alpha = rz / pq
        x += alpha * p
        r -= alpha * q
        rr = _dot(r, r)
        z = inv * r
        rz_next = _dot(r, z)
        beta = rz_next / rz
        rz = rz_next
        p = z + beta * p
        iterations += 1
    residual = math.sqrt(rr) / b_norm
    return _result(x, iterations, residual, tolerance)


def biconjugate_gradient_stabilized(a, b, x0=None, tolerance=1e-10, max_iterations=None, precondition=True):
    """Solve A x = b for a square A that need not be symmetric by BiCGSTAB
    (van der Vorst), preconditioned by the diagonal."""
    op = _operator(a)
    n = op.n
    if max_iterations is None:
        max_iterations = max(100, 10 * n)
    b = np.asarray(b, dtype=float)
    x = np.array(x0, dtype=float) if x0 is not None else np.zeros(n)
    inv = np.ones(n)
    if precondition and op.diagonal is not None:
        d = np.asarray(op.diagonal, dtype=float)
        with np.errstate(divide="ignore"):
            inv = np.where(d != 0, 1 / d, 1.0)
    b_norm = math.sqrt(_dot(b, b))
    if not b_norm > 0:
        return _result(np.zeros(n), 0, 0.0, tolerance)
    p = np.zeros(n)
    v = np.zeros(n)
    t = op.apply(x)
    r = b - t
    r0 = r.copy()
    rr = _dot(r, r)
    goal = tolerance * b_norm
    rho = 1.0
    alpha = 1.0
    omega = 1.0
    iterations = 0
    while math.sqrt(rr) > goal and iterations < max_iterations:
        rho_next = _dot(r0, r)
        if rho_next == 0:
            break
        beta = (rho_next / rho) * (alpha / omega)
        rho = rho_next
        p = r + beta * (p - omega * v)
        y = inv * p
        v = op.apply(y)
        r0v = _dot(r0, v)
        if r0v == 0:
            break
        alpha = rho / r0v
        s = r - alpha * v
        ss = _dot(s, s)
        if math.sqrt(ss) <= goal:
            x += alpha * y
            rr = ss
            iterations += 1
            break
        z = inv * s
        t = op.apply(z)
        tt = _dot(t, t)
        ts = _dot(t, s)
        omega = ts / tt if tt > 0 else 0.0
        x += alpha * y + omega * z
        r = s - omega * t
        rr = _dot(r, r)
        iterations += 1
        if omega == 0:
            break
    residual = math.sqrt(rr) / b_norm
    return _result(x, iterations, residual, tolerance)
