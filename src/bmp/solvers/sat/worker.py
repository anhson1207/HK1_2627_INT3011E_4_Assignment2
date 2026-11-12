"""Isolated SAT execution for CaDiCaL deadlines and optional process memory caps."""

from __future__ import annotations

from dataclasses import replace
from multiprocessing import get_context
import subprocess
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
            try:
                resource.setrlimit(resource.RLIMIT_AS, (cap, cap))
            except (OSError, ValueError):
                # macOS may reject a finite RLIMIT_AS for a forked process.
                # The parent still enforces the sampled resident-set cap.
                pass
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
    sat_solved_any: bool = False,
    incumbent_source: str | None = None,
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
            "sat_solved_any": sat_solved_any,
            "incumbent_source": incumbent_source,
        }))


def report_sat_event(solver, *, k: int, outcome: str, solve_time_s: float | None = None,
                     bandwidth: int | None = None) -> None:
    """Send a per-threshold event before and after SAT solving in bounded runs."""
    conn = getattr(solver, "_progress_conn", None)
    if conn is not None:
        conn.send(("sat_event", {
            "k": k, "outcome": outcome, "solve_time_s": solve_time_s,
            "bandwidth": bandwidth,
        }))


def run_bounded_solver(
    solver, graph: Graph, *, timeout_seconds: float,
    heuristic_permutation: Mapping[int, int] | None,
    symmetry_breaking: bool, limits: ResourceLimits,
) -> SolverResult:
    """Run the whole search in a POSIX child and enforce a wall clock deadline."""
    started = monotonic()
    if timeout_seconds <= 0:
        if heuristic_permutation is not None:
            incumbent = dict(heuristic_permutation)
            upper = calculate_bandwidth(graph, incumbent)
        else:
            upper, incumbent = identity_upper_bound(graph)
        return SolverResult(
            instance=graph.name, method="SAT", solver=solver.backend_name,
            encoding=solver.encoder.name,
            strategy=(
                f"repeated_{solver.search_mode}"
                if hasattr(solver, "search_mode") and "Repeated" in type(solver).__name__
                else (
                    "incremental_binary"
                    if getattr(solver, "search_mode", "linear") == "binary"
                    else "incremental"
                )
            ),
            status=SolutionStatus.TIMEOUT, bandwidth=upper, permutation=incumbent,
            runtime_s=monotonic() - started, lower_bound=0, upper_bound=upper,
            encoding_time_s=0.0, solving_time_s=0.0,
            num_variables=None, num_clauses=None, sat_calls=0,
            metadata={
                "worker_reason": "Wall clock deadline exceeded before worker launch",
                "timeout_seconds": timeout_seconds,
                "initial_clauses": None, "added_clauses": None,
                "sat_trace": [], "sampled_peak_memory_mb": None,
                "sat_solved_any": False, "incumbent_source": "HEURISTIC",
            },
        )
    context = get_context("fork")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(
        target=_run_child,
        args=(child, solver, graph, heuristic_permutation, symmetry_breaking, limits),
    )
    process.start()
    child.close()
    progress = None
    sat_trace: list[dict] = []
    peak_memory_mb: float | None = None

    def sample_memory() -> float | None:
        try:
            measured = subprocess.run(
                ["ps", "-o", "rss=", "-p", str(process.pid)],
                capture_output=True, text=True, timeout=1, check=False,
            )
            return int(measured.stdout.strip()) / 1024 if measured.returncode == 0 and measured.stdout.strip() else None
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return None

    try:
        deadline = started + timeout_seconds
        error = "Wall clock deadline exceeded; worker terminated"
        status = SolutionStatus.TIMEOUT
        while monotonic() < deadline:
            rss = sample_memory()
            if rss is not None:
                peak_memory_mb = max(peak_memory_mb or 0.0, rss)
                if limits.memory_limit_mb is not None and rss > limits.memory_limit_mb:
                    error = f"Resident memory {rss:.1f} MiB exceeded limit {limits.memory_limit_mb:.1f} MiB"
                    status = SolutionStatus.SKIPPED
                    break
            if not parent.poll(min(0.2, max(0.0, deadline - monotonic()))):
                continue
            try:
                kind, payload = parent.recv()
            except EOFError:
                error = "Worker exited without a result"
                status = SolutionStatus.ERROR
                break
            if kind == "progress":
                progress = payload
                continue
            if kind == "sat_event":
                if payload["outcome"] == "STARTED":
                    sat_trace.append(payload)
                elif sat_trace and sat_trace[-1]["outcome"] == "STARTED":
                    sat_trace[-1] = payload
                else:
                    sat_trace.append(payload)
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
                fields["metadata"] = {**fields["metadata"], "sat_trace": sat_trace,
                                      "sampled_peak_memory_mb": peak_memory_mb}
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
        sat_solved_any = bool(progress.get("sat_solved_any")) or any(
            ev.get("outcome") == "SAT" for ev in sat_trace
        )
        inc_source = progress.get("incumbent_source") or ("SAT" if sat_solved_any else "HEURISTIC")
    elif heuristic_permutation is not None:
        incumbent = dict(heuristic_permutation)
        upper = calculate_bandwidth(graph, incumbent)
        lower = 0
        sat_solved_any = False
        inc_source = "HEURISTIC"
    else:
        upper, incumbent = identity_upper_bound(graph)
        lower = 0
        sat_solved_any = False
        inc_source = "HEURISTIC"
    if sat_trace and sat_trace[-1]["outcome"] == "STARTED":
        sat_trace[-1] = {**sat_trace[-1], "outcome": "UNKNOWN"}
    return SolverResult(
        instance=graph.name, method="SAT", solver=solver.backend_name,
        encoding=solver.encoder.name,
        strategy=(
            f"repeated_{solver.search_mode}"
            if hasattr(solver, "search_mode") and "Repeated" in type(solver).__name__
            else (
                "incremental_binary"
                if getattr(solver, "search_mode", "linear") == "binary"
                else "incremental"
            )
        ),
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
            "sat_trace": sat_trace,
            "sampled_peak_memory_mb": peak_memory_mb,
            "sat_solved_any": sat_solved_any,
            "incumbent_source": inc_source,
        },
    )
