# BMP Optimization

Research software for the **graph Bandwidth Minimization Problem (BMP)**. For an
undirected simple graph, BMP seeks a bijection from vertices to positions
`1..n` that minimises the largest position difference across an edge.

This repository currently contains the completed **Phase 1 foundation**. It does
not yet claim a SAT implementation or publish benchmark performance results.

## Implemented and verified

- Immutable canonical graph model for undirected simple graphs.
- Edge-list, adjacency-matrix, and coordinate Matrix Market readers.
- Deterministic path, cycle, complete, star, edgeless, and `G(n,p)` generators.
- Solver-independent solution/status schema with certified lower/upper bounds.
- Independent bijection and bandwidth validator.
- Exact depth-first brute-force oracle for tiny graphs (default maximum: 10).
- JSON command-line output and TOML quick-run configuration.
- Known-optimum tests for P5, K5, K1,4, C4, and an edgeless graph.

The brute-force solver is a correctness oracle for future SAT/CP/MIP solvers, not
a scalable BMP algorithm.

## Project structure

```text
.
├── .github/workflows/ci.yml
├── configs/quick.toml
├── data/samples/
├── docs/
│   ├── methodology.md
│   ├── requirements-analysis.md
│   └── roadmap.md
├── src/bmp/
│   ├── cli.py
│   ├── core/
│   ├── io/
│   └── solvers/brute_force.py
├── tests/
├── pyproject.toml
└── README.md
```

Directories for unimplemented SAT adapters, commercial solvers, experiments, and
plots are intentionally absent. They will be added with working code in later
phases.

## Installation on macOS and VS Code

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

In VS Code, run **Python: Select Interpreter** and select
`.venv/bin/python`. Phase 1 has no third-party runtime dependency.

## Usage

Run the checked-in quick configuration:

```bash
bmp run-config configs/quick.toml
```

Solve a sample directly:

```bash
bmp solve data/samples/star_k1_4.edgelist --timeout 5
```

Inspect an input without solving it:

```bash
bmp inspect data/samples/cycle_c4.edgelist
```

Generate a reproducible random graph and solve it if it is small enough:

```bash
bmp generate random 8 /tmp/random8.edgelist --probability 0.3 --seed 2026
bmp solve /tmp/random8.edgelist --timeout 10
```

Validate a JSON result independently:

```bash
bmp solve data/samples/path_p5.edgelist > /tmp/path-result.json
bmp validate data/samples/path_p5.edgelist /tmp/path-result.json
```

## Tests

The standard-library suite needs no test framework dependency:

```bash
python -m unittest discover -s tests -v
```

## Input conventions

The project edge-list format accepts comments and an optional DIMACS-style
header. Use a header to retain isolated vertices:

```text
# four vertices, two edges
p edge 4 2
1 2
2 3
```

Adjacency matrices must be square, symmetric, and zero-diagonal. Matrix Market
support currently covers coordinate `pattern`, `integer`, and `real` matrices;
non-zero entries are interpreted as unweighted adjacency.

## Scientific scope and roadmap

The [requirements analysis](docs/requirements-analysis.md) separates official
mandatory work from encouraged extensions and flags questions for the instructor.
The [methodology](docs/methodology.md) documents Phase 1 invariants and the exact
oracle. The [roadmap](docs/roadmap.md) gives the staged plan for mandatory
Pairwise/Order SAT encodings, Repeated/Incremental SAT, exact-solver adapters,
cardinality experiments, heuristics, benchmarking, and report-ready figures.

The supplied “Order Encoding” paper concerns Radio Mean Labeling. Only its
threshold-variable concepts will be considered; its problem-specific constraints
will not be copied into BMP without a separate correctness derivation.

## Reproducibility and results

Random generators require explicit seeds. Every solve result records status,
objective, certified bounds, runtime, search effort, graph metadata, and an
independent validation report. No benchmark numbers have been fabricated or
pre-populated. Curated real CSV/JSON results and figures may be committed later;
large raw artifacts remain ignored.

## References

- Official Assignment 2 requirements, Modern Topics in Computer Science,
  academic year 2026-2027.
- J. Torres-Jimenez et al., “A dual representation simulated annealing algorithm
  for the bandwidth minimization problem on graphs,” *Information Sciences*,
  303 (2015), 33-49. DOI: 10.1016/j.ins.2014.12.041.
- N. Tamura et al., “Compiling finite linear CSP into SAT,” *Constraints*, 14(2),
  2009. This is the general order-encoding reference cited by the supplied Radio
  Mean Labeling manuscript.
