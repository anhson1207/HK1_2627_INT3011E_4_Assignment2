"""Bounded Leader SAT run plus 113-row preflight and paper comparison.

Usage: .venv/bin/python scripts/run_official_benchmark.py --max-ready 2 --per-call 2 --total 50
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from time import monotonic

import pysat

from bmp.core.benchmark_catalog import ALL_INSTANCES
from bmp.core.validation import validate_solution
from bmp.encodings.estimator import ResourceLimits, estimate_cnf_size
from bmp.encodings.order import OrderEncoding
from bmp.encodings.pairwise import PairwiseEncoding
from bmp.io.readers import inspect_matrix_market
from bmp.solvers.sat.backends.cadical import CadicalBackend
from bmp.solvers.sat.incremental import IncrementalSATSolver
from bmp.solvers.sat.repeated import RepeatedSATSolver

PROVENANCE = Path("data/benchmark_provenance.json")
OUTPUT = Path("results/leader")


def _write_csv(path: Path, records: list[dict[str, object]]) -> None:
    if not records:
        return
    fields = list(records[0])
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)


def run(*, max_ready: int, per_call: float, total: float, max_clauses: int) -> tuple[list[dict], list[dict]]:
    provenance = {row["instance"]: row for row in json.loads(PROVENANCE.read_text())}
    if set(provenance) != set(ALL_INSTANCES):
        raise ValueError("Provenance must contain exactly the 113 paper instances")
    backend = CadicalBackend()
    version = f"{backend.version} (PySAT {pysat.__version__})"
    backend.delete()
    limits = ResourceLimits(max_variables=100_000, max_clauses=max_clauses, timeout_seconds=None)
    ready_names = sorted(
        (name for name, row in provenance.items() if row["validation_status"] == "READY"),
        key=lambda name: (ALL_INSTANCES[name].n, name),
    )
    selected = set(ready_names[:max_ready])
    plan = []
    for name, meta in ALL_INSTANCES.items():
        source_status = provenance[name]["validation_status"]
        plan.append({
            "instance": name, "source_table": meta.source_table, "n": meta.n,
            "dataset_status": source_status,
            "benchmark_status": (
                "PLANNED" if name in selected else
                "SKIPPED" if source_status == "READY" else source_status
            ),
            "reason": ("batch scope" if source_status == "READY" and name not in selected else provenance[name].get("validation_reason")),
        })
    results = []
    started = monotonic()
    for name in ready_names[:max_ready]:
        source = provenance[name]
        source_path = Path(source["file_path"])
        if hashlib.sha256(source_path.read_bytes()).hexdigest() != source["sha256"]:
            raise ValueError(f"Raw source checksum changed: {name}")
        graph = inspect_matrix_market(source_path).graph
        if graph.order != ALL_INSTANCES[name].n:
            raise ValueError(f"Data changed since provenance audit: {name}")
        for family in ("pairwise", "order"):
            for amo in ("pairwise", "sequential"):
                for strategy in ("repeated", "incremental"):
                    if monotonic() - started >= total:
                        break
                    encoder = PairwiseEncoding(amo) if family == "pairwise" else OrderEncoding(amo)
                    solver = (
                        RepeatedSATSolver(encoder, threshold_policy="unit")
                        if strategy == "repeated"
                        else IncrementalSATSolver(encoder, threshold_policy="unit")
                    )
                    estimate = estimate_cnf_size(
                        graph, encoding=family, amo=amo, k=0,
                    )
                    result = solver.solve(
                        graph, timeout_seconds=min(per_call, max(0, total - (monotonic() - started))),
                        limits=limits,
                    )
                    validated = result.permutation is not None and validate_solution(graph, result).valid
                    record = {
                        "instance": name, "n": graph.order, "m": graph.size,
                        "encoding": family, "cardinality": amo, "strategy": strategy,
                        "backend": "CaDiCaL", "backend_version": version,
                        "status": result.status.value, "bandwidth": result.bandwidth,
                        "lower_bound": result.lower_bound, "upper_bound": result.upper_bound,
                        "encoding_time_s": result.encoding_time_s,
                        "solver_time_s": result.solving_time_s,
                        "total_wall_time_s": result.runtime_s,
                        "peak_memory_mb": None,
                        "actual_variables": result.num_variables,
                        "actual_clauses": result.num_clauses,
                        "estimated_variables_k0": estimate.num_variables,
                        "estimated_clauses_k0": estimate.num_clauses,
                        "initial_clauses": result.metadata.get("initial_clauses"),
                        "added_clauses": result.metadata.get("added_clauses"),
                        "sat_calls": result.sat_calls, "timeout_limit_s": per_call,
                        "max_variables": limits.max_variables,
                        "max_clauses": limits.max_clauses,
                        "random_seed": None, "validated_solution": validated,
                        "worker_reason": result.metadata.get("worker_reason"),
                        "skipped_reason": result.metadata.get("skipped_reason"),
                    }
                    results.append(record)
                    print(name, family, amo, strategy, result.status.value, result.bandwidth, flush=True)
    executed = {r["instance"] for r in results}
    for row in plan:
        if row["benchmark_status"] == "PLANNED":
            if row["instance"] in executed:
                row["benchmark_status"] = "EXECUTED"
            else:
                row["benchmark_status"] = "SKIPPED"
                row["reason"] = "total time budget"
    comparison = []
    for name, meta in ALL_INSTANCES.items():
        candidates = [r for r in results if r["instance"] == name and r["validated_solution"] and r["bandwidth"] is not None]
        best = min(candidates, key=lambda r: (r["bandwidth"], r["status"] != "OPTIMAL")) if candidates else None
        comparison.append({
            "instance": name, "n": meta.n, "published_lb": meta.paper_lb,
            "published_best": meta.paper_best, "published_drsa": meta.drsa_bandwidth,
            "leader_sat_bandwidth": best["bandwidth"] if best else None,
            "leader_sat_status": best["status"] if best else (
                "SKIPPED" if provenance[name]["validation_status"] == "READY"
                else provenance[name]["validation_status"]
            ),
            "difference_from_published_best": best["bandwidth"] - meta.paper_best if best else None,
            "proof_status": "PROVED" if best and best["status"] == "OPTIMAL" else (
                "UNPROVED" if best else "NOT_RUN"
            ),
        })
    OUTPUT.mkdir(parents=True, exist_ok=True)
    _write_csv(OUTPUT / "official_preflight.csv", plan)
    _write_csv(OUTPUT / "official_sat_runs.csv", results)
    _write_csv(OUTPUT / "official_paper_comparison.csv", comparison)
    (OUTPUT / "official_sat_runs.json").write_text(json.dumps(results, indent=2) + "\n")
    return plan, results


def run_symmetry_ablation(*, instance: str, per_call: float, max_clauses: int) -> list[dict]:
    """Separate same-graph, same-budget reversal symmetry comparison."""
    provenance = {row["instance"]: row for row in json.loads(PROVENANCE.read_text())}
    source = provenance[instance]
    if source["validation_status"] != "READY":
        raise ValueError(f"Symmetry ablation requires a READY graph: {instance}")
    path = Path(source["file_path"])
    if hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]:
        raise ValueError("Raw source checksum changed")
    graph = inspect_matrix_market(path).graph
    limits = ResourceLimits(max_variables=100_000, max_clauses=max_clauses, timeout_seconds=None)
    records = []
    for family in ("pairwise", "order"):
        for symmetry in (False, True):
            encoder = PairwiseEncoding("sequential") if family == "pairwise" else OrderEncoding("sequential")
            result = RepeatedSATSolver(encoder, threshold_policy="unit").solve(
                graph, timeout_seconds=per_call, symmetry_breaking=symmetry, limits=limits,
            )
            records.append({
                "instance": instance, "n": graph.order, "m": graph.size,
                "encoding": family, "cardinality": "sequential", "strategy": "repeated",
                "symmetry_breaking": symmetry, "timeout_limit_s": per_call,
                "status": result.status.value, "bandwidth": result.bandwidth,
                "lower_bound": result.lower_bound, "sat_calls": result.sat_calls,
                "total_wall_time_s": result.runtime_s,
                "actual_variables": result.num_variables,
                "actual_clauses": result.num_clauses,
                "validated_solution": result.permutation is not None and validate_solution(graph, result).valid,
            })
            print("ablation", instance, family, symmetry, result.status.value, result.bandwidth, flush=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    _write_csv(OUTPUT / "official_symmetry_ablation.csv", records)
    return records


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-ready", type=int, default=2)
    parser.add_argument("--per-call", type=float, default=2.0)
    parser.add_argument("--total", type=float, default=50.0)
    parser.add_argument("--max-clauses", type=int, default=500_000)
    parser.add_argument("--symmetry-ablation-instance", default=None)
    options = parser.parse_args()
    if options.symmetry_ablation_instance:
        run_symmetry_ablation(
            instance=options.symmetry_ablation_instance,
            per_call=options.per_call, max_clauses=options.max_clauses,
        )
    else:
        run(max_ready=options.max_ready, per_call=options.per_call,
            total=options.total, max_clauses=options.max_clauses)
