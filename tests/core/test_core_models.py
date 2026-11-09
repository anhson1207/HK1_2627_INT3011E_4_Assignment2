from __future__ import annotations

import unittest

from bmp.core.graph import Graph, GraphInstance
from bmp.core.solution import BMPSolution, SolutionStatus, SolverResult
from bmp.core.validation import calculate_bandwidth, validate_solution


class CoreModelsTests(unittest.TestCase):
    def test_graph_instance_creation(self) -> None:
        g = GraphInstance.create(name="test_g", n=4, edges=[(0, 1), (1, 2), (2, 3)])
        self.assertEqual(g.n, 4)
        self.assertEqual(g.order, 4)
        self.assertEqual(g.size, 3)
        self.assertEqual(g.name, "test_g")

    def test_graph_instance_empty_and_edgeless(self) -> None:
        g0 = GraphInstance.create(name="empty", n=0, edges=[])
        self.assertEqual(g0.order, 0)
        self.assertEqual(g0.size, 0)
        self.assertEqual(calculate_bandwidth(g0, {}), 0)

        g5 = GraphInstance.create(name="edgeless5", n=5, edges=[])
        self.assertEqual(g5.order, 5)
        self.assertEqual(g5.size, 0)
        self.assertEqual(calculate_bandwidth(g5, {0: 1, 1: 2, 2: 3, 3: 4, 4: 5}), 0)

    def test_solver_result_fields(self) -> None:
        res = SolverResult(
            instance="star4",
            method="SAT",
            solver="cadical",
            encoding="pairwise",
            strategy="repeated",
            status=SolutionStatus.OPTIMAL,
            bandwidth=2,
            permutation={0: 1, 1: 2, 2: 3, 3: 4},
            runtime_s=0.15,
            encoding_time_s=0.05,
            solving_time_s=0.10,
            num_variables=16,
            num_clauses=30,
            sat_calls=3,
            lower_bound=2,
            upper_bound=2,
        )
        self.assertTrue(res.proved_optimal)
        self.assertEqual(res.status, SolutionStatus.OPTIMAL)
        self.assertEqual(res.assignment, {0: 1, 1: 2, 2: 3, 3: 4})
        self.assertEqual(res.runtime_seconds, 0.15)
        d = res.to_dict()
        self.assertEqual(d["instance"], "star4")
        self.assertEqual(d["num_variables"], 16)
        self.assertEqual(d["sat_calls"], 3)

    def test_validate_solution_with_solver_result(self) -> None:
        g = GraphInstance.create(name="path3", n=3, edges=[(0, 1), (1, 2)])
        res = SolverResult(
            instance="path3",
            status=SolutionStatus.OPTIMAL,
            bandwidth=1,
            permutation={0: 1, 1: 2, 2: 3},
        )
        report = validate_solution(g, res)
        self.assertTrue(report.valid)
        self.assertEqual(report.actual_bandwidth, 1)

    def test_validate_solution_detects_wrong_claim(self) -> None:
        g = GraphInstance.create(name="path3", n=3, edges=[(0, 1), (1, 2)])
        res = SolverResult(
            instance="path3",
            status=SolutionStatus.FEASIBLE,
            bandwidth=2,  # Actual is 1
            permutation={0: 1, 1: 2, 2: 3},
        )
        report = validate_solution(g, res)
        self.assertFalse(report.valid)
        self.assertEqual(report.actual_bandwidth, 1)


if __name__ == "__main__":
    unittest.main()

