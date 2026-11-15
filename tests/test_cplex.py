from __future__ import annotations

import json
import sys
import unittest
from unittest.mock import patch

from bmp.core.generators import (
    complete_graph,
    cycle_graph,
    edgeless_graph,
    path_graph,
    star_graph,
)
from bmp.core.graph import Graph
from bmp.core.solution import SolutionStatus
from bmp.core.validation import validate_assignment
from bmp.solvers.brute_force import BruteForceSolver
from bmp.solvers.exact.cplex import CPLEXMIPSolver


class CPLEXTests(unittest.TestCase):
    def test_known_optima(self) -> None:
        cases = [
            (path_graph(5), 1),
            (complete_graph(5), 4),
            (star_graph(4), 2),
            (cycle_graph(4), 2),
            (edgeless_graph(5), 0),
        ]
        for graph, expected in cases:
            with self.subTest(graph=graph.name):
                result = CPLEXMIPSolver().solve(graph, timeout_seconds=10)
                if result.status is SolutionStatus.UNAVAILABLE:
                    self.skipTest(result.metadata["reason"])
                oracle = BruteForceSolver().solve(graph)
                self.assertEqual(result.status, SolutionStatus.OPTIMAL)
                self.assertEqual(result.bandwidth, expected)
                self.assertEqual(result.bandwidth, oracle.bandwidth)
                self.assertEqual(result.lower_bound, expected)
                self.assertEqual(result.upper_bound, expected)
                self.assertTrue(validate_assignment(graph, result.assignment or {}).valid)
                json.dumps(result.to_dict(), allow_nan=False)

    def test_zero_timeout_keeps_identity(self) -> None:
        graph = cycle_graph(4)
        result = CPLEXMIPSolver().solve(graph, timeout_seconds=0)
        if result.status is SolutionStatus.UNAVAILABLE:
            self.skipTest(result.metadata["reason"])
        self.assertEqual(result.status, SolutionStatus.TIMEOUT)
        self.assertEqual(result.bandwidth, 3)
        self.assertTrue(validate_assignment(graph, result.assignment or {}).valid)

    def test_noncontiguous_vertex_ids(self) -> None:
        graph = Graph.from_edges((20, -3, 8), ((20, -3), (-3, 8)))
        result = CPLEXMIPSolver().solve(graph, timeout_seconds=10)
        if result.status is SolutionStatus.UNAVAILABLE:
            self.skipTest(result.metadata["reason"])
        self.assertEqual(result.status, SolutionStatus.OPTIMAL)
        self.assertEqual(result.bandwidth, 1)
        self.assertEqual(set(result.assignment or {}), set(graph.vertices))
        self.assertTrue(validate_assignment(graph, result.assignment or {}).valid)

    def test_negative_timeout_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CPLEXMIPSolver().solve(path_graph(3), timeout_seconds=-1)

    def test_missing_backend_returns_unavailable(self) -> None:
        with patch.dict(sys.modules, {"cplex": None}):
            result = CPLEXMIPSolver().solve(path_graph(3))
        self.assertEqual(result.status, SolutionStatus.UNAVAILABLE)
        self.assertIn("cplex", result.metadata["reason"])
        self.assertTrue(validate_assignment(path_graph(3), result.assignment or {}).valid)


if __name__ == "__main__":
    unittest.main()
