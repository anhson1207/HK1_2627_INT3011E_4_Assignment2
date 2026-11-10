"""Incremental SAT solver for Bandwidth Minimization Problem."""

from __future__ import annotations

from time import monotonic
from typing import Mapping

from bmp.core.graph import Graph
from bmp.core.solution import SolutionStatus, SolverResult
from bmp.core.validation import calculate_bandwidth
from bmp.encodings.base import BMPEncoder
from bmp.encodings.estimator import ResourceLimits, estimate_cnf_size, estimate_incremental_cnf_size
from bmp.encodings.order import OrderEncoding
from bmp.encodings.pairwise import PairwiseEncoding
from bmp.solvers.sat.backends.base import get_sat_backend
from bmp.solvers.sat.search import compute_initial_upper_bound, compute_lower_bound
from bmp.solvers.sat.worker import report_progress


class IncrementalSATSolver:
    """Incremental SAT solver that maintains a persistent SAT solver instance across thresholds."""

    def __init__(
        self,
        encoder: BMPEncoder | None = None,
        *,
        backend_name: str = "cadical",
        threshold_policy: str = "adaptive",
    ) -> None:
        self.encoder = encoder if encoder is not None else PairwiseEncoding()
        self.backend_name = backend_name
        self.threshold_policy = threshold_policy
        if threshold_policy not in ("adaptive", "unit"):
            raise ValueError("threshold_policy must be 'adaptive' or 'unit'")

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

        effective_timeout = timeout_seconds if timeout_seconds is not None else (limits.timeout_seconds if limits else None)
        limits = limits if limits is not None else ResourceLimits(timeout_seconds=None)
        if effective_timeout is not None or limits.memory_limit_mb is not None:
            from bmp.solvers.sat.worker import run_bounded_solver
            return run_bounded_solver(
                self, graph, timeout_seconds=effective_timeout if effective_timeout is not None else 300.0,
                heuristic_permutation=heuristic_permutation,
                symmetry_breaking=symmetry_breaking, limits=limits,
            )

        # Base case: edgeless or order <= 1
        if n <= 1 or not graph.edges:
            identity_perm = {v: i + 1 for i, v in enumerate(graph.vertices)}
            return SolverResult(
                instance=graph.name,
                method="SAT",
                solver=self.backend_name,
                encoding=self.encoder.name,
                strategy="incremental",
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
                metadata={"symmetry_breaking": symmetry_breaking},
            )

        lb = compute_lower_bound(graph)
        ub, init_perm = compute_initial_upper_bound(
            graph,
            heuristic_permutation,
            symmetry_breaking=symmetry_breaking,
        )

        if lb == ub:
            return SolverResult(
                instance=graph.name,
                method="SAT",
                solver=self.backend_name,
                encoding=self.encoder.name,
                strategy="incremental",
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
                metadata={"symmetry_breaking": symmetry_breaking, "fast_path": "lb_equals_ub"},
            )

        # Resource safety check
        if limits is not None:
            enc_family = "order" if "order" in self.encoder.name else "pairwise"
            amo_type = getattr(self.encoder, "amo_name", "pairwise")
            estimate = estimate_cnf_size(
                graph,
                encoding=enc_family,
                amo=amo_type,
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
                    strategy="incremental",
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
                    },
                )

        best_bandwidth = ub
        best_permutation: dict[int, int] | None = dict(init_perm) if init_perm else None
        certified_lb = lb
        sat_calls = 0
        total_encoding_time = 0.0
        total_solving_time = 0.0
        timed_out = False
        resource_reason: str | None = None
        fixed_clauses = 0
        added_clauses = 0
        accumulated_clauses = 0
        total_variables = 0
        report_progress(
            self, bandwidth=best_bandwidth, permutation=best_permutation,
            lower_bound=certified_lb, sat_calls=0,
        )

        # Initialize persistent SAT solver backend
        backend = get_sat_backend(self.backend_name)
        try:
            # 1. Encode fixed k-independent constraints
            enc_start = monotonic()
            fixed_formula = self.encoder.encode_fixed(graph, symmetry_breaking=symmetry_breaking)
            total_encoding_time += monotonic() - enc_start

            backend.append_formula(fixed_formula.clauses)
            accumulated_clauses = len(fixed_formula.clauses)
            fixed_clauses = accumulated_clauses
            total_variables = fixed_formula.num_variables

            # 2. Descending search
            # We first test at current best_bandwidth (or best_bandwidth - 1 if init_perm is verified)
            k_curr = best_bandwidth - 1

            # For PairwiseEncoding, add initial bandwidth clauses for k_curr
            enc_start = monotonic()
            bw_clauses = self.encoder.encode_bandwidth_step(graph, k_curr)
            total_encoding_time += monotonic() - enc_start

            backend.append_formula(bw_clauses)
            accumulated_clauses += len(bw_clauses)
            added_clauses += len(bw_clauses)
            initial_k = k_curr
            report_progress(
                self, bandwidth=best_bandwidth, permutation=best_permutation,
                lower_bound=certified_lb, sat_calls=0,
                encoding_time_s=total_encoding_time, solving_time_s=total_solving_time,
                num_variables=total_variables, num_clauses=accumulated_clauses,
                initial_clauses=fixed_clauses, added_clauses=added_clauses,
            )

            while k_curr >= certified_lb:
                if effective_timeout is not None and (monotonic() - started) >= effective_timeout:
                    timed_out = True
                    break

                solve_start = monotonic()
                sat_calls += 1
                remaining = None if effective_timeout is None else effective_timeout - (monotonic() - started)
                is_sat = backend.solve_with_timeout(remaining)
                total_solving_time += monotonic() - solve_start
                if is_sat is None:
                    timed_out = True
                    break

                if is_sat:
                    model = backend.get_model()
                    if model is None:
                        raise RuntimeError(f"Solver returned SAT but model is None for k={k_curr}")
                    decoded = self.encoder.decode(graph, model, k_curr)
                    actual_bw = calculate_bandwidth(graph, decoded)
                    best_bandwidth = actual_bw
                    best_permutation = decoded
                    report_progress(
                        self, bandwidth=best_bandwidth, permutation=best_permutation,
                        lower_bound=certified_lb, sat_calls=sat_calls,
                        encoding_time_s=total_encoding_time, solving_time_s=total_solving_time,
                        num_variables=total_variables, num_clauses=accumulated_clauses,
                        initial_clauses=fixed_clauses, added_clauses=added_clauses,
                    )

                    if best_bandwidth <= certified_lb:
                        certified_lb = best_bandwidth
                        break

                    k_next = k_curr - 1 if self.threshold_policy == "unit" else best_bandwidth - 1
                    if k_next < certified_lb:
                        certified_lb = best_bandwidth
                        break

                    next_estimate = estimate_incremental_cnf_size(
                        graph,
                        encoding="order" if isinstance(self.encoder, OrderEncoding) else "pairwise",
                        amo=getattr(self.encoder, "amo_name", "pairwise"),
                        initial_k=initial_k, target_k=k_next,
                        symmetry_breaking=symmetry_breaking,
                    )
                    _, resource_reason = limits.check(next_estimate)
                    if resource_reason:
                        break
                    if effective_timeout is not None and monotonic() - started >= effective_timeout:
                        timed_out = True
                        break

                    # Add strengthening clauses for k_next
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
                    # UNSAT at k_curr proves no bandwidth <= k_curr exists
                    certified_lb = k_curr + 1
                    report_progress(
                        self, bandwidth=best_bandwidth, permutation=best_permutation,
                        lower_bound=certified_lb, sat_calls=sat_calls,
                        encoding_time_s=total_encoding_time, solving_time_s=total_solving_time,
                        num_variables=total_variables, num_clauses=accumulated_clauses,
                        initial_clauses=fixed_clauses, added_clauses=added_clauses,
                    )
                    break

        finally:
            backend.delete()

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
            strategy="incremental",
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
                "initial_clauses": fixed_clauses,
                "added_clauses": added_clauses,
                "skipped_reason": resource_reason,
            },
        )


__all__ = ["IncrementalSATSolver"]

