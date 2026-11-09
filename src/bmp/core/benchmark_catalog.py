"""Catalog and preflight verification for Harwell-Boeing benchmark instances (Table 6 & 7)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from bmp.core.graph import Graph
from bmp.io.readers import read_graph


@dataclass(frozen=True, slots=True)
class BenchmarkInstanceMeta:
    """Metadata for a benchmark instance documented in BMP reference paper."""

    name: str
    n: int
    paper_lb: int
    paper_best: int
    category: str  # 'small' (Table 6) or 'large' (Table 7/8)


# Table 6 instances from Torres-Jimenez et al. (2015), Information Sciences 303, pp. 33-49
TABLE_6_INSTANCES: dict[str, BenchmarkInstanceMeta] = {
    "arc130": BenchmarkInstanceMeta("arc130", 130, 63, 63, "small"),
    "ash85": BenchmarkInstanceMeta("ash85", 85, 9, 9, "small"),
    "bcspwr01": BenchmarkInstanceMeta("bcspwr01", 39, 5, 5, "small"),
    "bcspwr02": BenchmarkInstanceMeta("bcspwr02", 49, 7, 7, "small"),
    "bcspwr03": BenchmarkInstanceMeta("bcspwr03", 118, 9, 10, "small"),
    "bcsstk01": BenchmarkInstanceMeta("bcsstk01", 48, 16, 16, "small"),
    "bcsstk04": BenchmarkInstanceMeta("bcsstk04", 132, 36, 37, "small"),
    "bcsstk05": BenchmarkInstanceMeta("bcsstk05", 153, 19, 20, "small"),
    "bcsstk22": BenchmarkInstanceMeta("bcsstk22", 138, 9, 10, "small"),
    "can_144": BenchmarkInstanceMeta("can_144", 144, 13, 13, "small"),
    "can_161": BenchmarkInstanceMeta("can_161", 161, 18, 18, "small"),
    "curtis54": BenchmarkInstanceMeta("curtis54", 54, 10, 10, "small"),
    "dwt_234": BenchmarkInstanceMeta("dwt_234", 234, 11, 11, "small"),
    "fs_183_1": BenchmarkInstanceMeta("fs_183_1", 183, 52, 60, "small"),
    "gent113": BenchmarkInstanceMeta("gent113", 113, 25, 27, "small"),
    "gre_115": BenchmarkInstanceMeta("gre_115", 115, 20, 23, "small"),
    "gre_185": BenchmarkInstanceMeta("gre_185", 185, 17, 21, "small"),
    "ibm32": BenchmarkInstanceMeta("ibm32", 32, 11, 11, "small"),
    "impcol_b": BenchmarkInstanceMeta("impcol_b", 59, 19, 20, "small"),
    "impcol_c": BenchmarkInstanceMeta("impcol_c", 137, 23, 30, "small"),
    "lns_131": BenchmarkInstanceMeta("lns_131", 131, 18, 20, "small"),
    "lund_a": BenchmarkInstanceMeta("lund_a", 147, 19, 23, "small"),
    "lund_b": BenchmarkInstanceMeta("lund_b", 147, 19, 23, "small"),
    "mcca": BenchmarkInstanceMeta("mcca", 180, 32, 37, "small"),
    "nos4": BenchmarkInstanceMeta("nos4", 100, 10, 10, "small"),
    "pores_1": BenchmarkInstanceMeta("pores_1", 30, 7, 7, "small"),
    "steam3": BenchmarkInstanceMeta("steam3", 80, 7, 7, "small"),
    "west0132": BenchmarkInstanceMeta("west0132", 132, 23, 32, "small"),
    "west0156": BenchmarkInstanceMeta("west0156", 156, 33, 36, "small"),
    "west0167": BenchmarkInstanceMeta("west0167", 167, 31, 34, "small"),
    "will199": BenchmarkInstanceMeta("will199", 199, 55, 64, "small"),
    "will57": BenchmarkInstanceMeta("will57", 57, 6, 6, "small"),
}

# Representative subset of large instances from Table 7 & 8
TABLE_7_INSTANCES: dict[str, BenchmarkInstanceMeta] = {
    "494_bus": BenchmarkInstanceMeta("494_bus", 494, 25, 28, "large"),
    "662_bus": BenchmarkInstanceMeta("662_bus", 662, 36, 39, "large"),
    "685_bus": BenchmarkInstanceMeta("685_bus", 685, 30, 32, "large"),
    "ash292": BenchmarkInstanceMeta("ash292", 292, 16, 19, "large"),
    "bcspwr04": BenchmarkInstanceMeta("bcspwr04", 274, 23, 24, "large"),
    "bcspwr05": BenchmarkInstanceMeta("bcspwr05", 443, 25, 27, "large"),
    "bcsstk06": BenchmarkInstanceMeta("bcsstk06", 420, 38, 45, "large"),
    "can_292": BenchmarkInstanceMeta("can_292", 292, 34, 38, "large"),
    "dwt_209": BenchmarkInstanceMeta("dwt_209", 209, 21, 23, "large"),
    "dwt_221": BenchmarkInstanceMeta("dwt_221", 221, 12, 13, "large"),
    "dwt_245": BenchmarkInstanceMeta("dwt_245", 245, 21, 21, "large"),
    "dwt_310": BenchmarkInstanceMeta("dwt_310", 310, 11, 12, "large"),
    "dwt_361": BenchmarkInstanceMeta("dwt_361", 361, 14, 14, "large"),
    "dwt_419": BenchmarkInstanceMeta("dwt_419", 419, 23, 25, "large"),
    "dwt_503": BenchmarkInstanceMeta("dwt_503", 503, 29, 41, "large"),
    "gre_216a": BenchmarkInstanceMeta("gre_216a", 216, 17, 21, "large"),
    "nos1": BenchmarkInstanceMeta("nos1", 237, 3, 3, "large"),
    "steam1": BenchmarkInstanceMeta("steam1", 240, 32, 44, "large"),
}


@dataclass(frozen=True, slots=True)
class PreflightReport:
    """Outcome of preflight check for benchmark instances."""

    total_expected: int
    found_count: int
    missing_count: int
    valid_count: int
    invalid_count: int
    missing_instances: tuple[str, ...]
    verified_instances: tuple[str, ...]
    errors: tuple[str, ...]

    @property
    def ready_for_execution(self) -> bool:
        return self.missing_count == 0 and self.invalid_count == 0


def verify_instance_file(
    file_path: Path,
    expected_meta: BenchmarkInstanceMeta | None = None,
) -> tuple[bool, Graph | None, str | None]:
    """Verify that an instance file exists, parses correctly, and matches metadata."""
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

    Checks existence, integrity, and vertex counts against the reference catalog.
    """
    if catalog is None:
        catalog = TABLE_6_INSTANCES

    found: list[str] = []
    missing: list[str] = []
    valid: list[str] = []
    invalid: list[str] = []
    errors: list[str] = []

    for name, meta in catalog.items():
        # Look for <name>.mtx, <name>.edgelist, or <name>.csv
        candidates = [
            directory / f"{name}.mtx",
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
        missing_instances=tuple(sorted(missing)),
        verified_instances=tuple(sorted(valid)),
        errors=tuple(errors),
    )


__all__ = [
    "BenchmarkInstanceMeta",
    "PreflightReport",
    "TABLE_6_INSTANCES",
    "TABLE_7_INSTANCES",
    "preflight_check_dataset",
    "verify_instance_file",
]
