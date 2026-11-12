# MEMBER 3 — COMPLETION & 113-INSTANCE EVALUATION REPORT (1D BMP)

> Branch: `dev/member-3` (local only — **not pushed to remote**, baseline `789b2a3`, remote `origin/dev/member-3` untouched at `19ce024`)  
> Problem Formulation: **1D Bandwidth Minimization Problem (1D BMP)** — minimize $\beta(p) = \max_{(u,v) \in E} |p(u) - p(v)|$ over bijections $p: V \to \{1, \dots, n\}$  
> Environment: macOS 14.0 (`Darwin 23.0.0 arm64`), Apple M2 (8 cores), 16.0 GB RAM, Python `3.14.3`, OR-Tools `9.15.6755`, `python-sat 1.9.dev17` (`minisat22`, `cadical195`, `glucose4`), `docplex 2.32.264`, CPLEX / CP Optimizer CE `22.2.0.0`, `gurobipy 13.0.3`

---

## 1. Initial State & Baseline Audit (`789b2a3`)

Before edits on `dev/member-3`:
- **Product Encoding** ([`src/bmp/encodings/cardinality/product.py`](file:///Users/nguyenanhson/BMP/src/bmp/encodings/cardinality/product.py)) and **Ladder Encoding** ([`src/bmp/encodings/cardinality/ladder.py`](file:///Users/nguyenanhson/BMP/src/bmp/encodings/cardinality/ladder.py)) were implemented and unit-tested (`encode_product_amo`, `ProductAMOEncoder`, `encode_ladder_amo`, `LadderAMOEncoder`).
- **MiniSat22 Backend** ([`src/bmp/solvers/sat/backends/minisat.py`](file:///Users/nguyenanhson/BMP/src/bmp/solvers/sat/backends/minisat.py)) wrapped PySAT `Minisat22` for both `RepeatedSATSolver` and `IncrementalSATSolver`, but prior M3.8 experiments (`results/member3_m3_8_full113/sat_runs.csv`) only ran `minisat` in 1 configuration (`order + product + incremental`) on 8 instances with 0 `minisat + repeated` and 0 `minisat + ladder` runs.
- **RCM** ([`src/bmp/heuristics/rcm.py`](file:///Users/nguyenanhson/BMP/src/bmp/heuristics/rcm.py)), **SA** ([`src/bmp/heuristics/sa.py`](file:///Users/nguyenanhson/BMP/src/bmp/heuristics/sa.py)), and **IBM CP Optimizer** ([`src/bmp/solvers/exact/cp_optimizer.py`](file:///Users/nguyenanhson/BMP/src/bmp/solvers/exact/cp_optimizer.py)) were implemented.
- **CP-SAT Baseline** (`results/member3_m3_8_full113/cpsat_113.csv`, preserved untouched):
  - **78 / 113** valid solutions (**4 `OPTIMAL_PROVED`**, **74 `FEASIBLE_SOLUTION_FOUND`**)
  - **35 / 113 `TIMEOUT_NO_INCUMBENT`** (0 solutions returned)
- **Dataset**: **113** Harwell–Boeing instances matching Torres-Jimenez et al. (*Information Sciences* 303, 2015, pp. 33–49), partitioned cleanly across **Table 6 (31)**, **Table 7 (41)**, and **Table 8 (41)** (`54 READY`, `58 NEEDS_VERIFICATION`, `1 INVALID_DATA` for `mbeause` with 4 degree-0 vertices). Historical baselines in `results/member3-harwell-boeing.csv` and `results/member3_m3_8_full113/` remain unmodified.

---

## 2. Root-Cause Bugs Discovered & Fixed

1. **OR-Tools CP-SAT `AllDifferent` Presolve Stall on 35/113 Instances (`branches=0, conflicts=0`)**  
   - **Diagnosis**: Profiling `bcspwr03` (`n=118`) and `dwt_209` (`n=209`) with `log_search_progress=True` revealed OR-Tools `v9.15.6755` expands `model.add_all_different(...)` into $O(n^2)$ Boolean encoding variables (`13,924` Booleans on `n=118`) and stalls in presolve `[Probe]` + general orbit symmetry detection (`Stopped after presolve`, `0` branches, `0` conflicts, `UNKNOWN`) before verifying even the complete feasible warm-start hint (`The solution hint is complete and is feasible`). Additionally, M3.8 used `threads=1` and `cpsat_extended_max_n=700`, skipping Pass 2 recovery on `mcfe` (`n=765`).
   - **Fix** ([`src/bmp/solvers/exact/cpsat.py`](file:///Users/nguyenanhson/BMP/src/bmp/solvers/exact/cpsat.py)): Added `injectivity_mode="auto"` (`"auto" | "all_different" | "no_overlap"`) and `presolve: bool | None = None`. For $n \le 75$, keeps `add_all_different` + `presolve=True` to preserve tight dual bounds and `OPT` proofs. For $n > 75$, uses mathematically equivalent fixed-size unit intervals $[p_v, p_v+1)$ via `model.add_no_overlap(...)` and disables `cp_model_presolve` (`False`), eliminating the quadratic Boolean presolve stall without weakening validation.

2. **All-Pairs BFS Lower-Bound Bottleneck on Dense Harwell–Boeing Graphs**  
   - **Diagnosis**: Cold calls to `compute_lower_bound(g)` on dense graphs like `mbeause` (`n=496, m=36,209`) spent **12.31s** iterating edge lists inside `_cached_component_diameters`.
   - **Fix** ([`src/bmp/solvers/sat/search.py`](file:///Users/nguyenanhson/BMP/src/bmp/solvers/sat/search.py)): Replaced inner BFS stamp lists with Python arbitrary-precision integer bitmask BFS (`adj_mask[u]`), cutting `compute_lower_bound(mbeause)` runtime from **12.31s -> 1.16s** (>10x speedup) with identical exact result (`245`).

---

## 3. Files Modified & Created (Strictly Local `dev/member-3`)

### Modified Files
- [`src/bmp/solvers/exact/cpsat.py`](file:///Users/nguyenanhson/BMP/src/bmp/solvers/exact/cpsat.py) — Adaptive `injectivity_mode` (`no_overlap` + `cp_model_presolve=False` for `n > 75`, `all_different` + `presolve=True` for `n <= 75`), metadata instrumentation.
- [`src/bmp/solvers/sat/search.py`](file:///Users/nguyenanhson/BMP/src/bmp/solvers/sat/search.py) — Big-int bitmask BFS in `_cached_component_diameters`.
- [`tests/test_member3_cp_m3_3.py`](file:///Users/nguyenanhson/BMP/tests/test_member3_cp_m3_3.py) — Added oracle cross-checks for `no_overlap` / `presolve=False` across `ORACLE_GRAPHS` and live regression test unblocking `bcspwr03`.

### Created Files
- [`scripts/run_member3_complete.py`](file:///Users/nguyenanhson/BMP/scripts/run_member3_complete.py) — Reproducible runner for dataset/Table 6–8 verification and Experiments A–E.
- [`tests/test_member3_complete_suite.py`](file:///Users/nguyenanhson/BMP/tests/test_member3_complete_suite.py) — Unit/integration checks for status classification (`OPT/FEAS/INFEAS/TIMEOUT_WITH_INCUMBENT/TIMEOUT/INVALID/BLOCKED_LICENSE`), `MiniSat22` repeated vs incremental on `grid_3x3` and `petersen_10` (`bw=5`), Product/Ladder edge cases, and 113/31/41/41 export verification.
- [`MEMBER3_COMPLETION_REPORT.md`](file:///Users/nguyenanhson/BMP/MEMBER3_COMPLETION_REPORT.md) — This report.
- Experimental outputs under [`results/member3_complete/`](file:///Users/nguyenanhson/BMP/results/member3_complete):
  - `dataset_manifest.csv` (113 unique instances)
  - `table_6_reference.csv` (31 rows)
  - `table_7_reference.csv` (41 rows)
  - `table_8_reference.csv` (41 rows)
  - `cpsat_results.csv` (118 pass records across 113 instances)
  - `minisat_repeated_results.csv` (64 runs)
  - `minisat_incremental_results.csv` (32 runs)
  - `product_ladder_comparison.csv` (64 runs across `minisat` and `cadical`)
  - `heuristics_results.csv` (452 runs: 113 RCM + 339 multi-seed SA)
  - `cp_optimizer_results.csv` (113 evaluation records: 20 CE live + 93 license-gated)
  - `aggregate_experimental_summary.csv` & `run_metadata.json`

---

## 4. Experimental Evaluation Results

### Experiment A — CP-SAT Baseline (`78/113`) vs Final Implementation (`113/113`)

| Metric | M3.8 Baseline (`cpsat_113.csv`) | Final Improved (`cpsat_results.csv`, `threads=4`) | Change |
| :--- | :---: | :---: | :---: |
| Total Instances Evaluated | **113** | **113** | Preserved 113 |
| Valid Solutions Found | **78 / 113** (69.0%) | **113 / 113** (**100.0%**) | **+35 solved (all 35 failures resolved)** |
| `OPT` Proved | **4** | **16** | **+12 (`4x`)** |
| `FEAS` Valid Incumbent | **74** | **97** | +23 |
| `TIMEOUT` (No Incumbent) | **35** | **0** | **-35 (100% eliminated)** |
| `INVALID` / `INFEAS` / `UNKNOWN` | 0 / 0 / 0 | 0 / 0 / 0 | 0 regressions |
| Pass 1 Valid (at identical `3.0s` limit) | 76 / 113 (Pass 1) | **112 / 113** (`12 OPT`, `100 FEAS`, `1 TIMEOUT`) | Resolved `will57` (`OPT bw=6`) in Pass 2 (`12.0s`) |
| Strict Bandwidth Improved vs Baseline-78 | — | **59 / 78** (75.6%) | `113 / 113` same or better (0 regression) |
| Matches/Beats Paper Published Best | — | **28 / 113** | Strictly better than RCM on **91 / 113** |

Certified `OPT` instances (`16/16` match Torres-Jimenez 2015 `published_best` identically): `pores_1` (7), `ibm32` (11), `bcspwr01` (5), `bcsstk01` (16), `bcspwr02` (7), `curtis54` (10), `will57` (6), `steam3` (7), `ash85` (9), `nos4` (10), `bcspwr03` (10), `arc130` (63), `can_144` (13), `can_161` (18), `nos1` (3), `nos2` (3). Mean wall time across 113 best runs: **3.125s** (median **3.043s**, std **1.432s**, min **0.128s**, max **15.046s**).

### Experiment B — MiniSat22 (`Solver(name="m22")`) Actual Execution

Executed live with PySAT `Minisat22` + `OrderEncoding` (`timeout=4.0s`) across 6 synthetic known-optima graphs (`path_p8`, `cycle_c8`, `grid_3x3`, `erdos_renyi_n10_p0.35_s11`, `petersen_10`, `path_p12`) and 10 smallest Table 6 Harwell–Boeing instances (`pores_1` through `ash85`):
- **Repeated SAT (`minisat_repeated_results.csv`, 64 runs: `linear`/`binary` × `product`/`ladder`)**:
  - **24 `OPT`** (all 24 synthetic runs, e.g., `grid_3x3 bw=3`, `petersen_10 bw=5`), **40 `TIMEOUT_WITH_INCUMBENT`** (all 40 HB runs hitting 4.0s proof timeout while holding validated incumbents), **0 `INVALID`**, mean bandwidth **9.69**, mean wall time **2.531s** (median **4.008s**).
- **Incremental SAT (`minisat_incremental_results.csv`, 32 runs: `product`/`ladder`)**:
  - **12 `OPT`** (all 12 synthetic runs), **20 `TIMEOUT_WITH_INCUMBENT`** (HB 4.0s limit; MiniSat22 executed `1–5` live calls and improved incumbent bandwidth on `pores_1` `bw=7` via Ladder, `bcspwr01` `bw=5`, `bcspwr02` `bw=8`, etc. before timing out on UNSAT lower-bound proofs), **0 `INVALID`**, mean bandwidth **9.47**, mean wall time **2.574s**.

### Experiment C — Product vs Ladder AMO (`product_ladder_comparison.csv`, 64 runs)

Identical 16 instances × `OrderEncoding` + `IncrementalSATSolver` (`timeout=4.0s`) across `minisat` and `cadical`:
- **`product` (`32` runs)**: **12 `OPT`**, **20 `TIMEOUT_WITH_INCUMBENT`**, mean variables **`4,442.2`** (**24.1% fewer variables than Ladder**), mean clauses `26,353.5` (`minisat` `26,015.8`, `cadical` `26,691.2`), mean wall time `2.568s`.
- **`ladder` (`32` runs)**: **12 `OPT`**, **20 `TIMEOUT_WITH_INCUMBENT`**, mean variables **`5,856.4`**, mean clauses `26,792.9` (`minisat` `25,493.2`, `cadical` `28,092.6`), mean wall time `2.527s`.

### Experiment D — RCM vs Multi-Seed SA (`heuristics_results.csv`, 452 runs)

- **RCM (`113` deterministic runs)**: **113 / 113** valid, mean bandwidth **131.823** (median **61.0**, min **4**, max **547**), mean runtime **0.035s** (median **0.011s**). Matched `published_best` on `10 / 113`.
- **SA (`339` runs: seeds `0, 17, 42`, `0.2s` limit, initialized from RCM)**: **339 / 339** valid, mean bandwidth **130.631** (median **61.0**), strictly improved over RCM in `33 / 339` runs (`16 / 113` instances), mean runtime **0.203s**.

### Experiment E — CP Optimizer (`cp_optimizer_results.csv`, 113 instances)

- **20 / 20 CE-eligible HB instances (`n <= 138`)**: Executed live (`timeout=5.0s`), **20 `FEAS`**, **100% valid**, mean bandwidth **22.80** (median **14.0**, min **5**, max **65**), mean wall time **5.081s**.
- **93 / 113 remaining instances (`n >= 144`)**: Blocked cleanly by external IBM ILOG CP Optimizer Community Edition $2^{1000}$ search-space limit (`BLOCKED_LICENSE`); zero results fabricated or substituted.

---

## 5. Verification & Remaining Limitations

- **Test Execution**: Ran full Member 3 and core test suite (15 files, **99 collected tests**) via:
  ```bash
  PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider -q \
    tests/test_graph.py tests/test_readers.py tests/test_validation.py tests/test_known_optima.py \
    tests/test_cli.py tests/test_cardinality_amo.py tests/test_member3.py \
    tests/test_member3_integration_m3_1.py tests/test_member3_sat_m3_2.py tests/test_member3_cp_m3_3.py \
    tests/test_member3_drsa_m3_4.py tests/test_member3_forensics_m3_5.py \
    tests/test_member3_unified_m3_6.py tests/test_member3_full113_m3_8.py tests/test_member3_complete_suite.py
  ```
  Result: **99/99 passed (`Command exited with code 0`)**, 0 failed, 0 skipped.
- **Remaining Limitations**:
  1. IBM CP Optimizer CE (macOS arm64) enforces the $2^{1000}$ search-space limit (`93/113` blocked without full academic/commercial license).
  2. Within 4s SAT timeouts, MiniSat22 and CaDiCaL prove `OPT` on small structured graphs (`n <= 12`) and improve incumbents on small HB instances (`n <= 57`), but cannot close UNSAT lower-bound proofs on full Harwell–Boeing instances (`n >= 30`).
  3. On `97/113` larger HB instances (`n > 80`), CP-SAT produces certified valid `FEAS` upper bounds (0 failures), while full optimality certification requires longer proof budgets or tighter theoretical lower bounds.

---

## 6. Reproduction Commands (Local Only)

```bash
# Re-run full Member 3 experimental evaluation into results/member3_complete/
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/run_member3_complete.py \
  --cpsat-threads 4 --cpsat-pass1-timeout 3.0 --cpsat-pass2-timeout 12.0 \
  --cpsat-proof-timeout 15.0 --sat-timeout 4.0 --sa-timeout 0.2

# Run complete unit & integration regression test suite
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider -q \
  tests/test_graph.py tests/test_readers.py tests/test_validation.py tests/test_known_optima.py \
  tests/test_cli.py tests/test_cardinality_amo.py tests/test_member3.py \
  tests/test_member3_integration_m3_1.py tests/test_member3_sat_m3_2.py tests/test_member3_cp_m3_3.py \
  tests/test_member3_drsa_m3_4.py tests/test_member3_forensics_m3_5.py \
  tests/test_member3_unified_m3_6.py tests/test_member3_full113_m3_8.py tests/test_member3_complete_suite.py
```
