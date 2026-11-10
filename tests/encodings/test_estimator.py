from __future__ import annotations

import unittest

from bmp.core.generators import cycle_graph, erdos_renyi_graph, path_graph, star_graph
from bmp.core.solution import SolutionStatus
from bmp.encodings.estimator import ResourceLimits, estimate_cnf_size, estimate_incremental_cnf_size
from bmp.encodings.order import OrderEncoding
from bmp.encodings.pairwise import PairwiseEncoding
from bmp.solvers.sat.incremental import IncrementalSATSolver
from bmp.solvers.sat.repeated import RepeatedSATSolver


class EstimatorAndResourceGuardTests(unittest.TestCase):
    def test_paper_scale_bandwidth_formula_uses_edge_count(self) -> None:
        from bmp.core.graph import Graph
        for n, m, expected in ((500, 2500, 623_750_000), (1000, 5000, 4_995_000_000)):
            edges = ((u, (u + distance) % n) for u in range(n) for distance in range(1, 6))
            graph = Graph.create(n=n, edges=edges)
            self.assertEqual(graph.size, m)
            estimate = estimate_cnf_size(graph, encoding="pairwise", k=0)
            self.assertEqual(estimate.num_bandwidth_clauses, expected)
            self.assertEqual(estimate.num_clauses, estimate.num_fixed_clauses + expected)
            self.assertFalse(ResourceLimits().check(estimate)[0])

    def test_pairwise_single_vertex_and_incremental_cumulative(self) -> None:
        from bmp.core.graph import Graph
        single = Graph.create(n=1)
        formula = PairwiseEncoding().encode(single, 0)
        estimate = estimate_cnf_size(single, encoding="pairwise", k=0)
        self.assertEqual((estimate.num_variables, estimate.num_clauses),
                         (formula.num_variables, formula.num_clauses))

        graph = cycle_graph(5)
        for encoder, family in ((PairwiseEncoding(), "pairwise"), (OrderEncoding(), "order")):
            initial, target = 3, 1
            fixed = encoder.encode_fixed(graph)
            accumulated = fixed.num_clauses
            for k in range(initial, target - 1, -1):
                if family == "pairwise" and k < initial:
                    accumulated += len(encoder.encode_bandwidth_diff(graph, k, k + 1))
                else:
                    accumulated += len(encoder.encode_bandwidth_step(graph, k))
            estimate = estimate_incremental_cnf_size(
                graph, encoding=family, amo="pairwise",
                initial_k=initial, target_k=target,
            )
            self.assertEqual(estimate.num_clauses, accumulated)

    def test_worker_deadline_keeps_feasible_solution(self) -> None:
        from bmp.core.validation import validate_solution
        graph = cycle_graph(5)
        for solver in (RepeatedSATSolver(), IncrementalSATSolver()):
            result = solver.solve(graph, timeout_seconds=0)
            self.assertEqual(result.status, SolutionStatus.TIMEOUT)
            self.assertTrue(validate_solution(graph, result).valid)
            self.assertEqual(result.sat_calls, 0)

    def test_unit_threshold_policy_preserves_optimality(self) -> None:
        graph = erdos_renyi_graph(6, 0.4, seed=42)
        repeated = RepeatedSATSolver(OrderEncoding("sequential"), threshold_policy="unit").solve(graph)
        incremental = IncrementalSATSolver(OrderEncoding("sequential"), threshold_policy="unit").solve(graph)
        self.assertEqual(repeated.status, SolutionStatus.OPTIMAL)
        self.assertEqual(incremental.status, SolutionStatus.OPTIMAL)
        self.assertEqual(repeated.bandwidth, incremental.bandwidth)

    def test_later_threshold_resource_guard_retains_incumbent(self) -> None:
        from bmp.core.validation import validate_solution
        graph = erdos_renyi_graph(7, 0.4, seed=19)
        for family, encoder in (("pairwise", PairwiseEncoding()), ("order", OrderEncoding())):
            initial = estimate_cnf_size(graph, encoding=family, k=4)
            limits = ResourceLimits(max_clauses=initial.num_clauses, timeout_seconds=None)
            for solver in (RepeatedSATSolver(encoder), IncrementalSATSolver(encoder)):
                with self.subTest(family=family, strategy=type(solver).__name__):
                    result = solver.solve(graph, limits=limits)
                    self.assertEqual(result.status, SolutionStatus.SKIPPED)
                    self.assertEqual(result.bandwidth, 4)
                    self.assertGreaterEqual(result.sat_calls, 1)
                    self.assertTrue(validate_solution(graph, result).valid)

    def test_estimate_exactness_pairwise_and_order(self) -> None:
        """Verify that analytical estimation exactly matches actual CNF formula counts."""
        test_graphs = [
            path_graph(5),
            cycle_graph(4),
            star_graph(4),
            erdos_renyi_graph(6, 0.4, seed=42),
        ]

        configs = [
            (PairwiseEncoding, "pairwise", "pairwise"),
            (PairwiseEncoding, "pairwise", "sequential"),
            (OrderEncoding, "order", "pairwise"),
            (OrderEncoding, "order", "sequential"),
        ]

        for g in test_graphs:
            for enc_cls, enc_family, amo_type in configs:
                for sym in (False, True):
                    # Test for k=1 and k=2
                    for k in (1, 2):
                        with self.subTest(g=g.name, enc=enc_family, amo=amo_type, sym=sym, k=k):
                            est = estimate_cnf_size(
                                g,
                                encoding=enc_family,
                                amo=amo_type,
                                k=k,
                                symmetry_breaking=sym,
                            )
                            encoder = enc_cls(amo=amo_type)
                            formula = encoder.encode(g, k=k, symmetry_breaking=sym)

                            self.assertEqual(
                                est.num_variables,
                                formula.num_variables,
                                f"Variables mismatch for {g.name} {enc_family} {amo_type} k={k}",
                            )
                            self.assertEqual(
                                est.num_clauses,
                                formula.num_clauses,
                                f"Clauses mismatch for {g.name} {enc_family} {amo_type} k={k}",
                            )

    def test_resource_limits_rejection(self) -> None:
        g = path_graph(5)
        # Sizing: cycle/path 5 has ~100-200 clauses
        est = estimate_cnf_size(g, encoding="pairwise", amo="pairwise", k=1)
        self.assertGreater(est.num_clauses, 50)

        # Config limit below estimate
        limits = ResourceLimits(max_clauses=30)
        is_ok, reason = limits.check(est)
        self.assertFalse(is_ok)
        self.assertIsNotNone(reason)
        self.assertIn("exceeds safety limit", reason or "")

        # Config limit above estimate
        generous_limits = ResourceLimits(max_clauses=10_000, max_variables=10_000)
        is_ok2, reason2 = generous_limits.check(est)
        self.assertTrue(is_ok2)
        self.assertIsNone(reason2)

    def test_solvers_skip_when_limits_exceeded(self) -> None:
        g = star_graph(4)  # n=5
        # Set strict clause limit to 50 clauses
        limits = ResourceLimits(max_clauses=50)

        # 1. Repeated solver with limits
        rep_solver = RepeatedSATSolver(encoder=PairwiseEncoding(amo="pairwise"))
        rep_res = rep_solver.solve(g, limits=limits)
        self.assertEqual(rep_res.status, SolutionStatus.SKIPPED)
        self.assertEqual(rep_res.sat_calls, 0)
        self.assertIn("skipped_reason", rep_res.metadata)

        # 2. Incremental solver with limits
        inc_solver = IncrementalSATSolver(encoder=OrderEncoding(amo="pairwise"))
        inc_res = inc_solver.solve(g, limits=limits)
        self.assertEqual(inc_res.status, SolutionStatus.SKIPPED)
        self.assertEqual(inc_res.sat_calls, 0)
        self.assertIn("skipped_reason", inc_res.metadata)


if __name__ == "__main__":
    unittest.main()
