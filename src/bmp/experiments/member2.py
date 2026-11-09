"""Member 2 comparison runner over the repository's sample graphs.

Run with ``python -m bmp.experiments.member2 configs/member2.toml``.
The leader's SAT benchmark remains unchanged; this runner adds the Member 2
Glucose, MIP, AMO, and strengthening comparisons.
"""

from __future__ import annotations

import argparse
import csv
import json
import platform
import statistics
import sys
import tomllib
from collections import defaultdict
from pathlib import Path
from time import monotonic
from typing import Any

from bmp.core.solution import SolutionStatus
from bmp.core.validation import validate_assignment
from bmp.encodings.order import OrderEncoding
from bmp.encodings.pairwise import PairwiseEncoding
from bmp.io.readers import read_graph
from bmp.solvers.brute_force import BruteForceSolver
from bmp.solvers.exact.cplex import CPLEXMIPSolver
from bmp.solvers.exact.gurobi import GurobiMIPSolver
from bmp.solvers.sat.incremental import IncrementalSATSolver
from bmp.solvers.sat.repeated import RepeatedSATSolver


FIELDS = (
    "study", "instance", "vertices", "edges", "solver", "encoding", "amo",
    "strategy", "symmetry_breaking", "repetition", "timeout_seconds", "seed",
    "status", "bandwidth", "actual_bandwidth", "validation", "runtime_total_s",
    "num_variables", "num_clauses", "sat_calls", "encoding_time_s", "solving_time_s",
    "best_bound", "mip_gap", "error",
)


def _configurations(amo_names: list[str]) -> list[tuple[str, str, str | None, str | None, str | None, bool]]:
    configs: list[tuple[str, str, str | None, str | None, str | None, bool]] = []
    for encoding in ("pairwise", "order"):
        for strategy in ("repeated", "incremental"):
            configs.append(("sat_strategy", "glucose", encoding, "pairwise", strategy, False))
    for amo in amo_names:
        configs.append(("amo", "glucose", "pairwise", amo, "repeated", False))
    for solver in ("brute-force", "gurobi", "cplex"):
        configs.append(("solver_comparison", solver, None, None, None, False))
    for solver in ("gurobi", "cplex"):
        for symmetry in (False, True):
            configs.append(("mip_strengthening", solver, None, None, None, symmetry))
    return configs


def _run_one(
    graph: Any, study: str, solver_name: str, encoding: str | None,
    amo: str | None, strategy: str | None, symmetry_breaking: bool,
    timeout_seconds: float, repetition: int, seed: int | None,
) -> dict[str, Any]:
    row = dict.fromkeys(FIELDS)
    row.update(
        study=study, instance=graph.name, vertices=graph.order, edges=graph.size,
        solver=solver_name, encoding=encoding, amo=amo, strategy=strategy,
        symmetry_breaking=symmetry_breaking, repetition=repetition,
        timeout_seconds=timeout_seconds, seed=seed,
    )
    started = monotonic()
    try:
        if solver_name == "glucose":
            encoder = PairwiseEncoding(amo=amo or "pairwise") if encoding == "pairwise" else OrderEncoding(amo=amo or "pairwise")
            sat_solver = (
                RepeatedSATSolver(encoder, backend_name="glucose")
                if strategy == "repeated"
                else IncrementalSATSolver(encoder, backend_name="glucose")
            )
            result = sat_solver.solve(graph, timeout_seconds=timeout_seconds)
            row.update(
                num_variables=result.num_variables, num_clauses=result.num_clauses,
                sat_calls=result.sat_calls,
                encoding_time_s=result.encoding_time_s, solving_time_s=result.solving_time_s,
            )
        elif solver_name == "brute-force":
            result = BruteForceSolver().solve(graph, timeout_seconds=timeout_seconds)
        elif solver_name == "gurobi":
            result = GurobiMIPSolver().solve(
                graph, timeout_seconds=timeout_seconds,
                symmetry_breaking=symmetry_breaking,
            )
        elif solver_name == "cplex":
            result = CPLEXMIPSolver().solve(
                graph, timeout_seconds=timeout_seconds,
                symmetry_breaking=symmetry_breaking,
            )
        else:
            raise ValueError(f"Unknown solver: {solver_name}")

        row["status"] = result.status.value
        row["bandwidth"] = result.bandwidth
        if solver_name in ("gurobi", "cplex"):
            row["best_bound"] = result.metadata.get("best_bound")
            row["mip_gap"] = result.metadata.get("mip_gap")
            if result.status is SolutionStatus.UNAVAILABLE:
                row["error"] = result.metadata.get("reason")
        if result.assignment is not None and result.status is not SolutionStatus.UNAVAILABLE:
            report = validate_assignment(graph, result.assignment, claimed_bandwidth=result.bandwidth)
            row["validation"] = report.valid
            row["actual_bandwidth"] = report.actual_bandwidth
            if not report.valid:
                row["status"] = SolutionStatus.ERROR.value
                row["error"] = "; ".join(report.errors)
    except TimeoutError as exc:
        row["status"] = SolutionStatus.TIMEOUT.value
        row["error"] = str(exc)
    except Exception as exc:
        row["status"] = SolutionStatus.ERROR.value
        row["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        row["runtime_total_s"] = monotonic() - started
    return row


def _write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    keys = ("study", "instance", "solver", "encoding", "amo", "strategy", "symmetry_breaking")
    for row in rows:
        groups[tuple(row[key] for key in keys)].append(row)
    summary = []
    for group, members in groups.items():
        complete = [r for r in members if r["status"] == "OPTIMAL" and r["validation"] is True]
        entry = dict(zip(keys, group))
        entry.update(
            runs=len(members), optimal=len(complete),
            median_runtime_s=statistics.median(r["runtime_total_s"] for r in complete) if complete else None,
            timeouts=sum(r["status"] == "TIMEOUT" for r in members),
            unavailable=sum(r["status"] == "UNAVAILABLE" for r in members),
            errors=sum(r["status"] == "ERROR" for r in members),
            bandwidth=complete[0]["bandwidth"] if complete else None,
        )
        summary.append(entry)
    return summary


def run_config(config_path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    config_path = config_path.resolve()
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))["benchmark"]
    timeout = float(config["timeout_seconds"])
    repetitions = int(config["repetitions"])
    seed = config.get("seed")
    if timeout <= 0 or repetitions < 1:
        raise ValueError("timeout_seconds and repetitions must be positive")
    instances = [read_graph(config_path.parent / item) for item in config["instances"]]
    if not instances:
        raise ValueError("At least one instance is required")
    output_dir = (config_path.parent / config["output_dir"]).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    amo_names = list(config.get("amo", ["pairwise", "sequential", "binary", "commander"]))
    rows: list[dict[str, Any]] = []
    for graph in instances:
        for study, solver, encoding, amo, strategy, symmetry in _configurations(amo_names):
            for repetition in range(1, repetitions + 1):
                rows.append(_run_one(
                    graph, study, solver, encoding, amo, strategy, symmetry,
                    timeout, repetition, seed,
                ))
    summary = _summarize(rows)
    _write_csv(rows, output_dir / "runs.csv")
    (output_dir / "runs.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    metadata = {
        "config": str(config_path), "python": sys.version, "platform": platform.platform(),
        "sample_scope": "repository sample edge lists", "seed_used": False,
        "leader_core_commit": "414606c50c352888e4ed9f0a04bef257c7e9d099",
        "note": "SAT strategy timeout is checked by leader code between SAT calls; individual solve calls have no hard deadline.",
    }
    (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return rows, summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    rows, summary = run_config(args.config)
    counts = {status: sum(row["status"] == status for row in rows) for status in ("OPTIMAL", "TIMEOUT", "UNAVAILABLE", "ERROR")}
    print(f"{len(rows)} runs, {len(summary)} summary groups: {counts}")


if __name__ == "__main__":
    main()
