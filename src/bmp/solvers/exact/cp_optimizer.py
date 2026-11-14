"""Exact BMP with IBM ILOG CP Optimizer via ``docplex.cp``."""

from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass
from math import floor
from pathlib import Path
from shutil import which
from time import monotonic
from typing import Mapping

from bmp.core.graph import Graph
from bmp.core.solution import SolutionStatus, SolverResult
from bmp.core.validation import validate_solution
from bmp.solvers.exact._common import prepare_cp_hints, run_cp_with_deadline
from bmp.solvers.sat.search import compute_lower_bound, select_anchor_vertex


def _resolve_executable(executable: str) -> str | None:
    """Resolve ``executable`` via PATH or interpreter's sibling bin directory."""
    direct = which(executable)
    if direct is not None:
        return direct
    candidate = Path(sys.executable).parent / executable
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate)
    return None


def _build_model(
    graph: Graph,
    *,
    symmetry_breaking: bool = False,
    lower_bound: int | None = None,
    upper_bound: int | None = None,
    initial_permutation: Mapping[int, int] | None = None,
):
    from docplex.cp.model import CpoModel

    model = CpoModel()
    positions = {
        v: model.integer_var(1, graph.order, f"p_{i}")
        for i, v in enumerate(graph.vertices)
    }
    num_vars = len(positions) + 1
    num_constrs = 0

    if positions:
        model.add(model.all_diff(list(positions.values())))
        num_constrs += 1
    if symmetry_breaking and graph.order >= 2:
        anchor = select_anchor_vertex(graph)
        cutoff = (graph.order + 1) // 2
        model.add(positions[anchor] <= cutoff)
        num_constrs += 1

    lb = compute_lower_bound(graph) if lower_bound is None else lower_bound
    ub = max(0, graph.order - 1) if upper_bound is None else upper_bound
    bandwidth = model.integer_var(lb, max(lb, ub), "B")
    # AllDiff trên miền 1..n tạo song ánh. B chặn độ dài mọi cạnh.
    for u, v in sorted(graph.edges):
        model.add(model.abs(positions[u] - positions[v]) <= bandwidth)
        num_constrs += 1

    if initial_permutation is not None and positions:
        sp = model.create_empty_solution()
        for v, pos_var in positions.items():
            sp[pos_var] = initial_permutation[v]
        hint_bw = max(
            (abs(initial_permutation[u] - initial_permutation[v]) for u, v in graph.edges),
            default=0,
        )
        sp[bandwidth] = max(lb, min(max(lb, ub), hint_bw))
        model.set_starting_point(sp)

    model.add(model.minimize(bandwidth))
    model._bmp_stats = (num_vars, num_constrs)  # type: ignore[attr-defined]
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
            started = monotonic()
            name = "cp-optimizer"
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
                import docplex
                from docplex.cp.solution import STOP_CAUSE_LIMIT
                from docplex.cp.utils import CpoException
            except ImportError as exc:
                return SolverResult(
                    instance=graph.name,
                    method="CP",
                    solver=name,
                    status=SolutionStatus.UNAVAILABLE,
                    runtime_seconds=monotonic() - started,
                    lower_bound=certified_lb,
                    metadata={**base_meta, "reason": str(exc)},
                )
            base_meta["docplex_version"] = getattr(docplex, "__version__", "unknown")
            base_meta["import_time_s"] = round(monotonic() - import_started, 6)

            resolved = _resolve_executable(self.executable)
            if resolved is None:
                return SolverResult(
                    instance=graph.name,
                    method="CP",
                    solver=name,
                    status=SolutionStatus.UNAVAILABLE,
                    runtime_seconds=monotonic() - started,
                    lower_bound=certified_lb,
                    metadata={
                        **base_meta,
                        "reason": f"Executable not found: {self.executable}",
                    },
                )
            base_meta["executable_path"] = resolved

            if timeout_seconds == 0:
                return SolverResult(
                    instance=graph.name,
                    method="CP",
                    solver=name,
                    status=SolutionStatus.TIMEOUT,
                    runtime_seconds=monotonic() - started,
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

            budget_started = monotonic()
            model_started = monotonic()
            model, positions = _build_model(
                graph,
                symmetry_breaking=symmetry_breaking,
                lower_bound=model_lb,
                upper_bound=model_ub,
                initial_permutation=hint_perm,
            )
            model_construction_time_s = monotonic() - model_started
            num_vars, num_constrs = getattr(
                model, "_bmp_stats", (len(positions) + 1, len(graph.edges) + 1)
            )
            base_meta["model_variables"] = num_vars
            base_meta["model_constraints"] = num_constrs
            base_meta["model_construction_time_s"] = round(model_construction_time_s, 6)

            options: dict[str, object] = {
                "agent": "local",
                "execfile": resolved,
                "LogVerbosity": "Quiet",
                "Workers": 1 if threads is None else int(threads),
                "RandomSeed": active_seed,
            }
            if timeout_seconds is not None:
                remaining = timeout_seconds - (monotonic() - budget_started)
                if remaining <= 0:
                    return SolverResult(
                        instance=graph.name,
                        method="CP",
                        solver=name,
                        status=SolutionStatus.TIMEOUT,
                        runtime_seconds=monotonic() - started,
                        lower_bound=certified_lb,
                        metadata={
                            **base_meta,
                            "reason": "time limit exhausted before solve",
                            "engine_init_time_s": 0.0,
                            "solver_time_s": 0.0,
                        },
                    )
                options["TimeLimit"] = remaining

            engine_version = None
            try:
                init_started = monotonic()
                with model.create_solver(**options) as solver:
                    engine_init_time_s = monotonic() - init_started
                    get_ver = getattr(solver, "get_solver_version", None)
                    if get_ver is not None:
                        engine_version = get_ver()
                    solve_started = monotonic()
                    result = solver.solve()
                    solver_time_s = monotonic() - solve_started
            except (CpoException, OSError) as exc:
                reason = str(exc)
                lowered = reason.lower()
                runtime_missing = isinstance(exc, OSError) or any(
                    marker in lowered
                    for marker in (
                        "executable",
                        "license",
                        "licence",
                        "execfile",
                        "not found",
                        "no such file",
                        "community edition",
                        "error1016",
                        "error 1016",
                        "size limit",
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
                    lower_bound=certified_lb,
                    metadata={**base_meta, "reason": reason},
                )

            native = result.get_solve_status()
            stop = result.get_stop_cause()
            fail_status = (
                result.get_fail_status() if hasattr(result, "get_fail_status") else None
            )
            raw_solver_bound = _extract_objective_bound(result)
            solver_lb = (
                max(0, floor(raw_solver_bound + 1e-7))
                if raw_solver_bound is not None
                else None
            )
            infos = (
                dict(result.get_solver_infos() or {})
                if hasattr(result, "get_solver_infos")
                else {}
            )
            peak_mem_bytes = infos.get("PeakMemoryUsage") or infos.get("MemoryUsage")
            engine_peak_mb = (
                round(float(peak_mem_bytes) / (1024 * 1024), 4)
                if isinstance(peak_mem_bytes, (int, float))
                else None
            )

            metadata: dict[str, object] = {
                **base_meta,
                "solver_version": engine_version or "unknown",
                "native_status": native,
                "stop_cause": stop,
                "fail_status": fail_status,
                "native_best_bound": raw_solver_bound,
                "solver_lower_bound": solver_lb,
                "engine_init_time_s": round(engine_init_time_s, 6),
                "solver_time_s": round(solver_time_s, 6),
                "engine_solve_time_s": infos.get("SolveTime"),
                "engine_extraction_time_s": infos.get("ExtractionTime"),
                "engine_peak_memory_mb": engine_peak_mb,
                "num_branches": infos.get("NumberOfBranches"),
                "num_fails": infos.get("NumberOfFails"),
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
                        lower_bound=certified_lb,
                        metadata=metadata,
                    )
                value = certificate.actual_bandwidth
                if status is SolutionStatus.OPTIMAL:
                    effective_lb: int | None = value
                elif solver_lb is not None:
                    effective_lb = min(value, max(model_lb, solver_lb))
                else:
                    effective_lb = model_lb if use_lower_bound else None

                return SolverResult(
                    instance=graph.name,
                    method="CP",
                    solver=name,
                    status=status,
                    runtime_seconds=monotonic() - started,
                    encoding_time_s=model_construction_time_s,
                    solving_time_s=solver_time_s,
                    num_variables=num_vars,
                    num_clauses=num_constrs,
                    permutation=assignment,
                    bandwidth=value,
                    upper_bound=value,
                    lower_bound=effective_lb,
                    metadata=metadata,
                )

            if solver_lb is not None:
                fallback_lb: int | None = max(model_lb, solver_lb)
            else:
                fallback_lb = model_lb if use_lower_bound else None
            return SolverResult(
                instance=graph.name,
                method="CP",
                solver=name,
                status=status,
                runtime_seconds=monotonic() - started,
                encoding_time_s=model_construction_time_s,
                solving_time_s=solver_time_s,
                num_variables=num_vars,
                num_clauses=num_constrs,
                lower_bound=fallback_lb if status is SolutionStatus.TIMEOUT else None,
                metadata=metadata,
            )

        if isolate_timeout and timeout_seconds is not None and timeout_seconds > 0:
            return run_cp_with_deadline(
                _execute,
                graph=graph,
                solver_name="cp-optimizer",
                timeout_seconds=timeout_seconds,
                certified_lb=certified_lb,
                base_metadata={
                    "seed": active_seed,
                    "symmetry_breaking": symmetry_breaking,
                    "anchor_vertex": anchor,
                },
            )
        return _execute()


__all__ = ["CPOptimizerSolver", "_build_model"]
