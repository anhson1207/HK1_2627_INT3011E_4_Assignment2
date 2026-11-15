"""Phase M3.6 scientific visualization suite using cnsplots & matplotlib."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _apply_safe_rcparams() -> None:
    import matplotlib

    matplotlib.rcParams["font.family"] = "sans-serif"
    matplotlib.rcParams["font.sans-serif"] = ["DejaVu Sans"]
    matplotlib.rcParams["font.cursive"] = ["DejaVu Sans"]
    matplotlib.rcParams["font.serif"] = ["DejaVu Sans"]
    matplotlib.rcParams["mathtext.fontset"] = "dejavusans"
    matplotlib.rcParams["mathtext.default"] = "regular"
    matplotlib.rcParams["mathtext.rm"] = "DejaVu Sans"
    matplotlib.rcParams["mathtext.it"] = "DejaVu Sans"
    matplotlib.rcParams["mathtext.bf"] = "DejaVu Sans"
    matplotlib.rcParams["mathtext.cal"] = "DejaVu Sans"


def _set_plain_log_y(ax: Any) -> None:
    import matplotlib.ticker as mticker

    ax.set_yscale("log")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:g}" if v > 0 else "0"))
    ax.yaxis.set_minor_formatter(mticker.NullFormatter())


def _save_fig(fig: Any, out_path: Path, generated: list[Path]) -> None:
    import cnsplots as cns
    import matplotlib.pyplot as plt

    _apply_safe_rcparams()
    fig.tight_layout()
    cns.savefig(str(out_path), fig=fig)
    plt.close(fig)
    generated.append(out_path)


def create_m3_6_plots(
    csv_path: Path,
    *,
    preflight_csv_path: Path | None = None,
    out_dir: Path | None = None,
) -> list[Path]:
    """Generate clean, accurately annotated figures from measured M3.6 CSV results."""

    import matplotlib

    matplotlib.use("Agg")
    import cnsplots as cns

    _apply_safe_rcparams()
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd

    df = pd.read_csv(csv_path)
    target_dir = out_dir or (csv_path.parent / "figures")
    target_dir.mkdir(parents=True, exist_ok=True)
    generated: list[Path] = []
    if df.empty:
        return generated

    hb = df[df["stage"] != "Stage_A_SmallOracle"].copy()
    hb["n"] = pd.to_numeric(hb["n"], errors="coerce")
    hb["m"] = pd.to_numeric(hb["m"], errors="coerce")
    hb["bandwidth"] = pd.to_numeric(hb["bandwidth"], errors="coerce")
    hb["paper_best"] = pd.to_numeric(hb["paper_best"], errors="coerce")
    hb["total_wall_time_s"] = pd.to_numeric(hb["total_wall_time_s"], errors="coerce")
    hb["peak_rss_mb"] = pd.to_numeric(hb["peak_rss_mb"], errors="coerce")

    # 1. Cross-Family Bandwidth vs Published Best on Stage C Representative Instances
    c_df = hb[hb["stage"] == "Stage_C_Exact_Baseline"].copy()
    if not c_df.empty:
        valid_c = c_df[c_df["bandwidth"].notna()].copy()
        if not valid_c.empty:
            best_fam = (
                valid_c.groupby(["instance", "n", "family", "paper_best"], as_index=False)["bandwidth"]
                .min()
            )
            # Also add Stage B DRSA Warm best on these representative instances for complete 4-family view
            rep_names = sorted(c_df["instance"].unique(), key=lambda i: int(c_df[c_df["instance"] == i]["n"].iloc[0]))
            h_rep = hb[(hb["family"] == "Heuristic") & (hb["instance"].isin(rep_names)) & (hb["bandwidth"].notna())]
            if not h_rep.empty:
                best_h = h_rep.groupby(["instance", "n", "family", "paper_best"], as_index=False)["bandwidth"].min()
                best_fam = pd.concat([best_fam, best_h], ignore_index=True)
            best_fam["rel_to_best"] = best_fam["bandwidth"] / best_fam["paper_best"]
            best_fam["inst_lbl"] = best_fam["instance"] + " (n=" + best_fam["n"].astype(int).astype(str) + ")"
            order_lbl = [f"{nm} (n={int(c_df[c_df['instance'] == nm]['n'].iloc[0])})" for nm in rep_names]
            fig = cns.figure(920, 420, unit="pt")
            ax = fig.add_subplot(111)
            cns.barplot(data=best_fam, x="inst_lbl", y="rel_to_best", hue="family", order=order_lbl, ax=ax)
            ax.axhline(1.0, linestyle="--", color="black", linewidth=1.0, label="Published Best (=1.0)")
            ax.set_ylabel("Bandwidth / Published Best (1.0 = matched Best)")
            ax.set_xlabel("Representative READY Instance")
            ax.set_title(
                f"Fig 1: Cross-Family Best Incumbent Ratio vs Published Best (Stage C | N_inst={len(rep_names)} | timeout=15s Exact / 0.8s Heur | nonzero_union)"
            )
            ax.tick_params(axis="x", labelrotation=22)
            _save_fig(fig, target_dir / "fig01_cross_family_quality.svg", generated)

    # 2. Completion / Optimality / License Status Rates across Method Keys (Harwell-Boeing)
    if not hb.empty:
        summary_in = hb.copy()
        summary_in["method_lbl"] = summary_in["family"] + ":" + summary_in["method"]
        counts = summary_in.groupby(["method_lbl", "status"], observed=True).size().reset_index(name="count")
        fig = cns.figure(940, 430, unit="pt")
        ax = fig.add_subplot(111)
        cns.barplot(data=counts, x="method_lbl", y="count", hue="status", ax=ax)
        ax.set_ylabel("Run count (timeouts & license blocks shown separately)")
        ax.set_xlabel("Solver / Method")
        ax.set_title(
            f"Fig 2: Outcome & Proof Status Distribution Across All Harwell-Boeing M3.6 Runs (N_runs={len(hb)} | READY subset)"
        )
        ax.tick_params(axis="x", labelrotation=28)
        _save_fig(fig, target_dir / "fig02_method_status_rates.svg", generated)

    # 3 & 4. Wall Time & Peak RSS vs Graph Size n (executed runs only, log scale)
    exec_hb = hb[~hb["status"].isin(["RESOURCE_LIMIT", "UNAVAILABLE", "ERROR"]) & hb["total_wall_time_s"].notna()].copy()
    if not exec_hb.empty:
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.2, 4.6))
        cns.scatterplot(data=exec_hb, x="n", y="total_wall_time_s", hue="family", style="status", ax=ax1)
        _set_plain_log_y(ax1)
        ax1.set_title("Wall Time (s) vs Graph Order n (executed runs only; log scale)")
        ax1.set_ylabel("Total wall time (s)")
        ax1.set_xlabel("Number of vertices (n)")

        rss_df = exec_hb[exec_hb["peak_rss_mb"].notna()].copy()
        if not rss_df.empty:
            cns.scatterplot(data=rss_df, x="n", y="peak_rss_mb", hue="family", ax=ax2)
        ax2.set_title("Measured Peak RSS Memory (MB) vs Graph Order n")
        ax2.set_ylabel("Peak RSS (MB)")
        ax2.set_xlabel("Number of vertices (n)")
        fig.suptitle(
            f"Fig 3: Runtime & Memory Scaling Across READY Benchmark (N_exec={len(exec_hb)}; non-executed guards excluded)",
            fontsize=10.5,
        )
        _save_fig(fig, target_dir / "fig03_runtime_and_memory_vs_size.svg", generated)

    # 4. Preflight Eligibility & Blocker Breakdown across all 54 READY instances
    if preflight_csv_path is not None and Path(preflight_csv_path).exists():
        pre_df = pd.read_csv(preflight_csv_path)
        if not pre_df.empty and {"method", "eligibility"}.issubset(pre_df.columns):
            pre_counts = pre_df.groupby(["method", "eligibility"], observed=True).size().reset_index(name="count")
            fig = cns.figure(900, 400, unit="pt")
            ax = fig.add_subplot(111)
            cns.barplot(data=pre_counts, x="method", y="count", hue="eligibility", ax=ax)
            ax.axhline(54, linestyle="--", color="black", linewidth=0.9, label="All 54 READY")
            ax.set_ylabel("Instance count (out of 54 READY)")
            ax.set_xlabel("Solver / Method")
            ax.set_title(
                f"Fig 4: Preflight Eligibility & Resource/License Limits Across 54 READY Instances (N_checks={len(pre_df)})"
            )
            ax.tick_params(axis="x", labelrotation=22)
            _save_fig(fig, target_dir / "fig04_preflight_eligibility_54.svg", generated)

    # 5. Study SAT-A: Backends (CaDiCaL vs Glucose vs MiniSat) on Order+Sequential+Incremental
    sat_d_all = hb[(hb["stage"] == "Stage_D_SAT_Studies") & (hb["family"] == "SAT")].copy()
    sat_a = sat_d_all[
        (sat_d_all["study"] == "SAT_A_Backends")
        & (sat_d_all["main_encoding"] == "order")
        & (sat_d_all["amo_encoding"] == "sequential")
        & (sat_d_all["strategy"] == "incremental")
        & (sat_d_all["symmetry_breaking"] == True)
        & (sat_d_all["warm_start_mode"] == "NO_WARM_START")
    ].copy()
    if not sat_a.empty:
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.8, 4.5))
        cns.barplot(data=sat_a[sat_a["total_wall_time_s"].notna()], x="instance", y="total_wall_time_s", hue="backend", ax=ax1)
        ax1.set_title("Wall Time (s) [Order+Seq+Inc+Sym; timeout=10s]")
        ax1.set_ylabel("Total wall time (s)")
        ax1.tick_params(axis="x", labelrotation=20)
        cns.barplot(data=sat_a[sat_a["bandwidth"].notna()], x="instance", y="bandwidth", hue="backend", ax=ax2)
        ax2.set_title("Best Bandwidth Incumbent (timeout=10s)")
        ax2.set_ylabel("Bandwidth")
        ax2.tick_params(axis="x", labelrotation=20)
        fig.suptitle(
            f"Fig 5: Controlled Study SAT-A – CaDiCaL vs Glucose vs MiniSat (N_runs={len(sat_a)}, threads=1)",
            fontsize=10.5,
        )
        _save_fig(fig, target_dir / "fig05_sat_backends_comparison.svg", generated)

    # 6. Study SAT-B: Pairwise vs Order Main Encoding (CNF size & wall time)
    sat_b = sat_d_all[
        (sat_d_all["study"] == "SAT_B_MainEncoding")
        & (sat_d_all["backend"] == "cadical")
        & (sat_d_all["amo_encoding"] == "sequential")
        & (sat_d_all["strategy"] == "incremental")
        & (sat_d_all["symmetry_breaking"] == True)
        & (sat_d_all["warm_start_mode"] == "NO_WARM_START")
    ].copy()
    if not sat_b.empty and sat_b["main_encoding"].nunique() >= 2:
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.8, 4.5))
        cnf_ok = sat_b[sat_b["CNF_clauses"].notna()].copy()
        cns.barplot(data=cnf_ok, x="instance", y="CNF_clauses", hue="main_encoding", ax=ax1)
        _set_plain_log_y(ax1)
        ax1.set_title("CNF Clauses (log scale; includes estimator counts at RESOURCE_LIMIT)")
        ax1.set_ylabel("Clauses")
        ax1.tick_params(axis="x", labelrotation=20)
        t_ok = sat_b[sat_b["total_wall_time_s"].notna()].copy()
        cns.barplot(data=t_ok, x="instance", y="total_wall_time_s", hue="main_encoding", ax=ax2)
        ax2.set_title("Executed Wall Time (s) [blocked Pairwise runs omitted here]")
        ax2.set_ylabel("Wall time (s)")
        ax2.tick_params(axis="x", labelrotation=20)
        fig.suptitle(
            f"Fig 6: Controlled Study SAT-B – Pairwise vs Order Encoding (Sequential+CaDiCaL+Inc, N_runs={len(sat_b)})",
            fontsize=10.5,
        )
        _save_fig(fig, target_dir / "fig06_sat_pairwise_vs_order.svg", generated)

    # 7. Study SAT-C: Six Cardinality AMO Encodings (CNF Clauses/Variables & Runtime)
    sat_c = sat_d_all[
        (sat_d_all["study"] == "SAT_C_Cardinality_AMO")
        & (sat_d_all["backend"] == "cadical")
        & (sat_d_all["main_encoding"] == "order")
        & (sat_d_all["strategy"] == "incremental")
        & (sat_d_all["symmetry_breaking"] == True)
        & (sat_d_all["warm_start_mode"] == "NO_WARM_START")
        & (sat_d_all["instance"].isin(["bcspwr01", "bcsstk01", "bcspwr02", "ash85"]))
    ].copy()
    if not sat_c.empty and sat_c["amo_encoding"].nunique() >= 2:
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.6, 4.6))
        cns.barplot(data=sat_c[sat_c["CNF_clauses"].notna()], x="instance", y="CNF_clauses", hue="amo_encoding", ax=ax1)
        _set_plain_log_y(ax1)
        ax1.set_title("CNF Clauses across 6 AMOs (Order+CaDiCaL; ladder=sequential for m>=3)")
        ax1.set_ylabel("CNF clauses (log)")
        ax1.tick_params(axis="x", labelrotation=15)
        cns.barplot(data=sat_c[sat_c["total_wall_time_s"].notna()], x="instance", y="total_wall_time_s", hue="amo_encoding", ax=ax2)
        ax2.set_title("Executed Wall Time (s) across 6 AMOs (timeout=10s)")
        ax2.set_ylabel("Total wall time (s)")
        ax2.tick_params(axis="x", labelrotation=15)
        fig.suptitle(
            f"Fig 7: Controlled Study SAT-C – Six Cardinality AMO Variants (N_inst={sat_c['instance'].nunique()}, N_runs={len(sat_c)})",
            fontsize=10.5,
        )
        _save_fig(fig, target_dir / "fig07_sat_six_amo_variants.svg", generated)

    # 8. Study SAT-D: Repeated vs Incremental SAT
    sat_d = sat_d_all[
        (sat_d_all["study"] == "SAT_D_Strategy")
        & (sat_d_all["backend"] == "cadical")
        & (sat_d_all["main_encoding"] == "order")
        & (sat_d_all["amo_encoding"] == "sequential")
        & (sat_d_all["symmetry_breaking"] == True)
        & (sat_d_all["warm_start_mode"] == "NO_WARM_START")
    ].copy()
    if not sat_d.empty and sat_d["strategy"].nunique() >= 2:
        sat_d_sub = sat_d.copy()
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.6, 4.4))
        cns.barplot(data=sat_d_sub[sat_d_sub["total_wall_time_s"].notna()], x="instance", y="total_wall_time_s", hue="strategy", ax=ax1)
        ax1.set_title("Repeated vs Incremental Wall Time (s)")
        ax1.set_ylabel("Total wall time (s)")
        ax1.tick_params(axis="x", labelrotation=20)
        cns.barplot(data=sat_d_sub[sat_d_sub["SAT_calls"].notna()], x="instance", y="SAT_calls", hue="strategy", ax=ax2)
        ax2.set_title("SAT Solver Calls Executed")
        ax2.set_ylabel("SAT calls")
        ax2.tick_params(axis="x", labelrotation=20)
        fig.suptitle(
            f"Fig 8: Controlled Study SAT-D – Repeated vs Incremental SAT (Order+Sequential+CaDiCaL, N_runs={len(sat_d_sub)}, timeout=10s)",
            fontsize=10.5,
        )
        _save_fig(fig, target_dir / "fig08_sat_repeated_vs_incremental.svg", generated)

    # 9. Study CP: CP-SAT vs IBM CP Optimizer (Incumbent & Bound + Warm Start Impact)
    cp_c = hb[(hb["stage"] == "Stage_C_Exact_Baseline") & (hb["family"] == "CP")].copy()
    if not cp_c.empty:
        valid_cp = cp_c[cp_c["bandwidth"].notna()].copy()
        if not valid_cp.empty:
            valid_cp["solver_warm"] = valid_cp["method"] + ":" + valid_cp["warm_start_mode"]
            fig = cns.figure(940, 430, unit="pt")
            ax = fig.add_subplot(111)
            cns.barplot(data=valid_cp, x="instance", y="bandwidth", hue="solver_warm", ax=ax)
            ax.set_ylabel("Achieved Bandwidth (lower is better; CPO UNAVAILABLE on n>=209 CE 2^1000 cap)")
            ax.set_xlabel("Stage C Instance")
            ax.set_title(
                f"Fig 9: CP-SAT vs IBM CP Optimizer & Warm-Start Effects (Stage C | timeout=15s, threads=1 | N_valid={len(valid_cp)})"
            )
            ax.tick_params(axis="x", labelrotation=20)
            _save_fig(fig, target_dir / "fig09_cp_sat_vs_cp_optimizer.svg", generated)

    # 10. Stage B Heuristics across all 54 READY: Gap vs Published Best by Table
    b54 = hb[(hb["stage"] == "Stage_B_Heuristic_54") & (hb["seed"].isin([17]) | hb["seed"].isna())].copy()
    if not b54.empty and b54["bandwidth"].notna().any():
        b54 = b54[b54["bandwidth"].notna()].copy()
        b54["gap_to_pub_best"] = b54["bandwidth"] - b54["paper_best"]
        fig = cns.figure(920, 420, unit="pt")
        ax = fig.add_subplot(111)
        cns.boxplot(data=b54, x="method", y="gap_to_pub_best", hue="table", ax=ax)
        ax.axhline(0.0, linestyle="--", color="black", linewidth=1.0)
        ax.set_ylabel("Bandwidth - Published Best (0 = matched Published Best)")
        ax.set_xlabel("Heuristic Method (0.8s budget for stochastic methods, seed=17)")
        ax.set_title(
            f"Fig 10: Heuristic Gap to Published Best Across 54 READY Instances (53 unique topologies | N_runs={len(b54)})"
        )
        _save_fig(fig, target_dir / "fig10_heuristics_54_ready.svg", generated)

    # 11. Stage C Instance x Method Heatmap (Bandwidth relative to Published Best & Proof Marker)
    if not c_df.empty:
        piv = c_df.copy()
        piv["col"] = piv["method"] + "_" + piv["warm_start_mode"].str.replace("_WARM_START", "").str.replace("SHARED_", "")
        table_bw = piv.pivot_table(index="instance", columns="col", values="bandwidth", aggfunc="min")
        if not table_bw.empty:
            fig, ax = plt.subplots(figsize=(11.5, 5.2))
            mat = table_bw.to_numpy(dtype=float)
            im = ax.imshow(np.nan_to_num(mat, nan=0.0), aspect="auto", cmap="YlGnBu")
            ax.set_xticks(range(len(table_bw.columns)))
            ax.set_xticklabels(table_bw.columns, rotation=32, ha="right", fontsize=8)
            ax.set_yticks(range(len(table_bw.index)))
            ax.set_yticklabels(table_bw.index, fontsize=9)
            for i_row, inst in enumerate(table_bw.index):
                for j_col, col in enumerate(table_bw.columns):
                    val = table_bw.iloc[i_row, j_col]
                    sub = piv[(piv["instance"] == inst) & (piv["col"] == col)]
                    st = sub["status"].iloc[0] if not sub.empty else ""
                    txt = f"{int(val)}{'*' if st == 'OPTIMAL' else ''}" if not pd.isna(val) else ("LIM" if "RESOURCE" in st else ("LIC" if st == "UNAVAILABLE" else "TO"))
                    ax.text(j_col, i_row, txt, ha="center", va="center", fontsize=7.5, color="black")
            fig.colorbar(im, ax=ax, label="Bandwidth (* = PROVED OPTIMAL; TO=TIMEOUT, LIC=License, LIM=Resource)")
            ax.set_title("Fig 11: Stage C Exact Baseline Bandwidth & Proof Matrix (10 Representative READY, timeout=15s)")
            _save_fig(fig, target_dir / "fig11_stage_c_matrix_heatmap.svg", generated)

    # 12. Performance Profile on Executed Exact Solvers (Stage C + Stage D comparable runs)
    if not c_df.empty:
        prof_src = c_df[~c_df["status"].isin(["RESOURCE_LIMIT", "UNAVAILABLE", "ERROR"])].copy()
        methods_p = sorted(prof_src["method"].unique())
        taus = np.linspace(1.0, 5.0, 41)
        fig = cns.figure(820, 420, unit="pt")
        ax = fig.add_subplot(111)
        best_per_inst = prof_src[prof_src["bandwidth"].notna()].groupby("instance")["bandwidth"].min().to_dict()
        insts_p = sorted(best_per_inst)
        for mname in methods_p:
            sub = prof_src[(prof_src["method"] == mname) & (prof_src["warm_start_mode"] == "NO_WARM_START")]
            if sub.empty:
                sub = prof_src[prof_src["method"] == mname]
            ratios = []
            for inst in insts_p:
                r = sub[sub["instance"] == inst]
                bw_vals = r["bandwidth"].dropna()
                if bw_vals.empty or best_per_inst[inst] <= 0:
                    ratios.append(np.inf)
                else:
                    ratios.append(float(bw_vals.min()) / float(best_per_inst[inst]))
            y_vals = [sum(rt <= t for rt in ratios) / max(1, len(insts_p)) for t in taus]
            ax.plot(taus, y_vals, linewidth=2.0, label=mname)
        ax.set_xlabel("Quality ratio tau = bandwidth / best_stageC_bandwidth")
        ax.set_ylabel("Fraction of instances achieved")
        ax.set_ylim(0.0, 1.05)
        ax.legend(loc="lower right", frameon=True)
        ax.set_title(f"Fig 12: Incumbent Quality Performance Profile (Stage C NO_WARM_START, N_inst={len(insts_p)})")
        _save_fig(fig, target_dir / "fig12_quality_performance_profile.svg", generated)

    return generated
