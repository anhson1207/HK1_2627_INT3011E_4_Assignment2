"""Phase M2.3: 54-READY preflight, license-aware MIP guards, baseline & controlled studies."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import platform
import statistics
import sys
import tomllib
from pathlib import Path
from time import monotonic
from typing import Any

from bmp.core.benchmark_catalog import ALL_INSTANCES, BenchmarkInstanceMeta
from bmp.core.graph import Graph
from bmp.core.solution import SolutionStatus
from bmp.core.validation import validate_solution
from bmp.encodings.estimator import ResourceLimits, estimate_cnf_size
from bmp.experiments.member2_hb import (
    FIELDS,
    _git_commit,
    _load_provenance_and_audit,
    _mip_backend_version,
    _pilot_small_graphs,
    _run_mip_direct,
    _run_sat_direct,
    _sat_backend_version,
    _self_rss_mb,
    _supports_fork,
)
from bmp.io.readers import inspect_matrix_market
from bmp.solvers.sat.search import compute_initial_upper_bound, compute_lower_bound

M2_3_FIELDS: tuple[str, ...] = FIELDS + (
    "threads",
    "threshold_policy",
    "mip_vars",
    "mip_constrs",
    "license_status",
    "proof_comparison_tag",
    "topology_components",
    "topology_max_degree",
)

PREFLIGHT_FIELDS: tuple[str, ...] = (
    "instance",
    "table",
    "n",
    "m",
    "file_checksum_status",
    "graph_validation_status",
    "dataset_ready",
    "connected_components",
    "isolated_vertices",
    "max_degree",
    "density",
    "initial_lb",
    "initial_ub",
    "pairwise_cnf_vars",
    "pairwise_cnf_clauses",
    "pairwise_cnf_estimate",
    "order_cnf_vars",
    "order_cnf_clauses",
    "order_cnf_estimate",
    "order_binary_cnf_vars",
    "order_binary_cnf_clauses",
    "order_at_ub_clauses",
    "mip_vars",
    "mip_constrs",
    "mip_estimate",
    "eligibility_sat",
    "eligibility_pairwise_sat",
    "eligibility_gurobi",
    "eligibility_cplex",
    "solver_executable",
    "timeout_feasibility_note",
    "reason",
)


def _graph_topology(graph: Graph) -> tuple[int, int, int]:
    """Return (connected_components, isolated_vertices, max_degree) in O(n + m)."""
    if graph.order == 0:
        return 0, 0, 0
    adj: dict[int, list[int]] = {v: [] for v in graph.vertices}
    for u, v in graph.edges:
        adj[u].append(v)
        adj[v].append(u)
    isolated = sum(1 for nbrs in adj.values() if not nbrs)
    max_deg = max((len(nbrs) for nbrs in adj.values()), default=0)
    seen: set[int] = set()
    components = 0
    for start in graph.vertices:
        if start in seen:
            continue
        components += 1
        stack = [start]
        seen.add(start)
        while stack:
            cur = stack.pop()
            for nxt in adj[cur]:
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
    return components, isolated, max_deg


def detect_commercial_licenses() -> dict[str, dict[str, Any]]:
    """Probe active Gurobi and CPLEX license capabilities without touching license files."""
    info: dict[str, dict[str, Any]] = {}

    # Probe Gurobi
    try:
        import gurobipy as gp

        env = None
        model = None
        try:
            env = gp.Env(empty=True)
            env.setParam("OutputFlag", 0)
            env.start()
            version = ".".join(map(str, gp.gurobi.version()))
            model = gp.Model("license_probe", env=env)
            model.addVars(2001, vtype=gp.GRB.BINARY, name="x")
            model.optimize()
            info["gurobi"] = {
                "available": True,
                "license_type": "FULL_OR_UNRESTRICTED",
                "max_variables": None,
                "max_constraints": None,
                "version": version,
                "note": "Gurobi solved >2000-variable empty probe without size restriction",
            }
        except gp.GurobiError as exc:
            msg = str(exc)
            if "size-limited" in msg.lower() or "too large" in msg.lower():
                info["gurobi"] = {
                    "available": True,
                    "license_type": "SIZE_LIMITED_EVAL",
                    "max_variables": 2000,
                    "max_constraints": 2000,
                    "version": ".".join(map(str, gp.gurobi.version())),
                    "note": "PyPI embedded size-limited evaluation license (max 2,000 vars & 2,000 constrs)",
                }
            else:
                info["gurobi"] = {
                    "available": False,
                    "license_type": "LICENSE_INVALID",
                    "max_variables": 0,
                    "max_constraints": 0,
                    "version": "unavailable",
                    "note": msg,
                }
        finally:
            if model is not None:
                try:
                    model.dispose()
                except Exception:
                    pass
            if env is not None:
                try:
                    env.dispose()
                except Exception:
                    pass
    except ImportError as exc:
        info["gurobi"] = {
            "available": False,
            "license_type": "PACKAGE_MISSING",
            "max_variables": 0,
            "max_constraints": 0,
            "version": "missing",
            "note": str(exc),
        }

    # Probe CPLEX
    try:
        import cplex

        model = None
        try:
            model = cplex.Cplex()
            model.set_log_stream(None)
            model.set_results_stream(None)
            model.set_warning_stream(None)
            model.set_error_stream(None)
            version = str(model.get_version())
            model.variables.add(types="B" * 1001)
            model.solve()
            info["cplex"] = {
                "available": True,
                "license_type": "FULL_OR_UNRESTRICTED",
                "max_variables": None,
                "max_constraints": None,
                "version": version,
                "note": "CPLEX solved >1000-variable empty probe without size restriction",
            }
        except cplex.exceptions.CplexError as exc:
            msg = str(exc)
            if "1016" in msg or "community edition" in msg.lower():
                info["cplex"] = {
                    "available": True,
                    "license_type": "COMMUNITY_EDITION",
                    "max_variables": 1000,
                    "max_constraints": 1000,
                    "version": version if "version" in locals() else "unavailable",
                    "note": "IBM CPLEX Community Edition (Error 1016 above 1,000 vars or 1,000 constrs)",
                }
            else:
                info["cplex"] = {
                    "available": False,
                    "license_type": "LICENSE_INVALID",
                    "max_variables": 0,
                    "max_constraints": 0,
                    "version": "unavailable",
                    "note": msg,
                }
        finally:
            if model is not None:
                try:
                    model.end()
                except Exception:
                    pass
    except ImportError as exc:
        info["cplex"] = {
            "available": False,
            "license_type": "PACKAGE_MISSING",
            "max_variables": 0,
            "max_constraints": 0,
            "version": "missing",
            "note": str(exc),
        }

    return info


def export_preflight_54(
    *,
    provenance_path: Path,
    raw_dir: Path,
    output_dir: Path,
    max_sat_vars: int = 500_000,
    max_sat_clauses: int = 2_500_000,
    licenses: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Run full 54-READY preflight and export preflight_54.csv/.json."""
    prov_map = {
        entry["instance"]: entry
        for entry in json.loads(provenance_path.read_text(encoding="utf-8"))
    }
    licenses = licenses or detect_commercial_licenses()
    sat_limits = ResourceLimits(max_variables=max_sat_vars, max_clauses=max_sat_clauses)

    gurobi_cap_v = licenses["gurobi"].get("max_variables")
    gurobi_cap_c = licenses["gurobi"].get("max_constraints")
    cplex_cap_v = licenses["cplex"].get("max_variables")
    cplex_cap_c = licenses["cplex"].get("max_constraints")

    ready_metas = sorted(
        (
            m
            for m in ALL_INSTANCES.values()
            if prov_map.get(m.name, {}).get("validation_status") == "READY"
        ),
        key=lambda m: (m.source_table, m.n, m.name),
    )

    records: list[dict[str, Any]] = []
    for meta in ready_metas:
        prov = prov_map[meta.name]
        fpath = Path(str(prov.get("file_path") or ""))
        if not fpath.exists():
            fpath = raw_dir / f"{meta.name}.mtx.gz"

        file_exists = fpath.exists()
        actual_sha = hashlib.sha256(fpath.read_bytes()).hexdigest() if file_exists else None
        expected_sha = str(prov.get("sha256") or "")
        if not file_exists:
            sha_status = "MISSING"
        elif actual_sha == expected_sha:
            sha_status = "VERIFIED"
        else:
            sha_status = "CHECKSUM_MISMATCH"

        audit = inspect_matrix_market(fpath) if file_exists else None
        graph = audit.graph if audit is not None else None
        n_ok = graph is not None and graph.order == meta.n
        mm_status = audit.status if audit is not None else "MISSING"
        dataset_ready = bool(file_exists and sha_status == "VERIFIED" and mm_status == "READY" and n_ok)

        if graph is None:
            records.append({
                "instance": meta.name,
                "table": meta.source_table,
                "n": meta.n,
                "m": 0,
                "file_checksum_status": sha_status,
                "graph_validation_status": mm_status,
                "dataset_ready": False,
                "connected_components": 0,
                "isolated_vertices": 0,
                "max_degree": 0,
                "density": 0.0,
                "initial_lb": None,
                "initial_ub": None,
                "pairwise_cnf_vars": None,
                "pairwise_cnf_clauses": None,
                "pairwise_cnf_estimate": "N/A",
                "order_cnf_vars": None,
                "order_cnf_clauses": None,
                "order_cnf_estimate": "N/A",
                "order_binary_cnf_vars": None,
                "order_binary_cnf_clauses": None,
                "order_at_ub_clauses": None,
                "mip_vars": None,
                "mip_constrs": None,
                "mip_estimate": "N/A",
                "eligibility_sat": False,
                "eligibility_pairwise_sat": False,
                "eligibility_gurobi": False,
                "eligibility_cplex": False,
                "solver_executable": False,
                "timeout_feasibility_note": "File missing or invalid",
                "reason": "Raw Matrix Market file missing or failed inspection",
            })
            continue

        components, isolated, max_deg = _graph_topology(graph)
        init_lb = compute_lower_bound(graph)
        init_ub, _ = compute_initial_upper_bound(graph, symmetry_breaking=True)
        ord_seq = estimate_cnf_size(graph, encoding="order", amo="sequential", symmetry_breaking=True)
        ord_bin = estimate_cnf_size(graph, encoding="order", amo="binary", symmetry_breaking=True)
        pw_seq = estimate_cnf_size(graph, encoding="pairwise", amo="sequential", symmetry_breaking=True)
        ord_at_ub = estimate_cnf_size(
            graph,
            encoding="order",
            amo="sequential",
            k=max(0, init_ub - 1),
            symmetry_breaking=True,
        )

        sat_ok, sat_reason = sat_limits.check(ord_seq)
        pw_ok, _ = sat_limits.check(pw_seq)
        mip_vars = graph.order ** 2 + 1
        mip_constrs = 2 * graph.order + 2 * graph.size + 1

        gur_ok = bool(
            licenses["gurobi"]["available"]
            and (gurobi_cap_v is None or mip_vars <= gurobi_cap_v)
            and (gurobi_cap_c is None or mip_constrs <= gurobi_cap_c)
        )
        cpx_ok = bool(
            licenses["cplex"]["available"]
            and (cplex_cap_v is None or mip_vars <= cplex_cap_v)
            and (cplex_cap_c is None or mip_constrs <= cplex_cap_c)
        )

        reasons: list[str] = []
        if not sat_ok and sat_reason:
            reasons.append(f"SAT(order/seq): {sat_reason}")
        if not gur_ok:
            reasons.append(f"Gurobi: {mip_vars:,} vars exceeds cap {gurobi_cap_v}")
        if not cpx_ok:
            reasons.append(f"CPLEX: {mip_vars:,} vars exceeds CE cap {cplex_cap_v}")

        if not sat_ok:
            timeout_note = "Blocked before solving (SAT ResourceLimits)"
        elif graph.order <= 50:
            timeout_note = "30s feasible for proof/incumbent refinement"
        elif graph.order <= 165:
            timeout_note = "30s yields initial/improved SAT incumbent; proof unlikely in 30s"
        else:
            timeout_note = "High CNF size (<=500k vars); 30s likely TIMEOUT (UNPROVED)"

        records.append({
            "instance": meta.name,
            "table": meta.source_table,
            "n": graph.order,
            "m": graph.size,
            "file_checksum_status": sha_status,
            "graph_validation_status": mm_status,
            "dataset_ready": dataset_ready,
            "connected_components": components,
            "isolated_vertices": isolated,
            "max_degree": max_deg,
            "density": round(graph.density, 6),
            "initial_lb": init_lb,
            "initial_ub": init_ub,
            "pairwise_cnf_vars": pw_seq.num_variables,
            "pairwise_cnf_clauses": pw_seq.num_clauses,
            "pairwise_cnf_estimate": f"{pw_seq.num_variables:,}v / {pw_seq.num_clauses:,}c",
            "order_cnf_vars": ord_seq.num_variables,
            "order_cnf_clauses": ord_seq.num_clauses,
            "order_cnf_estimate": f"{ord_seq.num_variables:,}v / {ord_seq.num_clauses:,}c",
            "order_binary_cnf_vars": ord_bin.num_variables,
            "order_binary_cnf_clauses": ord_bin.num_clauses,
            "order_at_ub_clauses": ord_at_ub.num_clauses,
            "mip_vars": mip_vars,
            "mip_constrs": mip_constrs,
            "mip_estimate": f"{mip_vars:,}v / {mip_constrs:,}c",
            "eligibility_sat": sat_ok,
            "eligibility_pairwise_sat": pw_ok,
            "eligibility_gurobi": gur_ok,
            "eligibility_cplex": cpx_ok,
            "solver_executable": bool(sat_ok or gur_ok or cpx_ok),
            "timeout_feasibility_note": timeout_note,
            "reason": "; ".join(reasons) if reasons else "Eligible for SAT and licensed MIP",
        })

    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "preflight_54.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=PREFLIGHT_FIELDS)
        writer.writeheader()
        writer.writerows(records)
    (output_dir / "preflight_54.json").write_text(
        json.dumps(records, indent=2) + "\n", encoding="utf-8"
    )
    return records


def _row_identity(row: dict[str, Any]) -> tuple[str, ...]:
    base = list(row_base_identity(row))
    base.append(str(row.get("search_mode") or ""))
    return tuple(base)


def row_base_identity(row: dict[str, Any]) -> tuple[str, ...]:
    return (
        str(row.get("instance") or ""),
        str(row.get("solver") or ""),
        str(row.get("encoding") or ""),
        str(row.get("strategy") or ""),
        str(row.get("amo") or ""),
        "false"
        if row.get("symmetry_breaking") is False
        else ("true" if row.get("symmetry_breaking") is True else str(row.get("symmetry_breaking") or "").lower()),
        "" if row.get("timeout_s") in (None, "") else str(float(row["timeout_s"])),
        str(row.get("repetition") or ""),
    )


def _format_m2_3_csv_row(raw_row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for field in M2_3_FIELDS:
        val = raw_row.get(field)
        if val is None:
            out[field] = ""
        elif isinstance(val, (dict, list)):
            out[field] = json.dumps(val, separators=(",", ":"), sort_keys=True)
        else:
            out[field] = val
    return out


def _proof_comparison_tag(
    *,
    status: str,
    bandwidth: int | None,
    pub_best: int | None,
    dataset_status: str,
) -> str:
    if bandwidth is None or status in ("UNAVAILABLE", "SKIPPED", "RESOURCE_LIMIT", "ERROR"):
        return "N/A"
    if dataset_status == "SYNTHETIC_SAMPLE":
        if pub_best is not None and bandwidth == pub_best and status == "OPTIMAL":
            return "PROVED_ORACLE"
        return "PROVED" if status == "OPTIMAL" else "UNPROVED"
    if pub_best is None:
        return "PROVED" if status == "OPTIMAL" else "UNPROVED"
    if status == "OPTIMAL":
        if bandwidth == pub_best:
            return "PROVED_MATCHED_BEST"
        if bandwidth < pub_best:
            return "PROVED_IMPROVED_BEST"
        return "PROVED_ABOVE_BEST"
    if bandwidth == pub_best:
        return "UNPROVED_MATCHED_BEST"
    if bandwidth < pub_best:
        return "UNPROVED_BELOW_BEST"
    return "UNPROVED_ABOVE_BEST"


def _build_m2_3_plan(config: dict[str, Any], provenance_map: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    mode = str(config.get("mode", "m2_3_baseline"))
    timeout = float(config.get("timeout_seconds", 30.0))
    entries: list[dict[str, Any]] = []

    def push(
        *,
        scope: str,
        instances: list[str],
        solver: str,
        encoding: str | None,
        strategy: str | None,
        amo: str | None,
        symmetry: bool,
        timeout_s: float,
        experiment: str,
        threads: int = 1,
        repetitions: int = 1,
    ) -> None:
        search_mode = (
            "linear"
            if strategy == "repeated"
            else ("adaptive" if strategy == "incremental" else None)
        )
        for rep in range(1, repetitions + 1):
            for inst in instances:
                entries.append({
                    "scope": scope,
                    "instance": inst,
                    "solver": solver,
                    "encoding": encoding,
                    "strategy": strategy,
                    "search_mode": search_mode,
                    "amo": amo,
                    "symmetry_breaking": symmetry,
                    "timeout_s": timeout_s,
                    "experiments": experiment,
                    "threads": threads,
                    "repetition": rep,
                })

    if mode == "m2_3_baseline":
        ready_names = [
            m.name
            for m in sorted(
                (
                    meta
                    for meta in ALL_INSTANCES.values()
                    if provenance_map.get(meta.name, {}).get("validation_status") == "READY"
                ),
                key=lambda x: (x.source_table, x.n, x.name),
            )
        ]
        push(
            scope="hb",
            instances=ready_names,
            solver="cadical",
            encoding="order",
            strategy="incremental",
            amo="sequential",
            symmetry=True,
            timeout_s=timeout,
            experiment="Baseline_54",
            threads=1,
            repetitions=int(config.get("repetitions", 1)),
        )
        return entries

    # Controlled Comparative Studies A-G
    rep_instances = list(config["representative_instances"])
    pairwise_instances = list(config.get("pairwise_instances", rep_instances))
    study_t = float(config.get("study_timeout_seconds", timeout))
    sat_repeat_instances = list(config.get("repeat_instances", []))
    sat_reps = int(config.get("study_repetitions", 1))
    variance_reps = int(config.get("variance_repetitions", 3))

    # Study A: Main Encoding (Pairwise vs Order) holding CaDiCaL, sequential, incremental, sym=True fixed
    push(
        scope="hb", instances=rep_instances, solver="cadical",
        encoding="order", strategy="incremental", amo="sequential",
        symmetry=True, timeout_s=study_t, experiment="Study_A_encoding",
        repetitions=sat_reps,
    )
    push(
        scope="hb", instances=pairwise_instances, solver="cadical",
        encoding="pairwise", strategy="incremental", amo="sequential",
        symmetry=True, timeout_s=study_t, experiment="Study_A_encoding",
        repetitions=sat_reps,
    )

    # Study B: Cardinality Encoding (Pairwise, Sequential, Binary, Commander) holding Order, Glucose, Incremental, sym=True fixed
    for amo in ("sequential", "binary", "commander", "pairwise"):
        push(
            scope="hb", instances=rep_instances, solver="glucose",
            encoding="order", strategy="incremental", amo=amo,
            symmetry=True, timeout_s=study_t, experiment="Study_B_cardinality",
            repetitions=sat_reps,
        )

    # Study C: SAT Backend (CaDiCaL vs Glucose 4) holding Order, Sequential, Incremental, sym=True fixed
    for solver in ("cadical", "glucose"):
        push(
            scope="hb", instances=rep_instances, solver=solver,
            encoding="order", strategy="incremental", amo="sequential",
            symmetry=True, timeout_s=study_t, experiment="Study_C_backend",
            repetitions=sat_reps,
        )

    # Study D: SAT Strategy (Repeated vs Incremental) holding CaDiCaL, Order, Sequential, sym=True fixed
    for strategy in ("incremental", "repeated"):
        push(
            scope="hb", instances=rep_instances, solver="cadical",
            encoding="order", strategy=strategy, amo="sequential",
            symmetry=True, timeout_s=study_t, experiment="Study_D_strategy",
            repetitions=sat_reps,
        )

    # Study E: Symmetry Breaking (On vs Off) on configurations where both run (SAT on rep_instances; Gurobi on bcspwr01 + small)
    for sym in (True, False):
        push(
            scope="hb", instances=rep_instances, solver="cadical",
            encoding="order", strategy="incremental", amo="sequential",
            symmetry=sym, timeout_s=study_t, experiment="Study_E_symmetry",
            repetitions=1,
        )
        push(
            scope="hb", instances=["bcspwr01"], solver="gurobi",
            encoding=None, strategy=None, amo=None,
            symmetry=sym, timeout_s=study_t, experiment="Study_E_symmetry",
            threads=1, repetitions=1,
        )

    # Runtime stability / repetition checks on focus instances (Task M2.3.5)
    if sat_repeat_instances and variance_reps > 1:
        for solver in ("cadical", "glucose"):
            push(
                scope="hb", instances=sat_repeat_instances, solver=solver,
                encoding="order", strategy="incremental", amo="sequential",
                symmetry=True, timeout_s=study_t,
                experiment="Variance_Repeat;Study_C_backend",
                repetitions=variance_reps,
            )
        if "bcspwr01" in sat_repeat_instances:
            push(
                scope="hb", instances=["bcspwr01"], solver="gurobi",
                encoding=None, strategy=None, amo=None,
                symmetry=True, timeout_s=study_t,
                experiment="Variance_Repeat;Study_F_mip;Study_G_sat_vs_mip",
                threads=1, repetitions=variance_reps,
            )

    # Study F: MIP (Gurobi vs CPLEX) on SmallOracle + licensed-checked HB representatives
    small_names = [g.name for g, _ in _pilot_small_graphs()]
    small_reps = variance_reps if config.get("repeat_small_mip", True) else 1
    for solver in ("gurobi", "cplex"):
        for sym in (False, True):
            push(
                scope="small", instances=small_names, solver=solver,
                encoding=None, strategy=None, amo=None,
                symmetry=sym, timeout_s=study_t,
                experiment="Study_F_mip;Study_E_symmetry;Study_G_sat_vs_mip" if sym else "Study_F_mip;Study_E_symmetry",
                threads=1, repetitions=small_reps,
            )
        push(
            scope="hb", instances=rep_instances, solver=solver,
            encoding=None, strategy=None, amo=None,
            symmetry=True, timeout_s=study_t, experiment="Study_F_mip;Study_G_sat_vs_mip",
            threads=1, repetitions=1,
        )

    # SmallOracle SAT reference for Study G
    for solver in ("cadical", "glucose"):
        push(
            scope="small", instances=small_names, solver=solver,
            encoding="order", strategy="incremental", amo="sequential",
            symmetry=True, timeout_s=study_t, experiment="Study_G_sat_vs_mip",
            threads=1, repetitions=small_reps,
        )

    # Study G tag on HB SAT incremental CaDiCaL/Glucose runs
    for solver in ("cadical", "glucose"):
        push(
            scope="hb", instances=rep_instances, solver=solver,
            encoding="order", strategy="incremental", amo="sequential",
            symmetry=True, timeout_s=study_t, experiment="Study_G_sat_vs_mip",
            threads=1, repetitions=1,
        )

    return entries


def _merge_plan_tags(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse duplicate run configs within the same plan while merging experiment tags."""
    merged: dict[tuple[str, ...], dict[str, Any]] = {}
    order: list[tuple[str, ...]] = []
    for item in entries:
        key = row_base_identity({
            "instance": item["instance"],
            "solver": item["solver"],
            "encoding": item["encoding"],
            "strategy": item["strategy"],
            "amo": item["amo"],
            "symmetry_breaking": item["symmetry_breaking"],
            "timeout_s": item["timeout_s"],
            "repetition": item["repetition"],
        }) + (str(item.get("search_mode") or ""),)
        if key not in merged:
            merged[key] = dict(item)
            order.append(key)
        else:
            existing_tags = [t for t in str(merged[key]["experiments"]).split(";") if t]
            for tag in str(item["experiments"]).split(";"):
                if tag and tag not in existing_tags:
                    existing_tags.append(tag)
            merged[key]["experiments"] = ";".join(existing_tags)
    return [merged[k] for k in order]


def _execute_m2_3_item(
    *,
    run_id: str,
    item: dict[str, Any],
    table: str,
    dataset_source: str,
    dataset_checksum: str | None,
    dataset_status: str,
    graph: Graph | None,
    matrix_path: Path | None,
    load_err: str | None,
    pub_lb: int | None,
    pub_best: int | None,
    expected_n: int,
    max_sat_vars: int | None,
    max_sat_clauses: int | None,
    max_mip_vars: int,
    memory_limit_mb: float | None,
    use_fork: bool,
    output_dir: Path,
    git_sha: str,
    solver_versions: dict[str, str],
    licenses: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    solver = str(item["solver"])
    encoding = item["encoding"]
    strategy = item["strategy"]
    amo = item["amo"]
    symmetry = bool(item["symmetry_breaking"])
    timeout = float(item["timeout_s"])
    threads = int(item.get("threads") or 1)
    threshold_policy = "adaptive" if solver in ("glucose", "cadical") else None

    comp_cnt, _, max_deg = _graph_topology(graph) if graph is not None else (None, None, None)

    row: dict[str, Any] = {field: None for field in M2_3_FIELDS}
    row.update(
        run_id=run_id,
        timestamp=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        git_commit=git_sha,
        experiment=item["experiments"],
        instance=item["instance"],
        table=table,
        dataset_source=dataset_source,
        dataset_checksum=dataset_checksum,
        dataset_status=dataset_status,
        n=expected_n,
        m=graph.size if graph is not None else None,
        method="SAT" if solver in ("glucose", "cadical") else "MIP",
        encoding=encoding,
        amo=amo,
        solver=solver,
        solver_version=solver_versions[solver],
        strategy=strategy,
        search_mode=item["search_mode"],
        symmetry_breaking=symmetry,
        repetition=int(item["repetition"]),
        timeout_s=timeout,
        published_lb=pub_lb,
        published_best=pub_best,
        threads=threads,
        threshold_policy=threshold_policy,
        topology_components=comp_cnt,
        topology_max_degree=max_deg,
    )

    started = monotonic()
    sat_limits = ResourceLimits(
        max_variables=int(max_sat_vars) if max_sat_vars is not None else None,
        max_clauses=int(max_sat_clauses) if max_sat_clauses is not None else None,
        timeout_seconds=timeout,
        memory_limit_mb=float(memory_limit_mb) if memory_limit_mb is not None else None,
    )

    if dataset_status not in ("READY", "SYNTHETIC_SAMPLE"):
        row["status"] = SolutionStatus.SKIPPED.value
        row["proof_status"] = "N/A"
        row["error"] = load_err
    elif graph is None:
        row["status"] = SolutionStatus.UNAVAILABLE.value
        row["proof_status"] = "N/A"
        row["error"] = load_err
    elif solver in ("glucose", "cadical"):
        assert encoding is not None and strategy is not None and amo is not None
        est = estimate_cnf_size(
            graph, encoding=encoding, amo=amo, k=None, symmetry_breaking=symmetry
        )
        is_ok, cap_reason = sat_limits.check(est)
        if not is_ok:
            row.update({
                "status": "RESOURCE_LIMIT",
                "proof_status": "N/A",
                "cnf_variables": est.num_variables,
                "cnf_original_vars": est.num_original_vars,
                "cnf_channeling_vars": est.num_channeling_vars,
                "cnf_aux_vars": est.num_aux_vars,
                "cnf_clauses": est.num_clauses,
                "error": cap_reason,
            })
        elif use_fork:
            res = _run_sat_direct(
                graph, solver, encoding, strategy, amo, symmetry, sat_limits, est, solver_versions[solver]
            )
            # Treat resident-memory kill explicitly as RESOURCE_LIMIT
            if res.get("status") == SolutionStatus.SKIPPED.value and "exceeded limit" in str(res.get("error") or "").lower():
                res["status"] = "RESOURCE_LIMIT"
            row.update(res)
        else:
            raise RuntimeError("Windows non-fork subprocess mode should use worker() directly")
    else:
        mip_vars = graph.order ** 2 + 1
        mip_constrs = 2 * graph.order + 2 * graph.size + (1 if symmetry and graph.order >= 2 else 0)
        row["mip_vars"] = mip_vars
        row["mip_constrs"] = mip_constrs
        lic = licenses[solver]
        lic_cap_v = lic.get("max_variables")
        lic_cap_c = lic.get("max_constraints")

        if not lic["available"]:
            row.update({
                "status": SolutionStatus.UNAVAILABLE.value,
                "proof_status": "N/A",
                "license_status": lic["license_type"],
                "error": lic["note"],
            })
        elif (lic_cap_v is not None and mip_vars > lic_cap_v) or (
            lic_cap_c is not None and mip_constrs > lic_cap_c
        ):
            row.update({
                "status": SolutionStatus.UNAVAILABLE.value,
                "proof_status": "N/A",
                "license_status": "BLOCKED_LICENSE",
                "error": (
                    f"{solver.upper()} license-aware preflight blocked: model needs "
                    f"{mip_vars:,} vars / {mip_constrs:,} constrs (> cap {lic_cap_v}/{lic_cap_c} "
                    f"for {lic['license_type']})"
                ),
            })
        elif mip_vars > max_mip_vars:
            row.update({
                "status": "RESOURCE_LIMIT",
                "proof_status": "N/A",
                "license_status": lic["license_type"],
                "error": f"MIP variables {mip_vars:,} exceed safety cap {max_mip_vars:,}",
            })
        else:
            res = _run_mip_direct(
                graph, solver, symmetry, timeout, solver_versions[solver], threads=threads
            )
            res["license_status"] = "BLOCKED_LICENSE" if res.get("status") == SolutionStatus.UNAVAILABLE.value else lic["license_type"]
            row.update(res)

    if solver in ("glucose", "cadical"):
        row["license_status"] = "OPEN_SOURCE_PYSAT"

    perm = row.get("permutation")
    if perm is not None and graph is not None:
        perm_int = {int(v): int(p) for v, p in perm.items()}
        rep = validate_solution(graph, perm_int, claimed_bandwidth=row.get("bandwidth"))
        row["validation"] = rep.valid
        row["bandwidth"] = rep.actual_bandwidth
        row["permutation"] = perm_int
        if not rep.valid:
            row["status"] = SolutionStatus.ERROR.value
            row["error"] = "; ".join(rep.errors)

    row["total_wall_time_s"] = round(monotonic() - started, 6)
    row["proof_comparison_tag"] = _proof_comparison_tag(
        status=str(row["status"]),
        bandwidth=row.get("bandwidth"),
        pub_best=pub_best,
        dataset_status=dataset_status,
    )
    return row


def summarize_m2_3(
    output_dir: Path,
    rows: list[dict[str, Any]],
    preflight_records: list[dict[str, Any]] | None = None,
) -> None:
    """Write summary.json, baseline_summary.json, and comparison.md for M2.3."""
    def status_breakdown(sub: list[dict[str, Any]]) -> dict[str, int]:
        return {
            st: sum(str(r.get("status")) == st for r in sub)
            for st in ("OPTIMAL", "FEASIBLE", "TIMEOUT", "RESOURCE_LIMIT", "SKIPPED", "UNAVAILABLE", "ERROR")
        }

    baseline_rows = [r for r in rows if "Baseline_54" in str(r.get("experiment", "")).split(";")]
    baseline_exec = [r for r in baseline_rows if r.get("status") not in ("RESOURCE_LIMIT", "SKIPPED")]
    baseline_wall_total = round(sum(float(r.get("total_wall_time_s") or 0.0) for r in baseline_rows), 3)

    baseline_payload = {
        "total_ready_in_catalog": 54,
        "preflighted_count": len(preflight_records) if preflight_records is not None else len(baseline_rows),
        "baseline_records_count": len(baseline_rows),
        "actually_solved_attempted_count": len(baseline_exec),
        "status_counts": status_breakdown(baseline_rows),
        "total_wall_time_s": baseline_wall_total,
        "by_table": {
            tbl: status_breakdown([r for r in baseline_rows if r.get("table") == tbl])
            for tbl in ("Table 6", "Table 7", "Table 8")
        },
        "solved_optimal_instances": [
            {
                "instance": r["instance"],
                "table": r["table"],
                "n": r["n"],
                "m": r["m"],
                "bandwidth": r["bandwidth"],
                "published_best": r["published_best"],
                "wall_time_s": r["total_wall_time_s"],
                "proof_comparison_tag": r.get("proof_comparison_tag"),
            }
            for r in baseline_rows
            if r.get("status") == "OPTIMAL"
        ],
        "matched_best_unproved_instances": [
            r["instance"]
            for r in baseline_rows
            if r.get("proof_comparison_tag") in ("UNPROVED_MATCHED_BEST", "UNPROVED_BELOW_BEST")
        ],
    }
    (output_dir / "baseline_summary.json").write_text(
        json.dumps(baseline_payload, indent=2) + "\n", encoding="utf-8"
    )

    hb_rows = [r for r in rows if r.get("dataset_status") == "READY"]
    small_rows = [r for r in rows if r.get("dataset_status") == "SYNTHETIC_SAMPLE"]
    by_name: dict[str, dict[str, Any]] = {}
    for row in hb_rows:
        valid = row.get("validation") in (True, "True")
        bw_val = row.get("bandwidth")
        st = str(row.get("status") or "")
        if not valid or bw_val in (None, "") or st in ("UNAVAILABLE", "SKIPPED", "RESOURCE_LIMIT", "ERROR"):
            continue
        name = str(row["instance"])
        bw_int = int(bw_val)
        wall = float(row.get("total_wall_time_s") or 0.0)
        key = (bw_int, st != "OPTIMAL", wall)
        if name not in by_name or key < (
            int(by_name[name]["bandwidth"]),
            str(by_name[name]["status"]) != "OPTIMAL",
            float(by_name[name].get("total_wall_time_s") or 0.0),
        ):
            by_name[name] = row

    counts = {"equal_proved": 0, "equal_unproved": 0, "better": 0, "worse": 0, "not_solved": 0}
    comp_lines = [
        "# Member 2 Phase M2.3 – Benchmark Comparison Across 54 READY Instances",
        "",
        "| Instance | Table | n | m | Paper LB | Paper Best | Best BW | Status (Proof) | Comparison Tag | Solver / Config | Wall (s) |",
        "|---|---|---:|---:|---:|---:|---:|---|---|---|---:|",
    ]
    ready_metas = [
        m for m in ALL_INSTANCES.values()
        if any(r["instance"] == m.name for r in baseline_rows)
    ]
    if not ready_metas and preflight_records:
        ready_metas = [ALL_INSTANCES[r["instance"]] for r in preflight_records]
    for meta in sorted(ready_metas, key=lambda x: (x.source_table, x.n, x.name)):
        best = by_name.get(meta.name)
        base = next((r for r in baseline_rows if r["instance"] == meta.name), None)
        n_edges = (best or base or {}).get("m") or "—"
        if best is None:
            counts["not_solved"] += 1
            reason = str((base or {}).get("status") or "NOT_RUN")
            comp_lines.append(
                f"| `{meta.name}` | {meta.source_table} | {meta.n} | {n_edges} | {meta.paper_lb} | {meta.paper_best} | — | {reason} | N/A | — | — |"
            )
            continue
        bw = int(best["bandwidth"])
        st = str(best["status"])
        if bw < meta.paper_best:
            counts["better"] += 1
        elif bw == meta.paper_best:
            if st == "OPTIMAL":
                counts["equal_proved"] += 1
            else:
                counts["equal_unproved"] += 1
        else:
            counts["worse"] += 1
        cfg = f"{best['solver']} ({best['encoding'] or 'MIP'}/{best['amo'] or '-'})"
        comp_lines.append(
            f"| `{meta.name}` | {meta.source_table} | {meta.n} | {n_edges} | {meta.paper_lb} | {meta.paper_best} | {bw} | {st} ({best.get('proof_status')}) | {best.get('proof_comparison_tag')} | {cfg} | {float(best['total_wall_time_s']):.3f} |"
        )

    summary_payload = {
        "total_runs": len(rows),
        "small_oracle_runs": len(small_rows),
        "hb_ready_runs": len(hb_rows),
        "overall_status_counts": status_breakdown(rows),
        "hb_status_counts": status_breakdown(hb_rows),
        "small_oracle_status_counts": status_breakdown(small_rows),
        "hb_paper_relation_counts": counts,
        "baseline_summary": baseline_payload,
    }
    (output_dir / "summary.json").write_text(json.dumps(summary_payload, indent=2) + "\n", encoding="utf-8")
    (output_dir / "comparison.md").write_text("\n".join(comp_lines) + "\n", encoding="utf-8")


def run_m2_3(
    config_path: Path,
    *,
    selected: set[str] | None = None,
    resume: bool = True,
    preflight_only: bool = False,
) -> None:
    """Execute Phase M2.3 preflight, baseline, or controlled study configuration."""
    config_path = config_path.resolve()
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))["benchmark"]
    mode = str(config.get("mode", "m2_3_baseline"))
    root = config_path.parent
    provenance_path = (root / config.get("provenance", "../data/benchmark_provenance.json")).resolve()
    raw_dir = (root / config.get("raw_dir", "../data/benchmarks/raw")).resolve()
    output_dir = (root / config["output_dir"]).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    max_sat_vars = int(config.get("max_sat_variables", 500_000))
    max_sat_clauses = int(config.get("max_sat_clauses", 2_500_000))
    max_mip_vars = int(config.get("max_mip_variables", 250_000))
    memory_limit_mb = config.get("memory_limit_mb")
    max_batch_seconds = float(config.get("max_batch_seconds", 900.0) or 0.0)

    licenses = detect_commercial_licenses()
    preflight_json_path = output_dir / "preflight_54.json"
    if resume and not preflight_only and preflight_json_path.exists():
        preflight_records = json.loads(preflight_json_path.read_text(encoding="utf-8"))
    else:
        preflight_records = export_preflight_54(
            provenance_path=provenance_path,
            raw_dir=raw_dir,
            output_dir=output_dir,
            max_sat_vars=max_sat_vars,
            max_sat_clauses=max_sat_clauses,
            licenses=licenses,
        )
    if preflight_only:
        return

    if not resume:
        (output_dir / "run_log.txt").unlink(missing_ok=True)

    provenance_map = {
        entry["instance"]: entry
        for entry in json.loads(provenance_path.read_text(encoding="utf-8"))
    }
    output_csv = output_dir / "runs.csv"
    output_json = output_dir / "runs.json"

    existing_json: list[dict[str, Any]] = []
    if resume and output_json.exists():
        existing_json = json.loads(output_json.read_text(encoding="utf-8"))
    all_rows_json: list[dict[str, Any]] = list(existing_json) if resume else []
    by_key: dict[tuple[str, ...], dict[str, Any]] = {_row_identity(r): r for r in all_rows_json}

    plan_items = _merge_plan_tags(_build_m2_3_plan(config, provenance_map))

    # Merge any newly requested experiment tags into already-completed rows cleanly
    tags_updated = False
    for item in plan_items:
        probe_key = row_base_identity({
            "instance": item["instance"],
            "solver": item["solver"],
            "encoding": item["encoding"],
            "strategy": item["strategy"],
            "amo": item["amo"],
            "symmetry_breaking": item["symmetry_breaking"],
            "timeout_s": item["timeout_s"],
            "repetition": item["repetition"],
        }) + (str(item.get("search_mode") or ""),)
        if probe_key in by_key:
            cur_tags = [t for t in str(by_key[probe_key].get("experiment") or "").split(";") if t]
            for tag in str(item["experiments"]).split(";"):
                if tag and tag not in cur_tags:
                    cur_tags.append(tag)
                    tags_updated = True
            by_key[probe_key]["experiment"] = ";".join(cur_tags)

    small_map = {g.name: (g, obw) for g, obw in _pilot_small_graphs()}
    hb_cache: dict[str, tuple[str, Any | None, Path | None, str | None, str | None]] = {}
    git_sha = _git_commit()
    use_fork = _supports_fork()
    solver_versions = {
        "cadical": _sat_backend_version("cadical"),
        "glucose": _sat_backend_version("glucose"),
        "gurobi": licenses["gurobi"]["version"] if licenses["gurobi"]["available"] else _mip_backend_version("gurobi"),
        "cplex": licenses["cplex"]["version"] if licenses["cplex"]["available"] else _mip_backend_version("cplex"),
    }

    batch_started = monotonic()
    log_lines: list[str] = []
    run_counter = len(all_rows_json)

    # Always write full synchronized CSV header + existing rows so updated tags persist
    with output_csv.open("w", newline="", encoding="utf-8") as csv_stream:
        writer = csv.DictWriter(csv_stream, fieldnames=M2_3_FIELDS)
        writer.writeheader()
        for existing_row in all_rows_json:
            writer.writerow(_format_m2_3_csv_row(existing_row))
        csv_stream.flush()

        for item in plan_items:
            name = item["instance"]
            if selected and name not in selected:
                continue
            probe_key = row_base_identity({
                "instance": name,
                "solver": item["solver"],
                "encoding": item["encoding"],
                "strategy": item["strategy"],
                "amo": item["amo"],
                "symmetry_breaking": item["symmetry_breaking"],
                "timeout_s": item["timeout_s"],
                "repetition": item["repetition"],
            }) + (str(item.get("search_mode") or ""),)
            if probe_key in by_key:
                continue

            if max_batch_seconds > 0 and (monotonic() - batch_started) >= max_batch_seconds:
                msg = f"BATCH_BUDGET_STOP after {monotonic() - batch_started:.1f}s before {name} {item['solver']}"
                log_lines.append(msg)
                print(msg, flush=True)
                break

            if item["scope"] == "small":
                g, obw = small_map[name]
                table = "Synthetic/Sample"
                dataset_src = f"bmp.core.generators:{name}"
                checksum = None
                dst_status = "SYNTHETIC_SAMPLE"
                graph, mpath, load_err = g, None, None
                pub_lb, pub_best, expected_n = None, obw, g.order
            else:
                meta: BenchmarkInstanceMeta = ALL_INSTANCES[name]
                if name not in hb_cache:
                    hb_cache[name] = _load_provenance_and_audit(meta, provenance_map, raw_dir)
                dst_status, graph, mpath, checksum, load_err = hb_cache[name]
                table = meta.source_table
                dataset_src = str(provenance_map.get(name, {}).get("source_url", "NIST MatrixMarket Harwell-Boeing"))
                pub_lb, pub_best, expected_n = meta.paper_lb, meta.paper_best, meta.n

            run_counter += 1
            run_id = f"m2_3_{run_counter:04d}"
            row = _execute_m2_3_item(
                run_id=run_id,
                item=item,
                table=table,
                dataset_source=dataset_src,
                dataset_checksum=checksum,
                dataset_status=dst_status,
                graph=graph,
                matrix_path=mpath,
                load_err=load_err,
                pub_lb=pub_lb,
                pub_best=pub_best,
                expected_n=expected_n,
                max_sat_vars=max_sat_vars,
                max_sat_clauses=max_sat_clauses,
                max_mip_vars=max_mip_vars,
                memory_limit_mb=float(memory_limit_mb) if memory_limit_mb is not None else None,
                use_fork=use_fork,
                output_dir=output_dir,
                git_sha=git_sha,
                solver_versions=solver_versions,
                licenses=licenses,
            )
            all_rows_json.append(row)
            by_key[probe_key] = row
            writer.writerow(_format_m2_3_csv_row(row))
            csv_stream.flush()
            os.fsync(csv_stream.fileno())

            line = (
                f"{run_id} [{row['experiment']}] {name} ({row['table']}, n={row['n']}) "
                f"{row['solver']} {row['encoding'] or '-'} {row['amo'] or '-'} {row['strategy'] or '-'} "
                f"sym={row['symmetry_breaking']} rep={row['repetition']} t={row['timeout_s']}s -> "
                f"{row['status']} ({row['proof_status']}) bw={row['bandwidth']} lb={row['lower_bound']} "
                f"tag={row['proof_comparison_tag']} wall={row['total_wall_time_s']:.3f}s"
            )
            if row["error"]:
                line += f" | note={row['error']}"
            log_lines.append(line)
            print(line, flush=True)

    if not resume or tags_updated or log_lines or not output_json.exists():
        output_json.write_text(json.dumps(all_rows_json, indent=2) + "\n", encoding="utf-8")

    metadata = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "git_commit": git_sha,
        "config": str(config_path),
        "mode": mode,
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "solver_versions": solver_versions,
        "licenses": licenses,
        "resource_limits": {
            "max_sat_variables": max_sat_vars,
            "max_sat_clauses": max_sat_clauses,
            "max_mip_variables": max_mip_vars,
            "memory_limit_mb": memory_limit_mb,
            "max_batch_seconds": max_batch_seconds,
        },
        "last_invocation_wall_s": round(monotonic() - batch_started, 3),
    }
    (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    if log_lines:
        with (output_dir / "run_log.txt").open("a", encoding="utf-8") as lf:
            lf.write("\n".join(log_lines) + "\n")

    summarize_m2_3(output_dir, all_rows_json, preflight_records)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--instance", action="append")
    parser.add_argument("--rerun", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    run_m2_3(
        args.config,
        selected=set(args.instance) if args.instance else None,
        resume=not args.rerun,
        preflight_only=args.preflight_only,
    )


if __name__ == "__main__":
    main()
