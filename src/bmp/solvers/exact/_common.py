"""Shared bounds, symmetry normalization, and result builder for exact MIP solvers."""

from __future__ import annotations

from typing import Mapping

from bmp.core.bounds import identity_upper_bound
from bmp.core.graph import Graph
from bmp.core.solution import BMPSolution, SolutionStatus
from bmp.core.validation import calculate_bandwidth, validate_assignment
from bmp.solvers.sat.search import compute_lower_bound, select_anchor_vertex


def prepare_mip_bounds(
    graph: Graph, *, symmetry_breaking: bool = False
) -> tuple[int, int, dict[int, int], int | None]:
    """Compute certified lower bound, identity upper bound, and symmetry anchor.

    When ``symmetry_breaking`` is enabled on a graph with at least two vertices,
    the anchor vertex is chosen with ``select_anchor_vertex`` (matching SAT) and
    the initial identity permutation is reversed if needed so ``p(anchor) <= ceil(n/2)``
    while preserving the exact initial bandwidth.
    """
    lower = compute_lower_bound(graph)
    best_bandwidth, best_assignment = identity_upper_bound(graph)
    anchor: int | None = None

    if symmetry_breaking and graph.order >= 2:
        anchor = select_anchor_vertex(graph)
        cutoff = (graph.order + 1) // 2
        if best_assignment[anchor] > cutoff:
            best_assignment = {
                vertex: graph.order + 1 - pos for vertex, pos in best_assignment.items()
            }
            best_bandwidth = calculate_bandwidth(graph, best_assignment)

    return lower, best_bandwidth, best_assignment, anchor


def build_mip_result(
    graph: Graph,
    *,
    solver_name: str,
    status: SolutionStatus,
    assignment: Mapping[int, int],
    claimed_bandwidth: int,
    bound: int,
    runtime_seconds: float,
    metadata: Mapping[str, object],
) -> BMPSolution:
    """Validate an assignment and wrap it into a standardized SolverResult."""
    report = validate_assignment(graph, assignment, claimed_bandwidth=claimed_bandwidth)
    if not report.valid or report.actual_bandwidth is None:
        raise RuntimeError(f"{solver_name} assignment failed validation: {report.errors}")
    safe_bound = max(0, min(report.actual_bandwidth, bound))
    return BMPSolution(
        instance=graph.name,
        method="MIP",
        solver=solver_name,
        status=status,
        runtime_seconds=runtime_seconds,
        permutation=assignment,
        bandwidth=report.actual_bandwidth,
        lower_bound=safe_bound,
        upper_bound=report.actual_bandwidth,
        metadata=dict(metadata),
    )


__all__ = ["build_mip_result", "prepare_mip_bounds"]
