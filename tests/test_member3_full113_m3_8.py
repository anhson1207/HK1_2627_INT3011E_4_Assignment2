"""Comprehensive verification & regression tests for Phase M3.8 Full 113/113 Coverage."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from bmp.core.benchmark_catalog import ALL_INSTANCES
from bmp.core.solution import SolutionStatus, SolverResult
from bmp.core.validation import validate_solution
from bmp.encodings.estimator import ResourceLimits
from bmp.encodings.order import OrderEncoding
from bmp.experiments.member3_m3_8 import (
    COVERAGE_STATUSES,
    _build_mip_cp_license_table,
    _map_result_to_m3_8_status,
    build_m3_8_dataset_and_views,
    run_m3_8_full113,
)
from bmp.experiments.member3_m3_8_plots import create_m3_8_plots
from bmp.heuristics.drsa import DRSASolver
from bmp.heuristics.rcm import RCMSolver
from bmp.heuristics.sa import SimulatedAnnealingSolver
from bmp.solvers.sat.incremental import IncrementalSATSolver

ROOT = Path(__file__).resolve().parents[1]


def _write_temp_m3_8_config(path: Path, out_dir: Path, legacy_csv: Path | None = None) -> None:
    leg_path = (ROOT / "results/member3-harwell-boeing.csv") if legacy_csv is None else legacy_csv
    path.write_text(
        '[benchmark]\n'
        'experiment_id = "unit_test_m3_8"\n'
        f'provenance = "{(ROOT / "data/benchmark_provenance.json").as_posix()}"\n'
        f'raw_dir = "{(ROOT / "data/benchmarks/raw").as_posix()}"\n'
        f'legacy_results_csv = "{leg_path.as_posix()}"\n'
        f'output_dir = "{out_dir.as_posix()}"\n'
        'threads = 1\n'
        'primary_seed = 17\n'
        'max_batch_seconds = 120.0\n'
        'memory_limit_mb = 4096.0\n'
        'max_sat_variables = 500000\n'
        'max_sat_clauses = 2500000\n'
        'sa_timeout_seconds = 0.2\n'
        'sa_max_iterations = 2000\n'
        'sa_legacy_iterations = 2000\n'
        'drsa_timeout_seconds = 0.2\n'
        'sensitivity_heuristic_timeout_seconds = 0.15\n'
        'cpsat_short_timeout_seconds = 1.5\n'
        'cpsat_extended_timeout_seconds = 2.0\n'
        'cpsat_extended_max_n = 700\n'
        'cpsat_proof_timeout_seconds = 2.0\n'
        'cpsat_proof_candidates = ["bcspwr01", "pores_1"]\n'
        'sat_timeout_seconds = 2.0\n'
        'sat_study_instances = ["bcspwr01"]\n'
        'mip_timeout_seconds = 2.0\n'
        'cpo_timeout_seconds = 2.0\n',
        encoding="utf-8",
    )


class Member3Full113M38Tests(unittest.TestCase):
    _shared_tmp: TemporaryDirectory[str]
    ds_rows: list[dict]
    view_rows: list[dict]
    graphs_by_view: dict
    meta_by_view: dict

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls._shared_tmp = TemporaryDirectory()
        cls.ds_rows, cls.view_rows, cls.graphs_by_view, cls.meta_by_view = build_m3_8_dataset_and_views(
            root=ROOT,
            provenance_path=ROOT / "data/benchmark_provenance.json",
            raw_dir=ROOT / "data/benchmarks/raw",
            output_dir=Path(cls._shared_tmp.name),
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._shared_tmp.cleanup()
        super().tearDownClass()

    def test_provenance_and_historical_72_untouched(self) -> None:
        prov = json.loads((ROOT / "data/benchmark_provenance.json").read_text(encoding="utf-8"))
        self.assertEqual(len(prov), 113)
        self.assertEqual(sum(1 for e in prov if e.get("validation_status") == "READY"), 54)
        self.assertEqual(sum(1 for e in prov if e.get("validation_status") == "NEEDS_VERIFICATION"), 58)
        self.assertEqual(sum(1 for e in prov if e.get("validation_status") == "INVALID_DATA"), 1)

        with (ROOT / "results/member3-harwell-boeing.csv").open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 288)

    def test_build_113_dataset_136_views_and_mbeause_496_vs_492(self) -> None:
        self.assertEqual(len(ALL_INSTANCES), 113)
        ds_rows = self.ds_rows
        view_rows = self.view_rows
        graphs_by_view = self.graphs_by_view
        meta_by_view = self.meta_by_view

        self.assertEqual(len(ds_rows), 113)
        self.assertEqual(sum(1 for r in ds_rows if r["official_benchmark"]), 54)
        self.assertEqual(sum(1 for r in ds_rows if not r["official_benchmark"]), 59)
        self.assertEqual(sum(1 for r in ds_rows if r["validation_status"] == "NEEDS_VERIFICATION"), 58)
        self.assertEqual(sum(1 for r in ds_rows if r["validation_status"] == "INVALID_DATA"), 1)
        self.assertEqual(sum(1 for r in ds_rows if r["table"] == "Table 6"), 31)
        self.assertEqual(sum(1 for r in ds_rows if r["table"] == "Table 7"), 41)
        self.assertEqual(sum(1 for r in ds_rows if r["table"] == "Table 8"), 41)

        # 111 unique topologies (sherman1 == saylr3, mbeaflw == mbeacxc)
        self.assertEqual(len({r["topology_sha256"] for r in ds_rows}), 111)
        dups = {r["instance"]: r["topology_duplicate_of"] for r in ds_rows if r["topology_duplicate_of"]}
        self.assertEqual(dups, {"mbeaflw": "mbeacxc", "sherman1": "saylr3"})

        # 136 views = 113 primary + 22 nonzero_union sensitivity + 1 mbeause 492 sensitivity
        self.assertEqual(len(view_rows), 136)
        self.assertEqual(len(graphs_by_view), 136)
        self.assertEqual(len(meta_by_view), 136)
        self.assertEqual(sum(1 for r in view_rows if r["view_kind"] == "SENSITIVITY_NONZERO_UNION"), 22)
        self.assertEqual(sum(1 for r in view_rows if r["view_kind"] == "SENSITIVITY_MBEAUSE_492"), 1)

        # Check mbeause 496 vs 492 exact vertices/edges
        g496 = graphs_by_view["mbeause__primary"]
        g492 = graphs_by_view["mbeause__drop4_492_sens"]
        self.assertEqual(g496.order, 496)
        self.assertEqual(g496.size, 36209)
        self.assertEqual([v for v in g496.vertices if g496.degree(v) == 0], [493, 494, 495, 496])
        self.assertEqual(g492.order, 492)
        self.assertEqual(g492.size, 36209)
        self.assertEqual([v for v in g492.vertices if g492.degree(v) == 0], [])

        # Check all 22 sensitivity instances have strictly fewer nonzero edges than stored_union
        nz_sens = [r for r in view_rows if r["view_kind"] == "SENSITIVITY_NONZERO_UNION"]
        ds_map = {r["instance"]: r for r in ds_rows}
        for sr in nz_sens:
            dr = ds_map[sr["instance"]]
            self.assertGreater(int(dr["m_stored_union"]), int(dr["m_nonzero_union"]))
            self.assertGreater(int(dr["explicit_offdiag_zeros"]), 0)
            self.assertFalse(bool(sr["official_benchmark"]))

    def test_status_mapper_and_license_gate_classification(self) -> None:
        self.assertEqual(
            _map_result_to_m3_8_status(SolverResult(method="m", status=SolutionStatus.OPTIMAL, bandwidth=5), validation_passed=True, has_incumbent=True),
            "OPTIMAL_PROVED",
        )
        self.assertEqual(
            _map_result_to_m3_8_status(SolverResult(method="m", status=SolutionStatus.FEASIBLE, bandwidth=7), validation_passed=True, has_incumbent=True),
            "FEASIBLE_SOLUTION_FOUND",
        )
        self.assertEqual(
            _map_result_to_m3_8_status(SolverResult(method="m", status=SolutionStatus.TIMEOUT, bandwidth=9), validation_passed=True, has_incumbent=True),
            "TIMEOUT_WITH_INCUMBENT",
        )
        self.assertEqual(
            _map_result_to_m3_8_status(SolverResult(method="m", status=SolutionStatus.TIMEOUT, bandwidth=None), validation_passed=None, has_incumbent=False),
            "TIMEOUT_NO_INCUMBENT",
        )
        self.assertEqual(
            _map_result_to_m3_8_status(SolverResult(method="m", status=SolutionStatus.SKIPPED, metadata={"skipped_reason": "cap"}), validation_passed=None, has_incumbent=False),
            "RESOURCE_LIMIT",
        )
        self.assertEqual(
            _map_result_to_m3_8_status(SolverResult(method="m", status=SolutionStatus.UNAVAILABLE), validation_passed=None, has_incumbent=False),
            "BLOCKED_LICENSE",
        )
        self.assertEqual(
            _map_result_to_m3_8_status(SolverResult(method="m", status=SolutionStatus.OPTIMAL, bandwidth=5), validation_passed=False, has_incumbent=True),
            "ERROR",
        )
        self.assertIn("BLOCKED_LICENSE", COVERAGE_STATUSES)
        self.assertIn("RESOURCE_LIMIT", COVERAGE_STATUSES)

        mock_env = {
            "solvers": {
                "gurobi": {"available": True, "license_type": "SIZE_LIMITED_EVAL", "max_variables": 2000, "max_constraints": 2000, "version": "12.0"},
                "cplex": {"available": True, "license_type": "COMMUNITY_EDITION", "max_variables": 1000, "max_constraints": 1000, "version": "22.1"},
                "cp-optimizer": {"available": True, "license_type": "COMMUNITY_EDITION_2P1000", "max_log2_search_space": 1000.0, "version": "22.2"},
            }
        }
        lic = _build_mip_cp_license_table(dataset_rows=self.ds_rows, meta_by_view=self.meta_by_view, env_info=mock_env)
        self.assertEqual(len(lic), 339)  # 113 * 3
        gur_el = [r for r in lic if r["solver"] == "gurobi" and r["eligibility"] == "ELIGIBLE"]
        cpx_el = [r for r in lic if r["solver"] == "cplex" and r["eligibility"] == "ELIGIBLE"]
        cpo_el = [r for r in lic if r["solver"] == "cp-optimizer" and r["eligibility"] == "ELIGIBLE"]
        self.assertEqual(len(gur_el), 3)
        self.assertEqual(len(cpx_el), 1)
        self.assertEqual(len(cpo_el), 20)
        for b in (r for r in lic if r["eligibility"] == "BLOCKED_LICENSE"):
            self.assertIn("EXTERNAL_LICENSE_BLOCKER", b["blocker_reason"])

    def test_live_heuristics_on_ready_unverified_and_mbeause_dual_views(self) -> None:
        for vid in ("bcspwr01__primary", "steam3__primary", "steam3__nonzero_sens", "mbeause__primary", "mbeause__drop4_492_sens"):
            g = self.graphs_by_view[vid]
            r_rcm = RCMSolver().solve(g)
            r_sa = SimulatedAnnealingSolver(iterations=5000, seed=17, initial_mode="rcm").solve(g, timeout_seconds=0.25)
            r_dw = DRSASolver(seed=17, initial_mode="rcm", initial_temperature=2.0, cooling=0.99, variant="MODIFIED_VARIANT").solve(g, timeout_seconds=0.25)
            r_dp = DRSASolver(seed=17, initial_mode="random", initial_temperature=1000.0, cooling=0.99, variant="PAPER_FAITHFUL").solve(g, timeout_seconds=0.25)
            for res in (r_rcm, r_sa, r_dw, r_dp):
                rep = validate_solution(g, res.permutation, claimed_bandwidth=res.bandwidth)
                self.assertTrue(rep.valid, f"Invalid solution on {vid} via {res.method}: {rep}")

    def test_live_sat_resource_limit_guard_returns_skipped_never_error(self) -> None:
        g = self.graphs_by_view["steam3__primary"]
        res = IncrementalSATSolver(OrderEncoding(amo="product"), backend_name="cadical").solve(
            g,
            timeout_seconds=1.5,
            limits=ResourceLimits(max_variables=100, max_clauses=500),
        )
        self.assertIs(res.status, SolutionStatus.SKIPPED)
        self.assertEqual(_map_result_to_m3_8_status(res, validation_passed=None, has_incumbent=False), "RESOURCE_LIMIT")

    def test_checkpoint_resume_determinism_on_temp_config(self) -> None:
        subset_keys = ("bcspwr01", "bcspwr02", "pores_1", "ibm32", "steam3")
        subset_catalog = {k: ALL_INSTANCES[k] for k in subset_keys}
        with TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            out_dir = tmp_dir / "m38_out"
            leg_csv = tmp_dir / "legacy_sub.csv"
            with (ROOT / "results/member3-harwell-boeing.csv").open(encoding="utf-8", newline="") as fin:
                rows = [r for r in csv.DictReader(fin) if r["instance"] in subset_keys]
                fieldnames = list(rows[0].keys())
            with leg_csv.open("w", encoding="utf-8", newline="") as fout:
                w = csv.DictWriter(fout, fieldnames=fieldnames)
                w.writeheader()
                w.writerows(rows)

            cfg = tmp_dir / "m38.toml"
            _write_temp_m3_8_config(cfg, out_dir, legacy_csv=leg_csv)

            with patch("bmp.experiments.member3_m3_8.ALL_INSTANCES", subset_catalog):
                s1 = run_m3_8_full113(
                    config_path=cfg,
                    stages={"RCM_113"},
                    resume=False,
                    max_runs_in_batch=3,
                    generate_plots=False,
                )
                self.assertTrue(s1["batch_execution"]["interrupted_by_batch_budget"])
                self.assertEqual(s1["batch_execution"]["executed_in_this_batch"], 3)
                self.assertEqual(s1["batch_execution"]["total_run_records"], 3)

                s2 = run_m3_8_full113(
                    config_path=cfg,
                    stages={"RCM_113"},
                    resume=True,
                    max_runs_in_batch=3,
                    generate_plots=False,
                )
                self.assertEqual(s2["batch_execution"]["executed_in_this_batch"], 3)
                self.assertEqual(s2["batch_execution"]["total_run_records"], 6)
                self.assertEqual(s2["validation_totals"]["validation_failed"], 0)
                ckpt = json.loads((out_dir / "checkpoint_runs.json").read_text(encoding="utf-8"))
                self.assertEqual(len({r["run_id"] for r in ckpt}), 6)

    def test_persisted_m3_8_deliverables_and_coverage_invariants(self) -> None:
        out_dir = ROOT / "results/member3_m3_8_full113"
        expected_files = (
            "dataset_113.csv",
            "graph_views_113.csv",
            "method_coverage_113.csv",
            "rcm_113.csv",
            "sa_113.csv",
            "drsa_113.csv",
            "cpsat_113.csv",
            "sat_preflight_113.csv",
            "sat_runs.csv",
            "mip_cp_license_113.csv",
            "full113_summary.json",
            "no_regression_comparison.csv",
            "published_best_comparison.csv",
            "run_log.txt",
            "reproduction.md",
        )
        for fn in expected_files:
            p = out_dir / fn
            self.assertTrue(p.is_file() and p.stat().st_size > 0, f"Missing or empty deliverable: {p}")

        svgs = sorted((out_dir / "figures").glob("*.svg"))
        self.assertEqual(len(svgs), 10)
        for svg in svgs:
            txt = svg.read_text(encoding="utf-8")
            ET.fromstring(txt)
            self.assertNotIn("nan", txt.lower())

        summary = json.loads((out_dir / "full113_summary.json").read_text(encoding="utf-8"))
        self.assertFalse(summary["batch_execution"]["interrupted_by_batch_budget"])
        self.assertEqual(summary["dataset_summary"]["total_catalog_names"], 113)
        self.assertEqual(summary["dataset_summary"]["graphs_constructed_primary"], 113)
        self.assertEqual(summary["dataset_summary"]["tier1_ready_count"], 54)
        self.assertEqual(summary["dataset_summary"]["tier2_exploratory_count"], 59)
        self.assertEqual(summary["dataset_summary"]["total_graph_views_constructed"], 136)
        self.assertEqual(summary["validation_totals"]["validation_failed"], 0)
        self.assertEqual(summary["validation_totals"]["execution_errors"], 0)
        self.assertEqual(summary["sat_preflight_summary"]["total_preflight_rows"], 8136)

        with (out_dir / "method_coverage_113.csv").open(encoding="utf-8", newline="") as f:
            cov_rows = list(csv.DictReader(f))
        self.assertEqual(len(cov_rows), 9)
        cov_map = {r["method_label"]: r for r in cov_rows}
        for r in cov_rows:
            self.assertEqual(int(r["catalog_instances"]), 113)
            self.assertEqual(int(r["dataset_loaded"]), 113)
            self.assertEqual(int(r["preflight_evaluated"]), 113)
            total_acc = (
                int(r["optimal_proved"])
                + int(r["feasible_solution_found"])
                + int(r["timeout_with_incumbent"])
                + int(r["timeout_no_incumbent"])
                + int(r["resource_limit"])
                + int(r["blocked_license"])
                + int(r["error_count"])
            )
            self.assertEqual(total_acc, 113, f"Status accounting mismatch for {r['method_label']}")
            self.assertEqual(
                int(r["valid_solution_found"]),
                int(r["tier1_ready_valid"]) + int(r["tier2_exploratory_valid"]),
            )
            self.assertEqual(int(r["error_count"]), 0)

        for hm in ("RCM (primary 113)", "SA (primary 113)", "DRSA Warm MODIFIED (113)", "DRSA Paper-Bounded (113)"):
            self.assertEqual(int(cov_map[hm]["valid_solution_found"]), 113)
            self.assertEqual(int(cov_map[hm]["tier1_ready_valid"]), 54)
            self.assertEqual(int(cov_map[hm]["tier2_exploratory_valid"]), 59)

        self.assertGreaterEqual(int(cov_map["CP-SAT Best Across Passes (113)"]["valid_solution_found"]), 72)
        self.assertGreaterEqual(int(cov_map["CP-SAT Best Across Passes (113)"]["optimal_proved"]), 4)
        self.assertEqual(
            int(cov_map["SAT Order+Product+Inc CaDiCaL (113)"]["solver_attempted"]),
            int(cov_map["SAT Order+Product+Inc CaDiCaL (113)"]["valid_solution_found"]),
        )
        self.assertEqual(
            int(cov_map["IBM CP Optimizer CE (113)"]["solver_attempted"]),
            int(cov_map["IBM CP Optimizer CE (113)"]["valid_solution_found"]),
        )

    def test_persisted_published_best_and_no_regression_consistency(self) -> None:
        out_dir = ROOT / "results/member3_m3_8_full113"
        with (out_dir / "published_best_comparison.csv").open(encoding="utf-8", newline="") as f:
            pub = list(csv.DictReader(f))
        self.assertEqual(len(pub), 113)
        self.assertEqual(sum(1 for r in pub if r["confidence_tier"] == "CANONICAL_VERIFIED"), 54)
        self.assertEqual(sum(1 for r in pub if r["confidence_tier"] == "EXPLORATORY_UNVERIFIED"), 59)
        self.assertTrue(all(r["best_feasible_bw"] not in ("", None) for r in pub))
        self.assertTrue(all(r["below_published_lb_flag"] == "False" for r in pub))

        # No-regression vs 72 legacy baseline (RCM exact 72/72 under nonzero_union, SA compat 72/72 valid)
        with (ROOT / "results/member3-harwell-boeing.csv").open(encoding="utf-8", newline="") as f:
            legacy = list(csv.DictReader(f))
        leg_rcm = {r["instance"]: int(r["our_bandwidth"]) for r in legacy if r["method"] == "rcm"}
        leg_sa = {r["instance"]: int(r["our_bandwidth"]) for r in legacy if r["method"] == "sa"}

        with (out_dir / "rcm_113.csv").open(encoding="utf-8", newline="") as f:
            rcm_rows = list(csv.DictReader(f))
        rcm_nz = {}
        for r in rcm_rows:
            if r["is_primary_113"] == "True":
                rcm_nz.setdefault(r["instance"], int(r["bandwidth"]))
            elif r["conversion_policy"] == "nonzero_union":
                rcm_nz[r["instance"]] = int(r["bandwidth"])
        for inst, old_bw in leg_rcm.items():
            self.assertEqual(rcm_nz[inst], old_bw, f"RCM legacy mismatch on {inst}")

        with (out_dir / "sa_113.csv").open(encoding="utf-8", newline="") as f:
            sa_rows = list(csv.DictReader(f))
        sa_leg = [r for r in sa_rows if r["stage"] == "SA_LEGACY72_COMPAT"]
        self.assertEqual(len(sa_leg), len(leg_sa))
        self.assertTrue(all(r["validation_passed"] == "True" for r in sa_leg))

        with (out_dir / "no_regression_comparison.csv").open(encoding="utf-8", newline="") as f:
            nr = list(csv.DictReader(f))
        eras = {r["era"] for r in nr}
        self.assertEqual(eras, {"Before_M3_1_Original_72", "After_M3_7_54_READY", "After_M3_8_Full_113", "After_M3_8_Legacy72_Compat"})

    def test_create_m3_8_plots_regenerates_all_svgs_cleanly(self) -> None:
        src_dir = ROOT / "results/member3_m3_8_full113"
        with TemporaryDirectory() as tmp:
            tmp_out = Path(tmp) / "m38_plot_test"
            tmp_out.mkdir(parents=True, exist_ok=True)
            for csv_file in src_dir.glob("*.csv"):
                shutil.copy2(csv_file, tmp_out / csv_file.name)
            generated = create_m3_8_plots(tmp_out)
            self.assertEqual(len(generated), 10)
            for p in generated:
                self.assertTrue(p.is_file() and p.stat().st_size > 0)
                ET.fromstring(p.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
