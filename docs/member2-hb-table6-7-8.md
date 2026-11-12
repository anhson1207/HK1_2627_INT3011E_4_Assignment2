# Member 2: Harwell–Boeing Tables 6–8

The supplied paper has 31 actual data rows in Table 6, 41 in Table 7, and 41
in Table 8. `data/hb_table6_7_8/manifest.csv` stores all 113 reference rows.
There are 113 unique instance names and no name occurs in two tables. The
first Table 8 row is `gre_512`; the last is `west0989`. The PDF's `mbeaﬂw`
uses a typographic ligature; the matrix name is `mbeaflw`. Blank or dash
reference values remain blank in the manifest. Reference `LB`, `Best`, and
`DRSA` are used only for comparison after solving.

`data/hb_table6_7_8/sources.csv` records the NIST Harwell–Boeing matrix URL,
matrix name, SHA-256, entry count, converted graph edge count, and validation
status. The 72 already verified matrices and graphs were copied from the local
Table 6–7 dataset after checking their hashes and sizes. New matrices were
downloaded from NIST. Conversion keeps all matrix rows as graph vertices,
ignores diagonal and zero-valued entries, and merges off-diagonal entries into
undirected simple edges. It keeps isolated vertices and every component.

`mbeause` is a documented source mismatch: Table 8 states `n=492`, while the
NIST matrix and SuiteSparse `HB/mbeause` are 496×496. The downloaded matrix is
retained in `raw/`, its URL and hash are recorded, and no graph is synthesized
for this row. Its 11 configuration rows are recorded as `UNAVAILABLE`.

The combined config is `configs/member2_hb_table6_7_8.toml`. It uses the same
11 configurations, one repetition, 60-second total wall limit, and CNF/MIP
resource caps as the Table 6–7 config. The original 792 rows were audited by
the runner: 792 distinct expected keys, no duplicates, missing keys, or extra
configurations. Saved assignments were independently checked again. The
combined `runs.csv` began as an exact copy of that local file; the old results
directory remains untouched. The remaining 451 keys belong to Table 8.

Run these commands from the repository root in PowerShell:

```powershell
# Current count, status breakdown, and latest progress.
$r = Import-Csv results/member2_hb_table6_7_8/runs.csv
"$($r.Count) / 1243 lượt đã ghi"
$r | Group-Object status | Select-Object Name,Count
Get-Content results/member2_hb_table6_7_8/benchmark.log -Tail 20

# If the background benchmark has stopped, resume pending keys.
.\.venv\Scripts\python.exe -m bmp.experiments.member2_hb configs/member2_hb_table6_7_8.toml

# Refresh comparison.md and summary.json from the current CSV.
.\.venv\Scripts\python.exe -m bmp.experiments.member2_hb configs/member2_hb_table6_7_8.toml --report-only

# Audit the saved data and print pending-key counts without solving.
.\.venv\Scripts\python.exe -m bmp.experiments.member2_hb configs/member2_hb_table6_7_8.toml --preflight-only
```

Each new result is appended and flushed before the next solve. Rerunning the
benchmark command skips every recorded key, including `TIMEOUT`,
`RESOURCE_LIMIT`, and `UNAVAILABLE`. A valid incumbent remains recorded on a
timeout, and `OPTIMAL` requires a proof. `comparison.md` reports every PDF
reference row, while `summary.json` counts outcomes by table and across unique
instances. The paper's `Best` is a best-known bandwidth, not an optimality
certificate.
