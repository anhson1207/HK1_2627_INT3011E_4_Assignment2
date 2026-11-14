# Leader L7 audit and official benchmark attempt

Date: 10 November 2026 (Asia/Ho_Chi_Minh). Branch: `dev/leader`.

## Scope and acceptance

The SAT core, paper catalog, NIST acquisition, audited preprocessing, and a bounded official smoke run are implemented. The Leader work is **not yet COMPLETE**: 58 source matrices have an undirected conversion ambiguity, one paper row conflicts with the source dimension, and the bounded official runs have not proved any optimum. Member 3 should review the unresolved matrix conversion against the original experiment's graph construction or published permutations before these instances enter a performance comparison.

## Paper catalog

Source: J. Torres-Jimenez et al., *A dual representation simulated annealing algorithm for the bandwidth minimization problem on graphs*, Information Sciences 303 (2015), 33-49, DOI `10.1016/j.ins.2014.12.041`. The user-supplied PDF has SHA-256 `1f67dd962b13b2c026bb89f324906e8ec58464f9b201692d30fd456e209001de`; Table 6 is on PDF page 13, Table 7 on page 14, and Table 8 on page 15. Every row was parsed into `src/bmp/core/official_paper_results.csv` with its table, n, LB, Best, four method bandwidths, four published times, and reference. The PDF table captions say 33 small and 80 large, while the **actual rows** and paper prose are 31 small and 82 large: 31 + 41 + 41 = 113. The old catalog incorrectly put `dwt_234` in Table 6 and covered only 18 of the 82 large rows.

`published_best` is an unproved reference upper bound unless a corresponding permutation is validated on the exact graph. It is never used as a SAT incumbent.

## NIST acquisition and graph conversion

`scripts/acquire_benchmark.py` matches each paper name to exactly one entry in the [NIST Harwell-Boeing name index](https://math.nist.gov/MatrixMarket/matrices.html), tolerating archive underscore padding only for the name lookup. It downloads the matching Matrix Market `mtx.gz` source, keeps compressed raw bytes unchanged under ignored `data/benchmarks/raw/`, and writes URL, archive name, path, SHA-256, download status, and validation evidence to `data/benchmark_provenance.json`. This is a resumable acquisition script. No paper PDF or raw matrix is committed.

The shared Matrix Market parser (`inspect_matrix_market`) checks the coordinate header, field and symmetry type, declared dimensions and entry count, square shape, entry indices, duplicate directed coordinates, diagonal entries, and structural symmetry. It treats nonzero off-diagonal coordinates as a candidate undirected edge, removes diagonal entries, collapses mirrored coordinates, preserves all vertices and components, and maps source row IDs 1..n to graph IDs 0..n-1. For a declared symmetric, Hermitian, or skew-symmetric matrix, the triangular pattern represents both directions. For a general matrix, a READY result requires a mirrored nonzero pattern. An asymmetric pattern or duplicate coordinate is retained for audit but marked NEEDS_VERIFICATION; the paper does not specify whether union, intersection, or another rule was used for nonsymmetric inputs. The pipeline does not silently use that candidate graph for official SAT results.

The graph audit records n, m, component count, largest component size, density, diagonal removals, duplicates, and asymmetric pairs. It checks the 19 disconnected instances in the paper's Table 5 by largest-component size and flags unexpected disconnection. A vertex-count match alone is a structural check, not complete dataset validation.

Acquisition outcome: **113 downloaded, 54 READY, 58 NEEDS_VERIFICATION, 1 INVALID_DATA, 0 MISSING_DATA**. All 58 NEEDS_VERIFICATION matrices have asymmetric source patterns; two (`fs_680_1` and `fs_760_1`) also yield disconnected candidate graphs despite being absent from Table 5. `mbeause` is the invalid row: the NIST source is 496 x 496 with largest component 492, which agrees with Table 5's total/large-component figures (496/492), while Table 8 reports n=492. This discrepancy is preserved rather than changing the graph or paper row. All 19 Table 5 largest-component checks matched the candidate graphs.

## CNF and resource audit

For Pairwise Position, bandwidth clauses are exactly `m * (n-k) * (n-k-1)` for 0 <= k < n. The pairwise AMO fixed count is `n + 2*n*C(n,2)` before symmetry clauses. Sequential AMO uses `3*n-4` clauses and `n-1` auxiliaries per length-n AMO for n >= 3. Order fixed clauses include monotonicity, channeling, and occupancy AMO; its bandwidth term is `2*m*(n-k-1)`. The estimator now handles n=1 Pairwise exactly, rejects negative k, and exposes cumulative Order counts for the unit-step incremental schedule. Adaptive jumps receive a safe upper bound.

Small-graph tests compare the estimator to actual CNF for both encodings, both AMOs, multiple k, and symmetry on/off. The requested scale checks yield 623,750,000 bandwidth clauses and 748,500,500 total Pairwise/Pairwise clauses for n=500,m=2500,k=0; and 4,995,000,000 bandwidth clauses and 5,994,001,000 total clauses for n=1000,m=5000,k=0. Neither CNF is allocated. Per-threshold resource checks prevent later Repeated or Incremental steps from exceeding configured variable/clause limits. A skipped initial CNF reports estimated size only in metadata; `num_clauses` and `num_variables` remain null because no CNF was built.

PySAT's CaDiCaL 195 binding does not support interruptible limited solving. A bounded run therefore executes the whole SAT search in a POSIX forked worker. The parent terminates it at the wall-clock deadline. The child reports verified incumbents, certified lower bounds, SAT calls, and built CNF counts while it runs, so TIMEOUT retains the latest completed evidence. An optional process address-space cap uses `RLIMIT_AS`; this is an operating-system constraint, not a prediction from clauses. Peak RAM is left null because no reliable per-run peak measurement was collected. The default solver API guards formula size even when the caller omits limits; the CLI defaults to 500,000 variables and 2,500,000 clauses.

Repeated SAT creates a fresh CaDiCaL solver for each k. Incremental SAT retains one solver and its learned clauses, adds only new Pairwise bandwidth clauses, and currently adds full Order bandwidth clauses at each threshold, including duplicates. The official comparison uses the `unit` threshold policy so both strategies test descending k values in the same order from the same validated deterministic incumbent. General use retains the adaptive policy. The deterministic incumbent checks identity and Cuthill-McKee orderings on the exact graph.

## Official run on READY matrices

Hardware: Apple M2, arm64, 16 GiB RAM. Software: Python 3.14, PySAT 1.9.dev17, CaDiCaL 195. Source: NIST Matrix Market gzip files with hashes in the provenance JSON. Configuration: Pairwise/Order x Pairwise/Sequential AMO x Repeated/Incremental, no symmetry breaking, linear unit-step k schedule, 3 seconds per run, 60 seconds overall, 100,000-variable and 500,000-clause limits, no random seed. The two smallest READY Table 6 graphs were chosen by n: `bcspwr01` (39 vertices, 46 edges) and `bcsstk01` (48 vertices, 176 edges). The 113-row preflight plan is in `results/leader/official_preflight.csv`; the 16 actual runs and 113-row paper comparison are in the adjacent CSV/JSON files.

| Instance | Paper LB | Paper Best | Best Leader SAT | Certified SAT LB | Valid runs | Optimality |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| bcspwr01 | 5 | 5 | 5 | 4 | 8/8 | Unproved; all runs TIMEOUT |
| bcsstk01 | 16 | 16 | 20 | 12 | 8/8 | Unproved; all runs TIMEOUT |

The paper's published LB is recorded as a reference; the SAT certified LB column is computed independently. `bcspwr01` matches published Best but this does **not** prove optimality. On these two cases Order+Sequential reached the lowest bandwidth within the short limit, but the sample and timeout censoring do not support a general speed ranking. Fewer clauses alone do not imply lower runtime or RAM. Machine times must not be compared directly with the paper's machine times.

The remaining 111 paper-comparison rows show SKIPPED, NEEDS_VERIFICATION, or INVALID_DATA rather than invented SAT results. The batch cap and total wall budget prevent an unbounded 113-instance experiment.
For TIMEOUT rows, SAT calls and solver time count completed calls; total wall time includes the interrupted call and worker overhead. CNF counts reflect the latest fully appended formula reported by the worker.

A separate 4-run `bcspwr01` symmetry ablation is in `results/leader/official_symmetry_ablation.csv`: Pairwise+Sequential reached bandwidth 6 with symmetry off and on; Order+Sequential reached 5 with symmetry off and on. Every run timed out at 3 seconds with a validated incumbent, so this ablation provides no speedup conclusion.

## Reproduce and extend

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e . pytest python-sat
.venv/bin/python -m pytest -q
.venv/bin/python scripts/acquire_benchmark.py --max-instances 113
.venv/bin/python scripts/run_official_benchmark.py --max-ready 2 --per-call 3 --total 60 --max-clauses 500000
.venv/bin/python scripts/run_official_benchmark.py --symmetry-ablation-instance bcspwr01 --per-call 3
```

The raw files are required to repeat SAT runs; they are intentionally ignored by Git. The provenance JSON permits checksum verification after reacquisition. Python 3.11+ is supported by the project, but the official run above used Python 3.14. The worker's `fork` method requires POSIX; a spawn-compatible worker remains future integration work.

## Integration handoff

Member 2: Implement Binary/Commander as `AMOEncoder.encode(literals, allocator)` and register with `register_amo_encoder`; register Glucose with `register_sat_backend` and implement `SATBackend`, including a bounded-execution strategy. MIP adapters should accept `GraphInstance` and return `SolverResult` with a validated vertex-to-label permutation, recomputed bandwidth, certified lower bound if available, and accurate status. They can export the same benchmark fields without changing SAT core.

Member 3: Implement Product/Ladder through the same AMO registry and MiniSat through the SAT backend registry. CP-SAT/CP Optimizer adapters should return the same `SolverResult`. The canonical 113-row catalog is `bmp.core.benchmark_catalog.ALL_INSTANCES`; acquisition and topology audit are in `scripts/acquire_benchmark.py` and `bmp.io.readers.inspect_matrix_market`. The unresolved asymmetric conversion and `mbeause` dimension conflict are the immediate dataset tasks. RCM/SA/DRSA permutations should be passed as `heuristic_permutation` to the SAT solvers; the SAT code independently validates them before using them as incumbents. The paper's Best number by itself is never a valid heuristic input.

Shared interfaces: `GraphInstance` is the immutable `Graph` alias; `SolverResult` serializes status, incumbent, bounds, timing, counts, and metadata; `validate_solution` recomputes feasibility and bandwidth; `BenchmarkRecord` covers the synthetic runner, while the official runner exports a wider CSV/JSON schema. New adapters should preserve these meanings, especially TIMEOUT with a feasible incumbent and OPTIMAL only with a certificate.
