"""Reversal symmetry constraints preserve the optimum on small graphs."""

from __future__ import annotations

import unittest
from pathlib import Path

from bmp.core.solution import SolutionStatus
from bmp.core.validation import validate_assignment
from bmp.io.readers import read_graph
from bmp.solvers.brute_force import BruteForceSolver
from bmp.solvers.exact.cplex import CPLEXMIPSolver
from bmp.solvers.exact.gurobi import GurobiMIPSolver


ROOT = Path(__file__).resolve().parents[1]
SAMPLES = sorted((ROOT / "data/samples").glob("*.edgelist"))


class MIPStrengtheningTests(unittest.TestCase):
    def test_reversal_symmetry_matches_oracle(self) -> None:
        for sample in SAMPLES:
            graph = read_graph(sample)
            oracle = BruteForceSolver().solve(graph)
            for solver_type in (GurobiMIPSolver, CPLEXMIPSolver):
                for symmetry_breaking in (False, True):
                    with self.subTest(
                        graph=graph.name, solver=solver_type.__name__,
                        symmetry_breaking=symmetry_breaking,
                    ):
                        result = solver_type().solve(
                            graph, timeout_seconds=5,
                            symmetry_breaking=symmetry_breaking,
                        )
                        if result.status is SolutionStatus.UNAVAILABLE:
                            self.skipTest(result.metadata["reason"])
                        self.assertEqual(result.status, SolutionStatus.OPTIMAL)
                        self.assertEqual(result.bandwidth, oracle.bandwidth)
                        self.assertTrue(validate_assignment(graph, result).valid)


if __name__ == "__main__":
    unittest.main()
