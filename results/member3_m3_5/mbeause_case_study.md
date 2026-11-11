# Case Study: `mbeause` (`raw n=496` vs `Table 8 paper_n=492` vs `Table 5 Total=496 / Largest=492`)

## 1. SOURCE-VERIFIED FACTS
- **Raw File**: `data/benchmarks/raw/mbeause.mtx.gz` (`sha256=96a9158e7f52d1452059746efd57c25cdf2a988439e720b500066a7517d4dd88`)
- **Matrix Market Header**: `%%MatrixMarket matrix coordinate real general`
- **Raw Matrix Dimensions**: `496 x 496`, `declared_nnz=41063` (`explicit_zero_entries=0`)
- **Undirected Edges (`nonzero_union`)**: `m=36209` (`asymmetric_pairs_nonzero=31755`)
- **Isolated Vertices in `mbeause` (`degree == 0`)**: `[493, 494, 495, 496]` (4 isolated nodes `[493, 494, 495, 496]`).
- **Internal Conflict in Torres-Jimenez et al. (2015)**:
  - **Table 5 (p. 44)**: lists `mbeause` with **`Total number of vertices = 496`** and **`Vertices in the largest component = 492`**.
  - **Table 8 (p. 47)**: lists `mbeause` with **`n = 492`**, `LB = 249`, `Best = 254`, `DRSA = 254` (while adjacent rows `mbeacxc` and `mbeaflw` have `n = 496`).
  - **Section 5 (p. 45)**: explicitly claims *"in previous works the number of vertices in the largest connected component was considered as the number of vertices of the instance; however, we take into account the entire graph and compute the labeling for all vertices in the graph."*

## 2. MATHEMATICAL PROOF: ISOLATED VERTICES PRESERVE EXACT OPTIMAL BANDWIDTH
**Theorem**: Let $G = (V, E)$ be an undirected graph with $E \neq \emptyset$, and let $G' = (V \cup S, E)$ be obtained by adding $r = |S| \ge 1$ isolated vertices ($\deg(v) = 0$ for all $v \in S$). Then $B^*(G') = B^*(G)$.
- *Proof*: ($\le$) Any bijection $\tau: V \to \{1, \dots, |V|\}$ achieving $B_\tau(G) = B^*(G)$ extends to $\tau': V \cup S \to \{1, \dots, |V|+r\}$ by assigning $\tau'(v) = \tau(v)$ for $v \in V$ and $\tau'(S) = \{|V|+1, \dots, |V|+r\}$; since isolated vertices incident no edges, $\max_{(u,v)\in E}|\tau'(u)-\tau'(v)| = B^*(G)$. ($\ge$) Conversely, restricting any bijection $\tau': V \cup S \to \{1, \dots, |V|+r\}$ to $V$ and order-compressing its image onto $\{1, \dots, |V|\}$ preserves or strictly reduces every distance $|\tau(u)-\tau(v)|$ because collapsing gaps created by isolated labels in between never increases pairwise rank difference! $\square$

## 3. REPRODUCIBLE COMPUTATIONAL DIAGNOSTICS
- **`mbeause_496` (full raw graph)**: `n=496`, `m=36209`, `components=[492, 1, 1, 1, 1]`, `trivial_lb=245`, `RCM=473`, `DRSA(1.5s)=473`.
- **`mbeause_492` (largest component)**: `n=492`, `m=36209`, `components=[492]`, `trivial_lb=245`, `RCM=473`, `DRSA(1.5s)=473`.
- Exact BruteForce oracle tests on small graphs (`K3`, `P4`, `C5`) + 2 isolated vertices confirm 100% equality:
  - `K3`: `B*(base)=2`, `B*(+2 isolated)=2`, `equal=True`
  - `P4`: `B*(base)=1`, `B*(+2 isolated)=1`, `equal=True`
  - `C5`: `B*(base)=2`, `B*(+2 isolated)=2`, `equal=True`

## 4. DECISION
- **`mbeause` remains `INVALID_DATA` (`evidence_level=CONFLICTING_EVIDENCE`)** for official provenance/benchmark compliance because of BOTH (a) the unresolved `n=492` vs `496` mismatch in Paper Table 8 (`492`) vs raw `.mtx` & Paper Table 5 (`496`), AND (b) `mbeause` being a `real general` asymmetric matrix (`31,755` one-sided off-diagonal entries).
- Never mutate raw `mbeause.mtx.gz` or delete isolated vertices `{493..496}` inside the official loader.
