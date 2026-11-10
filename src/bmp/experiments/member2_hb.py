"""Resumable Member 2 benchmark for the 72 HB instances in Tables 6 and 7."""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path
from time import monotonic

from bmp.core.bounds import degree_lower_bound, identity_upper_bound
from bmp.core.validation import validate_assignment
from bmp.encodings.order import OrderEncoding
from bmp.encodings.pairwise import PairwiseEncoding
from bmp.io.readers import read_graph
from bmp.solvers.exact.cplex import CPLEXMIPSolver
from bmp.solvers.exact.gurobi import GurobiMIPSolver
from bmp.solvers.sat.incremental import IncrementalSATSolver
from bmp.solvers.sat.repeated import RepeatedSATSolver
from bmp.solvers.sat.search import compute_lower_bound

FIELDS = ("instance", "table", "n", "edges", "solver", "encoding", "strategy", "amo",
          "symmetry_breaking", "repetition", "timeout_seconds", "runtime_total_s",
          "status", "bandwidth", "best_bound", "validation", "assignment",
          "incumbent_origin", "num_variables", "num_clauses", "sat_calls",
          "encoding_time_s", "solving_time_s", "error")


def configurations(config):
    if "glucose" in config["solvers"]:
        for encoding in ("pairwise", "order"):
            for strategy in ("repeated", "incremental"):
                yield ("glucose", encoding, strategy, "pairwise", False)
        for amo in config["amo"]:
            if amo != "pairwise":
                yield ("glucose", "pairwise", "repeated", amo, False)
    for solver in ("gurobi", "cplex"):
        if solver in config["solvers"]:
            for symmetry in (False, True):
                yield (solver, "", "", "", symmetry)


def identity(row):
    return (row["instance"], row["solver"], row["encoding"], row["strategy"],
            row["amo"], str(row["symmetry_breaking"]).lower(), str(row["repetition"]))


def estimate_sat_clauses(graph, encoding, amo, lb):
    n, m = graph.order, graph.size
    if encoding == "order":
        fixed = n * (n - 1) // 2 + 4 * n * n
        return fixed + 2 * m * max(0, n - lb - 1)
    if amo == "pairwise":
        fixed = n * n * (n - 1)
    elif amo == "sequential":
        fixed = 6 * n * n
    else:
        fixed = 10 * n * n
    return fixed + m * max(0, n - lb - 1) * max(0, n - lb)


def worker(graph_path, solver, encoding, strategy, amo, symmetry, timeout, progress_path):
    graph = read_graph(graph_path)
    started = monotonic()
    def checkpoint(assignment, bandwidth):
        data = json.dumps({"assignment": dict(assignment), "bandwidth": bandwidth})
        temporary = progress_path.with_suffix(".tmp")
        temporary.write_text(data, encoding="utf-8")
        os.replace(temporary, progress_path)
    if solver == "glucose":
        encoder = PairwiseEncoding(amo) if encoding == "pairwise" else OrderEncoding(amo)
        engine = (RepeatedSATSolver(encoder, backend_name="glucose") if strategy == "repeated"
                  else IncrementalSATSolver(encoder, backend_name="glucose"))
        result = engine.solve(graph, timeout_seconds=timeout, on_incumbent=checkpoint)
    elif solver == "gurobi":
        result = GurobiMIPSolver().solve(graph, timeout_seconds=max(0.0, timeout - 2.0),
                                         symmetry_breaking=symmetry)
    else:
        result = CPLEXMIPSolver().solve(graph, timeout_seconds=max(0.0, timeout - 2.0),
                                        symmetry_breaking=symmetry)
    assignment = dict(result.assignment) if result.assignment is not None else None
    report = validate_assignment(graph, assignment, claimed_bandwidth=result.bandwidth) if assignment else None
    status = result.status.value
    if status == "FEASIBLE":
        status = "TIMEOUT"  # The SAT engines use FEASIBLE for their soft timeout.
    if report is not None and not report.valid:
        status = "ERROR"
    print(json.dumps({
        "status": status, "bandwidth": report.actual_bandwidth if report and report.valid else None,
        "best_bound": result.lower_bound, "validation": report.valid if report else None,
        "assignment": assignment, "incumbent_origin": "solver" if assignment else "",
        "runtime_total_s": monotonic() - started, "num_variables": result.num_variables,
        "num_clauses": result.num_clauses, "sat_calls": result.sat_calls,
        "encoding_time_s": result.encoding_time_s, "solving_time_s": result.solving_time_s,
        "error": "; ".join(report.errors) if report and not report.valid else result.metadata.get("reason", ""),
    }), flush=True)


def run(config_path, selected=None, resume=True):
    config_path = config_path.resolve()
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))["benchmark"]
    config.setdefault("solvers", ["glucose", "gurobi", "cplex"])
    config.setdefault("amo", ["pairwise", "sequential", "binary", "commander"])
    timeout = float(config["timeout_seconds"])
    repetitions = int(config["repetitions"])
    if timeout <= 0 or repetitions < 1:
        raise ValueError("timeout_seconds and repetitions must be positive")
    root = config_path.parent
    with (root / config["manifest"]).open(newline="", encoding="utf-8") as source:
        manifest = list(csv.DictReader(source))
    if len(manifest) != 72 or len({item["instance"] for item in manifest}) != 72:
        raise ValueError("Manifest must contain the 72 unique Table 6/7 instances")
    output_dir = (root / config["output_dir"]).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "runs.csv"
    existing = []
    if output_path.exists():
        with output_path.open(newline="", encoding="utf-8") as source:
            existing = list(csv.DictReader(source))
    done = {identity(row) for row in existing} if resume else set()
    with output_path.open("a", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS)
        if not output_path.stat().st_size:
            writer.writeheader()
            output.flush()
        for item in manifest:
            name = item["instance"]
            if selected and name not in selected:
                continue
            graph_path = root / config["graph_dir"] / f"{name}.edgelist"
            graph = read_graph(graph_path) if graph_path.exists() else None
            if graph and graph.order != int(item["n"]):
                graph = None
            lb = compute_lower_bound(graph) if graph and "glucose" in config["solvers"] else None
            for solver, encoding, strategy, amo, symmetry in configurations(config):
                for repetition in range(1, repetitions + 1):
                    row = dict.fromkeys(FIELDS, "")
                    row.update(instance=name, table=item["table"], n=item["n"],
                               edges=graph.size if graph else "", solver=solver,
                               encoding=encoding, strategy=strategy, amo=amo,
                               symmetry_breaking=str(symmetry).lower(), repetition=repetition,
                               timeout_seconds=timeout)
                    if identity(row) in done:
                        continue
                    started = monotonic()
                    if graph is None:
                        result = {"status": "UNAVAILABLE", "error": "Graph missing or n differs from PDF"}
                    elif solver == "glucose" and (estimate := estimate_sat_clauses(graph, encoding, amo, lb)) > int(config["max_sat_estimated_clauses"]):
                        result = {"status": "RESOURCE_LIMIT", "error": f"Estimated CNF clauses {estimate} exceed configured cap {config['max_sat_estimated_clauses']}"}
                    elif solver in ("gurobi", "cplex") and graph.order ** 2 > int(config["max_mip_variables"]):
                        result = {"status": "RESOURCE_LIMIT", "error": f"MIP binary variables {graph.order ** 2} exceed configured cap {config['max_mip_variables']}"}
                    else:
                        progress_path = output_dir / "sat_incumbent.json"
                        progress_path.unlink(missing_ok=True)
                        args = [sys.executable, "-m", "bmp.experiments.member2_hb", "--worker",
                                str(graph_path), solver, encoding or "-", strategy or "-", amo or "-",
                                str(symmetry).lower(), str(timeout), str(progress_path)]
                        try:
                            completed = subprocess.run(args, capture_output=True, text=True,
                                                       timeout=timeout, check=False)
                            if completed.returncode:
                                result = {"status": "ERROR", "error": completed.stderr[-2000:] or completed.stdout[-2000:]}
                            else:
                                result = json.loads(completed.stdout.strip().splitlines()[-1])
                        except subprocess.TimeoutExpired:
                            checkpoint = json.loads(progress_path.read_text(encoding="utf-8")) if progress_path.exists() else None
                            assignment = ({int(v): int(p) for v, p in checkpoint["assignment"].items()}
                                          if checkpoint else identity_upper_bound(graph)[1])
                            report = validate_assignment(graph, assignment)
                            result = {"status": "TIMEOUT", "bandwidth": report.actual_bandwidth,
                                      "best_bound": degree_lower_bound(graph), "validation": report.valid,
                                      "assignment": assignment,
                                      "incumbent_origin": "sat_checkpoint" if checkpoint else "identity_start",
                                      "error": "Hard wall timeout; preserved last recorded valid incumbent"}
                        except (ValueError, IndexError) as exc:
                            result = {"status": "ERROR", "error": f"Worker output error: {exc}"}
                    assignment = result.pop("assignment", None)
                    if assignment is not None and graph is not None:
                        assignment = {int(v): int(p) for v, p in assignment.items()}
                        report = validate_assignment(graph, assignment, claimed_bandwidth=result.get("bandwidth"))
                        result["validation"] = report.valid
                        result["bandwidth"] = report.actual_bandwidth
                        if not report.valid:
                            result["status"] = "ERROR"
                            result["error"] = "; ".join(report.errors)
                    row.update(result)
                    row["assignment"] = json.dumps(assignment, sort_keys=True) if assignment else ""
                    row["runtime_total_s"] = monotonic() - started
                    writer.writerow(row)
                    output.flush()
                    os.fsync(output.fileno())
                    done.add(identity(row))
                    print(f"{name} {solver} {encoding} {strategy} {amo} sym={symmetry}: {row['status']} bw={row['bandwidth']} {row['runtime_total_s']:.2f}s", flush=True)
    summarize(output_dir, manifest)


def summarize(output_dir, manifest):
    with (output_dir / "runs.csv").open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))
    by_name = {}
    for row in rows:
        if row["validation"] != "True" or not row["bandwidth"] or row["status"] in ("UNAVAILABLE", "RESOURCE_LIMIT", "ERROR"):
            continue
        name = row["instance"]
        if (name not in by_name or
                (int(row["bandwidth"]), row["status"] != "OPTIMAL", float(row["runtime_total_s"])) <
                (int(by_name[name]["bandwidth"]), by_name[name]["status"] != "OPTIMAL",
                 float(by_name[name]["runtime_total_s"]))):
            by_name[name] = row
    report = []
    counts = {key: 0 for key in ("equal", "better", "worse", "no_solution")}
    for item in manifest:
        name = item["instance"]
        row = by_name.get(name)
        if row is None:
            relation = "no_solution"
        else:
            bw, best = int(row["bandwidth"]), int(item["Best"])
            relation = "equal" if bw == best else "better" if bw < best else "worse"
        counts[relation] += 1
        report.append((name, item["Best"], row["bandwidth"] if row else "—",
                       row["solver"] if row else "—", row["runtime_total_s"] if row else "—",
                       row["status"] if row else "—", relation))
    lines = ["# Member 2 HB Tables 6–7", "", "| Đồ thị | Best bài báo | Bandwidth của mình | Solver | Thời gian (s) | Trạng thái | Đối chiếu |",
             "|---|---:|---:|---|---:|---|---|"]
    lines += ["| " + " | ".join(map(str, entry)) + " |" for entry in report]
    attempted = {row["instance"] for row in rows if row["status"] not in ("RESOURCE_LIMIT", "UNAVAILABLE")}
    optimal = {row["instance"] for row in rows if row["status"] == "OPTIMAL" and row["validation"] == "True"}
    timeout_cases = {row["instance"] for row in rows if row["status"] == "TIMEOUT"}
    resource_cases = {row["instance"] for row in rows if row["status"] in ("RESOURCE_LIMIT", "UNAVAILABLE")}
    lines += ["", f"Bằng Best: {counts['equal']}; tốt hơn: {counts['better']}; kém hơn: {counts['worse']}; chưa có nghiệm: {counts['no_solution']}.",
              f"Đồ thị có ít nhất một lượt giải: {len(attempted)}/72; đồ thị đạt tối ưu: {len(optimal)}; đồ thị có timeout: {len(timeout_cases)}; đồ thị có giới hạn tài nguyên/license: {len(resource_cases)}.",
              f"Tổng lượt: {len(rows)}; OPTIMAL: {sum(row['status'] == 'OPTIMAL' for row in rows)}; TIMEOUT: {sum(row['status'] == 'TIMEOUT' for row in rows)}; RESOURCE_LIMIT: {sum(row['status'] == 'RESOURCE_LIMIT' for row in rows)}; UNAVAILABLE: {sum(row['status'] == 'UNAVAILABLE' for row in rows)}."]
    (output_dir / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", nargs="?", type=Path)
    parser.add_argument("--instance", action="append")
    parser.add_argument("--rerun", action="store_true")
    parser.add_argument("--report-only", action="store_true",
                        help="Refresh comparison.md from the CSV without solving")
    parser.add_argument("--worker", nargs=8, metavar=("GRAPH", "SOLVER", "ENCODING", "STRATEGY", "AMO", "SYMMETRY", "TIMEOUT", "PROGRESS"))
    args = parser.parse_args()
    if args.worker:
        graph, solver, encoding, strategy, amo, symmetry, timeout, progress = args.worker
        worker(Path(graph), solver, encoding, strategy, amo, symmetry == "true", float(timeout), Path(progress))
    elif args.config and args.report_only:
        config_path = args.config.resolve()
        config = tomllib.loads(config_path.read_text(encoding="utf-8"))["benchmark"]
        with (config_path.parent / config["manifest"]).open(newline="", encoding="utf-8") as source:
            manifest = list(csv.DictReader(source))
        summarize((config_path.parent / config["output_dir"]).resolve(), manifest)
    elif args.config:
        run(args.config, set(args.instance) if args.instance else None, not args.rerun)
    else:
        parser.error("config is required")


if __name__ == "__main__":
    main()
