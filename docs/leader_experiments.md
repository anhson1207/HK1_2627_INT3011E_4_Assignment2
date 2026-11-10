# Leader SAT Experiments & Empirical Evaluation

This document records the earlier small synthetic-graph benchmark. The official paper dataset audit and bounded SAT run are in [Leader L7 Audit](leader_l7_audit.md). These microsecond-scale figures are historical observations, not a ranking of methods on the official instances.

All experiments were executed on an Apple Silicon M-series system using **Python 3.14**, **PySAT 1.9.dev17**, and the **CaDiCaL 1.9.5** backend solver. All returned labelings were independently verified using the strict certificate validator.

---

## 1. Experimental Setup

### Tested Encodings
1. **Pairwise Encoding** with Pairwise AMO (`pairwise_pairwise`)
2. **Pairwise Encoding** with Sequential Counter AMO (`pairwise_sequential`)
3. **Order Encoding** with Pairwise AMO (`order_pairwise`)
4. **Order Encoding** with Sequential Counter AMO (`order_sequential`)

### Solving Strategies
1. **Repeated SAT** (`repeated_linear` and `repeated_binary`)
2. **Incremental SAT** (`incremental`)

### Benchmark Instances
- **Canonical Graphs**: Path $P_5$, Path $P_7$, Star $K_{1, 4}$, Star $K_{1, 6}$, Cycle $C_4$, Cycle $C_6$, Complete $K_5$, Edgeless $E_5$.
- **Random Graphs**: $G(6, 0.35)$ (seed 42), $G(7, 0.40)$ (seed 100).
- **Sample Graphs**: `data/samples/` (`star_k1_4`, `path_p5`, `cycle_c4`, `complete_k5`, `edgeless_5`); these are synthetic, not Harwell-Boeing matrices.

---

## 2. Summary of Empirical Results

| Encoding | Strategy | Symmetry Breaking | Avg Total Runtime (s) | Avg Solver Time (s) | Avg Clauses | Avg SAT Calls |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| **pairwise** | repeated | False | 0.001924 | 0.001783 | 152.0 | 1.8 |
| **pairwise** | repeated | True | 0.000287 | 0.000212 | 152.3 | 1.2 |
| **pairwise** | incremental | False | 0.000305 | 0.000128 | 152.0 | 1.8 |
| **pairwise** | incremental | True | 0.000173 | 0.000072 | 152.3 | 1.2 |
| **order** | repeated | False | 0.000336 | 0.000218 | 156.9 | 1.8 |
| **order** | repeated | True | 0.000212 | 0.000128 | 150.9 | 1.2 |
| **order** | incremental | False | 0.000195 | 0.000045 | 162.3 | 1.8 |
| **order** | incremental | True | **0.000137** | **0.000027** | 156.9 | 1.2 |

*(Data source: `data/leader_sat_benchmark.csv`)*

---

## 3. Analysis & Key Insights

### 3.1 Incremental SAT vs. Repeated SAT
- **Solving Time**: The small synthetic runs show differences, but they do not establish that Incremental SAT is generally faster than Repeated SAT.
- **Learned Clause Reuse**: The incremental solver keeps one CaDiCaL instance and its learned clauses. The size of any benefit requires a controlled experiment on the same threshold sequence.
- **Overhead**: For tiny instances ($n \le 5$), the solver initialization overhead in Repeated SAT is noticeable; Incremental SAT avoids re-creating the native solver state.

### 3.2 Pairwise Encoding vs. Order Encoding
- **Bandwidth Clauses**: For an edge $(u, v)$, Pairwise encoding generates $O(n^2)$ binary exclusion clauses, whereas Order encoding generates only $2(n - k - 1) = O(n)$ binary clauses.
- **Solving Efficiency**: Order has fewer bandwidth clauses at a fixed k, but total clause count, variables, propagation, and proof search all affect runtime. No speed conclusion follows from size alone.
- **Variable Count Tradeoff**: Order encoding introduces $n(n - 1)$ threshold variables plus channeling variables, whereas Pairwise uses $n^2$ variables.

### 3.3 Cardinality Encoding: Pairwise AMO vs. Sequential Counter
- On $n = 5$ ($K_{1, 4}$):
  - **Pairwise AMO**: 25 variables, 129 clauses.
  - **Sequential Counter AMO**: 65 variables (40 auxiliary), 123 clauses.
- **Scaling Behavior**: For small $n$, Pairwise AMO has fewer variables and slightly lower overhead. As $n$ grows, Sequential Counter's linear clause growth ($3m - 4$) prevents clause explosion compared to quadratic growth ($\binom{m}{2}$).

### 3.4 Impact of Reversal Symmetry Breaking
- **Search Space Reduction**: Enforcing $p(\text{anchor}) \le \lceil n / 2 \rceil$ cuts the permutation search space in half.
- **Speedup**: The historical synthetic runs show lower times with symmetry on several tiny cases. The short official `bcspwr01` ablation found the same bandwidth with symmetry on and off and did not establish a speed advantage.
- **Correctness**: The synthetic benchmark solutions were independently validated; exhaustive and random small-graph tests check that reversal symmetry preserves optima.

---

## 4. Verification and Data Availability
- Full dataset available in `data/leader_sat_benchmark.csv` and `data/leader_sat_benchmark.json`.
- All solutions verified by independent validator `validate_solution()`.

