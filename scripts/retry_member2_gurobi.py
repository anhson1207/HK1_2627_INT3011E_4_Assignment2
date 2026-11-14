"""Resume the 90 Gurobi Table 6-8 retries and merge them with the CPLEX baseline."""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from time import monotonic

from bmp.core.bounds import degree_lower_bound, identity_upper_bound
from bmp.core.validation import validate_assignment
from bmp.experiments.member2_hb import FIELDS, identity, read_rows
from bmp.io.readers import read_graph

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "results/member2_cplex_retry_1016/runs_merged.csv"
GRAPHS = ROOT / "data/hb_table6_7_8/graphs"
OUTPUT = ROOT / "results/member2_gurobi_retry"
EXTRA = ("gurobi_started", "gurobi_status", "timeout_origin")
DETAIL_FIELDS = FIELDS + EXTRA


def targets():
    baseline = read_rows(SOURCE)
    keys = [identity(row) for row in baseline]
    if len(baseline) != 1243 or len(set(keys)) != 1243:
        raise ValueError("Baseline must contain 1,243 unique keys")
    selected = [row for row in baseline if row["solver"] == "gurobi" and (
        row["status"] == "RESOURCE_LIMIT" and
        row["error"] == f"MIP binary variables {int(row['n']) ** 2} exceed configured cap 250000"
        or row["instance"] == "pores_1" and row["status"] == "ERROR")]
    grouped = defaultdict(list)
    for row in selected:
        grouped[row["instance"]].append(row)
        if (row["encoding"], row["strategy"], row["amo"], row["repetition"],
                float(row["timeout_seconds"])) != ("", "", "", "1", 60.0):
            raise ValueError(f"Unexpected target configuration: {identity(row)}")
    if len(selected) != 90 or len(grouped) != 45 or any(
            sorted(r["symmetry_breaking"] for r in group) != ["false", "true"]
            for group in grouped.values()):
        raise ValueError(f"Expected 90 rows on 45 graphs, found {len(selected)} on {len(grouped)}")
    if max(int(r["n"]) ** 2 for r in selected if r["instance"] != "pores_1") > 1_250_000:
        raise ValueError("Retry MIP cap does not cover every selected graph")
    ordered = ["pores_1"] + sorted((n for n in grouped if n != "pores_1"),
                                  key=lambda n: (int(grouped[n][0]["n"]), n))
    return baseline, selected, ordered


def prepare():
    _, selected, ordered = targets()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "benchmark.toml").write_text(
        '[benchmark]\nmanifest = "manifest.csv"\n'
        'graph_dir = "../../data/hb_table6_7_8/graphs"\n'
        'output_dir = "."\ntimeout_seconds = 60.0\nrepetitions = 1\n'
        'max_sat_estimated_clauses = 2000000\nmax_mip_variables = 1250000\n'
        'amo = ["pairwise", "sequential", "binary", "commander"]\n'
        'solvers = ["gurobi"]\n', encoding="utf-8")
    manifest = {r["instance"]: r for r in read_rows(ROOT / "data/hb_table6_7_8/manifest.csv")}
    with (OUTPUT / "manifest.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=next(iter(manifest.values())).keys())
        writer.writeheader()
        writer.writerows(manifest[name] for name in ordered)
    expected = {identity(r) for r in selected}
    rows = read_rows(OUTPUT / "runs.csv") if (OUTPUT / "runs.csv").exists() else []
    seen = [identity(r) for r in rows]
    if len(seen) != len(set(seen)) or set(seen) - expected:
        raise ValueError("Retry CSV contains duplicate or unexpected keys")
    return selected, ordered, rows, expected


def run():
    selected, ordered, recorded, expected = prepare()
    by_key = {identity(r): r for r in selected}
    done = {identity(r) for r in recorded}
    path = OUTPUT / "runs.csv"
    with path.open("a", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=DETAIL_FIELDS)
        if not path.stat().st_size:
            writer.writeheader()
            stream.flush()
            os.fsync(stream.fileno())
        for name in ordered:
            graph = read_graph(GRAPHS / f"{name}.edgelist")
            for symmetry in ("false", "true"):
                key = (name, "gurobi", "", "", "", symmetry, "1")
                if key in done:
                    continue
                row = dict(by_key[key])
                row.update({field: "" for field in EXTRA})
                progress = OUTPUT / "gurobi_stage.json"
                progress.unlink(missing_ok=True)
                args = [sys.executable, "-m", "bmp.experiments.member2_hb", "--worker",
                        str(GRAPHS / f"{name}.edgelist"), "gurobi", "-", "-", "-",
                        symmetry, "60.0", str(progress)]
                started = monotonic()
                print(f"START {name} symmetry={symmetry}", flush=True)
                try:
                    completed = subprocess.run(args, cwd=ROOT, capture_output=True,
                                               text=True, encoding="utf-8", errors="replace",
                                               timeout=60.0, check=False)
                    if completed.returncode:
                        error = (completed.stderr or completed.stdout).strip()[-2000:]
                        status = "UNAVAILABLE" if "license" in error.lower() else "ERROR"
                        result = {"status": status, "error": error,
                                  "gurobi_started": False, "gurobi_status": ""}
                    else:
                        result = json.loads(completed.stdout.strip().splitlines()[-1])
                        result["gurobi_started"] = bool(result.get("gurobi_started"))
                        result["timeout_origin"] = (
                            "gurobi" if result["status"] == "TIMEOUT" and
                            str(result.get("gurobi_status")) == "9" else "")
                except subprocess.TimeoutExpired:
                    stage = json.loads(progress.read_text(encoding="utf-8"))["stage"] if progress.exists() else "startup"
                    result = {"status": "TIMEOUT", "error": f"Hard wall timeout during {stage}",
                              "gurobi_started": stage in ("optimizing", "finished"),
                              "gurobi_status": "", "timeout_origin": "hard_wall_" + stage}
                except (ValueError, IndexError) as exc:
                    result = {"status": "ERROR", "error": f"Worker output error: {exc}",
                              "gurobi_started": False, "gurobi_status": ""}
                if result.get("status") in ("TIMEOUT", "UNAVAILABLE", "ERROR") and not result.get("assignment"):
                    bandwidth, assignment = identity_upper_bound(graph)
                    report = validate_assignment(graph, assignment, claimed_bandwidth=bandwidth)
                    result.update(bandwidth=bandwidth, best_bound=degree_lower_bound(graph),
                                  validation=report.valid, assignment=assignment,
                                  incumbent_origin="identity_start")
                assignment = result.pop("assignment", None)
                if assignment:
                    assignment = {int(v): int(p) for v, p in assignment.items()}
                    report = validate_assignment(graph, assignment, claimed_bandwidth=result.get("bandwidth"))
                    result["validation"] = report.valid
                    result["bandwidth"] = report.actual_bandwidth
                    if not report.valid:
                        result.update(status="ERROR", error="; ".join(report.errors))
                row.update(result)
                row["assignment"] = json.dumps(assignment, sort_keys=True) if assignment else ""
                row["gurobi_started"] = str(bool(row["gurobi_started"]))
                row["runtime_total_s"] = monotonic() - started
                writer.writerow({field: row.get(field, "") for field in DETAIL_FIELDS})
                stream.flush()
                os.fsync(stream.fileno())
                done.add(key)
                print(f"DONE {len(done)}/{len(expected)} {name} symmetry={symmetry} "
                      f"{row['status']} bw={row['bandwidth']} started={row['gurobi_started']} "
                      f"raw={row['gurobi_status']}", flush=True)
    report()


def report():
    baseline, selected, _ = targets()
    recorded = read_rows(OUTPUT / "runs.csv") if (OUTPUT / "runs.csv").exists() else []
    expected = {identity(r) for r in selected}
    by_key = {identity(r): r for r in recorded}
    if len(recorded) != 90 or set(by_key) != expected:
        raise ValueError(f"Retry incomplete: {len(recorded)}/90 rows")
    merged = [{field: by_key[identity(row)][field] if identity(row) in by_key else row[field]
               for field in FIELDS} for row in baseline]
    keys = [identity(row) for row in merged]
    if len(merged) != 1243 or len(set(keys)) != 1243:
        raise ValueError("Merged table must contain 1,243 unique keys")
    before_cplex = [r for r in baseline if r["solver"] == "cplex"]
    after_cplex = [r for r in merged if r["solver"] == "cplex"]
    if before_cplex != after_cplex:
        raise ValueError("CPLEX rows changed")
    with (OUTPUT / "runs_merged.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(merged)

    initial = {}
    started_by_key = {identity(r): r["gurobi_started"] == "True" for r in recorded}
    def counts(rows):
        gurobi = [r for r in rows if r["solver"] == "gurobi"]
        ran = {r["instance"] for r in gurobi if r["status"] in
               ("TIMEOUT", "OPTIMAL", "FEASIBLE", "INFEASIBLE") and
               (started_by_key[identity(r)] if rows is merged and identity(r) in started_by_key
                else r["incumbent_origin"] == "solver")}
        improved, optimal = set(), set()
        for row in gurobi:
            if row["validation"] != "True" or not row["bandwidth"] or row["incumbent_origin"] != "solver":
                continue
            name = row["instance"]
            if name not in initial:
                initial[name], _ = identity_upper_bound(read_graph(GRAPHS / f"{name}.edgelist"))
            if int(row["bandwidth"]) < initial[name]:
                improved.add(name)
            if row["status"] == "OPTIMAL":
                optimal.add(name)
        return len(ran), len(improved), len(optimal)

    before, after = counts(baseline), counts(merged)
    (OUTPUT / "comparison.md").write_text(
        "# Gurobi retry, Tables 6–8\n\n"
        "90 lượt trên 45 đồ thị; mỗi đồ thị tính một lần trong mỗi cột. "
        "Kết quả CPLEX giữ nguyên.\n\n"
        "| Dữ liệu | Đồ thị đã chạy solver | Bandwidth hợp lệ nhỏ hơn đánh số ban đầu | Chứng minh tối ưu |\n"
        "|---|---:|---:|---:|\n"
        f"| Trước | {before[0]} | {before[1]} | {before[2]} |\n"
        f"| Sau | {after[0]} | {after[1]} | {after[2]} |\n\n"
        "runs_merged.csv: 1.243 khóa duy nhất. runs.csv ghi trạng thái Gurobi gốc, "
        "dấu mốc bắt đầu tối ưu và nguồn timeout.\n", encoding="utf-8")
    print(f"Merged 1,243 keys; CPLEX unchanged; before={before}; after={after}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run", "progress", "report"))
    action = parser.parse_args().action
    if action == "run":
        run()
    elif action == "report":
        report()
    else:
        selected, ordered, rows, _ = prepare()
        print(f"Completed {len(rows)}/{len(selected)} on {len({r['instance'] for r in rows})}/{len(ordered)} graphs")
        print("Status", dict(Counter(r["status"] for r in rows)))
        if rows:
            last = rows[-1]
            print("Latest", last["instance"], last["symmetry_breaking"], last["status"])


if __name__ == "__main__":
    main()
