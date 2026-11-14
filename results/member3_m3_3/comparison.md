# Member 3 Phase M3.3 – CP-SAT vs IBM CP Optimizer Pilot Comparison

- **Git commit:** `d31113a`
- **OR-Tools CP-SAT:** `9.15.6755`
- **IBM CP Optimizer:** `docplex 2.32.264` + engine `/Users/nguyenanhson/BMP/.venv/bin/cpoptimizer`
- **Preflight verified READY total:** `54` (`PILOT_READY`: `19`)
- **Status counts by solver:** `{'cp-sat': {'OPTIMAL': 8, 'FEASIBLE': 8, 'TIMEOUT': 5}, 'cp-optimizer': {'FEASIBLE': 13, 'UNAVAILABLE': 2}}`
- **All returned solutions validated:** `True`

## Experiment C – CP-SAT vs IBM CP Optimizer (`sym=True`, `threads=1`, `seed=17`, `timeout=20s`)

| Instance | n | m | Pub LB/Best | CP-SAT Status | CP-SAT BW (LB) | CP-SAT Time (s) | CPO Status | CPO BW (LB) | CPO Time (s) |
|---|---:|---:|:---:|---|---:|---:|---|---:|---:|
| bcspwr01 | 39 | 46 | 5/5 | OPTIMAL | 5 (5) | 13.547 | FEASIBLE | 5 (4) | 21.758 |
| bcspwr02 | 49 | 59 | 7/7 | OPTIMAL | 7 (7) | 13.948 | FEASIBLE | 7 (6) | 20.330 |
| bcsstk01 | 48 | 176 | 16/16 | FEASIBLE | 24 (12) | 20.224 | FEASIBLE | 18 (12) | 20.171 |
| ash85 | 85 | 219 | 9/9 | TIMEOUT | None (7) | 15.855 | FEASIBLE | 10 (7) | 28.779 |
| nos4 | 100 | 247 | 10/10 | TIMEOUT | None (8) | 16.751 | FEASIBLE | 10 (8) | 27.698 |
| dwt_209 | 209 | 767 | 21/23 | TIMEOUT | None (18) | 21.421 | UNAVAILABLE | None (18) | 7.066 |

## Symmetry & Bound Ablation Summary

| Instance | Solver | Sym | Use LB | Hint | Status | BW (LB) | Wall Time (s) |
|---|---|---:|---:|---|---|---:|---:|
| bcspwr01 | cp-sat | True | True | rcm | OPTIMAL | 5 (5) | 13.547 |
| bcspwr01 | cp-sat | False | True | rcm | OPTIMAL | 5 (5) | 8.846 |
| bcspwr02 | cp-sat | True | True | rcm | OPTIMAL | 7 (7) | 13.948 |
| bcspwr02 | cp-sat | False | True | rcm | FEASIBLE | 7 (6) | 20.284 |
| bcsstk01 | cp-sat | True | True | rcm | FEASIBLE | 24 (12) | 20.224 |
| bcsstk01 | cp-sat | False | True | rcm | FEASIBLE | 23 (12) | 20.489 |
| ash85 | cp-sat | True | True | rcm | TIMEOUT | None (7) | 15.855 |
| ash85 | cp-sat | False | True | rcm | TIMEOUT | None (7) | 18.587 |
| nos4 | cp-sat | True | True | rcm | TIMEOUT | None (8) | 16.751 |
| nos4 | cp-sat | False | True | rcm | FEASIBLE | 13 (8) | 22.365 |
| dwt_209 | cp-sat | True | True | rcm | TIMEOUT | None (18) | 21.421 |
| dwt_209 | cp-sat | False | True | rcm | TIMEOUT | None (18) | 13.725 |
| bcspwr01 | cp-sat | True | True | none | OPTIMAL | 5 (5) | 4.527 |
| bcspwr01 | cp-sat | True | False | rcm | OPTIMAL | 5 (5) | 4.763 |
| bcspwr01 | cp-sat | True | True | identity | OPTIMAL | 5 (5) | 5.319 |
| bcspwr02 | cp-sat | True | True | none | FEASIBLE | 9 (6) | 21.089 |
| bcspwr02 | cp-sat | True | False | rcm | OPTIMAL | 7 (7) | 16.635 |
| bcspwr02 | cp-sat | True | True | identity | OPTIMAL | 7 (7) | 12.897 |
| bcsstk01 | cp-sat | True | True | none | FEASIBLE | 19 (12) | 34.667 |
| bcsstk01 | cp-sat | True | False | rcm | FEASIBLE | 23 (0) | 20.064 |
| bcsstk01 | cp-sat | True | True | identity | FEASIBLE | 23 (12) | 23.911 |
| bcspwr01 | cp-optimizer | True | True | rcm | FEASIBLE | 5 (4) | 21.758 |
| bcspwr01 | cp-optimizer | False | True | rcm | FEASIBLE | 5 (4) | 20.209 |
| bcspwr02 | cp-optimizer | True | True | rcm | FEASIBLE | 7 (6) | 20.330 |
| bcspwr02 | cp-optimizer | False | True | rcm | FEASIBLE | 7 (6) | 20.240 |
| bcsstk01 | cp-optimizer | True | True | rcm | FEASIBLE | 18 (12) | 20.171 |
| bcsstk01 | cp-optimizer | False | True | rcm | FEASIBLE | 17 (12) | 21.398 |
| ash85 | cp-optimizer | True | True | rcm | FEASIBLE | 10 (7) | 28.779 |
| ash85 | cp-optimizer | False | True | rcm | FEASIBLE | 10 (7) | 20.282 |
| nos4 | cp-optimizer | True | True | rcm | FEASIBLE | 10 (8) | 27.698 |
| nos4 | cp-optimizer | False | True | rcm | FEASIBLE | 10 (8) | 20.639 |
| dwt_209 | cp-optimizer | True | True | rcm | UNAVAILABLE | None (18) | 7.066 |
| dwt_209 | cp-optimizer | False | True | rcm | UNAVAILABLE | None (18) | 0.457 |
| bcspwr01 | cp-optimizer | True | True | none | FEASIBLE | 5 (4) | 24.548 |
| bcspwr02 | cp-optimizer | True | True | none | FEASIBLE | 7 (7) | 20.167 |
| bcsstk01 | cp-optimizer | True | True | none | FEASIBLE | 18 (12) | 20.213 |

## Experiment D – Reference Comparison with Leader/M2 SAT & MIP (Different Time Budgets Noted)

| Instance | Reference Run | Status | BW | LB | Wall Time (s) |
|---|---|---|---:|---:|---:|
| bcspwr01 | M2.3 cadical (order, 30s) | TIMEOUT | 5 | 4 | 30.006169 |
| bcsstk01 | M2.3 cadical (order, 30s) | TIMEOUT | 20 | 12 | 30.006976 |
| bcspwr02 | M2.3 cadical (order, 30s) | TIMEOUT | 8 | 6 | 30.007461 |
| ash85 | M2.3 cadical (order, 30s) | TIMEOUT | 10 | 7 | 30.010279 |
| nos4 | M2.3 cadical (order, 30s) | TIMEOUT | 12 | 8 | 30.010674 |
| dwt_209 | M2.3 cadical (order, 30s) | TIMEOUT | 42 | 18 | 30.014892 |
| bcspwr01 | M2.3 cadical (pairwise, 30s) | TIMEOUT | 5 | 4 | 30.007418 |
| bcsstk01 | M2.3 cadical (pairwise, 30s) | TIMEOUT | 26 | 12 | 30.013279 |
| bcspwr02 | M2.3 cadical (pairwise, 30s) | TIMEOUT | 8 | 6 | 30.008356 |
| ash85 | M2.3 cadical (pairwise, 30s) | TIMEOUT | 10 | 7 | 30.743716 |
| bcspwr01 | M2.3 glucose (order, 30s) | TIMEOUT | 5 | 4 | 30.009685 |
| bcsstk01 | M2.3 glucose (order, 30s) | TIMEOUT | 22 | 12 | 30.009991 |
| bcspwr02 | M2.3 glucose (order, 30s) | TIMEOUT | 8 | 6 | 30.100918 |
| ash85 | M2.3 glucose (order, 30s) | TIMEOUT | 10 | 7 | 30.010861 |
| bcspwr01 | M2.3 gurobi (MIP, 30s) | OPTIMAL | 5 | 5 | 13.258293 |
| bcsstk01 | M2.3 gurobi (MIP, 30s) | UNAVAILABLE | None | None | 3.1e-05 |
| bcspwr02 | M2.3 gurobi (MIP, 30s) | UNAVAILABLE | None | None | 1.4e-05 |
| ash85 | M2.3 gurobi (MIP, 30s) | UNAVAILABLE | None | None | 1.2e-05 |
| bcspwr01 | M2.3 cplex (MIP, 30s) | UNAVAILABLE | None | None | 0.000118 |
| bcsstk01 | M2.3 cplex (MIP, 30s) | UNAVAILABLE | None | None | 1.4e-05 |
| bcspwr02 | M2.3 cplex (MIP, 30s) | UNAVAILABLE | None | None | 1e-05 |
| ash85 | M2.3 cplex (MIP, 30s) | UNAVAILABLE | None | None | 1.1e-05 |
| ash85 | M3.2 minisat best (order_sequential, 10s) | TIMEOUT | 10 | 7 | 10.029539 |
| bcspwr01 | M3.2 minisat best (pairwise_commander, 10s) | TIMEOUT | 5 | 4 | 10.005202 |
| bcspwr02 | M3.2 minisat best (order_sequential, 10s) | TIMEOUT | 8 | 6 | 10.004842 |
| bcsstk01 | M3.2 minisat best (pairwise_product, 10s) | TIMEOUT | 21 | 12 | 10.174157 |
