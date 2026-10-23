# BMP SAT Solving Methodology & Technical Documentation

This document provides the formal mathematical foundations, logical formulations, and algorithmic implementations for solving the **Bandwidth Minimization Problem (BMP)** using Boolean Satisfiability (SAT) methods developed for the Leader scope.

---

## 1. Mathematical Formulation of BMP

Given a finite, simple, undirected, unweighted graph $G = (V, E)$ with $n = |V|$ vertices and $m = |E|$ edges.
Vertices are indexed $V = \{0, 1, \dots, n-1\}$.

A **labeling** (or embedding) is a bijection:
$$p: V \to \{1, 2, \dots, n\}$$

The **bandwidth** of graph $G$ under labeling $p$ is defined as the maximum stretch across all edges:
$$B_p(G) = \max_{(u, v) \in E} |p(u) - p(v)|$$

The **Bandwidth Minimization Problem (BMP)** seeks an optimal labeling $p^*$ that achieves the minimum bandwidth:
$$B^*(G) = \min_{p \in \Pi(V)} B_p(G)$$

### Decision Problem $SAT(G, k)$
For a fixed integer threshold $k \ge 0$, determine whether there exists a bijective labeling $p: V \to \{1, \dots, n\}$ such that:
$$\forall (u, v) \in E, \quad |p(u) - p(v)| \le k$$

- If $SAT(G, k)$ is True, a feasible labeling with bandwidth at most $k$ exists.
- If $SAT(G, k)$ is False (UNSAT), no labeling with bandwidth $\le k$ can exist.

### Boundary Cases
- If $E = \emptyset$ or $n \le 1$: $B^*(G) = 0$.
- Path graph $P_n$: $B^*(P_n) = 1$.
- Complete graph $K_n$: $B^*(K_n) = n - 1$.
- Star graph $K_{1, n-1}$: $B^*(K_{1, n-1}) = \lfloor n / 2 \rfloor$.
- Cycle graph $C_n$: $B^*(C_n) = 2$ (for $n \ge 4$).

---

## 2. Basic Position / Pairwise SAT Encoding

### 2.1 Boolean Variables
For each vertex $v \in V$ and each position/label $p \in \{1, \dots, n\}$, define:
$$x_{v, p} = \text{True} \iff p(v) = p$$
Total original variables: $n^2$.

### 2.2 Constraints

#### 1. Exactly-One Label per Vertex
Every vertex $v \in V$ must receive exactly one label from $\{1, \dots, n\}$:
- **At-Least-One (ALO)**:
  $$\bigvee_{p=1}^n x_{v, p} \quad \forall v \in V$$
- **At-Most-One (AMO)**:
  $$\sum_{p=1}^n x_{v, p} \le 1 \quad \forall v \in V$$
  Encoded using a pluggable AMO encoder (Pairwise AMO or Sequential Counter).

#### 2. All-Different (Injectivity / Occupancy)
No two distinct vertices can be assigned the same label $p$:
$$\sum_{v \in V} x_{v, p} \le 1 \quad \forall p \in \{1, \dots, n\}$$
Encoded using a pluggable AMO encoder.

#### 3. Bandwidth Constraint for Threshold $k$
For every edge $(u, v) \in E$ and every pair of labels $(p, q) \in \{1, \dots, n\}^2$ satisfying $|p - q| > k$, forbid vertex $u$ receiving label $p$ while vertex $v$ receives label $q$:
$$\neg x_{u, p} \lor \neg x_{v, q}$$

Number of bandwidth clauses per edge: $(n - k)(n - k - 1)$.
Overall formula size: $O(n^2)$ variables, $O(|E| n^2)$ clauses.

---

## 3. Order SAT Encoding

### 3.1 Boolean Variables
Order encoding represents integer variables via unary "greater-than-or-equal" threshold variables:
$$y_{v, t} = \text{True} \iff p(v) \ge t, \quad \forall v \in V, \; t \in \{2, \dots, n\}$$
Notice that $t = 1$ is omitted since $p(v) \ge 1$ is trivially True, and $t = n + 1$ is trivially False.
Total order variables: $n(n - 1)$.

To achieve strong unit propagation for injectivity without exploding clause counts, we channel $y_{v, t}$ to exact-value indicator variables $x_{v, p} \in \{0, 1\}$ ($p \in \{1, \dots, n\}$), where $x_{v, p} \iff p(v) = p$.

### 3.2 Constraints

#### 1. Monotonicity of Order Variables
If $p(v) \ge t + 1$, then necessarily $p(v) \ge t$:
$$y_{v, t+1} \implies y_{v, t} \iff \neg y_{v, t+1} \lor y_{v, t}, \quad \forall v \in V, \; t \in \{2, \dots, n-1\}$$

#### 2. Channeling Constraints
- For $p = 1$: $x_{v, 1} \iff \neg y_{v, 2}$
  $$\neg x_{v, 1} \lor \neg y_{v, 2}, \quad x_{v, 1} \lor y_{v, 2}$$
- For $2 \le p \le n - 1$: $x_{v, p} \iff (y_{v, p} \land \neg y_{v, p+1})$
  $$\neg x_{v, p} \lor y_{v, p}, \quad \neg x_{v, p} \lor \neg y_{v, p+1}, \quad \neg y_{v, p} \lor y_{v, p+1} \lor x_{v, p}$$
- For $p = n$: $x_{v, n} \iff y_{v, n}$
  $$\neg x_{v, n} \lor y_{v, n}, \quad x_{v, n} \lor \neg y_{v, n}$$

#### 3. Injectivity / All-Different
$$\sum_{v \in V} x_{v, p} \le 1 \quad \forall p \in \{1, \dots, n\}$$

#### 4. Bandwidth Constraints
For every edge $(u, v) \in E$, the condition $|p(u) - p(v)| \le k$ is equivalent to the conjunction of:
1. $p(u) - p(v) \le k \iff (p(u) \ge t + k \implies p(v) \ge t)$
2. $p(v) - p(u) \le k \iff (p(v) \ge t + k \implies p(u) \ge t)$

In terms of order variables, for all $t \ge 2$ such that $t + k \le n$:
$$\neg y_{u, t+k} \lor y_{v, t}$$
$$\neg y_{v, t+k} \lor y_{u, t}$$

**Proof of Correctness:**
- Suppose $p(u) - p(v) > k$. Then $p(u) \ge p(v) + k + 1$. Choose $t = p(v) + 1 \ge 2$.
  Then $t + k = p(v) + k + 1 \le p(u) \le n$.
  For this $t$, $y_{u, t+k}$ is True (since $p(u) \ge t+k$) and $y_{v, t}$ is False (since $p(v) < t$).
  Hence, the clause $\neg y_{u, t+k} \lor y_{v, t}$ evaluates to $\text{False} \lor \text{False} = \text{False}$, violating the clause.
- Conversely, if $p(u) - p(v) \le k$, for any $t \ge 2$ such that $y_{u, t+k}$ is True ($p(u) \ge t+k$), we have $p(v) \ge p(u) - k \ge t$, which implies $y_{v, t}$ is True, so the clause is satisfied.

**Complexity Advantage:**
The order encoding requires only $2(n - k - 1) = O(n)$ binary clauses per edge! In comparison, the pairwise encoding requires $O(n^2)$ clauses per edge.

---

## 4. Cardinality Encodings for At-Most-One (AMO)

### 4.1 Pairwise AMO
For a set of Boolean literals $\{x_1, \dots, x_m\}$:
$$\neg x_i \lor \neg x_j \quad \forall 1 \le i < j \le m$$
- Auxiliary variables: $0$.
- Clauses: $\binom{m}{2} = \frac{m(m-1)}{2} = O(m^2)$.

### 4.2 Sequential Counter AMO (Sinz 2005)
Introduces $m - 1$ auxiliary register variables $s_1, \dots, s_{m-1}$ representing the prefix sum:
- $\neg x_1 \lor s_1$
- For $1 < i < m$:
  - $\neg x_i \lor s_i$
  - $\neg s_{i-1} \lor s_i$
  - $\neg x_i \lor \neg s_{i-1}$
- $\neg x_m \lor \neg s_{m-1}$
- Auxiliary variables: $m - 1 = O(m)$.
- Clauses: $3m - 4 = O(m)$.
- Maintains Generalized Arc-Consistency (GAC) through unit propagation.

---

## 5. Solving Strategies

### 5.1 Repeated SAT
1. Compute certified lower bound $LB = \max(LB_{degree}, LB_{component})$.
2. Compute initial upper bound $UB$ (from identity permutation or heuristic).
3. If $LB == UB$, return $UB$ as certified optimal.
4. Set $k = UB - 1$.
5. In each iteration:
   - Construct a fresh CNF formula for $(G, k)$.
   - Initialize a fresh SAT solver instance (`cadical195`).
   - Solve:
     - If SAT: decode model $\to$ actual bandwidth $B \le k$. If $B \le LB$, stop with OPTIMAL. Else $k = B - 1$.
     - If UNSAT: $k+1$ is proved to be the optimal bandwidth $B^*(G)$.
   - Free native solver memory.

### 5.2 Incremental SAT
1. Initialize a single persistent solver instance (`cadical195`).
2. Add $k$-independent fixed clauses:
   - ALO and AMO for vertex label assignments.
   - Injectivity AMO for each label.
3. Start descending search at $k = UB - 1$:
   - For **Pairwise Encoding**:
     Add only the incremental difference clauses:
     $$\Delta(k_{next}, k_{curr}) = \{\neg x_{u, p} \lor \neg x_{v, q} \mid (u, v) \in E, \; k_{next} < |p - q| \le k_{curr}\}$$
   - For **Order Encoding**:
     Add the new threshold clauses for $k_{next}$:
     $$\{\neg y_{u, t+k_{next}} \lor y_{v, t}, \; \neg y_{v, t+k_{next}} \lor y_{u, t} \mid (u, v) \in E, \; 2 \le t \le n - k_{next}\}$$
   - Because $k$ decreases monotonically, each added clause set strictly strengthens the formula.
   - Retains all learned conflict clauses across iterations.
   - Terminates with status OPTIMAL when solver returns UNSAT at $B - 1$.

---

## 6. Reversal Symmetry Breaking

### Theoretical Foundation
For any graph $G$, the label reversal operation:
$$\sigma(p) = n + 1 - p$$
is an automorphism of the complete graph $K_n$. For any permutation $\pi$, the reversed permutation $\pi'(v) = n + 1 - \pi(v)$ satisfies:
$$|\pi'(u) - \pi'(v)| = |(n + 1 - \pi(u)) - (n + 1 - \pi(v))| = |\pi(v) - \pi(u)| = |\pi(u) - \pi(v)|$$
Thus, $B_{\pi'}(G) = B_\pi(G)$.

### Anchor Vertex Restriction
We deterministically select an anchor vertex $a \in V$ with the highest degree and neighbor-degree sum:
$$\pi(a) \le \lceil n / 2 \rceil$$
If an optimal labeling has $\pi^*(a) > \lceil n / 2 \rceil$, its reflection $(\pi^*)'$ satisfies $(\pi^*)'(a) \le \lfloor n / 2 \rfloor \le \lceil n / 2 \rceil$, which guarantees that at least one optimal solution is preserved.

### CNF Implementation
- **Pairwise**: Unit clauses $\neg x_{a, p}$ for all $p \in \{\lceil n / 2 \rceil + 1, \dots, n\}$.
- **Order**: A single unit clause $\neg y_{a, \lceil n / 2 \rceil + 1}$, which automatically propagates to all higher thresholds.
