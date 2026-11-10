from __future__ import annotations

from time import sleep

from bmp.core.generators import erdos_renyi_graph
from bmp.core.validation import validate_solution
from bmp.encodings.estimator import ResourceLimits
from bmp.encodings.order import OrderEncoding
from bmp.solvers.sat.repeated import RepeatedSATSolver
from bmp.solvers.sat.search import compute_initial_upper_bound
from bmp.solvers.sat.worker import report_progress, report_sat_event, run_bounded_solver


class _HangingSolver:
    backend_name = "test"
    encoder = OrderEncoding("sequential")
    search_mode = "linear"

    def solve(self, graph, **kwargs):
        ub, permutation = compute_initial_upper_bound(graph)
        report_progress(self, bandwidth=ub, permutation=permutation, lower_bound=0, sat_calls=0)
        report_sat_event(self, k=ub - 1, outcome="STARTED")
        sleep(2)


def test_timeout_keeps_initial_solution_and_marks_interrupted_call_unknown():
    graph = erdos_renyi_graph(7, 0.4, seed=19)
    initial_ub, _ = compute_initial_upper_bound(graph)
    result = run_bounded_solver(
        _HangingSolver(), graph, timeout_seconds=0.3,
        heuristic_permutation=None, symmetry_breaking=False,
        limits=ResourceLimits(timeout_seconds=None),
    )
    assert result.status == "TIMEOUT"
    assert result.bandwidth == initial_ub
    assert result.sat_calls == 0
    assert result.metadata["sat_trace"][-1]["outcome"] == "UNKNOWN"
    assert validate_solution(graph, result).valid


def test_completed_trace_matches_certified_sat_calls():
    graph = erdos_renyi_graph(7, 0.4, seed=19)
    result = RepeatedSATSolver(OrderEncoding("sequential"), threshold_policy="unit").solve(
        graph, timeout_seconds=2,
        limits=ResourceLimits(timeout_seconds=None, memory_limit_mb=4096),
    )
    trace = result.metadata["sat_trace"]
    assert len([event for event in trace if event["outcome"] in ("SAT", "UNSAT")]) == result.sat_calls
    assert result.status == "OPTIMAL"
    assert trace[-1]["outcome"] == "UNSAT"
    assert abs(sum(event["solve_time_s"] for event in trace) - result.solving_time_s) < 0.001
    assert validate_solution(graph, result).valid
    assert result.metadata["sampled_peak_memory_mb"] > 0


def test_resident_memory_guard_retains_valid_incumbent():
    graph = erdos_renyi_graph(7, 0.4, seed=19)
    result = run_bounded_solver(
        _HangingSolver(), graph, timeout_seconds=1,
        heuristic_permutation=None, symmetry_breaking=False,
        limits=ResourceLimits(timeout_seconds=None, memory_limit_mb=1),
    )
    assert result.status == "SKIPPED"
    assert "Resident memory" in result.metadata["worker_reason"]
    assert result.sat_calls == 0
    assert validate_solution(graph, result).valid
