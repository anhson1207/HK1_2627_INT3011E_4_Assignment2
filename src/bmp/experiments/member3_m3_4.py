"""Phase M3.4 DRSA, SA, and RCM preflight, controlled benchmarks, ablations, and plots."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import platform
import shutil
import statistics
import tomllib
from pathlib import Path
from time import monotonic
from typing import Any

from bmp.core.benchmark_catalog import ALL_INSTANCES
from bmp.core.bounds import cuthill_mckee_order, identity_upper_bound
from bmp.core.graph import Graph
from bmp.core.validation import validate_solution
from bmp.experiments.member2_hb import _git_commit, _self_rss_mb
from bmp.heuristics import DRSASolver, RCMSolver, SimulatedAnnealingSolver
from bmp.io.readers import inspect_matrix_market
from bmp.solvers.exact.cpsat import CPSATSolver
from bmp.solvers.sat.incremental import IncrementalSATSolver
from bmp.solvers.sat.search import compute_lower_bound

PREFLIGHT_FIELDS: tuple[str, ...] = (
    "instance",
    "table",
    "dataset_status",
    "sha256_verified",
    "sha256",
    "n",
    "m",
    "initial_lb",
    "identity_ub",
    "rcm_ub",
    "published_lb",
    "published_best",
    "published_sa",
    "published_drsa",
    "drsa_paper_lf",
    "stage_b_selected",
    "stage_c_eligible",
    "reason",
)

M3_4_FIELDS: tuple[str, ...] = (
    "run_id",
    "timestamp",
    "git_commit",
    "stage",
    "experiment",
    "config_id",
    "instance",
    "table",
    "dataset_source",
    "sha256",
    "dataset_status",
    "n",
    "m",
    "method",
    "variant",
    "solver",
    "initial_solution",
    "initial_bandwidth",
    "final_bandwidth",
    "published_lb",
    "published_best",
    "published_sa",
    "published_drsa",
    "published_comparison",
    "absolute_improvement",
    "relative_improvement",
    "gap_to_published_best",
    "seed",
    "p_rex",
    "p_nex",
    "p_rot",
    "t0",
    "alpha",
    "tf",
    "l0",
    "lf",
    "markov_chain_policy",
    "evaluation_mode",
    "use_incremental",
    "time_limit_s",
    "runtime_seconds",
    "time_to_first_improvement_s",
    "time_to_best_s",
    "moves_evaluated",
    "accepted_moves",
    "rejected_moves",
    "best_update_count",
    "f_update_count",
    "cooling_steps",
    "temperature_stages",
    "op_rex_count",
    "op_nex_count",
    "op_rot_count",
    "op_rex_improvements",
    "op_nex_improvements",
    "op_rot_improvements",
    "final_delta",
    "final_f_value",
    "stop_reason",
    "timed_out",
    "status",
    "peak_rss_mb",
    "validation",
    "note",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _locate_raw_file(
    instance: str,
    raw_dir: Path,
    fallback_raw_dir: Path | None,
) -> Path | None:
    for base in (raw_dir, fallback_raw_dir):
        if base is None:
            continue
        for ext in (".mtx.gz", ".mtx"):
            cand = base / f"{instance}{ext}"
            if cand.is_file():
                return cand
    return None


def _format_csv_row(row: dict[str, Any], fieldnames: tuple[str, ...]) -> dict[str, Any]:
    return {field: ("" if row.get(field) is None else row[field]) for field in fieldnames}


def _classify_published_comparison(
    final_bw: int | None, published_best: int | None
) -> str | None:
    if final_bw is None or published_best is None:
        return None
    if final_bw == published_best:
        return "MATCHED_BEST"
    if final_bw > published_best:
        return "ABOVE_BEST"
    return "BELOW_PUBLISHED_BEST_REQUIRES_VERIFICATION"


def _run_preflight(
    provenance_entries: list[dict[str, Any]],
    *,
    raw_dir: Path,
    fallback_raw_dir: Path | None,
    stage_b_set: set[str],
) -> tuple[list[dict[str, Any]], dict[str, tuple[Graph, dict[str, Any], Path, dict[str, Any]]]]:
    """Verify SHA-256, preprocessing, bounds, and official paper stats for all 54 READY instances."""
    preflight_rows: list[dict[str, Any]] = []
    loaded_ready: dict[str, tuple[Graph, dict[str, Any], Path, dict[str, Any]]] = {}

    for entry in sorted(
        (e for e in provenance_entries if e["validation_status"] == "READY"),
        key=lambda e: (e["n"], e["m"], e["instance"]),
    ):
        name = entry["instance"]
        meta = ALL_INSTANCES[name]
        paper_info = {
            "sa_bandwidth": meta.sa_bandwidth,
            "drsa_bandwidth": meta.drsa_bandwidth,
        }
        raw_path = _locate_raw_file(name, raw_dir, fallback_raw_dir)
        if raw_path is None:
            preflight_rows.append(
                {
                    "instance": name,
                    "table": meta.source_table,
                    "dataset_status": entry["validation_status"],
                    "sha256_verified": False,
                    "sha256": entry.get("sha256"),
                    "n": entry["n"],
                    "m": entry["m"],
                    "published_lb": meta.paper_lb,
                    "published_best": meta.paper_best,
                    "published_sa": paper_info.get("sa_bandwidth"),
                    "published_drsa": paper_info.get("drsa_bandwidth"),
                    "drsa_paper_lf": 10 * entry["n"] * entry["m"],
                    "stage_b_selected": name in stage_b_set,
                    "stage_c_eligible": False,
                    "reason": "Raw archive missing on disk",
                }
            )
            continue

        actual_sha = _sha256(raw_path)
        sha_ok = actual_sha == entry.get("sha256")
        if not sha_ok:
            raise RuntimeError(f"SHA-256 mismatch for READY instance {name}: {actual_sha}")

        audit = inspect_matrix_market(raw_path)
        if (
            audit.status != "READY"
            or audit.rows != entry["n"]
            or audit.graph.size != entry["m"]
            or audit.rows != meta.n
        ):
            raise RuntimeError(
                f"Metadata mismatch on {name}: expected ({entry['n']}, {entry['m']}), "
                f"got ({audit.rows}, {audit.graph.size}, status={audit.status})"
            )

        graph = Graph.from_edges(
            range(1, audit.rows + 1),
            ((u + 1, v + 1) for u, v in audit.graph.edges),
            name=name,
            metadata={"source": str(raw_path), "sha256": actual_sha, "table": meta.source_table},
        )

        lb = compute_lower_bound(graph)
        id_ub, _ = identity_upper_bound(graph)
        rcm_res = RCMSolver().solve(graph)
        assert rcm_res.bandwidth is not None

        loaded_ready[name] = (graph, entry, raw_path, paper_info)
        preflight_rows.append(
            {
                "instance": name,
                "table": meta.source_table,
                "dataset_status": entry["validation_status"],
                "sha256_verified": True,
                "sha256": actual_sha,
                "n": graph.order,
                "m": graph.size,
                "initial_lb": lb,
                "identity_ub": id_ub,
                "rcm_ub": rcm_res.bandwidth,
                "published_lb": meta.paper_lb,
                "published_best": meta.paper_best,
                "published_sa": paper_info.get("sa_bandwidth"),
                "published_drsa": paper_info.get("drsa_bandwidth"),
                "drsa_paper_lf": 10 * graph.order * graph.size,
                "stage_b_selected": name in stage_b_set,
                "stage_c_eligible": True,
                "reason": "Verified READY (SHA-256 + GraphInstance + official paper metadata)",
            }
        )

    return preflight_rows, loaded_ready


def _build_plan(
    cfg: dict[str, Any],
    ready_instances: list[str],
) -> list[dict[str, Any]]:
    """Construct complete M3.4 execution plan (Stage B + Ablations + Stage C)."""
    plan: list[dict[str, Any]] = []
    idx = 0

    def add(
        *,
        stage: str,
        experiment: str,
        config_id: str,
        instance: str,
        solver: str,
        seed: int | None,
        timeout_s: float | None,
        params: dict[str, Any],
        max_moves: int | None = None,
    ) -> None:
        nonlocal idx
        idx += 1
        plan.append(
            {
                "run_id": f"m34-{idx:04d}",
                "stage": stage,
                "experiment": experiment,
                "config_id": config_id,
                "instance": instance,
                "solver": solver,
                "seed": seed,
                "timeout_s": timeout_s,
                "max_moves": max_moves,
                "params": params,
            }
        )

    seeds = [int(s) for s in cfg["seeds"]]
    stage_b_instances = list(cfg["stage_b_instances"])
    stage_b_t = float(cfg["stage_b_timeout_seconds"])

    # --- Stage B: Multi-seed pilot RCM vs SA vs DRSA on verified READY subset ---
    for inst in stage_b_instances:
        add(
            stage="Stage_B_Pilot",
            experiment="rcm_baseline",
            config_id="rcm_deterministic",
            instance=inst,
            solver="rcm",
            seed=None,
            timeout_s=None,
            params={},
        )
        for seed in seeds:
            add(
                stage="Stage_B_Pilot",
                experiment="sa_vs_drsa_same_init_rcm",
                config_id="sa_rcm_init",
                instance=inst,
                solver="sa",
                seed=seed,
                timeout_s=stage_b_t,
                params={
                    "initial_mode": "rcm",
                    "initial_temperature": 2.0,
                    "cooling": 0.9999,
                    "iterations": 10_000_000,
                    "minimum_temperature": 1e-12,
                },
            )
            add(
                stage="Stage_B_Pilot",
                experiment="sa_random_baseline",
                config_id="sa_random_init",
                instance=inst,
                solver="sa",
                seed=seed,
                timeout_s=stage_b_t,
                params={
                    "initial_mode": "random",
                    "initial_temperature": 2.0,
                    "cooling": 0.9999,
                    "iterations": 10_000_000,
                    "minimum_temperature": 1e-12,
                },
            )
            add(
                stage="Stage_B_Pilot",
                experiment="drsa_paper_faithful",
                config_id="drsa_paper_random",
                instance=inst,
                solver="drsa",
                seed=seed,
                timeout_s=stage_b_t,
                params={
                    "initial_mode": "random",
                    "initial_temperature": 1000.0,
                    "cooling": 0.99,
                    "final_temperature": 1e-7,
                    "initial_chain_length": 40,
                    "p_rex": 0.6,
                    "p_nex": 0.2,
                    "p_rot": 0.2,
                    "evaluation_mode": "paper",
                    "variant": "PAPER_FAITHFUL",
                },
            )
            add(
                stage="Stage_B_Pilot",
                experiment="drsa_rcm_high_temp_test",
                config_id="drsa_rcm_t1000",
                instance=inst,
                solver="drsa",
                seed=seed,
                timeout_s=stage_b_t,
                params={
                    "initial_mode": "rcm",
                    "initial_temperature": 1000.0,
                    "cooling": 0.99,
                    "final_temperature": 1e-7,
                    "initial_chain_length": 40,
                    "p_rex": 0.6,
                    "p_nex": 0.2,
                    "p_rot": 0.2,
                    "evaluation_mode": "paper",
                    "variant": "MODIFIED_VARIANT",
                },
            )
            add(
                stage="Stage_B_Pilot",
                experiment="sa_vs_drsa_same_init_rcm",
                config_id="drsa_modified_warm",
                instance=inst,
                solver="drsa",
                seed=seed,
                timeout_s=stage_b_t,
                params={
                    "initial_mode": "rcm",
                    "initial_temperature": 2.0,
                    "cooling": 0.99,
                    "final_temperature": 1e-7,
                    "initial_chain_length": 40,
                    "p_rex": 0.6,
                    "p_nex": 0.2,
                    "p_rot": 0.2,
                    "evaluation_mode": "paper",
                    "variant": "MODIFIED_VARIANT",
                },
            )

    # --- Ablations (Operator mixture, Evaluation f=b+d vs b-only, Speed incremental vs full) ---
    ablation_instances = list(cfg["ablation_instances"])
    ab_t = float(cfg["ablation_timeout_seconds"])
    ablation_configs = [
        ("ablate_op_rex_only", 1.0, 0.0, 0.0, "paper", "operator_ablation"),
        ("ablate_op_nex_only", 0.0, 1.0, 0.0, "paper", "operator_ablation"),
        ("ablate_op_rot_only", 0.0, 0.0, 1.0, "paper", "operator_ablation"),
        ("ablate_op_mixture_warm", 0.6, 0.2, 0.2, "paper", "operator_and_eval_ablation"),
        ("ablate_eval_bw_only", 0.6, 0.2, 0.2, "bandwidth_only", "evaluation_ablation"),
    ]
    for inst in ablation_instances:
        for seed in seeds:
            for cid, prex, pnex, prot, emode, exp_name in ablation_configs:
                add(
                    stage="Ablation_Study",
                    experiment=exp_name,
                    config_id=cid,
                    instance=inst,
                    solver="drsa",
                    seed=seed,
                    timeout_s=ab_t,
                    params={
                        "initial_mode": "rcm",
                        "initial_temperature": 2.0,
                        "cooling": 0.99,
                        "final_temperature": 1e-7,
                        "initial_chain_length": 40,
                        "p_rex": prex,
                        "p_nex": pnex,
                        "p_rot": prot,
                        "evaluation_mode": emode,
                        "variant": "MODIFIED_VARIANT",
                    },
                )

    speed_moves = int(cfg["ablation_speed_moves"])
    for inst in cfg["ablation_speed_instances"]:
        for use_inc, cid in ((True, "ablate_speed_incremental"), (False, "ablate_speed_full")):
            add(
                stage="Ablation_Study",
                experiment="incremental_vs_full_speed",
                config_id=cid,
                instance=inst,
                solver="drsa",
                seed=int(cfg["stage_c_seed"]),
                timeout_s=None,
                max_moves=speed_moves,
                params={
                    "initial_mode": "random",
                    "initial_temperature": 1000.0,
                    "cooling": 0.99,
                    "final_temperature": 1e-7,
                    "initial_chain_length": 40,
                    "p_rex": 0.6,
                    "p_nex": 0.2,
                    "p_rot": 0.2,
                    "evaluation_mode": "paper",
                    "use_incremental": use_inc,
                    "variant": "PAPER_FAITHFUL",
                },
            )

    # --- Stage C: Bounded full expansion over all 54 verified READY instances ---
    c_t = float(cfg["stage_c_timeout_seconds"])
    c_seed = int(cfg["stage_c_seed"])
    for inst in ready_instances:
        add(
            stage="Stage_C_54_READY",
            experiment="stage_c_rcm",
            config_id="stage_c_rcm",
            instance=inst,
            solver="rcm",
            seed=None,
            timeout_s=None,
            params={},
        )
        add(
            stage="Stage_C_54_READY",
            experiment="stage_c_sa",
            config_id="stage_c_sa_rcm",
            instance=inst,
            solver="sa",
            seed=c_seed,
            timeout_s=c_t,
            params={
                "initial_mode": "rcm",
                "initial_temperature": 2.0,
                "cooling": 0.9999,
                "iterations": 10_000_000,
                "minimum_temperature": 1e-12,
            },
        )
        add(
            stage="Stage_C_54_READY",
            experiment="stage_c_drsa_paper",
            config_id="stage_c_drsa_paper_random",
            instance=inst,
            solver="drsa",
            seed=c_seed,
            timeout_s=c_t,
            params={
                "initial_mode": "random",
                "initial_temperature": 1000.0,
                "cooling": 0.99,
                "final_temperature": 1e-7,
                "initial_chain_length": 40,
                "p_rex": 0.6,
                "p_nex": 0.2,
                "p_rot": 0.2,
                "evaluation_mode": "paper",
                "variant": "PAPER_FAITHFUL",
            },
        )
        add(
            stage="Stage_C_54_READY",
            experiment="stage_c_drsa_warm",
            config_id="stage_c_drsa_warm",
            instance=inst,
            solver="drsa",
            seed=c_seed,
            timeout_s=c_t,
            params={
                "initial_mode": "rcm",
                "initial_temperature": 2.0,
                "cooling": 0.99,
                "final_temperature": 1e-7,
                "initial_chain_length": 40,
                "p_rex": 0.6,
                "p_nex": 0.2,
                "p_rot": 0.2,
                "evaluation_mode": "paper",
                "variant": "MODIFIED_VARIANT",
            },
        )

    return plan


def _execute_item(
    item: dict[str, Any],
    *,
    graph: Graph,
    prov: dict[str, Any],
    raw_path: Path,
    paper_info: dict[str, Any],
    git_sha: str,
) -> tuple[dict[str, Any], list[dict[str, Any]] | None]:
    meta = ALL_INSTANCES[graph.name]
    params = dict(item["params"])
    solver_name = str(item["solver"])
    timeout_s = item["timeout_s"]
    max_moves = item["max_moves"]

    if solver_name == "rcm":
        result = RCMSolver().solve(graph)
        method_label = "RCM"
    elif solver_name == "sa":
        result = SimulatedAnnealingSolver(**params).solve(
            graph,
            timeout_seconds=timeout_s,
            seed=item["seed"],
        )
        method_label = "SA"
    else:
        result = DRSASolver(**params).solve(
            graph,
            timeout_seconds=timeout_s,
            max_total_moves=max_moves,
            seed=item["seed"],
        )
        method_label = "DRSA"

    md = dict(result.metadata or {})
    valid: bool | None = None
    if result.permutation is not None:
        cert = validate_solution(graph, result.permutation, claimed_bandwidth=result.bandwidth)
        valid = bool(cert.valid)
        if not valid:
            raise RuntimeError(f"Validation failed on {item['run_id']}: {cert.errors}")

    init_bw = md.get("initial_bandwidth", result.bandwidth)
    final_bw = result.bandwidth
    abs_imp = (
        int(init_bw) - int(final_bw)
        if init_bw is not None and final_bw is not None
        else None
    )
    rel_imp = (
        round(abs_imp / int(init_bw), 6)
        if abs_imp is not None and init_bw and int(init_bw) > 0
        else (0.0 if abs_imp == 0 else None)
    )
    gap_pub = (
        int(final_bw) - int(meta.paper_best)
        if final_bw is not None and meta.paper_best is not None
        else None
    )

    op_counts = dict(md.get("operator_counts") or {})
    op_imps = dict(md.get("operator_improvements") or {})
    probs = dict(md.get("operator_probabilities") or {})

    row: dict[str, Any] = {
        "run_id": item["run_id"],
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "git_commit": git_sha,
        "stage": item["stage"],
        "experiment": item["experiment"],
        "config_id": item["config_id"],
        "instance": graph.name,
        "table": meta.source_table,
        "dataset_source": str(raw_path),
        "sha256": prov.get("sha256"),
        "dataset_status": prov.get("validation_status"),
        "n": graph.order,
        "m": graph.size,
        "method": method_label,
        "variant": md.get("variant", "BASELINE"),
        "solver": result.solver,
        "initial_solution": md.get("initial_mode", "rcm" if solver_name == "rcm" else None),
        "initial_bandwidth": init_bw,
        "final_bandwidth": final_bw,
        "published_lb": meta.paper_lb,
        "published_best": meta.paper_best,
        "published_sa": paper_info.get("sa_bandwidth"),
        "published_drsa": paper_info.get("drsa_bandwidth"),
        "published_comparison": _classify_published_comparison(final_bw, meta.paper_best),
        "absolute_improvement": abs_imp,
        "relative_improvement": rel_imp,
        "gap_to_published_best": gap_pub,
        "seed": item["seed"],
        "p_rex": probs.get("REX"),
        "p_nex": probs.get("NEX"),
        "p_rot": probs.get("ROT"),
        "t0": md.get("initial_temperature"),
        "alpha": md.get("cooling"),
        "tf": md.get("final_temperature", md.get("minimum_temperature")),
        "l0": md.get("initial_chain_length"),
        "lf": md.get("final_chain_length"),
        "markov_chain_policy": (
            "cool_and_grow_when_chain_no_global_best_improvement"
            if solver_name == "drsa"
            else ("geometric_per_iteration" if solver_name == "sa" else "deterministic_bfs")
        ),
        "evaluation_mode": md.get("evaluation_mode", "bandwidth_only" if solver_name in ("sa", "rcm") else None),
        "use_incremental": md.get("use_incremental"),
        "time_limit_s": timeout_s,
        "runtime_seconds": round(result.runtime_seconds, 6),
        "time_to_first_improvement_s": md.get("time_to_first_improvement_s"),
        "time_to_best_s": md.get("time_to_best_s"),
        "moves_evaluated": md.get("evaluations"),
        "accepted_moves": md.get("accepted_moves"),
        "rejected_moves": md.get("rejected_moves"),
        "best_update_count": md.get("best_updates"),
        "f_update_count": md.get("best_f_updates"),
        "cooling_steps": md.get("cooling_steps"),
        "temperature_stages": md.get("temperature_stages"),
        "op_rex_count": op_counts.get("REX"),
        "op_nex_count": op_counts.get("NEX"),
        "op_rot_count": op_counts.get("ROT"),
        "op_rex_improvements": op_imps.get("REX"),
        "op_nex_improvements": op_imps.get("NEX"),
        "op_rot_improvements": op_imps.get("ROT"),
        "final_delta": md.get("final_fractional_delta"),
        "final_f_value": md.get("final_evaluation_f"),
        "stop_reason": md.get("stop_reason"),
        "timed_out": md.get("timed_out"),
        "status": str(result.status.value),
        "peak_rss_mb": _self_rss_mb(),
        "validation": valid,
        "note": None,
    }
    trace = md.get("best_so_far_timeline")
    return row, trace if isinstance(trace, list) else None


def _run_warm_start_check(
    loaded_ready: dict[str, tuple[Graph, dict[str, Any], Path, dict[str, Any]]],
    *,
    seed: int,
) -> list[dict[str, Any]]:
    """Verify M3.4.9 warm-start feeding DRSA incumbents into Incremental SAT and CP-SAT."""
    checks: list[dict[str, Any]] = []
    for inst in ("bcspwr01", "bcspwr02"):
        if inst not in loaded_ready:
            continue
        graph = loaded_ready[inst][0]
        drsa_res = DRSASolver(
            seed=seed,
            initial_mode="rcm",
            initial_temperature=2.0,
            variant="MODIFIED_VARIANT",
        ).solve(graph, timeout_seconds=1.5)
        assert drsa_res.permutation is not None
        cp_res = CPSATSolver().solve(
            graph,
            timeout_seconds=10.0,
            symmetry_breaking=True,
            threads=1,
            seed=seed,
            initial_permutation=drsa_res.permutation,
        )
        sat_res = IncrementalSATSolver(backend_name="cadical").solve(
            graph,
            timeout_seconds=3.0,
            symmetry_breaking=True,
            heuristic_permutation=drsa_res.permutation,
        )
        checks.append(
            {
                "instance": graph.name,
                "heuristic_solver": "drsa_modified_warm",
                "heuristic_time_s": round(drsa_res.runtime_seconds, 6),
                "heuristic_bw": drsa_res.bandwidth,
                "cp_sat_status": str(cp_res.status.value),
                "cp_sat_bw": cp_res.bandwidth,
                "cp_sat_lb": cp_res.lower_bound,
                "cp_sat_time_s": round(cp_res.runtime_seconds, 6),
                "cp_sat_model_ub": cp_res.metadata.get("model_upper_bound"),
                "sat_status": str(sat_res.status.value),
                "sat_bw": sat_res.bandwidth,
                "sat_lb": sat_res.lower_bound,
                "sat_time_s": round(sat_res.runtime_seconds, 6),
            }
        )
    return checks


def _generate_figures(
    rows: list[dict[str, Any]],
    traces: dict[str, list[dict[str, Any]]],
    output_dir: Path,
    stage_b_instances: list[str],
) -> list[str]:
    saved: list[str] = []
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        try:
            import cnsplots as cns
        except Exception:
            cns = None
    except Exception:
        return saved

    fig_dir = output_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)

    def _save(fig: Any, fname: str) -> None:
        out = fig_dir / fname
        fig.tight_layout()
        if cns is not None and hasattr(cns, "savefig"):
            cns.savefig(str(out), fig=fig)
        else:
            fig.savefig(out, format="svg", bbox_inches="tight")
        plt.close(fig)
        saved.append(f"figures/{fname}")

    # --- Fig 1: Stage B RCM vs SA(RCM) vs DRSA(Paper) vs DRSA(Warm) vs Published Best ---
    b_rows = [r for r in rows if r["stage"] == "Stage_B_Pilot"]
    if b_rows:
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.5, 4.8))
        configs = [
            ("rcm_deterministic", "RCM", "#7f7f7f"),
            ("sa_rcm_init", "SA (RCM)", "#4c72b0"),
            ("drsa_paper_random", "DRSA (Paper Random)", "#dd8452"),
            ("drsa_modified_warm", "DRSA (Modified Warm)", "#55a868"),
        ]
        x = list(range(len(stage_b_instances)))
        width = 0.19
        for ci, (cid, label, color) in enumerate(configs):
            means: list[float] = []
            for inst in stage_b_instances:
                vals = [
                    r["final_bandwidth"]
                    for r in b_rows
                    if r["instance"] == inst and r["config_id"] == cid and r["final_bandwidth"] is not None
                ]
                means.append(statistics.mean(vals) if vals else 0.0)
            offsets = [xi + (ci - 1.5) * width for xi in x]
            ax1.bar(offsets, means, width=width, label=label, color=color, alpha=0.88)

        pub_vals = []
        for inst in stage_b_instances:
            pb = ALL_INSTANCES[inst].paper_best
            pub_vals.append(pb if pb is not None else 0)
        ax1.plot(x, pub_vals, "k--o", linewidth=1.3, markersize=4.5, label="Published Best (Torres-Jimenez 2015)")
        ax1.set_xticks(x)
        ax1.set_xticklabels(stage_b_instances, rotation=28, ha="right", fontsize=8.5)
        ax1.set_ylabel("Mean Bandwidth across seeds {17,23,42}")
        ax1.set_title("Stage B: Mean Bandwidth (RCM vs SA vs DRSA)")
        ax1.grid(axis="y", linestyle="--", alpha=0.3)
        ax1.legend(fontsize=7.5)

        # Panel 2: Gap to Published Best across seeds (box/points for Stage B 4s)
        seed_configs = [
            ("sa_rcm_init", "SA (RCM)", "#4c72b0"),
            ("sa_random_init", "SA (Random)", "#8172b3"),
            ("drsa_paper_random", "DRSA (Paper)", "#dd8452"),
            ("drsa_modified_warm", "DRSA (Warm)", "#55a868"),
        ]
        gap_data = []
        gap_labels = []
        for cid, label, _ in seed_configs:
            gaps = [
                r["gap_to_published_best"]
                for r in b_rows
                if r["config_id"] == cid and r["gap_to_published_best"] is not None
            ]
            gap_data.append(gaps if gaps else [0])
            gap_labels.append(label)
        bp = ax2.boxplot(gap_data, tick_labels=gap_labels, patch_artist=True)
        for patch, (_, _, col) in zip(bp["boxes"], seed_configs, strict=True):
            patch.set_facecolor(col)
            patch.set_alpha(0.65)
        ax2.axhline(0.0, color="black", linestyle="--", linewidth=1.0)
        ax2.set_ylabel("Bandwidth Gap (bw - Published Best)")
        ax2.set_title("Stage B: Gap Distribution Across 8 Instances x 3 Seeds")
        ax2.tick_params(axis="x", labelsize=8)
        ax2.grid(axis="y", linestyle="--", alpha=0.3)
        _save(fig, "fig1_rcm_sa_drsa_bandwidth.svg")

    # --- Fig 2: Convergence curve + Operator / Evaluation Ablations ---
    ab_rows = [r for r in rows if r["stage"] == "Ablation_Study"]
    if b_rows or ab_rows:
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.5, 4.8))
        # Left: convergence on bcsstk01 seed=17
        for cid, label, col in (
            ("sa_rcm_init", "SA (RCM, 4s)", "#4c72b0"),
            ("drsa_modified_warm", "DRSA Warm (RCM, 4s)", "#55a868"),
            ("drsa_paper_random", "DRSA Paper (Random, 4s)", "#dd8452"),
        ):
            match = [
                r
                for r in b_rows
                if r["instance"] == "bcsstk01" and r["config_id"] == cid and r["seed"] == 17
            ]
            if match and match[0]["run_id"] in traces:
                pts = traces[match[0]["run_id"]]
                ts = [p["time_s"] for p in pts] + [match[0]["runtime_seconds"]]
                bs = [p["bandwidth"] for p in pts] + [match[0]["final_bandwidth"]]
                ax1.step(ts, bs, where="post", label=label, color=col, linewidth=1.8)
        ax1.axhline(ALL_INSTANCES["bcsstk01"].paper_best, color="black", linestyle="--", linewidth=1.1, label="Published Best (16)")
        ax1.set_xlabel("Elapsed Wall Time (s)")
        ax1.set_ylabel("Best-so-far Bandwidth")
        ax1.set_title("Convergence on bcsstk01 (n=48, m=176, seed=17)")
        ax1.grid(True, linestyle="--", alpha=0.3)
        ax1.legend(fontsize=8)

        # Right: Operator & Eval ablation on bcsstk01, ash85, nos4
        ab_insts = sorted({r["instance"] for r in ab_rows if "ablate_op_" in r["config_id"] or r["config_id"] == "ablate_eval_bw_only"})
        ab_cfgs = [
            ("ablate_op_rex_only", "REX only", "#8c564b"),
            ("ablate_op_nex_only", "NEX only", "#e377c2"),
            ("ablate_op_rot_only", "ROT only", "#17becf"),
            ("ablate_eval_bw_only", "Mix (bw-only)", "#bcbd22"),
            ("ablate_op_mixture_warm", "Mix (f=b+d)", "#55a868"),
        ]
        if ab_insts:
            x2 = list(range(len(ab_insts)))
            w2 = 0.16
            for ci, (cid, label, col) in enumerate(ab_cfgs):
                vals_mean = [
                    statistics.mean(
                        r["final_bandwidth"]
                        for r in ab_rows
                        if r["instance"] == inst and r["config_id"] == cid
                    )
                    for inst in ab_insts
                ]
                offs = [xi + (ci - 2) * w2 for xi in x2]
                ax2.bar(offs, vals_mean, width=w2, label=label, color=col, alpha=0.88)
            ax2.set_xticks(x2)
            ax2.set_xticklabels(ab_insts, fontsize=9)
            ax2.set_ylabel("Mean Bandwidth (3 seeds, 3s)")
            ax2.set_title("Operator & Evaluation Ablation (RCM Start, T0=2.0)")
            ax2.grid(axis="y", linestyle="--", alpha=0.3)
            ax2.legend(fontsize=7.5)
        _save(fig, "fig2_convergence_and_ablations.svg")

    # --- Fig 3: Stage C (all 54 READY instances) + Incremental vs Full Speedup ---
    c_rows = [r for r in rows if r["stage"] == "Stage_C_54_READY"]
    if c_rows:
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.5, 4.8))
        for cid, label, col, marker in (
            ("stage_c_rcm", "RCM", "#7f7f7f", "^"),
            ("stage_c_sa_rcm", "SA (RCM, 1.5s)", "#4c72b0", "s"),
            ("stage_c_drsa_warm", "DRSA Warm (RCM, 1.5s)", "#55a868", "o"),
            ("stage_c_drsa_paper_random", "DRSA Paper (Random, 1.5s)", "#dd8452", "x"),
        ):
            sub = [r for r in c_rows if r["config_id"] == cid and r["published_best"] and r["final_bandwidth"] is not None]
            if sub:
                xs = [r["n"] for r in sub]
                ys = [(r["final_bandwidth"] - r["published_best"]) / r["published_best"] * 100.0 for r in sub]
                ax1.scatter(xs, ys, label=label, color=col, marker=marker, alpha=0.75, s=26)
        ax1.axhline(0.0, color="black", linestyle="--", linewidth=1.0)
        ax1.set_xlabel("Graph Order n (54 Verified READY Instances)")
        ax1.set_ylabel("Relative Excess over Published Best (%)")
        ax1.set_title("Stage C Scaling Across All 54 Verified READY Graphs")
        ax1.grid(True, linestyle="--", alpha=0.3)
        ax1.legend(fontsize=8)

        # Panel 2: Incremental vs Full Recomputation Throughput (5k fixed moves)
        sp_rows = [r for r in rows if r["experiment"] == "incremental_vs_full_speed"]
        sp_insts = []
        for r in sp_rows:
            if r["instance"] not in sp_insts:
                sp_insts.append(r["instance"])
        if sp_insts:
            x3 = list(range(len(sp_insts)))
            inc_rates = []
            full_rates = []
            for inst in sp_insts:
                ri = next(r for r in sp_rows if r["instance"] == inst and r["config_id"] == "ablate_speed_incremental")
                rf = next(r for r in sp_rows if r["instance"] == inst and r["config_id"] == "ablate_speed_full")
                inc_rates.append(ri["moves_evaluated"] / max(1e-6, ri["runtime_seconds"]))
                full_rates.append(rf["moves_evaluated"] / max(1e-6, rf["runtime_seconds"]))
            ax2.bar([xi - 0.18 for xi in x3], inc_rates, width=0.35, label="Incremental Delta State", color="#55a868")
            ax2.bar([xi + 0.18 for xi in x3], full_rates, width=0.35, label="Full Edge Recomputation", color="#c44e52")
            ax2.set_xticks(x3)
            ax2.set_xticklabels(sp_insts)
            ax2.set_ylabel("Throughput (moves / second)")
            ax2.set_title("Incremental Delta vs Full Recomputation (5,000 Moves)")
            ax2.grid(axis="y", linestyle="--", alpha=0.3)
            ax2.legend(fontsize=8)
        _save(fig, "fig3_stage_c_54_scaling.svg")

    # --- Fig 4: Operator usage / bandwidth improvements & Time-to-best ---
    drsa_b = [
        r
        for r in b_rows
        if r["config_id"] in ("drsa_paper_random", "drsa_modified_warm")
    ]
    if drsa_b:
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.5, 4.8))
        ops = ["REX", "NEX", "ROT"]
        colors_op = ["#4c72b0", "#dd8452", "#55a868"]
        for ci, cid, title_lbl in (
            (0, "drsa_paper_random", "DRSA Paper (Random)"),
            (1, "drsa_modified_warm", "DRSA Warm (RCM)"),
        ):
            sub = [r for r in drsa_b if r["config_id"] == cid]
            tot_moves = sum(
                (r["op_rex_count"] or 0) + (r["op_nex_count"] or 0) + (r["op_rot_count"] or 0)
                for r in sub
            )
            tot_imps = sum(
                (r["op_rex_improvements"] or 0) + (r["op_nex_improvements"] or 0) + (r["op_rot_improvements"] or 0)
                for r in sub
            )
            if tot_moves > 0:
                move_pcts = [
                    sum(r["op_rex_count"] or 0 for r in sub) * 100.0 / tot_moves,
                    sum(r["op_nex_count"] or 0 for r in sub) * 100.0 / tot_moves,
                    sum(r["op_rot_count"] or 0 for r in sub) * 100.0 / tot_moves,
                ]
            else:
                move_pcts = [0.0, 0.0, 0.0]
            if tot_imps > 0:
                imp_pcts = [
                    sum(r["op_rex_improvements"] or 0 for r in sub) * 100.0 / tot_imps,
                    sum(r["op_nex_improvements"] or 0 for r in sub) * 100.0 / tot_imps,
                    sum(r["op_rot_improvements"] or 0 for r in sub) * 100.0 / tot_imps,
                ]
            else:
                imp_pcts = [0.0, 0.0, 0.0]
            base_x = ci * 2.5
            bottom_m = 0.0
            bottom_i = 0.0
            for oi, op_name in enumerate(ops):
                lbl_m = f"{op_name}" if ci == 0 else None
                ax1.bar(base_x, move_pcts[oi], bottom=bottom_m, width=0.7, color=colors_op[oi], label=lbl_m, alpha=0.88)
                ax1.bar(base_x + 0.9, imp_pcts[oi], bottom=bottom_i, width=0.7, color=colors_op[oi], alpha=0.55, hatch="//")
                bottom_m += move_pcts[oi]
                bottom_i += imp_pcts[oi]
        ax1.set_xticks([0.0, 0.9, 2.5, 3.4])
        ax1.set_xticklabels(
            ["Paper\nUsage %", "Paper\nBW-Imp %", "Warm\nUsage %", "Warm\nBW-Imp %"],
            fontsize=8.5,
        )
        ax1.set_ylabel("Percentage (%)")
        ax1.set_title("Operator Selection Share (0.6/0.2/0.2) vs BW-Improvement Share")
        ax1.grid(axis="y", linestyle="--", alpha=0.3)
        ax1.legend(fontsize=8)

        # Panel 2: Time-to-best vs Absolute Improvement over Initial Heuristic (Stage B)
        for cid, label, col, marker in (
            ("sa_rcm_init", "SA (RCM)", "#4c72b0", "s"),
            ("drsa_modified_warm", "DRSA Warm (RCM)", "#55a868", "o"),
            ("drsa_paper_random", "DRSA Paper (Random)", "#dd8452", "^"),
        ):
            sub = [r for r in b_rows if r["config_id"] == cid and r["time_to_best_s"] is not None]
            if sub:
                ax2.scatter(
                    [r["time_to_best_s"] for r in sub],
                    [r["absolute_improvement"] for r in sub],
                    label=label,
                    color=col,
                    marker=marker,
                    alpha=0.75,
                    s=32,
                )
        ax2.axhline(0.0, color="black", linestyle="--", linewidth=0.9)
        ax2.set_xlabel("Time to Best Bandwidth (s)")
        ax2.set_ylabel("Absolute Improvement (init_bw - best_bw)")
        ax2.set_title("Stage B: Time-to-Best vs Improvement Over Initial Solution")
        ax2.grid(True, linestyle="--", alpha=0.3)
        ax2.legend(fontsize=8)
        _save(fig, "fig4_operator_usage_and_time_to_best.svg")

    return saved


def _write_summary_and_report(
    *,
    rows: list[dict[str, Any]],
    preflight_rows: list[dict[str, Any]],
    warm_checks: list[dict[str, Any]],
    figures: list[str],
    output_dir: Path,
    metadata: dict[str, Any],
    batch_stats: dict[str, Any],
) -> dict[str, Any]:
    by_stage_cfg: dict[str, dict[str, Any]] = {}
    for r in rows:
        key = f"{r['stage']}::{r['config_id']}"
        bucket = by_stage_cfg.setdefault(
            key,
            {
                "stage": r["stage"],
                "config_id": r["config_id"],
                "method": r["method"],
                "variant": r["variant"],
                "count": 0,
                "matched_best": 0,
                "improved_over_initial": 0,
                "bws": [],
                "gaps": [],
                "runtimes": [],
            },
        )
        bucket["count"] += 1
        if r["published_comparison"] == "MATCHED_BEST":
            bucket["matched_best"] += 1
        if r["absolute_improvement"] is not None and r["absolute_improvement"] > 0:
            bucket["improved_over_initial"] += 1
        if r["final_bandwidth"] is not None:
            bucket["bws"].append(r["final_bandwidth"])
        if r["gap_to_published_best"] is not None:
            bucket["gaps"].append(r["gap_to_published_best"])
        if r["runtime_seconds"] is not None:
            bucket["runtimes"].append(r["runtime_seconds"])

    aggregates: dict[str, dict[str, Any]] = {}
    for k, b in by_stage_cfg.items():
        aggregates[k] = {
            "stage": b["stage"],
            "config_id": b["config_id"],
            "method": b["method"],
            "variant": b["variant"],
            "count": b["count"],
            "matched_published_best": b["matched_best"],
            "improved_over_initial": b["improved_over_initial"],
            "mean_bandwidth": round(statistics.mean(b["bws"]), 4) if b["bws"] else None,
            "mean_gap_to_published_best": round(statistics.mean(b["gaps"]), 4) if b["gaps"] else None,
            "mean_runtime_s": round(statistics.mean(b["runtimes"]), 4) if b["runtimes"] else None,
        }

    summary = {
        "total_executed_runs": len(rows),
        "preflight_ready_total": len(preflight_rows),
        "all_validations_passed": all(r.get("validation") is True for r in rows),
        "stage_c_batch_stats": batch_stats,
        "config_aggregates": aggregates,
        "warm_start_checks": warm_checks,
        "figures": figures,
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    # Comparison markdown
    lines = [
        "# Member 3 Phase M3.4 – RCM vs SA vs DRSA Controlled Evaluation",
        "",
        f"- **Git commit:** `{metadata['git_commit']}`",
        f"- **Preflight verified READY:** `{len(preflight_rows)}` (`{metadata['provenance_counts']}`)",
        f"- **Executed runs:** `{len(rows)}` (`100% validation passed`: `{summary['all_validations_passed']}`)",
        f"- **Stage C batch coverage:** `{batch_stats}`",
        "",
        "## Summary by Stage & Configuration",
        "",
        "| Stage | Config ID | Method | Variant | Runs | Mean BW | Mean Gap to Pub Best | Matched Pub Best | Improved Over Init | Mean Time (s) |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for agg in aggregates.values():
        lines.append(
            f"| {agg['stage']} | {agg['config_id']} | {agg['method']} | {agg['variant']} | "
            f"{agg['count']} | {agg['mean_bandwidth']} | {agg['mean_gap_to_published_best']} | "
            f"{agg['matched_published_best']} | {agg['improved_over_initial']} | {agg['mean_runtime_s']} |"
        )

    b_rows = [r for r in rows if r["stage"] == "Stage_B_Pilot"]
    if b_rows:
        lines.extend(["", "## Stage B Mean Bandwidth Across Seeds {17, 23, 42} (4.0s)", ""])
        lines.append("| Instance | n | m | Pub Best | RCM | SA (RCM) | SA (Rand) | DRSA Paper (Rand) | DRSA (RCM T0=1000) | DRSA Warm (RCM T0=2) |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for inst in sorted({r["instance"] for r in b_rows}, key=lambda name: (ALL_INSTANCES[name].n, name)):
            meta = ALL_INSTANCES[inst]
            m_val = next((r["m"] for r in b_rows if r["instance"] == inst), "?")
            def _mean_cell(cid: str) -> str:
                vals = [r["final_bandwidth"] for r in b_rows if r["instance"] == inst and r["config_id"] == cid]
                if not vals:
                    return "—"
                if len(vals) == 1:
                    return str(vals[0])
                return f"{statistics.mean(vals):.2f} ({min(vals)}–{max(vals)})"
            lines.append(
                f"| {inst} | {meta.n} | {m_val} | {meta.paper_best} | "
                f"{_mean_cell('rcm_deterministic')} | {_mean_cell('sa_rcm_init')} | {_mean_cell('sa_random_init')} | "
                f"{_mean_cell('drsa_paper_random')} | {_mean_cell('drsa_rcm_t1000')} | {_mean_cell('drsa_modified_warm')} |"
            )

    if warm_checks:
        lines.extend(["", "## Warm-Start Verification (M3.4.9)", ""])
        lines.append("| Instance | DRSA Warm BW (Time s) | CP-SAT Status | CP-SAT BW (LB, Time s) | Inc SAT Status | SAT BW (LB, Time s) |")
        lines.append("|---|---:|---|---:|---|---:|")
        for w in warm_checks:
            lines.append(
                f"| {w['instance']} | {w['heuristic_bw']} ({w['heuristic_time_s']}s) | "
                f"{w['cp_sat_status']} | {w['cp_sat_bw']} ({w['cp_sat_lb']}, {w['cp_sat_time_s']}s) | "
                f"{w['sat_status']} | {w['sat_bw']} ({w['sat_lb']}, {w['sat_time_s']}s) |"
            )

    (output_dir / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def run(config_path: str | Path, *, resume: bool = True) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[3]
    cfg_file = Path(config_path)
    if not cfg_file.is_absolute():
        cfg_file = root / cfg_file
    cfg = tomllib.loads(cfg_file.read_text(encoding="utf-8"))["benchmark"]

    prov_path = root / cfg["provenance"]
    raw_dir = root / cfg["raw_dir"]
    fallback_raw = root / cfg["fallback_raw_dir"] if cfg.get("fallback_raw_dir") else None
    output_dir = root / cfg["output_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(cfg_file, output_dir / "config.toml")

    provenance_entries = json.loads(prov_path.read_text(encoding="utf-8"))
    preflight_rows, loaded_ready = _run_preflight(
        provenance_entries,
        raw_dir=raw_dir,
        fallback_raw_dir=fallback_raw,
        stage_b_set=set(cfg["stage_b_instances"]),
    )

    missing_b = sorted(set(cfg["stage_b_instances"]) - set(loaded_ready))
    if missing_b:
        raise RuntimeError(f"Missing or non-READY Stage B instances: {missing_b}")

    with (output_dir / "preflight.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=PREFLIGHT_FIELDS)
        writer.writeheader()
        for prow in preflight_rows:
            writer.writerow(_format_csv_row(prow, PREFLIGHT_FIELDS))

    ready_sorted = [row["instance"] for row in preflight_rows if row["stage_c_eligible"]]
    plan = _build_plan(cfg, ready_sorted)
    git_sha = _git_commit()

    runs_json_path = output_dir / "runs.json"
    trace_json_path = output_dir / "progress_trace.json"
    existing: dict[str, dict[str, Any]] = {}
    traces: dict[str, list[dict[str, Any]]] = {}
    if resume and runs_json_path.is_file():
        for prev in json.loads(runs_json_path.read_text(encoding="utf-8")):
            existing[str(prev["run_id"])] = prev
    if resume and trace_json_path.is_file():
        traces = json.loads(trace_json_path.read_text(encoding="utf-8"))

    stage_c_budget = float(cfg.get("stage_c_max_batch_seconds", 360.0))
    stage_c_started: float | None = None
    stage_c_planned = sum(1 for item in plan if item["stage"] == "Stage_C_54_READY")
    stage_c_skipped_budget = 0

    rows: list[dict[str, Any]] = []
    log_lines: list[str] = []

    for item in plan:
        rid = item["run_id"]
        if rid in existing:
            rows.append(existing[rid])
            log_lines.append(f"[RESUME] {rid} {item['stage']} {item['config_id']} {item['instance']}")
            continue

        if item["stage"] == "Stage_C_54_READY":
            if stage_c_started is None:
                stage_c_started = monotonic()
            elif (monotonic() - stage_c_started) >= stage_c_budget:
                stage_c_skipped_budget += 1
                log_lines.append(f"[BUDGET_SKIP] {rid} {item['config_id']} {item['instance']}")
                continue

        graph, prov, raw_path, paper_info = loaded_ready[item["instance"]]
        row, trace = _execute_item(
            item,
            graph=graph,
            prov=prov,
            raw_path=raw_path,
            paper_info=paper_info,
            git_sha=git_sha,
        )
        rows.append(row)
        if trace is not None and item["stage"] != "Stage_C_54_READY":
            traces[rid] = trace
        log_lines.append(
            f"[DONE] {rid} {row['stage']} {row['config_id']} {row['instance']} seed={row['seed']} -> "
            f"bw={row['final_bandwidth']} (init={row['initial_bandwidth']}, pub={row['published_best']}) "
            f"evals={row['moves_evaluated']} t={row['runtime_seconds']}s stop={row['stop_reason']}"
        )

        seen_ids = {str(r["run_id"]) for r in rows}
        checkpoint = rows + [r for key_id, r in existing.items() if key_id not in seen_ids]
        runs_json_path.write_text(json.dumps(checkpoint, indent=2), encoding="utf-8")
        trace_json_path.write_text(json.dumps(traces, indent=2), encoding="utf-8")

    runs_json_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    trace_json_path.write_text(json.dumps(traces, indent=2), encoding="utf-8")

    with (output_dir / "runs.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=M3_4_FIELDS)
        writer.writeheader()
        for r in rows:
            writer.writerow(_format_csv_row(r, M3_4_FIELDS))

    warm_checks = _run_warm_start_check(loaded_ready, seed=int(cfg["stage_c_seed"]))
    figures = _generate_figures(rows, traces, output_dir, list(cfg["stage_b_instances"]))

    stage_c_executed = sum(1 for r in rows if r["stage"] == "Stage_C_54_READY")
    batch_stats = {
        "stage_c_planned": stage_c_planned,
        "stage_c_executed": stage_c_executed,
        "stage_c_skipped_batch_budget": stage_c_skipped_budget,
        "stage_c_instances_covered": len({r["instance"] for r in rows if r["stage"] == "Stage_C_54_READY"}),
        "stage_c_max_batch_seconds": stage_c_budget,
    }

    metadata = {
        "experiment_name": cfg["name"],
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "git_commit": git_sha,
        "environment": {
            "os": platform.platform(),
            "machine": platform.machine(),
            "python_version": platform.python_version(),
        },
        "config": cfg,
        "provenance_counts": {
            "total": len(provenance_entries),
            "ready": sum(1 for e in provenance_entries if e["validation_status"] == "READY"),
            "needs_verification": sum(
                1 for e in provenance_entries if e["validation_status"] == "NEEDS_VERIFICATION"
            ),
            "invalid_data": sum(
                1 for e in provenance_entries if e["validation_status"] == "INVALID_DATA"
            ),
        },
        "total_planned_runs": len(plan),
    }

    summary = _write_summary_and_report(
        rows=rows,
        preflight_rows=preflight_rows,
        warm_checks=warm_checks,
        figures=figures,
        output_dir=output_dir,
        metadata=metadata,
        batch_stats=batch_stats,
    )
    (output_dir / "run_log.txt").write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/member3_m3_4.toml"),
        help="Path to M3.4 DRSA/SA/RCM TOML benchmark config",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        default=False,
        help="Ignore existing runs.json and run fresh",
    )
    args = parser.parse_args(argv)
    summary = run(args.config, resume=not args.no_resume)
    print(json.dumps({"total_executed_runs": summary["total_executed_runs"], "all_validations_passed": summary["all_validations_passed"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
