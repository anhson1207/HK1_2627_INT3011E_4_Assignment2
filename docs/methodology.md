# Phase 1 methodology

## Problem definition

For a finite undirected simple graph \(G=(V,E)\), a labeling is a bijection
\(p:V\rightarrow\{1,\ldots,|V|\}\). Its bandwidth is

\[
B_p(G)=\max_{(u,v)\in E}|p(u)-p(v)|.
\]

BMP minimises \(B_p(G)\) over all bijective labelings. This project defines the
bandwidth of an edgeless graph as zero.

## Canonical data model

Every adapter creates an immutable undirected simple `Graph`. Edges are stored in
canonical endpoint order, duplicates collapse, self-loops are rejected, and
isolated vertices are retained when the input format declares graph order. This
prevents each solver from silently applying different data-cleaning rules.

Supported Phase 1 inputs are edge lists, square symmetric adjacency matrices,
and coordinate Matrix Market files. Matrix values are interpreted only as
zero/non-zero adjacency; weighted BMP is outside the current scope.

## Independent certificate validation

A candidate is accepted only if it maps every vertex exactly once to the full
label set `1..n`. The validator then recomputes the maximum edge difference and
checks any claimed objective. It is separate from the solver and will remain the
last correctness gate for future SAT, CP, and MIP adapters.

## Exact oracle

The Phase 1 solver enumerates labelings by depth-first search for graphs of at
most ten vertices. It starts from a valid identity-order upper bound and prunes a
partial labeling once its current edge span cannot improve the incumbent. The
certified degree bound

\[
B^*\ge \lceil\Delta(G)/2\rceil
\]

allows early optimality detection. Reversing all positions preserves every edge
difference, so one of the two orientation-equivalent complete assignments may be
discarded. A completed search proves optimality; a timeout returns status
`TIMEOUT`, retains a validated incumbent, and reports distinct certified lower
and upper bounds.

This is an oracle for small-instance cross-checks, not a scalable benchmark
solver. It has no dependency on the SAT encoding that it will later validate.

## Reproducibility

Random graphs use a local pseudorandom generator with an explicit seed. CLI
results are JSON and include instance size, density, status, objective, bounds,
runtime, search-node count, and independent validation. No unexecuted benchmark
rows or synthetic performance numbers are included.
