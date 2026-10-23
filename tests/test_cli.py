from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from bmp.cli import main


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def test_quick_config_runs_and_validates(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main(["run-config", str(PROJECT_ROOT / "configs" / "quick.toml")])
        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "OPTIMAL")
        self.assertEqual(payload["bandwidth"], 1)
        self.assertTrue(payload["validation"]["valid"])


if __name__ == "__main__":
    unittest.main()
