"""Phase M3.6 Unified Multi-Method Benchmark & Scientific Comparison Framework."""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import importlib.metadata as importlib_md
import json
import math
import os
import platform
import statistics
import subprocess
import sys
import tomllib
from collections import defaultdict, deque
from pathlib import Path
from time import monotonic
from typing import Any

from bmp.core.benchmark_catalog import (
    ALL_INSTANCES,
    VALIDATOR_VERSION,
    resolve_raw_matrix_path,
)
from bmp.core.generators import cycle_graph, path_graph
from bmp.core.graph import Graph
from bmp.core.solution import SolutionStatus, SolverResult
from bmp.core.validation import validate_solution
from bmp.encodings.estimator import ResourceLimits, estimate_cnf_size
from bmp.encodings.order import OrderEncoding
from bmp.encodings.pairwise import PairwiseEncoding
from bmp.experiments.member2_hb import _git_commit, _sat_backend_version, _self_rss_mb
from bmp.experiments.member2_m2_3 import (
    _graph_topology,
    _proof_comparison_tag,
    detect_commercial_licenses,
)
from bmp.heuristics import DRSASolver, RCMSolver, SimulatedAnnealingSolver
from bmp.io.readers import (
    CONVERSION_VERSION,
    OFFICIAL_CONVERSION_POLICY,
    compute_graph_fingerprint,
    compute_topology_sha256,
    inspect_matrix_market_forensics,
    read_matrix_market,
)
from bmp.solvers.brute_force import BruteForceSolver
from bmp.solvers.exact import CPLEXMIPSolver, CPOptimizerSolver, CPSATSolver, GurobiMIPSolver
from bmp.solvers.exact.cp_optimizer import _resolve_executable
from bmp.solvers.sat import IncrementalSATSolver, RepeatedSATSolver
from bmp.solvers.sat.search import compute_initial_upper_bound, compute_lower_bound

METHOD_LABELS: tuple[str, ...] = (
    "cadical",
    "glucose",
    "minisat",
    "gurobi",
    "cplex",
    "cp-sat",
    "cp-optimizer",
    "rcm",
    "sa",
    "drsa",
)

PREFLIGHT_M3_6_FIELDS: tuple[str, ...] = (
    "instance",
    "table",
    "n",
    "m",
    "dataset_sha256",
    "topology_sha256",
    "graph_fingerprint",
    "topology_duplicate_of",
    "conversion_policy",
    "conversion_version",
    "connected_components",
    "isolated_vertices",
    "max_degree",
    "initial_lb",
    "initial_ub",
    "dataset_ready",
    "family",
    "method",
    "solver_executable",
    "eligibility",
    "license_class",
    "estimated_vars",
    "estimated_constrs_or_clauses",
    "cpo_log2_search_space",
    "preflight_reason",
)

M3_6_FIELDS: tuple[str, ...] = (
    "experiment_id",
    "run_id",
    "stage",
    "study",
    "timestamp",
    "git_commit",
    "instance",
    "table",
    "dataset_sha256",
    "graph_fingerprint",
    "topology_sha256",
    "topology_duplicate_of",
    "conversion_policy",
    "conversion_version",
    "n",
    "m",
    "family",
    "method",
    "backend",
    "main_encoding",
    "amo_encoding",
    "strategy",
    "search_mode",
    "symmetry_breaking",
    "warm_start_mode",
    "seed",
    "threads",
    "solver_version",
    "license_class",
    "time_limit_seconds",
    "memory_limit_mb",
    "max_moves",
    "batch_id",
    "repetition_id",
    "status",
    "proof_status",
    "bandwidth",
    "objective",
    "lower_bound",
    "upper_bound",
    "objective_bound",
    "optimality_gap",
    "validation",
    "incumbent_source",
    "stop_reason",
    "loading_time_s",
    "preprocessing_time_s",
    "encoding_or_model_time_s",
    "solver_time_s",
    "total_wall_time_s",
    "peak_rss_mb",
    "SAT_calls",
    "CNF_variables",
    "CNF_clauses",
    "heuristic_moves",
    "paper_lb",
    "paper_best",
    "comparison_status",
)


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _write_csv_atomic(path: Path, fieldnames: tuple[str, ...] | list[str], rows: list[dict[str, Any]]) -> None:
    import io

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(fieldnames))
    writer.writeheader()
    for row in rows:
        writer.writerow({k: ("" if row.get(k) is None else row[k]) for k in fieldnames})
    _atomic_write_text(path, buf.getvalue())


def _pkg_version(name: str) -> str | None:
    try:
        return importlib_md.version(name)
    except importlib_md.PackageNotFoundError:
        return None


def _probe_cpo_environment() -> dict[str, Any]:
    docplex_ver = _pkg_version("docplex")
    exe_name = os.environ.get("BMP_CPO_EXECUTABLE", "cpoptimizer")
    exe_path = _resolve_executable(exe_name)
    if docplex_ver is None:
        return {
            "available": False,
            "classification": "PACKAGE_MISSING",
            "license_type": "PACKAGE_MISSING",
            "version": None,
            "executable_path": None,
            "max_log2_search_space": 0.0,
            "note": "docplex is not installed",
        }
    if exe_path is None:
        return {
            "available": False,
            "classification": "ENGINE_MISSING",
            "license_type": "ENGINE_MISSING",
            "version": docplex_ver,
            "executable_path": None,
            "max_log2_search_space": 0.0,
            "note": f"CP Optimizer binary {exe_name!r} not found",
        }
    # Verify actual solve on tiny graph and inspect solver_version + CE threshold heuristics
    cpo = CPOptimizerSolver()
    probe_small = cpo.solve(cycle_graph(5), timeout_seconds=3.0, symmetry_breaking=True)
    if probe_small.status is not SolutionStatus.OPTIMAL:
        return {
            "available": False,
            "classification": "ERROR",
            "license_type": "ENGINE_ERROR",
            "version": str(probe_small.metadata.get("solver_version") or docplex_ver),
            "executable_path": exe_path,
            "max_log2_search_space": 0.0,
            "note": str(probe_small.metadata.get("reason") or probe_small.status.value),
        }
    # Probe a 150-vertex path (~1084 bits search space > 1000-bit CE threshold) to detect CE cap dynamically
    probe_ce = cpo.solve(path_graph(150), timeout_seconds=1.5, symmetry_breaking=True)
    ce_reason = str(probe_ce.metadata.get("reason") or "")
    is_ce = "1016" in ce_reason or "2^1000" in ce_reason or "community edition" in ce_reason.lower()
    engine_ver = str(probe_small.metadata.get("solver_version") or "unknown")
    return {
        "available": True,
        "classification": "SOLVER_AVAILABLE_WITH_LIMITATIONS" if is_ce else "SOLVER_VERIFIED",
        "license_type": "COMMUNITY_EDITION_2P1000" if is_ce else "FULL_OR_UNRESTRICTED",
        "version": engine_ver,
        "docplex_version": docplex_ver,
        "executable_path": exe_path,
        "max_log2_search_space": 1000.0 if is_ce else None,
        "note": (
            "IBM CP Optimizer Community Edition (2^1000 search space limit; approx. n*log2(n) <= 1000)"
            if is_ce
            else "Unrestricted CP Optimizer runtime verified"
        ),
    }


def _probe_ortools_environment() -> dict[str, Any]:
    ver = _pkg_version("ortools")
    if ver is None:
        return {
            "available": False,
            "classification": "PACKAGE_MISSING",
            "license_type": "PACKAGE_MISSING",
            "version": None,
            "note": "ortools package not installed",
        }
    res = CPSATSolver(seed=17).solve(cycle_graph(5), timeout_seconds=3.0, symmetry_breaking=True, threads=1)
    if res.status is SolutionStatus.OPTIMAL and res.bandwidth == 2:
        return {
            "available": True,
            "classification": "SOLVER_VERIFIED",
            "license_type": "OPEN_SOURCE_APACHE2",
            "version": str(res.metadata.get("solver_version") or ver),
            "note": "OR-Tools CP-SAT verified on C5 oracle",
        }
    return {
        "available": False,
        "classification": "ERROR",
        "license_type": "ERROR",
        "version": ver,
        "note": str(res.metadata.get("reason") or res.status.value),
    }


def _probe_sat_backend(name: str) -> dict[str, Any]:
    try:
        res = RepeatedSATSolver(OrderEncoding("sequential"), backend_name=name).solve(
            cycle_graph(5), timeout_seconds=3.0, symmetry_breaking=True
        )
        ver = _sat_backend_version(name)
        ok = res.status is SolutionStatus.OPTIMAL and res.bandwidth == 2
        return {
            "available": ok,
            "classification": "SOLVER_VERIFIED" if ok else "ERROR",
            "license_type": "OPEN_SOURCE_PYTHON_SAT",
            "version": ver,
            "note": f"python-sat backend {name} verified on C5 oracle" if ok else str(res.status.value),
        }
    except Exception as exc:
        return {
            "available": False,
            "classification": "ERROR",
            "license_type": "UNAVAILABLE",
            "version": "unavailable",
            "note": str(exc),
        }


def audit_environment() -> dict[str, Any]:
    """Audit Git state, OS/CPU/RAM, installed packages, licenses, and live solver smoke checks."""

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

    mip_lic = detect_commercial_licenses()
    solvers = {
        "cadical": _probe_sat_backend("cadical"),
        "glucose": _probe_sat_backend("glucose"),
        "minisat": _probe_sat_backend("minisat"),
        "gurobi": {
            "available": mip_lic["gurobi"]["available"],
            "classification": (
                "SOLVER_AVAILABLE_WITH_LIMITATIONS"
                if mip_lic["gurobi"]["available"] and mip_lic["gurobi"]["license_type"] == "SIZE_LIMITED_EVAL"
                else ("SOLVER_VERIFIED" if mip_lic["gurobi"]["available"] else mip_lic["gurobi"]["license_type"])
            ),
            **mip_lic["gurobi"],
        },
        "cplex": {
            "available": mip_lic["cplex"]["available"],
            "classification": (
                "SOLVER_AVAILABLE_WITH_LIMITATIONS"
                if mip_lic["cplex"]["available"] and mip_lic["cplex"]["license_type"] == "COMMUNITY_EDITION"
                else ("SOLVER_VERIFIED" if mip_lic["cplex"]["available"] else mip_lic["cplex"]["license_type"])
            ),
            **mip_lic["cplex"],
        },
        "cp-sat": _probe_ortools_environment(),
        "cp-optimizer": _probe_cpo_environment(),
        "rcm": {
            "available": True,
            "classification": "SOLVER_VERIFIED",
            "license_type": "BUILTIN_PROJECT",
            "version": VALIDATOR_VERSION,
            "note": "Deterministic Reverse Cuthill-McKee baseline",
        },
        "sa": {
            "available": True,
            "classification": "SOLVER_VERIFIED",
            "license_type": "BUILTIN_PROJECT",
            "version": VALIDATOR_VERSION,
            "note": "Incremental-delta REX Simulated Annealing baseline",
        },
        "drsa": {
            "available": True,
            "classification": "SOLVER_VERIFIED",
            "license_type": "BUILTIN_PROJECT",
            "version": VALIDATOR_VERSION,
            "note": "Dual Representation Simulated Annealing (Torres-Jimenez et al. 2015)",
        },
    }
    return {
        "timestamp": _now_iso(),
        "git_commit": _git_commit(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_model": cpu_brand,
        "cpu_cores": os.cpu_count(),
        "ram_gb": ram_gb,
        "packages": {
            pkg: _pkg_version(pkg)
            for pkg in ("python-sat", "ortools", "gurobipy", "cplex", "docplex", "cnsplots", "matplotlib", "pandas", "numpy", "scipy", "pytest")
        },
        "solvers": solvers,
    }


def _small_oracle_instances() -> list[tuple[str, Graph, int]]:
    """Canonical small graphs whose exact optimal bandwidth is brute-force certified."""
    oracle = BruteForceSolver()
    specs = [
        ("oracle_p6", path_graph(6)),
        ("oracle_c6", cycle_graph(6)),
        (
            "oracle_chord_p6",
            Graph.from_edges(range(1, 7), [(1, 2), (2, 3), (3, 4), (4, 5), (5, 6), (1, 3)], name="oracle_chord_p6"),
        ),
        (
            "oracle_grid3x3",
            Graph.from_edges(
                range(1, 10),
                [(1, 2), (2, 3), (4, 5), (5, 6), (7, 8), (8, 9), (1, 4), (4, 7), (2, 5), (5, 8), (3, 6), (6, 9)],
                name="oracle_grid3x3",
            ),
        ),
    ]
    out: list[tuple[str, Graph, int]] = []
    for name, base_g in specs:
        fp = compute_graph_fingerprint(base_g, conversion_policy="small_oracle")
        topo = compute_topology_sha256(base_g)
        g = Graph(
            base_g.vertices,
            base_g.edges,
            name=name,
            metadata={
                **base_g.metadata,
                "conversion_policy": "small_oracle",
                "conversion_version": CONVERSION_VERSION,
                "topology_sha256": topo,
                "graph_fingerprint": fp,
            },
        )
        res = oracle.solve(g)
        if res.status is not SolutionStatus.OPTIMAL or res.bandwidth is None:
            raise RuntimeError(f"BruteForce oracle failed on {name}")
        out.append((name, g, int(res.bandwidth)))
    return out


def _cpo_search_bits(n: int) -> float:
    return float(n + 1) * math.log2(max(2, n))


def run_preflight_54(
    *,
    root: Path,
    provenance_path: Path,
    raw_dir: Path,
    output_dir: Path,
    env_info: dict[str, Any],
    max_sat_vars: int = 500_000,
    max_sat_clauses: int = 2_500_000,
    max_cp_vars: int = 2000,
    max_cp_constrs: int = 25000,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, tuple[Graph, float]]]:
    """Audit all 54 READY canonical instances across all 10 method labels."""

    prov_entries: list[dict[str, Any]] = json.loads(provenance_path.read_text(encoding="utf-8"))
    if len(prov_entries) != 113:
        raise ValueError(f"Expected 113 provenance entries, found {len(prov_entries)}")

    ready_entries = sorted(
        (e for e in prov_entries if e["validation_status"] == "READY"),
        key=lambda e: (str(e["source_table"]), int(e["n"]), str(e["instance"])),
    )
    if len(ready_entries) != 54:
        raise ValueError(f"Expected 54 READY instances in M3.5 provenance, found {len(ready_entries)}")

    # Ensure strictly non-READY instances are blocked
    non_ready = {e["instance"] for e in prov_entries if e["validation_status"] != "READY"}
    assert len(non_ready) == 59

    sat_limits = ResourceLimits(max_variables=max_sat_vars, max_clauses=max_sat_clauses)
    solvers = env_info["solvers"]
    preflight_rows: list[dict[str, Any]] = []
    ready_meta_map: dict[str, dict[str, Any]] = {}
    loaded_graphs: dict[str, tuple[Graph, float]] = {}

    for entry in ready_entries:
        inst = str(entry["instance"])
        meta = ALL_INSTANCES[inst]
        raw_path = raw_dir / f"{inst}.mtx.gz"
        if not raw_path.is_file():
            resolved = resolve_raw_matrix_path(inst, root=root)
            if resolved is None:
                raise FileNotFoundError(f"Raw archive missing for READY instance {inst}")
            raw_path = resolved

        t0 = monotonic()
        actual_sha = hashlib.sha256(raw_path.read_bytes()).hexdigest()
        if actual_sha != str(entry["sha256"]):
            raise ValueError(f"SHA-256 mismatch on READY instance {inst}: {actual_sha} != {entry['sha256']}")

        forensics = inspect_matrix_market_forensics(raw_path)
        if forensics.status != "READY":
            raise ValueError(f"Instance {inst} failed Matrix Market READY audit: {forensics.status}")
        graph = read_matrix_market(raw_path)
        load_s = monotonic() - t0

        topo = str(graph.metadata["topology_sha256"])
        fp = str(graph.metadata["graph_fingerprint"])
        if graph.order != meta.n or graph.size != int(entry["m"]):
            raise ValueError(f"Dimension mismatch on {inst}: ({graph.order}, {graph.size}) vs ({meta.n}, {entry['m']})")
        if "topology_sha256" in entry and entry["topology_sha256"] != topo:
            raise ValueError(f"topology_sha256 mismatch on {inst}")
        if "graph_fingerprint" in entry and entry["graph_fingerprint"] != fp:
            raise ValueError(f"graph_fingerprint mismatch on {inst}")

        components, isolated, max_deg = _graph_topology(graph)
        init_lb = compute_lower_bound(graph)
        init_ub, _ = compute_initial_upper_bound(graph, symmetry_breaking=True)
        ord_seq = estimate_cnf_size(graph, encoding="order", amo="sequential", symmetry_breaking=True)
        sat_ok, sat_reason = sat_limits.check(ord_seq)

        mip_vars = graph.order ** 2 + 1
        mip_constrs = 2 * graph.order + 2 * graph.size + 1
        cp_vars = graph.order + 1
        cpsat_constrs = 2 * graph.size + (2 if graph.order >= 2 else 0)
        cpo_constrs = graph.size + (2 if graph.order >= 2 else 0)
        cpo_bits = round(_cpo_search_bits(graph.order), 2)

        ready_meta_map[inst] = {
            **entry,
            "canonical_path": str(raw_path),
            "components": components,
            "isolated": isolated,
            "max_degree": max_deg,
            "initial_lb": init_lb,
            "initial_ub": init_ub,
            "ord_seq_vars": ord_seq.num_variables,
            "ord_seq_clauses": ord_seq.num_clauses,
            "mip_vars": mip_vars,
            "mip_constrs": mip_constrs,
            "cp_vars": cp_vars,
            "cpsat_constrs": cpsat_constrs,
            "cpo_constrs": cpo_constrs,
            "cpo_log2_search_space": cpo_bits,
            "paper_lb": meta.paper_lb,
            "paper_best": meta.paper_best,
        }
        loaded_graphs[inst] = (graph, load_s)

        for method in METHOD_LABELS:
            s_info = solvers[method]
            s_exec = bool(s_info["available"])
            lic_cls = str(s_info["license_type"])
            if method in ("cadical", "glucose", "minisat"):
                fam = "SAT"
                est_v, est_c = ord_seq.num_variables, ord_seq.num_clauses
                if not s_exec:
                    elig, reason = "UNAVAILABLE", str(s_info["note"])
                elif not sat_ok:
                    elig, reason = "RESOURCE_LIMIT", str(sat_reason)
                else:
                    elig, reason = "ELIGIBLE", "Order+Sequential CNF within ResourceLimits"
            elif method in ("gurobi", "cplex"):
                fam = "MIP"
                est_v, est_c = mip_vars, mip_constrs
                cap_v = s_info.get("max_variables")
                cap_c = s_info.get("max_constraints")
                if not s_exec:
                    elig, reason = "UNAVAILABLE", str(s_info["note"])
                elif (cap_v is not None and mip_vars > cap_v) or (cap_c is not None and mip_constrs > cap_c):
                    elig, reason = "BLOCKED_LICENSE", f"{method} {lic_cls} cap ({cap_v} vars / {cap_c} constrs) exceeded ({mip_vars}/{mip_constrs})"
                else:
                    elig, reason = "ELIGIBLE", f"MIP {mip_vars} vars, {mip_constrs} constrs within {lic_cls}"
            elif method == "cp-sat":
                fam = "CP"
                est_v, est_c = cp_vars, cpsat_constrs
                if not s_exec:
                    elig, reason = "UNAVAILABLE", str(s_info["note"])
                elif cp_vars > max_cp_vars or cpsat_constrs > max_cp_constrs:
                    elig, reason = "RESOURCE_LIMIT", f"Exceeds configured CP guard ({cp_vars}/{cpsat_constrs})"
                else:
                    elig, reason = "ELIGIBLE", f"OR-Tools CP-SAT {cp_vars} vars, {cpsat_constrs} constrs"
            elif method == "cp-optimizer":
                fam = "CP"
                est_v, est_c = cp_vars, cpo_constrs
                max_bits = s_info.get("max_log2_search_space")
                if not s_exec:
                    elig, reason = "UNAVAILABLE", str(s_info["note"])
                elif max_bits is not None and cpo_bits > float(max_bits):
                    elig, reason = "BLOCKED_LICENSE", f"CPO Community Edition 2^1000 limit exceeded (~2^{cpo_bits:.1f} search space for n={graph.order})"
                else:
                    elig, reason = "ELIGIBLE", f"IBM CP Optimizer ~2^{cpo_bits:.1f} search space within CE threshold"
            else:
                fam = "Heuristic"
                est_v, est_c = graph.order, graph.size
                elig, reason = "ELIGIBLE", f"O(n+m) memory/delta evaluation (bounded for SA/DRSA)"

            preflight_rows.append(
                {
                    "instance": inst,
                    "table": meta.source_table,
                    "n": graph.order,
                    "m": graph.size,
                    "dataset_sha256": actual_sha,
                    "topology_sha256": topo,
                    "graph_fingerprint": fp,
                    "topology_duplicate_of": entry.get("topology_duplicate_of"),
                    "conversion_policy": OFFICIAL_CONVERSION_POLICY,
                    "conversion_version": CONVERSION_VERSION,
                    "connected_components": components,
                    "isolated_vertices": isolated,
                    "max_degree": max_deg,
                    "initial_lb": init_lb,
                    "initial_ub": init_ub,
                    "dataset_ready": True,
                    "family": fam,
                    "method": method,
                    "solver_executable": s_exec,
                    "eligibility": elig,
                    "license_class": lic_cls,
                    "estimated_vars": est_v,
                    "estimated_constrs_or_clauses": est_c,
                    "cpo_log2_search_space": cpo_bits if method == "cp-optimizer" else None,
                    "preflight_reason": reason,
                }
            )

    _write_csv_atomic(output_dir / "preflight_54.csv", PREFLIGHT_M3_6_FIELDS, preflight_rows)
    return preflight_rows, ready_meta_map, loaded_graphs


def _deterministic_run_id(spec: dict[str, Any]) -> str:
    key = "|".join(
        str(spec.get(k, ""))
        for k in (
            "stage",
            "study",
            "instance",
            "family",
            "method",
            "backend",
            "main_encoding",
            "amo_encoding",
            "strategy",
            "search_mode",
            "symmetry_breaking",
            "warm_start_mode",
            "seed",
            "threads",
            "time_limit_seconds",
            "max_moves",
            "heuristic_variant",
        )
    )
    return "m36-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def build_experiment_plan(
    cfg: dict[str, Any],
    ready_meta_map: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build deterministic multi-stage M3.6 benchmark plan (Stages A-E)."""

    plan: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    def add(spec: dict[str, Any]) -> None:
        rid = _deterministic_run_id(spec)
        if rid in seen_ids:
            return
        seen_ids.add(rid)
        spec["run_id"] = rid
        plan.append(spec)

    rep_instances = [i for i in cfg["representative_instances"] if i in ready_meta_map]
    sat_instances = [i for i in cfg["sat_study_instances"] if i in ready_meta_map]
    sat_amo_instances = [i for i in cfg["sat_amo_study_instances"] if i in ready_meta_map]
    ext_instances = [i for i in cfg["extended_instances"] if i in ready_meta_map]
    all_ready = list(ready_meta_map.keys())

    primary_seed = int(cfg["primary_seed"])
    stability_seeds = [int(s) for s in cfg["stability_seeds"]]
    threads = int(cfg["threads"])
    t_small = float(cfg["small_oracle_timeout_seconds"])
    t_heur = float(cfg["heuristic_timeout_seconds"])
    t_heur_ext = float(cfg["heuristic_extended_timeout_seconds"])
    t_exact = float(cfg["exact_timeout_seconds"])
    t_sat = float(cfg["sat_study_timeout_seconds"])
    t_ext = float(cfg["extended_timeout_seconds"])

    # STAGE A: SmallOracle cross-method correctness on brute-force verified graphs
    for oracle_name, _, _ in _small_oracle_instances():
        for b in ("cadical", "glucose", "minisat"):
            add({
                "stage": "Stage_A_SmallOracle", "study": "oracle_sat", "instance": oracle_name, "is_oracle": True,
                "family": "SAT", "method": b, "backend": b, "main_encoding": "order", "amo_encoding": "sequential",
                "strategy": "incremental", "search_mode": "linear", "symmetry_breaking": True,
                "warm_start_mode": "NO_WARM_START", "seed": primary_seed, "threads": 1,
                "time_limit_seconds": t_small, "max_moves": None, "heuristic_variant": "",
            })
        for mip in ("gurobi", "cplex"):
            add({
                "stage": "Stage_A_SmallOracle", "study": "oracle_mip", "instance": oracle_name, "is_oracle": True,
                "family": "MIP", "method": mip, "backend": mip, "main_encoding": "assignment_mip", "amo_encoding": None,
                "strategy": "exact", "search_mode": "branch_and_bound", "symmetry_breaking": True,
                "warm_start_mode": "NO_WARM_START", "seed": primary_seed, "threads": 1,
                "time_limit_seconds": t_small, "max_moves": None, "heuristic_variant": "",
            })
        for cp in ("cp-sat", "cp-optimizer"):
            add({
                "stage": "Stage_A_SmallOracle", "study": "oracle_cp", "instance": oracle_name, "is_oracle": True,
                "family": "CP", "method": cp, "backend": cp, "main_encoding": "alldiff_cp", "amo_encoding": None,
                "strategy": "exact", "search_mode": "cp_search", "symmetry_breaking": True,
                "warm_start_mode": "NO_WARM_START", "seed": primary_seed, "threads": 1,
                "time_limit_seconds": t_small, "max_moves": None, "heuristic_variant": "",
            })
        add({
            "stage": "Stage_A_SmallOracle", "study": "oracle_heuristic", "instance": oracle_name, "is_oracle": True,
            "family": "Heuristic", "method": "rcm", "backend": "rcm", "main_encoding": None, "amo_encoding": None,
            "strategy": "constructive", "search_mode": "bfs_reverse", "symmetry_breaking": False,
            "warm_start_mode": "NONE", "seed": None, "threads": 1,
            "time_limit_seconds": t_small, "max_moves": None, "heuristic_variant": "DETERMINISTIC",
        })
        add({
            "stage": "Stage_A_SmallOracle", "study": "oracle_heuristic", "instance": oracle_name, "is_oracle": True,
            "family": "Heuristic", "method": "sa", "backend": "sa", "main_encoding": None, "amo_encoding": None,
            "strategy": "single_rep_sa", "search_mode": "rex", "symmetry_breaking": False,
            "warm_start_mode": "RCM_INIT", "seed": primary_seed, "threads": 1,
            "time_limit_seconds": t_small, "max_moves": 5000, "heuristic_variant": "BASELINE",
        })
        add({
            "stage": "Stage_A_SmallOracle", "study": "oracle_heuristic", "instance": oracle_name, "is_oracle": True,
            "family": "Heuristic", "method": "drsa", "backend": "drsa", "main_encoding": None, "amo_encoding": None,
            "strategy": "dual_rep_sa", "search_mode": "rex_nex_rot", "symmetry_breaking": False,
            "warm_start_mode": "RCM_INIT", "seed": primary_seed, "threads": 1,
            "time_limit_seconds": t_small, "max_moves": 5000, "heuristic_variant": "MODIFIED_VARIANT",
        })

    # STAGE B: Heuristic 54 READY coverage + multi-seed stability on representative 10
    for inst in all_ready:
        add({
            "stage": "Stage_B_Heuristic_54", "study": "heuristic_coverage_54", "instance": inst, "is_oracle": False,
            "family": "Heuristic", "method": "rcm", "backend": "rcm", "main_encoding": None, "amo_encoding": None,
            "strategy": "constructive", "search_mode": "bfs_reverse", "symmetry_breaking": False,
            "warm_start_mode": "NONE", "seed": None, "threads": 1,
            "time_limit_seconds": 5.0, "max_moves": None, "heuristic_variant": "DETERMINISTIC",
        })
        for seed in (stability_seeds if inst in rep_instances else [primary_seed]):
            st_study = "heuristic_stability_3seed" if inst in rep_instances and seed != primary_seed else "heuristic_coverage_54"
            add({
                "stage": "Stage_B_Heuristic_54", "study": st_study, "instance": inst, "is_oracle": False,
                "family": "Heuristic", "method": "sa", "backend": "sa", "main_encoding": None, "amo_encoding": None,
                "strategy": "single_rep_sa", "search_mode": "rex", "symmetry_breaking": False,
                "warm_start_mode": "RCM_INIT", "seed": seed, "threads": 1,
                "time_limit_seconds": t_heur, "max_moves": 10_000_000, "heuristic_variant": "BASELINE",
            })
            add({
                "stage": "Stage_B_Heuristic_54", "study": st_study, "instance": inst, "is_oracle": False,
                "family": "Heuristic", "method": "drsa", "backend": "drsa", "main_encoding": None, "amo_encoding": None,
                "strategy": "dual_rep_sa", "search_mode": "rex_nex_rot", "symmetry_breaking": False,
                "warm_start_mode": "RANDOM_INIT", "seed": seed, "threads": 1,
                "time_limit_seconds": t_heur, "max_moves": None, "heuristic_variant": "PAPER_FAITHFUL",
            })
            add({
                "stage": "Stage_B_Heuristic_54", "study": st_study, "instance": inst, "is_oracle": False,
                "family": "Heuristic", "method": "drsa", "backend": "drsa", "main_encoding": None, "amo_encoding": None,
                "strategy": "dual_rep_sa", "search_mode": "rex_nex_rot", "symmetry_breaking": False,
                "warm_start_mode": "RCM_INIT", "seed": seed, "threads": 1,
                "time_limit_seconds": t_heur, "max_moves": None, "heuristic_variant": "MODIFIED_VARIANT",
            })

    # STAGE C: Exact Baseline + CP/MIP/SAT Cross-Family on 10 Representative READY Instances
    for inst in rep_instances:
        for warm in ("NO_WARM_START", "SHARED_RCM_WARM"):
            add({
                "stage": "Stage_C_Exact_Baseline", "study": "cross_family_baseline", "instance": inst, "is_oracle": False,
                "family": "SAT", "method": "cadical", "backend": "cadical", "main_encoding": "order",
                "amo_encoding": "sequential", "strategy": "incremental", "search_mode": "linear",
                "symmetry_breaking": True, "warm_start_mode": warm, "seed": primary_seed,
                "threads": threads, "time_limit_seconds": t_exact, "max_moves": None, "heuristic_variant": "",
            })
            add({
                "stage": "Stage_C_Exact_Baseline", "study": "cross_family_baseline", "instance": inst, "is_oracle": False,
                "family": "CP", "method": "cp-sat", "backend": "cp-sat", "main_encoding": "alldiff_cp",
                "amo_encoding": None, "strategy": "exact", "search_mode": "cp_search",
                "symmetry_breaking": True, "warm_start_mode": warm, "seed": primary_seed,
                "threads": threads, "time_limit_seconds": t_exact, "max_moves": None, "heuristic_variant": "",
            })
            add({
                "stage": "Stage_C_Exact_Baseline", "study": "cross_family_baseline", "instance": inst, "is_oracle": False,
                "family": "CP", "method": "cp-optimizer", "backend": "cp-optimizer", "main_encoding": "alldiff_cp",
                "amo_encoding": None, "strategy": "exact", "search_mode": "cp_search",
                "symmetry_breaking": True, "warm_start_mode": warm, "seed": primary_seed,
                "threads": threads, "time_limit_seconds": t_exact, "max_moves": None, "heuristic_variant": "",
            })
        add({
            "stage": "Stage_C_Exact_Baseline", "study": "cross_family_baseline", "instance": inst, "is_oracle": False,
            "family": "CP", "method": "cp-sat", "backend": "cp-sat", "main_encoding": "alldiff_cp",
            "amo_encoding": None, "strategy": "exact", "search_mode": "cp_search",
            "symmetry_breaking": True, "warm_start_mode": "SHARED_DRSA_WARM", "seed": primary_seed,
            "threads": threads, "time_limit_seconds": t_exact, "max_moves": None, "heuristic_variant": "",
        })
        add({
            "stage": "Stage_C_Exact_Baseline", "study": "cross_family_baseline", "instance": inst, "is_oracle": False,
            "family": "MIP", "method": "gurobi", "backend": "gurobi", "main_encoding": "assignment_mip",
            "amo_encoding": None, "strategy": "exact", "search_mode": "branch_and_bound",
            "symmetry_breaking": True, "warm_start_mode": "NO_WARM_START", "seed": primary_seed,
            "threads": threads, "time_limit_seconds": t_exact, "max_moves": None, "heuristic_variant": "",
        })
        add({
            "stage": "Stage_C_Exact_Baseline", "study": "cross_family_baseline", "instance": inst, "is_oracle": False,
            "family": "MIP", "method": "cplex", "backend": "cplex", "main_encoding": "assignment_mip",
            "amo_encoding": None, "strategy": "exact", "search_mode": "branch_and_bound",
            "symmetry_breaking": True, "warm_start_mode": "NO_WARM_START", "seed": primary_seed,
            "threads": threads, "time_limit_seconds": t_exact, "max_moves": None, "heuristic_variant": "",
        })
    # Also test Gurobi + SHARED_DRSA_WARM & SAT + SHARED_DRSA_WARM on eligible instances
    add({
        "stage": "Stage_C_Exact_Baseline", "study": "warm_start_study", "instance": "bcspwr01", "is_oracle": False,
        "family": "MIP", "method": "gurobi", "backend": "gurobi", "main_encoding": "assignment_mip",
        "amo_encoding": None, "strategy": "exact", "search_mode": "branch_and_bound",
        "symmetry_breaking": True, "warm_start_mode": "SHARED_DRSA_WARM", "seed": primary_seed,
        "threads": threads, "time_limit_seconds": t_exact, "max_moves": None, "heuristic_variant": "",
    })
    for inst in ("bcspwr01", "bcsstk01", "bcspwr02", "ash85", "nos4", "nos1", "saylr1"):
        if inst in ready_meta_map:
            add({
                "stage": "Stage_C_Exact_Baseline", "study": "warm_start_study", "instance": inst, "is_oracle": False,
                "family": "SAT", "method": "cadical", "backend": "cadical", "main_encoding": "order",
                "amo_encoding": "sequential", "strategy": "incremental", "search_mode": "linear",
                "symmetry_breaking": True, "warm_start_mode": "SHARED_DRSA_WARM", "seed": primary_seed,
                "threads": threads, "time_limit_seconds": t_exact, "max_moves": None, "heuristic_variant": "",
            })

    # STAGE D: Controlled Single-Variable SAT Studies
    # Study SAT-A: Backends (cadical, glucose, minisat) fixed Order + Sequential + Incremental + sym=True
    for inst in sat_instances:
        for b in ("cadical", "glucose", "minisat"):
            add({
                "stage": "Stage_D_SAT_Studies", "study": "SAT_A_Backends", "instance": inst, "is_oracle": False,
                "family": "SAT", "method": b, "backend": b, "main_encoding": "order",
                "amo_encoding": "sequential", "strategy": "incremental", "search_mode": "linear",
                "symmetry_breaking": True, "warm_start_mode": "NO_WARM_START", "seed": primary_seed,
                "threads": threads, "time_limit_seconds": t_sat, "max_moves": None, "heuristic_variant": "",
            })
        # Study SAT-B: Main Encoding (pairwise vs order) fixed Sequential + Incremental + CaDiCaL + sym=True
        for enc in ("pairwise", "order"):
            add({
                "stage": "Stage_D_SAT_Studies", "study": "SAT_B_MainEncoding", "instance": inst, "is_oracle": False,
                "family": "SAT", "method": "cadical", "backend": "cadical", "main_encoding": enc,
                "amo_encoding": "sequential", "strategy": "incremental", "search_mode": "linear",
                "symmetry_breaking": True, "warm_start_mode": "NO_WARM_START", "seed": primary_seed,
                "threads": threads, "time_limit_seconds": t_sat, "max_moves": None, "heuristic_variant": "",
            })
        # Study SAT-D: Strategy (repeated vs incremental) fixed Order + Sequential + CaDiCaL + sym=True
        for strat in ("repeated", "incremental"):
            add({
                "stage": "Stage_D_SAT_Studies", "study": "SAT_D_Strategy", "instance": inst, "is_oracle": False,
                "family": "SAT", "method": "cadical", "backend": "cadical", "main_encoding": "order",
                "amo_encoding": "sequential", "strategy": strat, "search_mode": "linear",
                "symmetry_breaking": True, "warm_start_mode": "NO_WARM_START", "seed": primary_seed,
                "threads": threads, "time_limit_seconds": t_sat, "max_moves": None, "heuristic_variant": "",
            })

    # Study SAT-C: Six AMO Variants fixed Order + CaDiCaL + Incremental + sym=True
    for inst in sat_amo_instances:
        for amo in ("pairwise", "sequential", "binary", "commander", "product", "ladder"):
            add({
                "stage": "Stage_D_SAT_Studies", "study": "SAT_C_Cardinality_AMO", "instance": inst, "is_oracle": False,
                "family": "SAT", "method": "cadical", "backend": "cadical", "main_encoding": "order",
                "amo_encoding": amo, "strategy": "incremental", "search_mode": "linear",
                "symmetry_breaking": True, "warm_start_mode": "NO_WARM_START", "seed": primary_seed,
                "threads": threads, "time_limit_seconds": t_sat, "max_moves": None, "heuristic_variant": "",
            })
        # Study SAT-E: Symmetry Breaking ablation
        for sym in (False, True):
            add({
                "stage": "Stage_D_SAT_Studies", "study": "SAT_E_Symmetry", "instance": inst, "is_oracle": False,
                "family": "SAT", "method": "cadical", "backend": "cadical", "main_encoding": "order",
                "amo_encoding": "sequential", "strategy": "incremental", "search_mode": "linear",
                "symmetry_breaking": sym, "warm_start_mode": "NO_WARM_START", "seed": primary_seed,
                "threads": threads, "time_limit_seconds": t_sat, "max_moves": None, "heuristic_variant": "",
            })

    # STAGE E: Targeted Extended 60s Runs on Selected Hard/Promising Instances
    for inst in ext_instances:
        add({
            "stage": "Stage_E_Extended", "study": "extended_60s", "instance": inst, "is_oracle": False,
            "family": "CP", "method": "cp-sat", "backend": "cp-sat", "main_encoding": "alldiff_cp",
            "amo_encoding": None, "strategy": "exact", "search_mode": "cp_search",
            "symmetry_breaking": True, "warm_start_mode": "SHARED_DRSA_WARM", "seed": primary_seed,
            "threads": threads, "time_limit_seconds": t_ext, "max_moves": None, "heuristic_variant": "",
        })
        add({
            "stage": "Stage_E_Extended", "study": "extended_60s", "instance": inst, "is_oracle": False,
            "family": "SAT", "method": "cadical", "backend": "cadical", "main_encoding": "order",
            "amo_encoding": "sequential", "strategy": "incremental", "search_mode": "linear",
            "symmetry_breaking": True, "warm_start_mode": "SHARED_DRSA_WARM", "seed": primary_seed,
            "threads": threads, "time_limit_seconds": t_ext, "max_moves": None, "heuristic_variant": "",
        })
        add({
            "stage": "Stage_E_Extended", "study": "extended_60s", "instance": inst, "is_oracle": False,
            "family": "Heuristic", "method": "drsa", "backend": "drsa", "main_encoding": None,
            "amo_encoding": None, "strategy": "dual_rep_sa", "search_mode": "rex_nex_rot",
            "symmetry_breaking": False, "warm_start_mode": "RCM_INIT", "seed": primary_seed,
            "threads": 1, "time_limit_seconds": t_heur_ext, "max_moves": None, "heuristic_variant": "MODIFIED_VARIANT",
        })

    return plan


def _execute_single_spec(
    spec: dict[str, Any],
    *,
    graph: Graph,
    load_time_s: float,
    meta: dict[str, Any],
    env_info: dict[str, Any],
    cfg: dict[str, Any],
    warm_cache: dict[tuple[str, str], tuple[dict[int, int] | None, float]],
    experiment_id: str,
    batch_id: str,
) -> dict[str, Any]:
    """Execute one benchmark specification with strict schema, validation, and preflight guards."""

    method = str(spec["method"])
    family = str(spec["family"])
    s_info = env_info["solvers"][method]
    lic_class = str(s_info["license_type"])
    solver_ver = str(s_info.get("version") or "unknown")
    is_oracle = bool(spec.get("is_oracle", False))
    paper_lb = meta.get("paper_lb")
    paper_best = meta.get("paper_best")
    timeout_s = float(spec["time_limit_seconds"])
    sym = bool(spec["symmetry_breaking"])
    warm_mode = str(spec["warm_start_mode"])
    seed = spec["seed"]
    threads = int(spec["threads"])

    sat_limits = ResourceLimits(
        timeout_seconds=timeout_s,
        max_variables=int(cfg["max_sat_variables"]),
        max_clauses=int(cfg["max_sat_clauses"]),
        memory_limit_mb=float(cfg["memory_limit_mb"]),
    )
    max_cp_vars = int(cfg["max_cp_variables"])
    max_cp_constrs = int(cfg["max_cp_constraints"])

    base_row: dict[str, Any] = {
        "experiment_id": experiment_id,
        "run_id": spec["run_id"],
        "stage": spec["stage"],
        "study": spec["study"],
        "timestamp": _now_iso(),
        "git_commit": env_info["git_commit"],
        "instance": spec["instance"],
        "table": meta["source_table"],
        "dataset_sha256": meta["sha256"],
        "graph_fingerprint": graph.metadata.get("graph_fingerprint") or meta.get("graph_fingerprint"),
        "topology_sha256": graph.metadata.get("topology_sha256") or meta.get("topology_sha256"),
        "topology_duplicate_of": meta.get("topology_duplicate_of"),
        "conversion_policy": graph.metadata.get("conversion_policy", OFFICIAL_CONVERSION_POLICY),
        "conversion_version": graph.metadata.get("conversion_version", CONVERSION_VERSION),
        "n": graph.order,
        "m": graph.size,
        "family": family,
        "method": method,
        "backend": spec["backend"],
        "main_encoding": spec["main_encoding"],
        "amo_encoding": spec["amo_encoding"],
        "strategy": spec["strategy"],
        "search_mode": spec["search_mode"],
        "symmetry_breaking": sym,
        "warm_start_mode": warm_mode,
        "seed": seed,
        "threads": threads,
        "solver_version": solver_ver,
        "license_class": lic_class,
        "time_limit_seconds": timeout_s,
        "memory_limit_mb": float(cfg["memory_limit_mb"]),
        "max_moves": spec.get("max_moves"),
        "batch_id": batch_id,
        "repetition_id": 1,
        "paper_lb": paper_lb,
        "paper_best": paper_best,
    }

    def blocked_row(status: str, proof_status: str, reason: str, est_vars: int | None = None, est_cls: int | None = None) -> dict[str, Any]:
        return {
            **base_row,
            "status": status,
            "proof_status": proof_status,
            "bandwidth": None,
            "objective": None,
            "lower_bound": None,
            "upper_bound": None,
            "objective_bound": None,
            "optimality_gap": None,
            "validation": None,
            "incumbent_source": None,
            "stop_reason": reason,
            "loading_time_s": round(load_time_s, 6) if not is_oracle else 0.0,
            "preprocessing_time_s": None,
            "encoding_or_model_time_s": None,
            "solver_time_s": None,
            "total_wall_time_s": None,
            "peak_rss_mb": None,
            "SAT_calls": None,
            "CNF_variables": est_vars if family == "SAT" else None,
            "CNF_clauses": est_cls if family == "SAT" else None,
            "heuristic_moves": None,
            "comparison_status": "N/A",
        }

    # Preflight checks before launching heavy models
    if not s_info["available"]:
        return blocked_row("UNAVAILABLE", "UNAVAILABLE", str(s_info["note"]))

    if family == "SAT":
        enc_name = str(spec["main_encoding"])
        amo_name = str(spec["amo_encoding"])
        est = estimate_cnf_size(graph, encoding=enc_name, amo=amo_name, symmetry_breaking=sym)
        sat_ok, sat_reason = sat_limits.check(est)
        if not sat_ok:
            return blocked_row(
                "RESOURCE_LIMIT",
                "RESOURCE_LIMIT",
                f"SAT estimator guard: {sat_reason}",
                est_vars=est.num_variables,
                est_cls=est.num_clauses,
            )
    elif family == "MIP":
        mip_vars = graph.order ** 2 + 1
        mip_constrs = 2 * graph.order + 2 * graph.size + 1
        cap_v = s_info.get("max_variables")
        cap_c = s_info.get("max_constraints")
        if (cap_v is not None and mip_vars > cap_v) or (cap_c is not None and mip_constrs > cap_c):
            return blocked_row(
                "UNAVAILABLE",
                "BLOCKED_LICENSE",
                f"{method} {lic_class} cap ({cap_v}/{cap_c}) exceeded ({mip_vars}/{mip_constrs})",
            )
    elif method == "cp-sat":
        if graph.order + 1 > max_cp_vars or (2 * graph.size + 2) > max_cp_constrs:
            return blocked_row("RESOURCE_LIMIT", "RESOURCE_LIMIT", "CP-SAT exceeds configured variable/constraint guard")
    elif method == "cp-optimizer":
        bits = _cpo_search_bits(graph.order)
        max_bits = s_info.get("max_log2_search_space")
        if max_bits is not None and bits > float(max_bits):
            return blocked_row(
                "UNAVAILABLE",
                "BLOCKED_LICENSE",
                f"IBM CPO Community Edition 2^1000 search-space cap exceeded (~2^{bits:.1f} bits)",
            )

    # Measure Preprocessing & Warm-start Preparation cleanly
    prep_started = monotonic()
    warm_perm: dict[int, int] | None = None
    if warm_mode == "SHARED_RCM_WARM":
        cache_key = (spec["instance"], "SHARED_RCM_WARM")
        if cache_key not in warm_cache:
            t_w = monotonic()
            w_res = RCMSolver().solve(graph)
            warm_cache[cache_key] = (dict(w_res.permutation) if w_res.permutation else None, monotonic() - t_w)
        warm_perm, prep_s = warm_cache[cache_key]
    elif warm_mode == "SHARED_DRSA_WARM":
        cache_key = (spec["instance"], "SHARED_DRSA_WARM")
        if cache_key not in warm_cache:
            t_w = monotonic()
            drsa_t = float(cfg.get("warm_start_drsa_timeout_seconds", 0.5))
            w_res = DRSASolver(
                seed=int(cfg["primary_seed"]),
                initial_mode="rcm",
                initial_temperature=2.0,
                variant="MODIFIED_VARIANT",
            ).solve(graph, timeout_seconds=drsa_t)
            warm_cache[cache_key] = (dict(w_res.permutation) if w_res.permutation else None, monotonic() - t_w)
        warm_perm, prep_s = warm_cache[cache_key]
    else:
        _ = compute_lower_bound(graph)
        prep_s = monotonic() - prep_started

    # Execute Solver
    solve_started = monotonic()
    result: SolverResult
    if family == "SAT":
        encoder = (
            PairwiseEncoding(amo=str(spec["amo_encoding"]))
            if spec["main_encoding"] == "pairwise"
            else OrderEncoding(amo=str(spec["amo_encoding"]))
        )
        engine = (
            RepeatedSATSolver(encoder, backend_name=method)
            if spec["strategy"] == "repeated"
            else IncrementalSATSolver(encoder, backend_name=method)
        )
        result = engine.solve(
            graph,
            timeout_seconds=timeout_s,
            heuristic_permutation=warm_perm,
            symmetry_breaking=sym,
            limits=sat_limits,
        )
    elif method == "gurobi":
        result = GurobiMIPSolver().solve(
            graph, timeout_seconds=timeout_s, symmetry_breaking=sym, threads=threads, initial_permutation=warm_perm
        )
    elif method == "cplex":
        result = CPLEXMIPSolver().solve(
            graph, timeout_seconds=timeout_s, symmetry_breaking=sym, threads=threads, initial_permutation=warm_perm
        )
    elif method == "cp-sat":
        result = CPSATSolver(seed=int(seed or 17)).solve(
            graph, timeout_seconds=timeout_s, symmetry_breaking=sym, threads=threads, initial_permutation=warm_perm
        )
    elif method == "cp-optimizer":
        result = CPOptimizerSolver().solve(
            graph, timeout_seconds=timeout_s, symmetry_breaking=sym, threads=threads, initial_permutation=warm_perm
        )
    elif method == "rcm":
        result = RCMSolver().solve(graph, timeout_seconds=timeout_s)
    elif method == "sa":
        result = SimulatedAnnealingSolver(
            iterations=10_000_000 if spec["max_moves"] is None else int(spec["max_moves"]),
            initial_temperature=2.0,
            cooling=0.9999,
            minimum_temperature=1e-12,
            seed=int(seed or 17),
            initial_mode="rcm",
        ).solve(graph, timeout_seconds=timeout_s)
    elif method == "drsa":
        hvar = str(spec["heuristic_variant"])
        if hvar == "PAPER_FAITHFUL":
            result = DRSASolver(
                seed=int(seed or 17),
                initial_mode="random",
                initial_temperature=1000.0,
                cooling=0.99,
                final_temperature=1e-7,
                initial_chain_length=40,
                variant="PAPER_FAITHFUL",
            ).solve(graph, timeout_seconds=timeout_s, max_total_moves=spec.get("max_moves"))
        else:
            result = DRSASolver(
                seed=int(seed or 17),
                initial_mode="rcm",
                initial_temperature=2.0,
                cooling=0.99,
                final_temperature=1e-7,
                initial_chain_length=40,
                variant="MODIFIED_VARIANT",
            ).solve(graph, timeout_seconds=timeout_s, max_total_moves=spec.get("max_moves"))
    else:
        raise ValueError(f"Unsupported method {method!r}")

    solve_call_wall_s = monotonic() - solve_started
    md = dict(result.metadata or {})

    # Independent validation
    report = (
        validate_solution(graph, result.permutation, claimed_bandwidth=result.bandwidth)
        if result.permutation is not None and result.status not in (SolutionStatus.UNAVAILABLE, SolutionStatus.SKIPPED)
        else None
    )
    reason = str(
        md.get("skipped_reason")
        or md.get("worker_reason")
        or md.get("reason")
        or md.get("stop_reason")
        or md.get("stop_cause")
        or ""
    )

    if result.status is SolutionStatus.SKIPPED:
        mapped_status = "RESOURCE_LIMIT"
        proof_status = "RESOURCE_LIMIT"
    elif result.status is SolutionStatus.UNAVAILABLE:
        mapped_status = "UNAVAILABLE"
        proof_status = "BLOCKED_LICENSE" if ("1016" in reason or "size-limited" in reason.lower() or "2^1000" in reason) else "UNAVAILABLE"
    elif report is not None and not report.valid:
        mapped_status = "ERROR"
        proof_status = "VALIDATION_FAILED"
        reason = "; ".join(report.errors)
    elif result.status is SolutionStatus.OPTIMAL:
        mapped_status = "OPTIMAL"
        proof_status = "PROVED_OPTIMAL"
    elif result.status is SolutionStatus.FEASIBLE:
        if family == "SAT" and reason and ("deadline" in reason.lower() or "timed out" in reason.lower() or "timeout" in reason.lower()):
            mapped_status = "TIMEOUT"
            proof_status = "TIMEOUT_WITH_INCUMBENT"
        elif family == "Heuristic":
            mapped_status = "FEASIBLE"
            proof_status = "HEURISTIC_UNPROVED"
        else:
            mapped_status = "FEASIBLE"
            proof_status = "EXACT_FEASIBLE_UNPROVED"
    elif result.status is SolutionStatus.TIMEOUT:
        mapped_status = "TIMEOUT"
        proof_status = "TIMEOUT_WITH_INCUMBENT" if report and report.valid else "TIMEOUT_NO_SOLUTION"
    else:
        mapped_status = result.status.value
        proof_status = result.status.value

    bw = report.actual_bandwidth if report and report.valid else None
    lb = result.lower_bound
    ub = result.upper_bound if bw is None else min(bw, result.upper_bound or bw)
    obj_bound = md.get("best_bound") if md.get("best_bound") is not None else md.get("solver_lower_bound")
    if obj_bound is None and lb is not None:
        obj_bound = lb
    mip_gap = md.get("mip_gap")
    if mip_gap is None and bw is not None and lb is not None and bw > 0:
        mip_gap = (bw - lb) / bw
    elif mip_gap is None and bw == 0 and lb == 0:
        mip_gap = 0.0

    # Paper comparison tag (note heuristic cannot be PROVED_MATCHED_BEST)
    if family == "Heuristic":
        if bw is None:
            comp_status = "NO_VALID_SOLUTION"
        elif bw < int(paper_lb):
            comp_status = "BELOW_PUBLISHED_LB_REQUIRES_VERIFICATION"
        elif bw == int(paper_best):
            comp_status = "UNPROVED_MATCHED_BEST"
        elif bw < int(paper_best):
            comp_status = "BELOW_PUBLISHED_BEST_REQUIRES_VERIFICATION"
        else:
            comp_status = "ABOVE_PUBLISHED_BEST"
    else:
        comp_status = _proof_comparison_tag(
            status=mapped_status,
            bandwidth=bw,
            pub_best=int(paper_best) if paper_best is not None else None,
            dataset_status="READY",
        )
        if bw is not None and paper_lb is not None and bw < int(paper_lb):
            comp_status = "BELOW_PUBLISHED_LB_REQUIRES_VERIFICATION"

    enc_model_s: float | None = None
    if family == "SAT":
        enc_model_s = round(result.encoding_time_s, 6)
    elif family == "CP":
        if md.get("model_construction_time_s") is not None:
            enc_model_s = round(float(md["model_construction_time_s"]), 6)

    solver_time = (
        round(result.solving_time_s, 6)
        if family == "SAT"
        else (
            round(float(md["solver_time_s"]), 6)
            if md.get("solver_time_s") is not None
            else round(result.runtime_seconds, 6)
        )
    )
    total_wall = round((0.0 if is_oracle else load_time_s) + prep_s + solve_call_wall_s, 6)
    peak_rss = md.get("sampled_peak_memory_mb") or md.get("engine_peak_memory_mb") or md.get("peak_memory_mb") or _self_rss_mb()

    heur_moves = md.get("moves_evaluated") or md.get("iterations_completed")
    if heur_moves is None and method == "drsa":
        heur_moves = result.sat_calls  # unused normally, keep None if absent
        heur_moves = md.get("moves_evaluated")

    method_label = (
        f"drsa_{str(spec['heuristic_variant']).lower()}"
        if method == "drsa" and spec.get("heuristic_variant")
        else method
    )

    return {
        **base_row,
        "method": method_label,
        "status": mapped_status,
        "proof_status": proof_status,
        "bandwidth": bw,
        "objective": bw,
        "lower_bound": lb,
        "upper_bound": ub,
        "objective_bound": obj_bound,
        "optimality_gap": None if mip_gap is None else round(float(mip_gap), 6),
        "validation": report.valid if report else None,
        "incumbent_source": md.get("incumbent_source") or method,
        "stop_reason": reason or mapped_status,
        "loading_time_s": round(0.0 if is_oracle else load_time_s, 6),
        "preprocessing_time_s": round(prep_s, 6),
        "encoding_or_model_time_s": enc_model_s,
        "solver_time_s": solver_time if mapped_status not in ("RESOURCE_LIMIT", "UNAVAILABLE") else None,
        "total_wall_time_s": total_wall if mapped_status not in ("RESOURCE_LIMIT", "UNAVAILABLE") else None,
        "peak_rss_mb": round(float(peak_rss), 2) if peak_rss is not None and mapped_status not in ("RESOURCE_LIMIT", "UNAVAILABLE") else None,
        "SAT_calls": result.sat_calls if family == "SAT" and mapped_status != "RESOURCE_LIMIT" else None,
        "CNF_variables": result.num_variables if family == "SAT" and mapped_status != "RESOURCE_LIMIT" else None,
        "CNF_clauses": result.num_clauses if family == "SAT" and mapped_status != "RESOURCE_LIMIT" else None,
        "heuristic_moves": int(heur_moves) if family == "Heuristic" and heur_moves is not None else None,
        "comparison_status": comp_status,
    }


def compute_m3_6_statistics(
    rows: list[dict[str, Any]],
    ready_meta_map: dict[str, dict[str, Any]],
    output_dir: Path,
) -> dict[str, Any]:
    """Compute rigorous M3.6 statistics separating measured vs censored/blocked runs & 54 vs 53 topologies."""

    hb_rows = [r for r in rows if r["stage"] != "Stage_A_SmallOracle"]
    oracle_rows = [r for r in rows if r["stage"] == "Stage_A_SmallOracle"]

    # Per-method summary grouped by (family, method, study/stage) or overall HB method label
    by_method: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in hb_rows:
        key = f"{r['family']}::{r['method']}"
        if r["family"] == "SAT":
            key = f"SAT::{r['backend']}({r['main_encoding']}/{r['amo_encoding']}/{r['strategy']})"
        elif r["family"] in ("CP", "MIP") and r["warm_start_mode"] != "NO_WARM_START":
            key = f"{r['family']}::{r['method']}({r['warm_start_mode']})"
        by_method[key].append(r)

    method_summary_rows: list[dict[str, Any]] = []
    for key, grp in sorted(by_method.items()):
        n_att = len(grp)
        opt_c = sum(r["status"] == "OPTIMAL" for r in grp)
        feas_c = sum(r["status"] == "FEASIBLE" for r in grp)
        to_c = sum(r["status"] == "TIMEOUT" for r in grp)
        res_c = sum(r["status"] == "RESOURCE_LIMIT" for r in grp)
        una_c = sum(r["status"] == "UNAVAILABLE" for r in grp)
        err_c = sum(r["status"] == "ERROR" for r in grp)
        solved_with_bw = [r for r in grp if r["bandwidth"] is not None]
        opt_times = [float(r["total_wall_time_s"]) for r in grp if r["status"] == "OPTIMAL" and r["total_wall_time_s"] is not None]
        exec_times = [float(r["total_wall_time_s"]) for r in grp if r["status"] not in ("RESOURCE_LIMIT", "UNAVAILABLE") and r["total_wall_time_s"] is not None]
        rss_vals = [float(r["peak_rss_mb"]) for r in grp if r["peak_rss_mb"] is not None]
        gaps = [float(r["optimality_gap"]) for r in grp if r["optimality_gap"] is not None]
        matched_best = sum("MATCHED_BEST" in str(r["comparison_status"]) for r in grp)
        method_summary_rows.append({
            "method_key": key,
            "family": grp[0]["family"],
            "method": grp[0]["method"],
            "attempted": n_att,
            "optimal_count": opt_c,
            "feasible_count": feas_c,
            "timeout_count": to_c,
            "resource_limit_count": res_c,
            "unavailable_count": una_c,
            "error_count": err_c,
            "valid_incumbent_count": len(solved_with_bw),
            "matched_published_best_count": matched_best,
            "best_bandwidth": min((int(r["bandwidth"]) for r in solved_with_bw), default=None),
            "median_wall_time_optimal_only_s": round(statistics.median(opt_times), 4) if opt_times else None,
            "median_wall_time_executed_s": round(statistics.median(exec_times), 4) if exec_times else None,
            "peak_rss_max_mb": round(max(rss_vals), 2) if rss_vals else None,
            "median_optimality_gap": round(statistics.median(gaps), 4) if gaps else None,
            "runtime_scope_note": f"opt_n={len(opt_times)}, exec_n={len(exec_times)}, censored_or_blocked={to_c+res_c+una_c}",
        })

    # Per-instance comparison across all 54 READY
    by_inst: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in hb_rows:
        by_inst[str(r["instance"])].append(r)

    per_instance_rows: list[dict[str, Any]] = []
    paper_rows: list[dict[str, Any]] = []
    for inst, meta in sorted(ready_meta_map.items(), key=lambda kv: (str(kv[1]["source_table"]), int(kv[1]["n"]), kv[0])):
        grp = by_inst.get(inst, [])
        exact_grp = [r for r in grp if r["family"] != "Heuristic"]
        heur_grp = [r for r in grp if r["family"] == "Heuristic"]
        valid_grp = [r for r in grp if r["bandwidth"] is not None]
        best_bw = min((int(r["bandwidth"]) for r in valid_grp), default=None)
        best_exact_bw = min((int(r["bandwidth"]) for r in exact_grp if r["bandwidth"] is not None), default=None)
        best_heur_bw = min((int(r["bandwidth"]) for r in heur_grp if r["bandwidth"] is not None), default=None)
        lbs = [int(r["lower_bound"]) for r in grp if r["lower_bound"] is not None]
        best_lb = max(lbs, default=int(meta["initial_lb"]))
        opt_provers = sorted({f"{r['family']}:{r['method']}" for r in exact_grp if r["status"] == "OPTIMAL"})
        winners = sorted({f"{r['family']}:{r['method']}" for r in valid_grp if r["bandwidth"] == best_bw})
        pub_best = int(meta["paper_best"])
        pub_lb = int(meta["paper_lb"])
        rel_gap_pub = None if best_bw is None or pub_best <= 0 else round((best_bw - pub_best) / pub_best, 6)

        per_instance_rows.append({
            "instance": inst,
            "table": meta["source_table"],
            "n": meta["n"],
            "m": meta["m"],
            "topology_sha256": meta["topology_sha256"],
            "graph_fingerprint": meta["graph_fingerprint"],
            "topology_duplicate_of": meta.get("topology_duplicate_of"),
            "paper_lb": pub_lb,
            "paper_best": pub_best,
            "best_certified_lb": best_lb,
            "best_feasible_bw": best_bw,
            "best_exact_bw": best_exact_bw,
            "best_heuristic_bw": best_heur_bw,
            "proved_optimal": bool(opt_provers),
            "optimal_proving_methods": ";".join(opt_provers),
            "winning_methods": ";".join(winners),
            "gap_vs_published_best": None if best_bw is None else best_bw - pub_best,
            "rel_gap_vs_published_best": rel_gap_pub,
            "runs_attempted": len(grp),
        })

        paper_rows.append({
            "instance": inst,
            "table": meta["source_table"],
            "n": meta["n"],
            "m": meta["m"],
            "paper_lb": pub_lb,
            "paper_best": pub_best,
            "m3_6_best_lb": best_lb,
            "m3_6_best_exact_bw": best_exact_bw,
            "m3_6_best_heuristic_bw": best_heur_bw,
            "m3_6_overall_best_bw": best_bw,
            "proved_optimal": bool(opt_provers),
            "matched_published_best": best_bw == pub_best,
            "below_published_lb_anomaly": best_bw is not None and best_bw < pub_lb,
            "gap_vs_paper_best": None if best_bw is None else best_bw - pub_best,
        })

    # 54-instance (INSTANCE_WEIGHTED) vs 53-topology (TOPOLOGY_UNIQUE) sensitivity analysis
    unique_rows = [r for r in per_instance_rows if not r.get("topology_duplicate_of")]
    analysis_rows: list[dict[str, Any]] = []
    for scope_name, subset in (("INSTANCE_WEIGHTED_54", per_instance_rows), ("TOPOLOGY_UNIQUE_53", unique_rows)):
        gaps_pub = [float(r["gap_vs_published_best"]) for r in subset if r["gap_vs_published_best"] is not None]
        heur_gaps = [
            float(int(r["best_heuristic_bw"]) - int(r["paper_best"]))
            for r in subset
            if r["best_heuristic_bw"] is not None
        ]
        matched_cnt = sum(r["best_feasible_bw"] == r["paper_best"] for r in subset)
        proved_cnt = sum(bool(r["proved_optimal"]) for r in subset)
        analysis_rows.append({
            "analysis_scope": scope_name,
            "instance_count": len(subset),
            "duplicate_pair_note": "Includes both saylr3 and sherman1" if scope_name == "INSTANCE_WEIGHTED_54" else "Deduplicates sherman1 == saylr3 (M3.5 canonical topology check)",
            "exact_proved_optimal_instances": proved_cnt,
            "matched_published_best_instances": matched_cnt,
            "mean_gap_overall_vs_published_best": round(statistics.mean(gaps_pub), 4) if gaps_pub else None,
            "median_gap_overall_vs_published_best": round(statistics.median(gaps_pub), 4) if gaps_pub else None,
            "mean_gap_heuristic_vs_published_best": round(statistics.mean(heur_gaps), 4) if heur_gaps else None,
            "median_gap_heuristic_vs_published_best": round(statistics.median(heur_gaps), 4) if heur_gaps else None,
        })

    # Check saylr3 vs sherman1 run-level equality in Stage B
    s3_drsa = [r for r in hb_rows if r["instance"] == "saylr3"]
    sh1_drsa = [r for r in hb_rows if r["instance"] == "sherman1"]
    saylr_map = {r["method"]: r["bandwidth"] for r in s3_drsa}
    sherm_map = {r["method"]: r["bandwidth"] for r in sh1_drsa}

    _write_csv_atomic(output_dir / "per_method_summary.csv", list(method_summary_rows[0].keys()) if method_summary_rows else ["method_key"], method_summary_rows)
    _write_csv_atomic(output_dir / "per_instance_comparison.csv", list(per_instance_rows[0].keys()) if per_instance_rows else ["instance"], per_instance_rows)
    _write_csv_atomic(output_dir / "paper_comparison.csv", list(paper_rows[0].keys()) if paper_rows else ["instance"], paper_rows)
    _write_csv_atomic(output_dir / "unique_topology_analysis.csv", list(analysis_rows[0].keys()), analysis_rows)

    # Paired statistical comparisons (same instance & seed/budget scope -> win/tie/loss & delta statistics)
    def _paired_summary(name: str, left: list[dict[str, Any]], right: list[dict[str, Any]], key_fn) -> dict[str, Any] | None:
        l_map = {key_fn(r): r for r in left if r["bandwidth"] is not None}
        r_map = {key_fn(r): r for r in right if r["bandwidth"] is not None}
        common = sorted(set(l_map) & set(r_map))
        if not common:
            return None
        diffs = [int(l_map[k]["bandwidth"]) - int(r_map[k]["bandwidth"]) for k in common]
        time_diffs = [
            float(l_map[k]["total_wall_time_s"]) - float(r_map[k]["total_wall_time_s"])
            for k in common
            if l_map[k]["total_wall_time_s"] is not None and r_map[k]["total_wall_time_s"] is not None
        ]
        return {
            "comparison": name,
            "n_pairs": len(common),
            "left_wins_bw": sum(d < 0 for d in diffs),
            "ties_bw": sum(d == 0 for d in diffs),
            "right_wins_bw": sum(d > 0 for d in diffs),
            "mean_bw_diff_left_minus_right": round(statistics.mean(diffs), 4),
            "median_bw_diff": round(statistics.median(diffs), 4),
            "std_bw_diff": round(statistics.stdev(diffs), 4) if len(diffs) >= 2 else 0.0,
            "min_bw_diff": min(diffs),
            "max_bw_diff": max(diffs),
            "mean_wall_diff_s": round(statistics.mean(time_diffs), 4) if time_diffs else None,
            "median_wall_diff_s": round(statistics.median(time_diffs), 4) if time_diffs else None,
        }

    paired_candidates = [
        _paired_summary(
            "RCM_vs_SA_54_seed17",
            [r for r in hb_rows if r["method"] == "rcm"],
            [r for r in hb_rows if r["method"] == "sa" and r["seed"] == 17],
            lambda r: r["instance"],
        ),
        _paired_summary(
            "SA_vs_DRSA_Warm_54_seed17",
            [r for r in hb_rows if r["method"] == "sa" and r["seed"] == 17],
            [r for r in hb_rows if r["method"] == "drsa_modified_variant" and r["seed"] == 17],
            lambda r: r["instance"],
        ),
        _paired_summary(
            "DRSA_PaperBounded_vs_DRSA_Warm_54_seed17",
            [r for r in hb_rows if r["method"] == "drsa_paper_faithful" and r["seed"] == 17],
            [r for r in hb_rows if r["method"] == "drsa_modified_variant" and r["seed"] == 17],
            lambda r: r["instance"],
        ),
        _paired_summary(
            "CP_SAT_vs_CP_Optimizer_StageC_RCMWarm",
            [r for r in hb_rows if r["stage"] == "Stage_C_Exact_Baseline" and r["method"] == "cp-sat" and r["warm_start_mode"] == "SHARED_RCM_WARM"],
            [r for r in hb_rows if r["stage"] == "Stage_C_Exact_Baseline" and r["method"] == "cp-optimizer" and r["warm_start_mode"] == "SHARED_RCM_WARM"],
            lambda r: r["instance"],
        ),
        _paired_summary(
            "CP_SAT_NoWarm_vs_DRSAWarm_StageC",
            [r for r in hb_rows if r["stage"] == "Stage_C_Exact_Baseline" and r["method"] == "cp-sat" and r["warm_start_mode"] == "NO_WARM_START"],
            [r for r in hb_rows if r["stage"] == "Stage_C_Exact_Baseline" and r["method"] == "cp-sat" and r["warm_start_mode"] == "SHARED_DRSA_WARM"],
            lambda r: r["instance"],
        ),
        _paired_summary(
            "SAT_CaDiCaL_vs_Glucose_OrderSeqInc",
            [r for r in hb_rows if r["family"] == "SAT" and r["backend"] == "cadical" and r["main_encoding"] == "order" and r["amo_encoding"] == "sequential" and r["strategy"] == "incremental" and r["symmetry_breaking"] is True and r["warm_start_mode"] == "NO_WARM_START"],
            [r for r in hb_rows if r["family"] == "SAT" and r["backend"] == "glucose" and r["main_encoding"] == "order" and r["amo_encoding"] == "sequential" and r["strategy"] == "incremental"],
            lambda r: r["instance"],
        ),
        _paired_summary(
            "SAT_CaDiCaL_vs_MiniSat_OrderSeqInc",
            [r for r in hb_rows if r["family"] == "SAT" and r["backend"] == "cadical" and r["main_encoding"] == "order" and r["amo_encoding"] == "sequential" and r["strategy"] == "incremental" and r["symmetry_breaking"] is True and r["warm_start_mode"] == "NO_WARM_START"],
            [r for r in hb_rows if r["family"] == "SAT" and r["backend"] == "minisat" and r["main_encoding"] == "order" and r["amo_encoding"] == "sequential" and r["strategy"] == "incremental"],
            lambda r: r["instance"],
        ),
    ]
    paired_rows = [row for row in paired_candidates if row is not None]
    if paired_rows:
        _write_csv_atomic(output_dir / "paired_comparisons.csv", list(paired_rows[0].keys()), paired_rows)

    anomalies = [r for r in hb_rows if "ANOMALY" in str(r["comparison_status"]) or "BELOW_PUBLISHED" in str(r["comparison_status"]) or r["status"] == "ERROR"]
    status_counts = defaultdict(int)
    for r in rows:
        status_counts[str(r["status"])] += 1

    return {
        "total_runs": len(rows),
        "small_oracle_runs": len(oracle_rows),
        "harwell_boeing_runs": len(hb_rows),
        "distinct_hb_instances_attempted": len(by_inst),
        "status_counts": dict(sorted(status_counts.items())),
        "validation_passed_count": sum(r["validation"] is True for r in rows),
        "validation_failed_count": sum(r["validation"] is False for r in rows),
        "anomalies_count": len(anomalies),
        "unique_topology_sensitivity": analysis_rows,
        "saylr3_vs_sherman1_stage_b_bw": {"saylr3": saylr_map, "sherman1": sherm_map},
        "method_summary": method_summary_rows,
    }


def run_m3_6_benchmark(
    *,
    config_path: str | Path = "configs/member3_m3_6.toml",
    stages: set[str] | None = None,
    resume: bool = True,
    max_batch_seconds: float | None = None,
    max_runs_in_batch: int | None = None,
    generate_plots: bool = False,
) -> dict[str, Any]:
    """Run unified M3.6 benchmark with deterministic checkpoint/resume & resource guards."""

    cfg_file = Path(config_path)
    cfg_raw = tomllib.loads(cfg_file.read_text(encoding="utf-8"))
    cfg = cfg_raw["benchmark"]
    root = Path.cwd()
    provenance_path = (root / str(cfg["provenance"])).resolve()
    raw_dir = (root / str(cfg["raw_dir"])).resolve()
    out_dir = (root / str(cfg["output_dir"])).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    env_info = audit_environment()
    _atomic_write_text(out_dir / "metadata.json", json.dumps(env_info, indent=2) + "\n")

    preflight_rows, ready_meta_map, loaded_graphs = run_preflight_54(
        root=root,
        provenance_path=provenance_path,
        raw_dir=raw_dir,
        output_dir=out_dir,
        env_info=env_info,
        max_sat_vars=int(cfg["max_sat_variables"]),
        max_sat_clauses=int(cfg["max_sat_clauses"]),
        max_cp_vars=int(cfg["max_cp_variables"]),
        max_cp_constrs=int(cfg["max_cp_constraints"]),
    )

    oracle_list = _small_oracle_instances()
    oracle_map: dict[str, tuple[Graph, dict[str, Any]]] = {}
    for oname, og, o_bw in oracle_list:
        oracle_map[oname] = (
            og,
            {
                "instance": oname,
                "source_table": "SmallOracle",
                "sha256": og.metadata["graph_fingerprint"],
                "topology_sha256": og.metadata["topology_sha256"],
                "graph_fingerprint": og.metadata["graph_fingerprint"],
                "topology_duplicate_of": None,
                "paper_lb": o_bw,
                "paper_best": o_bw,
            },
        )

    plan = build_experiment_plan(cfg, ready_meta_map)
    if stages:
        plan = [spec for spec in plan if spec["stage"] in stages]
    _atomic_write_text(out_dir / "experiment_plan.json", json.dumps(plan, indent=2) + "\n")

    runs_json = out_dir / "runs.json"
    runs_csv = out_dir / "runs.csv"
    existing_rows: list[dict[str, Any]] = []
    done_ids: set[str] = set()
    if resume and runs_json.is_file():
        existing_rows = json.loads(runs_json.read_text(encoding="utf-8"))
        done_ids = {str(r["run_id"]) for r in existing_rows}

    experiment_id = str(cfg["experiment_id"])
    batch_limit = float(cfg["max_batch_seconds"]) if max_batch_seconds is None else float(max_batch_seconds)
    batch_id = f"batch_{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    batch_start = monotonic()
    warm_cache: dict[tuple[str, str], tuple[dict[int, int] | None, float]] = {}

    executed_now = 0
    interrupted_by_budget = False
    for spec in plan:
        rid = str(spec["run_id"])
        if rid in done_ids:
            continue
        if max_runs_in_batch is not None and executed_now >= max_runs_in_batch:
            interrupted_by_budget = True
            break
        if executed_now > 0 and (monotonic() - batch_start) >= batch_limit:
            interrupted_by_budget = True
            break

        inst = str(spec["instance"])
        if spec.get("is_oracle"):
            graph, meta = oracle_map[inst]
            load_s = 0.0
        else:
            graph, load_s = loaded_graphs[inst]
            meta = ready_meta_map[inst]

        row = _execute_single_spec(
            spec,
            graph=graph,
            load_time_s=load_s,
            meta=meta,
            env_info=env_info,
            cfg=cfg,
            warm_cache=warm_cache,
            experiment_id=experiment_id,
            batch_id=batch_id,
        )
        existing_rows.append(row)
        done_ids.add(rid)
        executed_now += 1
        if executed_now % 5 == 0 or row["family"] != "Heuristic":
            _atomic_write_text(runs_json, json.dumps(existing_rows, indent=2) + "\n")
            _write_csv_atomic(runs_csv, M3_6_FIELDS, existing_rows)

    _atomic_write_text(runs_json, json.dumps(existing_rows, indent=2) + "\n")
    _write_csv_atomic(runs_csv, M3_6_FIELDS, existing_rows)

    full_plan = build_experiment_plan(cfg, ready_meta_map)
    pending_count = sum(1 for spec in full_plan if spec["run_id"] not in done_ids)
    stats = compute_m3_6_statistics(existing_rows, ready_meta_map, out_dir)
    summary = {
        "experiment_id": experiment_id,
        "git_commit": env_info["git_commit"],
        "validator_version": VALIDATOR_VERSION,
        "planned_total_runs": len(full_plan),
        "completed_total_runs": len(existing_rows),
        "pending_runs": pending_count,
        "executed_in_this_batch": executed_now,
        "interrupted_by_batch_budget": interrupted_by_budget,
        **stats,
    }
    _atomic_write_text(out_dir / "summary.json", json.dumps(summary, indent=2) + "\n")

    log_lines = [
        f"Phase M3.6 Unified Benchmark run log (batch_id={batch_id})",
        f"Git HEAD: {env_info['git_commit']} | OS: {env_info['platform']} | CPU: {env_info['cpu_model']} ({env_info['cpu_cores']} cores, {env_info['ram_gb']} GB)",
        f"Completed total runs: {len(existing_rows)} / {len(full_plan)} (executed this batch: {executed_now}, pending: {pending_count})",
        f"Status counts: {stats['status_counts']}",
        f"Validation: valid={stats['validation_passed_count']}, failed={stats['validation_failed_count']}, anomalies={stats['anomalies_count']}",
    ]
    _atomic_write_text(out_dir / "run_log.txt", "\n".join(log_lines) + "\n")

    comp_lines = [
        "# M3.6 Multi-Method Benchmark Quick Comparison Summary",
        "",
        f"- **Completed runs**: `{len(existing_rows)} / {len(full_plan)}` (pending: `{pending_count}`)",
        f"- **Status distribution**: `{stats['status_counts']}`",
        f"- **Independent validation**: `valid={stats['validation_passed_count']}`, `failed={stats['validation_failed_count']}`",
        "",
        "## 54 Instances vs 53 Unique Topologies (`saylr3 == sherman1`)",
        "",
        "| Scope | Count | Exact Proved Optimal | Matched Published Best | Mean Gap vs Pub Best |",
        "|---|---:|---:|---:|---:|",
    ]
    for arow in stats["unique_topology_sensitivity"]:
        comp_lines.append(
            f"| `{arow['analysis_scope']}` | {arow['instance_count']} | {arow['exact_proved_optimal_instances']} | "
            f"{arow['matched_published_best_instances']} | {arow['mean_gap_overall_vs_published_best']} |"
        )
    _atomic_write_text(out_dir / "comparison.md", "\n".join(comp_lines) + "\n")

    if generate_plots and runs_csv.is_file() and existing_rows:
        from bmp.experiments.member3_m3_6_plots import create_m3_6_plots

        create_m3_6_plots(runs_csv, preflight_csv_path=out_dir / "preflight_54.csv", out_dir=out_dir / "figures")

    return summary


__all__ = [
    "METHOD_LABELS",
    "M3_6_FIELDS",
    "PREFLIGHT_M3_6_FIELDS",
    "audit_environment",
    "build_experiment_plan",
    "compute_m3_6_statistics",
    "run_m3_6_benchmark",
    "run_preflight_54",
]
