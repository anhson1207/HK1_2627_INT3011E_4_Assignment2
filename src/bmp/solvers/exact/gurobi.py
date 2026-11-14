"""Optional Gurobi mixed-integer model for graph bandwidth minimization."""

from __future__ import annotations

import math
from dataclasses import dataclass
from time import monotonic
from typing import Callable

from bmp.core.bounds import degree_lower_bound, identity_upper_bound
from bmp.core.graph import Graph
from bmp.core.solution import BMPSolution, SolutionStatus
from bmp.core.validation import validate_assignment


def _is_license_error(error: Exception) -> bool:
    return any(
        word in str(error).lower()
        for word in ("license", "licence", "credential")
    )


@dataclass(slots=True)
class GurobiMIPSolver:
    """Solve BMP with a permutation assignment and edge-span constraints."""

    def solve(
        self, graph: Graph, *, timeout_seconds: float | None = None,
        symmetry_breaking: bool = False,
        on_stage: Callable[[str], None] | None = None,
    ) -> BMPSolution:
        if timeout_seconds is not None and (not math.isfinite(timeout_seconds) or timeout_seconds < 0):
            raise ValueError("timeout_seconds must be finite and non-negative")

        started = monotonic()
        lower = degree_lower_bound(graph)
        best_bandwidth, best_assignment = identity_upper_bound(graph)

        def result(status: SolutionStatus, *, metadata: dict[str, object], bound: int) -> BMPSolution:
            report = validate_assignment(graph, best_assignment, claimed_bandwidth=best_bandwidth)
            if not report.valid:
                raise RuntimeError(f"Gurobi assignment failed validation: {report.errors}")
            return BMPSolution(
                status=status,
                solver="gurobi",
                runtime_seconds=monotonic() - started,
                assignment=best_assignment,
                bandwidth=report.actual_bandwidth,
                lower_bound=bound,
                upper_bound=report.actual_bandwidth,
                metadata=metadata,
            )

        try:
            import gurobipy as gp
        except ImportError as error:
            return result(
                SolutionStatus.UNAVAILABLE,
                metadata={"reason": f"gurobipy is unavailable: {error}"},
                bound=lower,
            )

        try:
            if on_stage:
                on_stage("initializing")
            environment = gp.Env(empty=True)
            environment.setParam("OutputFlag", 0)
            environment.start()
            model = gp.Model("bandwidth_minimization", env=environment)
        except gp.GurobiError as error:
            message = str(error)
            if _is_license_error(error):
                return result(
                    SolutionStatus.UNAVAILABLE,
                    metadata={"reason": f"Gurobi license unavailable: {message}"},
                    bound=lower,
                )
            raise RuntimeError(f"Gurobi model initialization failed: {message}") from error

        if timeout_seconds == 0:
            return result(
                SolutionStatus.TIMEOUT,
                metadata={"gurobi_status": "NOT_RUN", "reason": "zero time limit"},
                bound=lower,
            )

        n = graph.order
        positions = range(1, n + 1)
        try:
            if on_stage:
                on_stage("building")
            x = model.addVars(graph.vertices, positions, vtype=gp.GRB.BINARY, name="x")
            bandwidth = model.addVar(
                vtype=gp.GRB.INTEGER, lb=lower, ub=best_bandwidth, name="B"
            )
            for vertex in graph.vertices:
                model.addConstr(gp.quicksum(x[vertex, p] for p in positions) == 1)
            for p in positions:
                model.addConstr(gp.quicksum(x[vertex, p] for vertex in graph.vertices) == 1)
            if symmetry_breaking and n >= 2:
                anchor = graph.vertices[0]
                cutoff = (n + 1) // 2
                model.addConstr(gp.quicksum(x[anchor, p] for p in range(cutoff + 1, n + 1)) == 0)
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
            if on_stage:
                on_stage("optimizing")
            model.optimize()
            if on_stage:
                on_stage("finished")
        except gp.GurobiError as error:
            if _is_license_error(error):
                return result(
                    SolutionStatus.UNAVAILABLE,
                    metadata={"reason": f"Gurobi license unavailable: {error}"},
                    bound=lower,
                )
            raise RuntimeError(f"Gurobi model or optimization failed: {error}") from error

        code = model.Status
        metadata: dict[str, object] = {
            "gurobi_status": int(code), "symmetry_breaking": symmetry_breaking,
            "incumbent_origin": "solver" if model.SolCount else "identity_start",
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
            return result(SolutionStatus.OPTIMAL, metadata=metadata, bound=best_bandwidth)
        if code == gp.GRB.TIME_LIMIT:
            return result(SolutionStatus.TIMEOUT, metadata=metadata, bound=bound)
        raise RuntimeError(f"Gurobi ended with unexpected status {code}")
