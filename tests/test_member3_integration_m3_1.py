"""Integration and compatibility regression tests for Phase M3.1."""

from __future__ import annotations

import io
import json
import sys
import types
import unittest
from contextlib import redirect_stdout
from itertools import product
from pathlib import Path
from unittest.mock import patch

from bmp.cli import main as cli_main
from bmp.core.benchmark_catalog import ALL_INSTANCES
from bmp.core.bounds import cuthill_mckee_order
from bmp.core.generators import cycle_graph, erdos_renyi_graph, path_graph, star_graph
from bmp.core.graph import Graph, GraphInstance
from bmp.core.solution import BMPSolution, SolutionStatus, SolverResult
from bmp.core.validation import validate_solution
from bmp.data import (
    HarwellBoeingDataset,
    compare_matrix_market_conversions,
    load_provenance_index,
)
from bmp.encodings.cardinality import (
    LadderAMOEncoder,
    ProductAMOEncoder,
    SequentialCounterAMOEncoder,
    SimpleVarAllocator,
    get_amo_encoder,
)
from bmp.heuristics import RCMSolver, SimulatedAnnealingSolver
from bmp.solvers.exact import (
    CPLEXMIPSolver,
    CPOptimizerSolver,
    CPSATSolver,
    GurobiMIPSolver,
)
from bmp.solvers.sat.backends import MiniSat22Backend, MiniSatBackend, SATBackend, get_sat_backend

ROOT = Path(__file__).resolve().parents[1]


class Member3M31IntegrationTests(unittest.TestCase):
    def test_solver_result_and_graph_instance_contracts(self) -> None:
        self.assertIs(GraphInstance, Graph)
        self.assertIs(BMPSolution, SolverResult)
        graph = erdos_renyi_graph(7, 0.4, seed=17)

        for solver, solver_name in (
            (RCMSolver(), "rcm"),
            (SimulatedAnnealingSolver(iterations=50, seed=17), "sa"),
        ):
            result = solver.solve(graph)
            self.assertIsInstance(result, SolverResult)
            self.assertEqual(result.solver, solver_name)
            self.assertEqual(result.method, "HEURISTIC")
            self.assertEqual(result.status, SolutionStatus.FEASIBLE)
            self.assertFalse(result.proved_optimal)
            self.assertIsNotNone(result.permutation)
            self.assertEqual(result.assignment, result.permutation)
            self.assertGreaterEqual(result.upper_bound or 0, result.lower_bound or 0)
            self.assertTrue(validate_solution(graph, result).valid)
            json.dumps(result.to_dict(), allow_nan=False)

    def test_rcm_shares_deterministic_cuthill_mckee_order(self) -> None:
        graph = Graph.from_edges([10, -2, 5, 3, 7], [(10, -2), (-2, 5), (3, 7)])
        order = cuthill_mckee_order(graph)
        expected = {v: pos for pos, v in enumerate(reversed(order), start=1)}
        res = RCMSolver().solve(graph)
        self.assertEqual(dict(res.permutation or {}), expected)

    def test_product_and_ladder_amo_adapters_and_negative_literals(self) -> None:
        literals = [-1, 2, -3, 4, 5, -6]
        var_ids = sorted(abs(lit) for lit in literals)
        for amo_name, cls in (("product", ProductAMOEncoder), ("ladder", LadderAMOEncoder)):
            encoder = get_amo_encoder(amo_name)
            self.assertIsInstance(encoder, cls)
            alloc = SimpleVarAllocator(10)
            clauses, aux = encoder.encode(literals, alloc)
            self.assertTrue(aux)
            self.assertEqual(set(aux), set(range(10, alloc.next_id)))

            with MiniSatBackend(clauses) as backend:
                for bits in product((False, True), repeat=len(var_ids)):
                    env = dict(zip(var_ids, bits))
                    assumptions = [v if env[v] else -v for v in var_ids]
                    true_count = sum(
                        env[abs(lit)] == (lit > 0) for lit in literals
                    )
                    self.assertEqual(backend.solve(assumptions), true_count <= 1)

        # Ladder aligns algebraically with SequentialCounter for m >= 3, differs at m == 2.
        l3 = [1, 2, 3, 4]
        seq_clauses, seq_aux = SequentialCounterAMOEncoder().encode(l3, SimpleVarAllocator(10))
        lad_clauses, lad_aux = LadderAMOEncoder().encode(l3, SimpleVarAllocator(10))
        self.assertEqual((lad_aux, lad_clauses), (seq_aux, seq_clauses))
        _, seq_aux_2 = SequentialCounterAMOEncoder().encode([1, 2], SimpleVarAllocator(10))
        _, lad_aux_2 = LadderAMOEncoder().encode([1, 2], SimpleVarAllocator(10))
        self.assertEqual(len(seq_aux_2), 0)
        self.assertEqual(len(lad_aux_2), 1)

    def test_minisat_implements_l8_satbackend_contract(self) -> None:
        self.assertTrue(issubclass(MiniSatBackend, SATBackend))
        self.assertIs(MiniSat22Backend, MiniSatBackend)
        self.assertTrue(MiniSatBackend.is_available())
        for name in ("minisat", "minisat22"):
            with get_sat_backend(name) as backend:
                self.assertIsInstance(backend, MiniSatBackend)
                self.assertEqual(backend.name, "minisat")
                self.assertEqual(backend.version, "minisat22")
                backend.append_formula([[1, 2], [-1]])
                self.assertTrue(backend.solve_with_timeout(None))
                self.assertIn(2, backend.get_model() or [])
                self.assertIsNone(backend.solve_with_timeout(0))
                self.assertIsNone(backend.get_model())
                self.assertTrue(backend.solve_with_timeout(1.0))
                backend.add_clause([-2])
                self.assertIsNone(backend.get_model())
                self.assertFalse(backend.solve_with_timeout(1.0))
                with self.assertRaises(ValueError):
                    backend.solve_with_timeout(-0.5)
            backend.delete()  # idempotent after context exit
            with self.assertRaises(RuntimeError):
                backend.solve()

    def test_cp_solvers_handle_missing_packages_cleanly(self) -> None:
        graph = path_graph(4)
        with patch.dict(sys.modules, {"ortools": None, "ortools.sat": None, "ortools.sat.python": None, "ortools.sat.python.cp_model": None}):
            res = CPSATSolver(seed=3).solve(graph, timeout_seconds=5, symmetry_breaking=True)
        self.assertIsInstance(res, SolverResult)
        self.assertEqual(res.status, SolutionStatus.UNAVAILABLE)
        self.assertEqual(res.method, "CP")
        self.assertEqual(res.solver, "cp-sat")
        self.assertIsNone(res.permutation)
        self.assertIn("reason", res.metadata)

        with patch.dict(sys.modules, {"docplex": None, "docplex.cp": None, "docplex.cp.model": None, "docplex.cp.solution": None, "docplex.cp.utils": None}):
            res_cpo = CPOptimizerSolver().solve(graph, timeout_seconds=5, symmetry_breaking=True)
        self.assertIsInstance(res_cpo, SolverResult)
        self.assertEqual(res_cpo.status, SolutionStatus.UNAVAILABLE)
        self.assertEqual(res_cpo.method, "CP")
        self.assertEqual(res_cpo.solver, "cp-optimizer")
        self.assertIsNone(res_cpo.permutation)
        self.assertIn("reason", res_cpo.metadata)

    def test_cp_optimizer_mock_extracts_feasible_bound_and_never_upgrades_to_optimal(self) -> None:
        graph = cycle_graph(4)
        fake_pos = {v: f"var_{v}" for v in graph.vertices}
        fake_result = types.SimpleNamespace(
            get_solve_status=lambda: "Feasible",
            get_stop_cause=lambda: "LimitReached",
            get_objective_bounds=lambda: (2.0,),
            get_value=lambda pos: {f"var_{v}": i for i, v in enumerate(graph.vertices, start=1)}[pos],
        )

        class _FakeSolverCtx:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def solve(self):
                return fake_result

        fake_model = types.SimpleNamespace(create_solver=lambda **kw: _FakeSolverCtx())
        fake_cp_model = types.ModuleType("docplex.cp.model")
        fake_cp_solution = types.ModuleType("docplex.cp.solution")
        fake_cp_solution.STOP_CAUSE_LIMIT = "LimitReached"
        fake_cp_utils = types.ModuleType("docplex.cp.utils")
        fake_cp_utils.CpoException = RuntimeError
        fake_cp = types.ModuleType("docplex.cp")
        fake_docplex = types.ModuleType("docplex")

        with (
            patch.dict(
                sys.modules,
                {
                    "docplex": fake_docplex,
                    "docplex.cp": fake_cp,
                    "docplex.cp.model": fake_cp_model,
                    "docplex.cp.solution": fake_cp_solution,
                    "docplex.cp.utils": fake_cp_utils,
                },
            ),
            patch("bmp.solvers.exact.cp_optimizer._build_model", return_value=(fake_model, fake_pos)),
            patch("bmp.solvers.exact.cp_optimizer.which", return_value="/fake/cpoptimizer"),
        ):
            res = CPOptimizerSolver().solve(graph, timeout_seconds=1.0)

        self.assertEqual(res.status, SolutionStatus.FEASIBLE)
        self.assertFalse(res.proved_optimal)
        self.assertEqual(res.lower_bound, 2)
        self.assertEqual(res.metadata["solver_lower_bound"], 2)
        self.assertTrue(validate_solution(graph, res).valid)

    def test_dataset_provenance_ready_filtering_and_steam3_diagnostics(self) -> None:
        self.assertEqual(len(ALL_INSTANCES), 113)
        prov = load_provenance_index(ROOT / "data" / "benchmark_provenance.json")
        self.assertEqual(len(prov), 113)
        self.assertEqual(sum(1 for v in prov.values() if v["validation_status"] == "READY"), 54)

        ds = HarwellBoeingDataset(
            ROOT / "data" / "harwell_boeing",
            provenance_path=ROOT / "data" / "benchmark_provenance.json",
        )
        ready = ds.ready_instances()
        self.assertEqual(len(ready), 40)
        self.assertEqual(ds.validation_status("steam3"), "NEEDS_VERIFICATION")
        with self.assertRaisesRegex(ValueError, "NEEDS_VERIFICATION"):
            ds.load("steam3", require_ready=True)

        diag = compare_matrix_market_conversions(ROOT / "data" / "harwell_boeing" / "raw" / "steam3.mtx.gz")
        self.assertFalse(diag["official_benchmark"])
        self.assertEqual(diag["explicit_off_diagonal_zeros"], 614)
        self.assertEqual(diag["variants"]["drop_explicit_zeros"]["m"], 156)
        self.assertEqual(diag["variants"]["keep_explicit_zeros"]["m"], 424)

    def test_cli_supports_m3_solvers_without_sat_or_mip_regression(self) -> None:
        sample = str(ROOT / "data" / "samples" / "cycle_c4.edgelist")
        for solver in ("rcm", "sa", "cp-sat", "cp-optimizer", "cadical", "glucose"):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = cli_main(["solve", sample, "--solver", solver])
            self.assertEqual(rc, 0)
            payload = json.loads(buf.getvalue())
            self.assertEqual(payload["solver"], solver)
            if solver in ("rcm", "sa"):
                self.assertEqual(payload["status"], "FEASIBLE")
                self.assertTrue(payload["validation"]["valid"])
            elif solver in ("cadical", "glucose"):
                self.assertEqual(payload["status"], "OPTIMAL")
                self.assertTrue(payload["validation"]["valid"])
            else:
                self.assertIn(payload["status"], ("OPTIMAL", "FEASIBLE", "UNAVAILABLE"))

        self.assertIsNotNone(GurobiMIPSolver)
        self.assertIsNotNone(CPLEXMIPSolver)
        self.assertTrue((ROOT / "results" / "member3-harwell-boeing.csv").is_file())


if __name__ == "__main__":
    unittest.main()
