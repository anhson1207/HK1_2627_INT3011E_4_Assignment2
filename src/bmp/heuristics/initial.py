"""Shared initial labelings, dual representation, and incremental DRSA/SA state."""

from __future__ import annotations

from dataclasses import dataclass
import math
from random import Random
from typing import Mapping, Sequence

from bmp.core.bounds import cuthill_mckee_order, identity_upper_bound
from bmp.core.graph import Graph
from bmp.core.validation import calculate_bandwidth, validate_assignment

INITIAL_MODES: tuple[str, ...] = (
    "random",
    "identity",
    "cm",
    "rcm",
    "best_initial",
)

# Strictly below 1.0 in IEEE-754 float64 so b + delta < b + 1 always holds even on K_n (n >= 22).
_MAX_DELTA: float = math.nextafter(1.0, 0.0)


def compute_fractional_delta_from_histogram(
    histogram: Sequence[int], bandwidth: int, order: int
) -> float:
    """Compute Torres-Jimenez et al. (2015) Algorithm 4 fractional score ``delta in [0, 1)``.

    Implements the continued-fraction / Horner evaluation over edge distance counts
    ``d[0..bandwidth]`` with variable-base capacities ``v[i] = order + 1 - i``:

        delta = 0
        for i in 0..bandwidth:
            delta = (delta + d[i]) / (order + 1 - i)

    For edgeless graphs (``bandwidth == 0``), returns ``0.0``.
    """
    if bandwidth <= 0 or order <= 0:
        return 0.0
    delta = 0.0
    base_top = order + 1
    for i in range(bandwidth + 1):
        delta = (delta + histogram[i]) / (base_top - i)
    if delta >= 1.0:
        delta = _MAX_DELTA
    elif delta < 0.0:
        delta = 0.0
    return delta


def _combine_bw_delta(bandwidth: int, delta: float) -> float:
    """Combine integer bandwidth and fractional delta while preserving f < bandwidth + 1."""
    if delta < 0.999:
        return float(bandwidth) + delta
    nxt = float(bandwidth + 1)
    val = float(bandwidth) + delta
    return math.nextafter(nxt, 0.0) if val >= nxt else val


def evaluate_solution_components(
    graph: Graph,
    permutation: Mapping[int, int],
    *,
    evaluation_mode: str = "paper",
) -> tuple[int, float, float, list[int]]:
    """Compute ``(bandwidth, delta, f_value, histogram_d)`` from scratch and validate mode."""
    if evaluation_mode not in ("paper", "bandwidth_only"):
        raise ValueError(f"Unsupported evaluation_mode: {evaluation_mode!r}")
    report = validate_assignment(graph, permutation)
    if not report.valid:
        raise ValueError(f"Invalid permutation: {'; '.join(report.errors)}")

    n = graph.order
    hist = [0] * max(1, n)
    bw = 0
    for u, v in graph.edges:
        diff = abs(permutation[u] - permutation[v])
        hist[diff] += 1
        if diff > bw:
            bw = diff

    delta = (
        compute_fractional_delta_from_histogram(hist, bw, n)
        if evaluation_mode == "paper"
        else 0.0
    )
    return bw, delta, _combine_bw_delta(bw, delta), hist


def p_to_q_mapping(vertices: Sequence[int], p_map: Mapping[int, int]) -> dict[int, int]:
    """Convert vertex->label ``p`` (1-based labels) into label->vertex ``q``."""
    return {int(p_map[v]): v for v in vertices}


def q_to_p_mapping(q_map: Mapping[int, int]) -> dict[int, int]:
    """Convert label->vertex ``q`` (1-based labels) into vertex->label ``p``."""
    return {v: int(label) for label, v in q_map.items()}


@dataclass
class DualRepresentation:
    """Explicit dual labeling ``(p, q)`` with 0-based dense arrays and 1-based BMP views.

    - ``p_slots[slot]`` stores 0-based label ``0..n-1`` of vertex ``vertices[slot]``.
    - ``q_slots[label0]`` stores dense vertex slot ``0..n-1`` assigned label ``label0 + 1``.
    Invariants maintained after every operation:
        ``p_slots[q_slots[i]] == i`` and ``q_slots[p_slots[s]] == s``.
    """

    vertices: tuple[int, ...]
    vertex_to_slot: dict[int, int]
    p_slots: list[int]
    q_slots: list[int]

    @classmethod
    def from_p(cls, graph: Graph, p_map: Mapping[int, int]) -> DualRepresentation:
        report = validate_assignment(graph, p_map)
        if not report.valid:
            raise ValueError(f"Invalid p representation: {'; '.join(report.errors)}")
        vertices = graph.vertices
        v_to_slot = {v: idx for idx, v in enumerate(vertices)}
        n = len(vertices)
        p_slots = [int(p_map[v]) - 1 for v in vertices]
        q_slots = [0] * n
        for slot, lbl0 in enumerate(p_slots):
            q_slots[lbl0] = slot
        rep = cls(vertices=vertices, vertex_to_slot=v_to_slot, p_slots=p_slots, q_slots=q_slots)
        rep.validate()
        return rep

    @classmethod
    def from_q(cls, graph: Graph, q_map: Mapping[int, int]) -> DualRepresentation:
        n = graph.order
        expected_labels = set(range(1, n + 1))
        if set(q_map.keys()) != expected_labels:
            raise ValueError("Invalid q representation: labels must be 1..n")
        p_map = q_to_p_mapping(q_map)
        return cls.from_p(graph, p_map)

    @property
    def order(self) -> int:
        return len(self.vertices)

    def p_map(self) -> dict[int, int]:
        """Return external 1-based ``p[vertex] = label`` mapping."""
        return {v: self.p_slots[idx] + 1 for idx, v in enumerate(self.vertices)}

    def q_map(self) -> dict[int, int]:
        """Return external 1-based ``q[label] = vertex`` mapping."""
        return {lbl0 + 1: self.vertices[slot] for lbl0, slot in enumerate(self.q_slots)}

    def validate(self) -> None:
        """Verify strict inverse bijection invariants between ``p`` and ``q``."""
        n = len(self.vertices)
        if len(self.p_slots) != n or len(self.q_slots) != n:
            raise AssertionError("DualRepresentation length mismatch with graph order")
        seen_labels: set[int] = set()
        seen_slots: set[int] = set()
        for s in range(n):
            lbl = self.p_slots[s]
            if not (0 <= lbl < n):
                raise AssertionError(f"Out-of-range label {lbl} at slot {s}")
            seen_labels.add(lbl)
            if self.q_slots[lbl] != s:
                raise AssertionError(f"Inverse violation: q[p[{s}]]={self.q_slots[lbl]} != {s}")
        for lbl in range(n):
            slot = self.q_slots[lbl]
            if not (0 <= slot < n):
                raise AssertionError(f"Out-of-range slot {slot} at label {lbl}")
            seen_slots.add(slot)
            if self.p_slots[slot] != lbl:
                raise AssertionError(f"Inverse violation: p[q[{lbl}]]={self.p_slots[slot]} != {lbl}")
        if len(seen_labels) != n or len(seen_slots) != n:
            raise AssertionError("DualRepresentation duplicate entries detected")

        ext_p = self.p_map()
        ext_q = self.q_map()
        for v in self.vertices:
            if ext_q[ext_p[v]] != v:
                raise AssertionError("External q[p[v]] != v violation")
        for lbl in range(1, n + 1):
            if ext_p[ext_q[lbl]] != lbl:
                raise AssertionError("External p[q[label]] != label violation")

    def rex_swap_slots(self, u_slot: int, v_slot: int) -> None:
        """Swap labels of vertex slots ``u_slot`` and ``v_slot`` in ``p`` and propagate to ``q``."""
        if u_slot == v_slot:
            return
        lu = self.p_slots[u_slot]
        lv = self.p_slots[v_slot]
        self.p_slots[u_slot] = lv
        self.p_slots[v_slot] = lu
        self.q_slots[lu] = v_slot
        self.q_slots[lv] = u_slot

    def rot_left_labels(self, i: int, j: int) -> None:
        """Move element at 0-based label ``i`` of ``q`` to ``j`` and shift ``i+1..j`` left by 1."""
        if not (0 <= i < j < len(self.q_slots)):
            raise ValueError(f"Invalid ROT indices i={i}, j={j} for n={len(self.q_slots)}")
        moved = self.q_slots[i]
        for pos in range(i, j):
            nxt = self.q_slots[pos + 1]
            self.q_slots[pos] = nxt
            self.p_slots[nxt] = pos
        self.q_slots[j] = moved
        self.p_slots[moved] = j

    def undo_rot_left_labels(self, i: int, j: int) -> None:
        """Restore exact state before ``rot_left_labels(i, j)`` without copying arrays."""
        moved = self.q_slots[j]
        for pos in range(j, i, -1):
            prv = self.q_slots[pos - 1]
            self.q_slots[pos] = prv
            self.p_slots[prv] = pos
        self.q_slots[i] = moved
        self.p_slots[moved] = i


def build_initial_permutation(
    graph: Graph,
    *,
    mode: str = "rcm",
    rng: Random | None = None,
    initial_permutation: Mapping[int, int] | None = None,
) -> tuple[dict[int, int], int, str]:
    """Build and independently validate an initial permutation under a clear policy."""
    if initial_permutation is not None:
        report = validate_assignment(graph, initial_permutation)
        if not report.valid or report.actual_bandwidth is None:
            raise ValueError(f"Invalid initial_permutation: {'; '.join(report.errors)}")
        return dict(initial_permutation), report.actual_bandwidth, "explicit"

    mode_norm = mode.lower()
    if mode_norm not in INITIAL_MODES:
        raise ValueError(f"Unsupported initial_mode {mode!r}; expected one of {INITIAL_MODES}")

    n = graph.order
    if n == 0:
        return {}, 0, mode_norm

    if mode_norm == "identity":
        bw, perm = identity_upper_bound(graph)
        return perm, bw, "identity"

    if mode_norm == "cm":
        order = cuthill_mckee_order(graph)
        perm = {v: idx for idx, v in enumerate(order, start=1)}
        return perm, calculate_bandwidth(graph, perm), "cm"

    if mode_norm == "rcm":
        order = cuthill_mckee_order(graph)
        perm = {v: idx for idx, v in enumerate(reversed(order), start=1)}
        return perm, calculate_bandwidth(graph, perm), "rcm"

    if mode_norm == "best_initial":
        best_bw, best_perm = identity_upper_bound(graph)
        order = cuthill_mckee_order(graph)
        for cand_order in (order, list(reversed(order))):
            cand = {v: idx for idx, v in enumerate(cand_order, start=1)}
            cand_bw = calculate_bandwidth(graph, cand)
            if cand_bw < best_bw:
                best_bw, best_perm = cand_bw, cand
        return best_perm, best_bw, "best_initial"

    # mode_norm == "random"
    active_rng = rng if rng is not None else Random(0)
    labels = list(range(1, n + 1))
    active_rng.shuffle(labels)
    perm = {v: lbl for v, lbl in zip(graph.vertices, labels, strict=True)}
    return perm, calculate_bandwidth(graph, perm), "random"


class IncrementalBandwidthState:
    """Fast dual-representation state with deduplicated delta updates and exact rollback.

    Maintains edge lengths ``edge_len[0..m-1]``, distance histogram ``hist[0..n-1]``,
    current bandwidth, and Algorithm 4 fractional score ``delta``.
    """

    def __init__(
        self,
        graph: Graph,
        initial_p: Mapping[int, int],
        *,
        evaluation_mode: str = "paper",
        use_incremental: bool = True,
    ) -> None:
        if evaluation_mode not in ("paper", "bandwidth_only"):
            raise ValueError(f"Unsupported evaluation_mode: {evaluation_mode!r}")
        self.graph = graph
        self.n = graph.order
        self.evaluation_mode = evaluation_mode
        self.use_incremental = use_incremental

        self.dual = DualRepresentation.from_p(graph, initial_p)
        v_to_slot = self.dual.vertex_to_slot
        p_slots = self.dual.p_slots

        edges_u: list[int] = []
        edges_v: list[int] = []
        adj_tmp: list[list[tuple[int, int]]] = [[] for _ in range(self.n)]
        for e_idx, (u, v) in enumerate(graph.edges):
            us = v_to_slot[u]
            vs = v_to_slot[v]
            edges_u.append(us)
            edges_v.append(vs)
            adj_tmp[us].append((e_idx, vs))
            adj_tmp[vs].append((e_idx, us))

        self.m = len(edges_u)
        self.edge_u = tuple(edges_u)
        self.edge_v = tuple(edges_v)
        self.adj_edges: tuple[tuple[tuple[int, int], ...], ...] = tuple(
            tuple(row) for row in adj_tmp
        )
        self.adj_neighbors: tuple[tuple[int, ...], ...] = tuple(
            tuple(nbr for _, nbr in row) for row in adj_tmp
        )
        self.non_isolated_slots: tuple[int, ...] = tuple(
            s for s in range(self.n) if adj_tmp[s]
        )

        self.edge_len: list[int] = [0] * self.m
        self.hist: list[int] = [0] * max(1, self.n)
        self._edge_stamp: list[int] = [0] * self.m
        self._stamp_id: int = 0

        bw = 0
        for e_idx in range(self.m):
            dist = abs(p_slots[self.edge_u[e_idx]] - p_slots[self.edge_v[e_idx]])
            self.edge_len[e_idx] = dist
            self.hist[dist] += 1
            if dist > bw:
                bw = dist

        self.bandwidth: int = bw
        self.delta: float = (
            compute_fractional_delta_from_histogram(self.hist, bw, self.n)
            if self.evaluation_mode == "paper"
            else 0.0
        )
        self.f_value: float = _combine_bw_delta(bw, self.delta)

    def recompute_from_scratch(self) -> tuple[int, float, float, list[int]]:
        """Recompute bandwidth, delta, and histogram independently from current ``p_slots``."""
        p_slots = self.dual.p_slots
        hist = [0] * max(1, self.n)
        bw = 0
        for e_idx in range(self.m):
            dist = abs(p_slots[self.edge_u[e_idx]] - p_slots[self.edge_v[e_idx]])
            hist[dist] += 1
            if dist > bw:
                bw = dist
        delta = (
            compute_fractional_delta_from_histogram(hist, bw, self.n)
            if self.evaluation_mode == "paper"
            else 0.0
        )
        return bw, delta, _combine_bw_delta(bw, delta), hist

    def assert_synced(self) -> None:
        """Verify incremental state equals full recomputation and dual invariants hold."""
        self.dual.validate()
        bw, delta, f_val, hist = self.recompute_from_scratch()
        if bw != self.bandwidth:
            raise AssertionError(f"Bandwidth desync: incremental={self.bandwidth} vs full={bw}")
        if self.hist != hist:
            raise AssertionError("Histogram desync detected")
        if abs(delta - self.delta) > 1e-12 or abs(f_val - self.f_value) > 1e-12:
            raise AssertionError(
                f"Evaluation desync: inc=({self.delta}, {self.f_value}) vs full=({delta}, {f_val})"
            )

    def _finish_full_update(self) -> list[tuple[int, int, int]]:
        p_slots = self.dual.p_slots
        hist = self.hist
        for k in range(len(hist)):
            hist[k] = 0
        bw = 0
        for e_idx in range(self.m):
            dist = abs(p_slots[self.edge_u[e_idx]] - p_slots[self.edge_v[e_idx]])
            self.edge_len[e_idx] = dist
            hist[dist] += 1
            if dist > bw:
                bw = dist
        self.bandwidth = bw
        self.delta = (
            compute_fractional_delta_from_histogram(hist, bw, self.n)
            if self.evaluation_mode == "paper"
            else 0.0
        )
        self.f_value = _combine_bw_delta(bw, self.delta)
        return []

    def _recompute_bw_from_hist(self, prev_bw: int, max_added: int) -> int:
        if max_added > prev_bw:
            return max_added
        hist = self.hist
        if hist[prev_bw] > 0:
            return prev_bw
        bw = prev_bw - 1
        while bw > 0 and hist[bw] == 0:
            bw -= 1
        return bw

    def apply_swap_p(self, u_slot: int, v_slot: int) -> tuple[int, float, list[tuple[int, int, int]]]:
        """Swap labels of ``u_slot`` and ``v_slot`` in ``p``, returning rollback token."""
        prev_bw = self.bandwidth
        prev_delta = self.delta
        if u_slot == v_slot:
            return prev_bw, prev_delta, []

        self.dual.rex_swap_slots(u_slot, v_slot)
        if not self.use_incremental:
            return prev_bw, prev_delta, self._finish_full_update()

        p_slots = self.dual.p_slots
        edge_len = self.edge_len
        hist = self.hist
        lu = p_slots[u_slot]
        lv = p_slots[v_slot]

        changed: list[tuple[int, int, int]] = []
        max_added = 0

        # Skip edge (u_slot, v_slot) if adjacent because |p[u] - p[v]| is unchanged.
        for e_idx, nbr in self.adj_edges[u_slot]:
            if nbr == v_slot:
                continue
            old_len = edge_len[e_idx]
            new_len = abs(lu - p_slots[nbr])
            if new_len != old_len:
                hist[old_len] -= 1
                hist[new_len] += 1
                edge_len[e_idx] = new_len
                changed.append((e_idx, old_len, new_len))
                if new_len > max_added:
                    max_added = new_len

        for e_idx, nbr in self.adj_edges[v_slot]:
            if nbr == u_slot:
                continue
            old_len = edge_len[e_idx]
            new_len = abs(lv - p_slots[nbr])
            if new_len != old_len:
                hist[old_len] -= 1
                hist[new_len] += 1
                edge_len[e_idx] = new_len
                changed.append((e_idx, old_len, new_len))
                if new_len > max_added:
                    max_added = new_len

        new_bw = self._recompute_bw_from_hist(prev_bw, max_added)
        self.bandwidth = new_bw
        self.delta = (
            compute_fractional_delta_from_histogram(hist, new_bw, self.n)
            if self.evaluation_mode == "paper"
            else 0.0
        )
        self.f_value = _combine_bw_delta(new_bw, self.delta)
        return prev_bw, prev_delta, changed

    def undo_swap_p(
        self, u_slot: int, v_slot: int, token: tuple[int, float, list[tuple[int, int, int]]]
    ) -> None:
        """Revert ``apply_swap_p`` without full array copies."""
        prev_bw, prev_delta, changed = token
        if u_slot == v_slot:
            return
        self.dual.rex_swap_slots(u_slot, v_slot)
        if not self.use_incremental:
            self._finish_full_update()
            return
        edge_len = self.edge_len
        hist = self.hist
        for e_idx, old_len, new_len in changed:
            edge_len[e_idx] = old_len
            hist[new_len] -= 1
            hist[old_len] += 1
        self.bandwidth = prev_bw
        self.delta = prev_delta
        self.f_value = _combine_bw_delta(prev_bw, prev_delta)

    def apply_rot_q(self, i: int, j: int) -> tuple[int, float, list[tuple[int, int, int]]]:
        """Rotate ``q[i..j]`` left (move ``q[i]`` to ``j``) and return rollback token."""
        prev_bw = self.bandwidth
        prev_delta = self.delta
        if i == j:
            return prev_bw, prev_delta, []

        self.dual.rot_left_labels(i, j)
        if not self.use_incremental:
            return prev_bw, prev_delta, self._finish_full_update()

        self._stamp_id += 1
        stamp = self._stamp_id
        edge_stamp = self._edge_stamp
        edge_len = self.edge_len
        hist = self.hist
        p_slots = self.dual.p_slots
        edge_u = self.edge_u
        edge_v = self.edge_v
        q_slots = self.dual.q_slots

        changed: list[tuple[int, int, int]] = []
        max_added = 0

        for lbl in range(i, j + 1):
            slot = q_slots[lbl]
            for e_idx, _ in self.adj_edges[slot]:
                if edge_stamp[e_idx] == stamp:
                    continue
                edge_stamp[e_idx] = stamp
                old_len = edge_len[e_idx]
                new_len = abs(p_slots[edge_u[e_idx]] - p_slots[edge_v[e_idx]])
                if new_len != old_len:
                    hist[old_len] -= 1
                    hist[new_len] += 1
                    edge_len[e_idx] = new_len
                    changed.append((e_idx, old_len, new_len))
                    if new_len > max_added:
                        max_added = new_len

        new_bw = self._recompute_bw_from_hist(prev_bw, max_added)
        self.bandwidth = new_bw
        self.delta = (
            compute_fractional_delta_from_histogram(hist, new_bw, self.n)
            if self.evaluation_mode == "paper"
            else 0.0
        )
        self.f_value = _combine_bw_delta(new_bw, self.delta)
        return prev_bw, prev_delta, changed

    def undo_rot_q(
        self, i: int, j: int, token: tuple[int, float, list[tuple[int, int, int]]]
    ) -> None:
        """Revert ``apply_rot_q`` without full array copies."""
        prev_bw, prev_delta, changed = token
        if i == j:
            return
        self.dual.undo_rot_left_labels(i, j)
        if not self.use_incremental:
            self._finish_full_update()
            return
        edge_len = self.edge_len
        hist = self.hist
        for e_idx, old_len, new_len in changed:
            edge_len[e_idx] = old_len
            hist[new_len] -= 1
            hist[old_len] += 1
        self.bandwidth = prev_bw
        self.delta = prev_delta
        self.f_value = _combine_bw_delta(prev_bw, prev_delta)


__all__ = [
    "DualRepresentation",
    "INITIAL_MODES",
    "IncrementalBandwidthState",
    "build_initial_permutation",
    "compute_fractional_delta_from_histogram",
    "evaluate_solution_components",
    "p_to_q_mapping",
    "q_to_p_mapping",
]
