# Báo cáo Kỹ thuật & Thực nghiệm Phase M3.2 – Product AMO, Ladder AMO & MiniSat Integration

## 1. Product AMO Encoding (`ProductAMOEncoder`)

### Cơ chế mã hóa và Công thức giải tích
- Bố trí $m \ge 2$ literal vào ma trận kích thước $r \times c$ với:
  $$r = \lfloor\sqrt{m - 1}\rfloor + 1, \qquad c = \left\lceil\frac{m}{r}\right\rceil$$
- Số biến phụ cho mỗi ràng buộc $AMO$ độ rộng $m$:
  $$\text{aux}_{\text{product}}(m) = \begin{cases} 0 & m < 2 \\ r + c = O(\sqrt{m}) & m \ge 2 \end{cases}$$
- Số mệnh đề sinh ra (gồm $2m$ implication từ literal sang biến hàng/cột và Pairwise AMO trên các hàng và cột):
  $$\text{clauses}_{\text{product}}(m) = \begin{cases} 0 & m < 2 \\ 2m + \binom{r}{2} + \binom{c}{2} & m \ge 2 \end{cases}$$
- Đã tích hợp hoàn chỉnh vào `ProductAMOEncoder(AMOEncoder)` hỗ trợ literal âm/dương, `SimpleVarAllocator` dùng chung, đăng ký `"product"` trong `bmp.encodings.cardinality`, công thức giải tích chính xác trong `bmp.encodings.estimator._product_amo_counts` và CLI (`--amo product`).

### Ưu, nhược điểm và Thực nghiệm (Study B)
- **Ưu điểm:** Không cần $O(m)$ biến phụ như Sequential/Ladder ($r + c = O(\sqrt{m})$). Ví dụ trên `bcspwr01` ($n=39$) với `OrderEncoding`, `order_product` dùng `3,510` biến tổng cộng so với `4,485` biến của `order_sequential` và `3,783` biến của `order_commander`. Trên `PairwiseEncoding`, `Product` giảm số mệnh đề từ `1,855,327` (`pairwise`) xuống `1,291,097` trên `ash85` ($n=85$).
- **Nhược điểm:** Ở $m = 2$, lưới $2 \times 1$ cần $3$ biến phụ và $5$ mệnh đề (nhiều hơn $1$ mệnh đề của Pairwise); so với `Binary` ($O(\log m)$ biến phụ), số biến phụ $O(\sqrt{m})$ lớn hơn nhưng giữ ít mệnh đề bậc dài hơn ($2m + O(m)$ nhị phân thay vì $m\lceil\log_2 m\rceil$).
- **Kết quả pilot `Minisat` 10s (Study B):** Trong giới hạn 10 giây, `order_product` đạt bandwidth `5` trên `bcspwr01` (`8 -> 5`) và `23` trên `bcsstk01` (`27 -> 23`), còn `pairwise_product` đạt `21` trên `bcsstk01` (`27 -> 21`). Tuy nhiên chưa cấu hình nào chứng minh UNSAT tại $B^* - 1$ trong 10 giây.

---

## 2. Ladder AMO Encoding (`LadderAMOEncoder`) & Đối chứng với Sequential Counter

### Công thức và Quan hệ đại số với Sequential Counter
- `LadderAMOEncoder` sử dụng chuỗi tín hiệu implication $s_0, \dots, s_{m-2}$:
  - $x_0 \Rightarrow s_0$ (`[-x_0, s_0]`)
  - Với $1 \le i \le m - 2$: $x_i \Rightarrow s_i$, $s_{i-1} \Rightarrow s_i$, và $\neg x_i \lor \neg s_{i-1}$
  - $\neg x_{m-1} \lor \neg s_{m-2}$
- **Kết quả kiểm toán & đối chiếu cấu trúc:**
  1. Với mọi **$m \ge 3$**, `LadderAMOEncoder` và `SequentialCounterAMOEncoder` (`src/bmp/encodings/cardinality/sequential.py`) sinh ra **chính xác cùng số biến phụ ($m-1$), cùng số mệnh đề ($3m-4$), và cùng từng mệnh đề CNF theo cùng thứ tự biến**. Hai phương pháp là **tương đương hoàn toàn về mặt toán học lẫn triển khai** cho $m \ge 3$.
  2. **Khác biệt duy nhất tại trường hợp biên $m = 2$:** `SequentialCounterAMOEncoder` tối ưu riêng thành `0` biến phụ và `1` mệnh đề nhị phân `[-x_0, -x_1]`, trong khi `LadderAMOEncoder` / `encode_ladder_amo` giữ đồng nhất công thức $m-1 = 1$ biến phụ và $3m - 4 = 2$ mệnh đề (`[-x_0, s_0]`, `[-x_1, -s_0]`) nhằm bảo toàn hợp đồng đếm ở bộ kiểm thử gốc M3.0/M3.1. Có thể tối ưu $m=2$ bằng phép triệt $s_0$ mà vẫn giữ nguyên ngữ nghĩa $\neg x_0 \lor \neg x_1$, tuy nhiên M3.2 giữ nguyên quy tắc $m \ge 2$ để bảo toàn hồi quy và khớp 100% với `estimate_cnf_size`.
  3. Do bản chất tương đương trên mọi $n \ge 3$, `LadderAMOEncoder` được giữ lại dưới dạng biến thể có tên riêng để tái lập yêu cầu bài tập, **không** báo cáo như một phát minh mã hóa độc lập mới.

### Kết quả đối chứng thực nghiệm (Study C – 12 cặp trên Table 6)
- Trong toàn bộ `12/12` cặp đối chứng trên `bcspwr01`, `bcspwr02`, `bcsstk01` ($n \ge 39$), `estimate_cnf_size` ở ngưỡng khởi tạo $k = UB - 1$ của `ladder` và `sequential` khớp nhau **100% tuyệt đối** (`4485/54504`, `4485/13188`, `7105/92675`, `7105/20664`, `6816/94824`, `6816/23137`).
- Trên `9/12` cặp, số biến/mệnh đề ở ngưỡng dừng cuối cùng cũng khớp 100%; ở `3` cặp còn lại gần ngưỡng `10.0s` (`bcspwr01 order repeated`, `bcspwr02 order repeated`, `bcsstk01 pairwise incremental`), dao động thời gian nhỏ khiến một phía kịp kiểm tra sâu hơn 1 ngưỡng $k$, làm `cnf_clauses` tại ngưỡng dừng cuối khác nhau do **độ sâu ngưỡng đạt được** chứ không phải do khác biệt công thức CNF.

---

## 3. MiniSat 2.2 Backend (`MiniSatBackend`) & Tích hợp Pipeline SAT

- `MiniSatBackend` (`src/bmp/solvers/sat/backends/minisat.py`) kế thừa `SATBackend`, bao gói `pysat.solvers.Minisat22` và đăng ký `"minisat"`, `"minisat22"`.
- **Lifecycle & Timeout:**
  - Triển khai `add_clause`, `append_formula`, `solve`, `solve_with_timeout` (dùng `threading.Timer` gọi `Minisat22.interrupt()` trên `solve_limited(..., expect_interrupt=True)` và xóa cờ trong `finally` qua `clear_interrupt()`), `get_model()` (chỉ trả model khi `_last_sat == True`), `delete()` / `close()`.
  - Kiểm chứng live bằng bài toán `PHP(8, 7)` có biến gác (`solve_with_timeout(0.05)` trả `None`, sau đó dùng lại chính instance đó với assumption tắt ràng buộc PHP trả `True` cùng witness hợp lệ).
  - Tương thích hoàn toàn với worker subprocess `run_bounded_solver` (`worker.py`) và theo dõi `sat_trace`, `sampled_peak_memory_mb`.
- **Tái sử dụng trong Incremental SAT (Study D & Instrumentation):**
  - Kiểm thử instrumentation xác nhận `IncrementalSATSolver(..., backend_name="minisat")` tạo `MiniSatBackend` **đúng 1 lần** (`solver_creations == 1`) qua nhiều ngưỡng giảm dần, ngược lại `RepeatedSATSolver` tạo lại mới bằng đúng số `sat_calls`.

---

## 4. Phân tích Thực nghiệm Pilot M3.2 (`results/member3_m3_2/`)

> **Ranh giới bằng chứng khoa học:**
> - **Correctness** đã chứng minh chặt chẽ bằng brute-force oracle trên đồ thị nhỏ (path, cycle, complete, star, edgeless, disconnected, isolated vertex, random seed) với `Pairwise`/`Order` $\times$ `Product`/`Ladder` $\times$ `Repeated`/`Incremental` $\times$ `MiniSat`/`CaDiCaL`/`Glucose`.
> - **Pilot Benchmark** thực hiện riêng biệt trên 5 đồ thị Harwell–Boeing Table 6 đã được provenance L8 xác nhận `READY` (`bcspwr01`, `bcspwr02`, `bcsstk01`, `ash85`, và `bcsstk04` kiểm tra guard), **ngân sách 10.0s mỗi lượt**, `symmetry_breaking=True`, tổng `80` lượt chạy đã loại trùng lặp (`799.60s` tổng batch time). **100% (80/80) kiểm định hợp lệ.**

### Tổng hợp kết quả theo Study

1. **Tình trạng kết thúc (`80` lượt):** `79 TIMEOUT` (luôn giữ incumbent hợp lệ; **`62/80` lượt cải thiện được so với `initial_ub`**) và `1 RESOURCE_LIMIT` (`bcsstk04` `pairwise_product`, ước lượng `23,496` biến / `12,952,818` mệnh đề > ngưỡng `2,500,000`, bị chặn an toàn ở mức preflight với `peak_memory_mb = 13.22 MiB`, `sat_calls = None`).
2. **Study A (`MiniSat` vs `CaDiCaL` vs `Glucose` trên `order_sequential`, `incremental`, 10s):**
   - `bcspwr01` (`init_ub=8`, `paper_best=5`): `Glucose` đạt `5` (`3` calls, `29.20 MiB`), `MiniSat` đạt `6` (`2` calls, `26.92 MiB`), `CaDiCaL` đạt `6` (`2` calls, `32.55 MiB`).
   - `bcspwr02` (`init_ub=13`, `paper_best=7`): `MiniSat` đạt `8` (`5` calls, `34.06 MiB`), `Glucose` đạt `9` (`4` calls, `36.02 MiB`), `CaDiCaL` đạt `10` (`3` calls, `40.95 MiB`).
   - `bcsstk01` (`init_ub=27`): `MiniSat` và `CaDiCaL` đạt `25` (`2` calls), `Glucose` đạt `26` (`1` call).
   - `ash85` (`init_ub=10`): Cả 3 backend đều timeout ngay lần gọi đầu $k=9$ (`21,505` biến, `82,746` mệnh đề, `41.45–56.12 MiB` RSS).
   - **Nhận xét:** Không có backend nào chứng minh tối ưu trong 10s ở 4 đồ thị HB; `MiniSat` có mức tiêu thụ bộ nhớ gọn (`26.9–50.3 MiB`) và cạnh tranh tốt về primal bound trong 10s trên `bcspwr02`/`bcsstk01`, trong khi `Glucose` tìm thấy `5` trên `bcspwr01` sớm nhất.
3. **Study D (`Repeated` vs `Incremental` trên `MiniSat + Product`, `sym=True`):**
   - `Incremental` chỉ khởi tạo solver 1 lần (`solver_creations=1, solver_reused=True`), đạt `bcspwr02` (`order`: `8`, `pairwise`: `9`), `bcsstk01` (`order`: `23`, `pairwise`: `21`), tốt hơn `Repeated` linear (`9/11` và `25/25`) và `Repeated` binary (`9/13` và `27/27`) trong cùng 10s.
   - `Repeated binary` bỏ qua các ngưỡng dễ bên trên và nhảy thẳng vào điểm giữa (`9` trên `bcspwr02`, `19` trên `bcsstk01`): nếu điểm giữa quá khó trong 10s, phiên bản `binary` không hạ được `initial_ub` (`13` giữ nguyên trên `bcspwr02 pairwise`, `27` giữ nguyên trên `bcsstk01`), trong khi `linear` / `incremental` giảm dần ổn định từng bước.
4. **Bộ nhớ và quy mô CNF (`Order` vs `Pairwise` trên `ash85`):**
   - Cùng trên `ash85` (`n=85, m=219`), `order_sequential` cần `82,746` mệnh đề (`41.45 MiB` RSS), trong khi `pairwise_product` cần `1,291,097` mệnh đề (`339.12 MiB`) và `pairwise_pairwise` cần `1,855,327` mệnh đề (`401.67 MiB` — cao nhất toàn batch) và thậm chí chưa kịp hoàn tất tạo CNF/chạy SAT trước ngưỡng 10s. Điều này cho thấy lợi thế mở rộng của `Order` encoding so với `Pairwise` trên đồ thị lớn.

### Hạn chế còn lại
- Chưa có chứng nhận `OPTIMAL` cho các instance Harwell–Boeing dưới ngưỡng 10s (chỉ là kết quả pilot khám phá giới hạn primal & tài nguyên; chứng nhận tối ưu và benchmark rộng hơn thực hiện cùng MIP/CP/DRSA ở các phase tiếp theo).
- Chưa chạy live OR-Tools CP-SAT / IBM CP Optimizer và chưa triển khai DRSA (thuộc M3.3 và M3.4).
