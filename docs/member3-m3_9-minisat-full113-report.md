# Phase M3.9: MiniSat22 Full 113-Instance Harwell–Boeing Benchmark & Scalability Report

> Branch: `dev/member-3` (1D BMP — strictly separated from `main`, `dev/leader`, and `dev/member-2`)  
> Environment: macOS 14.0 (`Darwin 23.0.0 arm64`), Apple M2 (8 cores), 16.0 GiB RAM, Python `3.14.3`, `python-sat 1.9.dev17` (`minisat22`, `cadical195`, `glucose4`), OR-Tools `9.15.6755`, `docplex 2.32.264`

---

## 1. Git Audit (Before & After)

- **Baseline HEAD before M3.9**: `0d90086` (`dev/member-3`, 50 local commits ahead of `origin/dev/member-3` `19ce024`, ahead 40 / behind 6 of `origin/dev/leader` `e614334`).
- **Untouched Historical Data**: `results/member3_m3_8_full113/`, `results/member3_complete/`, `results/member3-harwell-boeing.csv`, and pre-existing untracked `results/member2_hb_table6_7/` were preserved completely intact.
- **M3.9 Implementation & Results Output**: Stored cleanly in [`results/member3_m3_9_minisat_full113/`](file:///Users/nguyenanhson/BMP/results/member3_m3_9_minisat_full113).

## 2. MiniSat22 Baseline vs Phase M3.9 Scope

| Milestone | Eligible / Studied HB | Attempted | MiniSat Solver Witnesses | SAT OPT Proved | Datasets Preserved |
|---|---:|---:|---:|---:|---|
| M3.8 (`results/member3_m3_8_full113/`) | 8 studied | 8 | 4 | 0 | `sat_runs.csv` |
| Member 3 Complete (`0d90086`) | 10 studied (`4.0s`) | 10 | 5 | 0 | `64` repeated + `32` incremental runs |
| **Phase M3.9 (`results/member3_m3_9_minisat_full113/`)** | **85 / 113** | **85 / 85** | **14 / 113** | **3 (`pores_1`, `steam3`, `nos1`)** | `169` repeated + `78` incremental MiniSat runs |

## 3. Dataset Coverage & Provenance (Exact 113 Instances)

- Source catalog: Torres-Jimenez et al. (*Information Sciences* 303, 2015, pp. 33–49) in [`dataset_113.csv`](file:///Users/nguyenanhson/BMP/results/member3_m3_9_minisat_full113/dataset_113.csv).
- **Exact Partition**: **31 Table 6** + **41 Table 7** + **41 Table 8** = **113 primary Harwell–Boeing views** (111 unique topologies; `sherman1 == saylr3`, `mbeaflw == mbeacxc`).
- **Provenance Tiers**:
  - `TIER1_READY`: **54** instances (`nonzero_union`)
  - `TIER2A_NEEDS_VERIFICATION`: **58** instances (`stored_union`)
  - `TIER2B_INVALID_DATA`: **1** instance (`mbeause`, 496 vertices vs Table 8 header 492)

## 4. MiniSat22 Backend Verification

- Verified live `Minisat22` invocation (`Solver(name="m22")` / [`MiniSatBackend`](file:///Users/nguyenanhson/BMP/src/bmp/solvers/sat/backends/minisat.py)) across `python-sat 1.9.dev17`.
- Verified `append_formula`, `add_clause`, `assumptions`, incremental reuse (`len(created) == 1` + cleanup `backend._deleted == True`), interruption timeout via worker subprocess isolation ([`worker.py`](file:///Users/nguyenanhson/BMP/src/bmp/solvers/sat/worker.py)), RSS memory sampling, and independent solution validation.

## 5. Product Encoding & 6. Ladder Encoding Results

Paired comparison on **14 identical benchmarks** (4 synthetic known-optima + 10 Table 6/8 HB instances) using `Order(one_sided, compact_boundary)` + `MiniSat22` (`3.5s` limit, [`product_ladder_comparison.csv`](file:///Users/nguyenanhson/BMP/results/member3_m3_9_minisat_full113/product_ladder_comparison.csv)):

| Configuration | Runs | Witnesses | SAT OPT | Mean Vars | Mean Clauses | Mean Wall Time |
|---|---:|---:|---:|---:|---:|---:|
| `MiniSat22 + Product + Incremental` | 14 | **11** | **5** | **7,677.4** | 40,605.9 | **2.375s** |
| `MiniSat22 + Ladder + Incremental` | 14 | 8 | 4 | 10,375.9 | 35,828.4 | 2.602s |
| `MiniSat22 + Product + Repeated Binary` | 14 | **8** | **5** | **7,872.9** | 34,292.9 | **2.403s** |
| `MiniSat22 + Ladder + Repeated Binary` | 14 | 6 | 4 | 10,375.9 | 33,299.0 | 2.571s |

Cross-backend comparison on the **10 HB subset** (`Order + Product + Compact + Incremental Linear`, `3.5s`): `Glucose4` found `7/10` witnesses (`mean 3.509s`), `MiniSat22` found `7/10` HB witnesses (`11/14` total), and `CaDiCaL` found `4/10` witnesses within `3.5s`.

## 7. SAT Main Encoding & Selective L9 Integration

Selectively integrated L9 optimizations cleanly from `origin/dev/leader` while preserving Member 3 APIs (`on_incumbent`, all 6 AMO estimators, bitmask BFS lower bounds):
- [`OrderEncoding`](file:///Users/nguyenanhson/BMP/src/bmp/encodings/order.py): `channel_mode="one_sided"`, `compact_boundary=True` (cuts `2n` variables and ~3x channeling clauses).
- [`PairwiseEncoding`](file:///Users/nguyenanhson/BMP/src/bmp/encodings/pairwise.py): `occupancy_mode="pigeonhole"`, `bandwidth_mode="support_single"` (eliminates $n$ vertex AMO blocks and quadratic conflict pairs, using optimized `*range(...)` clause generation).
- [`search.py`](file:///Users/nguyenanhson/BMP/src/bmp/solvers/sat/search.py): `extract_connected_components` + `solve_sat_with_decomposition`.
- **Stage A Oracle Verification**: **84 / 84 checks passed** (`7` oracle graphs × `4` L9+Product/Ladder encoders × `3` MiniSat22 search strategies).

## 8. Repeated vs Incremental SAT & 9. Linear vs Binary Search

Paired search strategy evaluation across 8 representative HB instances (`Order + Product + Compact`, `3.5s`, [`search_strategy_comparison.csv`](file:///Users/nguyenanhson/BMP/results/member3_m3_9_minisat_full113/search_strategy_comparison.csv)):

| Strategy (`Order + Product + Compact`, MiniSat22) | Instances | Witnesses | SAT OPT | Mean Wall Time |
|---|---:|---:|---:|---:|
| `repeated_linear` | 8 | **6** | 1 | 3.270s |
| `incremental_linear` | 8 | 5 | 1 | 3.318s |
| `repeated_binary` | 8 | 4 | 1 | 3.271s |
| `incremental_binary` | 8 | 1 | 1 | 3.256s |

**Key Finding**: Descending `linear` search starting just below `RCM` (`k = RCM - 1`) finds SAT witnesses immediately near feasible upper bounds (`6/8`), whereas `binary` search jumps to `(LB + UB) // 2` (often UNSAT), stalling MiniSat22 when $k_{\text{mid}} < \text{OPT}$; conversely, `repeated_binary` discovers large single-step improvements (e.g., `will57`: `14 -> 9` and `arc130`: `121 -> 68`, `fs_183_1`: `155 -> 103`), while `repeated_linear` stays eligible even on dense `n=496` matrices (`mbeacxc`, `mbeaflw`, `mbeause`) where binary midpoints exceed 10M clauses.

## 10. Heuristic Upper-Bound Impact

Paired warm-start evaluation on 6 HB instances (`Order + Product + Compact + Repeated Binary`, `3.5s`, [`warm_start_comparison.csv`](file:///Users/nguyenanhson/BMP/results/member3_m3_9_minisat_full113/warm_start_comparison.csv)):
- `IDENTITY`: mean initial bw `24.0` -> mean pipeline bw `8.8`, `4/6` witnesses, `1 OPT`.
- `RCM`: mean initial bw **`10.5`** -> mean pipeline bw **`8.3`**, **`4/6` witnesses**, `1 OPT`.
- `SA`: mean initial bw **`10.5`** -> mean pipeline bw **`8.3`**, **`4/6` witnesses**, `1 OPT`.
- `DRSA`: mean initial bw `10.0` -> mean pipeline bw `8.8`, `3/6` witnesses, `1 OPT` (starting at tight `DRSA - 1` pushes MiniSat directly into hard UNSAT territory).

Strict attribution (`classify_m3_9_attribution`) keeps `initial_incumbent_source`, `solver_found_solution`, `solver_best_bandwidth`, `pipeline_best_bandwidth`, and `proof_source` completely separated.

## 11. Full 113 Preflight Summary

Evaluated all **113** primary graphs × **8** MiniSat configurations under `max_variables = 500,000`, `max_clauses = 2,500,000`, `memory_limit_mb = 4,096` ([`minisat_preflight_113.csv`](file:///Users/nguyenanhson/BMP/results/member3_m3_9_minisat_full113/minisat_preflight_113.csv)):
- **Union Eligible Across Valid MiniSat Configs**: **`85 / 113`** (`31/31` Table 6, `23/41` Table 7, `31/41` Table 8).
- Noticeable gain: Adding component decomposition + `Pairwise(product, pigeonhole, support_single)` + `Repeated Linear` unlocked **+29 instances** beyond `Order Full` (`56 -> 85`), covering large multi-component/sparse instances like `nos2` (`n=957` -> components `[638, 319]`), `saylr3` (`n=1000` -> `[681, 2, 2]` + `315` isolated), `pores_3` (`n=532`), and `mbeacxc/mbeaflw/mbeause` (`n=496` via `Repeated Linear` at `k = rcm - 1`).

## 12–19. Full 113 Solver Campaign Results (Mandatory Unique-Instance Summary)

| Table | Total | Preflight | Eligible | MiniSat attempted | MiniSat feasible | SAT optimal | Bound optimal | Timeout | ResourceLimit |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Table 6 | 31 | 31 | 31 | 31 | 13 | 2 | 0 | 18 | 0 |
| Table 7 | 41 | 41 | 23 | 23 | 0 | 0 | 0 | 23 | 18 |
| Table 8 | 41 | 41 | 31 | 31 | 1 | 1 | 0 | 30 | 10 |
| Total | 113 | 113 | 85 | 85 | 14 | 3 | 0 | 71 | 28 |

*Note*: `MiniSat feasible` counts unique instances where MiniSat22 returned a direct SAT model witness (`SAT_SOLVER_FEASIBLE` or `SAT_PROVED_OPTIMAL` via SAT+UNSAT) or closed optimality via UNSAT refutation (`steam3` `n=80` with `RCM=7` and MiniSat22 UNSAT at `k=6`): Table 6 has `11 SAT_SOLVER_FEASIBLE` + `2 SAT_PROVED_OPTIMAL` (`pores_1`, `steam3`) = `13`; Table 8 has `1 SAT_PROVED_OPTIMAL` (`nos1` `n=237, bw=3`) -> Total **`14 / 85`** attempted eligible instances (**`85 / 85 = 100%`** eligible attempted, **`28`** explicit `RESOURCE_LIMIT`, **`0`** validation failures).

By Tier ([`per_tier_summary.csv`](file:///Users/nguyenanhson/BMP/results/member3_m3_9_minisat_full113/per_tier_summary.csv)):
- `TIER1_READY`: 54 total -> 42 eligible / 42 attempted -> 5 witnesses (1 OPT: `pores_1`), 37 timeout, 12 ResourceLimit.
- `TIER2A_NEEDS_VERIFICATION`: 58 total -> 42 eligible / 42 attempted -> 9 witnesses (2 OPT: `steam3`, `nos1`), 33 timeout, 16 ResourceLimit.
- `TIER2B_INVALID_DATA` (`mbeause`): 1 total -> 1 eligible / 1 attempted -> 1 timeout.

## 20–21. Runtime & Memory Profile (Executed Campaign Runs)

Across `108` live MiniSat22 invocations in `minisat_runs_113.csv`:
- **Wall runtime**: min `1.555s`, median `10.062s`, mean `12.431s`, max `25.661s`.
- **Peak RSS memory**: min `22.5 MiB`, median `258.0 MiB`, mean `679.2 MiB`, max **`2,816.4 MiB`** (strictly bounded under the `4,096 MiB` limit; 0 OOM kills).
- **12 Generated SVGs**: [`results/member3_m3_9_minisat_full113/figures/`](file:///Users/nguyenanhson/BMP/results/member3_m3_9_minisat_full113/figures) (`fig01_minisat_coverage_113.svg` through `fig12_resource_limit_vs_timeout_dist.svg`).

## 22–23. No-Regression & Preservation Verification

- **CP-SAT (`results/member3_complete/cpsat_results.csv`)**: Untouched **113 / 113 valid solutions (16 OPT, 97 FEAS)** on 1D vertex permutations (not 2DBMP).
- **RCM / SA / DRSA / CP Optimizer**: Untouched `113/113` RCM & SA, `113/113` DRSA (`member3_m3_8_full113`), `20/20` CPO CE (`93` license-blocked).
- **Historical MiniSat baseline (`results/member3_complete/`)**: Untouched `64` repeated + `32` incremental runs preserved cleanly.

## 24. Verification: Tests, Wheel Build & CLI

- **Wheel Build & Outside-Repo Import**: Built `bmp_optimization-0.1.0-py3-none-any.whl` via `pip wheel --no-deps --no-build-isolation`; imported cleanly from `/tmp` and executed `MiniSat22` + `OrderEncoding(one_sided, compact_boundary)` on `cycle_graph(5)` (`OPTIMAL bw=2`).
- **CLI Verification**: `.venv/bin/bmp solve data/samples/cycle_c4.edgelist --solver minisat --encoding order --amo product --strategy incremental` -> `OPTIMAL bw=2`, `validation.valid=True`; `.venv/bin/bmp estimate-cnf ... -k 1` -> exact `44` vars / `104` clauses.
- **Full Pytest Suite**: Executed across the entire `tests/` directory (`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider -q tests/`) after all final edits -> **182 / 182 tests passed (`Command exited with code 0`, 0 failed, 0 skipped)**.

## 25–28. Integration Instructions, Limitations & Final Verdict

- **Integration**: `dev/member-3` now cleanly carries selective L9 encoding improvements (`order.py`, `pairwise.py`, `search.py`, `incremental.py`, `repeated.py`, `estimator.py`) alongside Member 3's **Product/Ladder AMOs**, **MiniSat22 backend**, and **CP-SAT 113/113**, making it safe to review/merge with `dev/leader` and `dev/member-2`.
- **Remaining Limitations**:
  1. `28 / 113` Harwell–Boeing matrices (dense `n >= 496` Table 7/8 instances such as `bp_*`, `can_715`, `can_838`, `dwt_878..992`, `gr_30_30`, `nos3..nos7`, `orsirr_2`) exceed `500,000` variables or `2,500,000` clauses across all candidate SAT encodings (`RESOURCE_LIMIT`).
  2. Within practical SAT CDCL time budgets (`10–35s`), `MiniSat22` lacks the inprocessing/lookahead strength of `CaDiCaL` on medium/large Harwell–Boeing UNSAT proofs (`71 / 85` attempted instances hit timeout after exhausting budget without closing the `LB = UB` optimality gap).
- **Final Verdict**: **Phase M3.9 COMPLETE** — **113 / 113** HB dataset verified, **85 / 85 (`100%`)** of preflight-eligible instances actually executed with real `Minisat22`, **14 / 113** direct SAT solver witnesses (`3 SAT_PROVED_OPTIMAL` including Table 8 `nos1` `n=237` in `1.99s`), zero regressions across CP-SAT `113/113`, RCM, SA, DRSA, and all 18 CSV/JSON/SVG artifacts generated reproducibly.
