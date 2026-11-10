"""Resumable Member 2 benchmark over Leader's 113-instance official catalog.

Enforces READY-only dataset verification status, Leader CNF estimator/ResourceLimits,
worker timeout & RSS tracking, and exports CSV/JSON + paper comparison.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import multiprocessing
import os
import subprocess
import sys
import tomllib
from pathlib import Path
from time import monotonic
from typing import Any

from bmp.core.benchmark_catalog import ALL_INSTANCES, BenchmarkInstanceMeta
from bmp.core.solution import SolutionStatus
from bmp.core.validation import validate_solution
from bmp.encodings.estimator import ResourceLimits, estimate_cnf_size
from bmp.encodings.order import OrderEncoding
from bmp.encodings.pairwise import PairwiseEncoding
from bmp.io.readers import inspect_matrix_market
from bmp.solvers.exact.cplex import CPLEXMIPSolver
from bmp.solvers.exact.gurobi import GurobiMIPSolver
from bmp.solvers.sat.incremental import IncrementalSATSolver
from bmp.solvers.sat.repeated import RepeatedSATSolver

FIELDS = (
    "instance",
    "table",
    "dataset_status",
    "n",
    "edges",
    "solver",
    "encoding",
    "strategy",
    "amo",
    "symmetry_breaking",
    "repetition",
    "timeout_seconds",
    "runtime_total_s",
    "peak_memory_mb",
    "status",
    "bandwidth",
    "best_bound",
    "mip_gap",
    "validation",
    "permutation",
    "incumbent_source",
    "num_variables",
    "num_clauses",
    "sat_calls",
    "encoding_time_s",
    "solving_time_s",
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


def identity(row: dict[str, Any]) -> tuple[str, ...]:
    return (
        str(row["instance"]),
        str(row["solver"]),
        str(row["encoding"]),
        str(row["strategy"]),
        str(row["amo"]),
        str(row["symmetry_breaking"]).lower(),
        str(row["repetition"]),
    )


def _load_provenance_and_audit(
    meta: BenchmarkInstanceMeta,
    provenance_map: dict[str, dict[str, Any]],
    raw_dir: Path | None,
) -> tuple[str, Any | None, Path | None, str | None]:
    """Resolve official instance readiness via provenance and Matrix Market inspection."""
    prov = provenance_map.get(meta.name)
    dataset_status = str(prov.get("validation_status", "NEEDS_VERIFICATION")) if prov else "NEEDS_VERIFICATION"

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
            f"Dataset status is {dataset_status}; excluded from official READY benchmark",
        )

    if candidate_path is None or not candidate_path.exists():
        return (
            dataset_status,
            None,
            None,
            "Verified READY matrix file not found locally; run scripts/acquire_benchmark.py",
        )

    if prov and prov.get("sha256"):
        digest = hashlib.sha256(candidate_path.read_bytes()).hexdigest()
        if digest != prov["sha256"]:
            return (
                "INVALID_DATA",
                None,
                candidate_path,
                f"SHA-256 mismatch against provenance for {meta.name}",
            )

    audit = inspect_matrix_market(candidate_path)
    if audit.status != "READY":
        return (
            audit.status,
            None,
            candidate_path,
            f"Matrix Market inspection status={audit.status} (asymmetric={audit.asymmetric_pairs}, duplicates={audit.duplicate_entries})",
        )
    if audit.graph.order != meta.n:
        return (
            "INVALID_DATA",
            None,
            candidate_path,
            f"Vertex count mismatch: matrix has {audit.graph.order}, paper expects {meta.n}",
        )
    return "READY", audit.graph, candidate_path, None


def _run_sat_direct(
    graph: Any,
    solver: str,
    encoding: str,
    strategy: str,
    amo: str,
    symmetry: bool,
    limits: ResourceLimits,
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
    if report is not None and not report.valid:
        status = SolutionStatus.ERROR.value
    error = ""
    if report is not None and not report.valid:
        error = "; ".join(report.errors)
    elif result.status is SolutionStatus.SKIPPED:
        error = str(
            result.metadata.get("skipped_reason")
            or result.metadata.get("worker_reason")
            or ""
        )
    elif result.status in (SolutionStatus.TIMEOUT, SolutionStatus.FEASIBLE, SolutionStatus.ERROR):
        error = str(result.metadata.get("worker_reason") or result.metadata.get("reason") or "")
    return {
        "status": status,
        "bandwidth": report.actual_bandwidth if report and report.valid else None,
        "best_bound": result.lower_bound,
        "mip_gap": None,
        "validation": report.valid if report else None,
        "permutation": dict(result.permutation) if result.permutation is not None else None,
        "incumbent_source": result.metadata.get("incumbent_source", "initial"),
        "peak_memory_mb": result.metadata.get("sampled_peak_memory_mb") or _self_rss_mb(),
        "num_variables": result.num_variables,
        "num_clauses": result.num_clauses,
        "sat_calls": result.sat_calls,
        "encoding_time_s": result.encoding_time_s,
        "solving_time_s": result.solving_time_s,
        "error": error,
    }


def _run_mip_direct(
    graph: Any,
    solver: str,
    symmetry: bool,
    timeout: float,
) -> dict[str, Any]:
    mip = GurobiMIPSolver() if solver == "gurobi" else CPLEXMIPSolver()
    result = mip.solve(graph, timeout_seconds=timeout, symmetry_breaking=symmetry)
    report = (
        validate_solution(graph, result.permutation, claimed_bandwidth=result.bandwidth)
        if result.permutation is not None and result.status is not SolutionStatus.UNAVAILABLE
        else None
    )
    status = result.status.value
    if report is not None and not report.valid:
        status = SolutionStatus.ERROR.value
    return {
        "status": status,
        "bandwidth": report.actual_bandwidth if report and report.valid else None,
        "best_bound": result.metadata.get("best_bound", result.lower_bound),
        "mip_gap": result.metadata.get("mip_gap"),
        "validation": report.valid if report else None,
        "permutation": (
            dict(result.permutation)
            if result.permutation is not None and result.status is not SolutionStatus.UNAVAILABLE
            else None
        ),
        "incumbent_source": "mip" if result.status is not SolutionStatus.UNAVAILABLE else "",
        "peak_memory_mb": _self_rss_mb(),
        "num_variables": None,
        "num_clauses": None,
        "sat_calls": None,
        "encoding_time_s": None,
        "solving_time_s": None,
        "error": str(result.metadata.get("reason", "")) if status == "UNAVAILABLE" else "",
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
            "status": result.status.value,
            "bandwidth": report.actual_bandwidth if report and report.valid else None,
            "best_bound": result.lower_bound,
            "mip_gap": None,
            "validation": report.valid if report else None,
            "permutation": dict(result.permutation) if result.permutation is not None else None,
            "incumbent_source": result.metadata.get("incumbent_source", "initial"),
            "runtime_total_s": monotonic() - started,
            "peak_memory_mb": _self_rss_mb(),
            "num_variables": result.num_variables,
            "num_clauses": result.num_clauses,
            "sat_calls": result.sat_calls,
            "encoding_time_s": result.encoding_time_s,
            "solving_time_s": result.solving_time_s,
            "error": str(result.metadata.get("skipped_reason") or ""),
        }
    else:
        payload = _run_mip_direct(graph, solver, symmetry, max(0.0, timeout - 1.0))
        payload["runtime_total_s"] = monotonic() - started
    print(json.dumps(payload), flush=True)


def run(config_path: Path, selected: set[str] | None = None, resume: bool = True) -> None:
    config_path = config_path.resolve()
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))["benchmark"]
    config.setdefault("solvers", ["glucose", "gurobi", "cplex"])
    config.setdefault("amo", ["pairwise", "sequential", "binary", "commander"])
    timeout = float(config["timeout_seconds"])
    repetitions = int(config["repetitions"])
    if timeout <= 0 or repetitions < 1:
        raise ValueError("timeout_seconds and repetitions must be positive")

    root = config_path.parent
    provenance_path = root / config.get("provenance", "../data/benchmark_provenance.json")
    provenance_map: dict[str, dict[str, Any]] = {}
    if provenance_path.exists():
        for entry in json.loads(provenance_path.read_text(encoding="utf-8")):
            provenance_map[entry["instance"]] = entry

    raw_dir_cfg = config.get("raw_dir", "../data/benchmarks/raw")
    raw_dir = (root / raw_dir_cfg).resolve()

    max_sat_vars = config.get("max_sat_variables", 500_000)
    max_sat_clauses = config.get("max_sat_clauses", 2_500_000)
    max_mip_vars = int(config.get("max_mip_variables", 250_000))
    memory_limit_mb = config.get("memory_limit_mb")

    output_dir = (root / config["output_dir"]).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "runs.csv"
    existing: list[dict[str, str]] = []
    if output_path.exists():
        with output_path.open(newline="", encoding="utf-8") as source:
            existing = list(csv.DictReader(source))
    done = {identity(row) for row in existing} if resume else set()

    catalog = list(ALL_INSTANCES.values())
    use_fork = _supports_fork()
    sat_limits = ResourceLimits(
        max_variables=int(max_sat_vars) if max_sat_vars is not None else None,
        max_clauses=int(max_sat_clauses) if max_sat_clauses is not None else None,
        timeout_seconds=timeout,
        memory_limit_mb=float(memory_limit_mb) if memory_limit_mb is not None else None,
    )

    with output_path.open("a", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS)
        if not output_path.stat().st_size:
            writer.writeheader()
            output.flush()

        for meta in catalog:
            name = meta.name
            if selected and name not in selected:
                continue

            dataset_status, graph, matrix_path, load_err = _load_provenance_and_audit(
                meta, provenance_map, raw_dir
            )

            for solver, encoding, strategy, amo, symmetry in configurations(config):
                for repetition in range(1, repetitions + 1):
                    row: dict[str, Any] = dict.fromkeys(FIELDS, "")
                    row.update(
                        instance=name,
                        table=meta.source_table,
                        dataset_status=dataset_status,
                        n=meta.n,
                        edges=graph.size if graph is not None else "",
                        solver=solver,
                        encoding=encoding,
                        strategy=strategy,
                        amo=amo,
                        symmetry_breaking=str(symmetry).lower(),
                        repetition=repetition,
                        timeout_seconds=timeout,
                    )
                    if identity(row) in done:
                        continue

                    started = monotonic()
                    if dataset_status != "READY":
                        result = {
                            "status": SolutionStatus.SKIPPED.value,
                            "error": load_err,
                        }
                    elif graph is None or matrix_path is None:
                        result = {
                            "status": SolutionStatus.UNAVAILABLE.value,
                            "error": load_err,
                        }
                    elif solver in ("glucose", "cadical"):
                        est = estimate_cnf_size(
                            graph,
                            encoding=encoding,
                            amo=amo,
                            k=None,
                            symmetry_breaking=symmetry,
                        )
                        is_ok, cap_reason = sat_limits.check(est)
                        if not is_ok:
                            result = {
                                "status": SolutionStatus.SKIPPED.value,
                                "num_variables": est.num_variables,
                                "num_clauses": est.num_clauses,
                                "error": cap_reason,
                            }
                        elif use_fork:
                            result = _run_sat_direct(
                                graph, solver, encoding, strategy, amo, symmetry, sat_limits
                            )
                        else:
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
                                        "bandwidth": rep.actual_bandwidth if rep.valid else None,
                                        "validation": rep.valid,
                                        "permutation": perm,
                                        "incumbent_source": "sat_checkpoint",
                                        "error": "Hard wall timeout; preserved last valid incumbent",
                                    }
                                else:
                                    result = {
                                        "status": SolutionStatus.TIMEOUT.value,
                                        "error": "Hard wall timeout before any checkpoint",
                                    }
                    elif solver in ("gurobi", "cplex") and graph.order ** 2 > max_mip_vars:
                        result = {
                            "status": SolutionStatus.SKIPPED.value,
                            "num_variables": graph.order ** 2,
                            "error": f"MIP binary variables {graph.order ** 2} exceed cap {max_mip_vars}",
                        }
                    else:
                        result = _run_mip_direct(graph, solver, symmetry, timeout)

                    permutation = result.pop("permutation", None)
                    if permutation is not None and graph is not None:
                        permutation = {int(v): int(p) for v, p in permutation.items()}
                        report = validate_solution(
                            graph, permutation, claimed_bandwidth=result.get("bandwidth")
                        )
                        result["validation"] = report.valid
                        result["bandwidth"] = report.actual_bandwidth
                        if not report.valid:
                            result["status"] = SolutionStatus.ERROR.value
                            result["error"] = "; ".join(report.errors)

                    row.update(result)
                    row["permutation"] = json.dumps(permutation, sort_keys=True) if permutation else ""
                    row["runtime_total_s"] = monotonic() - started
                    writer.writerow(row)
                    output.flush()
                    os.fsync(output.fileno())
                    done.add(identity(row))
                    print(
                        f"{name} [{dataset_status}] {solver} {encoding} {strategy} {amo} "
                        f"sym={symmetry}: {row['status']} bw={row['bandwidth']} {row['runtime_total_s']:.2f}s",
                        flush=True,
                    )

    summarize(output_dir, catalog)


def summarize(output_dir: Path, catalog: list[BenchmarkInstanceMeta] | None = None) -> None:
    if catalog is None:
        catalog = list(ALL_INSTANCES.values())
    runs_csv = output_dir / "runs.csv"
    with runs_csv.open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))

    by_name: dict[str, dict[str, str]] = {}
    for row in rows:
        if (
            row["validation"] != "True"
            or not row["bandwidth"]
            or row["status"] in ("UNAVAILABLE", "SKIPPED", "ERROR")
        ):
            continue
        name = row["instance"]
        key = (
            int(row["bandwidth"]),
            row["status"] != "OPTIMAL",
            float(row["runtime_total_s"]),
        )
        if name not in by_name or key < (
            int(by_name[name]["bandwidth"]),
            by_name[name]["status"] != "OPTIMAL",
            float(by_name[name]["runtime_total_s"]),
        ):
            by_name[name] = row

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
            row["solver"] if row else "—",
            f"{float(row['runtime_total_s']):.3f}" if row else "—",
            row["status"] if row else "—",
            relation,
        ))

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
        f"Bằng Best: {counts['equal']}; tốt hơn: {counts['better']}; kém hơn: {counts['worse']}; chưa có nghiệm: {counts['no_solution']}.",
        f"Tổng lượt: {len(rows)}; OPTIMAL: {sum(r['status'] == 'OPTIMAL' for r in rows)}; "
        f"FEASIBLE: {sum(r['status'] == 'FEASIBLE' for r in rows)}; "
        f"TIMEOUT: {sum(r['status'] == 'TIMEOUT' for r in rows)}; "
        f"SKIPPED: {sum(r['status'] == 'SKIPPED' for r in rows)}; "
        f"UNAVAILABLE: {sum(r['status'] == 'UNAVAILABLE' for r in rows)}; "
        f"ERROR: {sum(r['status'] == 'ERROR' for r in rows)}.",
    ]
    (output_dir / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # JSON export alongside CSV for shared compatibility
    (output_dir / "runs.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", nargs="?", type=Path)
    parser.add_argument("--instance", action="append")
    parser.add_argument("--rerun", action="store_true")
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Refresh comparison.md/runs.json from runs.csv without solving",
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
