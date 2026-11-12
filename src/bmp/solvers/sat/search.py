"""Search utilities and bounds calculation for SAT-based BMP solvers."""

from __future__ import annotations

from collections import deque
from functools import lru_cache
from typing import Mapping

from bmp.core.bounds import cuthill_mckee_order, degree_lower_bound, identity_upper_bound
from bmp.core.graph import Edge, Graph


@lru_cache(maxsize=256)
def _cached_component_diameters(
    vertices: tuple[int, ...], edges: frozenset[Edge]
) -> tuple[tuple[int, int], ...]:
    n = len(vertices)
    if n < 2 or not edges:
        return ()

    v_to_idx = {v: i for i, v in enumerate(vertices)}
    adj: list[list[int]] = [[] for _ in range(n)]
    adj_mask = [0] * n
    for u, v in edges:
        ui = v_to_idx[u]
        vi = v_to_idx[v]
        adj[ui].append(vi)
        adj[vi].append(ui)
        adj_mask[ui] |= 1 << vi
        adj_mask[vi] |= 1 << ui

    comp_visited = [False] * n
    components: list[tuple[int, int]] = []

    for root in range(n):
        if comp_visited[root]:
            continue
        comp_visited[root] = True
        comp_nodes = [root]
        head = 0
        while head < len(comp_nodes):
            curr = comp_nodes[head]
            head += 1
            for nbr in adj[curr]:
                if not comp_visited[nbr]:
                    comp_visited[nbr] = True
                    comp_nodes.append(nbr)

        c_size = len(comp_nodes)
        if c_size >= 2:
            c_diam = 0
            for start in comp_nodes:
                visited_mask = 1 << start
                frontier_mask = visited_mask
                depth = -1
                while frontier_mask:
                    depth += 1
                    next_mask = 0
                    rem = frontier_mask
                    while rem:
                        lsb = rem & -rem
                        next_mask |= adj_mask[lsb.bit_length() - 1]
                        rem ^= lsb
                    next_mask &= ~visited_mask
                    visited_mask |= next_mask
                    frontier_mask = next_mask
                if depth > c_diam:
                    c_diam = depth
            components.append((c_size, max(1, c_diam)))

    return tuple(components)


def compute_component_diameters(graph: Graph) -> list[tuple[int, int]]:
    """Compute (component_size, component_diameter) for all components with >= 2 vertices."""
    return list(_cached_component_diameters(graph.vertices, graph.edges))


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

    adjacency: dict[int, list[int]] = {v: [] for v in graph.vertices}
    for u, v in graph.edges:
        adjacency[u].append(v)
        adjacency[v].append(u)
    degrees = {v: len(adjacency[v]) for v in graph.vertices}

    return max(
        graph.vertices,
        key=lambda v: (
            degrees[v],
            sum(degrees[nbr] for nbr in adjacency[v]),
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
        # Cuthill-McKee and its reverse are inexpensive deterministic incumbents.
        # Both are checked on the exact graph before becoming upper bounds.
        from bmp.core.validation import calculate_bandwidth
        order = cuthill_mckee_order(graph)
        for candidate_order in (order, list(reversed(order))):
            candidate = {v: label for label, v in enumerate(candidate_order, start=1)}
            candidate_bw = calculate_bandwidth(graph, candidate)
            if candidate_bw < bw:
                bw, perm = candidate_bw, candidate

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
