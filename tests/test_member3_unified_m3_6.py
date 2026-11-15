"""Comprehensive regression & contract tests for Phase M3.6 Unified Benchmark Framework."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from bmp.core.benchmark_catalog import ALL_INSTANCES
from bmp.experiments.member3_m3_6 import (
    METHOD_LABELS,
    M3_6_FIELDS,
    PREFLIGHT_M3_6_FIELDS,
    audit_environment,
    build_experiment_plan,
    compute_m3_6_statistics,
    run_m3_6_benchmark,
    run_preflight_54,
)
from bmp.experiments.member3_m3_6_plots import create_m3_6_plots

ROOT = Path(__file__).resolve().parents[1]


class Member3M36UnifiedTests(unittest.TestCase):
    def test_environment_and_preflight_54_contract(self) -> None:
        env = audit_environment()
        self.assertIn("solvers", env)
        self.assertEqual(set(env["solvers"]), set(METHOD_LABELS))
        self.assertTrue(env["solvers"]["cadical"]["available"])
        self.assertTrue(env["solvers"]["cp-sat"]["available"])

        with TemporaryDirectory() as tmp:
            out = Path(tmp)
            pf_rows, ready_map, loaded = run_preflight_54(
                root=ROOT,
                provenance_path=ROOT / "data/benchmark_provenance.json",
                raw_dir=ROOT / "data/benchmarks/raw",
                output_dir=out,
                env_info=env,
            )
            self.assertEqual(len(ready_map), 54)
            self.assertEqual(len(loaded), 54)
            self.assertEqual(len(pf_rows), 540)  # 54 READY x 10 method labels
            self.assertEqual({e["topology_sha256"] for e in ready_map.values()}.__len__(), 53)

            # Verify CSV schema and license-aware prediction consistency
            with (out / "preflight_54.csv").open(encoding="utf-8", newline="") as stream:
                reader = csv.DictReader(stream)
                self.assertEqual(tuple(reader.fieldnames or ()), PREFLIGHT_M3_6_FIELDS)
                rows = list(reader)
            self.assertEqual(len(rows), 540)
            cpx_elig = [r for r in rows if r["method"] == "cplex" and r["eligibility"] == "ELIGIBLE"]
            gur_elig = [r["instance"] for r in rows if r["method"] == "gurobi" and r["eligibility"] == "ELIGIBLE"]
            cpo_elig = [r["instance"] for r in rows if r["method"] == "cp-optimizer" and r["eligibility"] == "ELIGIBLE"]
            self.assertEqual(cpx_elig, [])
            if env["solvers"]["gurobi"]["license_type"] == "SIZE_LIMITED_EVAL":
                self.assertEqual(gur_elig, ["bcspwr01"])
            if env["solvers"]["cp-optimizer"].get("max_log2_search_space") == 1000.0:
                self.assertEqual(len(cpo_elig), 8)
                self.assertNotIn("can_144", cpo_elig)

    def test_checkpoint_resume_batch_guard_and_csv_json_parity(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            out_dir = tmp_dir / "out"
            cfg = tmp_dir / "test_m3_6.toml"
            cfg.write_text(
                f'[benchmark]\n'
                f'experiment_id = "unit_test_m3_6"\n'
                f'provenance = "{(ROOT / "data/benchmark_provenance.json").as_posix()}"\n'
                f'raw_dir = "{(ROOT / "data/benchmarks/raw").as_posix()}"\n'
                f'output_dir = "{out_dir.as_posix()}"\n'
                'threads = 1\n'
                'exact_timeout_seconds = 3.0\n'
                'sat_study_timeout_seconds = 3.0\n'
                'extended_timeout_seconds = 3.0\n'
                'heuristic_timeout_seconds = 0.25\n'
                'heuristic_extended_timeout_seconds = 0.25\n'
                'warm_start_drsa_timeout_seconds = 0.2\n'
                'small_oracle_timeout_seconds = 3.0\n'
                'max_batch_seconds = 120.0\n'
                'max_sat_variables = 500000\n'
                'max_sat_clauses = 2500000\n'
                'max_cp_variables = 2000\n'
                'max_cp_constraints = 25000\n'
                'memory_limit_mb = 4096.0\n'
                'primary_seed = 17\n'
                'stability_seeds = [17]\n'
                'representative_instances = ["bcspwr01"]\n'
                'sat_study_instances = ["bcspwr01"]\n'
                'sat_amo_study_instances = ["bcspwr01"]\n'
                'extended_instances = ["bcspwr01"]\n',
                encoding="utf-8",
            )

            # Batch 1: cap at 6 runs -> interrupts cleanly without losing checkpoints
            s1 = run_m3_6_benchmark(
                config_path=cfg,
                stages={"Stage_A_SmallOracle"},
                resume=False,
                max_runs_in_batch=6,
            )
            self.assertEqual(s1["executed_in_this_batch"], 6)
            self.assertEqual(s1["completed_total_runs"], 6)
            self.assertTrue(s1["interrupted_by_batch_budget"])

            # Batch 2: resume remaining Stage A oracle runs + check zero duplicates
            s2 = run_m3_6_benchmark(
                config_path=cfg,
                stages={"Stage_A_SmallOracle"},
                resume=True,
                max_runs_in_batch=100,
                generate_plots=True,
            )
            self.assertEqual(s2["completed_total_runs"], 40)
            self.assertEqual(s2["executed_in_this_batch"], 34)
            self.assertEqual(s2["validation_failed_count"], 0)

            # Re-running with resume=True executes 0 additional runs
            s3 = run_m3_6_benchmark(config_path=cfg, stages={"Stage_A_SmallOracle"}, resume=True)
            self.assertEqual(s3["executed_in_this_batch"], 0)
            self.assertEqual(s3["completed_total_runs"], 40)

            json_rows = json.loads((out_dir / "runs.json").read_text(encoding="utf-8"))
            with (out_dir / "runs.csv").open(encoding="utf-8", newline="") as stream:
                reader = csv.DictReader(stream)
                self.assertEqual(tuple(reader.fieldnames or ()), M3_6_FIELDS)
                csv_rows = list(reader)
            self.assertEqual(len(json_rows), len(csv_rows))
            self.assertEqual(len({r["run_id"] for r in json_rows}), len(json_rows))

            # Exact SmallOracle checks across SAT, Gurobi, CPLEX, CP-SAT, CPO
            for row in json_rows:
                self.assertTrue(row["graph_fingerprint"])
                self.assertTrue(row["topology_sha256"])
                self.assertTrue(row["validation"])
                if row["family"] != "Heuristic" and row["status"] == "OPTIMAL":
                    self.assertEqual(row["bandwidth"], row["paper_best"])
                    self.assertEqual(row["proof_status"], "PROVED_OPTIMAL")
                elif row["family"] == "Heuristic":
                    self.assertNotEqual(row["proof_status"], "PROVED_OPTIMAL")

    def test_resource_limit_duplicate_topology_and_plots_pipeline(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            out_dir = tmp_dir / "out"
            cfg = tmp_dir / "cfg_res.toml"
            cfg.write_text(
                f'[benchmark]\n'
                f'experiment_id = "unit_res_dup"\n'
                f'provenance = "{(ROOT / "data/benchmark_provenance.json").as_posix()}"\n'
                f'raw_dir = "{(ROOT / "data/benchmarks/raw").as_posix()}"\n'
                f'output_dir = "{out_dir.as_posix()}"\n'
                'threads = 1\n'
                'exact_timeout_seconds = 3.0\n'
                'sat_study_timeout_seconds = 3.0\n'
                'extended_timeout_seconds = 3.0\n'
                'heuristic_timeout_seconds = 0.15\n'
                'heuristic_extended_timeout_seconds = 0.2\n'
                'warm_start_drsa_timeout_seconds = 0.15\n'
                'small_oracle_timeout_seconds = 3.0\n'
                'max_batch_seconds = 120.0\n'
                'max_sat_variables = 5000\n'
                'max_sat_clauses = 25000\n'
                'max_cp_variables = 2000\n'
                'max_cp_constraints = 25000\n'
                'memory_limit_mb = 4096.0\n'
                'primary_seed = 17\n'
                'stability_seeds = [17]\n'
                'representative_instances = ["bcspwr01", "dwt_209"]\n'
                'sat_study_instances = ["bcspwr01", "dwt_209"]\n'
                'sat_amo_study_instances = ["bcspwr01"]\n'
                'extended_instances = ["bcspwr01"]\n',
                encoding="utf-8",
            )
            summary = run_m3_6_benchmark(
                config_path=cfg,
                stages={"Stage_D_SAT_Studies", "Stage_C_Exact_Baseline"},
                resume=False,
                generate_plots=True,
            )
            self.assertGreater(summary["status_counts"].get("RESOURCE_LIMIT", 0), 0)
            rows = json.loads((out_dir / "runs.json").read_text(encoding="utf-8"))
            # Resource-limited & license-blocked rows MUST NOT fake zero runtime or zero bandwidth
            for r in rows:
                if r["status"] in ("RESOURCE_LIMIT", "UNAVAILABLE"):
                    self.assertIsNone(r["total_wall_time_s"])
                    self.assertIsNone(r["solver_time_s"])
                    self.assertIsNone(r["bandwidth"])
            # Duplicate topology table reflects 54 vs 53
            dup_rows = {d["analysis_scope"]: d for d in summary["unique_topology_sensitivity"]}
            self.assertEqual(dup_rows["INSTANCE_WEIGHTED_54"]["instance_count"], 54)
            self.assertEqual(dup_rows["TOPOLOGY_UNIQUE_53"]["instance_count"], 53)
            # Plots created cleanly
            figs = list((out_dir / "figures").glob("*.svg"))
            self.assertGreaterEqual(len(figs), 4)

    def test_paired_comparisons_strict_stage_and_study_scoping_and_drsa_regime(self) -> None:
        from bmp.core.generators import erdos_renyi_graph
        from bmp.heuristics import DRSASolver

        g_small = erdos_renyi_graph(12, 0.5, seed=7)
        bounded = DRSASolver(seed=17, variant="PAPER_FAITHFUL").solve(g_small, max_total_moves=5)
        self.assertTrue(bounded.metadata["bounded_execution"])
        self.assertEqual(bounded.metadata["execution_regime"], "BOUNDED_MAX_TOTAL_MOVES")

        with TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            ready_map = {
                "bcsstk01": {
                    "source_table": "Table 6",
                    "n": 48,
                    "m": 176,
                    "topology_sha256": "abc",
                    "graph_fingerprint": "def",
                    "topology_duplicate_of": None,
                    "paper_best": 16,
                    "paper_lb": 16,
                    "initial_lb": 12,
                }
            }
            base = {
                "run_id": "id",
                "timestamp": "t",
                "git_commit": "h",
                "instance": "bcsstk01",
                "table": "Table 6",
                "n": 48,
                "m": 176,
                "family": "Heuristic",
                "backend": "drsa",
                "main_encoding": None,
                "amo_encoding": None,
                "strategy": None,
                "symmetry_breaking": False,
                "warm_start_mode": "RCM_INIT",
                "seed": 17,
                "status": "FEASIBLE",
                "proof_status": "UNPROVED",
                "optimality_gap": 0.1,
                "validation": True,
                "peak_rss_mb": 100.0,
                "comparison_status": "ABOVE_PUBLISHED_BEST",
                "paper_lb": 16,
                "paper_best": 16,
                "lower_bound": 12,
                "upper_bound": 19,
                "graph_fingerprint": "def",
                "topology_sha256": "abc",
                "topology_duplicate_of": None,
            }
            rows = [
                {**base, "run_id": "1", "stage": "Stage_B_Heuristic_54", "study": "heur", "method": "sa", "bandwidth": 19, "total_wall_time_s": 0.85, "time_limit_seconds": 0.8},
                {**base, "run_id": "2", "stage": "Stage_B_Heuristic_54", "study": "heur", "method": "drsa_modified_variant", "bandwidth": 18, "total_wall_time_s": 0.85, "time_limit_seconds": 0.8},
                # Stage E 5.0s must NOT overwrite Stage B 0.8s in paired comparisons
                {**base, "run_id": "3", "stage": "Stage_E_Extended", "study": "ext", "method": "drsa_modified_variant", "bandwidth": 16, "total_wall_time_s": 5.01, "time_limit_seconds": 5.0},
                # SAT_A_Backends vs SAT_E_Symmetry: SAT_E must NOT overwrite SAT_A CaDiCaL
                {**base, "run_id": "4", "stage": "Stage_D_SAT_Studies", "study": "SAT_A_Backends", "family": "SAT", "method": "cadical", "backend": "cadical", "main_encoding": "order", "amo_encoding": "sequential", "strategy": "incremental", "symmetry_breaking": True, "warm_start_mode": "NO_WARM_START", "bandwidth": 25, "status": "TIMEOUT", "total_wall_time_s": 10.0, "time_limit_seconds": 10.0},
                {**base, "run_id": "5", "stage": "Stage_D_SAT_Studies", "study": "SAT_A_Backends", "family": "SAT", "method": "minisat", "backend": "minisat", "main_encoding": "order", "amo_encoding": "sequential", "strategy": "incremental", "symmetry_breaking": True, "warm_start_mode": "NO_WARM_START", "bandwidth": 23, "status": "TIMEOUT", "total_wall_time_s": 10.0, "time_limit_seconds": 10.0},
                {**base, "run_id": "6", "stage": "Stage_D_SAT_Studies", "study": "SAT_E_Symmetry", "family": "SAT", "method": "cadical", "backend": "cadical", "main_encoding": "order", "amo_encoding": "sequential", "strategy": "incremental", "symmetry_breaking": True, "warm_start_mode": "NO_WARM_START", "bandwidth": 23, "status": "TIMEOUT", "total_wall_time_s": 10.0, "time_limit_seconds": 10.0},
            ]
            compute_m3_6_statistics(rows, ready_map, out_dir)
            with (out_dir / "paired_comparisons.csv").open(encoding="utf-8", newline="") as stream:
                paired = {r["comparison"]: r for r in csv.DictReader(stream)}
            self.assertEqual(float(paired["SA_vs_DRSA_Warm_54_seed17"]["mean_bw_diff_left_minus_right"]), 1.0)
            self.assertEqual(float(paired["SA_vs_DRSA_Warm_54_seed17"]["mean_wall_diff_s"]), 0.0)
            self.assertEqual(float(paired["SAT_CaDiCaL_vs_MiniSat_OrderSeqInc"]["mean_bw_diff_left_minus_right"]), 2.0)


if __name__ == "__main__":
    unittest.main()
