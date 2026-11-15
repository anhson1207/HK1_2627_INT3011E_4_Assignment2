# Member 3 Integration Guide – Shared BMP Contracts & Extension Points

Tài liệu này tổng hợp toàn bộ giao diện chuẩn (**validated APIs**) trên nhánh `dev/member-2` sau Phase M2.3 để Member 3 tích hợp trực tiếp **Product/Ladder AMO**, **MiniSat**, **CP-SAT**, **CP Optimizer**, **Heuristics (RCM, SA, DRSA)** và **Benchmark Runner chung** mà không phá vỡ SAT Core L8 hoặc các kiểm thử hiện có.

---

## 1. Core Contracts Đã Kiểm chứng

| Thành phần | Module & Symbol chính | Ghi chú tích hợp cho Member 3 |
|---|---|---|
| Đồ thị | `bmp.core.graph`: [`Graph`](../src/bmp/core/graph.py), `GraphInstance` (`= Graph`) | Immutable graph: `.vertices`, `.edges`, `.order` ($n$), `.size` ($m$), `.density`. Dùng `Graph.from_edges(...)` hoặc `Graph.create(...)`. Không yêu cầu đỉnh liên tục `0..n-1`. |
| Kết quả Solver | `bmp.core.solution`: [`SolverResult`](../src/bmp/core/solution.py), `BMPSolution` (`= SolverResult`), [`SolutionStatus`](../src/bmp/core/solution.py) | `SolverResult` chấp nhận `permutation`/`assignment`, `runtime_s`/`runtime_seconds`, `lower_bound <= upper_bound`, `status` thuộc `SolutionStatus` (`OPTIMAL`, `FEASIBLE`, `INFEASIBLE`, `TIMEOUT`, `SKIPPED`, `UNKNOWN`, `ERROR`, `UNAVAILABLE`). **Lưu ý**: trong codebase không dùng tên `BenchmarkResult`; bản ghi bảng dùng [`BenchmarkRecord`](../src/bmp/solvers/sat/benchmark.py) hoặc schema CSV `M2_3_FIELDS` (`member2_m2_3.py`). |
| Kiểm định độc lập | `bmp.core.validation`: [`validate_solution`](../src/bmp/core/validation.py) (`validate_assignment`), [`calculate_bandwidth`](../src/bmp/core/validation.py) | Kiểm tra ánh xạ toàn phần, phạm vi `1..n`, song ánh và đối chiếu `claimed_bandwidth == actual_bandwidth`. Mọi solver/heuristic mới phải đi qua hàm này trước khi báo cáo kết quả. |
| Dataset & Catalog | `bmp.core.benchmark_catalog`: `ALL_INSTANCES` (113), `TABLE_6_INSTANCES` (31), `TABLE_7_INSTANCES` (41), `TABLE_8_INSTANCES` (41), `BenchmarkInstanceMeta`, `preflight_check_dataset`, `verify_instance_file` | Chỉ benchmark chính thức trên **54 instance `READY`** trong `data/benchmark_provenance.json`. Tuyệt đối không chạy báo cáo chính thức trên `58 NEEDS_VERIFICATION` và `1 INVALID_DATA` (`mbeause`). |
| Dataset Loader | `bmp.io.readers`: `read_graph`, `inspect_matrix_market`, `read_matrix_market`, `write_edge_list` | **Lưu ý chỉ số đỉnh**: `inspect_matrix_market(path).graph` tạo đỉnh `0..n-1`, còn `read_matrix_market(path)` / `read_graph(path)` tạo đỉnh `1..n`. Luôn duyệt `graph.vertices` thay vì `range(graph.order)`. |
| Resource Guard | `bmp.encodings.estimator`: `ResourceLimits`, `estimate_cnf_size`, `estimate_incremental_cnf_size` | Giới hạn mặc định an toàn: `max_variables=500_000`, `max_clauses=2_500_000`, `timeout_seconds=300.0`, `memory_limit_mb=None` (hoặc `4096.0` trong runner). Dùng `run_bounded_solver` trong `bmp.solvers.sat.worker` cho deadline SAT. |

---

## 2. Hướng dẫn Tích hợp cho Từng Nhóm Thành phần Member 3

### A. Product & Ladder Cardinality Encodings (`AMOEncoder`)
1. Tạo `src/bmp/encodings/cardinality/product.py` và `ladder.py` cài đặt protocol `AMOEncoder` (`bmp.encodings.cardinality.base`):
   ```python
   def encode(self, literals: Sequence[int], allocator: VarAllocator) -> tuple[list[list[int]], list[int]]:
       ...
   ```
2. Đăng ký qua `register_amo_encoder("product", ProductAMOEncoder)` và `register_amo_encoder("ladder", LadderAMOEncoder)`, đồng thời re-export trong `src/bmp/encodings/cardinality/__init__.py` để `OrderEncoding(amo=...)` và `PairwiseEncoding(amo=...)` tự động nhận diện.
3. **Quan trọng**: cập nhật công thức giải tích trong `_single_amo_counts()` của `src/bmp/encodings/estimator.py` cho `"product"` và `"ladder"` (khớp chính xác 100% số biến phụ và mệnh đề thực tế sinh ra với mọi $m \ge 0$, kèm test đối chứng giống `tests/encodings/test_cardinality.py` và `tests/encodings/test_estimator.py`).
4. Cập nhật `choices` của `--amo` trong `src/bmp/cli.py`.

### B. MiniSat SAT Backend (`SATBackend`)
1. Tạo `src/bmp/solvers/sat/backends/minisat.py` kế thừa `SATBackend` (`bmp.solvers.sat.backends.base`):
   - Cài đặt đầy đủ `name`, `version`, `add_clause`, `append_formula`, `solve`, `solve_with_timeout`, `get_model`, `delete`, và context manager.
   - Đảm bảo `solve_with_timeout(0)` trả về `None` (hoặc thực thi đúng contract trong `test_glucose_backend.py`) và giải phóng tài nguyên C/C++ trong `delete()`.
2. Đăng ký qua `register_sat_backend("minisat", MinisatBackend)` (và `"minisat22"` / `"minisatgh"` nếu dùng PySAT), re-export trong `src/bmp/solvers/sat/backends/__init__.py` và cập nhật `--solver` trong `src/bmp/cli.py`.

### C. CP-SAT & CP Optimizer Solvers
1. Đặt tại `src/bmp/solvers/exact/` (hoặc `bmp.solvers.cp/`) theo hợp đồng tương tự `GurobiMIPSolver` / `CPLEXMIPSolver`:
   - `solve(graph: Graph, *, timeout_seconds: float | None = None, symmetry_breaking: bool = False, threads: int | None = None) -> SolverResult`
   - Trả về `SolutionStatus.UNAVAILABLE` (kèm `metadata["reason"]`) khi thiếu package (`ortools`, `docplex`/`cpoptimizer`) hoặc thiếu license — **không raise `ImportError` tại module import**.
   - Nếu solver trả về nghiệm, bắt buộc kiểm tra qua `validate_assignment(graph, candidate)` trước khi trả `OPTIMAL`/`FEASIBLE`/`TIMEOUT`.
   - Ghi rõ `best_bound`, `mip_gap` / optimality proof status và `solver_version` trong `metadata`.

### D. Metaheuristics (RCM, SA, DRSA) & Hybrid SAT Hook
1. Các heuristic đặt tại `src/bmp/solvers/heuristics/` nên trả về `SolverResult` với:
   - `method="HEURISTIC"`, `status=SolutionStatus.FEASIBLE` (chỉ được đặt `OPTIMAL` nếu `actual_bw <= certified_lower_bound`), `lower_bound=compute_lower_bound(graph)`, `upper_bound=actual_bw`, `metadata={"incumbent_source": "heuristic"}`.
2. **Tích hợp trực tiếp Hybrid SAT**: cả `RepeatedSATSolver.solve(...)` và `IncrementalSATSolver.solve(...)` đã hỗ trợ sẵn tham số:
   ```python
   heuristic_permutation: Mapping[int, int] | None = None
   ```
   Khi truyền permutation từ RCM/SA/DRSA vào `solve(..., symmetry_breaking=True)`, SAT Core sẽ kiểm tra tính tương thích symmetry-breaking, khởi tạo từ $UB_{heur}$, và lưu `incumbent_source="heuristic"` hoặc `"sat"` nếu SAT cải thiện thêm.

### E. Benchmark Runner Chung
1. Không sửa đè Schema `FIELDS` của M2.2 hoặc ghi vào `results/member2_m2_2/` / `results/leader/`.
2. Tham khảo `src/bmp/experiments/member2_m2_3.py`:
   - Dùng `ALL_INSTANCES` (113) + `data/benchmark_provenance.json` (`READY`-only policy).
   - Bắt buộc preflight bằng `ResourceLimits` và license-aware check trước khi dựng công thức CNF hoặc mô hình lớn.
   - Bảo toàn trạng thái chuẩn (`OPTIMAL`, `FEASIBLE`, `TIMEOUT`, `RESOURCE_LIMIT`, `SKIPPED`, `UNAVAILABLE`, `ERROR`), dùng `None` (`""` trong CSV) cho các chỉ số không áp dụng, và phân biệt `PROVED_MATCHED_BEST` với `UNPROVED_MATCHED_BEST`.
