"""Scientific SVG visualization suite for Leader Phase L9 (12 publication-grade figures)."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import cnsplots as cns
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import FuncFormatter, NullFormatter

_PALETTE = {
    "blue": "#2563EB",
    "teal": "#0D9488",
    "emerald": "#059669",
    "amber": "#D97706",
    "red": "#DC2626",
    "slate": "#475569",
    "muted": "#94A3B8",
    "purple": "#7C3AED",
    "indigo": "#4F46E5",
    "rose": "#E11D48",
}


def _apply_safe_rcparams() -> None:
    """Apply crisp DejaVu Sans publication styling compatible with headless macOS/Linux."""
    try:
        cns.setup_matplotlib()
    except Exception:
        pass
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["DejaVu Sans"],
        "mathtext.fontset": "dejavusans",
        "mathtext.default": "regular",
        "axes.unicode_minus": False,
        "axes.edgecolor": "#334155",
        "axes.linewidth": 0.9,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.alpha": 0.25,
        "grid.linestyle": "--",
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "svg.fonttype": "none",
    })


def _format_log_axis(ax: plt.Axes, *, x: bool = False, y: bool = True) -> None:
    """Apply plain human-readable tick labels without FreeType mathtext dependency."""
    fmt = FuncFormatter(lambda v, _: f"{int(round(v)):,}" if v >= 1 else (f"{v:g}" if v > 0 else "0"))
    null_fmt = NullFormatter()
    if x:
        ax.set_xscale("log")
        ax.xaxis.set_major_formatter(fmt)
        ax.xaxis.set_minor_formatter(null_fmt)
    if y:
        ax.set_yscale("log")
        ax.yaxis.set_major_formatter(fmt)
        ax.yaxis.set_minor_formatter(null_fmt)


def _save_svg(fig: plt.Figure, out_path: Path) -> Path:
    """Save figure tightly as SVG and close cleanly."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_path, format="svg", bbox_inches="tight")
    plt.close(fig)
    return out_path


def _empty_panel(ax: plt.Axes, title: str, message: str = "No observed data in slice") -> None:
    """Render clean fallback message instead of crashing on empty slices."""
    ax.set_title(title, fontsize=11, fontweight="bold")
    ax.text(0.5, 0.5, message, ha="center", va="center", transform=ax.transAxes, color=_PALETTE["slate"])
    ax.set_xticks([])
    ax.set_yticks([])


def _load_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path)


def _to_bool(series: pd.Series) -> pd.Series:
    return series.map(lambda v: str(v).strip().lower() == "true")


def create_l9_plots(output_dir: Path) -> list[Path]:
    """Generate all 12 Task L9.15 SVG figures under `<output_dir>/figures/`."""
    _apply_safe_rcparams()
    fig_dir = output_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)

    ds_df = _load_csv(output_dir / "dataset_113.csv")
    pf_df = _load_csv(output_dir / "sat_preflight_113.csv")
    gap_df = _load_csv(output_dir / "resource_gap_analysis.csv")
    enc_df = _load_csv(output_dir / "encoding_comparison.csv")
    amo_df = _load_csv(output_dir / "amo_comparison.csv")
    strat_df = _load_csv(output_dir / "strategy_comparison.csv")
    warm_df = _load_csv(output_dir / "warm_start_comparison.csv")
    best_df = _load_csv(output_dir / "per_instance_best.csv")
    noreg_df = _load_csv(output_dir / "no_regression_report.csv")

    generated: list[Path] = []

    # 1. fig01_dataset_113_overview.svg
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.5, 4.8))
    if not ds_df.empty:
        tables = ["Table 6", "Table 7", "Table 8"]
        statuses = ["READY", "NEEDS_VERIFICATION", "INVALID_DATA"]
        colors = [_PALETTE["emerald"], _PALETTE["amber"], _PALETTE["red"]]
        bottom = np.zeros(len(tables))
        for st, col in zip(statuses, colors):
            vals = np.array([len(ds_df[(ds_df["table"] == t) & (ds_df["validation_status"] == st)]) for t in tables])
            ax1.bar(tables, vals, bottom=bottom, label=st, color=col, width=0.55)
            for i, v in enumerate(vals):
                if v > 0:
                    ax1.text(i, bottom[i] + v / 2.0, str(int(v)), ha="center", va="center", color="white", fontweight="bold", fontsize=9)
            bottom += vals
        ax1.set_title("Harwell-Boeing 113 Dataset Audit by Table & Tier", fontsize=11, fontweight="bold")
        ax1.set_ylabel("Instance Count")
        ax1.set_ylim(0, max(bottom.max() * 1.15, 1))
        ax1.legend(frameon=False, fontsize=8.5)

        for st, col in zip(statuses, colors):
            sub = ds_df[ds_df["validation_status"] == st]
            if not sub.empty:
                ax2.scatter(sub["n"], sub["largest_component_n"], s=28, alpha=0.82, label=st, color=col, edgecolors="none")
        max_n = float(ds_df["n"].max())
        ax2.plot([1, max_n], [1, max_n], linestyle="--", color=_PALETTE["muted"], linewidth=1.0, label="y = n (single connected)")
        ax2.axhline(408, linestyle=":", color=_PALETTE["blue"], linewidth=1.1, label="Order+Seq cap (n <= 408)")
        ax2.axhline(500, linestyle="-.", color=_PALETTE["purple"], linewidth=1.1, label="Pairwise Pig.+Seq cap (n <= 500)")
        ax2.set_title("Total Vertices vs Largest Connected Component", fontsize=11, fontweight="bold")
        ax2.set_xlabel("Raw Graph Vertices n")
        ax2.set_ylabel("Largest Active Component Vertices")
        ax2.legend(frameon=False, fontsize=8)
    else:
        _empty_panel(ax1, "Dataset Overview")
        _empty_panel(ax2, "Component Reduction")
    generated.append(_save_svg(fig, fig_dir / "fig01_dataset_113_overview.svg"))

    # 2. fig02_sat_preflight_eligibility.svg
    fig, ax = plt.subplots(figsize=(11.5, 5.2))
    if not pf_df.empty:
        cfg_order = pf_df["config_id"].drop_duplicates().tolist()
        elig_vals = [len(pf_df[(pf_df["config_id"] == c) & (pf_df["preflight_status"] == "ELIGIBLE")]) for c in cfg_order]
        lim_vals = [len(pf_df[(pf_df["config_id"] == c) & (pf_df["preflight_status"] != "ELIGIBLE")]) for c in cfg_order]
        labels = [c.replace("base_", "L8: ").replace("l9_", "L9: ") for c in cfg_order]
        y = np.arange(len(cfg_order))
        ax.barh(y, elig_vals, color=_PALETTE["emerald"], label="ELIGIBLE (<=500k vars, <=2.5M clauses, <=4096 MiB)")
        ax.barh(y, lim_vals, left=elig_vals, color=_PALETTE["red"], alpha=0.85, label="RESOURCE_LIMIT")
        for i, (e, l) in enumerate(zip(elig_vals, lim_vals)):
            ax.text(max(e / 2, 2), i, str(e), va="center", ha="center", color="white", fontweight="bold", fontsize=9)
            if l > 0:
                ax.text(e + l / 2, i, str(l), va="center", ha="center", color="white", fontweight="bold", fontsize=9)
        ax.set_yticks(y)
        ax.set_yticklabels(labels, fontsize=9)
        ax.invert_yaxis()
        ax.set_xlim(0, 118)
        ax.set_xlabel("Harwell-Boeing Instances (out of 113)")
        ax.set_title("SAT Preflight Eligibility: Leader L8 Baseline vs Leader L9 Optimizations", fontsize=11.5, fontweight="bold")
        ax.legend(loc="lower right", frameon=False, fontsize=9)
    else:
        _empty_panel(ax, "SAT Preflight Eligibility")
    generated.append(_save_svg(fig, fig_dir / "fig02_sat_preflight_eligibility.svg"))

    # 3. fig03_cnf_vars_scaling.svg
    fig, ax = plt.subplots(figsize=(10.5, 5.2))
    if not pf_df.empty:
        var_cfgs = [
            ("base_pw_pw_rep_lin", "L8 Pairwise + Pairwise AMO", _PALETTE["red"], "o"),
            ("base_ord_seq_rep_lin", "L8 Order + Sequential (raw n)", _PALETTE["amber"], "s"),
            ("l9_ord_compact_seq_inc_bin_dec", "L9 Order Compact + Seq + Decomp", _PALETTE["blue"], "^"),
            ("l9_pw_pig_supsing_seq_rep_bin_dec", "L9 Pairwise Pigeonhole + Seq + Decomp", _PALETTE["emerald"], "D"),
        ]
        plotted = False
        for cid, lbl, col, mk in var_cfgs:
            sub = pf_df[(pf_df["config_id"] == cid) & (pf_df["total_vars"] > 0)].sort_values("n")
            if not sub.empty:
                ax.scatter(sub["n"], sub["total_vars"], label=lbl, color=col, marker=mk, s=22, alpha=0.82)
                plotted = True
        if plotted:
            ax.axhline(500_000, color=_PALETTE["slate"], linestyle="--", linewidth=1.2, label="ResourceLimits Cap (500,000 vars)")
            _format_log_axis(ax, x=True, y=True)
            ax.set_xlabel("Graph Vertices n")
            ax.set_ylabel("Estimated Total SAT Variables")
            ax.set_title("CNF Variable Scaling Across 113 Harwell-Boeing Instances", fontsize=11.5, fontweight="bold")
            ax.legend(frameon=False, fontsize=8.5)
        else:
            _empty_panel(ax, "CNF Variable Scaling")
    else:
        _empty_panel(ax, "CNF Variable Scaling")
    generated.append(_save_svg(fig, fig_dir / "fig03_cnf_vars_scaling.svg"))

    # 4. fig04_cnf_clauses_scaling.svg
    fig, ax = plt.subplots(figsize=(10.5, 5.2))
    if not pf_df.empty:
        cl_cfgs = [
            ("base_pw_pw_rep_lin", "L8 Pairwise Conflict + Pairwise AMO", _PALETTE["red"], "o"),
            ("base_ord_seq_inc_lin", "L8 Order Incremental (per-step bloat)", _PALETTE["amber"], "s"),
            ("l9_ord_compact_seq_inc_bin_dec", "L9 Order Compact Incremental (activation)", _PALETTE["blue"], "^"),
            ("l9_pw_pig_sup_seq_rep_lin_dec", "L9 Pairwise Pigeonhole + Support", _PALETTE["teal"], "v"),
            ("l9_pw_pig_supsing_seq_rep_bin_dec", "L9 Pairwise Pigeonhole + Support Single", _PALETTE["emerald"], "D"),
        ]
        plotted = False
        for cid, lbl, col, mk in cl_cfgs:
            sub = pf_df[(pf_df["config_id"] == cid) & (pf_df["total_clauses"] > 0)].sort_values("n")
            if not sub.empty:
                ax.scatter(sub["n"], sub["total_clauses"], label=lbl, color=col, marker=mk, s=22, alpha=0.82)
                plotted = True
        if plotted:
            ax.axhline(2_500_000, color=_PALETTE["slate"], linestyle="--", linewidth=1.2, label="ResourceLimits Cap (2,500,000 clauses)")
            _format_log_axis(ax, x=True, y=True)
            ax.set_xlabel("Graph Vertices n")
            ax.set_ylabel("Estimated Total Clauses")
            ax.set_title("CNF Clause Scaling & Support / Activation Reduction Across 113 Instances", fontsize=11.5, fontweight="bold")
            ax.legend(frameon=False, fontsize=8.2)
        else:
            _empty_panel(ax, "CNF Clause Scaling")
    else:
        _empty_panel(ax, "CNF Clause Scaling")
    generated.append(_save_svg(fig, fig_dir / "fig04_cnf_clauses_scaling.svg"))

    # 5. fig05_encoding_ablation_runtime_vars.svg
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.5, 4.8))
    if not enc_df.empty:
        enc_df = enc_df.copy()
        enc_df["label"] = enc_df["encoding"].astype(str) + ":" + enc_df["encoding_variant"].astype(str)
        grp = enc_df.groupby("label", as_index=False).agg(
            sat_solved=("sat_solved_any", lambda s: int(_to_bool(s).sum())),
            mean_vars=("num_variables", "mean"),
            mean_clauses=("num_clauses", "mean"),
            total_runs=("run_id", "count"),
        )
        y = np.arange(len(grp))
        ax1.barh(y, grp["mean_clauses"], color=_PALETTE["blue"], alpha=0.88)
        ax1.set_yticks(y)
        ax1.set_yticklabels(grp["label"], fontsize=8.5)
        ax1.invert_yaxis()
        _format_log_axis(ax1, x=True, y=False)
        ax1.set_xlabel("Mean CNF Clauses (Ablation Subset)")
        ax1.set_title("Encoding Ablation: Mean Clause Count", fontsize=11, fontweight="bold")

        solved_sub = enc_df[_to_bool(enc_df["sat_solved_any"]) & (enc_df["total_wall_time_s"] > 0)]
        if not solved_sub.empty:
            rt = solved_sub.groupby("label", as_index=False).agg(
                mean_time=("total_wall_time_s", "mean"),
                solved=("run_id", "count"),
            )
            y2 = np.arange(len(rt))
            ax2.barh(y2, rt["mean_time"], color=_PALETTE["teal"])
            for idx, row in enumerate(rt.itertuples()):
                ax2.text(row.mean_time * 1.03, idx, f"n={row.solved}", va="center", fontsize=8.5, color=_PALETTE["slate"])
            ax2.set_yticks(y2)
            ax2.set_yticklabels(rt["label"], fontsize=8.5)
            ax2.invert_yaxis()
            ax2.set_xlabel("Mean Wall Time on SAT-Solved Runs (s)")
            ax2.set_title("Encoding Ablation: Runtime on Solved Runs", fontsize=11, fontweight="bold")
        else:
            _empty_panel(ax2, "Encoding Runtime (Solved Runs)")
    else:
        _empty_panel(ax1, "Encoding Ablation")
        _empty_panel(ax2, "Encoding Runtime")
    generated.append(_save_svg(fig, fig_dir / "fig05_encoding_ablation_runtime_vars.svg"))

    # 6. fig06_amo_comparison_pairwise_vs_seq.svg
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.0, 4.8))
    if not amo_df.empty:
        amo_df = amo_df.copy()
        amo_df["label"] = amo_df["encoding"].astype(str) + "+" + amo_df["amo"].astype(str)
        agg = amo_df.groupby("label", as_index=False).agg(
            runs=("run_id", "count"),
            eligible=("solver_status", lambda s: int((s != "RESOURCE_LIMIT").sum())),
            sat_solved=("sat_solved_any", lambda s: int(_to_bool(s).sum())),
            mean_clauses=("num_clauses", "mean"),
        )
        x = np.arange(len(agg))
        w = 0.36
        ax1.bar(x - w / 2, agg["eligible"], width=w, color=_PALETTE["blue"], label="Preflight Eligible")
        ax1.bar(x + w / 2, agg["sat_solved"], width=w, color=_PALETTE["emerald"], label="CaDiCaL Valid SAT Found")
        ax1.set_xticks(x)
        ax1.set_xticklabels(agg["label"], rotation=15, ha="right", fontsize=8.5)
        ax1.set_ylabel("Instances (Ablation Subset)")
        ax1.set_title("Leader AMO: Eligibility & Valid SAT Solve Rate", fontsize=11, fontweight="bold")
        ax1.legend(frameon=False, fontsize=8.5)

        ax2.bar(x, agg["mean_clauses"], width=0.5, color=[_PALETTE["amber"], _PALETTE["teal"], _PALETTE["amber"], _PALETTE["teal"]][: len(agg)])
        _format_log_axis(ax2, x=False, y=True)
        ax2.set_xticks(x)
        ax2.set_xticklabels(agg["label"], rotation=15, ha="right", fontsize=8.5)
        ax2.set_ylabel("Mean Estimated/Built Clauses")
        ax2.set_title("Leader AMO: Pairwise vs Sequential Clause Size", fontsize=11, fontweight="bold")
    else:
        _empty_panel(ax1, "Leader AMO Comparison")
        _empty_panel(ax2, "Leader AMO Clauses")
    generated.append(_save_svg(fig, fig_dir / "fig06_amo_comparison_pairwise_vs_seq.svg"))

    # 7. fig07_repeated_vs_incremental_clause_growth.svg
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.5, 4.8))
    if not strat_df.empty:
        strat_df = strat_df.copy()
        strat_df["label"] = strat_df["strategy"].astype(str) + ":" + strat_df["search_mode"].astype(str) + " (" + strat_df["encoding"].astype(str) + ")"
        agg = strat_df.groupby("label", as_index=False).agg(
            eligible=("solver_status", lambda s: int((s != "RESOURCE_LIMIT").sum())),
            sat_solved=("sat_solved_any", lambda s: int(_to_bool(s).sum())),
            optimal=("proved_optimal", lambda s: int(_to_bool(s).sum())),
            mean_clauses=("num_clauses", "mean"),
        )
        y = np.arange(len(agg))
        ax1.barh(y - 0.18, agg["sat_solved"], height=0.35, color=_PALETTE["blue"], label="CaDiCaL SAT Found")
        ax1.barh(y + 0.18, agg["optimal"], height=0.35, color=_PALETTE["emerald"], label="Proved OPTIMAL")
        ax1.set_yticks(y)
        ax1.set_yticklabels(agg["label"], fontsize=8.2)
        ax1.invert_yaxis()
        ax1.set_xlabel("Instances (Ablation Subset)")
        ax1.set_title("Repeated vs Incremental & Linear vs Binary Search", fontsize=11, fontweight="bold")
        ax1.legend(frameon=False, fontsize=8.2)

        ax2.barh(y, agg["mean_clauses"], height=0.5, color=_PALETTE["indigo"], alpha=0.85)
        ax2.set_yticks(y)
        ax2.set_yticklabels(agg["label"], fontsize=8.2)
        ax2.invert_yaxis()
        _format_log_axis(ax2, x=True, y=False)
        ax2.set_xlabel("Mean Estimated/Built Clauses")
        ax2.set_title("Clause Footprint by Strategy & Search Mode", fontsize=11, fontweight="bold")
    else:
        _empty_panel(ax1, "Strategy & Search Comparison")
        _empty_panel(ax2, "Clause Footprint")
    generated.append(_save_svg(fig, fig_dir / "fig07_repeated_vs_incremental_clause_growth.svg"))

    # 8. fig08_warm_start_ub_impact.svg
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.0, 4.8))
    if not warm_df.empty:
        warm_df = warm_df.copy()
        agg = warm_df.groupby("warm_start_mode", as_index=False).agg(
            mean_ub=("initial_ub", "mean"),
            sat_solved=("sat_solved_any", lambda s: int(_to_bool(s).sum())),
            improved=("sat_improved_initial_ub", lambda s: int(_to_bool(s).sum())),
            runs=("run_id", "count"),
        )
        x = np.arange(len(agg))
        ax1.bar(x, agg["mean_ub"], width=0.5, color=[_PALETTE["red"], _PALETTE["blue"], _PALETTE["emerald"]][: len(agg)])
        ax1.set_xticks(x)
        ax1.set_xticklabels(agg["warm_start_mode"], fontsize=9.5)
        ax1.set_ylabel("Mean Initial Upper Bound")
        ax1.set_title("Warm-Start Mode: Initial Upper Bound Tightness", fontsize=11, fontweight="bold")

        w = 0.35
        ax2.bar(x - w / 2, agg["sat_solved"], width=w, color=_PALETTE["blue"], label="CaDiCaL SAT Found")
        ax2.bar(x + w / 2, agg["improved"], width=w, color=_PALETTE["emerald"], label="SAT Improved Initial UB")
        ax2.set_xticks(x)
        ax2.set_xticklabels(agg["warm_start_mode"], fontsize=9.5)
        ax2.set_ylabel("Instance Count")
        ax2.set_title("Warm-Start Mode: Solve & Improvement Rate", fontsize=11, fontweight="bold")
        ax2.legend(frameon=False, fontsize=8.5)
    else:
        _empty_panel(ax1, "Warm-Start Tightness")
        _empty_panel(ax2, "Warm-Start Solve Rate")
    generated.append(_save_svg(fig, fig_dir / "fig08_warm_start_ub_impact.svg"))

    # 9. fig09_113_coverage_by_tier_table.svg
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.5, 4.8))
    if not best_df.empty:
        status_order = ["SAT_OPTIMAL", "SAT_FEASIBLE", "TIMEOUT_NO_SAT_MODEL", "RESOURCE_LIMIT"]
        status_colors = [_PALETTE["emerald"], _PALETTE["blue"], _PALETTE["amber"], _PALETTE["red"]]

        tables = ["Table 6", "Table 7", "Table 8"]
        bottom = np.zeros(len(tables))
        for st, col in zip(status_order, status_colors):
            vals = np.array([len(best_df[(best_df["table"] == t) & (best_df["final_status"] == st)]) for t in tables])
            ax1.bar(tables, vals, bottom=bottom, label=st, color=col, width=0.55)
            for i, v in enumerate(vals):
                if v > 0:
                    ax1.text(i, bottom[i] + v / 2.0, str(int(v)), ha="center", va="center", color="white", fontweight="bold", fontsize=9)
            bottom += vals
        ax1.set_title("Full 113/113 Outcomes by Harwell-Boeing Table", fontsize=11, fontweight="bold")
        ax1.set_ylabel("Instance Count")
        ax1.legend(frameon=False, fontsize=8)

        tiers = ["Tier 1 READY (official)", "Tier 2 Exploratory"]
        tier_masks = [_to_bool(best_df["official_benchmark"]), ~_to_bool(best_df["official_benchmark"])]
        bottom2 = np.zeros(2)
        for st, col in zip(status_order, status_colors):
            vals2 = np.array([len(best_df[m & (best_df["final_status"] == st)]) for m in tier_masks])
            ax2.bar(tiers, vals2, bottom=bottom2, label=st, color=col, width=0.5)
            for i, v in enumerate(vals2):
                if v > 0:
                    ax2.text(i, bottom2[i] + v / 2.0, str(int(v)), ha="center", va="center", color="white", fontweight="bold", fontsize=9)
            bottom2 += vals2
        ax2.set_title("Full 113/113 Outcomes by Audit Provenance Tier", fontsize=11, fontweight="bold")
        ax2.set_ylabel("Instance Count")
        ax2.legend(frameon=False, fontsize=8)
    else:
        _empty_panel(ax1, "113 Coverage by Table")
        _empty_panel(ax2, "113 Coverage by Tier")
    generated.append(_save_svg(fig, fig_dir / "fig09_113_coverage_by_tier_table.svg"))

    # 10. fig10_sat_vs_heuristic_vs_published.svg
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.5, 4.8))
    if not best_df.empty:
        solved_sat = best_df[_to_bool(best_df["sat_solver_found_solution"])].copy()
        solved_sat = solved_sat[pd.to_numeric(solved_sat["best_sat_bandwidth"], errors="coerce") > 0]
        if not solved_sat.empty:
            ax1.scatter(solved_sat["rcm_ub"], solved_sat["best_sat_bandwidth"], color=_PALETTE["blue"], alpha=0.82, s=34, label="CaDiCaL Best SAT vs RCM UB")
            hi = float(max(solved_sat["rcm_ub"].max(), solved_sat["best_sat_bandwidth"].max()))
            ax1.plot([1, hi], [1, hi], linestyle="--", color=_PALETTE["muted"], label="Parity (SAT = RCM)")
            _format_log_axis(ax1, x=True, y=True)
            ax1.set_xlabel("Deterministic RCM Upper Bound")
            ax1.set_ylabel("Best Valid CaDiCaL SAT Bandwidth")
            ax1.set_title("CaDiCaL SAT Solutions vs RCM Upper Bound", fontsize=11, fontweight="bold")
            ax1.legend(frameon=False, fontsize=8.5)

            pub_pos = solved_sat[pd.to_numeric(solved_sat["published_best"], errors="coerce") > 0]
            if not pub_pos.empty:
                ax2.scatter(pub_pos["published_best"], pub_pos["best_sat_bandwidth"], color=_PALETTE["emerald"], alpha=0.82, s=34, label="CaDiCaL SAT vs Published Best")
                hi2 = float(max(pub_pos["published_best"].max(), pub_pos["best_sat_bandwidth"].max()))
                ax2.plot([1, hi2], [1, hi2], linestyle="--", color=_PALETTE["muted"], label="Parity (SAT = Published Best)")
                _format_log_axis(ax2, x=True, y=True)
                ax2.set_xlabel("Published Best / Reference Bandwidth")
                ax2.set_ylabel("Best Valid CaDiCaL SAT Bandwidth")
                ax2.set_title("CaDiCaL SAT Solutions vs Published Reference", fontsize=11, fontweight="bold")
                ax2.legend(frameon=False, fontsize=8.5)
            else:
                _empty_panel(ax2, "SAT vs Published Reference")
        else:
            _empty_panel(ax1, "SAT vs RCM UB")
            _empty_panel(ax2, "SAT vs Published Best")
    else:
        _empty_panel(ax1, "SAT vs RCM UB")
        _empty_panel(ax2, "SAT vs Published Best")
    generated.append(_save_svg(fig, fig_dir / "fig10_sat_vs_heuristic_vs_published.svg"))

    # 11. fig11_resource_gap_analysis.svg
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.5, 4.8))
    if not gap_df.empty:
        elig = gap_df[_to_bool(gap_df["l9_pw_supsing_eligible"])]
        lim = gap_df[~_to_bool(gap_df["l9_pw_supsing_eligible"])]
        for sub, lbl, col in [(elig, "ELIGIBLE (L9 best)", _PALETTE["emerald"]), (lim, "RESOURCE_LIMIT", _PALETTE["red"])]:
            if not sub.empty:
                ax1.scatter(sub["n"], sub["l9_pw_supsing_vars"], s=26, alpha=0.82, color=col, label=lbl)
                ax2.scatter(sub["n"], sub["l9_pw_supsing_clauses"], s=26, alpha=0.82, color=col, label=lbl)
        ax1.axhline(500_000, color=_PALETTE["slate"], linestyle="--", linewidth=1.2, label="Cap = 500,000 vars")
        ax2.axhline(2_500_000, color=_PALETTE["slate"], linestyle="--", linewidth=1.2, label="Cap = 2,500,000 clauses")
        _format_log_axis(ax1, x=True, y=True)
        _format_log_axis(ax2, x=True, y=True)
        ax1.set_xlabel("Graph Vertices n")
        ax1.set_ylabel("Minimum Leader L9 Variables Needed")
        ax1.set_title("Variable Cap Bottleneck Across 113 Instances", fontsize=11, fontweight="bold")
        ax1.legend(frameon=False, fontsize=8.2)
        ax2.set_xlabel("Graph Vertices n")
        ax2.set_ylabel("Minimum Leader L9 Clauses Needed")
        ax2.set_title("Clause Cap Bottleneck Across 113 Instances", fontsize=11, fontweight="bold")
        ax2.legend(frameon=False, fontsize=8.2)
    else:
        _empty_panel(ax1, "Variable Cap Bottleneck")
        _empty_panel(ax2, "Clause Cap Bottleneck")
    generated.append(_save_svg(fig, fig_dir / "fig11_resource_gap_analysis.svg"))

    # 12. fig12_before_after_l9_summary.svg
    fig, ax = plt.subplots(figsize=(10.8, 4.9))
    if not noreg_df.empty and not best_df.empty:
        l8_row = noreg_df[noreg_df["era"] == "Before_L9_L8_Official"].iloc[0]
        l9_row = noreg_df[noreg_df["era"] == "After_L9_Leader_SAT"].iloc[0]
        metrics = [
            "Catalog Evaluated",
            "Preflight Eligible",
            "SAT Attempted",
            "CaDiCaL SAT Solved",
            "Proved OPTIMAL",
        ]
        l8_elig = (
            int(((pf_df["config_id"] == "base_ord_seq_rep_lin") & (pf_df["preflight_status"] == "ELIGIBLE")).sum())
            if not pf_df.empty
            else 53
        )
        before_vals = [
            2,
            l8_elig,
            int(l8_row["sat_attempted_instances"]),
            int(l8_row["sat_solved_instances"]),
            int(l8_row["proved_optimal_instances"]),
        ]
        after_vals = [
            113,
            int(l9_row["eligible_count"]),
            int(l9_row["sat_attempted_instances"]),
            int(l9_row["sat_solved_instances"]),
            int(l9_row["proved_optimal_instances"]),
        ]
        x = np.arange(len(metrics))
        w = 0.36
        b1 = ax.bar(x - w / 2, before_vals, width=w, color=_PALETTE["muted"], label="Before L9 (Leader L8 Baseline)")
        b2 = ax.bar(x + w / 2, after_vals, width=w, color=_PALETTE["blue"], label="After L9 (Leader L9 Full 113)")
        for bar in list(b1) + list(b2):
            h = bar.get_height()
            ax.text(bar.get_x() + bar.get_width() / 2.0, h + 1.5, str(int(h)), ha="center", va="bottom", fontsize=8.8, fontweight="bold")
        ax.set_xticks(x)
        ax.set_xticklabels(metrics, fontsize=9.5)
        ax.set_ylim(0, 128)
        ax.set_ylabel("Harwell-Boeing Instances (out of 113)")
        ax.set_title("Leader SAT Scalability & Coverage Improvement (Before L9 vs After L9)", fontsize=11.5, fontweight="bold")
        ax.legend(frameon=False, fontsize=9)
    else:
        _empty_panel(ax, "Before L9 vs After L9 Summary")
    generated.append(_save_svg(fig, fig_dir / "fig12_before_after_l9_summary.svg"))

    return generated


__all__ = ["create_l9_plots"]
