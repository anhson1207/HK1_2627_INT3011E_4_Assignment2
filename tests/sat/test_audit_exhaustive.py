from __future__ import annotations

import itertools
import unittest

from bmp.core.graph import GraphInstance
from bmp.core.solution import SolutionStatus
from bmp.core.validation import validate_solution
from bmp.encodings.order import OrderEncoding
from bmp.encodings.pairwise import PairwiseEncoding
from bmp.solvers.brute_force import BruteForceSolver
from bmp.solvers.sat.incremental import IncrementalSATSolver
from bmp.solvers.sat.repeated import RepeatedSATSolver


class Exhaustive4VerticesTests(unittest.TestCase):
    """Exhaustively verify all 2^(4 choose 2) = 64 simple undirected graphs on 4 vertices."""

    def test_all_64_graphs_on_4_vertices(self) -> None:
        vertices = (0, 1, 2, 3)
        all_possible_edges = list(itertools.combinations(vertices, 2))
        self.assertEqual(len(all_possible_edges), 6)

        bf = BruteForceSolver(max_vertices=4)
        pw_rep = RepeatedSATSolver(encoder=PairwiseEncoding(amo="pairwise"), backend_name="cadical")
        pw_inc = IncrementalSATSolver(encoder=PairwiseEncoding(amo="sequential"), backend_name="cadical")
        ord_rep = RepeatedSATSolver(encoder=OrderEncoding(amo="pairwise"), backend_name="cadical")
        ord_inc = IncrementalSATSolver(encoder=OrderEncoding(amo="sequential"), backend_name="cadical")

        # Iterate over all 2^6 = 64 subsets of edges
        tested_count = 0
        for edge_mask in range(1 << 6):
            edges = [
                all_possible_edges[i]
                for i in range(6)
                if (edge_mask & (1 << i)) != 0
            ]
            g = GraphInstance.create(
                name=f"g4_mask_{edge_mask}",
                vertices=vertices,
                edges=edges,
            )

            # Ground truth from brute force
            oracle_res = bf.solve(g)
            opt_bw = oracle_res.bandwidth
            self.assertIsNotNone(opt_bw)

            # Test all 4 configurations
            for solver, name in [
                (pw_rep, "PairwiseRepeated"),
                (pw_inc, "PairwiseIncremental"),
                (ord_rep, "OrderRepeated"),
                (ord_inc, "OrderIncremental"),
            ]:
                res = solver.solve(g)
                self.assertEqual(
                    res.status,
                    SolutionStatus.OPTIMAL,
                    f"Solver {name} failed on graph mask {edge_mask}",
                )
                self.assertEqual(
                    res.bandwidth,
                    opt_bw,
                    f"Solver {name} got {res.bandwidth} != oracle {opt_bw} on mask {edge_mask}",
                )
                report = validate_solution(g, res)
                self.assertTrue(report.valid, f"Validation failed for {name} on mask {edge_mask}: {report.errors}")

            # Also test symmetry breaking on this graph
            sym_res = ord_inc.solve(g, symmetry_breaking=True)
            self.assertEqual(sym_res.status, SolutionStatus.OPTIMAL)
            self.assertEqual(sym_res.bandwidth, opt_bw)
            self.assertTrue(validate_solution(g, sym_res).valid)

            tested_count += 1

        self.assertEqual(tested_count, 64)


if __name__ == "__main__":
    unittest.main()
