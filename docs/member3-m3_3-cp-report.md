# Báo cáo Kỹ thuật & Thực nghiệm Phase M3.3 – OR-Tools CP-SAT & IBM ILOG CP Optimizer Validation

> **Phạm vi bằng chứng:** Mọi số liệu trong báo cáo được đo trực tiếp trên cùng máy Apple Silicon (`macOS-14.0-arm64`, Python `3.14.3`) sau khi đồng bộ toàn bộ mã nguồn và preflight provenance (`54/113 READY`). Không suy diễn thứ hạng toàn cục cho tập 113 ma trận Harwell–Boeing từ 6 instance pilot và không dùng đồ thị `NEEDS_VERIFICATION`/`INVALID_DATA`.

---

## 1. Kiến trúc Mô hình Toán học Constraint Programming cho BMP

Với đồ thị vô hướng đơn $G = (V, E)$ ($n = |V|$, $m = |E|$), bài toán Bandwidth Minimization (BMP) tìm song ánh $p : V \to \{1, \dots, n\}$ cực tiểu hóa:
$$B(p) = \max_{(u, v) \in E} |p_u - p_v|.$$

### 1.1. Hai triển khai thống nhất trên [`CPSATSolver`](../src/bmp/solvers/exact/cpsat.py) và [`CPOptimizerSolver`](../src/bmp/solvers/exact/cp_optimizer.py)

Cả hai bộ giải cùng dùng chung lớp tiền xử lý cận & khởi tạo [`prepare_cp_hints`](../src/bmp/solvers/exact/_common.py) và bộ kiểm định độc lập `validate_solution`:

| Thành phần | OR-Tools CP-SAT (`9.15.6755`) | IBM CP Optimizer (`docplex 2.32.264`, engine `22.2.0.0`) |
|---|---|---|
| Biến vị trí | $p_v \in \{1, \dots, n\}$ (`new_int_var`) | $p_v \in \{1, \dots, n\}$ (`integer_var`) |
| Biến mục tiêu | $B \in [\text{model\_lb}, \text{model\_ub}]$ | $B \in [\text{model\_lb}, \text{model\_ub}]$ |
| Ràng buộc song ánh | `model.add_all_different(positions.values())` | `model.add(alldiff(pos_vars))` |
| Ràng buộc băng thông | Tuyến tính hóa: $p_u - p_v \le B$ và $p_v - p_u \le B$ ($\forall (u,v)\in E$) | Phi tuyến CP: `abs(p_u - p_v) <= B` ($\forall (u,v)\in E$) |
| Phá đối xứng phản chiếu | $p_{\text{anchor}} \le \lceil n/2 \rceil$ (khi `symmetry_breaking=True`, $n \ge 2$) | $p_{\text{anchor}} \le \lceil n/2 \rceil$ (khi `symmetry_breaking=True`, $n \ge 2$) |
| Khởi tạo nghiệm ban đầu | `model.add_hint(...)` (từ `RCM` hoặc `initial_permutation`) | `create_empty_solution()` + `set_starting_point(...)` |
| Kích thước mô hình | $n + 1$ biến; $2m + 1 + \mathbb{I}[\text{sym}]$ ràng buộc | $n + 1$ biến; $m + 1 + \mathbb{I}[\text{sym}]$ ràng buộc |

- **Chuẩn hóa đối xứng cho warm-start (`normalize_for_symmetry`):** Trước khi đưa nghiệm khởi tạo vào CP-SAT (`add_hint`) hoặc CP Optimizer (`set_starting_point`), nếu `symmetry_breaking=True` và $p(\text{anchor}) > \lceil n / 2 \rceil$, hoán vị được đảo chiều $p'(v) = n + 1 - p(v)$ để giữ nguyên băng thông nhưng **đảm bảo tương thích 100% với ràng buộc phá đối xứng**.
- **Tính chính xác chặn dưới (`best_bound`) & trạng thái:**
  - `certified_graph_lower_bound` dùng `compute_lower_bound(graph)` ($\max_v \lceil \deg(v)/2 \rceil$ và chặn clique/bậc địa phương theo L8).
  - Trong CP-SAT, `solver.best_objective_bound` (kiểu `float`) được làm tròn nguyên bảo thủ bằng `floor(best_bound + 1e-7)`.
  - Trong IBM CP Optimizer, khi trạng thái native là `Feasible` (dừng vì `TimeLimit` với `SearchStoppedByLimit`), hệ thống **không bao giờ nâng cấp giả tạo thành `OPTIMAL`**, đồng thời báo cáo cả `best_bound` ($\max(\text{model\_lb}, \text{native\_bound})$) lẫn `native_best_bound` tách biệt trong metadata.
  - Khi gặp giới hạn tìm kiếm $2^{1000}$ của phiên bản IBM CP Optimizer Community Edition (`error1016`), [`CPOptimizerSolver`](../src/bmp/solvers/exact/cp_optimizer.py) phân loại thành `SolutionStatus.UNAVAILABLE` (nhất quán với `Gurobi`/`CPLEX` trong M2.3), không gán nhãn sai thành `INFEASIBLE`.

---

## 2. Kiểm định Tài nguyên & Preflight trên 113 Harwell–Boeing

Tệp cấu hình [`configs/member3_m3_3.toml`](../configs/member3_m3_3.toml) kiểm tra provenance `data/benchmark_provenance.json` (`total=113`, `ready=54`, `needs_verification=58`, `invalid_data=1`). Toàn bộ `54` đồ thị `READY` được preflight kiểm chứng SHA-256 (`results/member3_m3_3/preflight.csv`):

- **`19/54` instance ở nhóm `PILOT_READY`** ($n \le 250$, nằm dưới ngưỡng kiểm soát `max_cp_vars=2000`, `max_cp_constraints=25000`).
- **`35/54` instance ở nhóm `HEAVY_FOR_20S`** ($n \in [274, 1104]$, đòi hỏi thời gian giải dài hơn pilot `20s`).
- **Tập pilot 6 đồ thị đã xác minh `READY`** (`Table 6` và `Table 7`): `bcspwr01` ($39, 46$), `bcsstk01` ($48, 176$), `bcspwr02` ($49, 59$), `ash85` ($85, 219$), `nos4` ($100, 247$), và `dwt_209` ($209, 767$).
- **Độ gọn mô hình CP so với SAT CNF:** Trên `ash85` ($n=85, m=219$), SAT `OrderEncoding + Sequential` cần `21,505` biến và `82,746` mệnh đề (hoặc `1,855,327` mệnh đề với `Pairwise`), trong khi CP-SAT chỉ dùng **`86` biến và `440` ràng buộc**, và IBM CP Optimizer chỉ dùng **`86` biến và `221` ràng buộc**.

---

## 3. Phân tích Kết quả Thực nghiệm Pilot (`results/member3_m3_3/`, 36 lượt chạy)

Toàn bộ `36` lượt chạy (`21` OR-Tools CP-SAT + `15` IBM CP Optimizer; `threads=1`, `seed=17`, `timeout=20.0s`) ghi đầy đủ vào [`runs.json`](../results/member3_m3_3/runs.json) và [`runs.csv`](../results/member3_m3_3/runs.csv). **100% (`29/29`) nghiệm trả về vượt qua kiểm định `validate_solution == True`** (`0 ERROR`).

- **Tổng hợp trạng thái kết thúc:**
  - `cp-sat` (`21` lượt): **`8 OPTIMAL`**, **`8 FEASIBLE`**, **`5 TIMEOUT`**.
  - `cp-optimizer` (`15` lượt): **`13 FEASIBLE`**, **`2 UNAVAILABLE`** (`dwt_209` vượt giới hạn không gian tìm kiếm $2^{1000}$ của IBM CE `error1016`).

### 3.1. Experiment C – Đối chiếu trực tiếp CP-SAT vs IBM CP Optimizer (`sym=True`, `hint=rcm`, `lb=True`, `ub=True`, `20s`)

| Instance | $n$ | $m$ | Pub LB/Best | CP-SAT Status | CP-SAT BW (LB) | CP-SAT Time (s) | CPO Status | CPO BW (LB) | CPO Time (s) |
|---|---:|---:|:---:|---|---:|---:|---|---:|---:|
| `bcspwr01` | 39 | 46 | `5 / 5` | **OPTIMAL** | **5 (5)** | 13.547 | FEASIBLE | **5 (4)** | 21.758 |
| `bcspwr02` | 49 | 59 | `7 / 7` | **OPTIMAL** | **7 (7)** | 13.948 | FEASIBLE | **7 (6)** | 20.330 |
| `bcsstk01` | 48 | 176 | `16 / 16` | FEASIBLE | 24 (12) | 20.224 | **FEASIBLE** | **18 (12)** | 20.171 |
| `ash85` | 85 | 219 | `9 / 9` | TIMEOUT | None (7) | 15.855 | **FEASIBLE** | **10 (7)** | 28.779 |
| `nos4` | 100 | 247 | `10 / 10` | TIMEOUT | None (8) | 16.751 | **FEASIBLE** | **10 (8)** | 27.698 |
| `dwt_209` | 209 | 767 | `21 / 23` | TIMEOUT | None (18) | 21.421 | UNAVAILABLE | None (18) | 7.066 |

**Những phát hiện đối xứng rõ nét giữa hai công nghệ CP:**
1. **OR-Tools CP-SAT vượt trội về chứng minh tối ưu (`OPTIMAL`) trên đồ thị thưa vừa:** Nhờ kết hợp lazy clause generation (LCG) và tích lũy dual bound từ LP/SAT core, CP-SAT chứng minh được tối ưu tuyệt đối cho cả `bcspwr01` (`5=5`, `4.527s–13.547s`) và `bcspwr02` (`7=7`, `12.897s–16.635s`).
2. **IBM CP Optimizer vượt trội về tìm nghiệm khả thi chất lượng cao (`primal bound`) trên đồ thị mật độ cao / kích thước đến $n=100$:** Trong khi CP-SAT sa lầy ở root presolve/probing với `num_branches = 0` và `TIMEOUT` (không trả được hoán vị khả thi nào) trên `ash85`, `nos4`, `dwt_209`, IBM CP Optimizer tìm được nghiệm khả thi trong **`100%` (`13/13`) lượt chạy khả dụng** với `133k–436k` nhánh/lượt:
   - Trên `bcsstk01` ($m=176$ cạnh, dày gấp ~3 lần `bcspwr02`): CPO đạt **`bw=18`** (`sym=True`, `m33-026`) và **`bw=17`** (`sym=False`, `m33-027`) — chỉ cách `published_best=16` đúng `1` đơn vị, tốt hơn rõ rệt CP-SAT (`19–24`).
   - Trên `ash85`: CPO đạt **`bw=10`** (`published_best=9`), so với `TIMEOUT (None)` của CP-SAT.
   - Trên `nos4`: CPO chạm đúng **`bw=10 == published_best`** trên cả `sym=True` và `sym=False` (`m33-030/031`), dù dual bound vẫn dừng ở `8` (`FEASIBLE`, chưa chứng minh tối ưu).
3. **Quan sát về dual bound của CP Optimizer trên `bcspwr02` (`m33-035`):** Ở lượt chạy `ub=False, hint=none` (`m33-035`), CP Optimizer đạt `bw=7` và `best_bound=7` (`gap=0`), nhưng `solve_status` gốc của engine vẫn là `Feasible` (`SearchStoppedByLimit`) vì cận dưới nội bộ đạt `7` sát điểm dừng 20s trước khi hoàn thành bước kết luận tối ưu. Bộ bao giữ nguyên `FEASIBLE` và không nâng cấp trái phép.
4. **Giới hạn bản quyền IBM CP Optimizer Community Edition (`2^1000`, `error1016`):** Với mô hình hoán vị miền $D(p_v) = \{1, \dots, n\}$, không gian tìm kiếm $n^n \approx 2^{n\log_2 n}$ vượt $2^{1000}$ kể từ $n \ge 141$. Trên `dwt_209` ($n=209 \Rightarrow 209^{209} \approx 2^{1611}$), engine báo `Problem size limit exceeded ... error1016` và trả trạng thái `UNAVAILABLE` ngay lập tức (`0.457s–7.066s`). (Ở bước kiểm tra phụ trước đó trên `bcsstk04`, $n=132 \Rightarrow 132^{132} \approx 2^{930} < 2^{1000}$ vẫn chạy hợp lệ.)

### 3.2. Tác động của Symmetry Breaking và Bound/Hint Ablation (Experiments A & B)

- **Ảnh hưởng của `symmetry_breaking` có tính phụ thuộc cấu trúc đồ thị:**
  - *Tích cực cho dual proof:* Trên `bcspwr02` (CP-SAT), `sym=True` đạt **`OPTIMAL` (`13.948s`)**, trong khi `sym=False` chỉ dừng ở **`FEASIBLE` (`20.284s`, `bb=6`)**.
  - *Có thể cản trở primal heuristic / LNS trên đồ thị khó:* Trên `bcsstk01`, tắt phá đối xứng (`sym=False`) giúp **cả CP-SAT (`23` vs `24`) lẫn CP Optimizer (`17` vs `18`)** tìm được primal tốt hơn; trên `nos4`, CP-SAT `sym=False` thoát khỏi bế tắc root (`3,120` nhánh, đạt `bw=13`) trong khi `sym=True` dừng tại `TIMEOUT (0 nhánh)`. Tương tự trên CP Optimizer cho `ash85` và `nos4`, `sym=False` bám sát budget `20.28s–20.64s` trong khi `sym=True` bị trễ init/cutoff lên `27.70s–28.78s`.
- **Ảnh hưởng của `use_lower_bound` và `hint`:**
  - Khi tắt `use_lower_bound=False` trên `bcsstk01` (`m33-020`), dual bound của CP-SAT giữ ở **`0`** suốt `20s`, chứng minh việc bơm `certified_graph_lower_bound` (`12`) là cần thiết để thu hẹp khoảng `gap` (`23` xuống `11–12`).
  - Khi tắt hoàn toàn `ub=False, hint=none` (`m33-016`) trên `bcspwr02`, CP-SAT mất khả năng chứng minh tối ưu (`FEASIBLE bw=9, lb=6` dù sinh `138,504` nhánh), ngược lại với `hint=rcm` hoặc `hint=identity` CP-SAT đều chốt **`OPTIMAL bw=7`** (`12.90s–16.64s`). Ở chiều ngược lại, trên `bcsstk01` (`m33-019`), `ub=False, hint=none` tình cờ vượt tràn thời gian mềm của OR-Tools tới `34.67s` và tìm được `bw=19` (tốt hơn `24` của cấu hình mặc định trong `20s`).

### 3.3. Experiment D – Đối chiếu với SAT & MIP (Leader / M2.3 / M3.2)

> **Lưu ý kiểm soát thực nghiệm:** Các số liệu SAT và MIP bên dưới được đọc trực tiếp từ kết quả lịch sử cùng máy của M2.3 (ngân sách `30s`) và M3.2 (ngân sách `10s`), không phải chạy lại đồng loạt ở mức `20s`; bảng đối chiếu chỉ nhằm phân tích đặc tính công nghệ.

| Instance | SAT tốt nhất (M2.3 `30s` / M3.2 `10s`) | MIP (`Gurobi`/`CPLEX` M2.3 `30s`) | CP-SAT M3.3 (`20s`) | CP Optimizer M3.3 (`20s`) |
|---|---|---|---|---|
| `bcspwr01` | `TIMEOUT` `bw=5 (lb=4)` (CaDiCaL/Glucose/MiniSat) | `Gurobi OPTIMAL` `bw=5 (13.26s)`; CPLEX `UNAVAIL` | **`OPTIMAL` `bw=5` (`4.53–13.55s`)** | `FEASIBLE` `bw=5 (4)` |
| `bcspwr02` | `TIMEOUT` `bw=8 (lb=6)` (CaDiCaL/Glucose/MiniSat) | Gurobi & CPLEX `UNAVAIL` (license cap) | **`OPTIMAL` `bw=7` (`12.90–16.64s`)** | `FEASIBLE` `bw=7 (6)` |
| `bcsstk01` | `TIMEOUT` `bw=20` (`CaDiCaL 30s`), `21` (`MiniSat 10s`) | Gurobi & CPLEX `UNAVAIL` | `FEASIBLE` `bw=19–24` | **`FEASIBLE` `bw=17–18`** |
| `ash85` | `TIMEOUT` `bw=10 (lb=7)` | Gurobi & CPLEX `UNAVAIL` | `TIMEOUT` (`None`, `lb=7`) | `FEASIBLE` **`bw=10 (lb=7)`** |
| `nos4` | `TIMEOUT` `bw=12 (lb=8)` (`CaDiCaL 30s`) | (Không có/TIMEOUT) | `TIMEOUT (None)` / `13` (`sym=F`) | **`FEASIBLE` `bw=10 (lb=8)`** |
| `dwt_209` | `TIMEOUT` `bw=42 (lb=18)` (`CaDiCaL 30s`) | (Không có) | `TIMEOUT` (`None`, `lb=18`) | `UNAVAILABLE` (CE $2^{1000}$) |

**Kết luận kiến trúc tổng hợp giữa 3 mô hình (SAT vs MIP vs CP):**
1. **MIP (`Gurobi`/`CPLEX`):** Rất hiệu quả khi giải được (`bcspwr01`), nhưng bùng nổ số biến nhị phân/ràng buộc tuyến tính $O(n^2)$ khiến phiên bản academic/CE bị chặn `UNAVAILABLE` ngay ở `n=48–49` (`bcsstk01`, `bcspwr02`).
2. **SAT (`CaDiCaL`/`Glucose`/`MiniSat`):** Tạo mã hóa CNF tới hàng chục nghìn–hàng triệu mệnh đề; tìm primal từ warm-start/incremental tốt khi không bị timeout CNF trên $n \le 85$, nhưng rất khó chứng minh UNSAT tại $k = B^* - 1$ ngay cả trên `bcspwr01`.
3. **CP (`OR-Tools CP-SAT` & `IBM CP Optimizer`):** Biểu diễn trực tiếp hoán vị bằng $n+1$ biến và ràng buộc toàn cục `AllDifferent`, vừa giữ kích thước mô hình gọn, vừa **lần đầu chứng minh `OPTIMAL` trên `bcspwr02` (`n=49`) mà MIP CE và SAT chưa đạt được**. Đồng thời CP-SAT và CP Optimizer bổ trợ rõ rệt nhau: CP-SAT mạnh về dual proof (`OPTIMAL`), còn CP Optimizer mạnh về LNS primal search trên đồ thị đến $n=100$ khi không bị giới hạn bản quyền $2^{1000}$.

Các biểu đồ đối chứng đã xuất tại [`fig1_cp_bandwidth_comparison.svg`](../results/member3_m3_3/figures/fig1_cp_bandwidth_comparison.svg) và [`fig2_cp_runtime_symmetry.svg`](../results/member3_m3_3/figures/fig2_cp_runtime_symmetry.svg).

---

## 4. Đe dọa tới Tính hợp lệ (Threats to Validity)

1. **Khác biệt ngân sách & phép đo bộ nhớ (Construct Validity):** Thí nghiệm D tham chiếu dữ liệu SAT M2.3 (`30s`) và M3.2 (`10s`) thay vì chạy lại đồng loạt ở `20s`; ngoài ra `peak_memory_mb` của CP-SAT đo RSS tiến trình Python+C++ (`107.8–170.2 MiB`), trong khi IBM CP Optimizer báo cáo `PeakMemoryUsage` riêng của engine C++ bên ngoài (`1.37–2.50 MiB`, ngoại trừ khi lỗi khởi chạy `dwt_209` đo RSS tiến trình `94.6 MiB`). Do đó không so sánh trực tiếp MB thô giữa CP-SAT và CPO mà chỉ nêu đúng ranh giới đo.
2. **Tính mềm của timeout C++ và đa luồng (Internal Validity):** Khi chạy đơn luồng (`threads=1`, `isolate_timeout=False` trong batch), `max_time_in_seconds = 20.0` của OR-Tools CP-SAT dừng kiểm tra theo chu kỳ presolve nội bộ (dừng sớm ở `12.90s–18.59s` hoặc vượt lên `34.67s` ở `m33-019`); còn `cpoptimizer` tốn thêm chi phí khởi tạo subprocess (`engine_init_time_s` đạt `8.18s` trên `m33-028`). Cơ chế watchdog cô lập tiến trình (`isolate_timeout=True`) đã được kiểm chứng bằng unit test riêng khi cần giới hạn thời gian cứng. Các lượt chạy dùng một seed (`seed=17`) và đơn luồng nên chưa đánh giá được lợi thế portfolio song song (`threads >= 4`).
3. **Giới hạn khái quát hóa (External Validity):** Tập pilot mới bao phủ `6/54` đồ thị `READY` ($n \in [39, 209]$) và IBM CP Optimizer Community Edition bị giới hạn bản quyền trên $n \ge 141$. Cần kết hợp với **DRSA (Phase M3.4)** để xử lý các instance quy mô lớn $n \ge 200$ và mở rộng đánh giá toàn diện tập `54 READY` trong M3.6–M3.7.
