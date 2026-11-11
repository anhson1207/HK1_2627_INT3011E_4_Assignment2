"""Regression and forensic test suite for Phase M3.5 (Harwell-Boeing Dataset Fidelity)."""

from __future__ import annotations

import csv
import gzip
from hashlib import sha256
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from contextlib import redirect_stdout

from bmp.cli import main as cli_main
from bmp.core.benchmark_catalog import (
    ALL_INSTANCES,
    VALIDATOR_VERSION,
    audit_raw_copy_parity,
    resolve_raw_matrix_path,
)
from bmp.core.graph import Graph, GraphInstance
from bmp.core.solution import SolutionStatus
from bmp.core.validation import validate_solution
from bmp.data import HarwellBoeingDataset, compare_matrix_market_conversions, load_provenance_index
from bmp.encodings.cardinality import (
    BinaryAMOEncoder,
    ProductAMOEncoder,
    SequentialCounterAMOEncoder,
)
from bmp.encodings.order import OrderEncoding
from bmp.encodings.pairwise import PairwiseEncoding
from bmp.heuristics import DRSASolver, RCMSolver, SimulatedAnnealingSolver
from bmp.io.readers import (
    CONVERSION_VERSION,
    OFFICIAL_CONVERSION_POLICY,
    compute_graph_fingerprint,
    compute_topology_sha256,
    convert_matrix_market,
    graph_from_matrix_market_forensics,
    inspect_matrix_market,
    inspect_matrix_market_forensics,
    read_edge_list,
    read_matrix_market,
)
from bmp.solvers.brute_force import BruteForceSolver
from bmp.solvers.exact import CPLEXMIPSolver, CPOptimizerSolver, CPSATSolver, GurobiMIPSolver
from bmp.solvers.sat import IncrementalSATSolver, RepeatedSATSolver

ROOT = Path(__file__).resolve().parents[1]


class Member3M35ForensicsTests(unittest.TestCase):
    def test_provenance_and_raw_sha256_integrity(self) -> None:
        prov_path = ROOT / "data" / "benchmark_provenance.json"
        entries = json.loads(prov_path.read_text(encoding="utf-8"))
        self.assertEqual(len(entries), 113)
        for row in entries:
            raw = ROOT / row["file_path"]
            self.assertTrue(raw.is_file(), f"Missing raw archive {raw}")
            actual_sha = sha256(raw.read_bytes()).hexdigest()
            self.assertEqual(actual_sha, row["sha256"], f"SHA-256 mismatch on {row['instance']}")

        # Tampering detection via temporary copy
        with TemporaryDirectory() as tmp:
            bad = Path(tmp) / "fake.mtx.gz"
            bad.write_bytes(gzip.compress(b"%%MatrixMarket matrix coordinate pattern symmetric\n2 2 1\n1 2\n"))
            self.assertNotEqual(sha256(bad.read_bytes()).hexdigest(), entries[0]["sha256"])

    def test_canonical_fingerprint_determinism_and_sensitivity(self) -> None:
        g1 = Graph.from_edges((1, 2, 3, 4), [(1, 2), (2, 3)], name="p")
        g0 = Graph.from_edges((0, 1, 2, 3), [(0, 1), (1, 2)], name="p0")
        self.assertEqual(compute_topology_sha256(g1), compute_topology_sha256(g0))
        self.assertEqual(
            compute_graph_fingerprint(g1, conversion_policy="nonzero_union"),
            compute_graph_fingerprint(g0, conversion_policy="nonzero_union"),
        )

        # Sensitivity to vertex addition/removal, edge edit, vertex reorder, and policy change
        g_more_iso = Graph.from_edges((1, 2, 3, 4, 5), [(1, 2), (2, 3)], name="p")
        g_less_v = Graph.from_edges((1, 2, 3), [(1, 2), (2, 3)], name="p")
        g_edge_add = Graph.from_edges((1, 2, 3, 4), [(1, 2), (2, 3), (3, 4)], name="p")
        g_reordered = Graph.from_edges((4, 3, 2, 1), [(1, 2), (2, 3)], name="p")

        base_fp = compute_graph_fingerprint(g1, conversion_policy="nonzero_union")
        self.assertNotEqual(base_fp, compute_graph_fingerprint(g_more_iso, conversion_policy="nonzero_union"))
        self.assertNotEqual(base_fp, compute_graph_fingerprint(g_less_v, conversion_policy="nonzero_union"))
        self.assertNotEqual(base_fp, compute_graph_fingerprint(g_edge_add, conversion_policy="nonzero_union"))
        self.assertNotEqual(base_fp, compute_graph_fingerprint(g_reordered, conversion_policy="nonzero_union"))
        self.assertNotEqual(base_fp, compute_graph_fingerprint(g1, conversion_policy="stored_union"))

        # Consistency across all raw directory copies + .edgelist for bcspwr01
        raw_path = resolve_raw_matrix_path("bcspwr01", root=ROOT)
        self.assertIsNotNone(raw_path)
        assert raw_path is not None
        g_raw = read_matrix_market(raw_path)
        g_hb = HarwellBoeingDataset(ROOT / "data/harwell_boeing", provenance_path=ROOT / "data/benchmark_provenance.json").load("bcspwr01")
        g_edge = read_edge_list(ROOT / "data/hb_table6_7/graphs/bcspwr01.edgelist")
        g_audit = inspect_matrix_market(raw_path).graph
        self.assertEqual(g_raw.metadata["graph_fingerprint"], g_hb.metadata["graph_fingerprint"])
        self.assertEqual(g_raw.metadata["topology_sha256"], compute_topology_sha256(g_edge))
        self.assertEqual(g_raw.metadata["topology_sha256"], compute_topology_sha256(g_audit))

    def test_general_vs_symmetric_and_skew_symmetric_parsing(self) -> None:
        with TemporaryDirectory() as tmp:
            sym_p = Path(tmp) / "sym.mtx"
            sym_p.write_text(
                "%%MatrixMarket matrix coordinate real symmetric\n"
                "3 3 3\n"
                "1 1 5.0\n"
                "2 1 1.0\n"
                "3 2 -2.0\n",
                encoding="utf-8",
            )
            skew_p = Path(tmp) / "skew.mtx"
            skew_p.write_text(
                "%%MatrixMarket matrix coordinate real skew-symmetric\n"
                "3 3 2\n"
                "2 1 3.0\n"
                "3 2 -4.0\n",
                encoding="utf-8",
            )
            gen_sym_p = Path(tmp) / "gen_sym.mtx"
            gen_sym_p.write_text(
                "%%MatrixMarket matrix coordinate real general\n"
                "3 3 4\n"
                "1 2 1.0\n"
                "2 1 -9.0\n"
                "2 3 2.0\n"
                "3 2 2.0\n",
                encoding="utf-8",
            )
            gen_asym_p = Path(tmp) / "gen_asym.mtx"
            gen_asym_p.write_text(
                "%%MatrixMarket matrix coordinate real general\n"
                "3 3 2\n"
                "1 2 1.0\n"
                "2 3 1.0\n",
                encoding="utf-8",
            )
            for ready_p in (sym_p, skew_p, gen_sym_p):
                self.assertEqual(inspect_matrix_market(ready_p).status, "READY")
                g = convert_matrix_market(ready_p, policy="nonzero_union", require_official=True)
                self.assertEqual(g.edges, frozenset({(1, 2), (2, 3)}))
                self.assertTrue(g.metadata["official_benchmark_graph"])
            self.assertEqual(inspect_matrix_market(gen_asym_p).status, "NEEDS_VERIFICATION")
            self.assertEqual(inspect_matrix_market_forensics(gen_asym_p).asymmetric_pairs_nonzero, 2)

    def test_explicit_zero_intersection_triangular_duplicates_and_diagonals(self) -> None:
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "zeros_dups_diag.mtx"
            p.write_text(
                "%%MatrixMarket matrix coordinate real general\n"
                "4 4 8\n"
                "1 1 0.0\n"
                "2 2 9.0\n"
                "1 2 2.0\n"
                "2 1 0.0\n"
                "3 1 4.0\n"
                "1 3 5.0\n"
                "4 2 7.0\n"
                "4 2 8.0\n",
                encoding="utf-8",
            )
            f = inspect_matrix_market_forensics(p)
            self.assertEqual(f.diagonal_entries_total, 2)
            self.assertEqual(f.diagonal_entries_zero, 1)
            self.assertEqual(f.diagonal_entries_nonzero, 1)
            self.assertEqual(f.offdiagonal_entries_zero, 1)
            self.assertEqual(f.duplicate_offdiagonal_nonzero, 1)
            self.assertEqual(f.status, "NEEDS_VERIFICATION")

            g_nz_u = graph_from_matrix_market_forensics(f, policy="nonzero_union")
            g_st_u = graph_from_matrix_market_forensics(f, policy="stored_union")
            g_nz_i = graph_from_matrix_market_forensics(f, policy="nonzero_intersection")
            g_st_i = graph_from_matrix_market_forensics(f, policy="stored_intersection")
            g_low = graph_from_matrix_market_forensics(f, policy="triangular_lower")
            g_upp = graph_from_matrix_market_forensics(f, policy="triangular_upper")

            self.assertEqual(g_nz_u.edges, frozenset({(1, 2), (1, 3), (2, 4)}))
            self.assertEqual(g_st_u.edges, frozenset({(1, 2), (1, 3), (2, 4)}))
            self.assertEqual(g_nz_i.edges, frozenset({(1, 3)}))
            self.assertEqual(g_st_i.edges, frozenset({(1, 2), (1, 3)}))
            self.assertEqual(g_low.edges, frozenset({(1, 3), (2, 4)}))
            self.assertEqual(g_upp.edges, frozenset({(1, 2), (1, 3)}))

            # Separate case where explicit zero creates an extra union edge not in nonzero_union
            p2 = Path(tmp) / "extra_zero.mtx"
            p2.write_text(
                "%%MatrixMarket matrix coordinate real general\n"
                "3 3 2\n"
                "1 2 1.0\n"
                "2 3 0.0\n",
                encoding="utf-8",
            )
            g2_nz = convert_matrix_market(p2, policy="nonzero_union")
            g2_st = convert_matrix_market(p2, policy="stored_union")
            self.assertEqual(g2_nz.edges, frozenset({(1, 2)}))
            self.assertEqual(g2_st.edges, frozenset({(1, 2), (2, 3)}))

    def test_disconnected_and_isolated_vertex_optimal_bandwidth_invariance(self) -> None:
        oracle = BruteForceSolver()
        base_graphs = [
            Graph.from_edges([1, 2, 3], [(1, 2), (2, 3), (1, 3)], name="K3"),
            Graph.from_edges([1, 2, 3, 4], [(1, 2), (3, 4)], name="disjoint_2K2"),
        ]
        for g in base_graphs:
            g_iso = Graph.from_edges(tuple(g.vertices) + (5, 6), g.edges, name=f"{g.name}_iso")
            self.assertEqual(g_iso.order, g.order + 2)
            self.assertEqual(oracle.solve(g).bandwidth, oracle.solve(g_iso).bandwidth)

    def test_exploratory_conversion_isolation_and_ready_filtering(self) -> None:
        raw_steam3 = resolve_raw_matrix_path("steam3", root=ROOT)
        self.assertIsNotNone(raw_steam3)
        assert raw_steam3 is not None

        with self.assertRaisesRegex(ValueError, "refused non-official"):
            convert_matrix_market(raw_steam3, policy="stored_union", require_official=True)
        with self.assertRaisesRegex(ValueError, "refused non-official"):
            convert_matrix_market(raw_steam3, policy="nonzero_union", require_official=True)

        exploratory = convert_matrix_market(raw_steam3, policy="stored_union")
        self.assertFalse(exploratory.metadata["official_benchmark_graph"])
        self.assertEqual(exploratory.metadata["conversion_policy"], "stored_union")

        ds = HarwellBoeingDataset(
            ROOT / "data/harwell_boeing",
            provenance_path=ROOT / "data/benchmark_provenance.json",
        )
        with self.assertRaisesRegex(ValueError, "NEEDS_VERIFICATION"):
            ds.load("steam3", require_ready=True)
        with self.assertRaisesRegex(ValueError, "STORED_UNION|stored_union|refused"):
            ds.load("bcspwr01", require_ready=True, conversion_policy="stored_union")

    def test_steam3_and_mbeause_forensic_findings(self) -> None:
        steam3_path = resolve_raw_matrix_path("steam3", root=ROOT)
        assert steam3_path is not None
        diag = compare_matrix_market_conversions(steam3_path)
        self.assertFalse(diag["official_benchmark"])
        self.assertEqual(diag["explicit_off_diagonal_zeros"], 614)
        self.assertAlmostEqual(float(diag["structural_symmetry_stored"]), 1.0, places=6)
        self.assertEqual(diag["variants"]["drop_explicit_zeros"]["m"], 156)
        self.assertEqual(diag["variants"]["keep_explicit_zeros"]["m"], 424)
        self.assertEqual(diag["variants"]["nonzero_intersection"]["m"], 78)

        gA = convert_matrix_market(steam3_path, policy="nonzero_union")
        gB = convert_matrix_market(steam3_path, policy="stored_union")
        cp = CPSATSolver(seed=17)
        dA = DRSASolver(seed=17, initial_mode="rcm", initial_temperature=2.0).solve(gA, timeout_seconds=0.8)
        dB = DRSASolver(seed=17, initial_mode="rcm", initial_temperature=2.0).solve(gB, timeout_seconds=0.8)
        rA = cp.solve(gA, timeout_seconds=30.0, symmetry_breaking=True, threads=4, initial_permutation=dA.permutation)
        rB = cp.solve(gB, timeout_seconds=60.0, symmetry_breaking=True, threads=4, initial_permutation=dB.permutation)
        self.assertEqual(rA.status, SolutionStatus.OPTIMAL)
        self.assertEqual(rA.bandwidth, 5)  # < Published LB=7
        self.assertEqual(rB.bandwidth, 7)  # == Published LB=7 & Best=7
        self.assertIn(rB.status, (SolutionStatus.OPTIMAL, SolutionStatus.FEASIBLE))
        if rB.status is SolutionStatus.OPTIMAL:
            self.assertEqual(rB.lower_bound, 7)

        # Verify recorded full-run forensic summary confirms OPTIMAL bw=7 on stored_union
        summary_path = ROOT / "results/member3_m3_5/summary.json"
        if summary_path.is_file():
            m35_summary = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(m35_summary["steam3_cp_sat"]["stored_union"]["cp_sat_status"], "OPTIMAL")
            self.assertEqual(m35_summary["steam3_cp_sat"]["stored_union"]["cp_sat_bw"], 7)

        # mbeause: n=496 raw vs 492 active nodes (isolated 493..496), equal RCM bandwidth
        mbeause_path = resolve_raw_matrix_path("mbeause", root=ROOT)
        assert mbeause_path is not None
        gm_496 = convert_matrix_market(mbeause_path, policy="nonzero_union")
        self.assertEqual(gm_496.order, 496)
        self.assertEqual(gm_496.size, 36209)
        isolated = [v for v in gm_496.vertices if gm_496.degree(v) == 0]
        self.assertEqual(isolated, [493, 494, 495, 496])
        active = [v for v in gm_496.vertices if gm_496.degree(v) > 0]
        remap = {v: i + 1 for i, v in enumerate(active)}
        gm_492 = Graph.from_edges(
            range(1, 493),
            ((remap[u], remap[v]) for u, v in gm_496.edges),
            name="mbeause_492",
        )
        self.assertEqual(RCMSolver().solve(gm_496).bandwidth, RCMSolver().solve(gm_492).bandwidth)

    def test_provenance_additive_schema_table5_and_duplicates(self) -> None:
        prov = load_provenance_index(ROOT / "data/benchmark_provenance.json")
        self.assertEqual(len(prov), 113)
        self.assertEqual(sum(1 for e in prov.values() if e["validation_status"] == "READY"), 54)
        self.assertEqual(sum(1 for e in prov.values() if e["validation_status"] == "NEEDS_VERIFICATION"), 58)
        self.assertEqual(sum(1 for e in prov.values() if e["validation_status"] == "INVALID_DATA"), 1)

        if "validator_version" in prov["ash85"]:
            self.assertEqual(prov["ash85"]["validator_version"], VALIDATOR_VERSION)
            for inst, entry in prov.items():
                for key in (
                    "conversion_policy",
                    "conversion_version",
                    "graph_fingerprint",
                    "topology_sha256",
                    "evidence_level",
                    "source_confirmation",
                    "unresolved_issues",
                    "last_verified_date",
                    "validator_version",
                ):
                    self.assertIn(key, entry, f"Missing {key} in {inst}")
            self.assertEqual(prov["sherman1"]["topology_duplicate_of"], "saylr3")
            self.assertEqual(prov["mbeaflw"]["topology_duplicate_of"], "mbeacxc")

        # Duplicate topology parity directly on raw graphs
        for a, b in (("mbeacxc", "mbeaflw"), ("saylr3", "sherman1")):
            pa = resolve_raw_matrix_path(a, root=ROOT)
            pb = resolve_raw_matrix_path(b, root=ROOT)
            assert pa is not None and pb is not None
            ga = read_matrix_market(pa)
            gb = read_matrix_market(pb)
            self.assertEqual(ga.metadata["graph_fingerprint"], gb.metadata["graph_fingerprint"])
            self.assertEqual(ga.edges, gb.edges)

        # fs_680_1 discrepancy check: disconnected under nonzero_union, connected under stored_union
        fs680 = resolve_raw_matrix_path("fs_680_1", root=ROOT)
        assert fs680 is not None
        g680_A = convert_matrix_market(fs680, policy="nonzero_union")
        g680_B = convert_matrix_market(fs680, policy="stored_union")
        self.assertGreater(sum(1 for v in g680_A.vertices if g680_A.degree(v) == 0), 0)
        self.assertEqual(sum(1 for v in g680_B.vertices if g680_B.degree(v) == 0), 0)

    def test_cross_method_eight_pipelines_graph_and_fingerprint_equality(self) -> None:
        raw_bcspwr01 = resolve_raw_matrix_path("bcspwr01", root=ROOT)
        assert raw_bcspwr01 is not None
        g_small_ready = read_matrix_market(raw_bcspwr01)
        g_hb = HarwellBoeingDataset(
            ROOT / "data/harwell_boeing",
            provenance_path=ROOT / "data/benchmark_provenance.json",
        ).load("bcspwr01", require_ready=True)
        g_edge = read_edge_list(ROOT / "data/hb_table6_7/graphs/bcspwr01.edgelist")

        self.assertIsInstance(g_small_ready, GraphInstance)
        self.assertEqual(g_small_ready.order, g_hb.order)
        self.assertEqual(g_small_ready.edges, g_hb.edges)
        self.assertEqual(g_small_ready.edges, g_edge.edges)
        self.assertEqual(g_small_ready.metadata["graph_fingerprint"], g_hb.metadata["graph_fingerprint"])
        self.assertEqual(
            compute_topology_sha256(g_small_ready),
            compute_topology_sha256(g_edge),
        )

        # Verify all 8 solver pipelines accept the exact canonical GraphInstance and produce valid results
        # Using a compact 6-vertex READY-style graph for rapid live solves across SAT/MIP/CP/Heuristics,
        # plus direct heuristic + CP-SAT execution on canonical bcspwr01.
        tiny = Graph.from_edges(range(1, 7), [(1, 2), (2, 3), (3, 4), (4, 5), (5, 6), (1, 3)], name="canonical_p6_chord")
        tiny_fp = compute_graph_fingerprint(tiny, conversion_policy=OFFICIAL_CONVERSION_POLICY)

        # 1. Leader SAT (Pairwise + Sequential + CaDiCaL)
        r_leader = RepeatedSATSolver(
            PairwiseEncoding(SequentialCounterAMOEncoder()),
            backend_name="cadical",
        ).solve(tiny, timeout_seconds=5.0)
        # 2. Member 2 SAT (Order + Binary + Glucose) & Member 2 MIP (Gurobi / CPLEX)
        r_m2_sat = IncrementalSATSolver(
            OrderEncoding(BinaryAMOEncoder()),
            backend_name="glucose",
        ).solve(tiny, timeout_seconds=5.0)
        r_gurobi = GurobiMIPSolver().solve(tiny, timeout_seconds=5.0, symmetry_breaking=True, threads=1)
        r_cplex = CPLEXMIPSolver().solve(tiny, timeout_seconds=5.0, symmetry_breaking=True, threads=1)
        # 3. Member 3 SAT (Pairwise + Product + MiniSat)
        r_m3_sat = RepeatedSATSolver(
            PairwiseEncoding(ProductAMOEncoder()),
            backend_name="minisat",
        ).solve(tiny, timeout_seconds=5.0)
        # 4. Member 3 CP-SAT & 5. Member 3 CP Optimizer
        r_cpsat = CPSATSolver(seed=17).solve(tiny, timeout_seconds=5.0, symmetry_breaking=True, threads=1)
        r_cpo = CPOptimizerSolver().solve(tiny, timeout_seconds=5.0, symmetry_breaking=True)
        # 6. RCM, 7. SA, 8. DRSA (also checked directly on canonical bcspwr01!)
        r_rcm = RCMSolver().solve(tiny)
        r_sa = SimulatedAnnealingSolver(iterations=200, seed=17).solve(tiny)
        r_drsa = DRSASolver(seed=17).solve(tiny, max_total_moves=5000)

        for res in (r_leader, r_m2_sat, r_gurobi, r_cplex, r_m3_sat, r_cpsat, r_cpo, r_rcm, r_sa, r_drsa):
            if res.status is SolutionStatus.UNAVAILABLE:
                continue
            self.assertTrue(validate_solution(tiny, res).valid, f"{res.solver} failed validation")
            if res.status is SolutionStatus.OPTIMAL:
                self.assertEqual(res.bandwidth, 2)

        # Also validate canonical bcspwr01 graph fingerprint parity across M3.2-M3.4 solvers
        bc_rcm = RCMSolver().solve(g_small_ready)
        bc_sa = SimulatedAnnealingSolver(iterations=200, seed=17).solve(g_small_ready)
        bc_drsa = DRSASolver(seed=17, initial_mode="rcm").solve(g_small_ready, max_total_moves=5000)
        bc_cp = CPSATSolver(seed=17).solve(g_small_ready, timeout_seconds=5.0, threads=2, initial_permutation=bc_drsa.permutation)
        for res in (bc_rcm, bc_sa, bc_drsa, bc_cp):
            self.assertTrue(validate_solution(g_small_ready, res).valid)
        self.assertEqual(compute_graph_fingerprint(g_small_ready), compute_graph_fingerprint(g_hb))
        self.assertEqual(compute_topology_sha256(tiny), compute_topology_sha256(Graph.from_edges(tiny.vertices, tiny.edges)))
        self.assertTrue(tiny_fp)

    def test_dataset_copy_parity_and_cli_preflight_m3_5(self) -> None:
        for inst in ("bcspwr01", "steam3", "ash85"):
            parity = audit_raw_copy_parity(inst, root=ROOT)
            self.assertTrue(parity["raw_parity_ok"])
            self.assertTrue(parity["edgelist_matches_nonzero_union"])
            self.assertGreaterEqual(parity["copy_count"], 2)

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli_main(["preflight-benchmark", "--dir", str(ROOT / "data/benchmarks/raw"), "--table", "all"])
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["total_expected"], 113)
        self.assertEqual(payload["found_count"], 113)
        self.assertEqual(payload["validator_version"], VALIDATOR_VERSION)
        self.assertEqual(payload["official_conversion_policy"], OFFICIAL_CONVERSION_POLICY)
        self.assertEqual(payload["conversion_version"], CONVERSION_VERSION)


if __name__ == "__main__":
    unittest.main()
