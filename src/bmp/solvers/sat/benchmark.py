"""SAT benchmark runner for Leader experiments."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from time import monotonic
from typing import Sequence

from bmp.core.generators import (
    complete_graph,
    cycle_graph,
    edgeless_graph,
    erdos_renyi_graph,
    path_graph,
    star_graph,
)
from bmp.core.graph import Graph
from bmp.core.validation import validate_solution
from bmp.encodings.order import OrderEncoding
from bmp.encodings.pairwise import PairwiseEncoding
from bmp.io.readers import read_graph
from bmp.solvers.sat.incremental import IncrementalSATSolver
from bmp.solvers.sat.repeated import RepeatedSATSolver


@dataclass
class BenchmarkRecord:
    instance: str
    n: int
    m: int
    density: float
    encoding: str
    amo: str
    strategy: str
    symmetry_breaking: bool
    status: str
    bandwidth: int | None
    lower_bound: int | None
    upper_bound: int | None
    runtime_s: float
    encoding_time_s: float
    solving_time_s: float
    num_variables: int | None
    num_clauses: int | None
    sat_calls: int
    valid: bool


def run_benchmark(
    graphs: Sequence[Graph],
    *,
    timeout_per_instance: float = 30.0,
    include_symmetry_breaking: bool = True,
) -> list[BenchmarkRecord]:
    """Execute systematic evaluation across SAT configurations."""
    records: list[BenchmarkRecord] = []

    # Configurations to test
    configs = [
        # (encoding_family, amo, strategy, symmetry_breaking)
        ("pairwise", "pairwise", "repeated", False),
        ("pairwise", "pairwise", "incremental", False),
        ("pairwise", "sequential", "repeated", False),
        ("pairwise", "sequential", "incremental", False),
        ("order", "pairwise", "repeated", False),
        ("order", "pairwise", "incremental", False),
    ]

    if include_symmetry_breaking:
        configs.extend([
            ("pairwise", "pairwise", "repeated", True),
            ("pairwise", "pairwise", "incremental", True),
            ("order", "pairwise", "repeated", True),
            ("order", "pairwise", "incremental", True),
        ])

    for graph in graphs:
        for enc_family, amo, strategy, sym in configs:
            # Create encoder
            if enc_family == "pairwise":
                encoder = PairwiseEncoding(amo=amo)
            else:
                encoder = OrderEncoding(amo=amo)

            # Create solver
            if strategy == "repeated":
                solver = RepeatedSATSolver(encoder=encoder, backend_name="cadical")
            else:
                solver = IncrementalSATSolver(encoder=encoder, backend_name="cadical")

            result = solver.solve(
                graph,
                timeout_seconds=timeout_per_instance,
                symmetry_breaking=sym,
            )

            # Validate certificate
            is_valid = False
            if result.permutation is not None:
                report = validate_solution(graph, result)
                is_valid = report.valid

            rec = BenchmarkRecord(
                instance=graph.name,
                n=graph.order,
                m=graph.size,
                density=graph.density,
                encoding=enc_family,
                amo=amo,
                strategy=strategy,
                symmetry_breaking=sym,
                status=result.status.value,
                bandwidth=result.bandwidth,
                lower_bound=result.lower_bound,
                upper_bound=result.upper_bound,
                runtime_s=round(result.runtime_s, 6),
                encoding_time_s=round(result.encoding_time_s, 6),
                solving_time_s=round(result.solving_time_s, 6),
                num_variables=result.num_variables,
                num_clauses=result.num_clauses,
                sat_calls=result.sat_calls,
                valid=is_valid,
            )
            records.append(rec)

    return records


def export_csv(records: Sequence[BenchmarkRecord], path: Path) -> None:
    if not records:
        return
    fieldnames = list(asdict(records[0]).keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in records:
            writer.writerow(asdict(r))


def export_json(records: Sequence[BenchmarkRecord], path: Path) -> None:
    data = [asdict(r) for r in records]
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


__all__ = [
    "BenchmarkRecord",
    "export_csv",
    "export_json",
    "run_benchmark",
]

