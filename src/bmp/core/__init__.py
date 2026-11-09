"""Shared graph, solution, bound, and validation models."""

from bmp.core.graph import Edge, Graph, GraphInstance
from bmp.core.solution import BMPSolution, SolutionStatus, SolverResult
from bmp.core.validation import (
    ValidationReport,
    calculate_bandwidth,
    compute_bandwidth,
    validate_assignment,
    validate_solution,
)

__all__ = [
    "Edge",
    "Graph",
    "GraphInstance",
    "BMPSolution",
    "SolutionStatus",
    "SolverResult",
    "ValidationReport",
    "calculate_bandwidth",
    "compute_bandwidth",
    "validate_assignment",
    "validate_solution",
]
