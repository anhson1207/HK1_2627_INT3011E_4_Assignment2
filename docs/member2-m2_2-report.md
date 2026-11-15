# Member 2 – Phase M2.2: Live Solver Validation & Official Pilot Benchmark Report

## 1. Mục tiêu Phase M2.2 và Phạm vi Nhánh `dev/member-2`

Sau Phase M2.1 đồng bộ kiến trúc Leader L8 vào `dev/member-2` (commit gốc `ed0c90d`), **Phase M2.2** tập trung vào:
1. Kiểm toán môi trường thực tế và kích hoạt optional backends (`gurobipy`, `cplex`, `cnsplots`, `matplotlib`, `pandas`).
2. Xác thực trực tiếp (**live solver validation**) của **Gurobi** và **CPLEX** trên các đồ thị nhỏ có oracle `BruteForceSolver` và các instance Harwell–Boeing thực tế, đo lường chính xác ranh giới license thương mại.
3. Thực hiện preflight dữ liệu theo L8 provenance (`54 READY / 58 NEEDS_VERIFICATION / 1 INVALID_DATA`) và `estimate_cnf_size` + `ResourceLimits`.
4. Chạy **controlled pilot benchmark** có kiểm soát trên Ma trận thí nghiệm A–F với Schema 45 cột (tách biệt rành mạch `OPTIMAL`, `FEASIBLE`, `TIMEOUT`, `RESOURCE_LIMIT`, `SKIPPED`, `UNAVAILABLE`, `ERROR`, tuyệt đối không ghi `0` thay `None`/`N/A`).
5. Xuất báo cáo định lượng, đối chiếu Paper Best / Leader L8, sinh 8 biểu đồ `cnsplots` trong `results/member2_m2_2/figures/`, bảo toàn nguyên vẹn `results/member2/` và `results/leader/`.

---

## 2. Môi trường Thực thi & Phiên bản Thư viện / Solver

Thông số thu thập từ `results/member2_m2_2/metadata.json` và kiểm định runtime trong `.venv`:

| Thành phần | Giá trị quan sát | Ghi chú |
|---|---|---|
| Branch / Base commit | `dev/member-2` (từ `ed0c90d`) | Chỉ sửa `dev/member-2` |
| Hệ điều hành / Kiến trúc | `macOS-14.0-arm64-arm-64bit-Mach-O` (`arm64`, 8 CPU cores, 16.0 GiB RAM) | Multiprocessing hỗ trợ `spawn`, `fork`, `forkserver` |
| Python | `3.14.3` | Chạy trong `.venv` |
| `python-sat` | `1.9.dev17` | Cung cấp CaDiCaL & Glucose4 |
| CaDiCaL | `cadical195 (PySAT 1.9.dev17)` | **SOLVER_VERIFIED** |
| Glucose 4 | `glucose4 (PySAT 1.9.dev17)` | **SOLVER_VERIFIED** |
| Gurobi | `gurobipy 13.0.3` | **SOLVER_VERIFIED** trong giới hạn license đánh giá |
| CPLEX | `cplex 22.2.0.1` (`get_version() == 22.2.0.0`) | **SOLVER_VERIFIED** trong giới hạn Community Edition |
| Plotting stack | `cnsplots 0.8.0`, `matplotlib 3.11.2`, `pandas 3.1.1` | `mutool` không có -> `cnsplots` lưu standard matplotlib SVG |
| Test runner | `pytest 9.1.1` | Toàn bộ 93/93 tests passed |

---

## 3. Trạng thái Live Solver & Ranh giới License

Trong môi trường `.venv`, các optional dependencies được cài đặt qua `pip install -e ".[gurobi,cplex,plots]"`:

- **CaDiCaL (`cadical195`) & Glucose 4 (`glucose4`)**: `SOLVER_VERIFIED` — chạy ổn định qua chuẩn `SATBackend` và cơ chế worker timeout có `fork` trên macOS.
- **Gurobi (`13.0.3`)**: `SOLVER_VERIFIED` với embedded size-limited evaluation license từ PyPI (**tối đa 2,000 biến và 2,000 ràng buộc**).
  - Vì mô hình Assignment MIP sử dụng $n^2 + 1$ biến ($x_{v,p} \in \{0,1\}$ và $B$), Gurobi chạy thành công trên toàn bộ đồ thị nhỏ ($n \le 14$) và instance **Harwell–Boeing `bcspwr01`** ($n=39 \implies 1,522$ biến, $170$ ràng buộc).
  - Từ `bcsstk01` ($n=48 \implies 2,305$ biến), `bcspwr02` ($n=49 \implies 2,402$ biến) trở lên, Gurobi trả về `UNAVAILABLE` với thông báo `Model too large for size-limited license`.
- **CPLEX (`22.2.0.0`)**: `SOLVER_VERIFIED` với **IBM CPLEX Community Edition** (**tối đa 1,000 biến và 1,000 ràng buộc**, tương ứng $n \le 31$).
  - Chạy và chứng minh `OPTIMAL` trên toàn bộ đồ thị nhỏ ($n \le 14$).
  - Trên mọi instance Harwell–Boeing trong pilot ($n \ge 39$, tức $\ge 1,522$ biến), CPLEX trả về `UNAVAILABLE` với `CPLEX Error 1016: Community Edition. Problem size limits exceeded`.

---

## 4. Kiểm toán Dữ liệu 113-Instance & Table 6 Preflight

Đối chiếu `ALL_INSTANCES` (113 instance) với `data/benchmark_provenance.json` và `inspect_matrix_market`:

| Bảng nguồn | `READY` | `NEEDS_VERIFICATION` | `INVALID_DATA` | Tổng |
|---|---:|---:|---:|---:|
| Table 6 | 13 | 18 | 0 | 31 |
| Table 7 | 27 | 14 | 0 | 41 |
| Table 8 | 14 | 26 | 1 | 41 |
| **Tổng** | **54** | **58** | **1** | **113** |

- Tất cả **54/54** file `READY` đều hiện diện trong `data/benchmarks/raw/` (`0` thiếu file, `0` sai checksum SHA-256).
- `58 NEEDS_VERIFICATION` (general unsymmetric coordinate matrices) và `1 INVALID_DATA` (`mbeause`, 496 vs 492 vertex mismatch) tuyệt đối không đưa vào benchmark chính thức.

### Table 6 `READY` Resource Preflight (13 instances, `ResourceLimits(500_000 vars, 2_500_000 clauses)`)

| Instance | $n$ | $m$ | MIP Vars ($n^2+1$) | `order/seq` Vars | `order/seq` Clauses | `order/seq` Ok | `pairwise/seq` Vars | `pairwise/seq` Clauses | `pairwise/seq` Ok |
|---|---:|---:|---:|---:|---:| :---: |---:|---:| :---: |
| `bcspwr01` | 39 | 46 | 1,522 | 4,485 | 13,832 | `True` | 4,485 | 77,044 | `True` |
| `bcsstk01` | 48 | 176 | 2,305 | 6,816 | 32,289 | `True` | 6,816 | 410,568 | `True` |
| `bcspwr02` | 49 | 59 | 2,402 | 7,105 | 22,080 | `True` | 7,105 | 152,855 | `True` |
| `ash85` | 85 | 219 | 7,226 | 21,505 | 86,688 | `True` | 21,505 | 1,606,457 | `True` |
| `nos4` | 100 | 247 | 10,001 | 29,800 | 118,107 | `True` | 29,800 | 2,504,650 | `False` |
| `bcspwr03` | 118 | 179 | 13,925 | 41,536 | 138,411 | `True` | 41,536 | 2,554,051 | `False` |
| `bcsstk04` | 132 | 1,758 | 17,425 | 52,008 | 581,509 | `True` | 52,008 | 30,503,022 | `False` |
| `bcsstk22` | 138 | 279 | 19,045 | 56,856 | 208,651 | `True` | 56,856 | 5,388,141 | `False` |
| `can_144` | 144 | 576 | 20,737 | 61,920 | 308,737 | `True` | 61,920 | 11,984,472 | `False` |
| `lund_a` | 147 | 1,151 | 21,610 | 64,533 | 486,180 | `True` | 64,533 | 24,831,460 | `False` |
| `lund_b` | 147 | 1,147 | 21,610 | 64,533 | 485,012 | `True` | 64,533 | 24,745,612 | `False` |
| `bcsstk05` | 153 | 1,135 | 23,410 | 69,921 | 507,680 | `True` | 69,921 | 26,535,019 | `False` |
| `can_161` | 161 | 608 | 25,922 | 77,441 | 374,720 | `True` | 77,441 | 15,816,559 | `False` |

Nhờ công thức $O(n)$ mệnh đề cạnh của `OrderEncoding`, toàn bộ 13/13 instance `Table 6 READY` vượt qua ngưỡng `2,500,000` mệnh đề, trong khi `PairwiseEncoding` ($O(n^2)$ mệnh đề cạnh) vượt ngưỡng từ `nos4` ($n=100$) trở lên.

---

## 5. Cấu hình Pilot Benchmark & Quy tắc Bảo vệ

File cấu hình [`configs/member2_m2_2.toml`](../configs/member2_m2_2.toml) định nghĩa chế độ `pilot_m2_2`:
- **Bộ SmallOracle (`9` đồ thị kiểm chứng)**: 5 đồ thị mẫu (`path_p5`, `cycle_c4`, `star_k1_4`, `complete_k5`, `edgeless_5`) + 4 đồ thị ngẫu nhiên `Erdos–Rényi` ($n \in \{8, 10, 12, 14\}$). Với $n \le 10$ có kiểm chứng độc lập bằng `BruteForceSolver`.
- **Bộ HB Table 6 `READY` Pilot (`4` đại diện nhóm kích thước)**: `bcspwr01` ($n=39, m=46$), `bcsstk01` ($n=48, m=176$), `bcspwr02` ($n=49, m=59$), `nos4` ($n=100, m=247$).
- **Timeout & Resource Guards**: `timeout_seconds = 30.0`, `extended_timeout_seconds = 60.0` (trên `bcspwr02`, `bcsstk01` với `order/sequential/incremental`), `max_sat_variables = 500000`, `max_sat_clauses = 2500000`, `max_mip_variables = 250000`, `memory_limit_mb = 4096.0`, `max_batch_seconds = 900.0` (chạy 2 pha có kiểm chứng resume checkpoint: pha 1 hoàn tất 89/114 lượt trong `906.0s`, pha 2 `--resume` hoàn tất 25 lượt còn lại trong `363.934s`).
- **Tổng hợp trạng thái trên 114 lượt (`results/member2_m2_2/summary.json`)**:
  - `OPTIMAL`: **62** (`54` lượt `SmallOracle`, `7` lượt SAT trên `bcspwr01`, `1` lượt Gurobi `sym=True` trên `bcspwr01`)
  - `FEASIBLE`: **0**
  - `TIMEOUT`: **36** (tất cả đều kèm chứng chỉ hợp lệ hoặc incumbent không đổi; không coi là UNSAT)
  - `RESOURCE_LIMIT`: **2** (`nos4` `pairwise/sequential` trên CaDiCaL và Glucose, `2,504,650 > 2,500,000` clauses)
  - `UNAVAILABLE`: **14** (6 lượt Gurobi trên `bcspwr02`, `bcsstk01`, `nos4`; 8 lượt CPLEX trên cả 4 instance HB)
  - `SKIPPED`: **0** (trên bộ pilot toàn `READY` + `SYNTHETIC_SAMPLE`), `ERROR`: **0**.
  - Kiểm tra độc lập `validate_solution`: `98/98` nghiệm trả về đều hợp lệ (`validation=True`, `0` nghiệm sai, `16` lượt `RESOURCE_LIMIT`/`UNAVAILABLE` không có nghiệm mang giá trị `None`).

---

## 6. Kết quả Experiment A – CaDiCaL vs Glucose 4

So sánh trực tiếp với cấu hình `order + sequential + sym=True`:

### Bảng A.1: `bcspwr01` ($n=39, m=46$, Paper Best = `5`, `TIMEOUT=30s`)
| Backend | Strategy | Status | BW | Bound | Wall Time (s) | Solver Time (s) | Peak RSS (MB) |
|---|---|---|---:|---:|---:|---:|---:|
| `glucose` | `incremental` | `OPTIMAL` | 5 | 5 | 7.322 | 7.301 | 60.31 |
| `cadical` | `incremental` | `OPTIMAL` | 5 | 5 | 7.781 | 7.758 | 54.95 |
| `cadical` | `repeated` | `OPTIMAL` | 5 | 5 | 6.925 | 6.873 | 61.58 |
| `glucose` | `repeated` | `OPTIMAL` | 5 | 5 | 6.928 | 6.882 | 56.47 |

- Trên `bcspwr01`, cả hai backend đều chứng minh tối ưu **`bw = 5`** trong khoảng `6.9s–7.8s` (nhanh hơn giá trị tham chiếu `16.8s–22.7s` ghi nhận trong `l8_sat_runs.csv`, tuy nhiên không so sánh chéo hiệu năng tuyệt đối do khác bối cảnh/thời điểm chạy).
- Lưu ý: trên các bài toán timeout lớn hơn (`30s` và `60s`), `cadical` đạt **incumbent chất lượng tốt hơn rõ rệt** so với `glucose`:
  - `bcspwr02` (`order/sequential/incremental`): CaDiCaL đạt `bw = 7` (bằng Paper Best) tại `30s` và `60s`, Glucose chỉ dừng ở `bw = 8` (`m2_2_0060`, `m2_2_0111`).
  - `bcsstk01` (`order/sequential/incremental`): CaDiCaL đạt `bw = 17` tại `30s` (`10` `sat_calls`) và `60s` (khớp Leader L8 `120s`), trong khi Glucose dừng ở `bw = 21` (`6` `sat_calls`).
  - `nos4` (`order/sequential/incremental`, `30s`): CaDiCaL đạt `bw = 10` (bằng Paper Best, `3` `sat_calls`, `sol_t=20.64s`), trong khi Glucose kẹt ngay ở bước `sat_calls=0` sau khi khởi tạo heuristic `bw = 13` (hết timeout trong lệnh gọi SAT đầu tiên tại $k=12$).

---

## 7. Kết quả Experiment B – Cardinality Encodings (AMO)

Chạy `glucose + order + incremental + sym=True` (`timeout=30s`) với cả 4 bộ mã hóa AMO trên 4 instance HB:

| Instance | AMO | Clauses | CNF Vars | Aux Vars | Status | BW | Bound | Wall Time (s) |
|---|---|---:|---:|---:|---|---:|---:|---:|
| `bcspwr01` | `sequential` | 22,296 | 4,485 | 1,482 | `OPTIMAL` | 5 | 5 | **7.322** |
| `bcspwr01` | `binary` | 27,015 | 3,237 | 234 | `OPTIMAL` | 5 | 5 | 11.627 |
| `bcspwr01` | `pairwise` | 46,788 | 3,003 | 0 | `OPTIMAL` | 5 | 5 | 11.732 |
| `bcspwr01` | `commander` | 22,296 | 3,783 | 780 | `OPTIMAL` | 5 | 5 | 12.511 |
| `bcspwr02` | `sequential` | 38,836 | 7,105 | 2,352 | `TIMEOUT` | 8 | 6 | 30.010 |
| `bcspwr02` | `binary` | 51,073 | 5,047 | 294 | `TIMEOUT` | **7** | 6 | 30.009 |
| `bcspwr02` | `commander` | 43,674 | 5,978 | 1,225 | `TIMEOUT` | **7** | 6 | 30.017 |
| `bcspwr02` | `pairwise` | 94,291 | 4,753 | 0 | `TIMEOUT` | **7** | 6 | 30.007 |
| `bcsstk01` | `binary` | 102,049 | 4,848 | 288 | `TIMEOUT` | **18** | 12 | 30.009 |
| `bcsstk01` | `pairwise` | 132,161 | 4,560 | 0 | `TIMEOUT` | 19 | 12 | 30.012 |
| `bcsstk01` | `sequential` | 65,377 | 6,816 | 2,256 | `TIMEOUT` | 21 | 12 | 30.010 |
| `bcsstk01` | `commander` | 65,377 | 5,712 | 1,152 | `TIMEOUT` | 21 | 12 | 30.009 |
| `nos4` | `binary` | 152,579 | 20,600 | 700 | `TIMEOUT` | **12** | 8 | 30.013 |
| `nos4` | `commander` | 112,379 | 25,100 | 5,200 | `TIMEOUT` | **12** | 8 | 30.009 |
| `nos4` | `sequential` | 112,179 | 29,800 | 9,900 | `TIMEOUT` | 13 | 8 | 30.009 |
| `nos4` | `pairwise` | **577,579** | 19,900 | 0 | `TIMEOUT` | 13 | 8 | 30.009 |

- Trên `bcspwr01` (nhận kết quả tối ưu), `sequential` đạt thời gian giải nhanh nhất (`7.322s` so với `11.627s` `binary`, `11.732s` `pairwise`, `12.511s` `commander`).
- Về kích thước: `pairwise` AMO sinh ra số biến ít nhất (0 biến phụ) nhưng phình số mệnh đề bậc hai (`577,579` clauses trên `nos4` so với `112,179` của `sequential`). `binary` dùng ít biến phụ nhất (`234–700`), còn `commander` giữ số mệnh đề ngang với `sequential` nhưng ít biến phụ hơn (~52%).
- Trên `bcspwr01` với `pairwise + repeated` (lượt `m2_2_0083..0086`), cả 4 AMO đều hết `30.0s` (`TIMEOUT`, `bw=5`, `bnd=4`) vì phần lớn ngân sách thời gian bị chi phối bởi $O(n^2)$ mệnh đề cạnh của Pairwise position encoding.

---

## 8. Kết quả Experiment C – Repeated SAT vs Incremental SAT

Trên `order + sequential + sym=True` (`timeout=30s`):
- Trên `bcspwr01` (nơi giải xong `OPTIMAL` trong 4 bước giảm $k$ từ `8` xuống `5`), **Repeated** chạy nhanh hơn nhẹ so với **Incremental**:
  - CaDiCaL: `6.925s` (`repeated`) vs `7.781s` (`incremental`)
  - Glucose: `6.928s` (`repeated`) vs `7.322s` (`incremental`)
- Lý do kỹ thuật: đối với `bcspwr01` khi tìm kiếm giảm dần chỉ qua 4 mức $k$, overhead học/khởi tạo CNF mới trong `repeated` rất nhỏ (`0.014s–0.015s`), trong khi phiên bản `incremental` nạp thêm mệnh đề qua nhiều bước trên đồ thị thưa chưa tích lũy lợi thế học mệnh đề xung đột vượt trội. Ngược lại, trên `bcsstk01` ($m=176$, mật độ cạnh lớn hơn), `cadical + incremental` đạt `bw = 17` (`m2_2_0057`) trong khi `cadical + repeated` chỉ kịp xuống `bw = 18` (`m2_2_0065`) tại cùng giới hạn `30s`.

---

## 9. Kết quả Experiment D – Pairwise Position vs Order Encoding

So sánh `order` vs `pairwise` cùng cấu hình `sequential + incremental + sym=True` (`30s`):

| Instance | Backend | Order Status | Order BW | Order Wall | Order Clauses | Pairwise Status | Pairwise BW | Pairwise Wall | Pairwise Clauses |
|---|---|---|---:|---:|---:|---|---:|---:|---:|
| `bcspwr01` | `cadical` | `OPTIMAL` | 5 | **7.781s** | 22,296 | `TIMEOUT` | 5 | 30.006s | 60,484 |
| `bcspwr01` | `glucose` | `OPTIMAL` | 5 | **7.322s** | 22,296 | `TIMEOUT` | 5 | 30.006s | 60,484 |
| `bcspwr02` | `cadical` | `TIMEOUT` | **7** | 30.005s | 43,674 | `TIMEOUT` | 8 | 30.008s | 110,847 |
| `bcsstk01` | `cadical` | `TIMEOUT` | **17** | 30.004s | 105,505 | `TIMEOUT` | 19 | 30.008s | 156,424 |
| `nos4` | `cadical` | `TIMEOUT` | **10** | 30.007s | 199,617 | `RESOURCE_LIMIT` | N/A | 0.000s | 2,504,650 (est) |
| `nos4` | `glucose` | `TIMEOUT` | **13** | 30.009s | 112,179 | `RESOURCE_LIMIT` | N/A | 0.000s | 2,504,650 (est) |

`OrderEncoding` vượt trội rõ rệt so với `PairwiseEncoding` trên cả 4 instance Harwell–Boeing trong pilot này: số mệnh đề tích lũy nhỏ hơn từ `1.48x` (`bcsstk01`: `105,505` vs `156,424`) đến `2.71x` (`bcspwr01`) và tránh bùng nổ `2,504,650` mệnh đề trên `nos4` (`>12.5x` so với CaDiCaL `order` tích lũy `199,617`), đồng thời là mã hóa **duy nhất** trong 4 cấu hình thử nghiệm chứng minh được `OPTIMAL bw=5` trên `bcspwr01` trong `30s`.

---

## 10. Kết quả Experiment E – Live Gurobi vs Live CPLEX & Symmetry Breaking

1. **Trên 9 đồ thị `SmallOracle` ($n \le 14$)**:
   - Cả **Gurobi (`13.0.3`)** và **CPLEX (`22.2.0.0`)** giải **100% (`36/36` lượt)** đạt `OPTIMAL` và khớp tuyệt đối `BruteForceSolver` ($n \le 10$) lẫn nghiệm SAT (`0.0005s–0.1342s` tổng cộng).
   - Ảnh hưởng của `symmetry_breaking=True`:
     - Gurobi median: `0.0061s -> 0.0012s` (trên `Erdos–Rényi n=12`: `0.1332s -> 0.1046s`).
     - CPLEX median: `0.0070s -> 0.0013s` (trên `Erdos–Rényi n=12`: `0.1342s -> 0.0747s`).
2. **Trên Harwell–Boeing `bcspwr01` ($n=39, m=46$, `1,522` biến, `170` ràng buộc, `threads=1`, `timeout=30s`)**:
   - **Gurobi `symmetry_breaking=False`** (`m2_2_0095`): `TIMEOUT` tại `30.014s` (`bw = 5`, `objective_bound = 4.0`, `UNPROVED`).
   - **Gurobi `symmetry_breaking=True`** (`m2_2_0099`): **`OPTIMAL (PROVED)`** chỉ trong **`3.403s`** (`bw = 5`, `objective_bound = 5.0`) — cho thấy symmetry breaking đảo nhãn $p(a) \le \lceil n/2 \rceil$ giúp Gurobi đóng cận dưới từ 4 lên 5 thành công trong `3.403s` so với việc chưa thể chứng minh tối ưu tại ngưỡng timeout `30.014s`!
   - **CPLEX** trên `bcspwr01`: `UNAVAILABLE` (`Error 1016: Community Edition > 1000 vars`).
   - Trên `bcspwr02`, `bcsstk01`, `nos4` ($n \ge 48$): cả Gurobi và CPLEX đều trả về `UNAVAILABLE` sạch theo đúng giới hạn license PyPI/CE.

---

## 11. Kết quả Experiment F – Tổng hợp SAT vs MIP & Đối chiếu Paper / Leader L8

| Instance | $n$ | $m$ | Paper LB / Best | Leader L8 CaDiCaL | M2.2 Best Solver & Config | M2.2 BW / Bound | Status (Proof) | Wall Time (s) | Đối chiếu Paper Best |
|---|---:|---:|---|---|---|---:|---|---:|---|
| `bcspwr01` | 39 | 46 | `5 / 5` | `OPTIMAL bw=5` (`16.8–22.7s`, 30s) | `gurobi (MIP, sym=True)` | `5 / 5` | `OPTIMAL (PROVED)` | **3.403** | **Khớp (Bằng Best)** |
| `bcspwr01` | 39 | 46 | `5 / 5` | — | `cadical / glucose (order/seq/rep)` | `5 / 5` | `OPTIMAL (PROVED)` | `6.925 / 6.928` | **Khớp (Bằng Best)** |
| `bcspwr02` | 49 | 59 | `7 / 7` | *(chưa chạy pilot L8)* | `cadical (order/seq/inc, 30s & 60s)` | `7 / 6` | `TIMEOUT (UNPROVED)` | `30.005 / 60.016` | Chạm ngưỡng Best (`7`), chưa chứng minh tối ưu (`bnd=6`) |
| `bcsstk01` | 48 | 176 | `16 / 16` | `TIMEOUT bw=17` (30s & 120s) | `cadical (order/seq/inc, 30s & 60s)` | `17 / 12` | `TIMEOUT (UNPROVED)` | `30.004 / 60.010` | Còn cách Best `1` đơn vị (`17 vs 16`), khớp Leader L8 `bw=17` |
| `nos4` | 100 | 247 | `10 / 10` | *(chưa chạy pilot L8)* | `cadical (order/seq/inc, 30s)` | `10 / 8` | `TIMEOUT (UNPROVED)` | `30.007` | Chạm ngưỡng Best (`10`), chưa chứng minh tối ưu (`bnd=8`) |

**Nhận xét tổng hợp**:
- Trên `bcspwr01` ($n=39$), **Gurobi (`sym=True`) là solver nhanh nhất toàn bộ thí nghiệm (`3.403s`)**, vượt hơn 2 lần cả hai SAT backend tốt nhất (`~6.93s`).
- Tuy nhiên ngay từ `bcsstk01` ($n=48$) trở đi, do mô hình MIP cần $n^2+1$ biến nhị phân vượt trần evaluation/Community Edition license (`2,000` / `1,000` biến), **SAT (`OrderEncoding` + `CaDiCaL`) là phương pháp thực thi duy nhất giải tiếp được tới $n=100$ (`nos4`)**, đạt đúng giá trị nghiệm tốt nhất `7` trên `bcspwr02` và `10` trên `nos4`, cũng như `17` trên `bcsstk01`.

---

## 12. Trực quan hóa (`cnsplots`)

Lệnh `--m2-2` của `bmp.experiments.member2_plots` tự động loại bỏ các trạng thái `SKIPPED`, `UNAVAILABLE`, `RESOURCE_LIMIT`, `ERROR` khỏi mọi biểu đồ runtime (tránh vẽ nhầm `0s`) và xuất 8 biểu đồ vector SVG từ dữ liệu pilot thực (`results/member2_m2_2/runs.csv`) tại `results/member2_m2_2/figures/`:

1. [`fig1_cardinality_vs_runtime.svg`](../results/member2_m2_2/figures/fig1_cardinality_vs_runtime.svg) — Experiment B: Cardinality AMO vs Wall Time (`Order Incremental`, `glucose`).
2. [`fig2_backend_vs_runtime.svg`](../results/member2_m2_2/figures/fig2_backend_vs_runtime.svg) — Experiment A: CaDiCaL vs Glucose 4 Wall Time.
3. [`fig3_strategy_repeated_vs_incremental.svg`](../results/member2_m2_2/figures/fig3_strategy_repeated_vs_incremental.svg) — Experiment C: Repeated SAT vs Incremental SAT (`Order Sequential`).
4. [`fig4_encoding_pairwise_vs_order.svg`](../results/member2_m2_2/figures/fig4_encoding_pairwise_vs_order.svg) — Experiment D: Pairwise Position vs Order Encoding Wall Time.
5. [`fig5_gurobi_vs_cplex.svg`](../results/member2_m2_2/figures/fig5_gurobi_vs_cplex.svg) — Experiment E: Live Gurobi vs Live CPLEX trên các instance hợp lệ trong giới hạn license.
6. [`fig6_sat_vs_mip.svg`](../results/member2_m2_2/figures/fig6_sat_vs_mip.svg) — Experiment F: SAT vs MIP tổng thể (trục log ms).
7. [`fig7_cnf_clauses_vs_runtime.svg`](../results/member2_m2_2/figures/fig7_cnf_clauses_vs_runtime.svg) — Phân tán số mệnh đề CNF vs tổng thời gian chạy theo Outcome (`OPTIMAL`/`TIMEOUT`).
8. [`fig8_status_outcomes.svg`](../results/member2_m2_2/figures/fig8_status_outcomes.svg) — Phân bố trạng thái (`OPTIMAL`, `TIMEOUT`, `RESOURCE_LIMIT`, `UNAVAILABLE`) theo từng solver trên Table 6 `READY`.

---

## 13. Threats to Validity & Hạn chế Kỹ thuật

1. **Giới hạn license thương mại**: `gurobipy 13.0.3` (evaluation limit 2,000 biến/ràng buộc) và `cplex 22.2.0.0` (Community Edition 1,000 biến/ràng buộc) khiến các bài toán $n \ge 48$ hoặc $n \ge 32$ không có nghiệm MIP; không thể kết luận hiệu năng MIP học thuật/không giới hạn từ pilot này.
2. **Giới hạn thời gian pilot (`30s` / `60s`)**: Trên `bcspwr02`, `bcsstk01`, `nos4`, các SAT solver chỉ chứng minh cận dưới sơ bộ từ bounds (`6`, `12`, `8`) và chưa chứng minh UNSAT ở $B_{best}-1$; mọi kết quả `TIMEOUT` được giữ nguyên là `UNPROVED`, tuyệt đối không coi là tối ưu đã chứng minh.
3. **Độ dài hàng đợi & đơn luồng/đa tiến trình tuần tự**: Các lượt chạy được thực thi tuần tự với 1 lặp lại (`repetitions=1`) trên một máy macOS ARM64; không loại trừ nhiễu hệ điều hành ở các phép đo dưới `0.02s` (SmallOracle).
4. **Cơ chế lọc `58 NEEDS_VERIFICATION`**: Chỉ `54 READY` instances đủ điều kiện benchmark chính thức; `58` ma trận không đối xứng và `1 INVALID_DATA` cần quy ước chuyển đổi thống nhất cấp nhóm trước khi mở rộng bảng 7–8.
5. **Pairwise explosion guard**: Trên `nos4` ($n=100$), `PairwiseEncoding` ước lượng `2,504,650` clauses vượt `2,500,000` và bị chặn `RESOURCE_LIMIT`; không phản ánh tốc độ giải mà phản ánh giới hạn kích thước công thức $O(n^2 m)$.

---

## 14. Hướng dẫn Tái lập (Reproducibility Commands)

```bash
# 1. Xác minh toàn bộ test suite (93 tests)
.venv/bin/pytest -v -r a

# 2. Chạy pilot benchmark M2.2 (tự động hỗ trợ resume khi chạm batch budget 900s)
.venv/bin/python -m bmp.experiments.member2_hb configs/member2_m2_2.toml --rerun
# Nếu dừng bởi BATCH_BUDGET_STOP, chạy lại không kèm --rerun để hoàn tất phần còn lại:
.venv/bin/python -m bmp.experiments.member2_hb configs/member2_m2_2.toml

# 3. Sinh toàn bộ 8 biểu đồ cnsplots SVG từ dữ liệu thực
.venv/bin/python -m bmp.experiments.member2_plots results/member2_m2_2/runs.csv --m2-2
```
