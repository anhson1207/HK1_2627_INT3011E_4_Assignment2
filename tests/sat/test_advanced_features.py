from __future__ import annotations

import unittest

from bmp.core.generators import (
    complete_graph,
    cycle_graph,
    path_graph,
    star_graph,
)
from bmp.core.solution import SolutionStatus
from bmp.core.validation import validate_solution
from bmp.encodings.order import OrderEncoding
from bmp.encodings.pairwise import PairwiseEncoding
from bmp.solvers.sat.incremental import IncrementalSATSolver
from bmp.solvers.sat.repeated import RepeatedSATSolver
from bmp.solvers.sat.search import select_anchor_vertex


class AdvancedFeaturesTests(unittest.TestCase):
    def test_symmetry_breaking_preserves_optima(self) -> None:
        graphs = [
            (path_graph(5), 1),
            (cycle_graph(5), 2),
            (star_graph(5), 3),
            (complete_graph(4), 3),
        ]
        for graph, expected_opt in graphs:
            anchor = select_anchor_vertex(graph)
            cutoff = (graph.order + 1) // 2

            for enc_cls in (PairwiseEncoding, OrderEncoding):
                for strat_cls in (RepeatedSATSolver, IncrementalSATSolver):
                    solver = strat_cls(encoder=enc_cls())
                    res = solver.solve(graph, symmetry_breaking=True)

                    self.assertEqual(res.status, SolutionStatus.OPTIMAL)
                    self.assertEqual(res.bandwidth, expected_opt)
                    self.assertIsNotNone(res.permutation)
                    assert res.permutation is not None

                    # Verify that anchor satisfies the symmetry constraint: p(anchor) <= ceil(n / 2)
                    self.assertLessEqual(
                        res.permutation[anchor],
                        cutoff,
                        f"Anchor {anchor} has label {res.permutation[anchor]} > {cutoff}",
                    )

                    report = validate_solution(graph, res)
                    self.assertTrue(report.valid)

    def test_hybrid_heuristic_upper_bound(self) -> None:
        g = path_graph(6)
        # Supply a good heuristic assignment with bandwidth 1: {1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6}
        heuristic_perm = {i: i for i in range(1, 7)}

        solver = RepeatedSATSolver(encoder=PairwiseEncoding())
        res = solver.solve(g, heuristic_permutation=heuristic_perm)

        self.assertEqual(res.status, SolutionStatus.OPTIMAL)
        self.assertEqual(res.bandwidth, 1)
        # Because heuristic was already at lower bound, it stopped with 0 SAT calls!
        self.assertEqual(res.sat_calls, 0)


if __name__ == "__main__":
    unittest.main()

