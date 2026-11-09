"""Analytical estimation and resource guards for CNF formula sizing."""

from __future__ import annotations

from dataclasses import dataclass, field
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
        amo: 'pairwise' or 'sequential'
        k: Bandwidth threshold. If None, assumes worst-case (k=0 for maximum clauses)
        symmetry_breaking: Whether anchor vertex symmetry breaking is active
    """
    n = graph.order
    m = graph.size

    if n <= 1:
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

    eval_k = 0 if k is None else max(0, min(k, n - 1))
    enc_family = encoding.lower()
    amo_type = amo.lower()

    if enc_family == "pairwise":
        num_orig = n * n
        num_chan = 0
        alo_clauses = n

        if amo_type in ("pairwise", "naive"):
            num_aux = 0
            amo_vertex_clauses = n * (n * (n - 1) // 2)
            amo_label_clauses = n * (n * (n - 1) // 2)
        elif amo_type in ("sequential", "seqcounter"):
            if n == 2:
                num_aux = 0
                amo_vertex_clauses = 2
                amo_label_clauses = 2
            else:
                num_aux = 2 * n * (n - 1)
                amo_vertex_clauses = n * (3 * n - 4)
                amo_label_clauses = n * (3 * n - 4)
        else:
            raise ValueError(f"Unsupported AMO type for estimation: {amo}")

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
        if amo_type in ("pairwise", "naive"):
            num_aux = 0
            alldiff_clauses = n * (n * (n - 1) // 2)
        elif amo_type in ("sequential", "seqcounter"):
            if n == 2:
                num_aux = 0
                alldiff_clauses = 2
            else:
                num_aux = n * (n - 1)
                alldiff_clauses = n * (3 * n - 4)
        else:
            raise ValueError(f"Unsupported AMO type for estimation: {amo}")

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


__all__ = [
    "CNFSizeEstimate",
    "ResourceLimits",
    "estimate_cnf_size",
]
