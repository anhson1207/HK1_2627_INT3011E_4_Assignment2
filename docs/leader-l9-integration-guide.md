# Leader Phase L9 – Hướng dẫn Tích hợp lên `dev/member-3` / `main`

## 1. Phạm vi thay đổi trên `dev/leader`

Phase L9 mở rộng SAT stack của Leader lên đầy đủ 113 instance Harwell–Boeing, tối ưu CNF size, sửa lỗ hổng forward progress khi phân tách thành phần liên thông, và bảo toàn API tương thích với hệ thống chung.

### Files thêm mới
- `configs/leader_l9_full113.toml`: Cấu hình benchmark L9 113 instance (resource limits, timeout từng pha, danh sách baseline/ablation/warm-start/proof).
- `src/bmp/experiments/__init__.py` & `src/bmp/experiments/leader_l9.py`: Runner tái lập toàn bộ 113/113 với checkpoint/resume, preflight 12 cấu hình, tách bạch `sat_solved_any` vs `HEURISTIC_FALLBACK`.
- `src/bmp/experiments/leader_l9_plots.py`: Tạo 12 biểu đồ SVG (`fig01`..`fig12`) chuẩn XML (`DejaVu Sans`, plain log formatter, kiểm tra `.empty`).
- `scripts/run_leader_l9.py`: CLI chạy chiến dịch L9 (`--config`, `--stages`, `--no-resume`, `--max-batch-seconds`, `--max-runs`, `--plots`).
- `tests/sat/test_leader_l9_full113.py`: Bộ regression test L9 (oracle equivalence, estimator exactness, incremental binary search, decomposition progress forwarding, dataset 113 invariants, SVG validation).
- `results/leader_l9_full113/`: Toàn bộ 17 artifacts thực nghiệm và 12 file SVG trong `figures/`.
- `docs/leader-l9-full113-sat-report.md`: Báo cáo khoa học L9 đầy đủ 113 instance.

### Files sửa đổi & API mở rộng (Backward-Compatible)
- `src/bmp/io/readers.py`: Bổ sung `ConversionPolicy`, `SUPPORTED_CONVERSION_POLICIES`, `MatrixMarketForensics`, `inspect_matrix_market_forensics`, `graph_from_matrix_market_forensics`, `convert_matrix_market`, `compute_topology_sha256`, `compute_graph_fingerprint` trong khi giữ nguyên `inspect_matrix_market` và `read_matrix_market`.
- `src/bmp/core/benchmark_catalog.py`: Thêm `resolve_raw_matrix_path`, `audit_raw_copy_parity`, `CANONICAL_RAW_DIR`, `FALLBACK_RAW_DIRS`.
- `src/bmp/core/bounds.py`: Thêm `cuthill_mckee_order` ($O(n+m)$).
- `src/bmp/encodings/pairwise.py`: Thêm `occupancy_mode="both"|"pigeonhole"` và `bandwidth_mode="conflict"|"support"|"support_single"` (mặc định giữ nguyên hành vi L8).
- `src/bmp/encodings/order.py`: Thêm `channel_mode="full"|"one_sided"` và `compact_boundary=False|True` (mặc định giữ nguyên hành vi L8).
- `src/bmp/encodings/estimator.py`: Mở rộng `estimate_cnf_size`, `estimate_incremental_cnf_size`, thêm `estimate_for_encoder` và `estimate_incremental_for_encoder`.
- `src/bmp/solvers/sat/search.py`: Tăng tốc `_cached_component_diameters` (`scipy.sparse.csgraph` kèm fallback thuần Python) và `tighten_permutation_local` ($O(1)$ pruning + $O(n+m)$ adjacency), thêm `extract_connected_components`, `reduce_isolated_vertices`, `compose_component_permutations`, `solve_sat_with_decomposition` (kèm `_SingleComponentProgressProxy` / `_MultiComponentProgressProxy` để không mất SAT incumbent khi timeout), `compute_initial_upper_bound(..., init_mode=...)`.
- `src/bmp/solvers/sat/worker.py`: Ghi nhận `sat_solved_any` & `incumbent_source` trong `report_progress` và khi `TIMEOUT`, sửa trường hợp `timeout_seconds <= 0`.
- `src/bmp/solvers/sat/incremental.py` & `src/bmp/solvers/sat/repeated.py`: Hỗ trợ `search_mode="linear"|"binary"`, `init_mode`, `decompose_components`.

### Dependencies
- Không thêm dependency bắt buộc mới (`pyproject.toml` giữ nguyên). `scipy` / `numpy` chỉ được import tùy chọn trong `search.py` với fallback thuần Python.

---

## 2. Xung đột tiềm ẩn & Thứ tự tích hợp an toàn

1. **Vùng có thể conflict khi merge với `origin/main` (`b9f5848`) hoặc `dev/member-3` (`789b2a3`):**
   - `src/bmp/io/readers.py` & `src/bmp/core/benchmark_catalog.py`: Nếu `dev/member-3` đã có M3.5–M3.8 `MatrixMarketForensics`, cần giữ một implementation thống nhất hỗ trợ cả `nonzero_union`, `stored_union`, `all_offdiag` và `compute_topology_sha256` / `compute_graph_fingerprint`.
   - `src/bmp/encodings/estimator.py`, `src/bmp/solvers/sat/incremental.py`, `src/bmp/solvers/sat/repeated.py`, `src/bmp/solvers/sat/worker.py`: Kiểm tra tránh ghi đè Product/Binary/Commander/Ladder AMO từ `main`/M2/M3; các tham số mới của Leader dùng keyword-only với giá trị mặc định tương thích ngược hoàn toàn.
   - `src/bmp/cli.py`: `dev/leader` không sửa `cli.py` trong L9, giảm thiểu conflict CLI.
2. **Dữ liệu & Lịch sử:**
   - L9 không sửa `data/benchmark_provenance.json`, `results/leader/` (L7/L8) hoặc dữ liệu của Member 2/3.
   - Tuyệt đối không merge/copy nhầm thư mục `results/member2_hb_table6_7/` vào nhánh tích hợp.
3. **Thứ tự khuyến nghị:**
   - Merge hoặc cherry-pick theo nhóm commit từ `dev/leader`: Dataset compatibility → Encoding & Estimator optimizations → SAT Worker/Incremental/Repeated/Search fixes → L9 Runner/Tests/Results/Docs.
4. **Kiểm thử bắt buộc sau tích hợp:**
   ```bash
   PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider -vv -rs tests/
   ```
   Xác minh lại toàn bộ suite Member 2 (`Binary`/`Commander`/`Glucose`/`Gurobi`/`CPLEX`), Member 3 (`Product`/`Ladder`/`MiniSat`/`CP-SAT`/`DRSA`) và `tests/sat/test_leader_l9_full113.py` đều pass `0 failed`.
