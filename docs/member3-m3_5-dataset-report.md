# Báo cáo Phase M3.5 – Kiểm toán Pháp y Tập Dữ liệu Harwell–Boeing & Tính Tương Đương Benchmark

> **Tài liệu gốc:** J. Torres-Jimenez, I. Izquierdo-Marquez, A. Garcia-Robledo, A. Gonzalez-Gomez, J. Bernal, R. N. Kacker (2015), *"A dual representation simulated annealing algorithm for the bandwidth minimization problem on graphs"*, Information Sciences **303**, 33–49.  
> **Chuẩn định dạng:** NIST Matrix Market Coordinate Text Format & Harwell–Boeing Sparse Matrix Collection.  
> **Phiên bản Validator / Policy:** `validator_version="m3.5"`, `official_conversion_policy="nonzero_union"`, `conversion_version="1.0"`.

---

## 1. Tóm tắt Pháp y Cốt lõi (Phân tách Tường minh theo Bằng chứng)

### 1.1. Sự thật đã Kiểm chứng từ Nguồn Gốc (`SOURCE-VERIFIED FACTS`)
1. **Phân bổ 113 ma trận gốc (NIST Harwell–Boeing `.mtx.gz`):**
   - Toàn bộ `113/113` tệp lưu trữ dưới `data/benchmarks/raw/` đều khớp **100% SHA-256** với `data/benchmark_provenance.json` (`31 Table 6 + 41 Table 7 + 41 Table 8`).
   - Cấu trúc header Matrix Market: `48 symmetric`, `1 skew-symmetric` (`plskz362`), `64 general`; phân bổ miền giá trị: `82 real`, `31 pattern`; **`0/113` ma trận chứa phần tử trùng tọa độ (`duplicate_entries == 0`)**.
2. **Tập `54 READY` không có bất kỳ độ mơ hồ chuyển đổi nào (`SOURCE_CONFIRMED`):**
   - Gồm `48 symmetric` + `1 skew-symmetric` (`plskz362`, lưu một tam giác, `0` số 0 tường minh) **VÀ `5 general`** (`orsirr_2`, `saylr1`, `saylr3`, `sherman1`, `sherman4`, đều ở Bảng 8) có **đúng 0 số 0 tường minh** và **đúng 0 cặp bất đối xứng ngoài đường chéo (`structural_symmetry_nonzero == 1.0000`)**. Notice `sherman4` đối xứng 100% về cấu trúc cạnh dù `value_symmetry_nonzero == 0.0000` (giá trị số thực ngược/khác nhau theo cặp `(i,j)` và `(j,i)`).
   - Hệ quả: trên toàn bộ `54 READY`, cả 4 quy tắc chuyển đổi `nonzero_union`, `stored_union`, `nonzero_intersection`, `stored_intersection` đều sinh **cùng một đồ thị vô hướng duy nhất**.
3. **26 ma trận chứa số 0 tường minh (`explicit zeros`):**
   - Có `26/113` tệp (toàn bộ nằm trong `58 NEEDS_VERIFICATION`, `header_symmetry = general`, `field = real`) ghi tường minh giá trị `0.0`: `4` ma trận chỉ có số `0.0` trên đường chéo (`gre_185`, `gre_216a`, `gre_343`, `gre_512`) và **`22` ma trận có số `0.0` ngoài đường chéo (`explicit_offdiagonal_zeros > 0`)**.
4. **Kiểm toán 3 bản sao dataset và danh sách cạnh trong repo:**
   - Toàn bộ **`72/72` tệp `.mtx.gz` Bảng 6–7** tại `data/harwell_boeing/raw/` và `data/hb_table6_7/raw/` giống **100% từng byte (SHA-256)** với `data/benchmarks/raw/` (`41` tệp Bảng 8 chỉ có trong `data/benchmarks/raw/`).
   - Toàn bộ **`72/72` tệp `data/hb_table6_7/graphs/*.edgelist`** trùng khớp 100% về `topology_sha256` với chuẩn `nonzero_union` của dự án ([`official_preflight.csv`](../results/member3_m3_5/official_preflight.csv)).
5. **Paper gốc không định nghĩa quy tắc cho ma trận không đối xứng & số `0.0` tường minh:**
   - Torres-Jimenez et al. (2015) chỉ định nghĩa BMPG trên đồ thị vô hướng hữu hạn $G=(V, E)$ (Mục 1–2) và khẳng định trong Mục 5 rằng **giữ nguyên toàn bộ đỉnh (kể cả đỉnh cô lập)** theo Bảng 5. Paper không công bố công thức chuyển ma trận `RUA`/`PUA` bất đối xứng hay quy tắc giữ/bỏ `0.0` ngoài đường chéo.

### 1.2. Phát hiện Tính toán Tái lập được (`REPRODUCIBLE COMPUTATIONAL FINDINGS`)
1. **Phát hiện 2 cặp đồ thị trùng cấu trúc hoàn toàn (trên `113` ma trận chỉ còn `111` đồ thị phân biệt; trên `54 READY` chỉ còn `53` cấu trúc phân biệt):**
   - `mbeacxc == mbeaflw` (`n=496, m=41686`, Table 8 `NEEDS_VERIFICATION`): đã được paper gốc ghi nhận tại trang 48 (*chỉ khác trọng số*).
   - **`saylr3 == sherman1`** (`n=1000, m=1375, components=318, largest_component=681`, Table 8 **`READY`**): được `topology_sha256` của M3.5 phát hiện lần đầu tiên trong kho mã này; paper gốc liệt kê cả hai như 2 thực nghiệm tách biệt dù đồ thị vô hướng giống nhau từng cạnh (thậm chí trong Bảng 8 paper, `LB=35`, `Best=46`, `GRASP-PR=52` của cả hai khớp nhau).
2. **Bác bỏ toán học `Variant A` (`nonzero_union`) và `Variant C` (`nonzero_intersection`) trên `steam3` (`n=80`, Table 6):**
   - Bộ giải chính xác `CPSATSolver` chứng minh tối ưu (`OPTIMAL`, có biên dưới = biên trên):
     - `nonzero_union` (`m=156`, bỏ 614 số `0.0` ngoài chéo): **`OPTIMAL B*(G) = 5` < Published LB = `7`** (bác bỏ tuyệt đối).
     - `nonzero_intersection` (`m=78`, `21` thành phần liên thông): **`OPTIMAL B*(G) = 3` < Published LB = `7`** (bác bỏ tuyệt đối).
     - **`stored_union` / `stored_intersection` (`m=424`, giữ nguyên 614 ô `0.0`):** **`structural_symmetry_stored == 1.0000`** và `CPSATSolver` chứng minh **`OPTIMAL B*(G) = 7 == Published LB = 7 == Published Best = 7`** (`9.39s`).
3. **Bác bỏ `Variant C/D` (giao / intersection) và bất đối xứng một phía trên nhóm bài toán nhỏ:**
   - `pores_1` (`Published LB=7`): `nonzero_union` đạt `OPTIMAL bw=7`, trong khi `nonzero_intersection` bị bác bỏ với `OPTIMAL bw=6 < 7` và `triangular_upper` đạt `OPTIMAL bw=6 < 7`.
   - `ibm32` (`Published LB=11`): `nonzero_union` đạt `OPTIMAL bw=11`, trong khi `nonzero_intersection` bị bác bỏ (`OPTIMAL bw=1`), `triangular_lower` (`OPTIMAL bw=6`), `triangular_upper` (`OPTIMAL bw=7`).
   - `curtis54` (`Published LB=10`): `triangular_upper` bị bác bỏ (`OPTIMAL bw=8`).
   - `impcol_b` (`Published LB=19`): `nonzero_intersection` bị bác bỏ (`OPTIMAL bw=4`).
   - `will57` (`Published LB=6`): `nonzero_union` đạt `OPTIMAL bw=6`.
4. **Đối chứng 19/19 ma trận đa thành phần trong Bảng 5 của Paper ([`table5_component_consistency.csv`](../results/member3_m3_5/table5_component_consistency.csv)):**
   - **`stored_union` (`Variant B`) khớp 100% tập 19 đồ thị đa thành phần của Bảng 5** (khớp cả `19/19` kích thước thành phần lớn nhất và **không sinh thêm** đồ thị rời rạc nào ngoài Bảng 5).
   - **`nonzero_union` (`Variant A`) tạo sai 2 đồ thị rời rạc không hề có trong Bảng 5:** `fs_680_1` (tách thành `190` thành phần, `189` đỉnh cô lập do bỏ 462 số `0.0`) và `fs_760_1` (`16` thành phần, `15` đỉnh cô lập do bỏ 237 số `0.0`). Dưới `stored_union`, cả hai đều liên thông hoàn toàn (`components=1`).
   - **`nonzero_intersection` (`Variant C`)** vỡ thành `60` đồ thị không liên thông và sai kích thước thành phần lớn nhất ở **10/10 ma trận bất đối xứng** trong Bảng 5.
5. **Dấu hiệu cấu trúc của nhóm `steam*` & `hor_131` & `fs_541_1`:**
   - Bốn ma trận `steam1` (`z_off=1514`), `steam2` (`z_off=8100`), `steam3` (`z_off=614`), và `hor_131` (`z_off=528`) đều đạt **`structural_symmetry_stored == 1.0000`** khi giữ lại các ô số `0.0` (chúng vốn là cấu trúc đối xứng bị khuyết nửa cặp do phần tử số học bằng `0.0`). Trên `steam2`, thăm dò DRSA (ngân sách 1.2s) đạt `63 == Published Best` dưới `stored_union` so với `82` dưới `nonzero_union`. Trên `fs_541_1`, cận dưới bậc đồ thị tăng từ `269` (`nonzero_union`) lên `270 == Published LB` (`stored_union`).
6. **Phân tích pháp y `mbeause` (`raw n=496` vs `Table 8 paper_n=492` vs `Table 5 Total=496 / Largest=492`):**
   - Ma trận gốc có `496 x 496`, chứa đúng `4` đỉnh cô lập `[493, 494, 495, 496]` và thành phần liên thông lớn nhất gồm `492` đỉnh (`m=36209`).
   - Paper tự mâu thuẫn nội bộ: Bảng 5 (tr. 44) ghi `Total=496, Largest=492` nhưng Bảng 8 (tr. 47) vẫn để `n=492` (trong khi `mbeacxc`/`mbeaflw` liền kề ghi `n=496`).
   - Bằng chứng lý thuyết & kiểm thử oracle khẳng định việc thêm/bớt đỉnh cô lập khi $E \neq \emptyset$ **không làm thay đổi băng thông tối ưu $B^*(G)$**; trên `mbeause`, `RCM` và `DRSA` đều cho kết quả giống hệt nhau (`473`) trên cả bản `496` đỉnh lẫn `492` đỉnh.

### 1.3. Giả thuyết & Câu hỏi Chưa Chốt (`HYPOTHESES / UNRESOLVED QUESTIONS`)
- Mặc dù **`stored_union` (giữ các phần tử tường minh `0.0` theo pattern cấu trúc Harwell–Boeing và lấy hợp $A + A^T$)** được chứng minh khớp Bảng 5 (`19/19`, `0` ngoại lệ), giải thích `steam1/2/3`, `hor_131`, `fs_680_1`, `fs_760_1` và `pores_1/ibm32/will57`, paper Torres-Jimenez et al. (2015) không phát biểu tường minh quy tắc chuyển từ ma trận `RUA/PUA` sang cạnh đồ thị trong văn bản, và nguồn hoán vị tham chiếu `~jtj/bmp/` chưa được đối chứng trực tiếp trong pha này.
- Vì vậy, **tuân thủ kỷ luật dữ liệu tuyệt đối**, M3.5 **KHÔNG** nâng khống bất kỳ ma trận nào từ `58 NEEDS_VERIFICATION` hay `mbeause` lên `READY`. Quy ước chuẩn chính thức của kho mã cho các thực nghiệm đối chứng giữ nguyên **`54 READY` (`53` cấu trúc phân biệt) dưới `conversion_policy="nonzero_union"`** và phân tầng rõ `evidence_level` cho `58 + 1` đồ thị còn lại.

---

## 2. Phân tầng Chứng cứ trên Toàn bộ `113` Đồ thị ([`matrix_audit_113.csv`](../results/member3_m3_5/matrix_audit_113.csv))

| Trạng thái Chính thức (`validation_status`) | Phân tầng Bằng chứng (`evidence_level`) | Số lượng | Đại diện & Ghi chú | Chính sách cho M3.6 |
|---|---|---:|---|---|
| `READY` | `SOURCE_CONFIRMED` | **54** | 48 symmetric, 1 skew-symmetric (`plskz362`), 5 general 100% structurally symmetric (`orsirr_2`, `saylr1`, `saylr3`, `sherman1`, `sherman4`); gồm 1 cặp trùng cấu trúc `saylr3==sherman1` | **ĐƯỢC PHÉP chạy thực nghiệm chính thức** (báo cáo cả 54 READY và 53 unique topologies) |
| `NEEDS_VERIFICATION` | `CONFLICTING_EVIDENCE` | **3** | `steam3` (`OPT 5 < LB 7` vs `stored_union OPT 7`), `fs_680_1`, `fs_760_1` (lệch thành phần Bảng 5 dưới `nonzero_union`) | **LOẠI khỏi so sánh chính thức**; chỉ trình bày ở phụ lục độ nhạy (`official_benchmark=False`) |
| `NEEDS_VERIFICATION` | `STRONGLY_SUPPORTED` | **7** | `steam1`, `steam2`, `hor_131` (`sym_st=1.0000`); `pores_1`, `ibm32`, `curtis54`, `will57` (`CP-SAT` khớp `LB/Best` dưới `union`, bác bỏ `intersection`) | **LOẠI khỏi so sánh chính thức** do chưa có xác nhận văn bản paper |
| `NEEDS_VERIFICATION` | `PLAUSIBLE` | **10** | Các ma trận bất đối xứng không có `0.0` ngoài chéo nằm trong Bảng 5 (`gent113`, `impcol_a`, `jpwh_991`, `lns_131`, `lns_511`, `mbeacxc`, `mbeaflw`, `mcca`, `mcfe`, `pores_3`) khớp kích thước lớn nhất Bảng 5 theo `union` | **LOẠI khỏi so sánh chính thức** |
| `NEEDS_VERIFICATION` | `UNRESOLVED` | **38** | Các ma trận `general` bất đối xứng còn lại (`gre_*`, `bp_*`, `west*`, `shl_*`, `str_*`, `arc130`, `fs_183_1`, `fs_541_1`, `impcol_b/c/d/e`, `jagmesh1`, `nnc261`, `nnc666`, `plat362`, `will199`) | **LOẠI khỏi so sánh chính thức** |
| `INVALID_DATA` | `CONFLICTING_EVIDENCE` | **1** | `mbeause` (raw `n=496`, Table 5 `496/492`, Table 8 `n=492`, `31,755` cặp bất đối xứng) | **LOẠI khỏi thực nghiệm chính thức** |
| **Tổng cộng** | | **113** | | **54 READY chính thức (53 cấu trúc duy nhất)** |

---

## 3. Thiết kế Kỹ thuật Đã Triển khai & Kiểm chứng Độc lập

1. **Chuẩn hóa Fingerprint & Độc lập Định dạng ([`src/bmp/io/readers.py`](../src/bmp/io/readers.py)):**
   - Bổ sung [`compute_topology_sha256`](../src/bmp/io/readers.py) (chuẩn hóa chỉ số đỉnh theo thứ tự khai báo `0..n-1` bất biến giữa `0-based` và `1-based`, nhạy với thêm/bớt đỉnh cô lập, đổi cạnh, đảo thứ tự đỉnh) và [`compute_graph_fingerprint`](../src/bmp/io/readers.py) (gắn kèm `conversion_policy` và `conversion_version`).
   - Tách rạch ròi bộ phân tích dùng chung [`inspect_matrix_market_forensics`](../src/bmp/io/readers.py) / [`convert_matrix_market`](../src/bmp/io/readers.py) khỏi các quy tắc thử nghiệm (`stored_union`, `nonzero_intersection`, `stored_intersection`, `triangular_lower`, `triangular_upper`). Tham số bảo vệ `require_official=True` ném `ValueError` nếu cố nạp ma trận ngoài chuẩn `READY + nonzero_union`.
2. **Quản lý Bản sao Dataset & Backward Compatibility ([`src/bmp/core/benchmark_catalog.py`](../src/bmp/core/benchmark_catalog.py), [`src/bmp/data/harwell_boeing.py`](../src/bmp/data/harwell_boeing.py)):**
   - Bổ sung [`resolve_raw_matrix_path`](../src/bmp/core/benchmark_catalog.py) (ưu tiên `data/benchmarks/raw`, dự phòng `data/hb_table6_7/raw` và `data/harwell_boeing/raw`) và [`audit_raw_copy_parity`](../src/bmp/core/benchmark_catalog.py) kiểm chứng `72/72` bản sao khớp 100% SHA-256. Không xóa các thư mục theo dõi lịch sử để không phá vỡ test M2/M3 hiện hữu; tài liệu hóa lộ trình dọn bản sao cho sau khi hợp nhất.
   - Tái cấu trúc [`HarwellBoeingDataset.load`](../src/bmp/data/harwell_boeing.py) bỏ tệp tạm và parser trùng lặp, tái sử dụng trực tiếp [`parse_matrix_market_forensics`](../src/bmp/io/readers.py).
   - Mở rộng [`preflight-benchmark`](../src/bmp/cli.py) hiển thị thêm `validator_version="m3.5"`, `official_conversion_policy="nonzero_union"`, `conversion_version="1.0"` giữ nguyên tương thích ngược.
3. **Bổ sung siêu dữ liệu cộng thêm cho [`data/benchmark_provenance.json`](../data/benchmark_provenance.json):**
   - Bổ sung an toàn không phá vỡ dữ liệu cũ: `conversion_policy`, `conversion_version`, `graph_fingerprint`, `topology_sha256`, `stored_union_edges`, `stored_union_topology_sha256`, `explicit_zero_entries`, `explicit_offdiagonal_zeros`, `structural_symmetry_nonzero`, `structural_symmetry_stored`, `value_symmetry_nonzero`, `evidence_level`, `source_confirmation`, `topology_duplicate_of`, `unresolved_issues`, `last_verified_date`, `validator_version`.
4. **Kiểm chứng Bình đẳng Đầu vào trên 8 Tuyến Solver ([`tests/test_member3_forensics_m3_5.py`](../tests/test_member3_forensics_m3_5.py)):**
   - Đã kiểm chứng cùng một `GraphInstance` chuẩn hóa và `graph_fingerprint` đi vào cả 8 tuyến: `Leader SAT (Pairwise+Sequential+CaDiCaL)`, `Member 2 SAT (Order+Binary+Glucose)`, `Member 2 MIP (Gurobi / CPLEX)`, `Member 3 SAT (Pairwise+Product+MiniSat)`, `CP-SAT`, `CP Optimizer`, `RCM`, `SA`, và `DRSA`.

---

## 4. Danh mục Tệp Đầu ra M3.5

- [`results/member3_m3_5/matrix_audit_113.csv`](../results/member3_m3_5/matrix_audit_113.csv) — Bảng kiểm toán đầy đủ 113 ma trận (header, zeros, đối xứng cấu trúc/giá trị, thành phần, SHA-256, `topology_sha256`, `graph_fingerprint`).
- [`results/member3_m3_5/unsymmetric_audit_58.csv`](../results/member3_m3_5/unsymmetric_audit_58.csv) — Kiểm toán chi tiết từng ma trận trong `58 NEEDS_VERIFICATION`.
- [`results/member3_m3_5/conversion_candidates.csv`](../results/member3_m3_5/conversion_candidates.csv) — Thí nghiệm thăm dò `official_benchmark=False` (`CP-SAT` + `RCM`/`DRSA` qua 6 biến thể).
- [`results/member3_m3_5/table5_component_consistency.csv`](../results/member3_m3_5/table5_component_consistency.csv) — Đối chiếu 19/19 thành phần Bảng 5 + bất thường `fs_680_1` & `fs_760_1`.
- [`results/member3_m3_5/evidence_register.csv`](../results/member3_m3_5/evidence_register.csv) — Sổ đăng ký bằng chứng nguồn gốc vs tính toán.
- [`results/member3_m3_5/steam3_case_study.md`](../results/member3_m3_5/steam3_case_study.md) & [`results/member3_m3_5/mbeause_case_study.md`](../results/member3_m3_5/mbeause_case_study.md) — Hai hồ sơ điều tra chuyên sâu.
- [`results/member3_m3_5/official_preflight.csv`](../results/member3_m3_5/official_preflight.csv), [`results/member3_m3_5/dataset_decisions.csv`](../results/member3_m3_5/dataset_decisions.csv), [`results/member3_m3_5/graph_fingerprints.json`](../results/member3_m3_5/graph_fingerprints.json), [`results/member3_m3_5/summary.json`](../results/member3_m3_5/summary.json), [`results/member3_m3_5/run_log.txt`](../results/member3_m3_5/run_log.txt).
