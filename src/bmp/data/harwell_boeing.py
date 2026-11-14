"""Harwell-Boeing dataset loader integrated with Leader provenance and readers."""

from __future__ import annotations

import csv
import gzip
import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Mapping

from bmp.core.benchmark_catalog import ALL_INSTANCES, BenchmarkInstanceMeta
from bmp.core.bounds import cuthill_mckee_order
from bmp.core.graph import Graph
from bmp.core.validation import calculate_bandwidth
from bmp.io.readers import (
    CONVERSION_VERSION,
    OFFICIAL_CONVERSION_POLICY,
    graph_from_matrix_market_forensics,
    inspect_matrix_market,
    inspect_matrix_market_forensics,
    parse_matrix_market_forensics,
)
from bmp.solvers.sat.search import compute_lower_bound


@dataclass(frozen=True, slots=True)
class Instance:
    """Metadata row from legacy Member 3 Harwell-Boeing manifest."""

    instance: str
    table_number: int
    n: int
    paper_lb: int
    paper_best: int
    status: str
    source_url: str
    format: str
    sha256: str
    path: str
    matrix_order: str
    reason: str


def load_provenance_index(
    provenance_path: str | Path | None = None,
) -> dict[str, Mapping[str, object]]:
    """Load audited Leader provenance keyed by instance name when present."""
    path = (
        Path(provenance_path)
        if provenance_path is not None
        else Path(__file__).resolve().parents[3] / "data" / "benchmark_provenance.json"
    )
    if not path.is_file():
        return {}
    entries = json.loads(path.read_text(encoding="utf-8"))
    return {
        str(entry["instance"]): entry
        for entry in entries
        if isinstance(entry, dict) and "instance" in entry
    }


def compare_matrix_market_conversions(path: str | Path) -> dict[str, object]:
    """Diagnostic-only comparison of conversion rules on a Matrix Market file.

    Returns edge counts, certified lower bounds, RCM bandwidth, and canonical
    fingerprints under ``drop_explicit_zeros`` (project standard ``nonzero_union``)
    vs exploratory policies (``stored_union``, ``nonzero_intersection``,
    ``stored_intersection``). Outputs are marked ``official_benchmark=False`` and
    must never override ``benchmark_provenance.json`` validation status.
    """
    source = Path(path)
    forensics = inspect_matrix_market_forensics(source)

    variants: dict[str, dict[str, object]] = {}
    for label, policy in (
        ("drop_explicit_zeros", "nonzero_union"),
        ("keep_explicit_zeros", "stored_union"),
        ("nonzero_intersection", "nonzero_intersection"),
        ("stored_intersection", "stored_intersection"),
    ):
        g = graph_from_matrix_market_forensics(forensics, policy=policy, one_based=True)
        order = cuthill_mckee_order(g)
        rcm_perm = {v: pos for pos, v in enumerate(reversed(order), start=1)}
        variants[label] = {
            "policy": policy,
            "official_benchmark": False,
            "n": g.order,
            "m": g.size,
            "certified_lower_bound": compute_lower_bound(g),
            "rcm_bandwidth": calculate_bandwidth(g, rcm_perm),
            "topology_sha256": g.metadata["topology_sha256"],
            "graph_fingerprint": g.metadata["graph_fingerprint"],
        }

    return {
        "source": source.name,
        "official_benchmark": False,
        "field": forensics.field,
        "symmetry": forensics.symmetry,
        "declared_entries": forensics.declared_entries,
        "diagonal_entries": forensics.diagonal_entries_total,
        "explicit_off_diagonal_zeros": forensics.offdiagonal_entries_zero,
        "nonzero_off_diagonal_entries": forensics.offdiagonal_entries_nonzero,
        "structural_symmetry_nonzero": forensics.structural_symmetry_nonzero,
        "structural_symmetry_stored": forensics.structural_symmetry_stored,
        "value_symmetry_nonzero": forensics.value_symmetry_nonzero,
        "variants": variants,
    }


class HarwellBoeingDataset:
    """Dataset adapter backed by shared catalog, provenance, and audited readers."""

    def __init__(
        self,
        directory: str | Path = "data/harwell_boeing",
        *,
        provenance_path: str | Path | None = None,
    ) -> None:
        self.directory = Path(directory)
        self._provenance = load_provenance_index(provenance_path)
        self._instances: dict[str, Instance] = {}
        with (self.directory / "metadata.csv").open(
            encoding="utf-8", newline=""
        ) as stream:
            for row in csv.DictReader(stream):
                for field in ("table_number", "n", "paper_lb", "paper_best"):
                    row[field] = int(row[field])
                item = Instance(**row)
                if item.instance in self._instances or item.table_number not in (6, 7):
                    raise ValueError(
                        f"Duplicate or out-of-scope instance: {item.instance}"
                    )
                self._instances[item.instance] = item

    def instances(self, table: int | None = None) -> tuple[Instance, ...]:
        if table not in (None, 6, 7):
            raise ValueError("Expected Table 6 or Table 7")
        return tuple(
            item
            for item in self._instances.values()
            if table is None or item.table_number == table
        )

    def metadata(self, name: str) -> Instance:
        return self._instances[name]

    def catalog_meta(self, name: str) -> BenchmarkInstanceMeta | None:
        return ALL_INSTANCES.get(name)

    def validation_status(self, name: str) -> str:
        """Return audited provenance status ('READY', 'NEEDS_VERIFICATION', ...)."""
        item = self.metadata(name)
        prov = self._provenance.get(name)
        if prov is not None and "validation_status" in prov:
            return str(prov["validation_status"])
        matrix_path = self.directory / item.path
        if not matrix_path.is_file():
            return "MISSING"
        return inspect_matrix_market(matrix_path).status

    def ready_instances(self, table: int | None = None) -> tuple[Instance, ...]:
        """Return only instances verified READY in dataset provenance."""
        return tuple(
            item
            for item in self.instances(table)
            if self.validation_status(item.instance) == "READY"
        )

    def available(self, name: str) -> bool:
        item = self.metadata(name)
        return item.status == "AVAILABLE" and (self.directory / item.path).is_file()

    def load(
        self,
        name: str,
        *,
        require_ready: bool = False,
        conversion_policy: str = OFFICIAL_CONVERSION_POLICY,
    ) -> Graph:
        item = self.metadata(name)
        if item.status == "MISSING":
            raise FileNotFoundError(f"{name}: {item.reason}")
        if item.status != "AVAILABLE":
            raise ValueError(f"{name}: {item.reason}")

        matrix_path = self.directory / item.path
        payload = matrix_path.read_bytes()
        if sha256(payload).hexdigest() != item.sha256:
            raise ValueError(f"{name}: SHA-256 mismatch")

        val_status = self.validation_status(name)
        if require_ready and (val_status != "READY" or conversion_policy != OFFICIAL_CONVERSION_POLICY):
            raise ValueError(
                f"{name}: validation_status={val_status}, policy={conversion_policy} (refused when require_ready=True)"
            )

        lines = gzip.decompress(payload).decode("utf-8-sig").splitlines()
        forensics = parse_matrix_market_forensics(lines, source_name=matrix_path.name)
        if forensics.rows != item.n:
            raise ValueError(
                f"{name}: matrix {forensics.rows}x{forensics.columns} differs from paper n={item.n}"
            )
        graph = graph_from_matrix_market_forensics(
            forensics,
            policy=conversion_policy,
            one_based=True,
        )

        return Graph(
            graph.vertices,
            graph.edges,
            name,
            {
                **graph.metadata,
                "source": item.source_url,
                "sha256": item.sha256,
                "conversion_policy": conversion_policy,
                "conversion_version": CONVERSION_VERSION,
                "table_number": item.table_number,
                "paper_lb": item.paper_lb,
                "paper_best": item.paper_best,
                "validation_status": val_status,
            },
        )


__all__ = [
    "HarwellBoeingDataset",
    "Instance",
    "compare_matrix_market_conversions",
    "load_provenance_index",
]
