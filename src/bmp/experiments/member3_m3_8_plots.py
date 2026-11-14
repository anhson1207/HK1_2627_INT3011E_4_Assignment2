"""Phase M3.8 Full 113/113 Scientific Visualization Suite (cnsplots & matplotlib)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from bmp.experiments.member3_m3_6_plots import _apply_safe_rcparams, _save_fig, _set_plain_log_y


def _set_plain_log_x(ax: Any) -> None:
    import matplotlib.ticker as mticker

    ax.set_xscale("log")
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:g}" if v > 0 else "0"))
    ax.xaxis.set_minor_formatter(mticker.NullFormatter())


def create_m3_8_plots(output_dir: Path) -> list[Path]:
    """Generate all 10 required Phase M3.8 SVG figures clearly separating VERIFIED vs EXPLORATORY."""

    import matplotlib

    matplotlib.use("Agg")
    import cnsplots as cns

    _apply_safe_rcparams()
    import matplotlib.pyplot as plt
    import pandas as pd

    fig_dir = output_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    generated: list[Path] = []

    cov_df = pd.read_csv(output_dir / "method_coverage_113.csv") if (output_dir / "method_coverage_113.csv").exists() else pd.DataFrame()
    pub_df = pd.read_csv(output_dir / "published_best_comparison.csv") if (output_dir / "published_best_comparison.csv").exists() else pd.DataFrame()
    rcm_df = pd.read_csv(output_dir / "rcm_113.csv") if (output_dir / "rcm_113.csv").exists() else pd.DataFrame()
    sa_df = pd.read_csv(output_dir / "sa_113.csv") if (output_dir / "sa_113.csv").exists() else pd.DataFrame()
    drsa_df = pd.read_csv(output_dir / "drsa_113.csv") if (output_dir / "drsa_113.csv").exists() else pd.DataFrame()
    cps_df = pd.read_csv(output_dir / "cpsat_113.csv") if (output_dir / "cpsat_113.csv").exists() else pd.DataFrame()
    sat_pf = pd.read_csv(output_dir / "sat_preflight_113.csv") if (output_dir / "sat_preflight_113.csv").exists() else pd.DataFrame()
    lic_df = pd.read_csv(output_dir / "mip_cp_license_113.csv") if (output_dir / "mip_cp_license_113.csv").exists() else pd.DataFrame()
    noreg_df = pd.read_csv(output_dir / "no_regression_comparison.csv") if (output_dir / "no_regression_comparison.csv").exists() else pd.DataFrame()

    # 1. Coverage 113 instances by method (Stacked outcome counts)
    if not cov_df.empty:
        melt_cols = [
            "optimal_proved",
            "feasible_solution_found",
            "timeout_with_incumbent",
            "timeout_no_incumbent",
            "resource_limit",
            "blocked_license",
            "error_count",
        ]
        m_df = cov_df.melt(id_vars=["method_label"], value_vars=melt_cols, var_name="outcome", value_name="count")
        m_df = m_df[m_df["count"] > 0]
        fig = cns.figure(940, 440, unit="pt")
        ax = fig.add_subplot(111)
        cns.barplot(data=m_df, x="method_label", y="count", hue="outcome", ax=ax)
        ax.axhline(113, linestyle="--", color="black", linewidth=0.9, label="All 113 instances")
        ax.set_ylabel("Instance count (total catalog = 113)")
        ax.set_xlabel("Method")
        ax.set_title("Fig 1: Full 113 Instance Coverage Breakdown by Exact Status (No Blocked Counted as Solved)")
        ax.tick_params(axis="x", labelrotation=28)
        _save_fig(fig, fig_dir / "fig01_coverage_113_by_method.svg", generated)

    # 2. RCM vs SA vs DRSA Warm vs DRSA Paper-Bounded across 113 (VERIFIED vs EXPLORATORY)
    heur_parts = []
    for sub in (
        rcm_df[rcm_df["is_primary_113"] == True] if not rcm_df.empty else pd.DataFrame(),
        sa_df[(sa_df["stage"] == "SA_113") & (sa_df["is_primary_113"] == True)] if not sa_df.empty else pd.DataFrame(),
        drsa_df[drsa_df["is_primary_113"] == True] if not drsa_df.empty else pd.DataFrame(),
    ):
        if not sub.empty:
            heur_parts.append(sub)
    if heur_parts:
        h_all = pd.concat(heur_parts, ignore_index=True)
        h_all["bandwidth"] = pd.to_numeric(h_all["bandwidth"], errors="coerce")
        h_all["paper_best"] = pd.to_numeric(h_all["paper_best"], errors="coerce")
        h_all = h_all[h_all["bandwidth"].notna()].copy()
        h_all["gap_to_pub"] = h_all["bandwidth"] - h_all["paper_best"]
        h_all["tier_lbl"] = h_all["official_benchmark"].map({True: "TIER1_VERIFIED_54", False: "TIER2_EXPLORATORY_59"})
        fig = cns.figure(900, 420, unit="pt")
        ax = fig.add_subplot(111)
        cns.boxplot(data=h_all, x="method", y="gap_to_pub", hue="tier_lbl", ax=ax)
        ax.axhline(0.0, linestyle="--", color="black", linewidth=0.9)
        ax.set_ylabel("Bandwidth - Published Best (lower is better; 0 = matched best)")
        ax.set_xlabel("Heuristic Configuration (113/113 valid solutions)")
        ax.set_title(f"Fig 2: RCM vs SA vs DRSA Across All 113 Instances (N_runs={len(h_all)} | Tier 1 vs Tier 2 Separated)")
        ax.tick_params(axis="x", labelrotation=15)
        _save_fig(fig, fig_dir / "fig02_rcm_sa_drsa_113.svg", generated)

    # 3. Bandwidth vs Published Best across 113 (VERIFIED vs EXPLORATORY, valid solutions only)
    if not pub_df.empty:
        valid_pub = pub_df[pub_df["best_feasible_bw"].notna()].copy()
        if not valid_pub.empty:
            fig = cns.figure(760, 450, unit="pt")
            ax = fig.add_subplot(111)
            cns.scatterplot(data=valid_pub, x="paper_best", y="best_feasible_bw", hue="confidence_tier", style="table", ax=ax)
            lim_max = max(float(valid_pub["paper_best"].max()), float(valid_pub["best_feasible_bw"].max())) * 1.05
            ax.plot([1, lim_max], [1, lim_max], linestyle="--", color="black", linewidth=1.0, label="Matched Published Best (y=x)")
            _set_plain_log_y(ax)
            _set_plain_log_x(ax)
            ax.set_ylabel("Best Valid Bandwidth Achieved across M3.8 (log scale)")
            ax.set_xlabel("Paper Published Best (log scale)")
            ax.set_title(f"Fig 3: Best Achieved Bandwidth vs Published Best (113 Instances | VERIFIED={len(valid_pub[valid_pub['official_benchmark']==True])} vs EXPLORATORY={len(valid_pub[valid_pub['official_benchmark']==False])})")
            _save_fig(fig, fig_dir / "fig03_bandwidth_vs_published_best_113.svg", generated)

    # 4. Runtime vs Graph Size n (executed solver attempts only, log scale)
    all_parts = [d for d in (rcm_df, sa_df, drsa_df, cps_df, pd.read_csv(output_dir / "sat_runs.csv") if (output_dir / "sat_runs.csv").exists() else pd.DataFrame()) if not d.empty]
    if all_parts:
        exec_all = pd.concat(all_parts, ignore_index=True)
        exec_all = exec_all[(exec_all["solver_attempted"] == True) & (exec_all["total_wall_time_s"].notna())].copy()
        if not exec_all.empty:
            fig = cns.figure(880, 420, unit="pt")
            ax = fig.add_subplot(111)
            cns.scatterplot(data=exec_all, x="n", y="total_wall_time_s", hue="family", style="m3_8_coverage_status", ax=ax)
            _set_plain_log_y(ax)
            ax.set_ylabel("Total Wall Time (s, log scale; executed runs only)")
            ax.set_xlabel("Number of Vertices (n)")
            ax.set_title(f"Fig 4: Runtime Scaling Across Executed 113-Dataset Runs (N_exec={len(exec_all)}; Non-Executed Guards Excluded)")
            _save_fig(fig, fig_dir / "fig04_runtime_vs_graph_size_113.svg", generated)

    # 5. Bandwidth Improvement Over RCM Across 113 (VERIFIED vs EXPLORATORY)
    if not pub_df.empty:
        imp_rows = []
        for col, mname in (
            ("sa_bw", "SA"),
            ("drsa_warm_bw", "DRSA Warm"),
            ("cpsat_bw", "CP-SAT"),
            ("sat_bw", "SAT (Order+Prod)"),
            ("cpo_bw", "CP Optimizer CE"),
        ):
            if col not in pub_df.columns:
                continue
            sub = pub_df[pub_df[col].notna() & pub_df["rcm_bw"].notna()].copy()
            for _, r in sub.iterrows():
                imp = int(r["rcm_bw"]) - int(r[col])
                imp_rows.append({
                    "method": mname,
                    "confidence_tier": r["confidence_tier"],
                    "improvement_vs_rcm": imp,
                    "strictly_improved": imp > 0,
                })
        if imp_rows:
            imp_df = pd.DataFrame(imp_rows)
            agg_imp = imp_df.groupby(["method", "confidence_tier"], as_index=False)["strictly_improved"].sum()
            fig = cns.figure(860, 400, unit="pt")
            ax = fig.add_subplot(111)
            cns.barplot(data=agg_imp, x="method", y="strictly_improved", hue="confidence_tier", ax=ax)
            ax.set_ylabel("Instances strictly improved over RCM (bw < rcm_bw)")
            ax.set_xlabel("Method")
            ax.set_title("Fig 5: Count of Instances Strictly Improved Over Deterministic RCM Across 113")
            _save_fig(fig, fig_dir / "fig05_improvement_over_rcm_113.svg", generated)

    # 6. CP-SAT Multi-Pass Status Distribution across 113
    if not cps_df.empty:
        cps_cnt = cps_df.groupby(["stage", "m3_8_coverage_status"], observed=True).size().reset_index(name="count")
        fig = cns.figure(880, 400, unit="pt")
        ax = fig.add_subplot(111)
        cns.barplot(data=cps_cnt, x="stage", y="count", hue="m3_8_coverage_status", ax=ax)
        ax.set_ylabel("Instance count")
        ax.set_xlabel("CP-SAT Execution Pass")
        ax.set_title("Fig 6: CP-SAT 113-Dataset Coverage & Outcome Distribution Across Passes 1–3")
        _save_fig(fig, fig_dir / "fig06_cpsat_status_distribution_113.svg", generated)

    # 7. SAT Preflight Eligible vs Resource-Blocked Distribution across 113
    if not sat_pf.empty:
        pf_cad = sat_pf[(sat_pf["backend"] == "cadical") & (sat_pf["strategy"] == "incremental")].copy()
        pf_cad["enc_amo"] = pf_cad["main_encoding"] + "+" + pf_cad["amo_encoding"]
        pf_cnt = pf_cad.groupby(["enc_amo", "eligibility"], observed=True).size().reset_index(name="count")
        fig = cns.figure(940, 420, unit="pt")
        ax = fig.add_subplot(111)
        cns.barplot(data=pf_cnt, x="enc_amo", y="count", hue="eligibility", ax=ax)
        ax.axhline(113, linestyle="--", color="black", linewidth=0.8)
        ax.set_ylabel("Instances (out of 113)")
        ax.set_xlabel("Main Encoding + AMO Encoding")
        ax.set_title("Fig 7: SAT Preflight Eligibility vs Resource Limit Across All 113 Instances")
        ax.tick_params(axis="x", labelrotation=28)
        _save_fig(fig, fig_dir / "fig07_sat_preflight_113.svg", generated)

    # 8. MIP & CP Optimizer License Limitations Across 113
    if not lic_df.empty:
        lic_cnt = lic_df.groupby(["solver", "eligibility", "official_benchmark"], observed=True).size().reset_index(name="count")
        lic_cnt["status_tier"] = lic_cnt["eligibility"] + "_" + lic_cnt["official_benchmark"].map({True: "READY54", False: "TIER2_59"})
        fig = cns.figure(880, 400, unit="pt")
        ax = fig.add_subplot(111)
        cns.barplot(data=lic_cnt, x="solver", y="count", hue="status_tier", ax=ax)
        ax.set_ylabel("Instance count")
        ax.set_xlabel("Commercial / Limited-Edition Exact Solver")
        ax.set_title("Fig 8: Gurobi, CPLEX & IBM CP Optimizer Eligibility vs External License Blockers (113 Instances)")
        _save_fig(fig, fig_dir / "fig08_mip_cp_license_blockers_113.svg", generated)

    # 9. Table 6 vs Table 7 vs Table 8 Valid Coverage & Gap Comparison
    if not pub_df.empty:
        sub_t = pub_df[pub_df["gap_vs_published_best"].notna()].copy()
        if not sub_t.empty:
            sub_t["table_tier"] = sub_t["table"] + " (" + sub_t["confidence_tier"] + ")"
            fig = cns.figure(900, 420, unit="pt")
            ax = fig.add_subplot(111)
            cns.boxplot(data=sub_t, x="table", y="gap_vs_published_best", hue="confidence_tier", ax=ax)
            ax.axhline(0.0, linestyle="--", color="black", linewidth=0.9)
            ax.set_ylabel("Best Bandwidth - Published Best")
            ax.set_xlabel("Paper Table (Table 6: 31, Table 7: 41, Table 8: 41 = 113)")
            ax.set_title("Fig 9: Quality Gap vs Published Best Across Tables 6, 7 & 8 (Tier 1 VERIFIED vs Tier 2 EXPLORATORY)")
            _save_fig(fig, fig_dir / "fig09_table6_vs_table7_vs_table8_113.svg", generated)

    # 10. No-Regression 3-Era Comparison (Before M3.1 vs After M3.7 vs After M3.8)
    if not noreg_df.empty:
        sub_nr = noreg_df[noreg_df["method"].isin(["rcm", "sa", "cp-sat", "cp-optimizer", "RCM (primary 113)", "SA (primary 113)", "DRSA Warm MODIFIED (113)", "CP-SAT Best Across Passes (113)", "CP::cp-sat", "Heuristic::rcm", "Heuristic::sa", "sa_legacy_2000 (nonzero_union seed=17)"])].copy()
        if not sub_nr.empty:
            sub_nr["lbl"] = sub_nr["era"] + "::" + sub_nr["method"]
            fig = cns.figure(940, 440, unit="pt")
            ax = fig.add_subplot(111)
            cns.barplot(data=sub_nr, x="lbl", y="valid_feasible_solutions", hue="era", ax=ax)
            ax.axhline(72, linestyle=":", color="gray", linewidth=1.0, label="Legacy 72 Baseline")
            ax.axhline(54, linestyle="--", color="black", linewidth=1.0, label="Canonical 54 READY")
            ax.axhline(113, linestyle="-.", color="green", linewidth=1.0, label="Full 113 Coverage")
            ax.set_ylabel("Valid Feasible/Optimal Solutions Count")
            ax.set_xlabel("Era & Method")
            ax.set_title("Fig 10: No-Regression Progress Across Three Milestones (Pre-M3.1 [72] -> M3.7 [54] -> M3.8 [113])")
            ax.tick_params(axis="x", labelrotation=32)
            _save_fig(fig, fig_dir / "fig10_no_regression_3_eras.svg", generated)

    return generated
