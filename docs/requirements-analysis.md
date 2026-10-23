# Requirements analysis

## Source priority

This project treats the official two-page assignment sheet as normative. The
BMP paper defines the problem and motivates DRSA, but the assignment explicitly
states that this paper is only a BMP problem reference. The supplied Order
Encoding paper studies **Radio Mean Labeling**, not BMP. Its threshold-variable
technique may be adapted only after BMP-specific soundness and completeness are
derived; its radio-mean clauses cannot be copied into this project.

## Mandatory assignment scope for BMP

- Implement a position-based pairwise SAT encoding and a genuine order encoding.
- Experiment with both repeated SAT and incremental SAT for both encodings.
- Compare SAT solving with exact ILP/CP approaches, named in the handout as
  CPLEX CP, CPLEX MIP, Gurobi, and CP-SAT.
- Build actual solver implementations, validate results, and submit a scientific
  report using the provided guidance and Elsevier `cas-sc` template.
- Experiment on larger matrices, publish source and experimental results through
  a repository link for data availability, and use `cnsplots` for report figures.

## Encouraged rather than core BMP requirements

The handout describes binary, commander, product, and sequential-counter AMO/ALO
experiments as encouraged. These belong after the two mandatory BMP encodings
are proved correct. The handout also allows teams to design their own report
structure. DRSA, RCM, simulated annealing, Z3, branch-and-bound, and hybrid
heuristic-to-SAT workflows are scientifically useful extensions, not stated
core deliverables in the official assignment sheet.

## Assumptions requiring instructor confirmation

1. Whether unavailable commercial licenses may be reported as `UNAVAILABLE`
   while keeping reproducible open-source CP-SAT and SAT baselines.
2. Whether “CPLEX CP” specifically means IBM CP Optimizer and which version is
   expected in the comparison.
3. Which large-matrix collection and instance subset will be used for grading;
   the BMP paper's 113 Harwell-Boeing instances are a defensible candidate but
   are not mandated by the assignment sheet.
4. Whether `cnsplots` is compulsory for every figure or only the final report's
   publication styling.
5. Whether solver timeouts and hardware are prescribed, and how timeout results
   should contribute to comparisons.

## Phase 1 boundary

Phase 1 supplies a dependency-free canonical graph model, readers, deterministic
generators, a solver-independent result schema, an independent validator, a
small-instance exact oracle, a command-line workflow, tests, and documentation.
SAT encodings are deliberately deferred rather than represented by placeholders.
