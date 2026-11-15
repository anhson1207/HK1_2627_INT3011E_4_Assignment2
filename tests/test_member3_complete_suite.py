"""Verification tests for Member 3 complete 113-instance deliverables and improvements."""

from __future__ import annotations

import csv
import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from bmp.core.solution import SolutionStatus, SolverResult
from bmp.core.validation import validate_solution
from bmp.encodings.cardinality import LadderAMOEncoder, ProductAMOEncoder, SimpleVarAllocator
from bmp.encodings.order import OrderEncoding
from bmp.solvers.brute_force import BruteForceSolver
from bmp.solvers.exact.cpsat import CPSATSolver
from bmp.solvers.sat.incremental import IncrementalSATSolver
from bmp.solvers.sat.repeated import RepeatedSATSolver
from bmp.solvers.sat.search import compute_lower_bound

ROOT = Path(__file__).resolve().parents[1]


def _load_complete_script():
    spec = importlib.util.spec_from_file_location(
        "run_member3_complete", ROOT / "scripts" / "run_member3_complete.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Member3CompleteSuiteTests(unittest.TestCase):
    def test_status_classification_never_conflates_feas_timeout_or_invalid_as_opt(self) -> None:
        mod = _load_complete_script()
        self.assertEqual(
            mod._classify_status(
                SolverResult(method="CP", status=SolutionStatus.OPTIMAL, bandwidth=5),
                validation_passed=True,
                has_incumbent=True,
            ),
            "OPT",
        )
        self.assertEqual(
            mod._classify_status(
                SolverResult(method="CP", status=SolutionStatus.FEASIBLE, bandwidth=7),
                validation_passed=True,
                has_incumbent=True,
            ),
            "FEAS",
        )
        self.assertEqual(
            mod._classify_status(
                SolverResult(method="SAT", status=SolutionStatus.TIMEOUT, bandwidth=9),
                validation_passed=True,
                has_incumbent=True,
            ),
            "TIMEOUT_WITH_INCUMBENT",
        )
        self.assertEqual(
            mod._classify_status(
                SolverResult(method="CP", status=SolutionStatus.TIMEOUT),
                validation_passed=None,
                has_incumbent=False,
            ),
            "TIMEOUT",
        )
        self.assertEqual(
            mod._classify_status(
                SolverResult(method="CP", status=SolutionStatus.OPTIMAL, bandwidth=5),
                validation_passed=False,
                has_incumbent=True,
            ),
            "INVALID",
        )
        self.assertEqual(
            mod._classify_status(
                SolverResult(method="CP", status=SolutionStatus.INFEASIBLE),
                validation_passed=None,
                has_incumbent=False,
            ),
            "INFEAS",
        )
        self.assertEqual(
            mod._classify_status(
                SolverResult(method="CP", status=SolutionStatus.UNAVAILABLE),
                validation_passed=None,
                has_incumbent=False,
            ),
            "BLOCKED_LICENSE",
        )

    def test_grid_and_petersen_known_optima_with_minisat22_product_and_ladder(self) -> None:
        mod = _load_complete_script()
        grid = mod._grid_graph(3, 3)
        self.assertEqual(grid.order, 9)
        self.assertEqual(grid.size, 12)
        self.assertEqual(compute_lower_bound(grid), 2)

        for amo in ("product", "ladder"):
            inc = IncrementalSATSolver(OrderEncoding(amo=amo), backend_name="minisat").solve(
                grid, timeout_seconds=5.0, symmetry_breaking=True
            )
            rep = RepeatedSATSolver(
                OrderEncoding(amo=amo), backend_name="minisat", search_mode="binary"
            ).solve(grid, timeout_seconds=5.0, symmetry_breaking=True)
            self.assertEqual(inc.status, SolutionStatus.OPTIMAL)
            self.assertEqual(rep.status, SolutionStatus.OPTIMAL)
            self.assertEqual(inc.bandwidth, 3)
            self.assertEqual(rep.bandwidth, 3)
            self.assertTrue(validate_solution(grid, inc).valid)
            self.assertTrue(validate_solution(grid, rep).valid)

        petersen = mod._petersen_graph()
        self.assertEqual(petersen.order, 10)
        self.assertEqual(petersen.size, 15)
        cp_res = CPSATSolver(seed=17).solve(petersen, timeout_seconds=5.0, symmetry_breaking=True)
        sat_res = IncrementalSATSolver(OrderEncoding(), backend_name="minisat").solve(
            petersen, timeout_seconds=5.0, symmetry_breaking=True
        )
        self.assertEqual(cp_res.status, SolutionStatus.OPTIMAL)
        self.assertEqual(sat_res.status, SolutionStatus.OPTIMAL)
        self.assertEqual(cp_res.bandwidth, 5)
        self.assertEqual(sat_res.bandwidth, 5)
        self.assertTrue(validate_solution(petersen, cp_res).valid)
        self.assertTrue(validate_solution(petersen, sat_res).valid)

    def test_product_and_ladder_amo_non_square_and_collision_safety(self) -> None:
        for encoder in (ProductAMOEncoder(), LadderAMOEncoder()):
            for count in (0, 1, 2, 3, 5, 6, 7):
                lits = list(range(1, count + 1))
                alloc = SimpleVarAllocator(start_id=count + 1)
                clauses, aux = encoder.encode(lits, alloc)
                self.assertEqual(len(set(aux)), len(aux))
                self.assertTrue(set(aux).isdisjoint(set(lits)))
                if count <= 1:
                    self.assertEqual(clauses, [])
                else:
                    self.assertTrue(clauses)

    def test_113_dataset_and_three_table_references_export(self) -> None:
        mod = _load_complete_script()
        with TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            manifest, graphs, _ = mod.load_113_dataset_and_tables(out_dir)
            self.assertEqual(len(manifest), 113)
            self.assertEqual(len(graphs), 113)
            self.assertEqual(len({r["instance"] for r in manifest}), 113)
            for fname, expected_len in (
                ("dataset_manifest.csv", 113),
                ("table_6_reference.csv", 31),
                ("table_7_reference.csv", 41),
                ("table_8_reference.csv", 41),
            ):
                with (out_dir / fname).open(encoding="utf-8", newline="") as f:
                    rows = list(csv.DictReader(f))
                self.assertEqual(len(rows), expected_len)

    def test_bitmask_lower_bound_matches_oracle_on_small_graphs(self) -> None:
        mod = _load_complete_script()
        for g in (mod._grid_graph(2, 3), mod._petersen_graph()):
            bf = BruteForceSolver().solve(g)
            self.assertLessEqual(compute_lower_bound(g), bf.bandwidth)


if __name__ == "__main__":
    unittest.main()
