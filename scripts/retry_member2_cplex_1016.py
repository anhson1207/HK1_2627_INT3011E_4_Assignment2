"""Run and report the Table 6-8 CPLEX rows that failed with error 1016."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

from bmp.core.bounds import identity_upper_bound
from bmp.experiments.member2_hb import FIELDS, identity, read_rows
from bmp.io.readers import read_graph


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "results/member2_hb_table6_7_8/runs.csv"
MANIFEST = ROOT / "data/hb_table6_7_8/manifest.csv"
GRAPHS = ROOT / "data/hb_table6_7_8/graphs"
OUTPUT = ROOT / "results/member2_cplex_retry_1016"
CONFIG = OUTPUT / "benchmark.toml"


def targets():
    original = read_rows(SOURCE)
    keys = [identity(row) for row in original]
    if len(original) != 1243 or len(set(keys)) != 1243:
        raise ValueError(f"Original table has {len(original)} rows and {len(set(keys))} unique keys")
    selected = [row for row in original if row["solver"] == "cplex"
                and row["status"] == "UNAVAILABLE" and "1016" in row["error"]]
    by_name = defaultdict(list)
    for row in selected:
        by_name[row["instance"]].append(row)
        if (row["encoding"], row["strategy"], row["amo"], row["repetition"],
                float(row["timeout_seconds"])) != ("", "", "", "1", 60.0):
            raise ValueError(f"Unexpected configuration: {identity(row)}")
    if any(sorted(row["symmetry_breaking"] for row in rows) != ["false", "true"]
           for rows in by_name.values()):
        raise ValueError("Target graph without exactly two symmetry configurations")
    print(f"Target rows: {len(selected)}; graphs: {len(by_name)}", flush=True)
    return original, selected, by_name


def prepare():
    _, selected, by_name = targets()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    manifest = [row for row in read_rows(MANIFEST) if row["instance"] in by_name]
    if len(manifest) != len(by_name):
        raise ValueError("Target graphs missing from manifest")
    with (OUTPUT / "manifest.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=manifest[0].keys())
        writer.writeheader()
        writer.writerows(manifest)
    CONFIG.write_text(
        "[benchmark]\n"
        'manifest = "manifest.csv"\n'
        'graph_dir = "../../data/hb_table6_7_8/graphs"\n'
        'output_dir = "."\n'
        "timeout_seconds = 60.0\n"
        "repetitions = 1\n"
        "max_sat_estimated_clauses = 2000000\n"
        "max_mip_variables = 250000\n"
        'amo = ["pairwise", "sequential", "binary", "commander"]\n'
        'solvers = ["cplex"]\n', encoding="utf-8")
    expected = {identity(row) for row in selected}
    if len(expected) != len(selected) or len(expected) != 2 * len(manifest):
        raise ValueError("Retry configuration would run a different key set")


def recorded():
    rows = read_rows(OUTPUT / "runs.csv") if (OUTPUT / "runs.csv").exists() else []
    keys = [identity(row) for row in rows]
    _, selected, _ = targets()
    expected = {identity(row) for row in selected}
    if len(set(keys)) != len(keys) or set(keys) - expected:
        raise ValueError("Retry CSV contains duplicate or unexpected keys")
    return rows, expected


def invoke(*extra):
    command = [sys.executable, "-m", "bmp.experiments.member2_hb", str(CONFIG), *extra]
    print("Running benchmark runner with", sys.executable.encode("ascii", "backslashreplace").decode("ascii"),
          "and", len(extra), "extra arguments", flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def check_ibm32():
    rows, _ = recorded()
    ibm = [row for row in rows if row["instance"] == "ibm32"]
    if len(ibm) != 2 or {row["symmetry_breaking"] for row in ibm} != {"false", "true"}:
        raise ValueError("Both ibm32 configurations have not been recorded")
    initial, _ = identity_upper_bound(read_graph(GRAPHS / "ibm32.edgelist"))
    for row in ibm:
        if (row["status"] not in {"TIMEOUT", "OPTIMAL"} or row["validation"] != "True"
                or row["incumbent_origin"] != "solver" or not row["assignment"]
                or not row["bandwidth"] or not row["best_bound"]
                or "1016" in row["error"]):
            raise ValueError(f"ibm32 did not pass CPLEX preflight: {row}")
        print("ibm32", row["symmetry_breaking"], "status", row["status"],
              "bandwidth", row["bandwidth"], "initial", initial,
              "bound", row["best_bound"], "validation", row["validation"], flush=True)


def report():
    original, selected, _ = targets()
    retry, expected = recorded()
    by_key = {identity(row): row for row in retry}
    if set(by_key) != expected:
        raise ValueError(f"Retry incomplete: {len(by_key)} / {len(expected)} rows")
    merged = [by_key.get(identity(row), row) for row in original]
    keys = [identity(row) for row in merged]
    if len(merged) != 1243 or len(set(keys)) != 1243:
        raise ValueError("Merged table does not contain 1,243 unique keys")
    with (OUTPUT / "runs_merged.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(merged)

    initial = {}
    def counts(rows):
        cplex = [row for row in rows if row["solver"] == "cplex"]
        running = {row["instance"] for row in cplex
                   if row["status"] in {"TIMEOUT", "OPTIMAL", "FEASIBLE", "INFEASIBLE"}}
        improved = set()
        optimal = set()
        for row in cplex:
            if row["validation"] != "True" or not row["bandwidth"]:
                continue
            name = row["instance"]
            if name not in initial:
                initial[name], _ = identity_upper_bound(read_graph(GRAPHS / f"{name}.edgelist"))
            if int(row["bandwidth"]) < initial[name] and row["incumbent_origin"] == "solver":
                improved.add(name)
            if row["status"] == "OPTIMAL":
                optimal.add(name)
        return (len(running), len(improved), len(optimal))

    before, after = counts(original), counts(merged)
    lines = ["# CPLEX 1016 retry, Tables 6-8", "",
             f"Retried {len(retry)} rows on {len({row['instance'] for row in retry})} graphs. "
             "Each graph is counted once per column.", "",
             "| Dataset | Graphs CPLEX ran | Graphs with valid bandwidth below identity start | Graphs proven optimal |",
             "|---|---:|---:|---:|",
             f"| Before | {before[0]} | {before[1]} | {before[2]} |",
             f"| After | {after[0]} | {after[1]} | {after[2]} |", "",
             "A run counts as executed when its CPLEX-derived status is TIMEOUT, OPTIMAL, "
             "FEASIBLE, or INFEASIBLE. solving_time_s is not used.", "",
             "Merged CSV: runs_merged.csv (1,243 unique keys).", ""]
    (OUTPUT / "comparison.md").write_text("\n".join(lines), encoding="utf-8")
    print("Before:", before, "After:", after, "merged keys:", len(set(keys)), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run", "report", "progress"))
    args = parser.parse_args()
    if args.action == "prepare":
        prepare()
    elif args.action == "run":
        prepare()
        invoke("--instance", "ibm32")
        check_ibm32()
        invoke()
        report()
    elif args.action == "report":
        report()
    else:
        rows, expected = recorded()
        print(f"Completed: {len(rows)} / {len(expected)}", flush=True)
        print("Status:", dict(Counter(row["status"] for row in rows)), flush=True)
        if rows:
            print("Latest:", rows[-1]["instance"], rows[-1]["symmetry_breaking"],
                  rows[-1]["status"], rows[-1]["bandwidth"], flush=True)


if __name__ == "__main__":
    main()
