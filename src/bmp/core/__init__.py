"""Shared graph, solution, bound, and validation models."""

from bmp.core.benchmark_catalog import (
    BenchmarkInstanceMeta,
    PreflightReport,
    TABLE_6_INSTANCES,
    TABLE_7_INSTANCES,
    preflight_check_dataset,
    verify_instance_file,
)
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
    "BenchmarkInstanceMeta",
    "Edge",
    "Graph",
    "GraphInstance",
    "BMPSolution",
    "PreflightReport",
    "SolutionStatus",
    "SolverResult",
    "TABLE_6_INSTANCES",
    "TABLE_7_INSTANCES",
    "ValidationReport",
    "calculate_bandwidth",
    "compute_bandwidth",
    "preflight_check_dataset",
    "validate_assignment",
    "validate_solution",
    "verify_instance_file",
]
