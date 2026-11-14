"""Run Phase M3.5 Harwell-Boeing dataset forensics and generate deliverables."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from bmp.experiments.member3_m3_5 import run_m3_5_forensics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--provenance", type=Path, default=Path("data/benchmark_provenance.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("results/member3_m3_5"))
    parser.add_argument(
        "--update-provenance",
        action="store_true",
        default=False,
        help="Additively enrich benchmark_provenance.json with M3.5 forensic & fingerprint fields.",
    )
    args = parser.parse_args()
    summary = run_m3_5_forensics(
        root=args.root,
        provenance_path=args.provenance,
        output_dir=args.output_dir,
        update_provenance=args.update_provenance,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
