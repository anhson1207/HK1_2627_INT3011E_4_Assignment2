"""Independent validation of BMP assignments and claimed objectives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

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


def compute_bandwidth(graph: Graph, assignment: Mapping[int, int]) -> int:
    """Compute the maximum edge span for an already valid assignment."""

    if not graph.edges:
        return 0
    return max(abs(assignment[u] - assignment[v]) for u, v in graph.edges)


def validate_assignment(
    graph: Graph,
    assignment: Mapping[int, int],
    *,
    claimed_bandwidth: int | None = None,
) -> ValidationReport:
    """Check totality, range, bijectivity, and the claimed bandwidth."""

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
        actual_bandwidth = compute_bandwidth(graph, assignment)
        if claimed_bandwidth is not None and claimed_bandwidth != actual_bandwidth:
            errors.append(
                f"Claimed bandwidth {claimed_bandwidth} does not match actual bandwidth "
                f"{actual_bandwidth}"
            )

    return ValidationReport(not errors, actual_bandwidth, tuple(errors))
