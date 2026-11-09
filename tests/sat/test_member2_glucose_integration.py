"""Check the leader's BMP encodings and strategies with Glucose 4."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from bmp.core.solution import SolutionStatus
from bmp.core.validation import validate_assignment
from bmp.encodings.order import OrderEncoding
from bmp.encodings.pairwise import PairwiseEncoding
from bmp.io.readers import read_graph
from bmp.solvers.sat.backends import get_sat_backend
from bmp.solvers.sat.incremental import IncrementalSATSolver
from bmp.solvers.sat.repeated import RepeatedSATSolver


ROOT = Path(__file__).resolve().parents[2]


class Member2GlucoseIntegrationTests(unittest.TestCase):
    def test_incremental_strategy_reuses_one_backend_across_two_thresholds(self) -> None:
        graph = read_graph(ROOT / "data/samples/cycle_c4.edgelist")
        real_factory = get_sat_backend
        for encoding_type in (PairwiseEncoding, OrderEncoding):
            with self.subTest(encoding=encoding_type.__name__):
                created = []

                def tracked_factory(name: str):
                    backend = real_factory(name)
                    created.append(backend)
                    return backend

                # A weaker valid lower bound forces the strategy to visit K=2,
                # then K=1; the actual graph and Glucose backend remain real.
                with patch("bmp.solvers.sat.incremental.compute_lower_bound", return_value=1), patch(
                    "bmp.solvers.sat.incremental.get_sat_backend", side_effect=tracked_factory
                ):
                    result = IncrementalSATSolver(
                        encoding_type(amo="pairwise"), backend_name="glucose"
                    ).solve(graph)
                self.assertEqual(result.sat_calls, 2)
                self.assertEqual(len(created), 1)
                self.assertEqual(result.status, SolutionStatus.OPTIMAL)
                self.assertEqual(result.bandwidth, 2)
                self.assertTrue(validate_assignment(graph, result).valid)

    def test_cycle_c4_all_four_configurations_and_thresholds(self) -> None:
        graph = read_graph(ROOT / "data/samples/cycle_c4.edgelist")
        for encoding_type in (PairwiseEncoding, OrderEncoding):
            for strategy in ("repeated", "incremental"):
                with self.subTest(encoding=encoding_type.__name__, strategy=strategy):
                    encoder = encoding_type(amo="pairwise")
                    if strategy == "repeated":
                        for k, expected_sat in ((1, False), (2, True)):
                            formula = encoder.encode(graph, k)
                            with get_sat_backend("glucose") as backend:
                                backend.append_formula(formula.clauses)
                                self.assertEqual(backend.solve(), expected_sat)
                                if expected_sat:
                                    assignment = encoder.decode(graph, backend.get_model() or [], k)
                                    report = validate_assignment(graph, assignment)
                                    self.assertTrue(report.valid, report.errors)
                                    self.assertEqual(report.actual_bandwidth, 2)
                    else:
                        # A single Glucose instance is strengthened from K=2 to K=1.
                        with get_sat_backend("glucose") as backend:
                            backend.append_formula(encoder.encode_fixed(graph).clauses)
                            backend.append_formula(encoder.encode_bandwidth_step(graph, 2))
                            self.assertTrue(backend.solve())
                            assignment = encoder.decode(graph, backend.get_model() or [], 2)
                            report = validate_assignment(graph, assignment)
                            self.assertTrue(report.valid, report.errors)
                            self.assertEqual(report.actual_bandwidth, 2)
                            if isinstance(encoder, PairwiseEncoding):
                                tightening = encoder.encode_bandwidth_diff(graph, 1, 2)
                            else:
                                tightening = encoder.encode_bandwidth_step(graph, 1)
                            backend.append_formula(tightening)
                            self.assertFalse(backend.solve())

                    solver = (
                        RepeatedSATSolver(encoder, backend_name="glucose")
                        if strategy == "repeated"
                        else IncrementalSATSolver(encoder, backend_name="glucose")
                    )
                    result = solver.solve(graph)
                    self.assertEqual(result.status, SolutionStatus.OPTIMAL)
                    self.assertEqual(result.bandwidth, 2)
                    self.assertTrue(validate_assignment(graph, result).valid)

    def test_binary_and_commander_in_pairwise_model(self) -> None:
        graph = read_graph(ROOT / "data/samples/cycle_c4.edgelist")
        for amo in ("binary", "commander"):
            with self.subTest(amo=amo):
                encoder = PairwiseEncoding(amo=amo)
                for k, expected_sat in ((1, False), (2, True)):
                    formula = encoder.encode(graph, k)
                    with get_sat_backend("glucose") as backend:
                        backend.append_formula(formula.clauses)
                        self.assertEqual(backend.solve(), expected_sat)
                        if expected_sat:
                            decoded = encoder.decode(graph, backend.get_model() or [], k)
                            self.assertEqual(validate_assignment(graph, decoded).actual_bandwidth, 2)


if __name__ == "__main__":
    unittest.main()
