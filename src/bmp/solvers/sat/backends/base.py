"""Base protocol and registry for SAT solver backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Sequence


class SATBackend(ABC):
    """Abstract interface for SAT solvers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the solver backend (e.g. 'cadical', 'glucose', 'minisat')."""
        ...

    @property
    @abstractmethod
    def version(self) -> str:
        """Version string of the solver backend."""
        ...

    @abstractmethod
    def add_clause(self, clause: Sequence[int]) -> None:
        """Add a single disjunctive clause (list of literals)."""
        ...

    @abstractmethod
    def append_formula(self, clauses: Sequence[Sequence[int]]) -> None:
        """Add a collection of clauses to the solver."""
        ...

    @abstractmethod
    def solve(self, assumptions: Sequence[int] = ()) -> bool:
        """Solve formula with optional assumptions. Returns True if SAT, False if UNSAT."""
        ...

    @abstractmethod
    def get_model(self) -> list[int] | None:
        """Return satisfying variable assignment (literals) if SAT, else None."""
        ...

    @abstractmethod
    def delete(self) -> None:
        """Free native resources allocated by the solver."""
        ...

    def __enter__(self) -> SATBackend:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.delete()


_BACKEND_REGISTRY: dict[str, type[SATBackend] | Callable[..., SATBackend]] = {}


def register_sat_backend(name: str, factory: type[SATBackend] | Callable[..., SATBackend]) -> None:
    _BACKEND_REGISTRY[name.lower()] = factory


def get_sat_backend(name: str = "cadical", **kwargs: object) -> SATBackend:
    key = name.lower()
    if key not in _BACKEND_REGISTRY:
        supported = ", ".join(sorted(_BACKEND_REGISTRY.keys()))
        raise ValueError(
            f"SAT backend '{name}' is not registered. Available backends: [{supported}]"
        )
    factory = _BACKEND_REGISTRY[key]
    return factory(**kwargs)


__all__ = [
    "SATBackend",
    "get_sat_backend",
    "register_sat_backend",
]
