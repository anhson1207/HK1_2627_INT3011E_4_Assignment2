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

### Bảng Preflight Chi tiết Toàn bộ 54 Instance `READY`

| Instance | Table | n | m | SHA-256 | Graph Status | Pairwise CNF | Order CNF | MIP Est. (Vars/Constrs) | SAT | Gurobi | CPLEX | Reason |
|---|---|---:|---:|---|---|---|---|---| :---: | :---: | :---: |---|
| `bcspwr01` | Table 6 | 39 | 46 | VERIFIED | READY | 4,485v / 77,044c | 4,485v / 13,832c | 1,522v / 171c | True | True | False | CPLEX: 1,522 vars exceeds CE cap 1000 |
| `bcsstk01` | Table 6 | 48 | 176 | VERIFIED | READY | 6,816v / 410,568c | 6,816v / 32,289c | 2,305v / 449c | True | False | False | Gurobi: 2,305 vars exceeds cap 2000; CPLEX: 2,305 vars exceeds CE cap 1000 |
| `bcspwr02` | Table 6 | 49 | 59 | VERIFIED | READY | 7,105v / 152,855c | 7,105v / 22,080c | 2,402v / 217c | True | False | False | Gurobi: 2,402 vars exceeds cap 2000; CPLEX: 2,402 vars exceeds CE cap 1000 |
| `ash85` | Table 6 | 85 | 219 | VERIFIED | READY | 21,505v / 1,606,457c | 21,505v / 86,688c | 7,226v / 609c | True | False | False | Gurobi: 7,226 vars exceeds cap 2000; CPLEX: 7,226 vars exceeds CE cap 1000 |
| `nos4` | Table 6 | 100 | 247 | VERIFIED | READY | 29,800v / 2,504,650c | 29,800v / 118,107c | 10,001v / 695c | True | False | False | Gurobi: 10,001 vars exceeds cap 2000; CPLEX: 10,001 vars exceeds CE cap 1000 |
| `bcspwr03` | Table 6 | 118 | 179 | VERIFIED | READY | 41,536v / 2,554,051c | 41,536v / 138,411c | 13,925v / 595c | True | False | False | Gurobi: 13,925 vars exceeds cap 2000; CPLEX: 13,925 vars exceeds CE cap 1000 |
| `bcsstk04` | Table 6 | 132 | 1758 | VERIFIED | READY | 52,008v / 30,503,022c | 52,008v / 581,509c | 17,425v / 3,781c | True | False | False | Gurobi: 17,425 vars exceeds cap 2000; CPLEX: 17,425 vars exceeds CE cap 1000 |
| `bcsstk22` | Table 6 | 138 | 279 | VERIFIED | READY | 56,856v / 5,388,141c | 56,856v / 208,651c | 19,045v / 835c | True | False | False | Gurobi: 19,045 vars exceeds cap 2000; CPLEX: 19,045 vars exceeds CE cap 1000 |
| `can_144` | Table 6 | 144 | 576 | VERIFIED | READY | 61,920v / 11,984,472c | 61,920v / 308,737c | 20,737v / 1,441c | True | False | False | Gurobi: 20,737 vars exceeds cap 2000; CPLEX: 20,737 vars exceeds CE cap 1000 |
| `lund_a` | Table 6 | 147 | 1151 | VERIFIED | READY | 64,533v / 24,831,460c | 64,533v / 486,180c | 21,610v / 2,597c | True | False | False | Gurobi: 21,610 vars exceeds cap 2000; CPLEX: 21,610 vars exceeds CE cap 1000 |
| `lund_b` | Table 6 | 147 | 1147 | VERIFIED | READY | 64,533v / 24,745,612c | 64,533v / 485,012c | 21,610v / 2,589c | True | False | False | Gurobi: 21,610 vars exceeds cap 2000; CPLEX: 21,610 vars exceeds CE cap 1000 |
| `bcsstk05` | Table 6 | 153 | 1135 | VERIFIED | READY | 69,921v / 26,535,019c | 69,921v / 507,680c | 23,410v / 2,577c | True | False | False | Gurobi: 23,410 vars exceeds cap 2000; CPLEX: 23,410 vars exceeds CE cap 1000 |
| `can_161` | Table 6 | 161 | 608 | VERIFIED | READY | 77,441v / 15,816,559c | 77,441v / 374,720c | 25,922v / 1,539c | True | False | False | Gurobi: 25,922 vars exceeds cap 2000; CPLEX: 25,922 vars exceeds CE cap 1000 |
| `dwt_209` | Table 7 | 209 | 767 | VERIFIED | READY | 130,625v / 33,603,751c | 130,625v / 623,168c | 43,682v / 1,953c | True | False | False | Gurobi: 43,682 vars exceeds cap 2000; CPLEX: 43,682 vars exceeds CE cap 1000 |
| `dwt_221` | Table 7 | 221 | 704 | VERIFIED | READY | 146,081v / 34,520,089c | 146,081v / 649,880c | 48,842v / 1,851c | True | False | False | Gurobi: 48,842 vars exceeds cap 2000; CPLEX: 48,842 vars exceeds CE cap 1000 |
| `dwt_234` | Table 7 | 234 | 300 | VERIFIED | READY | 163,800v / 16,683,615c | 163,800v / 521,221c | 54,757v / 1,069c | True | False | False | Gurobi: 54,757 vars exceeds cap 2000; CPLEX: 54,757 vars exceeds CE cap 1000 |
| `dwt_245` | Table 7 | 245 | 608 | VERIFIED | READY | 179,585v / 36,704,797c | 179,585v / 714,920c | 60,026v / 1,707c | True | False | False | Gurobi: 60,026 vars exceeds cap 2000; CPLEX: 60,026 vars exceeds CE cap 1000 |
| `bcspwr04` | Table 7 | 274 | 669 | VERIFIED | READY | 224,680v / 50,491,213c | 224,680v / 888,615c | 75,077v / 1,887c | True | False | False | Gurobi: 75,077 vars exceeds cap 2000; CPLEX: 75,077 vars exceeds CE cap 1000 |
| `ash292` | Table 7 | 292 | 958 | VERIFIED | READY | 255,208v / 81,912,862c | 255,208v / 1,152,069c | 85,265v / 2,501c | True | False | False | Gurobi: 85,265 vars exceeds cap 2000; CPLEX: 85,265 vars exceeds CE cap 1000 |
| `can_292` | Table 7 | 292 | 1124 | VERIFIED | READY | 255,208v / 96,018,214c | 255,208v / 1,248,681c | 85,265v / 2,833c | True | False | False | Gurobi: 85,265 vars exceeds cap 2000; CPLEX: 85,265 vars exceeds CE cap 1000 |
| `dwt_310` | Table 7 | 310 | 1069 | VERIFIED | READY | 287,680v / 102,974,095c | 287,680v / 1,330,863c | 96,101v / 2,759c | True | False | False | Gurobi: 96,101 vars exceeds cap 2000; CPLEX: 96,101 vars exceeds CE cap 1000 |
| `dwt_361` | Table 7 | 361 | 1296 | VERIFIED | READY | 390,241v / 169,207,739c | 390,241v / 1,842,480c | 130,322v / 3,315c | True | False | False | Gurobi: 130,322 vars exceeds cap 2000; CPLEX: 130,322 vars exceeds CE cap 1000 |
| `dwt_419` | Table 7 | 419 | 1572 | VERIFIED | READY | 525,845v / 276,373,866c | 525,845v / 2,539,768c | 175,562v / 3,983c | False | False | False | SAT(order/seq): Estimated variables (525,845) exceeds safety limit (500,000); Gurobi: 175,562 vars exceeds cap 2000; CPLEX: 175,562 vars exceeds CE cap 1000 |
| `bcsstk06` | Table 7 | 420 | 3720 | VERIFIED | READY | 528,360v / 655,701,270c | 528,360v / 4,348,801c | 176,401v / 8,281c | False | False | False | SAT(order/seq): Estimated variables (528,360) exceeds safety limit (500,000); Gurobi: 176,401 vars exceeds cap 2000; CPLEX: 176,401 vars exceeds CE cap 1000 |
| `bcsstm07` | Table 7 | 420 | 3416 | VERIFIED | READY | 528,360v / 602,203,350c | 528,360v / 4,094,049c | 176,401v / 7,673c | False | False | False | SAT(order/seq): Estimated variables (528,360) exceeds safety limit (500,000); Gurobi: 176,401 vars exceeds cap 2000; CPLEX: 176,401 vars exceeds CE cap 1000 |
| `bcspwr05` | Table 7 | 443 | 590 | VERIFIED | READY | 587,861v / 116,700,154c | 587,861v / 1,891,760c | 196,250v / 2,067c | False | False | False | SAT(order/seq): Estimated variables (587,861) exceeds safety limit (500,000); Gurobi: 196,250 vars exceeds cap 2000; CPLEX: 196,250 vars exceeds CE cap 1000 |
| `can_445` | Table 7 | 445 | 1682 | VERIFIED | READY | 593,185v / 333,514,817c | 593,185v / 2,876,232c | 198,026v / 4,255c | False | False | False | SAT(order/seq): Estimated variables (593,185) exceeds safety limit (500,000); Gurobi: 198,026 vars exceeds cap 2000; CPLEX: 198,026 vars exceeds CE cap 1000 |
| `bcsstk20` | Table 7 | 485 | 1325 | VERIFIED | READY | 704,705v / 312,438,697c | 704,705v / 2,925,296c | 235,226v / 3,621c | False | False | False | SAT(order/seq): Estimated variables (704,705) exceeds safety limit (500,000); Gurobi: 235,226 vars exceeds cap 2000; CPLEX: 235,226 vars exceeds CE cap 1000 |
| `494_bus` | Table 7 | 494 | 586 | VERIFIED | READY | 731,120v / 144,176,617c | 731,120v / 2,282,097c | 244,037v / 2,161c | False | False | False | SAT(order/seq): Estimated variables (731,120) exceeds safety limit (500,000); Gurobi: 244,037 vars exceeds cap 2000; CPLEX: 244,037 vars exceeds CE cap 1000 |
| `dwt_503` | Table 7 | 503 | 2762 | VERIFIED | READY | 758,021v / 698,936,356c | 758,021v / 4,540,088c | 253,010v / 6,531c | False | False | False | SAT(order/seq): Estimated variables (758,021) exceeds safety limit (500,000); Gurobi: 253,010 vars exceeds cap 2000; CPLEX: 253,010 vars exceeds CE cap 1000 |
| `dwt_592` | Table 7 | 592 | 2256 | VERIFIED | READY | 1,050,208v / 791,410,168c | 1,050,208v / 5,115,105c | 350,465v / 5,697c | False | False | False | SAT(order/seq): Estimated variables (1,050,208) exceeds safety limit (500,000); Gurobi: 350,465 vars exceeds cap 2000; CPLEX: 350,465 vars exceeds CE cap 1000 |
| `662_bus` | Table 7 | 662 | 906 | VERIFIED | READY | 1,313,408v / 399,074,453c | 1,313,408v / 4,260,145c | 438,245v / 3,137c | False | False | False | SAT(order/seq): Estimated variables (1,313,408) exceeds safety limit (500,000); Gurobi: 438,245 vars exceeds cap 2000; CPLEX: 438,245 vars exceeds CE cap 1000 |
| `685_bus` | Table 7 | 685 | 1282 | VERIFIED | READY | 1,406,305v / 603,479,177c | 1,406,305v / 5,032,872c | 469,226v / 3,935c | False | False | False | SAT(order/seq): Estimated variables (1,406,305) exceeds safety limit (500,000); Gurobi: 469,226 vars exceeds cap 2000; CPLEX: 469,226 vars exceeds CE cap 1000 |
| `can_715` | Table 7 | 715 | 2975 | VERIFIED | READY | 1,532,245v / 1,521,829,952c | 1,532,245v / 7,821,156c | 511,226v / 7,381c | False | False | False | SAT(order/seq): Estimated variables (1,532,245) exceeds safety limit (500,000); Gurobi: 511,226 vars exceeds cap 2000; CPLEX: 511,226 vars exceeds CE cap 1000 |
| `bcsstk19` | Table 7 | 817 | 3018 | VERIFIED | READY | 2,000,833v / 2,016,015,719c | 2,000,833v / 9,591,264c | 667,490v / 7,671c | False | False | False | SAT(order/seq): Estimated variables (2,000,833) exceeds safety limit (500,000); Gurobi: 667,490 vars exceeds cap 2000; CPLEX: 667,490 vars exceeds CE cap 1000 |
| `can_838` | Table 7 | 838 | 4586 | VERIFIED | READY | 2,105,056v / 3,220,855,933c | 2,105,056v / 12,585,969c | 702,245v / 10,849c | False | False | False | SAT(order/seq): Estimated variables (2,105,056) exceeds safety limit (500,000); Gurobi: 702,245 vars exceeds cap 2000; CPLEX: 702,245 vars exceeds CE cap 1000 |
| `dwt_878` | Table 7 | 878 | 3285 | VERIFIED | READY | 2,310,896v / 2,534,089,307c | 2,310,896v / 11,151,055c | 770,885v / 8,327c | False | False | False | SAT(order/seq): Estimated variables (2,310,896) exceeds safety limit (500,000); Gurobi: 770,885 vars exceeds cap 2000; CPLEX: 770,885 vars exceeds CE cap 1000 |
| `gr_30_30` | Table 7 | 900 | 3422 | VERIFIED | READY | 2,428,200v / 2,773,594,350c | 2,428,200v / 11,815,557c | 810,001v / 8,645c | False | False | False | SAT(order/seq): Estimated variables (2,428,200) exceeds safety limit (500,000); Gurobi: 810,001 vars exceeds cap 2000; CPLEX: 810,001 vars exceeds CE cap 1000 |
| `dwt_918` | Table 7 | 918 | 3233 | VERIFIED | READY | 2,526,336v / 2,726,609,175c | 2,526,336v / 11,821,047c | 842,725v / 8,303c | False | False | False | SAT(order/seq): Estimated variables (2,526,336) exceeds safety limit (500,000); Gurobi: 842,725 vars exceeds cap 2000; CPLEX: 842,725 vars exceeds CE cap 1000 |
| `dwt_992` | Table 7 | 992 | 7876 | VERIFIED | READY | 2,950,208v / 7,748,573,008c | 2,950,208v / 22,490,745c | 984,065v / 17,737c | False | False | False | SAT(order/seq): Estimated variables (2,950,208) exceeds safety limit (500,000); Gurobi: 984,065 vars exceeds cap 2000; CPLEX: 984,065 vars exceeds CE cap 1000 |
| `nos1` | Table 8 | 237 | 390 | VERIFIED | READY | 168,033v / 22,148,953c | 168,033v / 575,368c | 56,170v / 1,255c | True | False | False | Gurobi: 56,170 vars exceeds cap 2000; CPLEX: 56,170 vars exceeds CE cap 1000 |
| `saylr1` | Table 8 | 238 | 445 | VERIFIED | READY | 169,456v / 25,438,987c | 169,456v / 605,535c | 56,645v / 1,367c | True | False | False | Gurobi: 56,645 vars exceeds cap 2000; CPLEX: 56,645 vars exceeds CE cap 1000 |
| `plat362` | Table 8 | 362 | 2712 | VERIFIED | READY | 392,408v / 355,193,495c | 392,408v / 2,872,477c | 131,045v / 6,149c | False | False | False | SAT(order/seq): Estimated clauses (2,872,477) exceeds safety limit (2,500,000); Gurobi: 131,045 vars exceeds cap 2000; CPLEX: 131,045 vars exceeds CE cap 1000 |
| `plskz362` | Table 8 | 362 | 880 | VERIFIED | READY | 392,408v / 115,784,071c | 392,408v / 1,549,773c | 131,045v / 2,485c | True | False | False | Gurobi: 131,045 vars exceeds cap 2000; CPLEX: 131,045 vars exceeds CE cap 1000 |
| `nos5` | Table 8 | 468 | 2352 | VERIFIED | READY | 656,136v / 515,354,814c | 656,136v / 3,726,193c | 219,025v / 5,641c | False | False | False | SAT(order/seq): Estimated variables (656,136) exceeds safety limit (500,000); Gurobi: 219,025 vars exceeds cap 2000; CPLEX: 219,025 vars exceeds CE cap 1000 |
| `nos6` | Table 8 | 675 | 1290 | VERIFIED | READY | 1,365,525v / 589,614,862c | 1,365,525v / 4,922,896c | 455,626v / 3,931c | False | False | False | SAT(order/seq): Estimated variables (1,365,525) exceeds safety limit (500,000); Gurobi: 455,626 vars exceeds cap 2000; CPLEX: 455,626 vars exceeds CE cap 1000 |
| `nos7` | Table 8 | 729 | 1944 | VERIFIED | READY | 1,592,865v / 1,034,888,035c | 1,592,865v / 6,544,720c | 531,442v / 5,347c | False | False | False | SAT(order/seq): Estimated variables (1,592,865) exceeds safety limit (500,000); Gurobi: 531,442 vars exceeds cap 2000; CPLEX: 531,442 vars exceeds CE cap 1000 |
| `orsirr_2` | Table 8 | 886 | 2542 | VERIFIED | READY | 2,353,216v / 1,997,911,837c | 2,353,216v / 9,987,225c | 784,997v / 6,857c | False | False | False | SAT(order/seq): Estimated variables (2,353,216) exceeds safety limit (500,000); Gurobi: 784,997 vars exceeds cap 2000; CPLEX: 784,997 vars exceeds CE cap 1000 |
| `jagmesh1` | Table 8 | 936 | 2664 | VERIFIED | READY | 2,626,416v / 2,336,676,732c | 2,626,416v / 11,106,865c | 876,097v / 7,201c | False | False | False | SAT(order/seq): Estimated variables (2,626,416) exceeds safety limit (500,000); Gurobi: 876,097 vars exceeds cap 2000; CPLEX: 876,097 vars exceeds CE cap 1000 |
| `nos2` | Table 8 | 957 | 1590 | VERIFIED | READY | 2,745,633v / 1,460,167,153c | 2,745,633v / 9,443,368c | 915,850v / 5,095c | False | False | False | SAT(order/seq): Estimated variables (2,745,633) exceeds safety limit (500,000); Gurobi: 915,850 vars exceeds cap 2000; CPLEX: 915,850 vars exceeds CE cap 1000 |
| `nos3` | Table 8 | 960 | 7442 | VERIFIED | READY | 2,762,880v / 6,856,926,240c | 2,762,880v / 20,717,277c | 921,601v / 16,805c | False | False | False | SAT(order/seq): Estimated variables (2,762,880) exceeds safety limit (500,000); Gurobi: 921,601 vars exceeds cap 2000; CPLEX: 921,601 vars exceeds CE cap 1000 |
| `saylr3` | Table 8 | 1000 | 1375 | VERIFIED | READY | 2,998,000v / 1,379,618,500c | 2,998,000v / 9,739,251c | 1,000,001v / 4,751c | False | False | False | SAT(order/seq): Estimated variables (2,998,000) exceeds safety limit (500,000); Gurobi: 1,000,001 vars exceeds cap 2000; CPLEX: 1,000,001 vars exceeds CE cap 1000 |
| `sherman1` | Table 8 | 1000 | 1375 | VERIFIED | READY | 2,998,000v / 1,379,618,500c | 2,998,000v / 9,739,251c | 1,000,001v / 4,751c | False | False | False | SAT(order/seq): Estimated variables (2,998,000) exceeds safety limit (500,000); Gurobi: 1,000,001 vars exceeds cap 2000; CPLEX: 1,000,001 vars exceeds CE cap 1000 |
| `sherman4` | Table 8 | 1104 | 1341 | VERIFIED | READY | 3,654,240v / 1,640,257,512c | 3,654,240v / 11,481,127c | 1,218,817v / 4,891c | False | False | False | SAT(order/seq): Estimated variables (3,654,240) exceeds safety limit (500,000); Gurobi: 1,218,817 vars exceeds cap 2000; CPLEX: 1,218,817 vars exceeds CE cap 1000 |

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

---

## 9. Hướng dẫn Tái lập M2.3

```bash
# 1. Preflight toàn bộ 54 instance READY
.venv/bin/python -m bmp.experiments.member2_m2_3 configs/member2_m2_3_baseline.toml --preflight-only

# 2. Chạy Baseline SAT trên 54 READY (Batch 900s, tự chặn 29 RESOURCE_LIMIT)
.venv/bin/python -m bmp.experiments.member2_m2_3 configs/member2_m2_3_baseline.toml --rerun

# 3. Chạy Controlled Studies A-G (tự động kế thừa Baseline_54 và resume nếu chạm 900s)
.venv/bin/python -m bmp.experiments.member2_m2_3 configs/member2_m2_3_studies.toml

# 4. Sinh toàn bộ 10 biểu đồ cnsplots SVG cho M2.3
.venv/bin/python -m bmp.experiments.member2_plots results/member2_m2_3/runs.csv --m2-3 --preflight results/member2_m2_3/preflight_54.csv

# 5. Chạy toàn bộ regression tests
.venv/bin/pytest -v -r a
```
