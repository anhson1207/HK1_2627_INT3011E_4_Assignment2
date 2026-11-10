"""Exact BMP with the optional IBM CP Optimizer local executable."""

from __future__ import annotations

import math
from dataclasses import dataclass
from math import floor
from shutil import which
from time import monotonic

from bmp.core.graph import Graph
from bmp.core.solution import SolutionStatus, SolverResult
from bmp.core.validation import validate_solution
from bmp.solvers.sat.search import compute_lower_bound, select_anchor_vertex


def _build_model(graph: Graph, *, symmetry_breaking: bool = False):
    from docplex.cp.model import CpoModel

    model = CpoModel()
    positions = {
        v: model.integer_var(1, graph.order, f"p_{i}")
        for i, v in enumerate(graph.vertices)
    }
    if positions:
        model.add(model.all_diff(list(positions.values())))
    if symmetry_breaking and graph.order >= 2:
        anchor = select_anchor_vertex(graph)
        cutoff = (graph.order + 1) // 2
        model.add(positions[anchor] <= cutoff)
    lower = compute_lower_bound(graph)
    bandwidth = model.integer_var(lower, max(0, graph.order - 1), "B")
    # AllDiff trên miền 1..n tạo song ánh. B chặn độ dài mọi cạnh.
    for u, v in sorted(graph.edges):
        model.add(model.abs(positions[u] - positions[v]) <= bandwidth)
    model.add(model.minimize(bandwidth))
    return model, positions


def _extract_objective_bound(result: object) -> float | None:
    """Safely read dual objective bound from a CP Optimizer solve result."""
    getter = getattr(result, "get_objective_bounds", None)
    if getter is None:
        return None
    try:
        bounds = getter()
    except Exception:
        return None
    if not bounds:
        return None
    first = bounds[0]
    if isinstance(first, (int, float)) and not isinstance(first, bool) and math.isfinite(first):
        return float(first)
    return None


@dataclass(slots=True)
class CPOptimizerSolver:
    """Solve BMP using IBM ILOG CP Optimizer via ``docplex.cp``."""

    executable: str = "cpoptimizer"

    def solve(
        self,
        graph: Graph,
        *,
        timeout_seconds: float | None = None,
        symmetry_breaking: bool = False,
        threads: int | None = None,
    ) -> SolverResult:
        if timeout_seconds is not None and (
            not math.isfinite(timeout_seconds) or timeout_seconds < 0
        ):
            raise ValueError("timeout_seconds must be finite and non-negative")
        if threads is not None and threads < 1:
            raise ValueError("threads must be at least 1")

        started = monotonic()
        name = "cp-optimizer"
        graph_lb = compute_lower_bound(graph)
        anchor = (
            select_anchor_vertex(graph)
            if symmetry_breaking and graph.order >= 2
            else None
        )
        base_meta: dict[str, object] = {
            "symmetry_breaking": symmetry_breaking,
            "anchor_vertex": anchor,
            "threads": threads,
            "certified_graph_lower_bound": graph_lb,
            "incumbent_source": name,
        }

        try:
            from docplex.cp.solution import STOP_CAUSE_LIMIT
            from docplex.cp.utils import CpoException

            model, positions = _build_model(graph, symmetry_breaking=symmetry_breaking)
        except ImportError as exc:
            return SolverResult(
                instance=graph.name,
                method="CP",
                solver=name,
                status=SolutionStatus.UNAVAILABLE,
                runtime_seconds=monotonic() - started,
                lower_bound=graph_lb,
                metadata={**base_meta, "reason": str(exc)},
            )

        executable = which(self.executable)
        if executable is None:
            return SolverResult(
                instance=graph.name,
                method="CP",
                solver=name,
                status=SolutionStatus.UNAVAILABLE,
                runtime_seconds=monotonic() - started,
                lower_bound=graph_lb,
                metadata={
                    **base_meta,
                    "reason": f"Executable not found: {self.executable}",
                },
            )

        if timeout_seconds == 0:
            return SolverResult(
                instance=graph.name,
                method="CP",
                solver=name,
                status=SolutionStatus.TIMEOUT,
                runtime_seconds=monotonic() - started,
                lower_bound=graph_lb,
                metadata={
                    **base_meta,
                    "native_status": "NOT_RUN",
                    "reason": "zero time limit",
                },
            )

        options: dict[str, object] = {
            "agent": "local",
            "execfile": executable,
            "LogVerbosity": "Quiet",
            "Workers": 1 if threads is None else int(threads),
        }
        if timeout_seconds is not None:
            remaining = timeout_seconds - (monotonic() - started)
            if remaining <= 0:
                return SolverResult(
                    instance=graph.name,
                    method="CP",
                    solver=name,
                    status=SolutionStatus.TIMEOUT,
                    runtime_seconds=monotonic() - started,
                    lower_bound=graph_lb,
                    metadata={**base_meta, "reason": "time limit exhausted before solve"},
                )
            options["TimeLimit"] = remaining

        try:
            with model.create_solver(**options) as solver:
                result = solver.solve()
        except (CpoException, OSError) as exc:
            reason = str(exc)
            runtime_missing = isinstance(exc, OSError) or any(
                marker in reason.lower()
                for marker in (
                    "executable",
                    "license",
                    "licence",
                    "execfile",
                    "not found",
                    "no such file",
                )
            )
            status = (
                SolutionStatus.UNAVAILABLE if runtime_missing else SolutionStatus.ERROR
            )
            return SolverResult(
                instance=graph.name,
                method="CP",
                solver=name,
                status=status,
                runtime_seconds=monotonic() - started,
                lower_bound=graph_lb,
                metadata={**base_meta, "reason": reason},
            )

        native = result.get_solve_status()
        stop = result.get_stop_cause()
        raw_solver_bound = _extract_objective_bound(result)
        solver_lb = (
            max(0, floor(raw_solver_bound)) if raw_solver_bound is not None else None
        )
        metadata: dict[str, object] = {
            **base_meta,
            "native_status": native,
            "stop_cause": stop,
            "native_best_bound": raw_solver_bound,
            "solver_lower_bound": solver_lb,
        }

        status = {
            "Optimal": SolutionStatus.OPTIMAL,
            "Feasible": SolutionStatus.FEASIBLE,
            "Infeasible": SolutionStatus.INFEASIBLE,
        }.get(native, SolutionStatus.ERROR)
        if (
            native in ("Unknown", "JobAborted")
            and stop == STOP_CAUSE_LIMIT
            and timeout_seconds is not None
        ):
            status = SolutionStatus.TIMEOUT

        if status in (SolutionStatus.OPTIMAL, SolutionStatus.FEASIBLE):
            assignment = {
                v: result.get_value(position) for v, position in positions.items()
            }
            certificate = validate_solution(graph, assignment)
            if not certificate.valid or certificate.actual_bandwidth is None:
                metadata["reason"] = "; ".join(certificate.errors)
                return SolverResult(
                    instance=graph.name,
                    method="CP",
                    solver=name,
                    status=SolutionStatus.ERROR,
                    runtime_seconds=monotonic() - started,
                    lower_bound=graph_lb,
                    metadata=metadata,
                )
            value = certificate.actual_bandwidth
            effective_lb = (
                value
                if status is SolutionStatus.OPTIMAL
                else min(
                    value,
                    max(graph_lb, solver_lb) if solver_lb is not None else graph_lb,
                )
            )
            return SolverResult(
                instance=graph.name,
                method="CP",
                solver=name,
                status=status,
                runtime_seconds=monotonic() - started,
                permutation=assignment,
                bandwidth=value,
                upper_bound=value,
                lower_bound=effective_lb,
                metadata=metadata,
            )

        fallback_lb = (
            max(graph_lb, solver_lb) if solver_lb is not None else graph_lb
        )
        return SolverResult(
            instance=graph.name,
            method="CP",
            solver=name,
            status=status,
            runtime_seconds=monotonic() - started,
            lower_bound=fallback_lb if status is SolutionStatus.TIMEOUT else None,
            metadata=metadata,
        )


__all__ = ["CPOptimizerSolver", "_build_model"]
