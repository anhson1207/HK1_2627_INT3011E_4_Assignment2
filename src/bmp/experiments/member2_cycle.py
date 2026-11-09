"""Export direct K=1/K=2 Glucose checks for cycle_c4."""

from __future__ import annotations

import json
from pathlib import Path

from bmp.core.validation import validate_assignment
from bmp.encodings.order import OrderEncoding
from bmp.encodings.pairwise import PairwiseEncoding
from bmp.io.readers import read_graph
from bmp.solvers.sat.backends import get_sat_backend
from bmp.solvers.sat.incremental import IncrementalSATSolver
from bmp.solvers.sat.repeated import RepeatedSATSolver


def run_cycle_check() -> list[dict[str, object]]:
    root = Path(__file__).resolve().parents[3]
    graph = read_graph(root / "data/samples/cycle_c4.edgelist")
    rows: list[dict[str, object]] = []
    for encoding_type in (PairwiseEncoding, OrderEncoding):
        for strategy in ("repeated", "incremental"):
            encoder = encoding_type(amo="pairwise")
            models: dict[int, list[int] | None] = {}
            statuses: dict[int, str] = {}
            if strategy == "repeated":
                for k in (1, 2):
                    with get_sat_backend("glucose") as backend:
                        backend.append_formula(encoder.encode(graph, k).clauses)
                        sat = backend.solve()
                        statuses[k] = "SAT" if sat else "UNSAT"
                        models[k] = backend.get_model()
            else:
                with get_sat_backend("glucose") as backend:
                    backend.append_formula(encoder.encode_fixed(graph).clauses)
                    backend.append_formula(encoder.encode_bandwidth_step(graph, 2))
                    sat = backend.solve()
                    statuses[2] = "SAT" if sat else "UNSAT"
                    models[2] = backend.get_model()
                    tightening = (
                        encoder.encode_bandwidth_diff(graph, 1, 2)
                        if isinstance(encoder, PairwiseEncoding)
                        else encoder.encode_bandwidth_step(graph, 1)
                    )
                    backend.append_formula(tightening)
                    sat = backend.solve()
                    statuses[1] = "SAT" if sat else "UNSAT"
                    models[1] = backend.get_model()
            if statuses != {1: "UNSAT", 2: "SAT"}:
                raise AssertionError(f"Unexpected thresholds: {statuses}")
            assignment = encoder.decode(graph, models[2] or [], 2)
            validation = validate_assignment(graph, assignment)
            if not validation.valid or validation.actual_bandwidth != 2:
                raise AssertionError(f"Invalid model: {validation.errors}")
            solver = (
                RepeatedSATSolver(encoder, backend_name="glucose")
                if strategy == "repeated"
                else IncrementalSATSolver(encoder, backend_name="glucose")
            )
            result = solver.solve(graph)
            rows.append({
                "encoding": "pairwise" if encoding_type is PairwiseEncoding else "order",
                "strategy": strategy, "k1": statuses[1], "k2": statuses[2],
                "assignment_k2": assignment, "validation": validation.valid,
                "actual_bandwidth": validation.actual_bandwidth,
                "same_solver_k2_then_k1": strategy == "incremental",
                "strategy_status": result.status.value,
                "strategy_bandwidth": result.bandwidth,
                "strategy_sat_calls": result.sat_calls,
            })
    return rows


def main() -> None:
    root = Path(__file__).resolve().parents[3]
    destination = root / "results/member2/cycle_check.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    rows = run_cycle_check()
    destination.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(destination)


if __name__ == "__main__":
    main()
