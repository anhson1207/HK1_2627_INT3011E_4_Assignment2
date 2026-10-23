# BMP Optimization – SAT & Exact Optimization Framework

Research software for the **Bandwidth Minimization Problem (BMP)** on undirected simple graphs, developed for Assignment 2 of Modern Topics in Computer Science (2026–2027).

---

## 1. Problem Definition and Mathematical Formulation

Given an undirected, unweighted, simple graph $G = (V, E)$ with $n = |V|$ vertices and $m = |E|$ edges. Vertices are indexed $V = \{0, 1, \dots, n-1\}$.

A **labeling** (embedding) is a bijection:
$$p: V \to \{1, 2, \dots, n\}$$

The **bandwidth** of graph $G$ under labeling $p$ is:
$$B_p(G) = \max_{(u, v) \in E} |p(u) - p(v)|$$

The **Bandwidth Minimization Problem (BMP)** seeks a labeling $p^*$ achieving the minimum possible bandwidth:
$$B^*(G) = \min_{p \in \Pi(V)} B_p(G)$$

### Decision Problem $SAT(G, k)$
For a target bandwidth threshold $k \ge 0$, determine whether there exists a bijection $p$ such that:
$$\forall (u, v) \in E, \quad |p(u) - p(v)| \le k$$

- **Edgeless graph ($E = \emptyset$) or $n \le 1$**: $B^*(G) = 0$.
- **Path graph $P_5$**: $B^*(P_5) = 1$.
- **Complete graph $K_5$**: $B^*(K_5) = 4$.
- **Star graph $K_{1, 4}$**: $B^*(K_{1, 4}) = 2$.
- **Cycle graph $C_4$**: $B^*(C_4) = 2$.

---

## 2. Implemented Leader Scope

### A. SAT Encodings
1. **Pairwise / Basic Position Encoding (`PairwiseEncoding`)**:
   - Variables $x[v, p] \in \{0, 1\}$ indicating vertex $v$ receives label $p \in \{1, \dots, n\}$.
   - **Exactly-One (ALO + AMO)** per vertex: $\bigvee_{p=1}^n x[v, p]$ and $\sum_{p=1}^n x[v, p] \le 1$.
   - **All-Different (Injectivity)** per label: $\sum_{v \in V} x[v, p] \le 1$.
   - **Bandwidth Clauses**: $\forall (u, v) \in E, \; |p - q| > k \implies \neg x[u, p] \lor \neg x[v, q]$.
2. **Order SAT Encoding (`OrderEncoding`)**:
   - Unary threshold variables $y[v, t] \in \{0, 1\}$ indicating $p(v) \ge t$ for $t \in \{2, \dots, n\}$.
   - **Monotonicity**: $y[v, t+1] \implies y[v, t]$.
   - **Exact-value Channeling**: $x[v, p] \iff (y[v, p] \land \neg y[v, p+1])$.
   - **Injectivity**: At-Most-One on channeled variables $x[v, p]$ for each label $p$.
   - **Linear Bandwidth Clauses**: $\forall (u, v) \in E$ and $t \ge 2, \; t + k \le n$:
     $$\neg y[u, t+k] \lor y[v, t] \quad \text{and} \quad \neg y[v, t+k] \lor y[u, t]$$
     Requires only $2(n - k - 1) = O(n)$ binary clauses per edge (vs $O(n^2)$ for pairwise).
3. **Cardinality Encodings for AMO**:
   - **Pairwise AMO** (`PairwiseAMOEncoder`): Quadratic $\binom{m}{2}$ binary exclusion clauses, 0 auxiliary variables.
   - **Sequential Counter AMO** (`SequentialCounterAMOEncoder`, Sinz 2005): Linear $3m - 4$ clauses, $m - 1$ auxiliary variables, arc-consistent unit propagation.
   - Extensible registry interface for integrating Binary, Commander, Product, and Ladder in future milestones.

### B. SAT Solving & Strategies
1. **Repeated SAT (`RepeatedSATSolver`)**:
   - Fresh SAT solver instance per tested bandwidth $k$.
   - Descending linear search from upper bound $UB$ down to certified lower bound $LB$.
   - Binary search mode (`search_mode="binary"`).
2. **Incremental SAT (`IncrementalSATSolver`)**:
   - Single persistent CaDiCaL solver instance reusing learned conflict clauses.
   - Fixed $k$-independent clauses asserted once.
   - Monotonic constraint addition as $k$ decreases.
   - Proves global optimality upon receiving UNSAT at $B - 1$.
3. **CaDiCaL SAT Backend (`CadicalBackend`)**:
   - Seamless integration with PySAT supporting CaDiCaL (versions `cadical195`, `cadical300`, `cadical153`, `cadical103`).
   - Clean lifecycle management with context manager and `.delete()`.

### C. Advanced Techniques
1. **Reversal Symmetry Breaking**:
   - Label reversal $p'(v) = n + 1 - p(v)$ preserves edge bandwidth.
   - Deterministic anchor vertex selection $a = \arg\max_{v} (\deg(v), \sum_{u \in N(v)} \deg(u), -v)$.
   - Adds unit clause $p(a) \le \lceil n / 2 \rceil$, cutting the search space in half.
2. **Bounds Optimization**:
   - Certified degree bound $LB_{deg} = \lceil \Delta(G) / 2 \rceil$.
   - Component diameter bound $LB_{comp} = \max_C \lceil (|C| - 1) / \operatorname{diam}(C) \rceil$.
3. **Hybrid Heuristic + SAT Interface**:
   - Allows injecting an initial heuristic permutation (e.g. from RCM, SA, DRSA).

---

## 3. Project Structure

```text
.
├── configs/
│   └── quick.toml
├── data/
│   ├── samples/
│   ├── leader_sat_benchmark.csv
│   └── leader_sat_benchmark.json
├── docs/
│   ├── sat_methodology.md
│   ├── leader_experiments.md
│   ├── requirements-analysis.md
│   └── roadmap.md
├── src/bmp/
│   ├── cli.py
│   ├── core/
│   │   ├── graph.py          # GraphInstance / Graph model
│   │   ├── solution.py       # SolverResult / BMPSolution
│   │   ├── validation.py     # Independent validator & calculate_bandwidth
│   │   ├── bounds.py         # Analytical lower/upper bounds
│   │   └── generators.py     # Deterministic graph generators
│   ├── encodings/
│   │   ├── base.py           # CNFFormula & BMPEncoder interface
│   │   ├── pairwise.py       # Position / Pairwise encoding
│   │   ├── order.py          # Order / Threshold encoding
│   │   └── cardinality/
│   │       ├── base.py       # AMO protocol and registry
│   │       ├── pairwise_amo.py
│   │       └── sequential.py # Sinz (2005) sequential counter
│   ├── io/
│   │   └── readers.py
│   └── solvers/
│       ├── brute_force.py    # Small-instance exact oracle
│       └── sat/
│           ├── backends/
│           │   ├── base.py   # SATBackend interface
│           │   └── cadical.py# CaDiCaL PySAT backend
│           ├── repeated.py   # Repeated SAT solver
│           ├── incremental.py# Incremental SAT solver
│           ├── search.py     # Search helpers and bounds
│           └── benchmark.py  # Leader SAT experiment runner
├── tests/
│   ├── core/
│   ├── encodings/
│   └── sat/
├── pyproject.toml
└── README.md
```

---

## 4. Installation

```bash
# Clone repository and enter directory
cd BMP

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install package and SAT dependencies
pip install -e .
pip install python-sat pytest
```

---

## 5. CLI Usage

### Solve with Repeated SAT (Pairwise Encoding)
```bash
python -m bmp solve data/samples/star_k1_4.edgelist --encoding pairwise --strategy repeated --solver cadical --amo pairwise
```

### Solve with Incremental SAT (Sequential Counter AMO)
```bash
python -m bmp solve data/samples/star_k1_4.edgelist --encoding pairwise --strategy incremental --solver cadical --amo sequential
```

### Solve with Order Encoding (Repeated SAT)
```bash
python -m bmp solve data/samples/star_k1_4.edgelist --encoding order --strategy repeated --solver cadical
```

### Solve with Order Encoding (Incremental SAT)
```bash
python -m bmp solve data/samples/star_k1_4.edgelist --encoding order --strategy incremental --solver cadical
```

### Enable Symmetry Breaking
```bash
python -m bmp solve data/samples/cycle_c4.edgelist --encoding pairwise --strategy incremental --symmetry-breaking
```

### Run Leader SAT Benchmark Suite
```bash
python -m bmp benchmark-sat --output-json data/leader_sat_benchmark.json --output-csv data/leader_sat_benchmark.csv
```

---

## 6. Real Experimental Results (Leader SAT Evaluation)

Benchmark summary across 10 instances (100 runs total) from `data/leader_sat_benchmark.csv`:

| Encoding | Strategy | Symmetry Breaking | Avg Total Runtime (s) | Avg Solver Time (s) | Avg Clauses | Avg SAT Calls |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **pairwise** | repeated | False | 0.001924 | 0.001783 | 152.0 | 1.8 |
| **pairwise** | repeated | True | 0.000287 | 0.000212 | 152.3 | 1.2 |
| **pairwise** | incremental | False | 0.000305 | 0.000128 | 152.0 | 1.8 |
| **pairwise** | incremental | True | 0.000173 | 0.000072 | 152.3 | 1.2 |
| **order** | repeated | False | 0.000336 | 0.000218 | 156.9 | 1.8 |
| **order** | repeated | True | 0.000212 | 0.000128 | 150.9 | 1.2 |
| **order** | incremental | False | 0.000195 | 0.000045 | 162.3 | 1.8 |
| **order** | incremental | True | **0.000137** | **0.000027** | 156.9 | 1.2 |

Detailed methodology and ablation analysis are available in:
- [SAT Methodology](docs/sat_methodology.md)
- [Leader Experiments](docs/leader_experiments.md)

---

## 7. Running Tests

Run the complete test suite (unit tests, encoding equivalence, solver consistency, oracle cross-checks):

```bash
pytest -v
```

---

## 8. Ongoing Development & Member Responsibilities

- **`dev/leader` (Current Branch)**: SAT Position & Order Encodings, Pairwise & Sequential AMO, Repeated & Incremental CaDiCaL SAT, Symmetry Breaking.
- **`dev/member-2` (In Development by Member 2)**: Binary & Commander Cardinality Encodings, Glucose SAT Solver, Gurobi MIP, CPLEX MIP, Comprehensive Benchmarking Suite.
- **`dev/member-3` (In Development by Member 3)**: Product & Ladder Cardinality Encodings, MiniSat Solver, CP-SAT, CP Optimizer, Harwell-Boeing Dataset Pipeline, Metaheuristics (RCM, SA, DRSA).
