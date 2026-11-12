"""Phase M3.3 live validation, mathematical model, timeout, and mock tests for CP solvers."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import time
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from bmp.cli import main as cli_main
from bmp.core.generators import (
    complete_graph,
    cycle_graph,
    edgeless_graph,
    erdos_renyi_graph,
    path_graph,
    star_graph,
)
from bmp.core.graph import Graph
from bmp.core.solution import SolutionStatus, SolverResult
from bmp.core.validation import calculate_bandwidth, validate_solution
from bmp.solvers.brute_force import BruteForceSolver
from bmp.solvers.exact.cp_optimizer import CPOptimizerSolver, _build_model, _resolve_executable
from bmp.solvers.exact.cpsat import CPSATSolver
from bmp.solvers.sat.search import select_anchor_vertex

ROOT = Path(__file__).resolve().parents[1]


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except ModuleNotFoundError:
        return False


def _has_ortools() -> bool:
    return _has_module("ortools.sat.python.cp_model")


def _has_cpo() -> bool:
    exe = os.environ.get("BMP_CPO_EXECUTABLE", "cpoptimizer")
    return _has_module("docplex.cp.model") and _resolve_executable(exe) is not None


ORACLE_GRAPHS = (
    edgeless_graph(0),
    Graph.create(n=1, name="single_1"),
    path_graph(2),
    path_graph(5),
    cycle_graph(5),
    star_graph(4),
    complete_graph(5),
    edgeless_graph(5),
    Graph.from_edges([1, 2, 3, 4, 5, 6], [(1, 2), (2, 3), (4, 5), (5, 6)], name="disconnected"),
    Graph.from_edges([10, 20, 30, 40], [(10, 20), (20, 30)], name="isolated_vertex"),
    Graph.from_edges([-5, 3, 12, 99, 7], [(-5, 3), (3, 12), (12, 7)], name="noncontiguous"),
    erdos_renyi_graph(6, 0.45, seed=11),
    erdos_renyi_graph(7, 0.40, seed=23),
)


class LiveCPSATTests(unittest.TestCase):
    @unittest.skipUnless(_has_ortools(), "ortools is not installed")
    def test_cp_sat_matches_oracle_across_special_and_random_graphs(self) -> None:
        solver = CPSATSolver(seed=17)
        for graph in ORACLE_GRAPHS:
            oracle = BruteForceSolver().solve(graph)
            for sym in (False, True):
                for use_lb in (True, False):
                    with self.subTest(g=graph.name, sym=sym, use_lb=use_lb):
                        res = solver.solve(
                            graph,
                            timeout_seconds=10.0,
                            symmetry_breaking=sym,
                            threads=1,
                            use_lower_bound=use_lb,
                        )
                        self.assertEqual(res.status, SolutionStatus.OPTIMAL)
                        self.assertEqual(res.bandwidth, oracle.bandwidth)
                        self.assertEqual(res.lower_bound, oracle.bandwidth)
                        self.assertEqual(res.upper_bound, oracle.bandwidth)
                        self.assertTrue(validate_solution(graph, res).valid)
                        self.assertIn("solver_version", res.metadata)
                        self.assertIn("model_construction_time_s", res.metadata)

    @unittest.skipUnless(_has_ortools(), "ortools is not installed")
    def test_cp_sat_symmetry_normalizes_hint_and_enforces_timeouts(self) -> None:
        g = path_graph(4)
        anchor = select_anchor_vertex(g)
        # Construct an optimal permutation (bw=1) that violates p(anchor) <= ceil(4/2)=2
        perm = {1: 4, 2: 3, 3: 2, 4: 1}
        if perm[anchor] <= 2:
            perm = {1: 1, 2: 2, 3: 3, 4: 4}
        res = CPSATSolver(seed=5).solve(
            g,
            timeout_seconds=5.0,
            symmetry_breaking=True,
            initial_permutation=perm,
            threads=1,
        )
        self.assertEqual(res.status, SolutionStatus.OPTIMAL)
        self.assertEqual(res.bandwidth, 1)
        self.assertTrue(res.metadata["hint_reversed_for_symmetry"])
        self.assertLessEqual(res.permutation[anchor], 2)

        # Isolated wall-clock deadline test
        res_iso = CPSATSolver(seed=5).solve(
            cycle_graph(5),
            timeout_seconds=5.0,
            symmetry_breaking=True,
            isolate_timeout=True,
        )
        self.assertEqual(res_iso.status, SolutionStatus.OPTIMAL)
        self.assertEqual(res_iso.bandwidth, 2)
        self.assertTrue(res_iso.metadata["isolated_subprocess"])

        # CLI live check
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli_main([
                "solve",
                str(ROOT / "data" / "samples" / "cycle_c4.edgelist"),
                "--solver",
                "cp-sat",
                "--symmetry-breaking",
                "--timeout",
                "5",
            ])
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["status"], "OPTIMAL")
        self.assertEqual(payload["bandwidth"], 2)
        self.assertTrue(payload["validation"]["valid"])


class LiveCPOptimizerTests(unittest.TestCase):
    @unittest.skipUnless(_has_cpo(), "docplex or cpoptimizer runtime is unavailable")
    def test_cp_optimizer_matches_oracle_across_special_and_random_graphs(self) -> None:
        exe = os.environ.get("BMP_CPO_EXECUTABLE", "cpoptimizer")
        solver = CPOptimizerSolver(executable=exe, seed=17)
        for graph in ORACLE_GRAPHS:
            oracle = BruteForceSolver().solve(graph)
            for sym in (False, True):
                with self.subTest(g=graph.name, sym=sym):
                    res = solver.solve(
                        graph,
                        timeout_seconds=10.0,
                        symmetry_breaking=sym,
                        threads=1,
                    )
                    self.assertEqual(res.status, SolutionStatus.OPTIMAL)
                    self.assertEqual(res.bandwidth, oracle.bandwidth)
                    self.assertEqual(res.lower_bound, oracle.bandwidth)
                    self.assertEqual(res.upper_bound, oracle.bandwidth)
                    self.assertTrue(validate_solution(graph, res).valid)
                    self.assertIn("solver_version", res.metadata)
                    self.assertNotEqual(res.metadata["solver_version"], "unknown")
                    self.assertEqual(res.metadata["solver_lower_bound"], oracle.bandwidth)

    @unittest.skipUnless(_has_cpo(), "docplex or cpoptimizer runtime is unavailable")
    def test_cp_optimizer_starting_point_zero_budget_and_cli(self) -> None:
        g = path_graph(4)
        anchor = select_anchor_vertex(g)
        perm = {1: 4, 2: 3, 3: 2, 4: 1}
        if perm[anchor] <= 2:
            perm = {1: 1, 2: 2, 3: 3, 4: 4}
        res = CPOptimizerSolver(seed=7).solve(
            g,
            timeout_seconds=5.0,
            symmetry_breaking=True,
            initial_permutation=perm,
            threads=1,
            use_lower_bound=False,
        )
        self.assertEqual(res.status, SolutionStatus.OPTIMAL)
        self.assertEqual(res.bandwidth, 1)
        self.assertTrue(res.metadata["hint_reversed_for_symmetry"])
        self.assertLessEqual(res.permutation[anchor], 2)

        zero_res = CPOptimizerSolver().solve(cycle_graph(4), timeout_seconds=0)
        self.assertEqual(zero_res.status, SolutionStatus.TIMEOUT)
        self.assertIsNone(zero_res.permutation)

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli_main([
                "solve",
                str(ROOT / "data" / "samples" / "cycle_c4.edgelist"),
                "--solver",
                "cp-optimizer",
                "--symmetry-breaking",
                "--timeout",
                "5",
            ])
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["status"], "OPTIMAL")
        self.assertEqual(payload["bandwidth"], 2)
        self.assertTrue(payload["validation"]["valid"])


class CPContractAndMockTests(unittest.TestCase):
    def test_model_construction_stats_and_missing_dependencies_and_license_mock(self) -> None:
        g = path_graph(4)
        model, pos = _build_model(g, symmetry_breaking=True)
        self.assertEqual(set(pos), {1, 2, 3, 4})
        self.assertIn("alldiff(", model.get_cpo_string())

        # Invalid arguments rejected cleanly
        with self.assertRaises(ValueError):
            CPSATSolver().solve(g, timeout_seconds=-1)
        with self.assertRaises(ValueError):
            CPSATSolver().solve(g, threads=0)
        with self.assertRaises(ValueError):
            CPOptimizerSolver().solve(g, timeout_seconds=-0.5)
        with self.assertRaises(ValueError):
            CPOptimizerSolver().solve(g, initial_permutation={1: 1, 2: 1, 3: 1, 4: 1})

        # Missing runtime / license mocks never masquerade as INFEASIBLE
        with patch.dict(sys.modules, {"ortools": None, "ortools.sat": None, "ortools.sat.python": None, "ortools.sat.python.cp_model": None}):
            unavail = CPSATSolver().solve(g, timeout_seconds=5)
            self.assertEqual(unavail.status, SolutionStatus.UNAVAILABLE)
            self.assertIsNone(unavail.permutation)

        fake_ex = RuntimeError("CPO license validation failed")
        with patch("bmp.solvers.exact.cp_optimizer._resolve_executable", return_value="/fake/cpoptimizer"):
            with patch("docplex.cp.model.CpoModel.create_solver", side_effect=OSError("license unavailable")):
                lic_res = CPOptimizerSolver().solve(g, timeout_seconds=5)
                self.assertEqual(lic_res.status, SolutionStatus.UNAVAILABLE)
                self.assertIn("license", str(lic_res.metadata["reason"]).lower())

        from docplex.cp.utils import CpoException

        ce_ex = CpoException(
            "Solver error: Problem size limit exceeded.\n"
            "CP Optimizer Community Edition solves problems with search spaces up to 2^1000.\n"
            "Unrestricted version options (including academia) at https://ibm.biz/error1016"
        )
        with patch("bmp.solvers.exact.cp_optimizer._resolve_executable", return_value="/fake/cpoptimizer"):
            with patch("docplex.cp.model.CpoModel.create_solver", side_effect=ce_ex):
                ce_res = CPOptimizerSolver().solve(g, timeout_seconds=5)
                self.assertEqual(ce_res.status, SolutionStatus.UNAVAILABLE)
                self.assertIn("error1016", str(ce_res.metadata["reason"]).lower())

        # Strictly bounded child watchdog timeout kills stuck CP solve cleanly
        def slow_solve(self, model_arg):
            time.sleep(2.0)
            return 0

        with patch("ortools.sat.python.cp_model.CpSolver.solve", new=slow_solve):
            t0 = time.monotonic()
            iso_timeout = CPSATSolver().solve(g, timeout_seconds=0.15, isolate_timeout=True)
            dt = time.monotonic() - t0
            self.assertEqual(iso_timeout.status, SolutionStatus.TIMEOUT)
            self.assertIsNone(iso_timeout.permutation)
            self.assertLess(dt, 3.0)

    def test_select_anchor_vertex_linear_time_on_bcsstk04(self) -> None:
        from bmp.io.readers import read_graph
        g = read_graph(ROOT / "data" / "hb_table6_7" / "raw" / "bcsstk04.mtx.gz")
        t0 = time.monotonic()
        anchor = select_anchor_vertex(g)
        dt = time.monotonic() - t0
        self.assertEqual(anchor, 73)
        self.assertLess(dt, 0.25)

    def test_m3_3_preflight_plan_and_csv_schema(self) -> None:
        import json as _json
        import tomllib
        from bmp.experiments.member3_m3_3 import (
            M3_3_FIELDS,
            PREFLIGHT_FIELDS,
            _build_plan,
            _format_csv_row,
            _run_preflight,
        )

        cfg = tomllib.loads((ROOT / "configs" / "member3_m3_3.toml").read_text(encoding="utf-8"))["benchmark"]
        prov_entries = _json.loads((ROOT / cfg["provenance"]).read_text(encoding="utf-8"))
        preflight_rows, loaded_pilot = _run_preflight(
            prov_entries,
            raw_dir=ROOT / cfg["raw_dir"],
            fallback_raw_dir=ROOT / cfg["fallback_raw_dir"],
            pilot_set=set(cfg["pilot_instances"]),
            max_cp_vars=int(cfg["max_cp_vars"]),
            max_cp_constrs=int(cfg["max_cp_constraints"]),
        )
        self.assertEqual(len(preflight_rows), 54)
        self.assertTrue(all(row["dataset_status"] == "READY" for row in preflight_rows))
        self.assertEqual(len(loaded_pilot), 6)
        self.assertNotIn("steam3", {row["instance"] for row in preflight_rows})

        plan = _build_plan(cfg)
        self.assertEqual(len(plan), 36)
        self.assertEqual(sum(1 for item in plan if item["solver"] == "cp-sat"), 21)
        self.assertEqual(sum(1 for item in plan if item["solver"] == "cp-optimizer"), 15)

        formatted = _format_csv_row(
            {"run_id": "m33-x", "bandwidth": None, "validation": True},
            ("run_id", "bandwidth", "validation", "missing_field"),
        )
        self.assertEqual(formatted["run_id"], "m33-x")
        self.assertEqual(formatted["bandwidth"], "")
        self.assertEqual(formatted["validation"], True)
        self.assertEqual(formatted["missing_field"], "")
        self.assertIn("bandwidth", M3_3_FIELDS)
        self.assertIn("eligibility", PREFLIGHT_FIELDS)

    @unittest.skipUnless(_has_ortools(), "ortools is not installed")
    def test_cp_sat_no_overlap_and_presolve_off_match_exact_oracle_and_unblock_bcspwr03(self) -> None:
        from bmp.heuristics.rcm import RCMSolver
        from bmp.io.readers import read_graph
        from bmp.solvers.sat.search import compute_lower_bound

        solver = CPSATSolver(seed=17)
        for graph in ORACLE_GRAPHS:
            for inj in ("all_different", "no_overlap"):
                res = solver.solve(
                    graph,
                    timeout_seconds=10.0,
                    symmetry_breaking=True,
                    threads=1,
                    injectivity_mode=inj,
                    presolve=(inj == "all_different"),
                )
                oracle = BruteForceSolver().solve(graph)
                self.assertEqual(res.status, SolutionStatus.OPTIMAL)
                self.assertEqual(res.bandwidth, oracle.bandwidth)
                self.assertTrue(validate_solution(graph, res).valid)
                self.assertEqual(res.metadata["injectivity_mode"], inj)

        # Verify large-graph auto mode solves previously presolve-stalled bcspwr03 (n=118)
        g = read_graph(ROOT / "data" / "hb_table6_7" / "raw" / "bcspwr03.mtx.gz")
        self.assertEqual(compute_lower_bound(g), 9)
        rcm_res = RCMSolver().solve(g)
        res = solver.solve(
            g,
            timeout_seconds=4.0,
            symmetry_breaking=True,
            threads=1,
            initial_permutation=rcm_res.permutation,
        )
        self.assertIn(res.status, (SolutionStatus.OPTIMAL, SolutionStatus.FEASIBLE))
        self.assertEqual(res.metadata["injectivity_mode"], "no_overlap")
        self.assertFalse(res.metadata["presolve_enabled"])
        self.assertIsNotNone(res.bandwidth)
        self.assertLessEqual(res.bandwidth, rcm_res.bandwidth)
        self.assertTrue(validate_solution(g, res).valid)


if __name__ == "__main__":
    unittest.main()
