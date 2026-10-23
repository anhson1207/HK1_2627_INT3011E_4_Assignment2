"""Canonical immutable graph model shared by every solver."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Iterable, Mapping

Edge = tuple[int, int]


def _normalise_edge(edge: Edge) -> Edge:
    if len(edge) != 2:
        raise ValueError(f"An edge must have two endpoints, got {edge!r}")
    u, v = edge
    if isinstance(u, bool) or isinstance(v, bool) or not isinstance(u, int) or not isinstance(v, int):
        raise TypeError(f"Vertex identifiers must be integers, got {edge!r}")
    if u == v:
        raise ValueError(f"Self-loops are not allowed in a simple graph: {edge!r}")
    return (u, v) if u < v else (v, u)


@dataclass(frozen=True, slots=True)
class Graph:
    """An immutable undirected simple graph.

    Vertex identifiers are integers but need not be contiguous. Edges are
    normalised to ``(min(u, v), max(u, v))`` and duplicate input edges are
    collapsed. All input adapters produce this model.
    """

    vertices: tuple[int, ...]
    edges: frozenset[Edge]
    name: str = ""
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        vertices = tuple(self.vertices)
        if any(isinstance(v, bool) or not isinstance(v, int) for v in vertices):
            raise TypeError("All vertex identifiers must be integers")
        if len(set(vertices)) != len(vertices):
            raise ValueError("Vertex identifiers must be unique")

        vertex_set = set(vertices)
        normalised_edges = frozenset(_normalise_edge(edge) for edge in self.edges)
        unknown = {endpoint for edge in normalised_edges for endpoint in edge} - vertex_set
        if unknown:
            raise ValueError(f"Edges reference unknown vertices: {sorted(unknown)}")

        object.__setattr__(self, "vertices", vertices)
        object.__setattr__(self, "edges", normalised_edges)
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @classmethod
    def from_edges(
        cls,
        vertices: Iterable[int],
        edges: Iterable[Edge],
        *,
        name: str = "",
        metadata: Mapping[str, object] | None = None,
    ) -> Graph:
        """Build a graph while consuming input iterables exactly once."""

        return cls(
            vertices=tuple(vertices),
            edges=frozenset(edges),
            name=name,
            metadata={} if metadata is None else metadata,
        )

    @classmethod
    def create(
        cls,
        *,
        name: str = "",
        n: int | None = None,
        vertices: Iterable[int] | None = None,
        edges: Iterable[Edge] = (),
        metadata: Mapping[str, object] | None = None,
    ) -> Graph:
        """Convenience constructor accepting either vertex count n (0..n-1) or vertices."""
        if vertices is None:
            if n is None:
                raise ValueError("Either n or vertices must be provided")
            if n < 0:
                raise ValueError(f"Number of vertices n cannot be negative, got {n}")
            vertices = tuple(range(n))
        else:
            vertices = tuple(vertices)
            if n is not None and len(vertices) != n:
                raise ValueError(f"Explicit n={n} does not match len(vertices)={len(vertices)}")
        return cls.from_edges(vertices=vertices, edges=edges, name=name, metadata=metadata)

    @property
    def n(self) -> int:
        """Alias for order (number of vertices)."""
        return len(self.vertices)

    @property
    def order(self) -> int:
        """Number of vertices."""

        return len(self.vertices)

    @property
    def size(self) -> int:
        """Number of edges."""

        return len(self.edges)

    @property
    def density(self) -> float:
        """Undirected graph density in ``[0, 1]``."""

        if self.order < 2:
            return 0.0
        return 2.0 * self.size / (self.order * (self.order - 1))

    def neighbors(self, vertex: int) -> frozenset[int]:
        """Return the neighbors of ``vertex``."""

        if vertex not in self.vertices:
            raise KeyError(f"Unknown vertex: {vertex}")
        adjacent: set[int] = set()
        for u, v in self.edges:
            if u == vertex:
                adjacent.add(v)
            elif v == vertex:
                adjacent.add(u)
        return frozenset(adjacent)

    def degree(self, vertex: int) -> int:
        """Return the degree of ``vertex``."""

        return len(self.neighbors(vertex))

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable graph summary."""

        return {
            "name": self.name,
            "n": self.order,
            "m": self.size,
            "density": self.density,
            "vertices": list(self.vertices),
            "edges": [list(edge) for edge in sorted(self.edges)],
            "metadata": dict(self.metadata),
        }


GraphInstance = Graph
__all__ = ["Edge", "Graph", "GraphInstance"]
