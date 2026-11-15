# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): src/core/fit/sparse.ts (the solvers plugins/reverse/core/networkMap.ts and networkFit.ts use)
# SPDX-License-Identifier: AGPL-3.0-only
#
# The sparse solvers: triplets with duplicates summed into compressed rows,
# a row's columns in order; the product; conjugate gradient on a symmetric
# positive-definite system and BiCGSTAB on one that is not, both to the
# dense solution; a zero right-hand side zero at once.
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from scanrulerfc.reverse.sparse import Triplets, biconjugate_gradient_stabilized, conjugate_gradient  # noqa: E402


def laplacian(n, skew=0.0):
    t = Triplets(n)
    for i in range(n):
        t.add(i, i, 4.0)
        if i > 0:
            t.add(i, i - 1, -1.0 - skew)
        if i + 1 < n:
            t.add(i, i + 1, -1.0 + skew)
        t.add(i, i, 0.5)
    return t


class Sparse(unittest.TestCase):
    def test_triplets_sum_their_duplicates_into_ordered_rows(self):
        t = Triplets(3)
        t.add(1, 2, 1.0)
        t.add(1, 0, 2.0)
        t.add(1, 2, 3.0)
        t.add(0, 0, 0.0)
        a = t.to_csr()
        self.assertEqual(list(a.row_ptr), [0, 0, 2, 2])
        self.assertEqual(list(a.cols), [0, 2])
        self.assertEqual(list(a.vals), [2.0, 4.0])
        self.assertEqual(list(a.multiply(np.array([1.0, 1.0, 1.0]))), [0.0, 6.0, 0.0])

    def test_conjugate_gradient_solves_a_symmetric_system(self):
        t = laplacian(50)
        a = t.to_csr()
        dense = np.zeros((50, 50))
        np.add.at(dense, (np.array(t.rows), np.array(t.cols)), np.array(t.vals))
        b = np.sin(np.arange(50.0))
        r = conjugate_gradient(a, b, tolerance=1e-12)
        self.assertTrue(r["converged"])
        np.testing.assert_allclose(r["x"], np.linalg.solve(dense, b), atol=1e-10)
        self.assertEqual(conjugate_gradient(a, np.zeros(50))["iterations"], 0)

    def test_bicgstab_solves_one_that_is_not(self):
        t = laplacian(40, 0.3)
        dense = np.zeros((40, 40))
        np.add.at(dense, (np.array(t.rows), np.array(t.cols)), np.array(t.vals))
        b = np.cos(np.arange(40.0))
        r = biconjugate_gradient_stabilized(t.to_csr(), b, tolerance=1e-12)
        self.assertTrue(r["converged"])
        np.testing.assert_allclose(r["x"], np.linalg.solve(dense, b), atol=1e-10)


if __name__ == "__main__":
    unittest.main()
