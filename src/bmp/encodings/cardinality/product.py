"""Product At-Most-One (AMO) encoding for BMP SAT formulations.

Mục đích:
    Mã hóa ràng buộc At-Most-One (AMO) bằng 2-Product Encoding một cấp:
    - Bố trí n literal thành bảng rows x cols với rows = ceil(sqrt(n)), cols = ceil(n / rows)
    - Tạo rows + cols auxiliary variables (r_i cho hàng, c_j cho cột)
    - Mỗi literal l ở ô (i, j) sinh 2 mệnh đề: (NOT l OR r_i) và (NOT l OR c_j)
    - Áp dụng Pairwise AMO trên nhóm r_i và nhóm c_j
"""

from __future__ import annotations

from collections.abc import Sequence
from itertools import combinations
from math import isqrt

from bmp.encodings.cardinality.base import AMOEncoder, VarAllocator, register_amo_encoder


def _build_product_clauses(
    literals: Sequence[int],
    row_vars: Sequence[int],
    col_vars: Sequence[int],
) -> list[list[int]]:
    cols = len(col_vars)
    clauses: list[list[int]] = []
    for index, literal in enumerate(literals):
        row, col = divmod(index, cols)
        clauses.append([-literal, row_vars[row]])
        clauses.append([-literal, col_vars[col]])
    for group in (row_vars, col_vars):
        for first, second in combinations(group, 2):
            clauses.append([-first, -second])
    return clauses


def _product_dimensions(count: int) -> tuple[int, int]:
    rows = isqrt(count - 1) + 1
    cols = (count + rows - 1) // rows
    return rows, cols


def encode_product_amo(
    variables: list[int],
    top_id: int | None = None,
) -> tuple[list[list[int]], int]:
    """Encode At-Most-One over positive variable IDs using 2-Product encoding."""

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

    rows, cols = _product_dimensions(n)
    row_vars = list(range(current_top + 1, current_top + rows + 1))
    col_vars = list(range(current_top + rows + 1, current_top + rows + cols + 1))
    current_top += rows + cols
    return _build_product_clauses(variables, row_vars, col_vars), current_top


class ProductAMOEncoder(AMOEncoder):
    """AMOEncoder adapter for Member 3's 2-Product AMO encoding."""

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
        rows, cols = _product_dimensions(n)
        aux_vars = allocator.allocate(rows + cols)
        if len(aux_vars) != rows + cols or any(
            type(v) is not int or v <= 0 or v in used_ids for v in aux_vars
        ):
            raise ValueError("VarAllocator must allocate fresh positive variable IDs")
        if len(set(aux_vars)) != len(aux_vars):
            raise ValueError("VarAllocator must allocate distinct auxiliary variable IDs")

        row_vars = aux_vars[:rows]
        col_vars = aux_vars[rows:]
        return _build_product_clauses(literals, row_vars, col_vars), aux_vars


register_amo_encoder("product", ProductAMOEncoder)

__all__ = ["ProductAMOEncoder", "encode_product_amo"]
