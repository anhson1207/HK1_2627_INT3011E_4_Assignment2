"""Common result schema for exact solvers, SAT solvers, and heuristics."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping


class SolutionStatus(StrEnum):
    """Solver outcomes used throughout experiments."""

    OPTIMAL = "OPTIMAL"
    FEASIBLE = "FEASIBLE"
    INFEASIBLE = "INFEASIBLE"
    TIMEOUT = "TIMEOUT"
    UNKNOWN = "UNKNOWN"
    ERROR = "ERROR"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class SolverResult:
    """A comprehensive result container for BMP solvers."""

    instance: str = ""
    method: str | None = None
    solver: str = ""
    encoding: str | None = None
    strategy: str | None = None
    status: SolutionStatus = SolutionStatus.UNKNOWN
    bandwidth: int | None = None
    permutation: Mapping[int, int] | None = None
    runtime_s: float = 0.0
    encoding_time_s: float = 0.0
    solving_time_s: float = 0.0
    num_variables: int | None = None
    num_clauses: int | None = None
    sat_calls: int = 0
    lower_bound: int | None = None
    upper_bound: int | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __init__(
        self,
        *,
        instance: str = "",
        method: str | None = None,
        solver: str = "",
        encoding: str | None = None,
        strategy: str | None = None,
        status: SolutionStatus = SolutionStatus.UNKNOWN,
        bandwidth: int | None = None,
        permutation: Mapping[int, int] | None = None,
        assignment: Mapping[int, int] | None = None,
        runtime_s: float | None = None,
        runtime_seconds: float | None = None,
        encoding_time_s: float = 0.0,
        solving_time_s: float = 0.0,
        num_variables: int | None = None,
        num_clauses: int | None = None,
        sat_calls: int = 0,
        lower_bound: int | None = None,
        upper_bound: int | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> None:
        perm = permutation if permutation is not None else assignment
        r_time = runtime_s if runtime_s is not None else (runtime_seconds if runtime_seconds is not None else 0.0)

        if r_time < 0:
            raise ValueError("runtime cannot be negative")
        if bandwidth is not None and bandwidth < 0:
            raise ValueError("bandwidth cannot be negative")
        if lower_bound is not None and lower_bound < 0:
            raise ValueError("lower_bound cannot be negative")
        if upper_bound is not None and upper_bound < 0:
            raise ValueError("upper_bound cannot be negative")
        if lower_bound is not None and upper_bound is not None and lower_bound > upper_bound:
            raise ValueError("lower_bound cannot exceed upper_bound")

        object.__setattr__(self, "instance", instance)
        object.__setattr__(self, "method", method)
        object.__setattr__(self, "solver", solver)
        object.__setattr__(self, "encoding", encoding)
        object.__setattr__(self, "strategy", strategy)
        object.__setattr__(self, "status", status if isinstance(status, SolutionStatus) else SolutionStatus(status))
        object.__setattr__(self, "bandwidth", bandwidth)
        object.__setattr__(
            self,
            "permutation",
            MappingProxyType(dict(perm)) if perm is not None else None,
        )
        object.__setattr__(self, "runtime_s", float(r_time))
        object.__setattr__(self, "encoding_time_s", float(encoding_time_s))
        object.__setattr__(self, "solving_time_s", float(solving_time_s))
        object.__setattr__(self, "num_variables", num_variables)
        object.__setattr__(self, "num_clauses", num_clauses)
        object.__setattr__(self, "sat_calls", sat_calls)
        object.__setattr__(self, "lower_bound", lower_bound)
        object.__setattr__(self, "upper_bound", upper_bound)
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(metadata or {})),
        )

    @property
    def assignment(self) -> Mapping[int, int] | None:
        """Alias for permutation for backward compatibility."""
        return self.permutation

    @property
    def runtime_seconds(self) -> float:
        """Alias for runtime_s for backward compatibility."""
        return self.runtime_s

    @property
    def proved_optimal(self) -> bool:
        return self.status is SolutionStatus.OPTIMAL

    def to_dict(self) -> dict[str, object]:
        """Return a stable JSON-serialisable representation."""
        return {
            "instance": self.instance,
            "method": self.method,
            "solver": self.solver,
            "encoding": self.encoding,
            "strategy": self.strategy,
            "status": self.status.value,
            "bandwidth": self.bandwidth,
            "permutation": None
            if self.permutation is None
            else {str(v): label for v, label in sorted(self.permutation.items())},
            "assignment": None
            if self.permutation is None
            else {str(v): label for v, label in sorted(self.permutation.items())},
            "runtime_s": self.runtime_s,
            "runtime_seconds": self.runtime_s,
            "encoding_time_s": self.encoding_time_s,
            "solving_time_s": self.solving_time_s,
            "num_variables": self.num_variables,
            "num_clauses": self.num_clauses,
            "sat_calls": self.sat_calls,
            "lower_bound": self.lower_bound,
            "upper_bound": self.upper_bound,
            "proved_optimal": self.proved_optimal,
            "metadata": dict(self.metadata),
        }


BMPSolution = SolverResult
__all__ = ["SolutionStatus", "SolverResult", "BMPSolution"]
