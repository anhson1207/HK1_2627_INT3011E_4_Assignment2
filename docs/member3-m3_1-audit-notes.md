# Member 3 Phase M3.1 – Dataset, `steam3`, Deduplication & AMO Audit Notes

## 1. Ladder AMO vs Sequential Counter AMO

- `src/bmp/encodings/cardinality/ladder.py` (`LadderAMOEncoder`) triển khai chuỗi implication:
  - Với $m \ge 3$ literal: sinh $m - 1$ biến phụ và $3m - 4$ mệnh đề giống hệt `SequentialCounterAMOEncoder` (`src/bmp/encodings/cardinality/sequential.py`).
  - Tại $m = 2$: `SequentialCounterAMOEncoder` rút gọn đặc biệt thành `0` biến phụ và `1` mệnh đề `[-x0, -x1]`, trong khi `LadderAMOEncoder` / `encode_ladder_amo` giữ `1` biến phụ và `2` mệnh đề theo công thức tổng quát.
- Do đó `LadderAMOEncoder` được giữ lại như một biến thể/alias tái lập yêu cầu bài tập, không quảng bá là họ nén biến độc lập hoàn toàn với Sequential Counter.

## 2. Trường hợp `steam3` (`NEEDS_VERIFICATION`)

- Tệp nguồn: `data/harwell_boeing/raw/steam3.mtx.gz` (chỉ số khớp SHA-256 trên cả nhánh Leader và Member 3).
- Header gốc: `%%MatrixMarket matrix coordinate real general`, kích thước `80 x 80`, tổng `928` records:
  - `80` bản ghi trên đường chéo (`row == column`).
  - `614` bản ghi ngoài đường chéo có giá trị thực tường minh bằng `0.0`.
  - `234` bản ghi ngoài đường chéo có giá trị khác `0`.
- Đối chứng qua `compare_matrix_market_conversions()`:
  - **`drop_explicit_zeros`** (chuẩn parser hiện tại `read_matrix_market`): `m = 156` cạnh vô hướng, `certified_lower_bound = 4`, `RCM = 5`, `SA = 5`, `CP Optimizer (2s) = 6` — đều thấp hơn `paper_lb = 7`, `paper_best = 7` trong tài liệu tham chiếu.
  - **`keep_explicit_zeros`** (giả thuyết giữ cả cấu trúc explicit zero ngoài đường chéo như pattern `.rua` gốc của Harwell–Boeing): `m = 424` cạnh vô hướng, `certified_lower_bound = 6`, `RCM = 7`.
- **Kết luận bảo thủ:** Chưa có bằng chứng xác thực quy tắc tiền xử lý chính xác của bài báo gốc cho 32 ma trận `general` bất đối xứng; không tự ý sửa ma trận hay đổi trạng thái `NEEDS_VERIFICATION` sang `READY`.

## 3. Trùng lặp Dữ liệu Raw Harwell–Boeing (Đề xuất M3.5)

- `data/harwell_boeing/raw/` chứa 72 tệp `.mtx.gz` (Table 6–7, ~872 KB), trùng SHA-256 `72/72` với 72 tệp trong `data/hb_table6_7/raw/` của Leader/M2 (~1.8 MB gồm cả `.edgelist`).
- Trong M3.1, toàn bộ 72 file raw và `results/member3-harwell-boeing.csv` (288 dòng lịch sử) được giữ nguyên để không làm gãy đường dẫn kiểm thử cũ; đồng thời `HarwellBoeingDataset` và `scripts/run_member3_hb.py` đã đọc trực tiếp `data/benchmark_provenance.json` để mặc định chỉ chạy các instance `READY` (40/72 trong Table 6–7, hoặc 54/113 trên toàn catalog).
- Đề xuất M3.5: trỏ đường dẫn đọc mặc định về nguồn lưu trữ hợp nhất (`data/hb_table6_7/raw` hoặc `data/benchmarks/raw` qua `benchmark_catalog`) sau khi kiểm tra các test tham chiếu.
