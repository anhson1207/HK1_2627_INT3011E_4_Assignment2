"""Ladder (implication-chain) At-Most-One (AMO) encoding for BMP SAT formulations.

Ghi chú quan trọng về tương đương toán học:
    - Với m >= 3 literal, chuỗi implication của Ladder AMO sinh chính xác
      m - 1 biến phụ và 3m - 4 mệnh đề giống hệt Sequential Counter AMO
      (``SequentialCounterAMOEncoder`` trên nhánh Leader).
    - Khác biệt triển khai duy nhất nằm ở trường hợp m == 2:
      ``SequentialCounterAMOEncoder`` rút gọn đặc biệt thành 0 biến phụ và
      1 mệnh đề nhị phân [-x0, -x1], trong khi ``LadderAMOEncoder`` /
      ``encode_ladder_amo`` giữ công thức đồng nhất m - 1 = 1 biến phụ và
      3m - 4 = 2 mệnh đề để bảo toàn hợp đồng đếm biến/mệnh đề ban đầu.
    - Do đó không nên trình bày Ladder AMO như một họ nén biến độc lập
      hoàn toàn với Sequential Counter; nó được giữ lại dưới dạng biến thể/alias
      để phục vụ đối chứng tái lập bài tập.
"""

from __future__ import annotations

from collections.abc import Sequence

from bmp.encodings.cardinality.base import AMOEncoder, VarAllocator, register_amo_encoder


def _build_ladder_clauses(
    literals: Sequence[int],
    auxiliary: Sequence[int],
) -> list[list[int]]:
    n = len(literals)
    clauses: list[list[int]] = [[-literals[0], auxiliary[0]]]
    for i in range(1, n - 1):
        current_lit = literals[i]
        previous_signal = auxiliary[i - 1]
        current_signal = auxiliary[i]
        clauses.append([-current_lit, current_signal])
        clauses.append([-previous_signal, current_signal])
        clauses.append([-current_lit, -previous_signal])
    clauses.append([-literals[-1], -auxiliary[-1]])
    return clauses


def encode_ladder_amo(
    variables: list[int],
    top_id: int | None = None,
) -> tuple[list[list[int]], int]:
    """Encode At-Most-One over positive variable IDs using Ladder implication chain."""

    if any(type(v) is not int or v <= 0 for v in variables):
        raise ValueError("Variable IDs must be positive integers")
    if len(set(variables)) != len(variables):
        raise ValueError("Variable IDs must be distinct")
    if top_id is not None and (type(top_id) is not int or top_id < 0):
        raise ValueError("top_id must be a nonnegative integer")

    maximum = max(variables, default=0)
    if top_id is not None and top_id < maximum:
        raise ValueError("top_id must not be smaller than an input variable ID")

    current_top = max(maximum, top_id or 0)
    n = len(variables)
    if n <= 1:
        return [], current_top

    auxiliary = list(range(current_top + 1, current_top + n))
    current_top += n - 1
    return _build_ladder_clauses(variables, auxiliary), current_top


class LadderAMOEncoder(AMOEncoder):
    """AMOEncoder adapter for Member 3's Ladder AMO variant."""

    def encode(
        self,
        literals: Sequence[int],
        allocator: VarAllocator,
    ) -> tuple[list[list[int]], list[int]]:
        if any(type(lit) is not int or lit == 0 for lit in literals):
            raise ValueError("Literals must be nonzero integers")

        n = len(literals)
        if n <= 1:
            return [], []

        used_ids = {abs(lit) for lit in literals}
        aux_vars = allocator.allocate(n - 1)
        if len(aux_vars) != n - 1 or any(
            type(v) is not int or v <= 0 or v in used_ids for v in aux_vars
        ):
            raise ValueError("VarAllocator must allocate fresh positive variable IDs")
        if len(set(aux_vars)) != len(aux_vars):
            raise ValueError("VarAllocator must allocate distinct auxiliary variable IDs")

        return _build_ladder_clauses(literals, aux_vars), aux_vars


register_amo_encoder("ladder", LadderAMOEncoder)

__all__ = ["LadderAMOEncoder", "encode_ladder_amo"]
