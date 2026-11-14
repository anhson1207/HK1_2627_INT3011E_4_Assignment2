# Báo cáo Kỹ thuật & Thực nghiệm Phase M3.4 – Dual Representation Simulated Annealing (DRSA), SA & RCM

> **Tham chiếu gốc:** J. Torres-Jimenez, I. Izquierdo-Marquez, A. Garcia-Robledo, A. Gonzalez-Gomez, J. Bernal, R. N. Kacker (2015), *"A dual representation simulated annealing algorithm for the bandwidth minimization problem on graphs"*, Information Sciences **303**, 33–49.

---

## 1. Kiểm toán (Audit) RCM, SA Hiện tại & Khung Thiết kế M3.4

### 1.1. Kết quả Audit `RCMSolver` và `SimulatedAnnealingSolver` trước M3.4
- **`RCMSolver` ([`rcm.py`](../src/bmp/heuristics/rcm.py)):** Tái sử dụng trực tiếp [`cuthill_mckee_order`](../src/bmp/core/bounds.py) — sinh hoán vị hợp lệ $100\%$, xử lý đúng đồ thị không liên thông và đỉnh cô lập, giữ nguyên ID đỉnh không liên tiếp. Giữ nguyên thuật toán gốc và chỉ bổ sung tham số `timeout_seconds` tương thích giao diện chung.
- **`SimulatedAnnealingSolver` ([`sa.py`](../src/bmp/heuristics/sa.py)) trước M3.4:**
  - *Điểm đạt:* Đã dùng seed xác định và tách biến `incumbent` khỏi `assignment` hiện tại.
  - *Điểm yếu phát hiện:* (1) tính lại băng thông từ đầu trên toàn bộ $m$ cạnh $O(m)$ sau mọi bước hoán đổi; (2) đánh giá chỉ dùng số nguyên `b` nên kẹt trên cao nguyên (`delta == 0`); (3) chưa hỗ trợ `timeout_seconds`, `initial_permutation`, `initial_mode`, hoặc `progress_trace`.
- **Phân loại các biến thể triển khai trong M3.4:**
  - **`PAPER_FAITHFUL`:** [`DRSASolver`](../src/bmp/heuristics/drsa.py) cấu hình mặc định đúng theo Algorithm 1, Algorithm 2, Section 3.2–3.4 và Algorithm 4 ($T_0 = 1000$, $\alpha = 0.99$, $T_f = 10^{-7}$, $L_0 = 40$, $L_f = 10nm$, xác suất `0.6/0.2/0.2`, `ROT max_sep=5`, khởi tạo `random`, hàm đánh giá $f = b + \delta$). Khi chạy dưới giới hạn wall-time / move-cap, cờ `bounded_execution = True` và `stop_reason` được ghi rõ, **không** tuyên bố đã chạy trọn lịch làm lạnh gốc.
  - **`ENGINEERING_OPTIMIZATION`:** Lớp [`IncrementalBandwidthState`](../src/bmp/heuristics/initial.py) duy trì mảng độ dài cạnh, histogram khoảng cách, bộ tem chống đếm trùng cạnh khi xoay `ROT` và rollback không sao chép mảng; tối ưu [`compute_component_diameters`](../src/bmp/solvers/sat/search.py) bằng frontier BFS + memoization (giảm thời gian preflight `54 READY` từ ~`214s` xuống `75.52s`, cache xuống `3.6ms`). Kiểm thử đối chứng xác nhận kết quả giống tuyệt đối từng bit với tính lại toàn bộ.
  - **`MODIFIED_VARIANT`:** Các biến thể điều chỉnh chính sách khởi tạo/làm lạnh/đánh giá cho ngân sách Python ngắn (`drsa_modified_warm`: khởi tạo `RCM`, $T_0 = 2.0$, giữ nguyên dual `p/q`, `0.6/0.2/0.2` và $f = b + \delta$; các biến thể ablation `REX-only`, `NEX-only`, `ROT-only`, `bandwidth_only`). Hàm kiểm tra tự động trong [`DRSASolver`](../src/bmp/heuristics/drsa.py) chặn việc gắn nhãn `PAPER_FAITHFUL` nếu bất kỳ siêu tham số nào sai khác paper gốc.
  - **`BASELINE`:** `RCMSolver` và `SimulatedAnnealingSolver` (hoán đổi đỉnh ngẫu nhiên một biểu diễn + làm lạnh hình học cố định mỗi bước).

---

## 2. Cấu trúc Toán học & Kỹ thuật của DRSA

### 2.1. Hai Biểu diễn Nghịch đảo (`DualRepresentation`)
Với đồ thị $G=(V, E)$ có tập đỉnh $V$ (cho phép ID đỉnh không liên tiếp hoặc âm), lớp [`DualRepresentation`](../src/bmp/heuristics/initial.py) ánh xạ $V$ vào mảng chỉ số nội bộ `0..n-1` và duy trì đồng bộ hai biểu diễn nghịch đảo:
- **`p_slots[s]`** ($\pi_v$, 1-based trong `p_map()`): nhãn gán cho đỉnh tại khe `s`.
- **`q_slots[ell]`** ($\rho_\ell$, 1-based trong `q_map()`): đỉnh mang nhãn $\ell + 1$.
- **Bất biến bắt buộc:** $\pi[\rho[\ell]] = \ell$ và $\rho[\pi[v]] = v$ sau mọi thao tác và rollback. Đã đối chiếu khớp chính xác từng phần tử với Hình 1 (`REX` đỉnh 2 và 4) và Hình 3 (`ROT` vị trí $i=2, j=6$) trong paper gốc.

### 2.2. Ba Toán tử Nhiễu & Phép chọn Xác suất (Algorithm 2)
1. **REX (`0.6`, trên `p`):** Chọn ngẫu nhiên hai đỉnh phân biệt $u \ne v$, hoán đổi $\pi_u \leftrightarrow \pi_v$ và cập nhật $\rho_{\pi_u} \leftrightarrow \rho_{\pi_v}$ trong $O(1)$.
2. **NEX (`0.2`, trên `p`):** Chọn một đỉnh có bậc $\ge 1$ (`non_isolated_slots`) và một láng giềng kề thực sự $v \in N(u)$ trên `GraphInstance`, hoán đổi $\pi_u \leftrightarrow \pi_v$. Đồ thị không cạnh được xử lý tường minh (dừng sớm hợp lệ hoặc ghi `operator_noop_counts["NEX"]`).
3. **ROT (`0.2`, trên `q`):** Chọn $r \sim U\{1, \dots, \min(5, n-1)\}$, $i \sim U\{1, \dots, n-r\}$, $j = i + r$, dời $\rho_i$ tới $\rho_j$ và dịch $\rho_{i+1 \dots j}$ sang trái 1 vị trí (không phải phép đảo đoạn!). Cạnh bên trong đoạn xoay được khử trùng lặp qua mảng `_edge_stamp` để không bị đếm hai lần khi tính gia số histogram.

### 2.3. Hàm Đánh giá $f = \beta + \delta$ (Section 3.4 & Algorithm 4) & Phát hiện Số học IEEE-754
Theo **Algorithm 4** (cắt tại $i = \beta$ nhằm tránh hiện tượng tràn dưới $0$ từ các hiệu $d_{\beta+1 \dots n-1} = 0$):
$$\delta = \left(\dots\left(\frac{d_0}{n+1}\right) + d_1\right) \Big/ n \dots + d_\beta\Big/ (n - \beta + 1), \qquad f = \beta + \delta.$$
Nhờ cấu trúc phân số liên tiếp lồng nhau này, hạng tử chi phối lớn nhất là $d_\beta / (n - \beta + 1)$ (số cạnh đúng tại ranh giới băng thông $\beta$), kế tiếp là $d_{\beta-1}, \dots, d_1$, giúp phá bẫy cao nguyên đồng băng thông mà không cần tính giai thừa $(n+1)!$.
- **Phát hiện ổn định số học:** Trên đồ thị đầy đủ $K_{30}$ ($\beta = 29$), dù $0 \le \delta < 1$ chặt trong số thực 53-bit quanh $1.0$, phép cộng `float(29) + delta` trong float64 chỉ còn 48 bit phần lẻ nên từng tự làm tròn thành `30.0`. Do đó `DRSASolver` sử dụng so sánh cặp `(bw, delta)` chính xác cùng phép trừ hiệu `float(cand_bw - cur_bw) + (cand_delta - cur_delta)` cho tiêu chuẩn Metropolis, đồng thời chặn chuẩn hóa scalar `f_value < float(bw + 1)` ở mức `math.nextafter`.

### 2.4. Lịch làm lạnh Algorithm 1
Tính $r = (\ln T_f - \ln T_0)/\ln \alpha \approx 2291.04$ và hệ số tăng chiều dài xích Markov $\gamma = \exp((\ln L_f - \ln L_0)/r)$. Trong mỗi giai đoạn: chạy xích độ dài `round(L)`, đặt `improvement = True` nếu gặp nghiệm cải thiện global best `(cand_bw, cand_delta) < (best_bw, best_delta)`. Chỉ khi kết thúc cả xích mà **`improvement == False`**, thuật toán mới làm lạnh $T \leftarrow \alpha T$ và tăng chiều dài xích $L \leftarrow \gamma L$.

---

## 3. Kiểm chứng Provenance & Kết quả Thực nghiệm (`results/member3_m3_4/`, 395 lượt chạy)

Toàn bộ `113` đồ thị trong `benchmark_provenance.json` được kiểm tra: **`54 READY`**, `58 NEEDS_VERIFICATION` (`steam3`), `1 INVALID_DATA` (`mbeause`). Chỉ `54` đồ thị `READY` được nạp qua preflight SHA-256 ([`preflight.csv`](../results/member3_m3_4/preflight.csv)); **100% (`395/395`) lượt chạy vượt qua kiểm định `validate_solution == True`**.

### 3.1. Stage B Pilot: `8` đồ thị `READY` $\times$ `3` seeds `{17, 23, 42}`, ngân sách `4.0s`

| Đồ thị (Bảng, $n, m$) | Pub Best | RCM | SA (RCM, 4s) | SA (Rand, 4s) | DRSA Paper (Rand, 4s) | DRSA (`RCM, T0=1000`, 4s) | DRSA Warm (`RCM, T0=2`, 4s) |
|---|---:|---:|---:|---:|---:|---:|---:|
| `bcspwr01` (T6, 39, 46) | 5 | 8 | 6.67 (6–7) | 7.67 (6–10) | 22.67 (21–26) | 8.00 (8–8) | **6.33 (5–8)** |
| `bcsstk01` (T6, 48, 176) | 16 | 27 | 20.33 (19–22) | 20.00 (18–22) | 37.33 (37–38) | 27.00 (27–27) | **19.00 (17–22)** |
| `bcspwr02` (T6, 49, 59) | 7 | 13 | 10.67 (10–11) | 9.00 (9–9) | 29.00 (28–30) | 13.00 (13–13) | **9.00 (9–9)** |
| `ash85` (T6, 85, 219) | 9 | 10 | 10.00 | 20.67 (18–22) | 68.33 (68–69) | 10.00 | 10.00 |
| `nos4` (T6, 100, 247) | 10 | 15 | 15.00 | 23.67 (23–25) | 82.67 (82–84) | 15.00 | 15.00 |
| `bcsstk22` (T6, 138, 279) | 10 | 14 | 14.00 | 31.67 (30–34) | 112.00 (110–113) | 14.00 | 14.00 |
| `dwt_209` (T7, 209, 767) | 23 | 42 | 42.00 | 85.67 (83–89) | 187.33 (187–188) | 42.00 | 42.00 |
| `saylr1` (T8, 238, 445) | 14 | 14 | 14.00 | 81.00 (74–87) | 209.67 (208–211) | 14.00 | 14.00 |
| **Trung bình 24 lượt** | **11.75** | **17.875** | **16.583** | **34.917** | **93.625** | **17.875** | **16.167** |

**Phân tích hiện tượng nhiệt độ & thông lượng trên thực nghiệm thật:**
1. **`DRSA Paper (random, T0=1000, alpha=0.99)` dưới giới hạn `4.0s` Python:** Trong 4s, thông lượng Python đạt trung bình `31,746` lượt đánh giá/lượt (~`500–700` bước làm lạnh), nên nhiệt độ $T = 1000 \times 0.99^k$ vẫn đang ở vùng nóng ($T > 1$) và mới giảm băng thông thô (`93.625`, giảm từ khởi tạo ngẫu nhiên trên cả `24/24` lượt). Ngược lại, bài báo gốc viết bằng C (`gcc -O3`) chạy hàng triệu–chục triệu bước trong vài giây để xuyên qua vùng $T \in [10^{-3}, 10^{-7}]$.
2. **Bằng chứng không nên ghép `T0=1000` trực tiếp với nghiệm khởi tạo tốt (`drsa_rcm_t1000`):** Khi khởi tạo từ `RCM` (`17.875`) mà vẫn giữ `T0=1000`, `exp(-Delta f / 1000) ~ 0.99` chấp nhận gần như mọi nước đi làm xấu nghiệm ngay đầu ván, nên `0/24` lượt vượt lại được nghiệm `RCM` ban đầu trong `4s` (`mean = 17.875`).
3. **Sức mạnh của `DRSA Warm (RCM, T0=2.0, eval=paper, 0.6/0.2/0.2)` vs `SA (RCM, T0=2.0)`:** Cùng khởi tạo `RCM` và cùng ngân sách `4.0s`, `DRSA Warm` đạt băng thông trung bình tốt nhất toàn Stage B (**`16.167`** vs `16.583` của SA), chạm **`Published Best = 5`** trên `bcspwr01` (nơi SA chỉ xuống `6`), hạ `bcsstk01` xuống trung bình **`19.00`** và tối thiểu **`17`** (sát `Published Best = 16`, ngang mức tốt nhất 20s của IBM CP Optimizer), và hạ `bcspwr02` xuống **`9.00`** ổn định qua cả 3 seeds.
4. **Vai trò đặc trưng của toán tử `ROT`:** Trong Stage B của `drsa_modified_warm`, tỷ lệ gọi toán tử khớp chính xác `0.601 / 0.200 / 0.199`, nhưng **`ROT` (chỉ chiếm 20% số lần gọi) tạo ra `22/41` (`53.7%`) tổng số bước giảm global bandwidth** (`REX: 12, NEX: 7, ROT: 22`)! Đây là xác nhận thực nghiệm trực tiếp giả thuyết của Section 3.3 rằng dịch chuyển mượt trên biểu diễn đối ngẫu `q` đóng vai trò khai thác cục bộ chủ lực khi đã có cấu trúc miền tốt.

### 3.2. Kết quả Ablation (`3s` $\times$ `3` seeds) & Tối ưu Gia số

- **Ablation hàm đánh giá (`bcsstk01`, `3s`, 3 seeds):** `f = b + delta` (`ablate_op_mixture_warm`) đạt mean **`19.67`** (`18–22`) với trung bình **`109.0` lần cập nhật `best_f`**; trong khi `bw-only` (`ablate_eval_bw_only`) dù đánh giá nhiều bước hơn (`36,949` vs `27,045` moves vì không tốn vòng lặp `delta`) chỉ tạo **`6.3` lần cập nhật** và tụt xuống mean **`20.67`** (`19–22`), khẳng định hiệu quả phá cao nguyên đồng băng thông của `delta`.
- **Ablation toán tử đơn lẻ (`bcsstk01`, `3s`, 3 seeds):** `REX-only` (`19.33`, `19–20`), `NEX-only` (`20.00`, `19–21`), `ROT-only` (`22.33`, `19–27`), hỗn hợp `0.6/0.2/0.2` đạt cực tiểu sâu nhất **`18`** (`mean 19.67`). Trên `ash85` (`rcm=10`) và `nos4` (`rcm=15`), tất cả cấu hình khởi tạo từ RCM tại $T_0=2$ với ngân sách 3s đều giữ nguyên băng thông đầu (`10` và `15`) vì rào cản thung lũng cục bộ đòi hỏi cửa sổ thời gian/làm lạnh sâu hơn.
- **Tăng tốc đánh giá gia số vs tính lại toàn bộ (`5,000` moves cố định, kết quả trùng 100%):**
  - `bcsstk01` ($n=48, m=176$): `0.467s` vs `1.568s` (**`3.36x`**, cùng đạt `bw=39`).
  - `ash85` ($n=85, m=219$): `0.549s` vs `1.929s` (**`3.52x`**, cùng đạt `bw=71`).
  - `dwt_209` ($n=209, m=767$): `0.945s` vs `7.185s` (**`7.60x`**, cùng đạt `bw=193`).

### 3.3. Stage C: Mở rộng có giới hạn toàn bộ `54` đồ thị `READY` (`1.5s/lượt`, `seed=17`)
- **Độ phủ batch:** Toàn bộ **`216/216`** lượt (`54` `RCM`, `54` `SA(rcm)`, `54` `DRSA Paper`, `54` `DRSA Warm`) hoàn tất **100% dưới ngưỡng `stage_c_max_batch_seconds = 360.0s`** (`0` lượt bị skip). Đỉnh bộ nhớ `peak_rss_mb <= 44.88 MiB`.
- `RCM` (`0.0395s`/đồ thị, tổng `2.14s` cho 54 đồ thị đến $n=1104$) khớp ngay `Published Best` trên **`5/54`** đồ thị (`lund_b`, `lund_a`, `saylr1`, `nos7`, `jagmesh1`).
- Trong giới hạn cực ngắn `1.5s`, `DRSA Warm` đạt mean thấp nhất (`49.3889` vs SA `49.4259` vs RCM `49.5556`) và vượt `RCM` trên `3` đồ thị (`bcsstk01: 27 -> 21`, `bcspwr02: 13 -> 11`, `bcspwr05: 83 -> 82`), trong khi `DRSA Paper (random)` cần thời gian dài hơn 1.5s để làm lạnh từ $T_0=1000$ trên các đồ thị $n \le 1104$ (`mean = 446.2778`).

### 3.4. Tích hợp Warm-start cho Exact Solvers (Task M3.4.9)
- Kiểm chứng tích hợp xuyên suốt `Repeated SAT`, `Incremental SAT`, `CP-SAT`, `CP Optimizer`, và contract chuẩn bị cận `Gurobi`/`CPLEX` (`prepare_mip_bounds(initial_permutation=...)`).
- Thử nghiệm thực tế tách biệt thời gian tiền xử lý DRSA (`1.502s`) khỏi exact solver trên Harwell–Boeing:
  - `bcspwr01`: DRSA warm cho nghiệm hợp lệ `bw = 6` (`1.502s`) -> `CPSATSolver` chứng minh **`OPTIMAL` `bw=5 (lb=5)` trong `9.857s`** (nhanh hơn `13.547s` của RCM warm-start ở M3.3); `IncrementalSATSolver` đạt `bw=5` trong `3.010s`.
  - `bcspwr02`: DRSA warm cho `bw = 11` -> `CPSATSolver` đạt `bw=7 (lb=6)` trong `10.015s`.

Các biểu đồ phân tích đã xuất từ dữ liệu thật tại [`figures/`](../results/member3_m3_4/figures/): `fig1_rcm_sa_drsa_bandwidth.svg`, `fig2_convergence_and_ablations.svg`, `fig3_stage_c_54_scaling.svg`, `fig4_operator_usage_and_time_to_best.svg`.

---

## 4. Hạn chế Khoa học & Hướng Tiếp theo (M3.5–M3.7)

1. **Khác biệt thông lượng Python vs C gốc (Construct/Internal Validity):** Vì bản cài đặt viết bằng Python thuần để bảo đảm tính di động không cần trình biên dịch C khi đóng gói wheel, số lượt đánh giá trên giây đạt `~5k–11k moves/s` (nhanh hơn `3.4x–7.6x` so với tính lại toàn bộ nhưng thấp hơn nhiều bậc so với C `-O3`). Vì thế, cấu hình `PAPER_FAITHFUL` ($T_0=1000, \alpha=0.99, L_f=10nm$) không kịp hoàn tất toàn bộ chuỗi giảm nhiệt tới $T_f=10^{-7}$ trong giới hạn `1.5s–4.0s`.
2. **Chiến lược khởi tạo theo ngân sách:** Thực nghiệm chứng minh `T0=1000` phá hỏng khởi tạo tốt (`RCM`), còn `T0=2.0 + RCM` tinh chỉnh hiệu quả `bcspwr01/bcspwr02/bcsstk01` nhưng dễ giữ nguyên cực trị địa phương ở đồ thị trung bình (`ash85`, `nos4`) nếu thiếu cơ chế làm nóng lại (`reheating`) hoặc thời gian lâu hơn.
3. **Thế hệ sau (M3.5–M3.7):** Kết hợp chạy thời gian dài có chọn lọc / đa luồng song song seed trên các đồ thị khó, và tổng hợp đối chiếu thống nhất **SAT (Leader/M2/M3.2) vs MIP (M2) vs CP (M3.3) vs RCM/SA/DRSA (M3.4)** trên toàn tập `54 READY` cùng phân tích thống kê Wilcoxon/Wilks chuẩn.
