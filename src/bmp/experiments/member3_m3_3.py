"""Phase M3.3 CP-SAT & IBM CP Optimizer preflight, controlled pilot benchmark, and figures."""

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

from bmp.core.benchmark_catalog import ALL_INSTANCES
from bmp.core.bounds import identity_upper_bound
from bmp.core.graph import Graph
from bmp.core.solution import SolutionStatus
from bmp.core.validation import validate_solution
from bmp.experiments.member2_hb import _git_commit, _self_rss_mb
from bmp.io.readers import inspect_matrix_market
from bmp.solvers.exact.cp_optimizer import CPOptimizerSolver, _resolve_executable
from bmp.solvers.exact.cpsat import CPSATSolver
from bmp.solvers.sat.search import compute_initial_upper_bound, compute_lower_bound

PREFLIGHT_FIELDS: tuple[str, ...] = (
    "instance",
    "table",
    "dataset_status",
    "sha256_verified",
    "n",
    "m",
    "initial_lb",
    "initial_ub",
    "cp_model_vars",
    "cpsat_model_constrs",
    "cpo_model_constrs",
    "eligibility",
    "selected_for_pilot",
    "reason",
)

M3_3_FIELDS: tuple[str, ...] = (
    "run_id",
    "timestamp",
    "git_commit",
    "experiment",
    "instance",
    "table",
    "dataset_source",
    "dataset_checksum",
    "dataset_status",
    "n",
    "m",
    "method",
    "solver",
    "solver_version",
    "engine_availability",
    "threads",
    "seed",
    "symmetry_breaking",
    "use_lower_bound",
    "use_initial_upper_bound",
    "hint_type",
    "time_limit_s",
    "total_wall_time_s",
    "model_construction_time_s",
    "engine_init_time_s",
    "solver_time_s",
    "bandwidth",
    "best_bound",
    "optimality_gap",
    "solver_status",
    "proof_status",
    "validation",
    "initial_lb",
    "initial_ub",
    "final_ub",
    "peak_memory_mb",
    "published_lb",
    "published_best",
    "anchor_vertex",
    "model_variables",
    "model_constraints",
    "num_branches",
    "note",
)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _detect_cp_environment() -> dict[str, Any]:
    env: dict[str, Any] = {
        "os": platform.platform(),
        "machine": platform.machine(),
        "python_version": platform.python_version(),
    }
    try:
        import ortools

        env["ortools_available"] = True
        env["ortools_version"] = getattr(ortools, "__version__", "unknown")
    except ImportError as exc:
        env["ortools_available"] = False
        env["ortools_version"] = None
        env["ortools_error"] = str(exc)

    try:
        import docplex

        env["docplex_available"] = True
        env["docplex_version"] = getattr(docplex, "__version__", "unknown")
    except ImportError as exc:
        env["docplex_available"] = False
        env["docplex_version"] = None
        env["docplex_error"] = str(exc)

    exe_name = os.environ.get("BMP_CPO_EXECUTABLE", "cpoptimizer")
    resolved = _resolve_executable(exe_name)
    env["cpo_executable_name"] = exe_name
    env["cpo_executable_path"] = resolved
    env["cpo_engine_available"] = bool(env["docplex_available"] and resolved is not None)
    return env


def _locate_raw_file(
    name: str,
    raw_dir: Path,
    fallback_raw_dir: Path | None,
) -> Path | None:
    for d in (raw_dir, fallback_raw_dir):
        if d is None:
            continue
        p = d / f"{name}.mtx.gz"
        if p.is_file():
            return p
    return None


def _run_preflight(
    provenance_entries: list[dict[str, Any]],
    *,
    raw_dir: Path,
    fallback_raw_dir: Path | None,
    pilot_set: set[str],
    max_cp_vars: int,
    max_cp_constrs: int,
) -> tuple[list[dict[str, Any]], dict[str, tuple[Graph, dict[str, Any], Path]]]:
    """Audit all 54 READY instances with CP-specific variable/constraint estimates."""
    preflight_rows: list[dict[str, Any]] = []
    loaded_pilot: dict[str, tuple[Graph, dict[str, Any], Path]] = {}

    for entry in sorted(
        (e for e in provenance_entries if e["validation_status"] == "READY"),
        key=lambda e: (e["n"], e["m"], e["instance"]),
    ):
        name = entry["instance"]
        meta = ALL_INSTANCES[name]
        raw_path = _locate_raw_file(name, raw_dir, fallback_raw_dir)
        if raw_path is None:
            preflight_rows.append({
                "instance": name,
                "table": meta.source_table,
                "dataset_status": entry["validation_status"],
                "sha256_verified": False,
                "n": entry["n"],
                "m": entry["m"],
                "initial_lb": None,
                "initial_ub": None,
                "cp_model_vars": entry["n"] + 1,
                "cpsat_model_constrs": 2 * entry["m"] + 2,
                "cpo_model_constrs": entry["m"] + 2,
                "eligibility": "MISSING_RAW_FILE",
                "selected_for_pilot": name in pilot_set,
                "reason": "Raw gzip file not found in configured directories",
            })
            continue

        actual_sha = _sha256(raw_path)
        sha_ok = actual_sha == entry["sha256"]
        audit = inspect_matrix_market(raw_path)
        if not sha_ok or audit.status != "READY" or audit.rows != meta.n or audit.graph.size != entry["m"]:
            preflight_rows.append({
                "instance": name,
                "table": meta.source_table,
                "dataset_status": entry["validation_status"],
                "sha256_verified": sha_ok,
                "n": audit.rows,
                "m": audit.graph.size,
                "initial_lb": None,
                "initial_ub": None,
                "cp_model_vars": audit.rows + 1,
                "cpsat_model_constrs": 2 * audit.graph.size + 2,
                "cpo_model_constrs": audit.graph.size + 2,
                "eligibility": "INVALID_OR_MISMATCH",
                "selected_for_pilot": False,
                "reason": f"sha_ok={sha_ok}, audit_status={audit.status}",
            })
            continue

        graph = Graph.from_edges(
            range(1, audit.rows + 1),
            ((u + 1, v + 1) for u, v in audit.graph.edges),
            name=name,
            metadata={"source": str(raw_path), "sha256": actual_sha, "table": meta.source_table},
        )
        cp_vars = graph.order + 1
        cpsat_constrs = 2 * graph.size + (2 if graph.order >= 2 else 0)
        cpo_constrs = graph.size + (2 if graph.order >= 2 else 0)

        init_lb = compute_lower_bound(graph) if name in pilot_set or graph.order <= 250 else None
        init_ub = (
            compute_initial_upper_bound(graph, symmetry_breaking=True)[0]
            if name in pilot_set or graph.order <= 250
            else None
        )

        if cp_vars > max_cp_vars or cpsat_constrs > max_cp_constrs:
            eligibility = "EXCEEDS_PILOT_BUDGET"
            reason = f"vars={cp_vars} or constrs={cpsat_constrs} exceeds pilot guard ({max_cp_vars}/{max_cp_constrs})"
        elif graph.order > 250:
            eligibility = "HEAVY_FOR_20S"
            reason = "n>250 AllDifferent domain propagation typically needs extended >30s budget"
        else:
            eligibility = "PILOT_READY"
            reason = "Verified READY and within 20s CP pilot resource guard"

        preflight_rows.append({
            "instance": name,
            "table": meta.source_table,
            "dataset_status": entry["validation_status"],
            "sha256_verified": True,
            "n": graph.order,
            "m": graph.size,
            "initial_lb": init_lb,
            "initial_ub": init_ub,
            "cp_model_vars": cp_vars,
            "cpsat_model_constrs": cpsat_constrs,
            "cpo_model_constrs": cpo_constrs,
            "eligibility": eligibility,
            "selected_for_pilot": name in pilot_set,
            "reason": reason,
        })
        if name in pilot_set:
            loaded_pilot[name] = (graph, entry, raw_path)

    return preflight_rows, loaded_pilot


def _build_plan(config: dict[str, Any]) -> list[dict[str, Any]]:
    timeout_s = float(config["timeout_seconds"])
    threads = int(config.get("threads", 1))
    seed = int(config.get("seed", 17))
    pilot_instances = list(config["pilot_instances"])
    ablation_instances = list(config.get("ablation_instances", pilot_instances[:3]))

    ordered: dict[tuple[Any, ...], dict[str, Any]] = {}

    def add_item(
        *,
        experiment: str,
        instance: str,
        solver: str,
        symmetry: bool,
        use_lb: bool = True,
        use_ub: bool = True,
        hint_type: str = "rcm",
    ) -> None:
        key = (instance, solver, symmetry, use_lb, use_ub, hint_type, threads, seed, timeout_s)
        if key in ordered:
            exps = ordered[key]["experiments"]
            if experiment not in exps:
                exps.append(experiment)
            return
        ordered[key] = {
            "experiments": [experiment],
            "instance": instance,
            "solver": solver,
            "symmetry_breaking": symmetry,
            "use_lower_bound": use_lb,
            "use_initial_upper_bound": use_ub,
            "hint_type": hint_type,
            "threads": threads,
            "seed": seed,
            "time_limit_s": timeout_s,
        }

    # Experiment A & C: CP-SAT symmetry on/off across all pilot instances
    for inst in pilot_instances:
        for sym in (True, False):
            exp = "Experiment_A_cpsat;Experiment_C_cp_vs_cp;Experiment_D_cp_vs_sat_mip" if sym else "Experiment_A_cpsat"
            add_item(experiment=exp, instance=inst, solver="cp-sat", symmetry=sym)

    # Experiment A ablations: no initial UB/hint, no LB, identity hint
    for inst in ablation_instances:
        add_item(
            experiment="Experiment_A_cpsat_ablation",
            instance=inst,
            solver="cp-sat",
            symmetry=True,
            use_lb=True,
            use_ub=False,
            hint_type="none",
        )
        add_item(
            experiment="Experiment_A_cpsat_ablation",
            instance=inst,
            solver="cp-sat",
            symmetry=True,
            use_lb=False,
            use_ub=True,
            hint_type="rcm",
        )
        add_item(
            experiment="Experiment_A_cpsat_ablation",
            instance=inst,
            solver="cp-sat",
            symmetry=True,
            use_lb=True,
            use_ub=True,
            hint_type="identity",
        )

    # Experiment B & C: IBM CP Optimizer symmetry on/off across all pilot instances
    for inst in pilot_instances:
        for sym in (True, False):
            exp = "Experiment_B_cpo;Experiment_C_cp_vs_cp;Experiment_D_cp_vs_sat_mip" if sym else "Experiment_B_cpo"
            add_item(experiment=exp, instance=inst, solver="cp-optimizer", symmetry=sym)

    # Experiment B ablation: no starting point / no initial UB
    for inst in ablation_instances:
        add_item(
            experiment="Experiment_B_cpo_ablation",
            instance=inst,
            solver="cp-optimizer",
            symmetry=True,
            use_lb=True,
            use_ub=False,
            hint_type="none",
        )

    out: list[dict[str, Any]] = []
    for idx, item in enumerate(ordered.values(), start=1):
        item["run_id"] = f"m33-{idx:03d}"
        item["experiment"] = ";".join(item.pop("experiments"))
        out.append(item)
    return out


def _format_csv_row(row: dict[str, Any], fieldnames: tuple[str, ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for field in fieldnames:
        val = row.get(field)
        out[field] = "" if val is None else val
    return out


def _execute_item(
    item: dict[str, Any],
    *,
    graph: Graph,
    prov: dict[str, Any],
    raw_path: Path,
    env_info: dict[str, Any],
    git_sha: str,
) -> dict[str, Any]:
    meta = ALL_INSTANCES[graph.name]
    solver_name = item["solver"]
    sym = bool(item["symmetry_breaking"])
    use_lb = bool(item["use_lower_bound"])
    use_ub = bool(item["use_initial_upper_bound"])
    hint_type = item["hint_type"]
    threads = int(item["threads"])
    seed = int(item["seed"])
    timeout_s = float(item["time_limit_s"])

    init_perm = None
    if hint_type == "identity":
        _, init_perm = identity_upper_bound(graph)

    init_lb = compute_lower_bound(graph)
    init_ub, _ = compute_initial_upper_bound(
        graph, heuristic_permutation=init_perm, symmetry_breaking=sym
    )

    if solver_name == "cp-sat":
        solver = CPSATSolver(seed=seed)
        avail = bool(env_info["ortools_available"])
    else:
        exe = env_info["cpo_executable_path"] or env_info["cpo_executable_name"]
        solver = CPOptimizerSolver(executable=str(exe), seed=seed)
        avail = bool(env_info["cpo_engine_available"])

    res = solver.solve(
        graph,
        timeout_seconds=timeout_s,
        symmetry_breaking=sym,
        threads=threads,
        seed=seed,
        initial_permutation=init_perm,
        use_lower_bound=use_lb,
        use_initial_upper_bound=use_ub,
    )

    report = (
        validate_solution(graph, res.permutation, claimed_bandwidth=res.bandwidth)
        if res.permutation is not None
        else None
    )
    if report is not None and not report.valid:
        status_str = SolutionStatus.ERROR.value
        proof_status = "VALIDATION_FAILED"
        bw: int | None = None
    else:
        status_str = res.status.value
        bw = report.actual_bandwidth if report is not None else None
        if res.status is SolutionStatus.OPTIMAL:
            proof_status = "PROVED_OPTIMAL"
        elif res.status is SolutionStatus.FEASIBLE:
            proof_status = "FEASIBLE_UNPROVED"
        elif res.status is SolutionStatus.TIMEOUT:
            proof_status = "TIMEOUT_NO_SOLUTION"
        elif res.status is SolutionStatus.UNAVAILABLE:
            proof_status = "ENGINE_UNAVAILABLE"
        else:
            proof_status = status_str

    best_bound = res.lower_bound
    gap: int | None = None
    if bw is not None and best_bound is not None:
        gap = bw - best_bound

    peak_mem = res.metadata.get("engine_peak_memory_mb") or _self_rss_mb()

    row: dict[str, Any] = {field: None for field in M3_3_FIELDS}
    row.update(
        run_id=item["run_id"],
        timestamp=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        git_commit=git_sha,
        experiment=item["experiment"],
        instance=graph.name,
        table=meta.source_table,
        dataset_source=str(raw_path),
        dataset_checksum=prov["sha256"],
        dataset_status=prov["validation_status"],
        n=graph.order,
        m=graph.size,
        method="CP",
        solver=solver_name,
        solver_version=res.metadata.get("solver_version"),
        engine_availability="AVAILABLE" if avail else "UNAVAILABLE",
        threads=threads,
        seed=seed,
        symmetry_breaking=sym,
        use_lower_bound=use_lb,
        use_initial_upper_bound=use_ub,
        hint_type=hint_type,
        time_limit_s=timeout_s,
        total_wall_time_s=round(res.runtime_s, 6),
        model_construction_time_s=res.metadata.get("model_construction_time_s"),
        engine_init_time_s=res.metadata.get("engine_init_time_s"),
        solver_time_s=res.metadata.get("solver_time_s"),
        bandwidth=bw,
        best_bound=best_bound,
        optimality_gap=gap,
        solver_status=status_str,
        proof_status=proof_status,
        validation=report.valid if report is not None else None,
        initial_lb=init_lb,
        initial_ub=init_ub if use_ub else None,
        final_ub=res.upper_bound,
        peak_memory_mb=peak_mem,
        published_lb=meta.paper_lb,
        published_best=meta.paper_best,
        anchor_vertex=res.metadata.get("anchor_vertex"),
        model_variables=res.metadata.get("model_variables"),
        model_constraints=res.metadata.get("model_constraints"),
        num_branches=res.metadata.get("num_branches"),
        note=res.metadata.get("reason") or res.metadata.get("stop_cause"),
    )
    return row


def _collect_reference_baselines(
    root: Path, instances: list[str]
) -> list[dict[str, Any]]:
    """Collect read-only SAT/MIP reference runs from M2.3 and M3.2 on pilot graphs."""
    refs: list[dict[str, Any]] = []
    inst_set = set(instances)

    m2_path = root / "results" / "member2_m2_3" / "runs.json"
    if m2_path.is_file():
        seen: set[tuple[str, str]] = set()
        for r in json.loads(m2_path.read_text(encoding="utf-8")):
            inst = r.get("instance")
            if inst not in inst_set:
                continue
            label = f"M2.3 {r.get('solver')} ({r.get('encoding') or 'MIP'}, 30s)"
            key = (inst, label)
            if key in seen:
                continue
            # Prefer symmetry_breaking=True baseline entry
            if not r.get("symmetry_breaking", False) and r.get("method") == "SAT":
                continue
            seen.add(key)
            refs.append({
                "source": "results/member2_m2_3/runs.json (historical same-machine, 30s)",
                "instance": inst,
                "solver": label,
                "status": r.get("status"),
                "bandwidth": r.get("bandwidth"),
                "lower_bound": r.get("lower_bound"),
                "runtime_s": r.get("total_wall_time_s"),
            })

    m32_path = root / "results" / "member3_m3_2" / "runs.json"
    if m32_path.is_file():
        best_m32: dict[str, dict[str, Any]] = {}
        for r in json.loads(m32_path.read_text(encoding="utf-8")):
            inst = r.get("instance")
            if inst not in inst_set or r.get("backend") != "minisat" or r.get("bandwidth") is None:
                continue
            prev = best_m32.get(inst)
            if prev is None or int(r["bandwidth"]) < int(prev["bandwidth"]):
                best_m32[inst] = r
        for inst, r in sorted(best_m32.items()):
            refs.append({
                "source": "results/member3_m3_2/runs.json (same-machine pilot, 10s)",
                "instance": inst,
                "solver": f"M3.2 minisat best ({r['encoding']}_{r['amo']}, 10s)",
                "status": r["status"],
                "bandwidth": r["bandwidth"],
                "lower_bound": r["final_lb"],
                "runtime_s": r["total_time_s"],
            })
    return refs


def _generate_figures(rows: list[dict[str, Any]], output_dir: Path, pilot_instances: list[str]) -> list[str]:
    fig_dir = output_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import pandas as pd

        try:
            import cnsplots  # noqa: F401
        except Exception:
            pass
    except Exception:
        return saved

    main_rows = [
        r
        for r in rows
        if r["symmetry_breaking"] is True
        and r["use_lower_bound"] is True
        and r["use_initial_upper_bound"] is True
        and r["hint_type"] == "rcm"
        and r["bandwidth"] is not None
    ]
    if not main_rows:
        return saved

    df = pd.DataFrame(main_rows)
    order = [inst for inst in pilot_instances if inst in set(df["instance"])]

    # Figure 1: CP-SAT vs CP Optimizer Bandwidth & Published Best
    fig, ax = plt.subplots(figsize=(9, 4.8))
    x = list(range(len(order)))
    width = 0.26
    cpsat_vals = []
    cpo_vals = []
    pub_vals = []
    for inst in order:
        sub_c = df[(df["instance"] == inst) & (df["solver"] == "cp-sat")]
        sub_o = df[(df["instance"] == inst) & (df["solver"] == "cp-optimizer")]
        cpsat_vals.append(int(sub_c["bandwidth"].iloc[0]) if not sub_c.empty else 0)
        cpo_vals.append(int(sub_o["bandwidth"].iloc[0]) if not sub_o.empty else 0)
        pub_vals.append(int(ALL_INSTANCES[inst].paper_best))

    ax.bar([i - width for i in x], cpsat_vals, width, label="CP-SAT (20s, sym=True)", color="#1f77b4")
    ax.bar(x, cpo_vals, width, label="IBM CP Optimizer (20s, sym=True)", color="#ff7f0e")
    ax.bar([i + width for i in x], pub_vals, width, label="Published Best (DRSA paper)", color="#2ca02c")
    ax.set_xticks(x)
    ax.set_xticklabels(order)
    ax.set_ylabel("Bandwidth (lower is better)")
    ax.set_title("M3.3 Pilot: CP-SAT vs IBM CP Optimizer Bandwidth on Verified READY Instances")
    ax.legend()
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    fig.tight_layout()
    fig1 = fig_dir / "fig1_cp_bandwidth_comparison.svg"
    fig.savefig(fig1)
    plt.close(fig)
    saved.append(str(fig1.relative_to(output_dir)))

    # Figure 2: Total Wall Time vs Model Construction Time (sym=True vs False)
    fig, ax = plt.subplots(figsize=(9, 4.8))
    labels = []
    times_sym_on = []
    times_sym_off = []
    for slv in ("cp-sat", "cp-optimizer"):
        for inst in order:
            on_r = [
                r["total_wall_time_s"]
                for r in rows
                if r["solver"] == slv and r["instance"] == inst and r["symmetry_breaking"] is True
                and r["hint_type"] == "rcm" and r["use_lower_bound"] is True and r["use_initial_upper_bound"] is True
            ]
            off_r = [
                r["total_wall_time_s"]
                for r in rows
                if r["solver"] == slv and r["instance"] == inst and r["symmetry_breaking"] is False
            ]
            if on_r and off_r:
                labels.append(f"{inst}\n({slv})")
                times_sym_on.append(on_r[0])
                times_sym_off.append(off_r[0])

    idx = list(range(len(labels)))
    w = 0.36
    ax.bar([i - w / 2 for i in idx], times_sym_on, w, label="symmetry_breaking=True", color="#4c72b0")
    ax.bar([i + w / 2 for i in idx], times_sym_off, w, label="symmetry_breaking=False", color="#dd8452")
    ax.set_xticks(idx)
    ax.set_xticklabels(labels, rotation=25, ha="right", fontsize=8)
    ax.set_ylabel("Total Wall Time (s)")
    ax.set_title("M3.3 Pilot: Wall Time With vs Without Reversal Symmetry Breaking")
    ax.legend()
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    fig.tight_layout()
    fig2 = fig_dir / "fig2_cp_runtime_symmetry.svg"
    fig.savefig(fig2)
    plt.close(fig)
    saved.append(str(fig2.relative_to(output_dir)))
    return saved


def _write_summary_and_report(
    *,
    rows: list[dict[str, Any]],
    preflight_rows: list[dict[str, Any]],
    refs: list[dict[str, Any]],
    figures: list[str],
    output_dir: Path,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    by_solver: dict[str, dict[str, int]] = {}
    for r in rows:
        slv = str(r["solver"])
        st = str(r["solver_status"])
        by_solver.setdefault(slv, {})
        by_solver[slv][st] = by_solver[slv].get(st, 0) + 1

    paired = []
    by_pair = {
        (r["instance"], r["solver"]): r
        for r in rows
        if r["symmetry_breaking"] is True
        and r["use_lower_bound"] is True
        and r["use_initial_upper_bound"] is True
        and r["hint_type"] == "rcm"
    }
    for inst in metadata["config"]["pilot_instances"]:
        rc = by_pair.get((inst, "cp-sat"))
        ro = by_pair.get((inst, "cp-optimizer"))
        if rc and ro:
            paired.append({
                "instance": inst,
                "n": rc["n"],
                "m": rc["m"],
                "published_lb": rc["published_lb"],
                "published_best": rc["published_best"],
                "cpsat_status": rc["solver_status"],
                "cpsat_bw": rc["bandwidth"],
                "cpsat_lb": rc["best_bound"],
                "cpsat_time_s": rc["total_wall_time_s"],
                "cpo_status": ro["solver_status"],
                "cpo_bw": ro["bandwidth"],
                "cpo_lb": ro["best_bound"],
                "cpo_time_s": ro["total_wall_time_s"],
            })

    summary = {
        "total_runs": len(rows),
        "preflight_ready_total": len(preflight_rows),
        "status_by_solver": by_solver,
        "all_validations_passed": all(
            r["validation"] is True for r in rows if r["validation"] is not None
        ),
        "paired_cp_comparison": paired,
        "reference_baselines": refs,
        "figures": figures,
    }

    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    (output_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )

    lines = [
        "# Member 3 Phase M3.3 – CP-SAT vs IBM CP Optimizer Pilot Comparison",
        "",
        f"- **Git commit:** `{metadata['git_commit']}`",
        f"- **OR-Tools CP-SAT:** `{metadata['environment'].get('ortools_version')}`",
        f"- **IBM CP Optimizer:** `docplex {metadata['environment'].get('docplex_version')}` + engine `{metadata['environment'].get('cpo_executable_path')}`",
        f"- **Preflight verified READY total:** `{len(preflight_rows)}` (`PILOT_READY`: `{sum(1 for p in preflight_rows if p['eligibility'] == 'PILOT_READY')}`)",
        f"- **Status counts by solver:** `{by_solver}`",
        f"- **All returned solutions validated:** `{summary['all_validations_passed']}`",
        "",
        "## Experiment C – CP-SAT vs IBM CP Optimizer (`sym=True`, `threads=1`, `seed=17`, `timeout=20s`)",
        "",
        "| Instance | n | m | Pub LB/Best | CP-SAT Status | CP-SAT BW (LB) | CP-SAT Time (s) | CPO Status | CPO BW (LB) | CPO Time (s) |",
        "|---|---:|---:|:---:|---|---:|---:|---|---:|---:|",
    ]
    for p in paired:
        lines.append(
            f"| {p['instance']} | {p['n']} | {p['m']} | {p['published_lb']}/{p['published_best']} | "
            f"{p['cpsat_status']} | {p['cpsat_bw']} ({p['cpsat_lb']}) | {p['cpsat_time_s']:.3f} | "
            f"{p['cpo_status']} | {p['cpo_bw']} ({p['cpo_lb']}) | {p['cpo_time_s']:.3f} |"
        )

    lines.extend([
        "",
        "## Symmetry & Bound Ablation Summary",
        "",
        "| Instance | Solver | Sym | Use LB | Hint | Status | BW (LB) | Wall Time (s) |",
        "|---|---|---:|---:|---|---|---:|---:|",
    ])
    for r in rows:
        lines.append(
            f"| {r['instance']} | {r['solver']} | {r['symmetry_breaking']} | {r['use_lower_bound']} | "
            f"{r['hint_type']} | {r['solver_status']} | {r['bandwidth']} ({r['best_bound']}) | {r['total_wall_time_s']:.3f} |"
        )

    lines.extend([
        "",
        "## Experiment D – Reference Comparison with Leader/M2 SAT & MIP (Different Time Budgets Noted)",
        "",
        "| Instance | Reference Run | Status | BW | LB | Wall Time (s) |",
        "|---|---|---|---:|---:|---:|",
    ])
    for ref in refs:
        lines.append(
            f"| {ref['instance']} | {ref['solver']} | {ref['status']} | {ref['bandwidth']} | "
            f"{ref['lower_bound']} | {ref['runtime_s']} |"
        )

    (output_dir / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def run(config_path: str | Path, *, resume: bool = True) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[3]
    cfg_path = Path(config_path)
    if not cfg_path.is_absolute():
        cfg_path = root / cfg_path
    cfg = tomllib.loads(cfg_path.read_text(encoding="utf-8"))["benchmark"]

    prov_path = root / cfg["provenance"]
    raw_dir = root / cfg["raw_dir"]
    fallback_raw = root / cfg["fallback_raw_dir"] if cfg.get("fallback_raw_dir") else None
    output_dir = root / cfg["output_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)

    provenance_entries = json.loads(prov_path.read_text(encoding="utf-8"))
    pilot_instances = list(cfg["pilot_instances"])
    preflight_rows, loaded_pilot = _run_preflight(
        provenance_entries,
        raw_dir=raw_dir,
        fallback_raw_dir=fallback_raw,
        pilot_set=set(pilot_instances),
        max_cp_vars=int(cfg["max_cp_vars"]),
        max_cp_constrs=int(cfg["max_cp_constraints"]),
    )

    missing_pilot = sorted(set(pilot_instances) - set(loaded_pilot))
    if missing_pilot:
        raise RuntimeError(f"Missing or unverified pilot instances: {missing_pilot}")

    with (output_dir / "preflight.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=PREFLIGHT_FIELDS)
        writer.writeheader()
        for prow in preflight_rows:
            writer.writerow(_format_csv_row(prow, PREFLIGHT_FIELDS))

    env_info = _detect_cp_environment()
    git_sha = _git_commit()
    plan = _build_plan(cfg)

    runs_json_path = output_dir / "runs.json"
    existing: dict[str, dict[str, Any]] = {}
    if resume and runs_json_path.is_file():
        for prev in json.loads(runs_json_path.read_text(encoding="utf-8")):
            existing[str(prev["run_id"])] = prev

    log_lines: list[str] = []
    rows: list[dict[str, Any]] = []
    for item in plan:
        rid = item["run_id"]
        if rid in existing:
            rows.append(existing[rid])
            log_lines.append(f"[RESUME] {rid} {item['instance']} {item['solver']} sym={item['symmetry_breaking']}")
            continue

        graph, prov, raw_path = loaded_pilot[item["instance"]]
        row = _execute_item(
            item,
            graph=graph,
            prov=prov,
            raw_path=raw_path,
            env_info=env_info,
            git_sha=git_sha,
        )
        rows.append(row)
        log_lines.append(
            f"[DONE] {rid} {row['instance']} {row['solver']} sym={row['symmetry_breaking']} "
            f"lb={row['use_lower_bound']} ub={row['use_initial_upper_bound']} hint={row['hint_type']} -> "
            f"status={row['solver_status']} bw={row['bandwidth']} bound={row['best_bound']} "
            f"wall={row['total_wall_time_s']}s valid={row['validation']}"
        )
        seen_ids = {str(r["run_id"]) for r in rows}
        checkpoint = rows + [r for rid_key, r in existing.items() if rid_key not in seen_ids]
        runs_json_path.write_text(json.dumps(checkpoint, indent=2), encoding="utf-8")

    runs_json_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")

    with (output_dir / "runs.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=M3_3_FIELDS)
        writer.writeheader()
        for r in rows:
            writer.writerow(_format_csv_row(r, M3_3_FIELDS))

    refs = _collect_reference_baselines(root, pilot_instances)
    figures = _generate_figures(rows, output_dir, pilot_instances)

    metadata = {
        "experiment_name": cfg["name"],
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "git_commit": git_sha,
        "environment": env_info,
        "config": cfg,
        "provenance_counts": {
            "total": len(provenance_entries),
            "ready": sum(1 for e in provenance_entries if e["validation_status"] == "READY"),
            "needs_verification": sum(1 for e in provenance_entries if e["validation_status"] == "NEEDS_VERIFICATION"),
            "invalid_data": sum(1 for e in provenance_entries if e["validation_status"] == "INVALID_DATA"),
        },
        "total_planned_runs": len(plan),
    }

    summary = _write_summary_and_report(
        rows=rows,
        preflight_rows=preflight_rows,
        refs=refs,
        figures=figures,
        output_dir=output_dir,
        metadata=metadata,
    )
    (output_dir / "run_log.txt").write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/member3_m3_3.toml"),
        help="Path to M3.3 CP TOML benchmark config",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        default=False,
        help="Re-run all planned items instead of resuming from runs.json",
    )
    args = parser.parse_args(argv)
    summary = run(args.config, resume=not args.no_resume)
    print(json.dumps(summary["status_by_solver"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
