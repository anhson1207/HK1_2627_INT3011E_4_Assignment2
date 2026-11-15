"""Independent checks for L10 adaptive CaDiCaL attribution and bounds."""

import random

import pytest

from bmp.core.graph import Graph
from bmp.core.solution import SolutionStatus
from bmp.core.validation import validate_solution
from bmp.encodings.estimator import ResourceLimits
from bmp.encodings.order import OrderEncoding
from bmp.encodings.pairwise import PairwiseEncoding
from bmp.solvers.brute_force import BruteForceSolver
from bmp.solvers.sat.repeated import RepeatedSATSolver
from scripts.run_leader_l10 import invocation_evidence


EDGES = [(1, 5), (2, 3), (2, 4), (2, 5), (3, 4),
         (3, 6), (4, 7), (5, 6), (5, 7), (6, 7)]


def graph():
    return Graph.from_edges(range(1, 8), EDGES, name="l10_oracle")


def test_adaptive_model_and_optimality_against_oracle():
    g = graph()
    oracle = BruteForceSolver().solve(g)
    for encoder in (OrderEncoding("sequential"), PairwiseEncoding("sequential")):
        result = RepeatedSATSolver(encoder, search_mode="adaptive").solve(g)
        assert result.metadata["sat_solved_any"] is True
        assert result.sat_calls >= 1
        assert result.bandwidth == oracle.bandwidth
        assert result.status is SolutionStatus.OPTIMAL
        assert validate_solution(g, result.permutation, claimed_bandwidth=result.bandwidth).valid


def test_adaptive_timeout_retains_heuristic_attribution():
    g = graph()
    result = RepeatedSATSolver(OrderEncoding("sequential"), search_mode="adaptive").solve(
        g, timeout_seconds=0.0
    )
    assert result.metadata["sat_solved_any"] is False
    assert result.sat_calls == 0
    assert result.status is SolutionStatus.TIMEOUT


def test_adaptive_resource_guard_blocks_before_solver():
    g = graph()
    result = RepeatedSATSolver(OrderEncoding("sequential"), search_mode="adaptive").solve(
        g, limits=ResourceLimits(max_variables=1, max_clauses=1, timeout_seconds=None)
    )
    assert result.status is SolutionStatus.SKIPPED
    assert result.sat_calls == 0
    assert result.metadata["sat_solved_any"] is False


def test_external_bound_requires_valid_permutation():
    g = graph()
    invalid = {v: 1 for v in g.vertices}
    with pytest.raises(ValueError, match="valid permutation"):
        RepeatedSATSolver(OrderEncoding("sequential"), search_mode="adaptive").solve(
            g, heuristic_permutation=invalid
        )


def test_solver_invocation_evidence_distinguishes_construction_timeout():
    record = {"sat_calls": 0, "cnf_build_time_s": 0.2,
              "total_wall_time_s": 30.0, "num_clauses": 1000,
              "solver_status": "TIMEOUT_WITH_INCUMBENT"}
    assert invocation_evidence(record) == "WORKER_PROGRESS_TIMING_INFERRED"
    assert invocation_evidence({**record, "cnf_build_time_s": None}) == "NO_CALL_EVIDENCE"
    assert invocation_evidence({**record, "cnf_build_time_s": 0.0}) == "NO_CALL_EVIDENCE"
    assert invocation_evidence({**record, "solver_call_started": True}) == "WORKER_THRESHOLD_EVENT"


def test_certify_feasible_mode_calls_cadical_at_bound_equal_to_lower_bound():
    g = Graph.from_edges(range(1, 5), [(1, 2), (2, 3), (3, 4)], name="path4")
    result = RepeatedSATSolver(
        OrderEncoding("sequential"), search_mode="adaptive", certify_feasible_with_sat=True
    ).solve(g)
    assert result.status is SolutionStatus.OPTIMAL
    assert result.bandwidth == 1
    assert result.sat_calls >= 1
    assert result.metadata["sat_solved_any"] is True


@pytest.mark.parametrize("seed", range(12))
def test_adaptive_matches_small_oracle(seed):
    rng = random.Random(seed)
    n = 5 + seed % 3
    edges = [(u, v) for u in range(1, n + 1) for v in range(u + 1, n + 1)
             if rng.random() < 0.35]
    g = Graph.from_edges(range(1, n + 1), edges, name=f"oracle_{seed}")
    exact = BruteForceSolver().solve(g)
    result = RepeatedSATSolver(OrderEncoding("sequential"), search_mode="adaptive").solve(g)
    assert result.bandwidth == exact.bandwidth
    assert result.status is SolutionStatus.OPTIMAL
    assert validate_solution(g, result.permutation, claimed_bandwidth=result.bandwidth).valid
