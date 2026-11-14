"""CLI entrypoint for Phase M3.9 Full 113-Instance MiniSat22 Benchmark Campaign."""

from __future__ import annotations

from pathlib import Path

from bmp.experiments.member3_m3_9 import run_m3_9_full113


if __name__ == "__main__":
    summary = run_m3_9_full113(
        output_dir=Path("results/member3_m3_9_minisat_full113"),
        resume=True,
    )
    print("M3.9 Table Summary:")
    for row in summary["table_summary"]:
        print(" ", row)
