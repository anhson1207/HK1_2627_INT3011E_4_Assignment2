"""Deterministic generators for canonical test and benchmark graphs."""

from __future__ import annotations

import random

from bmp.core.graph import Graph


def _positive_size(value: int, *, minimum: int = 1) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"Size must be an integer >= {minimum}")


def path_graph(order: int) -> Graph:
    _positive_size(order)
    return Graph.from_edges(
        range(1, order + 1),
        ((vertex, vertex + 1) for vertex in range(1, order)),
        name=f"path_p{order}",
        metadata={"family": "path", "order": order},
    )


def cycle_graph(order: int) -> Graph:
    _positive_size(order, minimum=3)
    edges = [(vertex, vertex + 1) for vertex in range(1, order)]
    edges.append((order, 1))
    return Graph.from_edges(
        range(1, order + 1),
        edges,
        name=f"cycle_c{order}",
        metadata={"family": "cycle", "order": order},
    )


def complete_graph(order: int) -> Graph:
    _positive_size(order)
    return Graph.from_edges(
        range(1, order + 1),
        ((u, v) for u in range(1, order + 1) for v in range(u + 1, order + 1)),
        name=f"complete_k{order}",
        metadata={"family": "complete", "order": order},
    )


def star_graph(leaves: int) -> Graph:
    _positive_size(leaves)
    order = leaves + 1
    return Graph.from_edges(
        range(1, order + 1),
        ((1, leaf) for leaf in range(2, order + 1)),
        name=f"star_k1_{leaves}",
        metadata={"family": "star", "leaves": leaves, "order": order},
    )


def edgeless_graph(order: int) -> Graph:
    _positive_size(order, minimum=0)
    return Graph.from_edges(
        range(1, order + 1),
        (),
        name=f"edgeless_{order}",
        metadata={"family": "edgeless", "order": order},
    )


def erdos_renyi_graph(order: int, probability: float, *, seed: int) -> Graph:
    """Generate a reproducible ``G(n, p)`` simple graph."""

    _positive_size(order)
    if not 0.0 <= probability <= 1.0:
        raise ValueError("probability must lie in [0, 1]")
    generator = random.Random(seed)
    edges = [
        (u, v)
        for u in range(1, order + 1)
        for v in range(u + 1, order + 1)
        if generator.random() < probability
    ]
    return Graph.from_edges(
        range(1, order + 1),
        edges,
        name=f"erdos_renyi_n{order}_p{probability:g}_s{seed}",
        metadata={
            "family": "erdos-renyi",
            "order": order,
            "probability": probability,
            "seed": seed,
        },
    )
