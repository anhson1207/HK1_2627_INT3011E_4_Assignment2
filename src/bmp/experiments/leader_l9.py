"""Leader Phase L9: Full 113-Instance SAT Coverage, Encoding Optimization & Scalability Suite."""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import os
import platform
import resource
import statistics
import subprocess
import sys
import tomllib
from collections import Counter, defaultdict
from pathlib import Path
from time import monotonic
from typing import Any

import pysat

from bmp.core.benchmark_catalog import ALL_INSTANCES, resolve_raw_matrix_path
from bmp.core.bounds import identity_upper_bound
from bmp.core.graph import Graph
from bmp.core.solution import SolutionStatus, SolverResult
from bmp.core.validation import calculate_bandwidth, validate_solution
from bmp.encodings.estimator import (
    ResourceLimits,
    estimate_cnf_size,
    estimate_for_encoder,
    estimate_incremental_cnf_size,
    estimate_incremental_for_encoder,
)
from bmp.encodings.order import OrderEncoding
from bmp.encodings.pairwise import PairwiseEncoding
from bmp.io.readers import (
    CONVERSION_VERSION,
    MatrixMarketForensics,
    compute_graph_fingerprint,
    compute_topology_sha256,
    graph_from_matrix_market_forensics,
    inspect_matrix_market_forensics,
)
from bmp.solvers.sat.backends.cadical import CadicalBackend
from bmp.solvers.sat.incremental import IncrementalSATSolver
from bmp.solvers.sat.repeated import RepeatedSATSolver
from bmp.solvers.sat.search import (
    compute_initial_upper_bound,
    compute_lower_bound,
    extract_connected_components,
)

DATASET_113_FIELDS: tuple[str, ...] = (
    "instance",
    "table",
    "size_group",
    "tier",
    "official_benchmark",
    "validation_status",
    "source_sha256",
    "raw_file_path",
    "n",
    "m",
    "conversion_policy",
    "conversion_version",
    "topology_sha256",
    "graph_fingerprint",
    "topology_duplicate_of",
    "components",
    "isolated_vertices",
    "n_active",
    "largest_component_n",
    "certified_lb",
    "identity_ub",
    "rcm_ub",
    "rcm_tight_ub",
    "published_lb",
    "published_best",
    "notes",
)

PREFLIGHT_FIELDS: tuple[str, ...] = (
    "instance",
    "table",
    "tier",
    "official_benchmark",
    "n",
    "m",
    "n_active",
    "largest_component_n",
    "config_id",
    "config_era",
    "encoding",
    "encoding_variant",
    "amo",
    "strategy",
    "search_mode",
    "decompose_components",
    "eval_k",
    "primary_vars",
    "channeling_vars",
    "aux_vars",
    "total_vars",
    "fixed_clauses",
    "bandwidth_clauses",
    "total_clauses",
    "estimated_ram_mb",
    "preflight_status",
    "blocker_reason",
)

RUN_FIELDS: tuple[str, ...] = (
    "run_id",
    "stage",
    "instance",
    "table",
    "size_group",
    "tier",
    "official_benchmark",
    "graph_fingerprint",
    "conversion_policy",
    "n",
    "m",
    "n_active",
    "largest_component_n",
    "config_id",
    "encoding",
    "encoding_variant",
    "amo",
    "backend",
    "strategy",
    "search_mode",
    "decompose_components",
    "warm_start_mode",
    "symmetry_breaking",
    "time_limit_s",
    "memory_limit_mb",
    "solver_attempted",
    "sat_calls",
    "sat_solved_any",
    "sat_improved_initial_ub",
    "num_variables",
    "num_clauses",
    "preprocessing_time_s",
    "cnf_build_time_s",
    "solve_time_s",
    "total_wall_time_s",
    "peak_rss_mb",
    "solver_status",
    "proof_status",
    "proved_optimal",
    "found_permutation_valid",
    "valid_bandwidth",
    "initial_ub",
    "lower_bound",
    "upper_bound",
    "incumbent_source",
    "blocker_reason",
    "notes",
)

PER_INSTANCE_BEST_FIELDS: tuple[str, ...] = (
    "instance",
    "table",
    "size_group",
    "tier",
    "official_benchmark",
    "conversion_policy",
    "n",
    "m",
    "largest_component_n",
    "certified_lb",
    "rcm_ub",
    "rcm_tight_ub",
    "published_lb",
    "published_best",
    "sat_eligible_any_leader_cfg",
    "sat_attempted",
    "sat_solver_found_solution",
    "sat_improved_rcm",
    "proved_optimal",
    "best_sat_bandwidth",
    "best_pipeline_bandwidth",
    "incumbent_source",
    "best_sat_config",
    "final_status",
    "gap_sat_vs_published_best",
    "gap_pipeline_vs_published_best",
    "below_published_lb_flag",
    "blocker_reason",
)


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _write_csv_atomic(path: Path, fieldnames: tuple[str, ...] | list[str], rows: list[dict[str, Any]]) -> None:
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
    return "l9-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _estimate_ram_mb(num_vars: int, num_clauses: int) -> float:
    return round(32.0 + num_vars * 0.00012 + num_clauses * 0.000095, 2)


def _self_rss_mb() -> float:
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
    return round(rss / divisor, 2)


def _size_group(n: int) -> str:
    if n <= 150:
        return "Small (n<=150)"
    if n <= 500:
        return "Medium (151..500)"
    return "Large (n>500)"


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def audit_l9_environment(*, limits: ResourceLimits, memory_limit_mb: float) -> dict[str, Any]:
    """Record clean hardware/software metadata strictly for Leader L9 experiments."""
    cpu_brand = platform.processor() or platform.machine()
    ram_gb: float | None = None
    if platform.system() == "Darwin":
        try:
            cpu_brand = subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"], text=True).strip()
            ram_gb = round(int(subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip()) / (1024**3), 2)
        except Exception:
            pass
    elif Path("/proc/meminfo").is_file():
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                ram_gb = round(int(line.split()[1]) / (1024**2), 2)
                break

    backend = CadicalBackend()
    cadical_ver = backend.version
    backend.delete()
    return {
        "timestamp": _now_iso(),
        "git_branch": "dev/leader",
        "git_commit": _git_commit(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_model": cpu_brand,
        "cpu_cores": os.cpu_count(),
        "ram_gb": ram_gb,
        "pysat_version": getattr(pysat, "__version__", "unknown"),
        "cadical_backend": cadical_ver,
        "resource_limits": {
            "max_sat_variables": limits.max_variables,
            "max_sat_clauses": limits.max_clauses,
            "memory_limit_mb": memory_limit_mb,
            "threads": 1,
        },
    }


def _build_encoder(
    encoding: str,
    amo: str,
    *,
    variant: str = "baseline",
) -> PairwiseEncoding | OrderEncoding:
    enc = encoding.lower()
    if enc == "pairwise":
        if variant == "pigeonhole_support":
            return PairwiseEncoding(amo=amo, occupancy_mode="pigeonhole", bandwidth_mode="support")
        if variant == "pigeonhole_support_single":
            return PairwiseEncoding(amo=amo, occupancy_mode="pigeonhole", bandwidth_mode="support_single")
        if variant == "pigeonhole_conflict":
            return PairwiseEncoding(amo=amo, occupancy_mode="pigeonhole", bandwidth_mode="conflict")
        return PairwiseEncoding(amo=amo, occupancy_mode="both", bandwidth_mode="conflict")
    if enc == "order":
        if variant == "one_sided_compact":
            return OrderEncoding(amo=amo, channel_mode="one_sided", compact_boundary=True)
        if variant == "one_sided_fullb":
            return OrderEncoding(amo=amo, channel_mode="one_sided", compact_boundary=False)
        return OrderEncoding(amo=amo, channel_mode="full", compact_boundary=False)
    raise ValueError(f"Unsupported Leader encoding: {encoding}")


def build_l9_dataset_and_graphs(
    *,
    root: Path,
    provenance_path: Path,
    raw_dir: Path,
    output_dir: Path,
    use_cache: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Graph], dict[str, dict[str, Any]], dict[str, Any]]:
    """Construct all 113 Harwell-Boeing graphs cleanly while preserving Tier 1 vs Tier 2 separation."""
    cache_path = output_dir / "dataset_cache.json"
    if use_cache and cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if cached.get("conversion_version") == CONVERSION_VERSION and len(cached.get("dataset_rows", [])) == len(ALL_INSTANCES):
            dataset_rows = list(cached["dataset_rows"])
            mbeause_sens = dict(cached["mbeause_sens"])
            graphs_by_name: dict[str, Graph] = {}
            meta_by_name: dict[str, dict[str, Any]] = {}
            for row in dataset_rows:
                name = str(row["instance"])
                raw_path = raw_dir / f"{name}.mtx.gz"
                if not raw_path.exists():
                    resolved = resolve_raw_matrix_path(name, root=root)
                    if resolved is not None:
                        raw_path = resolved
                fx = inspect_matrix_market_forensics(raw_path)
                graphs_by_name[name] = graph_from_matrix_market_forensics(
                    fx, policy=str(row["conversion_policy"]), one_based=True
                )
                meta_by_name[name] = row
            return dataset_rows, graphs_by_name, meta_by_name, mbeause_sens

    prov_list = json.loads(provenance_path.read_text(encoding="utf-8"))
    prov_map = {str(e["instance"]): dict(e) for e in prov_list if isinstance(e, dict) and "instance" in e}

    dataset_rows: list[dict[str, Any]] = []
    graphs_by_name: dict[str, Graph] = {}
    meta_by_name: dict[str, dict[str, Any]] = {}
    seen_topo: dict[str, str] = {}
    mbeause_sens: dict[str, Any] = {}

    for name, cat_meta in ALL_INSTANCES.items():
        prov = prov_map.get(name, {})
        val_status = str(prov.get("validation_status", "UNKNOWN"))
        raw_path = raw_dir / f"{name}.mtx.gz"
        if not raw_path.exists():
            resolved = resolve_raw_matrix_path(name, root=root)
            if resolved is not None:
                raw_path = resolved
        if not raw_path.exists():
            raise FileNotFoundError(f"Missing raw benchmark matrix for {name}: {raw_path}")

        fx: MatrixMarketForensics = inspect_matrix_market_forensics(raw_path)
        if val_status == "READY":
            policy = "nonzero_union"
            tier = "TIER1_VERIFIED_CANONICAL"
            official = True
            notes = "Checksummed symmetric/mirrored READY instance"
        elif val_status == "NEEDS_VERIFICATION":
            policy = "stored_union"
            tier = "TIER2_EXPLORATORY_UNVERIFIED"
            official = False
            notes = f"Unsymmetric general matrix (asym={fx.asymmetric_pairs_nonzero}, explicit_offdiag_zeros={fx.offdiagonal_entries_zero}); exploratory stored_union view"
        else:
            policy = "nonzero_union"
            tier = "TIER2_EXPLORATORY_INVALID_DATA"
            official = False
            notes = f"INVALID_DATA provenance ({fx.rows} raw rows vs Table 8 n={cat_meta.n}); primary 496-vertex view + 492-isolated sensitivity"

        g = graph_from_matrix_market_forensics(fx, policy=policy, one_based=True)
        topo_sha = str(g.metadata["topology_sha256"])
        gfp = str(g.metadata["graph_fingerprint"])
        dup_of = seen_topo.get(topo_sha)
        if dup_of is None:
            seen_topo[topo_sha] = name

        comps, isolated = extract_connected_components(g)
        iso_cnt = len(isolated)
        n_active = g.order - iso_cnt
        max_comp_n = max((c.order for c in comps), default=(1 if g.order >= 1 else 0))
        comp_cnt = len(comps) + iso_cnt

        cert_lb = compute_lower_bound(g)
        id_ub, _ = identity_upper_bound(g)
        rcm_ub, _ = compute_initial_upper_bound(g, init_mode="rcm")
        rcm_tight_ub, _ = compute_initial_upper_bound(g, init_mode="rcm_tight")

        if name == "mbeause":
            iso_set = set(isolated)
            kept = [v for v in g.vertices if v not in iso_set]
            g_492 = Graph.from_edges(kept, g.edges, name="mbeause_492_sens")
            mbeause_sens = {
                "raw_496": {"n": g.order, "m": g.size, "isolated": isolated, "certified_lb": cert_lb, "rcm_ub": rcm_ub, "rcm_tight_ub": rcm_tight_ub},
                "drop4_492": {
                    "n": g_492.order,
                    "m": g_492.size,
                    "certified_lb": compute_lower_bound(g_492),
                    "rcm_ub": compute_initial_upper_bound(g_492, init_mode="rcm")[0],
                    "rcm_tight_ub": compute_initial_upper_bound(g_492, init_mode="rcm_tight")[0],
                    "topology_sha256": compute_topology_sha256(g_492),
                },
            }

        rel_raw = str(raw_path.relative_to(root)) if raw_path.is_relative_to(root) else str(raw_path)
        sha256 = str(prov.get("sha256") or hashlib.sha256(raw_path.read_bytes()).hexdigest())

        row = {
            "instance": name,
            "table": cat_meta.source_table,
            "size_group": _size_group(g.order),
            "tier": tier,
            "official_benchmark": official,
            "validation_status": val_status,
            "source_sha256": sha256,
            "raw_file_path": rel_raw,
            "n": g.order,
            "m": g.size,
            "conversion_policy": policy,
            "conversion_version": CONVERSION_VERSION,
            "topology_sha256": topo_sha,
            "graph_fingerprint": gfp,
            "topology_duplicate_of": dup_of or "",
            "components": comp_cnt,
            "isolated_vertices": iso_cnt,
            "n_active": n_active,
            "largest_component_n": max_comp_n,
            "certified_lb": cert_lb,
            "identity_ub": id_ub,
            "rcm_ub": rcm_ub,
            "rcm_tight_ub": rcm_tight_ub,
            "published_lb": cat_meta.paper_lb,
            "published_best": cat_meta.paper_best,
            "notes": notes,
        }
        dataset_rows.append(row)
        graphs_by_name[name] = g
        meta_by_name[name] = row

    _write_csv_atomic(output_dir / "dataset_113.csv", DATASET_113_FIELDS, dataset_rows)
    _write_json_atomic(
        output_dir / "dataset_cache.json",
        {
            "conversion_version": CONVERSION_VERSION,
            "dataset_rows": dataset_rows,
            "mbeause_sens": mbeause_sens,
        },
    )
    return dataset_rows, graphs_by_name, meta_by_name, mbeause_sens


L9_PREFLIGHT_CONFIGS: tuple[dict[str, Any], ...] = (
    # Baseline L8 configs (raw graph, unit linear)
    {"config_id": "base_pw_pw_rep_lin", "config_era": "L8_Baseline", "encoding": "pairwise", "variant": "baseline", "amo": "pairwise", "strategy": "repeated", "search_mode": "linear", "decompose": False},
    {"config_id": "base_pw_seq_rep_lin", "config_era": "L8_Baseline", "encoding": "pairwise", "variant": "baseline", "amo": "sequential", "strategy": "repeated", "search_mode": "linear", "decompose": False},
    {"config_id": "base_pw_seq_inc_lin", "config_era": "L8_Baseline", "encoding": "pairwise", "variant": "baseline", "amo": "sequential", "strategy": "incremental", "search_mode": "linear", "decompose": False},
    {"config_id": "base_ord_pw_rep_lin", "config_era": "L8_Baseline", "encoding": "order", "variant": "baseline", "amo": "pairwise", "strategy": "repeated", "search_mode": "linear", "decompose": False},
    {"config_id": "base_ord_seq_rep_lin", "config_era": "L8_Baseline", "encoding": "order", "variant": "baseline", "amo": "sequential", "strategy": "repeated", "search_mode": "linear", "decompose": False},
    {"config_id": "base_ord_seq_inc_lin", "config_era": "L8_Baseline", "encoding": "order", "variant": "baseline", "amo": "sequential", "strategy": "incremental", "search_mode": "linear", "decompose": False},
    # Optimized L9 configs (raw vs decomposed, binary/linear)
    {"config_id": "l9_ord_compact_seq_inc_bin_dec", "config_era": "L9_Optimized", "encoding": "order", "variant": "one_sided_compact", "amo": "sequential", "strategy": "incremental", "search_mode": "binary", "decompose": True},
    {"config_id": "l9_ord_compact_seq_rep_bin_dec", "config_era": "L9_Optimized", "encoding": "order", "variant": "one_sided_compact", "amo": "sequential", "strategy": "repeated", "search_mode": "binary", "decompose": True},
    {"config_id": "l9_ord_compact_seq_inc_lin_dec", "config_era": "L9_Optimized", "encoding": "order", "variant": "one_sided_compact", "amo": "sequential", "strategy": "incremental", "search_mode": "linear", "decompose": True},
    {"config_id": "l9_ord_compact_pw_rep_bin_dec", "config_era": "L9_Optimized", "encoding": "order", "variant": "one_sided_compact", "amo": "pairwise", "strategy": "repeated", "search_mode": "binary", "decompose": True},
    {"config_id": "l9_pw_pig_sup_seq_rep_bin_dec", "config_era": "L9_Optimized", "encoding": "pairwise", "variant": "pigeonhole_support", "amo": "sequential", "strategy": "repeated", "search_mode": "binary", "decompose": True},
    {"config_id": "l9_pw_pig_supsing_seq_rep_bin_dec", "config_era": "L9_Optimized", "encoding": "pairwise", "variant": "pigeonhole_support_single", "amo": "sequential", "strategy": "repeated", "search_mode": "binary", "decompose": True},
)


def evaluate_l9_preflight_113(
    *,
    dataset_rows: list[dict[str, Any]],
    graphs_by_name: dict[str, Graph],
    limits: ResourceLimits,
    memory_limit_mb: float,
    output_dir: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Run closed-form SAT preflight & resource gap analysis across all 113 instances."""
    pf_rows: list[dict[str, Any]] = []
    gap_rows: list[dict[str, Any]] = []

    for ds in dataset_rows:
        inst = str(ds["instance"])
        g = graphs_by_name[inst]
        rcm_ub = int(ds["rcm_ub"])
        lb = int(ds["certified_lb"])
        eval_k_full = max(lb, rcm_ub - 1) if g.edges else 0
        comps, _ = extract_connected_components(g)
        target_comp = comps[0] if comps else g
        eval_k_comp = max(0, min(eval_k_full, target_comp.order - 1)) if target_comp.edges else 0

        inst_gap_info: dict[str, Any] = {
            "instance": inst,
            "table": ds["table"],
            "tier": ds["tier"],
            "official_benchmark": ds["official_benchmark"],
            "n": ds["n"],
            "m": ds["m"],
            "n_active": ds["n_active"],
            "largest_component_n": ds["largest_component_n"],
            "eval_k": eval_k_full,
        }

        for cfg in L9_PREFLIGHT_CONFIGS:
            enc = _build_encoder(cfg["encoding"], cfg["amo"], variant=cfg["variant"])
            target_g = target_comp if cfg["decompose"] else g
            eval_k = eval_k_comp if cfg["decompose"] else eval_k_full
            if cfg["strategy"] == "incremental":
                est = estimate_incremental_for_encoder(
                    enc,
                    target_g,
                    initial_k=eval_k,
                    target_k=max(0, min(lb, eval_k)),
                    symmetry_breaking=True,
                    search_mode=cfg["search_mode"],
                )
            else:
                est = estimate_for_encoder(enc, target_g, k=eval_k, symmetry_breaking=True)
            ok, reason = limits.check(est)
            ram_mb = _estimate_ram_mb(est.num_variables, est.num_clauses)
            if ok and ram_mb > memory_limit_mb:
                ok = False
                reason = f"Estimated SAT solver RAM ({ram_mb:.1f} MiB) exceeds cap ({memory_limit_mb:.1f} MiB)"

            pf_status = "ELIGIBLE" if ok else "RESOURCE_LIMIT"
            pf_rows.append({
                "instance": inst,
                "table": ds["table"],
                "tier": ds["tier"],
                "official_benchmark": ds["official_benchmark"],
                "n": ds["n"],
                "m": ds["m"],
                "n_active": ds["n_active"],
                "largest_component_n": ds["largest_component_n"],
                "config_id": cfg["config_id"],
                "config_era": cfg["config_era"],
                "encoding": cfg["encoding"],
                "encoding_variant": cfg["variant"],
                "amo": cfg["amo"],
                "strategy": cfg["strategy"],
                "search_mode": cfg["search_mode"],
                "decompose_components": cfg["decompose"],
                "eval_k": eval_k,
                "primary_vars": est.num_original_vars,
                "channeling_vars": est.num_channeling_vars,
                "aux_vars": est.num_aux_vars,
                "total_vars": est.num_variables,
                "fixed_clauses": est.num_fixed_clauses,
                "bandwidth_clauses": est.num_bandwidth_clauses,
                "total_clauses": est.num_clauses,
                "estimated_ram_mb": ram_mb,
                "preflight_status": pf_status,
                "blocker_reason": "" if ok else str(reason),
            })

            if cfg["config_id"] == "base_ord_seq_rep_lin":
                inst_gap_info["l8_ord_seq_vars"] = est.num_variables
                inst_gap_info["l8_ord_seq_clauses"] = est.num_clauses
                inst_gap_info["l8_ord_seq_eligible"] = ok
            elif cfg["config_id"] == "l9_ord_compact_seq_inc_bin_dec":
                inst_gap_info["l9_ord_compact_vars"] = est.num_variables
                inst_gap_info["l9_ord_compact_clauses"] = est.num_clauses
                inst_gap_info["l9_ord_compact_eligible"] = ok
            elif cfg["config_id"] == "l9_pw_pig_supsing_seq_rep_bin_dec":
                inst_gap_info["l9_pw_supsing_vars"] = est.num_variables
                inst_gap_info["l9_pw_supsing_clauses"] = est.num_clauses
                inst_gap_info["l9_pw_supsing_eligible"] = ok
                inst_gap_info["l9_pw_supsing_ram_mb"] = ram_mb
                inst_gap_info["min_var_cap_needed"] = max(int(limits.max_variables or 0), est.num_variables)
                inst_gap_info["min_clause_cap_needed"] = max(int(limits.max_clauses or 0), est.num_clauses)
                inst_gap_info["l9_best_blocker_reason"] = "" if ok else str(reason)

        gap_rows.append(inst_gap_info)

    _write_csv_atomic(output_dir / "sat_preflight_113.csv", PREFLIGHT_FIELDS, pf_rows)
    if gap_rows:
        _write_csv_atomic(output_dir / "resource_gap_analysis.csv", list(gap_rows[0].keys()), gap_rows)
    return pf_rows, gap_rows


def _map_solver_status(
    res: SolverResult,
    *,
    validation_passed: bool | None,
    has_incumbent: bool,
) -> tuple[str, str, bool]:
    if res.status is SolutionStatus.OPTIMAL and validation_passed:
        return "OPTIMAL", "PROVED_OPTIMAL", True
    if res.status is SolutionStatus.FEASIBLE and validation_passed:
        return "FEASIBLE", "UNPROVED", False
    if res.status is SolutionStatus.TIMEOUT:
        st = "TIMEOUT_WITH_INCUMBENT" if (has_incumbent and validation_passed) else "TIMEOUT_NO_INCUMBENT"
        return st, "UNPROVED", False
    if res.status is SolutionStatus.SKIPPED:
        return "RESOURCE_LIMIT", "NOT_ATTEMPTED", False
    return "ERROR", "ERROR", False


def _execute_sat_spec(
    spec: dict[str, Any],
    *,
    graphs_by_name: dict[str, Graph],
    meta_by_name: dict[str, dict[str, Any]],
    limits: ResourceLimits,
    memory_limit_mb: float,
) -> dict[str, Any]:
    inst = str(spec["instance"])
    g = graphs_by_name[inst]
    ds = meta_by_name[inst]
    rid = str(spec["run_id"])

    encoding = str(spec["encoding"])
    variant = str(spec.get("encoding_variant", "baseline"))
    amo = str(spec["amo"])
    strategy = str(spec["strategy"])
    search_mode = str(spec["search_mode"])
    decompose = bool(spec.get("decompose_components", False))
    warm_mode = str(spec.get("warm_start_mode", "rcm"))
    sym = bool(spec.get("symmetry_breaking", True))
    tlim = float(spec["time_limit_s"])
    threshold_policy = str(spec.get("threshold_policy", "adaptive"))

    t_prep0 = monotonic()
    init_bw, init_perm = compute_initial_upper_bound(
        g,
        symmetry_breaking=sym,
        init_mode=warm_mode,
    )
    prep_s = monotonic() - t_prep0

    encoder = _build_encoder(encoding, amo, variant=variant)
    # Exact preflight check at target k before launching worker
    eval_k = max(0, min(int(ds["certified_lb"]), init_bw - 1)) if g.edges else 0
    comps, _ = extract_connected_components(g)
    target_g = comps[0] if (decompose and comps) else g
    target_k = max(0, min(eval_k, target_g.order - 1)) if target_g.edges else 0
    if strategy == "incremental":
        pre_est = estimate_incremental_for_encoder(
            encoder,
            target_g,
            initial_k=max(0, min(init_bw - 1, target_g.order - 1)),
            target_k=target_k,
            symmetry_breaking=sym,
            search_mode=search_mode,
        )
    else:
        pre_est = estimate_for_encoder(
            encoder,
            target_g,
            k=max(0, min(init_bw - 1, target_g.order - 1)),
            symmetry_breaking=sym,
        )
    ok_lim, lim_reason = limits.check(pre_est)
    est_ram = _estimate_ram_mb(pre_est.num_variables, pre_est.num_clauses)
    if ok_lim and est_ram > memory_limit_mb:
        ok_lim = False
        lim_reason = f"Estimated RAM ({est_ram:.1f} MiB) exceeds cap ({memory_limit_mb:.1f} MiB)"

    if not ok_lim:
        return {
            "run_id": rid,
            "stage": spec["stage"],
            "instance": inst,
            "table": ds["table"],
            "size_group": ds["size_group"],
            "tier": ds["tier"],
            "official_benchmark": ds["official_benchmark"],
            "graph_fingerprint": ds["graph_fingerprint"],
            "conversion_policy": ds["conversion_policy"],
            "n": g.order,
            "m": g.size,
            "n_active": ds["n_active"],
            "largest_component_n": ds["largest_component_n"],
            "config_id": spec["config_id"],
            "encoding": encoding,
            "encoding_variant": variant,
            "amo": amo,
            "backend": "cadical",
            "strategy": strategy,
            "search_mode": search_mode,
            "decompose_components": decompose,
            "warm_start_mode": warm_mode,
            "symmetry_breaking": sym,
            "time_limit_s": tlim,
            "memory_limit_mb": memory_limit_mb,
            "solver_attempted": False,
            "sat_calls": 0,
            "sat_solved_any": False,
            "sat_improved_initial_ub": False,
            "num_variables": pre_est.num_variables,
            "num_clauses": pre_est.num_clauses,
            "preprocessing_time_s": round(prep_s, 6),
            "cnf_build_time_s": None,
            "solve_time_s": None,
            "total_wall_time_s": None,
            "peak_rss_mb": None,
            "solver_status": "RESOURCE_LIMIT",
            "proof_status": "NOT_ATTEMPTED",
            "proved_optimal": False,
            "found_permutation_valid": None,
            "valid_bandwidth": None,
            "initial_ub": init_bw,
            "lower_bound": ds["certified_lb"],
            "upper_bound": init_bw,
            "incumbent_source": "HEURISTIC_FALLBACK",
            "blocker_reason": str(lim_reason),
            "notes": spec.get("notes", "Blocked before CNF allocation by ResourceLimits"),
        }

    if strategy == "repeated":
        solver = RepeatedSATSolver(
            encoder,
            backend_name="cadical",
            search_mode=search_mode,  # type: ignore[arg-type]
            threshold_policy=threshold_policy,  # type: ignore[arg-type]
            init_mode=warm_mode,
            decompose_components=decompose,
            certify_feasible_with_sat=bool(spec.get("certify_feasible_with_sat", False)),
        )
    else:
        solver = IncrementalSATSolver(
            encoder,
            backend_name="cadical",
            threshold_policy=threshold_policy,  # type: ignore[arg-type]
            search_mode=search_mode,  # type: ignore[arg-type]
            init_mode=warm_mode,
            decompose_components=decompose,
        )

    t0 = monotonic()
    res = solver.solve(
        g,
        timeout_seconds=tlim,
        heuristic_permutation=init_perm,
        symmetry_breaking=sym,
        limits=limits,
    )
    wall_s = monotonic() - t0 + prep_s
    md = dict(res.metadata or {})
    val_rep = validate_solution(g, res.permutation, claimed_bandwidth=res.bandwidth) if res.permutation else None
    val_ok = bool(val_rep is not None and val_rep.valid) if res.permutation else None
    bw = val_rep.actual_bandwidth if (val_ok and val_rep is not None) else None

    sat_solved_any = bool(md.get("sat_solved_any", False))
    trace = list(md.get("sat_trace", []))
    if not sat_solved_any and any(ev.get("outcome") == "SAT" for ev in trace):
        sat_solved_any = True
    sat_improved = bool(sat_solved_any and bw is not None and bw < init_bw)
    s_status, p_status, is_opt = _map_solver_status(
        res,
        validation_passed=val_ok,
        has_incumbent=bw is not None,
    )
    inc_src = str(md.get("incumbent_source") or ("SAT" if sat_solved_any else "HEURISTIC_FALLBACK"))
    if not sat_solved_any and inc_src == "SAT":
        inc_src = "HEURISTIC_FALLBACK"

    blocker = md.get("skipped_reason") or md.get("worker_reason")
    return {
        "run_id": rid,
        "stage": spec["stage"],
        "instance": inst,
        "table": ds["table"],
        "size_group": ds["size_group"],
        "tier": ds["tier"],
        "official_benchmark": ds["official_benchmark"],
        "graph_fingerprint": ds["graph_fingerprint"],
        "conversion_policy": ds["conversion_policy"],
        "n": g.order,
        "m": g.size,
        "n_active": ds["n_active"],
        "largest_component_n": ds["largest_component_n"],
        "config_id": spec["config_id"],
        "encoding": encoding,
        "encoding_variant": variant,
        "amo": amo,
        "backend": "cadical",
        "strategy": strategy,
        "search_mode": search_mode,
        "decompose_components": decompose,
        "warm_start_mode": warm_mode,
        "symmetry_breaking": sym,
        "time_limit_s": tlim,
        "memory_limit_mb": memory_limit_mb,
        "solver_attempted": bool(trace) or int(res.sat_calls or 0) > 0,
        "solver_call_started": bool(trace) or int(res.sat_calls or 0) > 0,
        "sat_calls": max(int(res.sat_calls or 0), len(trace)),
        "sat_solved_any": sat_solved_any,
        "sat_improved_initial_ub": sat_improved,
        "num_variables": res.num_variables if res.num_variables is not None else pre_est.num_variables,
        "num_clauses": res.num_clauses if res.num_clauses is not None else pre_est.num_clauses,
        "preprocessing_time_s": round(prep_s, 6),
        "cnf_build_time_s": round(float(res.encoding_time_s or 0.0), 6),
        "solve_time_s": round(float(res.solving_time_s or 0.0), 6),
        "total_wall_time_s": round(wall_s, 6),
        "peak_rss_mb": md.get("sampled_peak_memory_mb") or _self_rss_mb(),
        "solver_status": s_status,
        "proof_status": p_status,
        "proved_optimal": is_opt,
        "found_permutation_valid": val_ok,
        "valid_bandwidth": bw,
        "initial_ub": init_bw,
        "lower_bound": res.lower_bound,
        "upper_bound": res.upper_bound,
        "incumbent_source": inc_src,
        "witness_permutation_json": (
            json.dumps(dict(res.permutation), sort_keys=True)
            if spec.get("record_permutation") and sat_solved_any and val_ok and res.permutation is not None
            else ""
        ),
        "blocker_reason": str(blocker) if blocker else "",
        "notes": spec.get("notes", ""),
    }


def run_l9_campaign(
    *,
    config_path: Path = Path("configs/leader_l9_full113.toml"),
    stages: set[str] | None = None,
    resume: bool = True,
    max_batch_seconds: float | None = None,
    max_runs_in_batch: int | None = None,
    generate_plots: bool = True,
) -> dict[str, Any]:
    """Execute the complete Leader Phase L9 experimental pipeline with checkpoint/resume."""
    root = Path.cwd()
    cfg = tomllib.loads(config_path.read_text(encoding="utf-8"))["benchmark"]
    provenance_path = (root / cfg["provenance"]).resolve()
    raw_dir = (root / cfg["raw_dir"]).resolve()
    output_dir = (root / cfg["output_dir"]).resolve()
    l8_csv = (root / cfg["l8_runs_csv"]).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    memory_limit_mb = float(cfg["memory_limit_mb"])
    limits = ResourceLimits(
        max_variables=int(cfg["max_sat_variables"]),
        max_clauses=int(cfg["max_sat_clauses"]),
        timeout_seconds=None,
        memory_limit_mb=memory_limit_mb,
    )
    metadata = audit_l9_environment(limits=limits, memory_limit_mb=memory_limit_mb)
    _write_json_atomic(output_dir / "metadata.json", metadata)

    dataset_rows, graphs_by_name, meta_by_name, mbeause_sens = build_l9_dataset_and_graphs(
        root=root,
        provenance_path=provenance_path,
        raw_dir=raw_dir,
        output_dir=output_dir,
        use_cache=resume,
    )
    pf_rows, gap_rows = evaluate_l9_preflight_113(
        dataset_rows=dataset_rows,
        graphs_by_name=graphs_by_name,
        limits=limits,
        memory_limit_mb=memory_limit_mb,
        output_dir=output_dir,
    )

    checkpoint_path = output_dir / "checkpoint_runs.json"
    runs_by_id: dict[str, dict[str, Any]] = {}
    if resume and checkpoint_path.exists():
        for rec in json.loads(checkpoint_path.read_text(encoding="utf-8")):
            runs_by_id[str(rec["run_id"])] = rec

    specs: list[dict[str, Any]] = []

    def add_spec(**kw: Any) -> None:
        if kw["instance"] not in graphs_by_name:
            return
        kw["run_id"] = _stable_id({k: kw.get(k) for k in (
            "stage", "instance", "encoding", "encoding_variant", "amo", "strategy",
            "search_mode", "threshold_policy", "decompose_components",
            "warm_start_mode", "symmetry_breaking", "time_limit_s",
        )})
        specs.append(kw)

    # 1. Stage BASELINE_L8 (Task L9.3): 8 small/medium HB x 8 original L8 configurations
    t_base = float(cfg["baseline_timeout_seconds"])
    for inst in cfg["baseline_instances"]:
        for enc in ("pairwise", "order"):
            for amo in ("pairwise", "sequential"):
                for strat in ("repeated", "incremental"):
                    add_spec(
                        stage="BASELINE_L8",
                        instance=inst,
                        config_id=f"base_{enc[:3]}_{amo[:3]}_{strat[:3]}",
                        encoding=enc,
                        encoding_variant="baseline",
                        amo=amo,
                        strategy=strat,
                        search_mode="linear",
                        threshold_policy="unit",
                        decompose_components=False,
                        warm_start_mode="rcm",
                        symmetry_breaking=False,
                        time_limit_s=t_base,
                        notes="Pre-L9 baseline reference configuration",
                    )

    # 2. Stage ABLATION_ENCODING (Task L9.5): paired comparison of Pairwise & Order variants
    t_abl = float(cfg["ablation_timeout_seconds"])
    enc_variants = (
        ("pairwise", "baseline", "pw_both_conflict"),
        ("pairwise", "pigeonhole_support", "pw_pig_sup2"),
        ("pairwise", "pigeonhole_support_single", "pw_pig_sup1"),
        ("order", "baseline", "ord_full_fullb"),
        ("order", "one_sided_compact", "ord_onesided_compactb"),
    )
    for inst in cfg["ablation_instances"]:
        for enc, var, cid in enc_variants:
            add_spec(
                stage="ABLATION_ENCODING",
                instance=inst,
                config_id=cid,
                encoding=enc,
                encoding_variant=var,
                amo="sequential",
                strategy="repeated",
                search_mode="binary",
                threshold_policy="adaptive",
                decompose_components=False,
                warm_start_mode="rcm",
                symmetry_breaking=True,
                time_limit_s=t_abl,
                notes="Paired encoding comparison under Sequential AMO & Repeated Binary",
            )

    # 3. Stage ABLATION_AMO (Task L9.6): Pairwise AMO vs Sequential AMO under matched Order & Pairwise
    for inst in cfg["ablation_instances"]:
        for enc, var in (("order", "one_sided_compact"), ("pairwise", "pigeonhole_support")):
            for amo in ("pairwise", "sequential"):
                add_spec(
                    stage="ABLATION_AMO",
                    instance=inst,
                    config_id=f"amo_{enc[:3]}_{amo}",
                    encoding=enc,
                    encoding_variant=var,
                    amo=amo,
                    strategy="repeated",
                    search_mode="binary",
                    threshold_policy="adaptive",
                    decompose_components=False,
                    warm_start_mode="rcm",
                    symmetry_breaking=True,
                    time_limit_s=t_abl,
                    notes="Paired AMO comparison (Pairwise AMO vs Sequential Counter)",
                )

    # 4. Stage ABLATION_STRATEGY_SEARCH (Task L9.7): Repeated vs Incremental x Linear vs Binary
    for inst in cfg["ablation_instances"]:
        for strat in ("repeated", "incremental"):
            for smode in ("linear", "binary"):
                add_spec(
                    stage="ABLATION_STRATEGY_SEARCH",
                    instance=inst,
                    config_id=f"strat_{strat[:3]}_{smode[:3]}",
                    encoding="order",
                    encoding_variant="one_sided_compact",
                    amo="sequential",
                    strategy=strat,
                    search_mode=smode,
                    threshold_policy="adaptive",
                    decompose_components=False,
                    warm_start_mode="rcm",
                    symmetry_breaking=True,
                    time_limit_s=t_abl,
                    notes="Paired strategy x search mode comparison on Order Compact+Seq",
                )

    # 5. Stage ABLATION_WARM_START (Task L9.8): identity vs rcm vs rcm_tight
    for inst in cfg["warm_start_instances"]:
        for wmode in ("identity", "rcm", "rcm_tight"):
            add_spec(
                stage="ABLATION_WARM_START",
                instance=inst,
                config_id=f"warm_{wmode}",
                encoding="order",
                encoding_variant="one_sided_compact",
                amo="sequential",
                strategy="incremental",
                search_mode="binary",
                threshold_policy="adaptive",
                decompose_components=False,
                warm_start_mode=wmode,
                symmetry_breaking=True,
                time_limit_s=t_abl,
                notes="Paired warm-start comparison separating SAT solution vs heuristic fallback",
            )

    # 6. Stage CAMPAIGN_113_PASS1 (Task L9.9 Stage D): Run best eligible config across ALL 113 instances
    t_camp = float(cfg["campaign_timeout_seconds"])
    for ds in dataset_rows:
        inst = str(ds["instance"])
        max_comp = int(ds["largest_component_n"])
        if max_comp <= 408:
            # Order Compact + Sequential + Incremental Adaptive + Decomposition (2-lit clauses, fast propagation)
            add_spec(
                stage="CAMPAIGN_113_PASS1",
                instance=inst,
                config_id="l9_pass1_ord_compact_seq_inc_dec",
                encoding="order",
                encoding_variant="one_sided_compact",
                amo="sequential",
                strategy="incremental",
                search_mode="linear",
                threshold_policy="adaptive",
                decompose_components=True,
                warm_start_mode="rcm",
                symmetry_breaking=True,
                time_limit_s=t_camp,
                notes="Primary 113 campaign pass (Order Compact+Seq+Decomposed)",
            )
        else:
            # Medium/Large n_comp > 408: attempt Pairwise Pigeonhole Support Single + Seq where vars <= 500k
            add_spec(
                stage="CAMPAIGN_113_PASS1",
                instance=inst,
                config_id="l9_pass1_pw_supsing_seq_rep_dec",
                encoding="pairwise",
                encoding_variant="pigeonhole_support_single",
                amo="sequential",
                strategy="repeated",
                search_mode="binary",
                threshold_policy="adaptive",
                decompose_components=True,
                warm_start_mode="rcm",
                symmetry_breaking=True,
                time_limit_s=t_camp,
                notes="Primary 113 campaign pass (Pairwise Pigeonhole Support Single+Seq+Decomposed for n_comp>408)",
            )

    # Execute static stages with strict batch deadline
    batch_limit = float(cfg["max_batch_seconds"] if max_batch_seconds is None else max_batch_seconds)
    batch_start = monotonic()
    executed_this_batch = 0
    interrupted = False

    active_specs = [sp for sp in specs if stages is None or sp["stage"] in stages]
    for sp in active_specs:
        rid = str(sp["run_id"])
        if rid in runs_by_id:
            continue
        if max_runs_in_batch is not None and executed_this_batch >= max_runs_in_batch:
            interrupted = True
            break
        if (monotonic() - batch_start) >= batch_limit:
            interrupted = True
            break
        rec = _execute_sat_spec(
            sp,
            graphs_by_name=graphs_by_name,
            meta_by_name=meta_by_name,
            limits=limits,
            memory_limit_mb=memory_limit_mb,
        )
        runs_by_id[rid] = rec
        executed_this_batch += 1
        _write_json_atomic(checkpoint_path, list(runs_by_id.values()))
        print(
            f"[L9] +{executed_this_batch} | {sp['stage']} | {sp['instance']} | {sp['config_id']} "
            f"-> {rec['solver_status']} bw={rec['valid_bandwidth']} sat_solved={rec['sat_solved_any']}",
            flush=True,
        )

    # 7. Dynamic Stage TARGETED_RECOVERY_PASS2 (Task L9.9 Stage E):
    # Ensure EVERY ELIGIBLE instance (up to all 70/113) is genuinely attempted by CaDiCaL
    # using preflight-compatible Repeated Linear/Binary configs (recovering Pass-1 incremental caps & timeouts).
    t_rec = float(cfg["recovery_timeout_seconds"])
    dynamic_recovery_specs: list[dict[str, Any]] = []
    if (stages is None or "TARGETED_RECOVERY_PASS2" in stages) and not interrupted:
        sat_solved_insts = {
            r["instance"]
            for r in runs_by_id.values()
            if r["sat_solved_any"] is True
        }
        elig_cfgs_by_inst: dict[str, set[str]] = defaultdict(set)
        for pr in pf_rows:
            if pr["preflight_status"] == "ELIGIBLE":
                elig_cfgs_by_inst[str(pr["instance"])].add(str(pr["config_id"]))

        for ds in sorted(dataset_rows, key=lambda x: (int(x["largest_component_n"]), str(x["instance"]))):
            inst = str(ds["instance"])
            if inst in sat_solved_insts:
                continue
            elig_set = elig_cfgs_by_inst.get(inst, set())
            if not elig_set:
                continue
            max_comp = int(ds["largest_component_n"])
            candidates: list[tuple[str, str, str, str, str]] = []
            if "l9_ord_compact_seq_rep_bin_dec" in elig_set or max_comp <= 408:
                # Linear from rcm-1 excels when rcm is above B*; binary identity recovers when rcm==B* on small graphs
                candidates.append(("l9_rec_ord_rep_lin_rcm", "order", "one_sided_compact", "linear", "rcm"))
                if max_comp <= 120:
                    candidates.append(("l9_rec_ord_rep_bin_identity", "order", "one_sided_compact", "binary", "identity"))
            elif "l9_pw_pig_supsing_seq_rep_bin_dec" in elig_set or "l9_pw_pig_sup_seq_rep_bin_dec" in elig_set:
                candidates.append(("l9_rec_pw_supsing_lin_rcm", "pairwise", "pigeonhole_support_single", "linear", "rcm"))

            for cid, enc, var, smode, wmode in candidates:
                sp = {
                    "stage": "TARGETED_RECOVERY_PASS2",
                    "instance": inst,
                    "config_id": cid,
                    "encoding": enc,
                    "encoding_variant": var,
                    "amo": "sequential",
                    "strategy": "repeated",
                    "search_mode": smode,
                    "threshold_policy": "adaptive",
                    "decompose_components": True,
                    "warm_start_mode": wmode,
                    "symmetry_breaking": True,
                    "time_limit_s": t_rec,
                    "notes": f"Targeted recovery ({enc}:{var}, {smode}, {wmode} UB)",
                }
                sp["run_id"] = _stable_id({k: sp.get(k) for k in (
                    "stage", "instance", "encoding", "encoding_variant", "amo", "strategy",
                    "search_mode", "threshold_policy", "decompose_components",
                    "warm_start_mode", "symmetry_breaking", "time_limit_s",
                )})
                dynamic_recovery_specs.append(sp)

        for sp in dynamic_recovery_specs:
            rid = str(sp["run_id"])
            if rid in runs_by_id:
                continue
            if max_runs_in_batch is not None and executed_this_batch >= max_runs_in_batch:
                interrupted = True
                break
            if (monotonic() - batch_start) >= batch_limit:
                interrupted = True
                break
            rec = _execute_sat_spec(
                sp,
                graphs_by_name=graphs_by_name,
                meta_by_name=meta_by_name,
                limits=limits,
                memory_limit_mb=memory_limit_mb,
            )
            runs_by_id[rid] = rec
            executed_this_batch += 1
            _write_json_atomic(checkpoint_path, list(runs_by_id.values()))
            print(
                f"[L9 Rec] +{executed_this_batch} | {sp['instance']} | {sp['config_id']} "
                f"-> {rec['solver_status']} bw={rec['valid_bandwidth']} sat_solved={rec['sat_solved_any']}",
                flush=True,
            )

    # 8. Dynamic Stage EXTENDED_PROOF_PASS3 (Task L9.9 Stage F): longer timeout on small instances not yet OPTIMAL
    t_proof = float(cfg["proof_timeout_seconds"])
    dynamic_proof_specs: list[dict[str, Any]] = []
    if (stages is None or "EXTENDED_PROOF_PASS3" in stages) and not interrupted:
        proved_set = {
            r["instance"] for r in runs_by_id.values() if r.get("proved_optimal") is True
        }
        for inst in cfg["proof_candidates"]:
            if inst not in graphs_by_name or inst in proved_set:
                continue
            sp = {
                "stage": "EXTENDED_PROOF_PASS3",
                "instance": inst,
                "config_id": "l9_proof_ord_full_rep_lin_seq_tight",
                "encoding": "order",
                "encoding_variant": "baseline",
                "amo": "sequential",
                "strategy": "repeated",
                "search_mode": "linear",
                "threshold_policy": "adaptive",
                "decompose_components": True,
                "warm_start_mode": "rcm_tight",
                "symmetry_breaking": True,
                "time_limit_s": t_proof,
                "notes": "Extended optimality proof attempt (Order Full+Sequential+Repeated Linear+Tight UB)",
            }
            sp["run_id"] = _stable_id({k: sp.get(k) for k in (
                "stage", "instance", "encoding", "encoding_variant", "amo", "strategy",
                "search_mode", "threshold_policy", "decompose_components",
                "warm_start_mode", "symmetry_breaking", "time_limit_s",
            )})
            dynamic_proof_specs.append(sp)

        for sp in dynamic_proof_specs:
            rid = str(sp["run_id"])
            if rid in runs_by_id:
                continue
            if max_runs_in_batch is not None and executed_this_batch >= max_runs_in_batch:
                interrupted = True
                break
            if (monotonic() - batch_start) >= batch_limit:
                interrupted = True
                break
            rec = _execute_sat_spec(
                sp,
                graphs_by_name=graphs_by_name,
                meta_by_name=meta_by_name,
                limits=limits,
                memory_limit_mb=memory_limit_mb,
            )
            runs_by_id[rid] = rec
            executed_this_batch += 1
            _write_json_atomic(checkpoint_path, list(runs_by_id.values()))
            print(
                f"[L9 Proof] +{executed_this_batch} | {sp['instance']} -> {rec['solver_status']} "
                f"bw={rec['valid_bandwidth']} lb={rec['lower_bound']}",
                flush=True,
            )

    all_runs = list(runs_by_id.values())
    _write_json_atomic(checkpoint_path, all_runs)

    summary = export_l9_reports(
        dataset_rows=dataset_rows,
        pf_rows=pf_rows,
        gap_rows=gap_rows,
        all_runs=all_runs,
        l8_csv=l8_csv,
        mbeause_sens=mbeause_sens,
        metadata=metadata,
        output_dir=output_dir,
        planned_static=len(active_specs),
        planned_recovery=len(dynamic_recovery_specs),
        planned_proof=len(dynamic_proof_specs),
        executed_this_batch=executed_this_batch,
        interrupted=interrupted,
    )

    if generate_plots:
        from bmp.experiments.leader_l9_plots import create_l9_plots
        create_l9_plots(output_dir)

    return summary


def export_l9_reports(
    *,
    dataset_rows: list[dict[str, Any]],
    pf_rows: list[dict[str, Any]],
    gap_rows: list[dict[str, Any]],
    all_runs: list[dict[str, Any]],
    l8_csv: Path,
    mbeause_sens: dict[str, Any],
    metadata: dict[str, Any],
    output_dir: Path,
    planned_static: int = 0,
    planned_recovery: int = 0,
    planned_proof: int = 0,
    executed_this_batch: int = 0,
    interrupted: bool = False,
) -> dict[str, Any]:
    """Export all Task L9.14 deliverables accurately without mixing solver success with heuristic fallback."""
    by_stage: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in all_runs:
        by_stage[str(r["stage"])].append(r)

    _write_csv_atomic(output_dir / "baseline_results.csv", RUN_FIELDS, by_stage["BASELINE_L8"])
    _write_csv_atomic(output_dir / "encoding_comparison.csv", RUN_FIELDS, by_stage["ABLATION_ENCODING"])
    _write_csv_atomic(output_dir / "amo_comparison.csv", RUN_FIELDS, by_stage["ABLATION_AMO"])
    _write_csv_atomic(
        output_dir / "strategy_comparison.csv",
        RUN_FIELDS,
        by_stage["ABLATION_STRATEGY_SEARCH"],
    )
    _write_csv_atomic(
        output_dir / "search_comparison.csv",
        RUN_FIELDS,
        by_stage["ABLATION_STRATEGY_SEARCH"],
    )
    _write_csv_atomic(output_dir / "warm_start_comparison.csv", RUN_FIELDS, by_stage["ABLATION_WARM_START"])
    _write_csv_atomic(output_dir / "sat_runs_113.csv", RUN_FIELDS, all_runs)

    pf_by_inst: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for pr in pf_rows:
        pf_by_inst[str(pr["instance"])].append(pr)

    runs_by_inst: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in all_runs:
        runs_by_inst[str(r["instance"])].append(r)

    gap_by_inst = {str(gr["instance"]): gr for gr in gap_rows}

    per_inst_rows: list[dict[str, Any]] = []
    for ds in dataset_rows:
        inst = str(ds["instance"])
        rlist = runs_by_inst.get(inst, [])
        pfs = pf_by_inst.get(inst, [])
        eligible_any = any(p["preflight_status"] == "ELIGIBLE" for p in pfs)
        attempted = [r for r in rlist if bool(r["solver_attempted"])]
        sat_sols = [
            r for r in rlist
            if bool(r["sat_solved_any"]) and bool(r["found_permutation_valid"]) and r["valid_bandwidth"] is not None
        ]
        proved = [r for r in rlist if bool(r["proved_optimal"])]

        best_sat_row = min(
            sat_sols,
            key=lambda x: (int(x["valid_bandwidth"]), not bool(x["proved_optimal"]), float(x["total_wall_time_s"] or 1e9)),
        ) if sat_sols else None
        best_sat_bw = int(best_sat_row["valid_bandwidth"]) if best_sat_row else None
        rcm_ub = int(ds["rcm_ub"])
        rcm_tight = int(ds["rcm_tight_ub"])
        pipe_candidates = [rcm_ub, rcm_tight]
        if best_sat_bw is not None:
            pipe_candidates.append(best_sat_bw)
        for r in rlist:
            if bool(r["found_permutation_valid"]) and r["valid_bandwidth"] is not None:
                pipe_candidates.append(int(r["valid_bandwidth"]))
        best_pipe_bw = min(pipe_candidates)

        if proved:
            final_status = "OPTIMAL_PROVED"
            inc_src = "SAT" if best_sat_row else "BOUNDS_OPTIMALITY_CERTIFICATE"
        elif best_sat_bw is not None:
            final_status = "SAT_FEASIBLE"
            inc_src = "SAT"
        elif attempted:
            final_status = "TIMEOUT_NO_SAT_MODEL"
            inc_src = "HEURISTIC_FALLBACK"
        else:
            final_status = "RESOURCE_LIMIT"
            inc_src = "RESOURCE_LIMIT_FALLBACK"

        blocker = ""
        if final_status == "RESOURCE_LIMIT":
            blocker = str(gap_by_inst.get(inst, {}).get("l9_best_blocker_reason") or "ResourceLimits exceeded")
        elif final_status == "TIMEOUT_NO_SAT_MODEL":
            blocker = str(attempted[-1].get("blocker_reason") or "Wall-clock timeout before SAT model found")

        pub_lb = int(ds["published_lb"])
        pub_best = int(ds["published_best"])
        per_inst_rows.append({
            "instance": inst,
            "table": ds["table"],
            "size_group": ds["size_group"],
            "tier": ds["tier"],
            "official_benchmark": ds["official_benchmark"],
            "conversion_policy": ds["conversion_policy"],
            "n": ds["n"],
            "m": ds["m"],
            "largest_component_n": ds["largest_component_n"],
            "certified_lb": ds["certified_lb"],
            "rcm_ub": rcm_ub,
            "rcm_tight_ub": rcm_tight,
            "published_lb": pub_lb,
            "published_best": pub_best,
            "sat_eligible_any_leader_cfg": eligible_any,
            "sat_attempted": bool(attempted),
            "sat_solver_found_solution": best_sat_bw is not None,
            "sat_improved_rcm": bool(best_sat_bw is not None and best_sat_bw < rcm_ub),
            "proved_optimal": bool(proved),
            "best_sat_bandwidth": best_sat_bw,
            "best_pipeline_bandwidth": best_pipe_bw,
            "incumbent_source": inc_src,
            "best_sat_config": str(best_sat_row["config_id"]) if best_sat_row else "",
            "final_status": final_status,
            "gap_sat_vs_published_best": None if best_sat_bw is None else best_sat_bw - pub_best,
            "gap_pipeline_vs_published_best": best_pipe_bw - pub_best,
            "below_published_lb_flag": bool(best_sat_bw is not None and best_sat_bw < pub_lb),
            "blocker_reason": blocker,
        })

    _write_csv_atomic(output_dir / "per_instance_best.csv", PER_INSTANCE_BEST_FIELDS, per_inst_rows)

    # No-regression comparison (Before_L9_L8, After_L9_Leader, Ref_M3_8)
    l8_rows = list(csv.DictReader(l8_csv.open(encoding="utf-8", newline=""))) if l8_csv.exists() else []
    l8_solved_insts = {r["instance"] for r in l8_rows if str(r.get("sat_found_improvement")) == "True"}
    l8_opt_insts = {r["instance"] for r in l8_rows if str(r.get("status")) == "OPTIMAL"}

    no_reg_rows: list[dict[str, Any]] = [
        {
            "era": "Before_L9_L8_Official",
            "scope": "2 READY instances (29 runs)",
            "dataset_catalog": 113,
            "eligible_count": "max 53 (Order+Seq raw k=ub-1)",
            "sat_attempted_instances": len({r["instance"] for r in l8_rows}),
            "sat_solved_instances": len(l8_solved_insts),
            "proved_optimal_instances": len(l8_opt_insts),
            "error_count": sum(r.get("status") == "ERROR" for r in l8_rows),
            "notes": "Baseline Leader L8 (bcspwr01 OPTIMAL, bcsstk01 improved to 17)",
        },
        {
            "era": "After_L9_Leader_SAT",
            "scope": "Full 113 Harwell-Boeing (Tier 1 READY=54, Tier 2 Exploratory=59)",
            "dataset_catalog": 113,
            "eligible_count": sum(bool(r["sat_eligible_any_leader_cfg"]) for r in per_inst_rows),
            "sat_attempted_instances": sum(bool(r["sat_attempted"]) for r in per_inst_rows),
            "sat_solved_instances": sum(bool(r["sat_solver_found_solution"]) for r in per_inst_rows),
            "proved_optimal_instances": sum(bool(r["proved_optimal"]) for r in per_inst_rows),
            "error_count": sum(r["solver_status"] == "ERROR" for r in all_runs),
            "notes": "Leader SAT with Order Compact, Pairwise Pigeonhole+Support, Binary Incremental, Decomposition",
        },
        {
            "era": "Reference_M3_8_Product_AMO",
            "scope": "Coverage reference only (Order+Product+DRSA_Warm, not Leader AMO)",
            "dataset_catalog": 113,
            "eligible_count": 56,
            "sat_attempted_instances": 54,
            "sat_solved_instances": 54,
            "proved_optimal_instances": 0,
            "error_count": 0,
            "notes": "M3.8 used Member 3 Product AMO + DRSA warm-start (54/113 TIMEOUT_WITH_INCUMBENT, 59 RESOURCE_LIMIT)",
        },
    ]
    _write_csv_atomic(output_dir / "no_regression_report.csv", list(no_reg_rows[0].keys()), no_reg_rows)

    # Compute exact table / tier / size_group coverage breakdowns
    def _agg_slice(rows_slice: list[dict[str, Any]]) -> dict[str, int]:
        return {
            "total": len(rows_slice),
            "eligible": sum(bool(r["sat_eligible_any_leader_cfg"]) for r in rows_slice),
            "attempted": sum(bool(r["sat_attempted"]) for r in rows_slice),
            "sat_solved_feasible": sum(bool(r["sat_solver_found_solution"]) for r in rows_slice),
            "sat_improved_rcm": sum(bool(r["sat_improved_rcm"]) for r in rows_slice),
            "proved_optimal": sum(bool(r["proved_optimal"]) for r in rows_slice),
            "timeout_no_sat_model": sum(r["final_status"] == "TIMEOUT_NO_SAT_MODEL" for r in rows_slice),
            "resource_limit": sum(r["final_status"] == "RESOURCE_LIMIT" for r in rows_slice),
        }

    by_table = {tbl: _agg_slice([r for r in per_inst_rows if r["table"] == tbl]) for tbl in ("Table 6", "Table 7", "Table 8")}
    by_tier = {
        "Tier1_READY_54": _agg_slice([r for r in per_inst_rows if r["official_benchmark"]]),
        "Tier2_Exploratory_59": _agg_slice([r for r in per_inst_rows if not r["official_benchmark"]]),
    }
    by_size = {
        grp: _agg_slice([r for r in per_inst_rows if r["size_group"] == grp])
        for grp in ("Small (n<=150)", "Medium (151..500)", "Large (n>500)")
    }

    preflight_elig_by_cfg = {
        cfg["config_id"]: sum(
            1 for p in pf_rows if p["config_id"] == cfg["config_id"] and p["preflight_status"] == "ELIGIBLE"
        )
        for cfg in L9_PREFLIGHT_CONFIGS
    }

    sat_solved_total = sum(bool(r["sat_solver_found_solution"]) for r in per_inst_rows)
    opt_total = sum(bool(r["proved_optimal"]) for r in per_inst_rows)
    unresolved_total = len(per_inst_rows) - sat_solved_total

    summary = {
        "experiment_id": "leader_l9_full113_v1",
        "timestamp": _now_iso(),
        "metadata": metadata,
        "dataset_summary": {
            "total_instances": len(dataset_rows),
            "tier1_ready": sum(bool(r["official_benchmark"]) for r in dataset_rows),
            "tier2_needs_verification": sum(r["validation_status"] == "NEEDS_VERIFICATION" for r in dataset_rows),
            "tier2_invalid_data": sum(r["validation_status"] == "INVALID_DATA" for r in dataset_rows),
            "table_counts": dict(Counter(r["table"] for r in dataset_rows)),
            "unique_topologies": len({r["topology_sha256"] for r in dataset_rows}),
            "mbeause_sensitivity": mbeause_sens,
        },
        "batch_execution": {
            "total_run_records": len(all_runs),
            "planned_static_runs": planned_static,
            "planned_recovery_runs": planned_recovery,
            "planned_proof_runs": planned_proof,
            "executed_in_this_batch": executed_this_batch,
            "interrupted_by_batch_budget": interrupted,
            "validation_failures": sum(r["found_permutation_valid"] is False for r in all_runs),
            "execution_errors": sum(r["solver_status"] == "ERROR" for r in all_runs),
        },
        "preflight_eligible_by_config": preflight_elig_by_cfg,
        "overall_113_coverage": _agg_slice(per_inst_rows),
        "coverage_by_table": by_table,
        "coverage_by_tier": by_tier,
        "coverage_by_size_group": by_size,
        "verdict_line": (
            f"CaDiCaL found valid feasible SAT solutions on {sat_solved_total}/113 instances, "
            f"proved optimality on {opt_total}/113 instances, "
            f"and {unresolved_total}/113 instances remain unresolved (timeout or ResourceLimits)."
        ),
    }
    _write_json_atomic(output_dir / "summary.json", summary)

    repro_md = (
        "# Leader Phase L9 Full 113/113 Reproduction Guide\n\n"
        "```bash\n"
        ".venv/bin/python scripts/acquire_benchmark.py --max-instances 113\n"
        ".venv/bin/python scripts/run_leader_l9.py --config configs/leader_l9_full113.toml --plots\n"
        ".venv/bin/python -m pytest -p no:cacheprovider -vv tests/sat/test_leader_l9_full113.py\n"
        "```\n"
    )
    (output_dir / "reproduction.md").write_text(repro_md, encoding="utf-8")

    log_lines = [
        f"Leader Phase L9 Full 113/113 Log ({summary['timestamp']})",
        f"Git: {metadata['git_branch']}@{metadata['git_commit']} | PySAT {metadata['pysat_version']} | {metadata['cadical_backend']}",
        f"Dataset: 113/113 (Tier1={summary['dataset_summary']['tier1_ready']}, Tier2={113 - summary['dataset_summary']['tier1_ready']})",
        f"Total Run Records: {len(all_runs)} | Interrupted: {interrupted} | Errors: {summary['batch_execution']['execution_errors']} | Validation Failures: {summary['batch_execution']['validation_failures']}",
        summary["verdict_line"],
        f"By Table: {by_table}",
        f"By Tier: {by_tier}",
    ]
    (output_dir / "run_log.txt").write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    return summary


__all__ = [
    "L9_PREFLIGHT_CONFIGS",
    "audit_l9_environment",
    "build_l9_dataset_and_graphs",
    "evaluate_l9_preflight_113",
    "export_l9_reports",
    "run_l9_campaign",
]
