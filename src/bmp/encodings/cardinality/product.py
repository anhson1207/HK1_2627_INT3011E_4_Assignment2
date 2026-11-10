
"""
Product AMO Encoding cho bài toán BMP

Mục đích:
    Mã hóa ràng buộc At-Most-One (AMO) thành các CNF clauses

Phương pháp:
    2-Product Encoding một cấp
    - Bố trí các biến đầu vào thành bảng hàng x cột
    - Tạo auxiliary variables cho hàng và cột
    - Mỗi biến True kéo theo hàng và cột tương ứng True
    - Dùng Pairwise AMO cho các biến hàng và cột

Quy ước DIMACS:
    Số nguyên dương: biến Boolean
    Số nguyên âm: phủ định của biến Boolean
    Một clause: list[int]
    CNF: list[list[int]]
"""

from itertools import combinations
from math import isqrt


def encode_product_amo(
    variables: list[int],
    top_id: int | None = None,
) -> tuple[list[list[int]], int]:
    """
    Mã hóa AMO bằng 2-Product Encoding

    Args:
        variables:
            Danh sách ID của các biến Boolean cần áp dụng AMO
            Ví dụ: [1, 2, 3, 4]

        top_id:
            ID lớn nhất đã được sử dụng trong công thức CNF chung
            Dùng để cấp phát auxiliary variables không trùng ID

    Returns:
        (clauses, new_top_id):
            clauses: Các CNF clauses biểu diễn AMO
            new_top_id: ID lớn nhất sau khi tạo biến phụ

    Raises:
        ValueError: Nếu ID biến không hợp lệ, bị trùng,
                    hoặc top_id không hợp lệ
    """

    # -----------------------------------------------------
    # BƯỚC 1: Kiểm tra đầu vào
    # -----------------------------------------------------

    if any(type(v) is not int or v <= 0 for v in variables):
        raise ValueError("Variable IDs must be positive integers")

    if len(set(variables)) != len(variables):
        raise ValueError("Variable IDs must be distinct")

    if top_id is not None and (
        type(top_id) is not int or top_id < 0
    ):
        raise ValueError("top_id must be a nonnegative integer")

    maximum = max(variables, default=0)

    if top_id is not None and top_id < maximum:
        raise ValueError(
            "top_id must not be smaller than an input variable ID"
        )

    current_top = max(maximum, top_id or 0)
    n = len(variables)

    # AMO với 0 hoặc 1 biến luôn đúng
    # Không cần sinh clause
    if n <= 1:
        return [], current_top

    # -----------------------------------------------------
    # BƯỚC 2: Xác định kích thước bảng Product
    # -----------------------------------------------------

    # rows = ceil(sqrt(n))
    rows = isqrt(n - 1) + 1

    # cols = ceil(n / rows)
    cols = (n + rows - 1) // rows

    # -----------------------------------------------------
    # BƯỚC 3: Cấp phát auxiliary variables
    # -----------------------------------------------------

    # Các biến phụ đại diện cho hàng
    row_vars = list(
        range(current_top + 1, current_top + rows + 1)
    )

    # Các biến phụ đại diện cho cột
    col_vars = list(
        range(
            current_top + rows + 1,
            current_top + rows + cols + 1,
        )
    )

    current_top += rows + cols

    clauses: list[list[int]] = []

    # -----------------------------------------------------
    # BƯỚC 4: Liên kết biến gốc với hàng và cột
    # -----------------------------------------------------

    for index, variable in enumerate(variables):

        # Xác định ô chứa biến trong bảng Product
        row, col = divmod(index, cols)

        row_variable = row_vars[row]
        col_variable = col_vars[col]

        # variable => row_variable
        # Tương đương: NOT variable OR row_variable
        clauses.append([-variable, row_variable])

        # variable => col_variable
        clauses.append([-variable, col_variable])

    # -----------------------------------------------------
    # BƯỚC 5: Áp dụng Pairwise AMO cho hàng và cột
    # -----------------------------------------------------

    for group in (row_vars, col_vars):

        # Mỗi cặp biến phụ không được cùng True
        for first, second in combinations(group, 2):
            clauses.append([-first, -second])

    # -----------------------------------------------------
    # BƯỚC 6: Trả về CNF và ID lớn nhất đã sử dụng
    # -----------------------------------------------------

    return clauses, current_top
