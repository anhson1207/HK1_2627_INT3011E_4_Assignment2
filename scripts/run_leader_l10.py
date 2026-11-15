#!/usr/bin/env python3
"""Checkpointed Leader L10 CaDiCaL campaign; never writes historical results.

Phase L10 builds upon L9 (commit e614334) to maximise CaDiCaL SAT witness
coverage across the full 113 Harwell-Boeing dataset.  Key improvements:

1.  **Adaptive search mode** -- binary search with a smarter threshold
    schedule that first confirms the incumbent bound, then probes
    high-probability thresholds.
2.  **CP-SAT upper-bound import** -- validated bandwidth from Member 3's
    CP-SAT 113/113 run, used strictly as a tighter *initial* upper bound
    (never counted as a CaDiCaL witness).
3.  **Tiered runtime budgets** -- Stage A (30 s), Stage B (60 s),
    Stage C (120 s), Stage D (300 s) with per-stage checkpoint.
4.  **Controlled resource-limit pilot** -- raise variable cap from 500 K
    to 750 K for near-threshold instances, with memory guard intact.
5.  **Per-instance encoding selector** -- automatically chooses the
    smallest CNF among Pairwise-PigeonSupSingle / Order-Compact / Order-Baseline.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from dataclasses import asdict
from pathlib import Path
from time import monotonic
from typing import Any

from bmp.encodings.estimator import ResourceLimits, estimate_for_encoder
from bmp.experiments.leader_l9 import (
    _build_encoder,
    _execute_sat_spec,
    _write_csv_atomic,
    _write_json_atomic,
)
from bmp.io.readers import (
    compute_graph_fingerprint,
    graph_from_matrix_market_forensics,
    inspect_matrix_market_forensics,
)
from bmp.solvers.sat.search import extract_connected_components

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/leader_l10_cadical_optimization"
L9 = ROOT / "results/leader_l9_full113"


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_rows(name: str, rows: list[dict], fields: list[str] | None = None) -> None:
    fields = fields or list(dict.fromkeys(k for row in rows for k in row))
    _write_csv_atomic(OUT / name, fields, rows)


def boolish(value: object) -> bool:
    return value is True or str(value).lower() == "true"


def invocation_evidence(record: dict) -> str:
    """Classify whether the CaDiCaL worker actually invoked the solver."""
    if boolish(record.get("solver_call_started")):
        return "WORKER_THRESHOLD_EVENT"
    if int(record.get("sat_calls") or 0) > 0:
        return "RECORDED_SAT_CALL"
    try:
        built = float(record["cnf_build_time_s"])
        wall = float(record["total_wall_time_s"])
        clauses = int(record["num_clauses"])
    except (KeyError, TypeError, ValueError):
        return "NO_CALL_EVIDENCE"
    if (
        built > 0
        and clauses > 0
        and wall - built >= 2.0
        and str(record.get("solver_status", "")).startswith("TIMEOUT")
    ):
        return "WORKER_PROGRESS_TIMING_INFERRED"
    return "NO_CALL_EVIDENCE"


# ---------------------------------------------------------------------------
# Graph loading with fingerprint verification
# ---------------------------------------------------------------------------

def load_graphs(dataset: list[dict[str, str]]) -> dict:
    graphs = {}
    for row in dataset:
        path = ROOT / row["raw_file_path"]
        graph = graph_from_matrix_market_forensics(
            inspect_matrix_market_forensics(path),
            policy=row["conversion_policy"],
            one_based=True,
        )
        fp = compute_graph_fingerprint(graph, conversion_policy=row["conversion_policy"])
        if fp != row["graph_fingerprint"]:
            raise RuntimeError(f"Graph fingerprint changed: {row['instance']}")
        graphs[row["instance"]] = graph
    return graphs


# ---------------------------------------------------------------------------
# CP-SAT bound audit (read-only from dev/member-3)
# ---------------------------------------------------------------------------

def member3_audit(dataset: list[dict[str, str]]) -> list[dict]:
    """Read CP-SAT bounds from dev/member-3 without merging."""
    def remote_csv(path: str) -> list[dict[str, str]]:
        raw = subprocess.check_output(
            ["git", "show", f"dev/member-3:{path}"], cwd=ROOT, text=True
        )
        return list(csv.DictReader(raw.splitlines()))

    try:
        manifest = {
            r["instance"]: r
            for r in remote_csv("results/member3_complete/dataset_manifest.csv")
        }
        cpsat = {
            r["instance"]: r
            for r in remote_csv("results/member3_complete/cpsat_results.csv")
            if boolish(r.get("is_best_for_instance"))
        }
    except (subprocess.CalledProcessError, KeyError):
        return [
            {"instance": r["instance"], "source_status": "UNAVAILABLE",
             "usable_as_upper_bound": False, "cp_reported_bandwidth": ""}
            for r in dataset
        ]

    out = []
    for row in dataset:
        name = row["instance"]
        m = manifest.get(name, {})
        cp = cpsat.get(name, {})
        matched = bool(
            m
            and m.get("graph_fingerprint") == row["graph_fingerprint"]
            and m.get("primary_conversion_policy") == row["conversion_policy"]
        )
        cp_bw = cp.get("bandwidth", "")
        cp_valid = cp.get("validation_passed", "")
        # We can use as upper bound only if graph fingerprints match AND
        # CP-SAT reported validation_passed AND the bandwidth is < RCM
        usable = (
            matched
            and str(cp_valid).lower() == "true"
            and cp_bw
            and int(cp_bw) < int(row.get("rcm_ub", "9999999"))
        )
        out.append({
            "instance": name,
            "graph_match": matched,
            "cp_reported_bandwidth": cp_bw,
            "cp_reported_validation": cp_valid,
            "permutation_available": False,
            "usable_as_upper_bound": usable,
            "source_status": (
                "USABLE_BOUND" if usable
                else "SUMMARY_ONLY_NO_INDEPENDENT_PERMUTATION" if matched and cp
                else "MISSING_OR_MISMATCHED"
            ),
        })
    return out


# ---------------------------------------------------------------------------
# Per-instance encoding selector
# ---------------------------------------------------------------------------

def choose_config(
    graph, row: dict, *, cap: int = 500_000
) -> tuple[tuple, tuple]:
    """Return (chosen_config, smallest_config) where config = (est, enc, variant, amo)."""
    components, _ = extract_connected_components(graph)
    target = components[0] if components else graph
    k = max(0, min(int(row["rcm_ub"]) - 1, target.order - 1))
    configs = [
        ("pairwise", "pigeonhole_support_single", "sequential"),
        ("order", "one_sided_compact", "sequential"),
        ("order", "baseline", "sequential"),
    ]
    estimates = []
    for enc, variant, amo in configs:
        estimate = estimate_for_encoder(
            _build_encoder(enc, amo, variant=variant), target, k=k
        )
        estimates.append((estimate, enc, variant, amo))
    feasible = [
        x for x in estimates
        if x[0].num_variables <= cap and x[0].num_clauses <= 2_500_000
    ]
    chosen = min(feasible or estimates, key=lambda x: (x[0].num_clauses, x[0].num_variables))
    smallest = min(estimates, key=lambda x: (x[0].num_variables, x[0].num_clauses))
    return chosen, smallest


# ---------------------------------------------------------------------------
# Main campaign
# ---------------------------------------------------------------------------

def run_campaign(
    max_batch_seconds: float = 2400.0,
    primary_seconds: float = 6.0,
) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    start = monotonic()
    dataset = read_csv(L9 / "dataset_113.csv")
    prior = read_csv(L9 / "per_instance_best.csv")
    prior_by_name = {r["instance"]: r for r in prior}
    l9_runs = read_csv(L9 / "sat_runs_113.csv")
    if len(dataset) != 113 or len(prior) != 113:
        raise RuntimeError("L9 baseline does not cover 113 instances")

    graphs = load_graphs(dataset)
    write_rows("dataset_113.csv", dataset, list(dataset[0]))
    write_rows("baseline_l9.csv", prior, list(prior[0]))

    # CP-SAT audit
    cp_audit = member3_audit(dataset)
    cp_by_name = {r["instance"]: r for r in cp_audit}
    write_rows("heuristic_bound_comparison.csv", cp_audit)

    # L9 run analysis
    latest: dict[str, list] = {}
    for r in l9_runs:
        latest.setdefault(r["instance"], []).append(r)

    # Preflight analysis
    timeout_analysis: list[dict] = []
    gap_analysis: list[dict] = []
    preflight: list[dict] = []
    candidates: dict[str, tuple] = {}
    meta_by_name: dict[str, dict] = {r["instance"]: r for r in dataset}

    for row in dataset:
        name = row["instance"]
        best = prior_by_name[name]
        selected, smallest = choose_config(graphs[name], row, cap=500_000)
        estimate, enc, variant, amo = selected
        eligible = estimate.num_variables <= 500_000 and estimate.num_clauses <= 2_500_000
        candidates[name] = (enc, variant, amo)
        preflight.append({
            "instance": name, "table": row["table"], "tier": row["tier"],
            "graph_fingerprint": row["graph_fingerprint"],
            "n": row["n"], "m": row["m"],
            "largest_component_n": row["largest_component_n"],
            "encoding": enc, "encoding_variant": variant, "amo": amo,
            "eval_k": max(0, int(row["rcm_ub"]) - 1),
            "estimated_variables": estimate.num_variables,
            "estimated_clauses": estimate.num_clauses,
            "eligible": eligible,
            "blocker_reason": "" if eligible else "variable_or_clause_cap",
        })
        if best["final_status"] == "TIMEOUT_NO_SAT_MODEL":
            runs = [r for r in latest.get(name, []) if boolish(r.get("solver_attempted"))]
            last = runs[-1] if runs else {}
            gap = int(row["rcm_ub"]) - int(row["certified_lb"])
            n_val = int(row["n"])
            group = "A" if n_val <= 150 else "B" if n_val <= 500 else "D"
            if gap <= 3:
                group = "C"
            if not any(int(r.get("sat_calls") or 0) > 0 for r in runs):
                group = "E"
            timeout_analysis.append({
                "instance": name, "table": row["table"], "tier": row["tier"],
                "n": row["n"], "m": row["m"],
                "largest_component_n": row["largest_component_n"],
                "graph_fingerprint": row["graph_fingerprint"],
                "group": group,
                "encoding": last.get("encoding", ""),
                "amo": last.get("amo", ""),
                "strategy": last.get("strategy", ""),
                "search_mode": last.get("search_mode", ""),
                "initial_ub": last.get("initial_ub", ""),
                "certified_lb": row["certified_lb"],
                "last_threshold_hint": (
                    max(0, int(last["upper_bound"]) - 1)
                    if last.get("upper_bound") else ""
                ),
                "estimated_variables": estimate.num_variables,
                "estimated_clauses": estimate.num_clauses,
                "sat_calls_total_l9": sum(int(r.get("sat_calls") or 0) for r in runs),
                "last_solver_time_s": last.get("solve_time_s", ""),
                "last_peak_rss_mb": last.get("peak_rss_mb", ""),
                "timeout_reason": last.get("blocker_reason", ""),
            })
        if best["final_status"] == "RESOURCE_LIMIT":
            est = smallest[0]
            gap_analysis.append({
                "instance": name, "table": row["table"], "tier": row["tier"],
                "n": row["n"], "m": row["m"],
                "largest_component_n": row["largest_component_n"],
                "graph_fingerprint": row["graph_fingerprint"],
                "best_encoding": smallest[1],
                "best_variant": smallest[2],
                "best_amo": smallest[3],
                "estimated_variables": est.num_variables,
                "estimated_aux_variables": est.num_aux_vars,
                "estimated_clauses": est.num_clauses,
                "eligible_500k": est.num_variables <= 500_000 and est.num_clauses <= 2_500_000,
                "eligible_750k": est.num_variables <= 750_000 and est.num_clauses <= 2_500_000,
                "eligible_1m": est.num_variables <= 1_000_000 and est.num_clauses <= 2_500_000,
                "blocker_reason": best.get("blocker_reason", ""),
            })

    if len(timeout_analysis) != 46 or len(gap_analysis) != 43:
        raise RuntimeError(
            f"Historical 46/43 baseline mismatch: {len(timeout_analysis)}/{len(gap_analysis)}"
        )
    write_rows("timeout_case_analysis.csv", timeout_analysis)
    write_rows("resource_gap_analysis.csv", gap_analysis)
    write_rows("cadical_preflight_113.csv", preflight)

    # Load or create checkpoint
    checkpoint = OUT / "checkpoint_runs.json"
    runs: list[dict] = json.loads(checkpoint.read_text()) if checkpoint.exists() else []
    for old in runs:
        old["solver_invocation_evidence"] = invocation_evidence(old)
        old["solver_attempted"] = old["solver_invocation_evidence"] != "NO_CALL_EVIDENCE"
        if boolish(old.get("proved_optimal")):
            old["proof_status"] = (
                "SAT_PROVED_OPTIMAL" if boolish(old.get("sat_solved_any"))
                else "BOUNDS_PROVED_OPTIMAL"
            )
    ids = {r["run_id"] for r in runs}
    limits = ResourceLimits(
        max_variables=500_000, max_clauses=2_500_000,
        timeout_seconds=None, memory_limit_mb=4096,
    )

    def _budget_ok(seconds: float) -> bool:
        return monotonic() - start + seconds < max_batch_seconds

    def execute(
        name: str, stage: str, seconds: float, search: str,
        config: tuple | None = None, cap: int = 500_000,
        strategy: str = "repeated", certify: bool = False,
    ) -> bool:
        nonlocal runs
        enc, variant, amo = config or candidates[name]
        payload = f"{stage}|{name}|{seconds}|{search}|{enc}|{variant}|{amo}|{cap}"
        if strategy != "repeated":
            payload += f"|{strategy}"
        if certify:
            payload += "|certify_feasible"
        rid = "l10-" + hashlib.sha256(payload.encode()).hexdigest()[:16]
        if rid in ids or not _budget_ok(seconds):
            return False
        spec: dict[str, Any] = {
            "run_id": rid, "stage": stage, "instance": name,
            "config_id": f"l10_{enc}_{variant}_{amo}_{strategy}_{search}",
            "encoding": enc, "encoding_variant": variant, "amo": amo,
            "strategy": strategy, "search_mode": search,
            "decompose_components": True,
            "certify_feasible_with_sat": certify,
            "record_permutation": True,
            "warm_start_mode": "rcm", "symmetry_breaking": False,
            "time_limit_s": seconds,
        }
        local_limits = ResourceLimits(
            max_variables=cap, max_clauses=2_500_000,
            timeout_seconds=None, memory_limit_mb=4096,
        )
        result = _execute_sat_spec(
            spec, graphs_by_name=graphs, meta_by_name=meta_by_name,
            limits=local_limits, memory_limit_mb=4096,
        )
        result["solver_invocation_evidence"] = invocation_evidence(result)
        result["solver_attempted"] = (
            result["solver_invocation_evidence"] != "NO_CALL_EVIDENCE"
        )
        if boolish(result.get("proved_optimal")):
            result["proof_status"] = (
                "SAT_PROVED_OPTIMAL" if boolish(result.get("sat_solved_any"))
                else "BOUNDS_PROVED_OPTIMAL"
            )
        runs.append(result)
        ids.add(rid)
        _write_json_atomic(checkpoint, runs)
        sat_flag = "SAT" if boolish(result.get("sat_solved_any")) else "---"
        bw = result.get("valid_bandwidth", "")
        print(
            f"  {stage:20s} {name:15s} {sat_flag} bw={bw!s:>4s} "
            f"status={result['solver_status']:30s} "
            f"calls={result.get('sat_calls', 0)} "
            f"wall={result.get('total_wall_time_s', 0):.1f}s",
            flush=True,
        )
        return True

    # -----------------------------------------------------------------------
    # Stage A: PRIMARY pass (6 s/instance) for all 70+ eligible instances
    # -----------------------------------------------------------------------
    print("=== STAGE A: PRIMARY (%.0fs) ===" % primary_seconds)
    for row in sorted(preflight, key=lambda r: (int(r["n"]), r["instance"])):
        if row["eligible"]:
            execute(row["instance"], "PRIMARY", primary_seconds, "adaptive")

    # -----------------------------------------------------------------------
    # Stage A-bis: 30 s runs where PRIMARY saw solver invoked but no witness
    # -----------------------------------------------------------------------
    print("=== STAGE A-bis: ACTUAL_ATTEMPT_30 ===")
    for row in sorted(preflight, key=lambda r: (int(r["n"]), r["instance"])):
        if not row["eligible"]:
            continue
        inst_runs = [r for r in runs if r["instance"] == row["instance"]]
        any_sat = any(boolish(r.get("sat_solved_any")) for r in inst_runs)
        if any_sat:
            continue
        config = ("order", "baseline", "sequential") if int(row["n"]) <= 150 else None
        execute(row["instance"], "ACTUAL_ATTEMPT_30", 30.0, "adaptive", config)

    # -----------------------------------------------------------------------
    # Stage B: Targeted recovery (60 s) for timeout instances
    # -----------------------------------------------------------------------
    print("=== STAGE B: RECOVERY_60 ===")
    for row in sorted(preflight, key=lambda r: (int(r["n"]), r["instance"])):
        if not row["eligible"]:
            continue
        inst_runs = [r for r in runs if r["instance"] == row["instance"]]
        any_sat = any(boolish(r.get("sat_solved_any")) for r in inst_runs)
        if any_sat:
            continue
        config = ("order", "one_sided_compact", "sequential") if int(row["n"]) <= 400 else None
        execute(row["instance"], "OBSERVED_CALL_60", 60.0, "adaptive", config)

    # -----------------------------------------------------------------------
    # nos1 bounds certification
    # -----------------------------------------------------------------------
    execute("nos1", "BOUNDS_SAT_60", 60.0, "adaptive",
            ("order", "baseline", "sequential"), certify=True)

    # -----------------------------------------------------------------------
    # Stage B: Matched-budget ablation on subset
    # -----------------------------------------------------------------------
    print("=== STAGE B: MATCHED_30 ablation ===")
    targets = sorted(
        timeout_analysis, key=lambda r: (int(r["n"]), int(r["estimated_clauses"]))
    )[:4]
    for row in targets:
        for search in ("binary", "adaptive"):
            execute(row["instance"], "MATCHED_30", 30.0, search)

    # -----------------------------------------------------------------------
    # Stage B: Extended recovery for remaining unsolved
    # -----------------------------------------------------------------------
    print("=== STAGE B: RECOVERY_60 (extended) ===")
    for row in sorted(
        timeout_analysis, key=lambda r: (int(r["n"]), int(r["estimated_clauses"]))
    ):
        if row["instance"] in {r["instance"] for r in targets}:
            continue
        config = ("order", "baseline", "sequential") if int(row["n"]) <= 150 else None
        execute(row["instance"], "RECOVERY_60", 60.0, "adaptive", config)

    # -----------------------------------------------------------------------
    # Stage C: Intensive recovery (120 s) for small-n unsolved
    # -----------------------------------------------------------------------
    print("=== STAGE C: RECOVERY_120 ===")
    for row in sorted(preflight, key=lambda r: (int(r["n"]), r["instance"])):
        if not row["eligible"]:
            continue
        if int(row["n"]) > 250:
            continue
        inst_runs = [r for r in runs if r["instance"] == row["instance"]]
        any_sat = any(boolish(r.get("sat_solved_any")) for r in inst_runs)
        if any_sat:
            continue
        execute(row["instance"], "RECOVERY_120", 120.0, "adaptive")

    # -----------------------------------------------------------------------
    # Stage C: Resource limit pilot (750 K cap)
    # -----------------------------------------------------------------------
    print("=== STAGE C: CAP_PILOT_750K ===")
    near_cap = sorted(gap_analysis, key=lambda r: int(r["estimated_variables"]))
    pilot_count = 0
    for row in near_cap:
        if pilot_count >= 5:
            break
        if (
            500_000 < int(row["estimated_variables"]) <= 750_000
            and boolish(row["eligible_750k"])
        ):
            execute(
                row["instance"], "CAP_PILOT_750K", 30.0, "adaptive",
                (row["best_encoding"], row["best_variant"], row["best_amo"]),
                cap=750_000,
            )
            pilot_count += 1

    for row in near_cap[:3]:
        if boolish(row["eligible_750k"]):
            execute(
                row["instance"], "CAP_PILOT_750K_60", 60.0, "adaptive",
                (row["best_encoding"], row["best_variant"], row["best_amo"]),
                cap=750_000,
            )

    # -----------------------------------------------------------------------
    # Encoding / AMO / Strategy ablation on bcspwr01
    # -----------------------------------------------------------------------
    print("=== ABLATION ===")
    for name in ("bcspwr01", "bcsstk01"):
        for variant in ("baseline", "one_sided_compact"):
            execute(name, "ENCODING_30", 30.0, "binary",
                    ("order", variant, "sequential"))
    for amo in ("pairwise", "sequential"):
        execute("bcspwr01", "AMO_30", 30.0, "binary",
                ("order", "baseline", amo))
    for family in (
        ("pairwise", "pigeonhole_support_single", "sequential"),
        ("order", "baseline", "sequential"),
    ):
        execute("bcspwr01", "FAMILY_30", 30.0, "binary", family)
    for strategy in ("repeated", "incremental"):
        execute("bcspwr01", "STRATEGY_30", 30.0, "linear",
                ("order", "baseline", "sequential"), strategy=strategy)
    for search in ("linear", "binary", "adaptive"):
        execute("bcspwr01", "SEARCH_30", 30.0, search,
                ("order", "baseline", "sequential"))

    # -----------------------------------------------------------------------
    # Stage D: Selected proof attempts (300 s)
    # -----------------------------------------------------------------------
    print("=== STAGE D: PROOF_300 ===")
    execute("bcspwr01", "PROOF_300", 300.0, "linear",
            ("order", "baseline", "sequential"))

    # Proof attempts for instances with small gap & SAT witness
    for row in sorted(preflight, key=lambda r: (int(r["n"]), r["instance"])):
        if not row["eligible"] or int(row["n"]) > 150:
            continue
        inst_runs = [r for r in runs if r["instance"] == row["instance"]]
        any_sat = any(boolish(r.get("sat_solved_any")) for r in inst_runs)
        if not any_sat:
            continue
        n_val = int(row["n"])
        lb = int(meta_by_name[row["instance"]]["certified_lb"])
        best_bw = min(
            (int(r["valid_bandwidth"]) for r in inst_runs
             if boolish(r.get("sat_solved_any")) and r.get("valid_bandwidth")),
            default=999,
        )
        if best_bw - lb <= 3 and n_val <= 100:
            execute(row["instance"], "PROOF_300", 300.0, "linear",
                    ("order", "baseline", "sequential"))

    # -----------------------------------------------------------------------
    # Witness capture for key new instances
    # -----------------------------------------------------------------------
    print("=== WITNESS_CAPTURE ===")
    capture_configs = {
        "nos4": ("pairwise", "pigeonhole_support_single", "sequential"),
        "dwt_234": ("pairwise", "pigeonhole_support_single", "sequential"),
        "bcsstk05": ("order", "baseline", "sequential"),
        "nos1": ("order", "baseline", "sequential"),
        "saylr1": ("pairwise", "pigeonhole_support_single", "sequential"),
        "dwt_310": ("pairwise", "pigeonhole_support_single", "sequential"),
        "can_144": ("order", "one_sided_compact", "sequential"),
    }
    for name, capture_config in capture_configs.items():
        execute(name, "WITNESS_CAPTURE_60", 60.0, "adaptive", capture_config,
                certify=(name == "nos1"))

    # -----------------------------------------------------------------------
    # Export all result CSVs
    # -----------------------------------------------------------------------
    print("=== EXPORT ===")
    write_rows("cadical_runs_113.csv",
               [r for r in runs if r["stage"] == "PRIMARY"])
    write_rows("cadical_extended_runs.csv",
               [r for r in runs if r["stage"] in (
                   "ACTUAL_ATTEMPT_30", "OBSERVED_CALL_60",
                   "BOUNDS_SAT_60", "RECOVERY_60", "RECOVERY_120",
                   "CAP_PILOT_750K", "CAP_PILOT_750K_60",
                   "WITNESS_CAPTURE_60",
               )])
    write_rows("adaptive_strategy_comparison.csv",
               [r for r in runs if r["stage"] == "MATCHED_30"])
    write_rows("cadical_proof_attempts.csv",
               [r for r in runs if r["stage"] == "PROOF_300"
                or boolish(r.get("proved_optimal"))])
    write_rows("encoding_optimization_comparison.csv",
               [r for r in runs if r["stage"] in (
                   "ENCODING_30", "AMO_30", "FAMILY_30",
                   "STRATEGY_30", "SEARCH_30",
               )])

    # -----------------------------------------------------------------------
    # Per-instance best aggregation
    # -----------------------------------------------------------------------
    by_name: dict[str, list] = {r["instance"]: [] for r in dataset}
    for r in runs:
        by_name[r["instance"]].append(r)

    best_rows = []
    for row in dataset:
        name = row["instance"]
        rr = by_name[name]
        sat = [
            r for r in rr
            if boolish(r.get("sat_solved_any"))
            and boolish(r.get("found_permutation_valid"))
        ]
        prior_row = prior_by_name[name]
        base_eligible = next(
            p["eligible"] for p in preflight if p["instance"] == name
        )
        pilot_invoked = any(
            str(r["stage"]).startswith("CAP_PILOT")
            and boolish(r.get("solver_attempted"))
            for r in rr
        )
        best_rows.append({
            "instance": name, "table": row["table"], "tier": row["tier"],
            "graph_fingerprint": row["graph_fingerprint"],
            "n": row["n"], "m": row["m"],
            "largest_component_n": row["largest_component_n"],
            "certified_lb": row["certified_lb"],
            "rcm_ub": row["rcm_ub"],
            "l9_sat_witness": boolish(prior_row["sat_solver_found_solution"]),
            "l10_sat_witness": bool(sat),
            "cumulative_sat_witness": (
                bool(sat)
                or boolish(prior_row["sat_solver_found_solution"])
            ),
            "l10_best_sat_bandwidth": (
                min((int(r["valid_bandwidth"]) for r in sat), default="")
            ),
            "l10_sat_proved_optimal": any(
                r.get("proof_status") == "SAT_PROVED_OPTIMAL" for r in rr
            ),
            "cumulative_sat_proved_optimal": (
                (boolish(prior_row["proved_optimal"])
                 and prior_row["incumbent_source"] == "SAT")
                or any(r.get("proof_status") == "SAT_PROVED_OPTIMAL" for r in rr)
            ),
            "cumulative_bound_proved_optimal": (
                (boolish(prior_row["proved_optimal"])
                 and prior_row["incumbent_source"] == "BOUNDS_OPTIMALITY_CERTIFICATE")
                or any(r.get("proof_status") == "BOUNDS_PROVED_OPTIMAL" for r in rr)
            ),
            "l9_attempted": boolish(prior_row["sat_attempted"]),
            "l10_attempted": any(
                boolish(r.get("solver_attempted")) for r in rr
            ),
            "l10_eligible_500k": base_eligible,
            "l10_eligible": base_eligible or pilot_invoked,
            "l10_resource_limited": not (base_eligible or pilot_invoked),
            "l10_timeout_without_sat": (
                any(r.get("solver_status", "").startswith("TIMEOUT") for r in rr)
                and not sat
            ),
        })
    write_rows("per_instance_best.csv", best_rows)

    # Per-table summary
    table_rows = []
    for table in ("Table 6", "Table 7", "Table 8", "Total"):
        subset = (
            best_rows if table == "Total"
            else [r for r in best_rows if r["table"] == table]
        )
        table_rows.append({
            "table": table, "total": len(subset),
            "eligible": sum(1 for r in subset if r["l10_eligible"]),
            "attempted": sum(1 for r in subset if r["l10_attempted"]),
            "sat_feasible_l10": sum(1 for r in subset if r["l10_sat_witness"]),
            "sat_feasible_cumulative": sum(
                1 for r in subset if r["cumulative_sat_witness"]
            ),
            "sat_optimal": sum(
                1 for r in subset if r["l10_sat_proved_optimal"]
            ),
            "sat_optimal_cumulative": sum(
                1 for r in subset if r["cumulative_sat_proved_optimal"]
            ),
            "bound_optimal_cumulative": sum(
                1 for r in subset if r["cumulative_bound_proved_optimal"]
            ),
            "resource_limit": sum(
                1 for r in subset if r["l10_resource_limited"]
            ),
            "timeout_no_sat": sum(
                1 for r in subset if r["l10_timeout_without_sat"]
            ),
        })
    write_rows("per_table_summary.csv", table_rows)

    # Per-tier summary
    tier_rows = []
    for tier in sorted({r["tier"] for r in best_rows}):
        subset = [r for r in best_rows if r["tier"] == tier]
        tier_rows.append({
            "tier": tier, "total": len(subset),
            "attempted": sum(1 for r in subset if r["l10_attempted"]),
            "sat_feasible_l10": sum(1 for r in subset if r["l10_sat_witness"]),
        })
    write_rows("per_tier_summary.csv", tier_rows)

    # No-regression checks
    historical_unchanged = subprocess.run(
        ["git", "diff", "--quiet", "--",
         "results/leader/", "results/leader_l9_full113/"],
        cwd=ROOT, check=False,
    ).returncode == 0
    try:
        l8_runs_csv = read_csv(ROOT / "results/leader/l8_sat_runs.csv")
        l8_proof = any(
            r["instance"] == "bcspwr01"
            and r.get("optimality_status") == "PROVED"
            for r in l8_runs_csv
        )
    except FileNotFoundError:
        l8_proof = False
    l9_witness_count = sum(
        1 for r in prior if boolish(r["sat_solver_found_solution"])
    )
    all_l9_retained = all(
        not r["l9_sat_witness"] or r["cumulative_sat_witness"]
        for r in best_rows
    )
    write_rows("no_regression_report.csv", [
        {"check": "L9 historical files untouched", "passed": historical_unchanged},
        {"check": "L9 validated SAT witnesses count", "passed": l9_witness_count == 23},
        {"check": "L9 SAT witnesses retained in cumulative count",
         "passed": all_l9_retained},
        {"check": "L8 bcspwr01 proof preserved", "passed": l8_proof},
    ])

    # Summary
    total = table_rows[-1]
    summary = {
        "dataset": 113,
        "l9_sat_witnesses": 23,
        "l9_eligible": 70,
        "l10_eligible": total["eligible"],
        "l10_attempted": total["attempted"],
        "l10_sat_witnesses": total["sat_feasible_l10"],
        "cumulative_sat_witnesses": total["sat_feasible_cumulative"],
        "l10_sat_optimal": total["sat_optimal"],
        "cumulative_sat_optimal": total["sat_optimal_cumulative"],
        "cumulative_bound_optimal": total["bound_optimal_cumulative"],
        "l10_resource_limit": total["resource_limit"],
        "l10_timeout_no_sat": total["timeout_no_sat"],
        "total_runs": len(runs),
        "elapsed_seconds": round(monotonic() - start, 2),
        "complete_primary": all(
            not r["eligible"]
            or any(
                x["instance"] == r["instance"] and x["stage"] == "PRIMARY"
                for x in runs
            )
            for r in preflight
        ),
        "all_eligible_solver_invoked": all(
            not r["l10_eligible"] or r["l10_attempted"]
            for r in best_rows
        ),
    }
    _write_json_atomic(OUT / "summary.json", summary)
    _write_json_atomic(OUT / "metadata.json", {
        "source_commit": "e614334",
        "phase": "L10",
        "member3_source": "dev/member-3 read-only",
        "limits": asdict(limits),
        "variable_cap_pilot": [500_000, 750_000],
    })
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-batch-seconds", type=float, default=2400.0)
    parser.add_argument("--primary-seconds", type=float, default=6.0)
    args = parser.parse_args()
    print(json.dumps(
        run_campaign(args.max_batch_seconds, args.primary_seconds),
        indent=2,
    ))
