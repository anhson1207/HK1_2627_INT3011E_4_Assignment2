"""Controlled Member 3 runner aligned with provenance and SolverResult."""

from __future__ import annotations

import argparse
import csv
import os
from math import isfinite
from pathlib import Path

from bmp.core.solution import SolutionStatus
from bmp.core.validation import validate_solution
from bmp.data.harwell_boeing import HarwellBoeingDataset
from bmp.heuristics.rcm import RCMSolver
from bmp.heuristics.sa import SimulatedAnnealingSolver
from bmp.solvers.exact.cp_optimizer import CPOptimizerSolver
from bmp.solvers.exact.cpsat import CPSATSolver


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data" / "harwell_boeing",
        help="Directory containing metadata.csv and raw matrices",
    )
    parser.add_argument(
        "--provenance",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data" / "benchmark_provenance.json",
        help="Path to audited benchmark_provenance.json",
    )
    parser.add_argument("--table", type=int, choices=(6, 7))
    parser.add_argument("--instance", action="append")
    parser.add_argument(
        "--method", action="append", choices=("rcm", "sa", "cp-sat", "cp-optimizer")
    )
    parser.add_argument(
        "--include-unverified",
        action="store_true",
        default=False,
        help="Also run NEEDS_VERIFICATION instances (excluded from official READY runs)",
    )
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--iterations", type=int, default=2000)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not isfinite(args.timeout) or args.timeout <= 0 or args.iterations < 0:
        parser.error("Expected positive timeout and nonnegative iterations")

    dataset = HarwellBoeingDataset(args.dataset, provenance_path=args.provenance)
    methods = args.method or ["rcm", "sa"]
    instances = dataset.instances(args.table)
    if args.instance:
        unknown = set(args.instance) - {item.instance for item in instances}
        if unknown:
            parser.error(f"Unknown or out-of-table instances: {sorted(unknown)}")
        instances = tuple(item for item in instances if item.instance in args.instance)

    solvers = {
        "rcm": RCMSolver(),
        "sa": SimulatedAnnealingSolver(iterations=args.iterations, seed=args.seed),
        "cp-sat": CPSATSolver(seed=args.seed),
        "cp-optimizer": CPOptimizerSolver(
            os.getenv("BMP_CPO_EXECUTABLE", "cpoptimizer")
        ),
    }
    fields = (
        "instance",
        "table_number",
        "n",
        "m",
        "dataset_status",
        "method",
        "paper_lb",
        "paper_best",
        "our_bandwidth",
        "runtime_seconds",
        "status",
        "validated",
        "seed",
        "time_limit_seconds",
        "gap",
        "reason",
        "lower_bound",
        "iteration_budget",
    )
    with args.output.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for item in instances:
            val_status = dataset.validation_status(item.instance)
            if not args.include_unverified and val_status != "READY":
                for method in methods:
                    writer.writerow(
                        {
                            "instance": item.instance,
                            "table_number": item.table_number,
                            "n": item.n,
                            "dataset_status": val_status,
                            "method": method,
                            "paper_lb": item.paper_lb,
                            "paper_best": item.paper_best,
                            "status": SolutionStatus.SKIPPED.value,
                            "reason": f"Skipped unverified instance (validation_status={val_status})",
                        }
                    )
                stream.flush()
                continue

            graph, load_error = None, ""
            try:
                graph = dataset.load(item.instance)
            except (OSError, ValueError) as exc:
                load_error = str(exc)

            for method in methods:
                row: dict[str, object] = {
                    field: getattr(item, field)
                    for field in (
                        "instance",
                        "table_number",
                        "n",
                        "paper_lb",
                        "paper_best",
                    )
                }
                row.update(
                    dataset_status=val_status,
                    method=method,
                    status="NOT_RUN",
                    reason=load_error,
                )
                if graph is not None:
                    exact = method.startswith("cp-")
                    options = {"timeout_seconds": args.timeout} if exact else {}
                    row.update(
                        m=graph.size,
                        seed=args.seed if method in ("sa", "cp-sat") else None,
                        time_limit_seconds=args.timeout if exact else None,
                        iteration_budget=args.iterations if method == "sa" else None,
                    )
                    try:
                        result = solvers[method].solve(graph, **options)
                        row.update(
                            status=result.status.value,
                            runtime_seconds=result.runtime_seconds,
                            reason=result.metadata.get("reason", ""),
                            lower_bound=result.lower_bound,
                        )
                        if result.permutation is not None:
                            check = validate_solution(
                                graph,
                                result.permutation,
                                claimed_bandwidth=result.bandwidth,
                            )
                            row["validated"] = check.valid
                            if check.valid and check.actual_bandwidth is not None:
                                row.update(
                                    our_bandwidth=check.actual_bandwidth,
                                    gap=check.actual_bandwidth - item.paper_best,
                                )
                            else:
                                row.update(
                                    status=SolutionStatus.ERROR.value,
                                    reason="; ".join(check.errors),
                                )
                    except (ValueError, RuntimeError, OSError) as exc:
                        row.update(status=SolutionStatus.ERROR.value, reason=str(exc))
                writer.writerow(row)
            stream.flush()


if __name__ == "__main__":
    main()
