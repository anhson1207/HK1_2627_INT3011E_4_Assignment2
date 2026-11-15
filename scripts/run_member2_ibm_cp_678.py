"""Resume one IBM CP Optimizer run per HB Table 6/7/8 instance."""

import csv
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEMBER3 = ROOT.parent / "member3_ibm_cp_worktree"
sys.path.insert(0, str(MEMBER3 / "src"))

from bmp.core.validation import validate_assignment
from bmp.io.readers import read_graph
from bmp.solvers.exact.cp_optimizer import CPOptimizerSolver


FIELDS = (
    "instance", "table", "n", "edges", "solver", "timeout_seconds",
    "status", "runtime_seconds", "bandwidth", "initial_bandwidth",
    "validation", "backend_started", "native_status", "stop_cause", "reason",
)


def rows(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def main():
    if Path(sys.executable).resolve() != (ROOT / ".venv/Scripts/python.exe").resolve():
        raise RuntimeError("Run with Member 2 .venv/Scripts/python.exe")
    if not (MEMBER3 / "src/bmp/solvers/exact/cp_optimizer.py").is_file():
        raise RuntimeError("Member 3 worktree missing")
    executable = (ROOT / ".venv/Scripts/cpoptimizer.exe").resolve()
    if not executable.is_file():
        raise RuntimeError(f"Missing executable: {executable}")
    manifest = rows(ROOT / "data/hb_table6_7_8/manifest.csv")
    source = {r["instance"]: r for r in rows(ROOT / "data/hb_table6_7_8/sources.csv")}
    counts = Counter(r["table"] for r in manifest)
    names = [r["instance"] for r in manifest]
    if counts != {"6": 31, "7": 41, "8": 41} or len(names) != 113 or len(set(names)) != 113:
        raise ValueError(f"Unexpected manifest: {counts}, {len(set(names))} names")
    if set(names) != set(source):
        raise ValueError("Source and manifest names differ")
    graphs = {}
    for item in manifest:
        name = item["instance"]
        if name == "mbeause":
            if item["n"] != "492" or source[name]["status"] != "SIZE_MISMATCH":
                raise ValueError("mbeause source discrepancy changed")
            continue
        if source[name]["status"] != "VERIFIED":
            raise ValueError(f"{name}: source not verified")
        graph = read_graph(ROOT / "data/hb_table6_7_8/graphs" / f"{name}.edgelist")
        if graph.order != int(item["n"]) or graph.size != int(source[name]["edges"]):
            raise ValueError(f"{name}: graph size differs from manifest/source")
        if graph.vertices != tuple(range(1, graph.order + 1)):
            raise ValueError(f"{name}: vertex set does not preserve 1..n")
        graphs[name] = graph
    print(f"Preflight: {counts}; {len(graphs)} verified graphs; 113 unique names", flush=True)

    output = ROOT / "results/member2_ibm_cp_table6_7_8/runs.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    previous = rows(output) if output.exists() else []
    completed = [r["instance"] for r in previous]
    if len(completed) != len(set(completed)) or not set(completed) <= set(names):
        raise ValueError("Existing CSV contains duplicate or unexpected names")
    if previous and tuple(previous[0]) != FIELDS:
        raise ValueError("Existing CSV has unexpected columns")
    solver = CPOptimizerSolver(str(executable))
    with output.open("a", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        if not previous:
            writer.writeheader()
            stream.flush()
            os.fsync(stream.fileno())
        for index, item in enumerate(manifest, 1):
            name = item["instance"]
            if name in completed:
                continue
            record = dict(instance=name, table=item["table"], n=item["n"],
                          solver="cp-optimizer", timeout_seconds=2.0,
                          backend_started="unconfirmed")
            if name == "mbeause":
                record.update(status="NOT_RUN", reason="PDF n=492; source matrix n=496")
            else:
                graph = graphs[name]
                record["edges"] = graph.size
                record["initial_bandwidth"] = max(
                    (abs(u - v) for u, v in graph.edges), default=0
                )
                try:
                    result = solver.solve(graph, timeout_seconds=2.0)
                    record.update(status=result.status.value,
                                  runtime_seconds=result.runtime_seconds,
                                  bandwidth=result.bandwidth,
                                  native_status=result.metadata.get("native_status", ""),
                                  stop_cause=result.metadata.get("stop_cause", ""),
                                  reason=result.metadata.get("reason", ""))
                    if record["native_status"]:
                        record["backend_started"] = "confirmed"
                    if result.assignment is not None:
                        check = validate_assignment(
                            graph, result.assignment,
                            claimed_bandwidth=result.bandwidth,
                        )
                        record["validation"] = check.valid
                        if check.valid:
                            record["bandwidth"] = check.actual_bandwidth
                        else:
                            record.update(status="ERROR", reason="; ".join(check.errors))
                except Exception as exc:
                    record.update(status="ERROR", reason=f"{type(exc).__name__}: {exc}")
            writer.writerow(record)
            stream.flush()
            os.fsync(stream.fileno())
            print(f"[{index}/113] {name} table={item['table']} status={record['status']} "
                  f"bandwidth={record.get('bandwidth', '')} time={record.get('runtime_seconds', '')} "
                  f"reason={record.get('reason', '')}", flush=True)
    final = rows(output)
    if len(final) != 113 or len({r["instance"] for r in final}) != 113:
        raise ValueError("Final CSV does not contain 113 unique instances")
    print("Complete: 113 unique instances", flush=True)


if __name__ == "__main__":
    main()
