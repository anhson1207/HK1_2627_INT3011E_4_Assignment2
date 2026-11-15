"""Integration and regression tests for Phase M2.1 (Leader L8 sync + Member 2)."""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import sys
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from bmp.cli import main as cli_main
from bmp.core.benchmark_catalog import ALL_INSTANCES
from bmp.core.generators import (
    cycle_graph,
    edgeless_graph,
    erdos_renyi_graph,
    path_graph,
    star_graph,
)
from bmp.core.graph import Graph
from bmp.core.solution import SolutionStatus
from bmp.core.validation import validate_solution
from bmp.encodings.estimator import ResourceLimits, estimate_cnf_size
from bmp.encodings.order import OrderEncoding
from bmp.encodings.pairwise import PairwiseEncoding
from bmp.experiments.member2_hb import run as run_hb
from bmp.solvers.brute_force import BruteForceSolver
from bmp.solvers.exact._common import prepare_mip_bounds
from bmp.solvers.exact.cplex import CPLEXMIPSolver
from bmp.solvers.exact.gurobi import GurobiMIPSolver
from bmp.solvers.sat.backends import GlucoseBackend, SATBackend, get_sat_backend
from bmp.solvers.sat.incremental import IncrementalSATSolver
from bmp.solvers.sat.repeated import RepeatedSATSolver
from bmp.solvers.sat.search import select_anchor_vertex

ROOT = Path(__file__).resolve().parents[1]


class Member2M21IntegrationTests(unittest.TestCase):
    def test_order_and_pairwise_with_binary_and_commander_match_oracle_and_estimator(self) -> None:
        graphs = [path_graph(5), cycle_graph(4), star_graph(4), erdos_renyi_graph(6, 0.4, seed=42)]
        for graph in graphs:
            oracle = BruteForceSolver().solve(graph)
            for enc_cls, enc_name in ((PairwiseEncoding, "pairwise"), (OrderEncoding, "order")):
                for amo in ("binary", "commander"):
                    for sym in (False, True):
                        encoder = enc_cls(amo=amo)
                        for k in (1, 2):
                            est = estimate_cnf_size(
                                graph, encoding=enc_name, amo=amo, k=k, symmetry_breaking=sym
                            )
                            formula = encoder.encode(graph, k=k, symmetry_breaking=sym)
                            self.assertEqual(est.num_variables, formula.num_variables)
                            self.assertEqual(est.num_clauses, formula.num_clauses)

                        with self.subTest(g=graph.name, enc=enc_name, amo=amo, sym=sym):
                            for strat_cls in (RepeatedSATSolver, IncrementalSATSolver):
                                res = strat_cls(encoder, backend_name="glucose").solve(
                                    graph, symmetry_breaking=sym
                                )
                                self.assertEqual(res.status, SolutionStatus.OPTIMAL)
                                self.assertEqual(res.bandwidth, oracle.bandwidth)
                                self.assertTrue(validate_solution(graph, res).valid)

    def test_glucose_backend_implements_l8_satbackend_contract(self) -> None:
        self.assertTrue(issubclass(GlucoseBackend, SATBackend))
        self.assertTrue(GlucoseBackend.is_available())
        for name in ("glucose", "glucose4"):
            with get_sat_backend(name) as backend:
                self.assertIsInstance(backend, GlucoseBackend)
                backend.append_formula([[1, 2], [-1]])
                self.assertTrue(backend.solve_with_timeout(None))
                self.assertIn(2, backend.get_model() or [])
                self.assertIsNone(backend.solve_with_timeout(0))
                self.assertIsNone(backend.get_model())
                self.assertTrue(backend.solve_with_timeout(1.0))
                backend.add_clause([-2])
                self.assertFalse(backend.solve_with_timeout(1.0))
                with self.assertRaises(ValueError):
                    backend.solve_with_timeout(-0.5)

    def test_glucose_worker_timeout_and_resource_limits_skip(self) -> None:
        graph = erdos_renyi_graph(7, 0.4, seed=19)
        tight_limits = ResourceLimits(max_clauses=30, timeout_seconds=None)
        for strat_cls in (RepeatedSATSolver, IncrementalSATSolver):
            skipped = strat_cls(OrderEncoding(amo="binary"), backend_name="glucose").solve(
                graph, limits=tight_limits
            )
            self.assertEqual(skipped.status, SolutionStatus.SKIPPED)
            self.assertEqual(skipped.sat_calls, 0)
            self.assertIn("skipped_reason", skipped.metadata)

            bounded = strat_cls(OrderEncoding(amo="commander"), backend_name="glucose").solve(
                graph, timeout_seconds=5.0, limits=ResourceLimits(memory_limit_mb=4096)
            )
            self.assertEqual(bounded.status, SolutionStatus.OPTIMAL)
            self.assertIn("sat_trace", bounded.metadata)
            self.assertGreaterEqual(bounded.metadata["sampled_peak_memory_mb"], 0)
            self.assertTrue(validate_solution(graph, bounded).valid)

        # Verify bounded worker timeout preserves incumbent & marks interrupted Glucose call UNKNOWN
        hard = erdos_renyi_graph(12, 0.7, seed=7)
        with patch("bmp.solvers.sat.backends.glucose.GlucoseBackend.solve", side_effect=lambda *a, **k: (__import__("time").sleep(0.5) or False)):
            timed = RepeatedSATSolver(OrderEncoding("binary"), backend_name="glucose").solve(
                hard, timeout_seconds=0.15, limits=ResourceLimits(memory_limit_mb=4096)
            )
        self.assertEqual(timed.status, SolutionStatus.TIMEOUT)
        self.assertTrue(validate_solution(hard, timed).valid)
        self.assertGreater(timed.metadata["sampled_peak_memory_mb"], 0)
        self.assertEqual(timed.metadata["sat_trace"][-1]["outcome"], "UNKNOWN")

    def test_on_incumbent_deduplication_and_provenance_sources(self) -> None:
        edgeless = edgeless_graph(4)
        edgeless_res = RepeatedSATSolver(OrderEncoding(), backend_name="glucose").solve(edgeless)
        self.assertEqual(edgeless_res.metadata.get("incumbent_source"), "edgeless")

        # Initial LB == UB fast path records heuristic vs initial cleanly
        p4 = path_graph(4)
        p4_init = IncrementalSATSolver(OrderEncoding(), backend_name="glucose").solve(p4)
        self.assertEqual(p4_init.metadata.get("incumbent_source"), "initial")

        # Heuristic permutation source preserved when LB == UB
        p4_heur = IncrementalSATSolver(OrderEncoding(), backend_name="glucose").solve(
            p4, heuristic_permutation={1: 1, 2: 2, 3: 3, 4: 4}
        )
        self.assertEqual(p4_heur.metadata.get("incumbent_source"), "heuristic")

        # Explicit suboptimal starting permutation forces SAT to improve 3 -> 2
        g = cycle_graph(4)
        checkpoints: list[tuple[dict[int, int], int]] = []

        def record(perm, bw):
            self.assertTrue(validate_solution(g, perm, claimed_bandwidth=bw).valid)
            checkpoints.append((dict(perm), bw))

        with patch("bmp.solvers.sat.incremental.compute_lower_bound", return_value=1):
            res = IncrementalSATSolver(OrderEncoding("binary"), backend_name="glucose").solve(
                g,
                heuristic_permutation={1: 1, 2: 2, 3: 3, 4: 4},
                timeout_seconds=5.0,
                on_incumbent=record,
            )
        self.assertEqual(res.status, SolutionStatus.OPTIMAL)
        self.assertEqual(res.bandwidth, 2)
        self.assertEqual(res.metadata.get("incumbent_source"), "sat")
        # Strictly improving/unique checkpoints only (no duplicate emission)
        keys = [(bw, tuple(sorted(p.items()))) for p, bw in checkpoints]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual([bw for _, bw in checkpoints], [3, 2])

    def test_mip_bounds_symmetry_alignment_and_mock_cleanup(self) -> None:
        # Graph where anchor vertex sits at the end of vertex tuple (position n > ceil(n/2))
        g = Graph.from_edges((1, 2, 3, 4, 5), ((5, 1), (5, 2), (5, 3), (5, 4)))
        anchor = select_anchor_vertex(g)
        self.assertEqual(anchor, 5)
        lb, ub, init_perm, chosen = prepare_mip_bounds(g, symmetry_breaking=True)
        self.assertEqual(chosen, anchor)
        self.assertLessEqual(init_perm[anchor], (g.order + 1) // 2)
        self.assertTrue(validate_solution(g, init_perm, claimed_bandwidth=ub).valid)
        self.assertLessEqual(lb, ub)

        class _MockExpr:
            def __sub__(self, other):
                return self
            def __rsub__(self, other):
                return self
            def __ge__(self, other):
                return self
            def __eq__(self, other):  # type: ignore[override]
                return True

        # Mock Gurobi to verify dispose() cleanup & NODE_LIMIT UNKNOWN/FEASIBLE status
        fake_grb = types.SimpleNamespace(
            BINARY="B", INTEGER="I", MINIMIZE=1,
            OPTIMAL=2, TIME_LIMIT=9, INFEASIBLE=3, INF_OR_UNBD=4, NODE_LIMIT=8,
        )
        fake_model = MagicMock()
        fake_model.addVar.side_effect = lambda *a, **kw: _MockExpr()
        fake_model.addVars.side_effect = lambda vs, ps, **kw: {(v, p): _MockExpr() for v in vs for p in ps}
        fake_model.Status = fake_grb.NODE_LIMIT
        fake_model.SolCount = 0
        fake_model.ObjBound = 2.0
        fake_model.MIPGap = 0.0
        fake_env = MagicMock()
        fake_gp = types.SimpleNamespace(
            GRB=fake_grb,
            GurobiError=RuntimeError,
            Env=lambda empty=True: fake_env,
            Model=lambda *a, **kw: fake_model,
            quicksum=lambda xs: _MockExpr(),
        )
        with patch.dict(sys.modules, {"gurobipy": fake_gp}):
            res = GurobiMIPSolver().solve(cycle_graph(4), symmetry_breaking=True)
        self.assertEqual(res.status, SolutionStatus.UNKNOWN)
        fake_model.dispose.assert_called_once()
        fake_env.dispose.assert_called_once()

        # Mock CPLEX to verify end() cleanup
        fake_cplex_model = MagicMock()
        fake_cplex_model.solution.get_status.return_value = 102
        fake_cplex_model.solution.get_status_string.return_value = "MIP_optimal_tolerance"
        fake_cplex_model.solution.is_primal_feasible.return_value = False
        fake_cplex_model.solution.MIP.get_best_objective.return_value = 3.0
        fake_cplex_model.solution.MIP.get_mip_relative_gap.return_value = 0.0
        fake_cplex_model.solution.status = types.SimpleNamespace(
            MIP_optimal=101, MIP_optimal_tolerance=102,
            MIP_time_limit_feasible=107, MIP_time_limit_infeasible=108,
        )
        fake_cplex_mod = types.SimpleNamespace(
            Cplex=lambda: fake_cplex_model,
            SparsePair=lambda ind, val: (ind, val),
            exceptions=types.SimpleNamespace(CplexError=RuntimeError),
        )
        with patch.dict(sys.modules, {"cplex": fake_cplex_mod}):
            cres = CPLEXMIPSolver().solve(cycle_graph(4), symmetry_breaking=True)
        self.assertEqual(cres.status, SolutionStatus.OPTIMAL)
        fake_cplex_model.end.assert_called_once()

    def test_hb_runner_enforces_113_catalog_and_ready_only_guard(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_dir = root / "raw"
            raw_dir.mkdir()
            # Create a tiny valid symmetric READY matrix named bcspwr01 (n=39 in catalog, chain edges)
            n = 39
            body = "%%MatrixMarket matrix coordinate pattern symmetric\n39 39 38\n" + "".join(
                f"{i + 1} {i}\n" for i in range(1, n)
            )
            ready_path = raw_dir / "bcspwr01.mtx.gz"
            ready_bytes = gzip.compress(body.encode("utf-8"))
            ready_path.write_bytes(ready_bytes)
            sha = hashlib.sha256(ready_bytes).hexdigest()

            prov = [
                {
                    "instance": "bcspwr01",
                    "validation_status": "READY",
                    "file_path": str(ready_path),
                    "sha256": sha,
                },
                {
                    "instance": "arc130",
                    "validation_status": "NEEDS_VERIFICATION",
                    "file_path": "",
                    "sha256": "",
                },
                {
                    "instance": "mbeause",
                    "validation_status": "INVALID_DATA",
                    "file_path": "",
                    "sha256": "",
                },
            ]
            prov_path = root / "provenance.json"
            prov_path.write_text(json.dumps(prov), encoding="utf-8")

            cfg_path = root / "hb.toml"
            cfg_path.write_text(
                '[benchmark]\n'
                'provenance = "provenance.json"\n'
                'raw_dir = "raw"\n'
                'output_dir = "out"\n'
                'timeout_seconds = 10.0\n'
                'repetitions = 1\n'
                'max_sat_variables = 500000\n'
                'max_sat_clauses = 2500000\n'
                'amo = ["binary"]\n'
                'solvers = ["glucose"]\n',
                encoding="utf-8",
            )
            run_hb(cfg_path, selected={"bcspwr01", "arc130", "mbeause"}, resume=False)
            with (root / "out/runs.csv").open(newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))

            by_inst = {r["instance"]: r for r in rows}
            self.assertEqual(by_inst["arc130"]["status"], "SKIPPED")
            self.assertEqual(by_inst["arc130"]["dataset_status"], "NEEDS_VERIFICATION")
            self.assertEqual(by_inst["mbeause"]["status"], "SKIPPED")
            self.assertEqual(by_inst["mbeause"]["dataset_status"], "INVALID_DATA")
            self.assertEqual(by_inst["bcspwr01"]["dataset_status"], "READY")
            self.assertEqual(by_inst["bcspwr01"]["status"], "OPTIMAL")
            self.assertEqual(int(by_inst["bcspwr01"]["bandwidth"]), 1)
            self.assertEqual(by_inst["bcspwr01"]["validation"], "True")
            comp = (root / "out/comparison.md").read_text(encoding="utf-8")
            self.assertIn("113", comp)
            self.assertEqual(len(ALL_INSTANCES), 113)

    def test_cli_retains_leader_sat_and_supports_member2_extensions(self) -> None:
        sample = str(ROOT / "data/samples/cycle_c4.edgelist")
        cases = [
            ["solve", sample, "--solver", "glucose", "--encoding", "order", "--amo", "binary", "--strategy", "incremental"],
            ["solve", sample, "--solver", "cadical", "--encoding", "pairwise", "--amo", "commander", "--strategy", "repeated"],
            ["estimate-cnf", sample, "--encoding", "order", "--amo", "commander", "-k", "1"],
            ["preflight-benchmark", "--dir", str(ROOT / "data/samples"), "--table", "6"],
        ]
        for argv in cases:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = cli_main(argv)
            self.assertEqual(rc, 0)
            payload = json.loads(buf.getvalue())
            self.assertIsInstance(payload, dict)


if __name__ == "__main__":
    unittest.main()
