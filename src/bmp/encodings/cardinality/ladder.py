
"""
Ladder AMO Encoding cho bài toán BMP

Mục đích:
    Mã hóa ràng buộc At-Most-One (AMO) thành CNF

Ý tưởng:
    Sử dụng các auxiliary variables s1, s2, ..., s(n-1)
    để truyền trạng thái theo một chuỗi

    Nếu xi = True:
        - Tín hiệu tại vị trí i được kích hoạt
        - Các biến đứng sau xi không thể cùng True

Ghi chú:
    Đây là biến thể Ladder dạng implication,
    tương đương với Sequential Counter AMO cơ bản
    Cần thống nhất với leader về biến thể Ladder
    chính thức để tránh trùng lặp trong benchmark

Quy ước DIMACS:
    Biến dương: x
    Biến âm: NOT x
    Clause: list[int]
    CNF: list[list[int]]
"""


def encode_ladder_amo(
    variables: list[int],
    top_id: int | None = None,
) -> tuple[list[list[int]], int]:
    """
    Mã hóa At-Most-One bằng Ladder Encoding

    Args:
        variables:
            Danh sách ID biến Boolean cần áp dụng AMO
            Ví dụ: [1, 2, 3, 4]

        top_id:
            ID lớn nhất đã được sử dụng trong CNF chung
            Dùng để tránh trùng auxiliary variable IDs

    Returns:
        clauses:
            Danh sách CNF clauses biểu diễn AMO

        new_top_id:
            ID lớn nhất sau khi cấp phát biến phụ

    Raises:
        ValueError:
            Khi biến đầu vào hoặc top_id không hợp lệ
    """

    # --------------------------------------------------
    # BƯỚC 1: Kiểm tra dữ liệu đầu vào
    # --------------------------------------------------

    if any(type(v) is not int or v <= 0 for v in variables):
        raise ValueError(
            "Variable IDs must be positive integers"
        )

    if len(set(variables)) != len(variables):
        raise ValueError(
            "Variable IDs must be distinct"
        )

    if top_id is not None and (
        type(top_id) is not int or top_id < 0
    ):
        raise ValueError(
            "top_id must be a nonnegative integer"
        )

    maximum = max(variables, default=0)

    if top_id is not None and top_id < maximum:
        raise ValueError(
            "top_id must not be smaller than an input variable ID"
        )

    current_top = max(maximum, top_id or 0)
    n = len(variables)

    # Với 0 hoặc 1 biến, AMO luôn thỏa mãn
    if n <= 1:
        return [], current_top

    # --------------------------------------------------
    # BƯỚC 2: Cấp phát auxiliary variables
    # --------------------------------------------------

    # Với n biến gốc, cần n-1 biến phụ
    # Ví dụ:
    # variables = [1, 2, 3, 4]
    # auxiliary = [5, 6, 7]

    auxiliary = list(
        range(current_top + 1, current_top + n)
    )

    current_top += n - 1

    clauses: list[list[int]] = []

    # --------------------------------------------------
    # BƯỚC 3: Biến đầu tiên kích hoạt chuỗi
    # --------------------------------------------------

    # x1 => s1
    # NOT x1 OR s1

    clauses.append([
        -variables[0],
        auxiliary[0],
    ])

    # --------------------------------------------------
    # BƯỚC 4: Xử lý các biến ở giữa
    # --------------------------------------------------

    for i in range(1, n - 1):

        current_variable = variables[i]
        previous_signal = auxiliary[i - 1]
        current_signal = auxiliary[i]

        # Nếu xi True thì si phải True
        # xi => si
        clauses.append([
            -current_variable,
            current_signal,
        ])

        # Tín hiệu từ trước được truyền tiếp
        # s(i-1) => si
        clauses.append([
            -previous_signal,
            current_signal,
        ])

        # Nếu đã có tín hiệu trước đó,
        # xi không được True
        # NOT (xi AND s(i-1))
        clauses.append([
            -current_variable,
            -previous_signal,
        ])

    # --------------------------------------------------
    # BƯỚC 5: Xử lý biến cuối cùng
    # --------------------------------------------------

    # Nếu s(n-1) đã True thì xn phải False
    # NOT xn OR NOT s(n-1)

    clauses.append([
        -variables[-1],
        -auxiliary[-1],
    ])

    # --------------------------------------------------
    # BƯỚC 6: Trả về kết quả
    # --------------------------------------------------

    return clauses, current_top
