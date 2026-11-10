"""Seeded permutation simulated annealing with an RCM incumbent."""

from dataclasses import dataclass
from math import exp, isfinite
from random import Random
from time import monotonic

from bmp.core.graph import Graph
from bmp.core.solution import BMPSolution, SolutionStatus
from bmp.core.validation import compute_bandwidth
from bmp.heuristics.rcm import RCMSolver


@dataclass(slots=True)
class SimulatedAnnealingSolver:
    iterations: int = 2000
    initial_temperature: float = 2.0
    cooling: float = 0.995
    seed: int = 0
    minimum_temperature: float = 1e-12

    def solve(self, graph: Graph) -> BMPSolution:
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
        assignment = dict(initial.assignment)
        current = best = compute_bandwidth(graph, assignment)
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
                candidate = compute_bandwidth(graph, assignment)
                delta = candidate - current
                # Metropolis cho phép bước xấu với xác suất giảm theo nhiệt độ.
                if delta <= 0 or rng.random() < exp(-delta / temperature):
                    current = candidate
                    if current < best:
                        incumbent, best = assignment.copy(), current
                else:
                    # Hoàn tác swap để giữ trạng thái trước bước bị từ chối.
                    assignment[u], assignment[v] = assignment[v], assignment[u]
                temperature *= self.cooling

        return BMPSolution(
            SolutionStatus.FEASIBLE,
            "sa",
            monotonic() - started,
            assignment=incumbent,
            bandwidth=best,
            upper_bound=best,
            metadata={
                "seed": self.seed,
                "iterations": self.iterations,
                "iterations_completed": completed,
                "initial_temperature": self.initial_temperature,
                "minimum_temperature": self.minimum_temperature,
                "cooling": self.cooling,
            },
        )
