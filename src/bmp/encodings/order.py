"""Order SAT Encoding for Bandwidth Minimization Problem."""

from __future__ import annotations

from time import monotonic
from typing import Mapping, Sequence

from bmp.core.graph import Graph
from bmp.encodings.base import BMPEncoder, CNFFormula
from bmp.encodings.cardinality.base import AMOEncoder, SimpleVarAllocator, get_amo_encoder
from bmp.encodings.cardinality.pairwise_amo import PairwiseAMOEncoder


class OrderEncoding(BMPEncoder):
    """Order / Threshold-based SAT Encoding for BMP.

    Variables:
        Order variables y[v, t]: True iff label p(v) >= t (for 2 <= t <= n).
        Exact-value channeling variables x[v, p]: True iff p(v) == p (for 1 <= p <= n).

    Variable indexing:
        - For vertex v in 0..n-1, t in 2..n:
          y_var = v * (n - 1) + (t - 1)  (1-based ID: 1 .. n*(n-1))
        - For vertex v in 0..n-1, p in 1..n:
          offset = n * (n - 1)
          x_var = offset + v * n + p     (ID: n*(n-1) + 1 .. n*(n-1) + n^2)

    Constraints:
        1. Monotonicity of Order Variables:
           y[v, t + 1] -> y[v, t]   (not y[v, t+1] or y[v, t]) for all 2 <= t <= n - 1.
        2. Channeling between Exact Variables x and Order Variables y:
           x[v, 1] <-> not y[v, 2]
           x[v, n] <-> y[v, n]
           For 2 <= p <= n - 1:
             x[v, p] <-> (y[v, p] and not y[v, p + 1])
           Implemented via standard CNF clauses:
             x[v, p] -> y[v, p]           (not x[v, p] or y[v, p])
             x[v, p] -> not y[v, p+1]     (not x[v, p] or not y[v, p+1])
             y[v, p] and not y[v, p+1] -> x[v, p]
                                          (not y[v, p] or y[v, p+1] or x[v, p])
        3. Injectivity / All-Different:
           For each label p in 1..n:
             AMO_{v in V} x[v, p] (using specified amo_encoder)
           (Combined with Exactly-One implied by Order monotonicity, this guarantees bijection).
        4. Bandwidth Constraints (for bandwidth threshold k):
           For every edge (u, v) in E and for all t >= 2 such that t + k <= n:
             y[u, t + k] -> y[v, t]   (not y[u, t + k] or y[v, t])
             y[v, t + k] -> y[u, t]   (not y[v, t + k] or y[u, t])
    """

    def __init__(self, amo: str | AMOEncoder = "pairwise") -> None:
        if isinstance(amo, str):
            self._amo_encoder: AMOEncoder = get_amo_encoder(amo)
            self._amo_name = amo.lower()
        else:
            self._amo_encoder = amo
            self._amo_name = getattr(amo, "name", type(amo).__name__)

    @property
    def name(self) -> str:
        return f"order_{self._amo_name}"

    @property
    def amo_name(self) -> str:
        return self._amo_name

    def _vertex_index_map(self, graph: Graph) -> dict[int, int]:
        return {v: i for i, v in enumerate(graph.vertices)}

    def var_y(self, v_idx: int, t: int, n: int) -> int:
        """Variable ID for y[v, t] (p(v) >= t), where 2 <= t <= n."""
        if not (0 <= v_idx < n):
            raise ValueError(f"v_idx out of bounds: {v_idx} for n={n}")
        if not (2 <= t <= n):
            raise ValueError(f"Threshold t out of bounds: {t} for n={n}")
        return v_idx * (n - 1) + (t - 1)

    def var_x(self, v_idx: int, p: int, n: int) -> int:
        """Variable ID for exact channeling variable x[v, p] (p(v) == p), where 1 <= p <= n."""
        if not (0 <= v_idx < n):
            raise ValueError(f"v_idx out of bounds: {v_idx} for n={n}")
        if not (1 <= p <= n):
            raise ValueError(f"Label p out of bounds: {p} for n={n}")
        offset = n * (n - 1)
        return offset + v_idx * n + p

    def encode_fixed(self, graph: Graph, **kwargs: object) -> CNFFormula:
        """Generate fixed k-independent clauses (monotonicity, channeling, injectivity)."""
        started = monotonic()
        n = graph.order
        if n <= 1:
            return CNFFormula(build_time_s=monotonic() - started)

        v_map = self._vertex_index_map(graph)
        num_orig_vars = n * (n - 1) + n * n
        allocator = SimpleVarAllocator(start_id=num_orig_vars + 1)
        clauses: list[list[int]] = []

        # 1. Monotonicity: y[v, t+1] -> y[v, t]
        for v in graph.vertices:
            v_idx = v_map[v]
            for t in range(2, n):
                clauses.append([-self.var_y(v_idx, t + 1, n), self.var_y(v_idx, t, n)])

        # 2. Channeling with exact variables x[v, p]
        for v in graph.vertices:
            v_idx = v_map[v]
            # p = 1: x[v, 1] <-> not y[v, 2]
            y2 = self.var_y(v_idx, 2, n)
            x1 = self.var_x(v_idx, 1, n)
            clauses.append([-x1, -y2])
            clauses.append([x1, y2])

            # 2 <= p <= n - 1: x[v, p] <-> y[v, p] and not y[v, p+1]
            for p in range(2, n):
                xp = self.var_x(v_idx, p, n)
                yp = self.var_y(v_idx, p, n)
                yp_next = self.var_y(v_idx, p + 1, n)
                # xp -> yp
                clauses.append([-xp, yp])
                # xp -> not yp_next
                clauses.append([-xp, -yp_next])
                # yp and not yp_next -> xp
                clauses.append([-yp, yp_next, xp])

            # p = n: x[v, n] <-> y[v, n]
            yn = self.var_y(v_idx, n, n)
            xn = self.var_x(v_idx, n, n)
            clauses.append([-xn, yn])
            clauses.append([xn, -yn])

        # 3. Injectivity: At-Most-One vertex per label p in 1..n
        for p in range(1, n + 1):
            lits = [self.var_x(v_map[v], p, n) for v in graph.vertices]
            amo_clauses, _ = self._amo_encoder.encode(lits, allocator)
            clauses.extend(amo_clauses)

        # 4. Optional Reversal Symmetry Breaking: p(anchor) <= ceil(n / 2)
        if kwargs.get("symmetry_breaking", False) and n >= 2:
            from bmp.solvers.sat.search import select_anchor_vertex
            anchor = select_anchor_vertex(graph)
            a_idx = v_map[anchor]
            cutoff = (n + 1) // 2  # ceil(n / 2)
            if cutoff + 1 <= n:
                clauses.append([-self.var_y(a_idx, cutoff + 1, n)])

        top_var = allocator.next_id - 1
        num_aux_vars = top_var - num_orig_vars

        return CNFFormula(
            clauses=clauses,
            top_var=top_var,
            num_original_vars=num_orig_vars,
            num_aux_vars=num_aux_vars,
            build_time_s=monotonic() - started,
            comments=[f"OrderEncoding fixed clauses (n={n}, amo={self._amo_name})"],
        )

    def encode_bandwidth_step(self, graph: Graph, k: int, **kwargs: object) -> list[list[int]]:
        """Generate clauses enforcing bandwidth <= k using order variables.

        For every edge (u, v) and all t >= 2 such that t + k <= n:
            y[u, t + k] -> y[v, t]   (not y[u, t + k] or y[v, t])
            y[v, t + k] -> y[u, t]   (not y[v, t + k] or y[u, t])
        """
        n = graph.order
        if n <= 1 or not graph.edges:
            return []

        v_map = self._vertex_index_map(graph)
        clauses: list[list[int]] = []

        for u, v in graph.edges:
            u_idx = v_map[u]
            v_idx = v_map[v]
            for t in range(2, n - k + 1):
                y_u_tk = self.var_y(u_idx, t + k, n)
                y_v_t = self.var_y(v_idx, t, n)
                y_v_tk = self.var_y(v_idx, t + k, n)
                y_u_t = self.var_y(u_idx, t, n)

                clauses.append([-y_u_tk, y_v_t])
                clauses.append([-y_v_tk, y_u_t])

        return clauses

    def encode(self, graph: Graph, k: int, **kwargs: object) -> CNFFormula:
        """Generate full CNF formula for graph G and bandwidth k."""
        started = monotonic()
        formula = self.encode_fixed(graph, **kwargs)
        bw_clauses = self.encode_bandwidth_step(graph, k, **kwargs)
        formula.extend_clauses(bw_clauses)
        formula.build_time_s = monotonic() - started
        formula.comments.append(f"OrderEncoding full (k={k}, num_bw_clauses={len(bw_clauses)})")
        return formula

    def decode(self, graph: Graph, model: Sequence[int], k: int) -> dict[int, int]:
        """Decode SAT model into mapping: vertex -> label (1..n) from order variables."""
        n = graph.order
        if n == 0:
            return {}
        v_map = self._vertex_index_map(graph)
        model_set = set(model)
        assignment: dict[int, int] = {}

        for v in graph.vertices:
            v_idx = v_map[v]
            # p(v) = 1 + number of true y[v, t] variables for t in 2..n
            label = 1
            for t in range(2, n + 1):
                y_var = self.var_y(v_idx, t, n)
                if y_var in model_set:
                    label += 1
                else:
                    # By monotonicity, subsequent t should not be true
                    break
            assignment[v] = label

        return assignment


__all__ = ["OrderEncoding"]
