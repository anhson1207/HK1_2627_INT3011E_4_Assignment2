"""Base interfaces and data structures for SAT CNF encodings."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from time import monotonic
from typing import Mapping, Sequence

from bmp.core.graph import Graph


@dataclass(slots=True)
class CNFFormula:
    """Container for a CNF formula with variable and clause metadata."""

    clauses: list[list[int]] = field(default_factory=list)
    top_var: int = 0
    num_original_vars: int = 0
    num_aux_vars: int = 0
    build_time_s: float = 0.0
    var_map: dict[str, int] = field(default_factory=dict)
    comments: list[str] = field(default_factory=list)

    @property
    def num_clauses(self) -> int:
        return len(self.clauses)

    @property
    def num_variables(self) -> int:
        return self.top_var

    def add_clause(self, clause: Sequence[int]) -> None:
        self.clauses.append(list(clause))

    def extend_clauses(self, clauses: Sequence[Sequence[int]]) -> None:
        for c in clauses:
            self.clauses.append(list(c))

    def copy(self) -> CNFFormula:
        return CNFFormula(
            clauses=[list(c) for c in self.clauses],
            top_var=self.top_var,
            num_original_vars=self.num_original_vars,
            num_aux_vars=self.num_aux_vars,
            build_time_s=self.build_time_s,
            var_map=dict(self.var_map),
            comments=list(self.comments),
        )


class BMPEncoder(ABC):
    """Abstract base class for BMP SAT encoders."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the encoding (e.g. 'pairwise', 'order')."""
        ...

    @abstractmethod
    def encode(self, graph: Graph, k: int, **kwargs: object) -> CNFFormula:
        """Generate complete CNF formula for graph G and bandwidth k."""
        ...

    @abstractmethod
    def decode(self, graph: Graph, model: Sequence[int], k: int) -> dict[int, int]:
        """Decode a satisfying SAT assignment into a permutation: vertex -> label (1..n)."""
        ...

    @abstractmethod
    def encode_fixed(self, graph: Graph, **kwargs: object) -> CNFFormula:
        """Generate fixed k-independent clauses for incremental SAT."""
        ...

    @abstractmethod
    def encode_bandwidth_step(self, graph: Graph, k: int, **kwargs: object) -> list[list[int]]:
        """Generate clauses enforcing bandwidth <= k (for repeated or incremental additions)."""
        ...


__all__ = ["BMPEncoder", "CNFFormula"]

