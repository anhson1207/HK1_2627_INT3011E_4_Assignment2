"""Deterministic Reverse Cuthill–McKee baseline."""

from collections import deque
from time import monotonic

from bmp.core.graph import Graph
from bmp.core.solution import BMPSolution, SolutionStatus
from bmp.core.validation import compute_bandwidth


class RCMSolver:
    def solve(self, graph: Graph) -> BMPSolution:
        started = monotonic()
        neighbors = {v: [] for v in graph.vertices}
        for u, v in graph.edges:
            neighbors[u].append(v)
            neighbors[v].append(u)

        def priority(vertex: int) -> tuple[int, int]:
            return len(neighbors[vertex]), vertex

        order = []
        visited = set()
        # BFS theo bậc tăng dần, bắt đầu lại khi gặp thành phần mới.
        for root in sorted(graph.vertices, key=priority):
            if root in visited:
                continue
            queue = deque([root])
            visited.add(root)
            while queue:
                vertex = queue.popleft()
                order.append(vertex)
                for adjacent in sorted(neighbors[vertex], key=priority):
                    if adjacent not in visited:
                        visited.add(adjacent)
                        queue.append(adjacent)

        assignment = {v: i for i, v in enumerate(reversed(order), start=1)}
        value = compute_bandwidth(graph, assignment)
        return BMPSolution(
            SolutionStatus.FEASIBLE,
            "rcm",
            monotonic() - started,
            assignment=assignment,
            bandwidth=value,
            upper_bound=value,
        )
