"""Pairwise / Basic Position SAT Encoding for Bandwidth Minimization Problem."""

from __future__ import annotations

from time import monotonic
from typing import Literal, Sequence

from bmp.core.graph import Graph
from bmp.encodings.base import BMPEncoder, CNFFormula
from bmp.encodings.cardinality.base import AMOEncoder, SimpleVarAllocator, get_amo_encoder

OccupancyMode = Literal["both", "pigeonhole"]
BandwidthMode = Literal["conflict", "support", "support_single"]


class PairwiseEncoding(BMPEncoder):
    """Pairwise / Position-based SAT Encoding for BMP.

    Variables:
        x[v, p]: vertex v receives label p (1 <= p <= n).
        Variable index: 1-based, v * n + p, where v in 0..n-1, p in 1..n.

    Constraints:
        1. Vertex assignment (``occupancy_mode``):
           - ``both`` (default): ALO + AMO per vertex and AMO per label.
           - ``pigeonhole``: ALO per vertex + AMO per label (bijection forced by
             pigeonhole principle, saving n AMO blocks and auxiliary variables).
        2. Bandwidth <= k (``bandwidth_mode``):
           - ``conflict`` (default): binary nogoods (not x[u,p] or not x[v,q]) for |p-q| > k.
           - ``support``: bidirectional support clauses x[u,p] -> OR_{|q-p|<=k} x[v,q]
             and symmetric v -> u whenever a label has forbidden neighbors.
           - ``support_single``: unidirectional support u -> v (exact under bijection).
    """

    def __init__(
        self,
        amo: str | AMOEncoder = "pairwise",
        *,
        occupancy_mode: OccupancyMode = "both",
        bandwidth_mode: BandwidthMode = "conflict",
    ) -> None:
        if isinstance(amo, str):
            self._amo_encoder: AMOEncoder = get_amo_encoder(amo)
            self._amo_name = amo.lower()
        else:
            self._amo_encoder = amo
            self._amo_name = getattr(amo, "name", type(amo).__name__)

        self._occupancy_mode = occupancy_mode.lower()
        if self._occupancy_mode not in ("both", "pigeonhole"):
            raise ValueError(f"Unsupported occupancy_mode: {occupancy_mode!r}")

        self._bandwidth_mode = bandwidth_mode.lower()
        if self._bandwidth_mode not in ("conflict", "support", "support_single"):
            raise ValueError(f"Unsupported bandwidth_mode: {bandwidth_mode!r}")

    @property
    def name(self) -> str:
        if self._occupancy_mode == "both" and self._bandwidth_mode == "conflict":
            return f"pairwise_{self._amo_name}"
        return f"pairwise_{self._amo_name}_{self._occupancy_mode}_{self._bandwidth_mode}"

    @property
    def amo_name(self) -> str:
        return self._amo_name

    @property
    def occupancy_mode(self) -> str:
        return self._occupancy_mode

    @property
    def bandwidth_mode(self) -> str:
        return self._bandwidth_mode

    def _vertex_index_map(self, graph: Graph) -> dict[int, int]:
        """Map graph vertices (arbitrary unique ints) to contiguous 0..n-1."""
        return {v: i for i, v in enumerate(graph.vertices)}

    def var_x(self, v_idx: int, p: int, n: int) -> int:
        """1-based variable ID for vertex index v_idx and label p (1..n)."""
        if not (0 <= v_idx < n):
            raise ValueError(f"v_idx out of bounds: {v_idx} for n={n}")
        if not (1 <= p <= n):
            raise ValueError(f"Label p out of bounds: {p} for n={n}")
        return v_idx * n + p

    def encode_fixed(self, graph: Graph, **kwargs: object) -> CNFFormula:
        """Generate fixed k-independent clauses (ALO, AMO on vertices/labels)."""
        started = monotonic()
        n = graph.order
        if n == 0:
            return CNFFormula(build_time_s=monotonic() - started)

        v_map = self._vertex_index_map(graph)
        num_orig_vars = n * n
        allocator = SimpleVarAllocator(start_id=num_orig_vars + 1)
        clauses: list[list[int]] = []

        # 1. Per-vertex ALO (and optional AMO when occupancy_mode == 'both')
        need_vertex_amo = self._occupancy_mode == "both"
        for v in graph.vertices:
            v_idx = v_map[v]
            lits = [self.var_x(v_idx, p, n) for p in range(1, n + 1)]
            clauses.append(lits)
            if need_vertex_amo:
                amo_clauses, _ = self._amo_encoder.encode(lits, allocator)
                clauses.extend(amo_clauses)

        # 2. All-Different: At-Most-One vertex per label
        for p in range(1, n + 1):
            lits = [self.var_x(v_map[v], p, n) for v in graph.vertices]
            amo_clauses, _ = self._amo_encoder.encode(lits, allocator)
            clauses.extend(amo_clauses)

        # 3. Optional Reversal Symmetry Breaking: p(anchor) <= ceil(n / 2)
        if kwargs.get("symmetry_breaking", False) and n >= 2:
            from bmp.solvers.sat.search import select_anchor_vertex

            anchor = select_anchor_vertex(graph)
            a_idx = v_map[anchor]
            cutoff = (n + 1) // 2  # ceil(n / 2)
            for p in range(cutoff + 1, n + 1):
                clauses.append([-self.var_x(a_idx, p, n)])

        top_var = allocator.next_id - 1
        num_aux_vars = top_var - num_orig_vars

        return CNFFormula(
            clauses=clauses,
            top_var=top_var,
            num_original_vars=num_orig_vars,
            num_aux_vars=num_aux_vars,
            build_time_s=monotonic() - started,
            comments=[
                f"PairwiseEncoding fixed clauses (n={n}, amo={self._amo_name}, "
                f"occ={self._occupancy_mode}, bw={self._bandwidth_mode})"
            ],
        )

    def encode_bandwidth_step(self, graph: Graph, k: int, **kwargs: object) -> list[list[int]]:
        """Generate clauses enforcing bandwidth <= k."""
        n = graph.order
        if n <= 1 or not graph.edges or k >= n - 1:
            return []

        v_map = self._vertex_index_map(graph)
        clauses: list[list[int]] = []

        if self._bandwidth_mode == "conflict":
            for u, v in graph.edges:
                u_idx = v_map[u]
                v_idx = v_map[v]
                base_u = u_idx * n
                base_v = v_idx * n
                for p in range(1, n + 1):
                    lit_u = -(base_u + p)
                    low_end = p - k
                    if low_end > 1:
                        for q in range(1, low_end):
                            clauses.append([lit_u, -(base_v + q)])
                    high_start = p + k + 1
                    if high_start <= n:
                        for q in range(high_start, n + 1):
                            clauses.append([lit_u, -(base_v + q)])
            return clauses

        bidirectional = self._bandwidth_mode == "support"
        append_clause = clauses.append
        for u, v in graph.edges:
            base_u = v_map[u] * n
            base_v = v_map[v] * n
            for p in range(1, n + 1):
                lo = p - k if p > k + 1 else 1
                hi = p + k if p + k < n else n
                if lo == 1 and hi == n:
                    continue
                append_clause([-(base_u + p), *range(base_v + lo, base_v + hi + 1)])
                if bidirectional:
                    append_clause([-(base_v + p), *range(base_u + lo, base_u + hi + 1)])
        return clauses

    def encode_bandwidth_diff(self, graph: Graph, k_new: int, k_old: int) -> list[list[int]]:
        """Generate only new clauses required when tightening bound from k_old down to k_new."""
        if k_new >= k_old:
            return []
        if self._bandwidth_mode != "conflict":
            return self.encode_bandwidth_step(graph, k_new)

        n = graph.order
        if n <= 1 or not graph.edges:
            return []

        v_map = self._vertex_index_map(graph)
        clauses: list[list[int]] = []

        for u, v in graph.edges:
            u_idx = v_map[u]
            v_idx = v_map[v]
            base_u = u_idx * n
            base_v = v_idx * n
            for p in range(1, n + 1):
                lit_u = -(base_u + p)
                l_start = max(1, p - k_old)
                l_end = min(n, p - k_new - 1)
                for q in range(l_start, l_end + 1):
                    clauses.append([lit_u, -(base_v + q)])
                r_start = max(1, p + k_new + 1)
                r_end = min(n, p + k_old)
                for q in range(r_start, r_end + 1):
                    clauses.append([lit_u, -(base_v + q)])
        return clauses

    def encode(self, graph: Graph, k: int, **kwargs: object) -> CNFFormula:
        """Generate full CNF formula for graph G and bandwidth k."""
        started = monotonic()
        formula = self.encode_fixed(graph, **kwargs)
        bw_clauses = self.encode_bandwidth_step(graph, k, **kwargs)
        formula.extend_clauses(bw_clauses)
        formula.build_time_s = monotonic() - started
        formula.comments.append(f"PairwiseEncoding full (k={k}, num_bw_clauses={len(bw_clauses)})")
        return formula

    def decode(self, graph: Graph, model: Sequence[int], k: int) -> dict[int, int]:
        """Decode SAT model into mapping: vertex -> label (1..n)."""
        n = graph.order
        if n == 0:
            return {}
        v_map = self._vertex_index_map(graph)
        model_set = set(model)
        assignment: dict[int, int] = {}

        for v in graph.vertices:
            v_idx = v_map[v]
            assigned_label = None
            for p in range(1, n + 1):
                var = self.var_x(v_idx, p, n)
                if var in model_set:
                    assigned_label = p
                    break
            if assigned_label is None:
                raise ValueError(f"Vertex {v} (idx {v_idx}) has no assigned label in SAT model")
            assignment[v] = assigned_label

        return assignment


__all__ = ["BandwidthMode", "OccupancyMode", "PairwiseEncoding"]
