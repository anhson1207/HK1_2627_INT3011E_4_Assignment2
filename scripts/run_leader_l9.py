#!/usr/bin/env python3
"""CLI entrypoint for running Leader Phase L9 Full 113/113 SAT Benchmark & Figures."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from bmp.experiments.leader_l9 import run_l9_campaign


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Leader Phase L9 Full 113/113 Harwell-Boeing SAT evaluation with checkpoint/resume."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/leader_l9_full113.toml"),
        help="Path to TOML config (default: configs/leader_l9_full113.toml)",
    )
    parser.add_argument(
        "--stages",
        type=str,
        default="",
        help="Comma-separated stage filter (e.g. BASELINE_L8,ABLATION_ENCODING).",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Ignore existing checkpoint_runs.json and run fresh.",
    )
    parser.add_argument(
        "--max-batch-seconds",
        type=float,
        default=None,
        help="Override max_batch_seconds for bounded incremental execution.",
    )
    parser.add_argument(
        "--max-runs",
        type=int,
        default=None,
        help="Maximum number of uncached SAT runs to execute in this invocation.",
    )
    parser.add_argument(
        "--plots",
        action="store_true",
        help="Generate all 12 SVG plots into <output_dir>/figures after exporting reports.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    stages = {s.strip() for s in args.stages.split(",") if s.strip()} if args.stages else None
    summary = run_l9_campaign(
        config_path=args.config,
        stages=stages,
        resume=not args.no_resume,
        max_batch_seconds=args.max_batch_seconds,
        max_runs_in_batch=args.max_runs,
        generate_plots=args.plots,
    )
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
