"""Phase M2.3 cnsplots visualization suite for 54-READY preflight, Baseline, and Studies A-G."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any


def _measured_df(df, *, exclude_statuses: tuple[str, ...] = ("RESOURCE_LIMIT", "UNAVAILABLE", "SKIPPED", "ERROR")):
    mask = (~df["status"].isin(exclude_statuses)) & df["total_wall_time_s"].notna()
    return df[mask].copy()


def _save_svg(fig, out_path: Path, generated: list[Path]) -> None:
    import cnsplots as cns
    import matplotlib.pyplot as plt

    fig.tight_layout()
    cns.savefig(str(out_path), fig=fig)
    plt.close(fig)
    generated.append(out_path)


def create_m2_3_plots(
    csv_path: Path,
    preflight_csv_path: Path | None = None,
    out_dir: Path | None = None,
) -> list[Path]:
    """Generate all supported M2.3 figures using cnsplots from measured CSV & 54-READY preflight."""
    import cnsplots as cns
    import matplotlib

    matplotlib.use("Agg")
    matplotlib.rcParams["mathtext.fontset"] = "dejavusans"
    matplotlib.rcParams["mathtext.default"] = "regular"
    matplotlib.rcParams["font.sans-serif"] = ["DejaVu Sans", "Helvetica", "Arial"]
    matplotlib.rcParams["font.cursive"] = ["DejaVu Sans", "sans-serif"]
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker
    import pandas as pd

    df = pd.read_csv(csv_path)
    target_dir = out_dir or (csv_path.parent / "figures")
    target_dir.mkdir(parents=True, exist_ok=True)
    generated: list[Path] = []

    pf_path = preflight_csv_path or (csv_path.parent / "preflight_54.csv")
    pf_df = pd.read_csv(pf_path) if pf_path.exists() else pd.DataFrame()

    hb_df = df[df["dataset_status"] == "READY"].copy()
    small_df = df[df["dataset_status"] == "SYNTHETIC_SAMPLE"].copy()
    base_df = hb_df[hb_df["experiment"].astype(str).str.contains("Baseline_54", na=False)].copy()

    # 1. Baseline 54 outcome / completion rate by vertex size group
    if not base_df.empty:
        def _bin_label(n_val: float) -> str:
            if n_val <= 100:
                return "n<=100 (T6)"
            if n_val <= 250:
                return "101..250 (T6/7/8)"
            if n_val <= 400:
                return "251..400 (T7/8)"
            return "n>400 (T7/8)"

        b1 = base_df.copy()
        b1["size_group"] = b1["n"].map(_bin_label)
        order_bins = ["n<=100 (T6)", "101..250 (T6/7/8)", "251..400 (T7/8)", "n>400 (T7/8)"]
        b1["size_group"] = pd.Categorical(b1["size_group"], categories=order_bins, ordered=True)
        counts = b1.groupby(["size_group", "status"], observed=True).size().reset_index(name="count")
        n_base = len(base_df)
        opt_cnt = int((base_df["status"] == "OPTIMAL").sum())
        fig = cns.figure(840, 380, unit="pt")
        ax = fig.add_subplot(111)
        cns.barplot(data=counts, x="size_group", y="count", hue="status", ax=ax)
        ax.set_title(
            f"Baseline SAT Status by Size Bin (HB 54 READY | N_inst=54 | N_runs={n_base} | timeout=30s | Order+Seq+CaDiCaL+Inc | OPTIMAL={opt_cnt})"
        )
        ax.set_ylabel("Instance count (no imputation of TIMEOUT as solved)")
        ax.set_xlabel("Graph vertex-count group")
        _save_svg(fig, target_dir / "fig1_completion_by_size_group.svg", generated)

    # 2. Study A: Pairwise vs Order (Runtime & Log Clauses)
    sub_a = hb_df[hb_df["experiment"].astype(str).str.contains("Study_A_encoding", na=False)].copy()
    if not sub_a.empty:
        meas_a = _measured_df(sub_a)
        n_inst = sub_a["instance"].nunique()
        n_runs = len(sub_a)
        res_lim_cnt = int((sub_a["status"] == "RESOURCE_LIMIT").sum())
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.5, 4.4))
        if not meas_a.empty:
            cns.barplot(data=meas_a, x="instance", y="total_wall_time_s", hue="encoding", ax=ax1)
            ax1.axhline(30.0, linestyle="--", linewidth=1.0, color="gray", alpha=0.8)
        ax1.set_title("Wall Time (s) [missing pairwise on >85v = RESOURCE_LIMIT]")
        ax1.set_ylabel("Total wall time (s)")
        ax1.set_xlabel("Representative Instance")
        ax1.tick_params(axis="x", labelrotation=20)

        bw_a = _measured_df(sub_a[sub_a["bandwidth"].notna()])
        if not bw_a.empty:
            cns.barplot(data=bw_a, x="instance", y="bandwidth", hue="encoding", ax=ax2)
        ax2.set_title("Best Bandwidth Achieved (lower is better; UNPROVED at 30s)")
        ax2.set_ylabel("Bandwidth incumbent")
        ax2.set_xlabel("Representative Instance")
        ax2.tick_params(axis="x", labelrotation=20)
        fig.suptitle(
            f"Study A – Pairwise vs Order (HB T6/7/8 | N_inst={n_inst} | N_runs={n_runs} | CaDiCaL+Seq+Inc | timeout=30s | RESOURCE_LIMIT={res_lim_cnt})",
            fontsize=10,
        )
        _save_svg(fig, target_dir / "fig2_pairwise_vs_order.svg", generated)

    # 3. Study B: Cardinality AMO comparison
    sub_b = hb_df[hb_df["experiment"].astype(str).str.contains("Study_B_cardinality", na=False)].copy()
    meas_b = _measured_df(sub_b)
    if not meas_b.empty:
        n_inst = sub_b["instance"].nunique()
        n_runs = len(sub_b)
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.2, 4.6))
        cns.barplot(data=meas_b, x="instance", y="total_wall_time_s", hue="amo", ax=ax1)
        ax1.axhline(30.0, linestyle="--", linewidth=1.0, color="gray", alpha=0.8)
        ax1.set_title("Total Wall Time (s) (timeout=30s)")
        ax1.set_ylabel("Wall time (s)")
        ax1.set_xlabel("Representative Instance")
        ax1.tick_params(axis="x", labelrotation=20)

        bw_b = meas_b[meas_b["bandwidth"].notna()].copy()
        if not bw_b.empty:
            cns.barplot(data=bw_b, x="instance", y="bandwidth", hue="amo", ax=ax2)
        ax2.set_title("Achieved Bandwidth by AMO (Order+Glucose+Inc)")
        ax2.set_ylabel("Bandwidth incumbent")
        ax2.set_xlabel("Representative Instance")
        ax2.tick_params(axis="x", labelrotation=20)
        fig.suptitle(
            f"Study B – Cardinality AMO Comparison (HB T6/7/8 | N_inst={n_inst} | N_runs={n_runs} | Order+Glucose+Inc | timeout=30s)",
            fontsize=10,
        )
        _save_svg(fig, target_dir / "fig3_cardinality_amo.svg", generated)

    # 4. Study C: CaDiCaL vs Glucose 4
    sub_c = hb_df[hb_df["experiment"].astype(str).str.contains("Study_C_backend", na=False)].copy()
    meas_c = _measured_df(sub_c)
    if not meas_c.empty:
        n_inst = sub_c["instance"].nunique()
        n_runs = len(sub_c)
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.5, 4.4))
        cns.barplot(data=meas_c, x="instance", y="total_wall_time_s", hue="solver", ax=ax1)
        ax1.axhline(30.0, linestyle="--", linewidth=1.0, color="gray", alpha=0.8)
        ax1.set_title("Wall Time (s) incl. repeated runs on bcspwr01")
        ax1.set_ylabel("Total wall time (s)")
        ax1.set_xlabel("Representative Instance")
        ax1.tick_params(axis="x", labelrotation=20)

        bw_c = meas_c[meas_c["bandwidth"].notna()].copy()
        if not bw_c.empty:
            cns.barplot(data=bw_c, x="instance", y="bandwidth", hue="solver", ax=ax2)
        ax2.set_title("Achieved Bandwidth (CaDiCaL vs Glucose 4)")
        ax2.set_ylabel("Bandwidth incumbent")
        ax2.set_xlabel("Representative Instance")
        ax2.tick_params(axis="x", labelrotation=20)
        fig.suptitle(
            f"Study C – SAT Backend Comparison (HB T6/7/8 | N_inst={n_inst} | N_runs={n_runs} | Order+Seq+Inc | timeout=30s)",
            fontsize=10,
        )
        _save_svg(fig, target_dir / "fig4_cadical_vs_glucose.svg", generated)

    # 5. Study D: Repeated vs Incremental
    sub_d = hb_df[hb_df["experiment"].astype(str).str.contains("Study_D_strategy", na=False)].copy()
    meas_d = _measured_df(sub_d)
    if not meas_d.empty:
        n_inst = sub_d["instance"].nunique()
        n_runs = len(sub_d)
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.5, 4.4))
        cns.barplot(data=meas_d, x="instance", y="total_wall_time_s", hue="strategy", ax=ax1)
        ax1.axhline(30.0, linestyle="--", linewidth=1.0, color="gray", alpha=0.8)
        ax1.set_title("Total Wall Time (s) (timeout=30s)")
        ax1.set_ylabel("Wall time (s)")
        ax1.set_xlabel("Representative Instance")
        ax1.tick_params(axis="x", labelrotation=20)

        bw_d = meas_d[meas_d["bandwidth"].notna()].copy()
        if not bw_d.empty:
            cns.barplot(data=bw_d, x="instance", y="bandwidth", hue="strategy", ax=ax2)
        ax2.set_title("Achieved Bandwidth (Repeated vs Incremental)")
        ax2.set_ylabel("Bandwidth incumbent")
        ax2.set_xlabel("Representative Instance")
        ax2.tick_params(axis="x", labelrotation=20)
        fig.suptitle(
            f"Study D – SAT Strategy (HB T6/7/8 | N_inst={n_inst} | N_runs={n_runs} | CaDiCaL+Order+Seq | timeout=30s)",
            fontsize=10,
        )
        _save_svg(fig, target_dir / "fig5_repeated_vs_incremental.svg", generated)

    # 6. Study F & G: SAT vs MIP (SmallOracle fair subset + HB bcspwr01 licensed)
    sub_fg = _measured_df(
        df[
            df["experiment"].astype(str).str.contains("Study_G_sat_vs_mip|Study_F_mip", na=False)
            & (df["symmetry_breaking"].astype(str).str.lower() == "true")
        ]
    )
    if not sub_fg.empty:
        small_fg = sub_fg[sub_fg["dataset_status"] == "SYNTHETIC_SAMPLE"].copy()
        hb_fg = sub_fg[sub_fg["dataset_status"] == "READY"].copy()
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.2, 4.6))
        if not small_fg.empty:
            small_fg["runtime_ms"] = small_fg["total_wall_time_s"] * 1000.0
            cns.barplot(data=small_fg, x="instance", y="runtime_ms", hue="solver", ax=ax1)
            ax1.set_yscale("log")
            ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda y, _: f"{y:g}"))
            ax1.set_title(
                f"SmallOracle (N_inst={small_fg['instance'].nunique()}, N_runs={len(small_fg)}, sym=True)"
            )
            ax1.set_ylabel("Wall time (ms, log scale)")
            ax1.set_xlabel("Verified Small Graph (n<=14)")
            ax1.tick_params(axis="x", labelrotation=28)
        if not hb_fg.empty:
            cns.barplot(data=hb_fg, x="instance", y="total_wall_time_s", hue="solver", ax=ax2)
            ax2.set_title(
                f"HB Eligible Subset (Gurobi on bcspwr01 n=39; CPLEX & n>=48 BLOCKED_LICENSE)"
            )
            ax2.set_ylabel("Total wall time (s)")
            ax2.set_xlabel("HB READY Instance")
            ax2.tick_params(axis="x", labelrotation=20)
        fig.suptitle(
            "Studies F & G – Live Gurobi vs CPLEX & SAT vs MIP (Licensed Executed Runs Only)",
            fontsize=10,
        )
        _save_svg(fig, target_dir / "fig6_sat_vs_mip.svg", generated)

    # 7. Clauses/Variables vs Runtime scatter (executed HB SAT runs)
    sat_hb = _measured_df(hb_df[hb_df["method"] == "SAT"])
    sat_hb = sat_hb[sat_hb["cnf_clauses"].notna() & (sat_hb["cnf_clauses"] > 0)].copy()
    if not sat_hb.empty:
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.8, 4.4))
        for st_val, marker, color in (("OPTIMAL", "o", "#1b9e77"), ("TIMEOUT", "X", "#d95f02")):
            part = sat_hb[sat_hb["status"] == st_val]
            if not part.empty:
                ax1.scatter(part["cnf_clauses"], part["total_wall_time_s"], label=st_val, marker=marker, c=color, s=48, alpha=0.8)
                ax2.scatter(part["cnf_variables"], part["total_wall_time_s"], label=st_val, marker=marker, c=color, s=48, alpha=0.8)
        ax1.set_xscale("log")
        ax2.set_xscale("log")
        log_fmt = mticker.FuncFormatter(lambda v, _: f"{int(v):,}" if v >= 1 else f"{v:g}")
        ax1.xaxis.set_major_formatter(log_fmt)
        ax2.xaxis.set_major_formatter(log_fmt)
        ax1.xaxis.set_minor_formatter(mticker.NullFormatter())
        ax2.xaxis.set_minor_formatter(mticker.NullFormatter())
        ax1.set_title("CNF Clauses vs Wall Time (s)")
        ax1.set_xlabel("CNF Clauses (log scale)")
        ax1.set_ylabel("Total wall time (s)")
        ax1.legend(title="Status")
        ax2.set_title("CNF Variables vs Wall Time (s)")
        ax2.set_xlabel("CNF Variables (log scale)")
        ax2.set_ylabel("Total wall time (s)")
        ax2.legend(title="Status")
        fig.suptitle(
            f"HB Executed SAT Runs: Formula Size vs Wall Time (N_inst={sat_hb['instance'].nunique()} | N_runs={len(sat_hb)} | timeout=30s)",
            fontsize=10,
        )
        _save_svg(fig, target_dir / "fig7_clauses_vars_vs_runtime.svg", generated)

    # 8. Bandwidth Gap vs Published Best (Baseline 25 executed HB instances)
    base_exec = base_df[
        (base_df["status"] != "RESOURCE_LIMIT")
        & base_df["bandwidth"].notna()
        & base_df["published_best"].notna()
    ].copy()
    if not base_exec.empty:
        base_exec["bw_gap"] = base_exec["bandwidth"].astype(int) - base_exec["published_best"].astype(int)
        base_exec = base_exec.sort_values(["table", "n", "instance"])
        fig = cns.figure(940, 390, unit="pt")
        ax = fig.add_subplot(111)
        cns.barplot(data=base_exec, x="instance", y="bw_gap", hue="table", ax=ax)
        ax.axhline(0.0, linestyle="--", linewidth=1.0, color="black", alpha=0.7)
        ax.set_title(
            f"Baseline SAT Bandwidth Gap vs Published Best (best_bw - published_best | N_inst={len(base_exec)} executed of 54 READY | Order+Seq+CaDiCaL+Inc | timeout=30s | 29 blocked RESOURCE_LIMIT omitted)"
        )
        ax.set_ylabel("Gap above Published Best (0 = matched, unproved)")
        ax.set_xlabel("Executed READY Instance (sorted by Table & n)")
        ax.tick_params(axis="x", labelrotation=45)
        _save_svg(fig, target_dir / "fig8_bandwidth_gap_vs_published.svg", generated)

    # 9. Overall Outcome Status Distribution (Baseline vs Studies HB vs SmallOracle)
    if not df.empty:
        parts = []
        if not base_df.empty:
            b_part = base_df.copy()
            b_part["cohort"] = "HB Baseline_54 (54 READY)"
            parts.append(b_part)
        study_hb = hb_df[~hb_df["experiment"].astype(str).eq("Baseline_54")].copy()
        if not study_hb.empty:
            study_hb["cohort"] = "HB Studies A-G (6 reps)"
            parts.append(study_hb)
        if not small_df.empty:
            sm = small_df.copy()
            sm["cohort"] = "SmallOracle (9 graphs)"
            parts.append(sm)
        if parts:
            comb = pd.concat(parts, ignore_index=True)
            st_cnt = comb.groupby(["cohort", "status"]).size().reset_index(name="count")
            fig = cns.figure(880, 370, unit="pt")
            ax = fig.add_subplot(111)
            cns.barplot(data=st_cnt, x="cohort", y="count", hue="status", ax=ax)
            ax.set_title(
                f"Outcome Status Distribution Separated by Cohort (Total N_runs={len(df)}; SmallOracle not mixed with HB)"
            )
            ax.set_ylabel("Number of runs")
            ax.set_xlabel("Experimental Cohort")
            _save_svg(fig, target_dir / "fig9_status_distribution.svg", generated)

    # 10. Instance size n vs worst-case CNF Clauses across ALL 54 READY (Order vs Pairwise)
    if not pf_df.empty:
        fig = cns.figure(860, 390, unit="pt")
        ax = fig.add_subplot(111)
        ax.scatter(pf_df["n"], pf_df["pairwise_cnf_clauses"], label="Pairwise + Sequential (worst-case k=0)", marker="^", alpha=0.82, s=45)
        ax.scatter(pf_df["n"], pf_df["order_cnf_clauses"], label="Order + Sequential (worst-case k=0)", marker="o", alpha=0.85, s=45)
        ax.axhline(2_500_000, linestyle="--", color="red", linewidth=1.3, label="Safety limit (2,500,000 clauses)")
        ax.set_yscale("log")
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{int(v):,}" if v >= 1 else f"{v:g}"))
        ax.yaxis.set_minor_formatter(mticker.NullFormatter())
        ax.set_title(
            f"54-READY Preflight Scaling: Vertex Count n vs Estimated CNF Clauses (All 54 READY instances, symmetry_breaking=True)"
        )
        ax.set_xlabel("Graph vertices n")
        ax.set_ylabel("Estimated CNF clauses (log scale)")
        ax.legend()
        _save_svg(fig, target_dir / "fig10_instance_vs_cnf_size.svg", generated)

    return generated
