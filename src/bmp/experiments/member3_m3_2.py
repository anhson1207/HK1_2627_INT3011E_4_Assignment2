"""Phase M3.2 controlled SAT pilot benchmark for Product AMO, Ladder AMO, and MiniSat."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import platform
import statistics
import sys
import tomllib
from pathlib import Path
from time import monotonic
from typing import Any

from bmp.core.benchmark_catalog import ALL_INSTANCES
from bmp.core.graph import Graph
from bmp.core.solution import SolutionStatus
from bmp.core.validation import validate_solution
from bmp.encodings.estimator import ResourceLimits, estimate_cnf_size
from bmp.encodings.order import OrderEncoding
from bmp.encodings.pairwise import PairwiseEncoding
from bmp.experiments.member2_hb import _git_commit, _sat_backend_version, _self_rss_mb
from bmp.io.readers import inspect_matrix_market
from bmp.solvers.sat.incremental import IncrementalSATSolver
from bmp.solvers.sat.repeated import RepeatedSATSolver
from bmp.solvers.sat.search import compute_initial_upper_bound, compute_lower_bound

M3_2_FIELDS: tuple[str, ...] = (
    "run_id",
    "timestamp",
    "git_commit",
    "study",
    "instance",
    "table",
    "dataset_source",
    "dataset_sha256",
    "dataset_status",
    "n",
    "m",
    "encoding",
    "amo",
    "backend",
    "backend_version",
    "strategy",
    "search_mode",
    "symmetry_breaking",
    "timeout_s",
    "initial_lb",
    "initial_ub",
    "final_lb",
    "final_ub",
    "bandwidth",
    "status",
    "proof_status",
    "published_lb",
    "published_best",
    "sat_calls",
    "solver_creations",
    "solver_reused",
    "threshold_sequence",
    "cnf_variables",
    "cnf_original_vars",
    "cnf_channeling_vars",
    "cnf_aux_vars",
    "cnf_clauses",
    "estimated_variables",
    "estimated_clauses",
    "encoding_time_s",
    "solving_time_s",
    "total_time_s",
    "peak_memory_mb",
    "incumbent_source",
    "validation_valid",
    "validation_errors",
    "sat_trace",
    "note",
)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _build_encoder(encoding_family: str, amo: str):
    if encoding_family == "pairwise":
        return PairwiseEncoding(amo=amo)
    if encoding_family == "order":
        return OrderEncoding(amo=amo)
    raise ValueError(f"Unsupported encoding family: {encoding_family}")


def _build_plan(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Build deduplicated pilot plan covering Studies A, B, C, and D."""
    timeout_s = float(config["timeout_seconds"])
    sym = bool(config.get("symmetry_breaking", True))
    pilot_instances = list(config["pilot_instances"])
    b_order_instances = list(config.get("study_b_order_instances", pilot_instances))
    c_instances = list(config.get("study_c_instances", pilot_instances))
    probe_instances = list(config.get("resource_limit_probe_instances", []))

    ordered_specs: dict[tuple[Any, ...], dict[str, Any]] = {}

    def add_spec(
        *,
        study: str,
        instance: str,
        encoding: str,
        amo: str,
        backend: str,
        strategy: str,
        search_mode: str,
    ) -> None:
        key = (instance, encoding, amo, backend, strategy, search_mode, sym, timeout_s)
        if key in ordered_specs:
            existing = ordered_specs[key]["studies"]
            if study not in existing:
                existing.append(study)
            return
        ordered_specs[key] = {
            "studies": [study],
            "instance": instance,
            "encoding": encoding,
            "amo": amo,
            "backend": backend,
            "strategy": strategy,
            "search_mode": search_mode,
            "symmetry_breaking": sym,
            "timeout_s": timeout_s,
        }

    # Study A: MiniSat vs CaDiCaL vs Glucose (order + sequential + incremental)
    for instance in pilot_instances:
        for backend in config["study_a_backends"]:
            add_spec(
                study="study_a_backends",
                instance=instance,
                encoding="order",
                amo="sequential",
                backend=backend,
                strategy="incremental",
                search_mode="linear",
            )

    # Study B: Product AMO vs available AMOs under Pairwise & Order (MiniSat)
    for instance in pilot_instances:
        for amo in config["study_b_amos"]:
            add_spec(
                study="study_b_amo_comparison",
                instance=instance,
                encoding="pairwise",
                amo=amo,
                backend="minisat",
                strategy="incremental",
                search_mode="linear",
            )
    for instance in b_order_instances:
        for amo in config["study_b_amos"]:
            add_spec(
                study="study_b_amo_comparison",
                instance=instance,
                encoding="order",
                amo=amo,
                backend="minisat",
                strategy="incremental",
                search_mode="linear",
            )
    for instance in probe_instances:
        add_spec(
            study="study_b_amo_comparison",
            instance=instance,
            encoding="pairwise",
            amo="product",
            backend="minisat",
            strategy="incremental",
            search_mode="linear",
        )

    # Study C: Ladder vs Sequential equivalence audit on MiniSat
    for instance in c_instances:
        for encoding in ("pairwise", "order"):
            for strategy in ("incremental", "repeated"):
                for amo in config["study_c_amos"]:
                    add_spec(
                        study="study_c_ladder_vs_sequential",
                        instance=instance,
                        encoding=encoding,
                        amo=amo,
                        backend="minisat",
                        strategy=strategy,
                        search_mode="linear",
                    )

    # Study D: Repeated (linear & binary) vs Incremental on MiniSat
    for instance in pilot_instances:
        for encoding in ("order", "pairwise"):
            for strategy, search_mode in (
                ("repeated", "linear"),
                ("repeated", "binary"),
                ("incremental", "linear"),
            ):
                add_spec(
                    study="study_d_repeated_vs_incremental",
                    instance=instance,
                    encoding=encoding,
                    amo="product",
                    backend="minisat",
                    strategy=strategy,
                    search_mode=search_mode,
                )

    out: list[dict[str, Any]] = []
    for idx, spec in enumerate(ordered_specs.values(), start=1):
        spec["run_id"] = f"m32-{idx:03d}"
        spec["study"] = ";".join(spec.pop("studies"))
        out.append(spec)
    return out


def _format_csv_row(raw_row: dict[str, Any]) -> dict[str, Any]:
    formatted: dict[str, Any] = {}
    for field in M3_2_FIELDS:
        val = raw_row.get(field)
        if val is None:
            formatted[field] = ""
        elif isinstance(val, (dict, list)):
            formatted[field] = json.dumps(val, separators=(",", ":"), sort_keys=True)
        else:
            formatted[field] = val
    return formatted


def _load_verified_ready_instance(
    name: str,
    provenance_by_name: dict[str, dict[str, Any]],
    raw_dir: Path,
) -> tuple[Graph, dict[str, Any], Path]:
    meta = ALL_INSTANCES[name]
    prov = provenance_by_name[name]
    if prov["validation_status"] != "READY":
        raise ValueError(
            f"Refusing non-READY instance {name}: status={prov['validation_status']}"
        )
    raw_path = raw_dir / f"{name}.mtx.gz"
    if not raw_path.is_file():
        raise FileNotFoundError(f"Missing raw instance file: {raw_path}")
    actual_sha = _sha256(raw_path)
    if actual_sha != prov["sha256"]:
        raise ValueError(
            f"SHA-256 mismatch for {name}: expected {prov['sha256']}, got {actual_sha}"
        )
    audit = inspect_matrix_market(raw_path)
    if audit.status != "READY" or audit.rows != meta.n:
        raise ValueError(
            f"Matrix Market audit mismatch for {name}: status={audit.status}, n={audit.rows}"
        )
    graph = Graph.from_edges(
        range(1, audit.rows + 1),
        ((u + 1, v + 1) for u, v in audit.graph.edges),
        name=name,
        metadata={"source": str(raw_path), "sha256": actual_sha, "table": meta.source_table},
    )
    return graph, prov, raw_path


def _execute_item(
    spec: dict[str, Any],
    *,
    graph: Graph,
    prov: dict[str, Any],
    raw_path: Path,
    limits: ResourceLimits,
    threshold_policy: str,
    git_sha: str,
    backend_versions: dict[str, str],
) -> dict[str, Any]:
    meta = ALL_INSTANCES[spec["instance"]]
    encoding = spec["encoding"]
    amo = spec["amo"]
    backend = spec["backend"]
    strategy = spec["strategy"]
    search_mode = spec["search_mode"]
    sym = bool(spec["symmetry_breaking"])
    timeout_s = float(spec["timeout_s"])

    init_lb = compute_lower_bound(graph)
    init_ub, _ = compute_initial_upper_bound(graph, symmetry_breaking=sym)
    target_k = max(0, init_ub - 1) if init_ub > init_lb else init_ub
    est = estimate_cnf_size(
        graph, encoding=encoding, amo=amo, k=target_k, symmetry_breaking=sym
    )

    row: dict[str, Any] = {field: None for field in M3_2_FIELDS}
    row.update(
        run_id=spec["run_id"],
        timestamp=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        git_commit=git_sha,
        study=spec["study"],
        instance=graph.name,
        table=meta.source_table,
        dataset_source=str(raw_path),
        dataset_sha256=prov["sha256"],
        dataset_status=prov["validation_status"],
        n=graph.order,
        m=graph.size,
        encoding=encoding,
        amo=amo,
        backend=backend,
        backend_version=backend_versions[backend],
        strategy=strategy,
        search_mode=search_mode,
        symmetry_breaking=sym,
        timeout_s=timeout_s,
        initial_lb=init_lb,
        initial_ub=init_ub,
        published_lb=meta.paper_lb,
        published_best=meta.paper_best,
        estimated_variables=est.num_variables,
        estimated_clauses=est.num_clauses,
    )

    encoder = _build_encoder(encoding, amo)
    if strategy == "repeated":
        solver = RepeatedSATSolver(
            encoder=encoder,
            backend_name=backend,
            search_mode=search_mode,
            threshold_policy=threshold_policy,
        )
    else:
        solver = IncrementalSATSolver(
            encoder=encoder,
            backend_name=backend,
            threshold_policy=threshold_policy,
        )

    started = monotonic()
    result = solver.solve(
        graph,
        timeout_seconds=timeout_s,
        symmetry_breaking=sym,
        limits=limits,
    )
    wall_s = monotonic() - started

    trace = result.metadata.get("sat_trace")
    threshold_seq = (
        [f"{ev.get('k')}:{ev.get('outcome')}" for ev in trace]
        if isinstance(trace, list)
        else []
    )
    skipped_reason = result.metadata.get("skipped_reason") or result.metadata.get("worker_reason")

    if result.status is SolutionStatus.SKIPPED:
        mapped_status = "RESOURCE_LIMIT"
        proof_status = "RESOURCE_LIMIT"
    elif result.status is SolutionStatus.OPTIMAL:
        mapped_status = "OPTIMAL"
        proof_status = "PROVED_OPTIMAL"
    elif result.status is SolutionStatus.FEASIBLE:
        mapped_status = "TIMEOUT" if skipped_reason and "deadline" in str(skipped_reason).lower() else "FEASIBLE"
        proof_status = "TIMEOUT_WITH_INCUMBENT" if mapped_status == "TIMEOUT" else "FEASIBLE_UNPROVED"
    elif result.status is SolutionStatus.TIMEOUT:
        mapped_status = "TIMEOUT"
        proof_status = "TIMEOUT_WITH_INCUMBENT" if result.permutation is not None else "TIMEOUT_NO_SOLUTION"
    else:
        mapped_status = result.status.value
        proof_status = result.status.value

    report = (
        validate_solution(graph, result.permutation, claimed_bandwidth=result.bandwidth)
        if result.permutation is not None
        else None
    )
    if report is not None and not report.valid:
        mapped_status = "ERROR"
        proof_status = "VALIDATION_FAILED"

    ran_sat = (result.sat_calls > 0) or (
        result.num_variables is not None and mapped_status != "RESOURCE_LIMIT"
    )
    attempted_calls = (
        result.sat_calls
        if result.sat_calls > 0
        else (len(trace) if isinstance(trace, list) and mapped_status != "RESOURCE_LIMIT" else 0)
    )
    creations: int | None = None
    reused: bool | None = None
    if ran_sat and attempted_calls > 0:
        if strategy == "incremental":
            creations = 1
            reused = True
        else:
            creations = attempted_calls
            reused = False

    row.update(
        final_lb=result.lower_bound,
        final_ub=result.upper_bound,
        bandwidth=report.actual_bandwidth if report and report.valid else None,
        status=mapped_status,
        proof_status=proof_status,
        sat_calls=None if mapped_status == "RESOURCE_LIMIT" else attempted_calls,
        solver_creations=creations,
        solver_reused=reused,
        threshold_sequence=";".join(threshold_seq) if threshold_seq else None,
        cnf_variables=result.num_variables if ran_sat else None,
        cnf_original_vars=est.num_original_vars if ran_sat else None,
        cnf_channeling_vars=est.num_channeling_vars if ran_sat else None,
        cnf_aux_vars=est.num_aux_vars if ran_sat else None,
        cnf_clauses=result.num_clauses if ran_sat else None,
        encoding_time_s=round(result.encoding_time_s, 6) if ran_sat else None,
        solving_time_s=round(result.solving_time_s, 6) if ran_sat else None,
        total_time_s=round(wall_s, 6),
        peak_memory_mb=result.metadata.get("sampled_peak_memory_mb") or _self_rss_mb(),
        incumbent_source=result.metadata.get("incumbent_source"),
        validation_valid=report.valid if report is not None else None,
        validation_errors="; ".join(report.errors) if report and report.errors else None,
        sat_trace=trace,
        note=skipped_reason,
    )
    return row


def _write_summary_and_report(
    rows: list[dict[str, Any]],
    output_dir: Path,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    for r in rows:
        st = str(r["status"])
        status_counts[st] = status_counts.get(st, 0) + 1

    # Ladder vs Sequential structural check
    by_key = {
        (r["instance"], r["encoding"], r["amo"], r["backend"], r["strategy"], r["search_mode"]): r
        for r in rows
    }
    ladder_pairs: list[dict[str, Any]] = []
    for (inst, enc, amo, back, strat, mode), r_lad in by_key.items():
        if amo != "ladder":
            continue
        r_seq = by_key.get((inst, enc, "sequential", back, strat, mode))
        if r_seq is None:
            continue
        ladder_pairs.append({
            "instance": inst,
            "encoding": enc,
            "strategy": strat,
            "ladder_vars": r_lad["cnf_variables"],
            "sequential_vars": r_seq["cnf_variables"],
            "ladder_clauses": r_lad["cnf_clauses"],
            "sequential_clauses": r_seq["cnf_clauses"],
            "exact_cnf_match": (
                r_lad["cnf_variables"] == r_seq["cnf_variables"]
                and r_lad["cnf_clauses"] == r_seq["cnf_clauses"]
            ),
            "ladder_bw": r_lad["bandwidth"],
            "sequential_bw": r_seq["bandwidth"],
            "ladder_status": r_lad["status"],
            "sequential_status": r_seq["status"],
        })

    # Study summaries
    summary = {
        "total_runs": len(rows),
        "status_counts": status_counts,
        "all_validations_passed": all(
            r["validation_valid"] is True
            for r in rows
            if r["validation_valid"] is not None
        ),
        "ladder_vs_sequential_checks": ladder_pairs,
        "study_a_backends": [
            {
                "instance": r["instance"],
                "backend": r["backend"],
                "status": r["status"],
                "bandwidth": r["bandwidth"],
                "final_lb": r["final_lb"],
                "sat_calls": r["sat_calls"],
                "total_time_s": r["total_time_s"],
                "peak_memory_mb": r["peak_memory_mb"],
            }
            for r in rows
            if "study_a_backends" in str(r["study"])
        ],
        "study_b_amo_comparison": [
            {
                "instance": r["instance"],
                "encoding": r["encoding"],
                "amo": r["amo"],
                "status": r["status"],
                "bandwidth": r["bandwidth"],
                "estimated_variables": r["estimated_variables"],
                "estimated_clauses": r["estimated_clauses"],
                "cnf_variables": r["cnf_variables"],
                "cnf_clauses": r["cnf_clauses"],
                "total_time_s": r["total_time_s"],
            }
            for r in rows
            if "study_b_amo_comparison" in str(r["study"])
        ],
        "study_d_repeated_vs_incremental": [
            {
                "instance": r["instance"],
                "encoding": r["encoding"],
                "strategy": r["strategy"],
                "search_mode": r["search_mode"],
                "status": r["status"],
                "bandwidth": r["bandwidth"],
                "final_lb": r["final_lb"],
                "final_ub": r["final_ub"],
                "sat_calls": r["sat_calls"],
                "solver_creations": r["solver_creations"],
                "solver_reused": r["solver_reused"],
                "threshold_sequence": r["threshold_sequence"],
                "total_time_s": r["total_time_s"],
                "peak_memory_mb": r["peak_memory_mb"],
            }
            for r in rows
            if "study_d_repeated_vs_incremental" in str(r["study"])
        ],
    }

    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    (output_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )

    lines = [
        "# Member 3 Phase M3.2 SAT Pilot Benchmark Report",
        "",
        f"- **Git commit:** `{metadata['git_commit']}`",
        f"- **Total runs:** `{len(rows)}` (`READY`-only Harwell-Boeing Table 6 instances)",
        f"- **Status counts:** `{status_counts}`",
        f"- **All validations passed:** `{summary['all_validations_passed']}`",
        "",
        "## Study A – MiniSat vs CaDiCaL vs Glucose (`order_sequential`, `incremental`, `sym=True`)",
        "",
        "| Instance | Backend | Status | BW | Final LB | SAT Calls | Time (s) | Peak Mem (MiB) |",
        "|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for r in summary["study_a_backends"]:
        lines.append(
            f"| {r['instance']} | {r['backend']} | {r['status']} | {r['bandwidth']} | "
            f"{r['final_lb']} | {r['sat_calls']} | {r['total_time_s']:.3f} | {r['peak_memory_mb']} |"
        )

    lines.extend([
        "",
        "## Study B – Product AMO vs Existing AMOs (`minisat`, `incremental`, `sym=True`)",
        "",
        "| Instance | Encoding | AMO | Status | BW | Est Vars | Est Clauses | Actual Vars | Actual Clauses | Time (s) |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|",
    ])
    for r in summary["study_b_amo_comparison"]:
        lines.append(
            f"| {r['instance']} | {r['encoding']} | {r['amo']} | {r['status']} | {r['bandwidth']} | "
            f"{r['estimated_variables']} | {r['estimated_clauses']} | "
            f"{r['cnf_variables'] if r['cnf_variables'] is not None else 'N/A'} | "
            f"{r['cnf_clauses'] if r['cnf_clauses'] is not None else 'N/A'} | {r['total_time_s']:.3f} |"
        )

    lines.extend([
        "",
        "## Study C – Ladder vs Sequential Equivalence (`minisat`, `sym=True`)",
        "",
        "| Instance | Encoding | Strategy | Ladder (V/C) | Sequential (V/C) | Exact CNF Match | Status (L/S) | BW (L/S) |",
        "|---|---|---|---|---|---|---|---|",
    ])
    for p in ladder_pairs:
        lines.append(
            f"| {p['instance']} | {p['encoding']} | {p['strategy']} | "
            f"{p['ladder_vars']}/{p['ladder_clauses']} | {p['sequential_vars']}/{p['sequential_clauses']} | "
            f"{p['exact_cnf_match']} | {p['ladder_status']}/{p['sequential_status']} | "
            f"{p['ladder_bw']}/{p['sequential_bw']} |"
        )

    lines.extend([
        "",
        "## Study D – Repeated vs Incremental on MiniSat (`product`, `sym=True`)",
        "",
        "| Instance | Encoding | Strategy | Search Mode | Status | BW | LB/UB | Calls | Creations | Reused | Trace | Time (s) |",
        "|---|---|---|---|---|---:|---|---:|---:|:---:|---|---:|",
    ])
    for r in summary["study_d_repeated_vs_incremental"]:
        lines.append(
            f"| {r['instance']} | {r['encoding']} | {r['strategy']} | {r['search_mode']} | "
            f"{r['status']} | {r['bandwidth']} | {r['final_lb']}/{r['final_ub']} | "
            f"{r['sat_calls']} | {r['solver_creations']} | {r['solver_reused']} | "
            f"`{r['threshold_sequence']}` | {r['total_time_s']:.3f} |"
        )

    (output_dir / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def run(config_path: str | Path, *, resume: bool = True) -> dict[str, Any]:
    """Run the controlled M3.2 SAT pilot benchmark and write artifacts."""
    root = Path(__file__).resolve().parents[3]
    cfg_path = Path(config_path)
    if not cfg_path.is_absolute():
        cfg_path = root / cfg_path
    raw_cfg = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
    cfg = raw_cfg["benchmark"]

    prov_path = root / cfg["provenance"]
    raw_dir = root / cfg["raw_dir"]
    output_dir = root / cfg["output_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)

    provenance_entries = json.loads(prov_path.read_text(encoding="utf-8"))
    provenance_by_name = {entry["instance"]: entry for entry in provenance_entries}

    limits = ResourceLimits(
        max_variables=int(cfg["max_sat_variables"]),
        max_clauses=int(cfg["max_sat_clauses"]),
        timeout_seconds=float(cfg["timeout_seconds"]),
        memory_limit_mb=float(cfg["memory_limit_mb"]),
    )
    threshold_policy = str(cfg.get("threshold_policy", "adaptive"))
    git_sha = _git_commit()

    plan = _build_plan(cfg)
    backend_versions = {
        b: _sat_backend_version(b)
        for b in sorted({item["backend"] for item in plan})
    }

    # Verify and preload all unique pilot graphs upfront
    loaded: dict[str, tuple[Graph, dict[str, Any], Path]] = {}
    for name in sorted({item["instance"] for item in plan}):
        loaded[name] = _load_verified_ready_instance(name, provenance_by_name, raw_dir)

    runs_json_path = output_dir / "runs.json"
    existing_by_id: dict[str, dict[str, Any]] = {}
    if resume and runs_json_path.is_file():
        for prev in json.loads(runs_json_path.read_text(encoding="utf-8")):
            existing_by_id[str(prev["run_id"])] = prev

    log_lines: list[str] = []
    rows: list[dict[str, Any]] = []
    for item in plan:
        rid = item["run_id"]
        if rid in existing_by_id:
            rows.append(existing_by_id[rid])
            log_lines.append(f"[RESUME] {rid} {item['instance']} {item['encoding']}_{item['amo']} {item['backend']} {item['strategy']}/{item['search_mode']}")
            continue

        graph, prov, raw_path = loaded[item["instance"]]
        row = _execute_item(
            item,
            graph=graph,
            prov=prov,
            raw_path=raw_path,
            limits=limits,
            threshold_policy=threshold_policy,
            git_sha=git_sha,
            backend_versions=backend_versions,
        )
        rows.append(row)
        log_lines.append(
            f"[DONE] {rid} {row['instance']} {row['encoding']}_{row['amo']} "
            f"{row['backend']} {row['strategy']}/{row['search_mode']} -> "
            f"status={row['status']} bw={row['bandwidth']} lb={row['final_lb']} "
            f"calls={row['sat_calls']} time={row['total_time_s']}s valid={row['validation_valid']}"
        )
        # Incremental checkpoint on disk after each run
        runs_json_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")

    csv_path = output_dir / "runs.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=M3_2_FIELDS)
        writer.writeheader()
        for r in rows:
            writer.writerow(_format_csv_row(r))

    metadata = {
        "experiment_name": cfg["name"],
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "git_commit": git_sha,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "config": cfg,
        "backend_versions": backend_versions,
        "verified_dataset_instances": {
            name: {
                "table": ALL_INSTANCES[name].source_table,
                "n": graph.order,
                "m": graph.size,
                "sha256": prov["sha256"],
                "validation_status": prov["validation_status"],
                "raw_path": str(raw_path.relative_to(root)),
            }
            for name, (graph, prov, raw_path) in loaded.items()
        },
        "total_planned_runs": len(plan),
    }

    summary = _write_summary_and_report(rows, output_dir, metadata)
    (output_dir / "run_log.txt").write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/member3_m3_2.toml"),
        help="Path to M3.2 TOML benchmark config",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        default=False,
        help="Re-run all planned items instead of resuming from runs.json",
    )
    args = parser.parse_args(argv)
    summary = run(args.config, resume=not args.no_resume)
    print(json.dumps(summary["status_counts"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
