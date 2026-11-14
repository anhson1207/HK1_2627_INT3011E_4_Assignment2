"""Comprehensive Phase M3.9 regression & attribution test suite."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from bmp.core.benchmark_catalog import ALL_INSTANCES
from bmp.core.generators import (
    complete_graph,
    cycle_graph,
    edgeless_graph,
    erdos_renyi_graph,
    path_graph,
    star_graph,
)
from bmp.core.graph import Graph
from bmp.core.solution import SolutionStatus, SolverResult
from bmp.core.validation import validate_solution
from bmp.encodings.cardinality import LadderAMOEncoder, ProductAMOEncoder, SimpleVarAllocator
from bmp.encodings.estimator import ResourceLimits, estimate_for_encoder
from bmp.encodings.order import OrderEncoding
from bmp.encodings.pairwise import PairwiseEncoding
from bmp.experiments.member3_m3_9 import (
    DEFAULT_M3_9_LIMITS,
    _choose_scheduler_configs,
    _stable_run_id,
    build_m3_9_dataset_113,
    classify_m3_9_attribution,
    evaluate_minisat_preflight_113,
)
from bmp.heuristics.drsa import DRSASolver
from bmp.heuristics.rcm import RCMSolver
from bmp.heuristics.sa import SimulatedAnnealingSolver
from bmp.solvers.brute_force import BruteForceSolver
from bmp.solvers.exact.cpsat import CPSATSolver
from bmp.solvers.sat.backends import get_sat_backend
from bmp.solvers.sat.backends.minisat import MiniSatBackend
from bmp.solvers.sat.incremental import IncrementalSATSolver
from bmp.solvers.sat.repeated import RepeatedSATSolver

ROOT = Path(__file__).resolve().parents[1]


class Member3M39RegressionTests(unittest.TestCase):
    def test_l9_compact_order_and_pairwise_match_estimator_and_oracle_with_minisat22(self) -> None:
        graphs = [
            path_graph(5),
            cycle_graph(5),
            star_graph(4),
            complete_graph(5),
            edgeless_graph(4),
            Graph.from_edges([1, 2, 3, 4, 5, 6], [(1, 2), (2, 3), (4, 5), (5, 6)], name="disconn"),
            Graph.from_edges([10, 20, 30, 40], [(10, 20), (20, 30)], name="isol"),
            erdos_renyi_graph(6, 0.45, seed=11),
        ]
        encoders = [
            OrderEncoding("product", channel_mode="one_sided", compact_boundary=True),
            OrderEncoding("ladder", channel_mode="one_sided", compact_boundary=True),
            PairwiseEncoding("product", occupancy_mode="pigeonhole", bandwidth_mode="support"),
            PairwiseEncoding("product", occupancy_mode="pigeonhole", bandwidth_mode="support_single"),
            PairwiseEncoding("ladder", occupancy_mode="pigeonhole", bandwidth_mode="support_single"),
        ]
        for g in graphs:
            oracle = BruteForceSolver().solve(g)
            for enc in encoders:
                # Estimator matches CNF generation across all L9+Product/Ladder combinations
                if g.order >= 2 and g.edges:
                    formula = enc.encode(g, k=max(0, g.order - 2), symmetry_breaking=True)
                    est = estimate_for_encoder(enc, g, k=max(0, g.order - 2), symmetry_breaking=True)
                    self.assertEqual(est.num_variables, formula.num_variables)
                    self.assertEqual(est.num_clauses, formula.num_clauses)

                for solver in (
                    RepeatedSATSolver(enc, backend_name="minisat", search_mode="linear", decompose_components=True),
                    RepeatedSATSolver(enc, backend_name="minisat", search_mode="binary", decompose_components=True),
                    IncrementalSATSolver(enc, backend_name="minisat", search_mode="linear", decompose_components=True),
                    IncrementalSATSolver(enc, backend_name="minisat", search_mode="binary", decompose_components=True),
                ):
                    res = solver.solve(g, symmetry_breaking=True)
                    self.assertEqual(res.status, SolutionStatus.OPTIMAL)
                    self.assertEqual(res.bandwidth, oracle.bandwidth)
                    self.assertEqual(res.lower_bound, oracle.bandwidth)
                    self.assertTrue(validate_solution(g, res).valid)

    def test_minisat_incremental_binary_reuses_single_backend_and_cleans_up(self) -> None:
        g = cycle_graph(6)
        bad_perm = {1: 1, 2: 6, 3: 2, 4: 5, 5: 3, 6: 4}
        created: list[MiniSatBackend] = []
        real_get = get_sat_backend

        def tracked(name: str = "minisat", **kw: object):
            inst = real_get(name, **kw)
            created.append(inst)
            return inst

        with patch("bmp.solvers.sat.incremental.get_sat_backend", side_effect=tracked):
            res = IncrementalSATSolver(
                OrderEncoding("product", channel_mode="one_sided", compact_boundary=True),
                backend_name="minisat",
                search_mode="binary",
            ).solve(g, heuristic_permutation=bad_perm, symmetry_breaking=True)
        self.assertEqual(len(created), 1)
        self.assertTrue(created[0]._deleted)
        self.assertEqual(res.status, SolutionStatus.OPTIMAL)
        self.assertEqual(res.bandwidth, 2)
        self.assertEqual(res.strategy, "incremental_binary")
        self.assertTrue(res.metadata["sat_solved_any"])

    def test_strict_solver_vs_heuristic_and_bounds_attribution(self) -> None:
        # 1. Heuristic fallback on timeout must NEVER be marked solver_found_solution=True
        timeout_fallback = SolverResult(
            method="SAT",
            solver="minisat",
            status=SolutionStatus.TIMEOUT,
            bandwidth=9,
            lower_bound=5,
            sat_calls=1,
            metadata={"sat_solved_any": False, "timed_out": True, "incumbent_source": "HEURISTIC"},
        )
        a1 = classify_m3_9_attribution(timeout_fallback, validation_passed=True, initial_incumbent_source="RCM")
        self.assertFalse(a1["solver_found_solution"])
        self.assertIsNone(a1["solver_best_bandwidth"])
        self.assertEqual(a1["attribution_status"], "TIMEOUT_HEURISTIC_FALLBACK")
        self.assertEqual(a1["incumbent_source"], "RCM")

        # 2. Timeout AFTER solver returned a SAT witness preserves solver witness without marking OPT
        timeout_sat = SolverResult(
            method="SAT",
            solver="minisat",
            status=SolutionStatus.TIMEOUT,
            bandwidth=8,
            lower_bound=5,
            sat_calls=2,
            metadata={"sat_solved_any": True, "timed_out": True, "incumbent_source": "sat"},
        )
        a2 = classify_m3_9_attribution(timeout_sat, validation_passed=True, initial_incumbent_source="RCM")
        self.assertTrue(a2["solver_found_solution"])
        self.assertFalse(a2["sat_proved_optimal"])
        self.assertEqual(a2["solver_best_bandwidth"], 8)
        self.assertEqual(a2["attribution_status"], "SAT_SOLVER_FEASIBLE")

        # 3. Bounds-only optimality certificate kept distinct from SAT UNSAT proof
        lb_eq_ub = SolverResult(
            method="SAT",
            solver="minisat",
            status=SolutionStatus.OPTIMAL,
            bandwidth=3,
            lower_bound=3,
            sat_calls=0,
            metadata={"fast_path": "lb_equals_ub", "sat_solved_any": False, "incumbent_source": "BOUNDS_OPTIMALITY_CERTIFICATE"},
        )
        a3 = classify_m3_9_attribution(lb_eq_ub, validation_passed=True, initial_incumbent_source="RCM")
        self.assertFalse(a3["sat_proved_optimal"])
        self.assertTrue(a3["bound_proved_optimal"])
        self.assertEqual(a3["attribution_status"], "BOUNDS_PROVED_OPTIMAL")

        # 4. Invalid assignment rejected loudly
        bad_sat = SolverResult(
            method="SAT", solver="minisat", status=SolutionStatus.OPTIMAL, bandwidth=3,
            metadata={"sat_solved_any": True},
        )
        a4 = classify_m3_9_attribution(bad_sat, validation_passed=False, initial_incumbent_source="RCM")
        self.assertFalse(a4["solver_found_solution"])
        self.assertEqual(a4["attribution_status"], "INVALID")

    def test_dataset_113_preflight_and_scheduler_fallback(self) -> None:
        with TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            ds_rows, graphs, _ = build_m3_9_dataset_113(
                root=ROOT,
                provenance_path=ROOT / "data/benchmark_provenance.json",
                raw_dir=ROOT / "data/benchmarks/raw",
                output_dir=out_dir,
            )
            self.assertEqual(len(ds_rows), 113)
            self.assertEqual(sum(1 for r in ds_rows if r["table"] == "Table 6"), 31)
            self.assertEqual(sum(1 for r in ds_rows if r["table"] == "Table 7"), 41)
            self.assertEqual(sum(1 for r in ds_rows if r["table"] == "Table 8"), 41)
            self.assertEqual(sum(1 for r in ds_rows if r["tier"] == "TIER1_READY"), 54)
            self.assertEqual(sum(1 for r in ds_rows if r["tier"] == "TIER2A_NEEDS_VERIFICATION"), 58)
            self.assertEqual(sum(1 for r in ds_rows if r["tier"] == "TIER2B_INVALID_DATA"), 1)

            rcm_bw = {r["instance"]: int(r["published_best"]) for r in ds_rows}
            pf_rows, elig_by_inst = evaluate_minisat_preflight_113(
                dataset_rows=ds_rows,
                graphs_by_inst=graphs,
                rcm_bw_by_inst=rcm_bw,
                limits=DEFAULT_M3_9_LIMITS,
                output_dir=out_dir,
            )
            self.assertEqual(len(pf_rows), 113 * 8)
            # Pairwise Product Pigeonhole Support-Single + component decomposition expands eligibility > 70
            self.assertGreaterEqual(len(elig_by_inst), 80)

            # Verify scheduler picks Pairwise Pigeonhole Support-Single when Order is blocked (e.g. saylr3 n=1000)
            saylr3_pf = [r for r in pf_rows if r["instance"] == "saylr3"]
            plan = _choose_scheduler_configs(saylr3_pf, n=1000)
            self.assertTrue(plan)
            self.assertEqual(plan[0]["config_id"], "pairwise_product_pigeon_ss_rep_binary")

    def test_no_duplicate_run_ids_and_preserved_1d_bmp_cpsat_heuristics(self) -> None:
        p1 = {"stage": "D", "instance": "pores_1", "backend": "minisat", "config_id": "c1"}
        p2 = {"config_id": "c1", "backend": "minisat", "instance": "pores_1", "stage": "D"}
        self.assertEqual(_stable_run_id(p1), _stable_run_id(p2))

        g = path_graph(6)
        cp = CPSATSolver(seed=17).solve(g, timeout_seconds=3.0)
        rcm = RCMSolver().solve(g)
        sa = SimulatedAnnealingSolver(iterations=200, seed=17).solve(g)
        drsa = DRSASolver(seed=17, initial_mode="rcm").solve(g, timeout_seconds=0.5)
        for res in (cp, rcm, sa, drsa):
            self.assertTrue(validate_solution(g, res.permutation, claimed_bandwidth=res.bandwidth).valid)

    def test_historical_complete_and_m38_untouched(self) -> None:
        self.assertTrue((ROOT / "results/member3_complete/cpsat_results.csv").is_file())
        self.assertTrue((ROOT / "results/member3_m3_8_full113/full113_summary.json").is_file())
        with (ROOT / "results/member3_complete/cpsat_results.csv").open(encoding="utf-8") as f:
            best_cp = [r for r in csv.DictReader(f) if r["is_best_for_instance"] == "True"]
        self.assertEqual(len(best_cp), 113)
        self.assertTrue(all(r["validation_passed"] == "True" for r in best_cp))


if __name__ == "__main__":
    unittest.main()
