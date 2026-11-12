"""Comprehensive regression tests for Leader Phase L9 Full 113/113 SAT scalability and deliverables."""

from __future__ import annotations

import csv
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from bmp.core.bounds import cuthill_mckee_order
from bmp.core.generators import cycle_graph, path_graph, star_graph
from bmp.core.graph import Graph
from bmp.core.solution import SolutionStatus
from bmp.core.validation import validate_assignment
from bmp.encodings.estimator import ResourceLimits, estimate_for_encoder, estimate_incremental_for_encoder
from bmp.encodings.order import OrderEncoding
from bmp.encodings.pairwise import PairwiseEncoding
from bmp.experiments.leader_l9 import audit_l9_environment
from bmp.experiments.leader_l9_plots import create_l9_plots
from bmp.io.readers import graph_from_matrix_market_forensics, inspect_matrix_market_forensics
from bmp.solvers.brute_force import BruteForceSolver
from bmp.solvers.sat.backends.base import get_sat_backend
from bmp.solvers.sat.incremental import IncrementalSATSolver
from bmp.solvers.sat.repeated import RepeatedSATSolver
from bmp.solvers.sat.search import (
    compose_component_permutations,
    extract_connected_components,
    tighten_permutation_local,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
L9_DIR = REPO_ROOT / "results" / "leader_l9_full113"


def _disconnected_sample() -> Graph:
    """Two non-trivial components (P4 and K3) plus two isolated vertices with non-contiguous IDs."""
    return Graph.from_edges(
        [10, 20, 30, 40, 50, 60, 70, 80, 90],
        [(10, 20), (20, 30), (30, 40), (50, 60), (60, 70), (50, 70)],
        name="disc_sample",
    )


def test_pairwise_l9_variants_match_bruteforce_oracle() -> None:
    graphs = [path_graph(5), cycle_graph(4), star_graph(4), _disconnected_sample()]
    for g in graphs:
        oracle = BruteForceSolver().solve(g)
        for occ in ("both", "pigeonhole"):
            for bwm in ("conflict", "support", "support_single"):
                for amo in ("pairwise", "sequential"):
                    enc = PairwiseEncoding(amo=amo, occupancy_mode=occ, bandwidth_mode=bwm)
                    solver = RepeatedSATSolver(enc, backend_name="cadical", search_mode="linear")
                    res = solver.solve(g, symmetry_breaking=True)
                    assert res.status is SolutionStatus.OPTIMAL
                    assert res.bandwidth == oracle.bandwidth
                    assert validate_assignment(g, res.permutation or {}, claimed_bandwidth=res.bandwidth).valid


def test_order_l9_variants_match_bruteforce_oracle() -> None:
    graphs = [path_graph(5), cycle_graph(4), star_graph(4), _disconnected_sample()]
    for g in graphs:
        oracle = BruteForceSolver().solve(g)
        for ch_mode in ("full", "one_sided"):
            for compact in (False, True):
                for amo in ("pairwise", "sequential"):
                    enc = OrderEncoding(amo=amo, channel_mode=ch_mode, compact_boundary=compact)
                    solver = RepeatedSATSolver(enc, backend_name="cadical", search_mode="linear")
                    res = solver.solve(g, symmetry_breaking=True)
                    assert res.status is SolutionStatus.OPTIMAL
                    assert res.bandwidth == oracle.bandwidth
                    assert validate_assignment(g, res.permutation or {}, claimed_bandwidth=res.bandwidth).valid


def test_estimator_exactness_across_all_l9_variants() -> None:
    g = Graph.from_edges(range(1, 8), [(1, 2), (2, 3), (3, 4), (4, 5), (5, 6), (6, 7), (1, 5), (2, 6)], name="est7")
    for k in (2, 4):
        for amo in ("pairwise", "sequential"):
            for occ in ("both", "pigeonhole"):
                for bwm in ("conflict", "support", "support_single"):
                    enc = PairwiseEncoding(amo=amo, occupancy_mode=occ, bandwidth_mode=bwm)
                    f = enc.encode(g, k, symmetry_breaking=True)
                    est = estimate_for_encoder(enc, g, k=k, symmetry_breaking=True)
                    assert est.num_variables == f.num_variables
                    assert est.num_clauses == f.num_clauses
            for ch in ("full", "one_sided"):
                for comp in (False, True):
                    enc_o = OrderEncoding(amo=amo, channel_mode=ch, compact_boundary=comp)
                    f_o = enc_o.encode(g, k, symmetry_breaking=True)
                    est_o = estimate_for_encoder(enc_o, g, k=k, symmetry_breaking=True)
                    assert est_o.num_variables == f_o.num_variables
                    assert est_o.num_clauses == f_o.num_clauses

                    est_inc = estimate_incremental_for_encoder(
                        enc_o, g, initial_k=k + 1, target_k=k, symmetry_breaking=True, search_mode="binary"
                    )
                    assert est_inc.num_clauses > est_o.num_clauses


def test_incremental_binary_linear_and_decomposition_match_oracle() -> None:
    g = _disconnected_sample()
    oracle = BruteForceSolver().solve(g)
    enc = OrderEncoding(amo="sequential", channel_mode="one_sided", compact_boundary=True)
    for strat_cls in (RepeatedSATSolver, IncrementalSATSolver):
        for smode in ("linear", "binary"):
            for decomp in (False, True):
                solver = strat_cls(enc, backend_name="cadical", search_mode=smode, decompose_components=decomp)
                res = solver.solve(g, symmetry_breaking=True)
                assert res.status is SolutionStatus.OPTIMAL
                assert res.bandwidth == oracle.bandwidth
                assert validate_assignment(g, res.permutation or {}, claimed_bandwidth=res.bandwidth).valid


def test_cuthill_mckee_and_tighten_permutation_local() -> None:
    g = _disconnected_sample()
    order = cuthill_mckee_order(g)
    assert set(order) == set(g.vertices)
    perm = {v: idx for idx, v in enumerate(order, start=1)}
    rep_before = validate_assignment(g, perm)
    assert rep_before.valid and rep_before.actual_bandwidth is not None
    tight_bw, tight_perm = tighten_permutation_local(g, perm)
    rep_after = validate_assignment(g, tight_perm, claimed_bandwidth=tight_bw)
    assert rep_after.valid
    assert tight_bw <= rep_before.actual_bandwidth


def test_worker_zero_timeout_and_decomposed_incumbent_separation() -> None:
    g = _disconnected_sample()
    enc = OrderEncoding(amo="sequential", channel_mode="one_sided", compact_boundary=True)
    solver = IncrementalSATSolver(enc, backend_name="cadical", search_mode="binary", decompose_components=True)
    res_to = solver.solve(g, timeout_seconds=0.0, symmetry_breaking=True)
    assert res_to.status is SolutionStatus.TIMEOUT
    assert res_to.metadata.get("sat_solved_any") is False
    assert res_to.metadata.get("incumbent_source") == "HEURISTIC"
    assert validate_assignment(g, res_to.permutation or {}, claimed_bandwidth=res_to.bandwidth).valid

    # On positive timeout with decomposition, solver finishes OPTIMAL with valid permutation
    res_ok = solver.solve(g, timeout_seconds=10.0, symmetry_breaking=True)
    assert res_ok.status is SolutionStatus.OPTIMAL
    assert validate_assignment(g, res_ok.permutation or {}, claimed_bandwidth=res_ok.bandwidth).valid


def test_mbeause_forensics_496_vs_492_and_component_extraction() -> None:
    mbeause_path = REPO_ROOT / "data" / "benchmarks" / "raw" / "mbeause.mtx.gz"
    if not mbeause_path.exists():
        # Verify synthetic isolated-vertex reduction behaves identically if raw cache is absent
        g = _disconnected_sample()
        comps, isolated = extract_connected_components(g)
        assert len(comps) == 2 and sorted(isolated) == [80, 90]
        return
    fx = inspect_matrix_market_forensics(mbeause_path)
    g496 = graph_from_matrix_market_forensics(fx, policy="nonzero_union", one_based=True)
    comps, isolated = extract_connected_components(g496)
    assert g496.order == 496
    assert len(isolated) == 4
    assert comps[0].order == 492
    composed = compose_component_permutations(
        g496, [{v: i for i, v in enumerate(comps[0].vertices, start=1)}], isolated
    )
    assert validate_assignment(g496, composed).valid


def test_create_l9_plots_handles_minimal_csvs_cleanly(tmp_path: Path) -> None:
    # Minimal valid CSVs matching L9 schemas must produce 12 clean XML SVGs without crashes or NaN
    (tmp_path / "dataset_113.csv").write_text(
        "instance,table,validation_status,n,largest_component_n\npores_1,Table 6,READY,30,30\n", encoding="utf-8"
    )
    (tmp_path / "sat_preflight_113.csv").write_text(
        "instance,config_id,preflight_status,n,total_vars,total_clauses\n"
        "pores_1,base_pw_pw_rep_lin,ELIGIBLE,30,1800,45000\n"
        "pores_1,base_ord_seq_rep_lin,ELIGIBLE,30,2610,12000\n"
        "pores_1,l9_pw_pig_supsing_seq_rep_bin_dec,ELIGIBLE,30,1770,9000\n",
        encoding="utf-8",
    )
    (tmp_path / "per_instance_best.csv").write_text(
        "instance,table,official_benchmark,final_status,sat_solver_found_solution,rcm_ub,best_sat_bandwidth,published_best\n"
        "pores_1,Table 6,True,SAT_OPTIMAL,True,9,7,7\n",
        encoding="utf-8",
    )
    (tmp_path / "no_regression_report.csv").write_text(
        "era,eligible_count,sat_attempted_instances,sat_solved_instances,proved_optimal_instances\n"
        "Before_L9_L8_Official,53,2,2,1\nAfter_L9_Leader_SAT,70,70,23,3\n",
        encoding="utf-8",
    )
    svgs = create_l9_plots(tmp_path)
    assert len(svgs) == 12
    for svg in svgs:
        txt = svg.read_text(encoding="utf-8")
        ET.fromstring(txt)
        assert "NaN" not in txt


def test_persisted_leader_l9_deliverables_and_invariants() -> None:
    expected = [
        "dataset_113.csv",
        "sat_preflight_113.csv",
        "baseline_results.csv",
        "encoding_comparison.csv",
        "amo_comparison.csv",
        "strategy_comparison.csv",
        "search_comparison.csv",
        "warm_start_comparison.csv",
        "sat_runs_113.csv",
        "per_instance_best.csv",
        "resource_gap_analysis.csv",
        "no_regression_report.csv",
        "summary.json",
        "metadata.json",
        "run_log.txt",
        "reproduction.md",
        "figures",
    ]
    for name in expected:
        assert (L9_DIR / name).exists(), f"Missing deliverable: {name}"

    ds_rows = list(csv.DictReader((L9_DIR / "dataset_113.csv").open(encoding="utf-8")))
    assert len(ds_rows) == 113
    assert sum(r["validation_status"] == "READY" for r in ds_rows) == 54
    assert sum(r["validation_status"] == "NEEDS_VERIFICATION" for r in ds_rows) == 58
    assert sum(r["validation_status"] == "INVALID_DATA" for r in ds_rows) == 1

    runs = list(csv.DictReader((L9_DIR / "sat_runs_113.csv").open(encoding="utf-8")))
    assert len(runs) == len({r["run_id"] for r in runs})
    assert all(r["found_permutation_valid"] != "False" for r in runs)
    assert all(r["solver_status"] != "ERROR" for r in runs)
    for r in runs:
        if r["sat_solved_any"] == "True":
            assert r["incumbent_source"] == "SAT"

    best = list(csv.DictReader((L9_DIR / "per_instance_best.csv").open(encoding="utf-8")))
    assert len(best) == 113
    assert all(r["below_published_lb_flag"] == "False" for r in best)

    summary = json.loads((L9_DIR / "summary.json").read_text(encoding="utf-8"))
    assert summary["batch_execution"]["interrupted_by_batch_budget"] is False
    assert summary["overall_113_coverage"]["sat_solved_feasible"] == sum(
        r["sat_solver_found_solution"] == "True" for r in best
    )
    assert summary["overall_113_coverage"]["proved_optimal"] == sum(
        r["proved_optimal"] == "True" for r in best
    )

    svgs = sorted((L9_DIR / "figures").glob("*.svg"))
    assert len(svgs) == 12
    for svg in svgs:
        txt = svg.read_text(encoding="utf-8")
        ET.fromstring(txt)
        assert "NaN" not in txt and "No observed" not in txt

    meta = audit_l9_environment(limits=ResourceLimits(), memory_limit_mb=4096.0)
    assert meta["cadical_backend"]
    assert len(runs) == len({r["run_id"] for r in runs})
    # Verify checkpoint_runs.json equals sat_runs_113.csv count (resume idempotency)
    ckpt = json.loads((L9_DIR / "checkpoint_runs.json").read_text(encoding="utf-8"))
    assert len(ckpt) == len(runs)
