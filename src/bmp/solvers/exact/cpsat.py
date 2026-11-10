"""Exact BMP with Google OR-Tools CP-SAT."""

from dataclasses import dataclass
from math import floor
from time import monotonic

from bmp.core.graph import Graph
from bmp.core.solution import BMPSolution, SolutionStatus
from bmp.core.validation import validate_assignment


@dataclass(slots=True)
class CPSATSolver:
    seed: int = 0

    def solve(
        self, graph: Graph, *, timeout_seconds: float | None = None
    ) -> BMPSolution:
        if timeout_seconds is not None and timeout_seconds < 0:
            raise ValueError("timeout_seconds cannot be negative")
        started = monotonic()
        name = "cp-sat"
        try:
            from ortools.sat.python import cp_model
        except ImportError as exc:
            return BMPSolution(
                SolutionStatus.UNAVAILABLE,
                name,
                monotonic() - started,
                metadata={"reason": str(exc)},
            )

        model = cp_model.CpModel()
        positions = {
            v: model.new_int_var(1, graph.order, f"p_{v}") for v in graph.vertices
        }
        if positions:
            model.add_all_different(positions.values())
        bandwidth = model.new_int_var(0, max(0, graph.order - 1), "B")
        # Hai bất đẳng thức tuyến tính tương đương |p_u - p_v| <= B.
        for u, v in sorted(graph.edges):
            model.add(positions[u] - positions[v] <= bandwidth)
            model.add(positions[v] - positions[u] <= bandwidth)
        model.minimize(bandwidth)

        solver = cp_model.CpSolver()
        solver.parameters.num_search_workers = 1
        solver.parameters.random_seed = self.seed
        if timeout_seconds is not None:
            solver.parameters.max_time_in_seconds = max(
                0, timeout_seconds - (monotonic() - started)
            )
        native = solver.solve(model)
        status = {
            cp_model.OPTIMAL: SolutionStatus.OPTIMAL,
            cp_model.FEASIBLE: SolutionStatus.FEASIBLE,
            cp_model.INFEASIBLE: SolutionStatus.INFEASIBLE,
            cp_model.UNKNOWN: SolutionStatus.TIMEOUT
            if timeout_seconds is not None
            else SolutionStatus.ERROR,
        }.get(native, SolutionStatus.ERROR)
        metadata = {"native_status": solver.status_name(native), "seed": self.seed}
        lower_bound = None
        if status in (
            SolutionStatus.OPTIMAL,
            SolutionStatus.FEASIBLE,
            SolutionStatus.TIMEOUT,
        ):
            metadata["native_best_bound"] = solver.best_objective_bound
            # Làm tròn xuống để giữ lower bound nguyên bảo thủ.
            lower_bound = max(0, floor(solver.best_objective_bound))
        if status in (SolutionStatus.OPTIMAL, SolutionStatus.FEASIBLE):
            assignment = {
                v: solver.value(position) for v, position in positions.items()
            }
            certificate = validate_assignment(graph, assignment)
            if not certificate.valid:
                metadata["reason"] = "; ".join(certificate.errors)
                return BMPSolution(
                    SolutionStatus.ERROR, name, monotonic() - started, metadata=metadata
                )
            value = certificate.actual_bandwidth
            return BMPSolution(
                status,
                name,
                monotonic() - started,
                assignment=assignment,
                bandwidth=value,
                upper_bound=value,
                lower_bound=value if status is SolutionStatus.OPTIMAL else lower_bound,
                metadata=metadata,
            )
        return BMPSolution(
            status,
            name,
            monotonic() - started,
            lower_bound=lower_bound,
            metadata=metadata,
        )
