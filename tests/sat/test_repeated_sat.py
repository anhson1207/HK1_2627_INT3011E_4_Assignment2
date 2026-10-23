from __future__ import annotations

import unittest

from bmp.core.generators import (
    complete_graph,
    cycle_graph,
    edgeless_graph,
    erdos_renyi_graph,
    path_graph,
    star_graph,
)
from bmp.core.graph import GraphInstance
from bmp.core.solution import SolutionStatus
from bmp.core.validation import validate_solution
from bmp.encodings.pairwise import PairwiseEncoding
from bmp.solvers.brute_force import BruteForceSolver
from bmp.solvers.sat.repeated import RepeatedSATSolver


class RepeatedSATTests(unittest.TestCase):
    def test_canonical_graphs_pairwise_repeated(self) -> None:
        graphs = [
            (path_graph(5), 1),
            (complete_graph(5), 4),
            (star_graph(4), 2),
            (cycle_graph(4), 2),
            (edgeless_graph(5), 0),
        ]
        # Test both pairwise AMO and sequential counter AMO
        for amo in ("pairwise", "sequential"):
            encoder = PairwiseEncoding(amo=amo)
            solver = RepeatedSATSolver(encoder=encoder, backend_name="cadical")
            for graph, expected_opt in graphs:
                with self.subTest(graph=graph.name, amo=amo):
                    result = solver.solve(graph, timeout_seconds=10)
                    self.assertEqual(result.status, SolutionStatus.OPTIMAL)
                    self.assertEqual(result.bandwidth, expected_opt)
                    self.assertEqual(result.lower_bound, expected_opt)
                    self.assertEqual(result.upper_bound, expected_opt)
                    self.assertIsNotNone(result.permutation)

                    report = validate_solution(graph, result)
                    self.assertTrue(report.valid, f"Validation errors: {report.errors}")
                    self.assertEqual(report.actual_bandwidth, expected_opt)

    def test_disconnected_graph(self) -> None:
        # Two disconnected components: triangle (0, 1, 2) and edge (3, 4)
        # Vertices 0..4, edges: (0,1), (1,2), (0,2), (3,4)
        g = GraphInstance.create(name="disconnected_5", n=5, edges=[(0, 1), (1, 2), (0, 2), (3, 4)])
        bf_oracle = BruteForceSolver().solve(g)

        for amo in ("pairwise", "sequential"):
            solver = RepeatedSATSolver(encoder=PairwiseEncoding(amo=amo), backend_name="cadical")
            res = solver.solve(g)
            self.assertEqual(res.status, SolutionStatus.OPTIMAL)
            self.assertEqual(res.bandwidth, bf_oracle.bandwidth)
            report = validate_solution(g, res)
            self.assertTrue(report.valid)

    def test_cross_check_with_brute_force_on_random_graphs(self) -> None:
        bf = BruteForceSolver(max_vertices=8)
        for seed in (42, 100, 2026):
            g = erdos_renyi_graph(order=6, probability=0.4, seed=seed)
            expected = bf.solve(g)

            solver = RepeatedSATSolver(encoder=PairwiseEncoding(amo="pairwise"))
            sat_res = solver.solve(g)
            self.assertEqual(sat_res.status, SolutionStatus.OPTIMAL)
            self.assertEqual(sat_res.bandwidth, expected.bandwidth)

            report = validate_solution(g, sat_res)
            self.assertTrue(report.valid)

    def test_binary_search_repeated(self) -> None:
        g = cycle_graph(5)
        solver = RepeatedSATSolver(
            encoder=PairwiseEncoding(amo="pairwise"),
            search_mode="binary",
        )
        res = solver.solve(g)
        self.assertEqual(res.status, SolutionStatus.OPTIMAL)
        self.assertEqual(res.bandwidth, 2)
        report = validate_solution(g, res)
        self.assertTrue(report.valid)


if __name__ == "__main__":
    unittest.main()
