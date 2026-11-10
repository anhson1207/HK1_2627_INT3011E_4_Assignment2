"""Bounded, resumable L8 SAT experiment on checksum-verified READY matrices.

Default plan: 2 instances at 3 s, one full factorial at 30 s plus four
larger-graph configurations, and one selected 120 s extension. The total
budget, memory cap, and each stage deadline are configurable.
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
from bmp.encodings.estimator import ResourceLimits
from bmp.encodings.order import OrderEncoding
from bmp.encodings.pairwise import PairwiseEncoding
from bmp.io.readers import inspect_matrix_market
from bmp.solvers.sat.backends.cadical import CadicalBackend
from bmp.solvers.sat.incremental import IncrementalSATSolver
from bmp.solvers.sat.repeated import RepeatedSATSolver
from bmp.solvers.sat.search import compute_initial_upper_bound, compute_lower_bound

PROVENANCE = Path("data/benchmark_provenance.json")
OUTPUT_JSON = Path("results/leader/l8_sat_runs.json")
OUTPUT_CSV = Path("results/leader/l8_sat_runs.csv")
PLAN_CSV = Path("results/leader/l8_sat_plan.csv")


def plan(t3: float, t30: float, t120: float) -> list[dict]:
    full = [(family, amo, strategy)
            for family in ("pairwise", "order")
            for amo in ("pairwise", "sequential")
            for strategy in ("repeated", "incremental")]
    medium_larger = [(family, "sequential", strategy)
                     for family in ("pairwise", "order")
                     for strategy in ("repeated", "incremental")]
    stages = (
        ("3s", t3, (("bcspwr01", full), ("bcsstk01", full))),
        ("30s", t30, (("bcspwr01", full), ("bcsstk01", medium_larger))),
        ("120s", t120, (("bcsstk01", [("order", "sequential", "incremental")]),)),
    )
    return [dict(stage=stage, timeout_s=timeout, instance=name,
                 encoding=family, cardinality=amo, strategy=strategy)
            for stage, timeout, groups in stages
            for name, configs in groups
            for family, amo, strategy in configs]


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _persist(rows: list[dict]) -> None:
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    flat = [{**r, "sat_trace": json.dumps(r["sat_trace"], separators=(",", ":"))} for r in rows]
    _write_csv(OUTPUT_CSV, flat)


def run(*, t3: float, t30: float, t120: float, total: float,
        max_variables: int, max_clauses: int, memory_limit_mb: float,
        resume: bool = True) -> list[dict]:
    if min(t3, t30, t120, total, memory_limit_mb, max_variables, max_clauses) <= 0:
        raise ValueError("Timeouts, total budget and resource limits must be positive")
    rows = plan(t3, t30, t120)
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    _write_csv(PLAN_CSV, rows)
    provenance = {r["instance"]: r for r in json.loads(PROVENANCE.read_text())}
    graphs = {}
    for name in {row["instance"] for row in rows}:
        source = provenance[name]
        if source["validation_status"] != "READY":
            raise ValueError(f"Not a verified READY source: {name}")
        path = Path(source["file_path"])
        if hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]:
            raise ValueError(f"Source checksum mismatch: {name}")
        graph = inspect_matrix_market(path).graph
        if graph.order != ALL_INSTANCES[name].n or graph.size != source["m"]:
            raise ValueError(f"Source topology changed: {name}")
        graphs[name] = graph
    backend = CadicalBackend()
    version = f"{backend.version} (PySAT {pysat.__version__})"
    backend.delete()
    existing = json.loads(OUTPUT_JSON.read_text()) if resume and OUTPUT_JSON.exists() else []
    keys = {(r["stage"], r["instance"], r["encoding"], r["cardinality"], r["strategy"]): r for r in existing}
    spent_before = sum(float(r["runtime_s"]) for r in existing)
    started = monotonic()
    limits = ResourceLimits(max_variables=max_variables, max_clauses=max_clauses,
                            timeout_seconds=None, memory_limit_mb=memory_limit_mb)
    for item in rows:
        key = tuple(item[field] for field in ("stage", "instance", "encoding", "cardinality", "strategy"))
        if key in keys:
            old = keys[key]
            if (old["timeout_s"] != item["timeout_s"]
                    or old["raw_sha256"] != provenance[item["instance"]]["sha256"]
                    or old["memory_limit_mb"] != memory_limit_mb
                    or old["backend_version"] != version):
                raise ValueError(f"Cannot resume with changed timeout, source, memory cap or backend: {key}")
            continue
        remaining = total - spent_before - (monotonic() - started)
        if remaining < item["timeout_s"]:
            print(f"Batch budget reached; {len(rows) - len(keys)} planned runs remain", flush=True)
            break
        graph = graphs[item["instance"]]
        meta = ALL_INSTANCES[item["instance"]]
        initial_ub, _ = compute_initial_upper_bound(graph)
        initial_lb = compute_lower_bound(graph)
        encoder = (PairwiseEncoding if item["encoding"] == "pairwise" else OrderEncoding)(item["cardinality"])
        solver = (RepeatedSATSolver if item["strategy"] == "repeated" else IncrementalSATSolver)(
            encoder, threshold_policy="unit")
        result = solver.solve(graph, timeout_seconds=item["timeout_s"], limits=limits)
        validated = result.permutation is not None and validate_solution(graph, result).valid
        if result.permutation is not None and not validated:
            raise ValueError(f"Invalid incumbent produced by {key}")
        trace = list(result.metadata.get("sat_trace", []))
        completed = [event for event in trace if event["outcome"] in ("SAT", "UNSAT")]
        if len(completed) != result.sat_calls and result.status != "ERROR":
            raise ValueError(f"SAT trace/call count mismatch: {key}")
        improvement = bool(validated and result.bandwidth is not None
                           and result.bandwidth < initial_ub
                           and any(event["outcome"] == "SAT" and event["bandwidth"] == result.bandwidth for event in completed))
        record = {
            **item, "n": graph.order, "m": graph.size,
            "backend": "CaDiCaL", "backend_version": version,
            "raw_sha256": provenance[item["instance"]]["sha256"],
            "initial_ub": initial_ub, "initial_lb": initial_lb,
            "final_ub": result.upper_bound, "final_lb": result.lower_bound,
            "best_bandwidth": result.bandwidth,
            "published_lb": meta.paper_lb, "published_best": meta.paper_best,
            "sat_found_improvement": improvement,
            "optimality_status": "PROVED" if result.status == "OPTIMAL" else "UNPROVED",
            "status": result.status.value, "validated_solution": validated,
            "encoding_time_s": result.encoding_time_s,
            "solving_time_s": result.solving_time_s,
            "runtime_s": result.runtime_s,
            "peak_memory_mb": result.metadata.get("sampled_peak_memory_mb"),
            "memory_limit_mb": memory_limit_mb,
            "sat_calls": result.sat_calls,
            "cnf_variables": result.num_variables,
            "cnf_clauses": result.num_clauses,
            "sat_trace": trace,
            "worker_reason": result.metadata.get("worker_reason"),
            "skipped_reason": result.metadata.get("skipped_reason"),
        }
        existing.append(record)
        keys[key] = record
        _persist(existing)
        print(item["stage"], item["instance"], item["encoding"], item["cardinality"],
              item["strategy"], result.status.value, f"{initial_ub}->{result.bandwidth}",
              f"LB={result.lower_bound}", f"calls={result.sat_calls}", flush=True)
    return existing


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout-3", type=float, default=3.0)
    parser.add_argument("--timeout-30", type=float, default=30.0)
    parser.add_argument("--timeout-120", type=float, default=120.0)
    parser.add_argument("--total", type=float, default=600.0)
    parser.add_argument("--max-variables", type=int, default=100_000)
    parser.add_argument("--max-clauses", type=int, default=500_000)
    parser.add_argument("--memory-limit-mb", type=float, default=4096.0)
    parser.add_argument("--fresh", action="store_true", help="Replace previous L8 run data")
    args = parser.parse_args()
    run(t3=args.timeout_3, t30=args.timeout_30, t120=args.timeout_120,
        total=args.total, max_variables=args.max_variables, max_clauses=args.max_clauses,
        memory_limit_mb=args.memory_limit_mb, resume=not args.fresh)
