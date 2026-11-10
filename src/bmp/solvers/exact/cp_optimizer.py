"""Exact BMP with the optional IBM CP Optimizer local executable."""

from dataclasses import dataclass
from shutil import which
from time import monotonic

from bmp.core.graph import Graph
from bmp.core.solution import BMPSolution, SolutionStatus
from bmp.core.validation import validate_assignment


def _build_model(graph: Graph):
    from docplex.cp.model import CpoModel

    model = CpoModel()
    positions = {
        v: model.integer_var(1, graph.order, f"p_{i}")
        for i, v in enumerate(graph.vertices)
    }
    if positions:
        model.add(model.all_diff(list(positions.values())))
    bandwidth = model.integer_var(0, max(0, graph.order - 1), "B")
    # AllDiff trên miền 1..n tạo song ánh. B chặn độ dài mọi cạnh.
    for u, v in sorted(graph.edges):
        model.add(model.abs(positions[u] - positions[v]) <= bandwidth)
    model.add(model.minimize(bandwidth))
    return model, positions


@dataclass(slots=True)
class CPOptimizerSolver:
    executable: str = "cpoptimizer"

    def solve(
        self, graph: Graph, *, timeout_seconds: float | None = None
    ) -> BMPSolution:
        if timeout_seconds is not None and timeout_seconds < 0:
            raise ValueError("timeout_seconds cannot be negative")
        started = monotonic()
        name = "cp-optimizer"
        try:
            from docplex.cp.solution import STOP_CAUSE_LIMIT
            from docplex.cp.utils import CpoException

            model, positions = _build_model(graph)
        except ImportError as exc:
            return BMPSolution(
                SolutionStatus.UNAVAILABLE,
                name,
                monotonic() - started,
                metadata={"reason": str(exc)},
            )

        executable = which(self.executable)
        if executable is None:
            return BMPSolution(
                SolutionStatus.UNAVAILABLE,
                name,
                monotonic() - started,
                metadata={"reason": f"Executable not found: {self.executable}"},
            )
        options = {
            "agent": "local",
            "execfile": executable,
            "LogVerbosity": "Quiet",
            "Workers": 1,
        }
        if timeout_seconds is not None:
            remaining = timeout_seconds - (monotonic() - started)
            if remaining <= 0:
                return BMPSolution(SolutionStatus.TIMEOUT, name, monotonic() - started)
            options["TimeLimit"] = remaining
        try:
            with model.create_solver(**options) as solver:
                result = solver.solve()
        except (CpoException, OSError) as exc:
            reason = str(exc)
            runtime_missing = isinstance(exc, OSError) or any(
                marker in reason.lower()
                for marker in ("executable", "license", "licence", "execfile")
            )
            status = (
                SolutionStatus.UNAVAILABLE if runtime_missing else SolutionStatus.ERROR
            )
            return BMPSolution(
                status, name, monotonic() - started, metadata={"reason": reason}
            )

        native = result.get_solve_status()
        stop = result.get_stop_cause()
        metadata = {"native_status": native, "stop_cause": stop}
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
                lower_bound=value if status is SolutionStatus.OPTIMAL else None,
                metadata=metadata,
            )
        return BMPSolution(status, name, monotonic() - started, metadata=metadata)
