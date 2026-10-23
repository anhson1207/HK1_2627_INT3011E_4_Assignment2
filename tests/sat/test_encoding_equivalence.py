from __future__ import annotations

import unittest
from pysat.solvers import Solver

from bmp.core.generators import (
    complete_graph,
    cycle_graph,
    edgeless_graph,
    erdos_renyi_graph,
    path_graph,
    star_graph,
)
from bmp.core.graph import GraphInstance
from bmp.core.validation import calculate_bandwidth
from bmp.encodings.order import OrderEncoding
from bmp.encodings.pairwise import PairwiseEncoding
from bmp.solvers.brute_force import BruteForceSolver


class EncodingEquivalenceTests(unittest.TestCase):
    """Test decision-level SAT/UNSAT equivalence between Pairwise and Order encodings."""

    def test_decision_equivalence_across_thresholds(self) -> None:
        graphs = [
            path_graph(5),
            cycle_graph(4),
            star_graph(4),
            erdos_renyi_graph(5, 0.4, seed=42),
        ]
        pairwise_enc = PairwiseEncoding(amo="pairwise")
        order_enc = OrderEncoding(amo="pairwise")

        for graph in graphs:
            n = graph.order
            bf_oracle = BruteForceSolver().solve(graph)
            opt_bw = bf_oracle.bandwidth
            assert opt_bw is not None

            for k in range(0, n):
                with self.subTest(graph=graph.name, k=k):
                    # 1. Pairwise check
                    pw_formula = pairwise_enc.encode(graph, k)
                    pw_solver = Solver(name="cadical195", bootstrap_with=pw_formula.clauses)
                    pw_sat = pw_solver.solve()
                    pw_model = pw_solver.get_model() if pw_sat else None
                    pw_solver.delete()

                    # 2. Order check
                    ord_formula = order_enc.encode(graph, k)
                    ord_solver = Solver(name="cadical195", bootstrap_with=ord_formula.clauses)
                    ord_sat = ord_solver.solve()
                    ord_model = ord_solver.get_model() if ord_sat else None
                    ord_solver.delete()

                    # 3. Equivalence with ground truth (k >= opt_bw <==> SAT)
                    expected_sat = (k >= opt_bw)
                    self.assertEqual(pw_sat, expected_sat, f"Pairwise failed at graph={graph.name}, k={k}")
                    self.assertEqual(ord_sat, expected_sat, f"Order failed at graph={graph.name}, k={k}")
                    self.assertEqual(pw_sat, ord_sat, f"Pairwise and Order disagree at graph={graph.name}, k={k}")

                    # 4. If SAT, verify decoded permutation has bandwidth <= k
                    if pw_sat:
                        assert pw_model is not None
                        pw_perm = pairwise_enc.decode(graph, pw_model, k)
                        pw_bw = calculate_bandwidth(graph, pw_perm)
                        self.assertLessEqual(pw_bw, k)

                    if ord_sat:
                        assert ord_model is not None
                        ord_perm = order_enc.decode(graph, ord_model, k)
                        ord_bw = calculate_bandwidth(graph, ord_perm)
                        self.assertLessEqual(ord_bw, k)


if __name__ == "__main__":
    unittest.main()

