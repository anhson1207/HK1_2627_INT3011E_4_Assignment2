# Phase M3.6: Unified Multi-Method Benchmark & Scientific Comparison Report

**Nhánh thực nghiệm**: `dev/member-3` (base HEAD trước M3.6: `eca71ac` sau M3.5)  
**Mã chiến dịch thực nghiệm (`experiment_id`)**: `m3_6_unified_v1`  
**Tệp cấu hình**: [`configs/member3_m3_6.toml`](../configs/member3_m3_6.toml)  
**Runner & Plotting**: [`src/bmp/experiments/member3_m3_6.py`](../src/bmp/experiments/member3_m3_6.py), [`src/bmp/experiments/member3_m3_6_plots.py`](../src/bmp/experiments/member3_m3_6_plots.py), [`scripts/run_member3_m3_6.py`](../scripts/run_member3_m3_6.py)

---

## 1. Tóm tắt điều hành (Executive Summary)

Giai đoạn **M3.6** thống nhất toàn bộ **10 phương pháp** thuộc 4 họ thuật toán (`SAT`, `MIP`, `CP`, `Heuristic`) trong cùng một hệ thống benchmark có tính tái lập, công bằng theo rào cản phần cứng/bản quyền thực tế, và tách biệt rõ rạch ròi giữa **lời giải tối ưu được chứng minh (`OPTIMAL`)**, **nghiệm khả thi chưa chứng minh tối ưu (`FEASIBLE` / `TIMEOUT`)**, **bị chặn bởi bộ nhớ/kích thước (`RESOURCE_LIMIT`)** và **bị chặn bởi giới hạn bản quyền (`UNAVAILABLE`)**.

- **Tổng số lượt chạy kế hoạch & hoàn tất**: **500 / 500 lượt** (`pending_runs = 0`), chia qua 5 giai đoạn:
  - **Stage A (`Stage_A_SmallOracle`)**: `40` lượt trên 4 đồ thị chuẩn nhỏ (`P6`, `C6`, `chord_P6`, `grid3x3`) × 10 phương pháp — **28/28 `OPTIMAL`** đối với toàn bộ phương pháp chính xác (`SAT`, `MIP`, `CP`), **12/12 `FEASIBLE`** đối với heuristic, **0 sai lệch oracle**.
  - **Stage B (`Stage_B_Heuristic_54`)**: `276` lượt trên toàn bộ **54 Harwell–Boeing `READY`** (`nonzero_union v1.0`), gồm 54 × 4 chiến lược tại `seed=17` + lặp 3 seeds `[17, 23, 42]` trên tập 10 đồ thị đại diện cho `SA`, `DRSA Warm (MODIFIED_VARIANT)` và `DRSA Paper-Faithful Bounded` — **276/276 `FEASIBLE`**, `0` lỗi.
  - **Stage C (`Stage_C_Exact_Baseline`)**: `98` lượt trên 10 đồ thị đại diện `READY` (`n=39..238`, timeout `15.0s`, `threads=1`), gồm `NO_WARM_START`, `SHARED_RCM_WARM` và `SHARED_DRSA_WARM` (`0.5s` warmup). Kết quả: `6 OPTIMAL`, `36 FEASIBLE`, `31 TIMEOUT`, `25 UNAVAILABLE` (do chặn bản quyền CPLEX CE / Gurobi size-limited / IBM CP Optimizer CE $2^{1000}$).
  - **Stage D (`Stage_D_SAT_Studies`)**: `74` lượt cho 5 nghiên cứu có kiểm soát (`SAT-A` backends, `SAT-B` Pairwise vs Order, `SAT-C` 6 AMO, `SAT-D` Repeated vs Incremental, `SAT-E` Symmetry Breaking) tại timeout `10.0s`, `threads=1` — `72 TIMEOUT` (đều có incumbent hợp lệ được validator xác nhận), `2 RESOURCE_LIMIT` (Pairwise trên `nos4` và `saylr1` bị chặn an toàn bởi preflight estimator).
  - **Stage E (`Stage_E_Extended`)**: `12` lượt ngân sách mở rộng (`60.0s` cho `CP-SAT` & `CaDiCaL` với `SHARED_DRSA_WARM`, `5.0s` cho `DRSA Warm`) trên 4 đồ thị triển vọng (`bcsstk01`, `nos4`, `nos1`, `saylr1`).
- **Xác thực độc lập (`validate_solution`, M3.5 canonical validator)**: **`471 / 471`** lượt có nghiệm (`FEASIBLE`/`OPTIMAL` hoặc `TIMEOUT` có incumbent) vượt qua kiểm tra toán học (**`0` validation failures**, **`0` dưới cận dưới đã công bố**). 29 lượt còn lại là `25 UNAVAILABLE`, `2 RESOURCE_LIMIT` và `2 TIMEOUT` không tìm được incumbent (`CP-SAT NO_WARM_START` trên `nos1`, `CP-SAT SHARED_DRSA_WARM` 15s trên `saylr1`).
- **Tác động trùng lặp topology (`saylr3 == sherman1`)**: M3.5 chứng minh `saylr3` và `sherman1` có cùng `topology_sha256` (`n=1000, m=1375`). Thống kê được báo cáo song song theo cả **`INSTANCE_WEIGHTED_54`** và **`TOPOLOGY_UNIQUE_53`** (`mean_gap_overall`: `20.3148` vs `20.3019`, `median_gap`: `14.0` vs `14.0`).

---

## 2. Môi trường phần cứng, phần mềm & Ma trận kiểm tra trước (Preflight Audit)

### 2.1 Phần cứng & phiên bản phần mềm

Dữ liệu từ [`results/member3_m3_6/metadata.json`](../results/member3_m3_6/metadata.json):

| Thành phần | Giá trị ghi nhận thực tế |
|---|---|
| Hệ điều hành / Kiến trúc | `macOS-14.0-arm64-arm-64bit-Mach-O` (`arm64`) |
| CPU / Số luồng thực nghiệm | `Apple M2` (`8` cores; cố định `threads = 1` cho so sánh) |
| RAM hệ thống / Giới hạn bộ nhớ | `16.0 GB` / `memory_limit_mb = 4096.0 MB` |
| Python | `3.14.3` |
| Gói thư viện chính | `python-sat 1.9.dev17`, `ortools 9.15.6755`, `gurobipy 13.0.3`, `cplex 22.2.0.1`, `docplex 2.32.264`, `cnsplots 0.8.0`, `matplotlib 3.11.2`, `pandas 2.3.3`, `numpy 2.4.6`, `scipy 1.18.1`, `pytest 9.1.1` |

### 2.2 Phân loại solver & giới hạn bản quyền thực tế

| Họ | Phương pháp | Phiên bản runtime | Phân loại M3.6 | Hạn mức bản quyền / Guard áp dụng |
|---|---|---|---|---|
| SAT | `cadical` (`CadicalBackend`) | `cadical195` (PySAT) | `SOLVER_VERIFIED` | `OPEN_SOURCE_PYTHON_SAT`; `ResourceLimits(vars <= 500,000, clauses <= 2,500,000)` |
| SAT | `glucose` (`GlucoseBackend`) | `glucose4` (PySAT) | `SOLVER_VERIFIED` | `OPEN_SOURCE_PYTHON_SAT`; `ResourceLimits` như trên |
| SAT | `minisat` (`MinisatBackend`) | `minisat22` (PySAT) | `SOLVER_VERIFIED` | `OPEN_SOURCE_PYTHON_SAT`; `ResourceLimits` như trên |
| MIP | `gurobi` (`GurobiMIPSolver`) | `13.0.3` | `SOLVER_AVAILABLE_WITH_LIMITATIONS` | `SIZE_LIMITED_EVAL`: tối đa `2,000` biến & `2,000` ràng buộc |
| MIP | `cplex` (`CPLEXMIPSolver`) | `22.2.0.0` | `SOLVER_AVAILABLE_WITH_LIMITATIONS` | `COMMUNITY_EDITION`: tối đa `1,000` biến & `1,000` ràng buộc |
| CP | `cp-sat` (`CPSATSolver`) | `9.15.6755` | `SOLVER_VERIFIED` | `OPEN_SOURCE_APACHE2`; không giới hạn size bản quyền |
| CP | `cp-optimizer` (`CPOptimizerSolver`) | `22.2.0.0` (`docplex 2.32.264`) | `SOLVER_AVAILABLE_WITH_LIMITATIONS` | `COMMUNITY_EDITION_2P1000`: trần không gian tìm kiếm $2^{1000}$ (thử sống xác nhận $n=132$ hợp lệ, $n=144$ lỗi `error1016` tại $\approx 2^{1039.6}$) |
| Heuristic | `rcm` (`RCMSolver`) | `m3.5` | `SOLVER_VERIFIED` | `BUILTIN_PROJECT` (tất định $O(n+m)$) |
| Heuristic | `sa` (`SimulatedAnnealingSolver`) | `m3.5` | `SOLVER_VERIFIED` | `BUILTIN_PROJECT` (`initial_mode="rcm"`, $T_0=2.0, \alpha=0.9999$) |
| Heuristic | `drsa` (`DRSASolver`) | `m3.5` | `SOLVER_VERIFIED` | `BUILTIN_PROJECT` (`PAPER_FAITHFUL` & `MODIFIED_VARIANT`) |

### 2.3 Kết quả Preflight toàn bộ 54 đồ thị READY (`preflight_54.csv`: 540 lượt đánh giá)

Từ [`results/member3_m3_6/preflight_54.csv`](../results/member3_m3_6/preflight_54.csv) (xem `fig04_preflight_eligibility_54.svg`):

| Phương pháp | `ELIGIBLE` (/54) | `RESOURCE_LIMIT` (/54) | `BLOCKED_LICENSE` (/54) | Ngưỡng cắt ghi nhận thực tế |
|---|---:|---:|---:|---|
| `cp-sat`, `rcm`, `sa`, `drsa` | **54** | 0 | 0 | Chạy được 100% tập READY ($n \le 1104$) |
| `cadical`, `glucose`, `minisat` (Order+Seq) | **25** | **29** | 0 | Đỉnh hợp lệ lớn nhất: `plskz362` ($n=362, m=880$, `392,408` vars, `1,549,773` clauses). Bị chặn đầu tiên tại `plat362` ($2,872,477 > 2,500,000$ clauses) và từ `dwt_419` trở lên (`525,845 > 500,000` vars) |
| `cp-optimizer` | **8** | 0 | **46** | Hợp lệ tới `bcsstk22` ($n=138, \log_2 \approx 988.08 \le 1000$). Chặn từ `can_144` ($n=144, \log_2 \approx 1039.64$) |
| `gurobi` (`SIZE_LIMITED_EVAL`) | **1** | 0 | **53** | Duy nhất `bcspwr01` ($n=39 \Rightarrow 1,522$ biến, `171` ràng buộc $\le 2,000$). Chặn từ `bcsstk01` ($n=48 \Rightarrow 2,305$ biến) |
| `cplex` (`COMMUNITY_EDITION`) | **0** | 0 | **54** | Ngay cả đồ thị nhỏ nhất `bcspwr01` cần `1,522` biến ($> 1,000$). Đạt chuẩn trên `Stage A` ($n \le 9$) |

---

## 3. Phân tích Stage A: Kiểm chứng Oracle trên đồ thị chuẩn nhỏ (40 lượt)

Trên 4 đồ thị chuẩn xác định chính xác bằng toán học/brute-force:
- `oracle_p6` ($n=6, m=5, B^*=1$)
- `oracle_c6` ($n=6, m=6, B^*=2$)
- `oracle_chord_p6` ($n=6, m=6, B^*=2$)
- `oracle_grid3x3` ($n=9, m=12, B^*=3$)

**Kết quả**:
- Toàn bộ **28/28 lượt** của 7 solver chính xác (`cadical`, `glucose`, `minisat`, `gurobi`, `cplex`, `cp-sat`, `cp-optimizer`) đều trả về **`OPTIMAL`** và khớp tuyệt đối $B^*$ (`0` sai lệch).
- Toàn bộ **12/12 lượt** của 3 heuristic (`rcm`, `sa`, `drsa_modified_variant`) trả về **`FEASIBLE`** và cũng đạt đúng bằng $B^*$ trên cả 4 đồ thị.
- Thời gian giải SAT dao động $0.000\text{s} - 0.0028\text{s}$ (`total_wall_time_s` $0.014\text{s} - 0.061\text{s}$); Gurobi/CPLEX $0.0056\text{s} - 0.045\text{s}$; CP-SAT $0.0094\text{s} - 0.024\text{s}$; CP Optimizer $0.0066\text{s} - 0.041\text{s}$ (`0.030\text{s} - 0.142\text{s}` wall gồm khởi tạo binary ngoài); RCM $< 0.0004\text{s}$.

---

## 4. Phân tích Stage B: Đánh giá Heuristic trên toàn bộ 54 Harwell–Boeing READY (276 lượt)

Tất cả heuristic dùng `0.8s` cho mỗi lượt đánh giá có kiểm soát (RCM tất định kết thúc tức thời; median `0.0535s`).

### 4.1 Hiệu năng toàn tập 54 READY tại `seed = 17` (`fig10_heuristics_54_ready.svg`)

| Phương pháp | Cấu hình khởi tạo & lịch | Số lượt | Khớp Published Best | Mean BW | Median BW | Mean Gap vs Pub Best | Median Gap | Median Wall Time (s) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `rcm` | Tất định Cuthill–McKee | 54 | 5 / 54 | 49.56 | 40.5 | 21.06 | 14.0 | **0.0535** |
| `sa` | `rcm` + $T_0=2.0, \alpha=0.9999$ | 54 | 5 / 54 | 49.37 | 40.5 | 20.87 | 14.0 | 0.8572 |
| `drsa_modified_variant` | `rcm` + $T_0=2.0, \alpha=0.99, L_0=40$ | 54 | 5 / 54 | **49.30** | **40.5** | **20.80** | **14.0** | 0.8575 |
| `drsa_paper_faithful` | `random` + $T_0=1000, \alpha=0.99, L_0=40$ | 54 | 0 / 54 | 444.80 | 394.5 | 416.30 | 361.0 | 0.8586 |

Phân tách theo bảng công bố gốc (`seed = 17`):
- **Table 6 ($N=13$)**: `DRSA Warm` đạt mean gap `6.08` (median `4.0`) tốt hơn `SA` (`6.31`, `4.0`) và `RCM` (`7.08`, `5.0`); khớp best trên `lund_a=23`, `lund_b=23` (khi chạy thêm seed `[23, 42]` hoặc `5s` ở Stage E, `DRSA Warm` còn khớp thêm `bcsstk01=16`, `SA` khớp qua `lund_a`/`lund_b`/`saylr1`/`nos7`/`jagmesh1` và các seed mở rộng).
- **Table 7 ($N=27$)**: `DRSA Warm` (`mean_gap=29.85, median=23.0`) > `SA` (`29.89`) = `RCM` (`29.89`). Đây là nhóm đồ thị khó nhất trong `0.8s` (`0/27` khớp bài báo dài hạn).
- **Table 8 ($N=14$)**: cả 3 biến thể xuất phát từ RCM đều khớp published best trên **3/14** đồ thị (`saylr1=14`, `nos7=65`, `jagmesh1=27`; `mean_gap=17.00, median=15.0`).

### 4.2 So sánh ghép cặp có kiểm soát (`paired_comparisons.csv`)

1. **`RCM` vs `SA` (54 cặp, Stage B `0.8s`, `seed=17`)**: `SA` thắng **2**, hòa **52**, thua **0** (`mean_bw_diff = +0.1852`, cải thiện cụ thể `bcsstk01`: `27 -> 19` và `bcspwr02`: `13 -> 11`).
2. **`SA` vs `DRSA Warm` (54 cặp, Stage B `0.8s`, `seed=17`)**: cùng xuất phát từ `RCM` và cùng ngân sách `0.8s`, `DRSA Warm` thắng **3**, hòa **51**, thua **0** (`bcspwr01`: `8 -> 6`, `bcsstk01`: `19 -> 18`, `bcspwr05`: `83 -> 82`; `mean_bw_diff = +0.0741`, `max_bw_diff = 2`, `mean_wall_diff_s = -0.0038s`). Lưu ý: đây là cải thiện biên nhẹ trên đúng cấu hình `seed=17, 0.8s` (51/54 cặp hòa), chưa đủ bằng chứng để kết luận vượt trội thống kê toàn cục trên toàn bộ 54 đồ thị với đa seed.
3. **`DRSA Paper-Faithful Bounded (0.8s)` vs `DRSA Warm` (54 cặp, Stage B `0.8s`, `seed=17`)**: `DRSA Warm` thắng **54 / 54** cặp (`mean_bw_diff = 395.5`, `median_diff = 319.0`, `max = 1006`, `mean_wall_diff_s = 0.0073s`). **Phát hiện thực nghiệm quan trọng**: cấu hình bài báo gốc (`random` init, $T_0=1000.0$) đòi hỏi chuỗi Markov rất dài để hạ nhiệt và thoát pha đi dạo ngẫu nhiên ở nhiệt độ cao; dưới ngân sách ngắn `0.8s` trên các đồ thị $n \in [39, 1104]$, thuật toán bị ngắt trước khi làm nguội (`mean_gap = 416.30`, `execution_regime = BOUNDED_TIMEOUT` — tuyệt đối không được đồng nhất với hiệu năng chạy hết lịch $T_f = 10^{-7}$ của bài báo gốc). Khởi tạo RCM kết hợp $T_0=2.0$ là thiết yếu cho ứng dụng thực tế dưới giới hạn giây.

### 4.3 Độ ổn định đa hạt giống (`seeds = [17, 23, 42]` trên 10 đồ thị đại diện)

- `SA`: **9 / 10** đồ thị có độ lệch chuẩn bằng `0.0` (`mean_std = 0.200`, `max_std = 2.000`, chỉ biến thiên trên `bcsstk01`: `{17: 19, 23: 23, 42: 21}`).
- `DRSA Warm`: **7 / 10** đồ thị có độ lệch chuẩn bằng `0.0` (`mean_std = 0.422`, `max_std = 2.646`, biến thiên trên `bcspwr01`: `{6, 7, 8}`, `bcspwr02`: `{11, 10, 10}`, `bcsstk01`: `{18, 23, 22}`).
- `DRSA Paper-Faithful`: chỉ **1 / 10** đồ thị ổn định (`mean_std = 1.271`, `max_std = 3.000`).

---

## 5. Phân tích Stage C & Nghiên cứu có kiểm soát theo từng họ Solver

### 5.1 Họ SAT — Tổng hợp 5 nghiên cứu có kiểm soát (Stage D: 74 lượt, `timeout=10s`, `threads=1`)

1. **Study SAT-A (`fig05_sat_backends_comparison.svg`): So sánh Backend (`CaDiCaL` vs `Glucose` vs `MiniSat`) trên `Order + Sequential + Incremental + Sym`** (`18` lượt trên 6 đồ thị: `bcspwr01`, `bcsstk01`, `bcspwr02`, `ash85`, `nos4`, `saylr1`):
   - Trên `6` đồ thị mục tiêu, không backend nào chứng minh tối ưu (`UNSAT`) kịp trong `10s`; mọi backend đều giữ nguyên hợp lệ lời giải incumbent từ RCM nội bộ ở đầu quá trình tìm kiếm tuyến tính xuống.
   - Do khác biệt tốc độ propagation & thời điểm ngắt ở biên timeout `10s`, trong chính `SAT_A_Backends` trên `bcsstk01` và `bcspwr02`: **`Glucose`** khớp `bcspwr02=7` và hạ `bcsstk01` xuống `22` (`matched=3/6`, thắng `CaDiCaL` 2, hòa 4, `mean_bw_diff = +0.8333`, `max=3`), **`MiniSat`** thắng `CaDiCaL` `1` (trên `bcsstk01`: `23` vs `25`), hòa `5` (`mean_bw_diff = +0.3333`, `matched=2/6`), đều là kết quả `TIMEOUT` chưa chứng minh `UNSAT`. Peak RSS tối đa trên tập `n<=238`: `Glucose` (`265.91 MB`) và `MiniSat` (`238.25 MB`) nhẹ hơn so với `CaDiCaL` trên `saylr1` (`343.14 MB`).
2. **Study SAT-B (`fig06_sat_pairwise_vs_order.svg`): Pairwise Position Encoding vs Order Encoding (`CaDiCaL + Sequential + Incremental`)** (`12` lượt):
   - Khẳng định vượt trội tuyệt đối về mặt cấu trúc của **Order Encoding** $O(m(n-k))$ so với **Pairwise** $O(mn^2)$:
     - `bcspwr01` ($n=39$): Order `19,168` clauses vs Pairwise `57,448` clauses (`3.0x`).
     - `ash85` ($n=85$): Order `82,746` clauses (`142.19 MB` RSS) vs Pairwise **`1,291,097` clauses** (`527.03 MB` RSS — **gấp `15.6x`** số mệnh đề và `3.7x` RAM!).
     - `nos4` ($n=100$) & `saylr1` ($n=238$): Pairwise vọt lên **`2,504,650`** và **`25,438,987` clauses**, bị **Resource Guard** (`max_clauses = 2,500,000`) chặn an toàn (`RESOURCE_LIMIT`), trong khi Order giải chỉ dùng `112,179` (`154 MB`) và `593,965` (`335 MB`).
   - Toàn tập: Order có `best_bw=5`, `median_gap=0.3333`, so với Pairwise `best_bw=6`, `median_gap=0.4359` và `0` matched best.
3. **Study SAT-C (`fig07_sat_six_amo_variants.svg`): So sánh 6 biến thể At-Most-One (`Order + CaDiCaL + Incremental`)** (`24` lượt trên `bcspwr01, bcsstk01, bcspwr02, ash85`):
   - **Tương đương toán học giữa `Ladder` và `Sequential`**: đo đếm trực tiếp trên cả 4 đồ thị xác nhận **`Ladder == Sequential` chính xác tới từng biến và từng mệnh đề** (ví dụ `ash85`: cùng `21,505` biến và `82,746` mệnh đề; `bcspwr01`: cùng `4,485` biến và `19,168` mệnh đề), khớp định lý $m \ge 3$ trong [`src/bmp/encodings/cardinality/ladder.py`](../src/bmp/encodings/cardinality/ladder.py).
   - **So sánh 5 họ thực sự khác biệt về cấu trúc**:
     - `Pairwise AMO`: không cần biến phụ (tổng biến ít nhất: `3,003` trên `bcspwr01`, `14,365` trên `ash85`), nhưng số mệnh đề tăng bậc hai mạnh nhất (**`364,861`** trên `ash85`, **`317.19 MB` RSS**, gấp `4.4x` so với Sequential/Product/Commander).
     - `Binary`: ít biến hơn Sequential (`14,960` trên `ash85`), mệnh đề lớn hơn một chút (`111,986`), `162.58 MB` RSS, `median_gap = 0.275`.
     - `Product`: nhỏ gọn nhất về cả biến phụ lẫn mệnh đề trong nhóm phụ tuyến tính (**`15,980` biến** và **`82,746` mệnh đề** trên `ash85`, **peak RSS thấp nhất `148.80 MB`** trong 6 biến thể, `median_gap = 0.275`).
     - `Commander`: trung hòa tốt (`18,190` biến, `82,916` mệnh đề trên `ash85`, `154.34 MB` RSS; đạt `bw=22` trên `bcsstk01`).
4. **Study SAT-D (`fig08_sat_repeated_vs_incremental.svg`): Repeated vs Incremental SAT (`CaDiCaL + Order + Sequential`)** (`12` lượt):
   - Ở ngưỡng `10s`, trên `bcspwr01`, `bcsstk01`, `bcspwr02`, `Repeated` và `Incremental` thực hiện được gần bằng nhau số bước kiểm tra `SAT_calls` (`3`, `4`, `4-5`), trong đó `Repeated` tạo lại CNF hoàn chỉnh mỗi bước nên tổng mệnh đề bước cuối ít hơn (`13,464` vs `19,168` trên `bcspwr01` vì Incremental tích lũy các mệnh đề chặn băng thông các bước trước), còn Incremental tái sử dụng mệnh đề học được (conflict clauses) khi giải tới ngưỡng sâu hơn hoặc đồ thị dễ chứng minh hơn (như trên Leader small suite). Lưu ý khi timeout xảy ra ở bước đang chạy trong worker subprocess (`ash85, nos4, saylr1`), bộ đếm `SAT_calls` chỉ ghi số bước hoàn tất (`0`), còn `total_wall_time_s` phản ánh chính xác thời gian `~10.02–10.31s` đã tiêu thụ.
5. **Study SAT-E: Reversal Symmetry Breaking (`False` vs `True`)** (`8` lượt trên `bcspwr01..ash85`):
   - Phá đối xứng đảo nhãn $p'(v) = n+1-p(v)$ thêm **đúng `1` unit clause** (`19,167 -> 19,168` trên `bcspwr01`; `82,745 -> 82,746` trên `ash85`), giữ nguyên hoặc cải thiện tính hợp lệ tìm kiếm với chi phí mã hóa bằng `0`. Dưới timeout cố định `10s`, số liệu `ash85`, `bcspwr02`, `bcspwr01` giữ nguyên (`10`, `9`, `5`), còn trên `bcsstk01` sự thay đổi thứ tự nhánh tạo dao động nhỏ một lượt (`22` ở `False` vs `23` ở `True`).

### 5.2 Họ MIP — Gurobi 13.0.3 vs IBM CPLEX 22.2.0.0 (`Stage C`)

- Vì mô hình Assignment MIP đòi hỏi $n^2 + 1$ biến nhị phân/liên tục và $O(m)$ ràng buộc cạnh:
  - **`IBM CPLEX 22.2.0.0 Community Edition` (cap `1,000` vars / `1,000` constrs)**: bị chặn 10/10 trên đại diện Stage C (54/54 toàn HB), chỉ giải chính xác được trên `Stage A` ($n \le 9$, 4/4 `OPTIMAL`).
  - **`Gurobi 13.0.3 Size-Limited Eval` (cap `2,000` vars / `2,000` constrs)**: hợp lệ duy nhất trên **`bcspwr01` ($n=39 \Rightarrow 1,522$ biến, `171` ràng buộc)**; đạt incumbent **`5`** (khớp `paper_best = 5`, `LB = 4`, `optimality_gap = 0.2`, `TIMEOUT` ở `15.025s` với `143.23 MB` RSS; không rút ngắn thêm khi thêm `SHARED_DRSA_WARM` ở `15.539s`). Từ $n \ge 48$ (`bcsstk01`: `2,305` biến), Gurobi bị chặn bản quyền một cách trung thực (`UNAVAILABLE`).

### 5.3 Họ Constraint Programming — OR-Tools CP-SAT vs IBM CP Optimizer (`fig09_cp_sat_vs_cp_optimizer.svg`)

Hai đại diện CP thể hiện hai thế mạnh bổ trợ rõ nét nhất trong toàn bộ 4 họ solver (`Stage C`, `15s`, `threads=1`):
- **Khả năng chứng minh tối ưu (`OPTIMAL`) và phủ quy mô — `OR-Tools CP-SAT`**:
  - Hợp lệ trên **100% đồ thị (`10/10` Stage C, `54/54` READY)**.
  - Là **phương pháp duy nhất chứng minh được `OPTIMAL`** trên Harwell–Boeing thật trong `15s`: **`bcspwr01 = 5`** (`1.457s`, `143.23 MB`) và **`bcspwr02 = 7`** (`6.004s` với `NO_WARM_START`, giảm còn **`4.917s`** khi dùng `SHARED_RCM_WARM`, tốc độ nhanh hơn `18.1%` tổng wall time!).
  - Trên `dwt_209`, `nos1`, `saylr1` ($n=209..238$) — nơi CP Optimizer vượt trần CE $2^{1000}$ — CP-SAT vẫn giải khả thi (`nos1 = 4`, `saylr1 = 14` khớp best).
- **Chất lượng nghiệm primal dưới ngân sách ngắn — `IBM CP Optimizer 22.2.0.0`**:
  - Trong phạm vi hợp lệ $n \log_2(n) \le 1000$ (`7/10` đồ thị Stage C, `n <= 138`), **IBM CP Optimizer đạt `5 / 7` matches published best** (`bcspwr01=5`, `bcspwr02=7`, **`ash85=9`**, **`nos4=10`**, **`bcsstk22=10`**) — nhiều hơn bất kỳ solver exact nào khác trên cùng 7 đồ thị này!
  - Bảng ghép cặp `CP_SAT_vs_CP_Optimizer_StageC_RCMWarm` trên 7 đồ thị cùng chạy được (`paired_comparisons.csv`): **`CP Optimizer` thắng 5, hòa 2, thua 0** trước `CP-SAT` về bandwidth đạt được (`mean_bw_diff = +3.57`, `median = +4`, chẳng hạn `bcsstk01`: `17` vs `24`, `bcspwr03`: `14` vs `21-22`, `nos4`: `10` vs `13-15`, `bcsstk22`: `10` vs `14`), với **`median_optimality_gap = 0.2222`** (thấp nhất mọi phương pháp trên HB) và Peak RSS riêng tiến trình con `cpoptimizer` chỉ `~1.5–3.16 MB`! Tuy nhiên, ở chiều ngược lại, CP Optimizer chưa khép được cận dưới (`OPTIMAL` count = `0/7` trên HB trong 15s, kể cả trên `bcspwr01` mặc dù dual `LB=5` đã bằng `5`).

---

## 6. Nghiên cứu tổng hợp xuyên họ, Warm-Start & Ngân sách mở rộng (`Stage C` & `Stage E`)

### 6.1 So sánh tổng hợp 10 đại diện Stage C (`fig01`, `fig02`, `fig03`, `fig11`, `fig12`)

Từ [`results/member3_m3_6/per_instance_comparison.csv`](../results/member3_m3_6/per_instance_comparison.csv) và [`results/member3_m3_6/paper_comparison.csv`](../results/member3_m3_6/paper_comparison.csv):
- **Đồ thị chứng minh tối ưu (`OPTIMAL`) trên HB**: **2 / 54** (`bcspwr01=5`, `bcspwr02=7`, đều bởi `CP-SAT`).
- **Đồ thị khớp Published Best (toàn chiến dịch M3.6)**: **11 / 54** (`bcspwr01`, `bcsstk01`, `bcspwr02`, `ash85`, `nos4`, `bcsstk22`, `lund_a`, `lund_b`, `saylr1`, `nos7`, `jagmesh1`).
- **Đóng góp bổ trợ liên họ**:
  - `CP Optimizer` mạnh nhất trong nhóm nhỏ/trung bình (`ash85=9`, `nos4=10`, `bcsstk22=10`, `bcspwr03=14`).
  - `CP-SAT` là cầu nối chứng minh tối ưu và quy mô lớn hơn (`bcspwr01=5*`, `bcspwr02=7*`, `nos1=4`, `saylr1=14`).
  - `CaDiCaL (Order+Seq+Inc)` cân bằng rất tốt cho tới $n=238$ (khớp `bcspwr01=5`, `saylr1=14`, vượt `CP-SAT` trên `bcsstk01`: `21` vs `24`, nhưng bị chặn trước tại $n \ge 362$ mật độ cao).
  - `DRSA Warm` nhanh hơn hai bậc độ lớn (`0.8s`), là **phương pháp duy nhất chạy được cho mọi `n` đến `1,104`** và chạm `published_best` ở các đồ thị lớn có cấu trúc băng tự nhiên như `bcsstk01=16` (tại 5s Stage E), `lund_a=23`, `lund_b=23`, `saylr1=14`, `nos7=65`, `jagmesh1=27`.

### 6.2 Hiệu quả Warm-Start (`NO_WARM_START` vs `SHARED_RCM_WARM` vs `SHARED_DRSA_WARM`, tính cả thời gian tiền xử lý)

Phân tích trung thực chi phí toàn phần (`total_wall_time_s = preprocessing_time_s + encoding/model + solver`):
- **Tích cực rõ rệt khi solver không tìm được nghiệm ban đầu kịp**: trên **`nos1` ($n=237$)** ở Stage C (`15s`), `CP-SAT NO_WARM_START` bị **`TIMEOUT` không có nghiệm (`bandwidth = NaN`)**, trong khi cả `SHARED_RCM_WARM` (`+0.0035s` prep) lẫn `SHARED_DRSA_WARM` (`+0.502s` prep) đều giúp `CP-SAT` trả về nghiệm hợp lệ **`bw = 4`** (`LB=3`).
- **Tăng tốc chứng minh tối ưu**: trên `bcspwr02`, `CP-SAT + SHARED_RCM_WARM` rút tổng thời gian chứng minh `OPTIMAL` từ `6.004s` xuống **`4.917s` (`-18.1%`)**. Tuy nhiên trên `bcspwr01`, `SHARED_RCM_WARM` (`2.439s`) và `SHARED_DRSA_WARM` (`2.016s`, gồm `0.501s` tiền xử lý DRSA) hơi chậm hơn `NO_WARM_START` (`1.457s`) vì đồ thị quá nhỏ (`n=39`) nên overhead hint vượt lợi ích ban đầu.
- **Hiện tượng trung tính hoặc nhiễu hint ở CP-SAT**: trên `nos4` ($n=100$), `CP-SAT NO_WARM_START` tự tìm được **`13`**, trong khi `SHARED_RCM_WARM` và `SHARED_DRSA_WARM` kẹt tại **`15`**; trên `saylr1` ($n=238$) ở `15s`, `CP-SAT SHARED_DRSA_WARM` thậm chí rơi vào `TIMEOUT` không trả về incumbent trước `15s` (nhưng khi mở rộng lên **`60s` ở Stage E**, lại giải về đúng `14`). Nguyên nhân kỹ thuật: `AddHint` trong CP-SAT chỉ là gợi ý tìm kiếm mềm (soft hint) không tự kẹp cận trên hay buộc chấp nhận tức thời nếu LNS/presolve chưa kiểm nghiệm xong trong 15s.

### 6.3 Tác động ngân sách mở rộng (`Stage E`: `60s` / `5s`, `12` lượt)

- **`DRSA Warm` (`5.0s`)**: tại `bcsstk01` ($n=48$), tăng thời gian từ `0.8s -> 5.0s` cải thiện từ **`18 -> 16`** (**khớp `paper_best = 16`**!). Trên `nos4=15, nos1=4, saylr1=14`, nghiệm giữ ổn định.
- **`CaDiCaL` (`60.0s` + `SHARED_DRSA_WARM`)**: giảm `bcsstk01` từ `22 -> 21` (sau `16.35s`, trước khi timeout ở bước $k=20$) và giảm **`nos4` từ `13 -> 12`** (`solver_time_s = 57.26s` khi tìm sát nghiệm công bố `10`), đồng thời giữ `nos1=4, saylr1=14`.
- **`CP-SAT` (`60.0s` + `SHARED_DRSA_WARM`)**: phục hồi từ `TIMEOUT` ở `15s` trên **`saylr1` về `bw = 14`** (khớp `paper_best = 14`), nhưng không cải thiện thêm dưới `24` trên `bcsstk01` và `15` trên `nos4`.

---

## 7. Độ nhạy Topology Duy Nhất (`54` vs `53`: `saylr3 == sherman1`)

Theo kiểm toán pháp y M3.5, `saylr3` và `sherman1` đều có $n=1000, m=1375$, cùng `topology_sha256 = a592bd5e...` và `graph_fingerprint = f7e349fc...`. Thực nghiệm M3.6 kiểm chứng trên chạy thật Stage B:
- Cả 4 phương pháp heuristic đều cho **kết quả giống hệt nhau từng đơn vị** trên `saylr3` và `sherman1`: `rcm=67`, `sa=67`, `drsa_paper_faithful=958`, `drsa_modified_variant=67`.
- Phân tích độ nhạy tổng hợp ([`results/member3_m3_6/unique_topology_analysis.csv`](../results/member3_m3_6/unique_topology_analysis.csv)):

| Phạm vi phân tích | Số đồ thị | Proved Optimal | Khớp Published Best | Mean Gap Overall | Median Gap Overall | Mean Gap Heuristic |
|---|---:|---:|---:|---:|---:|---:|
| `INSTANCE_WEIGHTED_54` | 54 | 2 | 11 | `20.3148` | `14.0` | `20.7407` |
| `TOPOLOGY_UNIQUE_53` | 53 | 2 | 11 | `20.3019` | `14.0` | `20.7358` |

Chênh lệch mean gap chỉ `-0.0129` (`~0.06%` tương đối), khẳng định các kết luận xếp hạng trong M3.6 hoàn toàn bền vững trước trùng lặp topology nhưng vẫn cần công bố song song cả 2 chế độ để bảo toàn tính trung thực thống kê.

---

## 8. Những hạn chế, thiên lệch & mối đe dọa tính hợp lệ (Threats to Validity)

1. **Giới hạn bản quyền thương mại không cân xứng**: `CPLEX CE` (`<= 1,000` vars) không chạy được bất kỳ đồ thị HB nào; `Gurobi Eval` (`<= 2,000` vars) chỉ chạy `1/54`; `CP Optimizer CE` ($2^{1000}$) dừng ở $n \le 138$ (`8/54`). Do đó bảng xếp hạng tổng 54 READY không thể kết luận hiệu năng công nghiệp của bản quyền thương mại đầy đủ (Full License) của MIP/CP Optimizer ngoài phạm vi giới hạn trên.
2. **Kiểm soát ngân sách & kiểm toán giao thức**: Ngưỡng timeout baseline (`15s` exact / `10s` SAT study / `0.8s` heuristic / `60s` extended) ưu tiên chứng minh định hướng và hoàn thành đủ 500 run trên laptop Apple M2 16GB; nhiều bài toán `n >= 85` đòi hỏi vài phút tới hàng giờ nếu muốn chứng minh UNSAT toàn cục. Ngoài ra, trên Stage D tại biên `10.0s`, khác biệt nhỏ về tải CPU nền có thể gây dao động `±1` bước `k` ở các trường hợp `TIMEOUT` cận biên (ví dụ `bcsstk01`: `bw=22..25`).
3. **Khác biệt bản chất giữa `Paper-Faithful DRSA` và ngân sách `0.8s`**: M3.6 chứng minh bản gốc $T_0=1000$ với khởi tạo ngẫu nhiên không hội tụ trong `0.8s`; việc đánh giá Paper-Faithful đầy đủ tới hết lịch $T_f = 10^{-7}$ đòi hỏi ngân sách phút/giờ không tương đương với tiêu chuẩn dưới 1 giây.

---

## 9. Hướng dẫn tái lập đầy đủ (Reproducibility Guide)

### 9.1 Bước 1 — Cài đặt môi trường & tải bộ Harwell–Boeing (nếu clone mới)

Các file ma trận thô `.mtx.gz` được `.gitignore` để giữ repository nhẹ:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[cp-sat,cp-optimizer,plots,datasets,dev]"

# Tải và xác thực checksum 54 Harwell-Boeing READY + catalog
python scripts/acquire_benchmark.py --verify-only || python scripts/acquire_benchmark.py
bmp preflight-benchmark --dir data/benchmarks/raw --table all
```

### 9.2 Bước 2 — Chạy thực nghiệm M3.6 theo cấu hình & hỗ trợ Checkpoint/Resume

```bash
# Chạy toàn bộ kế hoạch M3.6 (tự động lưu từng run & resume nếu bị ngắt)
python scripts/run_member3_m3_6.py --config configs/member3_m3_6.toml --plots

# Hoặc chạy từng batch theo thời lượng tối đa (ví dụ 850s/batch) rồi resume:
python scripts/run_member3_m3_6.py --config configs/member3_m3_6.toml --max-batch-seconds 850
python scripts/run_member3_m3_6.py --config configs/member3_m3_6.toml --plots
```

### 9.3 Bước 3 — Kiểm thử hồi quy & kiểm chứng đóng gói độc lập

```bash
pytest -vv tests/test_member3_unified_m3_6.py
pytest -vv -rs tests/
```

---

## 10. Danh mục biểu đồ & tệp kết quả đã tạo

Tất cả dữ liệu đo đạc nằm trong [`results/member3_m3_6/`](../results/member3_m3_6/):
- `metadata.json`, `preflight_54.csv` (`540` dòng), `runs.csv` (`500` dòng), `runs.json`
- `summary.json`, `per_method_summary.csv`, `per_instance_comparison.csv`, `paper_comparison.csv`, `unique_topology_analysis.csv`, `paired_comparisons.csv`, `comparison.md`, `run_log.txt`
- 12 biểu đồ SVG xuất bằng `cnsplots` & `matplotlib` trong [`results/member3_m3_6/figures/`](../results/member3_m3_6/figures/):
  1. `fig01_cross_family_quality.svg` — Tỷ lệ Bandwidth / Published Best xuyên suốt 4 họ trên Stage C
  2. `fig02_method_status_rates.svg` — Phân bố trạng thái (`OPTIMAL`, `FEASIBLE`, `TIMEOUT`, `RESOURCE_LIMIT`, `UNAVAILABLE`)
  3. `fig03_runtime_and_memory_vs_size.svg` — Mở rộng thời gian chạy (log scale) & Peak RSS theo bậc đồ thị $n$
  4. `fig04_preflight_eligibility_54.svg` — Phân bố hợp lệ & rào cản trên 54 đồ thị READY cho 10 phương pháp
  5. `fig05_sat_backends_comparison.svg` — Study SAT-A: CaDiCaL vs Glucose vs MiniSat
  6. `fig06_sat_pairwise_vs_order.svg` — Study SAT-B: Pairwise vs Order Encoding (CNF clauses & Wall time)
  7. `fig07_sat_six_amo_variants.svg` — Study SAT-C: 6 biến thể Cardinality AMO (`Pairwise`, `Sequential`, `Binary`, `Commander`, `Product`, `Ladder`)
  8. `fig08_sat_repeated_vs_incremental.svg` — Study SAT-D: Repeated vs Incremental SAT
  9. `fig09_cp_sat_vs_cp_optimizer.svg` — Study CP: OR-Tools CP-SAT vs IBM CP Optimizer & Warm-start
  10. `fig10_heuristics_54_ready.svg` — Phân bố khoảng cách tới Published Best của Heuristics trên 54 READY
  11. `fig11_stage_c_matrix_heatmap.svg` — Ma trận Instance × Method kèm ký hiệu chứng minh `*`
  12. `fig12_quality_performance_profile.svg` — Biểu đồ hàm phân bố hiệu năng chất lượng (Performance Profile) trên Stage C
