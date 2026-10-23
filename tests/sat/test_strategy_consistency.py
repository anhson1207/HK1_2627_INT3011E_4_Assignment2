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
from bmp.encodings.order import OrderEncoding
from bmp.encodings.pairwise import PairwiseEncoding
from bmp.solvers.sat.incremental import IncrementalSATSolver
from bmp.solvers.sat.repeated import RepeatedSATSolver


class StrategyConsistencyTests(unittest.TestCase):
    """Verify that all 4 SAT configurations yield identical optimal bandwidths."""

    def test_all_four_configurations_match(self) -> None:
        graphs = [
            (path_graph(5), 1),
            (complete_graph(5), 4),
            (star_graph(4), 2),
            (cycle_graph(4), 2),
            (edgeless_graph(5), 0),
            (erdos_renyi_graph(6, 0.4, seed=42), None),
            (GraphInstance.create(name="disconn", n=5, edges=[(0, 1), (1, 2), (3, 4)]), 1),
        ]

        encoders = [
            ("pw_pair", PairwiseEncoding(amo="pairwise")),
            ("pw_seq", PairwiseEncoding(amo="sequential")),
            ("ord_pair", OrderEncoding(amo="pairwise")),
            ("ord_seq", OrderEncoding(amo="sequential")),
        ]

        for graph, expected_opt in graphs:
            results: dict[str, int | None] = {}
            for enc_name, encoder in encoders:
                # 1. Repeated strategy
                rep_solver = RepeatedSATSolver(encoder=encoder, backend_name="cadical")
                rep_res = rep_solver.solve(graph)
                self.assertEqual(rep_res.status, SolutionStatus.OPTIMAL)
                rep_report = validate_solution(graph, rep_res)
                self.assertTrue(rep_report.valid, f"{enc_name} Repeated invalid: {rep_report.errors}")
                results[f"{enc_name}_repeated"] = rep_res.bandwidth

                # 2. Incremental strategy
                inc_solver = IncrementalSATSolver(encoder=encoder, backend_name="cadical")
                inc_res = inc_solver.solve(graph)
                self.assertEqual(inc_res.status, SolutionStatus.OPTIMAL)
                inc_report = validate_solution(graph, inc_res)
                self.assertTrue(inc_report.valid, f"{enc_name} Incremental invalid: {inc_report.errors}")
                results[f"{enc_name}_incremental"] = inc_res.bandwidth

            # Check that all configurations agree on the exact same bandwidth
            values = list(results.values())
            self.assertTrue(all(v == values[0] for v in values), f"Disagreement on {graph.name}: {results}")
            if expected_opt is not None:
                self.assertEqual(values[0], expected_opt, f"Expected {expected_opt} but got {values[0]} on {graph.name}")


if __name__ == "__main__":
    unittest.main()

