"""End-to-end smoke check for the Member 2 result export."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from bmp.core.generators import cycle_graph
from bmp.core.solution import SolutionStatus
from bmp.experiments.member2 import run_config
from bmp.solvers.exact.cplex import CPLEXMIPSolver
from bmp.solvers.exact.gurobi import GurobiMIPSolver


ROOT = Path(__file__).resolve().parents[1]


class Member2RunnerTests(unittest.TestCase):
    def test_one_graph_exports_all_studies(self) -> None:
        instance = (ROOT / "data/samples/cycle_c4.edgelist").as_posix()
        probe = cycle_graph(4)
        gurobi_available = GurobiMIPSolver().solve(probe, timeout_seconds=2).status is not SolutionStatus.UNAVAILABLE
        cplex_available = CPLEXMIPSolver().solve(probe, timeout_seconds=2).status is not SolutionStatus.UNAVAILABLE

        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            config = directory / "benchmark.toml"
            config.write_text(
                '[benchmark]\n'
                f'instances = ["{instance}"]\n'
                'output_dir = "output"\n'
                'timeout_seconds = 5.0\n'
                'repetitions = 1\n'
                'amo = ["pairwise", "sequential", "binary", "commander"]\n',
                encoding="utf-8",
            )
            rows, summary = run_config(config)
            self.assertEqual(len(rows), 15)
            self.assertEqual(len(summary), 15)
            self.assertEqual({row["study"] for row in rows}, {
                "sat_strategy", "amo", "solver_comparison", "mip_strengthening",
            })

            for row in rows:
                solver = row["solver"]
                if solver in ("glucose", "cadical", "brute-force"):
                    self.assertEqual(row["status"], "OPTIMAL", row)
                    self.assertIs(row["validation"], True, row)
                    self.assertEqual(row["bandwidth"], 2, row)
                elif solver == "gurobi":
                    if gurobi_available:
                        self.assertEqual(row["status"], "OPTIMAL", row)
                        self.assertIs(row["validation"], True, row)
                        self.assertEqual(row["bandwidth"], 2, row)
                    else:
                        self.assertEqual(row["status"], "UNAVAILABLE", row)
                        self.assertTrue(row["error"], row)
                elif solver == "cplex":
                    if cplex_available:
                        self.assertEqual(row["status"], "OPTIMAL", row)
                        self.assertIs(row["validation"], True, row)
                        self.assertEqual(row["bandwidth"], 2, row)
                    else:
                        self.assertEqual(row["status"], "UNAVAILABLE", row)
                        self.assertTrue(row["error"], row)

            with (directory / "output/runs.csv").open(newline="", encoding="utf-8") as source:
                csv_rows = list(csv.DictReader(source))
            self.assertEqual(len(csv_rows), 15)
            self.assertIn("sat_calls", csv_rows[0])
            self.assertIn("peak_memory_mb", csv_rows[0])
            self.assertIn("incumbent_source", csv_rows[0])
            self.assertEqual(len(json.loads((directory / "output/runs.json").read_text())), 15)
            self.assertTrue((directory / "output/summary.json").exists())
            self.assertTrue((directory / "output/metadata.json").exists())


if __name__ == "__main__":
    unittest.main()
