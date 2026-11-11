"""Comprehensive Phase M3.2 SAT integration, estimator, MiniSat reuse, and oracle tests."""

from __future__ import annotations

import io
import json
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from itertools import combinations, product
from math import comb, isqrt
from pathlib import Path
from unittest.mock import patch

from pysat.solvers import Solver

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
from bmp.core.solution import SolutionStatus
from bmp.core.validation import validate_solution
from bmp.encodings.cardinality import (
    LadderAMOEncoder,
    ProductAMOEncoder,
    SequentialCounterAMOEncoder,
    SimpleVarAllocator,
    get_amo_encoder,
)
from bmp.encodings.estimator import (
    ResourceLimits,
    estimate_cnf_size,
    estimate_incremental_cnf_size,
)
from bmp.encodings.order import OrderEncoding
from bmp.encodings.pairwise import PairwiseEncoding
from bmp.solvers.brute_force import BruteForceSolver
from bmp.solvers.sat.backends import MiniSatBackend, SATBackend, get_sat_backend
from bmp.solvers.sat.incremental import IncrementalSATSolver
from bmp.solvers.sat.repeated import RepeatedSATSolver

ROOT = Path(__file__).resolve().parents[1]


def _oracle_amo_check(
    test: unittest.TestCase,
    clauses: list[list[int]],
    literals: list[int],
    *,
    require_exactly_one: bool = False,
) -> None:
    var_ids = sorted({abs(lit) for lit in literals})
    extra_clause = [literals] if require_exactly_one else []
    with Solver(name="cadical195", bootstrap_with=clauses + extra_clause) as oracle:
        for bits in product((False, True), repeat=len(var_ids)):
            env = dict(zip(var_ids, bits))
            assumptions = [v if env[v] else -v for v in var_ids]
            true_count = sum(env[abs(lit)] == (lit > 0) for lit in literals)
            expected = (true_count == 1) if require_exactly_one else (true_count <= 1)
            test.assertEqual(oracle.solve(assumptions=assumptions), expected)


class ProductAndLadderAMOTests(unittest.TestCase):
    def test_product_amo_exhaustive_and_non_square_sizes(self) -> None:
        encoder = ProductAMOEncoder()
        # Small sizes with full brute-force truth tables
        for m in (0, 1, 2, 3, 4, 5, 7, 8, 10):
            literals = list(range(1, m + 1))
            alloc = SimpleVarAllocator(start_id=max(literals, default=0) + 1)
            clauses, aux = encoder.encode(literals, alloc)

            if m <= 1:
                self.assertEqual((clauses, aux), ([], []))
                continue

            rows = isqrt(m - 1) + 1
            cols = (m + rows - 1) // rows
            expected_aux = rows + cols
            expected_clauses = 2 * m + comb(rows, 2) + comb(cols, 2)
            self.assertEqual(len(aux), expected_aux)
            self.assertEqual(len(clauses), expected_clauses)
            self.assertEqual(set(aux), set(range(m + 1, m + 1 + expected_aux)))
            if m <= 8:
                _oracle_amo_check(self, clauses, literals, require_exactly_one=False)
                _oracle_amo_check(self, clauses, literals, require_exactly_one=True)

        # For m=10, verify 0 true, all 1 true, and all pairs 2 true using SAT oracle
        lits10 = list(range(1, 11))
        clauses10, _ = encoder.encode(lits10, SimpleVarAllocator(11))
        with MiniSatBackend(clauses10) as s:
            self.assertTrue(s.solve([-v for v in lits10]))
            for idx, v in enumerate(lits10):
                assump = [-x for x in lits10]
                assump[idx] = v
                self.assertTrue(s.solve(assump))
            for u, v in combinations(lits10, 2):
                self.assertFalse(s.solve([u, v]))

    def test_product_and_ladder_negative_literals_and_shared_allocator(self) -> None:
        for amo_name in ("product", "ladder"):
            enc = get_amo_encoder(amo_name)
            first = [-1, 2, -3, 4, -5]
            second = [6, -7, 8, -9, 10]
            alloc = SimpleVarAllocator(start_id=20)
            c1, a1 = enc.encode(first, alloc)
            c2, a2 = enc.encode(second, alloc)
            self.assertTrue(a1)
            self.assertTrue(a2)
            self.assertTrue(set(a1).isdisjoint(set(a2)))
            self.assertTrue(set(a1).isdisjoint(range(1, 11)))
            self.assertTrue(set(a2).isdisjoint(range(1, 11)))

            with MiniSatBackend(c1 + c2) as solver:
                # 0 true in both constraints is valid
                self.assertTrue(solver.solve([1, -2, 3, -4, 5, -6, 7, -8, 9, -10]))
                # Two true in first (lit -1 and +4) -> UNSAT
                self.assertFalse(solver.solve([-1, 4]))
                # One true in first (-3) and one in second (-7) -> SAT
                self.assertTrue(solver.solve([1, -2, -3, -4, 5, -6, -7, -8, 9, -10]))

    def test_ladder_vs_sequential_equivalence_and_m2_boundary(self) -> None:
        lad = LadderAMOEncoder()
        seq = SequentialCounterAMOEncoder()

        # For m >= 3, clause structure and aux IDs are identical
        for m in (3, 4, 5, 7, 8):
            lits = list(range(1, m + 1))
            c_lad, a_lad = lad.encode(lits, SimpleVarAllocator(100))
            c_seq, a_seq = seq.encode(lits, SimpleVarAllocator(100))
            self.assertEqual(a_lad, a_seq)
            self.assertEqual(c_lad, c_seq)

        # For m == 2, SequentialCounter optimizes out the single aux register
        c_lad2, a_lad2 = lad.encode([1, 2], SimpleVarAllocator(10))
        c_seq2, a_seq2 = seq.encode([1, 2], SimpleVarAllocator(10))
        self.assertEqual((len(a_lad2), len(c_lad2)), (1, 2))
        self.assertEqual((len(a_seq2), len(c_seq2)), (0, 1))
        _oracle_amo_check(self, c_lad2, [1, 2], require_exactly_one=False)
        _oracle_amo_check(self, c_seq2, [1, 2], require_exactly_one=False)

        # Exhaustive Ladder truth tables up to m=8 including EO check
        for m in (0, 1, 2, 3, 4, 5, 7, 8):
            lits = list(range(1, m + 1))
            clauses, _ = lad.encode(lits, SimpleVarAllocator(m + 1))
            if m <= 1:
                self.assertEqual(clauses, [])
            else:
                _oracle_amo_check(self, clauses, lits, require_exactly_one=False)
                _oracle_amo_check(self, clauses, lits, require_exactly_one=True)


class EstimatorProductLadderTests(unittest.TestCase):
    def test_exact_cnf_counts_for_product_and_ladder(self) -> None:
        graphs = [
            edgeless_graph(0),
            Graph.create(n=1),
            path_graph(2),
            path_graph(5),
            cycle_graph(4),
            star_graph(4),
            erdos_renyi_graph(6, 0.45, seed=11),
            Graph.from_edges([10, 20, 30, 40, 50], [(10, 20), (20, 30), (40, 50)]),
        ]
        for g in graphs:
            for enc_cls, enc_name in ((PairwiseEncoding, "pairwise"), (OrderEncoding, "order")):
                for amo in ("product", "ladder"):
                    for sym in (False, True):
                        k_values = [0] if g.order <= 1 else list(range(0, g.order))
                        for k in k_values:
                            with self.subTest(g=g.name, n=g.order, enc=enc_name, amo=amo, sym=sym, k=k):
                                est = estimate_cnf_size(
                                    g, encoding=enc_name, amo=amo, k=k, symmetry_breaking=sym
                                )
                                formula = enc_cls(amo=amo).encode(g, k=k, symmetry_breaking=sym)
                                self.assertEqual(est.num_variables, formula.num_variables)
                                self.assertEqual(est.num_clauses, formula.num_clauses)
                                self.assertEqual(est.num_original_vars + est.num_channeling_vars + est.num_aux_vars, est.num_variables)
                                self.assertEqual(est.num_fixed_clauses + est.num_bandwidth_clauses, est.num_clauses)

    def test_incremental_estimator_and_resource_limits(self) -> None:
        graph = cycle_graph(5)
        for enc_cls, enc_name in ((PairwiseEncoding, "pairwise"), (OrderEncoding, "order")):
            for amo in ("product", "ladder"):
                encoder = enc_cls(amo=amo)
                initial, target = 3, 1
                fixed = encoder.encode_fixed(graph)
                accumulated = fixed.num_clauses
                for k in range(initial, target - 1, -1):
                    if enc_name == "pairwise" and k < initial:
                        accumulated += len(encoder.encode_bandwidth_diff(graph, k, k + 1))
                    else:
                        accumulated += len(encoder.encode_bandwidth_step(graph, k))
                est = estimate_incremental_cnf_size(
                    graph, encoding=enc_name, amo=amo, initial_k=initial, target_k=target
                )
                self.assertEqual(est.num_clauses, accumulated)

        # ResourceLimits guard blocks large Product/Ladder instance without allocating CNF
        large = erdos_renyi_graph(12, 0.5, seed=5)
        for amo in ("product", "ladder"):
            for enc_cls, enc_name in ((PairwiseEncoding, "pairwise"), (OrderEncoding, "order")):
                est = estimate_cnf_size(large, encoding=enc_name, amo=amo, k=0)
                tight = ResourceLimits(max_clauses=max(1, est.num_clauses // 4), timeout_seconds=None)
                self.assertFalse(tight.check(est)[0])
                for solver in (
                    RepeatedSATSolver(enc_cls(amo=amo), backend_name="minisat"),
                    IncrementalSATSolver(enc_cls(amo=amo), backend_name="minisat"),
                ):
                    res = solver.solve(large, limits=tight)
                    self.assertEqual(res.status, SolutionStatus.SKIPPED)
                    self.assertEqual(res.sat_calls, 0)
                    self.assertIn("skipped_reason", res.metadata)
                    self.assertTrue(validate_solution(large, res).valid)


class MiniSatFullIntegrationTests(unittest.TestCase):
    def test_minisat_live_timer_interrupt_and_reuse(self) -> None:
        # Guarded Pigeonhole PHP(11, 10): exponentially hard UNSAT when sel=True, trivial SAT when -sel=True
        n_p, n_h = 11, 10
        sel = 1000
        def pvar(i: int, j: int) -> int:
            return i * n_h + j + 1

        clauses: list[list[int]] = []
        for i in range(n_p):
            clauses.append([-sel] + [pvar(i, j) for j in range(n_h)])
        for j in range(n_h):
            for i1, i2 in combinations(range(n_p), 2):
                clauses.append([-sel, -pvar(i1, j), -pvar(i2, j)])
        clauses.append([sel, 1001])

        with MiniSatBackend() as backend:
            self.assertTrue(issubclass(MiniSatBackend, SATBackend))
            backend.append_formula(clauses)
            res_timeout = backend.solve_with_timeout(0.05, assumptions=[sel])
            self.assertIsNone(res_timeout)
            self.assertIsNone(backend.get_model())
            # Interrupt state must be cleared cleanly for subsequent solves
            res_after = backend.solve(assumptions=[-sel])
            self.assertTrue(res_after)
            self.assertIn(1001, backend.get_model() or [])

    def test_incremental_sat_reuses_single_minisat_backend_instance(self) -> None:
        graph = path_graph(6)
        # Non-optimal incumbent (bw=5 vs optimum=1) forces multiple descending threshold calls.
        bad_perm = {1: 1, 2: 6, 3: 2, 4: 5, 5: 3, 6: 4}
        created: list[MiniSatBackend] = []
        real_get = get_sat_backend

        def tracked_get(name: str = "cadical", **kwargs: object) -> SATBackend:
            inst = real_get(name, **kwargs)
            created.append(inst)  # type: ignore[arg-type]
            return inst

        for amo in ("product", "ladder"):
            created.clear()
            with patch("bmp.solvers.sat.incremental.get_sat_backend", side_effect=tracked_get):
                inc = IncrementalSATSolver(
                    PairwiseEncoding(amo=amo), backend_name="minisat", threshold_policy="unit"
                ).solve(graph, heuristic_permutation=bad_perm)
            self.assertEqual(len(created), 1)
            self.assertGreaterEqual(inc.sat_calls, 3)
            self.assertGreater(inc.metadata["added_clauses"], 0)
            self.assertEqual(inc.status, SolutionStatus.OPTIMAL)
            self.assertEqual(inc.bandwidth, 1)
            self.assertTrue(validate_solution(graph, inc).valid)

            created.clear()
            with patch("bmp.solvers.sat.repeated.get_sat_backend", side_effect=tracked_get):
                rep = RepeatedSATSolver(
                    PairwiseEncoding(amo=amo), backend_name="minisat", threshold_policy="unit"
                ).solve(graph, heuristic_permutation=bad_perm)
            self.assertEqual(len(created), rep.sat_calls)
            self.assertEqual(inc.bandwidth, rep.bandwidth)

    def test_minisat_worker_timeout_preserves_valid_incumbent(self) -> None:
        graph = erdos_renyi_graph(8, 0.5, seed=9)
        with patch(
            "bmp.solvers.sat.backends.minisat.MiniSatBackend.solve_with_timeout",
            side_effect=lambda *a, **k: (time.sleep(0.4) or False),
        ):
            for solver in (
                RepeatedSATSolver(OrderEncoding("product"), backend_name="minisat"),
                IncrementalSATSolver(OrderEncoding("ladder"), backend_name="minisat"),
            ):
                res = solver.solve(graph, timeout_seconds=0.1)
                self.assertIn(res.status, (SolutionStatus.TIMEOUT, SolutionStatus.FEASIBLE))
                self.assertTrue(validate_solution(graph, res).valid)
                self.assertIn("sat_trace", res.metadata)


class OracleAndCLIIntegrationTests(unittest.TestCase):
    def test_oracle_consistency_across_encodings_amos_backends_strategies(self) -> None:
        oracle_graphs = [
            path_graph(5),
            cycle_graph(4),
            complete_graph(5),
            star_graph(4),
            edgeless_graph(5),
            Graph.from_edges([1, 2, 3, 4, 5, 6], [(1, 2), (2, 3), (4, 5), (5, 6)], name="disconnected"),
            Graph.from_edges([10, 20, 30, 40], [(10, 20), (20, 30)], name="isolated_vertex"),
            erdos_renyi_graph(6, 0.45, seed=11),
            erdos_renyi_graph(7, 0.35, seed=23),
        ]

        for graph in oracle_graphs:
            oracle = BruteForceSolver().solve(graph)
            self.assertEqual(oracle.status, SolutionStatus.OPTIMAL)
            for enc_cls in (PairwiseEncoding, OrderEncoding):
                for amo in ("product", "ladder"):
                    encoder = enc_cls(amo=amo)
                    for sym in (False, True):
                        solvers = [
                            RepeatedSATSolver(encoder, backend_name="minisat", search_mode="linear"),
                            RepeatedSATSolver(encoder, backend_name="minisat", search_mode="binary"),
                            IncrementalSATSolver(encoder, backend_name="minisat"),
                        ]
                        # Also cross-check CaDiCaL and Glucose on representative graphs
                        if graph.name in ("path_p5", "disconnected", "erdos_renyi_6_0.45_11"):
                            solvers.extend([
                                RepeatedSATSolver(encoder, backend_name="cadical"),
                                IncrementalSATSolver(encoder, backend_name="glucose"),
                            ])
                        for solver in solvers:
                            with self.subTest(
                                g=graph.name,
                                enc=encoder.name,
                                strat=type(solver).__name__,
                                mode=getattr(solver, "search_mode", "linear"),
                                backend=solver.backend_name,
                                sym=sym,
                            ):
                                res = solver.solve(graph, symmetry_breaking=sym)
                                self.assertEqual(res.status, SolutionStatus.OPTIMAL)
                                self.assertEqual(res.bandwidth, oracle.bandwidth)
                                self.assertEqual(res.lower_bound, oracle.bandwidth)
                                self.assertEqual(res.upper_bound, oracle.bandwidth)
                                self.assertTrue(validate_solution(graph, res).valid)

    def test_cli_smoke_all_8_combinations_and_rejects_invalid_mode(self) -> None:
        sample = str(ROOT / "data" / "samples" / "cycle_c4.edgelist")
        for enc in ("pairwise", "order"):
            for amo in ("product", "ladder"):
                for strat in ("repeated", "incremental"):
                    out = io.StringIO()
                    with redirect_stdout(out):
                        rc = cli_main([
                            "solve", sample,
                            "--solver", "minisat",
                            "--encoding", enc,
                            "--amo", amo,
                            "--strategy", strat,
                        ])
                    self.assertEqual(rc, 0)
                    payload = json.loads(out.getvalue())
                    self.assertEqual(payload["status"], "OPTIMAL")
                    self.assertEqual(payload["bandwidth"], 2)
                    self.assertEqual(payload["solver"], "minisat")
                    self.assertEqual(payload["encoding"], f"{enc}_{amo}")
                    self.assertTrue(payload["validation"]["valid"])

        # Binary search mode with repeated + minisat + product
        out_bin = io.StringIO()
        with redirect_stdout(out_bin):
            rc_bin = cli_main([
                "solve", sample,
                "--solver", "minisat", "--encoding", "order",
                "--amo", "product", "--strategy", "repeated", "--search-mode", "binary",
            ])
        self.assertEqual(rc_bin, 0)
        self.assertEqual(json.loads(out_bin.getvalue())["bandwidth"], 2)

        # estimate-cnf with product & ladder
        for amo in ("product", "ladder"):
            out_est = io.StringIO()
            with redirect_stdout(out_est):
                rc_est = cli_main(["estimate-cnf", sample, "--encoding", "order", "--amo", amo, "-k", "1"])
            self.assertEqual(rc_est, 0)
            est_payload = json.loads(out_est.getvalue())
            self.assertEqual(est_payload["amo"], amo)
            self.assertGreater(est_payload["estimate"]["num_variables"], 0)

        # Reject incompatible --strategy incremental --search-mode binary loudly
        err_buf = io.StringIO()
        with redirect_stderr(err_buf):
            rc_bad = cli_main([
                "solve", sample,
                "--solver", "minisat", "--strategy", "incremental", "--search-mode", "binary",
            ])
        self.assertEqual(rc_bad, 2)
        self.assertEqual(json.loads(err_buf.getvalue())["status"], "ERROR")

    def test_m3_2_experiment_plan_ready_guard_and_null_formatting(self) -> None:
        import tomllib
        from bmp.experiments.member3_m3_2 import (
            _build_plan,
            _format_csv_row,
            _load_verified_ready_instance,
        )

        cfg = tomllib.loads((ROOT / "configs" / "member3_m3_2.toml").read_text())["benchmark"]
        plan = _build_plan(cfg)
        self.assertGreaterEqual(len(plan), 60)

        prov = {
            e["instance"]: e
            for e in json.loads((ROOT / "data" / "benchmark_provenance.json").read_text())
        }
        with self.assertRaisesRegex(ValueError, "Refusing non-READY"):
            _load_verified_ready_instance("steam3", prov, ROOT / "data" / "hb_table6_7" / "raw")

        formatted = _format_csv_row({"run_id": "x", "sat_calls": None, "cnf_variables": None})
        self.assertEqual(formatted["sat_calls"], "")
        self.assertEqual(formatted["cnf_variables"], "")


if __name__ == "__main__":
    unittest.main()
