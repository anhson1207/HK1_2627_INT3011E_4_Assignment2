"""Resumable Member 2 benchmark over Leader's 113-instance official catalog.

Enforces READY-only dataset verification status, Leader CNF estimator/ResourceLimits,
worker timeout & RSS tracking, M2.2 controlled experiment plans (A-F), and
full reproducible CSV/JSON/summary/comparison exports.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import multiprocessing
import os
import platform
import statistics
import subprocess
import sys
import tomllib
from pathlib import Path
from time import monotonic
from typing import Any

from bmp.core.benchmark_catalog import ALL_INSTANCES, BenchmarkInstanceMeta
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
from bmp.core.validation import validate_solution
from bmp.encodings.estimator import ResourceLimits, estimate_cnf_size
from bmp.encodings.order import OrderEncoding
from bmp.encodings.pairwise import PairwiseEncoding
from bmp.io.readers import inspect_matrix_market
from bmp.solvers.brute_force import BruteForceSolver
from bmp.solvers.exact.cplex import CPLEXMIPSolver
from bmp.solvers.exact.gurobi import GurobiMIPSolver
from bmp.solvers.sat.backends import get_sat_backend
from bmp.solvers.sat.incremental import IncrementalSATSolver
from bmp.solvers.sat.repeated import RepeatedSATSolver

FIELDS = (
    "run_id",
    "timestamp",
    "git_commit",
    "experiment",
    "instance",
    "table",
    "dataset_source",
    "dataset_checksum",
    "dataset_status",
    "n",
    "m",
    "method",
    "encoding",
    "amo",
    "solver",
    "solver_version",
    "strategy",
    "search_mode",
    "symmetry_breaking",
    "repetition",
    "timeout_s",
    "bandwidth",
    "lower_bound",
    "upper_bound",
    "objective_bound",
    "mip_gap",
    "status",
    "proof_status",
    "incumbent_source",
    "encoding_time_s",
    "solver_time_s",
    "total_wall_time_s",
    "peak_rss_mb",
    "cnf_variables",
    "cnf_original_vars",
    "cnf_channeling_vars",
    "cnf_aux_vars",
    "cnf_clauses",
    "sat_calls",
    "sat_trace",
    "published_lb",
    "published_best",
    "validation",
    "permutation",
    "error",
)


def _supports_fork() -> bool:
    return os.name != "nt" and "fork" in multiprocessing.get_all_start_methods()


def _self_rss_mb() -> float | None:
    try:
        import resource

        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
        return round(usage / divisor, 3)
    except Exception:
        return None


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=2,
        ).strip()
    except Exception:
        return "unknown"


def _sat_backend_version(backend_name: str) -> str:
    try:
        import pysat

        pysat_ver = getattr(pysat, "__version__", "unknown")
        with get_sat_backend(backend_name) as b:
            return f"{b.version} (PySAT {pysat_ver})"
    except Exception:
        return backend_name


def _mip_backend_version(solver_name: str) -> str:
    if solver_name == "gurobi":
        try:
            import gurobipy as gp

            return f"gurobipy {'.'.join(map(str, gp.gurobi.version()))}"
        except Exception:
            return "gurobipy (unavailable)"
    if solver_name == "cplex":
        try:
            import cplex

            with cplex.Cplex() as c:
                return f"cplex {c.get_version()}"
        except Exception:
            try:
                import cplex

                return f"cplex {getattr(cplex, '__version__', 'unavailable')}"
            except Exception:
                return "cplex (unavailable)"
    return solver_name


def configurations(config: dict[str, Any]):
    for sat_solver in ("glucose", "cadical"):
        if sat_solver in config["solvers"]:
            for encoding in ("pairwise", "order"):
                for strategy in ("repeated", "incremental"):
                    yield (sat_solver, encoding, strategy, "pairwise", False)
            for amo in config["amo"]:
                if amo != "pairwise":
                    yield (sat_solver, "pairwise", "repeated", amo, False)
    for solver in ("gurobi", "cplex"):
        if solver in config["solvers"]:
            for symmetry in (False, True):
                yield (solver, "", "", "", symmetry)


def _pilot_small_graphs() -> list[tuple[Graph, int | None]]:
    """Deterministic verified small graphs (samples + random graphs with oracle/exact check)."""
    specs: list[tuple[Graph, bool]] = [
        (path_graph(5), True),
        (cycle_graph(4), True),
        (star_graph(4), True),
        (complete_graph(5), True),
        (edgeless_graph(5), True),
        (erdos_renyi_graph(8, 0.35, seed=201), True),
        (erdos_renyi_graph(10, 0.28, seed=203), True),
        (erdos_renyi_graph(12, 0.30, seed=204), False),
        (erdos_renyi_graph(14, 0.25, seed=205), False),
    ]
    out: list[tuple[Graph, int | None]] = []
    for g, has_bf in specs:
        oracle_bw = BruteForceSolver(max_vertices=10).solve(g).bandwidth if has_bf else None
        out.append((g, oracle_bw))
    return out


def _pilot_plan_entries(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Build controlled, deduplicated experiment entries covering A-F."""
    pilot_t = float(config.get("pilot_timeout_seconds", config["timeout_seconds"]))
    ext_t = float(config.get("extended_timeout_seconds", 60.0))
    entries: list[dict[str, Any]] = []

    def add_unique(
        *,
        scope: str,
        instances: list[str],
        solver: str,
        encoding: str | None,
        strategy: str | None,
        amo: str | None,
        symmetry: bool,
        timeout: float,
        experiments: str,
        threads: int | None = None,
    ) -> None:
        for inst in instances:
            entries.append({
                "scope": scope,
                "instance": inst,
                "solver": solver,
                "encoding": encoding,
                "strategy": strategy,
                "search_mode": "linear" if strategy == "repeated" else ("adaptive" if strategy == "incremental" else None),
                "amo": amo,
                "symmetry_breaking": symmetry,
                "timeout_s": timeout,
                "experiments": experiments,
                "threads": threads,
            })

    small_names = [g.name for g, _ in _pilot_small_graphs()]
    hb_pilot = list(config.get("pilot_instances", ["bcspwr01", "bcspwr02", "bcsstk01", "nos4"]))

    # Small verified graphs: Live MIP E + SAT vs MIP F
    for solver in ("gurobi", "cplex"):
        for sym in (False, True):
            exps = "E_mip;F_sat_vs_mip" if sym else "E_mip"
            add_unique(
                scope="small", instances=small_names, solver=solver,
                encoding=None, strategy=None, amo=None,
                symmetry=sym, timeout=pilot_t, experiments=exps, threads=1,
            )
    for solver in ("cadical", "glucose"):
        add_unique(
            scope="small", instances=small_names, solver=solver,
            encoding="order", strategy="incremental", amo="sequential",
            symmetry=True, timeout=pilot_t, experiments="F_sat_vs_mip",
        )

    # HB Table 6 READY pilot: Experiment Matrix A, B, C, D, E, F
    # Deduplicated so identical runs tag multiple experiments cleanly
    add_unique(
        scope="hb", instances=hb_pilot, solver="cadical",
        encoding="order", strategy="incremental", amo="sequential",
        symmetry=True, timeout=pilot_t,
        experiments="A_backend;C_strategy;D_encoding;F_sat_vs_mip",
    )
    add_unique(
        scope="hb", instances=hb_pilot, solver="glucose",
        encoding="order", strategy="incremental", amo="sequential",
        symmetry=True, timeout=pilot_t,
        experiments="A_backend;B_cardinality;C_strategy;D_encoding;F_sat_vs_mip",
    )
    # Experiment C (Repeated vs Incremental) + Experiment A on Repeated
    for solver in ("cadical", "glucose"):
        add_unique(
            scope="hb", instances=hb_pilot, solver=solver,
            encoding="order", strategy="repeated", amo="sequential",
            symmetry=True, timeout=pilot_t,
            experiments="A_backend;C_strategy",
        )
    # Experiment B: Remaining Cardinality AMOs (pairwise, binary, commander) under Order Incremental Glucose
    for amo in ("pairwise", "binary", "commander"):
        add_unique(
            scope="hb", instances=hb_pilot, solver="glucose",
            encoding="order", strategy="incremental", amo=amo,
            symmetry=True, timeout=pilot_t,
            experiments="B_cardinality",
        )
    # Experiment B (Pairwise Position encoding AMO check on small HB bcspwr01)
    for amo in ("pairwise", "sequential", "binary", "commander"):
        add_unique(
            scope="hb", instances=["bcspwr01"], solver="glucose",
            encoding="pairwise", strategy="repeated", amo=amo,
            symmetry=True, timeout=pilot_t,
            experiments="B_cardinality_pairwise",
        )
    # Experiment D: Pairwise vs Order under Sequential Incremental
    for solver in ("cadical", "glucose"):
        add_unique(
            scope="hb", instances=hb_pilot, solver=solver,
            encoding="pairwise", strategy="incremental", amo="sequential",
            symmetry=True, timeout=pilot_t,
            experiments="D_encoding",
        )
    # Experiment E & F: Gurobi & CPLEX on HB pilot
    for solver in ("gurobi", "cplex"):
        for sym in (False, True):
            exps = "E_mip;F_sat_vs_mip" if sym else "E_mip"
            add_unique(
                scope="hb", instances=hb_pilot, solver=solver,
                encoding=None, strategy=None, amo=None,
                symmetry=sym, timeout=pilot_t, experiments=exps, threads=1,
            )
    # Extended 60s check on selected instances (bcspwr02, bcsstk01) for Order Sequential Incremental
    if ext_t > pilot_t:
        for solver in ("glucose", "cadical"):
            add_unique(
                scope="hb", instances=["bcspwr02", "bcsstk01"], solver=solver,
                encoding="order", strategy="incremental", amo="sequential",
                symmetry=True, timeout=ext_t,
                experiments="A_backend_ext60;F_sat_vs_mip_ext60",
            )
    return entries


def identity(row: dict[str, Any]) -> tuple[str, ...]:
    sym_val = row.get("symmetry_breaking")
    sym_key = (
        "false"
        if sym_val is False
        else ("true" if sym_val is True else str(sym_val or "").lower())
    )
    t_val = row.get("timeout_s")
    t_key = "" if t_val in (None, "") else str(float(t_val))
    return (
        str(row.get("instance") or ""),
        str(row.get("solver") or ""),
        str(row.get("encoding") or ""),
        str(row.get("strategy") or ""),
        str(row.get("amo") or ""),
        sym_key,
        t_key,
        str(row.get("repetition") or ""),
    )


def _load_provenance_and_audit(
    meta: BenchmarkInstanceMeta,
    provenance_map: dict[str, dict[str, Any]],
    raw_dir: Path | None,
) -> tuple[str, Any | None, Path | None, str | None, str | None]:
    """Resolve official instance readiness via provenance and Matrix Market inspection."""
    prov = provenance_map.get(meta.name)
    dataset_status = (
        str(prov.get("validation_status", "NEEDS_VERIFICATION")) if prov else "NEEDS_VERIFICATION"
    )
    prov_sha = str(prov.get("sha256", "")) if prov else None

    candidate_path: Path | None = None
    if prov and prov.get("file_path"):
        p = Path(str(prov["file_path"]))
        if p.exists():
            candidate_path = p
    if candidate_path is None and raw_dir is not None:
        for ext in (".mtx.gz", ".mtx"):
            probe = raw_dir / f"{meta.name}{ext}"
            if probe.exists():
                candidate_path = probe
                break

    if dataset_status != "READY":
        return (
            dataset_status,
            None,
            candidate_path,
            prov_sha,
            f"Dataset status is {dataset_status}; excluded from official READY benchmark",
        )

    if candidate_path is None or not candidate_path.exists():
        return (
            dataset_status,
            None,
            None,
            prov_sha,
            "Verified READY matrix file not found locally; run scripts/acquire_benchmark.py",
        )

    actual_sha = hashlib.sha256(candidate_path.read_bytes()).hexdigest()
    if prov_sha and actual_sha != prov_sha:
        return (
            "INVALID_DATA",
            None,
            candidate_path,
            actual_sha,
            f"SHA-256 mismatch against provenance for {meta.name}",
        )

    audit = inspect_matrix_market(candidate_path)
    if audit.status != "READY":
        return (
            audit.status,
            None,
            candidate_path,
            actual_sha,
            f"Matrix Market inspection status={audit.status} (asymmetric={audit.asymmetric_pairs}, duplicates={audit.duplicate_entries})",
        )
    if audit.graph.order != meta.n:
        return (
            "INVALID_DATA",
            None,
            candidate_path,
            actual_sha,
            f"Vertex count mismatch: matrix has {audit.graph.order}, paper expects {meta.n}",
        )
    return "READY", audit.graph, candidate_path, actual_sha, None


def _run_sat_direct(
    graph: Graph,
    solver: str,
    encoding: str,
    strategy: str,
    amo: str,
    symmetry: bool,
    limits: ResourceLimits,
    est_breakdown: Any,
    solver_version: str,
) -> dict[str, Any]:
    encoder = PairwiseEncoding(amo) if encoding == "pairwise" else OrderEncoding(amo)
    engine = (
        RepeatedSATSolver(encoder, backend_name=solver)
        if strategy == "repeated"
        else IncrementalSATSolver(encoder, backend_name=solver)
    )
    result = engine.solve(
        graph,
        timeout_seconds=limits.timeout_seconds,
        symmetry_breaking=symmetry,
        limits=limits,
    )
    report = (
        validate_solution(graph, result.permutation, claimed_bandwidth=result.bandwidth)
        if result.permutation is not None
        else None
    )
    status = result.status.value
    if result.status is SolutionStatus.SKIPPED and result.metadata.get("skipped_reason"):
        status = "RESOURCE_LIMIT"
    if report is not None and not report.valid:
        status = SolutionStatus.ERROR.value

    error = None
    if report is not None and not report.valid:
        error = "; ".join(report.errors)
    elif result.status is SolutionStatus.SKIPPED:
        error = result.metadata.get("skipped_reason") or result.metadata.get("worker_reason")
    elif result.status in (SolutionStatus.TIMEOUT, SolutionStatus.FEASIBLE, SolutionStatus.ERROR):
        error = result.metadata.get("worker_reason") or result.metadata.get("reason")

    proof_status = (
        "PROVED"
        if status == SolutionStatus.OPTIMAL.value
        else ("UNPROVED" if status in ("FEASIBLE", "TIMEOUT") else "N/A")
    )
    num_vars = result.num_variables
    orig_vars = est_breakdown.num_original_vars if num_vars is not None else None
    chan_vars = est_breakdown.num_channeling_vars if num_vars is not None else None
    aux_vars = (
        max(0, num_vars - (orig_vars or 0) - (chan_vars or 0))
        if num_vars is not None
        else None
    )
    return {
        "method": "SAT",
        "solver_version": solver_version,
        "status": status,
        "proof_status": proof_status,
        "bandwidth": report.actual_bandwidth if report and report.valid else None,
        "lower_bound": result.lower_bound,
        "upper_bound": result.upper_bound,
        "objective_bound": result.lower_bound,
        "mip_gap": None,
        "validation": report.valid if report else None,
        "permutation": dict(result.permutation) if result.permutation is not None else None,
        "incumbent_source": result.metadata.get("incumbent_source"),
        "peak_rss_mb": result.metadata.get("sampled_peak_memory_mb") or _self_rss_mb(),
        "cnf_variables": num_vars,
        "cnf_original_vars": orig_vars,
        "cnf_channeling_vars": chan_vars,
        "cnf_aux_vars": aux_vars,
        "cnf_clauses": result.num_clauses,
        "sat_calls": result.sat_calls,
        "sat_trace": result.metadata.get("sat_trace"),
        "encoding_time_s": result.encoding_time_s,
        "solver_time_s": result.solving_time_s,
        "error": error,
    }


def _run_mip_direct(
    graph: Graph,
    solver: str,
    symmetry: bool,
    timeout: float,
    solver_version: str,
    threads: int | None = None,
) -> dict[str, Any]:
    mip = GurobiMIPSolver() if solver == "gurobi" else CPLEXMIPSolver()
    result = mip.solve(
        graph,
        timeout_seconds=timeout,
        symmetry_breaking=symmetry,
        threads=threads,
    )
    report = (
        validate_solution(graph, result.permutation, claimed_bandwidth=result.bandwidth)
        if result.permutation is not None and result.status is not SolutionStatus.UNAVAILABLE
        else None
    )
    status = result.status.value
    if report is not None and not report.valid:
        status = SolutionStatus.ERROR.value

    proof_status = (
        "PROVED"
        if status == SolutionStatus.OPTIMAL.value
        else ("UNPROVED" if status in ("FEASIBLE", "TIMEOUT") else "N/A")
    )
    unavail = result.status is SolutionStatus.UNAVAILABLE
    return {
        "method": "MIP",
        "solver_version": result.metadata.get("solver_version") or solver_version,
        "status": status,
        "proof_status": proof_status,
        "bandwidth": report.actual_bandwidth if report and report.valid else None,
        "lower_bound": result.lower_bound if not unavail else None,
        "upper_bound": result.upper_bound if not unavail else None,
        "objective_bound": result.metadata.get("best_bound") if not unavail else None,
        "mip_gap": result.metadata.get("mip_gap") if not unavail else None,
        "validation": report.valid if report else None,
        "permutation": (
            dict(result.permutation)
            if result.permutation is not None and not unavail
            else None
        ),
        "incumbent_source": "mip" if not unavail else None,
        "peak_rss_mb": _self_rss_mb(),
        "cnf_variables": None,
        "cnf_original_vars": None,
        "cnf_channeling_vars": None,
        "cnf_aux_vars": None,
        "cnf_clauses": None,
        "sat_calls": None,
        "sat_trace": None,
        "encoding_time_s": None,
        "solver_time_s": result.runtime_seconds if not unavail else None,
        "error": result.metadata.get("reason") if unavail else None,
    }


def worker(
    graph_path: Path,
    solver: str,
    encoding: str,
    strategy: str,
    amo: str,
    symmetry: bool,
    timeout: float,
    max_variables: int | None,
    max_clauses: int | None,
    progress_path: Path,
) -> None:
    """Subprocess fallback for platforms without POSIX fork (e.g. Windows)."""
    audit = inspect_matrix_market(graph_path)
    graph = audit.graph
    started = monotonic()
    if solver in ("glucose", "cadical"):
        encoder = PairwiseEncoding(amo) if encoding == "pairwise" else OrderEncoding(amo)
        engine = (
            RepeatedSATSolver(encoder, backend_name=solver)
            if strategy == "repeated"
            else IncrementalSATSolver(encoder, backend_name=solver)
        )

        def checkpoint(permutation, bandwidth):
            data = json.dumps({"permutation": dict(permutation), "bandwidth": bandwidth})
            tmp = progress_path.with_suffix(".tmp")
            tmp.write_text(data, encoding="utf-8")
            os.replace(tmp, progress_path)

        limits = ResourceLimits(
            max_variables=max_variables,
            max_clauses=max_clauses,
            timeout_seconds=None,
            memory_limit_mb=None,
        )
        result = engine.solve(
            graph,
            timeout_seconds=None,
            symmetry_breaking=symmetry,
            limits=limits,
            on_incumbent=checkpoint,
        )
        report = (
            validate_solution(graph, result.permutation, claimed_bandwidth=result.bandwidth)
            if result.permutation is not None
            else None
        )
        payload = {
            "method": "SAT",
            "solver_version": _sat_backend_version(solver),
            "status": result.status.value,
            "proof_status": "PROVED" if result.status is SolutionStatus.OPTIMAL else "UNPROVED",
            "bandwidth": report.actual_bandwidth if report and report.valid else None,
            "lower_bound": result.lower_bound,
            "upper_bound": result.upper_bound,
            "objective_bound": result.lower_bound,
            "mip_gap": None,
            "validation": report.valid if report else None,
            "permutation": dict(result.permutation) if result.permutation is not None else None,
            "incumbent_source": result.metadata.get("incumbent_source"),
            "total_wall_time_s": monotonic() - started,
            "peak_rss_mb": _self_rss_mb(),
            "cnf_variables": result.num_variables,
            "cnf_clauses": result.num_clauses,
            "sat_calls": result.sat_calls,
            "sat_trace": result.metadata.get("sat_trace"),
            "encoding_time_s": result.encoding_time_s,
            "solver_time_s": result.solving_time_s,
            "error": result.metadata.get("skipped_reason"),
        }
    else:
        payload = _run_mip_direct(
            graph, solver, symmetry, max(0.0, timeout - 1.0), _mip_backend_version(solver)
        )
        payload["total_wall_time_s"] = monotonic() - started
    print(json.dumps(payload), flush=True)


def _format_csv_row(raw_row: dict[str, Any]) -> dict[str, Any]:
    """Convert None to empty string for CSV while keeping raw dict typed for JSON."""
    csv_row: dict[str, Any] = {}
    for field in FIELDS:
        val = raw_row.get(field)
        if val is None:
            csv_row[field] = ""
        elif isinstance(val, (dict, list)):
            csv_row[field] = json.dumps(val, separators=(",", ":"), sort_keys=True)
        else:
            csv_row[field] = val
    return csv_row


def _execute_plan_item(
    *,
    run_id: str,
    experiment: str,
    name: str,
    table: str,
    dataset_source: str,
    dataset_checksum: str | None,
    dataset_status: str,
    graph: Graph | None,
    matrix_path: Path | None,
    load_err: str | None,
    pub_lb: int | None,
    pub_best: int | None,
    expected_n: int,
    solver: str,
    encoding: str | None,
    strategy: str | None,
    search_mode: str | None,
    amo: str | None,
    symmetry: bool,
    timeout: float,
    threads: int | None,
    repetition: int,
    max_sat_vars: int | None,
    max_sat_clauses: int | None,
    max_mip_vars: int,
    memory_limit_mb: float | None,
    use_fork: bool,
    output_dir: Path,
    git_sha: str,
    solver_versions: dict[str, str],
) -> dict[str, Any]:
    row: dict[str, Any] = {field: None for field in FIELDS}
    row.update(
        run_id=run_id,
        timestamp=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        git_commit=git_sha,
        experiment=experiment,
        instance=name,
        table=table,
        dataset_source=dataset_source,
        dataset_checksum=dataset_checksum,
        dataset_status=dataset_status,
        n=expected_n,
        m=graph.size if graph is not None else None,
        method="SAT" if solver in ("glucose", "cadical") else "MIP",
        encoding=encoding,
        amo=amo,
        solver=solver,
        solver_version=solver_versions[solver],
        strategy=strategy,
        search_mode=search_mode,
        symmetry_breaking=symmetry,
        repetition=repetition,
        timeout_s=timeout,
        published_lb=pub_lb,
        published_best=pub_best,
    )

    started = monotonic()
    sat_limits = ResourceLimits(
        max_variables=int(max_sat_vars) if max_sat_vars is not None else None,
        max_clauses=int(max_sat_clauses) if max_sat_clauses is not None else None,
        timeout_seconds=timeout,
        memory_limit_mb=float(memory_limit_mb) if memory_limit_mb is not None else None,
    )

    if dataset_status not in ("READY", "SYNTHETIC_SAMPLE"):
        result: dict[str, Any] = {
            "status": SolutionStatus.SKIPPED.value,
            "proof_status": "N/A",
            "error": load_err,
        }
    elif graph is None:
        result = {
            "status": SolutionStatus.UNAVAILABLE.value,
            "proof_status": "N/A",
            "error": load_err,
        }
    elif solver in ("glucose", "cadical"):
        assert encoding is not None and strategy is not None and amo is not None
        est = estimate_cnf_size(
            graph, encoding=encoding, amo=amo, k=None, symmetry_breaking=symmetry
        )
        is_ok, cap_reason = sat_limits.check(est)
        if not is_ok:
            result = {
                "status": "RESOURCE_LIMIT",
                "proof_status": "N/A",
                "cnf_variables": est.num_variables,
                "cnf_original_vars": est.num_original_vars,
                "cnf_channeling_vars": est.num_channeling_vars,
                "cnf_aux_vars": est.num_aux_vars,
                "cnf_clauses": est.num_clauses,
                "error": cap_reason,
            }
        elif use_fork:
            result = _run_sat_direct(
                graph,
                solver,
                encoding,
                strategy,
                amo,
                symmetry,
                sat_limits,
                est,
                solver_versions[solver],
            )
        else:
            assert matrix_path is not None
            progress_path = output_dir / "sat_incumbent.json"
            progress_path.unlink(missing_ok=True)
            args = [
                sys.executable,
                "-m",
                "bmp.experiments.member2_hb",
                "--worker",
                str(matrix_path),
                solver,
                encoding,
                strategy,
                amo,
                str(symmetry).lower(),
                str(timeout),
                str(max_sat_vars or ""),
                str(max_sat_clauses or ""),
                str(progress_path),
            ]
            try:
                completed = subprocess.run(
                    args, capture_output=True, text=True, timeout=timeout, check=False
                )
                if completed.returncode:
                    result = {
                        "status": SolutionStatus.ERROR.value,
                        "proof_status": "N/A",
                        "error": completed.stderr[-2000:] or completed.stdout[-2000:],
                    }
                else:
                    result = json.loads(completed.stdout.strip().splitlines()[-1])
            except subprocess.TimeoutExpired:
                ckpt = (
                    json.loads(progress_path.read_text(encoding="utf-8"))
                    if progress_path.exists()
                    else None
                )
                if ckpt and ckpt.get("permutation"):
                    perm = {int(v): int(p) for v, p in ckpt["permutation"].items()}
                    rep = validate_solution(graph, perm)
                    result = {
                        "status": SolutionStatus.TIMEOUT.value,
                        "proof_status": "UNPROVED",
                        "bandwidth": rep.actual_bandwidth if rep.valid else None,
                        "validation": rep.valid,
                        "permutation": perm,
                        "incumbent_source": "sat_checkpoint",
                        "error": "Hard wall timeout; preserved last valid incumbent",
                    }
                else:
                    result = {
                        "status": SolutionStatus.TIMEOUT.value,
                        "proof_status": "N/A",
                        "error": "Hard wall timeout before any checkpoint",
                    }
    elif solver in ("gurobi", "cplex") and graph.order ** 2 > max_mip_vars:
        result = {
            "status": "RESOURCE_LIMIT",
            "proof_status": "N/A",
            "error": f"MIP binary variables {graph.order ** 2} exceed cap {max_mip_vars}",
        }
    else:
        result = _run_mip_direct(
            graph,
            solver,
            symmetry,
            timeout,
            solver_versions[solver],
            threads=threads,
        )

    perm = result.get("permutation")
    if perm is not None and graph is not None:
        perm_int = {int(v): int(p) for v, p in perm.items()}
        report = validate_solution(graph, perm_int, claimed_bandwidth=result.get("bandwidth"))
        result["validation"] = report.valid
        result["bandwidth"] = report.actual_bandwidth
        result["permutation"] = perm_int
        if not report.valid:
            result["status"] = SolutionStatus.ERROR.value
            result["error"] = "; ".join(report.errors)

    row.update(result)
    row["total_wall_time_s"] = round(monotonic() - started, 6)
    return row


def run(config_path: Path, selected: set[str] | None = None, resume: bool = True) -> None:
    config_path = config_path.resolve()
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))["benchmark"]
    config.setdefault("solvers", ["glucose", "gurobi", "cplex"])
    config.setdefault("amo", ["pairwise", "sequential", "binary", "commander"])
    mode = str(config.get("mode", "catalog"))
    timeout = float(config["timeout_seconds"])
    repetitions = int(config.get("repetitions", 1))
    max_batch_seconds = float(config.get("max_batch_seconds", 0.0) or 0.0)
    if timeout <= 0 or repetitions < 1:
        raise ValueError("timeout_seconds and repetitions must be positive")

    root = config_path.parent
    provenance_path = root / config.get(
        "provenance", config.get("provenance_file", "../data/benchmark_provenance.json")
    )
    provenance_map: dict[str, dict[str, Any]] = {}
    if provenance_path.exists():
        for entry in json.loads(provenance_path.read_text(encoding="utf-8")):
            provenance_map[entry["instance"]] = entry

    raw_dir = (root / config.get("raw_dir", "../data/benchmarks/raw")).resolve()
    max_sat_vars = config.get("max_sat_variables", config.get("max_variables", 500_000))
    max_sat_clauses = config.get("max_sat_clauses", config.get("max_clauses", 2_500_000))
    max_mip_vars = int(config.get("max_mip_variables", 250_000))
    memory_limit_mb = config.get("memory_limit_mb")

    output_dir = (root / config["output_dir"]).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_csv = output_dir / "runs.csv"
    output_json = output_dir / "runs.json"

    existing_json: list[dict[str, Any]] = []
    if resume and output_json.exists():
        existing_json = json.loads(output_json.read_text(encoding="utf-8"))
    done = {identity(r) for r in existing_json} if resume else set()
    all_rows_json: list[dict[str, Any]] = list(existing_json) if resume else []

    git_sha = _git_commit()
    use_fork = _supports_fork()
    solver_versions = {
        "cadical": _sat_backend_version("cadical"),
        "glucose": _sat_backend_version("glucose"),
        "gurobi": _mip_backend_version("gurobi"),
        "cplex": _mip_backend_version("cplex"),
    }

    small_map: dict[str, tuple[Graph, int | None]] = {
        g.name: (g, obw) for g, obw in _pilot_small_graphs()
    }
    hb_cache: dict[str, tuple[str, Any | None, Path | None, str | None, str | None]] = {}

    def resolve_instance(scope: str, name: str):
        if scope == "small":
            g, obw = small_map[name]
            return (
                "Synthetic/Sample",
                f"bmp.core.generators:{name}",
                None,
                "SYNTHETIC_SAMPLE",
                g,
                None,
                None,
                None,
                obw,
                g.order,
            )
        meta = ALL_INSTANCES[name]
        if name not in hb_cache:
            hb_cache[name] = _load_provenance_and_audit(meta, provenance_map, raw_dir)
        dst_st, graph, mpath, sha, err = hb_cache[name]
        src_url = provenance_map.get(name, {}).get("source_url", "NIST MatrixMarket Harwell-Boeing")
        return meta.source_table, str(src_url), sha, dst_st, graph, mpath, err, meta.paper_lb, meta.paper_best, meta.n

    plan_items: list[dict[str, Any]]
    if mode == "pilot_m2_2":
        plan_items = _pilot_plan_entries(config)
    else:
        plan_items = []
        for meta in ALL_INSTANCES.values():
            if selected and meta.name not in selected:
                continue
            for solver, encoding, strategy, amo, symmetry in configurations(config):
                plan_items.append({
                    "scope": "hb",
                    "instance": meta.name,
                    "solver": solver,
                    "encoding": encoding or None,
                    "strategy": strategy or None,
                    "search_mode": (
                        "linear"
                        if strategy == "repeated"
                        else ("adaptive" if strategy == "incremental" else None)
                    ),
                    "amo": amo or None,
                    "symmetry_breaking": symmetry,
                    "timeout_s": timeout,
                    "experiments": "catalog",
                    "threads": None,
                })

    batch_started = monotonic()
    log_lines: list[str] = []
    run_counter = len(all_rows_json)

    csv_mode = "a" if (resume and output_csv.exists()) else "w"
    with output_csv.open(csv_mode, newline="", encoding="utf-8") as csv_stream:
        writer = csv.DictWriter(csv_stream, fieldnames=FIELDS)
        if csv_mode == "w" or not output_csv.stat().st_size:
            writer.writeheader()
            csv_stream.flush()

        for item in plan_items:
            name = item["instance"]
            if selected and name not in selected:
                continue
            if item["scope"] == "small":
                g, obw = small_map[name]
                table = "Synthetic/Sample"
                dataset_src = f"bmp.core.generators:{name}"
                checksum = None
                dst_status = "SYNTHETIC_SAMPLE"
                graph, mpath, load_err = g, None, None
                pub_lb, pub_best, expected_n = None, obw, g.order
            else:
                (
                    table,
                    dataset_src,
                    checksum,
                    dst_status,
                    graph,
                    mpath,
                    load_err,
                    pub_lb,
                    pub_best,
                    expected_n,
                ) = resolve_instance("hb", name)

            for repetition in range(1, repetitions + 1):
                probe_id = (
                    name,
                    str(item["solver"] or ""),
                    str(item["encoding"] or ""),
                    str(item["strategy"] or ""),
                    str(item["amo"] or ""),
                    str(item["symmetry_breaking"]).lower(),
                    str(float(item["timeout_s"])),
                    str(repetition),
                )
                if probe_id in done:
                    continue
                if max_batch_seconds > 0 and (monotonic() - batch_started) >= max_batch_seconds:
                    log_lines.append(
                        f"BATCH_BUDGET_STOP after {monotonic() - batch_started:.1f}s before {name} {item['solver']}"
                    )
                    print(log_lines[-1], flush=True)
                    break

                run_counter += 1
                run_id = f"m2_2_{run_counter:04d}"
                row = _execute_plan_item(
                    run_id=run_id,
                    experiment=item["experiments"],
                    name=name,
                    table=table,
                    dataset_source=dataset_src,
                    dataset_checksum=checksum,
                    dataset_status=dst_status,
                    graph=graph,
                    matrix_path=mpath,
                    load_err=load_err,
                    pub_lb=pub_lb,
                    pub_best=pub_best,
                    expected_n=expected_n,
                    solver=item["solver"],
                    encoding=item["encoding"],
                    strategy=item["strategy"],
                    search_mode=item["search_mode"],
                    amo=item["amo"],
                    symmetry=bool(item["symmetry_breaking"]),
                    timeout=float(item["timeout_s"]),
                    threads=item.get("threads"),
                    repetition=repetition,
                    max_sat_vars=max_sat_vars,
                    max_sat_clauses=max_sat_clauses,
                    max_mip_vars=max_mip_vars,
                    memory_limit_mb=memory_limit_mb,
                    use_fork=use_fork,
                    output_dir=output_dir,
                    git_sha=git_sha,
                    solver_versions=solver_versions,
                )
                all_rows_json.append(row)
                writer.writerow(_format_csv_row(row))
                csv_stream.flush()
                os.fsync(csv_stream.fileno())
                done.add(probe_id)
                line = (
                    f"{run_id} [{row['experiment']}] {name} {row['solver']} "
                    f"{row['encoding'] or '-'} {row['amo'] or '-'} {row['strategy'] or '-'} "
                    f"sym={row['symmetry_breaking']} t={row['timeout_s']}s -> "
                    f"{row['status']} ({row['proof_status']}) bw={row['bandwidth']} "
                    f"bound={row['objective_bound']} wall={row['total_wall_time_s']:.3f}s"
                )
                if row["error"]:
                    line += f" | note={row['error']}"
                log_lines.append(line)
                print(line, flush=True)
            else:
                continue
            break

    # Export JSON, metadata, per-instance & experiment summary, comparison, and logs
    output_json.write_text(json.dumps(all_rows_json, indent=2) + "\n", encoding="utf-8")
    metadata = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "git_commit": git_sha,
        "config": str(config_path),
        "mode": mode,
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "solver_versions": solver_versions,
        "resource_limits": {
            "max_sat_variables": max_sat_vars,
            "max_sat_clauses": max_sat_clauses,
            "max_mip_variables": max_mip_vars,
            "memory_limit_mb": memory_limit_mb,
            "max_batch_seconds": max_batch_seconds,
        },
        "total_batch_wall_s": round(monotonic() - batch_started, 3),
    }
    (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    if log_lines:
        with (output_dir / "run_log.txt").open("a", encoding="utf-8") as lf:
            lf.write("\n".join(log_lines) + "\n")

    summarize(output_dir, list(ALL_INSTANCES.values()), rows=all_rows_json)


def summarize(
    output_dir: Path,
    catalog: list[BenchmarkInstanceMeta] | None = None,
    *,
    rows: list[dict[str, Any]] | None = None,
) -> None:
    if catalog is None:
        catalog = list(ALL_INSTANCES.values())
    if rows is None:
        runs_json = output_dir / "runs.json"
        if runs_json.exists():
            rows = json.loads(runs_json.read_text(encoding="utf-8"))
        else:
            with (output_dir / "runs.csv").open(newline="", encoding="utf-8") as source:
                rows = list(csv.DictReader(source))

    by_name: dict[str, dict[str, Any]] = {}
    for row in rows:
        valid = row.get("validation") in (True, "True")
        bw_val = row.get("bandwidth")
        st = str(row.get("status") or "")
        if not valid or bw_val in (None, "") or st in ("UNAVAILABLE", "SKIPPED", "RESOURCE_LIMIT", "ERROR"):
            continue
        name = str(row["instance"])
        bw_int = int(bw_val)
        wall = float(row.get("total_wall_time_s") or 0.0)
        key = (bw_int, st != "OPTIMAL", wall)
        if name not in by_name or key < (
            int(by_name[name]["bandwidth"]),
            str(by_name[name]["status"]) != "OPTIMAL",
            float(by_name[name].get("total_wall_time_s") or 0.0),
        ):
            by_name[name] = row

    # Per-instance best summary JSON
    per_instance_summary = []
    report_rows = []
    counts = {"equal": 0, "better": 0, "worse": 0, "no_solution": 0}
    for meta in catalog:
        row = by_name.get(meta.name)
        if row is None:
            relation = "no_solution"
        else:
            bw = int(row["bandwidth"])
            relation = "equal" if bw == meta.paper_best else "better" if bw < meta.paper_best else "worse"
        counts[relation] += 1
        report_rows.append((
            meta.name,
            meta.source_table,
            row["dataset_status"] if row else "—",
            meta.paper_lb,
            meta.paper_best,
            row["bandwidth"] if row else "—",
            f"{row['solver']} ({row['encoding'] or 'MIP'}/{row['amo'] or '-'})" if row else "—",
            f"{float(row['total_wall_time_s']):.3f}" if row else "—",
            row["status"] if row else "—",
            relation,
        ))
        if row is not None:
            per_instance_summary.append({
                "instance": meta.name,
                "table": meta.source_table,
                "n": meta.n,
                "published_lb": meta.paper_lb,
                "published_best": meta.paper_best,
                "best_bandwidth": int(row["bandwidth"]),
                "best_status": row["status"],
                "proof_status": row.get("proof_status"),
                "best_solver": row["solver"],
                "best_encoding": row.get("encoding"),
                "best_amo": row.get("amo"),
                "wall_time_s": float(row["total_wall_time_s"]),
                "relation_to_paper_best": relation,
            })

    summary_payload = {
        "total_runs": len(rows),
        "status_counts": {
            st: sum(str(r.get("status")) == st for r in rows)
            for st in ("OPTIMAL", "FEASIBLE", "TIMEOUT", "RESOURCE_LIMIT", "SKIPPED", "UNAVAILABLE", "ERROR")
        },
        "catalog_relation_counts": counts,
        "per_instance_best": per_instance_summary,
    }
    (output_dir / "summary.json").write_text(json.dumps(summary_payload, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Member 2 Official Benchmark Comparison (113-instance Catalog)",
        "",
        "| Đồ thị | Bảng | Dataset | Paper LB | Paper Best | Bandwidth | Solver | Thời gian (s) | Trạng thái | Đối chiếu |",
        "|---|---|---|---:|---:|---:|---|---:|---|---|",
    ]
    lines += ["| " + " | ".join(map(str, entry)) + " |" for entry in report_rows]
    lines += [
        "",
        f"Tổng catalog: {len(catalog)} (Table 6: 31, Table 7: 41, Table 8: 41).",
        f"Bằng Best: {counts['equal']}; tốt hơn: {counts['better']}; kém hơn: {counts['worse']}; chưa có nghiệm trong đợt chạy: {counts['no_solution']}.",
        f"Tổng lượt chạy (kể cả small oracle/pilot): {len(rows)}; "
        + "; ".join(f"{k}: {v}" for k, v in summary_payload["status_counts"].items())
        + ".",
    ]
    (output_dir / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", nargs="?", type=Path)
    parser.add_argument("--instance", action="append")
    parser.add_argument("--rerun", action="store_true")
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Refresh comparison.md/summary.json from CSV/JSON without solving",
    )
    parser.add_argument(
        "--worker",
        nargs=10,
        metavar=(
            "GRAPH",
            "SOLVER",
            "ENCODING",
            "STRATEGY",
            "AMO",
            "SYMMETRY",
            "TIMEOUT",
            "MAX_VARS",
            "MAX_CLAUSES",
            "PROGRESS",
        ),
    )
    args = parser.parse_args()
    if args.worker:
        graph, solver, encoding, strategy, amo, symmetry, timeout, mv, mc, progress = args.worker
        worker(
            Path(graph),
            solver,
            encoding,
            strategy,
            amo,
            symmetry == "true",
            float(timeout),
            int(mv) if mv else None,
            int(mc) if mc else None,
            Path(progress),
        )
    elif args.config and args.report_only:
        config_path = args.config.resolve()
        config = tomllib.loads(config_path.read_text(encoding="utf-8"))["benchmark"]
        summarize((config_path.parent / config["output_dir"]).resolve(), list(ALL_INSTANCES.values()))
    elif args.config:
        run(args.config, set(args.instance) if args.instance else None, not args.rerun)
    else:
        parser.error("config is required")


if __name__ == "__main__":
    main()
