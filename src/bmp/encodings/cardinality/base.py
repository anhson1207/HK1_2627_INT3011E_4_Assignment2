"""Base protocol and registry for At-Most-One (AMO) cardinality encodings."""

from __future__ import annotations

from typing import Callable, Protocol, Sequence


class VarAllocator(Protocol):
    """Protocol for allocating fresh variable identifiers."""

    def allocate(self, count: int = 1) -> list[int]:
        """Allocate `count` new positive variable IDs."""
        ...


class SimpleVarAllocator:
    """A thread-safe / deterministic variable allocator."""

    def __init__(self, start_id: int = 1) -> None:
        self._next_id = start_id

    @property
    def next_id(self) -> int:
        return self._next_id

    def allocate(self, count: int = 1) -> list[int]:
        if count < 0:
            raise ValueError(f"Allocation count cannot be negative: {count}")
        allocated = list(range(self._next_id, self._next_id + count))
        self._next_id += count
        return allocated


class AMOEncoder(Protocol):
    """Protocol for At-Most-One cardinality encodings."""

    def encode(
        self,
        literals: Sequence[int],
        allocator: VarAllocator,
    ) -> tuple[list[list[int]], list[int]]:
        """Encode At-Most-One for a sequence of literals.

        Returns:
            (clauses, auxiliary_variables)
        """
        ...


_REGISTRY: dict[str, type[AMOEncoder] | Callable[[], AMOEncoder]] = {}


def register_amo_encoder(name: str, factory: type[AMOEncoder] | Callable[[], AMOEncoder]) -> None:
    _REGISTRY[name.lower()] = factory


def get_amo_encoder(name: str) -> AMOEncoder:
    key = name.lower()
    if key not in _REGISTRY:
        supported = ", ".join(sorted(_REGISTRY.keys()))
        raise ValueError(f"Unknown AMO encoder '{name}'. Supported encoders: [{supported}]")
    factory = _REGISTRY[key]
    return factory()


__all__ = [
    "AMOEncoder",
    "SimpleVarAllocator",
    "VarAllocator",
    "get_amo_encoder",
    "register_amo_encoder",
]

