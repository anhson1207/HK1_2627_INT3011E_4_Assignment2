"""Paper-verified 113-row benchmark catalog and structural file preflight."""

from __future__ import annotations

from dataclasses import dataclass
import csv
import hashlib
from importlib.resources import files
from pathlib import Path
from typing import Mapping, Sequence

from bmp.core.graph import Graph
from bmp.io.readers import (
    OFFICIAL_CONVERSION_POLICY,
    compute_topology_sha256,
    inspect_matrix_market,
    read_edge_list,
    read_graph,
    read_matrix_market,
)

VALIDATOR_VERSION = "m3.5"
CANONICAL_RAW_DIR = Path("data/benchmarks/raw")
FALLBACK_RAW_DIRS: tuple[Path, ...] = (
    Path("data/hb_table6_7/raw"),
    Path("data/harwell_boeing/raw"),
)


@dataclass(frozen=True, slots=True)
class BenchmarkInstanceMeta:
    """Metadata for a benchmark instance documented in BMP reference paper."""

    name: str
    n: int
    paper_lb: int
    paper_best: int
    category: str  # 'small' (Table 6) or 'large' (Table 7/8)
    source_table: str = ""
    grasp_pr_bandwidth: int | None = None
    grasp_pr_time_s: float | None = None
    sa_bandwidth: int | None = None
    sa_time_s: float | None = None
    vns_bandwidth: int | None = None
    vns_time_s: float | None = None
    drsa_bandwidth: int | None = None
    drsa_time_s: float | None = None
    paper_reference: str = ""


# Values transcribed row by row from the supplied paper, Tables 6-8.
def _load_paper_catalog() -> dict[str, dict[str, BenchmarkInstanceMeta]]:
    catalogs: dict[str, dict[str, BenchmarkInstanceMeta]] = {
        "Table 6": {}, "Table 7": {}, "Table 8": {},
    }
    source = files("bmp.core").joinpath("official_paper_results.csv")
    with source.open("r", encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            name = row["instance"]
            table = row["source_table"]
            if table not in catalogs or name in catalogs[table]:
                raise ValueError(f"Invalid or duplicate benchmark row: {name} in {table}")
            catalogs[table][name] = BenchmarkInstanceMeta(
                name=name, n=int(row["n"]), paper_lb=int(row["published_lb"]),
                paper_best=int(row["published_best"]),
                category="small" if table == "Table 6" else "large",
                source_table=table,
                grasp_pr_bandwidth=int(row["grasp_pr_bandwidth"]),
                grasp_pr_time_s=float(row["grasp_pr_time_s"]),
                sa_bandwidth=int(row["sa_bandwidth"]),
                sa_time_s=float(row["sa_time_s"]),
                vns_bandwidth=int(row["vns_bandwidth"]),
                vns_time_s=float(row["vns_time_s"]),
                drsa_bandwidth=int(row["drsa_bandwidth"]),
                drsa_time_s=float(row["drsa_time_s"]),
                paper_reference=row["paper_reference"],
            )
    actual = tuple(len(catalogs[key]) for key in catalogs)
    if actual != (31, 41, 41):
        raise ValueError(f"Expected 31/41/41 paper rows, got {actual}")
    names = [name for table in catalogs.values() for name in table]
    if len(set(names)) != 113:
        raise ValueError("Benchmark instances must have 113 distinct names")
    return catalogs


_CATALOGS = _load_paper_catalog()
TABLE_6_INSTANCES = _CATALOGS["Table 6"]
TABLE_7_INSTANCES = _CATALOGS["Table 7"]
TABLE_8_INSTANCES = _CATALOGS["Table 8"]
ALL_INSTANCES = {**TABLE_6_INSTANCES, **TABLE_7_INSTANCES, **TABLE_8_INSTANCES}


@dataclass(frozen=True, slots=True)
class PreflightReport:
    """Outcome of preflight check for benchmark instances."""

    total_expected: int
    found_count: int
    missing_count: int
    valid_count: int
    invalid_count: int
    needs_verification_count: int
    missing_instances: tuple[str, ...]
    verified_instances: tuple[str, ...]
    needs_verification_instances: tuple[str, ...]
    errors: tuple[str, ...]

    @property
    def ready_for_execution(self) -> bool:
        return self.missing_count == 0 and self.invalid_count == 0 and self.needs_verification_count == 0


def verify_instance_file(
    file_path: Path,
    expected_meta: BenchmarkInstanceMeta | None = None,
) -> tuple[bool, Graph | None, str | None]:
    """Verify that an instance file parses and matches the published vertex count."""
    if not file_path.exists():
        return False, None, f"File does not exist: {file_path}"

    try:
        graph = read_graph(file_path)
    except Exception as exc:
        return False, None, f"Failed to parse graph {file_path.name}: {exc}"

    if expected_meta is not None:
        if graph.order != expected_meta.n:
            return (
                False,
                graph,
                f"Vertex count mismatch for {expected_meta.name}: parsed {graph.order}, expected {expected_meta.n}",
            )

    return True, graph, None


def preflight_check_dataset(
    directory: Path,
    catalog: Mapping[str, BenchmarkInstanceMeta] | None = None,
) -> PreflightReport:
    """Preflight audit for a directory containing Harwell-Boeing benchmark files.

    Checks existence, syntax, vertex counts, and Matrix Market pattern symmetry.
    Full paper topology validation is recorded in benchmark_provenance.json.
    """
    if catalog is None:
        catalog = TABLE_6_INSTANCES

    found: list[str] = []
    missing: list[str] = []
    valid: list[str] = []
    invalid: list[str] = []
    needs: list[str] = []
    errors: list[str] = []

    for name, meta in catalog.items():
        # Look for <name>.mtx, <name>.edgelist, or <name>.csv
        candidates = [
            directory / f"{name}.mtx",
            directory / f"{name}.mtx.gz",
            directory / f"{name}.edgelist",
            directory / f"{name}.csv",
        ]
        target = next((p for p in candidates if p.exists()), None)
        if target is None:
            missing.append(name)
        else:
            found.append(name)
            is_valid, _, err = verify_instance_file(target, meta)
            if is_valid:
                if target.name.lower().endswith((".mtx", ".mtx.gz")) and inspect_matrix_market(target).status != "READY":
                    needs.append(name)
                else:
                    valid.append(name)
            else:
                invalid.append(name)
                if err:
                    errors.append(err)

    return PreflightReport(
        total_expected=len(catalog),
        found_count=len(found),
        missing_count=len(missing),
        valid_count=len(valid),
        invalid_count=len(invalid),
        needs_verification_count=len(needs),
        missing_instances=tuple(sorted(missing)),
        verified_instances=tuple(sorted(valid)),
        needs_verification_instances=tuple(sorted(needs)),
        errors=tuple(errors),
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_raw_matrix_path(
    instance: str,
    *,
    search_dirs: Sequence[Path] | None = None,
    root: Path | None = None,
) -> Path | None:
    """Resolve the canonical raw Matrix Market file for ``instance``.

    Searches ``data/benchmarks/raw`` first, then legacy fallback directories
    (``data/hb_table6_7/raw``, ``data/harwell_boeing/raw``) without mutating
    existing tracked directories.
    """

    repo_root = Path.cwd() if root is None else Path(root)
    dirs = (CANONICAL_RAW_DIR, *FALLBACK_RAW_DIRS) if search_dirs is None else tuple(search_dirs)
    for rel_or_abs in dirs:
        base = rel_or_abs if rel_or_abs.is_absolute() else repo_root / rel_or_abs
        for suffix in (".mtx.gz", ".mtx"):
            candidate = base / f"{instance}{suffix}"
            if candidate.is_file():
                return candidate
    return None


def audit_raw_copy_parity(
    instance: str,
    *,
    root: Path | None = None,
) -> dict[str, object]:
    """Compare raw SHA-256 hashes across dataset copies and derived edge list."""

    repo_root = Path.cwd() if root is None else Path(root)
    locations = {
        "benchmarks_raw": repo_root / CANONICAL_RAW_DIR,
        "hb_table6_7_raw": repo_root / "data/hb_table6_7/raw",
        "harwell_boeing_raw": repo_root / "data/harwell_boeing/raw",
    }
    hashes: dict[str, str] = {}
    paths: dict[str, str] = {}
    for label, folder in locations.items():
        for suffix in (".mtx.gz", ".mtx"):
            cand = folder / f"{instance}{suffix}"
            if cand.is_file():
                hashes[label] = _file_sha256(cand)
                paths[label] = cand.as_posix()
                break

    distinct_hashes = sorted(set(hashes.values()))
    canonical_path = resolve_raw_matrix_path(instance, root=repo_root)
    edge_path = repo_root / "data/hb_table6_7/graphs" / f"{instance}.edgelist"
    edgelist_matches_nonzero_union: bool | None = None
    if edge_path.is_file() and canonical_path is not None:
        raw_graph = read_matrix_market(canonical_path)
        edge_graph = read_edge_list(edge_path)
        edgelist_matches_nonzero_union = (
            compute_topology_sha256(raw_graph) == compute_topology_sha256(edge_graph)
        )

    return {
        "instance": instance,
        "canonical_path": None if canonical_path is None else canonical_path.as_posix(),
        "copy_paths": paths,
        "copy_sha256": hashes,
        "copy_count": len(hashes),
        "raw_parity_ok": len(distinct_hashes) <= 1,
        "edgelist_path": edge_path.as_posix() if edge_path.is_file() else None,
        "edgelist_matches_nonzero_union": edgelist_matches_nonzero_union,
    }


__all__ = [
    "BenchmarkInstanceMeta",
    "CANONICAL_RAW_DIR",
    "FALLBACK_RAW_DIRS",
    "PreflightReport",
    "TABLE_6_INSTANCES",
    "TABLE_7_INSTANCES",
    "TABLE_8_INSTANCES",
    "ALL_INSTANCES",
    "VALIDATOR_VERSION",
    "audit_raw_copy_parity",
    "preflight_check_dataset",
    "resolve_raw_matrix_path",
    "verify_instance_file",
]
