"""Common result schema for exact solvers and heuristics."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping


class SolutionStatus(StrEnum):
    """Solver outcomes used throughout experiments."""

    OPTIMAL = "OPTIMAL"
    FEASIBLE = "FEASIBLE"
    INFEASIBLE = "INFEASIBLE"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class BMPSolution:
    """A solver-independent BMP result."""

    status: SolutionStatus
    solver: str
    runtime_seconds: float
    assignment: Mapping[int, int] | None = None
    bandwidth: int | None = None
    lower_bound: int | None = None
    upper_bound: int | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.runtime_seconds < 0:
            raise ValueError("runtime_seconds cannot be negative")
        if self.bandwidth is not None and self.bandwidth < 0:
            raise ValueError("bandwidth cannot be negative")
        if self.lower_bound is not None and self.lower_bound < 0:
            raise ValueError("lower_bound cannot be negative")
        if self.upper_bound is not None and self.upper_bound < 0:
            raise ValueError("upper_bound cannot be negative")
        if (
            self.lower_bound is not None
            and self.upper_bound is not None
            and self.lower_bound > self.upper_bound
        ):
            raise ValueError("lower_bound cannot exceed upper_bound")
        if self.assignment is not None:
            object.__setattr__(self, "assignment", MappingProxyType(dict(self.assignment)))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @property
    def proved_optimal(self) -> bool:
        return self.status is SolutionStatus.OPTIMAL

    def to_dict(self) -> dict[str, object]:
        """Return a stable JSON-serialisable representation."""

        return {
            "status": self.status.value,
            "solver": self.solver,
            "runtime_seconds": self.runtime_seconds,
            "bandwidth": self.bandwidth,
            "lower_bound": self.lower_bound,
            "upper_bound": self.upper_bound,
            "proved_optimal": self.proved_optimal,
            "assignment": None
            if self.assignment is None
            else {str(vertex): label for vertex, label in sorted(self.assignment.items())},
            "metadata": dict(self.metadata),
        }
