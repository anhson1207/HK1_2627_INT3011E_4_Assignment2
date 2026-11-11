from __future__ import annotations

import unittest
from pysat.solvers import Solver

from bmp.core.generators import erdos_renyi_graph
from bmp.core.graph import GraphInstance
from bmp.core.solution import SolutionStatus
from bmp.core.validation import calculate_bandwidth, validate_solution
from bmp.encodings.order import OrderEncoding
from bmp.encodings.pairwise import PairwiseEncoding
from bmp.solvers.brute_force import BruteForceSolver
from bmp.solvers.sat.incremental import IncrementalSATSolver
from bmp.solvers.sat.repeated import RepeatedSATSolver


class AuditRandom100Tests(unittest.TestCase):
    """Test 100 random graphs on 5-6 vertices against brute force and cross-check configurations."""

    def test_100_random_graphs_against_oracle(self) -> None:
        bf = BruteForceSolver(max_vertices=8)
        pw_solver = RepeatedSATSolver(encoder=PairwiseEncoding(amo="pairwise"))
        ord_solver = IncrementalSATSolver(encoder=OrderEncoding(amo="sequential"))

        tested = 0
        for seed in range(1, 101):
            # Alternating order 5 and 6, probabilities between 0.15 and 0.85
            order = 5 if seed % 2 == 1 else 6
            prob = 0.15 + (seed % 7) * 0.10
            g = erdos_renyi_graph(order=order, probability=prob, seed=seed)

            oracle_res = bf.solve(g)
            opt_oracle = oracle_res.bandwidth

            # 1. Pairwise Repeated
            pw_res = pw_solver.solve(g)
            self.assertEqual(pw_res.status, SolutionStatus.OPTIMAL)
            self.assertEqual(pw_res.bandwidth, opt_oracle)
            self.assertTrue(validate_solution(g, pw_res).valid)

            # 2. Order Incremental
            ord_res = ord_solver.solve(g)
            self.assertEqual(ord_res.status, SolutionStatus.OPTIMAL)
            self.assertEqual(ord_res.bandwidth, opt_oracle)
            self.assertTrue(validate_solution(g, ord_res).valid)

            tested += 1

        self.assertEqual(tested, 100)

    def test_threshold_equivalence_and_boundary_cases(self) -> None:
        """Verify SAT/UNSAT equivalence across all thresholds k in [0, n-1] for diverse topologies."""
        pw_enc = PairwiseEncoding(amo="pairwise")
        ord_enc = OrderEncoding(amo="pairwise")

        test_instances = [
            # Disconnected components: K3 and K3
            GraphInstance.create(
                name="disconn_2_triangles",
                n=6,
                edges=[(0, 1), (1, 2), (0, 2), (3, 4), (4, 5), (3, 5)],
            ),
            # Isolated vertices + path
            GraphInstance.create(
                name="isolated_plus_path",
                n=6,
                edges=[(0, 1), (1, 2)],  # vertices 3, 4, 5 isolated
            ),
            # Edgeless n=6
            GraphInstance.create(name="edgeless_6", n=6, edges=[]),
        ]

        for g in test_instances:
            bf_oracle = BruteForceSolver(max_vertices=8).solve(g)
            opt_bw = bf_oracle.bandwidth
            assert opt_bw is not None

            for k in range(0, g.order):
                with self.subTest(graph=g.name, k=k):
                    # Pairwise decision
                    pw_form = pw_enc.encode(g, k)
                    with Solver(name="cadical195", bootstrap_with=pw_form.clauses) as s_pw:
                        pw_sat = s_pw.solve()
                        pw_model = s_pw.get_model() if pw_sat else None

                    # Order decision
                    ord_form = ord_enc.encode(g, k)
                    with Solver(name="cadical195", bootstrap_with=ord_form.clauses) as s_ord:
                        ord_sat = s_ord.solve()
                        ord_model = s_ord.get_model() if ord_sat else None

                    expected_sat = (k >= opt_bw)
                    self.assertEqual(pw_sat, expected_sat, f"Pairwise failed at {g.name}, k={k}")
                    self.assertEqual(ord_sat, expected_sat, f"Order failed at {g.name}, k={k}")
                    self.assertEqual(pw_sat, ord_sat, f"Pairwise != Order at {g.name}, k={k}")

                    if pw_sat and pw_model:
                        perm_pw = pw_enc.decode(g, pw_model, k)
                        self.assertLessEqual(calculate_bandwidth(g, perm_pw), k)
                    if ord_sat and ord_model:
                        perm_ord = ord_enc.decode(g, ord_model, k)
                        self.assertLessEqual(calculate_bandwidth(g, perm_ord), k)


if __name__ == "__main__":
    unittest.main()
