"""Incremental SAT solver for Bandwidth Minimization Problem."""

from __future__ import annotations

from time import monotonic
from typing import Callable, Literal, Mapping

from bmp.core.graph import Graph
from bmp.core.solution import SolutionStatus, SolverResult
from bmp.core.validation import calculate_bandwidth
from bmp.encodings.base import BMPEncoder
from bmp.encodings.estimator import (
    ResourceLimits,
    estimate_for_encoder,
    estimate_incremental_for_encoder,
)
from bmp.encodings.pairwise import PairwiseEncoding
from bmp.solvers.sat.backends.base import get_sat_backend
from bmp.solvers.sat.search import (
    compute_initial_upper_bound,
    compute_lower_bound,
    solve_sat_with_decomposition,
)
from bmp.solvers.sat.worker import emit_incumbent, report_progress, report_sat_event


class IncrementalSATSolver:
    """Incremental SAT solver maintaining a persistent SAT backend across thresholds.

    Supports:
      - ``search_mode="linear"`` (default): monotonic descending tightening
        with ``threshold_policy`` in ``("adaptive", "unit")``.
      - ``search_mode="binary"``: exact incremental binary search using per-step
        activation assumptions (positive lock on SAT, negative disable on UNSAT).
    """

    def __init__(
        self,
        encoder: BMPEncoder | None = None,
        *,
        backend_name: str = "cadical",
        threshold_policy: Literal["adaptive", "unit"] = "adaptive",
        search_mode: Literal["linear", "binary"] = "linear",
        init_mode: str = "rcm",
        decompose_components: bool = False,
    ) -> None:
        self.encoder = encoder if encoder is not None else PairwiseEncoding()
        self.backend_name = backend_name
        self.threshold_policy = threshold_policy
        if threshold_policy not in ("adaptive", "unit"):
            raise ValueError("threshold_policy must be 'adaptive' or 'unit'")
        self.search_mode = search_mode.lower()
        if self.search_mode not in ("linear", "binary"):
            raise ValueError("search_mode must be 'linear' or 'binary'")
        self.init_mode = init_mode
        self.decompose_components = bool(decompose_components)

    def _clone_non_decomposed(self) -> IncrementalSATSolver:
        return IncrementalSATSolver(
            self.encoder,
            backend_name=self.backend_name,
            threshold_policy=self.threshold_policy,  # type: ignore[arg-type]
            search_mode=self.search_mode,  # type: ignore[arg-type]
            init_mode=self.init_mode,
            decompose_components=False,
        )

    @property
    def _strategy_label(self) -> str:
        return "incremental_binary" if self.search_mode == "binary" else "incremental"

    def solve(
        self,
        graph: Graph,
        *,
        timeout_seconds: float | None = None,
        heuristic_permutation: Mapping[int, int] | None = None,
        symmetry_breaking: bool = False,
        limits: ResourceLimits | None = None,
        on_incumbent: Callable[[Mapping[int, int], int], None] | None = None,
    ) -> SolverResult:
        started = monotonic()
        n = graph.order

        effective_timeout = (
            timeout_seconds if timeout_seconds is not None else (limits.timeout_seconds if limits else None)
        )
        limits = limits if limits is not None else ResourceLimits(timeout_seconds=None)
        if effective_timeout is not None or limits.memory_limit_mb is not None:
            from bmp.solvers.sat.worker import run_bounded_solver

            return run_bounded_solver(
                self,
                graph,
                timeout_seconds=effective_timeout if effective_timeout is not None else 300.0,
                heuristic_permutation=heuristic_permutation,
                symmetry_breaking=symmetry_breaking,
                limits=limits,
                on_incumbent=on_incumbent,
            )

        if self.decompose_components:
            return solve_sat_with_decomposition(  # type: ignore[return-value]
                self,
                graph,
                strategy_label=self._strategy_label,
                timeout_seconds=None,
                heuristic_permutation=heuristic_permutation,
                symmetry_breaking=symmetry_breaking,
                limits=limits,
            )

        # Base case: edgeless or order <= 1
        if n <= 1 or not graph.edges:
            identity_perm = {v: i + 1 for i, v in enumerate(graph.vertices)}
            emit_incumbent(graph, identity_perm, 0, on_incumbent=on_incumbent, last_key=None)
            return SolverResult(
                instance=graph.name,
                method="SAT",
                solver=self.backend_name,
                encoding=self.encoder.name,
                strategy=self._strategy_label,
                status=SolutionStatus.OPTIMAL,
                bandwidth=0,
                permutation=identity_perm,
                runtime_s=monotonic() - started,
                encoding_time_s=0.0,
                solving_time_s=0.0,
                num_variables=0,
                num_clauses=0,
                sat_calls=0,
                lower_bound=0,
                upper_bound=0,
                metadata={
                    "symmetry_breaking": symmetry_breaking,
                    "fast_path": "edgeless",
                    "sat_solved_any": False,
                    "incumbent_source": "edgeless",
                },
            )

        lb = compute_lower_bound(graph)
        ub, init_perm = compute_initial_upper_bound(
            graph,
            heuristic_permutation,
            symmetry_breaking=symmetry_breaking,
            init_mode=self.init_mode,
        )
        initial_source = "heuristic" if heuristic_permutation is not None else "initial"

        if lb == ub:
            emit_incumbent(graph, init_perm, ub, on_incumbent=on_incumbent, last_key=None)
            return SolverResult(
                instance=graph.name,
                method="SAT",
                solver=self.backend_name,
                encoding=self.encoder.name,
                strategy=self._strategy_label,
                status=SolutionStatus.OPTIMAL,
                bandwidth=ub,
                permutation=init_perm,
                runtime_s=monotonic() - started,
                encoding_time_s=0.0,
                solving_time_s=0.0,
                num_variables=0,
                num_clauses=0,
                sat_calls=0,
                lower_bound=lb,
                upper_bound=ub,
                metadata={
                    "symmetry_breaking": symmetry_breaking,
                    "fast_path": "lb_equals_ub",
                    "sat_solved_any": False,
                    "incumbent_source": initial_source,
                },
            )

        if limits is not None:
            estimate = estimate_for_encoder(
                self.encoder,
                graph,
                k=ub - 1,
                symmetry_breaking=symmetry_breaking,
            )
            is_ok, reason = limits.check(estimate)
            if not is_ok:
                return SolverResult(
                    instance=graph.name,
                    method="SAT",
                    solver=self.backend_name,
                    encoding=self.encoder.name,
                    strategy=self._strategy_label,
                    status=SolutionStatus.SKIPPED,
                    bandwidth=ub,
                    permutation=init_perm,
                    runtime_s=monotonic() - started,
                    encoding_time_s=0.0,
                    solving_time_s=0.0,
                    num_variables=None,
                    num_clauses=None,
                    sat_calls=0,
                    lower_bound=lb,
                    upper_bound=ub,
                    metadata={
                        "skipped_reason": reason,
                        "estimate": estimate.to_dict(),
                        "symmetry_breaking": symmetry_breaking,
                        "sat_solved_any": False,
                        "incumbent_source": initial_source,
                    },
                )

        best_bandwidth = ub
        best_permutation: dict[int, int] | None = dict(init_perm) if init_perm else None
        incumbent_source = initial_source
        last_key = emit_incumbent(
            graph,
            best_permutation,
            best_bandwidth,
            on_incumbent=on_incumbent,
            last_key=None,
        )
        certified_lb = lb
        sat_calls = 0
        total_encoding_time = 0.0
        total_solving_time = 0.0
        timed_out = False
        resource_reason: str | None = None
        sat_solved_any = False
        fixed_clauses = 0
        added_clauses = 0
        accumulated_clauses = 0
        total_variables = 0

        report_progress(
            self,
            bandwidth=best_bandwidth,
            permutation=best_permutation,
            lower_bound=certified_lb,
            sat_calls=0,
            sat_solved_any=False,
            incumbent_source=incumbent_source,
        )

        backend = get_sat_backend(self.backend_name)
        try:
            enc_start = monotonic()
            fixed_formula = self.encoder.encode_fixed(graph, symmetry_breaking=symmetry_breaking)
            total_encoding_time += monotonic() - enc_start

            backend.append_formula(fixed_formula.clauses)
            accumulated_clauses = len(fixed_formula.clauses)
            fixed_clauses = accumulated_clauses
            total_variables = fixed_formula.num_variables

            if self.search_mode == "binary":
                low = certified_lb
                high = best_bandwidth - 1
                next_act_var = total_variables + 1
                while low <= high:
                    if effective_timeout is not None and (monotonic() - started) >= effective_timeout:
                        timed_out = True
                        break
                    mid = (low + high) // 2
                    step_est = estimate_for_encoder(
                        self.encoder,
                        graph,
                        k=mid,
                        symmetry_breaking=symmetry_breaking,
                    )
                    projected_clauses = accumulated_clauses + step_est.num_bandwidth_clauses + 1
                    projected_vars = max(total_variables, step_est.num_variables) + 1
                    if limits.max_variables is not None and projected_vars > limits.max_variables:
                        resource_reason = (
                            f"Estimated variables ({projected_vars:,}) exceeds safety limit ({limits.max_variables:,})"
                        )
                        break
                    if limits.max_clauses is not None and projected_clauses > limits.max_clauses:
                        resource_reason = (
                            f"Estimated clauses ({projected_clauses:,}) exceeds safety limit ({limits.max_clauses:,})"
                        )
                        break

                    enc_start = monotonic()
                    raw_bw_clauses = self.encoder.encode_bandwidth_step(graph, mid)
                    act_var = next_act_var
                    next_act_var += 1
                    total_variables = next_act_var - 1
                    guarded_clauses = [[-act_var, *cl] for cl in raw_bw_clauses]
                    total_encoding_time += monotonic() - enc_start

                    backend.append_formula(guarded_clauses)
                    accumulated_clauses += len(guarded_clauses)
                    added_clauses += len(guarded_clauses)

                    report_progress(
                        self,
                        bandwidth=best_bandwidth,
                        permutation=best_permutation,
                        lower_bound=certified_lb,
                        sat_calls=sat_calls,
                        encoding_time_s=total_encoding_time,
                        solving_time_s=total_solving_time,
                        num_variables=total_variables,
                        num_clauses=accumulated_clauses,
                        initial_clauses=fixed_clauses,
                        added_clauses=added_clauses,
                        sat_solved_any=sat_solved_any,
                        incumbent_source="sat" if sat_solved_any else incumbent_source,
                    )

                    solve_start = monotonic()
                    report_sat_event(self, k=mid, outcome="STARTED")
                    sat_calls += 1
                    remaining = None if effective_timeout is None else effective_timeout - (monotonic() - started)
                    is_sat = backend.solve_with_timeout(remaining, assumptions=[act_var])
                    solve_time = monotonic() - solve_start
                    total_solving_time += solve_time
                    if is_sat is None:
                        report_sat_event(self, k=mid, outcome="UNKNOWN", solve_time_s=solve_time)
                        timed_out = True
                        break

                    if is_sat:
                        model = backend.get_model()
                        if model is None:
                            raise RuntimeError(f"Solver returned SAT but model is None for k={mid}")
                        decoded = self.encoder.decode(graph, model, mid)
                        actual_bw = calculate_bandwidth(graph, decoded)
                        sat_solved_any = True
                        report_sat_event(self, k=mid, outcome="SAT", solve_time_s=solve_time, bandwidth=actual_bw)
                        if actual_bw <= best_bandwidth:
                            best_bandwidth = actual_bw
                            best_permutation = decoded
                            incumbent_source = "sat"
                            last_key = emit_incumbent(
                                graph,
                                best_permutation,
                                best_bandwidth,
                                on_incumbent=on_incumbent,
                                last_key=last_key,
                            )
                        backend.add_clause([act_var])
                        accumulated_clauses += 1
                        added_clauses += 1
                        high = min(mid - 1, best_bandwidth - 1)
                    else:
                        report_sat_event(self, k=mid, outcome="UNSAT", solve_time_s=solve_time)
                        backend.add_clause([-act_var])
                        accumulated_clauses += 1
                        added_clauses += 1
                        low = mid + 1
                        certified_lb = max(certified_lb, low)

                    report_progress(
                        self,
                        bandwidth=best_bandwidth,
                        permutation=best_permutation,
                        lower_bound=certified_lb,
                        sat_calls=sat_calls,
                        encoding_time_s=total_encoding_time,
                        solving_time_s=total_solving_time,
                        num_variables=total_variables,
                        num_clauses=accumulated_clauses,
                        initial_clauses=fixed_clauses,
                        added_clauses=added_clauses,
                        sat_solved_any=sat_solved_any,
                        incumbent_source=incumbent_source,
                    )
            else:
                k_curr = best_bandwidth - 1
                enc_start = monotonic()
                bw_clauses = self.encoder.encode_bandwidth_step(graph, k_curr)
                total_encoding_time += monotonic() - enc_start

                backend.append_formula(bw_clauses)
                accumulated_clauses += len(bw_clauses)
                added_clauses += len(bw_clauses)
                initial_k = k_curr
                report_progress(
                    self,
                    bandwidth=best_bandwidth,
                    permutation=best_permutation,
                    lower_bound=certified_lb,
                    sat_calls=0,
                    encoding_time_s=total_encoding_time,
                    solving_time_s=total_solving_time,
                    num_variables=total_variables,
                    num_clauses=accumulated_clauses,
                    initial_clauses=fixed_clauses,
                    added_clauses=added_clauses,
                    sat_solved_any=False,
                    incumbent_source=incumbent_source,
                )

                while k_curr >= certified_lb:
                    if effective_timeout is not None and (monotonic() - started) >= effective_timeout:
                        timed_out = True
                        break

                    solve_start = monotonic()
                    report_sat_event(self, k=k_curr, outcome="STARTED")
                    sat_calls += 1
                    remaining = None if effective_timeout is None else effective_timeout - (monotonic() - started)
                    is_sat = backend.solve_with_timeout(remaining)
                    solve_time = monotonic() - solve_start
                    total_solving_time += solve_time
                    if is_sat is None:
                        report_sat_event(self, k=k_curr, outcome="UNKNOWN", solve_time_s=solve_time)
                        timed_out = True
                        break

                    if is_sat:
                        model = backend.get_model()
                        if model is None:
                            raise RuntimeError(f"Solver returned SAT but model is None for k={k_curr}")
                        decoded = self.encoder.decode(graph, model, k_curr)
                        actual_bw = calculate_bandwidth(graph, decoded)
                        sat_solved_any = True
                        report_sat_event(self, k=k_curr, outcome="SAT", solve_time_s=solve_time, bandwidth=actual_bw)
                        if actual_bw <= best_bandwidth:
                            best_bandwidth = actual_bw
                            best_permutation = decoded
                            incumbent_source = "sat"
                            last_key = emit_incumbent(
                                graph,
                                best_permutation,
                                best_bandwidth,
                                on_incumbent=on_incumbent,
                                last_key=last_key,
                            )
                        report_progress(
                            self,
                            bandwidth=best_bandwidth,
                            permutation=best_permutation,
                            lower_bound=certified_lb,
                            sat_calls=sat_calls,
                            encoding_time_s=total_encoding_time,
                            solving_time_s=total_solving_time,
                            num_variables=total_variables,
                            num_clauses=accumulated_clauses,
                            initial_clauses=fixed_clauses,
                            added_clauses=added_clauses,
                            sat_solved_any=sat_solved_any,
                            incumbent_source=incumbent_source,
                        )

                        if best_bandwidth <= certified_lb:
                            certified_lb = best_bandwidth
                            break

                        k_next = k_curr - 1 if self.threshold_policy == "unit" else best_bandwidth - 1
                        if k_next < certified_lb:
                            certified_lb = best_bandwidth
                            break

                        next_estimate = estimate_incremental_for_encoder(
                            self.encoder,
                            graph,
                            initial_k=initial_k,
                            target_k=k_next,
                            symmetry_breaking=symmetry_breaking,
                            search_mode="linear",
                        )
                        _, resource_reason = limits.check(next_estimate)
                        if resource_reason:
                            break
                        if effective_timeout is not None and monotonic() - started >= effective_timeout:
                            timed_out = True
                            break

                        enc_start = monotonic()
                        if isinstance(self.encoder, PairwiseEncoding):
                            new_clauses = self.encoder.encode_bandwidth_diff(graph, k_next, k_curr)
                        else:
                            new_clauses = self.encoder.encode_bandwidth_step(graph, k_next)
                        total_encoding_time += monotonic() - enc_start

                        backend.append_formula(new_clauses)
                        accumulated_clauses += len(new_clauses)
                        added_clauses += len(new_clauses)
                        k_curr = k_next
                    else:
                        report_sat_event(self, k=k_curr, outcome="UNSAT", solve_time_s=solve_time)
                        certified_lb = k_curr + 1
                        report_progress(
                            self,
                            bandwidth=best_bandwidth,
                            permutation=best_permutation,
                            lower_bound=certified_lb,
                            sat_calls=sat_calls,
                            encoding_time_s=total_encoding_time,
                            solving_time_s=total_solving_time,
                            num_variables=total_variables,
                            num_clauses=accumulated_clauses,
                            initial_clauses=fixed_clauses,
                            added_clauses=added_clauses,
                            sat_solved_any=sat_solved_any,
                            incumbent_source=incumbent_source,
                        )
                        break

        finally:
            backend.delete()

        runtime = monotonic() - started
        status = SolutionStatus.OPTIMAL
        if resource_reason:
            status = SolutionStatus.SKIPPED
        elif timed_out:
            status = SolutionStatus.TIMEOUT
        elif best_bandwidth is not None and certified_lb == best_bandwidth:
            status = SolutionStatus.OPTIMAL
        elif best_permutation is not None and certified_lb < best_bandwidth:
            status = SolutionStatus.FEASIBLE

        return SolverResult(
            instance=graph.name,
            method="SAT",
            solver=self.backend_name,
            encoding=self.encoder.name,
            strategy=self._strategy_label,
            status=status,
            bandwidth=best_bandwidth,
            permutation=best_permutation,
            runtime_s=runtime,
            encoding_time_s=total_encoding_time,
            solving_time_s=total_solving_time,
            num_variables=total_variables,
            num_clauses=accumulated_clauses,
            sat_calls=sat_calls,
            lower_bound=certified_lb,
            upper_bound=best_bandwidth,
            metadata={
                "symmetry_breaking": symmetry_breaking,
                "threshold_policy": self.threshold_policy,
                "search_mode": self.search_mode,
                "initial_clauses": fixed_clauses,
                "added_clauses": added_clauses,
                "incumbent_source": incumbent_source,
                "sat_solved_any": sat_solved_any,
                "timed_out": timed_out,
                "skipped_reason": resource_reason,
            },
        )


__all__ = ["IncrementalSATSolver"]
