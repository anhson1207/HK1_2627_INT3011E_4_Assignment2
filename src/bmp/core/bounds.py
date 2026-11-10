"""Cheap, certified bounds and deterministic ordering helpers used across solvers."""

from __future__ import annotations

from collections import deque

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


def cuthill_mckee_order(graph: Graph) -> list[int]:
    """Return deterministic Cuthill-McKee BFS traversal order over all components."""

    degrees = {vertex: graph.degree(vertex) for vertex in graph.vertices}
    adjacency = {vertex: graph.neighbors(vertex) for vertex in graph.vertices}
    remaining = set(graph.vertices)
    order: list[int] = []

    while remaining:
        root = min(remaining, key=lambda v: (degrees[v], v))
        remaining.remove(root)
        queue = deque([root])
        while queue:
            vertex = queue.popleft()
            order.append(vertex)
            for neighbor in sorted(adjacency[vertex] & remaining, key=lambda v: (degrees[v], v)):
                remaining.remove(neighbor)
                queue.append(neighbor)

    return order


__all__ = [
    "cuthill_mckee_order",
    "degree_lower_bound",
    "identity_upper_bound",
]
