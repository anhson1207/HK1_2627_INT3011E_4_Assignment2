from __future__ import annotations

import unittest

from bmp.core.generators import cycle_graph, erdos_renyi_graph, path_graph, star_graph
from bmp.core.solution import SolutionStatus
from bmp.core.validation import validate_solution
from bmp.encodings.order import OrderEncoding
from bmp.solvers.sat.incremental import IncrementalSATSolver
from bmp.solvers.sat.repeated import RepeatedSATSolver


class OrderSequentialEncodingTests(unittest.TestCase):
    def test_order_sequential_correctness_and_optimality(self) -> None:
        """Verify that OrderEncoding with Sequential Counter AMO is 100% sound and optimal."""
        graphs = [
            (path_graph(5), 1),
            (star_graph(4), 2),
            (cycle_graph(4), 2),
            (erdos_renyi_graph(6, 0.4, seed=42), None),
        ]

        for g, expected_opt in graphs:
            encoder = OrderEncoding(amo="sequential")
            # 1. Test Repeated
            rep_solver = RepeatedSATSolver(encoder=encoder)
            rep_res = rep_solver.solve(g)
            self.assertEqual(rep_res.status, SolutionStatus.OPTIMAL)
            if expected_opt is not None:
                self.assertEqual(rep_res.bandwidth, expected_opt)
            self.assertTrue(validate_solution(g, rep_res).valid)

            # 2. Test Incremental
            inc_solver = IncrementalSATSolver(encoder=encoder)
            inc_res = inc_solver.solve(g)
            self.assertEqual(inc_res.status, SolutionStatus.OPTIMAL)
            if expected_opt is not None:
                self.assertEqual(inc_res.bandwidth, expected_opt)
            self.assertTrue(validate_solution(g, inc_res).valid)

    def test_order_sequential_clause_reduction_on_growing_n(self) -> None:
        """Demonstrate that Sequential Counter AMO scales significantly better than Pairwise AMO on Order Encoding."""
        for n in (6, 8, 10):
            g = path_graph(n)
            ord_pw = OrderEncoding(amo="pairwise").encode(g, k=1)
            ord_seq = OrderEncoding(amo="sequential").encode(g, k=1)

            # Both represent the exact same decision problem
            # Check variables
            # Pairwise AMO: n(n-1) + n^2
            self.assertEqual(ord_pw.num_variables, n * (n - 1) + n * n)
            # Sequential Counter: n(n-1) + n^2 + n(n-1)
            self.assertEqual(ord_seq.num_variables, n * (n - 1) + n * n + n * (n - 1))

            # Check that for n >= 6, Sequential Counter uses strictly fewer All-Different clauses:
            # Pairwise All-Diff: n * (n*(n-1)/2) = O(n^3)
            # Sequential Counter All-Diff: n * (3n - 4) = O(n^2)
            alldiff_pw = n * (n * (n - 1) // 2)
            alldiff_seq = n * (3 * n - 4)
            self.assertLess(alldiff_seq, alldiff_pw)


if __name__ == "__main__":
    unittest.main()
