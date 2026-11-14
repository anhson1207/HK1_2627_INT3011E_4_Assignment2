"""Repeated SAT solver for Bandwidth Minimization Problem."""

from __future__ import annotations

from time import monotonic
from typing import Literal, Mapping

from bmp.core.graph import Graph
from bmp.core.solution import SolutionStatus, SolverResult
from bmp.core.validation import calculate_bandwidth, validate_solution
from bmp.encodings.base import BMPEncoder
from bmp.encodings.estimator import ResourceLimits, estimate_for_encoder
from bmp.encodings.pairwise import PairwiseEncoding
from bmp.solvers.sat.backends.base import get_sat_backend
from bmp.solvers.sat.search import (
    compute_initial_upper_bound,
    compute_lower_bound,
    solve_sat_with_decomposition,
)
from bmp.solvers.sat.worker import report_progress, report_sat_event


class RepeatedSATSolver:
    """Repeated SAT solver that creates a fresh solver for each candidate bandwidth k."""

    def __init__(
        self,
        encoder: BMPEncoder | None = None,
        *,
        backend_name: str = "cadical",
        search_mode: Literal["linear", "binary", "adaptive"] = "linear",
        threshold_policy: Literal["adaptive", "unit"] = "adaptive",
        init_mode: str = "rcm",
        decompose_components: bool = False,
        certify_feasible_with_sat: bool = False,
    ) -> None:
        self.encoder = encoder if encoder is not None else PairwiseEncoding()
        self.backend_name = backend_name
        self.search_mode = search_mode.lower()
        if self.search_mode not in ("linear", "binary", "adaptive"):
            raise ValueError(f"Unknown search mode: {search_mode}. Choose 'linear', 'binary', or 'adaptive'.")
        self.threshold_policy = threshold_policy
        if threshold_policy not in ("adaptive", "unit"):
            raise ValueError("threshold_policy must be 'adaptive' or 'unit'")
        self.init_mode = init_mode
        self.decompose_components = bool(decompose_components)
        self.certify_feasible_with_sat = bool(certify_feasible_with_sat)

    def _clone_non_decomposed(self) -> RepeatedSATSolver:
        return RepeatedSATSolver(
            self.encoder,
            backend_name=self.backend_name,
            search_mode=self.search_mode,  # type: ignore[arg-type]
            threshold_policy=self.threshold_policy,  # type: ignore[arg-type]
            init_mode=self.init_mode,
            decompose_components=False,
            certify_feasible_with_sat=self.certify_feasible_with_sat,
        )

    def solve(
        self,
        graph: Graph,
        *,
        timeout_seconds: float | None = None,
        heuristic_permutation: Mapping[int, int] | None = None,
        symmetry_breaking: bool = False,
        limits: ResourceLimits | None = None,
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
            )

        if self.decompose_components:
            return solve_sat_with_decomposition(  # type: ignore[return-value]
                self,
                graph,
                strategy_label=f"repeated_{self.search_mode}",
                timeout_seconds=None,
                heuristic_permutation=heuristic_permutation,
                symmetry_breaking=symmetry_breaking,
                limits=limits,
            )

        if n <= 1 or not graph.edges:
            identity_perm = {v: i + 1 for i, v in enumerate(graph.vertices)}
            return SolverResult(
                instance=graph.name,
                method="SAT",
                solver=self.backend_name,
                encoding=self.encoder.name,
                strategy=f"repeated_{self.search_mode}",
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
                    "sat_solved_any": False,
                    "incumbent_source": "BOUNDS_OPTIMALITY_CERTIFICATE",
                },
            )

        lb = compute_lower_bound(graph)
        ub, init_perm = compute_initial_upper_bound(
            graph,
            heuristic_permutation,
            symmetry_breaking=symmetry_breaking,
            init_mode=self.init_mode,
        )
        if not validate_solution(graph, init_perm, claimed_bandwidth=ub).valid:
            raise ValueError("Initial upper bound requires a valid permutation on this graph")

        if lb == ub and not self.certify_feasible_with_sat:
            return SolverResult(
                instance=graph.name,
                method="SAT",
                solver=self.backend_name,
                encoding=self.encoder.name,
                strategy=f"repeated_{self.search_mode}",
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
                    "incumbent_source": "BOUNDS_OPTIMALITY_CERTIFICATE",
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
                    strategy=f"repeated_{self.search_mode}",
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
                        "incumbent_source": "HEURISTIC",
                    },
                )

        best_bandwidth = ub
        best_permutation: dict[int, int] | None = dict(init_perm) if init_perm else None
        certified_lb = lb
        sat_calls = 0
        total_encoding_time = 0.0
        total_solving_time = 0.0
        last_num_vars = 0
        last_num_clauses = 0
        timed_out = False
        resource_reason: str | None = None
        sat_solved_any = False
        report_progress(
            self,
            bandwidth=best_bandwidth,
            permutation=best_permutation,
            lower_bound=certified_lb,
            sat_calls=0,
            sat_solved_any=False,
            incumbent_source="HEURISTIC",
        )

        if self.search_mode == "linear":
            k = best_bandwidth - 1
            while k >= certified_lb:
                if effective_timeout is not None and (monotonic() - started) >= effective_timeout:
                    timed_out = True
                    break

                estimate = estimate_for_encoder(
                    self.encoder,
                    graph,
                    k=k,
                    symmetry_breaking=symmetry_breaking,
                )
                _, resource_reason = limits.check(estimate)
                if resource_reason:
                    break

                enc_start = monotonic()
                formula = self.encoder.encode(graph, k, symmetry_breaking=symmetry_breaking)
                total_encoding_time += monotonic() - enc_start
                last_num_vars = formula.num_variables
                last_num_clauses = formula.num_clauses

                backend = get_sat_backend(self.backend_name)
                backend.append_formula(formula.clauses)
                report_progress(
                    self,
                    bandwidth=best_bandwidth,
                    permutation=best_permutation,
                    lower_bound=certified_lb,
                    sat_calls=sat_calls,
                    encoding_time_s=total_encoding_time,
                    solving_time_s=total_solving_time,
                    num_variables=last_num_vars,
                    num_clauses=last_num_clauses,
                    sat_solved_any=sat_solved_any,
                    incumbent_source="SAT" if sat_solved_any else "HEURISTIC",
                )
                report_sat_event(self, k=k, outcome="STARTED")
                sat_calls += 1
                remaining = None if effective_timeout is None else effective_timeout - (monotonic() - started)
                solve_start = monotonic()
                is_sat = backend.solve_with_timeout(remaining)
                solve_time = monotonic() - solve_start
                total_solving_time += solve_time

                if is_sat is None:
                    backend.delete()
                    report_sat_event(self, k=k, outcome="UNKNOWN", solve_time_s=solve_time)
                    timed_out = True
                    break

                if is_sat:
                    model = backend.get_model()
                    backend.delete()
                    if model is None:
                        raise RuntimeError(f"Solver returned SAT but model is None for k={k}")
                    decoded_perm = self.encoder.decode(graph, model, k)
                    actual_bw = calculate_bandwidth(graph, decoded_perm)
                    if not validate_solution(graph, decoded_perm).valid or actual_bw > k:
                        raise RuntimeError(f"Invalid CaDiCaL model at k={k}")
                    sat_solved_any = True
                    report_sat_event(self, k=k, outcome="SAT", solve_time_s=solve_time, bandwidth=actual_bw)
                    best_bandwidth = actual_bw
                    best_permutation = decoded_perm
                    report_progress(
                        self,
                        bandwidth=best_bandwidth,
                        permutation=best_permutation,
                        lower_bound=certified_lb,
                        sat_calls=sat_calls,
                        encoding_time_s=total_encoding_time,
                        solving_time_s=total_solving_time,
                        num_variables=last_num_vars,
                        num_clauses=last_num_clauses,
                        sat_solved_any=sat_solved_any,
                        incumbent_source="SAT",
                    )

                    if best_bandwidth <= certified_lb:
                        certified_lb = best_bandwidth
                        break
                    k = k - 1 if self.threshold_policy == "unit" else best_bandwidth - 1
                else:
                    backend.delete()
                    report_sat_event(self, k=k, outcome="UNSAT", solve_time_s=solve_time)
                    certified_lb = k + 1
                    report_progress(
                        self,
                        bandwidth=best_bandwidth,
                        permutation=best_permutation,
                        lower_bound=certified_lb,
                        sat_calls=sat_calls,
                        encoding_time_s=total_encoding_time,
                        solving_time_s=total_solving_time,
                        num_variables=last_num_vars,
                        num_clauses=last_num_clauses,
                        sat_solved_any=sat_solved_any,
                        incumbent_source="SAT" if sat_solved_any else "HEURISTIC",
                    )
                    break

        elif self.search_mode in ("binary", "adaptive"):
            low = certified_lb
            # Adaptive mode obtains an independently decoded SAT witness at the
            # validated incumbent bound before attempting a harder threshold.
            # The incumbent permutation is never passed as SAT assumptions.
            high = best_bandwidth if self.search_mode == "adaptive" else best_bandwidth - 1
            first_adaptive_call = self.search_mode == "adaptive"
            while low <= high:
                if effective_timeout is not None and (monotonic() - started) >= effective_timeout:
                    timed_out = True
                    break

                confirming_incumbent = first_adaptive_call
                if first_adaptive_call:
                    mid = high
                    first_adaptive_call = False
                elif self.search_mode == "adaptive":
                    gap = high - low
                    mid = high if gap <= 3 else low + (3 * gap + 3) // 4
                else:
                    mid = (low + high) // 2
                estimate = estimate_for_encoder(
                    self.encoder,
                    graph,
                    k=mid,
                    symmetry_breaking=symmetry_breaking,
                )
                _, resource_reason = limits.check(estimate)
                if resource_reason:
                    break

                enc_start = monotonic()
                formula = self.encoder.encode(graph, mid, symmetry_breaking=symmetry_breaking)
                total_encoding_time += monotonic() - enc_start
                last_num_vars = formula.num_variables
                last_num_clauses = formula.num_clauses

                backend = get_sat_backend(self.backend_name)
                backend.append_formula(formula.clauses)
                report_progress(
                    self,
                    bandwidth=best_bandwidth,
                    permutation=best_permutation,
                    lower_bound=certified_lb,
                    sat_calls=sat_calls,
                    encoding_time_s=total_encoding_time,
                    solving_time_s=total_solving_time,
                    num_variables=last_num_vars,
                    num_clauses=last_num_clauses,
                    sat_solved_any=sat_solved_any,
                    incumbent_source="SAT" if sat_solved_any else "HEURISTIC",
                )
                report_sat_event(self, k=mid, outcome="STARTED")
                sat_calls += 1
                remaining = None if effective_timeout is None else effective_timeout - (monotonic() - started)
                solve_start = monotonic()
                is_sat = backend.solve_with_timeout(remaining)
                solve_time = monotonic() - solve_start
                total_solving_time += solve_time

                if is_sat is None:
                    backend.delete()
                    report_sat_event(self, k=mid, outcome="UNKNOWN", solve_time_s=solve_time)
                    timed_out = True
                    break

                if is_sat:
                    model = backend.get_model()
                    backend.delete()
                    if model is None:
                        raise RuntimeError(f"Solver returned SAT but model is None for k={mid}")
                    decoded_perm = self.encoder.decode(graph, model, mid)
                    actual_bw = calculate_bandwidth(graph, decoded_perm)
                    if not validate_solution(graph, decoded_perm).valid or actual_bw > mid:
                        raise RuntimeError(f"Invalid CaDiCaL model at k={mid}")
                    sat_solved_any = True
                    report_sat_event(self, k=mid, outcome="SAT", solve_time_s=solve_time, bandwidth=actual_bw)
                    if actual_bw <= best_bandwidth:
                        best_bandwidth = actual_bw
                        best_permutation = decoded_perm
                        report_progress(
                            self,
                            bandwidth=best_bandwidth,
                            permutation=best_permutation,
                            lower_bound=certified_lb,
                            sat_calls=sat_calls,
                            encoding_time_s=total_encoding_time,
                            solving_time_s=total_solving_time,
                            num_variables=last_num_vars,
                            num_clauses=last_num_clauses,
                            sat_solved_any=sat_solved_any,
                            incumbent_source="SAT",
                        )
                    high = min(mid - 1, actual_bw - 1)
                else:
                    backend.delete()
                    report_sat_event(self, k=mid, outcome="UNSAT", solve_time_s=solve_time)
                    if confirming_incumbent:
                        raise RuntimeError("CaDiCaL reported UNSAT at a validated feasible bound")
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
                        num_variables=last_num_vars,
                        num_clauses=last_num_clauses,
                        sat_solved_any=sat_solved_any,
                        incumbent_source="SAT" if sat_solved_any else "HEURISTIC",
                    )

        runtime = monotonic() - started
        status = SolutionStatus.OPTIMAL
        if resource_reason:
            status = SolutionStatus.SKIPPED
        elif timed_out:
            status = SolutionStatus.FEASIBLE if best_permutation is not None else SolutionStatus.TIMEOUT
        elif best_bandwidth is not None and certified_lb == best_bandwidth:
            status = SolutionStatus.OPTIMAL
        elif best_permutation is not None and certified_lb < best_bandwidth:
            status = SolutionStatus.FEASIBLE

        return SolverResult(
            instance=graph.name,
            method="SAT",
            solver=self.backend_name,
            encoding=self.encoder.name,
            strategy=f"repeated_{self.search_mode}",
            status=status,
            bandwidth=best_bandwidth,
            permutation=best_permutation,
            runtime_s=runtime,
            encoding_time_s=total_encoding_time,
            solving_time_s=total_solving_time,
            num_variables=last_num_vars,
            num_clauses=last_num_clauses,
            sat_calls=sat_calls,
            lower_bound=certified_lb,
            upper_bound=best_bandwidth,
            metadata={
                "symmetry_breaking": symmetry_breaking,
                "search_mode": self.search_mode,
                "threshold_policy": self.threshold_policy,
                "skipped_reason": resource_reason,
                "sat_solved_any": sat_solved_any,
                "incumbent_source": "SAT" if sat_solved_any else "HEURISTIC",
            },
        )


__all__ = ["RepeatedSATSolver"]
