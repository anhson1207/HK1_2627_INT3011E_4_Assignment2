"""Small-instance exact oracle for cross-checking future solvers."""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic

from bmp.core.bounds import degree_lower_bound, identity_upper_bound
from bmp.core.graph import Graph
from bmp.core.solution import BMPSolution, SolutionStatus


class _SearchTimeout(Exception):
    pass


@dataclass(slots=True)
class BruteForceSolver:
    """Exact depth-first enumeration with safe partial-objective pruning.

    This solver is deliberately restricted to tiny graphs. Its role is to be
    an independently understandable correctness oracle for SAT/CP/MIP models,
    not a competitive BMP implementation.
    """

    max_vertices: int = 10

    def solve(self, graph: Graph, *, timeout_seconds: float | None = None) -> BMPSolution:
        if graph.order > self.max_vertices:
            raise ValueError(
                f"Brute-force oracle accepts at most {self.max_vertices} vertices; "
                f"received {graph.order}"
            )
        if timeout_seconds is not None and timeout_seconds < 0:
            raise ValueError("timeout_seconds cannot be negative")

        started = monotonic()
        lower_bound = degree_lower_bound(graph)
        best_bandwidth, best_assignment = identity_upper_bound(graph)
        search_nodes = 0

        if graph.order <= 1 or best_bandwidth == lower_bound:
            return BMPSolution(
                status=SolutionStatus.OPTIMAL,
                solver="brute-force",
                runtime_seconds=monotonic() - started,
                assignment=best_assignment,
                bandwidth=best_bandwidth,
                lower_bound=best_bandwidth,
                upper_bound=best_bandwidth,
                metadata={"search_nodes": search_nodes, "max_vertices": self.max_vertices},
            )

        assignment: dict[int, int] = {}
        remaining = set(graph.vertices)
        incident: dict[int, tuple[tuple[int, int], ...]] = {
            vertex: tuple(edge for edge in graph.edges if vertex in edge)
            for vertex in graph.vertices
        }
        timed_out = False

        def search(position: int, partial_bandwidth: int) -> None:
            nonlocal best_assignment, best_bandwidth, search_nodes
            if timeout_seconds is not None and monotonic() - started >= timeout_seconds:
                raise _SearchTimeout
            search_nodes += 1
            if not remaining:
                # Reversal of every labeling has the same bandwidth. Keep one
                # orientation without making any graph-automorphism assumption.
                if graph.order >= 2 and assignment[graph.vertices[0]] > assignment[graph.vertices[1]]:
                    return
                if partial_bandwidth < best_bandwidth:
                    best_bandwidth = partial_bandwidth
                    best_assignment = dict(assignment)
                return

            for vertex in sorted(remaining, key=lambda item: (-graph.degree(item), item)):
                assignment[vertex] = position
                next_bandwidth = partial_bandwidth
                for u, v in incident[vertex]:
                    other = v if u == vertex else u
                    if other in assignment:
                        next_bandwidth = max(
                            next_bandwidth,
                            abs(assignment[vertex] - assignment[other]),
                        )
                if next_bandwidth < best_bandwidth:
                    remaining.remove(vertex)
                    search(position + 1, next_bandwidth)
                    remaining.add(vertex)
                del assignment[vertex]
                if best_bandwidth == lower_bound:
                    return

        try:
            search(1, 0)
        except _SearchTimeout:
            timed_out = True

        runtime = monotonic() - started
        if timed_out and best_bandwidth > lower_bound:
            status = SolutionStatus.TIMEOUT
            certified_lower_bound = lower_bound
        else:
            status = SolutionStatus.OPTIMAL
            certified_lower_bound = best_bandwidth

        return BMPSolution(
            status=status,
            solver="brute-force",
            runtime_seconds=runtime,
            assignment=best_assignment,
            bandwidth=best_bandwidth,
            lower_bound=certified_lower_bound,
            upper_bound=best_bandwidth,
            metadata={
                "search_nodes": search_nodes,
                "max_vertices": self.max_vertices,
                "timed_out": timed_out,
            },
        )
