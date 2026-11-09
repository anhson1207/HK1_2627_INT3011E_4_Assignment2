"""Create Member 2 figures from the measured benchmark CSV using cnsplots."""

from __future__ import annotations

import argparse
import csv
import statistics
from collections import defaultdict
from pathlib import Path


def _aggregate(rows: list[dict[str, str]], study: str) -> list[dict[str, object]]:
    samples: dict[tuple[str, str], list[float]] = defaultdict(list)
    active_sat_instances = {
        row["instance"] for row in rows
        if row["study"] == "sat_strategy" and row["solver"] == "glucose"
        and row["encoding"] == "pairwise" and row["strategy"] == "repeated"
        and int(row["sat_calls"] or 0) > 0
    }
    for row in rows:
        if row["status"] != "OPTIMAL" or row["validation"] != "True":
            continue
        if row["solver"] == "glucose" and int(row["sat_calls"] or 0) == 0:
            continue
        if study == "sat_vs_mip":
            if row["instance"] not in active_sat_instances:
                continue
            if row["study"] == "sat_strategy" and row["encoding"] == "pairwise" and row["strategy"] == "repeated":
                method = "Glucose"
            elif row["study"] == "solver_comparison" and row["solver"] in ("gurobi", "cplex"):
                method = row["solver"].upper()
            else:
                continue
        elif study == "amo":
            if row["study"] != "amo":
                continue
            method = row["amo"].title()
        else:
            raise ValueError(study)
        samples[(row["instance"], method)].append(float(row["runtime_total_s"]) * 1000)
    return [
        {"instance": instance, "method": method, "median_runtime_ms": statistics.median(times)}
        for (instance, method), times in sorted(samples.items())
    ]


def create_plots(csv_path: Path) -> list[Path]:
    import cnsplots as cns
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import pandas as pd

    with csv_path.open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))
    output: list[Path] = []
    for study, filename, title in (
        ("sat_vs_mip", "sat_vs_mip.svg", "Glucose versus MIP on sample graphs"),
        ("amo", "amo_comparison.svg", "Pairwise model: AMO variants with Glucose"),
    ):
        data = pd.DataFrame(_aggregate(rows, study))
        if data.empty:
            raise ValueError(f"No valid measured rows for {study}")
        fig = cns.figure(760, 320, unit="pt")
        ax = fig.add_subplot(111)
        cns.barplot(data=data, x="instance", y="median_runtime_ms", hue="method", ax=ax)
        ax.set_title(title)
        ax.set_ylabel("Median total runtime (ms), 3 repetitions")
        ax.set_xlabel("")
        ax.tick_params(axis="x", labelrotation=22)
        fig.tight_layout()
        target = csv_path.parent / filename
        cns.savefig(str(target), fig=fig)
        plt.close(fig)
        output.append(target)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    args = parser.parse_args()
    for path in create_plots(args.csv):
        print(path)


if __name__ == "__main__":
    main()
