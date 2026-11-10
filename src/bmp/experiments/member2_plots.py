"""Create Member 2 figures from measured benchmark CSVs using cnsplots."""

from __future__ import annotations

import argparse
import csv
import statistics
from collections import defaultdict
from pathlib import Path


def _aggregate(rows: list[dict[str, str]], study: str) -> list[dict[str, object]]:
    samples: dict[tuple[str, str], list[float]] = defaultdict(list)
    active_sat_instances = {
        row["instance"]
        for row in rows
        if row.get("study") == "sat_strategy"
        and row.get("solver") == "glucose"
        and row.get("encoding") == "pairwise"
        and row.get("strategy") == "repeated"
        and int(row.get("sat_calls") or 0) > 0
    }
    for row in rows:
        if row["status"] != "OPTIMAL" or row.get("validation") != "True":
            continue
        if row["solver"] == "glucose" and int(row.get("sat_calls") or 0) == 0:
            continue
        if study == "sat_vs_mip":
            if row["instance"] not in active_sat_instances:
                continue
            if (
                row.get("study") == "sat_strategy"
                and row.get("encoding") == "pairwise"
                and row.get("strategy") == "repeated"
            ):
                method = "Glucose"
            elif row.get("study") == "solver_comparison" and row["solver"] in ("gurobi", "cplex"):
                method = row["solver"].upper()
            else:
                continue
        elif study == "amo":
            if row.get("study") != "amo":
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


def _measured_rows(df, *, require_completed: bool = False):
    """Filter out SKIPPED/RESOURCE_LIMIT/UNAVAILABLE/ERROR so they are never plotted as 0s."""
    allowed = {"OPTIMAL", "FEASIBLE"} if require_completed else {"OPTIMAL", "FEASIBLE", "TIMEOUT"}
    mask = df["status"].isin(allowed) & df["total_wall_time_s"].notna()
    return df[mask].copy()


def create_m2_2_plots(csv_path: Path, out_dir: Path | None = None) -> list[Path]:
    """Generate M2.2 visualization suite from official pilot benchmark CSV using cnsplots."""
    import cnsplots as cns
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import pandas as pd

    df = pd.read_csv(csv_path)
    target_dir = out_dir or (csv_path.parent / "figures")
    target_dir.mkdir(parents=True, exist_ok=True)
    generated: list[Path] = []

    hb_df = df[df["table"].isin(["Table 6", "Table 7", "Table 8"])].copy()
    small_df = df[df["dataset_status"] == "SYNTHETIC_SAMPLE"].copy()

    # 1. Cardinality Encoding vs Runtime (Experiment B, Order Incremental on HB pilot)
    sub_b = _measured_rows(
        hb_df[
            hb_df["experiment"].str.contains("B_cardinality", na=False)
            & (hb_df["encoding"] == "order")
            & (hb_df["strategy"] == "incremental")
        ]
    )
    if not sub_b.empty:
        # Compare across instances with same solver (prefer glucose if present)
        pref_solver = "glucose" if "glucose" in set(sub_b["solver"]) else sub_b["solver"].iloc[0]
        sub_b = sub_b[sub_b["solver"] == pref_solver].copy()
        if not sub_b.empty:
            fig = cns.figure(820, 360, unit="pt")
            ax = fig.add_subplot(111)
            cns.barplot(
                data=sub_b,
                x="instance",
                y="total_wall_time_s",
                hue="amo",
                ax=ax,
            )
            timeout_val = sub_b["timeout_s"].dropna().iloc[0]
            ax.set_title(
                f"Preliminary Pilot: Cardinality AMO vs Wall Time (Order Incremental, {pref_solver}, timeout={timeout_val}s)"
            )
            ax.set_ylabel("Total wall time (s) [capped at timeout]")
            ax.set_xlabel("Table 6 READY Instance")
            out_path = target_dir / "fig1_cardinality_vs_runtime.svg"
            fig.tight_layout()
            cns.savefig(str(out_path), fig=fig)
            plt.close(fig)
            generated.append(out_path)

    # 2. SAT Backend vs Runtime (Experiment A: CaDiCaL vs Glucose)
    sub_a = _measured_rows(
        hb_df[
            hb_df["experiment"].str.contains("A_backend", na=False)
            & (hb_df["encoding"] == "order")
            & (hb_df["strategy"] == "incremental")
        ]
    )
    if not sub_a.empty:
        fig = cns.figure(760, 340, unit="pt")
        ax = fig.add_subplot(111)
        cns.barplot(data=sub_a, x="instance", y="total_wall_time_s", hue="solver", ax=ax)
        timeout_val = sub_a["timeout_s"].dropna().iloc[0]
        ax.set_title(
            f"Preliminary Pilot: SAT Backend Comparison (Order Sequential Incremental, timeout={timeout_val}s)"
        )
        ax.set_ylabel("Total wall time (s)")
        ax.set_xlabel("Table 6 READY Instance")
        out_path = target_dir / "fig2_backend_vs_runtime.svg"
        fig.tight_layout()
        cns.savefig(str(out_path), fig=fig)
        plt.close(fig)
        generated.append(out_path)

    # 3. Repeated vs Incremental SAT (Experiment C)
    sub_c = _measured_rows(hb_df[hb_df["experiment"].str.contains("C_strategy", na=False)])
    if not sub_c.empty:
        sub_c["solver_strategy"] = sub_c["solver"].astype(str) + "_" + sub_c["strategy"].astype(str)
        fig = cns.figure(820, 350, unit="pt")
        ax = fig.add_subplot(111)
        cns.barplot(data=sub_c, x="instance", y="total_wall_time_s", hue="solver_strategy", ax=ax)
        timeout_val = sub_c["timeout_s"].dropna().iloc[0]
        ax.set_title(
            f"Preliminary Pilot: Repeated vs Incremental SAT (Order Sequential, timeout={timeout_val}s)"
        )
        ax.set_ylabel("Total wall time (s)")
        ax.set_xlabel("Table 6 READY Instance")
        out_path = target_dir / "fig3_strategy_repeated_vs_incremental.svg"
        fig.tight_layout()
        cns.savefig(str(out_path), fig=fig)
        plt.close(fig)
        generated.append(out_path)

    # 4. Pairwise vs Order (Experiment D)
    sub_d = _measured_rows(hb_df[hb_df["experiment"].str.contains("D_encoding", na=False)])
    if not sub_d.empty:
        sub_d["solver_encoding"] = sub_d["solver"].astype(str) + "_" + sub_d["encoding"].astype(str)
        fig = cns.figure(820, 350, unit="pt")
        ax = fig.add_subplot(111)
        cns.barplot(
            data=sub_d, x="instance", y="total_wall_time_s", hue="solver_encoding", ax=ax
        )
        timeout_val = sub_d["timeout_s"].dropna().iloc[0]
        ax.set_title(
            f"Preliminary Pilot: Pairwise vs Order Encoding (Sequential Incremental, timeout={timeout_val}s; missing bars=RESOURCE_LIMIT/SKIPPED)"
        )
        ax.set_ylabel("Total wall time (s)")
        ax.set_xlabel("Table 6 READY Instance")
        out_path = target_dir / "fig4_encoding_pairwise_vs_order.svg"
        fig.tight_layout()
        cns.savefig(str(out_path), fig=fig)
        plt.close(fig)
        generated.append(out_path)

    # 5. Gurobi vs CPLEX (Experiment E - fair subset where BOTH actually ran & solved/timed out)
    sub_e = _measured_rows(
        df[
            df["experiment"].str.contains("E_mip", na=False)
            & df["solver"].isin(["gurobi", "cplex"])
            & (df["symmetry_breaking"].astype(str).str.lower() == "true")
        ]
    )
    if not sub_e.empty:
        counts = sub_e.groupby("instance")["solver"].nunique()
        both_instances = counts[counts == 2].index.tolist()
        fair_e = sub_e[sub_e["instance"].isin(both_instances)].copy()
        if not fair_e.empty:
            fair_e["runtime_ms"] = fair_e["total_wall_time_s"] * 1000.0
            fig = cns.figure(820, 350, unit="pt")
            ax = fig.add_subplot(111)
            cns.barplot(data=fair_e, x="instance", y="runtime_ms", hue="solver", ax=ax)
            ax.set_title(
                "Live MIP Comparison: Gurobi vs CPLEX (Identical Formulation, Symmetry Breaking=True, Verified Small Graphs)"
            )
            ax.set_ylabel("Total wall time (ms)")
            ax.set_xlabel("Verified Instance (within CE/Eval variable limits)")
            ax.tick_params(axis="x", labelrotation=20)
            out_path = target_dir / "fig5_gurobi_vs_cplex.svg"
            fig.tight_layout()
            cns.savefig(str(out_path), fig=fig)
            plt.close(fig)
            generated.append(out_path)

    # 6. SAT vs MIP (Experiment F on verified instances with >= 2 distinct method families)
    sub_f = _measured_rows(df[df["experiment"].str.contains("F_sat_vs_mip", na=False)])
    if not sub_f.empty:
        sub_f["runtime_ms"] = sub_f["total_wall_time_s"] * 1000.0
        fig = cns.figure(860, 360, unit="pt")
        ax = fig.add_subplot(111)
        cns.barplot(data=sub_f, x="instance", y="runtime_ms", hue="solver", ax=ax)
        ax.set_yscale("log")
        ax.set_title(
            "SAT vs MIP Comparison (Log-Scale Runtime; Missing MIP bars on n>=48 reflect Evaluation/CE License Caps)"
        )
        ax.set_ylabel("Total wall time (ms, log scale)")
        ax.set_xlabel("Verified Instance")
        ax.tick_params(axis="x", labelrotation=25)
        out_path = target_dir / "fig6_sat_vs_mip.svg"
        fig.tight_layout()
        cns.savefig(str(out_path), fig=fig)
        plt.close(fig)
        generated.append(out_path)

    # 7. CNF Clauses vs Runtime scatter across SAT pilot runs
    sat_hb = _measured_rows(hb_df[hb_df["method"] == "SAT"])
    sat_hb = sat_hb[sat_hb["cnf_clauses"].notna() & (sat_hb["cnf_clauses"] > 0)].copy()
    if not sat_hb.empty:
        fig = cns.figure(760, 360, unit="pt")
        ax = fig.add_subplot(111)
        for status_val, marker in (("OPTIMAL", "o"), ("TIMEOUT", "X"), ("FEASIBLE", "^")):
            part = sat_hb[sat_hb["status"] == status_val]
            if not part.empty:
                ax.scatter(
                    part["cnf_clauses"],
                    part["total_wall_time_s"],
                    label=status_val,
                    marker=marker,
                    s=55,
                    alpha=0.85,
                )
        ax.set_xscale("log")
        ax.set_title("Preliminary Pilot: CNF Clause Count vs Total Wall Time (SAT Runs)")
        ax.set_xlabel("CNF Clauses (log scale)")
        ax.set_ylabel("Total wall time (s)")
        ax.legend(title="Outcome")
        out_path = target_dir / "fig7_cnf_clauses_vs_runtime.svg"
        fig.tight_layout()
        cns.savefig(str(out_path), fig=fig)
        plt.close(fig)
        generated.append(out_path)

    # 8. Outcome Status Breakdown across methods
    if not df.empty:
        status_counts = (
            hb_df.groupby(["method", "solver", "status"]).size().reset_index(name="count")
            if not hb_df.empty
            else df.groupby(["method", "solver", "status"]).size().reset_index(name="count")
        )
        status_counts["solver_status"] = status_counts["status"]
        fig = cns.figure(800, 350, unit="pt")
        ax = fig.add_subplot(111)
        cns.barplot(
            data=status_counts,
            x="solver",
            y="count",
            hue="solver_status",
            ax=ax,
        )
        ax.set_title("Preliminary HB Pilot: Outcome Status Distribution by Solver (Table 6 READY)")
        ax.set_ylabel("Run count")
        ax.set_xlabel("Solver")
        out_path = target_dir / "fig8_status_outcomes.svg"
        fig.tight_layout()
        cns.savefig(str(out_path), fig=fig)
        plt.close(fig)
        generated.append(out_path)

    return generated


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument("--m2-2", action="store_true", help="Generate full M2.2 visualization suite")
    parser.add_argument("--m2-3", action="store_true", help="Generate full M2.3 visualization suite")
    parser.add_argument("--preflight", type=Path, default=None, help="Optional preflight_54.csv path for --m2-3")
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args()
    if args.m2_3:
        from bmp.experiments.member2_m2_3_plots import create_m2_3_plots

        paths = create_m2_3_plots(args.csv, args.preflight, args.out_dir)
    elif args.m2_2:
        paths = create_m2_2_plots(args.csv, args.out_dir)
    else:
        paths = create_plots(args.csv)
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
