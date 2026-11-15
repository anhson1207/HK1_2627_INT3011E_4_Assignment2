# Member 3 Phase M3.2 SAT Pilot Benchmark Report

- **Git commit:** `2bc4441`
- **Total runs:** `80` (`READY`-only Harwell-Boeing Table 6 instances)
- **Status counts:** `{'TIMEOUT': 79, 'RESOURCE_LIMIT': 1}`
- **All validations passed:** `True`

## Study A – MiniSat vs CaDiCaL vs Glucose (`order_sequential`, `incremental`, `sym=True`)

| Instance | Backend | Status | BW | Final LB | SAT Calls | Time (s) | Peak Mem (MiB) |
|---|---|---|---:|---:|---:|---:|---:|
| bcspwr01 | minisat | TIMEOUT | 6 | 4 | 2 | 10.010 | 26.921875 |
| bcspwr01 | cadical | TIMEOUT | 6 | 4 | 2 | 10.007 | 32.546875 |
| bcspwr01 | glucose | TIMEOUT | 5 | 4 | 3 | 10.005 | 29.203125 |
| bcspwr02 | minisat | TIMEOUT | 8 | 6 | 5 | 10.005 | 34.0625 |
| bcspwr02 | cadical | TIMEOUT | 10 | 6 | 3 | 10.015 | 40.953125 |
| bcspwr02 | glucose | TIMEOUT | 9 | 6 | 4 | 10.006 | 36.015625 |
| bcsstk01 | minisat | TIMEOUT | 25 | 12 | 2 | 10.010 | 50.3125 |
| bcsstk01 | cadical | TIMEOUT | 25 | 12 | 2 | 10.009 | 36.890625 |
| bcsstk01 | glucose | TIMEOUT | 26 | 12 | 1 | 10.008 | 37.59375 |
| ash85 | minisat | TIMEOUT | 10 | 7 | 1 | 10.030 | 41.453125 |
| ash85 | cadical | TIMEOUT | 10 | 7 | 1 | 10.006 | 56.125 |
| ash85 | glucose | TIMEOUT | 10 | 7 | 1 | 10.030 | 44.65625 |

## Study B – Product AMO vs Existing AMOs (`minisat`, `incremental`, `sym=True`)

| Instance | Encoding | AMO | Status | BW | Est Vars | Est Clauses | Actual Vars | Actual Clauses | Time (s) |
|---|---|---|---|---:|---:|---:|---:|---:|---:|
| bcspwr01 | order | sequential | TIMEOUT | 6 | 4485 | 13188 | 4485 | 16132 | 10.010 |
| bcspwr02 | order | sequential | TIMEOUT | 8 | 7105 | 20664 | 7105 | 38836 | 10.005 |
| bcsstk01 | order | sequential | TIMEOUT | 25 | 6816 | 23137 | 6816 | 30881 | 10.010 |
| bcspwr01 | pairwise | product | TIMEOUT | 7 | 2535 | 54582 | 2535 | 54582 | 10.010 |
| bcspwr01 | pairwise | pairwise | TIMEOUT | 6 | 1521 | 103488 | 1521 | 106432 | 10.094 |
| bcspwr01 | pairwise | sequential | TIMEOUT | 7 | 4485 | 54504 | 4485 | 54504 | 10.028 |
| bcspwr01 | pairwise | binary | TIMEOUT | 6 | 1989 | 63942 | 1989 | 66886 | 10.007 |
| bcspwr01 | pairwise | commander | TIMEOUT | 5 | 3081 | 54504 | 3081 | 60484 | 10.005 |
| bcspwr02 | pairwise | product | TIMEOUT | 9 | 3773 | 92381 | 3773 | 105833 | 10.008 |
| bcspwr02 | pairwise | pairwise | TIMEOUT | 9 | 2401 | 193909 | 2401 | 207361 | 10.012 |
| bcspwr02 | pairwise | sequential | TIMEOUT | 9 | 7105 | 92675 | 7105 | 106127 | 10.007 |
| bcspwr02 | pairwise | binary | TIMEOUT | 10 | 2989 | 107473 | 2989 | 116323 | 10.108 |
| bcspwr02 | pairwise | commander | TIMEOUT | 8 | 4851 | 92675 | 4851 | 110847 | 10.035 |
| bcsstk01 | pairwise | product | TIMEOUT | 21 | 3648 | 94632 | 3648 | 136872 | 10.174 |
| bcsstk01 | pairwise | pairwise | TIMEOUT | 23 | 2304 | 189672 | 2304 | 213960 | 10.011 |
| bcsstk01 | pairwise | sequential | TIMEOUT | 25 | 6816 | 94824 | 6816 | 102568 | 10.008 |
| bcsstk01 | pairwise | binary | TIMEOUT | 25 | 2880 | 109032 | 2880 | 116776 | 10.069 |
| bcsstk01 | pairwise | commander | TIMEOUT | 27 | 4608 | 94824 | 4608 | 94824 | 10.098 |
| ash85 | pairwise | product | TIMEOUT | 10 | 10455 | 1291097 | N/A | N/A | 10.012 |
| ash85 | pairwise | pairwise | TIMEOUT | 10 | 7225 | 1855327 | N/A | N/A | 10.017 |
| ash85 | pairwise | sequential | TIMEOUT | 10 | 21505 | 1291097 | N/A | N/A | 10.042 |
| ash85 | pairwise | binary | TIMEOUT | 10 | 8415 | 1349577 | N/A | N/A | 10.124 |
| ash85 | pairwise | commander | TIMEOUT | 10 | 14875 | 1291437 | N/A | N/A | 10.043 |
| bcspwr01 | order | product | TIMEOUT | 5 | 3510 | 13227 | 3510 | 19207 | 11.305 |
| bcspwr01 | order | pairwise | TIMEOUT | 6 | 3003 | 37680 | 3003 | 40624 | 10.133 |
| bcspwr01 | order | binary | TIMEOUT | 6 | 3237 | 17907 | 3237 | 20851 | 10.038 |
| bcspwr01 | order | commander | TIMEOUT | 6 | 3783 | 13188 | 3783 | 16132 | 10.406 |
| bcspwr02 | order | product | TIMEOUT | 8 | 5439 | 20517 | 5439 | 38689 | 10.026 |
| bcspwr02 | order | pairwise | TIMEOUT | 8 | 4753 | 71281 | 4753 | 89453 | 10.266 |
| bcspwr02 | order | binary | TIMEOUT | 9 | 5047 | 28063 | 5047 | 41515 | 10.010 |
| bcspwr02 | order | commander | TIMEOUT | 8 | 5978 | 20664 | 5978 | 38836 | 10.023 |
| bcsstk01 | order | product | TIMEOUT | 23 | 5232 | 23041 | 5232 | 47329 | 10.022 |
| bcsstk01 | order | pairwise | TIMEOUT | 25 | 4560 | 70561 | 4560 | 78305 | 10.037 |
| bcsstk01 | order | binary | TIMEOUT | 21 | 4848 | 30241 | 4848 | 72481 | 10.167 |
| bcsstk01 | order | commander | TIMEOUT | 24 | 5712 | 23137 | 5712 | 38977 | 10.072 |
| bcsstk04 | pairwise | product | RESOURCE_LIMIT | 47 | 23496 | 12952818 | N/A | N/A | 4.478 |

## Study C – Ladder vs Sequential Equivalence (`minisat`, `sym=True`)

| Instance | Encoding | Strategy | Ladder (V/C) | Sequential (V/C) | Exact CNF Match | Status (L/S) | BW (L/S) |
|---|---|---|---|---|---|---|---|
| bcspwr01 | pairwise | incremental | 4485/54504 | 4485/54504 | True | TIMEOUT/TIMEOUT | 7/7 |
| bcspwr01 | pairwise | repeated | 4485/63612 | 4485/63612 | True | TIMEOUT/TIMEOUT | 5/5 |
| bcspwr01 | order | incremental | 4485/16132 | 4485/16132 | True | TIMEOUT/TIMEOUT | 6/6 |
| bcspwr01 | order | repeated | 4485/13464 | 4485/13372 | False | TIMEOUT/TIMEOUT | 5/6 |
| bcspwr02 | pairwise | incremental | 7105/106127 | 7105/106127 | True | TIMEOUT/TIMEOUT | 9/9 |
| bcspwr02 | pairwise | repeated | 7105/101525 | 7105/101525 | True | TIMEOUT/TIMEOUT | 10/11 |
| bcspwr02 | order | incremental | 7105/38836 | 7105/38836 | True | TIMEOUT/TIMEOUT | 8/8 |
| bcspwr02 | order | repeated | 7105/21018 | 7105/21136 | False | TIMEOUT/TIMEOUT | 10/9 |
| bcsstk01 | pairwise | incremental | 6816/127912 | 6816/102568 | False | TIMEOUT/TIMEOUT | 22/25 |
| bcsstk01 | pairwise | repeated | 6816/102568 | 6816/102568 | True | TIMEOUT/TIMEOUT | 26/26 |
| bcsstk01 | order | incremental | 6816/30881 | 6816/30881 | True | TIMEOUT/TIMEOUT | 25/25 |
| bcsstk01 | order | repeated | 6816/23489 | 6816/23489 | True | TIMEOUT/TIMEOUT | 26/26 |

## Study D – Repeated vs Incremental on MiniSat (`product`, `sym=True`)

| Instance | Encoding | Strategy | Search Mode | Status | BW | LB/UB | Calls | Creations | Reused | Trace | Time (s) |
|---|---|---|---|---|---:|---|---:|---:|:---:|---|---:|
| bcspwr01 | pairwise | incremental | linear | TIMEOUT | 7 | 4/7 | 1 | 1 | True | `7:SAT;6:UNKNOWN` | 10.010 |
| bcspwr02 | pairwise | incremental | linear | TIMEOUT | 9 | 6/9 | 4 | 1 | True | `12:SAT;11:SAT;10:SAT;9:SAT;8:UNKNOWN` | 10.008 |
| bcsstk01 | pairwise | incremental | linear | TIMEOUT | 21 | 12/21 | 6 | 1 | True | `26:SAT;25:SAT;24:SAT;23:SAT;22:SAT;21:SAT` | 10.174 |
| ash85 | pairwise | incremental | linear | TIMEOUT | 10 | 7/10 | 0 | None | None | `None` | 10.012 |
| bcspwr01 | order | incremental | linear | TIMEOUT | 5 | 4/5 | 3 | 1 | True | `7:SAT;6:SAT;5:SAT;4:UNKNOWN` | 11.305 |
| bcspwr02 | order | incremental | linear | TIMEOUT | 8 | 6/8 | 5 | 1 | True | `12:SAT;11:SAT;10:SAT;9:SAT;8:SAT;7:UNKNOWN` | 10.026 |
| bcsstk01 | order | incremental | linear | TIMEOUT | 23 | 12/23 | 4 | 1 | True | `26:SAT;25:SAT;24:SAT;23:SAT;22:UNKNOWN` | 10.022 |
| bcspwr01 | order | repeated | linear | TIMEOUT | 5 | 4/5 | 3 | 3 | False | `7:SAT;6:SAT;5:SAT;4:UNKNOWN` | 10.023 |
| bcspwr01 | order | repeated | binary | TIMEOUT | 5 | 4/5 | 1 | 1 | False | `5:SAT;4:UNKNOWN` | 10.018 |
| bcspwr01 | pairwise | repeated | linear | TIMEOUT | 6 | 4/6 | 2 | 2 | False | `7:SAT;6:SAT;5:UNKNOWN` | 10.008 |
| bcspwr01 | pairwise | repeated | binary | TIMEOUT | 5 | 4/5 | 1 | 1 | False | `5:SAT` | 10.026 |
| bcspwr02 | order | repeated | linear | TIMEOUT | 9 | 6/9 | 4 | 4 | False | `12:SAT;11:SAT;10:SAT;9:SAT;8:UNKNOWN` | 10.006 |
| bcspwr02 | order | repeated | binary | TIMEOUT | 9 | 6/9 | 1 | 1 | False | `9:SAT;7:UNKNOWN` | 10.010 |
| bcspwr02 | pairwise | repeated | linear | TIMEOUT | 11 | 6/11 | 2 | 2 | False | `12:SAT;11:SAT;10:UNKNOWN` | 10.009 |
| bcspwr02 | pairwise | repeated | binary | TIMEOUT | 13 | 6/13 | 1 | 1 | False | `9:UNKNOWN` | 10.007 |
| bcsstk01 | order | repeated | linear | TIMEOUT | 25 | 12/25 | 2 | 2 | False | `26:SAT;25:SAT;24:UNKNOWN` | 10.089 |
| bcsstk01 | order | repeated | binary | TIMEOUT | 27 | 12/27 | 1 | 1 | False | `19:UNKNOWN` | 10.010 |
| bcsstk01 | pairwise | repeated | linear | TIMEOUT | 25 | 12/25 | 2 | 2 | False | `26:SAT;25:SAT;24:UNKNOWN` | 10.006 |
| bcsstk01 | pairwise | repeated | binary | TIMEOUT | 27 | 12/27 | 1 | 1 | False | `19:UNKNOWN` | 10.009 |
| ash85 | order | repeated | linear | TIMEOUT | 10 | 7/10 | 1 | 1 | False | `9:UNKNOWN` | 10.011 |
| ash85 | order | repeated | binary | TIMEOUT | 10 | 7/10 | 1 | 1 | False | `8:UNKNOWN` | 10.035 |
| ash85 | order | incremental | linear | TIMEOUT | 10 | 7/10 | 1 | 1 | True | `9:UNKNOWN` | 10.005 |
| ash85 | pairwise | repeated | linear | TIMEOUT | 10 | 7/10 | 0 | None | None | `None` | 10.016 |
| ash85 | pairwise | repeated | binary | TIMEOUT | 10 | 7/10 | 0 | None | None | `None` | 10.055 |
