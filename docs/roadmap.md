# Research roadmap

## Phase 2 - mandatory SAT core

1. Pin and record a tested `python-sat` version and enumerate available solver
   backends at runtime rather than assuming names or licenses.
2. Define a CNF result object containing clauses, top variable identifier,
   variable map, build time, and encoding statistics.
3. Implement the position encoding `x[v,p]` with exactly-one vertex positions,
   exactly-one position occupants, and BMP decision clauses for `bandwidth <= k`.
4. Implement a genuine threshold/order encoding. Derive BMP injectivity and
   absolute-difference clauses from first principles, and include a proof sketch
   of soundness, completeness, and decoding.
5. Implement repeated SAT with fresh solver state and incremental SAT with fixed
   variable meanings plus activation literals/assumptions. Keep the same bound
   sequence and backend when comparing strategies.
6. Exhaustively compare both encodings and both search modes against the Phase 1
   oracle for all generated simple graphs through a small order.
7. Record variables, clauses, encoding time, solver time, total time, SAT calls,
   bounds, backend/version, and validated certificates in JSON/CSV.

## Phase 3 - cardinality and encoding study

- Provide one exactly-one interface and test pairwise, sequential counter,
  bitwise/binary, commander, product, ladder, cardinality network, and totalizer
  implementations only where their semantics fit.
- Inspect the pinned PySAT API before mapping an encoding name. Implement missing
  commander/product variants locally only with truth-table and brute-force tests.
- Separate ALO (normally one disjunction) from AMO; do not invent matching ALO
  variants merely for a symmetric experiment table.
- Compare logical equivalence first, then CNF size/build time/solve time.

## Phase 4 - exact solver comparison

- Add CP-SAT first because it is reproducible without a commercial license.
- Add optional Gurobi MIP, CPLEX MIP, and CP Optimizer adapters with import and
  license probes. Missing products return `UNAVAILABLE`, never fabricated data.
- Add Z3 only as a clearly labeled research extension.
- Normalise timeout, status, incumbent, best bound, runtime, and certificate
  validation as far as each API permits.

## Phase 5 - high-value optimisation research

- Implement RCM as a fast deterministic upper-bound baseline.
- Reproduce the BMP paper's DRSA dual representation, three perturbation
  operators, and evaluation function only after documenting every parameter and
  verifying the implementation on small instances.
- Test four controlled SAT conditions: baseline, heuristic upper bound, symmetry
  breaking, and both. Treat heuristic output only as an incumbent.
- Investigate reversal symmetry first because it holds for every BMP instance;
  graph-automorphism constraints require an orbit-preservation argument.
- Consider MB-ID/MB-PS only after the mandatory SAT and exact-solver comparison
  is stable.

## Phase 6 - experimental evaluation

- Curate, checksum, and document public benchmark provenance; never relabel
  generated graphs as standard benchmarks.
- Use fixed seeds, machine/library metadata, per-instance timeouts, and append-only
  raw records. Aggregate in a separate step.
- Produce runtime/size comparisons, solved-to-optimality curves, ablations, and
  performance profiles only from observed data. Evaluate `cnsplots` against its
  installed official API before adopting it.

## Phase 7 - report and release

- Freeze configurations and selected result tables/figures needed to reproduce
  the Elsevier `cas-sc` report.
- Audit claims against statuses and certificates, document unavailable licensed
  solvers, and publish repository and data-availability details.
- Tag a reproducible release after CI, clean-room installation, and benchmark
  regeneration checks pass.
