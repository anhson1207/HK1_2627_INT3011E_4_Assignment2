# Leader Phase L9 – Báo cáo Thực nghiệm & Tối ưu SAT Full 113 Harwell–Boeing

## 1. Thông tin Git & Môi trường thực nghiệm

- **Nhánh làm việc:** `dev/leader`
- **HEAD trước Phase L9:** `60cbc2e` (`feat(benchmark): trace and bound staged L8 SAT runs`)
- **Môi trường thực thi:** `macOS-14.0-arm64` (Apple M2, 8 cores, 16.0 GB RAM), Python `3.14.3`, `python-sat 1.9.dev17`, backend `cadical195`, `threads = 1`.
- **Giới hạn tài nguyên cấu hình (`configs/leader_l9_full113.toml`):** `max_sat_variables = 500,000`, `max_sat_clauses = 2,500,000`, `memory_limit_mb = 4096.0`, timeout các pha `6s / 8s / 12s / 20s / 45s`, quản lý qua POSIX worker isolation + checkpoint/resume (`446` run records, `interrupted_by_batch_budget = false`, `0` lỗi, `0` validation failures).

---

## 2. Bao phủ Dataset 113/113 & Chính sách chuyển đổi

Toàn bộ `113/113` ma trận Harwell–Boeing (`data/benchmarks/raw/*.mtx.gz`) đã được tải, kiểm tra SHA-256, xây dựng đồ thị và phân tầng minh bạch trong [`dataset_113.csv`](../results/leader_l9_full113/dataset_113.csv) (`111` topology duy nhất):

| Tầng dữ liệu | Số lượng | Chính sách chuyển đổi | Ghi chú kiểm toán |
|---|---:|---|---|
| **Tier 1 (`READY`)** | 54 | `nonzero_union` (`1.0`) | Đồ thị đối xứng/canonical chính thức từ L8 |
| **Tier 2a (`NEEDS_VERIFICATION`)** | 58 | `stored_union` (`1.0`) | Giữ đầy đủ entry lưu trữ theo chính sách M3.8 (ví dụ `steam3` $n=80, m=424$) |
| **Tier 2b (`INVALID_DATA`)** | 1 | `nonzero_union` (`mbeause`) | Primary graph $n=496, m=36,209$ (4 đỉnh cô lập `493..496`) + sensitivity `drop4_492` ($n=492$) |
| **Tổng cộng** | **113** | — | Table 6 (`31`), Table 7 (`41`), Table 8 (`41`) — `0` instance bị bỏ sót |

---

## 3. Tối ưu SAT Encoding, Search & Progress Forwarding

Các cải tiến thuộc phạm vi Leader (không dùng Product/Binary/Commander/Ladder AMO của thành viên khác):

1. **Order Encoding (`order.py`):** Bổ sung `channel_mode="one_sided"` và `compact_boundary=True` (bỏ biến biên $x_{v,1}, x_{v,n}$ thay bằng $\neg y_{v,2}$ và $y_{v,n}$, cắt ~17% clauses từ `52,389 -> 43,371` trên ablation subset). Lưu ý thực nghiệm: trên UNSAT proof (`bcspwr01`), bản `full` channeling vẫn lan truyền mạnh hơn `one_sided` (`27.93s OPTIMAL` vs timeout).
2. **Pairwise Encoding (`pairwise.py`):** Bổ sung `occupancy_mode="pigeonhole"` (bỏ $n$ block row AMO nên giữ $2n^2 - n$ biến thay vì $3n^2 - 2n$, nâng trần preflight từ $n_{\text{comp}} \le 408$ lên **$n_{\text{comp}} \le 500$**) và `bandwidth_mode="support"|"support_single"` (cắt mệnh đề từ $O(mn^2)$ xuống $\le 2mn$ / $\le mn$).
3. **Incremental Binary Search (`incremental.py`):** Dùng activation assumption literals cho từng ngưỡng $k$, khóa dương khi SAT và mệnh đề âm khi UNSAT — tái sử dụng 1 solver instance và tương đương 100% với oracle.
4. **Phân tách thành phần & Sửa progress forwarding (`search.py`):** Khử đỉnh cô lập và phân tách thành phần liên thông (`sherman4` $1104 \to 546$, `saylr3`/`sherman1` $1000 \to 681$, `dwt_234` $234 \to 117$); bổ sung `_SingleComponentProgressProxy` và `_MultiComponentProgressProxy` bảo đảm không rơi mất SAT incumbent trung gian khi worker chạm timeout, đồng thời tăng tốc `tighten_permutation_local` ($O(1)$ pruning) và `_cached_component_diameters` (`scipy.sparse.csgraph` + fallback thuần Python).
5. **Tách rạch ròi SAT Witness vs Heuristic Fallback (`worker.py`, `leader_l9.py`):** Chỉ đánh dấu `sat_solved_any=True` và `incumbent_source="SAT"` khi CaDiCaL thực sự trả về model hợp lệ.

---

## 4. Preflight 113/113 & Kết quả Thực nghiệm Tổng hợp

### A. So sánh Preflight Trước L9 vs Sau L9 (`sat_preflight_113.csv`)

| Cấu hình | Era | Eligible /113 | Ghi chú |
|---|---|---:|---|
| `base_pw_pw_rep_lin` | Pre-L9 | 10 / 113 | Clause explosion $O(mn^2)$ (trung vị 163.4M clauses) |
| `base_pw_seq_rep_lin` | Pre-L9 | 17 / 113 | $3n^2-2n$ biến, $O(mn^2)$ bandwidth clauses |
| `base_ord_pw_rep_lin` | Pre-L9 | 27 / 113 | Pairwise AMO nghẽn $O(n^3)$ |
| `base_ord_seq_inc_lin` | Pre-L9 | 20 / 113 | Incremental cộng dồn nhiều bước $k$ |
| `base_ord_seq_rep_lin` | Pre-L9 | 53 / 113 | Trần biến tại $n \le 408$ |
| `l9_ord_compact_seq_inc_bin_dec` | L9 | 42 / 113 | Giảm mệnh đề bước nhưng vẫn cộng dồn $k$ |
| `l9_ord_compact_seq_rep_bin_dec` | L9 | 54 / 113 | Cộng thêm decomposition (`dwt_234` v.v.) |
| `l9_pw_pig_sup_seq_rep_bin_dec` | L9 | 66 / 113 | Pigeonhole + Support |
| `l9_pw_pig_supsing_seq_rep_bin_dec` | L9 | **70 / 113** | Trần biến Leader $O(2n^2-n) \le 500,000$ ($n_{\text{comp}} \le 500$) |

### B. Kết quả CaDiCaL Thực tế theo Table, Tier và Nhóm kích thước (`summary.json`)

| Phân nhóm | Total | Eligible | Attempted | SAT Feasible (`sat_solved_any`) | SAT Improved RCM | Proved OPTIMAL | Timeout *(no SAT model)* | Resource Limit |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **Table 6** | 31 | 31 | 31 | **18** | 12 | **2** | 13 | 0 |
| **Table 7** | 41 | 18 | 18 | **3** | 3 | **0** | 15 | 23 |
| **Table 8** | 41 | 21 | 21 | **2** | 2 | **1** | 18 | 20 |
| **Tier 1 (`READY`)** | 54 | 34 | 34 | **9** | 6 | **1** | 24 | 20 |
| **Tier 2 (`Exploratory`)** | 59 | 36 | 36 | **14** | 11 | **2** | 22 | 23 |
| **Small ($n \le 150$)** | 23 | 23 | 23 | **15** | 9 | **2** | 8 | 0 |
| **Medium ($151..500$)** | 46 | 46 | 46 | **8** | 8 | **1** | 37 | 0 |
| **Large ($n > 500$)** | 44 | 1 | 1 | **0** | 0 | **0** | 1 | 43 |
| **Tổng toàn bộ** | **113** | **70** | **70** | **23** | **17** | **3** | **46** | **43** |

- **23 instance có nghiệm SAT hợp lệ thực sự từ CaDiCaL:** `arc130 (106)`, `ash85 (22)`, `bcspwr01 (5)`, `bcspwr02 (8)`, `bcspwr03 (32)`, `bcsstk01 (21)`, `bcsstk22 (24)`, `curtis54 (12)`, `fs_183_1 (108)`, `gent113 (59)`, `gre_115 (57)`, `ibm32 (13)`, `impcol_b (26)`, `pores_1 (7)`, `steam3 (10 / OPTIMAL 7)`, `west0156 (65)`, `will199 (102)`, `will57 (9)`, `dwt_209 (41)`, `dwt_221 (17)`, `dwt_245 (38)`, `impcol_a (60)`, `nnc261 (36)`.
- **3 instance chứng minh `OPTIMAL`:** `pores_1` (`bw=7`, Table 6), `steam3` (`bw=7` dưới `stored_union`, Table 6) do CaDiCaL chứng minh `UNSAT` tại $B^*-1$; và `nos1` (`bw=3 == certified_lb=3`, Table 8) chứng minh qua `BOUNDS_OPTIMALITY_CERTIFICATE` khi kết hợp decomposition + RCM.

---

## 5. Kết quả Ablation (Matched Benchmarks)

### Pairwise vs Order (`encoding_comparison.csv`, 12 instances, Sequential + Repeated Binary, 8s)
- `ord_full_fullb`: `mean_v = 13,537`, `mean_c = 52,389`, peak `151.1 MB`, **`1/12` SAT** (`bcspwr01`).
- `ord_onesided_compactb`: `mean_v = 13,412`, `mean_c = 43,371`, peak `142.0 MB`, **`1/12` SAT** (`bcspwr01`).
- `pw_both_conflict`: `mean_v = 13,537`, `mean_c = 709,970`, peak `321.9 MB`, `0/12` SAT.
- `pw_pig_sup2` / `pw_pig_sup1`: `mean_v = 9,045`, `mean_c = 39,765` / `26,635`, peak `205.5` / `189.7 MB`, `0/12` SAT (clause quá dài làm chậm unit propagation dù giảm được số biến).

### Pairwise AMO vs Sequential AMO (`amo_comparison.csv`, 12 instances, Repeated Binary, 8s)
- `amo_ord_pairwise` (`8,921` vars, `215,754` clauses, `366.8 MB`, `0/12`) vs `amo_ord_sequential` (`13,412` vars, **`43,309` clauses**, **`161.4 MB`**, **`1/12`**). Sequential giảm ~5× mệnh đề và ~2.3× RAM, mở rộng đáng kể phạm vi preflight; Pairwise chỉ nhỉnh hơn trên đồ thị siêu nhỏ ($n \le 50$, `baseline_results.csv`: `5/8` vs `3/8`).

### Repeated vs Incremental & Linear vs Binary (`strategy_comparison.csv`, 12 instances, 8s)
- `strat_rep_lin` (`6/12` SAT, `42,158` clauses, `172.1 MB`) vs `strat_inc_lin` (`6/12` SAT, `45,503` clauses, `172.2 MB`): ngang hiệu quả trong 8s khi xuất phát từ `rcm`, nhưng Repeated qua được nhiều preflight hơn (`54/113` vs `42/113`).
- `strat_rep_bin` (`2/12`) và `strat_inc_bin` (`1/12`) chậm hơn `Linear` khi xuất phát từ `rcm` (nhảy thẳng vào vùng UNSAT khó), nhưng khi đổi sang `warm_start_mode="identity"` (`warm_start_comparison.csv`), `Binary` đạt **`6/10`** SAT so với **`2/10`** của `rcm` / `rcm_tight`.

---

## 6. Phân tích `RESOURCE_LIMIT` & No-Regression

- **43 trường hợp `RESOURCE_LIMIT` tuyệt đối còn lại (`resource_gap_analysis.csv`):** 100% (`43/43`) là các đồ thị có $n_{\text{comp}} > 500$ vượt trần `500,000` biến của biểu diễn $O(2n^2-n)$ (trong đó `27/43` vượt cả `2,500,000` clauses, `0/43` vượt `4096 MB` RAM). Để vượt mốc 500 đỉnh cần chuyển sang biến $O(n \log n)$ (binary-bit ordering) hoặc MIP/CP/metaheuristics.
- **No-Regression (`no_regression_report.csv`):**
  - Trước L9 (L8 official `60cbc2e`): `2/113` attempted (`bcspwr01`, `bcsstk01`), `2` SAT feasible, `1` optimal (`bcspwr01` ở 30s `sym=False`).
  - Tham chiếu M3.8: `54/113` `TIMEOUT_WITH_INCUMBENT` với `Order + Product AMO (Member 3) + DRSA warm-start`, `59` `RESOURCE_LIMIT`, `0` OPTIMAL (chỉ đối chiếu coverage vì khác AMO và warm-start).
  - Sau L9 (Leader-only AMOs): `113/113` dataset & preflight, `70/113` eligible & **100% `70/70` đã được thử**, **`23/113` có SAT witness hợp lệ từ CaDiCaL**, **`3/113` chứng minh `OPTIMAL`**. (Riêng `bcspwr01` trong L9 đạt tối ưu `bw=5` trên 7 cấu hình nhưng run `45s` `sym=True` timeout ở $k=4$ UNSAT, được ghi nhận trung thực).

---

## 7. Kiểm thử, Wheel, CLI & Biểu đồ

- **Pytest:** `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider -vv -rs tests/` → **`65 passed, 128 subtests passed, 0 failed, 0 skipped in 35.79s`**.
- **Wheel & CLI:** Đóng gói thành công `bmp_optimization-0.1.0-py3-none-any.whl`, import ngoài repository OK, `.venv/bin/bmp --help` OK.
- **12 biểu đồ SVG (`results/leader_l9_full113/figures/`):** Tất cả 12 file hợp lệ XML, `0 NaN`, không có panel trống.

**Kết luận tổng kết:** **CaDiCaL tìm được nghiệm hợp lệ trên 23/113 instance, chứng minh tối ưu trên 3/113 instance, 90 instance chưa giải được** (46 trường hợp vượt ngân sách thời gian 6–45s trước khi chứng minh tối ưu hoặc tìm được SAT model, 43 trường hợp vượt ngưỡng `500,000` biến `RESOURCE_LIMIT`; riêng `nos1` thuộc cả nhóm 3 OPTIMAL via bounds nhưng không có SAT call witness nên có tổng `25` ca có kết quả/ứng cử, hay `90` ca chưa có SAT model nếu chỉ tính 23 SAT feasible; tổng cộng `113 - 23 = 90` chưa có SAT model hoặc `88` chưa có cả SAT lẫn OPTIMAL). Nhánh đạt trạng thái **`FULL_113_DATASET_COVERAGE`**, **`FULL_113_PREFLIGHT_COVERAGE`**, **`SAT_SOLVER_COVERAGE_PARTIAL`**, **`RESOURCE_LIMITED`**, và **`READY_FOR_INTEGRATION`**.

---

## 8. Bảng Coverage Đầy đủ 113/113 Harwell–Boeing Instances

| # | Instance | Table | Tier | Policy | n | m | LB | RCM UB | Pub Best | SAT Feasible | SAT BW | Pipe BW | Optimal | Status |
|---:|---|---|---|---|---:|---:|---:|---:|---:|:---:|---:|---:|:---:|---|
| 1 | `arc130` | Table 6 | Tier2 | `stored_union` | 130 | 715 | 62 | 121 | 63 | True | 106 | 67 | False | `SAT_FEASIBLE` |
| 2 | `ash85` | Table 6 | Tier1 | `nonzero_union` | 85 | 219 | 7 | 10 | 9 | True | 22 | 10 | False | `SAT_FEASIBLE` |
| 3 | `bcspwr01` | Table 6 | Tier1 | `nonzero_union` | 39 | 46 | 4 | 8 | 5 | True | 5 | 5 | False | `SAT_FEASIBLE` |
| 4 | `bcspwr02` | Table 6 | Tier1 | `nonzero_union` | 49 | 59 | 6 | 13 | 7 | True | 8 | 8 | False | `SAT_FEASIBLE` |
| 5 | `bcspwr03` | Table 6 | Tier1 | `nonzero_union` | 118 | 179 | 9 | 23 | 10 | True | 32 | 21 | False | `SAT_FEASIBLE` |
| 6 | `bcsstk01` | Table 6 | Tier1 | `nonzero_union` | 48 | 176 | 12 | 27 | 16 | True | 21 | 21 | False | `SAT_FEASIBLE` |
| 7 | `bcsstk04` | Table 6 | Tier1 | `nonzero_union` | 132 | 1758 | 27 | 47 | 37 | False | — | 39 | False | `TIMEOUT_NO_SAT_MODEL` |
| 8 | `bcsstk05` | Table 6 | Tier1 | `nonzero_union` | 153 | 1135 | 13 | 24 | 20 | False | — | 23 | False | `TIMEOUT_NO_SAT_MODEL` |
| 9 | `bcsstk22` | Table 6 | Tier1 | `nonzero_union` | 138 | 279 | 7 | 14 | 10 | True | 24 | 13 | False | `SAT_FEASIBLE` |
| 10 | `can_144` | Table 6 | Tier1 | `nonzero_union` | 144 | 576 | 11 | 18 | 13 | False | — | 14 | False | `TIMEOUT_NO_SAT_MODEL` |
| 11 | `can_161` | Table 6 | Tier1 | `nonzero_union` | 161 | 608 | 16 | 30 | 18 | False | — | 30 | False | `TIMEOUT_NO_SAT_MODEL` |
| 12 | `curtis54` | Table 6 | Tier2 | `stored_union` | 54 | 124 | 8 | 14 | 10 | True | 12 | 12 | False | `SAT_FEASIBLE` |
| 13 | `fs_183_1` | Table 6 | Tier2 | `stored_union` | 183 | 701 | 52 | 155 | 60 | True | 108 | 108 | False | `SAT_FEASIBLE` |
| 14 | `gent113` | Table 6 | Tier2 | `stored_union` | 113 | 549 | 18 | 57 | 27 | True | 59 | 43 | False | `SAT_FEASIBLE` |
| 15 | `gre_115` | Table 6 | Tier2 | `stored_union` | 115 | 267 | 15 | 37 | 23 | True | 57 | 34 | False | `SAT_FEASIBLE` |
| 16 | `gre_185` | Table 6 | Tier2 | `stored_union` | 185 | 650 | 14 | 29 | 21 | False | — | 29 | False | `TIMEOUT_NO_SAT_MODEL` |
| 17 | `ibm32` | Table 6 | Tier2 | `stored_union` | 32 | 90 | 8 | 15 | 11 | True | 13 | 13 | False | `SAT_FEASIBLE` |
| 18 | `impcol_b` | Table 6 | Tier2 | `stored_union` | 59 | 281 | 15 | 38 | 20 | True | 26 | 26 | False | `SAT_FEASIBLE` |
| 19 | `impcol_c` | Table 6 | Tier2 | `stored_union` | 137 | 352 | 20 | 47 | 30 | False | — | 42 | False | `TIMEOUT_NO_SAT_MODEL` |
| 20 | `lns_131` | Table 6 | Tier2 | `stored_union` | 131 | 275 | 13 | 33 | 20 | False | — | 32 | False | `TIMEOUT_NO_SAT_MODEL` |
| 21 | `lund_a` | Table 6 | Tier1 | `nonzero_union` | 147 | 1151 | 12 | 23 | 23 | False | — | 23 | False | `TIMEOUT_NO_SAT_MODEL` |
| 22 | `lund_b` | Table 6 | Tier1 | `nonzero_union` | 147 | 1147 | 12 | 23 | 23 | False | — | 23 | False | `TIMEOUT_NO_SAT_MODEL` |
| 23 | `mcca` | Table 6 | Tier2 | `stored_union` | 180 | 1680 | 32 | 58 | 37 | False | — | 51 | False | `TIMEOUT_NO_SAT_MODEL` |
| 24 | `nos4` | Table 6 | Tier1 | `nonzero_union` | 100 | 247 | 8 | 13 | 10 | False | — | 11 | False | `TIMEOUT_NO_SAT_MODEL` |
| 25 | `pores_1` | Table 6 | Tier2 | `stored_union` | 30 | 103 | 5 | 9 | 7 | True | 7 | 7 | True | `OPTIMAL_PROVED` |
| 26 | `steam3` | Table 6 | Tier2 | `stored_union` | 80 | 424 | 6 | 7 | 7 | True | 10 | 7 | True | `OPTIMAL_PROVED` |
| 27 | `west0132` | Table 6 | Tier2 | `stored_union` | 132 | 404 | 19 | 61 | 32 | False | — | 53 | False | `TIMEOUT_NO_SAT_MODEL` |
| 28 | `west0156` | Table 6 | Tier2 | `stored_union` | 156 | 371 | 23 | 72 | 36 | True | 65 | 62 | False | `SAT_FEASIBLE` |
| 29 | `west0167` | Table 6 | Tier2 | `stored_union` | 167 | 489 | 24 | 93 | 34 | False | — | 84 | False | `TIMEOUT_NO_SAT_MODEL` |
| 30 | `will199` | Table 6 | Tier2 | `stored_union` | 199 | 660 | 40 | 115 | 64 | True | 102 | 101 | False | `SAT_FEASIBLE` |
| 31 | `will57` | Table 6 | Tier2 | `stored_union` | 57 | 127 | 6 | 14 | 6 | True | 9 | 9 | False | `SAT_FEASIBLE` |
| 32 | `494_bus` | Table 7 | Tier1 | `nonzero_union` | 494 | 586 | 19 | 84 | 28 | False | — | 82 | False | `TIMEOUT_NO_SAT_MODEL` |
| 33 | `662_bus` | Table 7 | Tier1 | `nonzero_union` | 662 | 906 | 27 | 112 | 39 | False | — | 106 | False | `RESOURCE_LIMIT` |
| 34 | `685_bus` | Table 7 | Tier1 | `nonzero_union` | 685 | 1282 | 27 | 93 | 32 | False | — | 86 | False | `RESOURCE_LIMIT` |
| 35 | `ash292` | Table 7 | Tier1 | `nonzero_union` | 292 | 958 | 12 | 24 | 19 | False | — | 23 | False | `TIMEOUT_NO_SAT_MODEL` |
| 36 | `bcspwr04` | Table 7 | Tier1 | `nonzero_union` | 274 | 669 | 14 | 56 | 24 | False | — | 43 | False | `TIMEOUT_NO_SAT_MODEL` |
| 37 | `bcspwr05` | Table 7 | Tier1 | `nonzero_union` | 443 | 590 | 23 | 83 | 27 | False | — | 76 | False | `TIMEOUT_NO_SAT_MODEL` |
| 38 | `bcsstk06` | Table 7 | Tier1 | `nonzero_union` | 420 | 3720 | 27 | 47 | 45 | False | — | 47 | False | `TIMEOUT_NO_SAT_MODEL` |
| 39 | `bcsstk19` | Table 7 | Tier1 | `nonzero_union` | 817 | 3018 | 10 | 22 | 14 | False | — | 20 | False | `RESOURCE_LIMIT` |
| 40 | `bcsstk20` | Table 7 | Tier1 | `nonzero_union` | 485 | 1325 | 6 | 20 | 13 | False | — | 17 | False | `TIMEOUT_NO_SAT_MODEL` |
| 41 | `bcsstm07` | Table 7 | Tier1 | `nonzero_union` | 420 | 3416 | 27 | 47 | 45 | False | — | 47 | False | `TIMEOUT_NO_SAT_MODEL` |
| 42 | `bp_0` | Table 7 | Tier2 | `stored_union` | 822 | 3260 | 133 | 406 | 234 | False | — | 403 | False | `RESOURCE_LIMIT` |
| 43 | `bp_1000` | Table 7 | Tier2 | `stored_union` | 822 | 4635 | 154 | 532 | 283 | False | — | 531 | False | `RESOURCE_LIMIT` |
| 44 | `bp_1200` | Table 7 | Tier2 | `stored_union` | 822 | 4698 | 155 | 547 | 287 | False | — | 545 | False | `RESOURCE_LIMIT` |
| 45 | `bp_1400` | Table 7 | Tier2 | `stored_union` | 822 | 4760 | 155 | 536 | 291 | False | — | 535 | False | `RESOURCE_LIMIT` |
| 46 | `bp_1600` | Table 7 | Tier2 | `stored_union` | 822 | 4809 | 152 | 533 | 292 | False | — | 532 | False | `RESOURCE_LIMIT` |
| 47 | `bp_200` | Table 7 | Tier2 | `stored_union` | 822 | 3788 | 141 | 441 | 257 | False | — | 439 | False | `RESOURCE_LIMIT` |
| 48 | `bp_400` | Table 7 | Tier2 | `stored_union` | 822 | 4015 | 147 | 530 | 267 | False | — | 527 | False | `RESOURCE_LIMIT` |
| 49 | `bp_600` | Table 7 | Tier2 | `stored_union` | 822 | 4157 | 151 | 541 | 272 | False | — | 538 | False | `RESOURCE_LIMIT` |
| 50 | `bp_800` | Table 7 | Tier2 | `stored_union` | 822 | 4518 | 152 | 525 | 278 | False | — | 523 | False | `RESOURCE_LIMIT` |
| 51 | `can_292` | Table 7 | Tier1 | `nonzero_union` | 292 | 1124 | 30 | 64 | 38 | False | — | 56 | False | `TIMEOUT_NO_SAT_MODEL` |
| 52 | `can_445` | Table 7 | Tier1 | `nonzero_union` | 445 | 1682 | 37 | 92 | 52 | False | — | 92 | False | `TIMEOUT_NO_SAT_MODEL` |
| 53 | `can_715` | Table 7 | Tier1 | `nonzero_union` | 715 | 2975 | 52 | 145 | 71 | False | — | 131 | False | `RESOURCE_LIMIT` |
| 54 | `can_838` | Table 7 | Tier1 | `nonzero_union` | 838 | 4586 | 70 | 184 | 86 | False | — | 177 | False | `RESOURCE_LIMIT` |
| 55 | `dwt_209` | Table 7 | Tier1 | `nonzero_union` | 209 | 767 | 18 | 42 | 23 | True | 41 | 36 | False | `SAT_FEASIBLE` |
| 56 | `dwt_221` | Table 7 | Tier1 | `nonzero_union` | 221 | 704 | 9 | 27 | 13 | True | 17 | 17 | False | `SAT_FEASIBLE` |
| 57 | `dwt_234` | Table 7 | Tier1 | `nonzero_union` | 234 | 300 | 9 | 25 | 11 | False | — | 20 | False | `TIMEOUT_NO_SAT_MODEL` |
| 58 | `dwt_245` | Table 7 | Tier1 | `nonzero_union` | 245 | 608 | 15 | 40 | 21 | True | 38 | 34 | False | `SAT_FEASIBLE` |
| 59 | `dwt_310` | Table 7 | Tier1 | `nonzero_union` | 310 | 1069 | 8 | 13 | 12 | False | — | 13 | False | `TIMEOUT_NO_SAT_MODEL` |
| 60 | `dwt_361` | Table 7 | Tier1 | `nonzero_union` | 361 | 1296 | 12 | 25 | 14 | False | — | 25 | False | `TIMEOUT_NO_SAT_MODEL` |
| 61 | `dwt_419` | Table 7 | Tier1 | `nonzero_union` | 419 | 1572 | 19 | 55 | 25 | False | — | 55 | False | `TIMEOUT_NO_SAT_MODEL` |
| 62 | `dwt_503` | Table 7 | Tier1 | `nonzero_union` | 503 | 2762 | 22 | 64 | 41 | False | — | 60 | False | `RESOURCE_LIMIT` |
| 63 | `dwt_592` | Table 7 | Tier1 | `nonzero_union` | 592 | 2256 | 16 | 42 | 29 | False | — | 38 | False | `RESOURCE_LIMIT` |
| 64 | `dwt_878` | Table 7 | Tier1 | `nonzero_union` | 878 | 3285 | 22 | 37 | 25 | False | — | 37 | False | `RESOURCE_LIMIT` |
| 65 | `dwt_918` | Table 7 | Tier1 | `nonzero_union` | 918 | 3233 | 22 | 72 | 32 | False | — | 69 | False | `RESOURCE_LIMIT` |
| 66 | `dwt_992` | Table 7 | Tier1 | `nonzero_union` | 992 | 7876 | 34 | 63 | 35 | False | — | 63 | False | `RESOURCE_LIMIT` |
| 67 | `fs_541_1` | Table 7 | Tier2 | `stored_union` | 541 | 2466 | 270 | 535 | 270 | False | — | 469 | False | `RESOURCE_LIMIT` |
| 68 | `fs_680_1` | Table 7 | Tier2 | `stored_union` | 680 | 1464 | 16 | 24 | 17 | False | — | 24 | False | `RESOURCE_LIMIT` |
| 69 | `fs_760_1` | Table 7 | Tier2 | `stored_union` | 760 | 3518 | 33 | 62 | 37 | False | — | 62 | False | `RESOURCE_LIMIT` |
| 70 | `gr_30_30` | Table 7 | Tier1 | `nonzero_union` | 900 | 3422 | 31 | 31 | 33 | False | — | 31 | False | `RESOURCE_LIMIT` |
| 71 | `gre_216a` | Table 7 | Tier2 | `stored_union` | 216 | 660 | 11 | 21 | 21 | False | — | 21 | False | `TIMEOUT_NO_SAT_MODEL` |
| 72 | `gre_343` | Table 7 | Tier2 | `stored_union` | 343 | 1092 | 15 | 28 | 28 | False | — | 28 | False | `TIMEOUT_NO_SAT_MODEL` |
| 73 | `gre_512` | Table 8 | Tier2 | `stored_union` | 512 | 1680 | 19 | 36 | 36 | False | — | 36 | False | `RESOURCE_LIMIT` |
| 74 | `hor_131` | Table 8 | Tier2 | `stored_union` | 434 | 2138 | 40 | 101 | 54 | False | — | 101 | False | `TIMEOUT_NO_SAT_MODEL` |
| 75 | `impcol_a` | Table 8 | Tier2 | `stored_union` | 207 | 557 | 19 | 70 | 32 | True | 60 | 60 | False | `SAT_FEASIBLE` |
| 76 | `impcol_d` | Table 8 | Tier2 | `stored_union` | 425 | 1267 | 31 | 70 | 39 | False | — | 66 | False | `TIMEOUT_NO_SAT_MODEL` |
| 77 | `impcol_e` | Table 8 | Tier2 | `stored_union` | 225 | 1187 | 25 | 78 | 42 | False | — | 70 | False | `TIMEOUT_NO_SAT_MODEL` |
| 78 | `jagmesh1` | Table 8 | Tier1 | `nonzero_union` | 936 | 2664 | 20 | 27 | 27 | False | — | 27 | False | `RESOURCE_LIMIT` |
| 79 | `jpwh_991` | Table 8 | Tier2 | `stored_union` | 991 | 2678 | 71 | 172 | 88 | False | — | 172 | False | `RESOURCE_LIMIT` |
| 80 | `lns_511` | Table 8 | Tier2 | `stored_union` | 511 | 1425 | 26 | 58 | 44 | False | — | 57 | False | `RESOURCE_LIMIT` |
| 81 | `mbeacxc` | Table 8 | Tier2 | `stored_union` | 496 | 41686 | 243 | 480 | 260 | False | — | 480 | False | `TIMEOUT_NO_SAT_MODEL` |
| 82 | `mbeaflw` | Table 8 | Tier2 | `stored_union` | 496 | 41686 | 243 | 480 | 260 | False | — | 471 | False | `TIMEOUT_NO_SAT_MODEL` |
| 83 | `mbeause` | Table 8 | Tier2 | `nonzero_union` | 496 | 36209 | 245 | 473 | 254 | False | — | 473 | False | `TIMEOUT_NO_SAT_MODEL` |
| 84 | `mcfe` | Table 8 | Tier2 | `stored_union` | 765 | 15358 | 73 | 187 | 126 | False | — | 187 | False | `RESOURCE_LIMIT` |
| 85 | `nnc261` | Table 8 | Tier2 | `stored_union` | 261 | 794 | 17 | 39 | 24 | True | 36 | 35 | False | `SAT_FEASIBLE` |
| 86 | `nnc666` | Table 8 | Tier2 | `stored_union` | 666 | 2148 | 28 | 66 | 40 | False | — | 63 | False | `RESOURCE_LIMIT` |
| 87 | `nos1` | Table 8 | Tier1 | `nonzero_union` | 237 | 390 | 3 | 4 | 3 | False | — | 3 | True | `OPTIMAL_PROVED` |
| 88 | `nos2` | Table 8 | Tier1 | `nonzero_union` | 957 | 1590 | 3 | 4 | 3 | False | — | 4 | False | `RESOURCE_LIMIT` |
| 89 | `nos3` | Table 8 | Tier1 | `nonzero_union` | 960 | 7442 | 42 | 43 | 44 | False | — | 43 | False | `RESOURCE_LIMIT` |
| 90 | `nos5` | Table 8 | Tier1 | `nonzero_union` | 468 | 2352 | 43 | 88 | 63 | False | — | 88 | False | `TIMEOUT_NO_SAT_MODEL` |
| 91 | `nos6` | Table 8 | Tier1 | `nonzero_union` | 675 | 1290 | 12 | 30 | 16 | False | — | 30 | False | `RESOURCE_LIMIT` |
| 92 | `nos7` | Table 8 | Tier1 | `nonzero_union` | 729 | 1944 | 31 | 65 | 65 | False | — | 65 | False | `RESOURCE_LIMIT` |
| 93 | `orsirr_2` | Table 8 | Tier1 | `nonzero_union` | 886 | 2542 | 53 | 157 | 85 | False | — | 156 | False | `RESOURCE_LIMIT` |
| 94 | `plat362` | Table 8 | Tier1 | `nonzero_union` | 362 | 2712 | 23 | 52 | 34 | False | — | 52 | False | `TIMEOUT_NO_SAT_MODEL` |
| 95 | `plskz362` | Table 8 | Tier1 | `nonzero_union` | 362 | 880 | 12 | 34 | 18 | False | — | 33 | False | `TIMEOUT_NO_SAT_MODEL` |
| 96 | `pores_3` | Table 8 | Tier2 | `stored_union` | 532 | 1850 | 11 | 20 | 13 | False | — | 20 | False | `TIMEOUT_NO_SAT_MODEL` |
| 97 | `saylr1` | Table 8 | Tier1 | `nonzero_union` | 238 | 445 | 9 | 14 | 14 | False | — | 14 | False | `TIMEOUT_NO_SAT_MODEL` |
| 98 | `saylr3` | Table 8 | Tier1 | `nonzero_union` | 1000 | 1375 | 26 | 67 | 46 | False | — | 67 | False | `RESOURCE_LIMIT` |
| 99 | `sherman1` | Table 8 | Tier1 | `nonzero_union` | 1000 | 1375 | 26 | 67 | 46 | False | — | 66 | False | `RESOURCE_LIMIT` |
| 100 | `sherman4` | Table 8 | Tier1 | `nonzero_union` | 1104 | 1341 | 17 | 41 | 27 | False | — | 41 | False | `RESOURCE_LIMIT` |
| 101 | `shl_0` | Table 8 | Tier2 | `stored_union` | 663 | 1682 | 211 | 422 | 224 | False | — | 419 | False | `RESOURCE_LIMIT` |
| 102 | `shl_200` | Table 8 | Tier2 | `stored_union` | 663 | 1720 | 220 | 437 | 233 | False | — | 433 | False | `RESOURCE_LIMIT` |
| 103 | `shl_400` | Table 8 | Tier2 | `stored_union` | 663 | 1709 | 213 | 432 | 229 | False | — | 430 | False | `RESOURCE_LIMIT` |
| 104 | `steam1` | Table 8 | Tier2 | `stored_union` | 240 | 1761 | 24 | 50 | 44 | False | — | 47 | False | `TIMEOUT_NO_SAT_MODEL` |
| 105 | `steam2` | Table 8 | Tier2 | `stored_union` | 600 | 6580 | 40 | 63 | 63 | False | — | 63 | False | `RESOURCE_LIMIT` |
| 106 | `str_0` | Table 8 | Tier2 | `stored_union` | 363 | 2446 | 61 | 221 | 115 | False | — | 217 | False | `TIMEOUT_NO_SAT_MODEL` |
| 107 | `str_200` | Table 8 | Tier2 | `stored_union` | 363 | 3049 | 61 | 225 | 124 | False | — | 218 | False | `TIMEOUT_NO_SAT_MODEL` |
| 108 | `str_600` | Table 8 | Tier2 | `stored_union` | 363 | 3244 | 61 | 230 | 131 | False | — | 228 | False | `TIMEOUT_NO_SAT_MODEL` |
| 109 | `west0381` | Table 8 | Tier2 | `stored_union` | 381 | 2150 | 95 | 264 | 149 | False | — | 252 | False | `TIMEOUT_NO_SAT_MODEL` |
| 110 | `west0479` | Table 8 | Tier2 | `stored_union` | 479 | 1889 | 60 | 236 | 119 | False | — | 228 | False | `TIMEOUT_NO_SAT_MODEL` |
| 111 | `west0497` | Table 8 | Tier2 | `stored_union` | 497 | 1715 | 56 | 256 | 85 | False | — | 243 | False | `TIMEOUT_NO_SAT_MODEL` |
| 112 | `west0655` | Table 8 | Tier2 | `stored_union` | 655 | 2841 | 94 | 342 | 157 | False | — | 340 | False | `RESOURCE_LIMIT` |
| 113 | `west0989` | Table 8 | Tier2 | `stored_union` | 989 | 3500 | 110 | 475 | 207 | False | — | 471 | False | `RESOURCE_LIMIT` |
