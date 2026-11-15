# Báo cáo triển khai và thực nghiệm Member 3

## 1. Tổng quan nhiệm vụ

Member 3 phụ trách Product/Ladder AMO, MiniSat22, hai exact solver CP, RCM, SA và dataset chung. Thực nghiệm sử dụng các dòng xuất hiện trong Table 6 và Table 7 của bài DRSA. Đồ thị mẫu dùng cho kiểm thử.

## 2. Kiến trúc triển khai

`Graph` của Leader là đồ thị đơn vô hướng bất biến, có thể dùng ID đỉnh không liên tiếp. Các adapter nhận cùng một đối tượng `Graph` và trả `BMPSolution`. `assignment` ánh xạ mỗi đỉnh sang vị trí trong 1..n. `compute_bandwidth` tính max span trên các cạnh và `validate_assignment` kiểm tra song ánh cùng objective. `monotonic()` đo wall-clock trong solver, gồm bước dựng mô hình và giải, tách khỏi thời gian load ma trận.

| File | Vai trò |
|---|---|
| `src/bmp/encodings/cardinality/{product,ladder}.py` | AMO nhận IDs, trả CNF và top ID |
| `src/bmp/solvers/sat/backends/minisat.py` | Session MiniSat22 |
| `src/bmp/solvers/exact/{cpsat,cp_optimizer}.py` | Exact solver nhận Graph, time limit, trả BMPSolution |
| `src/bmp/heuristics/{rcm,sa}.py` | Heuristic nhận Graph, trả incumbent |
| `src/bmp/data/harwell_boeing.py` | Catalog và loader độc lập với solver |
| `scripts/run_member3_hb.py` | Chạy thực nghiệm Member 3 với subset, ngân sách và CSV |
| `tests/test_member3.py` | Regression tests, oracle và dữ liệu thật |

## 3. Product AMO Encoding

`encode_product_amo(variables, top_id=None)` tạo lưới r = ceil(sqrt(n)) và c = ceil(n/r). Mỗi literal gốc đúng kéo theo biến hàng và biến cột đúng. Pairwise AMO trên từng nhóm loại việc chọn hai ô khác nhau. Với n ≥ 2, có r+c biến phụ và 2n + C(r,2) + C(c,2) clause, tức O(sqrt(n)) biến phụ và O(n) clause. n ≤ 1 trả CNF rỗng. Với ràng buộc Exactly-One, thêm clause ALO chứa toàn bộ literal gốc.

Tests xét sự tồn tại của assignment cho auxiliary variables, đồng thời kiểm tra số clause, số biến phụ, ID không hợp lệ và cấp phát nối tiếp. Với Exactly-One, tests duyệt mọi assignment gốc từ 2 đến 9 biến qua assumptions MiniSat22.

## 4. Ladder AMO Encoding

`encode_ladder_amo` dùng tín hiệu prefix để biểu diễn đã có biến đúng trước vị trí hiện tại. Mỗi biến gốc đúng kích hoạt tín hiệu. Tín hiệu đi dọc chuỗi và loại các biến gốc đúng tiếp theo. Với n ≥ 2, dùng n−1 biến phụ và 3n−4 clause. Cả hai đại lượng đều O(n). n ≤ 1 trả CNF rỗng. Công thức này tương đương Sequential Counter cho k=1. Khi Leader có implementation, đối chiếu trước khi xem là hai cấu hình thực nghiệm riêng. Tests dùng cùng tiêu chí như Product.

## 5. MiniSat22

`MiniSat22Backend` nạp CNF qua PySAT. `solve(assumptions)` trả bool và `get_model()` trả model có dấu sau SAT hoặc None sau UNSAT. `add_clause` cập nhật CNF giữa các lượt. Context manager giải phóng native solver. PySAT được import lúc khởi tạo nên lỗi thiếu dependency được báo lúc dùng backend.

**BLOCKED — Waiting for Leader SAT pipeline.** Checkout có adapter MiniSat22 nhưng chưa có SAT model BMP, Repeated SAT, Incremental SAT hoặc decoder của Leader. Tests đã kiểm chứng SAT/UNSAT, assumptions, model, thêm clause, đóng session và tạo session mới. Chưa có phép đo MiniSat22 hay Product/Ladder trên đồ thị Harwell–Boeing.

## 6. CP-SAT

Mỗi đỉnh có biến nguyên p_v trong 1..n. AllDifferent bảo đảm đủ n vị trí. Mỗi cạnh thêm p_u−p_v ≤ B và p_v−p_u ≤ B, với 0 ≤ B ≤ max(0,n−1). Solver minimize B, dùng một worker và nhận seed qua `CPSATSolver(seed=...)`. Certificate được kiểm tra bằng validator Core. Native status được lưu trong metadata. Native OPTIMAL, FEASIBLE và INFEASIBLE có trạng thái tương ứng. UNKNOWN có time limit được trả về TIMEOUT theo enum Core. UNKNOWN không có time limit hoặc MODEL_INVALID được báo ERROR. Native best bound được giữ trong metadata, và lower bound nguyên làm tròn xuống bảo thủ. Với nghiệm optimal, bound bằng bandwidth đã xác minh.

## 7. IBM CP Optimizer

DOcplex dựng cùng miền vị trí, `all_diff`, `abs(p_u-p_v) <= B` và minimize B. Adapter resolve executable theo PATH hoặc đường dẫn do caller truyền, dùng một worker và đặt TimeLimit theo ngân sách còn lại. Nghiệm được kiểm tra bằng cùng validator. Metadata lưu native status và stop cause. Thiếu DOcplex, executable hoặc lỗi license được nhận diện qua lỗi backend trả UNAVAILABLE. Máy thực nghiệm có IBM runtime và đã chạy thật. Tests cũng xác nhận trường hợp thiếu executable. Chi phí khởi động native process có thể khiến wall-clock nhỉnh hơn time limit.

## 8. Reverse Cuthill–McKee

Tạo adjacency list, chọn root theo bậc tăng dần và ID để phá hòa, chạy BFS với láng giềng theo cùng thứ tự, rồi đảo ordering. Khi một thành phần hết, tiếp tục từ root chưa thăm. Đỉnh cô lập xuất hiện đúng một lần. Biến thể dùng root bậc thấp deterministic, không tìm pseudo-peripheral root. Phép đảo toàn bộ ordering giữ nguyên mọi edge span của Cuthill–McKee. Ưu điểm là chi phí thấp và tái lập, còn chất lượng phụ thuộc cấu trúc đồ thị và cách chọn root.

## 9. Simulated Annealing

SA bắt đầu với permutation của RCM, đề xuất swap hai đỉnh và tính lại max span. Chấp nhận bước không tăng bandwidth, hoặc chấp nhận bước tăng Δ với xác suất exp(−Δ/T). Sau mỗi bước nhân nhiệt độ với cooling factor. Dừng ở iteration budget hoặc khi nhiệt độ thấp hơn minimum, với mặc định T=2, cooling=0.995, minimum=1e−12. Seed của PRNG cục bộ và số bước thực hiện có trong metadata. Trả best-so-far dưới FEASIBLE, kể cả khi bước cuối xấu hơn incumbent. Đồ thị không cạnh trả ngay. Mỗi bước duyệt O(m) cạnh.

## 10. Dataset

PDF và ZIP không có ở đường dẫn được nêu. Metadata lấy từ PDF cùng DOI trên NIST, trang in 45 và 46. Table 6 có **31 dòng in** dù caption ghi 33. Table 7 có **41 dòng in**, vì đây là phần I của nhóm large. Các tổng lấy theo dòng trong bảng. Table 8 nằm ngoài tập thực nghiệm. `manifest.json` ghi DOI, URL và SHA-256 của PDF dùng để đối chiếu. [Bản bài báo lưu trên NIST](https://math.nist.gov/~JBernal/DRSA.pdf)

Cả 72 ma trận được tải từ Matrix Market của NIST, lưu nguyên bản .mtx.gz. `metadata.csv` ghi tên paper, table, n, LB, Best, URL thực tế, kích thước nguồn, đường dẫn, trạng thái và SHA-256 của file nén. Các tên có thêm underscore ở NIST giữ nguyên trong URL, còn tên paper dùng để gọi loader. **31/31 Table 6 và 41/41 Table 7** có checksum hợp lệ và n khớp. Số instance thiếu hoặc sai kích thước là 0. [Chỉ mục Matrix Market của NIST](https://math.nist.gov/MatrixMarket/matrices.html)

Loader kiểm tra checksum và kích thước rồi lọc đường chéo trong file tạm trước khi gọi reader Core. Một phần tử ngoài đường chéo khác 0 tạo cạnh vô hướng, kể cả khi chỉ có một chiều trong file. Trọng số bị bỏ, hai chiều cùng có mặt hợp nhất thành một cạnh. Giữ mọi đỉnh theo header và mọi connected component. Caller dùng `instances(table)`, `metadata(name)`, `available(name)` và `load(name)`. `available` kiểm tra catalog và sự tồn tại của file. `load` xác minh nội dung.

## 11. Experimental Results

CSV chi tiết từng lượt nằm tại `results/member3-harwell-boeing.csv`. Windows 11, Python 3.12.3, PySAT 1.9.dev15, OR-Tools 9.15.6755 và DOcplex 2.32.264. Thực nghiệm tuần tự trên 72 instance với một worker cho mỗi solver CP. Seed 17 áp dụng cho SA và CP-SAT. SA dùng tối đa 2.000 bước và mỗi lượt CP có time limit 2 giây. RCM chạy một lượt deterministic.

| Phương pháp | Số lượt | OPTIMAL | FEASIBLE | TIMEOUT | Median runtime (s) | Gap <0 / =0 / >0 | Median gap |
|---|---:|---:|---:|---:|---:|---:|---:|
| rcm | 72 | 0 | 72 | 0 | 0.0000 | 1 / 4 / 67 | 17 |
| sa | 72 | 0 | 72 | 0 | 0.3050 | 1 / 4 / 67 | 17 |
| cp-sat | 72 | 1 | 47 | 24 | 2.0000 | 0 / 2 / 46 | 261 |
| cp-optimizer | 72 | 0 | 72 | 0 | 2.0470 | 1 / 6 / 65 | 15 |

Có 264 certificate hợp lệ trong 288 lượt. Median runtime tính trên mọi lượt của phương pháp, còn thống kê gap chỉ tính trên các lượt có certificate. Một số thời gian RCM hiển thị 0 do độ phân giải monotonic của môi trường. CSV không có UNAVAILABLE, ERROR hoặc NOT_RUN cho bốn phương pháp đã chọn. MiniSat22 chưa chạy.

SA cải thiện 4/72 nghiệm RCM, mức giảm lớn nhất là 42 vị trí. Các trường hợp còn lại giữ nguyên upper bound.

Kết quả dưới paper LB cần xem xét riêng. Với steam3, dữ liệu NIST có 614 entry ghi tường minh giá trị 0. Theo quy tắc khác 0, đồ thị có 156 cạnh và RCM cho bandwidth 5. Kiểm tra chẩn đoán nếu coi mọi entry lưu ngoài đường chéo là cạnh cho 424 cạnh và RCM cho bandwidth 7. Đây là bằng chứng cho thấy quy tắc tạo adjacency có thể ảnh hưởng trực tiếp đến đối chiếu. Cần xác nhận chính xác input của bài báo trước khi diễn giải gap âm là cải thiện best-known.

Các dòng dưới LB trong CSV: steam3/rcm=5 (LB 7), steam3/sa=5 (LB 7), steam3/cp-optimizer=6 (LB 7).

## 12. Testing

`python -m pytest -p no:cacheprovider -ra`. Kết quả cuối **26 PASS, 34 subtest PASS, 0 FAIL, 0 SKIP**. Tests cũ kiểm tra Core, CLI, readers và known optima. Tests Member 3 kiểm tra AMO và ALO, MiniSat22, CP với oracle và validator, RCM deterministic, SA seed và điều kiện dừng, toàn bộ catalog và từ chối file thiếu, checksum sai hoặc sai n. Đã sửa tên stop cause của CP Optimizer theo hằng số DOcplex và bổ sung validation nội bộ cho hai exact solver.

## 13. Integration với Leader và Member 2

Giữ nguyên Graph, BMPSolution, readers, CLI, oracle, generators và cấu hình package. SAT model, tìm kiếm, decoder, protocol và benchmark framework chung chưa có trong checkout. Leader có thể tích hợp MiniSat22 bằng session API và dùng hai hàm AMO với top ID toàn cục. Member 2 có thể gọi cùng dataset loader và nhập CSV kết quả với `instance`, `table_number`, trạng thái, bound, seed và ngân sách. Script Member 3 thực hiện một lượt thử cục bộ, độc lập với kiến trúc benchmark chung.

## 14. Hướng dẫn tái lập

Chạy PowerShell tại repository. CP Optimizer cần executable cục bộ có quyền sử dụng và có thể khai báo đường dẫn qua biến môi trường.

~~~powershell
python -m venv .venv
$py = ".\.venv\Scripts\python.exe"
& $py -m pip install -e .
& $py -m pip install "pytest==9.2.0" "python-sat==1.9.dev15" "ortools==9.15.6755" "docplex==2.32.264"
$env:OPENBLAS_NUM_THREADS = "1"
# $env:BMP_CPO_EXECUTABLE = "C:\duong-dan\cpoptimizer.exe"
& $py -m pytest -p no:cacheprovider -ra
& $py -c "from bmp.data.harwell_boeing import HarwellBoeingDataset as D; d=D(); print([(t, sum(d.load(i.instance).order == i.n for i in d.instances(t))) for t in (6,7)])"

# CSV yêu cầu đường dẫn đầu ra mới
& $py scripts/run_member3_hb.py --table 6 --instance ash85 --method rcm --method sa --seed 17 --iterations 2000 --output results/hb-heuristics-repro.csv
& $py scripts/run_member3_hb.py --table 6 --instance bcspwr01 --method cp-sat --method cp-optimizer --seed 17 --timeout 2 --output results/hb-cp-repro.csv
& $py scripts/run_member3_hb.py --method rcm --method sa --method cp-sat --method cp-optimizer --seed 17 --timeout 2 --iterations 2000 --output results/hb-all-repro.csv
~~~

Ví dụ ghép Product với ALO và chạy MiniSat22.

~~~python
from bmp.encodings.cardinality.product import encode_product_amo
from bmp.solvers.sat.backends.minisat import MiniSat22Backend

variables = [1, 2, 3]
clauses, top_id = encode_product_amo(variables, top_id=10)
with MiniSat22Backend([*clauses, variables]) as backend:
    assert backend.solve([1, -2, -3])
    assert not backend.solve([1, 2])
# Ladder dùng cùng signature. Truyền top_id cho encoding kế tiếp.
~~~

## 15. Hạn chế và hướng mở rộng

Một seed và một cấu hình ngân sách mô tả một lượt thực nghiệm. Cần nhiều lần chạy và cấu hình thống nhất trước khi kết luận về tốc độ tương đối. Nghiệm CP chưa chứng minh optimal giữ FEASIBLE, và UNKNOWN khi hết thời gian có thể chưa có incumbent. Best trong paper là giá trị tham chiếu. Chỉ diễn giải khoảng cách khi assignment đã qua validator. MiniSat22 và AMO cần SAT pipeline Leader trước khi đo trên dataset. DRSA và các AMO khác như Totalizer/Cardinality Network nằm ngoài lượt bàn giao này.
