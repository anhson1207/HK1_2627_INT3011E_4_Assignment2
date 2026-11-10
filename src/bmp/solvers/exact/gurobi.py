"""Optional Gurobi mixed-integer model for graph bandwidth minimization."""

from __future__ import annotations

import math
from dataclasses import dataclass
from time import monotonic

from bmp.core.graph import Graph
from bmp.core.solution import BMPSolution, SolutionStatus
from bmp.core.validation import validate_assignment
from bmp.solvers.exact._common import build_mip_result, prepare_mip_bounds


def _is_license_error(error: Exception) -> bool:
    return any(
        word in str(error).lower()
        for word in ("license", "licence", "credential")
    )


@dataclass(slots=True)
class GurobiMIPSolver:
    """Solve BMP with a permutation assignment and edge-span constraints."""

    def solve(
        self,
        graph: Graph,
        *,
        timeout_seconds: float | None = None,
        symmetry_breaking: bool = False,
        threads: int | None = None,
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
                solver_name="gurobi",
                status=status,
                assignment=best_assignment,
                claimed_bandwidth=best_bandwidth,
                bound=bound,
                runtime_seconds=monotonic() - started,
                metadata=metadata,
            )

        try:
            import gurobipy as gp
        except ImportError as error:
            return make_result(
                SolutionStatus.UNAVAILABLE,
                metadata={"reason": f"gurobipy is unavailable: {error}"},
                bound=lower,
            )

        if timeout_seconds == 0:
            return make_result(
                SolutionStatus.TIMEOUT,
                metadata={"gurobi_status": "NOT_RUN", "reason": "zero time limit"},
                bound=lower,
            )

        environment = None
        model = None
        try:
            try:
                environment = gp.Env(empty=True)
                environment.setParam("OutputFlag", 0)
                environment.start()
                model = gp.Model("bandwidth_minimization", env=environment)
            except gp.GurobiError as error:
                message = str(error)
                if _is_license_error(error):
                    return make_result(
                        SolutionStatus.UNAVAILABLE,
                        metadata={"reason": f"Gurobi license unavailable: {message}"},
                        bound=lower,
                    )
                raise RuntimeError(f"Gurobi model initialization failed: {message}") from error

            n = graph.order
            positions = range(1, n + 1)
            try:
                x = model.addVars(graph.vertices, positions, vtype=gp.GRB.BINARY, name="x")
                bandwidth = model.addVar(
                    vtype=gp.GRB.INTEGER, lb=lower, ub=best_bandwidth, name="B"
                )
                for vertex in graph.vertices:
                    model.addConstr(gp.quicksum(x[vertex, p] for p in positions) == 1)
                for p in positions:
                    model.addConstr(gp.quicksum(x[vertex, p] for vertex in graph.vertices) == 1)
                if symmetry_breaking and anchor is not None and n >= 2:
                    cutoff = (n + 1) // 2
                    model.addConstr(
                        gp.quicksum(x[anchor, p] for p in range(cutoff + 1, n + 1)) == 0
                    )
                labels = {
                    vertex: gp.quicksum(p * x[vertex, p] for p in positions)
                    for vertex in graph.vertices
                }
                for u, v in graph.edges:
                    model.addConstr(bandwidth >= labels[u] - labels[v])
                    model.addConstr(bandwidth >= labels[v] - labels[u])
                model.setObjective(bandwidth, gp.GRB.MINIMIZE)
                for vertex in graph.vertices:
                    for p in positions:
                        x[vertex, p].Start = int(best_assignment[vertex] == p)
                bandwidth.Start = best_bandwidth
                if timeout_seconds is not None:
                    model.Params.TimeLimit = max(0.0, timeout_seconds - (monotonic() - started))
                if threads is not None:
                    model.Params.Threads = int(threads)
                model.optimize()
            except gp.GurobiError as error:
                if _is_license_error(error):
                    return make_result(
                        SolutionStatus.UNAVAILABLE,
                        metadata={"reason": f"Gurobi license unavailable: {error}"},
                        bound=lower,
                    )
                raise RuntimeError(f"Gurobi model or optimization failed: {error}") from error

            try:
                version_str = ".".join(map(str, gp.gurobi.version()))
            except Exception:
                version_str = "gurobipy"

            code = model.Status
            metadata: dict[str, object] = {
                "gurobi_status": int(code),
                "solver_version": version_str,
                "symmetry_breaking": symmetry_breaking,
                "anchor_vertex": anchor,
                "threads": threads,
            }
            if model.SolCount:
                candidate = {
                    vertex: max(positions, key=lambda p: x[vertex, p].X)
                    for vertex in graph.vertices
                }
                report = validate_assignment(graph, candidate)
                if not report.valid or report.actual_bandwidth is None:
                    raise RuntimeError(f"Gurobi returned an invalid assignment: {report.errors}")
                if report.actual_bandwidth < best_bandwidth:
                    best_assignment = candidate
                    best_bandwidth = report.actual_bandwidth

            bound = lower
            for key, getter in (
                ("best_bound", lambda: model.ObjBound),
                ("mip_gap", lambda: model.MIPGap),
            ):
                try:
                    value = float(getter())
                except (AttributeError, gp.GurobiError):
                    continue
                if math.isfinite(value):
                    metadata[key] = value
                    if key == "best_bound":
                        bound = max(lower, min(best_bandwidth, math.ceil(value - 1e-6)))

            if code == gp.GRB.OPTIMAL:
                return make_result(SolutionStatus.OPTIMAL, metadata=metadata, bound=best_bandwidth)
            if code == gp.GRB.TIME_LIMIT:
                return make_result(SolutionStatus.TIMEOUT, metadata=metadata, bound=bound)
            if code in (gp.GRB.INFEASIBLE, gp.GRB.INF_OR_UNBD):
                return make_result(SolutionStatus.INFEASIBLE, metadata=metadata, bound=bound)
            non_optimal_statuses = tuple(
                getattr(gp.GRB, name)
                for name in (
                    "INTERRUPTED",
                    "ITERATION_LIMIT",
                    "NODE_LIMIT",
                    "SOLUTION_LIMIT",
                    "WORK_LIMIT",
                    "MEM_LIMIT",
                    "USER_OBJ_LIMIT",
                )
                if hasattr(gp.GRB, name)
            )
            if code in non_optimal_statuses:
                status = SolutionStatus.FEASIBLE if model.SolCount > 0 else SolutionStatus.UNKNOWN
                return make_result(status, metadata=metadata, bound=bound)
            raise RuntimeError(f"Gurobi ended with unexpected status {code}")
        finally:
            if model is not None:
                try:
                    model.dispose()
                except Exception:
                    pass
            if environment is not None:
                try:
                    environment.dispose()
                except Exception:
                    pass


__all__ = ["GurobiMIPSolver"]
