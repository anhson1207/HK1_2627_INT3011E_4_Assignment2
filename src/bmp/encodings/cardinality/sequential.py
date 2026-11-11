"""Sequential Counter At-Most-One (AMO) encoding (Sinz 2005)."""

from __future__ import annotations

from typing import Sequence

from bmp.encodings.cardinality.base import AMOEncoder, VarAllocator, register_amo_encoder


class SequentialCounterAMOEncoder(AMOEncoder):
    """Sequential counter encoding for At-Most-One (Sinz, CP 2005).

    Encodes sum(literals) <= 1 with:
    - O(m) clauses (exactly 3m - 4 clauses for m >= 3, 1 clause for m=2)
    - m - 1 auxiliary variables for m >= 3.
    Preserves generalized arc-consistency through unit propagation.
    """

    def encode(
        self,
        literals: Sequence[int],
        allocator: VarAllocator,
    ) -> tuple[list[list[int]], list[int]]:
        m = len(literals)
        if m <= 1:
            return [], []
        if m == 2:
            return [[-literals[0], -literals[1]]], []

        # Allocate m - 1 register variables s_0, ..., s_{m-2}
        aux_vars = allocator.allocate(m - 1)
        clauses: list[list[int]] = []

        # First literal: not x_0 or s_0
        clauses.append([-literals[0], aux_vars[0]])

        # Middle literals: 1 <= i < m - 1
        for i in range(1, m - 1):
            x_i = literals[i]
            s_prev = aux_vars[i - 1]
            s_curr = aux_vars[i]

            # If x_i is true, s_i must be true
            clauses.append([-x_i, s_curr])
            # If s_{i-1} is true, s_i must be true (running sum propagation)
            clauses.append([-s_prev, s_curr])
            # If s_{i-1} is already true, x_i cannot be true (at most one)
            clauses.append([-x_i, -s_prev])

        # Last literal: not x_{m-1} or not s_{m-2}
        clauses.append([-literals[m - 1], -aux_vars[m - 2]])

        return clauses, aux_vars


register_amo_encoder("sequential", SequentialCounterAMOEncoder)
register_amo_encoder("seqcounter", SequentialCounterAMOEncoder)

__all__ = ["SequentialCounterAMOEncoder"]

