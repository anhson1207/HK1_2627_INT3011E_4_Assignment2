"""Exact BMP with Google OR-Tools CP-SAT."""

from __future__ import annotations

import math
from dataclasses import dataclass
from math import floor
from time import monotonic

from bmp.core.graph import Graph
from bmp.core.solution import SolutionStatus, SolverResult
from bmp.core.validation import validate_solution
from bmp.solvers.sat.search import compute_lower_bound, select_anchor_vertex


@dataclass(slots=True)
class CPSATSolver:
    """Solve BMP exactly using OR-Tools CP-SAT."""

    seed: int = 0

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
        name = "cp-sat"
        graph_lb = compute_lower_bound(graph)
        anchor = (
            select_anchor_vertex(graph)
            if symmetry_breaking and graph.order >= 2
            else None
        )

        try:
            from ortools.sat.python import cp_model
        except ImportError as exc:
            return SolverResult(
                instance=graph.name,
                method="CP",
                solver=name,
                status=SolutionStatus.UNAVAILABLE,
                runtime_seconds=monotonic() - started,
                lower_bound=graph_lb,
                metadata={
                    "reason": str(exc),
                    "seed": self.seed,
                    "symmetry_breaking": symmetry_breaking,
                    "anchor_vertex": anchor,
                    "threads": threads,
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
                    "native_status": "NOT_RUN",
                    "reason": "zero time limit",
                    "seed": self.seed,
                    "symmetry_breaking": symmetry_breaking,
                    "anchor_vertex": anchor,
                    "threads": threads,
                },
            )

        model = cp_model.CpModel()
        positions = {
            v: model.new_int_var(1, graph.order, f"p_{v}") for v in graph.vertices
        }
        if positions:
            model.add_all_different(positions.values())
        if symmetry_breaking and anchor is not None and graph.order >= 2:
            cutoff = (graph.order + 1) // 2
            model.add(positions[anchor] <= cutoff)

        bandwidth = model.new_int_var(graph_lb, max(0, graph.order - 1), "B")
        # Hai bất đẳng thức tuyến tính tương đương |p_u - p_v| <= B.
        for u, v in sorted(graph.edges):
            model.add(positions[u] - positions[v] <= bandwidth)
            model.add(positions[v] - positions[u] <= bandwidth)
        model.minimize(bandwidth)

        solver = cp_model.CpSolver()
        solver.parameters.num_search_workers = 1 if threads is None else int(threads)
        solver.parameters.random_seed = self.seed
        if timeout_seconds is not None:
            solver.parameters.max_time_in_seconds = max(
                0.0, timeout_seconds - (monotonic() - started)
            )

        native = solver.solve(model)
        status = {
            cp_model.OPTIMAL: SolutionStatus.OPTIMAL,
            cp_model.FEASIBLE: SolutionStatus.FEASIBLE,
            cp_model.INFEASIBLE: SolutionStatus.INFEASIBLE,
            cp_model.UNKNOWN: (
                SolutionStatus.TIMEOUT
                if timeout_seconds is not None
                else SolutionStatus.ERROR
            ),
        }.get(native, SolutionStatus.ERROR)

        metadata: dict[str, object] = {
            "native_status": solver.status_name(native),
            "seed": self.seed,
            "symmetry_breaking": symmetry_breaking,
            "anchor_vertex": anchor,
            "threads": threads,
            "certified_graph_lower_bound": graph_lb,
            "incumbent_source": name,
        }

        lower_bound: int | None = None
        if status in (
            SolutionStatus.OPTIMAL,
            SolutionStatus.FEASIBLE,
            SolutionStatus.TIMEOUT,
        ):
            best_bound = solver.best_objective_bound
            metadata["native_best_bound"] = best_bound
            if math.isfinite(best_bound):
                lower_bound = max(graph_lb, max(0, floor(best_bound)))
            else:
                lower_bound = graph_lb

        if status in (SolutionStatus.OPTIMAL, SolutionStatus.FEASIBLE):
            assignment = {
                v: solver.value(position) for v, position in positions.items()
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
            safe_lb = value if status is SolutionStatus.OPTIMAL else min(
                value, graph_lb if lower_bound is None else lower_bound
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
                lower_bound=safe_lb,
                metadata=metadata,
            )

        return SolverResult(
            instance=graph.name,
            method="CP",
            solver=name,
            status=status,
            runtime_seconds=monotonic() - started,
            lower_bound=lower_bound,
            metadata=metadata,
        )


__all__ = ["CPSATSolver"]
