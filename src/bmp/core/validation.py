"""Independent validation of BMP assignments and claimed objectives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from bmp.core.graph import Graph


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Detailed outcome of independently checking a candidate labeling."""

    valid: bool
    actual_bandwidth: int | None
    errors: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "valid": self.valid,
            "actual_bandwidth": self.actual_bandwidth,
            "errors": list(self.errors),
        }


def calculate_bandwidth(graph: Graph, assignment: Mapping[int, int]) -> int:
    """Compute the maximum edge span for an assignment.

    For an edgeless graph or graph with n <= 1, the bandwidth is 0.
    """
    if not graph.edges or graph.order <= 1:
        return 0
    return max(abs(assignment[u] - assignment[v]) for u, v in graph.edges)


# Backward-compatible alias
compute_bandwidth = calculate_bandwidth


def validate_solution(
    graph: Graph,
    solution: Any,
    *,
    claimed_bandwidth: int | None = None,
) -> ValidationReport:
    """Check totality, range, bijectivity, and the claimed bandwidth.

    Accepts either a mapping (vertex -> label) or a SolverResult/BMPSolution.
    """
    assignment: Mapping[int, int]
    if hasattr(solution, "permutation") and solution.permutation is not None:
        assignment = solution.permutation
        if claimed_bandwidth is None:
            claimed_bandwidth = solution.bandwidth
    elif hasattr(solution, "assignment") and solution.assignment is not None:
        assignment = solution.assignment
        if claimed_bandwidth is None:
            claimed_bandwidth = solution.bandwidth
    elif isinstance(solution, Mapping):
        assignment = solution
    else:
        return ValidationReport(False, None, (f"Invalid solution type: {type(solution)}",))

    errors: list[str] = []
    expected_vertices = set(graph.vertices)
    actual_vertices = set(assignment)
    missing = sorted(expected_vertices - actual_vertices)
    extra = sorted(actual_vertices - expected_vertices)
    if missing:
        errors.append(f"Missing vertices: {missing}")
    if extra:
        errors.append(f"Unknown vertices: {extra}")

    labels = list(assignment.values())
    non_integer = [label for label in labels if isinstance(label, bool) or not isinstance(label, int)]
    if non_integer:
        errors.append(f"Labels must be integers: {non_integer}")
    elif any(label < 1 or label > graph.order for label in labels):
        errors.append(f"Labels must lie in 1..{graph.order}")

    if len(labels) != len(set(labels)):
        errors.append("Labels must be pairwise distinct")
    if len(labels) == graph.order and set(labels) != set(range(1, graph.order + 1)):
        errors.append(f"Labels must form the permutation 1..{graph.order}")

    actual_bandwidth: int | None = None
    if not errors:
        actual_bandwidth = calculate_bandwidth(graph, assignment)
        if claimed_bandwidth is not None and claimed_bandwidth != actual_bandwidth:
            errors.append(
                f"Claimed bandwidth {claimed_bandwidth} does not match actual bandwidth "
                f"{actual_bandwidth}"
            )

    return ValidationReport(not errors, actual_bandwidth, tuple(errors))


# Backward-compatible alias
validate_assignment = validate_solution

__all__ = [
    "ValidationReport",
    "calculate_bandwidth",
    "compute_bandwidth",
    "validate_solution",
    "validate_assignment",
]
