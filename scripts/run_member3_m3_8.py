"""Run Phase M3.8 Full 113/113 Instance Coverage Benchmark & Generate Figures."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from bmp.experiments.member3_m3_8 import run_m3_8_full113


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/member3_m3_8.toml"))
    parser.add_argument("--stage", action="append", help="Optional stage filter (repeatable)")
    parser.add_argument("--no-resume", action="store_true", default=False)
    parser.add_argument("--max-batch-seconds", type=float, default=None)
    parser.add_argument("--max-runs", type=int, default=None)
    parser.add_argument("--plots", action="store_true", default=False)
    args = parser.parse_args()

    summary = run_m3_8_full113(
        config_path=args.config,
        stages=set(args.stage) if args.stage else None,
        resume=not args.no_resume,
        max_batch_seconds=args.max_batch_seconds,
        max_runs_in_batch=args.max_runs,
        generate_plots=args.plots,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
