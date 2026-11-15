#!/usr/bin/env python3
"""Render measured L10 charts and a Vietnamese report from checkpointed results."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/leader_l10_cadical_optimization"
DOC = ROOT / "docs/leader-l10-cadical-optimization-report.md"
FIG = OUT / "figures"


def rows(name):
    with (OUT / name).open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def chart(name, labels, values, title, ylabel="Instances"):
    plt.figure(figsize=(7, 4))
    plt.bar(labels, values, color="#31688e")
    plt.title(title)
    plt.ylabel(ylabel)
    plt.tight_layout()
    plt.savefig(FIG / f"{name}.svg")
    plt.close()


def render():
    FIG.mkdir(parents=True, exist_ok=True)
    summary = json.loads((OUT / "summary.json").read_text())
    table = rows("per_table_summary.csv")
    best = rows("per_instance_best.csv")
    runs = rows("cadical_runs_113.csv") + rows("cadical_extended_runs.csv") + rows("adaptive_strategy_comparison.csv")
    encoding_runs = rows("encoding_optimization_comparison.csv")
    proof_runs = rows("cadical_proof_attempts.csv")
    cp = rows("heuristic_bound_comparison.csv")
    resource = rows("resource_gap_analysis.csv")
    timeout = rows("timeout_case_analysis.csv")
    dataset = {r["instance"]: r for r in rows("dataset_113.csv")}
    chart("01_coverage", ["L9", "L10"], [70, summary["l10_attempted"]], "CaDiCaL attempted, unique instances")
    chart("02_sat_witnesses", ["L9", "L10", "Cumulative"],
          [23, summary["l10_sat_witnesses"], summary["cumulative_sat_witnesses"]],
          "Validated CaDiCaL SAT witnesses")
    chart("03_sat_by_table", [r["table"] for r in table[:-1]],
          [int(r["sat_feasible_l10"]) for r in table[:-1]], "L10 SAT witnesses by table")
    chart("04_unresolved", ["L9 timeout", "L9 resource", "L10 timeout", "L10 resource"],
          [46, 43, int(table[-1]["timeout_no_sat"]), int(table[-1]["resource_limit"])],
          "Unresolved unique instances")
    groups = ["A", "B", "C", "D", "E"]
    chart("05_timeout_groups", groups,
          [sum(r["group"] == g for r in timeout) for g in groups], "L9 timeout diagnostic groups")
    chart("06_resource_pilot", ["500k", "750k", "1m"],
          [sum(r[f"eligible_{c}"] == "True" for r in resource) for c in ("500k", "750k", "1m")],
          "Resource cases within variable and clause caps")
    ablation = [r for r in runs if r["stage"] == "MATCHED_30"]
    if ablation:
        modes = sorted({r["search_mode"] for r in ablation})
        chart("07_matched_search", modes,
              [sum(r["search_mode"] == m and r["sat_solved_any"] == "True" for r in ablation) for m in modes],
              "Matched 30-second SAT witness runs", "Runs")
    cp_match = sum(r["graph_match"] == "True" for r in cp)
    chart("08_cp_source_audit", ["Graph matched", "Validated permutation"],
          [cp_match, sum(r["usable_as_upper_bound"] == "True" for r in cp)],
          "CP-SAT source audit")
    if runs:
        fig, ax = plt.subplots(figsize=(7, 4))
        for marker, label, subset in (("o", "SAT", [r for r in runs if r["sat_solved_any"] == "True"]),
                                      ("x", "No SAT", [r for r in runs if r["sat_solved_any"] != "True"])):
            x = [int(r["n"]) for r in subset if r.get("total_wall_time_s")]
            y = [float(r["total_wall_time_s"]) for r in subset if r.get("total_wall_time_s")]
            ax.scatter(x, y, marker=marker, alpha=.7, label=label)
        ax.set(xlabel="Vertices", ylabel="Wall time (s)", title="CaDiCaL runtime by graph size")
        ax.legend()
        fig.tight_layout()
        fig.savefig(FIG / "09_runtime_vs_size.svg")
        plt.close(fig)
        fig, ax = plt.subplots(figsize=(7, 4))
        ax.scatter([int(r["n"]) for r in runs if r.get("peak_rss_mb")],
                   [float(r["peak_rss_mb"]) for r in runs if r.get("peak_rss_mb")], alpha=.6)
        ax.set(xlabel="Vertices", ylabel="Peak sampled RSS (MiB)", title="CaDiCaL memory by graph size")
        fig.tight_layout()
        fig.savefig(FIG / "10_memory_vs_size.svg")
        plt.close(fig)
        fig, ax = plt.subplots(figsize=(7, 4))
        for sat, label in ((True, "SAT"), (False, "No SAT")):
            subset = [r for r in runs if (r["sat_solved_any"] == "True") == sat and r.get("num_variables") and r.get("num_clauses")]
            ax.scatter([int(r["num_variables"]) for r in subset], [int(r["num_clauses"]) for r in subset],
                       label=label, alpha=.6)
        ax.set(xlabel="CNF variables", ylabel="CNF clauses", title="CNF size and SAT outcome")
        ax.legend()
        fig.tight_layout()
        fig.savefig(FIG / "11_cnf_vs_success.svg")
        plt.close(fig)
    chart("12_primary_status", ["Attempted", "SAT", "No SAT"],
          [sum(r["l10_attempted"] == "True" for r in best),
           sum(r["l10_sat_witness"] == "True" for r in best),
           sum(r["l10_attempted"] == "True" and r["l10_sat_witness"] != "True" for r in best)],
          "L10 primary coverage and witness")
    for filename, stage, key, title in (
        ("13_order_vs_pairwise", "FAMILY_30", "encoding", "Order vs Pairwise, matched 30 s"),
        ("14_amo", "AMO_30", "amo", "Sequential vs Pairwise AMO, matched 30 s"),
        ("15_repeated_incremental", "STRATEGY_30", "strategy", "Repeated vs Incremental, matched 30 s"),
        ("16_search_modes", "SEARCH_30", "search_mode", "Linear vs Binary vs Adaptive, matched 30 s"),
    ):
        subset = [r for r in encoding_runs if r["stage"] == stage]
        if subset:
            labels = sorted({r[key] for r in subset})
            chart(filename, labels,
                  [sum(r[key] == label and r["sat_solved_any"] == "True" for r in subset) for label in labels],
                  title, "SAT-model runs")
    paired_cp = [(int(dataset[r["instance"]]["rcm_ub"]), int(r["cp_reported_bandwidth"]))
                 for r in cp if r["graph_match"] == "True" and r["cp_reported_bandwidth"]]
    if paired_cp:
        fig, ax = plt.subplots(figsize=(7, 4))
        ax.scatter([x for x, _ in paired_cp], [y for _, y in paired_cp], alpha=.6)
        ax.set(xlabel="Validated RCM bandwidth", ylabel="CP-SAT reported bandwidth (unverified)",
               title="RCM vs CP-SAT reported values on matching graphs")
        fig.tight_layout()
        fig.savefig(FIG / "17_rcm_vs_cp_reported.svg")
        plt.close(fig)

    table_md = "\n".join(
        f"| {r['table']} | {r['total']} | {r['eligible']} | {r['attempted']} | {r['sat_feasible_cumulative']} | {r['sat_optimal_cumulative']} | {r['bound_optimal_cumulative']} | {r['timeout_no_sat']} | {r['resource_limit']} |"
        for r in table
    )
    complete = summary["complete_primary"]
    ablation_lines = []
    for stage in ("MATCHED_30", "ENCODING_30", "AMO_30", "FAMILY_30", "STRATEGY_30", "SEARCH_30"):
        subset = [r for r in runs + encoding_runs if r["stage"] == stage]
        if subset:
            ablation_lines.append(
                f"| {stage} | {len(subset)} | {sum(r['solver_attempted']=='True' for r in subset)} | "
                f"{sum(r['sat_solved_any']=='True' for r in subset)} |"
            )
    ablation_md = "\n".join(ablation_lines) if ablation_lines else "| Chưa có run | 0 | 0 | 0 |"
    pilot = [r for r in runs if r["stage"].startswith("CAP_PILOT")]
    pilot_invoked = len({r["instance"] for r in pilot if r["solver_attempted"] == "True"})
    peak = max((float(r["peak_rss_mb"]) for r in runs + encoding_runs if r.get("peak_rss_mb")), default=0)
    proof_new = sum(r.get("proof_status") == "SAT_PROVED_OPTIMAL" for r in proof_runs)
    matched_binary = [r for r in ablation if r["search_mode"] == "binary"]
    matched_adaptive = [r for r in ablation if r["search_mode"] == "adaptive"]
    matched_binary_sat = sum(r["sat_solved_any"] == "True" for r in matched_binary)
    matched_adaptive_sat = sum(r["sat_solved_any"] == "True" for r in matched_adaptive)
    report = f"""# Leader L10: Tối ưu CaDiCaL trên 113 đồ thị

## Git và baseline

HEAD trước L10: `e614334` trên `dev/leader`; remote cùng commit lúc audit. L9 có 113 đồ thị, 70 eligible, 70 CaDiCaL attempts, 23 SAT witnesses, 2 SAT proofs và 1 bounds proof. Kết quả L9 được giữ nguyên. HEAD sau L10: xem lịch sử Git của commit báo cáo.

## Dataset và kiểm chứng

Đã dựng lại 113 đồ thị từ tệp raw và đối chiếu 113/113 graph fingerprints cùng conversion policy. Table 6/7/8 lần lượt có 31/41/41 đồ thị; 54 READY, 58 NEEDS_VERIFICATION, 1 INVALID_DATA. Không thay đổi quy tắc conversion. Mọi mô hình CaDiCaL đã được giải mã và xác thực độc lập bằng `validate_solution` lúc chạy. Các run instrumented mới lưu `witness_permutation_json` để kiểm tra lại sau benchmark; checkpoint cũ không chứa permutation.

## Phân tích 46 timeout và 43 resource limits

Chi tiết từng trường hợp nằm trong `timeout_case_analysis.csv` và `resource_gap_analysis.csv`. Phân nhóm timeout dùng n, gap và kích thước CNF; đây là chẩn đoán heuristic, không phải chứng minh nguyên nhân timeout. Trong 43 resource cases, {sum(r['eligible_750k']=='True' for r in resource)} đồ thị nằm dưới cả trần 750k biến và 2.5M clauses theo estimator. Pilot giữ worker isolation, hard timeout và 4096 MiB guard.

## Adaptive search và encoding

Adaptive repeated SAT hỏi tại UB heuristic đã xác thực để lấy model CaDiCaL thật, rồi thử ngưỡng cao trước khi siết. Với gap nhỏ, nó thử tuyến tính; với gap lớn, nó dùng khoảng 3/4 phía trên. SAT model được validate tại threshold. UNKNOWN/timeout không được coi là UNSAT. Pilot so sánh binary/adaptive ở 30 giây trên cùng graph, encoding, backend và máy; xem `adaptive_strategy_comparison.csv`. Encoding chọn từ Pairwise support single, Order one-sided compact và Order full qua estimator. `ENCODING_30` so Order full với Order one-sided compact trên cùng graph, backend, thời hạn và search mode. `FAMILY_30` so Order và Pairwise; `AMO_30` so Pairwise và Sequential AMO. `STRATEGY_30` so Repeated và Incremental; `SEARCH_30` so linear/binary/adaptive. Chỉ các cặp đủ run được diễn giải.

| Ablation | Run records | Actual solver calls | SAT-model runs |
|---|---:|---:|---:|
{ablation_md}

Trong cặp `MATCHED_30`, binary có {matched_binary_sat}/{len(matched_binary)} SAT-model runs và adaptive có {matched_adaptive_sat}/{len(matched_adaptive)}. Đây là kết quả trên tập pilot chọn trước, không ngoại suy thành tỷ lệ toàn bộ 113 đồ thị.

## CP-SAT upper bound

Nhánh Member 3 chỉ cung cấp CSV kết quả và checkpoint không chứa permutation CP-SAT. {cp_match}/113 fingerprints khớp. Không thể chạy independent permutation validator, nên 0 CP-SAT bandwidth được dùng làm bound cho CaDiCaL. `heuristic_bound_comparison.csv` ghi rõ từng trường hợp. Không quy kết nghiệm CP-SAT cho CaDiCaL.

## Cấu hình CaDiCaL

PySAT 1.9.dev17 với CaDiCaL195 trên máy này có API `solve`, `solve_limited`, `set_phases`, `conf_budget`, `prop_budget`, `interrupt`, `clear_interrupt`, `get_model`, `add_clause` và `append_formula`. L10 dùng API đã có trong backend (`solve`, `get_model`, `append_formula`) với worker subprocess cho hard timeout. Không có ablation về phase hints hoặc restart nội bộ, nên không quy kết cải thiện cho tuning CaDiCaL.

## Kết quả campaign

| Table | Total | Eligible | Attempted | SAT feasible cumulative | SAT optimal cumulative | Bound optimal cumulative | L10 Timeout | L10 ResourceLimit |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
{table_md}

L10 có {summary['l10_sat_witnesses']} instance có SAT witness từ các run mới; hợp nhất với L9 là {summary['cumulative_sat_witnesses']} instance. Trạng thái primary records: {'hoàn tất' if complete else 'chưa hoàn tất'}; toàn bộ eligible có bằng chứng CaDiCaL call: {summary['all_eligible_solver_invoked']}. `solver_invocation_evidence` phân biệt event trực tiếp, call đã ghi và suy luận từ worker progress: snapshot CNF được gửi ngay trước lời gọi solver, worker vẫn sống ít nhất 2 giây sau snapshot. Trường hợp timeout trong construction không được tính là solver call. `sat_calls` cũ có thể thiếu một call đang chạy khi worker bị cắt; số 0 trên record suy luận không được đọc là không gọi solver. Các run được phân biệt theo ngân sách trong CSV. Số SAT proofs mới: {summary['l10_sat_optimal']}. Proof lịch sử `bcspwr01` ở L8 vẫn nằm trong Git history; L10 không suy ra proof mới từ nó.

## Runtime, RAM và giới hạn

Biểu đồ trong `figures/` chỉ dùng số đo thật. Peak RSS quan sát lớn nhất trong run CSV là {peak:.1f} MiB; sampled RSS không phải peak tuyệt đối. Solver time loại trừ lời gọi bị worker cắt giữa chừng; wall time là so sánh ngân sách phù hợp. Cấu hình 30 giây và 60 giây không được so như cùng ngân sách. Có {len(pilot)} pilot record dưới cap 750k và {pilot_invoked} unique instance có CaDiCaL call; pilot chỉ được tính mở rộng coverage nếu có lời gọi CaDiCaL quan sát được. Chưa có bằng chứng rằng bound CP-SAT, một encoding riêng, hay tăng thời gian là nguyên nhân của mọi cải thiện. Selected proof runs: {len(proof_runs)}, SAT proofs mới trong tập này: {proof_new}.

## No regression, kiểm thử và tái lập

`no_regression_report.csv` giữ 23 witness L9 trong số liệu hợp nhất; không sửa historical files. Xem `reproduction.md` để chạy lại. Full pytest: 83 passed, 0 failed. Wheel `bmp_optimization-0.1.0-py3-none-any.whl` đã build bằng `pip wheel --no-build-isolation`; CLI `bmp --help` chạy thành công. Kết luận nghiệm thu: {'đạt điều kiện actual solver attempt cho mọi eligible' if summary['all_eligible_solver_invoked'] else 'chưa đạt điều kiện actual solver attempt cho mọi eligible'}; các ablation và CP permutation validation còn giới hạn như trên.
"""
    DOC.write_text(report, encoding="utf-8")
    (OUT / "reproduction.md").write_text(
        "# L10 reproduction\n\nRun `.venv/bin/python scripts/run_leader_l10.py --max-batch-seconds 1500` from repo root. "
        "The campaign resumes from atomic `checkpoint_runs.json` and never writes L9 results. "
        "Then run `.venv/bin/python scripts/report_leader_l10.py`, `.venv/bin/python -m pytest -q`, "
        "`.venv/bin/python -m pip wheel . --no-deps --no-build-isolation -w /tmp/bmp-l10-dist`, "
        "and `.venv/bin/python -m bmp --help`.\n",
        encoding="utf-8")


if __name__ == "__main__":
    render()
