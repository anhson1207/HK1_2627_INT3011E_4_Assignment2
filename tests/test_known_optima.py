from __future__ import annotations

import unittest

from bmp.core.generators import (
    complete_graph,
    cycle_graph,
    edgeless_graph,
    path_graph,
    star_graph,
)
from bmp.core.solution import SolutionStatus
from bmp.core.validation import validate_assignment
from bmp.solvers.brute_force import BruteForceSolver


class KnownOptimaTests(unittest.TestCase):
    def test_canonical_known_optima(self) -> None:
        cases = [
            (path_graph(5), 1),
            (complete_graph(5), 4),
            (star_graph(4), 2),
            (cycle_graph(4), 2),
            (edgeless_graph(5), 0),
        ]
        solver = BruteForceSolver()
        for graph, expected in cases:
            with self.subTest(graph=graph.name):
                result = solver.solve(graph, timeout_seconds=5)
                self.assertEqual(result.status, SolutionStatus.OPTIMAL)
                self.assertEqual(result.bandwidth, expected)
                self.assertEqual(result.lower_bound, expected)
                self.assertEqual(result.upper_bound, expected)
                self.assertIsNotNone(result.assignment)
                report = validate_assignment(
                    graph,
                    result.assignment or {},
                    claimed_bandwidth=result.bandwidth,
                )
                self.assertTrue(report.valid, report.errors)

    def test_oracle_rejects_large_instances(self) -> None:
        with self.assertRaises(ValueError):
            BruteForceSolver(max_vertices=5).solve(path_graph(6))

    def test_timeout_is_explicit_and_keeps_a_valid_incumbent(self) -> None:
        graph = cycle_graph(4)
        result = BruteForceSolver().solve(graph, timeout_seconds=0)
        self.assertEqual(result.status, SolutionStatus.TIMEOUT)
        self.assertIsNotNone(result.assignment)
        self.assertIsNotNone(result.bandwidth)
        self.assertLess(result.lower_bound or 0, result.upper_bound or 0)
        report = validate_assignment(
            graph,
            result.assignment or {},
            claimed_bandwidth=result.bandwidth,
        )
        self.assertTrue(report.valid, report.errors)


if __name__ == "__main__":
    unittest.main()
