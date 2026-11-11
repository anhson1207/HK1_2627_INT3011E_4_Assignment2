"""Audit the recorded 16 L7 attempts without inventing missing call logs."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from bmp.io.readers import inspect_matrix_market
from bmp.solvers.sat.search import compute_initial_upper_bound, compute_lower_bound


def main() -> None:
    runs = json.loads(Path("results/leader/official_sat_runs.json").read_text())
    sources = {r["instance"]: r for r in json.loads(Path("data/benchmark_provenance.json").read_text())}
    if len(runs) != 16:
        raise ValueError("L7 artifact must contain exactly 16 runs")
    bounds = {}
    for name in {run["instance"] for run in runs}:
        source = sources[name]
        path = Path(source["file_path"])
        if hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]:
            raise ValueError(f"Source checksum changed: {name}")
        graph = inspect_matrix_market(path).graph
        bounds[name] = compute_initial_upper_bound(graph)[0], compute_lower_bound(graph)
    audited = []
    for run in runs:
        initial_ub, initial_lb = bounds[run["instance"]]
        completed = run["sat_calls"]
        improvement = run["bandwidth"] < initial_ub
        # Unit-step search starts at UB-1. With no LB increase, each
        # completed call must have returned SAT; the interrupted call was not logged.
        infer_sat = run["lower_bound"] == initial_lb and initial_ub - run["bandwidth"] == completed
        audited.append({
            "instance": run["instance"], "encoding": run["encoding"],
            "cardinality": run["cardinality"], "strategy": run["strategy"],
            "initial_ub": initial_ub, "initial_lb": initial_lb,
            "completed_sat_calls": completed,
            "completed_call_outcomes": ";".join("SAT (inferred)" for _ in range(completed)) if infer_sat else "UNRECOVERABLE",
            "interrupted_call_outcome": "UNRECORDED; no L7 trace",
            "sat_found_improvement": improvement,
            "final_ub": run["upper_bound"], "final_lb": run["lower_bound"],
            "encoding_time_s": run["encoding_time_s"],
            "reported_solver_phase_time_s": run["solver_time_s"],
            "total_wall_time_s": run["total_wall_time_s"],
            "timeout_reason": run["worker_reason"],
            "inference_basis": "Unit threshold policy; unchanged LB; UB decrease equals completed calls" if infer_sat else "No exact L7 call log",
        })
    output = Path("results/leader/l8_l7_run_audit.csv")
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(audited[0]))
        writer.writeheader()
        writer.writerows(audited)
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
