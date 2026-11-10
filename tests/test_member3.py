"""Member 3 unit and small-instance integration tests."""

import importlib.util
import os
from shutil import which
import unittest
from itertools import product
from pathlib import Path

from bmp.core.generators import (
    complete_graph,
    cycle_graph,
    edgeless_graph,
    erdos_renyi_graph,
    path_graph,
    star_graph,
)
from bmp.core.graph import Graph
from bmp.core.solution import SolutionStatus
from bmp.core.validation import validate_assignment
from bmp.encodings.cardinality.ladder import encode_ladder_amo
from bmp.encodings.cardinality.product import encode_product_amo
from bmp.heuristics.rcm import RCMSolver
from bmp.heuristics.sa import SimulatedAnnealingSolver
from bmp.io.readers import read_edge_list
from bmp.solvers.brute_force import BruteForceSolver
from bmp.solvers.exact.cp_optimizer import CPOptimizerSolver, _build_model
from bmp.solvers.exact.cpsat import CPSATSolver
from bmp.solvers.sat.backends.minisat import MiniSat22Backend


class CardinalityTests(unittest.TestCase):
    def test_truth_tables(self):
        for encode in (encode_product_amo, encode_ladder_amo):
            for n in (0, 1, 2, 4, 6):
                with self.subTest(encoder=encode.__name__, n=n):
                    variables = list(range(2, 2 * n + 1, 2))
                    clauses, top = encode(variables, 30)
                    auxiliary = {
                        abs(lit) for clause in clauses for lit in clause
                    } - set(variables)
                    self.assertEqual(auxiliary, set(range(31, top + 1)))
                    for bits in product((False, True), repeat=n):
                        values = dict(zip(variables, bits))
                        feasible = False
                        for extra in product((False, True), repeat=len(auxiliary)):
                            values.update(zip(sorted(auxiliary), extra))
                            if all(
                                any(values[abs(lit)] == (lit > 0) for lit in c)
                                for c in clauses
                            ):
                                feasible = True
                                break
                        self.assertEqual(feasible, sum(bits) <= 1)

    def test_top_id_and_validation(self):
        for encode in (encode_product_amo, encode_ladder_amo):
            self.assertEqual(encode([]), ([], 0))
            self.assertEqual(encode([9]), ([], 9))
            _, first_top = encode([2, 5])
            second, _ = encode([2, 5], first_top)
            self.assertTrue(
                all(
                    abs(lit) > first_top or abs(lit) in (2, 5)
                    for c in second
                    for lit in c
                )
            )
            for args in (([1, 1],), ([0],), ([True],), ([9], 8), ([], -1)):
                with self.assertRaises(ValueError):
                    encode(*args)


class MiniSatTests(unittest.TestCase):
    def test_assumptions_model_incremental_and_close(self):
        try:
            backend = MiniSat22Backend([[2, 5]])
        except ImportError as exc:
            self.skipTest(str(exc))
        with backend:
            self.assertFalse(backend.solve([-2, -5]))
            self.assertIsNone(backend.get_model())
            self.assertTrue(backend.solve([-2]))
            self.assertIn(5, backend.get_model())
            backend.add_clause([-5])
            self.assertTrue(backend.solve())
            self.assertIn(2, backend.get_model())
            backend.add_clause([-2])
            self.assertFalse(backend.solve())
        backend.close()
        with self.assertRaises(RuntimeError):
            backend.solve()
        with MiniSat22Backend([[2]]) as fresh:
            self.assertTrue(fresh.solve())


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except ModuleNotFoundError:
        return False


def _has_ortools() -> bool:
    return _has_module("ortools.sat.python.cp_model")


def _has_docplex() -> bool:
    return _has_module("docplex.cp.model")


def _has_cpo_runtime() -> bool:
    exe = os.environ.get("BMP_CPO_EXECUTABLE", "cpoptimizer")
    return _has_docplex() and which(exe) is not None


class SolverTests(unittest.TestCase):
    cases = [
        (path_graph(5), 1),
        (cycle_graph(4), 2),
        (star_graph(4), 2),
        (complete_graph(5), 4),
        (edgeless_graph(0), 0),
        (Graph.from_edges([-4, 8, 2, 9], [(-4, 8), (2, 9)]), 1),
    ]

    def check_certificate(self, graph, result):
        self.assertIsNotNone(result.assignment)
        report = validate_assignment(
            graph, result.assignment, claimed_bandwidth=result.bandwidth
        )
        self.assertTrue(report.valid, report.errors)

    def check_exact(self, solver):
        for graph, expected in self.cases:
            with self.subTest(graph=graph):
                result = solver.solve(graph, timeout_seconds=10)
                if result.status is SolutionStatus.UNAVAILABLE:
                    self.skipTest(str(result.metadata))
                self.assertEqual(
                    result.status, SolutionStatus.OPTIMAL, result.to_dict()
                )
                self.assertEqual(result.bandwidth, expected)
                self.assertEqual(
                    result.bandwidth, BruteForceSolver().solve(graph).bandwidth
                )
                self.check_certificate(graph, result)

    @unittest.skipUnless(_has_ortools(), "ortools is not installed in the current environment")
    def test_cp_sat(self):
        self.check_exact(CPSATSolver())

    @unittest.skipUnless(_has_ortools(), "ortools is not installed in the current environment")
    def test_cp_sat_zero_budget(self):
        result = CPSATSolver().solve(cycle_graph(4), timeout_seconds=0)
        self.assertEqual(result.status, SolutionStatus.TIMEOUT)
        self.assertIsNone(result.assignment)

    @unittest.skipUnless(_has_cpo_runtime(), "docplex or cpoptimizer runtime is unavailable")
    def test_cp_optimizer(self):
        self.check_exact(
            CPOptimizerSolver(os.environ.get("BMP_CPO_EXECUTABLE", "cpoptimizer"))
        )

    @unittest.skipUnless(_has_docplex(), "docplex is not installed in the current environment")
    def test_cp_optimizer_model_and_missing_runtime(self):
        model, positions = _build_model(path_graph(3))
        self.assertEqual(set(positions), {1, 2, 3})
        source = model.get_cpo_string()
        for expression in ("alldiff(", "abs(", "minimize("):
            self.assertIn(expression, source)
        result = CPOptimizerSolver("missing-bmp-cpoptimizer.exe").solve(path_graph(3))
        self.assertEqual(result.status, SolutionStatus.UNAVAILABLE)
        self.assertIsNone(result.assignment)

    def test_rcm_and_seeded_sa(self):
        for graph, optimum in self.cases + [(erdos_renyi_graph(7, 0.4, seed=17), None)]:
            with self.subTest(graph=graph):
                rcm = RCMSolver().solve(graph)
                sa = SimulatedAnnealingSolver(iterations=100, seed=17)
                first = sa.solve(graph)
                second = sa.solve(graph)
                for result in (rcm, first, second):
                    self.assertEqual(result.status, SolutionStatus.FEASIBLE)
                    self.check_certificate(graph, result)
                self.assertEqual(first.assignment, second.assignment)
                self.assertLessEqual(first.bandwidth, rcm.bandwidth)
                if optimum is not None:
                    self.assertGreaterEqual(first.bandwidth, optimum)
        self.assertEqual(RCMSolver().solve(path_graph(5)).bandwidth, 1)


class DatasetTests(unittest.TestCase):
    def test_samples_match_generators(self):
        samples = Path(__file__).resolve().parents[1] / "data" / "samples"
        for expected in (
            path_graph(5),
            cycle_graph(4),
            star_graph(4),
            complete_graph(5),
            edgeless_graph(5),
        ):
            graph = read_edge_list(samples / f"{expected.name}.edgelist")
            self.assertEqual(graph.name, expected.name)
            self.assertEqual(graph.vertices, expected.vertices)
            self.assertEqual(graph.edges, expected.edges)
            self.assertEqual(graph.metadata["source"], f"{expected.name}.edgelist")


class Member3HandoffTests(unittest.TestCase):
    def test_amo_counts_and_exactly_one(self):
        from math import comb, isqrt

        for n in range(2, 10):
            rows = isqrt(n - 1) + 1
            columns = (n + rows - 1) // rows
            for encode, aux_count, clause_count in (
                (
                    encode_product_amo,
                    rows + columns,
                    2 * n + comb(rows, 2) + comb(columns, 2),
                ),
                (encode_ladder_amo, n - 1, 3 * n - 4),
            ):
                variables = list(range(1, n + 1))
                clauses, top = encode(variables)
                self.assertEqual(top, n + aux_count)
                self.assertEqual(len(clauses), clause_count)
                try:
                    backend = MiniSat22Backend([*clauses, variables])
                except ImportError as exc:
                    self.skipTest(str(exc))
                with backend:
                    for bits in product((False, True), repeat=n):
                        assumptions = [
                            v if bit else -v for v, bit in zip(variables, bits)
                        ]
                        self.assertEqual(backend.solve(assumptions), sum(bits) == 1)

    def test_heuristic_stopping_and_deterministic_rcm(self):
        graph = Graph.from_edges([9, 2, -1, 4, 11], [(2, 9), (-1, 4)])
        reordered = Graph.from_edges(reversed(graph.vertices), graph.edges)
        rcm = RCMSolver().solve(graph)
        self.assertEqual(rcm.assignment, RCMSolver().solve(reordered).assignment)
        annealer = SimulatedAnnealingSolver(
            iterations=20, initial_temperature=1, cooling=0.5, minimum_temperature=0.5
        )
        result = annealer.solve(graph)
        self.assertEqual(result.metadata["iterations_completed"], 2)
        self.assertLessEqual(result.bandwidth, rcm.bandwidth)
        self.assertEqual(
            SimulatedAnnealingSolver(iterations=0).solve(graph).assignment,
            rcm.assignment,
        )

    def test_real_harwell_boeing_catalog(self):
        from bmp.data.harwell_boeing import HarwellBoeingDataset

        root = Path(__file__).resolve().parents[1] / "data" / "harwell_boeing"
        dataset = HarwellBoeingDataset(root)
        self.assertEqual([len(dataset.instances(t)) for t in (6, 7)], [31, 41])
        with self.assertRaises(ValueError):
            dataset.instances(8)
        for entry in dataset.instances():
            self.assertLessEqual(entry.paper_lb, entry.paper_best)
            self.assertTrue(dataset.available(entry.instance))
            graph = dataset.load(entry.instance)
            self.assertEqual(graph.order, entry.n)
            self.assertEqual(graph.metadata["sha256"], entry.sha256)
            self.assertTrue(all(u < v for u, v in graph.edges))

    def test_dataset_rejects_missing_corrupt_and_wrong_order(self):
        import csv
        import gzip
        from hashlib import sha256
        from tempfile import TemporaryDirectory

        from bmp.data.harwell_boeing import HarwellBoeingDataset

        payload = gzip.compress(
            b"%%MatrixMarket matrix coordinate pattern symmetric\n2 2 1\n1 2\n"
        )
        row = {
            "instance": "fixture",
            "table_number": 6,
            "n": 3,
            "paper_lb": 1,
            "paper_best": 1,
            "status": "AVAILABLE",
            "source_url": "",
            "format": "",
            "sha256": sha256(payload).hexdigest(),
            "path": "fixture.mtx.gz",
            "matrix_order": "2x2",
            "reason": "",
        }
        with TemporaryDirectory() as folder:
            directory = Path(folder)
            with (directory / "metadata.csv").open(
                "w", newline="", encoding="utf-8"
            ) as stream:
                writer = csv.DictWriter(stream, fieldnames=row)
                writer.writeheader()
                writer.writerow(row)
            dataset = HarwellBoeingDataset(directory)
            self.assertFalse(dataset.available("fixture"))
            with self.assertRaises(FileNotFoundError):
                dataset.load("fixture")
            matrix = directory / row["path"]
            matrix.write_bytes(b"bad")
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                dataset.load("fixture")
            matrix.write_bytes(payload)
            with self.assertRaisesRegex(ValueError, "differs from paper"):
                dataset.load("fixture")
