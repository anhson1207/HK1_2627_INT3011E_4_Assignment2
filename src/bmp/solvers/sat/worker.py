"""Isolated SAT execution for CaDiCaL deadlines and optional process memory caps."""

from __future__ import annotations

from dataclasses import replace
from multiprocessing import get_context
from time import monotonic
from typing import Mapping

from bmp.core.bounds import identity_upper_bound
from bmp.core.graph import Graph
from bmp.core.solution import SolutionStatus, SolverResult
from bmp.core.validation import calculate_bandwidth
from bmp.encodings.estimator import ResourceLimits


def _run_child(conn, solver, graph, heuristic, symmetry, limits):
    try:
        solver._progress_conn = conn
        if limits.memory_limit_mb is not None:
            import resource

            cap = int(limits.memory_limit_mb * 1024 * 1024)
            resource.setrlimit(resource.RLIMIT_AS, (cap, cap))
        result = solver.solve(
            graph, timeout_seconds=None, heuristic_permutation=heuristic,
            symmetry_breaking=symmetry,
            limits=replace(limits, timeout_seconds=None, memory_limit_mb=None),
        )
        conn.send(("ok", result.to_dict()))
    except BaseException as exc:
        try:
            conn.send(("error", f"{type(exc).__name__}: {exc}"))
        except Exception:
            pass
    finally:
        conn.close()


def report_progress(
    solver, *, bandwidth: int, permutation: Mapping[int, int],
    lower_bound: int, sat_calls: int, encoding_time_s: float = 0.0,
    solving_time_s: float = 0.0, num_variables: int | None = None,
    num_clauses: int | None = None,
    initial_clauses: int | None = None, added_clauses: int | None = None,
) -> None:
    conn = getattr(solver, "_progress_conn", None)
    if conn is not None:
        conn.send(("progress", {
            "bandwidth": bandwidth, "permutation": dict(permutation),
            "lower_bound": lower_bound, "sat_calls": sat_calls,
            "encoding_time_s": encoding_time_s,
            "solving_time_s": solving_time_s,
            "num_variables": num_variables, "num_clauses": num_clauses,
            "initial_clauses": initial_clauses,
            "added_clauses": added_clauses,
        }))


def run_bounded_solver(
    solver, graph: Graph, *, timeout_seconds: float,
    heuristic_permutation: Mapping[int, int] | None,
    symmetry_breaking: bool, limits: ResourceLimits,
) -> SolverResult:
    """Run the whole search in a POSIX child and enforce a wall clock deadline."""
    started = monotonic()
    context = get_context("fork")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(
        target=_run_child,
        args=(child, solver, graph, heuristic_permutation, symmetry_breaking, limits),
    )
    process.start()
    child.close()
    progress = None
    try:
        deadline = started + timeout_seconds
        error = "Wall clock deadline exceeded; worker terminated"
        status = SolutionStatus.TIMEOUT
        while parent.poll(max(0.0, deadline - monotonic())):
            try:
                kind, payload = parent.recv()
            except EOFError:
                error = "Worker exited without a result"
                status = SolutionStatus.ERROR
                break
            if kind == "progress":
                progress = payload
                continue
            process.join(timeout=1)
            if kind == "ok":
                fields = {
                    name: payload[name]
                    for name in (
                        "instance", "method", "solver", "encoding", "strategy", "status",
                        "bandwidth", "permutation", "runtime_s", "encoding_time_s",
                        "solving_time_s", "num_variables", "num_clauses", "sat_calls",
                        "lower_bound", "upper_bound", "metadata",
                    )
                }
                if fields["permutation"] is not None:
                    fields["permutation"] = {int(v): p for v, p in fields["permutation"].items()}
                fields["runtime_s"] = monotonic() - started
                return SolverResult(**fields)
            error = str(payload)
            status = SolutionStatus.ERROR
            break
        if not process.is_alive() and status is SolutionStatus.TIMEOUT:
            status = SolutionStatus.ERROR
            error = "Worker exited without a result"
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=1)
            if process.is_alive():
                process.kill()
                process.join()
        parent.close()

    # An independently validated incumbent is retained even if the worker dies.
    if progress is not None:
        incumbent = dict(progress["permutation"])
        upper = calculate_bandwidth(graph, incumbent)
        lower = progress["lower_bound"]
    elif heuristic_permutation is not None:
        incumbent = dict(heuristic_permutation)
        upper = calculate_bandwidth(graph, incumbent)
        lower = 0
    else:
        upper, incumbent = identity_upper_bound(graph)
        lower = 0
    return SolverResult(
        instance=graph.name, method="SAT", solver=solver.backend_name,
        encoding=solver.encoder.name,
        strategy=(f"repeated_{solver.search_mode}" if hasattr(solver, "search_mode") else "incremental"),
        status=status, bandwidth=upper, permutation=incumbent,
        runtime_s=monotonic() - started, lower_bound=lower, upper_bound=upper,
        encoding_time_s=progress["encoding_time_s"] if progress else 0.0,
        solving_time_s=progress["solving_time_s"] if progress else 0.0,
        num_variables=progress["num_variables"] if progress else None,
        num_clauses=progress["num_clauses"] if progress else None,
        sat_calls=progress["sat_calls"] if progress else 0,
        metadata={
            "worker_reason": error, "timeout_seconds": timeout_seconds,
            "initial_clauses": progress["initial_clauses"] if progress else None,
            "added_clauses": progress["added_clauses"] if progress else None,
        },
    )
