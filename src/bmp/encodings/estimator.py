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
    occupancy_mode: str = "both",
    bandwidth_mode: str = "conflict",
    channel_mode: str = "full",
    compact_boundary: bool = False,
) -> CNFSizeEstimate:
    """Compute exact closed-form count of variables and clauses before CNF generation."""
    n = graph.order
    m = graph.size

    if n == 0:
        return CNFSizeEstimate(
            num_variables=0,
            num_original_vars=0,
            num_channeling_vars=0,
            num_aux_vars=0,
            num_clauses=0,
            num_fixed_clauses=0,
            num_bandwidth_clauses=0,
            formula_breakdown={},
        )

    if n == 1:
        is_pw = encoding.lower() == "pairwise"
        return CNFSizeEstimate(
            num_variables=1 if is_pw else 0,
            num_original_vars=1 if is_pw else 0,
            num_channeling_vars=0,
            num_aux_vars=0,
            num_clauses=1 if is_pw else 0,
            num_fixed_clauses=1 if is_pw else 0,
            num_bandwidth_clauses=0,
            formula_breakdown={"alo_vertex": 1} if is_pw else {},
        )

    if k is not None and k < 0:
        raise ValueError("Bandwidth threshold k cannot be negative")
    eval_k = 0 if k is None else min(k, n - 1)
    enc_family = encoding.lower()
    amo_type = amo.lower()

    aux_per_amo, clauses_per_amo = _single_amo_counts(amo_type, n, amo)

    if enc_family == "pairwise":
        occ = occupancy_mode.lower()
        bwm = bandwidth_mode.lower()
        if occ not in ("both", "pigeonhole"):
            raise ValueError(f"Unsupported occupancy_mode: {occupancy_mode}")
        if bwm not in ("conflict", "support", "support_single"):
            raise ValueError(f"Unsupported bandwidth_mode: {bandwidth_mode}")

        num_orig = n * n
        num_chan = 0
        alo_clauses = n
        amo_blocks_factor = 2 if occ == "both" else 1

        num_aux = amo_blocks_factor * n * aux_per_amo
        amo_label_clauses = n * clauses_per_amo
        amo_vertex_clauses = n * clauses_per_amo if occ == "both" else 0

        sym_clauses = 0
        if symmetry_breaking and n >= 2:
            cutoff = (n + 1) // 2
            sym_clauses = n - cutoff

        fixed_clauses = alo_clauses + amo_vertex_clauses + amo_label_clauses + sym_clauses

        if bwm == "conflict":
            bw_pairs_per_edge = (n - eval_k) * (n - eval_k - 1) if eval_k < n else 0
            bw_clauses = m * bw_pairs_per_edge
        else:
            if n <= 1 or eval_k >= n - 1:
                bw_clauses = 0
            else:
                per_dir = min(n, 2 * max(0, n - eval_k - 1))
                dirs = 2 if bwm == "support" else 1
                bw_clauses = m * dirs * per_dir

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
        cmode = channel_mode.lower()
        if cmode not in ("full", "one_sided"):
            raise ValueError(f"Unsupported channel_mode: {channel_mode}")

        num_orig = n * (n - 1)
        num_chan = n * (n - 2) if compact_boundary else n * n

        mono_clauses = n * (n - 2) if n >= 2 else 0

        if n < 2:
            chan_clauses = 0
        elif compact_boundary:
            chan_clauses = (3 if cmode == "full" else 1) * n * (n - 2)
        else:
            chan_clauses = n * (3 * n - 2) if cmode == "full" else n * n

        num_aux = n * aux_per_amo
        alldiff_clauses = n * clauses_per_amo

        sym_clauses = 1 if (symmetry_breaking and n >= 2) else 0
        fixed_clauses = mono_clauses + chan_clauses + alldiff_clauses + sym_clauses

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
    occupancy_mode: str = "both",
    bandwidth_mode: str = "conflict",
    channel_mode: str = "full",
    compact_boundary: bool = False,
) -> CNFSizeEstimate:
    """Cumulative count for unit steps; safe upper bound for adaptive jumps."""
    if target_k > initial_k or target_k < 0:
        raise ValueError("Require 0 <= target_k <= initial_k")
    current = estimate_cnf_size(
        graph,
        encoding=encoding,
        amo=amo,
        k=target_k,
        symmetry_breaking=symmetry_breaking,
        occupancy_mode=occupancy_mode,
        bandwidth_mode=bandwidth_mode,
        channel_mode=channel_mode,
        compact_boundary=compact_boundary,
    )
    if encoding.lower() != "order" and bandwidth_mode.lower() == "conflict":
        return current
    added = sum(
        estimate_cnf_size(
            graph,
            encoding=encoding,
            amo=amo,
            k=step,
            occupancy_mode=occupancy_mode,
            bandwidth_mode=bandwidth_mode,
            channel_mode=channel_mode,
            compact_boundary=compact_boundary,
        ).num_bandwidth_clauses
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


def _encoder_estimate_kwargs(encoder: object) -> dict[str, object]:
    """Extract normalized estimator keyword options from a BMPEncoder instance."""
    name = getattr(encoder, "name", "")
    encoding = "order" if "order" in str(name).lower() else "pairwise"
    amo = str(getattr(encoder, "amo_name", "pairwise"))
    if encoding == "pairwise":
        return {
            "encoding": "pairwise",
            "amo": amo,
            "occupancy_mode": str(getattr(encoder, "occupancy_mode", "both")),
            "bandwidth_mode": str(getattr(encoder, "bandwidth_mode", "conflict")),
        }
    return {
        "encoding": "order",
        "amo": amo,
        "channel_mode": str(getattr(encoder, "channel_mode", "full")),
        "compact_boundary": bool(getattr(encoder, "compact_boundary", False)),
    }


def estimate_for_encoder(
    encoder: object,
    graph: Graph,
    *,
    k: int | None = None,
    symmetry_breaking: bool = False,
) -> CNFSizeEstimate:
    """Compute closed-form CNF size estimate directly matching an encoder instance."""
    return estimate_cnf_size(
        graph,
        k=k,
        symmetry_breaking=symmetry_breaking,
        **_encoder_estimate_kwargs(encoder),  # type: ignore[arg-type]
    )


def estimate_incremental_for_encoder(
    encoder: object,
    graph: Graph,
    *,
    initial_k: int,
    target_k: int,
    symmetry_breaking: bool = False,
    search_mode: str = "linear",
) -> CNFSizeEstimate:
    """Compute incremental CNF size estimate (linear diff/step or binary activation)."""
    kwargs = _encoder_estimate_kwargs(encoder)
    if search_mode == "linear":
        return estimate_incremental_cnf_size(
            graph,
            initial_k=initial_k,
            target_k=target_k,
            symmetry_breaking=symmetry_breaking,
            **kwargs,  # type: ignore[arg-type]
        )
    # Binary incremental starts at mid=(lb+ub-1)//2 and guards steps with activation vars.
    base = estimate_cnf_size(
        graph,
        k=initial_k,
        symmetry_breaking=symmetry_breaking,
        **kwargs,  # type: ignore[arg-type]
    )
    mid_k = max(0, (initial_k + target_k) // 2)
    step = estimate_cnf_size(
        graph,
        k=mid_k,
        symmetry_breaking=symmetry_breaking,
        **kwargs,  # type: ignore[arg-type]
    )
    return CNFSizeEstimate(
        num_variables=base.num_variables + 1,
        num_original_vars=base.num_original_vars,
        num_channeling_vars=base.num_channeling_vars,
        num_aux_vars=base.num_aux_vars + 1,
        num_clauses=base.num_fixed_clauses + step.num_bandwidth_clauses + 1,
        num_fixed_clauses=base.num_fixed_clauses,
        num_bandwidth_clauses=step.num_bandwidth_clauses,
        formula_breakdown={**base.formula_breakdown, "bandwidth": step.num_bandwidth_clauses},
    )


__all__ = [
    "CNFSizeEstimate",
    "ResourceLimits",
    "estimate_cnf_size",
    "estimate_for_encoder",
    "estimate_incremental_cnf_size",
    "estimate_incremental_for_encoder",
]
