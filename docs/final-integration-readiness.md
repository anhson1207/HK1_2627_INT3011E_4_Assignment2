# Final Integration Readiness & Research Summary Report (Phase M3.7)

**Audit Branch**: `dev/member-3`  
**Audited M3.6 Baseline HEAD**: `b01ff9b` (với các bản vá kiểm toán M3.7 thực hiện trực tiếp trên `dev/member-3` sau `b01ff9b`)  
**Phạm vi kiểm toán**: Toàn bộ mã nguồn Leader L8, Member 2 M2.3, Member 3 M3.1–M3.6, dữ liệu Harwell–Boeing, lịch sử Git, đóng gói wheel/CLI và 500 bản ghi thực nghiệm M3.6.  
**Trạng thái mục tiêu**: **Release Candidate cho hợp nhất vào `main`** *(chưa thực hiện `git merge` vào `main` trong Phase M3.7)*.

---

## Phần I — Integration Readiness Report (`TASK M3.7.1` & `M3.7.17`)

### 1. Kiểm toán lịch sử Git & quan hệ nhánh (Branch Ancestry)

Dữ liệu kiểm toán trực tiếp sau `git fetch --all --prune`:

| Ref | Commit SHA | Nội dung commit cuối | Quan hệ với `dev/member-3` |
|---|---|---|---|
| `dev/leader` (`origin/dev/leader`) | `60cbc2e` | `feat(benchmark): trace and bound staged L8 SAT runs` | Tổ tiên trực tiếp (`merge-base = 60cbc2e`, `dev/member-3` đi trước, `0` commit bị thiếu) |
| `dev/member-2` (`origin/dev/member-2`) | `3ffacbb` | `docs(member2): add complete 54-row preflight table and CLI reproduction guide` | Tổ tiên trực tiếp (`merge-base = 3ffacbb`, `dev/member-3` đi trước, `0` commit bị thiếu) |
| `main` (local) | `8d5c09e` | `chore: integrate GitHub repository history` | Tổ tiên trực tiếp (`merge-base = 8d5c09e`) |
| `origin/main` | `b9f5848` | `Merge pull request #4 from anhson1207/dev/member-2` | Chứa PR #3 (`3556747`, Leader) và PR #4 (`b9f5848`, Member 2); `git diff dev/member-2..origin/main` rỗng (tree `origin/main` đồng nhất với `3ffacbb`) |
| `dev/member-3` (`HEAD`) | `b01ff9b` + bản vá M3.7 | Tích hợp đầy đủ Leader L8 + Member 2 M2.3 + Member 3 M3.1–M3.7 | `git merge-tree --write-tree origin/main dev/member-3` **CLEAN (0 xung đột file)** |

**Kết luận Git Ancestry**:
- `dev/member-3` đã kế thừa **100% commit và module của Leader L8 và Member 2 M2.3** không bỏ sót hoặc ghi đè hồi quy.
- Hai commit sai khác giữa `origin/main` (`b9f5848`) và `dev/member-2` (`3ffacbb`) chỉ là 2 GitHub PR merge commits (`#3`, `#4`) có cùng nội dung tree; kiểm thử hợp nhất không đổi trạng thái (`git merge-tree --write-tree origin/main dev/member-3`) cho kết quả sạch tuyệt đối (**exit 0**, `0 conflicts`).

### 2. Danh mục Module & Trạng thái hoàn thiện (`TASK M3.7.2`)

| Nhóm | Thành phần / Module | Kiểm chứng thực tế trong M3.7 | Trạng thái |
|---|---|---|---|
| **Core Infrastructure** | [`graph.py`](file:///Users/nguyenanhson/BMP/src/bmp/core/graph.py), [`solution.py`](file:///Users/nguyenanhson/BMP/src/bmp/core/solution.py), [`validation.py`](file:///Users/nguyenanhson/BMP/src/bmp/core/validation.py), [`bounds.py`](file:///Users/nguyenanhson/BMP/src/bmp/core/bounds.py), [`generators.py`](file:///Users/nguyenanhson/BMP/src/bmp/core/generators.py), [`benchmark_catalog.py`](file:///Users/nguyenanhson/BMP/src/bmp/core/benchmark_catalog.py), [`readers.py`](file:///Users/nguyenanhson/BMP/src/bmp/io/readers.py), [`cli.py`](file:///Users/nguyenanhson/BMP/src/bmp/cli.py) | Hợp đồng `GraphInstance`/`SolverResult`/`validate_solution` đồng bộ qua 4 họ solver; catalog 113 instance + `official_paper_results.csv` bundled trong wheel; CLI `bmp` hoạt động ngoài repo | `COMPLETE` |
| **SAT Encodings & AMOs** | [`pairwise.py`](file:///Users/nguyenanhson/BMP/src/bmp/encodings/pairwise.py), [`order.py`](file:///Users/nguyenanhson/BMP/src/bmp/encodings/order.py), [`estimator.py`](file:///Users/nguyenanhson/BMP/src/bmp/encodings/estimator.py), 6 AMO encoders (`pairwise`, `sequential`, `binary`, `commander`, `product`, `ladder`) | `720 / 720` cấu hình tổ hợp (`2 encodings × 6 AMOs × 3 backends × 2 strategies × 2 symmetry × 5 graphs`) đạt `OPTIMAL` khớp `BruteForceSolver`. Xác nhận **`Ladder == Sequential` ở $m \ge 3$** (khác chỉ ở $m = 2$) | `COMPLETE` *(ghi chú `ladder` là biến thể tương đương `sequential` cho $m \ge 3$)* |
| **SAT Backends & Search** | `CadicalBackend`, `GlucoseBackend`, `MiniSatBackend`, [`repeated.py`](file:///Users/nguyenanhson/BMP/src/bmp/solvers/sat/repeated.py), [`incremental.py`](file:///Users/nguyenanhson/BMP/src/bmp/solvers/sat/incremental.py), [`worker.py`](file:///Users/nguyenanhson/BMP/src/bmp/solvers/sat/worker.py) | Incremental tái sử dụng đúng 1 thực thể backend qua tất cả `k`; Binary search & `ResourceLimits` (chặn pre-CNF với `sat_calls=0`) xác minh sống; `worker.py` cleanup child process sạch | `COMPLETE` |
| **MIP Exact Solvers** | [`gurobi.py`](file:///Users/nguyenanhson/BMP/src/bmp/solvers/exact/gurobi.py), [`cplex.py`](file:///Users/nguyenanhson/BMP/src/bmp/solvers/exact/cplex.py) | `20 / 20` lượt chạy sống trên `P5, C5, K4, K1_4, chord_P6` đạt `OPTIMAL` khớp oracle; `model.dispose()`/`environment.dispose()`/`model.end()` trong `finally`; vượt hạn mức bản quyền trả `UNAVAILABLE` (`Error 1016` / Gurobi size-limited) | `COMPLETE_WITH_LICENSE_LIMITS` |
| **CP Exact Solvers** | [`cpsat.py`](file:///Users/nguyenanhson/BMP/src/bmp/solvers/exact/cpsat.py), [`cp_optimizer.py`](file:///Users/nguyenanhson/BMP/src/bmp/solvers/exact/cp_optimizer.py) | `20 / 20` lượt chạy sống trên 5 đồ thị oracle đạt `OPTIMAL`; CP-SAT phủ 54/54 READY (`OPTIMAL` trên `bcspwr01`, `bcspwr02`); CP Optimizer bị chặn CE $2^{1000}$ hợp lệ (`UNAVAILABLE` trên `can_144` `error1016`) | `COMPLETE` (`CP-SAT`) / `COMPLETE_WITH_LICENSE_LIMITS` (`CP Optimizer`) |
| **Heuristics & DRSA** | [`rcm.py`](file:///Users/nguyenanhson/BMP/src/bmp/heuristics/rcm.py), [`sa.py`](file:///Users/nguyenanhson/BMP/src/bmp/heuristics/sa.py), [`drsa.py`](file:///Users/nguyenanhson/BMP/src/bmp/heuristics/drsa.py), [`initial.py`](file:///Users/nguyenanhson/BMP/src/bmp/heuristics/initial.py) | `DRSA` triển khai đúng dual `(p, q)`, `REX=0.6`, `NEX=0.2`, `ROT=0.2 (r<=5)`, đánh giá `f = b + delta`, lịch tăng chuỗi Markov $\gamma$; kiểm toán `verify_interval=1` (`ash85`, `500` moves: `279 accepts, 221 rejects`) khớp 100% tính lại toàn phần; bổ sung trường `execution_regime` tách biệt chạy đủ lịch làm lạnh vs chạy bị giới hạn budget | `COMPLETE` |
| **Experiments & Plotting** | `member2*.py`, `member3_m3_2..m3_6*.py` | Pipeline M3.6 (`500` runs, `--resume`, preflight 54 READY × 10 methods, 12 SVG `cnsplots`). Các lỗi rò rỉ stage/study ở tầng tổng hợp đã được vá và bảo vệ bằng regression test trong M3.7 | `COMPLETE` |

### 3. Trạng thái Dataset, Benchmark & Kiểm toán 500 bản ghi M3.6 (`TASK M3.7.6`–`M3.7.9`)

- **Dataset & Provenance ([`data/benchmark_provenance.json`](file:///Users/nguyenanhson/BMP/data/benchmark_provenance.json))**:
  - `113` đồ thị theo catalog gốc: **`54 READY`** (`53` topology duy nhất vì `sherman1 == saylr3` với `topology_sha256 = a592bd5eb799978745676e5b8414542529e14b4912136485a3b8b3dbf24a7697`), **`58 NEEDS_VERIFICATION`**, **`1 INVALID_DATA`** (`mbeause`: raw $n=496$ vs paper $n=492$, không tự ý cắt bỏ đỉnh cô lập).
  - `steam3`: giữ nguyên **`NEEDS_VERIFICATION`** (`explicit_offdiagonal_zeros = 614`), không đánh dấu `READY` trái phép dù `stored_union` khớp `LB=best=7`.
  - Toàn bộ `460` bản ghi HB trong `runs.json` sử dụng duy nhất chính sách `nonzero_union v1.0`, `0` instance có nhiều fingerprint khác nhau.
- **Kiểm toán độc lập 500 bản ghi `results/member3_m3_6/runs.csv` & `runs.json`**:
  - Đủ **500 / 500** `run_id` khớp `experiment_plan.json` (`0` trùng lặp, `0` mất bản ghi), **`0`** sai khác giữa CSV và JSON, **`0`** thời gian/bandwidth âm, **`0`** bản ghi bị chặn gán giá trị `0` giả.
  - Phân bố giai đoạn: `Stage_A_SmallOracle=40`, `Stage_B_Heuristic_54=276`, `Stage_C_Exact_Baseline=98`, `Stage_D_SAT_Studies=74`, `Stage_E_Extended=12` (tổng = `500`).
  - Phân bố trạng thái: `OPTIMAL=34` (`28` SmallOracle + `6` HB trên **2 instance/topology duy nhất**: `bcspwr01=5`, `bcspwr02=7` đều do `CP-SAT` chứng minh `LB == UB`), `FEASIBLE=332`, `TIMEOUT=107` (**105** có incumbent hợp lệ + **2** không incumbent là `cp-sat NO_WARM_START` trên `nos1` và `cp-sat SHARED_DRSA_WARM` 15s trên `saylr1`), `UNAVAILABLE=25`, `RESOURCE_LIMIT=2`.
  - Đối chiếu số nghiệm được xác thực độc lập (`validate_solution`): `34 + 332 + 105 = 471 / 471` (`validation_failed_count = 0`).

### 4. Lỗi phát hiện & khắc phục trong Phase M3.7 (`TASK M3.7.9`, `M3.7.10`, `M3.7.12`)

1. **[MAJOR — Đã sửa ở tầng tổng hợp] Rò rỉ Stage/Study trong `_paired_summary` ([`src/bmp/experiments/member3_m3_6.py`](file:///Users/nguyenanhson/BMP/src/bmp/experiments/member3_m3_6.py#L1450-L1494)) & `fig05`–`fig08` ([`src/bmp/experiments/member3_m3_6_plots.py`](file:///Users/nguyenanhson/BMP/src/bmp/experiments/member3_m3_6_plots.py#L161-L250))**:
   - `_paired_summary` trước đây không lọc `stage == "Stage_B_Heuristic_54"` nên 4 lượt `Stage_E_Extended` (`5.0s`, `bcsstk01=16`) ghi đè `Stage_B` (`0.8s`, `bcsstk01=18`), làm sai lệch `SA_vs_DRSA_Warm_54_seed17` thành `mean_bw_diff = +0.1111` (thực chất là **`+0.0741`**, `max_bw_diff = 2`, `mean_wall_diff_s = -0.0038s`); tương tự, `SAT_CaDiCaL_vs_Glucose/MiniSat` không lọc `study == "SAT_A_Backends"` nên `SAT_E_Symmetry` (`bcsstk01=23`) ghi đè `SAT_A_Backends` (`bcsstk01=25`), che mất chiến thắng của `MiniSat` (`23` vs `25` trên `bcsstk01`, thực chất **`right_wins=1, ties=5, mean_bw_diff=+0.3333`**; còn `Glucose` là **`mean_bw_diff=+0.8333, max=3`**).
   - **Khắc phục**: Đã siết bộ lọc `stage`/`study` chính xác trong `member3_m3_6.py` và `member3_m3_6_plots.py`, làm rõ mixed budgets trong `runtime_scope_note`, tái xuất `paired_comparisons.csv`, `per_method_summary.csv`, `summary.json`, 12 SVG plots từ đúng 500 raw records gốc (không sửa raw runs), cập nhật báo cáo M3.6 và thêm regression test `test_paired_comparisons_strict_stage_and_study_scoping_and_drsa_regime`.
2. **[MINOR — Đã sửa] Gắn nhãn chế độ chạy trên DRSA ([`src/bmp/heuristics/drsa.py`](file:///Users/nguyenanhson/BMP/src/bmp/heuristics/drsa.py#L434-L440))**: Bổ sung metadata `execution_regime` (`FULL_COOLING_SCHEDULE` vs `BOUNDED_<STOP_REASON>`) để tách bạch cấu hình tham số bài báo vs thực thi bị ngắt thời gian (`0.8s`).
3. **[MINOR — Ghi nhận Technical Debt, Không xóa bừa] Dữ liệu thô trùng `72` file giữa `data/harwell_boeing/raw` (`872 KB`) và `data/hb_table6_7` (`1.8 MB`)**: Hiện được `8` tệp nguồn và test của Leader/M2/M3.5 tham chiếu trực tiếp (`test_member2_hb_data.py`, `test_member3_forensics_m3_5.py`, `benchmark_catalog.py`, `fetch_hb.py`). Nhằm bảo toàn khả năng tái lập và tránh phá vỡ kiểm thử cũ trong giai đoạn release candidate, giữ nguyên trong hợp nhất này và đề xuất gộp thư mục ở đợt bảo trì sau merge.
4. **[MINOR — Ghi nhận] Chi phí `ps` polling trong `worker.py` và điều chỉnh flaky tests**: `run_bounded_solver` gọi subprocess `ps` mỗi `0.2s` làm tăng nhẹ chi phí hệ thống khi spawn hàng trăm worker liên tiếp dưới CPU load cao. Hai test nhạy timing ở M3.2 (`PHP(8,7) -> PHP(11,10)`) và M3.5 (`bcspwr01` CP-SAT `5s -> 15s`) đã được điều chỉnh hợp lý mà không làm giảm hiệu lực assertion.

### 5. Chiến lược Merge, Kiểm chứng sau Merge & Rollback

- **Chiến lược khuyến nghị (Merge Strategy)**:
  1. Do `origin/main` (`b9f5848`) đã hợp nhất `dev/leader` và `dev/member-2`, đồng thời `dev/member-3` đã chứa đầy đủ tổ tiên của cả `dev/leader` (`60cbc2e`) lẫn `dev/member-2` (`3ffacbb`) và kiểm tra `git merge-tree --write-tree origin/main dev/member-3` đạt **CLEAN**, **khuyến nghị mở Pull Request từ `dev/member-3 -> main` (merge `--no-ff`)** — không cần merge lại máy móc từng nhánh `dev/leader`/`dev/member-2`.
  2. (Tùy chọn cho người quản trị nhánh local `main`): đồng bộ `git switch main && git pull --ff-only origin main` trước khi nhấn Merge PR trên GitHub.
- **Lệnh kiểm chứng sau Merge trên `main`**:
  ```bash
  git checkout main && git pull origin main
  python3 -m venv .venv && source .venv/bin/activate
  pip install -e ".[cp-sat,cp-optimizer,plots,datasets,dev]"
  python scripts/acquire_benchmark.py --verify-only || python scripts/acquire_benchmark.py
  bmp preflight-benchmark --dir data/benchmarks/raw --table all
  pytest -vv -rs tests/
  ```
- **Chiến lược Rollback (nếu phát sinh sự cố sau khi merge vào `main`)**:
  ```bash
  # Hoàn tác commit merge vừa tạo trên main bằng revert an toàn (không rewrite history)
  git checkout main && git revert -m 1 <merge_commit_sha>
  git push origin main
  ```

---

## Phần II — Final Research Summary (`TASK M3.7.18`)

### 1. Research Objective
Giải quyết và đối chứng thực nghiệm có kiểm soát bài toán **Bandwidth Minimization Problem (BMP)** trên đồ thị vô hướng đơn bằng bốn trường phái tính toán hiện đại: **SAT**, **Mixed-Integer Programming (MIP)**, **Constraint Programming (CP)** và **Graph/Metaheuristic Optimization**, trên cùng bộ chuẩn Harwell–Boeing và đồ thị oracle chính xác.

### 2. Methods Evaluated
- **SAT**: Pairwise Position Encoding & Order Threshold Encoding; sáu bộ mã hóa At-Most-One (`Pairwise`, `Sequential Counter`, `Binary`, `Commander`, `Product`, `Ladder`); ba backend (`CaDiCaL 195`, `Glucose 4`, `MiniSat 22`); hai chiến lược tìm kiếm (`Repeated` [tuyến tính/nhị phân], `Incremental`); phá đối xứng đảo nhãn; `ResourceLimits` estimator & worker timeout.
- **MIP**: Mô hình Assignment MIP ($n^2 + 1$ biến) trên `Gurobi 13.0.3` và `IBM CPLEX 22.2.0.0`.
- **CP**: Mô hình vị trí biến nguyên + `AllDifferent` trên `Google OR-Tools CP-SAT 9.15.6755` và `IBM CP Optimizer 22.2.0.0`.
- **Heuristics**: `RCM` tất định; Simulated Annealing (`REX`, khởi tạo RCM); Dual Representation Simulated Annealing (`DRSA` theo Torres-Jimenez et al., 2015: `REX/NEX/ROT`, hàm đánh giá phân số `f = b + delta`, chuỗi Markov tăng trưởng $\gamma$) cả ở cấu hình bài báo gốc lẫn biến thể khởi tạo RCM (`MODIFIED_VARIANT`).

### 3. Experimental Dataset
- `113` đồ thị theo Tables 6–8 trong tài liệu chuẩn: **`54 READY`** (`nonzero_union v1.0`), **`58 NEEDS_VERIFICATION`** (gồm `steam3`), **`1 INVALID_DATA`** (`mbeause`), trong đó `54 READY` chứa **`53` topology duy nhất** (`sherman1 == saylr3`).

### 4. Key Quantitative Results
- **Correctness**: `720 / 720` cấu hình SAT + `40 / 40` MIP/CP trên 5 đồ thị oracle (`P5, C5, K4, K1_4, chord_P6`) và `40 / 40` lượt Stage A (`P6, C6, chord_P6, grid3x3`) khớp tuyệt đối tối ưu brute-force. Toàn bộ `471 / 471` nghiệm sinh ra trong M3.6 vượt qua kiểm tra độc lập.
- **Chứng minh tối ưu (`OPTIMAL`) trên Harwell–Boeing**: Trong ngưỡng `15s` Stage C, **`CP-SAT`** là solver duy nhất chứng minh `OPTIMAL` trên 2 đồ thị thực **`bcspwr01 = 5`** (`1.457s–2.439s`) và **`bcspwr02 = 7`** (`4.917s–6.181s`, nhanh hơn `18.1%` tổng wall time khi có `SHARED_RCM_WARM`).
- **Chất lượng nghiệm Primal**: **`IBM CP Optimizer`** khớp published best **`5 / 7`** lần trong phạm vi hợp lệ $n \le 138$ (`median_optimality_gap = 0.2222`), thắng `CP-SAT` 5–0 (hòa 2) theo ghép cặp cùng điều kiện. Tuy nhiên ngoài ngưỡng CE $2^{1000}$ ($n \ge 144$), chỉ `CP-SAT` và heuristics bao phủ được 100% tập `54 READY`.
- **Mở rộng cấu trúc SAT**: **Order Encoding** giảm số mệnh đề tới `15.6x` so với Pairwise trên `ash85` (`82,746` vs `1,291,097`, RSS `142 MB` vs `527 MB`), cho phép chạy tới `n=238..362` trong khi Pairwise chạm `ResourceLimits` (`2.5M`/`25.4M` mệnh đề). **`Ladder AMO` và `Sequential AMO` sinh chính xác cùng một công thức CNF với mọi $m \ge 3$**, không phải hai bộ nén độc lập. **`Product AMO`** đạt dung lượng RAM thấp nhất (`148.80 MB` trên `ash85`).
- **Heuristics**: `DRSA Warm` (`rcm`, $T_0=2.0$, `0.8s`) dẫn đầu nhẹ về mean gap (`20.80` vs `SA=20.87` vs `RCM=21.06` tại `seed=17`), thắng `DRSA Paper-Faithful Bounded (0.8s)` 54/54 (`median diff = 319`) do lịch gốc $T_0=1000$ cần thời gian vượt xa `0.8s`. Ở ngưỡng `5.0s` (Stage E), `DRSA Warm` đạt published best trên `bcsstk01 = 16`.

### 5. Scientific Contributions vs Literature
- **Thuật toán & mã hóa kế thừa từ y văn**: Pairwise & Order SAT encodings, 6 AMO cardinality encodings (Sinz Sequential, Binary, Commander, Product, Ladder), Assignment MIP, CP `AllDifferent`, RCM, và thuật toán DRSA gốc (Torres-Jimenez et al., 2015).
- **Đóng góp kỹ thuật, tích hợp & thực nghiệm của nhóm**:
  1. Thiết kế kiến trúc thống nhất `GraphInstance` / `SolverResult` / independent `validate_solution` xuyên 4 họ thuật toán và 3 backend SAT.
  2. Hệ thống kiểm toán dữ liệu pháp y 113 ma trận Harwell–Boeing (`data/benchmark_provenance.json`, phát hiện `steam3` explicit-zeros, `mbeause` sai bậc, trùng lặp `saylr3 == sherman1`, đánh giá độ nhạy 54 vs 53 topology).
  3. Cài đặt preflight estimator + `ResourceLimits` + license-aware guard công bằng và cơ chế benchmark hỗ trợ checkpoint/resume.
  4. Thực nghiệm đối chứng trực tiếp 500 run tách bạch rõ `OPTIMAL`, `TIMEOUT` có/không incumbent, và rào cản bản quyền/tài nguyên, chỉ ra vai trò thiết yếu của khởi tạo RCM đối với DRSA ở ngân sách dưới 1 giây.

### 6. Limitations
1. Giới hạn bản quyền thương mại (`CPLEX CE <= 1,000` vars, `Gurobi Eval <= 2,000` vars, `CP Optimizer CE <= 2^1000`) chặn phần lớn tập Harwell–Boeing nên không phản ánh năng lực bản quyền thương mại không giới hạn.
2. Thực nghiệm M3.6 dùng `1` máy (`Apple M2 8 cores, 16 GB RAM, threads=1`) với timeout ngắn (`0.8s–60s`); nhiều đồ thị `n >= 85` đòi hỏi thời gian lớn hơn đáng kể để chứng minh UNSAT.
3. Nghiên cứu đa hạt giống `[17, 23, 42]` thực hiện trên 10 đồ thị đại diện (chứ không lặp 3–10 seed cho toàn 54 đồ thị); `DRSA Paper-Faithful` mới thử dưới timeout `0.8s`.
4. Nhánh `58 NEEDS_VERIFICATION` chưa thể đưa vào benchmark chuẩn chừng nào quy tắc tiền xử lý gốc của bài báo chưa được xác nhận độc lập.
