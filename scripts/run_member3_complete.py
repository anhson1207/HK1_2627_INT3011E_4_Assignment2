"""Complete Member 3 local experimental evaluation and CSV generator (113 HB instances)."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import os
import platform
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from time import monotonic
from typing import Any

from bmp.core.benchmark_catalog import ALL_INSTANCES, resolve_raw_matrix_path
from bmp.core.generators import cycle_graph, erdos_renyi_graph, path_graph
from bmp.core.graph import Graph
from bmp.core.solution import SolutionStatus, SolverResult
from bmp.core.validation import validate_solution
from bmp.encodings.estimator import ResourceLimits
from bmp.encodings.order import OrderEncoding
from bmp.experiments.member3_m3_6 import audit_environment
from bmp.experiments.member3_m3_8 import _build_mip_cp_license_table
from bmp.heuristics.drsa import DRSASolver
from bmp.heuristics.rcm import RCMSolver
from bmp.heuristics.sa import SimulatedAnnealingSolver
from bmp.io.readers import (
    CONVERSION_VERSION,
    OFFICIAL_CONVERSION_POLICY,
    compute_graph_fingerprint,
    compute_topology_sha256,
    graph_from_matrix_market_forensics,
    inspect_matrix_market_forensics,
)
from bmp.solvers.exact.cp_optimizer import CPOptimizerSolver
from bmp.solvers.exact.cpsat import CPSATSolver
from bmp.solvers.sat.incremental import IncrementalSATSolver
from bmp.solvers.sat.repeated import RepeatedSATSolver
from bmp.solvers.sat.search import compute_lower_bound

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "results" / "member3_complete"


def _write_csv_atomic(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: ("" if row.get(k) is None else row.get(k)) for k in fieldnames})
    os.replace(tmp, path)


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _grid_graph(rows: int, cols: int) -> Graph:
    n = rows * cols
    edges: list[tuple[int, int]] = []
    for r in range(rows):
        for c in range(cols):
            v = r * cols + c + 1
            if r + 1 < rows:
                edges.append((v, (r + 1) * cols + c + 1))
            if c + 1 < cols:
                edges.append((v, r * cols + c + 2))
    return Graph.from_edges(list(range(1, n + 1)), edges, name=f"grid_{rows}x{cols}")


def _petersen_graph() -> Graph:
    edges: list[tuple[int, int]] = []
    for i in range(5):
        edges.append((i + 1, ((i + 1) % 5) + 1))
        edges.append((i + 6, ((i + 2) % 5) + 6))
        edges.append((i + 1, i + 6))
    return Graph.from_edges(list(range(1, 11)), edges, name="petersen_10")


def _classify_status(
    res: SolverResult,
    *,
    validation_passed: bool | None,
    has_incumbent: bool,
    blocked_license: bool = False,
) -> str:
    if blocked_license or res.status is SolutionStatus.UNAVAILABLE:
        return "BLOCKED_LICENSE"
    if res.status is SolutionStatus.SKIPPED:
        return "RESOURCE_LIMIT"
    if validation_passed is False:
        return "INVALID"
    if res.status is SolutionStatus.OPTIMAL and validation_passed:
        return "OPT"
    if res.status is SolutionStatus.FEASIBLE and validation_passed:
        return "FEAS"
    if res.status is SolutionStatus.INFEASIBLE:
        return "INFEAS"
    if res.status is SolutionStatus.TIMEOUT:
        return "TIMEOUT_WITH_INCUMBENT" if (has_incumbent and validation_passed) else "TIMEOUT"
    return "UNKNOWN"


def _numeric_stats(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "mean": None, "median": None, "std": None, "min": None, "max": None}
    return {
        "count": len(values),
        "mean": round(statistics.mean(values), 6),
        "median": round(statistics.median(values), 6),
        "std": round(statistics.stdev(values), 6) if len(values) >= 2 else 0.0,
        "min": round(min(values), 6),
        "max": round(max(values), 6),
    }


def load_113_dataset_and_tables(output_dir: Path) -> tuple[
    list[dict[str, Any]],
    dict[str, Graph],
    dict[str, dict[str, Any]],
]:
    prov_path = ROOT / "data" / "benchmark_provenance.json"
    prov_entries = json.loads(prov_path.read_text(encoding="utf-8"))
    prov_by_name = {str(e["instance"]): e for e in prov_entries}

    manifest_rows: list[dict[str, Any]] = []
    graphs: dict[str, Graph] = {}
    meta_by_inst: dict[str, dict[str, Any]] = {}
    seen_topologies: dict[str, str] = {}

    table_rows: dict[str, list[dict[str, Any]]] = {"Table 6": [], "Table 7": [], "Table 8": []}

    for inst in sorted(ALL_INSTANCES):
        cat = ALL_INSTANCES[inst]
        prov = prov_by_name[inst]
        val_status = str(prov.get("validation_status", "UNKNOWN"))
        sym_kind = str(prov.get("matrix_symmetry", ""))
        policy = str(prov.get("primary_conversion_policy") or (
            OFFICIAL_CONVERSION_POLICY if sym_kind in ("symmetric", "skew-symmetric") else "stored_union"
        ))
        raw_path = resolve_raw_matrix_path(inst, root=ROOT)
        assert raw_path is not None, f"Missing raw file for {inst}"
        forensics = inspect_matrix_market_forensics(raw_path)
        g_primary = graph_from_matrix_market_forensics(forensics, policy=policy)
        topo_sha = compute_topology_sha256(g_primary)
        fp_sha = compute_graph_fingerprint(g_primary)
        cert_lb = compute_lower_bound(g_primary)
        dup_of = seen_topologies.get(topo_sha, "")
        if not dup_of:
            seen_topologies[topo_sha] = inst

        graphs[inst] = g_primary
        m_nz = len(forensics.one_based_edges_by_policy["nonzero_union"])
        m_st = len(forensics.one_based_edges_by_policy["stored_union"])
        row = {
            "instance": inst,
            "source_table": cat.source_table,
            "category": cat.category,
            "raw_file_path": os.path.relpath(raw_path, ROOT),
            "source_sha256": prov.get("source_sha256", ""),
            "matrix_symmetry": forensics.symmetry,
            "primary_conversion_policy": policy,
            "conversion_version": CONVERSION_VERSION,
            "official_benchmark": val_status == "READY",
            "validation_status": val_status,
            "n": g_primary.order,
            "m": g_primary.size,
            "m_nonzero_union": m_nz,
            "m_stored_union": m_st,
            "explicit_offdiag_zeros": m_st - m_nz,
            "certified_lb": cert_lb,
            "published_lb": cat.paper_lb,
            "published_best": cat.paper_best,
            "topology_sha256": topo_sha,
            "graph_fingerprint": fp_sha,
            "topology_duplicate_of": dup_of,
            "paper_reference": cat.paper_reference,
        }
        manifest_rows.append(row)
        meta_by_inst[inst] = {
            **row,
            "table": cat.source_table,
            "conversion_policy": policy,
            "tier": "TIER1_VERIFIED_CANONICAL" if val_status == "READY" else f"TIER2_{val_status}",
        }

        table_rows[cat.source_table].append({
            "instance": inst,
            "source_table": cat.source_table,
            "n": cat.n,
            "observed_n": g_primary.order,
            "observed_m": g_primary.size,
            "validation_status": val_status,
            "published_lb": cat.paper_lb,
            "published_best": cat.paper_best,
            "grasp_pr_bandwidth": cat.grasp_pr_bandwidth,
            "grasp_pr_time_s": cat.grasp_pr_time_s,
            "sa_bandwidth": cat.sa_bandwidth,
            "sa_time_s": cat.sa_time_s,
            "vns_bandwidth": cat.vns_bandwidth,
            "vns_time_s": cat.vns_time_s,
            "drsa_bandwidth": cat.drsa_bandwidth,
            "drsa_time_s": cat.drsa_time_s,
            "paper_reference": cat.paper_reference,
        })

    assert len(manifest_rows) == 113, f"Expected 113 instances, got {len(manifest_rows)}"
    assert len(table_rows["Table 6"]) == 31
    assert len(table_rows["Table 7"]) == 41
    assert len(table_rows["Table 8"]) == 41

    _write_csv_atomic(output_dir / "dataset_manifest.csv", list(manifest_rows[0].keys()), manifest_rows)
    for tname, fname in (
        ("Table 6", "table_6_reference.csv"),
        ("Table 7", "table_7_reference.csv"),
        ("Table 8", "table_8_reference.csv"),
    ):
        trows = table_rows[tname]
        _write_csv_atomic(output_dir / fname, list(trows[0].keys()), trows)

    return manifest_rows, graphs, meta_by_inst


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--cpsat-threads", type=int, default=4)
    parser.add_argument("--cpsat-pass1-timeout", type=float, default=4.0)
    parser.add_argument("--cpsat-pass2-timeout", type=float, default=12.0)
    parser.add_argument("--cpsat-proof-timeout", type=float, default=20.0)
    parser.add_argument("--sat-timeout", type=float, default=6.0)
    parser.add_argument("--sa-timeout", type=float, default=0.25)
    parser.add_argument("--finish-cpo-and-summary", action="store_true")
    args = parser.parse_args()

    out_dir: Path = args.output_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    started_all = monotonic()

    print("[1/6] Loading and validating exact 113 Harwell-Boeing dataset & Tables 6/7/8...", flush=True)
    env_info = audit_environment()
    manifest_rows, graphs, meta_by_inst = load_113_dataset_and_tables(out_dir)
    print(f"      Loaded {len(manifest_rows)} unique HB instances (31 T6 / 41 T7 / 41 T8).", flush=True)

    rcm_cache: dict[str, tuple[dict[int, int], int]] = {}
    drsa_cache: dict[str, tuple[dict[int, int], int]] = {}
    sa_seeds = (0, 17, 42)

    def _read_existing_csv(fname: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        with (out_dir / fname).open(encoding="utf-8", newline="") as f:
            for rec in csv.DictReader(f):
                parsed: dict[str, Any] = {}
                for k, v in rec.items():
                    if v == "":
                        parsed[k] = None
                    elif v == "True":
                        parsed[k] = True
                    elif v == "False":
                        parsed[k] = False
                    else:
                        parsed[k] = v
                out.append(parsed)
        return out

    if args.finish_cpo_and_summary:
        heuristics_rows = _read_existing_csv("heuristics_results.csv")
        cpsat_rows = _read_existing_csv("cpsat_results.csv")
        best_cpsat_by_inst = {r["instance"]: r for r in cpsat_rows if r.get("is_best_for_instance") is True}
        minisat_rep_rows = _read_existing_csv("minisat_repeated_results.csv")
        minisat_inc_rows = _read_existing_csv("minisat_incremental_results.csv")
        prod_lad_rows = _read_existing_csv("product_ladder_comparison.csv")
        for row in manifest_rows:
            inst = row["instance"]
            if int(row["n"]) <= 150:
                rcm_res = RCMSolver().solve(graphs[inst])
                rcm_cache[inst] = (dict(rcm_res.permutation or {}), int(rcm_res.bandwidth or 0))
    else:
        # Precompute deterministic RCM + DRSA warm starts once (reported separately)
        print("[2/6] Experiment D: RCM vs Multi-Seed SA across all 113 HB instances...", flush=True)
        heuristics_rows = []
        for idx, row in enumerate(manifest_rows, start=1):
            inst = row["instance"]
            g = graphs[inst]
            rcm_res = RCMSolver().solve(g)
            rcm_rep = validate_solution(g, rcm_res.permutation, claimed_bandwidth=rcm_res.bandwidth)
            assert rcm_rep.valid and rcm_rep.actual_bandwidth is not None
            rcm_cache[inst] = (dict(rcm_res.permutation or {}), rcm_rep.actual_bandwidth)

            heuristics_rows.append({
                "instance": inst,
                "source_table": row["source_table"],
                "n": g.order,
                "m": g.size,
                "method": "RCM",
                "seed": "",
                "initial_bandwidth": rcm_rep.actual_bandwidth,
                "final_bandwidth": rcm_rep.actual_bandwidth,
                "improvement": 0,
                "improvement_pct": 0.0,
                "iterations_completed": 1,
                "runtime_s": round(float(rcm_res.runtime_s), 6),
                "published_best": row["published_best"],
                "gap_vs_published_best": rcm_rep.actual_bandwidth - int(row["published_best"]),
                "validation_passed": True,
            })

            sa_bws: list[float] = []
            sa_times: list[float] = []
            for s_val in sa_seeds:
                sa_res = SimulatedAnnealingSolver(
                    iterations=200000,
                    initial_temperature=2.0,
                    cooling=0.995,
                    seed=s_val,
                    initial_mode="rcm",
                ).solve(g, timeout_seconds=args.sa_timeout, initial_permutation=rcm_cache[inst][0])
                sa_rep = validate_solution(g, sa_res.permutation, claimed_bandwidth=sa_res.bandwidth)
                assert sa_rep.valid and sa_rep.actual_bandwidth is not None
                md = dict(sa_res.metadata or {})
                init_bw = int(md.get("initial_bandwidth", rcm_rep.actual_bandwidth))
                final_bw = sa_rep.actual_bandwidth
                imp = init_bw - final_bw
                sa_bws.append(float(final_bw))
                sa_times.append(float(sa_res.runtime_s))
                heuristics_rows.append({
                    "instance": inst,
                    "source_table": row["source_table"],
                    "n": g.order,
                    "m": g.size,
                    "method": "SA",
                    "seed": s_val,
                    "initial_bandwidth": init_bw,
                    "final_bandwidth": final_bw,
                    "improvement": imp,
                    "improvement_pct": round(100.0 * imp / init_bw, 3) if init_bw > 0 else 0.0,
                    "iterations_completed": md.get("iterations_completed", 0),
                    "runtime_s": round(float(sa_res.runtime_s), 6),
                    "published_best": row["published_best"],
                    "gap_vs_published_best": final_bw - int(row["published_best"]),
                    "validation_passed": True,
                })

            # Compute deterministic DRSA warm-start (for CP-SAT & SAT comparability with M3.8)
            drsa_res = DRSASolver(
                seed=17,
                initial_mode="rcm",
                initial_temperature=2.0,
                cooling=0.99,
                final_temperature=1e-7,
                initial_chain_length=40,
                variant="MODIFIED_VARIANT",
            ).solve(g, timeout_seconds=0.6)
            drsa_rep = validate_solution(g, drsa_res.permutation, claimed_bandwidth=drsa_res.bandwidth)
            assert drsa_rep.valid and drsa_rep.actual_bandwidth is not None
            drsa_cache[inst] = (dict(drsa_res.permutation or {}), drsa_rep.actual_bandwidth)

            if idx % 25 == 0 or idx == len(manifest_rows):
                print(f"      Heuristics progress: {idx}/113", flush=True)

        _write_csv_atomic(out_dir / "heuristics_results.csv", list(heuristics_rows[0].keys()), heuristics_rows)

        print("[3/6] Experiment A: Improved CP-SAT across all 113 HB instances...", flush=True)
        cpsat_rows: list[dict[str, Any]] = []
        best_cpsat_by_inst: dict[str, dict[str, Any]] = {}

        def _run_cpsat_pass(inst: str, stage: str, tlim: float, *, injectivity_mode: str = "auto", presolve: bool | None = None) -> dict[str, Any]:
            g = graphs[inst]
            meta = meta_by_inst[inst]
            warm_perm, warm_bw = drsa_cache[inst]
            t0 = monotonic()
            res = CPSATSolver(seed=17).solve(
                g,
                timeout_seconds=tlim,
                symmetry_breaking=True,
                threads=args.cpsat_threads,
                initial_permutation=warm_perm,
                isolate_timeout=False,
                injectivity_mode=injectivity_mode,
                presolve=presolve,
            )
            wall_s = monotonic() - t0
            md = dict(res.metadata or {})
            val_rep = (
                validate_solution(g, res.permutation, claimed_bandwidth=res.bandwidth)
                if res.permutation is not None
                else None
            )
            val_ok = bool(val_rep is not None and val_rep.valid) if res.permutation is not None else None
            bw = val_rep.actual_bandwidth if (val_ok and val_rep is not None) else None
            cls_status = _classify_status(res, validation_passed=val_ok, has_incumbent=bw is not None)
            rec = {
                "instance": inst,
                "source_table": meta["source_table"],
                "validation_status": meta["validation_status"],
                "n": g.order,
                "m": g.size,
                "stage": stage,
                "threads": args.cpsat_threads,
                "seed": 17,
                "time_limit_seconds": tlim,
                "injectivity_mode": md.get("injectivity_mode"),
                "presolve_enabled": md.get("presolve_enabled"),
                "warm_start_bw": warm_bw,
                "raw_status": res.status.value,
                "native_status": md.get("native_status"),
                "status_class": cls_status,
                "bandwidth": bw,
                "lower_bound": res.lower_bound,
                "published_lb": meta["published_lb"],
                "published_best": meta["published_best"],
                "gap_vs_published_best": (bw - int(meta["published_best"])) if bw is not None else None,
                "validation_passed": val_ok,
                "model_variables": md.get("model_variables", res.num_variables),
                "model_constraints": md.get("model_constraints", res.num_clauses),
                "num_branches": md.get("num_branches"),
                "num_conflicts": md.get("num_conflicts"),
                "model_construction_time_s": md.get("model_construction_time_s", res.encoding_time_s),
                "engine_init_time_s": md.get("engine_init_time_s"),
                "solver_time_s": md.get("solver_time_s", res.solving_time_s),
                "total_wall_time_s": round(wall_s, 6),
            }
            cpsat_rows.append(rec)

            rank = {"OPT": 4, "FEAS": 3, "INFEAS": 2, "TIMEOUT": 1, "UNKNOWN": 0, "INVALID": -1}
            prev = best_cpsat_by_inst.get(inst)
            rec_score = (rank.get(cls_status, 0), -(bw if bw is not None else 10**9))
            if prev is None or rec_score > (rank.get(prev["status_class"], 0), -(prev["bandwidth"] if prev["bandwidth"] is not None else 10**9)):
                best_cpsat_by_inst[inst] = rec
            return rec

        pass1_unsolved: list[str] = []
        proof_candidates: list[str] = []
        for idx, row in enumerate(manifest_rows, start=1):
            inst = row["instance"]
            r1 = _run_cpsat_pass(inst, "PASS1", args.cpsat_pass1_timeout)
            if r1["status_class"] in ("TIMEOUT", "UNKNOWN", "INVALID"):
                pass1_unsolved.append(inst)
            elif r1["status_class"] == "FEAS" and int(row["n"]) <= 75:
                proof_candidates.append(inst)
            if idx % 20 == 0 or idx == len(manifest_rows):
                solved_so_far = sum(1 for r in best_cpsat_by_inst.values() if r["status_class"] in ("OPT", "FEAS"))
                print(f"      CP-SAT Pass 1: {idx}/113 (valid solved={solved_so_far}/{idx})", flush=True)

        for inst in pass1_unsolved:
            r2 = _run_cpsat_pass(inst, "PASS2_RECOVERY", args.cpsat_pass2_timeout)
            print(f"      CP-SAT Pass 2 recovery {inst}: {r2['status_class']} bw={r2['bandwidth']} wall={r2['total_wall_time_s']}s", flush=True)

        for inst in proof_candidates:
            r3 = _run_cpsat_pass(inst, "PASS3_PROOF", args.cpsat_proof_timeout, injectivity_mode="all_different", presolve=True)
            print(f"      CP-SAT Pass 3 proof {inst}: {r3['status_class']} bw={r3['bandwidth']} wall={r3['total_wall_time_s']}s", flush=True)

        for rec in cpsat_rows:
            rec["is_best_for_instance"] = best_cpsat_by_inst[rec["instance"]] is rec

        _write_csv_atomic(out_dir / "cpsat_results.csv", list(cpsat_rows[0].keys()), cpsat_rows)

        print("[4/6] Experiment B: MiniSat22 (Solver(name='m22')) Repeated & Incremental...", flush=True)
        sat_limits = ResourceLimits(max_variables=500000, max_clauses=2500000, memory_limit_mb=4096.0)
        known_optima_graphs: list[tuple[str, Graph, int | None]] = [
            ("synthetic", path_graph(8), 1),
            ("synthetic", cycle_graph(8), 2),
            ("synthetic", _grid_graph(3, 3), 3),
            ("synthetic", erdos_renyi_graph(10, 0.35, seed=11), None),
            ("synthetic", _petersen_graph(), 4),
            ("synthetic", path_graph(12), 1),
        ]
        hb_small_names = [
            "pores_1", "ibm32", "bcspwr01", "bcsstk01", "bcspwr02",
            "curtis54", "will57", "impcol_b", "steam3", "ash85",
        ]
        sat_benchmarks: list[tuple[str, str, Graph, dict[int, int] | None]] = []
        for src, g_syn, _ in known_optima_graphs:
            rcm_syn = RCMSolver().solve(g_syn)
            sat_benchmarks.append((src, g_syn.name, g_syn, dict(rcm_syn.permutation or {})))
        for hname in hb_small_names:
            sat_benchmarks.append(("harwell_boeing", hname, graphs[hname], drsa_cache[hname][0]))

        minisat_rep_rows: list[dict[str, Any]] = []
        minisat_inc_rows: list[dict[str, Any]] = []

        def _run_sat_eval(
            *,
            source_kind: str,
            inst_name: str,
            g: Graph,
            warm_perm: dict[int, int] | None,
            backend_name: str,
            amo: str,
            strategy: str,
            search_mode: str,
            tlim: float,
        ) -> dict[str, Any]:
            encoder = OrderEncoding(amo=amo)
            solver = (
                RepeatedSATSolver(encoder, backend_name=backend_name, search_mode=search_mode)
                if strategy == "repeated"
                else IncrementalSATSolver(encoder, backend_name=backend_name)
            )
            t0 = monotonic()
            res = solver.solve(
                g,
                timeout_seconds=tlim,
                heuristic_permutation=warm_perm,
                symmetry_breaking=True,
                limits=sat_limits,
            )
            wall_s = monotonic() - t0
            val_rep = (
                validate_solution(g, res.permutation, claimed_bandwidth=res.bandwidth)
                if res.permutation is not None
                else None
            )
            val_ok = bool(val_rep is not None and val_rep.valid) if res.permutation is not None else None
            bw = val_rep.actual_bandwidth if (val_ok and val_rep is not None) else None
            status_cls = _classify_status(res, validation_passed=val_ok, has_incumbent=bw is not None)
            return {
                "instance": inst_name,
                "dataset_source": source_kind,
                "n": g.order,
                "m": g.size,
                "encoding": encoder.name,
                "amo_encoding": amo,
                "solver_backend": backend_name,
                "solving_mode": strategy,
                "search_mode": search_mode if strategy == "repeated" else "linear",
                "time_limit_seconds": tlim,
                "num_variables": res.num_variables,
                "num_clauses": res.num_clauses,
                "sat_calls": res.sat_calls,
                "model_construction_time_s": round(float(res.encoding_time_s or 0.0), 6),
                "solver_time_s": round(float(res.solving_time_s or 0.0), 6),
                "total_wall_time_s": round(wall_s, 6),
                "raw_status": res.status.value,
                "status_class": status_cls,
                "bandwidth": bw,
                "lower_bound": res.lower_bound,
                "validation_passed": val_ok,
            }

        for src, inst_name, g, wperm in sat_benchmarks:
            tlim = args.sat_timeout
            for amo in ("product", "ladder"):
                for smode in ("linear", "binary"):
                    minisat_rep_rows.append(
                        _run_sat_eval(
                            source_kind=src, inst_name=inst_name, g=g, warm_perm=wperm,
                            backend_name="minisat", amo=amo, strategy="repeated",
                            search_mode=smode, tlim=tlim,
                        )
                    )
                minisat_inc_rows.append(
                    _run_sat_eval(
                        source_kind=src, inst_name=inst_name, g=g, warm_perm=wperm,
                        backend_name="minisat", amo=amo, strategy="incremental",
                        search_mode="linear", tlim=tlim,
                    )
                )
            print(f"      MiniSat22 completed {inst_name} (n={g.order}, m={g.size})", flush=True)

        _write_csv_atomic(out_dir / "minisat_repeated_results.csv", list(minisat_rep_rows[0].keys()), minisat_rep_rows)
        _write_csv_atomic(out_dir / "minisat_incremental_results.csv", list(minisat_inc_rows[0].keys()), minisat_inc_rows)

        print("[5/6] Experiment C: Product vs Ladder Comparison (MiniSat22 & CaDiCaL)...", flush=True)
        prod_lad_rows: list[dict[str, Any]] = []
        # Reuse minisat_inc_rows verbatim and evaluate the exact same instances with CaDiCaL
        prod_lad_rows.extend(minisat_inc_rows)
        for src, inst_name, g, wperm in sat_benchmarks:
            for amo in ("product", "ladder"):
                prod_lad_rows.append(
                    _run_sat_eval(
                        source_kind=src, inst_name=inst_name, g=g, warm_perm=wperm,
                        backend_name="cadical", amo=amo, strategy="incremental",
                        search_mode="linear", tlim=args.sat_timeout,
                    )
                )
        _write_csv_atomic(out_dir / "product_ladder_comparison.csv", list(prod_lad_rows[0].keys()), prod_lad_rows)

    print("[6/6] Experiment E: IBM CP Optimizer CE vs License Gate across 113 instances...", flush=True)
    lic_rows = _build_mip_cp_license_table(
        dataset_rows=[meta_by_inst[r["instance"]] for r in manifest_rows],
        meta_by_view={f"{r['instance']}__primary": meta_by_inst[r["instance"]] for r in manifest_rows},
        env_info=env_info,
    )
    cpo_lic_by_inst = {r["instance"]: r for r in lic_rows if r["solver"] == "cp-optimizer"}
    cpo_rows: list[dict[str, Any]] = []
    cpo_solver = CPOptimizerSolver(seed=17)
    for row in manifest_rows:
        inst = row["instance"]
        g = graphs[inst]
        linfo = cpo_lic_by_inst[inst]
        if linfo["eligibility"] != "ELIGIBLE":
            cpo_rows.append({
                "instance": inst,
                "source_table": row["source_table"],
                "n": g.order,
                "m": g.size,
                "eligibility": linfo["eligibility"],
                "estimated_vars": linfo["estimated_vars"],
                "estimated_constrs": linfo["estimated_constrs"],
                "cpo_log2_search_space": linfo["cpo_log2_search_space"],
                "raw_status": "UNAVAILABLE",
                "status_class": "BLOCKED_LICENSE",
                "bandwidth": None,
                "lower_bound": row["certified_lb"],
                "validation_passed": None,
                "total_wall_time_s": None,
                "blocker_reason": linfo["blocker_reason"],
            })
            continue
        t0 = monotonic()
        res = cpo_solver.solve(
            g, timeout_seconds=5.0, symmetry_breaking=True, threads=1, initial_permutation=rcm_cache[inst][0]
        )
        wall_s = monotonic() - t0
        val_rep = validate_solution(g, res.permutation, claimed_bandwidth=res.bandwidth) if res.permutation else None
        val_ok = bool(val_rep is not None and val_rep.valid) if res.permutation else None
        bw = val_rep.actual_bandwidth if (val_ok and val_rep is not None) else None
        cls_status = _classify_status(res, validation_passed=val_ok, has_incumbent=bw is not None)
        cpo_rows.append({
            "instance": inst,
            "source_table": row["source_table"],
            "n": g.order,
            "m": g.size,
            "eligibility": linfo["eligibility"],
            "estimated_vars": linfo["estimated_vars"],
            "estimated_constrs": linfo["estimated_constrs"],
            "cpo_log2_search_space": linfo["cpo_log2_search_space"],
            "raw_status": res.status.value,
            "status_class": cls_status,
            "bandwidth": bw,
            "lower_bound": res.lower_bound,
            "validation_passed": val_ok,
            "total_wall_time_s": round(wall_s, 6),
            "blocker_reason": (res.metadata or {}).get("reason", ""),
        })

    _write_csv_atomic(out_dir / "cp_optimizer_results.csv", list(cpo_rows[0].keys()), cpo_rows)

    # Aggregate summary across all experiments
    agg_rows: list[dict[str, Any]] = []

    def _add_agg(exp_name: str, subset: list[dict[str, Any]], bw_key: str, time_key: str, status_key: str) -> None:
        cnt = Counter(str(r.get(status_key, "")) for r in subset)
        bws = [float(r[bw_key]) for r in subset if r.get(bw_key) is not None]
        ts = [float(r[time_key]) for r in subset if r.get(time_key) is not None]
        bstats = _numeric_stats(bws)
        tstats = _numeric_stats(ts)
        agg_rows.append({
            "experiment": exp_name,
            "total_runs": len(subset),
            "opt_count": cnt.get("OPT", 0),
            "feas_count": cnt.get("FEAS", 0),
            "infeas_count": cnt.get("INFEAS", 0),
            "timeout_with_incumbent_count": cnt.get("TIMEOUT_WITH_INCUMBENT", 0),
            "timeout_count": cnt.get("TIMEOUT", 0),
            "unknown_count": cnt.get("UNKNOWN", 0),
            "invalid_count": cnt.get("INVALID", 0),
            "resource_limit_count": cnt.get("RESOURCE_LIMIT", 0),
            "blocked_license_count": cnt.get("BLOCKED_LICENSE", 0),
            "valid_solutions": sum(1 for r in subset if r.get("validation_passed") is True),
            "bw_mean": bstats["mean"],
            "bw_median": bstats["median"],
            "bw_std": bstats["std"],
            "bw_min": bstats["min"],
            "bw_max": bstats["max"],
            "time_mean_s": tstats["mean"],
            "time_median_s": tstats["median"],
            "time_std_s": tstats["std"],
            "time_min_s": tstats["min"],
            "time_max_s": tstats["max"],
        })

    best_cp_list = list(best_cpsat_by_inst.values())
    _add_agg("Experiment_A_CPSAT_Pass1_113", [r for r in cpsat_rows if r["stage"] == "PASS1"], "bandwidth", "total_wall_time_s", "status_class")
    _add_agg("Experiment_A_CPSAT_Best_113", best_cp_list, "bandwidth", "total_wall_time_s", "status_class")
    _add_agg("Experiment_B_MiniSat22_Repeated", minisat_rep_rows, "bandwidth", "total_wall_time_s", "status_class")
    _add_agg("Experiment_B_MiniSat22_Incremental", minisat_inc_rows, "bandwidth", "total_wall_time_s", "status_class")
    _add_agg("Experiment_C_Product_Incremental", [r for r in prod_lad_rows if r["amo_encoding"] == "product"], "bandwidth", "total_wall_time_s", "status_class")
    _add_agg("Experiment_C_Ladder_Incremental", [r for r in prod_lad_rows if r["amo_encoding"] == "ladder"], "bandwidth", "total_wall_time_s", "status_class")

    rcm_agg_rows = [{**r, "st": "FEAS"} for r in heuristics_rows if r["method"] == "RCM"]
    sa_agg_rows = [{**r, "st": "FEAS"} for r in heuristics_rows if r["method"] == "SA"]
    _add_agg("Experiment_D_RCM_113", rcm_agg_rows, "final_bandwidth", "runtime_s", "st")
    _add_agg("Experiment_D_SA_3Seeds_339", sa_agg_rows, "final_bandwidth", "runtime_s", "st")
    _add_agg("Experiment_E_CPOptimizer_113", cpo_rows, "bandwidth", "total_wall_time_s", "status_class")

    _write_csv_atomic(out_dir / "aggregate_experimental_summary.csv", list(agg_rows[0].keys()), agg_rows)

    meta_payload = {
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "total_pipeline_wall_time_s": round(monotonic() - started_all, 3),
        "dataset_count": len(manifest_rows),
        "table_counts": dict(Counter(r["source_table"] for r in manifest_rows)),
        "validation_status_counts": dict(Counter(r["validation_status"] for r in manifest_rows)),
        "environment": env_info,
        "python": platform.python_version(),
        "os": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "configs": {
            "cpsat_threads": args.cpsat_threads,
            "cpsat_pass1_timeout_s": args.cpsat_pass1_timeout,
            "cpsat_pass2_timeout_s": args.cpsat_pass2_timeout,
            "cpsat_proof_timeout_s": args.cpsat_proof_timeout,
            "sat_timeout_s": args.sat_timeout,
            "sa_timeout_s": args.sa_timeout,
            "sa_seeds": list(sa_seeds),
        },
        "cpsat_best_113_summary": {
            "total": len(best_cp_list),
            "status_counts": dict(Counter(r["status_class"] for r in best_cp_list)),
            "valid_solutions": sum(1 for r in best_cp_list if r["status_class"] in ("OPT", "FEAS")),
        },
    }
    _write_json_atomic(out_dir / "run_metadata.json", meta_payload)
    print(f"Done in {monotonic() - started_all:.2f}s! Outputs written to {out_dir}", flush=True)


if __name__ == "__main__":
    main()
