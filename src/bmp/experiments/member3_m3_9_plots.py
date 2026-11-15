"""Phase M3.9 MiniSat22 113-Instance Scientific Visualization Suite (12 SVGs via cnsplots)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from bmp.experiments.member3_m3_6_plots import _apply_safe_rcparams, _save_fig, _set_plain_log_y
from bmp.experiments.member3_m3_8_plots import _set_plain_log_x


def create_m3_9_plots(output_dir: Path) -> list[Path]:
    """Generate all 12 required Phase M3.9 SVG figures cleanly from actual CSV outputs."""
    import matplotlib

    matplotlib.use("Agg")
    import cnsplots as cns

    _apply_safe_rcparams()
    import pandas as pd

    fig_dir = output_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    generated: list[Path] = []

    best_df = pd.read_csv(output_dir / "per_instance_best.csv") if (output_dir / "per_instance_best.csv").exists() else pd.DataFrame()
    tab_df = pd.read_csv(output_dir / "per_table_summary.csv") if (output_dir / "per_table_summary.csv").exists() else pd.DataFrame()
    pf_df = pd.read_csv(output_dir / "minisat_preflight_113.csv") if (output_dir / "minisat_preflight_113.csv").exists() else pd.DataFrame()
    pl_df = pd.read_csv(output_dir / "product_ladder_comparison.csv") if (output_dir / "product_ladder_comparison.csv").exists() else pd.DataFrame()
    rep_df = pd.read_csv(output_dir / "minisat_repeated_results.csv") if (output_dir / "minisat_repeated_results.csv").exists() else pd.DataFrame()
    inc_df = pd.read_csv(output_dir / "minisat_incremental_results.csv") if (output_dir / "minisat_incremental_results.csv").exists() else pd.DataFrame()
    srch_df = pd.read_csv(output_dir / "search_strategy_comparison.csv") if (output_dir / "search_strategy_comparison.csv").exists() else pd.DataFrame()
    runs_df = pd.read_csv(output_dir / "minisat_runs_113.csv") if (output_dir / "minisat_runs_113.csv").exists() else pd.DataFrame()

    # Fig 1: MiniSat coverage breakdown across all 113 HB instances
    if not best_df.empty:
        cnt_df = (
            best_df.groupby("attribution_status", as_index=False)["instance"]
            .count()
            .rename(columns={"instance": "count"})
        )
        fig = cns.figure(760, 380, unit="pt")
        ax = fig.add_subplot(111)
        cns.barplot(data=cnt_df, x="attribution_status", y="count", ax=ax)
        ax.axhline(113, linestyle="--", color="black", linewidth=0.9, label="All 113 instances")
        ax.set_xlabel("Verified Attribution Status (Total = 113 unique instances)")
        ax.set_ylabel("Instance Count")
        ax.set_title("Fig 1: MiniSat22 Full 113 Harwell-Boeing Coverage Breakdown")
        ax.tick_params(axis="x", labelrotation=22)
        _save_fig(fig, fig_dir / "fig01_minisat_coverage_113.svg", generated)

    # Fig 2: MiniSat status by Table (Table 6 / Table 7 / Table 8)
    if not tab_df.empty:
        sub_tab = tab_df[tab_df["table"].isin(["Table 6", "Table 7", "Table 8"])].copy()
        melt_cols = [
            "eligible",
            "minisat_attempted",
            "minisat_feasible_witness",
            "sat_optimal",
            "bound_optimal",
            "timeout_no_witness",
            "resource_limit",
        ]
        m_df = sub_tab.melt(id_vars=["table"], value_vars=melt_cols, var_name="metric", value_name="count")
        fig = cns.figure(820, 400, unit="pt")
        ax = fig.add_subplot(111)
        cns.barplot(data=m_df, x="table", y="count", hue="metric", ax=ax)
        ax.set_xlabel("Harwell-Boeing Source Table")
        ax.set_ylabel("Unique Instance Count")
        ax.set_title("Fig 2: MiniSat22 Coverage & Solver Witnesses Across Tables 6, 7, and 8")
        _save_fig(fig, fig_dir / "fig02_minisat_by_table.svg", generated)

    # Fig 3: Product vs Ladder AMO (CNF variables comparison on MiniSat22)
    if not pl_df.empty:
        ms_pl = pl_df[(pl_df["backend"] == "minisat") & (pl_df["num_variables"].notna())].copy()
        ms_pl["num_variables"] = pd.to_numeric(ms_pl["num_variables"], errors="coerce")
        ms_pl = ms_pl[ms_pl["num_variables"] > 0].copy()
        if not ms_pl.empty:
            fig = cns.figure(820, 400, unit="pt")
            ax = fig.add_subplot(111)
            cns.barplot(data=ms_pl, x="instance", y="num_variables", hue="amo_encoding", ax=ax)
            _set_plain_log_y(ax)
            ax.set_xlabel("Matched Benchmark Instance (Order One-Sided Compact Boundary)")
            ax.set_ylabel("CNF Variables (log scale)")
            ax.set_title("Fig 3: Product AMO vs Ladder AMO CNF Variables (MiniSat22)")
            ax.tick_params(axis="x", labelrotation=28)
            _save_fig(fig, fig_dir / "fig03_product_vs_ladder.svg", generated)

    # Fig 4: Repeated vs Incremental SAT runtime on MiniSat22 (matched instances)
    if not srch_df.empty:
        sub_ri = srch_df[srch_df["search_mode"] == "linear"].copy()
        sub_ri["total_wall_time_s"] = pd.to_numeric(sub_ri["total_wall_time_s"], errors="coerce")
        if not sub_ri.empty:
            fig = cns.figure(780, 380, unit="pt")
            ax = fig.add_subplot(111)
            cns.barplot(data=sub_ri, x="instance", y="total_wall_time_s", hue="strategy", ax=ax)
            ax.set_xlabel("Representative HB Instance (Order + Product + Compact)")
            ax.set_ylabel("Total Wall Time (seconds)")
            ax.set_title("Fig 4: MiniSat22 Repeated vs Incremental SAT Wall Time (Linear Mode)")
            ax.tick_params(axis="x", labelrotation=22)
            _save_fig(fig, fig_dir / "fig04_repeated_vs_incremental.svg", generated)

    # Fig 5: Linear vs Binary Search on MiniSat22 (matched instances)
    if not srch_df.empty:
        sub_lb = srch_df.copy()
        sub_lb["mode_label"] = sub_lb["strategy"] + "_" + sub_lb["search_mode"]
        sub_lb["total_wall_time_s"] = pd.to_numeric(sub_lb["total_wall_time_s"], errors="coerce")
        fig = cns.figure(820, 390, unit="pt")
        ax = fig.add_subplot(111)
        cns.barplot(data=sub_lb, x="instance", y="total_wall_time_s", hue="mode_label", ax=ax)
        ax.set_xlabel("Representative HB Instance")
        ax.set_ylabel("Total Wall Time (seconds)")
        ax.set_title("Fig 5: MiniSat22 Search Strategy Comparison (Linear vs Binary)")
        ax.tick_params(axis="x", labelrotation=22)
        _save_fig(fig, fig_dir / "fig05_linear_vs_binary.svg", generated)

    # Fig 6 & Fig 7: Preflight CNF Variables & Clauses vs Instance Size n across 113 instances
    if not pf_df.empty:
        sub_pf = pf_df[pf_df["estimated_variables"] > 0].copy()
        fig = cns.figure(820, 410, unit="pt")
        ax = fig.add_subplot(111)
        cns.scatterplot(data=sub_pf, x="max_component_n", y="estimated_variables", hue="config_id", ax=ax)
        ax.axhline(500_000, linestyle="--", color="red", linewidth=1.0, label="500k variable cap")
        _set_plain_log_x(ax)
        _set_plain_log_y(ax)
        ax.set_xlabel("Largest Component Order max_component_n (log)")
        ax.set_ylabel("Estimated CNF Variables (log)")
        ax.set_title("Fig 6: CNF Variables vs Component Size Across 113 HB Instances")
        _save_fig(fig, fig_dir / "fig06_cnf_vars_vs_n.svg", generated)

        sub_cls = pf_df[pf_df["estimated_clauses"] > 0].copy()
        fig = cns.figure(820, 410, unit="pt")
        ax = fig.add_subplot(111)
        cns.scatterplot(data=sub_cls, x="max_component_n", y="estimated_clauses", hue="config_id", ax=ax)
        ax.axhline(2_500_000, linestyle="--", color="red", linewidth=1.0, label="2.5M clause cap")
        _set_plain_log_x(ax)
        _set_plain_log_y(ax)
        ax.set_xlabel("Largest Component Order max_component_n (log)")
        ax.set_ylabel("Estimated CNF Clauses (log)")
        ax.set_title("Fig 7: CNF Clauses vs Component Size Across 113 HB Instances")
        _save_fig(fig, fig_dir / "fig07_cnf_clauses_vs_n.svg", generated)

    # Fig 8 & Fig 9: Actual Executed Runtime & Memory vs n (executed runs only)
    if not runs_df.empty:
        ex = runs_df[runs_df["actual_minisat_invoked"] == True].copy()
        ex["n"] = pd.to_numeric(ex["n"], errors="coerce")
        ex["total_wall_time_s"] = pd.to_numeric(ex["total_wall_time_s"], errors="coerce")
        ex["peak_rss_mb"] = pd.to_numeric(ex["peak_rss_mb"], errors="coerce")
        if not ex.empty:
            fig = cns.figure(820, 400, unit="pt")
            ax = fig.add_subplot(111)
            cns.scatterplot(data=ex, x="n", y="total_wall_time_s", hue="attribution_status", ax=ax)
            _set_plain_log_x(ax)
            ax.set_xlabel("Graph Order n (log scale, executed MiniSat22 runs only)")
            ax.set_ylabel("Total Wall Time (seconds)")
            ax.set_title("Fig 8: Executed MiniSat22 Wall Time vs Graph Size n")
            _save_fig(fig, fig_dir / "fig08_runtime_vs_n.svg", generated)

            ex_mem = ex[ex["peak_rss_mb"].notna()].copy()
            if not ex_mem.empty:
                fig = cns.figure(820, 400, unit="pt")
                ax = fig.add_subplot(111)
                cns.scatterplot(data=ex_mem, x="n", y="peak_rss_mb", hue="config_id", ax=ax)
                ax.axhline(4096.0, linestyle="--", color="red", linewidth=0.9, label="4096 MiB guard")
                _set_plain_log_x(ax)
                ax.set_xlabel("Graph Order n (log scale)")
                ax.set_ylabel("Measured Peak RSS (MiB)")
                ax.set_title("Fig 9: Measured Worker Peak RSS Memory vs Graph Size n")
                _save_fig(fig, fig_dir / "fig09_memory_vs_n.svg", generated)

    # Fig 10: MiniSat22 vs CaDiCaL vs Glucose4 on comparable Incremental Linear runs
    if not pl_df.empty:
        xb = pl_df[
            (pl_df["strategy"] == "incremental")
            & (pl_df["amo_encoding"] == "product")
            & (pl_df["table"] != "Synthetic")
        ].copy()
        xb["total_wall_time_s"] = pd.to_numeric(xb["total_wall_time_s"], errors="coerce")
        if not xb.empty:
            fig = cns.figure(820, 400, unit="pt")
            ax = fig.add_subplot(111)
            cns.barplot(data=xb, x="instance", y="total_wall_time_s", hue="backend", ax=ax)
            ax.set_xlabel("Matched Table 6/8 Instance (Order + Product + Compact)")
            ax.set_ylabel("Total Wall Time (seconds)")
            ax.set_title("Fig 10: Cross-Backend Comparison MiniSat22 vs CaDiCaL vs Glucose4")
            ax.tick_params(axis="x", labelrotation=28)
            _save_fig(fig, fig_dir / "fig10_minisat_vs_cadical_vs_glucose.svg", generated)

    # Fig 11: Baseline MiniSat (0d90086 / M3.8) vs M3.9 Final MiniSat coverage
    if not tab_df.empty:
        tot = tab_df[tab_df["table"] == "Total"].iloc[0]
        comp_rows = [
            {"era": "M3.8 Baseline", "metric": "HB_Eligible_Attempted", "count": 8},
            {"era": "M3.8 Baseline", "metric": "HB_Solver_Witnesses", "count": 4},
            {"era": "M3.8 Baseline", "metric": "HB_OPT_Proved", "count": 0},
            {"era": "0d90086 Complete", "metric": "HB_Eligible_Attempted", "count": 10},
            {"era": "0d90086 Complete", "metric": "HB_Solver_Witnesses", "count": 5},
            {"era": "0d90086 Complete", "metric": "HB_OPT_Proved", "count": 0},
            {"era": "M3.9 Final (113)", "metric": "HB_Eligible_Attempted", "count": int(tot["minisat_attempted"])},
            {"era": "M3.9 Final (113)", "metric": "HB_Solver_Witnesses", "count": int(tot["minisat_feasible_witness"])},
            {"era": "M3.9 Final (113)", "metric": "HB_OPT_Proved", "count": int(tot["sat_optimal"]) + int(tot["bound_optimal"])},
        ]
        c_df = pd.DataFrame(comp_rows)
        fig = cns.figure(760, 380, unit="pt")
        ax = fig.add_subplot(111)
        cns.barplot(data=c_df, x="era", y="count", hue="metric", ax=ax)
        ax.set_xlabel("Member 3 Milestone")
        ax.set_ylabel("Harwell-Boeing Instance Count")
        ax.set_title("Fig 11: MiniSat22 Harwell-Boeing Progression (M3.8 -> 0d90086 -> M3.9)")
        _save_fig(fig, fig_dir / "fig11_baseline_vs_final_minisat.svg", generated)

    # Fig 12: ResourceLimit vs Timeout vs Witness/OPT across graph size buckets
    if not best_df.empty:
        b_df = best_df.copy()
        b_df["n_num"] = pd.to_numeric(b_df["n"], errors="coerce")
        bins = [0, 60, 150, 400, 10000]
        labels = ["n<=60", "61<=n<=150", "151<=n<=400", "n>400"]
        b_df["size_bucket"] = pd.cut(b_df["n_num"], bins=bins, labels=labels)
        grp = (
            b_df.groupby(["size_bucket", "attribution_status"], observed=False, as_index=False)["instance"]
            .count()
            .rename(columns={"instance": "count"})
        )
        grp = grp[grp["count"] > 0]
        fig = cns.figure(820, 400, unit="pt")
        ax = fig.add_subplot(111)
        cns.barplot(data=grp, x="size_bucket", y="count", hue="attribution_status", ax=ax)
        ax.set_xlabel("Graph Size Bucket")
        ax.set_ylabel("Unique Instance Count (Sum = 113)")
        ax.set_title("Fig 12: ResourceLimit vs Timeout vs Witness Distribution by Graph Size")
        _save_fig(fig, fig_dir / "fig12_resource_limit_vs_timeout_dist.svg", generated)

    return generated
