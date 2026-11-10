# Member 2: Harwell–Boeing Tables 6–7

The manifest in `data/hb_table6_7/manifest.csv` transcribes all 31 rows of
Table 6 and all 41 rows of Table 7 through `gre_343`. `LB`, `Best`, and `DRSA`
are reference values only; they are never fed to a solver or used to make a
graph. The source PDF is `2 - Bandwidth Minimization Problem -  BMP.pdf`.
Before downloading, the working tree and `origin/dev/leader` and
`origin/dev/member-3` were checked for HB graph data; only the five sample
graphs were available.

`data/hb_table6_7/sources.csv` records the NIST Matrix Market URL, matrix name,
compressed-file SHA-256, entry count, graph edge count, and size check for each
matrix. `raw/` holds downloaded `.mtx.gz` files. The conversion keeps every
matrix row as a vertex, ignores diagonal entries and numeric zeros, and makes
one undirected edge from every nonzero off-diagonal structural entry. Reverse
and duplicate entries collapse into one edge. Components and isolated vertices
remain in the graph. The graph files are `graphs/*.edgelist`.

Run from the repository root in PowerShell:

```powershell
# Recreate the source download and verify all 72 graph sizes.
python scripts/fetch_hb.py

# Pilot: all Member 2 configurations on ibm32.
.\.venv\Scripts\python.exe -m bmp.experiments.member2_hb configs/member2_hb_table6_7.toml --instance ibm32

# Full run. Previously written rows are skipped.
.\.venv\Scripts\python.exe -m bmp.experiments.member2_hb configs/member2_hb_table6_7.toml

# Resume after an interruption: repeat the same command.
.\.venv\Scripts\python.exe -m bmp.experiments.member2_hb configs/member2_hb_table6_7.toml

# Refresh the human-readable comparison while a run is still underway.
.\.venv\Scripts\python.exe -m bmp.experiments.member2_hb configs/member2_hb_table6_7.toml --report-only
```

The runner writes and flushes each row to `results/member2_hb_table6_7/runs.csv`
before starting the next. Each row has its own wall time, status, certified
bound, assignment, and independent assignment check. A subprocess enforces the
60-second total limit even when a SAT solve call cannot be interrupted. An
incumbent checkpoint preserves the latest valid SAT assignment found before a
hard timeout. `TIMEOUT` can therefore carry a valid bandwidth. `OPTIMAL` is
reserved for a proof from SAT or MIP. `RESOURCE_LIMIT` records a configured CNF
or MIP size cap, and `UNAVAILABLE` records a solver or license failure.

The comparison in `comparison.md` reports the best valid assignment observed
for each graph and the runtime of the single row that supplied it. Smaller
bandwidth is better. The paper's `Best` is a best-known solution and does not
by itself prove optimality.

Change `timeout_seconds`, `repetitions`, `max_sat_estimated_clauses`, or
`max_mip_variables` in the dedicated TOML config as needed. The SAT tests use
Pairwise/Order × Repeated/Incremental and compare AMO variants on the same
Pairwise position model with Repeated search. Gurobi and CPLEX each use the
existing baseline and reversal-symmetry configurations. The old 225-row sample
benchmark remains in `results/member2/`.
