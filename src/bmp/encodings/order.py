"""Order SAT Encoding for Bandwidth Minimization Problem."""

from __future__ import annotations

from time import monotonic
from typing import Literal, Sequence

from bmp.core.graph import Graph
from bmp.encodings.base import BMPEncoder, CNFFormula
from bmp.encodings.cardinality.base import AMOEncoder, SimpleVarAllocator, get_amo_encoder

ChannelMode = Literal["full", "one_sided"]


class OrderEncoding(BMPEncoder):
    """Order / Threshold-based SAT Encoding for BMP.

    Variables:
        Order variables y[v, t]: True iff label p(v) >= t (for 2 <= t <= n).
        Exact-value channeling variables x[v, p]: True iff p(v) == p.
        - Default (``compact_boundary=False``): x[v, p] for all 1 <= p <= n.
        - ``compact_boundary=True``: omits x[v, 1] and x[v, n] by reusing
          ``-y[v, 2]`` and ``y[v, n]`` directly inside occupancy AMO, saving
          ``2n`` variables and boundary channeling clauses.

    Channeling constraints (``channel_mode``):
        - ``full`` (default): biconditional x[v,p] <-> (y[v,p] and not y[v,p+1]).
        - ``one_sided``: implies-only (y[v,p] and not y[v,p+1]) -> x[v,p], reducing
          channeling clauses by ~3x while remaining exact under monotone AllDiff AMO.
    """

    def __init__(
        self,
        amo: str | AMOEncoder = "pairwise",
        *,
        channel_mode: ChannelMode = "full",
        compact_boundary: bool = False,
    ) -> None:
        if isinstance(amo, str):
            self._amo_encoder: AMOEncoder = get_amo_encoder(amo)
            self._amo_name = amo.lower()
        else:
            self._amo_encoder = amo
            self._amo_name = getattr(amo, "name", type(amo).__name__)

        self._channel_mode = channel_mode.lower()
        if self._channel_mode not in ("full", "one_sided"):
            raise ValueError(f"Unsupported channel_mode: {channel_mode!r}")
        self._compact_boundary = bool(compact_boundary)

    @property
    def name(self) -> str:
        if self._channel_mode == "full" and not self._compact_boundary:
            return f"order_{self._amo_name}"
        b_tag = "compactb" if self._compact_boundary else "fullb"
        return f"order_{self._amo_name}_{self._channel_mode}_{b_tag}"

    @property
    def amo_name(self) -> str:
        return self._amo_name

    @property
    def channel_mode(self) -> str:
        return self._channel_mode

    @property
    def compact_boundary(self) -> bool:
        return self._compact_boundary

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
        """Variable ID for exact channeling variable x[v, p] (p(v) == p)."""
        if not (0 <= v_idx < n):
            raise ValueError(f"v_idx out of bounds: {v_idx} for n={n}")
        if not (1 <= p <= n):
            raise ValueError(f"Label p out of bounds: {p} for n={n}")
        offset = n * (n - 1)
        if self._compact_boundary:
            if p == 1 or p == n:
                raise ValueError(f"Boundary label p={p} uses literal directly when compact_boundary=True")
            return offset + v_idx * (n - 2) + (p - 1)
        return offset + v_idx * n + p

    def _label_literal(self, v_idx: int, p: int, n: int) -> int:
        """Literal representing p(v) == p (positive for true assignment)."""
        if self._compact_boundary:
            if p == 1:
                return -self.var_y(v_idx, 2, n)
            if p == n:
                return self.var_y(v_idx, n, n)
        return self.var_x(v_idx, p, n)

    def encode_fixed(self, graph: Graph, **kwargs: object) -> CNFFormula:
        """Generate fixed k-independent clauses (monotonicity, channeling, injectivity)."""
        started = monotonic()
        n = graph.order
        if n <= 1:
            return CNFFormula(build_time_s=monotonic() - started)

        v_map = self._vertex_index_map(graph)
        num_y_vars = n * (n - 1)
        num_chan_vars = n * (n - 2) if self._compact_boundary else n * n
        num_orig_vars = num_y_vars + num_chan_vars
        allocator = SimpleVarAllocator(start_id=num_orig_vars + 1)
        clauses: list[list[int]] = []
        one_sided = self._channel_mode == "one_sided"

        # 1. Monotonicity: y[v, t+1] -> y[v, t]
        for v in graph.vertices:
            v_idx = v_map[v]
            for t in range(2, n):
                clauses.append([-self.var_y(v_idx, t + 1, n), self.var_y(v_idx, t, n)])

        # 2. Channeling with exact variables x[v, p]
        for v in graph.vertices:
            v_idx = v_map[v]
            if not self._compact_boundary:
                y2 = self.var_y(v_idx, 2, n)
                x1 = self.var_x(v_idx, 1, n)
                if not one_sided:
                    clauses.append([-x1, -y2])
                clauses.append([x1, y2])

            for p in range(2, n):
                xp = self.var_x(v_idx, p, n)
                yp = self.var_y(v_idx, p, n)
                yp_next = self.var_y(v_idx, p + 1, n)
                if not one_sided:
                    clauses.append([-xp, yp])
                    clauses.append([-xp, -yp_next])
                clauses.append([-yp, yp_next, xp])

            if not self._compact_boundary:
                yn = self.var_y(v_idx, n, n)
                xn = self.var_x(v_idx, n, n)
                if not one_sided:
                    clauses.append([-xn, yn])
                clauses.append([xn, -yn])

        # 3. Injectivity: At-Most-One vertex per label p in 1..n
        v_indices = [v_map[v] for v in graph.vertices]
        for p in range(1, n + 1):
            lits = [self._label_literal(v_idx, p, n) for v_idx in v_indices]
            amo_clauses, _ = self._amo_encoder.encode(lits, allocator)
            clauses.extend(amo_clauses)

        # 4. Optional Reversal Symmetry Breaking: p(anchor) <= ceil(n / 2)
        if kwargs.get("symmetry_breaking", False) and n >= 2:
            from bmp.solvers.sat.search import select_anchor_vertex

            anchor = select_anchor_vertex(graph)
            a_idx = v_map[anchor]
            cutoff = (n + 1) // 2
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
            comments=[
                f"OrderEncoding fixed clauses (n={n}, amo={self._amo_name}, "
                f"channel={self._channel_mode}, compact_boundary={self._compact_boundary})"
            ],
        )

    def encode_bandwidth_step(self, graph: Graph, k: int, **kwargs: object) -> list[list[int]]:
        """Generate clauses enforcing bandwidth <= k using order variables."""
        n = graph.order
        if n <= 1 or not graph.edges or k >= n - 1:
            return []

        v_map = self._vertex_index_map(graph)
        clauses: list[list[int]] = []
        stride = n - 1

        for u, v in graph.edges:
            u_base = v_map[u] * stride
            v_base = v_map[v] * stride
            for t in range(2, n - k + 1):
                y_u_tk = u_base + (t + k - 1)
                y_v_t = v_base + (t - 1)
                y_v_tk = v_base + (t + k - 1)
                y_u_t = u_base + (t - 1)
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
            label = 1
            for t in range(2, n + 1):
                if self.var_y(v_idx, t, n) in model_set:
                    label += 1
                else:
                    break
            assignment[v] = label

        return assignment


__all__ = ["ChannelMode", "OrderEncoding"]
