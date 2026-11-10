"""Harwell-Boeing dataset loader integrated with Leader provenance and readers."""

from __future__ import annotations

import csv
import gzip
import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Mapping

from bmp.core.benchmark_catalog import ALL_INSTANCES, BenchmarkInstanceMeta
from bmp.core.bounds import cuthill_mckee_order
from bmp.core.graph import Graph
from bmp.core.validation import calculate_bandwidth
from bmp.io.readers import inspect_matrix_market, read_matrix_market
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


def _open_matrix_market_lines(source: Path) -> list[str]:
    if source.suffix.lower() == ".gz":
        with gzip.open(source, "rt", encoding="ascii") as stream:
            return stream.read().splitlines()
    return source.read_text(encoding="ascii").splitlines()


def compare_matrix_market_conversions(path: str | Path) -> dict[str, object]:
    """Diagnostic-only comparison of explicit-zero rules on a Matrix Market file.

    Returns edge counts, certified lower bounds, and RCM bandwidth under
    ``drop_explicit_zeros`` (project standard) vs ``keep_explicit_zeros``.
    Outputs are marked ``official_benchmark=False`` and must never be used to
    override ``benchmark_provenance.json`` validation status.
    """
    source = Path(path)
    lines = _open_matrix_market_lines(source)
    if not lines or len(lines[0].split()) != 5:
        raise ValueError(f"Invalid Matrix Market header in {source}")
    banner = lines[0].strip().lower().split()
    field, symmetry = banner[3], banner[4]
    records = [
        line.strip()
        for line in lines[1:]
        if line.strip() and not line.lstrip().startswith("%")
    ]
    rows, columns, declared = map(int, records[0].split())
    if rows != columns or declared != len(records) - 1:
        raise ValueError(f"Invalid dimensions or entry count in {source}")

    drop_edges: set[tuple[int, int]] = set()
    keep_edges: set[tuple[int, int]] = set()
    diag = 0
    explicit_off_zeros = 0
    nonzero_off = 0

    for record in records[1:]:
        parts = record.split()
        r, c = int(parts[0]), int(parts[1])
        is_zero = field != "pattern" and all(float(val) == 0 for val in parts[2:])
        if r == c:
            diag += 1
            continue
        edge = (min(r, c), max(r, c))
        keep_edges.add(edge)
        if is_zero:
            explicit_off_zeros += 1
        else:
            nonzero_off += 1
            drop_edges.add(edge)

    variants: dict[str, dict[str, int]] = {}
    for label, edge_set in (
        ("drop_explicit_zeros", drop_edges),
        ("keep_explicit_zeros", keep_edges),
    ):
        g = Graph.from_edges(range(1, rows + 1), edge_set, name=source.stem)
        order = cuthill_mckee_order(g)
        rcm_perm = {v: pos for pos, v in enumerate(reversed(order), start=1)}
        variants[label] = {
            "n": g.order,
            "m": g.size,
            "certified_lower_bound": compute_lower_bound(g),
            "rcm_bandwidth": calculate_bandwidth(g, rcm_perm),
        }

    return {
        "source": source.name,
        "official_benchmark": False,
        "field": field,
        "symmetry": symmetry,
        "declared_entries": declared,
        "diagonal_entries": diag,
        "explicit_off_diagonal_zeros": explicit_off_zeros,
        "nonzero_off_diagonal_entries": nonzero_off,
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

    def load(self, name: str, *, require_ready: bool = False) -> Graph:
        item = self.metadata(name)
        if item.status == "MISSING":
            raise FileNotFoundError(f"{name}: {item.reason}")
        if item.status != "AVAILABLE":
            raise ValueError(f"{name}: {item.reason}")

        payload = (self.directory / item.path).read_bytes()
        if sha256(payload).hexdigest() != item.sha256:
            raise ValueError(f"{name}: SHA-256 mismatch")

        val_status = self.validation_status(name)
        if require_ready and val_status != "READY":
            raise ValueError(
                f"{name}: validation_status={val_status} (refused when require_ready=True)"
            )

        lines = gzip.decompress(payload).decode("ascii").splitlines()
        if not lines or len(lines[0].split()) != 5:
            raise ValueError(f"{name}: invalid Matrix Market header")
        banner, *body = lines
        records = [
            line.strip()
            for line in body
            if line.strip() and not line.lstrip().startswith("%")
        ]
        if not records:
            raise ValueError(f"{name}: missing Matrix Market dimensions")
        rows, columns, count = map(int, records[0].split())
        if rows != columns or rows != item.n:
            raise ValueError(
                f"{name}: matrix {rows}x{columns} differs from paper n={item.n}"
            )
        if count != len(records) - 1:
            raise ValueError(f"{name}: wrong Matrix Market record count")

        # Validate diagonal structure cleanly before passing to audited core reader.
        field = banner.lower().split()[3]
        for record in records[1:]:
            i, j, *values = record.split()
            row, column = int(i), int(j)
            if not 1 <= row <= rows or not 1 <= column <= columns:
                raise ValueError(f"{name}: out-of-range matrix entry {record}")
            if row == column:
                if len(values) != (0 if field == "pattern" else 1):
                    raise ValueError(f"{name}: invalid diagonal record {record}")
                if values:
                    float(values[0])

        with TemporaryDirectory() as temporary:
            temp_path = Path(temporary) / f"{name}.mtx.gz"
            temp_path.write_bytes(payload)
            graph = read_matrix_market(temp_path)

        return Graph(
            graph.vertices,
            graph.edges,
            name,
            {
                **graph.metadata,
                "source": item.source_url,
                "sha256": item.sha256,
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
