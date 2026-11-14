# Case Study: `steam3` (`n=80`, NIST Table 6)

## 1. SOURCE-VERIFIED FACTS
- **Raw File**: `data/benchmarks/raw/steam3.mtx.gz` (`sha256=a4a1ed4bdb4871b5f1aff3ff6cf06f103545aa7e13039517ea014f9c19ce3f8f`)
- **Matrix Market Header**: `%%MatrixMarket matrix coordinate real general`
- **Declared Dimensions & Entries**: `80 x 80`, `declared_nnz=928`
- **Diagonal vs Off-diagonal Breakdown**: `diagonal=80` (zeros=`0`), `offdiagonal_total=848` (`nonzero=234`, `explicit_zero=614`)
- **Symmetry Ratios**: `structural_symmetry_nonzero=0.6667`, `structural_symmetry_stored=1.0000`
- **Paper Table 6 Reference**: `n=80`, `Published LB=7`, `Published Best=7`, `GRASP-PR=7`, `SA=7`, `VNS=7`, `DRSA=7`.

## 2. REPRODUCIBLE COMPUTATIONAL FINDINGS (NON-OFFICIAL EXPLORATORY CHECKS)

Notice the crucial structural clue: while the matrix header declares `real general`, **all 614 off-diagonal explicit zeros sit at asymmetric holes** — when explicit zeros are included, `structural_symmetry_stored = 1.0000` (all stored off-diagonal slots have reciprocal `(j, i)` pairs).

| Policy (`official_benchmark=False`) | Undirected Edges `m` | Trivial LB | RCM | DRSA | CP-SAT Status | CP-SAT Exact `B*(G)` | vs Published LB (`7`) / Best (`7`) |
|---|---:|---:|---:|---:|---|---:|---|
| `nonzero_union` | 156 | 4 | 5 | 5 | `OPTIMAL` | `5` | **FALSIFIED (`B* < LB=7`)** |
| `stored_union` | 424 | 6 | 7 | 7 | `OPTIMAL` | `7` | **EXACT MATCH (`B* = 7 = LB = Best`)** |
| `nonzero_intersection` | 78 | 3 | 3 | 3 | `OPTIMAL` | `3` | **FALSIFIED (`B* < LB=7`)** |
| `stored_intersection` | 424 | 6 | 7 | 7 | `OPTIMAL` | `7` | **EXACT MATCH (`B* = 7 = LB = Best`)** |
| `triangular_lower` | 137 | 4 | 5 | 5 | `OPTIMAL` | `5` | **FALSIFIED (`B* < LB=7`)** |
| `triangular_upper` | 97 | 3 | 4 | 4 | `FEASIBLE` | `4` | B*=4 |

### Mathematical Proof That Official `nonzero_union` Cannot Match Paper's `steam3` Graph
- On `nonzero_union` (`m=156`, dropping the 614 explicit off-diagonal zeros), `CPSATSolver` produces an **exact certified optimality proof** that $B^*(G_{\text{nonzero\_union}}) = 5 < 7 = \text{Published LB}$ (`status=OPTIMAL`, `lower_bound=5`, `upper_bound=5`).
- Because $B^*(G)$ is a hard combinatorial invariant invariant under heuristic choice, **NO algorithm in the universe can achieve optimal bandwidth > 5 on `G_nonzero_union`**, directly falsifying `nonzero_union` (and `nonzero_intersection`, which yields `OPTIMAL bw=3`) against Published LB=7.
- On `stored_union` (`m=424`, preserving all structural Matrix Market off-diagonal slots including explicit `0.0` entries), `CPSATSolver` certifies **`OPTIMAL bw=7 == Published LB=7 == Published Best=7`** (`sym_st=1.0000`).

## 3. HYPOTHESIS / VERDICT ON `steam3` CLASSIFICATION
- **Status kept `NEEDS_VERIFICATION` (`evidence_level=CONFLICTING_EVIDENCE`)**: we do **NOT** promote `steam3` to `READY` because Torres-Jimenez et al. (2015) never state the explicit-zero retention rule in writing and original upstream graph permutations (`~jtj/bmp/`) have not been directly inspected.
