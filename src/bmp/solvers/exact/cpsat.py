"""Exact BMP with Google OR-Tools CP-SAT."""

from __future__ import annotations

import math
from dataclasses import dataclass
from math import floor
from time import monotonic
from typing import Mapping

from bmp.core.graph import Graph
from bmp.core.solution import SolutionStatus, SolverResult
from bmp.core.validation import validate_solution
from bmp.solvers.exact._common import prepare_cp_hints, run_cp_with_deadline


@dataclass(slots=True)
class CPSATSolver:
    """Solve BMP exactly using Google OR-Tools CP-SAT."""

    seed: int = 0

    def solve(
        self,
        graph: Graph,
        *,
        timeout_seconds: float | None = None,
        symmetry_breaking: bool = False,
        threads: int | None = None,
        seed: int | None = None,
        initial_permutation: Mapping[int, int] | None = None,
        use_lower_bound: bool = True,
        use_initial_upper_bound: bool = True,
        isolate_timeout: bool = False,
    ) -> SolverResult:
        if timeout_seconds is not None and (
            not math.isfinite(timeout_seconds) or timeout_seconds < 0
        ):
            raise ValueError("timeout_seconds must be finite and non-negative")
        if threads is not None and threads < 1:
            raise ValueError("threads must be at least 1")

        active_seed = self.seed if seed is None else int(seed)
        certified_lb, model_lb, model_ub, hint_perm, anchor, reversed_hint = prepare_cp_hints(
            graph,
            symmetry_breaking=symmetry_breaking,
            initial_permutation=initial_permutation,
            use_lower_bound=use_lower_bound,
            use_initial_upper_bound=use_initial_upper_bound,
        )

        def _execute() -> SolverResult:
            total_started = monotonic()
            name = "cp-sat"
            base_meta: dict[str, object] = {
                "seed": active_seed,
                "symmetry_breaking": symmetry_breaking,
                "anchor_vertex": anchor,
                "threads": 1 if threads is None else int(threads),
                "certified_graph_lower_bound": certified_lb,
                "model_lower_bound": model_lb,
                "model_upper_bound": model_ub,
                "use_lower_bound": use_lower_bound,
                "use_initial_upper_bound": use_initial_upper_bound,
                "hint_provided": hint_perm is not None,
                "hint_reversed_for_symmetry": reversed_hint,
                "incumbent_source": name,
            }

            import_started = monotonic()
            try:
                import ortools
                from ortools.sat.python import cp_model
            except ImportError as exc:
                return SolverResult(
                    instance=graph.name,
                    method="CP",
                    solver=name,
                    status=SolutionStatus.UNAVAILABLE,
                    runtime_seconds=monotonic() - total_started,
                    lower_bound=certified_lb,
                    metadata={**base_meta, "reason": str(exc)},
                )
            import_time_s = monotonic() - import_started
            base_meta["solver_version"] = getattr(ortools, "__version__", "unknown")
            base_meta["import_time_s"] = round(import_time_s, 6)

            if timeout_seconds == 0:
                return SolverResult(
                    instance=graph.name,
                    method="CP",
                    solver=name,
                    status=SolutionStatus.TIMEOUT,
                    runtime_seconds=monotonic() - total_started,
                    lower_bound=certified_lb,
                    metadata={
                        **base_meta,
                        "native_status": "NOT_RUN",
                        "reason": "zero time limit",
                        "model_construction_time_s": 0.0,
                        "engine_init_time_s": 0.0,
                        "solver_time_s": 0.0,
                    },
                )

            solve_budget_started = monotonic()
            model_started = monotonic()
            model = cp_model.CpModel()
            positions = {
                v: model.new_int_var(1, graph.order, f"p_{v}") for v in graph.vertices
            }
            num_vars = len(positions) + 1
            num_constrs = 0

            if positions:
                model.add_all_different(positions.values())
                num_constrs += 1
            if symmetry_breaking and anchor is not None and graph.order >= 2:
                cutoff = (graph.order + 1) // 2
                model.add(positions[anchor] <= cutoff)
                num_constrs += 1

            bandwidth = model.new_int_var(model_lb, model_ub, "B")
            # Hai bất đẳng thức tuyến tính tương đương |p_u - p_v| <= B.
            for u, v in sorted(graph.edges):
                model.add(positions[u] - positions[v] <= bandwidth)
                model.add(positions[v] - positions[u] <= bandwidth)
                num_constrs += 2

            if hint_perm is not None and positions:
                for v, pos_var in positions.items():
                    model.add_hint(pos_var, hint_perm[v])
                hint_bw = max(
                    (abs(hint_perm[u] - hint_perm[v]) for u, v in graph.edges),
                    default=0,
                )
                model.add_hint(bandwidth, max(model_lb, min(model_ub, hint_bw)))

            model.minimize(bandwidth)
            model_construction_time_s = monotonic() - model_started

            init_started = monotonic()
            solver = cp_model.CpSolver()
            solver.parameters.num_search_workers = 1 if threads is None else int(threads)
            solver.parameters.random_seed = active_seed
            engine_init_time_s = monotonic() - init_started

            if timeout_seconds is not None:
                remaining = timeout_seconds - (monotonic() - solve_budget_started)
                if remaining <= 0:
                    return SolverResult(
                        instance=graph.name,
                        method="CP",
                        solver=name,
                        status=SolutionStatus.TIMEOUT,
                        runtime_seconds=monotonic() - total_started,
                        lower_bound=certified_lb,
                        metadata={
                            **base_meta,
                            "native_status": "NOT_RUN",
                            "reason": "time limit exhausted during model construction",
                            "model_variables": num_vars,
                            "model_constraints": num_constrs,
                            "model_construction_time_s": round(model_construction_time_s, 6),
                            "engine_init_time_s": round(engine_init_time_s, 6),
                            "solver_time_s": 0.0,
                        },
                    )
                solver.parameters.max_time_in_seconds = remaining

            solve_started = monotonic()
            native = solver.solve(model)
            solver_time_s = monotonic() - solve_started

            status_map = {
                cp_model.OPTIMAL: SolutionStatus.OPTIMAL,
                cp_model.FEASIBLE: SolutionStatus.FEASIBLE,
                cp_model.INFEASIBLE: SolutionStatus.INFEASIBLE,
                cp_model.UNKNOWN: (
                    SolutionStatus.TIMEOUT
                    if timeout_seconds is not None
                    else SolutionStatus.ERROR
                ),
            }
            model_invalid_code = getattr(cp_model, "MODEL_INVALID", None)
            if model_invalid_code is not None:
                status_map[model_invalid_code] = SolutionStatus.ERROR
            status = status_map.get(native, SolutionStatus.ERROR)

            metadata: dict[str, object] = {
                **base_meta,
                "native_status": solver.status_name(native),
                "model_variables": num_vars,
                "model_constraints": num_constrs,
                "model_construction_time_s": round(model_construction_time_s, 6),
                "engine_init_time_s": round(engine_init_time_s, 6),
                "solver_time_s": round(solver_time_s, 6),
                "ortools_wall_time_s": round(float(solver.wall_time), 6),
                "ortools_user_time_s": round(float(solver.user_time), 6),
                "num_branches": int(solver.num_branches),
                "num_conflicts": int(solver.num_conflicts),
            }
            if status is SolutionStatus.ERROR:
                metadata["reason"] = f"CP-SAT returned native status {solver.status_name(native)}"

            lower_bound: int | None = None
            if status in (
                SolutionStatus.OPTIMAL,
                SolutionStatus.FEASIBLE,
                SolutionStatus.TIMEOUT,
            ):
                best_bound = solver.best_objective_bound
                metadata["native_best_bound"] = best_bound
                if math.isfinite(best_bound):
                    rounded = max(0, floor(best_bound + 1e-7))
                    lower_bound = max(model_lb, rounded)
                else:
                    lower_bound = model_lb

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
                        runtime_seconds=monotonic() - total_started,
                        lower_bound=certified_lb,
                        metadata=metadata,
                    )
                value = certificate.actual_bandwidth
                safe_lb = (
                    value
                    if status is SolutionStatus.OPTIMAL
                    else min(value, model_lb if lower_bound is None else lower_bound)
                )
                return SolverResult(
                    instance=graph.name,
                    method="CP",
                    solver=name,
                    status=status,
                    runtime_seconds=monotonic() - total_started,
                    encoding_time_s=model_construction_time_s,
                    solving_time_s=solver_time_s,
                    num_variables=num_vars,
                    num_clauses=num_constrs,
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
                runtime_seconds=monotonic() - total_started,
                encoding_time_s=model_construction_time_s,
                solving_time_s=solver_time_s,
                num_variables=num_vars,
                num_clauses=num_constrs,
                lower_bound=lower_bound,
                metadata=metadata,
            )

        if isolate_timeout and timeout_seconds is not None and timeout_seconds > 0:
            return run_cp_with_deadline(
                _execute,
                graph=graph,
                solver_name="cp-sat",
                timeout_seconds=timeout_seconds,
                certified_lb=certified_lb,
                base_metadata={
                    "seed": active_seed,
                    "symmetry_breaking": symmetry_breaking,
                    "anchor_vertex": anchor,
                },
            )
        return _execute()


__all__ = ["CPSATSolver"]
