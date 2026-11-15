"""Phase M3.8 Full 113/113 Harwell-Boeing Coverage, Legacy Compatibility & Exact/Heuristic Audit."""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import math
import os
import statistics
import subprocess
import sys
import tomllib
from collections import Counter, defaultdict
from pathlib import Path
from time import monotonic
from typing import Any

from bmp.core.benchmark_catalog import ALL_INSTANCES, resolve_raw_matrix_path
from bmp.core.bounds import cuthill_mckee_order
from bmp.core.graph import Graph
from bmp.core.solution import SolutionStatus, SolverResult
from bmp.core.validation import calculate_bandwidth, validate_solution
from bmp.encodings.estimator import ResourceLimits, estimate_cnf_size, estimate_incremental_cnf_size
from bmp.encodings.order import OrderEncoding
from bmp.encodings.pairwise import PairwiseEncoding
from bmp.experiments.member2_hb import _self_rss_mb as _process_peak_rss_mb
from bmp.experiments.member3_m3_6 import audit_environment
from bmp.heuristics.drsa import DRSASolver
from bmp.heuristics.rcm import RCMSolver
from bmp.heuristics.sa import SimulatedAnnealingSolver
from bmp.io.readers import (
    CONVERSION_VERSION,
    OFFICIAL_CONVERSION_POLICY,
    MatrixMarketForensics,
    compute_graph_fingerprint,
    compute_topology_sha256,
    graph_from_matrix_market_forensics,
    inspect_matrix_market_forensics,
)
from bmp.solvers.exact import CPLEXMIPSolver, CPOptimizerSolver, CPSATSolver, GurobiMIPSolver
from bmp.solvers.sat.incremental import IncrementalSATSolver
from bmp.solvers.sat.repeated import RepeatedSATSolver
from bmp.solvers.sat.search import compute_lower_bound

COVERAGE_STATUSES: tuple[str, ...] = (
    "DATASET_LOADED",
    "PREFLIGHT_EVALUATED",
    "SOLVER_ATTEMPTED",
    "FEASIBLE_SOLUTION_FOUND",
    "OPTIMAL_PROVED",
    "TIMEOUT_WITH_INCUMBENT",
    "TIMEOUT_NO_INCUMBENT",
    "RESOURCE_LIMIT",
    "BLOCKED_LICENSE",
    "ERROR",
)

DATASET_113_FIELDS: tuple[str, ...] = (
    "instance",
    "table",
    "raw_file_path",
    "source_sha256",
    "matrix_rows",
    "matrix_cols",
    "matrix_symmetry",
    "primary_conversion_policy",
    "conversion_version",
    "tier",
    "official_benchmark",
    "validation_status",
    "n",
    "m_primary",
    "m_nonzero_union",
    "m_stored_union",
    "explicit_offdiag_zeros",
    "components",
    "isolated_vertices",
    "certified_lb",
    "paper_lb",
    "paper_best",
    "topology_sha256",
    "graph_fingerprint",
    "topology_duplicate_of",
    "graph_loading_result",
)

GRAPH_VIEWS_FIELDS: tuple[str, ...] = (
    "view_id",
    "instance",
    "table",
    "is_primary_113",
    "view_kind",
    "conversion_policy",
    "conversion_version",
    "official_benchmark",
    "validation_status",
    "n",
    "m",
    "components",
    "isolated_vertices",
    "certified_lb",
    "topology_sha256",
    "graph_fingerprint",
    "notes",
)

RUN_ROW_FIELDS: tuple[str, ...] = (
    "run_id",
    "stage",
    "view_id",
    "instance",
    "table",
    "is_primary_113",
    "official_benchmark",
    "validation_status",
    "conversion_policy",
    "graph_fingerprint",
    "topology_sha256",
    "topology_duplicate_of",
    "n",
    "m",
    "family",
    "method",
    "backend",
    "main_encoding",
    "amo_encoding",
    "strategy",
    "symmetry_breaking",
    "warm_start_mode",
    "warm_start_source",
    "warm_start_bw",
    "seed",
    "threads",
    "time_limit_seconds",
    "dataset_loaded",
    "preflight_evaluated",
    "solver_attempted",
    "has_valid_solution",
    "proved_optimal",
    "raw_status",
    "m3_8_coverage_status",
    "bandwidth",
    "lower_bound",
    "upper_bound",
    "best_bound",
    "gap_vs_lb",
    "paper_lb",
    "paper_best",
    "gap_vs_published_best",
    "below_paper_lb_flag",
    "validation_passed",
    "model_construction_time_s",
    "solver_time_s",
    "preprocessing_time_s",
    "total_wall_time_s",
    "peak_rss_mb",
    "SAT_calls",
    "CNF_variables",
    "CNF_clauses",
    "heuristic_moves",
    "blocker_reason",
    "notes",
)


def _write_csv_atomic(path: Path, fieldnames: list[str] | tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    os.replace(tmp, path)


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _stable_id(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    return "m38-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _estimate_ram_mb(num_vars: int, num_clauses: int) -> float:
    return round(32.0 + num_vars * 0.00012 + num_clauses * 0.000095, 2)


def _connected_component_count(graph: Graph) -> int:
    if graph.order == 0:
        return 0
    adj: dict[int, list[int]] = {v: [] for v in graph.vertices}
    for u, v in graph.edges:
        adj[u].append(v)
        adj[v].append(u)
    visited: set[int] = set()
    comps = 0
    for start in graph.vertices:
        if start in visited:
            continue
        comps += 1
        stack = [start]
        visited.add(start)
        while stack:
            curr = stack.pop()
            for nbr in adj[curr]:
                if nbr not in visited:
                    visited.add(nbr)
                    stack.append(nbr)
    return comps


def build_m3_8_dataset_and_views(
    *,
    root: Path,
    provenance_path: Path,
    raw_dir: Path,
    output_dir: Path,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Graph],
    dict[str, dict[str, Any]],
]:
    """Load ALL 113 Harwell-Boeing instances and construct canonical + exploratory graph views."""

    prov_list = json.loads(provenance_path.read_text(encoding="utf-8"))
    prov_map = {str(e["instance"]): dict(e) for e in prov_list if isinstance(e, dict) and "instance" in e}

    dataset_rows: list[dict[str, Any]] = []
    view_rows: list[dict[str, Any]] = []
    graphs_by_view: dict[str, Graph] = {}
    meta_by_view: dict[str, dict[str, Any]] = {}

    # Track topology SHA256 under chosen primary conversion across 113
    seen_primary_topo: dict[str, str] = {}

    for name, cat_meta in ALL_INSTANCES.items():
        prov = prov_map.get(name, {})
        val_status = str(prov.get("validation_status", "UNKNOWN"))
        raw_path = raw_dir / f"{name}.mtx.gz"
        if not raw_path.exists():
            resolved = resolve_raw_matrix_path(name, root=root)
            raw_path = resolved if resolved is not None else raw_path
        if not raw_path.exists():
            raise FileNotFoundError(f"Missing raw file for {name}: {raw_path}")

        forensics: MatrixMarketForensics = inspect_matrix_market_forensics(raw_path)
        g_nz = graph_from_matrix_market_forensics(forensics, policy="nonzero_union", one_based=True)
        g_st = (
            g_nz
            if forensics.offdiagonal_entries_zero == 0
            else graph_from_matrix_market_forensics(forensics, policy="stored_union", one_based=True)
        )

        # Tier-1 READY uses strict canonical nonzero_union; Tier-2 NEEDS_VERIFICATION prefers stored_union
        # because M3.5 demonstrated structural/explicit-zero preservation evidence (still marked official_benchmark=False).
        # mbeause keeps all 496 vertices on its primary view (INVALID_DATA), plus 492 sensitivity view.
        if val_status == "READY":
            primary_policy = "nonzero_union"
            g_primary = g_nz
            tier = "TIER1_VERIFIED_CANONICAL"
            official = True
        elif val_status == "NEEDS_VERIFICATION":
            primary_policy = "stored_union"
            g_primary = g_st
            tier = "TIER2_EXPLORATORY_UNVERIFIED"
            official = False
        else:
            # INVALID_DATA (mbeause)
            primary_policy = "nonzero_union"
            g_primary = g_nz
            tier = "TIER2_EXPLORATORY_INVALID_DATA"
            official = False

        comps = _connected_component_count(g_primary)
        iso_cnt = sum(1 for v in g_primary.vertices if g_primary.degree(v) == 0)
        cert_lb = compute_lower_bound(g_primary)
        topo_sha = compute_topology_sha256(g_primary)
        gfp = compute_graph_fingerprint(g_primary, conversion_policy=primary_policy, conversion_version=CONVERSION_VERSION)
        dup_of = seen_primary_topo.get(topo_sha)
        if dup_of is None:
            seen_primary_topo[topo_sha] = name

        g_wrapped = Graph(
            g_primary.vertices,
            g_primary.edges,
            name=name,
            metadata={
                **dict(g_primary.metadata or {}),
                "instance": name,
                "conversion_policy": primary_policy,
                "conversion_version": CONVERSION_VERSION,
                "topology_sha256": topo_sha,
                "graph_fingerprint": gfp,
                "validation_status": val_status,
                "official_benchmark": official,
            },
        )
        primary_view_id = f"{name}__primary"
        graphs_by_view[primary_view_id] = g_wrapped
        base_info = {
            "view_id": primary_view_id,
            "instance": name,
            "table": cat_meta.source_table,
            "is_primary_113": True,
            "tier": tier,
            "official_benchmark": official,
            "validation_status": val_status,
            "conversion_policy": primary_policy,
            "graph_fingerprint": gfp,
            "topology_sha256": topo_sha,
            "topology_duplicate_of": dup_of,
            "n": g_wrapped.order,
            "m": g_wrapped.size,
            "certified_lb": cert_lb,
            "paper_lb": cat_meta.paper_lb,
            "paper_best": cat_meta.paper_best,
            "raw_file_path": str(raw_path.relative_to(root)) if raw_path.is_relative_to(root) else str(raw_path),
        }
        meta_by_view[primary_view_id] = base_info

        dataset_rows.append({
            "instance": name,
            "table": cat_meta.source_table,
            "raw_file_path": base_info["raw_file_path"],
            "source_sha256": prov.get("sha256") or hashlib.sha256(raw_path.read_bytes()).hexdigest(),
            "matrix_rows": forensics.rows,
            "matrix_cols": forensics.columns,
            "matrix_symmetry": forensics.symmetry,
            "primary_conversion_policy": primary_policy,
            "conversion_version": CONVERSION_VERSION,
            "tier": tier,
            "official_benchmark": official,
            "validation_status": val_status,
            "n": g_wrapped.order,
            "m_primary": g_wrapped.size,
            "m_nonzero_union": g_nz.size,
            "m_stored_union": g_st.size,
            "explicit_offdiag_zeros": forensics.offdiagonal_entries_zero,
            "components": comps,
            "isolated_vertices": iso_cnt,
            "certified_lb": cert_lb,
            "paper_lb": cat_meta.paper_lb,
            "paper_best": cat_meta.paper_best,
            "topology_sha256": topo_sha,
            "graph_fingerprint": gfp,
            "topology_duplicate_of": dup_of,
            "graph_loading_result": "DATASET_LOADED",
        })

        view_rows.append({
            "view_id": primary_view_id,
            "instance": name,
            "table": cat_meta.source_table,
            "is_primary_113": True,
            "view_kind": "PRIMARY_CANONICAL_READY" if official else ("PRIMARY_EXPLORATORY_STORED_UNION" if val_status == "NEEDS_VERIFICATION" else "PRIMARY_RAW_496_INVALID_DATA"),
            "conversion_policy": primary_policy,
            "conversion_version": CONVERSION_VERSION,
            "official_benchmark": official,
            "validation_status": val_status,
            "n": g_wrapped.order,
            "m": g_wrapped.size,
            "components": comps,
            "isolated_vertices": iso_cnt,
            "certified_lb": cert_lb,
            "topology_sha256": topo_sha,
            "graph_fingerprint": gfp,
            "notes": f"Primary 113 view ({tier})",
        })

        # Sensitivity views (do NOT count toward 113 primary metrics; used strictly for conversion sensitivity!)
        if val_status == "NEEDS_VERIFICATION" and g_nz.size != g_st.size:
            nz_view_id = f"{name}__nonzero_sens"
            nz_topo = compute_topology_sha256(g_nz)
            nz_fp = compute_graph_fingerprint(g_nz, conversion_policy="nonzero_union", conversion_version=CONVERSION_VERSION)
            nz_lb = compute_lower_bound(g_nz)
            graphs_by_view[nz_view_id] = Graph(
                g_nz.vertices,
                g_nz.edges,
                name=name,
                metadata={
                    **dict(g_nz.metadata or {}),
                    "instance": name,
                    "conversion_policy": "nonzero_union",
                    "conversion_version": CONVERSION_VERSION,
                    "topology_sha256": nz_topo,
                    "graph_fingerprint": nz_fp,
                    "validation_status": val_status,
                    "official_benchmark": False,
                },
            )
            meta_by_view[nz_view_id] = {
                **base_info,
                "view_id": nz_view_id,
                "is_primary_113": False,
                "official_benchmark": False,
                "conversion_policy": "nonzero_union",
                "graph_fingerprint": nz_fp,
                "topology_sha256": nz_topo,
                "n": g_nz.order,
                "m": g_nz.size,
                "certified_lb": nz_lb,
            }
            view_rows.append({
                "view_id": nz_view_id,
                "instance": name,
                "table": cat_meta.source_table,
                "is_primary_113": False,
                "view_kind": "SENSITIVITY_NONZERO_UNION",
                "conversion_policy": "nonzero_union",
                "conversion_version": CONVERSION_VERSION,
                "official_benchmark": False,
                "validation_status": val_status,
                "n": g_nz.order,
                "m": g_nz.size,
                "components": _connected_component_count(g_nz),
                "isolated_vertices": sum(1 for v in g_nz.vertices if g_nz.degree(v) == 0),
                "certified_lb": nz_lb,
                "topology_sha256": nz_topo,
                "graph_fingerprint": nz_fp,
                "notes": f"Sensitivity comparison: stored_union m={g_st.size} vs nonzero_union m={g_nz.size}",
            })

        if name == "mbeause":
            # Construct explicit 492 sensitivity view removing the 4 isolated vertices [493..496]
            deg0_verts = sorted(v for v in g_nz.vertices if g_nz.degree(v) == 0)
            kept_verts = [v for v in g_nz.vertices if v not in set(deg0_verts)]
            g_492_raw = Graph.from_edges(kept_verts, g_nz.edges, name="mbeause")
            topo_492 = compute_topology_sha256(g_492_raw)
            fp_492 = compute_graph_fingerprint(g_492_raw, conversion_policy="nonzero_union_drop_4_isolated", conversion_version=CONVERSION_VERSION)
            lb_492 = compute_lower_bound(g_492_raw)
            sens_492_id = "mbeause__drop4_492_sens"
            graphs_by_view[sens_492_id] = Graph(
                g_492_raw.vertices,
                g_492_raw.edges,
                name="mbeause",
                metadata={
                    "instance": "mbeause",
                    "conversion_policy": "nonzero_union_drop_4_isolated",
                    "conversion_version": CONVERSION_VERSION,
                    "topology_sha256": topo_492,
                    "graph_fingerprint": fp_492,
                    "validation_status": val_status,
                    "official_benchmark": False,
                },
            )
            meta_by_view[sens_492_id] = {
                **base_info,
                "view_id": sens_492_id,
                "is_primary_113": False,
                "official_benchmark": False,
                "conversion_policy": "nonzero_union_drop_4_isolated",
                "graph_fingerprint": fp_492,
                "topology_sha256": topo_492,
                "n": g_492_raw.order,
                "m": g_492_raw.size,
                "certified_lb": lb_492,
            }
            view_rows.append({
                "view_id": sens_492_id,
                "instance": "mbeause",
                "table": cat_meta.source_table,
                "is_primary_113": False,
                "view_kind": "SENSITIVITY_MBEAUSE_492",
                "conversion_policy": "nonzero_union_drop_4_isolated",
                "conversion_version": CONVERSION_VERSION,
                "official_benchmark": False,
                "validation_status": val_status,
                "n": g_492_raw.order,
                "m": g_492_raw.size,
                "components": _connected_component_count(g_492_raw),
                "isolated_vertices": 0,
                "certified_lb": lb_492,
                "topology_sha256": topo_492,
                "graph_fingerprint": fp_492,
                "notes": f"Sensitivity view removing exact isolated vertices {deg0_verts} -> n=492 matching Table 8 row header",
            })

    _write_csv_atomic(output_dir / "dataset_113.csv", DATASET_113_FIELDS, dataset_rows)
    _write_csv_atomic(output_dir / "graph_views_113.csv", GRAPH_VIEWS_FIELDS, view_rows)
    return dataset_rows, view_rows, graphs_by_view, meta_by_view


def _map_result_to_m3_8_status(
    result: SolverResult,
    *,
    validation_passed: bool | None,
    has_incumbent: bool,
) -> str:
    if result.status is SolutionStatus.OPTIMAL and validation_passed:
        return "OPTIMAL_PROVED"
    if result.status is SolutionStatus.FEASIBLE and validation_passed:
        return "FEASIBLE_SOLUTION_FOUND"
    if result.status is SolutionStatus.TIMEOUT:
        return "TIMEOUT_WITH_INCUMBENT" if (has_incumbent and validation_passed) else "TIMEOUT_NO_INCUMBENT"
    if result.status is SolutionStatus.SKIPPED:
        reason = str((result.metadata or {}).get("skipped_reason", "")).lower()
        return "RESOURCE_LIMIT"
    if result.status is SolutionStatus.UNAVAILABLE:
        return "BLOCKED_LICENSE"
    return "ERROR"


def _make_run_record(
    *,
    run_id: str,
    stage: str,
    meta: dict[str, Any],
    family: str,
    method: str,
    backend: str | None,
    main_encoding: str | None,
    amo_encoding: str | None,
    strategy: str | None,
    symmetry_breaking: bool,
    warm_start_mode: str,
    warm_start_source: str | None,
    warm_start_bw: int | None,
    seed: int | None,
    threads: int,
    time_limit_seconds: float | None,
    solver_attempted: bool,
    raw_status: str,
    m3_8_status: str,
    bandwidth: int | None,
    lower_bound: int | None,
    upper_bound: int | None,
    best_bound: float | None,
    validation_passed: bool | None,
    model_construction_time_s: float | None,
    solver_time_s: float | None,
    preprocessing_time_s: float | None,
    total_wall_time_s: float | None,
    peak_rss_mb: float | None,
    sat_calls: int | None,
    cnf_vars: int | None,
    cnf_clauses: int | None,
    heuristic_moves: int | None,
    blocker_reason: str | None,
    notes: str = "",
) -> dict[str, Any]:
    pub_best = int(meta["paper_best"])
    pub_lb = int(meta["paper_lb"])
    valid_sol = bool(bandwidth is not None and validation_passed is True)
    proved_opt = bool(m3_8_status == "OPTIMAL_PROVED")
    gap_lb = None if (bandwidth is None or lower_bound is None) else int(bandwidth) - int(lower_bound)
    gap_pub = None if bandwidth is None else int(bandwidth) - pub_best
    below_lb = bool(bandwidth is not None and int(bandwidth) < pub_lb)
    return {
        "run_id": run_id,
        "stage": stage,
        "view_id": meta["view_id"],
        "instance": meta["instance"],
        "table": meta["table"],
        "is_primary_113": meta["is_primary_113"],
        "official_benchmark": meta["official_benchmark"],
        "validation_status": meta["validation_status"],
        "conversion_policy": meta["conversion_policy"],
        "graph_fingerprint": meta["graph_fingerprint"],
        "topology_sha256": meta["topology_sha256"],
        "topology_duplicate_of": meta.get("topology_duplicate_of"),
        "n": int(meta["n"]),
        "m": int(meta["m"]),
        "family": family,
        "method": method,
        "backend": backend,
        "main_encoding": main_encoding,
        "amo_encoding": amo_encoding,
        "strategy": strategy,
        "symmetry_breaking": symmetry_breaking,
        "warm_start_mode": warm_start_mode,
        "warm_start_source": warm_start_source,
        "warm_start_bw": warm_start_bw,
        "seed": seed,
        "threads": threads,
        "time_limit_seconds": time_limit_seconds,
        "dataset_loaded": True,
        "preflight_evaluated": True,
        "solver_attempted": solver_attempted,
        "has_valid_solution": valid_sol,
        "proved_optimal": proved_opt,
        "raw_status": raw_status,
        "m3_8_coverage_status": m3_8_status,
        "bandwidth": bandwidth,
        "lower_bound": lower_bound,
        "upper_bound": upper_bound,
        "best_bound": best_bound,
        "gap_vs_lb": gap_lb,
        "paper_lb": pub_lb,
        "paper_best": pub_best,
        "gap_vs_published_best": gap_pub,
        "below_paper_lb_flag": below_lb,
        "validation_passed": validation_passed,
        "model_construction_time_s": None if model_construction_time_s is None else round(model_construction_time_s, 6),
        "solver_time_s": None if solver_time_s is None else round(solver_time_s, 6),
        "preprocessing_time_s": None if preprocessing_time_s is None else round(preprocessing_time_s, 6),
        "total_wall_time_s": None if total_wall_time_s is None else round(total_wall_time_s, 6),
        "peak_rss_mb": None if peak_rss_mb is None else round(peak_rss_mb, 2),
        "SAT_calls": sat_calls,
        "CNF_variables": cnf_vars,
        "CNF_clauses": cnf_clauses,
        "heuristic_moves": heuristic_moves,
        "blocker_reason": blocker_reason,
        "notes": notes,
    }


def _evaluate_sat_preflight_113(
    *,
    dataset_rows: list[dict[str, Any]],
    graphs_by_view: dict[str, Graph],
    meta_by_view: dict[str, dict[str, Any]],
    rcm_bw_by_view: dict[str, int],
    sat_limits: ResourceLimits,
    output_dir: Path,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Build complete 113 x 2 x 6 x 3 x 2 SAT preflight matrix and minimal recommended config per instance."""

    pf_rows: list[dict[str, Any]] = []
    best_config_by_inst: dict[str, dict[str, Any]] = {}

    backends = ("cadical", "glucose", "minisat")
    main_encs = ("pairwise", "order")
    amos = ("pairwise", "sequential", "binary", "commander", "product", "ladder")
    strategies = ("repeated", "incremental")

    for ds in dataset_rows:
        inst = str(ds["instance"])
        vid = f"{inst}__primary"
        graph = graphs_by_view[vid]
        meta = meta_by_view[vid]
        rcm_bw = rcm_bw_by_view[vid]
        lb = int(meta["certified_lb"])
        eval_k = max(lb, rcm_bw - 1) if graph.edges else 0

        # Precompute formula estimates for each (enc, amo, strat) so we avoid repeating identical math across 3 backends
        formula_cache: dict[tuple[str, str, str], dict[str, Any]] = {}
        min_pair: tuple[int, int, str, str] | None = None
        for enc in main_encs:
            for amo in amos:
                est_rep = estimate_cnf_size(graph, encoding=enc, amo=amo, k=eval_k, symmetry_breaking=True)
                ok_rep, reason_rep = sat_limits.check(est_rep)
                # For incremental: single step lower-bound check matches solver.py resource guard on first step
                # plus cumulative worst-case note
                est_inc_step = estimate_incremental_cnf_size(
                    graph, encoding=enc, amo=amo, initial_k=eval_k, target_k=eval_k, symmetry_breaking=True
                )
                ok_inc, reason_inc = sat_limits.check(est_inc_step)

                for strat, est_obj, is_ok, rsn in (
                    ("repeated", est_rep, ok_rep, reason_rep),
                    ("incremental", est_inc_step, ok_inc, reason_inc),
                ):
                    est_ram = _estimate_ram_mb(est_obj.num_variables, est_obj.num_clauses)
                    elig = "ELIGIBLE" if (is_ok and est_ram <= float(sat_limits.memory_limit_mb or 4096.0)) else "RESOURCE_LIMIT"
                    if is_ok and elig == "RESOURCE_LIMIT":
                        rsn = f"Estimated SAT solver RAM ({est_ram:.1f} MB) exceeds safety limit"
                    formula_cache[(enc, amo, strat)] = {
                        "eval_k": eval_k,
                        "est_vars": est_obj.num_variables,
                        "est_clauses": est_obj.num_clauses,
                        "est_ram_mb": est_ram,
                        "elig": elig,
                        "reason": rsn or "Within ResourceLimits",
                        "min_var_cap": max(int(sat_limits.max_variables or 0), est_obj.num_variables),
                        "min_clause_cap": max(int(sat_limits.max_clauses or 0), est_obj.num_clauses),
                    }
                    if enc == "order" and strat == "incremental":
                        cand_key = (est_obj.num_clauses, est_obj.num_variables, enc, amo)
                        if min_pair is None or cand_key < min_pair:
                            min_pair = cand_key

        rec_amo = min_pair[3] if min_pair is not None else "product"
        best_config_by_inst[inst] = {
            "view_id": vid,
            "recommended_encoding": "order",
            "recommended_amo": rec_amo,
            "recommended_strategy": "incremental",
            "recommended_backend": "cadical",
            **formula_cache[("order", "product", "incremental")],
        }

        for enc in main_encs:
            for amo in amos:
                for strat in strategies:
                    finfo = formula_cache[(enc, amo, strat)]
                    for back in backends:
                        pf_rows.append({
                            "instance": inst,
                            "table": meta["table"],
                            "tier": ds["tier"],
                            "official_benchmark": meta["official_benchmark"],
                            "conversion_policy": meta["conversion_policy"],
                            "n": meta["n"],
                            "m": meta["m"],
                            "eval_k": finfo["eval_k"],
                            "main_encoding": enc,
                            "amo_encoding": amo,
                            "backend": back,
                            "strategy": strat,
                            "symmetry_breaking": True,
                            "estimated_vars": finfo["est_vars"],
                            "estimated_clauses": finfo["est_clauses"],
                            "estimated_ram_mb": finfo["est_ram_mb"],
                            "eligibility": finfo["elig"],
                            "recommended_minimal": (enc == "order" and amo == rec_amo and strat == "incremental" and back == "cadical"),
                            "min_required_var_cap": finfo["min_var_cap"],
                            "min_required_clause_cap": finfo["min_clause_cap"],
                            "blocker_reason": "" if finfo["elig"] == "ELIGIBLE" else finfo["reason"],
                        })

    if pf_rows:
        _write_csv_atomic(output_dir / "sat_preflight_113.csv", list(pf_rows[0].keys()), pf_rows)
    return pf_rows, best_config_by_inst


def _build_mip_cp_license_table(
    *,
    dataset_rows: list[dict[str, Any]],
    meta_by_view: dict[str, dict[str, Any]],
    env_info: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    solvers = env_info.get("solvers", {})
    for ds in dataset_rows:
        inst = str(ds["instance"])
        vid = f"{inst}__primary"
        meta = meta_by_view[vid]
        n = int(meta["n"])
        m = int(meta["m"])
        mip_vars = n * n + 1
        mip_constrs = 2 * n + 2 * m + (1 if n >= 2 else 0)
        cpo_bits = round(n * math.log2(n), 2) if n >= 2 else 0.0

        for meth in ("gurobi", "cplex", "cp-optimizer"):
            sinfo = solvers.get(meth, {})
            avail = bool(sinfo.get("available"))
            lic_cls = str(sinfo.get("license_type", "UNKNOWN"))
            if meth in ("gurobi", "cplex"):
                raw_v = sinfo.get("max_variables")
                raw_c = sinfo.get("max_constraints")
                cap_v = int(raw_v) if raw_v is not None else 10**9
                cap_c = int(raw_c) if raw_c is not None else 10**9
                elig = avail and (mip_vars <= cap_v) and (mip_constrs <= cap_c)
                if not avail:
                    reason = str(sinfo.get("note", "Unavailable"))
                    req_lic = f"{meth.upper()} Full Commercial/Academic License"
                elif not elig:
                    reason = f"EXTERNAL_LICENSE_BLOCKER: {meth} {lic_cls} cap ({cap_v} vars / {cap_c} constrs) exceeded ({mip_vars}/{mip_constrs})"
                    req_lic = f"{meth.upper()} Academic/Full License (need >= {mip_vars} vars, {mip_constrs} constrs)"
                else:
                    reason = f"Eligible under {lic_cls} ({mip_vars}/{mip_constrs} <= {cap_v}/{cap_c})"
                    req_lic = lic_cls
                est_v, est_c = mip_vars, mip_constrs
            else:
                raw_bits = sinfo.get("max_log2_search_space")
                max_bits = float(raw_bits) if raw_bits is not None else 1e9
                elig = avail and (cpo_bits <= max_bits)
                if not avail:
                    reason = str(sinfo.get("note", "Unavailable"))
                    req_lic = "IBM ILOG CPLEX Optimization Studio Academic/Commercial"
                elif not elig:
                    reason = f"EXTERNAL_LICENSE_BLOCKER: IBM CPO CE 2^{int(max_bits)} search-space limit exceeded (~2^{cpo_bits:.1f} bits for n={n})"
                    req_lic = f"IBM ILOG CP Optimizer Academic/Commercial Edition (>2^{cpo_bits:.0f})"
                else:
                    reason = f"Eligible under {lic_cls} (~2^{cpo_bits:.1f} <= 2^{int(max_bits)})"
                    req_lic = lic_cls

                est_v, est_c = n + 1, m + 2

            rows.append({
                "instance": inst,
                "table": meta["table"],
                "tier": ds["tier"],
                "official_benchmark": meta["official_benchmark"],
                "conversion_policy": meta["conversion_policy"],
                "n": n,
                "m": m,
                "solver": meth,
                "solver_version": sinfo.get("version"),
                "license_class": lic_cls,
                "estimated_vars": est_v,
                "estimated_constrs": est_c,
                "cpo_log2_search_space": cpo_bits if meth == "cp-optimizer" else None,
                "eligibility": "ELIGIBLE" if elig else "BLOCKED_LICENSE",
                "blocker_reason": "" if elig else reason,
                "required_license": req_lic,
            })
    return rows


def run_m3_8_full113(
    *,
    config_path: Path = Path("configs/member3_m3_8.toml"),
    stages: set[str] | None = None,
    resume: bool = True,
    max_batch_seconds: float | None = None,
    max_runs_in_batch: int | None = None,
    generate_plots: bool = True,
) -> dict[str, Any]:
    """Execute full 113-instance M3.8 pipeline cleanly with checkpoints and resume."""

    root = Path.cwd()
    cfg = tomllib.loads(config_path.read_text(encoding="utf-8"))["benchmark"]
    provenance_path = (root / cfg["provenance"]).resolve()
    raw_dir = (root / cfg["raw_dir"]).resolve()
    legacy_csv = (root / cfg["legacy_results_csv"]).resolve()
    output_dir = (root / cfg["output_dir"]).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    # Pre-import OR-Tools & PySAT once so in-process CP-SAT avoids cold-import penalty
    try:
        from ortools.sat.python import cp_model as _  # noqa: F401
    except Exception:
        pass

    env_info = audit_environment()
    dataset_rows, view_rows, graphs_by_view, meta_by_view = build_m3_8_dataset_and_views(
        root=root,
        provenance_path=provenance_path,
        raw_dir=raw_dir,
        output_dir=output_dir,
    )

    # Load checkpointed runs if resuming
    checkpoint_path = output_dir / "checkpoint_runs.json"
    runs_by_id: dict[str, dict[str, Any]] = {}
    if resume and checkpoint_path.exists():
        loaded_runs = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        for r in loaded_runs:
            runs_by_id[str(r["run_id"])] = r

    # Precompute RCM & DRSA-Warm caches from existing/freshly executed runs so CP-SAT/SAT can warm-start cleanly
    rcm_cache: dict[str, tuple[dict[int, int], int]] = {}
    drsa_cache: dict[str, tuple[dict[int, int], int]] = {}
    # Seed warm-start cache deterministically using RCMSolver / DRSASolver when needed
    def get_rcm_warm(vid: str) -> tuple[dict[int, int], int]:
        if vid not in rcm_cache:
            res = RCMSolver().solve(graphs_by_view[vid])
            rcm_cache[vid] = (dict(res.permutation or {}), int(res.bandwidth or 0))
        return rcm_cache[vid]

    def get_drsa_warm(vid: str) -> tuple[dict[int, int], int]:
        if vid not in drsa_cache:
            # Prefer cached checkpoint permutation? Keep deterministic computation if not cached
            res = DRSASolver(
                seed=int(cfg["primary_seed"]),
                initial_mode="rcm",
                initial_temperature=2.0,
                cooling=0.99,
                final_temperature=1e-7,
                initial_chain_length=40,
                variant="MODIFIED_VARIANT",
            ).solve(graphs_by_view[vid], timeout_seconds=float(cfg["drsa_timeout_seconds"]))
            drsa_cache[vid] = (dict(res.permutation or {}), int(res.bandwidth or 0))
        return drsa_cache[vid]

    # Build deterministic RCM baseline across 113 quickly (< 3s) for SAT preflight k = rcm_bw - 1
    rcm_bw_by_view: dict[str, int] = {}
    for ds in dataset_rows:
        vid = f"{ds['instance']}__primary"
        _, bw = get_rcm_warm(vid)
        rcm_bw_by_view[vid] = bw

    sat_limits = ResourceLimits(
        max_variables=int(cfg["max_sat_variables"]),
        max_clauses=int(cfg["max_sat_clauses"]),
        memory_limit_mb=float(cfg["memory_limit_mb"]),
    )
    pf_rows, best_sat_cfg = _evaluate_sat_preflight_113(
        dataset_rows=dataset_rows,
        graphs_by_view=graphs_by_view,
        meta_by_view=meta_by_view,
        rcm_bw_by_view=rcm_bw_by_view,
        sat_limits=sat_limits,
        output_dir=output_dir,
    )
    lic_rows = _build_mip_cp_license_table(
        dataset_rows=dataset_rows,
        meta_by_view=meta_by_view,
        env_info=env_info,
    )

    seed = int(cfg["primary_seed"])
    threads = int(cfg["threads"])
    batch_limit = float(cfg["max_batch_seconds"] if max_batch_seconds is None else max_batch_seconds)
    batch_start = monotonic()

    # Build deterministic ordered execution specs across Stages
    specs: list[dict[str, Any]] = []
    # Stage 1: RCM 113 + Sensitivity views
    for vr in view_rows:
        specs.append({
            "stage": "RCM_113",
            "view_id": vr["view_id"],
            "family": "Heuristic",
            "method": "rcm",
            "seed": None,
            "time_limit_seconds": None,
        })
    # Stage 2: SA 113 + Sensitivity + Legacy 72 compatibility check (iters=2000, nonzero_union)
    for vr in view_rows:
        tlim = float(cfg["sa_timeout_seconds"] if vr["is_primary_113"] else cfg["sensitivity_heuristic_timeout_seconds"])
        specs.append({
            "stage": "SA_113",
            "view_id": vr["view_id"],
            "family": "Heuristic",
            "method": "sa",
            "sa_iterations": int(cfg["sa_max_iterations"]),
            "seed": seed,
            "time_limit_seconds": tlim,
        })
    with legacy_csv.open(encoding="utf-8", newline="") as f:
        legacy_72_names = sorted({str(r["instance"]) for r in csv.DictReader(f)})
    for inst in legacy_72_names:
        vid_compat = f"{inst}__nonzero_sens" if f"{inst}__nonzero_sens" in graphs_by_view else f"{inst}__primary"
        if vid_compat not in graphs_by_view:
            continue
        specs.append({
            "stage": "SA_LEGACY72_COMPAT",
            "view_id": vid_compat,
            "family": "Heuristic",
            "method": "sa_legacy_2000",
            "sa_iterations": int(cfg["sa_legacy_iterations"]),
            "seed": seed,
            "time_limit_seconds": None,
        })

    # Stage 3: DRSA 113 (PAPER_FAITHFUL_BOUNDED + WARM MODIFIED_VARIANT on all 113, + WARM on sensitivity)
    for vr in view_rows:
        vid = vr["view_id"]
        tlim = float(cfg["drsa_timeout_seconds"] if vr["is_primary_113"] else cfg["sensitivity_heuristic_timeout_seconds"])
        specs.append({
            "stage": "DRSA_113",
            "view_id": vid,
            "family": "Heuristic",
            "method": "drsa_modified_variant",
            "drsa_variant": "MODIFIED_VARIANT",
            "seed": seed,
            "time_limit_seconds": tlim,
        })
        if vr["is_primary_113"]:
            specs.append({
                "stage": "DRSA_113",
                "view_id": vid,
                "family": "Heuristic",
                "method": "drsa_paper_faithful",
                "drsa_variant": "PAPER_FAITHFUL",
                "seed": seed,
                "time_limit_seconds": tlim,
            })

    # Priority 5: CP-SAT Pass 1 (all 113)
    for ds in dataset_rows:
        vid = f"{ds['instance']}__primary"
        specs.append({
            "stage": "CPSAT_113_PASS1",
            "view_id": vid,
            "family": "CP",
            "method": "cp-sat",
            "warm_start_mode": "DRSA_WARM",
            "seed": seed,
            "time_limit_seconds": float(cfg["cpsat_short_timeout_seconds"]),
        })

    # Priority 6: SAT 113 compact Order+Product+Incremental+CaDiCaL across all 113
    for ds in dataset_rows:
        inst = str(ds["instance"])
        vid = f"{inst}__primary"
        specs.append({
            "stage": "SAT_113_COMPACT",
            "view_id": vid,
            "family": "SAT",
            "method": "cadical",
            "backend": "cadical",
            "main_encoding": "order",
            "amo_encoding": "product",
            "strategy": "incremental",
            "warm_start_mode": "DRSA_WARM",
            "seed": seed,
            "time_limit_seconds": float(cfg["sat_timeout_seconds"]),
        })

    # Priority 7: MIP (Gurobi, CPLEX) & IBM CP Optimizer across 113 (live on ELIGIBLE, BLOCKED_LICENSE otherwise)
    lic_by_pair = {(r["instance"], r["solver"]): r for r in lic_rows}
    for ds in dataset_rows:
        inst = str(ds["instance"])
        vid = f"{inst}__primary"
        for solver_name in ("gurobi", "cplex", "cp-optimizer"):
            tlim = float(cfg["cpo_timeout_seconds"] if solver_name == "cp-optimizer" else cfg["mip_timeout_seconds"])
            specs.append({
                "stage": "MIP_CPO_113",
                "view_id": vid,
                "family": "CP" if solver_name == "cp-optimizer" else "MIP",
                "method": solver_name,
                "warm_start_mode": "DRSA_WARM" if solver_name != "cp-optimizer" else "RCM_WARM",
                "seed": seed,
                "time_limit_seconds": tlim,
            })

    # Priority 8 (Extended): CP-SAT Longer Proof Pass 3 & SAT Multi-AMO/Backend/Strategy Studies
    for inst in cfg["cpsat_proof_candidates"]:
        vid = f"{inst}__primary"
        if vid in graphs_by_view:
            specs.append({
                "stage": "CPSAT_PROOF_PASS3",
                "view_id": vid,
                "family": "CP",
                "method": "cp-sat",
                "warm_start_mode": "DRSA_WARM",
                "seed": seed,
                "time_limit_seconds": float(cfg["cpsat_proof_timeout_seconds"]),
            })

    for inst in cfg["sat_study_instances"]:
        vid = f"{inst}__primary"
        if vid not in graphs_by_view:
            continue
        study_combos = [
            ("glucose", "order", "product", "incremental"),
            ("minisat", "order", "product", "incremental"),
            ("cadical", "order", "sequential", "incremental"),
            ("cadical", "order", "binary", "incremental"),
            ("cadical", "order", "commander", "incremental"),
            ("cadical", "order", "ladder", "incremental"),
            ("cadical", "order", "pairwise", "incremental"),
            ("cadical", "pairwise", "product", "incremental"),
            ("cadical", "order", "product", "repeated"),
        ]
        for bck, menc, amo, strat in study_combos:
            specs.append({
                "stage": "SAT_STUDY_SMALL",
                "view_id": vid,
                "family": "SAT",
                "method": bck,
                "backend": bck,
                "main_encoding": menc,
                "amo_encoding": amo,
                "strategy": strat,
                "warm_start_mode": "RCM_WARM",
                "seed": seed,
                "time_limit_seconds": float(cfg["sat_timeout_seconds"]),
            })

    def _spec_run_id(sp: dict[str, Any]) -> str:
        return _stable_id({k: sp.get(k) for k in ("stage", "view_id", "method", "backend", "main_encoding", "amo_encoding", "strategy", "drsa_variant", "warm_start_mode", "seed", "time_limit_seconds")})

    for sp in specs:
        sp["run_id"] = _spec_run_id(sp)

    def _execute_spec(sp: dict[str, Any]) -> dict[str, Any]:
        rid = sp["run_id"]
        vid = sp["view_id"]
        meta = meta_by_view[vid]
        graph = graphs_by_view[vid]
        stage = sp["stage"]
        family = sp["family"]
        method = sp["method"]
        tlim = sp.get("time_limit_seconds")

        if family == "Heuristic":
            prep_s = 0.0
            t0 = monotonic()
            if method == "rcm":
                res = RCMSolver().solve(graph)
                rcm_cache[vid] = (dict(res.permutation or {}), int(res.bandwidth or 0))
            elif method in ("sa", "sa_legacy_2000"):
                res = SimulatedAnnealingSolver(
                    iterations=int(sp["sa_iterations"]),
                    initial_temperature=2.0,
                    cooling=0.995 if method == "sa_legacy_2000" else 0.9999,
                    minimum_temperature=1e-12,
                    seed=int(sp["seed"]),
                    initial_mode="rcm",
                ).solve(graph, timeout_seconds=tlim)
            elif sp.get("drsa_variant") == "PAPER_FAITHFUL":
                res = DRSASolver(
                    seed=int(sp["seed"]),
                    initial_mode="random",
                    initial_temperature=1000.0,
                    cooling=0.99,
                    final_temperature=1e-7,
                    initial_chain_length=40,
                    variant="PAPER_FAITHFUL",
                ).solve(graph, timeout_seconds=tlim)
            else:
                res = DRSASolver(
                    seed=int(sp["seed"]),
                    initial_mode="rcm",
                    initial_temperature=2.0,
                    cooling=0.99,
                    final_temperature=1e-7,
                    initial_chain_length=40,
                    variant="MODIFIED_VARIANT",
                ).solve(graph, timeout_seconds=tlim)
                if sp.get("time_limit_seconds") == float(cfg["drsa_timeout_seconds"]):
                    drsa_cache[vid] = (dict(res.permutation or {}), int(res.bandwidth or 0))
            wall_s = monotonic() - t0
            md = dict(res.metadata or {})
            val_rep = validate_solution(graph, res.permutation, claimed_bandwidth=res.bandwidth) if res.permutation else None
            val_ok = bool(val_rep is not None and val_rep.valid)
            bw = val_rep.actual_bandwidth if val_ok else None
            cov_status = _map_result_to_m3_8_status(res, validation_passed=val_ok, has_incumbent=bw is not None)
            moves = md.get("evaluations", md.get("iterations_completed"))
            return _make_run_record(
                run_id=rid, stage=stage, meta=meta, family=family, method=method,
                backend=method, main_encoding=None, amo_encoding=None, strategy=None,
                symmetry_breaking=False,
                warm_start_mode="NONE" if method == "rcm" else ("RANDOM_INIT" if sp.get("drsa_variant") == "PAPER_FAITHFUL" else "RCM_INIT"),
                warm_start_source=md.get("initial_mode"),
                warm_start_bw=md.get("initial_bandwidth"),
                seed=sp.get("seed"), threads=threads, time_limit_seconds=tlim,
                solver_attempted=True,
                raw_status=res.status.value, m3_8_status=cov_status,
                bandwidth=bw, lower_bound=res.lower_bound, upper_bound=res.upper_bound,
                best_bound=float(res.lower_bound) if res.lower_bound is not None else None,
                validation_passed=val_ok,
                model_construction_time_s=0.0, solver_time_s=res.runtime_seconds,
                preprocessing_time_s=prep_s, total_wall_time_s=wall_s,
                peak_rss_mb=_process_peak_rss_mb(),
                sat_calls=None, cnf_vars=None, cnf_clauses=None,
                heuristic_moves=int(moves) if moves is not None else None,
                blocker_reason=None,
                notes=str(md.get("execution_regime", md.get("stop_reason", ""))),
            )

        # Warm-start lookup for Exact/SAT solvers
        t_prep0 = monotonic()
        warm_mode = str(sp.get("warm_start_mode", "RCM_WARM"))
        if warm_mode == "DRSA_WARM":
            warm_perm, warm_bw = get_drsa_warm(vid)
            w_src = "DRSA_MODIFIED_VARIANT"
        else:
            warm_perm, warm_bw = get_rcm_warm(vid)
            w_src = "RCM"
        prep_s = monotonic() - t_prep0

        if method == "cp-sat":
            t0 = monotonic()
            res = CPSATSolver(seed=int(sp["seed"])).solve(
                graph,
                timeout_seconds=float(tlim),
                symmetry_breaking=True,
                threads=threads,
                initial_permutation=warm_perm,
                isolate_timeout=False,
            )
            wall_s = monotonic() - t0 + prep_s
            md = dict(res.metadata or {})
            val_rep = validate_solution(graph, res.permutation, claimed_bandwidth=res.bandwidth) if res.permutation else None
            val_ok = bool(val_rep is not None and val_rep.valid) if res.permutation else None
            bw = val_rep.actual_bandwidth if (val_ok and val_rep is not None) else None
            cov_status = _map_result_to_m3_8_status(res, validation_passed=val_ok, has_incumbent=bw is not None)
            best_bnd = md.get("native_best_bound", res.lower_bound)
            return _make_run_record(
                run_id=rid, stage=stage, meta=meta, family="CP", method="cp-sat",
                backend="cp-sat", main_encoding="alldiff_cp", amo_encoding=None, strategy="cp_search",
                symmetry_breaking=True,
                warm_start_mode=warm_mode, warm_start_source=w_src, warm_start_bw=warm_bw,
                seed=sp.get("seed"), threads=threads, time_limit_seconds=tlim,
                solver_attempted=True,
                raw_status=res.status.value, m3_8_status=cov_status,
                bandwidth=bw, lower_bound=res.lower_bound, upper_bound=res.upper_bound,
                best_bound=float(best_bnd) if best_bnd is not None and math.isfinite(float(best_bnd)) else None,
                validation_passed=val_ok,
                model_construction_time_s=float(md.get("model_construction_time_s", res.encoding_time_s or 0.0)),
                solver_time_s=float(md.get("solver_time_s", res.solving_time_s or 0.0)),
                preprocessing_time_s=prep_s, total_wall_time_s=wall_s,
                peak_rss_mb=_process_peak_rss_mb(),
                sat_calls=None, cnf_vars=md.get("model_variables", res.num_variables),
                cnf_clauses=md.get("model_constraints", res.num_clauses), heuristic_moves=None,
                blocker_reason=str(md.get("reason")) if md.get("reason") else None,
                notes=f"native_status={md.get('native_status')}",
            )

        if family == "SAT":
            menc = str(sp["main_encoding"])
            amo = str(sp["amo_encoding"])
            strat = str(sp["strategy"])
            bck = str(sp["backend"])
            eval_k = max(int(meta["certified_lb"]), int(warm_bw) - 1) if graph.edges else 0
            est_single = estimate_cnf_size(graph, encoding=menc, amo=amo, k=eval_k, symmetry_breaking=True)
            is_ok, reason = sat_limits.check(est_single)
            est_ram = _estimate_ram_mb(est_single.num_variables, est_single.num_clauses)
            if is_ok and est_ram > float(cfg["memory_limit_mb"]):
                is_ok = False
                reason = f"Estimated SAT solver RAM ({est_ram:.1f} MB) exceeds safety limit"
            if not is_ok:
                return _make_run_record(
                    run_id=rid, stage=stage, meta=meta, family="SAT", method=bck,
                    backend=bck, main_encoding=menc, amo_encoding=amo, strategy=strat,
                    symmetry_breaking=True, warm_start_mode=warm_mode, warm_start_source=w_src, warm_start_bw=warm_bw,
                    seed=sp.get("seed"), threads=threads, time_limit_seconds=tlim,
                    solver_attempted=False,
                    raw_status="SKIPPED", m3_8_status="RESOURCE_LIMIT",
                    bandwidth=None, lower_bound=meta["certified_lb"], upper_bound=None,
                    best_bound=float(meta["certified_lb"]), validation_passed=None,
                    model_construction_time_s=None, solver_time_s=None, preprocessing_time_s=prep_s,
                    total_wall_time_s=None, peak_rss_mb=None, sat_calls=0,
                    cnf_vars=est_single.num_variables, cnf_clauses=est_single.num_clauses, heuristic_moves=None,
                    blocker_reason=f"{reason} (est_ram={est_ram:.1f} MB)",
                    notes="Blocked safely before CNF allocation by ResourceLimits",
                )

            encoder = PairwiseEncoding(amo=amo) if menc == "pairwise" else OrderEncoding(amo=amo)
            engine = RepeatedSATSolver(encoder, backend_name=bck) if strat == "repeated" else IncrementalSATSolver(encoder, backend_name=bck)
            t0 = monotonic()
            res = engine.solve(
                graph,
                timeout_seconds=float(tlim),
                heuristic_permutation=warm_perm,
                symmetry_breaking=True,
                limits=sat_limits,
            )
            wall_s = monotonic() - t0 + prep_s
            md = dict(res.metadata or {})
            if res.status is SolutionStatus.SKIPPED:
                return _make_run_record(
                    run_id=rid, stage=stage, meta=meta, family="SAT", method=bck,
                    backend=bck, main_encoding=menc, amo_encoding=amo, strategy=strat,
                    symmetry_breaking=True, warm_start_mode=warm_mode, warm_start_source=w_src, warm_start_bw=warm_bw,
                    seed=sp.get("seed"), threads=threads, time_limit_seconds=tlim,
                    solver_attempted=False,
                    raw_status="SKIPPED", m3_8_status="RESOURCE_LIMIT",
                    bandwidth=None, lower_bound=res.lower_bound, upper_bound=None,
                    best_bound=float(res.lower_bound) if res.lower_bound is not None else None,
                    validation_passed=None,
                    model_construction_time_s=res.encoding_time_s, solver_time_s=res.solving_time_s,
                    preprocessing_time_s=prep_s, total_wall_time_s=wall_s,
                    peak_rss_mb=md.get("sampled_peak_memory_mb") or _process_peak_rss_mb(),
                    sat_calls=res.sat_calls,
                    cnf_vars=res.num_variables or est_single.num_variables,
                    cnf_clauses=res.num_clauses or est_single.num_clauses,
                    heuristic_moves=None, blocker_reason=str(md.get("skipped_reason")),
                )

            val_rep = validate_solution(graph, res.permutation, claimed_bandwidth=res.bandwidth) if res.permutation else None
            val_ok = bool(val_rep is not None and val_rep.valid) if res.permutation else None
            bw = val_rep.actual_bandwidth if (val_ok and val_rep is not None) else None
            cov_status = _map_result_to_m3_8_status(res, validation_passed=val_ok, has_incumbent=bw is not None)
            return _make_run_record(
                run_id=rid, stage=stage, meta=meta, family="SAT", method=bck,
                backend=bck, main_encoding=menc, amo_encoding=amo, strategy=strat,
                symmetry_breaking=True, warm_start_mode=warm_mode, warm_start_source=w_src, warm_start_bw=warm_bw,
                seed=sp.get("seed"), threads=threads, time_limit_seconds=tlim,
                solver_attempted=True,
                raw_status=res.status.value, m3_8_status=cov_status,
                bandwidth=bw, lower_bound=res.lower_bound, upper_bound=res.upper_bound,
                best_bound=float(res.lower_bound) if res.lower_bound is not None else None,
                validation_passed=val_ok,
                model_construction_time_s=res.encoding_time_s, solver_time_s=res.solving_time_s,
                preprocessing_time_s=prep_s, total_wall_time_s=wall_s,
                peak_rss_mb=md.get("sampled_peak_memory_mb") or _process_peak_rss_mb(),
                sat_calls=res.sat_calls,
                cnf_vars=res.num_variables or est_single.num_variables,
                cnf_clauses=res.num_clauses or est_single.num_clauses,
                heuristic_moves=None,
                blocker_reason=str(md.get("worker_reason")) if md.get("worker_reason") else None,
                notes=f"incumbent_source={md.get('incumbent_source', '')}",
            )

        # MIP (Gurobi, CPLEX) & IBM CP Optimizer
        linfo = lic_by_pair[(meta["instance"], method)]
        if linfo["eligibility"] != "ELIGIBLE":
            return _make_run_record(
                run_id=rid, stage=stage, meta=meta, family=family, method=method,
                backend=method,
                main_encoding="alldiff_cp" if method == "cp-optimizer" else "assignment_mip",
                amo_encoding=None,
                strategy="cp_search" if method == "cp-optimizer" else "branch_and_bound",
                symmetry_breaking=True, warm_start_mode=warm_mode, warm_start_source=w_src, warm_start_bw=warm_bw,
                seed=sp.get("seed"), threads=threads, time_limit_seconds=tlim,
                solver_attempted=False,
                raw_status="UNAVAILABLE", m3_8_status="BLOCKED_LICENSE",
                bandwidth=None, lower_bound=meta["certified_lb"], upper_bound=None,
                best_bound=float(meta["certified_lb"]), validation_passed=None,
                model_construction_time_s=None, solver_time_s=None, preprocessing_time_s=None,
                total_wall_time_s=None, peak_rss_mb=None,
                sat_calls=None, cnf_vars=linfo["estimated_vars"], cnf_clauses=linfo["estimated_constrs"],
                heuristic_moves=None, blocker_reason=str(linfo["blocker_reason"]),
                notes=str(linfo["required_license"]),
            )

        t0 = monotonic()
        if method == "gurobi":
            res = GurobiMIPSolver().solve(graph, timeout_seconds=float(tlim), symmetry_breaking=True, threads=threads, initial_permutation=warm_perm)
        elif method == "cplex":
            res = CPLEXMIPSolver().solve(graph, timeout_seconds=float(tlim), symmetry_breaking=True, threads=threads, initial_permutation=warm_perm)
        else:
            res = CPOptimizerSolver().solve(graph, timeout_seconds=float(tlim), symmetry_breaking=True, threads=threads, initial_permutation=warm_perm)
        wall_s = monotonic() - t0 + prep_s
        md = dict(res.metadata or {})
        val_rep = validate_solution(graph, res.permutation, claimed_bandwidth=res.bandwidth) if res.permutation else None
        val_ok = bool(val_rep is not None and val_rep.valid) if res.permutation else None
        bw = val_rep.actual_bandwidth if (val_ok and val_rep is not None) else None
        cov_status = _map_result_to_m3_8_status(res, validation_passed=val_ok, has_incumbent=bw is not None)
        best_bnd = md.get("best_bound", md.get("native_best_bound", res.lower_bound))
        return _make_run_record(
            run_id=rid, stage=stage, meta=meta, family=family, method=method,
            backend=method,
            main_encoding="alldiff_cp" if method == "cp-optimizer" else "assignment_mip",
            amo_encoding=None,
            strategy="cp_search" if method == "cp-optimizer" else "branch_and_bound",
            symmetry_breaking=True, warm_start_mode=warm_mode, warm_start_source=w_src, warm_start_bw=warm_bw,
            seed=sp.get("seed"), threads=threads, time_limit_seconds=tlim,
            solver_attempted=True,
            raw_status=res.status.value, m3_8_status=cov_status,
            bandwidth=bw, lower_bound=res.lower_bound, upper_bound=res.upper_bound,
            best_bound=float(best_bnd) if best_bnd is not None and math.isfinite(float(best_bnd)) else None,
            validation_passed=val_ok,
            model_construction_time_s=md.get("model_construction_time_s", res.encoding_time_s),
            solver_time_s=float(md.get("solver_time_s", res.solving_time_s or res.runtime_seconds)),
            preprocessing_time_s=prep_s, total_wall_time_s=wall_s,
            peak_rss_mb=md.get("engine_peak_memory_mb") if method == "cp-optimizer" else _process_peak_rss_mb(),
            sat_calls=None, cnf_vars=linfo["estimated_vars"], cnf_clauses=linfo["estimated_constrs"],
            heuristic_moves=None, blocker_reason=str(md.get("reason")) if md.get("reason") else None,
            notes=str(md.get("cplex_status_string") or md.get("native_status") or md.get("gurobi_status") or ""),
        )

    # Filter specs by stages if given
    active_specs = [sp for sp in specs if stages is None or sp["stage"] in stages]
    executed_this_batch = 0
    interrupted = False
    for idx, sp in enumerate(active_specs, start=1):
        rid = sp["run_id"]
        if rid in runs_by_id:
            continue
        if max_runs_in_batch is not None and executed_this_batch >= max_runs_in_batch:
            interrupted = True
            break
        if (monotonic() - batch_start) >= batch_limit:
            interrupted = True
            break
        rec = _execute_spec(sp)
        runs_by_id[rid] = rec
        executed_this_batch += 1
        if executed_this_batch % 15 == 0 or rec["family"] != "Heuristic":
            _write_json_atomic(checkpoint_path, list(runs_by_id.values()))
            print(f"[M3.8 batch] +{executed_this_batch} | {sp['stage']} | {sp['view_id']} | {sp['method']} -> {rec['m3_8_coverage_status']} bw={rec['bandwidth']}", flush=True)

    # Dynamic CP-SAT Pass 2 recovery for Pass 1 TIMEOUT_NO_INCUMBENT (up to max_n)
    pass1_rows = [r for r in runs_by_id.values() if r["stage"] == "CPSAT_113_PASS1"]
    pass2_specs: list[dict[str, Any]] = []
    if stages is None or "CPSAT_RECOVERY_PASS2" in stages:
        for pr in sorted(pass1_rows, key=lambda x: (int(x["n"]), str(x["instance"]))):
            if pr["m3_8_coverage_status"] == "TIMEOUT_NO_INCUMBENT" and int(pr["n"]) <= int(cfg["cpsat_extended_max_n"]):
                sp2 = {
                    "stage": "CPSAT_RECOVERY_PASS2",
                    "view_id": pr["view_id"],
                    "family": "CP",
                    "method": "cp-sat",
                    "warm_start_mode": "DRSA_WARM",
                    "seed": seed,
                    "time_limit_seconds": float(cfg["cpsat_extended_timeout_seconds"]),
                }
                sp2["run_id"] = _spec_run_id(sp2)
                pass2_specs.append(sp2)
        for sp2 in pass2_specs:
            if sp2["run_id"] in runs_by_id:
                continue
            if max_runs_in_batch is not None and executed_this_batch >= max_runs_in_batch:
                interrupted = True
                break
            if (monotonic() - batch_start) >= batch_limit:
                interrupted = True
                break
            rec = _execute_spec(sp2)
            runs_by_id[sp2["run_id"]] = rec
            executed_this_batch += 1
            _write_json_atomic(checkpoint_path, list(runs_by_id.values()))
            print(f"[M3.8 Pass2] +{executed_this_batch} | {sp2['view_id']} -> {rec['m3_8_coverage_status']} bw={rec['bandwidth']}", flush=True)

    all_runs = list(runs_by_id.values())
    _write_json_atomic(checkpoint_path, all_runs)

    # Export per-method required CSVs & summaries cleanly
    summary = export_m3_8_reports_and_summaries(
        dataset_rows=dataset_rows,
        view_rows=view_rows,
        all_runs=all_runs,
        pf_rows=pf_rows,
        lic_rows=lic_rows,
        legacy_csv=legacy_csv,
        output_dir=output_dir,
        planned_static_count=len(active_specs),
        planned_dynamic_pass2=len(pass2_specs),
        executed_this_batch=executed_this_batch,
        interrupted=interrupted,
    )

    if generate_plots:
        from bmp.experiments.member3_m3_8_plots import create_m3_8_plots
        create_m3_8_plots(output_dir)

    return summary


def export_m3_8_reports_and_summaries(
    *,
    dataset_rows: list[dict[str, Any]],
    view_rows: list[dict[str, Any]],
    all_runs: list[dict[str, Any]],
    pf_rows: list[dict[str, Any]],
    lic_rows: list[dict[str, Any]],
    legacy_csv: Path,
    output_dir: Path,
    planned_static_count: int = 0,
    planned_dynamic_pass2: int = 0,
    executed_this_batch: int = 0,
    interrupted: bool = False,
) -> dict[str, Any]:
    """Export all Task K required CSV/JSON/MD deliverables cleanly and verify counts."""

    rcm_rows = [r for r in all_runs if r["stage"] == "RCM_113"]
    sa_rows = [r for r in all_runs if r["stage"] in ("SA_113", "SA_LEGACY72_COMPAT")]
    drsa_rows = [r for r in all_runs if r["stage"] == "DRSA_113"]
    cpsat_rows = [r for r in all_runs if r["family"] == "CP" and r["method"] == "cp-sat"]
    sat_run_rows = [r for r in all_runs if r["family"] == "SAT"]
    mip_cpo_run_rows = [r for r in all_runs if r["stage"] == "MIP_CPO_113"]

    _write_csv_atomic(output_dir / "rcm_113.csv", RUN_ROW_FIELDS, rcm_rows)
    _write_csv_atomic(output_dir / "sa_113.csv", RUN_ROW_FIELDS, sa_rows)
    _write_csv_atomic(output_dir / "drsa_113.csv", RUN_ROW_FIELDS, drsa_rows)
    _write_csv_atomic(output_dir / "cpsat_113.csv", RUN_ROW_FIELDS, cpsat_rows)
    _write_csv_atomic(output_dir / "sat_runs.csv", RUN_ROW_FIELDS, sat_run_rows)

    # Merge license table with live execution results into mip_cp_license_113.csv
    exec_by_mip_cpo = {(r["instance"], r["method"]): r for r in mip_cpo_run_rows}
    merged_lic_rows: list[dict[str, Any]] = []
    for lr in lic_rows:
        ex = exec_by_mip_cpo.get((lr["instance"], lr["solver"]), {})
        merged_lic_rows.append({
            **lr,
            "solver_attempted": ex.get("solver_attempted", False),
            "m3_8_coverage_status": ex.get("m3_8_coverage_status", "PREFLIGHT_EVALUATED" if lr["eligibility"] == "ELIGIBLE" else "BLOCKED_LICENSE"),
            "bandwidth": ex.get("bandwidth"),
            "lower_bound": ex.get("lower_bound"),
            "total_wall_time_s": ex.get("total_wall_time_s"),
            "validation_passed": ex.get("validation_passed"),
        })
    if merged_lic_rows:
        _write_csv_atomic(output_dir / "mip_cp_license_113.csv", list(merged_lic_rows[0].keys()), merged_lic_rows)

    # Method Coverage 113 summary across exact primary 113 instances
    def _best_row_per_instance(subset: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        rank_map = {
            "OPTIMAL_PROVED": 6,
            "FEASIBLE_SOLUTION_FOUND": 5,
            "TIMEOUT_WITH_INCUMBENT": 4,
            "TIMEOUT_NO_INCUMBENT": 3,
            "RESOURCE_LIMIT": 2,
            "BLOCKED_LICENSE": 1,
            "ERROR": 0,
        }
        for r in subset:
            if not r["is_primary_113"]:
                continue
            inst = str(r["instance"])
            if inst not in out:
                out[inst] = r
                continue
            prev = out[inst]
            r_score = (rank_map.get(r["m3_8_coverage_status"], 0), -(r["bandwidth"] if r["bandwidth"] is not None else 10**9))
            p_score = (rank_map.get(prev["m3_8_coverage_status"], 0), -(prev["bandwidth"] if prev["bandwidth"] is not None else 10**9))
            if r_score > p_score:
                out[inst] = r
        return out

    method_subsets = [
        ("RCM (primary 113)", [r for r in rcm_rows if r["is_primary_113"]]),
        ("SA (primary 113)", [r for r in sa_rows if r["stage"] == "SA_113" and r["is_primary_113"]]),
        ("DRSA Warm MODIFIED (113)", [r for r in drsa_rows if r["method"] == "drsa_modified_variant" and r["is_primary_113"]]),
        ("DRSA Paper-Bounded (113)", [r for r in drsa_rows if r["method"] == "drsa_paper_faithful" and r["is_primary_113"]]),
        ("CP-SAT Best Across Passes (113)", list(_best_row_per_instance(cpsat_rows).values())),
        ("SAT Order+Product+Inc CaDiCaL (113)", [r for r in sat_run_rows if r["stage"] == "SAT_113_COMPACT" and r["is_primary_113"]]),
        ("Gurobi Eval (113)", [r for r in mip_cpo_run_rows if r["method"] == "gurobi"]),
        ("CPLEX CE (113)", [r for r in mip_cpo_run_rows if r["method"] == "cplex"]),
        ("IBM CP Optimizer CE (113)", [r for r in mip_cpo_run_rows if r["method"] == "cp-optimizer"]),
    ]

    cov_rows: list[dict[str, Any]] = []
    for label, srows in method_subsets:
        st_cnt = Counter(r["m3_8_coverage_status"] for r in srows)
        t1 = [r for r in srows if r["official_benchmark"]]
        t2 = [r for r in srows if not r["official_benchmark"]]
        exec_t = [float(r["total_wall_time_s"]) for r in srows if r["solver_attempted"] and r["total_wall_time_s"] is not None]
        cov_rows.append({
            "method_label": label,
            "catalog_instances": len(dataset_rows),
            "dataset_loaded": len(srows),
            "preflight_evaluated": len(srows),
            "solver_attempted": sum(bool(r["solver_attempted"]) for r in srows),
            "valid_solution_found": sum(bool(r["has_valid_solution"]) for r in srows),
            "optimal_proved": st_cnt["OPTIMAL_PROVED"],
            "feasible_solution_found": st_cnt["FEASIBLE_SOLUTION_FOUND"],
            "timeout_with_incumbent": st_cnt["TIMEOUT_WITH_INCUMBENT"],
            "timeout_no_incumbent": st_cnt["TIMEOUT_NO_INCUMBENT"],
            "resource_limit": st_cnt["RESOURCE_LIMIT"],
            "blocked_license": st_cnt["BLOCKED_LICENSE"],
            "error_count": st_cnt["ERROR"],
            "tier1_ready_valid": sum(bool(r["has_valid_solution"]) for r in t1),
            "tier2_exploratory_valid": sum(bool(r["has_valid_solution"]) for r in t2),
            "median_wall_time_s": round(statistics.median(exec_t), 4) if exec_t else None,
        })
    _write_csv_atomic(output_dir / "method_coverage_113.csv", list(cov_rows[0].keys()), cov_rows)

    # Published Best Comparison across all 113 (Tier 1 vs Tier 2 explicitly flagged!)
    by_inst_primary = defaultdict(list)
    for r in all_runs:
        if r["is_primary_113"] and r["stage"] != "SA_LEGACY72_COMPAT":
            by_inst_primary[str(r["instance"])].append(r)

    pub_rows: list[dict[str, Any]] = []
    for ds in dataset_rows:
        inst = str(ds["instance"])
        grp = by_inst_primary[inst]
        rcm_r = next((r for r in grp if r["method"] == "rcm"), None)
        sa_r = next((r for r in grp if r["method"] == "sa"), None)
        drsa_w = next((r for r in grp if r["method"] == "drsa_modified_variant"), None)
        drsa_p = next((r for r in grp if r["method"] == "drsa_paper_faithful"), None)
        cps_best = _best_row_per_instance([r for r in grp if r["method"] == "cp-sat"]).get(inst)
        sat_r = next((r for r in grp if r["stage"] == "SAT_113_COMPACT"), None)
        cpo_r = next((r for r in grp if r["method"] == "cp-optimizer"), None)
        gur_r = next((r for r in grp if r["method"] == "gurobi"), None)
        cpx_r = next((r for r in grp if r["method"] == "cplex"), None)

        valid_bws = [(r["bandwidth"], r["method"]) for r in grp if r["has_valid_solution"] and r["bandwidth"] is not None]
        best_bw, best_meth = min(valid_bws, key=lambda t: t[0]) if valid_bws else (None, None)
        exact_provers = sorted({r["method"] for r in grp if r["proved_optimal"]})
        best_lb = max([int(r["lower_bound"]) for r in grp if r["lower_bound"] is not None] + [int(ds["certified_lb"])])
        pub_best = int(ds["paper_best"])
        pub_lb = int(ds["paper_lb"])
        pub_rows.append({
            "instance": inst,
            "table": ds["table"],
            "tier": ds["tier"],
            "official_benchmark": ds["official_benchmark"],
            "validation_status": ds["validation_status"],
            "conversion_policy": ds["primary_conversion_policy"],
            "topology_duplicate_of": ds["topology_duplicate_of"],
            "n": ds["n"],
            "m": ds["m_primary"],
            "paper_lb": pub_lb,
            "paper_best": pub_best,
            "best_certified_lb": best_lb,
            "best_feasible_bw": best_bw,
            "best_method": best_meth,
            "proved_optimal": bool(exact_provers),
            "optimal_proving_methods": ";".join(exact_provers),
            "gap_vs_published_best": None if best_bw is None else int(best_bw) - pub_best,
            "below_published_lb_flag": bool(best_bw is not None and int(best_bw) < pub_lb),
            "confidence_tier": "CANONICAL_VERIFIED" if ds["official_benchmark"] else "EXPLORATORY_UNVERIFIED",
            "rcm_bw": rcm_r["bandwidth"] if rcm_r else None,
            "sa_bw": sa_r["bandwidth"] if sa_r else None,
            "drsa_warm_bw": drsa_w["bandwidth"] if drsa_w else None,
            "drsa_paper_bounded_bw": drsa_p["bandwidth"] if drsa_p else None,
            "cpsat_bw": cps_best["bandwidth"] if cps_best else None,
            "cpsat_status": cps_best["m3_8_coverage_status"] if cps_best else None,
            "sat_bw": sat_r["bandwidth"] if sat_r else None,
            "sat_status": sat_r["m3_8_coverage_status"] if sat_r else None,
            "cpo_bw": cpo_r["bandwidth"] if cpo_r else None,
            "gurobi_bw": gur_r["bandwidth"] if gur_r else None,
            "cplex_bw": cpx_r["bandwidth"] if cpx_r else None,
        })
    _write_csv_atomic(output_dir / "published_best_comparison.csv", list(pub_rows[0].keys()), pub_rows)

    # No-Regression 3-era comparison table
    with legacy_csv.open(encoding="utf-8", newline="") as f:
        legacy_rows = list(csv.DictReader(f))
    leg_by_meth = defaultdict(list)
    for r in legacy_rows:
        leg_by_meth[str(r["method"])].append(r)

    sa_leg_rows = [r for r in all_runs if r["stage"] == "SA_LEGACY72_COMPAT"]
    no_reg_rows: list[dict[str, Any]] = []
    # Era 1: Before M3.1 (288 legacy records on 72 Table 6-7)
    for meth in ("rcm", "sa", "cp-sat", "cp-optimizer"):
        lr = leg_by_meth.get(meth, [])
        no_reg_rows.append({
            "era": "Before_M3_1_Original_72",
            "method": meth,
            "dataset_available": 72,
            "solver_attempts": len(lr),
            "valid_feasible_solutions": sum(str(r.get("validated")).lower() == "true" and str(r.get("status")) in ("FEASIBLE", "OPTIMAL") for r in lr),
            "optimal_proofs": sum(str(r.get("status")) == "OPTIMAL" for r in lr),
            "timeout_with_incumbent": 0,
            "resource_blocks": 0,
            "license_blocks": 0,
            "execution_errors": 0,
            "notes": "Historical 72 Table 6-7 (nonzero_union); SA iters=2000; CP 2.0s; CPO on Windows full binary",
        })
    # Era 2: After M3.7 (54 READY M3.6 snapshot)
    m36_sum_path = output_dir.parent / "member3_m3_6" / "summary.json"
    if m36_sum_path.exists():
        m36_s = json.loads(m36_sum_path.read_text(encoding="utf-8"))
        for ms in m36_s.get("method_summary", []):
            no_reg_rows.append({
                "era": "After_M3_7_54_READY",
                "method": ms["method_key"],
                "dataset_available": 54,
                "solver_attempts": int(ms["attempted"]) - int(ms["resource_limit_count"]) - int(ms["unavailable_count"]),
                "valid_feasible_solutions": ms["valid_incumbent_count"],
                "optimal_proofs": ms["optimal_count"],
                "timeout_with_incumbent": max(0, int(ms["valid_incumbent_count"]) - int(ms["optimal_count"]) - int(ms["feasible_count"])),
                "resource_blocks": ms["resource_limit_count"],
                "license_blocks": ms["unavailable_count"],
                "execution_errors": ms["error_count"],
                "notes": f"M3.6 canonical 54 READY ({ms['runtime_scope_note']})",
            })
    # Era 3: After M3.8 (Full 113)
    for cr in cov_rows:
        no_reg_rows.append({
            "era": "After_M3_8_Full_113",
            "method": cr["method_label"],
            "dataset_available": 113,
            "solver_attempts": cr["solver_attempted"],
            "valid_feasible_solutions": cr["valid_solution_found"],
            "optimal_proved": cr["optimal_proved"],
            "optimal_proofs": cr["optimal_proved"],
            "timeout_with_incumbent": cr["timeout_with_incumbent"],
            "resource_blocks": cr["resource_limit"],
            "license_blocks": cr["blocked_license"],
            "execution_errors": cr["error_count"],
            "notes": f"Tier1={cr['tier1_ready_valid']}/54 + Tier2={cr['tier2_exploratory_valid']}/59",
        })
    # Plus explicit 72-instance compatibility check line
    no_reg_rows.append({
        "era": "After_M3_8_Legacy72_Compat",
        "method": "sa_legacy_2000 (nonzero_union seed=17)",
        "dataset_available": 72,
        "solver_attempts": len(sa_leg_rows),
        "valid_feasible_solutions": sum(bool(r["has_valid_solution"]) for r in sa_leg_rows),
        "optimal_proofs": 0,
        "timeout_with_incumbent": 0,
        "resource_blocks": 0,
        "license_blocks": 0,
        "execution_errors": sum(r["m3_8_coverage_status"] == "ERROR" for r in sa_leg_rows),
        "notes": "Direct 72/72 backward compatibility check vs historical results/member3-harwell-boeing.csv",
    })
    _write_csv_atomic(
        output_dir / "no_regression_comparison.csv",
        [
            "era", "method", "dataset_available", "solver_attempts", "valid_feasible_solutions",
            "optimal_proofs", "timeout_with_incumbent", "resource_blocks", "license_blocks", "execution_errors", "notes",
        ],
        no_reg_rows,
    )

    mbe_496 = next((r for r in pub_rows if r["instance"] == "mbeause"), None)
    mbe_492_runs = [r for r in all_runs if r["view_id"] == "mbeause__drop4_492_sens"]

    t1_pub = [r for r in pub_rows if r["official_benchmark"]]
    t2_pub = [r for r in pub_rows if not r["official_benchmark"]]
    t1_gaps = [r["gap_vs_published_best"] for r in t1_pub if r["gap_vs_published_best"] is not None]
    t2_gaps = [r["gap_vs_published_best"] for r in t2_pub if r["gap_vs_published_best"] is not None]

    summary = {
        "experiment_id": "m3_8_full113_v1",
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "dataset_summary": {
            "total_catalog_names": len(dataset_rows),
            "graphs_constructed_primary": sum(r["graph_loading_result"] == "DATASET_LOADED" for r in dataset_rows),
            "tier1_ready_count": len(t1_pub),
            "tier2_exploratory_count": len(t2_pub),
            "needs_verification_count": sum(r["validation_status"] == "NEEDS_VERIFICATION" for r in dataset_rows),
            "invalid_data_count": sum(r["validation_status"] == "INVALID_DATA" for r in dataset_rows),
            "table_counts": dict(Counter(r["table"] for r in dataset_rows)),
            "unique_topologies_in_113": len({r["topology_sha256"] for r in dataset_rows}),
            "duplicate_pairs_in_113": [
                {"instance": r["instance"], "duplicate_of": r["topology_duplicate_of"]}
                for r in dataset_rows if r["topology_duplicate_of"]
            ],
            "total_graph_views_constructed": len(view_rows),
        },
        "batch_execution": {
            "total_run_records": len(all_runs),
            "planned_static_runs": planned_static_count,
            "planned_dynamic_pass2_runs": planned_dynamic_pass2,
            "executed_in_this_batch": executed_this_batch,
            "interrupted_by_batch_budget": interrupted,
        },
        "coverage_table_113": cov_rows,
        "tier_comparison": {
            "tier1_verified_54": {
                "count": len(t1_pub),
                "proved_optimal": sum(bool(r["proved_optimal"]) for r in t1_pub),
                "matched_published_best": sum(r["gap_vs_published_best"] == 0 for r in t1_pub),
                "mean_gap_vs_published_best": round(statistics.mean(t1_gaps), 4) if t1_gaps else None,
                "median_gap_vs_published_best": round(statistics.median(t1_gaps), 4) if t1_gaps else None,
            },
            "tier2_exploratory_59": {
                "count": len(t2_pub),
                "proved_optimal": sum(bool(r["proved_optimal"]) for r in t2_pub),
                "matched_published_best": sum(r["gap_vs_published_best"] == 0 for r in t2_pub),
                "below_paper_lb_count": sum(bool(r["below_published_lb_flag"]) for r in t2_pub),
                "mean_gap_vs_published_best": round(statistics.mean(t2_gaps), 4) if t2_gaps else None,
                "median_gap_vs_published_best": round(statistics.median(t2_gaps), 4) if t2_gaps else None,
            },
        },
        "mbeause_sensitivity": {
            "raw_496": {
                "n": mbe_496["n"] if mbe_496 else None,
                "best_bw": mbe_496["best_feasible_bw"] if mbe_496 else None,
                "rcm_bw": mbe_496["rcm_bw"] if mbe_496 else None,
                "sa_bw": mbe_496["sa_bw"] if mbe_496 else None,
                "drsa_warm_bw": mbe_496["drsa_warm_bw"] if mbe_496 else None,
            },
            "dropped_4_isolated_492": {
                r["method"]: r["bandwidth"] for r in mbe_492_runs
            },
        },
        "sat_preflight_summary": {
            "total_preflight_rows": len(pf_rows),
            "configs_per_instance": 72,
            "recommended_compact_order_product_eligible": sum(
                1 for ds in dataset_rows
                if any(p["instance"] == ds["instance"] and p["main_encoding"] == "order" and p["amo_encoding"] == "product" and p["backend"] == "cadical" and p["strategy"] == "incremental" and p["eligibility"] == "ELIGIBLE" for p in pf_rows)
            ),
        },
        "validation_totals": {
            "total_with_solution": sum(bool(r["has_valid_solution"]) for r in all_runs),
            "validation_failed": sum(r["validation_passed"] is False for r in all_runs),
            "execution_errors": sum(r["m3_8_coverage_status"] == "ERROR" for r in all_runs),
        },
    }
    _write_json_atomic(output_dir / "full113_summary.json", summary)

    # Reproduction & run log markdown
    repro_md = (
        "# M3.8 Full 113/113 Reproduction Guide\n\n"
        "```bash\n"
        "python scripts/acquire_benchmark.py --verify-only || python scripts/acquire_benchmark.py\n"
        "python scripts/run_member3_m3_8.py --config configs/member3_m3_8.toml --plots\n"
        "pytest -vv tests/test_member3_full113_m3_8.py\n"
        "```\n"
    )
    (output_dir / "reproduction.md").write_text(repro_md, encoding="utf-8")

    log_lines = [
        f"Phase M3.8 Full 113/113 Coverage Log ({summary['timestamp']})",
        f"Catalog covered: {summary['dataset_summary']['total_catalog_names']}/113 | Constructed primary graphs: {summary['dataset_summary']['graphs_constructed_primary']}/113",
        f"Tier 1 READY: {summary['dataset_summary']['tier1_ready_count']} | Tier 2 Exploratory: {summary['dataset_summary']['tier2_exploratory_count']}",
        f"Total records: {summary['batch_execution']['total_run_records']} | Interrupted: {interrupted}",
        f"Validation failed: {summary['validation_totals']['validation_failed']} | Errors: {summary['validation_totals']['execution_errors']}",
    ]
    for cr in cov_rows:
        log_lines.append(
            f"  {cr['method_label']}: attempted={cr['solver_attempted']}, valid={cr['valid_solution_found']}, "
            f"opt={cr['optimal_proved']}, feas={cr['feasible_solution_found']}, to_inc={cr['timeout_with_incumbent']}, "
            f"to_no={cr['timeout_no_incumbent']}, res_lim={cr['resource_limit']}, blk_lic={cr['blocked_license']}"
        )
    (output_dir / "run_log.txt").write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    return summary
