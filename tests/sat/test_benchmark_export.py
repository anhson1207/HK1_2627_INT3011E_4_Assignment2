from __future__ import annotations

import csv
import json
from pathlib import Path

from bmp.solvers.sat.benchmark import BenchmarkRecord, export_csv, export_json


def test_benchmark_exports_preserve_status_and_certificate_fields(tmp_path: Path) -> None:
    record = BenchmarkRecord(
        instance="sample", n=4, m=3, density=0.5,
        encoding="order", amo="sequential", strategy="incremental",
        symmetry_breaking=False, status="TIMEOUT", bandwidth=2,
        lower_bound=1, upper_bound=2, runtime_s=1.0,
        encoding_time_s=0.1, solving_time_s=0.9,
        num_variables=40, num_clauses=80, sat_calls=2, valid=True,
    )
    csv_path = tmp_path / "runs.csv"
    json_path = tmp_path / "runs.json"
    export_csv([record], csv_path)
    export_json([record], json_path)
    with csv_path.open(newline="") as stream:
        csv_row = next(csv.DictReader(stream))
    json_row = json.loads(json_path.read_text())[0]
    assert csv_row["status"] == json_row["status"] == "TIMEOUT"
    assert int(csv_row["lower_bound"]) == json_row["lower_bound"] == 1
    assert int(csv_row["upper_bound"]) == json_row["upper_bound"] == 2
    assert csv_row["valid"] == "True" and json_row["valid"] is True
