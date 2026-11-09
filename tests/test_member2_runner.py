"""End-to-end smoke check for the Member 2 result export."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from bmp.experiments.member2 import run_config


ROOT = Path(__file__).resolve().parents[1]


class Member2RunnerTests(unittest.TestCase):
    def test_one_graph_exports_all_studies(self) -> None:
        instance = (ROOT / "data/samples/cycle_c4.edgelist").as_posix()
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
            self.assertTrue(all(row["status"] == "OPTIMAL" for row in rows))
            self.assertTrue(all(row["validation"] is True for row in rows))
            self.assertTrue(all(row["bandwidth"] == 2 for row in rows))
            with (directory / "output/runs.csv").open(newline="", encoding="utf-8") as source:
                csv_rows = list(csv.DictReader(source))
            self.assertEqual(len(csv_rows), 15)
            self.assertIn("sat_calls", csv_rows[0])
            self.assertEqual(len(json.loads((directory / "output/runs.json").read_text())), 15)


if __name__ == "__main__":
    unittest.main()
