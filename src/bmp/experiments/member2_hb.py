"""Resumable Member 2 benchmark for HB instances in Tables 6, 7, and 8."""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import tomllib
from collections import Counter
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


def read_rows(path):
    with path.open(newline="", encoding="utf-8") as source:
        return list(csv.DictReader(source))


def unique_instances(manifest):
    instances = {}
    for item in manifest:
        previous = instances.setdefault(item["instance"], item)
        if previous["n"] != item["n"]:
            raise ValueError(f"Conflicting n for repeated instance {item['instance']}")
    return instances


def expected_keys(instances, config, repetitions):
    keys = set()
    for name in instances:
        for solver, encoding, strategy, amo, symmetry in configurations(config):
            for repetition in range(1, repetitions + 1):
                keys.add((name, solver, encoding, strategy, amo,
                          str(symmetry).lower(), str(repetition)))
    return keys


def audit_legacy(rows, config, repetitions, legacy_manifest, graph_dir, timeout):
    """Reject duplicates, missing configurations, and invalid saved incumbents."""
    old_names = {row["instance"] for row in rows}
    references = unique_instances(legacy_manifest)
    unexpected_names = old_names - set(references)
    expected = expected_keys(references, config, repetitions)
    keys = [identity(row) for row in rows]
    duplicates = [key for key, count in Counter(keys).items() if count > 1]
    missing = expected - set(keys)
    unexpected = set(keys) - expected
    problems = []
    if unexpected_names:
        problems.append(f"Unknown legacy instances: {sorted(unexpected_names)}")
    if duplicates:
        problems.append(f"Duplicate legacy keys ({len(duplicates)}): {duplicates[:5]}")
    if missing:
        problems.append(f"Missing legacy keys ({len(missing)}): {sorted(missing)[:5]}")
    if unexpected:
        problems.append(f"Unexpected legacy configurations ({len(unexpected)}): {sorted(unexpected)[:5]}")
    graphs = {}
    for row in rows:
        name = row["instance"]
        if name not in references:
            continue
        if row["n"] != references[name]["n"] or row["table"] != references[name]["table"]:
            problems.append(f"Legacy n/table mismatch: {name}")
        if float(row["timeout_seconds"]) != timeout:
            problems.append(f"Legacy timeout mismatch: {name}")
        if row.get("assignment"):
            if name not in graphs:
                graphs[name] = read_graph(graph_dir / f"{name}.edgelist")
            assignment = {int(v): int(label) for v, label in json.loads(row["assignment"]).items()}
            report = validate_assignment(graphs[name], assignment,
                                         claimed_bandwidth=int(row["bandwidth"]) if row["bandwidth"] else None)
            if not report.valid and row["status"] != "ERROR":
                problems.append(f"Invalid legacy assignment: {name} {identity(row)}: {report.errors}")
    if problems:
        raise ValueError("Legacy runs cannot be reused:\n" + "\n".join(problems[:20]))
    return {"rows": len(rows), "unique_keys": len(set(keys)), "duplicates": len(duplicates),
            "missing": len(missing), "unexpected": len(unexpected), "instances": len(old_names)}


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
        def gurobi_stage(stage):
            temporary = progress_path.with_suffix(".tmp")
            temporary.write_text(json.dumps({"stage": stage}), encoding="utf-8")
            os.replace(temporary, progress_path)
        result = GurobiMIPSolver().solve(graph, timeout_seconds=max(0.0, timeout - 2.0),
                                         symmetry_breaking=symmetry, on_stage=gurobi_stage)
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
        "assignment": assignment, "incumbent_origin": result.metadata.get(
            "incumbent_origin", "solver" if assignment else ""),
        "runtime_total_s": monotonic() - started, "num_variables": result.num_variables,
        "num_clauses": result.num_clauses, "sat_calls": result.sat_calls,
        "encoding_time_s": result.encoding_time_s, "solving_time_s": result.solving_time_s,
        "error": "; ".join(report.errors) if report and not report.valid else result.metadata.get("reason", ""),
        "gurobi_started": solver == "gurobi" and result.metadata.get("gurobi_status") is not None,
        "gurobi_status": result.metadata.get("gurobi_status", ""),
    }), flush=True)


def run(config_path, selected=None, resume=True, preflight_only=False):
    config_path = config_path.resolve()
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))["benchmark"]
    config.setdefault("solvers", ["glucose", "gurobi", "cplex"])
    config.setdefault("amo", ["pairwise", "sequential", "binary", "commander"])
    if not resume and "reuse_runs" in config:
        raise ValueError("--rerun is incompatible with a reused benchmark; resume is the default")
    timeout = float(config["timeout_seconds"])
    repetitions = int(config["repetitions"])
    if timeout <= 0 or repetitions < 1:
        raise ValueError("timeout_seconds and repetitions must be positive")
    root = config_path.parent
    manifest = read_rows(root / config["manifest"])
    instances = unique_instances(manifest)
    if not manifest:
        raise ValueError("Manifest is empty")
    all_keys = expected_keys(instances, config, repetitions)
    legacy_rows = []
    legacy_audit = None
    if "reuse_runs" in config:
        previous_config = tomllib.loads((root / config["reuse_config"]).read_text(encoding="utf-8"))["benchmark"]
        comparable = ("timeout_seconds", "repetitions", "max_sat_estimated_clauses",
                      "max_mip_variables", "amo", "solvers")
        changed = [field for field in comparable if config[field] != previous_config[field]]
        if changed:
            raise ValueError(f"Cannot reuse legacy runs: changed settings {changed}")
        legacy_manifest = read_rows(root / config["reuse_manifest"])
        legacy_rows = read_rows(root / config["reuse_runs"])
        if not set(unique_instances(legacy_manifest)).issubset(instances):
            raise ValueError("Legacy instances are absent from the combined manifest")
        legacy_audit = audit_legacy(legacy_rows, config, repetitions, legacy_manifest,
                                    root / config["graph_dir"], timeout)
    output_dir = (root / config["output_dir"]).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "runs.csv"
    if legacy_rows and not output_path.exists():
        shutil.copyfile(root / config["reuse_runs"], output_path)
    existing = read_rows(output_path) if output_path.exists() else []
    existing_keys = [identity(row) for row in existing]
    duplicates = [key for key, count in Counter(existing_keys).items() if count > 1]
    unexpected = set(existing_keys) - all_keys
    if duplicates or unexpected:
        raise ValueError(f"Combined CSV has {len(duplicates)} duplicate and {len(unexpected)} unexpected keys")
    if legacy_rows:
        old_by_key = {identity(row): row for row in legacy_rows}
        new_by_key = {identity(row): row for row in existing}
        conflicting = [key for key, old in old_by_key.items()
                       if key in new_by_key and old != new_by_key[key]]
        if conflicting:
            raise ValueError(f"Combined CSV conflicts with original legacy rows: {conflicting[:5]}")
        missing_old = [row for row in legacy_rows if identity(row) not in new_by_key]
        if missing_old:
            with output_path.open("a", newline="", encoding="utf-8") as output:
                writer = csv.DictWriter(output, fieldnames=FIELDS)
                writer.writerows(missing_old)
            existing.extend(missing_old)
            existing_keys.extend(identity(row) for row in missing_old)
    preflight = {"reference_rows": len(manifest), "unique_instances": len(instances),
                 "configurations_per_instance": len(list(configurations(config))) * repetitions,
                 "expected_runs": len(all_keys), "legacy_runs_reused": len(legacy_rows),
                 "legacy_audit": legacy_audit, "runs_already_recorded": len(existing_keys),
                 "new_runs_remaining": len(all_keys - set(existing_keys))}
    (output_dir / "preflight.json").write_text(json.dumps(preflight, indent=2), encoding="utf-8")
    print(json.dumps(preflight, ensure_ascii=False), flush=True)
    if preflight_only:
        summarize(output_dir, manifest)
        return
    done = {identity(row) for row in existing} if resume else set()
    with output_path.open("a", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS)
        if not output_path.stat().st_size:
            writer.writeheader()
            output.flush()
        for item in instances.values():
            name = item["instance"]
            if selected and name not in selected:
                continue
            if all((name, solver, encoding, strategy, amo, str(symmetry).lower(), str(rep)) in done
                   for solver, encoding, strategy, amo, symmetry in configurations(config)
                   for rep in range(1, repetitions + 1)):
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
    rows = read_rows(output_dir / "runs.csv")
    by_name = {}
    for row in rows:
        if (row["validation"] != "True" or not row["bandwidth"] or
                row["status"] in ("UNAVAILABLE", "RESOURCE_LIMIT", "ERROR")):
            continue
        name = row["instance"]
        rank = (int(row["bandwidth"]), row["status"] != "OPTIMAL",
                float(row["runtime_total_s"]))
        previous = by_name.get(name)
        if previous is None or rank < (int(previous["bandwidth"]),
                                       previous["status"] != "OPTIMAL",
                                       float(previous["runtime_total_s"])):
            by_name[name] = row

    def relation(item):
        if item["Best"] in ("", "-", "—", "–"):
            return "missing_best"
        best_row = by_name.get(item["instance"])
        if best_row is None:
            return "no_solution"
        bw, best = int(best_row["bandwidth"]), int(item["Best"])
        return "equal" if bw == best else "better" if bw < best else "worse"

    def statistics(items):
        names = {item["instance"] for item in items}
        relevant = [row for row in rows if row["instance"] in names]
        counts = Counter(relation(item) for item in items)
        return {
            "reference_rows": len(items), "unique_instances": len(names),
            "runs_recorded": len(relevant),
            "optimal_runs": sum(row["status"] == "OPTIMAL" and row["validation"] == "True"
                                for row in relevant),
            "optimal_instances": len({row["instance"] for row in relevant
                                      if row["status"] == "OPTIMAL" and row["validation"] == "True"}),
            "timeout_runs": sum(row["status"] == "TIMEOUT" for row in relevant),
            "resource_limit_runs": sum(row["status"] == "RESOURCE_LIMIT" for row in relevant),
            "unavailable_runs": sum(row["status"] == "UNAVAILABLE" for row in relevant),
            "comparison": {category: counts[category] for category in
                           ("better", "equal", "worse", "no_solution", "missing_best")},
        }

    per_table = {str(table): statistics([item for item in manifest if item["table"] == str(table)])
                 for table in sorted({int(item["table"]) for item in manifest})}
    overall = statistics(list(unique_instances(manifest).values()))
    summary = {"tables": per_table, "overall": overall}
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    table_names = ", ".join(per_table)
    lines = [f"# Member 2 HB Tables {table_names}", "",
             "| Bảng | Instance | n | Best bài báo | DRSA | Bandwidth hợp lệ | Cấu hình đạt được | Thời gian (s) | Trạng thái | Đối chiếu Best |",
             "|---:|---|---:|---:|---:|---:|---|---:|---|---|"]
    for item in manifest:
        row = by_name.get(item["instance"])
        if row:
            config_label = (f"{row['solver']} / {row['encoding']} / {row['strategy']} / {row['amo']}"
                            if row["solver"] == "glucose" else
                            f"{row['solver']} / symmetry={row['symmetry_breaking']}")
        else:
            config_label = "—"
        cells = (item["table"], item["instance"], item["n"], item["Best"] or "—",
                 item["DRSA"] or "—", row["bandwidth"] if row else "—",
                 config_label, row["runtime_total_s"] if row else "—",
                 row["status"] if row else "—", relation(item))
        lines.append("| " + " | ".join(map(str, cells)) + " |")
    lines.extend(["", "Best trong bài báo là nghiệm tốt nhất đã biết; chỉ trạng thái OPTIMAL của solver mới chứng minh tối ưu.",
                  "Thời gian trong mỗi dòng là thời gian của đúng lượt chạy đã cho bandwidth hiển thị.", ""])
    for label, stats in [(f"Table {table}", values) for table, values in per_table.items()] + [("Toàn bộ (đồ thị duy nhất)", overall)]:
        c = stats["comparison"]
        lines.append(f"- {label}: {stats['reference_rows']} dòng tham chiếu, {stats['unique_instances']} đồ thị; "
                     f"{stats['runs_recorded']} lượt ghi, {stats['optimal_runs']} lượt OPTIMAL trên "
                     f"{stats['optimal_instances']} đồ thị; tốt hơn Best {c['better']}, bằng {c['equal']}, "
                     f"kém {c['worse']}, chưa có nghiệm {c['no_solution']}, thiếu Best {c['missing_best']}.")
    (output_dir / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", nargs="?", type=Path)
    parser.add_argument("--instance", action="append")
    parser.add_argument("--rerun", action="store_true")
    parser.add_argument("--report-only", action="store_true",
                        help="Refresh comparison.md from the CSV without solving")
    parser.add_argument("--preflight-only", action="store_true",
                        help="Audit/reuse saved rows and print counts without solving")
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
        run(args.config, set(args.instance) if args.instance else None,
            not args.rerun, args.preflight_only)
    else:
        parser.error("config is required")


if __name__ == "__main__":
    main()
