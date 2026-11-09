"""Search utilities and bounds calculation for SAT-based BMP solvers."""

from __future__ import annotations

from collections import deque
from typing import Mapping

from bmp.core.bounds import degree_lower_bound, identity_upper_bound
from bmp.core.graph import Graph


def compute_component_diameters(graph: Graph) -> list[tuple[int, int]]:
    """Compute (component_size, component_diameter) for all components with >= 2 vertices."""
    visited: set[int] = set()
    components: list[tuple[int, int]] = []

    adj: dict[int, list[int]] = {v: [] for v in graph.vertices}
    for u, v in graph.edges:
        adj[u].append(v)
        adj[v].append(u)

    for root in graph.vertices:
        if root in visited:
            continue
        comp_nodes: list[int] = []
        queue = deque([root])
        visited.add(root)
        while queue:
            curr = queue.popleft()
            comp_nodes.append(curr)
            for neighbor in adj[curr]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)

        c_size = len(comp_nodes)
        if c_size >= 2:
            # Compute diameter of this component via all-pairs BFS
            c_diam = 0
            for start in comp_nodes:
                dist: dict[int, int] = {start: 0}
                q = deque([start])
                while q:
                    u = q.popleft()
                    d = dist[u]
                    c_diam = max(c_diam, d)
                    for v in adj[u]:
                        if v not in dist:
                            dist[v] = d + 1
                            q.append(v)
            components.append((c_size, max(1, c_diam)))

    return components


def compute_lower_bound(graph: Graph) -> int:
    """Compute certified lower bound for bandwidth.

    Uses:
    1. Maximum degree bound: ceil(Delta(G) / 2)
    2. Component diameter bound: max_C ceil((|C| - 1) / diam(C))
    """
    if not graph.edges or graph.order <= 1:
        return 0

    lb_degree = degree_lower_bound(graph)
    lb_component = 0
    for c_size, c_diam in compute_component_diameters(graph):
        lb_c = (c_size - 1 + c_diam - 1) // c_diam  # ceil((c_size - 1) / c_diam)
        if lb_c > lb_component:
            lb_component = lb_c

    return max(lb_degree, lb_component)


def select_anchor_vertex(graph: Graph) -> int:
    """Select a deterministic anchor vertex for reversal symmetry breaking.

    Priority:
    1. Maximum vertex degree
    2. Maximum sum of neighbor degrees
    3. Smallest vertex ID (as tie-breaker)
    """
    if not graph.vertices:
        raise ValueError("Cannot select anchor on an empty graph")

    return max(
        graph.vertices,
        key=lambda v: (
            graph.degree(v),
            sum(graph.degree(nbr) for nbr in graph.neighbors(v)),
            -v,
        ),
    )


def compute_initial_upper_bound(
    graph: Graph,
    heuristic_permutation: Mapping[int, int] | None = None,
    *,
    symmetry_breaking: bool = False,
) -> tuple[int, dict[int, int]]:
    """Compute an initial upper bound and valid permutation.

    If symmetry_breaking is True, normalises the incumbent so the anchor vertex
    satisfies p(anchor) <= ceil(n / 2).
    """
    if not graph.edges or graph.order <= 1:
        identity_perm = {v: i + 1 for i, v in enumerate(graph.vertices)}
        return 0, identity_perm

    if heuristic_permutation is not None:
        from bmp.core.validation import calculate_bandwidth
        perm = dict(heuristic_permutation)
        bw = calculate_bandwidth(graph, perm)
    else:
        bw, perm = identity_upper_bound(graph)

    if symmetry_breaking and graph.order >= 2:
        anchor = select_anchor_vertex(graph)
        cutoff = (graph.order + 1) // 2
        if perm[anchor] > cutoff:
            perm = {v: graph.order + 1 - label for v, label in perm.items()}
            from bmp.core.validation import calculate_bandwidth
            bw = calculate_bandwidth(graph, perm)

    return bw, perm


__all__ = [
    "compute_component_diameters",
    "compute_initial_upper_bound",
    "compute_lower_bound",
]
