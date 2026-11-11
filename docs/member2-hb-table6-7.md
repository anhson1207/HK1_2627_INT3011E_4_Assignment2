# Member 2: Harwell–Boeing Official 113-Instance Catalog & Legacy Note

## Official Dataset Policy (Post-M2.1 Sync)

Following Leader L8 synchronization (`dev/leader` -> `dev/member-2`), the sole official benchmark catalog for Member 2 experiments is **Leader's 113-instance catalog** (`bmp.core.benchmark_catalog.ALL_INSTANCES`, populated from `official_paper_results.csv`):

- **Table 6**: 31 instances
- **Table 7**: 41 instances
- **Table 8**: 41 instances
- **L8 Provenance Audit (`data/benchmark_provenance.json`)**:
  - **54 `READY`** (verified structurally symmetric or fully mirrored nonzeros)
  - **58 `NEEDS_VERIFICATION`** (general unsymmetric coordinate storage without published edge-list rule)
  - **1 `INVALID_DATA`** (`mbeause`, 496 vs 492 vertex discrepancy)

`bmp.experiments.member2_hb` enforces this policy strictly:
- Non-`READY` instances are automatically recorded as `SKIPPED` (`Dataset status is not READY`) and never benchmarked as official results.
- Raw verified matrices live under `data/benchmarks/raw/` (acquired via `python scripts/acquire_benchmark.py`) and are checked against SHA-256 provenance and `inspect_matrix_market`.
- SAT runs use Leader's exact `estimate_cnf_size`, `ResourceLimits`, and bounded worker/subprocess timeout controls with explicit `incumbent_source` tracking (`sat`, `initial`, `heuristic`) and RSS sampling.

## Commands

```bash
# Acquire and verify raw NIST Harwell-Boeing matrices (113 catalog):
python scripts/acquire_benchmark.py --max-instances 113

# Pilot single READY instance (e.g. bcspwr01):
python -m bmp.experiments.member2_hb configs/member2_hb_table6_7.toml --instance bcspwr01

# Run full resumable official benchmark (READY instances only):
python -m bmp.experiments.member2_hb configs/member2_hb_table6_7.toml
```

## Legacy 72-Instance Subset (`data/hb_table6_7/`)

The earlier `data/hb_table6_7/` snapshot (72 instances: 31 from Table 6 and 41 from Table 7), along with `scripts/extract_hb_manifest.py` and `scripts/fetch_hb.py`, is **deprecated as an official benchmark source**. It omitted all 41 Table 8 rows and automatically converted 32 `NEEDS_VERIFICATION` unsymmetric matrices via edge union. Those files remain untouched solely for historical reproducibility (`tests/test_member2_hb_data.py`) and are excluded from default benchmarking.
