# Member 2 – Phase M2.3: Official SAT/MIP Benchmark Expansion & Member 2 Final Audit

## 1. Mục tiêu Phase M2.3 & Kiểm toán Tổng kết M2.2 (TASK M2.3.1)

Phase M2.3 trên nhánh `dev/member-2` (từ `1ac48fe`) mở rộng thực nghiệm từ pilot M2.2 sang toàn bộ **54 instance Harwell–Boeing đã xác minh (`READY`)**, triển khai các nghiên cứu đối chứng có kiểm soát (**Studies A–G**), lập bảng tiền kiểm 54 dòng, đánh giá biến thiên thời gian chạy, hoàn thiện 10 biểu đồ `cnsplots`, audit toàn bộ API bàn giao cho Member 3 và lập bảng nghiệm thu cuối cùng của Member 2.

### Kiểm toán lại M2.2 (`results/member2_m2_2/`)
- **Git & Tests**: Khi bắt đầu M2.3, `dev/member-2` sạch tại `1ac48fe`; toàn bộ `93 pytest` đạt `0 failed, 0 skipped`.
- **Toàn vẹn dữ liệu M2.2 (giữ nguyên không ghi đè)**: `114` lượt chạy tách bạch rõ:
  - **`54` lượt `SmallOracle`** ($n \le 14$): `54/54 OPTIMAL`, `0 TIMEOUT`.
  - **`60` lượt Harwell–Boeing (`Table 6 READY`)**: `8 OPTIMAL` (`7` SAT trên `bcspwr01`, `1` Gurobi `sym=True` trên `bcspwr01`), `36 TIMEOUT`, `2 RESOURCE_LIMIT` (`nos4 pairwise`), `14 UNAVAILABLE` (Gurobi trên $n \ge 48$, CPLEX trên $n \ge 39$).
- **Hiệu chỉnh phân tích M2.2 (`docs/member2-m2_2-report.md`)**: Đã điều chỉnh 3 câu nhận định để tránh suy diễn quá phạm vi dữ liệu: (i) không so sánh tốc độ chéo phần cứng/thời điểm với `l8_sat_runs.csv`; (ii) thu hẹp nhận định `Order` vs `Pairwise` đúng trên 4 instance Bảng 6 đã đo (`1.48x–2.71x` mệnh đề tích lũy và `>12.5x` so với ước lượng `nos4`); (iii) không tính bội số speedup cho trường hợp Gurobi `sym=False` vốn bị cắt bởi `TIMEOUT 30.014s`.

---

## 2. Môi trường, Phiên bản & Trạng thái License Thực tế (TASK M2.3.7)

Ghi nhận tự động từ `results/member2_m2_3/metadata.json` và `detect_commercial_licenses()`:

| Thành phần | Phiên bản / Giá trị | Trạng thái & Ranh giới |
|---|---|---|
| OS / CPU / RAM | `macOS-14.0-arm64` (`8` CPU cores, `16.0 GiB` RAM) | Hỗ trợ multiprocessing `fork`, `spawn`, `forkserver` |
| Python | `3.14.3` (`.venv`) | — |
| `python-sat` | `1.9.dev17` (`cadical195`, `glucose4`) | `SOLVER_VERIFIED` (open-source, không giới hạn biến) |
| Gurobi | `13.0.3` (`gurobipy`) | `SIZE_LIMITED_EVAL` — probe `2,001` biến xác nhận trần **`<= 2,000` biến & `<= 2,000` ràng buộc** |
| CPLEX | `22.2.0.0` (`cplex`) | `COMMUNITY_EDITION` — probe `1,001` biến xác nhận `Error 1016` tại trần **`<= 1,000` biến & `<= 1,000` ràng buộc** |
| Visualization | `cnsplots 0.8.0`, `matplotlib 3.11.2`, `pandas 3.1.1` | Xuất chuẩn SVG |

- **License-aware MIP preflight**: Trước khi tạo $n^2+1$ biến nhị phân, runner M2.3 đối chiếu trực tiếp `mip_vars = n^2 + 1` và `mip_constrs = 2n + 2m + sym` với giới hạn đã probe. Mọi cấu hình vượt trần bị chặn ngay ở `0.000s` với `status = UNAVAILABLE`, `license_status = BLOCKED_LICENSE` — tuyệt đối không giả lập nghiệm hay biến đổi bài toán.

---

## 3. Full 54-READY Preflight Audit (TASK M2.3.2)

Bảng tiền kiểm đầy đủ 32 cột được xuất tại [`results/member2_m2_3/preflight_54.csv`](../results/member2_m2_3/preflight_54.csv) và [`preflight_54.json`](../results/member2_m2_3/preflight_54.json). Toàn bộ **54/54 instance `READY`** (Table 6: `13`, Table 7: `27`, Table 8: `14`) đạt `SHA-256 VERIFIED` và `MatrixMarket READY` (`dataset_ready = True`). `58 NEEDS_VERIFICATION` và `1 INVALID_DATA` (`mbeause`) tiếp tục được loại trừ nghiêm ngặt.

| Phân nhóm | Tổng `READY` | `SAT (Order+Seq)` OK (`<=500k v, <=2.5M c`) | `SAT (Pairwise+Seq)` OK | `Gurobi` OK (`<=2k v/c`) | `CPLEX` OK (`<=1k v/c`) | Nguyên nhân chặn chính |
|---|---:|---:|---:|---:|---:|---|
| **Table 6** ($n \in [39, 161]$) | 13 | **13** | 4 (`bcspwr01..ash85`) | **1** (`bcspwr01`) | 0 | Gurobi chặn $n \ge 48$; CPLEX chặn $n \ge 39$; Pairwise chặn $n \ge 100$ |
| **Table 7** ($n \in [209, 992]$) | 27 | **9** ($n \le 361$) | 0 | 0 | 0 | `Order+Seq` vượt `500k` vars từ `dwt_419` (`525,845v`) trở lên (`18` instances) |
| **Table 8** ($n \in [237, 1104]$) | 14 | **3** (`nos1`, `saylr1`, `plskz362`) | 0 | 0 | 0 | `plat362` vượt `2.5M` clauses (`2,872,477c`); `10` instances $n \ge 468$ vượt `500k` vars |
| **Tổng cộng** | **54** | **25** | **4** | **1** | **0** | Tách biệt rõ `DATASET_READY` (54) vs `SOLVER_EXECUTABLE` (25 SAT / 1 Gurobi / 0 CPLEX) |

---

## 4. Kết quả Baseline SAT Benchmark trên 54 READY (TASK M2.3.3)

Cấu hình cố định: `Order + Sequential + CaDiCaL (cadical195) + Incremental (threshold_policy="adaptive") + Symmetry Breaking = True`, `ResourceLimits(500_000 vars, 2_500_000 clauses, 30.0s, 4096 MiB)`, `threads=1`.

| Chỉ số | Table 6 (13) | Table 7 (27) | Table 8 (14) | Tổng (54) |
|---|---:|---:|---:|---:|
| Tổng `READY` được preflight | 13 | 27 | 14 | **54** |
| Chặn trước khi solve (`RESOURCE_LIMIT`) | 0 | 18 | 11 | **29** |
| Thực sự thực thi SAT solver | 13 | 9 | 3 | **25** |
| `OPTIMAL` (PROVED) trong `30.0s` | 0 | 0 | 0 | **0** |
| `TIMEOUT` (`UNPROVED`) tại `30.0s` | 13 | 9 | 3 | **25** |
| `ERROR` | 0 | 0 | 0 | **0** |
| Tổng thời gian wall toàn bộ Baseline (s) | — | — | — | **755.266s** |

**Quan sát nổi bật từ 25 instance thực thi Baseline (`results/member2_m2_3/baseline_summary.json`)**:
- **Khớp Published Best (nhưng `UNPROVED_MATCHED_BEST`) trên 4/25 instance**: `bcspwr01` (`bw=5` sau `3` SAT calls `8 -> 7 -> 6 -> 5`, hết 30s khi đang kiểm tra $k=4$), `lund_a` (`bw=23`), `lund_b` (`bw=23`), `saylr1` (`bw=14`).
- **Cải thiện được incumbent trong 30s**: `bcspwr01` (`8 -> 5`, `3` calls), `bcsstk01` (`27 -> 20`, `7` calls), `bcspwr02` (`13 -> 8`, `5` calls), `nos4` (`13 -> 12`, `1` call), `bcsstk05` (`24 -> 23`, `1` call), `dwt_245` (`40 -> 39`, `1` call, `solve_time=4.946s`).
- **Ngưỡng bão hòa ở $n \ge 85$ trong `30.0s`**: Trên `19/25` instance lớn/dày (`ash85`, `bcspwr03..can_161`, `8/9` Bảng 7 trừ `dwt_245`, `3/3` Bảng 8), lời gọi SAT đầu tiên tại $k = UB_{init} - 1$ chưa kịp kết thúc trong `30.0s` (`sat_calls = 0`, giữ nguyên cận trên hợp lệ ban đầu).

---

## 5. Controlled Comparative Experiments – Studies A–G (TASK M2.3.4–M2.3.6)

Từ Baseline_54, chọn **6 đại diện Harwell–Boeing xuyên suốt cả 3 bảng và 3 dải kích thước** (cùng `9` đồ thị `SmallOracle` lặp `3` lần cho đối chứng MIP/SAT chính xác):
1. **`bcspwr01`** (`Table 6`, $n=39, m=46$): nhỏ nhất trong HB và instance HB duy nhất chạy được Gurobi live.
2. **`bcsstk01`** (`Table 6`, $n=48, m=176$): cỡ trung-nhỏ dày cạnh (7 SAT calls ở Baseline), đối chứng Leader L8.
3. **`bcspwr02`** (`Table 6`, $n=49, m=59$): cỡ trung-nhỏ thưa cạnh, gap nhỏ (`8` vs Best `7`).
4. **`ash85`** (`Table 6`, $n=85, m=219$): ranh giới lớn nhất mà `Pairwise+Sequential` còn lọt trần `2.5M` clauses (`1,606,457c`).
5. **`dwt_245`** (`Table 7`, $n=245, m=608$): đại diện Bảng 7 lớn hơn nhưng **đã thực sự giải được `>= 1` SAT call trong 30s ở Baseline** (`40 -> 39`), giúp đo tác động thật của thuật toán thay vì toàn bộ timeout trống.
6. **`nos1`** (`Table 8`, $n=237, m=390$): đại diện Bảng 8 có khoảng cách `LB=3, UB=4, Best=3` sát ngưỡng tối ưu.

### Kết quả chi tiết từng Study (cùng giới hạn `timeout = 30.0s`, `threads = 1`, `threshold_policy = "adaptive"`):

- **Study A – Main Encoding (`Order` vs `Pairwise`, CaDiCaL + Sequential + Incremental + Sym=True)**:
  - Trên `dwt_245` (`36,704,797` clauses) và `nos1` (`22,148,953` clauses), `Pairwise` bị chặn ngay `RESOURCE_LIMIT` (`0.000s–0.004s`).
  - Trên 4 instance chạy được (`bcspwr01..ash85`), `Order` tích lũy ít mệnh đề hơn `1.27x–15.6x` (`bcsstk01`: `74,881` vs `94,824` nhưng làm `7` SAT calls vs `1`, đạt **`bw=20`** tốt hơn `bw=26` của `Pairwise`; `ash85`: `82,746` vs `1,291,097`).
- **Study B – Cardinality AMO (`Sequential`, `Binary`, `Commander`, `Pairwise`, Order + Glucose + Incremental + Sym=True)**:
  - Trên `bcspwr01`: **`Commander`** là cấu hình duy nhất đạt **`OPTIMAL (PROVED) bw=5`** trong lần chạy chuẩn (`28.688s`, `3,783` vars, `780` aux vars, `22,296` clauses).
  - Trên `bcspwr02`: `Binary` (`m2_3_0069`) và `Pairwise` AMO (`m2_3_0081`) cùng kéo được bandwidth xuống **`bw=7` (`UNPROVED_MATCHED_BEST`)**, trong khi `Sequential` và `Commander` dừng tại `bw=8`.
  - Trên `dwt_245` và `nos1`: `Pairwise` AMO dù nằm trong `OrderEncoding` vẫn đẩy số mệnh đề vượt ngưỡng `2.5M` (`7,858,875` và `7,035,751` clauses) nên bị chặn `RESOURCE_LIMIT`; trong khi `Binary` (`~114k–122k` vars, `~855k–969k` clauses), `Commander` (`~140k–151k` vars) và `Sequential` (`~168k–180k` vars, ít clauses nhất: `573k–667k`) đều hợp lệ.
- **Study C – SAT Backend (`CaDiCaL` vs `Glucose 4`, Order + Sequential + Incremental + Sym=True) & Kiểm tra biến thiên (`Variance_Repeat`)**:
  - `CaDiCaL` vượt `Glucose` trên các instance có nhiều lần gọi SAT: `bcsstk01` (`bw=20` / `7` calls vs `bw=22` / `5` calls), `dwt_245` (`bw=39` / `1` call vs `bw=40` / `0` calls).
  - Trên `bcspwr01` (`repetitions = 3`): `CaDiCaL` cả 3 lần đạt `bw=5` (`UNPROVED` ở `k=4` tại `30.0s`, với `sol_t` tích lũy đến `k=5` là `2.00s, 2.08s, 3.17s`); `Glucose` đạt **`OPTIMAL` (`27.747s`)** ở `rep=2` và `TIMEOUT` (`30.01s`) với `bw=5` ở `rep=1, 3` — phản ánh rõ độ nhạy ngưỡng `~30s` của phép chứng minh UNSAT tại $k=4$ (từng hoàn tất ở `~7.3s–7.8s` trong M2.2 khi tải CPU khác).
- **Study D – SAT Strategy (`Incremental` vs `Repeated`, CaDiCaL + Order + Sequential + Sym=True)**:
  - Kết quả phụ thuộc mật độ/cấu trúc đồ thị: trên `bcsstk01` (nhiều cạnh), `Incremental` giữ được lợi thế reuse mệnh đề học và đạt **`bw=20`** (`7` calls) so với `bw=21` (`6` calls) của `Repeated`; ngược lại trên `dwt_245` ($n=245$, thưa hơn), `Repeated` khởi tạo mới solver ở từng ngưỡng lại tìm được **`bw=38`** (`2` calls, `sol=13.19s`) tốt hơn **`bw=39`** (`1` call) của `Incremental`.
- **Study E – Symmetry Breaking (`True` vs `False`)**:
  - Trên **Gurobi (`bcspwr01`, `30s`)**: `sym=True` chứng minh **`OPTIMAL (PROVED) bw=5`** trong `11.909s–13.258s` (`3/3` lần chạy lặp), còn `sym=False` bị **`TIMEOUT`** tại `30.011s` (`bw=5, bnd=4.0, gap=0.2`).
  - Trên **SAT (`CaDiCaL`, `30s`)**: `sym=True` và `sym=False` cho cùng `bw` trên `5/6` instance (`bcspwr01`: 5, `bcsstk01`: 20, `ash85`: 10, `dwt_245`: 39, `nos1`: 4), riêng `bcspwr02` với `sym=False` đạt `bw=7` (`UNPROVED_MATCHED_BEST`, `24.96s`, `6` calls) so với `bw=8` của `sym=True` — chứng tỏ trong ngân sách timeout cứng của CDCL, cắt một nửa không gian tìm kiếm đôi khi thay đổi thứ tự khám phá nhánh và không đảm bảo luôn tìm incumbent thấp hơn trước khi hết giờ.
- **Study F & G – Live MIP (`Gurobi` vs `CPLEX`) & `SAT` vs `MIP`**:
  - Trên `9 SmallOracle` (`162` lượt chạy, `3` lần lặp mỗi cấu hình): **100% đạt `OPTIMAL` khớp `BruteForceSolver`** (`Gurobi sym=F` median `8.63ms`, `sym=T` `13.04ms`; `CPLEX sym=F` `8.93ms`, `sym=T` `9.19ms`; `Glucose` `62.20ms`; `CaDiCaL` `75.67ms`). Lưu ý `162` lượt `SmallOracle` được tách biệt hoàn toàn khỏi tỷ lệ giải Harwell–Boeing.
  - Trên Harwell–Boeing: **chỉ `bcspwr01` ($n=39$) nằm trong giới hạn license Gurobi**, nơi Gurobi (`sym=True`) giải `OPTIMAL` ổn định ở **`11.909s–13.258s`** (median **`12.331s`**, trung bình **`12.50s`**, `stdev=0.69s`) với `MIPGap=0.0`. Từ $n \ge 48$ (`bcsstk01`..`nos1`) trở lên, cả Gurobi và CPLEX đều bị chặn bởi giới hạn license (`BLOCKED_LICENSE`) nên **SAT là phương pháp khả thi duy nhất** trên tập dữ liệu thực quy mô lớn trong điều kiện license hiện tại.

---

## 6. Trực quan hóa `cnsplots` (TASK M2.3.8)

Toàn bộ `10` biểu đồ chuẩn SVG nằm tại [`results/member2_m2_3/figures/`](../results/member2_m2_3/figures/), loại trừ sạch `RESOURCE_LIMIT` / `UNAVAILABLE` khỏi thống kê runtime (chỉ dùng dữ liệu thực tế và preflight đã xác minh):

1. [`fig1_completion_by_size_group.svg`](../results/member2_m2_3/figures/fig1_completion_by_size_group.svg) — Baseline SAT Status (`TIMEOUT` vs `RESOURCE_LIMIT`) theo 4 nhóm kích thước đỉnh (`N_inst=54, N_runs=54, timeout=30s`).
2. [`fig2_pairwise_vs_order.svg`](../results/member2_m2_3/figures/fig2_pairwise_vs_order.svg) — Study A: `Pairwise` vs `Order` (Wall time & Bandwidth; `dwt_245`/`nos1` pairwise bị `RESOURCE_LIMIT`).
3. [`fig3_cardinality_amo.svg`](../results/member2_m2_3/figures/fig3_cardinality_amo.svg) — Study B: So sánh 4 Cardinality AMO (`Order + Glucose + Incremental`, `N_inst=6, N_runs=24, timeout=30s`).
4. [`fig4_cadical_vs_glucose.svg`](../results/member2_m2_3/figures/fig4_cadical_vs_glucose.svg) — Study C: `CaDiCaL` vs `Glucose 4` (`N_inst=6, N_runs=16` gồm lặp `bcspwr01`, `timeout=30s`).
5. [`fig5_repeated_vs_incremental.svg`](../results/member2_m2_3/figures/fig5_repeated_vs_incremental.svg) — Study D: `Repeated` vs `Incremental` (`CaDiCaL + Order + Sequential`, `N_inst=6, N_runs=12`).
6. [`fig6_sat_vs_mip.svg`](../results/member2_m2_3/figures/fig6_sat_vs_mip.svg) — Study F & G: `SmallOracle` (Gurobi, CPLEX, CaDiCaL, Glucose) vs HB `bcspwr01` (`Gurobi` vs `SAT`, ghi chú `BLOCKED_LICENSE` với CPLEX & $n \ge 48$).
7. [`fig7_clauses_vars_vs_runtime.svg`](../results/member2_m2_3/figures/fig7_clauses_vars_vs_runtime.svg) — Tương quan CNF Clauses / CNF Variables với Wall Time trên các lượt HB SAT thực thi (`OPTIMAL` vs `TIMEOUT`).
8. [`fig8_bandwidth_gap_vs_published.svg`](../results/member2_m2_3/figures/fig8_bandwidth_gap_vs_published.svg) — Khoảng cách bandwidth `(best_bw - published_best)` trên `25` instance `Baseline_54` thực thi (không gộp `29` lượt `RESOURCE_LIMIT`).
9. [`fig9_status_distribution.svg`](../results/member2_m2_3/figures/fig9_status_distribution.svg) — Phân bố outcome tách bạch 3 cohort (`HB Baseline_54`, `HB Studies A-G`, `SmallOracle`, tổng `277` lượt).
10. [`fig10_instance_vs_cnf_size.svg`](../results/member2_m2_3/figures/fig10_instance_vs_cnf_size.svg) — Scaling preflight toàn bộ `54 READY`: $n$ vs ước lượng CNF Clauses (`Order+Seq` vs `Pairwise+Seq`, đường cắt `2,500,000` clauses).

---

## 7. Thảo luận Khoa học & Threats to Validity (TASK M2.3.9)

- **Chính sách mở rộng của SAT vs MIP**: Trong bài toán BMP, Assignment MIP cần $n^2 + 1$ biến nhị phân nên chạm trần community/eval license rất sớm ($n=32$ cho CPLEX, $n=45$ cho Gurobi) và gặp áp lực mở rộng nhánh-cận khi không có symmetry breaking. Ngược lại, `OrderEncoding` giảm số mệnh đề cạnh từ $O(n^2 m)$ xuống $O(n m)$, cho phép SAT chạm ngưỡng $n \le 362$ (`plskz362`) dưới mức `500,000` biến / `2,500,000` mệnh đề. Tuy nhiên ở $n \ge 419$, ngay cả `Order + Sequential` cũng vượt `500,000` biến (một phần do $n(n-1)$ biến phụ của Sequential Counter AMO; dùng `Binary` AMO chỉ cần $\lceil \log_2 n \rceil$ biến phụ/đỉnh giúp hạ xuống ~`354k` biến ở `dwt_419`, là hướng mở rộng tự nhiên cho giai đoạn sau khi nới giới hạn biến).
- **Ý nghĩa của `0/25 OPTIMAL` trong Baseline `30s`**: Không có gì mâu thuẫn khoa học — mục tiêu nghiên cứu của dự án là khảo sát giới hạn thực nghiệm của exact SAT/MIP trên benchmark vốn trước đây trong tài liệu tham khảo được giải bằng metaheuristics (GRASP, SA, VNS, DRSA). Việc xác định chính xác ngưỡng $n \approx 39\text{–}49$ nơi chứng minh UNSAT mất $\sim 7\text{–}30\text{s}$ và ngưỡng $n \ge 85$ nơi lời gọi đầu tiên vượt `30s` là kết quả thực nghiệm xác thực, không phải lỗi thuật toán.
- **Threats to Validity**:
  1. Dữ liệu Harwell–Boeing gốc vẫn còn `58 NEEDS_VERIFICATION` và `1 INVALID_DATA`, chưa thể kết luận trên toàn bộ 113 ma trận cho đến khi nhóm chốt chuẩn đối xứng hóa ma trận không đối xứng.
  2. Giới hạn `30.0s` cho SAT baseline khiến phần lớn các lần chạy `TIMEOUT` giữ `UNPROVED` nên **không xếp bằng tổng hợp runtime trung bình giữa các cấu hình timeout khác nhau**.
  3. Giới hạn license Gurobi/CPLEX thương mại ngăn đánh giá MIP trên `53/54` instance `READY`.
  4. Thực nghiệm chạy tuần tự trên 1 máy macOS ARM64 (`16 GiB RAM`); độ nhạy của CDCL ở vùng ngưỡng `~30s` trên `bcspwr01` đòi hỏi chạy lặp khi đo thời gian chứng minh UNSAT.

---

## 8. Bảng Nghiệm thu Toàn bộ Phần Member 2 (TASK M2.3.14)

| # | Hạng mục nghiệm thu | Trạng thái | Căn cứ & Ghi chú kiểm chứng |
|---:|---|---|---|
| 1 | Binary AMO correctness | **COMPLETE** | Đã kiểm định equivalence + `estimate_cnf_size` khớp 100% qua brute-force và `tests/test_member2_integration_m2_1.py` |
| 2 | Commander AMO correctness | **COMPLETE** | Đã kiểm định equivalence + `estimate_cnf_size` khớp 100% + đạt `OPTIMAL bw=5` trên `bcspwr01` (`m2_3_0073`) |
| 3 | Glucose backend correctness | **COMPLETE** | Tuân thủ đầy đủ `SATBackend` L8, worker timeout, RSS tracking (`test_glucose_backend.py`, `test_member2_integration_m2_1.py`) |
| 4 | Gurobi live verification | **COMPLETE_WITH_LIMITATIONS** | Live verified (`13.0.3`): `OPTIMAL` 100% `SmallOracle` & `bcspwr01` (`12.331s` median); bị chặn trần `2,000` vars/constrs trên $n \ge 48$ (`SIZE_LIMITED_EVAL`) |
| 5 | CPLEX live verification | **COMPLETE_WITH_LIMITATIONS** | Live verified (`22.2.0.0`): `OPTIMAL` 100% `SmallOracle`; bị chặn `Error 1016` trên toàn bộ HB ($n \ge 39$, `COMMUNITY_EDITION` `<= 1,000` vars/constrs) |
| 6 | SAT benchmark | **COMPLETE_WITH_LIMITATIONS** | Hoàn tất `Baseline_54` (`25` thực thi, `29 RESOURCE_LIMIT`) + Studies A–E trên `6` đại diện Tables 6–8 (`30s` timeout cap khiến đa số $n \ge 48$ ở trạng thái `TIMEOUT/UNPROVED`) |
| 7 | MIP benchmark | **COMPLETE_WITH_LIMITATIONS** | Hoàn tất đủ phạm vi license cho phép (`108 SmallOracle OPTIMAL` + `bcspwr01 Gurobi sym=T/F`), `11` cặp HB vượt giới hạn được gắn `BLOCKED_LICENSE` trung thực |
| 8 | Benchmark runner | **COMPLETE** | `member2_hb.py` & `member2_m2_3.py` hỗ trợ preflight, `ResourceLimits`, license probe, worker timeout, checkpoint/resume tag-merge, Schema M2.3 |
| 9 | Visualization | **COMPLETE** | `8` SVG M2.2 + `10` SVG M2.3 qua `cnsplots` tách rõ cohort, loại trừ non-run statuses khỏi runtime bars |
| 10 | Dataset integration | **COMPLETE** | Tích hợp trọn vẹn catalog `113` instances + `data/benchmark_provenance.json` (`54 READY / 58 NEEDS_VERIFICATION / 1 INVALID_DATA`) |
| 11 | Testing | **COMPLETE** | Full pytest passed (`96 passed`, `0 failed`, `0 skipped`), gồm SAT/MIP/Estimator/Catalog/CLI/M2.1/M2.2/M2.3 và wheel packaging check |
| 12 | Documentation | **COMPLETE** | Hoàn thiện `docs/member2-report.md`, `docs/member2-hb-table6-7.md`, `docs/member2-m2_2-report.md`, `docs/member2-m2_3-report.md` |
| 13 | Integration readiness (Member 3) | **COMPLETE** | Toàn bộ contract đã audit & tài liệu hóa chi tiết tại [`docs/member3-integration-guide.md`](member3-integration-guide.md) |

**Kết luận nghiệm thu**: Member 2 **đạt đủ điều kiện nghiệm thu (`COMPLETE` cho phần kiến trúc/SAT Core extensions/testing/runner/integration và `COMPLETE_WITH_LIMITATIONS` cho phần benchmark quy mô lớn dưới giới hạn license thương mại + ngân sách timeout `30s`)** và **sẵn sàng bàn giao trực tiếp cho Member 3 và Leader**.
