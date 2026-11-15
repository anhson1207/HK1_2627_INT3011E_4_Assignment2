# Member 2: SAT integration, MIP, and sample experiment

## Reproducible basis

Working tree: `dev/member-2`, HEAD `8d5c09ed9633245659225a583c83bc8fd469933d`.
The SAT core files were copied into this same working tree from
`origin/dev/leader` commit `414606c50c352888e4ed9f0a04bef257c7e9d099`
(no worktree switch, merge, commit, or push).
Member 2's pre-existing MIP and AMO files were retained. Python imports `bmp`
from this checkout's `src/bmp` through the local editable environment and
pytest's `pythonpath=src` setting.

Runtime: Python 3.13 on Windows; `python-sat==1.9.dev21`, `gurobipy==13.0.3`,
`cplex==22.2.0.1`, `cnsplots==0.8.0`. The 5 repository sample edge lists are
the entire dataset used here. Config: `configs/member2.toml`; 3 repetitions per
configuration and graph, 5-second limit, seed 2026 recorded but not applied
because no run samples or shuffles input. Each method uses the same five graphs.
SAT strategy code checks the deadline between SAT calls; it does not impose a
hard limit on an individual SAT call. Total times are Python wall times around
each call. No warm-up or machine-isolation control was used.

## Implementation

The Binary AMO encoder assigns each literal a distinct code on
`ceil(log2(n))` auxiliary bits. The Commander AMO encoder groups at most three
literals, applies pairwise AMO inside each group, implies a group commander
from each literal, then recursively constrains the commanders. Both support
negative literals and preserve the shared variable allocator. They are
registered under `binary` and `commander` in the leader's AMO registry, beside
`pairwise` and `sequential`. Product, ladder, cardinality network, and
totalizer are not integrated in this branch.

Gurobi and CPLEX use the same assignment MIP: binary `x[v,p]`, one position per
vertex, one vertex per position, integer bandwidth `B`, and for every edge
`(u,v)`, `B >= label(u)-label(v)` and `B >= label(v)-label(u)`, where
`label(v) = sum_p p*x[v,p]`. The optional strengthening constrains the first
vertex to the lower half of positions. Reversal sends each position `p` to
`n+1-p` without changing any edge span, so every optimum has a representative
that meets this constraint. It can be enabled with `symmetry_breaking=True`.

## Correctness checks

On `cycle_c4`, Pairwise/Order crossed with Repeated/Incremental all gave
K=1 UNSAT and K=2 SAT. Every K=2 model decoded to a valid permutation with
actual bandwidth 2. The direct incremental checks kept one Glucose instance
while strengthening K=2 to K=1. The strategy solvers themselves returned
OPTIMAL bandwidth 2. An additional test gives the incremental strategy a weaker
valid lower bound, forcing two SAT calls at K=2 and K=1; it verifies that the
backend factory is called once for both calls. Machine-readable details,
including permutations, are in
`results/member2/cycle_check.json`.

All four registered AMOs were run in the Pairwise position model. The five
sample optima matched brute-force for SAT, Gurobi, and CPLEX:

| Sample | Optimal bandwidth |
| --- | ---: |
| path_p5 | 1 |
| complete_k5 | 4 |
| star_k1_4 | 2 |
| cycle_c4 | 2 |
| edgeless_5 | 0 |

For path_p5, complete_k5, and edgeless_5, the leader's SAT strategy returns via
a certified bound or edgeless fast path (`sat_calls=0`); these are valid
strategy results but do not measure a Glucose solve. The SAT-versus-MIP and AMO
figures therefore include only star_k1_4 and cycle_c4, where SAT was called.

## Measured results

The benchmark produced 225 rows and 75 median groups. All 225 rows were
OPTIMAL and validated; TIMEOUT, UNAVAILABLE, and ERROR counts were each zero.
These small cases support correctness checks, not a broad performance claim.
Selected median total times (milliseconds, 3 repetitions):

| Case | Pairwise Repeated Glucose | Gurobi | CPLEX |
| --- | ---: | ---: | ---: |
| star_k1_4 | 0.403 | 15.240 | 5.271 |
| cycle_c4 | 0.288 | 15.468 | 10.036 |

For cycle_c4, Pairwise AMO variants under repeated Glucose measured:
Pairwise 0.115 ms, Sequential 0.150 ms, Binary 0.165 ms, Commander 0.178 ms.
These are short Python calls; the ordering may change across runs or machines.

The MIP symmetry constraint preserved all five optima for both solvers,
matching brute-force in 20 baseline/strengthening checks. Its runtime effect
was mixed: on `complete_k5`, Gurobi changed from 15.830 to 15.645 ms while
CPLEX changed from 26.428 to 27.501 ms (median, 3 repetitions). No speedup is
claimed. All individual measurements and other medians are in `runs.csv`,
`runs.json`, and `summary.json`.

The figures `sat_vs_mip.svg` and `amo_comparison.svg` were generated from
`runs.csv` using `cnsplots.figure`, `cnsplots.barplot`, and `cnsplots.savefig`.
MuPDF's optional `mutool` was unavailable, so cnsplots saved standard SVGs.

Final verification in the same `.venv`: `pytest -ra` reported 59 passed,
0 skipped, 0 failed, plus 2,234 passing subtests. The CI-style top-level
`unittest discover -s tests -q` reported 35 tests, all passing. Pytest also
collects the leader's nested SAT test directories.

## Reproduction on Windows PowerShell

```powershell
.venv\Scripts\python.exe -m pytest -ra
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe -X utf8 -m bmp.experiments.member2_cycle
.venv\Scripts\python.exe -X utf8 -m bmp.experiments.member2 configs/member2.toml
.venv\Scripts\python.exe -X utf8 -m bmp.experiments.member2_plots results/member2/runs.csv
```

For a fresh environment, install `python -m pip install -e .[gurobi,cplex,plots] pytest`.
Gurobi and CPLEX also require working licenses. The generated CSV/JSON/SVG
files are retained under `results/member2/`; rerunning the benchmark overwrites
those filenames with new measurements.
