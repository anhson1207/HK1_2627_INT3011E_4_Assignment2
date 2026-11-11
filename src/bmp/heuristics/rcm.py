"""Deterministic Reverse Cuthill-McKee baseline heuristic."""

from __future__ import annotations

import math
from time import monotonic

from bmp.core.bounds import cuthill_mckee_order
from bmp.core.graph import Graph
from bmp.core.solution import SolutionStatus, SolverResult
from bmp.core.validation import calculate_bandwidth, validate_solution
from bmp.solvers.sat.search import compute_lower_bound


class RCMSolver:
    """Compute a deterministic Reverse Cuthill-McKee labeling."""

    def solve(
        self,
        graph: Graph,
        *,
        timeout_seconds: float | None = None,
    ) -> SolverResult:
        if timeout_seconds is not None and (
            not math.isfinite(timeout_seconds) or timeout_seconds < 0
        ):
            raise ValueError("timeout_seconds must be finite and non-negative")

        started = monotonic()
        order = cuthill_mckee_order(graph)
        assignment = {v: i for i, v in enumerate(reversed(order), start=1)}
        value = calculate_bandwidth(graph, assignment)
        report = validate_solution(graph, assignment, claimed_bandwidth=value)
        if not report.valid or report.actual_bandwidth is None:
            raise RuntimeError(f"RCM produced an invalid assignment: {report.errors}")
        lower = min(compute_lower_bound(graph), report.actual_bandwidth)
        return SolverResult(
            instance=graph.name,
            method="HEURISTIC",
            solver="rcm",
            status=SolutionStatus.FEASIBLE,
            runtime_seconds=monotonic() - started,
            permutation=assignment,
            bandwidth=report.actual_bandwidth,
            lower_bound=lower,
            upper_bound=report.actual_bandwidth,
            metadata={
                "variant": "BASELINE",
                "incumbent_source": "heuristic",
                "algorithm": "reverse_cuthill_mckee",
                "initial_bandwidth": report.actual_bandwidth,
                "stop_reason": "completed",
            },
        )


__all__ = ["RCMSolver"]
