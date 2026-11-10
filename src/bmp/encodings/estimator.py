"""Analytical estimation and resource guards for CNF formula sizing."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isqrt
from typing import Mapping

from bmp.core.graph import Graph


@dataclass(frozen=True, slots=True)
class CNFSizeEstimate:
    """Analytical estimate of variable and clause counts for a BMP SAT encoding."""

    num_variables: int
    num_original_vars: int
    num_channeling_vars: int
    num_aux_vars: int
    num_clauses: int
    num_fixed_clauses: int
    num_bandwidth_clauses: int
    formula_breakdown: Mapping[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "num_variables": self.num_variables,
            "num_original_vars": self.num_original_vars,
            "num_channeling_vars": self.num_channeling_vars,
            "num_aux_vars": self.num_aux_vars,
            "num_clauses": self.num_clauses,
            "num_fixed_clauses": self.num_fixed_clauses,
            "num_bandwidth_clauses": self.num_bandwidth_clauses,
            "formula_breakdown": dict(self.formula_breakdown),
        }


@dataclass(frozen=True, slots=True)
class ResourceLimits:
    """Configurable safety limits to prevent out-of-memory or excessive solving."""

    max_variables: int | None = 500_000
    max_clauses: int | None = 2_500_000
    timeout_seconds: float | None = 300.0
    memory_limit_mb: float | None = None

    def check(self, estimate: CNFSizeEstimate) -> tuple[bool, str | None]:
        """Check if an estimate violates the configured limits.

        Returns (is_ok, violation_reason).
        """
        if self.max_variables is not None and estimate.num_variables > self.max_variables:
            return False, (
                f"Estimated variables ({estimate.num_variables:,}) exceeds "
                f"safety limit ({self.max_variables:,})"
            )
        if self.max_clauses is not None and estimate.num_clauses > self.max_clauses:
            return False, (
                f"Estimated clauses ({estimate.num_clauses:,}) exceeds "
                f"safety limit ({self.max_clauses:,})"
            )
        return True, None


def _binary_amo_counts(m: int) -> tuple[int, int]:
    """Return exact (aux_vars, clauses) for Binary AMO over m literals."""
    if m < 2:
        return 0, 0
    bits = (m - 1).bit_length()
    return bits, m * bits


def _commander_amo_counts(m: int) -> tuple[int, int]:
    """Return exact (aux_vars, clauses) for recursive group-3 Commander AMO over m literals."""
    if m < 2:
        return 0, 0
    if m <= 3:
        return 0, m * (m - 1) // 2
    aux = 0
    clauses = 0
    num_groups = 0
    for start in range(0, m, 3):
        group_size = min(3, m - start)
        clauses += group_size * (group_size - 1) // 2 + group_size
        aux += 1
        num_groups += 1
    sub_aux, sub_clauses = _commander_amo_counts(num_groups)
    return aux + sub_aux, clauses + sub_clauses


def _product_amo_counts(m: int) -> tuple[int, int]:
    """Return exact (aux_vars, clauses) for 2-Product AMO over m literals."""
    if m < 2:
        return 0, 0
    rows = isqrt(m - 1) + 1
    cols = (m + rows - 1) // rows
    aux = rows + cols
    clauses = 2 * m + rows * (rows - 1) // 2 + cols * (cols - 1) // 2
    return aux, clauses


def _ladder_amo_counts(m: int) -> tuple[int, int]:
    """Return exact (aux_vars, clauses) for Ladder AMO over m literals."""
    if m < 2:
        return 0, 0
    return m - 1, 3 * m - 4


def _single_amo_counts(amo_type: str, m: int, raw_amo: str) -> tuple[int, int]:
    """Return exact (aux_vars, clauses) for a single AMO constraint of width m."""
    if amo_type in ("pairwise", "naive"):
        return 0, m * (m - 1) // 2
    if amo_type in ("sequential", "seqcounter"):
        if m < 2:
            return 0, 0
        if m == 2:
            return 0, 1
        return m - 1, 3 * m - 4
    if amo_type == "binary":
        return _binary_amo_counts(m)
    if amo_type == "commander":
        return _commander_amo_counts(m)
    if amo_type == "product":
        return _product_amo_counts(m)
    if amo_type == "ladder":
        return _ladder_amo_counts(m)
    raise ValueError(f"Unsupported AMO type for estimation: {raw_amo}")


def estimate_cnf_size(
    graph: Graph,
    *,
    encoding: str = "pairwise",
    amo: str = "pairwise",
    k: int | None = None,
    symmetry_breaking: bool = False,
) -> CNFSizeEstimate:
    """Compute exact closed-form count of variables and clauses before CNF generation.

    Parameters:
        graph: Target Graph
        encoding: 'pairwise' or 'order'
        amo: 'pairwise', 'sequential', 'binary', 'commander', 'product', or 'ladder'
        k: Bandwidth threshold. If None, assumes worst-case (k=0 for maximum clauses)
        symmetry_breaking: Whether anchor vertex symmetry breaking is active
    """
    n = graph.order
    m = graph.size

    if n == 0 or (n == 1 and encoding.lower() == "order"):
        return CNFSizeEstimate(
            num_variables=0,
            num_original_vars=0,
            num_channeling_vars=0,
            num_aux_vars=0,
            num_clauses=0,
            num_fixed_clauses=0,
            num_bandwidth_clauses=0,
            formula_breakdown={"empty": 0},
        )

    if k is not None and k < 0:
        raise ValueError("Bandwidth threshold k cannot be negative")
    eval_k = 0 if k is None else min(k, n - 1)
    enc_family = encoding.lower()
    amo_type = amo.lower()

    aux_per_amo, clauses_per_amo = _single_amo_counts(amo_type, n, amo)

    if enc_family == "pairwise":
        num_orig = n * n
        num_chan = 0
        alo_clauses = n

        num_aux = 2 * n * aux_per_amo
        amo_vertex_clauses = n * clauses_per_amo
        amo_label_clauses = n * clauses_per_amo

        sym_clauses = 0
        if symmetry_breaking and n >= 2:
            cutoff = (n + 1) // 2
            sym_clauses = n - cutoff

        fixed_clauses = alo_clauses + amo_vertex_clauses + amo_label_clauses + sym_clauses

        # Bandwidth clauses: for each edge (u, v), pairs (p, q) with |p - q| > eval_k
        bw_pairs_per_edge = (n - eval_k) * (n - eval_k - 1) if eval_k < n else 0
        bw_clauses = m * bw_pairs_per_edge

        breakdown = {
            "alo_vertex": alo_clauses,
            "amo_vertex": amo_vertex_clauses,
            "amo_label_alldiff": amo_label_clauses,
            "symmetry_breaking": sym_clauses,
            "bandwidth": bw_clauses,
        }

        return CNFSizeEstimate(
            num_variables=num_orig + num_aux,
            num_original_vars=num_orig,
            num_channeling_vars=num_chan,
            num_aux_vars=num_aux,
            num_clauses=fixed_clauses + bw_clauses,
            num_fixed_clauses=fixed_clauses,
            num_bandwidth_clauses=bw_clauses,
            formula_breakdown=breakdown,
        )

    elif enc_family == "order":
        num_orig = n * (n - 1)  # y[v, t] for t in 2..n
        num_chan = n * n        # x[v, p] for p in 1..n

        # Monotonicity
        mono_clauses = n * (n - 2) if n >= 2 else 0

        # Channeling clauses
        chan_clauses = n * (3 * n - 2) if n >= 2 else 0

        # All-Different on channeled x[v, p]
        num_aux = n * aux_per_amo
        alldiff_clauses = n * clauses_per_amo

        sym_clauses = 1 if (symmetry_breaking and n >= 2) else 0
        fixed_clauses = mono_clauses + chan_clauses + alldiff_clauses + sym_clauses

        # Bandwidth clauses: for each edge, 2 * (n - eval_k - 1) binary clauses
        bw_per_edge = 2 * (n - eval_k - 1) if (eval_k < n - 1) else 0
        bw_clauses = m * bw_per_edge

        breakdown = {
            "order_monotonicity": mono_clauses,
            "order_channeling": chan_clauses,
            "alldiff_amo": alldiff_clauses,
            "symmetry_breaking": sym_clauses,
            "bandwidth": bw_clauses,
        }

        return CNFSizeEstimate(
            num_variables=num_orig + num_chan + num_aux,
            num_original_vars=num_orig,
            num_channeling_vars=num_chan,
            num_aux_vars=num_aux,
            num_clauses=fixed_clauses + bw_clauses,
            num_fixed_clauses=fixed_clauses,
            num_bandwidth_clauses=bw_clauses,
            formula_breakdown=breakdown,
        )

    else:
        raise ValueError(f"Unknown encoding family: {encoding}")


def estimate_incremental_cnf_size(
    graph: Graph,
    *,
    encoding: str,
    amo: str,
    initial_k: int,
    target_k: int,
    symmetry_breaking: bool = False,
) -> CNFSizeEstimate:
    """Cumulative count for unit steps; safe upper bound for adaptive jumps.

    Pairwise adds only new distance clauses. Order currently adds the full
    bandwidth formula at every tested threshold, including duplicate clauses.
    Summing the entire range overestimates Order when adaptive search jumps.
    """
    if target_k > initial_k or target_k < 0:
        raise ValueError("Require 0 <= target_k <= initial_k")
    current = estimate_cnf_size(
        graph, encoding=encoding, amo=amo, k=target_k,
        symmetry_breaking=symmetry_breaking,
    )
    if encoding.lower() != "order":
        return current
    added = sum(
        estimate_cnf_size(graph, encoding="order", amo=amo, k=step).num_bandwidth_clauses
        for step in range(target_k, initial_k + 1)
    )
    return CNFSizeEstimate(
        num_variables=current.num_variables,
        num_original_vars=current.num_original_vars,
        num_channeling_vars=current.num_channeling_vars,
        num_aux_vars=current.num_aux_vars,
        num_clauses=current.num_fixed_clauses + added,
        num_fixed_clauses=current.num_fixed_clauses,
        num_bandwidth_clauses=added,
        formula_breakdown={**current.formula_breakdown, "bandwidth": added},
    )


__all__ = [
    "CNFSizeEstimate",
    "ResourceLimits",
    "estimate_cnf_size",
    "estimate_incremental_cnf_size",
]
