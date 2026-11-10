"""Small Member 3 verification runner for real Harwell–Boeing matrices."""

import argparse
import csv
import os
from math import isfinite
from pathlib import Path

from bmp.core.validation import validate_assignment
from bmp.data.harwell_boeing import HarwellBoeingDataset
from bmp.heuristics.rcm import RCMSolver
from bmp.heuristics.sa import SimulatedAnnealingSolver
from bmp.solvers.exact.cpsat import CPSATSolver
from bmp.solvers.exact.cp_optimizer import CPOptimizerSolver


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data" / "harwell_boeing",
        help="Directory containing metadata.csv and the original matrices",
    )
    parser.add_argument("--table", type=int, choices=(6, 7))
    parser.add_argument("--instance", action="append")
    parser.add_argument(
        "--method", action="append", choices=("rcm", "sa", "cp-sat", "cp-optimizer")
    )
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--iterations", type=int, default=2000)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not isfinite(args.timeout) or args.timeout <= 0 or args.iterations < 0:
        parser.error("Expected positive timeout and nonnegative iterations")

    dataset = HarwellBoeingDataset(args.dataset)
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
            graph, load_error = None, ""
            try:
                graph = dataset.load(item.instance)
            except (OSError, ValueError) as exc:
                load_error = str(exc)
            # Mỗi phương pháp dùng cùng Graph đã load cho instance này.
            for method in methods:
                row = {
                    field: getattr(item, field)
                    for field in (
                        "instance",
                        "table_number",
                        "n",
                        "paper_lb",
                        "paper_best",
                    )
                }
                row.update(method=method, status="NOT_RUN", reason=load_error)
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
                        if result.assignment is not None:
                            check = validate_assignment(
                                graph,
                                result.assignment,
                                claimed_bandwidth=result.bandwidth,
                            )
                            row["validated"] = check.valid
                            if check.valid:
                                row.update(
                                    our_bandwidth=check.actual_bandwidth,
                                    gap=check.actual_bandwidth - item.paper_best,
                                )
                            else:
                                row.update(
                                    status="ERROR", reason="; ".join(check.errors)
                                )
                    except (ValueError, RuntimeError, OSError) as exc:
                        row.update(status="ERROR", reason=str(exc))
                writer.writerow(row)
            stream.flush()


if __name__ == "__main__":
    main()
