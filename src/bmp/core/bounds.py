"""Cheap, certified bounds used by exact and hybrid solvers."""

from __future__ import annotations

from bmp.core.graph import Graph
from bmp.core.validation import compute_bandwidth


def degree_lower_bound(graph: Graph) -> int:
    """Return ``ceil(max_degree / 2)``, or zero for an edgeless graph.

    With bandwidth ``b``, at most ``2b`` positions lie within distance ``b``
    of a vertex, so every vertex degree is at most ``2b``.
    """

    if not graph.edges:
        return 0
    maximum_degree = max(graph.degree(vertex) for vertex in graph.vertices)
    return (maximum_degree + 1) // 2


def identity_upper_bound(graph: Graph) -> tuple[int, dict[int, int]]:
    """Return the objective of the graph's stored vertex order."""

    assignment = {vertex: position for position, vertex in enumerate(graph.vertices, start=1)}
    return compute_bandwidth(graph, assignment), assignment
