"""Pairwise (quadratic) At-Most-One (AMO) encoding."""

from __future__ import annotations

from typing import Sequence

from bmp.encodings.cardinality.base import AMOEncoder, VarAllocator, register_amo_encoder


class PairwiseAMOEncoder(AMOEncoder):
    """Pairwise At-Most-One encoder.

    For m literals, generates m*(m-1)/2 binary clauses:
    (not x_i or not x_j) for all 0 <= i < j < m.
    Uses 0 auxiliary variables.
    """

    def encode(
        self,
        literals: Sequence[int],
        allocator: VarAllocator,
    ) -> tuple[list[list[int]], list[int]]:
        m = len(literals)
        if m <= 1:
            return [], []

        clauses: list[list[int]] = []
        for i in range(m):
            lit_i = literals[i]
            for j in range(i + 1, m):
                clauses.append([-lit_i, -literals[j]])
        return clauses, []


register_amo_encoder("pairwise", PairwiseAMOEncoder)
register_amo_encoder("naive", PairwiseAMOEncoder)

__all__ = ["PairwiseAMOEncoder"]
