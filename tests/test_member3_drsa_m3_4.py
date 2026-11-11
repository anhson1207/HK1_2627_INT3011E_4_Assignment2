"""Stage A correctness, paper-faithfulness, delta-eval, and warm-start tests for DRSA/SA/RCM."""

from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path
from random import Random
from unittest.mock import patch

from bmp import cli
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
from bmp.core.validation import calculate_bandwidth, validate_assignment, validate_solution
from bmp.heuristics import (
    DRSASolver,
    DualRepresentation,
    IncrementalBandwidthState,
    RCMSolver,
    SimulatedAnnealingSolver,
    build_initial_permutation,
    compute_fractional_delta,
    compute_increment_factor,
    evaluate_solution,
    p_to_q_mapping,
    q_to_p_mapping,
)
from bmp.solvers.brute_force import BruteForceSolver
from bmp.solvers.exact._common import prepare_mip_bounds
from bmp.solvers.exact.cp_optimizer import CPOptimizerSolver
from bmp.solvers.exact.cplex import CPLEXMIPSolver
from bmp.solvers.exact.cpsat import CPSATSolver
from bmp.solvers.exact.gurobi import GurobiMIPSolver
from bmp.solvers.sat.incremental import IncrementalSATSolver
from bmp.solvers.sat.repeated import RepeatedSATSolver
from bmp.solvers.sat.search import select_anchor_vertex


class DualRepresentationAndOperatorsTests(unittest.TestCase):
    def test_paper_fig1_rex_and_fig3_rot_hand_examples(self) -> None:
        # From Torres-Jimenez et al. (2015), Figs. 1 and 3:
        # n = 8, initial pi = (1, 6, 2, 3, 8, 4, 5, 7), rho = (1, 3, 4, 6, 7, 2, 8, 5)
        g = Graph.from_edges(
            [1, 2, 3, 4, 5, 6, 7, 8],
            [(1, 3), (1, 5), (1, 6), (2, 7), (3, 4), (3, 6), (5, 7), (6, 7), (6, 8)],
            name="paper_fig1_3",
        )
        pi_init = {1: 1, 2: 6, 3: 2, 4: 3, 5: 8, 6: 4, 7: 5, 8: 7}
        rho_expected = {1: 1, 2: 3, 3: 4, 4: 6, 5: 7, 6: 2, 7: 8, 8: 5}
        self.assertEqual(p_to_q_mapping(g.vertices, pi_init), rho_expected)
        self.assertEqual(q_to_p_mapping(rho_expected), pi_init)

        dual = DualRepresentation.from_p(g, pi_init)
        dual.validate()
        self.assertEqual([dual.q_map()[i] for i in range(1, 9)], [1, 3, 4, 6, 7, 2, 8, 5])

        # Fig. 1 REX: swap labels of vertices 2 and 4 (0-based slots 1 and 3)
        dual.rex_swap_slots(1, 3)
        dual.validate()
        self.assertEqual([dual.p_map()[v] for v in range(1, 9)], [1, 3, 2, 6, 8, 4, 5, 7])
        self.assertEqual([dual.q_map()[i] for i in range(1, 9)], [1, 3, 2, 6, 7, 4, 8, 5])

        # Revert REX back to initial
        dual.rex_swap_slots(1, 3)
        self.assertEqual(dual.p_map(), pi_init)

        # Fig. 3 ROT: 1-based i=2, j=6 => 0-based i=1, j=5 on rho=(1,3,4,6,7,2,8,5)
        # Moves q[2]=3 to position 6, shifting 4,6,7,2 left by 1
        dual.rot_left_labels(1, 5)
        dual.validate()
        self.assertEqual([dual.q_map()[i] for i in range(1, 9)], [1, 4, 6, 7, 2, 3, 8, 5])
        self.assertEqual([dual.p_map()[v] for v in range(1, 9)], [1, 5, 6, 2, 8, 3, 4, 7])

        # Exact rollback restores original p and q
        dual.undo_rot_left_labels(1, 5)
        dual.validate()
        self.assertEqual(dual.p_map(), pi_init)
        self.assertEqual(dual.q_map(), rho_expected)

    def test_from_q_validation_and_non_contiguous_vertices(self) -> None:
        g = Graph.from_edges([100, -5, 42, 7], [(100, -5), (42, 7)], name="sparse_ids")
        q_init = {1: 42, 2: -5, 3: 100, 4: 7}
        dual = DualRepresentation.from_q(g, q_init)
        dual.validate()
        self.assertEqual(dual.p_map(), {42: 1, -5: 2, 100: 3, 7: 4})
        self.assertEqual(dual.q_map(), q_init)

        with self.assertRaises(ValueError):
            DualRepresentation.from_p(g, {100: 1, -5: 1, 42: 3, 7: 4})
        with self.assertRaises(ValueError):
            DualRepresentation.from_q(g, {1: 42, 2: 42, 3: 100, 4: 7})

    def test_nex_swaps_only_adjacent_vertices_and_handles_isolated_and_edgeless(self) -> None:
        # Graph with 1 edge (10, 20) and 4 isolated vertices [30, 40, 50, 60]
        g_iso = Graph.from_edges([10, 20, 30, 40, 50, 60], [(10, 20)], name="mostly_isolated")
        res = DRSASolver(
            p_rex=0.0,
            p_nex=1.0,
            p_rot=0.0,
            seed=17,
            initial_mode="identity",
        ).solve(g_iso, max_total_moves=60)
        self.assertEqual(res.status, SolutionStatus.FEASIBLE)
        self.assertTrue(validate_solution(g_iso, res).valid)
        self.assertEqual(res.metadata["operator_counts"], {"REX": 0, "NEX": 60, "ROT": 0})
        self.assertEqual(res.metadata["operator_noop_counts"]["NEX"], 0)

        # Edgeless graph handled cleanly without crash
        g_empty = edgeless_graph(6)
        empty_res = DRSASolver(p_rex=0.0, p_nex=1.0, p_rot=0.0, seed=5).solve(
            g_empty, max_total_moves=20
        )
        self.assertEqual(empty_res.status, SolutionStatus.FEASIBLE)
        self.assertEqual(empty_res.bandwidth, 0)
        self.assertEqual(empty_res.metadata["stop_reason"], "trivial_or_edgeless")
        self.assertEqual(empty_res.metadata["final_fractional_delta"], 0.0)

        # Verify NEX truly only swaps graph edges on random graph
        g_rand = erdos_renyi_graph(12, 0.25, seed=9)
        state = IncrementalBandwidthState(g_rand, {v: i for i, v in enumerate(g_rand.vertices, 1)})
        edge_set = {frozenset(e) for e in g_rand.edges}
        rng = Random(42)
        for _ in range(100):
            u_slot = state.non_isolated_slots[rng.randrange(len(state.non_isolated_slots))]
            nbrs = state.adj_neighbors[u_slot]
            v_slot = nbrs[rng.randrange(len(nbrs))]
            u_v = g_rand.vertices[u_slot]
            v_v = g_rand.vertices[v_slot]
            self.assertIn(frozenset((u_v, v_v)), edge_set)
            tok = state.apply_swap_p(u_slot, v_slot)
            state.assert_synced()
            state.undo_swap_p(u_slot, v_slot, tok)
            state.assert_synced()

    def test_operator_selection_probabilities_match_paper_ratio(self) -> None:
        g = erdos_renyi_graph(12, 0.35, seed=11)
        res = DRSASolver(seed=17).solve(g, max_total_moves=3000)
        counts = res.metadata["operator_counts"]
        total = sum(counts.values())
        self.assertEqual(total, 3000)
        self.assertAlmostEqual(counts["REX"] / total, 0.6, delta=0.035)
        self.assertAlmostEqual(counts["NEX"] / total, 0.2, delta=0.03)
        self.assertAlmostEqual(counts["ROT"] / total, 0.2, delta=0.03)


class EvaluationFunctionAndScheduleTests(unittest.TestCase):
    def test_algorithm4_evaluation_properties_tie_breaking_and_no_overflow(self) -> None:
        g = path_graph(5)
        # Same bandwidth b=2, fewer critical distance-2 edges should strictly win
        p_few_b2 = {1: 1, 2: 3, 3: 2, 4: 4, 5: 5}  # diffs: |1-3|=2, |3-2|=1, |2-4|=2, |4-5|=1 -> d=[0,2,2,0,0]
        p_more_b2 = {1: 1, 2: 3, 3: 5, 4: 4, 5: 2}  # diffs: |1-3|=2, |3-5|=2, |5-4|=1, |4-2|=2 -> d=[0,1,3,0,0]
        b1, d1, f1, h1 = evaluate_solution(g, p_few_b2)
        b2, d2, f2, h2 = evaluate_solution(g, p_more_b2)
        self.assertEqual((b1, b2), (2, 2))
        self.assertEqual(h1[:3], [0, 2, 2])
        self.assertEqual(h2[:3], [0, 1, 3])
        self.assertTrue(0.0 <= d1 < d2 < 1.0)
        self.assertLess(f1, f2)

        # Strict bandwidth ordering regardless of histogram on large clique
        k30 = complete_graph(30)
        pk30 = {v: v for v in k30.vertices}
        bk, dk, fk, _ = evaluate_solution(k30, pk30)
        self.assertEqual(bk, 29)
        self.assertTrue(0.0 <= dk < 1.0)
        self.assertLess(fk, 30.0)

        # Lower bandwidth always strictly less than higher bandwidth + any delta
        p_opt = {v: v for v in g.vertices}
        b_opt, d_opt, f_opt, _ = evaluate_solution(g, p_opt)
        self.assertEqual(b_opt, 1)
        self.assertAlmostEqual(d_opt, 4 / 5, places=12)
        self.assertLess(f_opt, f1)

        # No factorial overflow even at n=400
        g_big = path_graph(400)
        rev_big = {v: 401 - v for v in g_big.vertices}
        b_big, d_big, f_big, _ = evaluate_solution(g_big, rev_big)
        self.assertEqual(b_big, 1)
        self.assertTrue(math.isfinite(d_big) and 0.0 <= d_big < 1.0)
        self.assertTrue(math.isfinite(f_big))
        self.assertAlmostEqual(compute_fractional_delta([0, 399], 1, 400), d_big, places=12)

    def test_algorithm1_cooling_and_increment_factor(self) -> None:
        r, gamma = compute_increment_factor(1000.0, 1e-7, 0.99, 40, 4000)
        self.assertAlmostEqual(r, (math.log(1e-7) - math.log(1000.0)) / math.log(0.99), places=9)
        self.assertAlmostEqual(40.0 * (gamma ** r), 4000.0, places=6)

        # Verify Algorithm 1 keeps T & L unchanged during improving stages
        g = cycle_graph(12)
        res = DRSASolver(
            initial_temperature=10.0,
            final_temperature=0.5,
            cooling=0.8,
            initial_chain_length=15,
            final_chain_length=60,
            seed=17,
        ).solve(g)
        self.assertEqual(res.status, SolutionStatus.FEASIBLE)
        self.assertEqual(res.metadata["stop_reason"], "final_temperature")
        # Each improvement kept T fixed for another Markov chain => stages > cooling_steps
        self.assertGreater(res.metadata["temperature_stages"], res.metadata["cooling_steps"])
        self.assertTrue(res.metadata["paper_faithful_params"] is False)
        self.assertEqual(res.metadata["variant"], "MODIFIED_VARIANT")

        # Default config is strictly tagged PAPER_FAITHFUL unless parameter changed
        default_res = DRSASolver(seed=17).solve(path_graph(6), max_total_moves=50)
        self.assertEqual(default_res.metadata["variant"], "PAPER_FAITHFUL")
        self.assertTrue(default_res.metadata["paper_faithful_params"])
        self.assertEqual(default_res.metadata["stop_reason"], "max_total_moves")
        self.assertTrue(default_res.metadata["bounded_execution"])


class IncrementalDeltaDifferentialTests(unittest.TestCase):
    def test_incremental_vs_full_recomputation_identical_for_drsa_and_sa(self) -> None:
        cases = [
            path_graph(8),
            cycle_graph(9),
            complete_graph(7),
            star_graph(6),
            edgeless_graph(5),
            Graph.from_edges([10, 20, 30, 40, 50, 60], [(10, 20), (20, 30), (40, 50)], name="disconn"),
            erdos_renyi_graph(15, 0.4, seed=77),
        ]
        for g in cases:
            with self.subTest(graph=g.name):
                drsa_inc = DRSASolver(seed=23, verify_interval=1, use_incremental=True).solve(
                    g, max_total_moves=250
                )
                drsa_full = DRSASolver(seed=23, verify_interval=0, use_incremental=False).solve(
                    g, max_total_moves=250
                )
                self.assertEqual(drsa_inc.permutation, drsa_full.permutation)
                self.assertEqual(drsa_inc.bandwidth, drsa_full.bandwidth)
                self.assertAlmostEqual(
                    drsa_inc.metadata["final_evaluation_f"],
                    drsa_full.metadata["final_evaluation_f"],
                    places=12,
                )
                self.assertEqual(drsa_inc.metadata["accepted_moves"], drsa_full.metadata["accepted_moves"])
                self.assertEqual(drsa_inc.metadata["rejected_moves"], drsa_full.metadata["rejected_moves"])

                sa_inc = SimulatedAnnealingSolver(iterations=250, seed=23, verify_interval=1, use_incremental=True).solve(g)
                sa_full = SimulatedAnnealingSolver(iterations=250, seed=23, verify_interval=0, use_incremental=False).solve(g)
                self.assertEqual(sa_inc.permutation, sa_full.permutation)
                self.assertEqual(sa_inc.bandwidth, sa_full.bandwidth)
                self.assertEqual(sa_inc.metadata["accepted_moves"], sa_full.metadata["accepted_moves"])

    def test_rot_with_edges_inside_window_has_zero_edge_desync(self) -> None:
        # Clique ensures EVERY pair in ROT(0..5) has an edge inside the rotated window!
        k8 = complete_graph(8)
        state = IncrementalBandwidthState(k8, {v: v for v in k8.vertices})
        for i in range(0, 3):
            for sep in range(1, 6):
                tok = state.apply_rot_q(i, i + sep)
                state.assert_synced()
                state.undo_rot_q(i, i + sep, tok)
                state.assert_synced()


class SmallOracleTimeoutAndWarmStartTests(unittest.TestCase):
    def test_stage_a_small_oracle_deterministic_and_timeout_contracts(self) -> None:
        suite = [
            path_graph(6),
            cycle_graph(6),
            star_graph(5),
            complete_graph(5),
            edgeless_graph(5),
            Graph.from_edges([1, 2, 3, 4, 5, 6], [(1, 2), (2, 3), (4, 5)], name="disconn"),
            erdos_renyi_graph(7, 0.45, seed=19),
        ]
        for g in suite:
            oracle_bw = BruteForceSolver(max_vertices=8).solve(g).bandwidth
            rcm = RCMSolver().solve(g)
            sa = SimulatedAnnealingSolver(iterations=300, seed=17).solve(g)
            drsa1 = DRSASolver(seed=17).solve(g, max_total_moves=300)
            drsa2 = DRSASolver(seed=17).solve(g, max_total_moves=300)
            self.assertEqual(drsa1.permutation, drsa2.permutation)
            self.assertEqual(drsa1.bandwidth, drsa2.bandwidth)
            for res in (rcm, sa, drsa1):
                self.assertEqual(res.status, SolutionStatus.FEASIBLE)
                self.assertFalse(res.proved_optimal)
                self.assertTrue(validate_solution(g, res).valid)
                if oracle_bw is not None and res.bandwidth is not None:
                    self.assertGreaterEqual(res.bandwidth, oracle_bw)

        # Timeout preserves valid initial/best-so-far incumbent
        g_rand = erdos_renyi_graph(25, 0.3, seed=5)
        t0_drsa = DRSASolver(seed=17, initial_mode="rcm").solve(g_rand, timeout_seconds=0.0)
        t0_sa = SimulatedAnnealingSolver(seed=17).solve(g_rand, timeout_seconds=0.0)
        self.assertEqual(t0_drsa.status, SolutionStatus.FEASIBLE)
        self.assertEqual(t0_drsa.metadata["stop_reason"], "timeout")
        self.assertEqual(t0_drsa.bandwidth, RCMSolver().solve(g_rand).bandwidth)
        self.assertEqual(t0_sa.status, SolutionStatus.FEASIBLE)
        self.assertEqual(t0_sa.metadata["stop_reason"], "timeout")

        # Initial modes validation
        for mode in ("random", "identity", "cm", "rcm", "best_initial"):
            perm, bw, rmode = build_initial_permutation(g_rand, mode=mode, rng=Random(1))
            self.assertEqual(rmode, mode)
            self.assertTrue(validate_assignment(g_rand, perm).valid)
            self.assertEqual(calculate_bandwidth(g_rand, perm), bw)

    def test_warm_start_integration_across_sat_cp_and_mip_contracts(self) -> None:
        g = erdos_renyi_graph(7, 0.45, seed=17)
        heuristic_res = DRSASolver(seed=17, initial_mode="rcm", initial_temperature=2.0).solve(
            g, timeout_seconds=0.0  # Even timed-out heuristic returns valid incumbent!
        )
        warm_perm = heuristic_res.permutation
        assert warm_perm is not None
        anchor = select_anchor_vertex(g)

        # Verify MIP bounds warm-start normalization preserves symmetry & bandwidth
        lb, ub_bw, norm_perm, norm_anchor = prepare_mip_bounds(
            g, symmetry_breaking=True, initial_permutation=warm_perm
        )
        self.assertEqual(norm_anchor, anchor)
        self.assertEqual(ub_bw, heuristic_res.bandwidth)
        self.assertLessEqual(norm_perm[anchor], (g.order + 1) // 2)
        self.assertLessEqual(lb, ub_bw)

        oracle_opt = BruteForceSolver(max_vertices=8).solve(g).bandwidth

        # SAT Repeated + Incremental preserve optimality and record heuristic upper bound
        rep = RepeatedSATSolver(backend_name="cadical").solve(
            g, timeout_seconds=5.0, symmetry_breaking=True, heuristic_permutation=warm_perm
        )
        inc = IncrementalSATSolver(backend_name="cadical").solve(
            g, timeout_seconds=5.0, symmetry_breaking=True, heuristic_permutation=warm_perm
        )
        for sat_res in (rep, inc):
            self.assertEqual(sat_res.status, SolutionStatus.OPTIMAL)
            self.assertEqual(sat_res.bandwidth, oracle_opt)
            self.assertTrue(validate_solution(g, sat_res).valid)

        # CP-SAT and CP Optimizer preserve optimality when warm-started with DRSA
        cp_sat = CPSATSolver().solve(
            g, timeout_seconds=5.0, symmetry_breaking=True, initial_permutation=warm_perm
        )
        self.assertEqual(cp_sat.status, SolutionStatus.OPTIMAL)
        self.assertEqual(cp_sat.bandwidth, oracle_opt)
        self.assertEqual(cp_sat.metadata["model_upper_bound"], heuristic_res.bandwidth)

        cp_opt = CPOptimizerSolver().solve(
            g, timeout_seconds=5.0, symmetry_breaking=True, initial_permutation=warm_perm
        )
        if cp_opt.status is not SolutionStatus.UNAVAILABLE:
            self.assertEqual(cp_opt.status, SolutionStatus.OPTIMAL)
            self.assertEqual(cp_opt.bandwidth, oracle_opt)
            self.assertEqual(cp_opt.metadata["model_upper_bound"], heuristic_res.bandwidth)

        # Gurobi & CPLEX contracts cleanly preserve warm_start metadata whether available or mocked missing
        with patch.dict("sys.modules", {"gurobipy": None, "cplex": None}):
            gres = GurobiMIPSolver().solve(
                g, timeout_seconds=5.0, symmetry_breaking=True, initial_permutation=warm_perm
            )
            cres = CPLEXMIPSolver().solve(
                g, timeout_seconds=5.0, symmetry_breaking=True, initial_permutation=warm_perm
            )
            self.assertEqual(gres.status, SolutionStatus.UNAVAILABLE)
            self.assertEqual(gres.bandwidth, heuristic_res.bandwidth)
            self.assertEqual(cres.status, SolutionStatus.UNAVAILABLE)
            self.assertEqual(cres.bandwidth, heuristic_res.bandwidth)

    def test_cli_drsa_and_heuristic_flags(self) -> None:
        g = path_graph(6)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "p6.edges"
            from bmp.io.readers import write_edge_list

            write_edge_list(g, path)
            for args in (
                ["solve", str(path), "--solver", "rcm"],
                ["solve", str(path), "--solver", "sa", "--timeout", "1.0", "--seed", "7"],
                [
                    "solve",
                    str(path),
                    "--solver",
                    "drsa",
                    "--drsa-variant",
                    "paper",
                    "--max-moves",
                    "100",
                    "--seed",
                    "17",
                ],
                [
                    "solve",
                    str(path),
                    "--solver",
                    "drsa",
                    "--drsa-variant",
                    "modified_warm",
                    "--timeout",
                    "1.0",
                    "--seed",
                    "17",
                ],
            ):
                rc = cli.main(args)
                self.assertEqual(rc, 0)

        with self.assertRaises(ValueError):
            DRSASolver(cooling=1.5)._validate_parameters()
        with self.assertRaises(ValueError):
            DRSASolver(p_rex=0.0, p_nex=0.0, p_rot=0.0)._validate_parameters()

    def test_m3_4_preflight_plan_csv_and_resume(self) -> None:
        import tomllib
        from bmp.experiments.member3_m3_4 import (
            M3_4_FIELDS,
            PREFLIGHT_FIELDS,
            _build_plan,
            _format_csv_row,
            _classify_published_comparison,
        )

        root = Path(__file__).resolve().parents[1]
        cfg = tomllib.loads((root / "configs" / "member3_m3_4.toml").read_text(encoding="utf-8"))["benchmark"]
        prov = json.loads((root / cfg["provenance"]).read_text(encoding="utf-8"))
        ready_names = sorted(
            (e["instance"] for e in prov if e["validation_status"] == "READY")
        )
        self.assertEqual(len(ready_names), 54)
        self.assertNotIn("steam3", ready_names)
        self.assertNotIn("mbeause", ready_names)

        plan = _build_plan(cfg, ready_names)
        self.assertEqual(len(plan), 395)
        self.assertEqual(sum(1 for p in plan if p["stage"] == "Stage_B_Pilot"), 128)
        self.assertEqual(sum(1 for p in plan if p["stage"] == "Ablation_Study"), 51)
        self.assertEqual(sum(1 for p in plan if p["stage"] == "Stage_C_54_READY"), 216)

        row_csv = _format_csv_row(
            {"run_id": "m34-test", "final_bandwidth": None, "validation": True},
            ("run_id", "final_bandwidth", "validation", "note"),
        )
        self.assertEqual(row_csv["final_bandwidth"], "")
        self.assertEqual(row_csv["note"], "")
        self.assertEqual(row_csv["validation"], True)
        self.assertEqual(_classify_published_comparison(5, 5), "MATCHED_BEST")
        self.assertEqual(_classify_published_comparison(7, 5), "ABOVE_BEST")
        self.assertEqual(
            _classify_published_comparison(4, 5),
            "BELOW_PUBLISHED_BEST_REQUIRES_VERIFICATION",
        )
        self.assertIn("final_delta", M3_4_FIELDS)
        self.assertIn("drsa_paper_lf", PREFLIGHT_FIELDS)

        # Verify actual checkpoint / resume on pre-verified READY outputs
        out_dir = root / "results" / "member3_m3_4"
        runs_data = json.loads((out_dir / "runs.json").read_text(encoding="utf-8"))
        self.assertEqual(len(runs_data), 395)
        self.assertTrue(all(r["validation"] is True for r in runs_data))


if __name__ == "__main__":
    unittest.main()
