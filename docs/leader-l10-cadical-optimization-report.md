# Leader L10: Tối ưu CaDiCaL trên 113 đồ thị

## Git và baseline

HEAD trước L10: `e614334` trên `dev/leader`; remote cùng commit lúc audit. L9 có 113 đồ thị, 70 eligible, 70 CaDiCaL attempts, 23 SAT witnesses, 2 SAT proofs và 1 bounds proof. Kết quả L9 được giữ nguyên. HEAD sau L10: xem lịch sử Git của commit báo cáo.

## Dataset và kiểm chứng

Đã dựng lại 113 đồ thị từ tệp raw và đối chiếu 113/113 graph fingerprints cùng conversion policy. Table 6/7/8 lần lượt có 31/41/41 đồ thị; 54 READY, 58 NEEDS_VERIFICATION, 1 INVALID_DATA. Không thay đổi quy tắc conversion. Mọi mô hình CaDiCaL đã được giải mã và xác thực độc lập bằng `validate_solution` lúc chạy. Các run instrumented mới lưu `witness_permutation_json` để kiểm tra lại sau benchmark; checkpoint cũ không chứa permutation.

## Phân tích 46 timeout và 43 resource limits

Chi tiết từng trường hợp nằm trong `timeout_case_analysis.csv` và `resource_gap_analysis.csv`. Phân nhóm timeout dùng n, gap và kích thước CNF; đây là chẩn đoán heuristic, không phải chứng minh nguyên nhân timeout. Trong 43 resource cases, 6 đồ thị nằm dưới cả trần 750k biến và 2.5M clauses theo estimator. Pilot giữ worker isolation, hard timeout và 4096 MiB guard.

## Adaptive search và encoding

Adaptive repeated SAT hỏi tại UB heuristic đã xác thực để lấy model CaDiCaL thật, rồi thử ngưỡng cao trước khi siết. Với gap nhỏ, nó thử tuyến tính; với gap lớn, nó dùng khoảng 3/4 phía trên. SAT model được validate tại threshold. UNKNOWN/timeout không được coi là UNSAT. Pilot so sánh binary/adaptive ở 30 giây trên cùng graph, encoding, backend và máy; xem `adaptive_strategy_comparison.csv`. Encoding chọn từ Pairwise support single, Order one-sided compact và Order full qua estimator. `ENCODING_30` so Order full với Order one-sided compact trên cùng graph, backend, thời hạn và search mode. `FAMILY_30` so Order và Pairwise; `AMO_30` so Pairwise và Sequential AMO. `STRATEGY_30` so Repeated và Incremental; `SEARCH_30` so linear/binary/adaptive. Chỉ các cặp đủ run được diễn giải.

| Ablation | Run records | Actual solver calls | SAT-model runs |
|---|---:|---:|---:|
| MATCHED_30 | 8 | 8 | 1 |
| ENCODING_30 | 4 | 4 | 3 |
| AMO_30 | 2 | 2 | 2 |
| FAMILY_30 | 2 | 2 | 1 |
| STRATEGY_30 | 2 | 2 | 2 |
| SEARCH_30 | 3 | 3 | 3 |

Trong cặp `MATCHED_30`, binary có 0/4 SAT-model runs và adaptive có 1/4. Đây là kết quả trên tập pilot chọn trước, không ngoại suy thành tỷ lệ toàn bộ 113 đồ thị.

## CP-SAT upper bound

Nhánh Member 3 chỉ cung cấp CSV kết quả và checkpoint không chứa permutation CP-SAT. 107/113 fingerprints khớp. Không thể chạy independent permutation validator, nên 0 CP-SAT bandwidth được dùng làm bound cho CaDiCaL. `heuristic_bound_comparison.csv` ghi rõ từng trường hợp. Không quy kết nghiệm CP-SAT cho CaDiCaL.

## Cấu hình CaDiCaL

PySAT 1.9.dev17 với CaDiCaL195 trên máy này có API `solve`, `solve_limited`, `set_phases`, `conf_budget`, `prop_budget`, `interrupt`, `clear_interrupt`, `get_model`, `add_clause` và `append_formula`. L10 dùng API đã có trong backend (`solve`, `get_model`, `append_formula`) với worker subprocess cho hard timeout. Không có ablation về phase hints hoặc restart nội bộ, nên không quy kết cải thiện cho tuning CaDiCaL.

## Kết quả campaign

| Table | Total | Eligible | Attempted | SAT feasible cumulative | SAT optimal cumulative | Bound optimal cumulative | L10 Timeout | L10 ResourceLimit |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Table 6 | 31 | 31 | 31 | 20 | 3 | 0 | 14 | 0 |
| Table 7 | 41 | 19 | 19 | 4 | 0 | 0 | 18 | 22 |
| Table 8 | 41 | 23 | 23 | 3 | 1 | 1 | 22 | 18 |
| Total | 113 | 73 | 73 | 27 | 4 | 1 | 54 | 40 |

L10 có 19 instance có SAT witness từ các run mới; hợp nhất với L9 là 27 instance. Trạng thái primary records: hoàn tất; toàn bộ eligible có bằng chứng CaDiCaL call: True. `solver_invocation_evidence` phân biệt event trực tiếp, call đã ghi và suy luận từ worker progress: snapshot CNF được gửi ngay trước lời gọi solver, worker vẫn sống ít nhất 2 giây sau snapshot. Trường hợp timeout trong construction không được tính là solver call. `sat_calls` cũ có thể thiếu một call đang chạy khi worker bị cắt; số 0 trên record suy luận không được đọc là không gọi solver. Các run được phân biệt theo ngân sách trong CSV. Số SAT proofs mới: 2. Proof lịch sử `bcspwr01` ở L8 vẫn nằm trong Git history; L10 không suy ra proof mới từ nó.

## Runtime, RAM và giới hạn

Biểu đồ trong `figures/` chỉ dùng số đo thật. Peak RSS quan sát lớn nhất trong run CSV là 3634.8 MiB; sampled RSS không phải peak tuyệt đối. Solver time loại trừ lời gọi bị worker cắt giữa chừng; wall time là so sánh ngân sách phù hợp. Cấu hình 30 giây và 60 giây không được so như cùng ngân sách. Có 5 pilot record dưới cap 750k và 3 unique instance có CaDiCaL call; pilot chỉ được tính mở rộng coverage nếu có lời gọi CaDiCaL quan sát được. Chưa có bằng chứng rằng bound CP-SAT, một encoding riêng, hay tăng thời gian là nguyên nhân của mọi cải thiện. Selected proof runs: 5, SAT proofs mới trong tập này: 2.

## No regression, kiểm thử và tái lập

`no_regression_report.csv` giữ 23 witness L9 trong số liệu hợp nhất; không sửa historical files. Xem `reproduction.md` để chạy lại. Full pytest: 83 passed, 0 failed. Wheel `bmp_optimization-0.1.0-py3-none-any.whl` đã build bằng `pip wheel --no-build-isolation`; CLI `bmp --help` chạy thành công. Kết luận nghiệm thu: đạt điều kiện actual solver attempt cho mọi eligible; các ablation và CP permutation validation còn giới hạn như trên.
