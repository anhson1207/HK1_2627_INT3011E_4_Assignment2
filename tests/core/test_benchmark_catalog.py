from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bmp.core.benchmark_catalog import (
    TABLE_6_INSTANCES,
    TABLE_7_INSTANCES,
    preflight_check_dataset,
    verify_instance_file,
)


class BenchmarkCatalogTests(unittest.TestCase):
    def test_catalog_definitions(self) -> None:
        self.assertIn("bcspwr01", TABLE_6_INSTANCES)
        self.assertEqual(TABLE_6_INSTANCES["bcspwr01"].n, 39)
        self.assertEqual(TABLE_6_INSTANCES["bcspwr01"].paper_lb, 5)

        self.assertIn("pores_1", TABLE_6_INSTANCES)
        self.assertEqual(TABLE_6_INSTANCES["pores_1"].n, 30)

        self.assertIn("494_bus", TABLE_7_INSTANCES)
        self.assertEqual(TABLE_7_INSTANCES["494_bus"].n, 494)

    def test_preflight_on_empty_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report = preflight_check_dataset(Path(tmpdir), TABLE_6_INSTANCES)
            self.assertEqual(report.total_expected, len(TABLE_6_INSTANCES))
            self.assertEqual(report.found_count, 0)
            self.assertEqual(report.missing_count, len(TABLE_6_INSTANCES))
            self.assertFalse(report.ready_for_execution)

    def test_preflight_detects_valid_and_mismatched_instances(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            dir_path = Path(tmpdir)

            # Create a valid pores_1.mtx (n=30)
            valid_content = "%%MatrixMarket matrix coordinate pattern general\n30 30 2\n1 2\n2 1\n"
            (dir_path / "pores_1.mtx").write_text(valid_content, encoding="utf-8")

            # Create a mismatched bcspwr01.mtx (declared n=10 instead of expected 39)
            mismatched_content = "%%MatrixMarket matrix coordinate pattern general\n10 10 2\n1 2\n2 1\n"
            (dir_path / "bcspwr01.mtx").write_text(mismatched_content, encoding="utf-8")

            sub_catalog = {
                "pores_1": TABLE_6_INSTANCES["pores_1"],
                "bcspwr01": TABLE_6_INSTANCES["bcspwr01"],
            }

            report = preflight_check_dataset(dir_path, sub_catalog)
            self.assertEqual(report.total_expected, 2)
            self.assertEqual(report.found_count, 2)
            self.assertEqual(report.valid_count, 1)
            self.assertEqual(report.invalid_count, 1)
            self.assertIn("pores_1", report.verified_instances)
            self.assertFalse(report.ready_for_execution)
            self.assertTrue(any("Vertex count mismatch" in err for err in report.errors))


if __name__ == "__main__":
    unittest.main()
