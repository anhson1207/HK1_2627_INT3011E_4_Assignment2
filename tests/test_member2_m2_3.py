"""Regression tests for Phase M2.3 (54-preflight schema, license guard, resume merging, cnsplots)."""

from __future__ import annotations

import csv
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from bmp.experiments.member2_m2_3 import (
    M2_3_FIELDS,
    PREFLIGHT_FIELDS,
    _proof_comparison_tag,
    detect_commercial_licenses,
    export_preflight_54,
    run_m2_3,
)
from bmp.experiments.member2_m2_3_plots import create_m2_3_plots

ROOT = Path(__file__).resolve().parents[1]


class Member2M23Tests(unittest.TestCase):
    def test_detect_commercial_licenses_and_proof_comparison_tags(self) -> None:
        lic = detect_commercial_licenses()
        self.assertIn("gurobi", lic)
        self.assertIn("cplex", lic)
        self.assertIn(lic["gurobi"]["license_type"], {"SIZE_LIMITED_EVAL", "FULL_OR_UNRESTRICTED", "PACKAGE_MISSING", "LICENSE_INVALID"})
        self.assertIn(lic["cplex"]["license_type"], {"COMMUNITY_EDITION", "FULL_OR_UNRESTRICTED", "PACKAGE_MISSING", "LICENSE_INVALID"})

        self.assertEqual(
            _proof_comparison_tag(status="OPTIMAL", bandwidth=5, pub_best=5, dataset_status="READY"),
            "PROVED_MATCHED_BEST",
        )
        self.assertEqual(
            _proof_comparison_tag(status="TIMEOUT", bandwidth=5, pub_best=5, dataset_status="READY"),
            "UNPROVED_MATCHED_BEST",
        )
        self.assertEqual(
            _proof_comparison_tag(status="UNAVAILABLE", bandwidth=None, pub_best=5, dataset_status="READY"),
            "N/A",
        )

    def test_preflight_subset_runner_license_guard_and_tag_merge(self) -> None:
        full_prov = json.loads((ROOT / "data/benchmark_provenance.json").read_text(encoding="utf-8"))
        subset_names = {"bcspwr01", "nos4", "plat362"}
        subset_prov = [row for row in full_prov if row["instance"] in subset_names]
        raw_dir = ROOT / "data/benchmarks/raw"

        with TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            prov_path = tmp_dir / "provenance.json"
            prov_path.write_text(json.dumps(subset_prov), encoding="utf-8")
            out_dir = tmp_dir / "out"

            records = export_preflight_54(
                provenance_path=prov_path,
                raw_dir=raw_dir,
                output_dir=out_dir,
                max_sat_vars=500_000,
                max_sat_clauses=2_500_000,
            )
            self.assertEqual(len(records), 3)
            with (out_dir / "preflight_54.csv").open(newline="", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                self.assertEqual(tuple(reader.fieldnames or ()), PREFLIGHT_FIELDS)
                pf_rows = {r["instance"]: r for r in reader}

            self.assertEqual(pf_rows["bcspwr01"]["dataset_ready"], "True")
            self.assertEqual(pf_rows["bcspwr01"]["eligibility_sat"], "True")
            self.assertEqual(pf_rows["bcspwr01"]["eligibility_pairwise_sat"], "True")
            self.assertEqual(pf_rows["nos4"]["eligibility_sat"], "True")
            self.assertEqual(pf_rows["nos4"]["eligibility_pairwise_sat"], "False")
            self.assertEqual(pf_rows["plat362"]["eligibility_sat"], "False")

            # Baseline run (blocked plat362 by RESOURCE_LIMIT, bounded nos4)
            cfg = tmp_dir / "studies.toml"
            cfg.write_text(
                "[benchmark]\n"
                'mode = "m2_3_studies"\n'
                f'provenance = "{prov_path.as_posix()}"\n'
                f'raw_dir = "{raw_dir.as_posix()}"\n'
                'output_dir = "out"\n'
                "timeout_seconds = 0.25\n"
                "study_timeout_seconds = 0.25\n"
                "study_repetitions = 1\n"
                "variance_repetitions = 1\n"
                "repeat_small_mip = false\n"
                'representative_instances = ["nos4"]\n'
                'pairwise_instances = ["nos4"]\n'
                "max_batch_seconds = 120.0\n",
                encoding="utf-8",
            )
            run_m2_3(cfg, selected={"path_p5", "nos4"}, resume=False)
            rows1 = json.loads((out_dir / "runs.json").read_text(encoding="utf-8"))
            count1 = len(rows1)
            self.assertGreater(count1, 10)

            # Re-running with resume=True must preserve exact row count and schema
            run_m2_3(cfg, selected={"path_p5", "nos4"}, resume=True)
            rows2 = json.loads((out_dir / "runs.json").read_text(encoding="utf-8"))
            self.assertEqual(len(rows2), count1)

            with (out_dir / "runs.csv").open(newline="", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                self.assertEqual(tuple(reader.fieldnames or ()), M2_3_FIELDS)

            nos4_pw = [r for r in rows2 if r["instance"] == "nos4" and r["encoding"] == "pairwise"]
            self.assertTrue(nos4_pw)
            self.assertEqual(nos4_pw[0]["status"], "RESOURCE_LIMIT")
            self.assertIsNone(nos4_pw[0]["bandwidth"])

            nos4_cplex = [r for r in rows2 if r["instance"] == "nos4" and r["solver"] == "cplex"]
            self.assertTrue(nos4_cplex)
            self.assertEqual(nos4_cplex[0]["status"], "UNAVAILABLE")
            self.assertEqual(nos4_cplex[0]["license_status"], "BLOCKED_LICENSE")

            self.assertTrue((out_dir / "baseline_summary.json").exists())
            self.assertTrue((out_dir / "summary.json").exists())
            self.assertTrue((out_dir / "metadata.json").exists())

    def test_m2_3_cnsplots_suite_generates_valid_svgs(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            csv_path = tmp_dir / "runs.csv"
            pf_path = tmp_dir / "preflight_54.csv"

            with pf_path.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=["instance", "table", "n", "m", "order_cnf_clauses", "pairwise_cnf_clauses"])
                writer.writeheader()
                writer.writerow({"instance": "bcspwr01", "table": "Table 6", "n": 39, "m": 46, "order_cnf_clauses": 13832, "pairwise_cnf_clauses": 77044})
                writer.writerow({"instance": "nos1", "table": "Table 8", "n": 237, "m": 390, "order_cnf_clauses": 575368, "pairwise_cnf_clauses": 22148953})
                writer.writerow({"instance": "dwt_992", "table": "Table 7", "n": 992, "m": 7876, "order_cnf_clauses": 22490745, "pairwise_cnf_clauses": 7748573008})

            sample_rows = [
                {
                    "run_id": "r1",
                    "experiment": "Baseline_54;Study_A_encoding;Study_C_backend;Study_D_strategy;Study_E_symmetry;Study_G_sat_vs_mip",
                    "instance": "bcspwr01",
                    "table": "Table 6",
                    "dataset_status": "READY",
                    "n": 39,
                    "m": 46,
                    "method": "SAT",
                    "encoding": "order",
                    "amo": "sequential",
                    "solver": "cadical",
                    "strategy": "incremental",
                    "symmetry_breaking": True,
                    "timeout_s": 30.0,
                    "bandwidth": 5,
                    "published_best": 5,
                    "status": "OPTIMAL",
                    "total_wall_time_s": 7.78,
                    "cnf_variables": 4485,
                    "cnf_clauses": 22296,
                },
                {
                    "run_id": "r2",
                    "experiment": "Study_A_encoding",
                    "instance": "bcspwr01",
                    "table": "Table 6",
                    "dataset_status": "READY",
                    "n": 39,
                    "m": 46,
                    "method": "SAT",
                    "encoding": "pairwise",
                    "amo": "sequential",
                    "solver": "cadical",
                    "strategy": "incremental",
                    "symmetry_breaking": True,
                    "timeout_s": 30.0,
                    "bandwidth": 5,
                    "published_best": 5,
                    "status": "TIMEOUT",
                    "total_wall_time_s": 30.0,
                    "cnf_variables": 4485,
                    "cnf_clauses": 60484,
                },
                {
                    "run_id": "r3",
                    "experiment": "Study_B_cardinality;Study_C_backend",
                    "instance": "bcspwr01",
                    "table": "Table 6",
                    "dataset_status": "READY",
                    "n": 39,
                    "m": 46,
                    "method": "SAT",
                    "encoding": "order",
                    "amo": "sequential",
                    "solver": "glucose",
                    "strategy": "incremental",
                    "symmetry_breaking": True,
                    "timeout_s": 30.0,
                    "bandwidth": 5,
                    "published_best": 5,
                    "status": "OPTIMAL",
                    "total_wall_time_s": 7.32,
                    "cnf_variables": 4485,
                    "cnf_clauses": 22296,
                },
                {
                    "run_id": "r4",
                    "experiment": "Study_D_strategy",
                    "instance": "bcspwr01",
                    "table": "Table 6",
                    "dataset_status": "READY",
                    "n": 39,
                    "m": 46,
                    "method": "SAT",
                    "encoding": "order",
                    "amo": "sequential",
                    "solver": "cadical",
                    "strategy": "repeated",
                    "symmetry_breaking": True,
                    "timeout_s": 30.0,
                    "bandwidth": 5,
                    "published_best": 5,
                    "status": "OPTIMAL",
                    "total_wall_time_s": 6.92,
                    "cnf_variables": 4485,
                    "cnf_clauses": 13464,
                },
                {
                    "run_id": "r5",
                    "experiment": "Study_F_mip;Study_G_sat_vs_mip",
                    "instance": "bcspwr01",
                    "table": "Table 6",
                    "dataset_status": "READY",
                    "n": 39,
                    "m": 46,
                    "method": "MIP",
                    "encoding": "",
                    "amo": "",
                    "solver": "gurobi",
                    "strategy": "",
                    "symmetry_breaking": True,
                    "timeout_s": 30.0,
                    "bandwidth": 5,
                    "published_best": 5,
                    "status": "OPTIMAL",
                    "total_wall_time_s": 3.40,
                    "cnf_variables": "",
                    "cnf_clauses": "",
                },
                {
                    "run_id": "r6",
                    "experiment": "Study_F_mip;Study_G_sat_vs_mip",
                    "instance": "path_p5",
                    "table": "Synthetic/Sample",
                    "dataset_status": "SYNTHETIC_SAMPLE",
                    "n": 5,
                    "m": 4,
                    "method": "MIP",
                    "encoding": "",
                    "amo": "",
                    "solver": "cplex",
                    "strategy": "",
                    "symmetry_breaking": True,
                    "timeout_s": 30.0,
                    "bandwidth": 1,
                    "published_best": 1,
                    "status": "OPTIMAL",
                    "total_wall_time_s": 0.002,
                    "cnf_variables": "",
                    "cnf_clauses": "",
                },
                {
                    "run_id": "r7",
                    "experiment": "Baseline_54",
                    "instance": "dwt_992",
                    "table": "Table 7",
                    "dataset_status": "READY",
                    "n": 992,
                    "m": 7876,
                    "method": "SAT",
                    "encoding": "order",
                    "amo": "sequential",
                    "solver": "cadical",
                    "strategy": "incremental",
                    "symmetry_breaking": True,
                    "timeout_s": 30.0,
                    "bandwidth": "",
                    "published_best": 35,
                    "status": "RESOURCE_LIMIT",
                    "total_wall_time_s": 0.0,
                    "cnf_variables": 2950208,
                    "cnf_clauses": 22490745,
                },
            ]
            with csv_path.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=list(sample_rows[0].keys()))
                writer.writeheader()
                writer.writerows(sample_rows)

            fig_dir = tmp_dir / "figures"
            written = create_m2_3_plots(csv_path, pf_path, fig_dir)
            self.assertEqual(len(written), 10)
            for path in written:
                self.assertTrue(path.exists())
                text = path.read_text(encoding="utf-8")
                self.assertIn("<svg", text)
                self.assertIn("</svg>", text)


if __name__ == "__main__":
    unittest.main()
