"""Optional CPLEX mixed-integer model for graph bandwidth minimization."""

from __future__ import annotations

import math
from dataclasses import dataclass
from time import monotonic

from bmp.core.graph import Graph
from bmp.core.solution import BMPSolution, SolutionStatus
from bmp.core.validation import validate_assignment
from bmp.solvers.exact._common import build_mip_result, prepare_mip_bounds


def _is_availability_error(error: Exception) -> bool:
    message = str(error).lower()
    return any(
        word in message
        for word in ("license", "licence", "credential", "community edition", "error 1016")
    )


@dataclass(slots=True)
class CPLEXMIPSolver:
    """Solve BMP with binary vertex-position assignments and edge spans."""

    def solve(
        self,
        graph: Graph,
        *,
        timeout_seconds: float | None = None,
        symmetry_breaking: bool = False,
    ) -> BMPSolution:
        if timeout_seconds is not None and (not math.isfinite(timeout_seconds) or timeout_seconds < 0):
            raise ValueError("timeout_seconds must be finite and non-negative")

        started = monotonic()
        lower, best_bandwidth, best_assignment, anchor = prepare_mip_bounds(
            graph, symmetry_breaking=symmetry_breaking
        )

        def make_result(status: SolutionStatus, *, metadata: dict[str, object], bound: int) -> BMPSolution:
            return build_mip_result(
                graph,
                solver_name="cplex",
                status=status,
                assignment=best_assignment,
                claimed_bandwidth=best_bandwidth,
                bound=bound,
                runtime_seconds=monotonic() - started,
                metadata=metadata,
            )

        try:
            import cplex
        except ImportError as error:
            return make_result(
                SolutionStatus.UNAVAILABLE,
                metadata={"reason": f"cplex is unavailable: {error}"},
                bound=lower,
            )

        if timeout_seconds == 0:
            return make_result(
                SolutionStatus.TIMEOUT,
                metadata={"cplex_status": "NOT_RUN", "reason": "zero time limit"},
                bound=lower,
            )

        model = None
        try:
            try:
                model = cplex.Cplex()
                model.set_log_stream(None)
                model.set_results_stream(None)
                model.set_warning_stream(None)
                model.set_error_stream(None)
            except cplex.exceptions.CplexError as error:
                if _is_availability_error(error):
                    return make_result(
                        SolutionStatus.UNAVAILABLE,
                        metadata={"reason": f"CPLEX runtime or license unavailable: {error}"},
                        bound=lower,
                    )
                raise RuntimeError(f"CPLEX initialization failed: {error}") from error

            n = graph.order
            positions = range(1, n + 1)
            x_index = {
                (vertex, p): i * n + p - 1
                for i, vertex in enumerate(graph.vertices)
                for p in positions
            }
            b_index = n * n
            try:
                model.objective.set_sense(model.objective.sense.minimize)
                model.variables.add(
                    obj=[0.0] * b_index + [1.0],
                    lb=[0.0] * b_index + [float(lower)],
                    ub=[1.0] * b_index + [float(best_bandwidth)],
                    types="B" * b_index + "I",
                    names=[f"x_{i}_{p}" for i in range(n) for p in positions] + ["B"],
                )

                def add_row(indices: list[int], values: list[float], sense: str, rhs: float) -> None:
                    model.linear_constraints.add(
                        lin_expr=[cplex.SparsePair(ind=indices, val=values)],
                        senses=[sense],
                        rhs=[rhs],
                    )

                for vertex in graph.vertices:
                    add_row([x_index[vertex, p] for p in positions], [1.0] * n, "E", 1.0)
                for p in positions:
                    add_row([x_index[vertex, p] for vertex in graph.vertices], [1.0] * n, "E", 1.0)
                if symmetry_breaking and anchor is not None and n >= 2:
                    cutoff = (n + 1) // 2
                    upper_positions = list(range(cutoff + 1, n + 1))
                    add_row(
                        [x_index[anchor, p] for p in upper_positions],
                        [1.0] * len(upper_positions),
                        "E",
                        0.0,
                    )
                for u, v in graph.edges:
                    for first, second in ((u, v), (v, u)):
                        indices = [b_index]
                        values = [1.0]
                        for p in positions:
                            indices.extend((x_index[first, p], x_index[second, p]))
                            values.extend((-float(p), float(p)))
                        add_row(indices, values, "G", 0.0)

                start_values = [
                    float(best_assignment[vertex] == p)
                    for vertex in graph.vertices
                    for p in positions
                ] + [float(best_bandwidth)]
                model.MIP_starts.add(
                    cplex.SparsePair(ind=list(range(b_index + 1)), val=start_values),
                    model.MIP_starts.effort_level.auto,
                )
                if timeout_seconds is not None:
                    model.parameters.timelimit.set(max(1e-6, timeout_seconds - (monotonic() - started)))
                model.solve()
            except cplex.exceptions.CplexError as error:
                if _is_availability_error(error):
                    return make_result(
                        SolutionStatus.UNAVAILABLE,
                        metadata={"reason": f"CPLEX runtime or license unavailable: {error}"},
                        bound=lower,
                    )
                raise RuntimeError(f"CPLEX model or optimization failed: {error}") from error

            code = model.solution.get_status()
            metadata: dict[str, object] = {
                "cplex_status": code,
                "cplex_status_string": model.solution.get_status_string(),
                "symmetry_breaking": symmetry_breaking,
                "anchor_vertex": anchor,
            }
            primal_feasible = bool(model.solution.is_primal_feasible())
            if primal_feasible:
                values = model.solution.get_values()
                candidate = {
                    vertex: max(positions, key=lambda p: values[x_index[vertex, p]])
                    for vertex in graph.vertices
                }
                report = validate_assignment(graph, candidate)
                if not report.valid or report.actual_bandwidth is None:
                    raise RuntimeError(f"CPLEX returned an invalid assignment: {report.errors}")
                if report.actual_bandwidth < best_bandwidth:
                    best_assignment = candidate
                    best_bandwidth = report.actual_bandwidth

            bound = lower
            for key, getter in (
                ("best_bound", model.solution.MIP.get_best_objective),
                ("mip_gap", model.solution.MIP.get_mip_relative_gap),
            ):
                try:
                    value = float(getter())
                except cplex.exceptions.CplexError:
                    continue
                if math.isfinite(value):
                    metadata[key] = value
                    if key == "best_bound":
                        bound = max(lower, min(best_bandwidth, math.ceil(value - 1e-6)))

            status_ns = model.solution.status
            if code == status_ns.MIP_optimal:
                return make_result(SolutionStatus.OPTIMAL, metadata=metadata, bound=best_bandwidth)
            if code == getattr(status_ns, "MIP_optimal_tolerance", -1):
                if bound >= best_bandwidth:
                    return make_result(SolutionStatus.OPTIMAL, metadata=metadata, bound=best_bandwidth)
                return make_result(SolutionStatus.FEASIBLE, metadata=metadata, bound=bound)
            time_limit_codes = tuple(
                getattr(status_ns, name)
                for name in (
                    "MIP_time_limit_feasible",
                    "MIP_time_limit_infeasible",
                    "MIP_dettime_limit_feasible",
                    "MIP_dettime_limit_infeasible",
                )
                if hasattr(status_ns, name)
            )
            if code in time_limit_codes:
                return make_result(SolutionStatus.TIMEOUT, metadata=metadata, bound=bound)
            if code == getattr(status_ns, "MIP_infeasible", -1):
                return make_result(SolutionStatus.INFEASIBLE, metadata=metadata, bound=bound)
            limit_codes = tuple(
                getattr(status_ns, name)
                for name in (
                    "MIP_abort_feasible",
                    "MIP_abort_infeasible",
                    "MIP_mem_limit_feasible",
                    "MIP_mem_limit_infeasible",
                    "MIP_node_limit_feasible",
                    "MIP_node_limit_infeasible",
                )
                if hasattr(status_ns, name)
            )
            if code in limit_codes:
                status = SolutionStatus.FEASIBLE if primal_feasible else SolutionStatus.UNKNOWN
                return make_result(status, metadata=metadata, bound=bound)
            raise RuntimeError(
                f"CPLEX ended with unexpected status {code}: {metadata['cplex_status_string']}"
            )
        finally:
            if model is not None:
                try:
                    model.end()
                except Exception:
                    pass


__all__ = ["CPLEXMIPSolver"]
