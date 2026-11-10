"""Seeded permutation simulated annealing with an RCM incumbent."""

from __future__ import annotations

from dataclasses import dataclass
from math import exp, isfinite
from random import Random
from time import monotonic

from bmp.core.graph import Graph
from bmp.core.solution import SolutionStatus, SolverResult
from bmp.core.validation import calculate_bandwidth, validate_solution
from bmp.heuristics.rcm import RCMSolver
from bmp.solvers.sat.search import compute_lower_bound


@dataclass(slots=True)
class SimulatedAnnealingSolver:
    """Single-representation swap simulated annealing starting from RCM."""

    iterations: int = 2000
    initial_temperature: float = 2.0
    cooling: float = 0.995
    seed: int = 0
    minimum_temperature: float = 1e-12

    def solve(self, graph: Graph) -> SolverResult:
        if (
            self.iterations < 0
            or not isfinite(self.initial_temperature)
            or self.initial_temperature <= 0
        ):
            raise ValueError(
                "Expected nonnegative iterations and a positive finite temperature"
            )
        if not 0 < self.cooling < 1:
            raise ValueError("cooling must be between zero and one")
        if not 0 < self.minimum_temperature <= self.initial_temperature:
            raise ValueError(
                "Expected positive minimum_temperature <= initial_temperature"
            )

        started = monotonic()
        initial = RCMSolver().solve(graph)
        if initial.permutation is None:
            raise RuntimeError("RCM did not produce a permutation")
        assignment = dict(initial.permutation)
        current = best = calculate_bandwidth(graph, assignment)
        incumbent = assignment.copy()
        rng = Random(self.seed)
        temperature = self.initial_temperature

        completed = 0
        if graph.edges:
            for _ in range(self.iterations):
                if temperature < self.minimum_temperature:
                    break
                completed += 1
                u, v = rng.sample(graph.vertices, 2)
                assignment[u], assignment[v] = assignment[v], assignment[u]
                candidate = calculate_bandwidth(graph, assignment)
                delta = candidate - current
                if delta <= 0 or rng.random() < exp(-delta / temperature):
                    current = candidate
                    if current < best:
                        incumbent, best = assignment.copy(), current
                else:
                    assignment[u], assignment[v] = assignment[v], assignment[u]
                temperature *= self.cooling

        report = validate_solution(graph, incumbent, claimed_bandwidth=best)
        if not report.valid or report.actual_bandwidth is None:
            raise RuntimeError(f"Simulated annealing produced an invalid assignment: {report.errors}")

        lower = min(compute_lower_bound(graph), report.actual_bandwidth)
        return SolverResult(
            instance=graph.name,
            method="HEURISTIC",
            solver="sa",
            status=SolutionStatus.FEASIBLE,
            runtime_seconds=monotonic() - started,
            permutation=incumbent,
            bandwidth=report.actual_bandwidth,
            lower_bound=lower,
            upper_bound=report.actual_bandwidth,
            metadata={
                "seed": self.seed,
                "iterations": self.iterations,
                "iterations_completed": completed,
                "initial_temperature": self.initial_temperature,
                "minimum_temperature": self.minimum_temperature,
                "cooling": self.cooling,
                "incumbent_source": "heuristic",
            },
        )


__all__ = ["SimulatedAnnealingSolver"]
