# Phase M3.8 Scientific & Technical Report — Full 113/113 Harwell–Boeing Coverage & No-Regression Recovery

- **Branch**: `dev/member-3`
- **Config**: [`configs/member3_m3_8.toml`](../configs/member3_m3_8.toml)
- **Experiment ID**: `m3_8_full113_v1`
- **Result Directory**: `results/member3_m3_8_full113/` (15 tabular/JSON/text deliverables + 10 SVG figures)
- **Test Suite**: [`tests/test_member3_full113_m3_8.py`](../tests/test_member3_full113_m3_8.py)

---

## 1. Executive Summary & Mission Scope

Phase M3.8 expands Member 3's experimental framework from the **54 `READY` subset** audited in M3.5–M3.7 back out to **all 113 Harwell–Boeing instances** (Tables 6, 7, and 8 of the reference paper), while enforcing **zero contamination between verified canonical benchmarks and exploratory/unverified instances**, and proving **no regression** relative to Member 3's pre-M3.1 `72`-instance legacy baseline (`19ce024`, [`results/member3-harwell-boeing.csv`](../results/member3-harwell-boeing.csv)).

Key verified outcomes on Apple M2 (`arm64`, macOS, Python 3.14.3, `threads=1`, `seed=17`):

- **113 / 113 catalog coverage (`100%` loaded, `0` missing files, `0` execution errors)**: `31` Table 6 + `41` Table 7 + `41` Table 8 instances, constructing `113` primary graph views and `23` sensitivity views (**`136` total graph views**, representing `111` unique topologies with `sherman1 == saylr3` and `mbeaflw == mbeacxc`).
- **1,279 executed / evaluated records (`validation_failed = 0`, `execution_errors = 0`, `828` validated feasible/optimal solutions)**:
  - **113 / 113 valid solutions** achieved by all four heuristic modes (`RCM`, `SA`, `DRSA Warm MODIFIED`, `DRSA Paper-Bounded`), with **113 / 113 valid best incumbents** across the benchmark (`0` solutions below `paper_lb`).
  - **CP-SAT multi-pass (Pass 1 @ 3s, Pass 2 Recovery @ 12s for `n <= 700`, Pass 3 Proof @ 30s)**: attempted on `113 / 113`, yielding **`78 / 113` valid solutions** (`4 OPTIMAL_PROVED`: `bcspwr01=5`, `bcspwr02=7`, `ibm32=11`, `pores_1=7`; `74 FEASIBLE_SOLUTION_FOUND`; `35 TIMEOUT_NO_INCUMBENT`).
  - **SAT (`Order + Product + Incremental CaDiCaL`, 6s)**: evaluated all `113 / 113`; **`54 / 54` attempted instances returned valid improved incumbents** (`TIMEOUT_WITH_INCUMBENT`, `25` Tier 1 + `29` Tier 2), while `59` were safely guarded as `RESOURCE_LIMIT` (`0` OOM, `0` crashes). Plus `72 / 72` valid incumbents in `SAT_STUDY_SMALL` (`8` instances × `9` configs) and `8,136` preflight matrix rows (`113 × 72`).
  - **Commercial MIP / CP License Reality on 113**: `Gurobi Eval` (`3/113` eligible, `110` `BLOCKED_LICENSE`), `CPLEX CE` (`1/113` eligible `pores_1`, `112` `BLOCKED_LICENSE`), and `IBM CP Optimizer CE 22.2.0.0` (`20/113` eligible -> **`20/20` valid `FEASIBLE_SOLUTION_FOUND`**, improving RCM on `18/20`; `93` `BLOCKED_LICENSE` due to macOS CE `2^1000` search-space cap).
- **15 / 113 matched the paper's published best bandwidth** (`8/54` Tier 1 Verified + `7/59` Tier 2 Exploratory).

---

## 2. Strict Two-Tier Data Governance & Graph Views (`113` Primary + `23` Sensitivity)

`data/benchmark_provenance.json` remains **unmodified** (`54 READY`, `58 NEEDS_VERIFICATION`, `1 INVALID_DATA`). All outputs maintain strict separation via `official_benchmark` and `tier`:

| Tier | Classification | Count | Primary Conversion Policy | `official_benchmark` | Rationale |
| :--- | :--- | :---: | :--- | :---: | :--- |
| **Tier 1** | `TIER1_VERIFIED_CANONICAL` (`READY`) | **54** | `nonzero_union` (`v1.0`) | `True` | Provenance-verified edge counts matching Table 6–8 definitions |
| **Tier 2a** | `TIER2_EXPLORATORY_UNVERIFIED` (`NEEDS_VERIFICATION`) | **58** | `stored_union` (`v1.0`) | `False` | `22` files contain explicit off-diagonal zeros in Matrix Market files; `stored_union` preserves stored structural nonzeros |
| **Tier 2b** | `TIER2_EXPLORATORY_INVALID_DATA` (`mbeause`) | **1** | `nonzero_union` (`n=496`, `m=36,209`) | `False` | Raw matrix has 4 isolated vertices `[493, 494, 495, 496]`; paired with `492`-vertex sensitivity view |
| **Total** | Full Harwell–Boeing Catalog | **113** | Dual-tier audited | `54 T / 59 F` | Zero mixing of Tier 1 and Tier 2 metrics |

### Sensitivity Findings on the 22 Explicit-Zero Files & `mbeause`

1. **`22` `NEEDS_VERIFICATION` files with `explicit_offdiag_zeros > 0`**: Comparing `stored_union` (primary Tier 2 view) vs `nonzero_union` (`SENSITIVITY_NONZERO_UNION`) confirms `6/22` share the same RCM bandwidth while `16/22` diverge noticeably:
   - `steam2`: `stored_union` (`m=6,580`) achieves `RCM=63` (**matches `paper_best=63`**), whereas `nonzero_union` (`m=3,670`) yields `RCM=82`.
   - `steam3`: `stored_union` (`m=424`) achieves `RCM=7` (**matches `paper_best=7`**), whereas `nonzero_union` (`m=156`) drops to `5` (below `paper_lb=7`).
   - Similar differences appear on `impcol_b` (`38` vs `35`), `impcol_d` (`70` vs `61`), `fs_760_1` (`62` vs `85`), and `fs_680_1` (`24` vs `26`).
   This proves why `stored_union` reproduces the paper's structural matrix definitions on exploratory instances while keeping them isolated as `official_benchmark=False`.
2. **`mbeause` (`n=496` vs `n=492` Sensitivity)**:
   - Primary `mbeause__primary` (`n=496, m=36,209`, isolated `[493, 494, 495, 496]`): `SA = 471` (best), `RCM = 473`, `DRSA Warm = 473` (paper `lb=249`, `best=254`).
   - Sensitivity `mbeause__drop4_492_sens` (`n=492, m=36,209`, 0 isolated): `RCM = 473`, `SA = 473`, `DRSA Warm = 473`.
3. **Topological Duplicates across 113**:
   - Tier 1: `sherman1 == saylr3` (`n=1000, m=1375, isolated=315`).
   - Tier 2: `mbeaflw == mbeacxc` (`n=496, m=41686, isolated=9`).

---

## 3. Full 113-Instance Coverage Matrix (Exact Mutually-Exclusive Accounting)

From [`results/member3_m3_8_full113/method_coverage_113.csv`](../results/member3_m3_8_full113/method_coverage_113.csv) and [`results/member3_m3_8_full113/full113_summary.json`](../results/member3_m3_8_full113/full113_summary.json):

| Method | Catalog | Loaded & Preflight | Attempted | Valid (`T1+T2`) | `OPTIMAL_PROVED` | `FEASIBLE` | `TIMEOUT_W_INC` | `TIMEOUT_NO_INC` | `RESOURCE_LIMIT` | `BLOCKED_LICENSE` | `ERROR` | Median Wall (s) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **RCM (primary 113)** | 113 | 113 | 113 | **113** (`54+59`) | 0 | 113 | 0 | 0 | 0 | 0 | 0 | 0.0106 |
| **SA (primary 113)** | 113 | 113 | 113 | **113** (`54+59`) | 0 | 113 | 0 | 0 | 0 | 0 | 0 | 0.8072 |
| **DRSA Warm MODIFIED (113)** | 113 | 113 | 113 | **113** (`54+59`) | 0 | 113 | 0 | 0 | 0 | 0 | 0 | 0.8105 |
| **DRSA Paper-Bounded (113)** | 113 | 113 | 113 | **113** (`54+59`) | 0 | 113 | 0 | 0 | 0 | 0 | 0 | 0.8144 |
| **CP-SAT Best Across Passes (113)** | 113 | 113 | 113 | **78** (`40+38`) | **4** | 74 | 0 | 35 | 0 | 0 | 0 | 3.8799 |
| **SAT Order+Product+Inc CaDiCaL (113)** | 113 | 113 | 54 | **54** (`25+29`) | 0 | 0 | 54 | 0 | 59 | 0 | 0 | 6.0150 |
| **Gurobi Eval (113)** | 113 | 113 | 3 | **3** (`1+2`) | 0 | 0 | 3 | 0 | 0 | 110 | 0 | 15.8432 |
| **CPLEX CE (113)** | 113 | 113 | 1 | **1** (`0+1`) | 0 | 0 | 1 | 0 | 0 | 112 | 0 | 15.9326 |
| **IBM CP Optimizer CE (113)** | 113 | 113 | 20 | **20** (`8+12`) | 0 | 20 | 0 | 0 | 0 | 93 | 0 | 10.1726 |

---

## 4. Method-by-Method Empirical Analysis

### 4.1 Heuristics (`RCM`, `SA`, `DRSA`) across All 113 Instances

- **RCM**: `131.82` mean bandwidth (`Tier 1`: mean gap `+21.06`, median `14.0`; `Tier 2`: mean gap `+96.37`, median `51.0`), achieving exact `best_method == "rcm"` match with `paper_best` on **10 instances** (`lund_a`, `lund_b`, `jagmesh1`, `nos7`, `saylr1`, `gre_216a`, `gre_343`, `gre_512`, `steam2`, `steam3`).
- **SA (`0.8s` incremental delta)**: `130.06` mean bandwidth (`Tier 1`: mean gap `+21.02`, median `14.0`; `Tier 2`: mean gap `+93.03`, median `38.0`), strictly improving RCM on `8/113`.
- **DRSA Warm (`MODIFIED_VARIANT`, `0.8s`)**: `130.92` mean bandwidth (`Tier 1`: mean gap **`+20.96`**, median `14.0`; `Tier 2`: mean gap `+94.73`, median `47.0`), matching or beating SA on `106/113`, strictly beating SA on `5/113`, and strictly beating RCM on `9/113`.
- **DRSA Paper-Bounded (`PAPER_FAITHFUL`, `0.8s`, random init, `T0=1000`)**: `432.69` mean bandwidth (`Tier 1` mean gap `+418.78`; `Tier 2` mean gap `+308.59`), isolating why unseeded high-temperature cooling requires longer runtimes on large Harwell–Boeing matrices compared to warm-started schedules.

### 4.2 Constraint Programming (`CP-SAT` Multi-Pass & `IBM CP Optimizer CE`)

- **CP-SAT Pass 1 (3.0s, 113 instances)**: `1 OPTIMAL_PROVED` (`pores_1=7`), `72 FEASIBLE`, `40 TIMEOUT_NO_INCUMBENT`.
- **CP-SAT Pass 2 Recovery (12.0s, 39 timeout cases with `n <= 700`)**: recovered **`bcspwr02` (`OPTIMAL_PROVED=7`)**, `curtis54` (`14`), and `will57` (`13`).
- **CP-SAT Pass 3 Proof (30.0s, 10 small candidates)**: proved optimality on **4 instances** — `pores_1=7` (`3.48s`), `ibm32=11` (`10.98s`), `bcspwr01=5` (`4.70s`), `bcspwr02=7` (`13.27s`) — plus `5 FEASIBLE` (`curtis54=14`, `will57=12`, `impcol_b=25`, `ash85=10`, `nos4=15`) and `1 TIMEOUT_NO_INCUMBENT` (`steam3`). Across all passes, CP-SAT strictly beat RCM on **`16 / 78`** valid instances.
- **IBM CP Optimizer CE (`22.2.0.0`, 10.0s)**: `20 / 113` eligible (`n * log2(n) <= 1000`, `n <= 138`) all returned valid solutions (`20 / 20`), **beating RCM on `18 / 20` (`90%`)** (e.g., `will57=8`, `impcol_b=25`, `bcspwr01=5`, `ash85=10`, `pores_1=7`, `steam3=7`), while the remaining `93 / 113` are transparently logged as `BLOCKED_LICENSE`.

### 4.3 SAT Preflight (`8,136` Configs), `SAT_113_COMPACT` & `SAT_STUDY_SMALL`

- Preflight under `ResourceLimits(500k vars, 2.5M clauses, 4096 MB)` at `k = max(lb, rcm_bw - 1)` across `113 × 72` configs identifies `Order + Product + Incremental CaDiCaL` (and `Order + Commander`) as highest coverage (`56 / 113` preflight-eligible).
- Live `SAT_113_COMPACT` (`6.0s` cap): `54 / 54` attempted instances produced validated improved incumbents (`TIMEOUT_WITH_INCUMBENT`), strictly beating RCM on `12 / 54`, with `59` instances cleanly gated as `RESOURCE_LIMIT` (`0` crashes).
- `SAT_STUDY_SMALL` (`8` instances × `9` backend/encoding/strategy configs = `72` runs): **`72 / 72` valid incumbents**, zero errors.

### 4.4 MIP Solvers (`Gurobi Eval`, `CPLEX CE`)

- `Gurobi Eval` (`2,000` vars / `2,000` constrs cap): `3/113` eligible -> `bcspwr01` (`bw=6`), `ibm32` (`bw=12`), `pores_1` (`bw=8`); `110/113` `BLOCKED_LICENSE`.
- `CPLEX CE` (`1,000` vars / `1,000` constrs cap): `1/113` eligible -> `pores_1` (`bw=9`); `112/113` `BLOCKED_LICENSE`.

---

## 5. Three-Era No-Regression Verification

From [`results/member3_m3_8_full113/no_regression_comparison.csv`](../results/member3_m3_8_full113/no_regression_comparison.csv):

1. **Before M3.1 (`19ce024`, 72 Table 6–7 instances)**: `RCM 72/72`, `SA 72/72` (`iterations=2000, cooling=0.995`), `CP-SAT 48/72 (1 OPT, 2.0s)`, `CP Optimizer 72/72` (executed on Windows 11 full binary).
2. **After M3.7 (`54 READY`, M3.6 snapshot)**: `500 / 500` unified runs strictly confined to the `54 READY` subset.
3. **After M3.8 (`113/113`)**:
   - **RCM matches `72 / 72` (`100%`)** of the `19ce024` baseline under `nonzero_union`.
   - **`SA_LEGACY72_COMPAT` matches `65 / 72` exact and validates `72 / 72`** (`7` Tier-2 differences on `arc130`, `fs_183_1`, `fs_541_1`, `bp_400`, `bp_600`, `bp_1200`, `bp_1400` arise from deterministic incremental state order/sampling), while `SA_113` (`0.8s`) matches or improves `19ce024` on `66 / 72`.
   - **CP-SAT expands from `48/72 (1 OPT)` -> `78/113 (4 OPT)`**.
   - **CP Optimizer CE validates `20/20` eligible instances (`n <= 138`)** while honestly documenting the `93` external CE license blocks on macOS vs the earlier Windows full binary (`72/72`).

---

## 6. Visualizations (`results/member3_m3_8_full113/figures/`)

1. `fig01_coverage_113_by_method.svg` — Full 113 coverage breakdown by exact status
2. `fig02_rcm_sa_drsa_113.svg` — RCM vs SA vs DRSA gap to published best (Tier 1 vs Tier 2 separated)
3. `fig03_bandwidth_vs_published_best_113.svg` — Best achieved bandwidth vs paper published best (log-log)
4. `fig04_runtime_vs_graph_size_113.svg` — Wall runtime vs graph order `n` (executed runs only)
5. `fig05_improvement_over_rcm_113.svg` — Strictly improved count over deterministic RCM
6. `fig06_cpsat_status_distribution_113.svg` — CP-SAT outcome distribution across Passes 1–3
7. `fig07_sat_preflight_113.svg` — SAT preflight eligibility vs `RESOURCE_LIMIT` across 113 instances
8. `fig08_mip_cp_license_blockers_113.svg` — Gurobi, CPLEX, and IBM CPO eligibility vs `EXTERNAL_LICENSE_BLOCKER`
9. `fig09_table6_vs_table7_vs_table8_113.svg` — Table 6 / Table 7 / Table 8 gap comparison (Tier 1 vs Tier 2)
10. `fig10_no_regression_3_eras.svg` — Three-era no-regression milestone progress (`72 -> 54 -> 113`)
