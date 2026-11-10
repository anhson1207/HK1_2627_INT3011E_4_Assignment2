"""Shared bounds, symmetry normalization, and deadline wrappers for exact solvers."""

from __future__ import annotations

import multiprocessing
from multiprocessing import get_context
import os
from time import monotonic
from typing import Any, Callable, Mapping

from bmp.core.bounds import identity_upper_bound
from bmp.core.graph import Graph
from bmp.core.solution import BMPSolution, SolutionStatus, SolverResult
from bmp.core.validation import calculate_bandwidth, validate_assignment
from bmp.solvers.sat.search import (
    compute_initial_upper_bound,
    compute_lower_bound,
    select_anchor_vertex,
)


def prepare_mip_bounds(
    graph: Graph, *, symmetry_breaking: bool = False
) -> tuple[int, int, dict[int, int], int | None]:
    """Compute certified lower bound, identity upper bound, and symmetry anchor.

    When ``symmetry_breaking`` is enabled on a graph with at least two vertices,
    the anchor vertex is chosen with ``select_anchor_vertex`` (matching SAT) and
    the initial identity permutation is reversed if needed so ``p(anchor) <= ceil(n/2)``
    while preserving the exact initial bandwidth.
    """
    lower = compute_lower_bound(graph)
    best_bandwidth, best_assignment = identity_upper_bound(graph)
    anchor: int | None = None

    if symmetry_breaking and graph.order >= 2:
        anchor = select_anchor_vertex(graph)
        cutoff = (graph.order + 1) // 2
        if best_assignment[anchor] > cutoff:
            best_assignment = {
                vertex: graph.order + 1 - pos for vertex, pos in best_assignment.items()
            }
            best_bandwidth = calculate_bandwidth(graph, best_assignment)

    return lower, best_bandwidth, best_assignment, anchor


def normalize_for_symmetry(
    graph: Graph,
    permutation: Mapping[int, int],
    *,
    anchor: int | None,
) -> tuple[dict[int, int], bool]:
    """Reverse ``permutation`` iff ``anchor`` breaks ``p(anchor) <= ceil(n / 2)``."""
    perm = dict(permutation)
    if anchor is None or graph.order < 2:
        return perm, False
    cutoff = (graph.order + 1) // 2
    if perm[anchor] <= cutoff:
        return perm, False
    reversed_perm = {vertex: graph.order + 1 - pos for vertex, pos in perm.items()}
    return reversed_perm, True


def prepare_cp_hints(
    graph: Graph,
    *,
    symmetry_breaking: bool = False,
    initial_permutation: Mapping[int, int] | None = None,
    use_lower_bound: bool = True,
    use_initial_upper_bound: bool = True,
) -> tuple[int, int, int, dict[int, int] | None, int | None, bool]:
    """Compute certified bounds, optional initial hint, and symmetry anchor for CP models."""
    certified_lb = compute_lower_bound(graph)
    model_lb = certified_lb if use_lower_bound else 0
    anchor = (
        select_anchor_vertex(graph)
        if symmetry_breaking and graph.order >= 2
        else None
    )

    reversed_hint = False
    hint_perm: dict[int, int] | None = None
    model_ub = max(0, graph.order - 1)

    if initial_permutation is not None:
        report = validate_assignment(graph, initial_permutation)
        if not report.valid or report.actual_bandwidth is None:
            raise ValueError(f"Invalid initial_permutation: {'; '.join(report.errors)}")
        hint_perm, reversed_hint = normalize_for_symmetry(
            graph, initial_permutation, anchor=anchor
        )
        hint_bw = calculate_bandwidth(graph, hint_perm)
        if use_initial_upper_bound:
            model_ub = max(model_lb, min(model_ub, hint_bw))
    elif use_initial_upper_bound:
        if graph.order == 0:
            hint_perm = {}
            model_ub = 0
        else:
            init_ub, computed_perm = compute_initial_upper_bound(
                graph, symmetry_breaking=symmetry_breaking
            )
            hint_perm = computed_perm
            model_ub = max(model_lb, min(model_ub, init_ub))

    return certified_lb, model_lb, model_ub, hint_perm, anchor, reversed_hint


def _cp_child_worker(conn, fn: Callable[[], SolverResult]) -> None:
    try:
        res = fn()
        conn.send(("ok", res.to_dict()))
    except BaseException as exc:
        try:
            conn.send(("error", f"{type(exc).__name__}: {exc}"))
        except Exception:
            pass
    finally:
        conn.close()


def run_cp_with_deadline(
    fn: Callable[[], SolverResult],
    *,
    graph: Graph,
    solver_name: str,
    timeout_seconds: float,
    certified_lb: int,
    grace_seconds: float = 1.5,
    base_metadata: Mapping[str, object] | None = None,
) -> SolverResult:
    """Execute a CP solve callable in an isolated child with strict wall deadline."""
    if os.name == "nt" or "fork" not in multiprocessing.get_all_start_methods():
        return fn()

    started = monotonic()
    ctx = get_context("fork")
    parent, child = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=_cp_child_worker, args=(child, fn))
    proc.start()
    child.close()

    deadline = started + timeout_seconds + grace_seconds
    try:
        while monotonic() < deadline:
            remaining = max(0.0, deadline - monotonic())
            if parent.poll(min(0.1, remaining)):
                try:
                    kind, payload = parent.recv()
                except EOFError:
                    break
                proc.join(timeout=1.0)
                if kind == "ok":
                    fields = {
                        k: payload[k]
                        for k in (
                            "instance",
                            "method",
                            "solver",
                            "encoding",
                            "strategy",
                            "status",
                            "bandwidth",
                            "permutation",
                            "runtime_s",
                            "encoding_time_s",
                            "solving_time_s",
                            "num_variables",
                            "num_clauses",
                            "sat_calls",
                            "lower_bound",
                            "upper_bound",
                            "metadata",
                        )
                    }
                    if fields["permutation"] is not None:
                        fields["permutation"] = {
                            int(v): int(p) for v, p in fields["permutation"].items()
                        }
                    fields["metadata"] = {
                        **dict(fields["metadata"] or {}),
                        "isolated_subprocess": True,
                    }
                    fields["runtime_s"] = monotonic() - started
                    return SolverResult(**fields)
                return SolverResult(
                    instance=graph.name,
                    method="CP",
                    solver=solver_name,
                    status=SolutionStatus.ERROR,
                    runtime_seconds=monotonic() - started,
                    lower_bound=certified_lb,
                    metadata={
                        **dict(base_metadata or {}),
                        "reason": str(payload),
                        "isolated_subprocess": True,
                    },
                )
            if not proc.is_alive():
                break

        return SolverResult(
            instance=graph.name,
            method="CP",
            solver=solver_name,
            status=SolutionStatus.TIMEOUT,
            runtime_seconds=monotonic() - started,
            lower_bound=certified_lb,
            metadata={
                **dict(base_metadata or {}),
                "reason": "Strict CP wall-clock deadline exceeded; worker terminated",
                "isolated_subprocess": True,
                "timed_out": True,
            },
        )
    finally:
        if proc.is_alive():
            proc.terminate()
            proc.join(timeout=1.0)
            if proc.is_alive():
                proc.kill()
                proc.join()
        parent.close()


def build_mip_result(
    graph: Graph,
    *,
    solver_name: str,
    status: SolutionStatus,
    assignment: Mapping[int, int],
    claimed_bandwidth: int,
    bound: int,
    runtime_seconds: float,
    metadata: Mapping[str, object],
) -> BMPSolution:
    """Validate an assignment and wrap it into a standardized SolverResult."""
    report = validate_assignment(graph, assignment, claimed_bandwidth=claimed_bandwidth)
    if not report.valid or report.actual_bandwidth is None:
        raise RuntimeError(f"{solver_name} assignment failed validation: {report.errors}")
    safe_bound = max(0, min(report.actual_bandwidth, bound))
    return BMPSolution(
        instance=graph.name,
        method="MIP",
        solver=solver_name,
        status=status,
        runtime_seconds=runtime_seconds,
        permutation=assignment,
        bandwidth=report.actual_bandwidth,
        lower_bound=safe_bound,
        upper_bound=report.actual_bandwidth,
        metadata=dict(metadata),
    )


__all__ = [
    "build_mip_result",
    "normalize_for_symmetry",
    "prepare_cp_hints",
    "prepare_mip_bounds",
    "run_cp_with_deadline",
]
