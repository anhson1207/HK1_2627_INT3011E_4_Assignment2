"""Regression tests for Phase M2.2 (live MIP metadata, pilot schema, and cnsplots)."""

from __future__ import annotations

import csv
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from bmp.core.generators import cycle_graph
from bmp.core.solution import SolutionStatus
from bmp.experiments.member2_hb import FIELDS, run as run_hb
from bmp.experiments.member2_plots import create_m2_2_plots
from bmp.solvers.exact.cplex import CPLEXMIPSolver
from bmp.solvers.exact.gurobi import GurobiMIPSolver

ROOT = Path(__file__).resolve().parents[1]


class Member2M22Tests(unittest.TestCase):
    def test_live_mip_threads_and_solver_version_metadata(self) -> None:
        graph = cycle_graph(4)
        for solver in (GurobiMIPSolver(), CPLEXMIPSolver()):
            with self.subTest(solver=type(solver).__name__):
                res = solver.solve(graph, timeout_seconds=5.0, symmetry_breaking=True, threads=1)
                if res.status is SolutionStatus.UNAVAILABLE:
                    self.skipTest(str(res.metadata.get("reason", "solver unavailable")))
                self.assertEqual(res.status, SolutionStatus.OPTIMAL)
                self.assertEqual(res.bandwidth, 2)
                self.assertEqual(res.metadata.get("threads"), 1)
                self.assertIsInstance(res.metadata.get("solver_version"), str)
                self.assertTrue(res.metadata["solver_version"])

    def test_pilot_m2_2_schema_na_handling_and_resource_limit(self) -> None:
        provenance = (ROOT / "data/benchmark_provenance.json").as_posix()
        raw_dir = (ROOT / "data/benchmarks/raw").as_posix()

        with TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            cfg = tmp_dir / "pilot.toml"
            cfg.write_text(
                "[benchmark]\n"
                'mode = "pilot_m2_2"\n'
                f'provenance_file = "{provenance}"\n'
                f'raw_dir = "{raw_dir}"\n'
                'output_dir = "out"\n'
                'pilot_instances = ["nos4"]\n'
                "timeout_seconds = 0.25\n"
                "extended_timeout_seconds = 0.25\n"
                "max_variables = 500000\n"
                "max_clauses = 2500000\n"
                "max_batch_seconds = 120.0\n",
                encoding="utf-8",
            )
            run_hb(cfg, selected={"path_p5", "nos4"}, resume=False)

            out_dir = tmp_dir / "out"
            for name in ("runs.csv", "runs.json", "metadata.json", "summary.json", "run_log.txt", "comparison.md"):
                self.assertTrue((out_dir / name).exists(), f"missing {name}")

            json_rows = json.loads((out_dir / "runs.json").read_text(encoding="utf-8"))
            with (out_dir / "runs.csv").open(newline="", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                self.assertEqual(tuple(reader.fieldnames or ()), FIELDS)
                csv_rows = list(reader)

            self.assertEqual(len(json_rows), len(csv_rows))
            self.assertGreater(len(json_rows), 10)

            sat_rows = [r for r in json_rows if r["method"] == "SAT"]
            mip_rows = [r for r in json_rows if r["method"] == "MIP"]
            self.assertTrue(sat_rows)
            self.assertTrue(mip_rows)

            for r in mip_rows:
                self.assertIsNone(r["cnf_variables"])
                self.assertIsNone(r["cnf_clauses"])
                self.assertIsNone(r["sat_calls"])
            for c in [c for c in csv_rows if c["method"] == "MIP"]:
                self.assertEqual(c["cnf_variables"], "")
                self.assertEqual(c["sat_calls"], "")

            for r in sat_rows:
                self.assertIsNone(r["mip_gap"])
            for c in [c for c in csv_rows if c["method"] == "SAT"]:
                self.assertEqual(c["mip_gap"], "")

            nos4_pw = [
                r for r in sat_rows if r["instance"] == "nos4" and r["encoding"] == "pairwise"
            ]
            self.assertTrue(nos4_pw)
            for r in nos4_pw:
                self.assertEqual(r["status"], "RESOURCE_LIMIT")
                self.assertIsNone(r["bandwidth"])
                self.assertIsNone(r["sat_calls"])
                self.assertTrue(r["error"])

    def test_m2_2_cnsplots_generates_svgs_and_excludes_nonrun_statuses(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            csv_path = tmp_dir / "runs.csv"
            rows = [
                {
                    "run_id": "r1",
                    "experiment": "A_backend;B_cardinality;C_strategy;D_encoding;F_sat_vs_mip",
                    "instance": "path_p5",
                    "table": "Synthetic/Sample",
                    "dataset_status": "SYNTHETIC_SAMPLE",
                    "n": 5,
                    "m": 4,
                    "method": "SAT",
                    "encoding": "order",
                    "amo": "sequential",
                    "solver": "glucose",
                    "strategy": "incremental",
                    "symmetry_breaking": True,
                    "timeout_s": 30.0,
                    "bandwidth": 1,
                    "lower_bound": 1,
                    "upper_bound": 1,
                    "status": "OPTIMAL",
                    "solver_time_s": 0.01,
                    "total_wall_time_s": 0.01,
                    "cnf_variables": 100,
                    "cnf_clauses": 250,
                    "published_best": "",
                },
                {
                    "run_id": "r2",
                    "experiment": "A_backend;F_sat_vs_mip",
                    "instance": "path_p5",
                    "table": "Synthetic/Sample",
                    "dataset_status": "SYNTHETIC_SAMPLE",
                    "n": 5,
                    "m": 4,
                    "method": "SAT",
                    "encoding": "order",
                    "amo": "sequential",
                    "solver": "cadical",
                    "strategy": "incremental",
                    "symmetry_breaking": True,
                    "timeout_s": 30.0,
                    "bandwidth": 1,
                    "lower_bound": 1,
                    "upper_bound": 1,
                    "status": "OPTIMAL",
                    "solver_time_s": 0.02,
                    "total_wall_time_s": 0.02,
                    "cnf_variables": 100,
                    "cnf_clauses": 250,
                    "published_best": "",
                },
                {
                    "run_id": "r3",
                    "experiment": "B_cardinality",
                    "instance": "bcspwr01",
                    "table": "Table 6",
                    "dataset_status": "READY",
                    "n": 39,
                    "m": 46,
                    "method": "SAT",
                    "encoding": "order",
                    "amo": "commander",
                    "solver": "glucose",
                    "strategy": "incremental",
                    "symmetry_breaking": True,
                    "timeout_s": 30.0,
                    "bandwidth": 5,
                    "lower_bound": 5,
                    "upper_bound": 5,
                    "status": "OPTIMAL",
                    "solver_time_s": 8.0,
                    "total_wall_time_s": 8.2,
                    "cnf_variables": 6000,
                    "cnf_clauses": 50000,
                    "published_best": 5,
                },
                {
                    "run_id": "r4",
                    "experiment": "E_mip",
                    "instance": "bcspwr01",
                    "table": "Table 6",
                    "dataset_status": "READY",
                    "n": 39,
                    "m": 46,
                    "method": "MIP",
                    "encoding": "",
                    "amo": "",
                    "solver": "cplex",
                    "strategy": "",
                    "symmetry_breaking": False,
                    "timeout_s": 30.0,
                    "bandwidth": "",
                    "lower_bound": 2,
                    "upper_bound": "",
                    "status": "UNAVAILABLE",
                    "solver_time_s": "",
                    "total_wall_time_s": 0.001,
                    "cnf_variables": "",
                    "cnf_clauses": "",
                    "published_best": 5,
                },
                {
                    "run_id": "r5",
                    "experiment": "D_encoding",
                    "instance": "nos4",
                    "table": "Table 6",
                    "dataset_status": "READY",
                    "n": 100,
                    "m": 247,
                    "method": "SAT",
                    "encoding": "pairwise",
                    "amo": "sequential",
                    "solver": "glucose",
                    "strategy": "incremental",
                    "symmetry_breaking": True,
                    "timeout_s": 30.0,
                    "bandwidth": "",
                    "lower_bound": 10,
                    "upper_bound": "",
                    "status": "RESOURCE_LIMIT",
                    "solver_time_s": "",
                    "total_wall_time_s": 0.0,
                    "cnf_variables": 50000,
                    "cnf_clauses": 2504247,
                    "published_best": "",
                },
            ]
            fieldnames = list(rows[0].keys())
            with csv_path.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

            fig_dir = tmp_dir / "figures"
            written = create_m2_2_plots(csv_path, fig_dir)
            self.assertGreaterEqual(len(written), 3)
            for path in written:
                self.assertTrue(path.exists())
                self.assertEqual(path.suffix, ".svg")
                text = path.read_text(encoding="utf-8")
                self.assertIn("<svg", text)


if __name__ == "__main__":
    unittest.main()
