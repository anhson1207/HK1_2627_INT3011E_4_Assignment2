"""Readers that normalise external graph data to :class:`bmp.core.Graph`."""

from __future__ import annotations

import csv
import gzip
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from bmp.core.graph import Graph

GraphFormat = Literal["auto", "edge-list", "adjacency-matrix", "matrix-market"]
ConversionPolicy = Literal[
    "nonzero_union",
    "stored_union",
    "nonzero_intersection",
    "stored_intersection",
    "triangular_lower",
    "triangular_upper",
]

OFFICIAL_CONVERSION_POLICY: str = "nonzero_union"
CONVERSION_VERSION: str = "1.0"
SUPPORTED_CONVERSION_POLICIES: tuple[str, ...] = (
    "nonzero_union",
    "stored_union",
    "nonzero_intersection",
    "stored_intersection",
    "triangular_lower",
    "triangular_upper",
)


def compute_topology_sha256(graph: Graph) -> str:
    """Return canonical index-normalised SHA-256 over graph order and edge set.

    Maps vertex identifiers in declaration order ``graph.vertices`` to
    ``0..n-1`` so ``0``-based and ``1``-based adapters yield an identical
    undirected topology digest while remaining sensitive to vertex additions,
    removals, reordering, or edge edits.
    """

    vertex_index = {vertex: idx for idx, vertex in enumerate(graph.vertices)}
    normalised_edges = sorted(
        (min(vertex_index[u], vertex_index[v]), max(vertex_index[u], vertex_index[v]))
        for u, v in graph.edges
    )
    payload_lines = [f"bmp-topology-v1|{graph.order}|{graph.size}"]
    payload_lines.extend(f"{u} {v}" for u, v in normalised_edges)
    return hashlib.sha256("\n".join(payload_lines).encode("utf-8")).hexdigest()


def compute_graph_fingerprint(
    graph: Graph,
    *,
    conversion_policy: str | None = None,
    conversion_version: str = CONVERSION_VERSION,
) -> str:
    """Return a deterministic SHA-256 fingerprint bound to graph topology & policy."""

    policy = conversion_policy or str(
        graph.metadata.get("conversion_policy") or OFFICIAL_CONVERSION_POLICY
    )
    topology_sha = compute_topology_sha256(graph)
    payload = f"bmp-graph-v1|{policy}|{conversion_version}|{topology_sha}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _meaningful_lines(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip() and not line.lstrip().startswith(("#", "%"))
    ]


def read_edge_list(path: str | Path) -> Graph:
    """Read an integer edge list with an optional DIMACS-style header.

    A header ``p edge N M`` declares vertices ``1..N`` and preserves isolated
    vertices. Edge records may be ``u v`` or ``e u v``.
    """

    source = Path(path)
    declared_n: int | None = None
    declared_m: int | None = None
    edges: list[tuple[int, int]] = []
    observed: set[int] = set()

    for line_number, raw in enumerate(source.read_text(encoding="utf-8-sig").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith(("#", "%", "c ")):
            continue
        fields = line.split()
        if fields[0].lower() == "p":
            if len(fields) != 4 or fields[1].lower() not in {"edge", "edges"}:
                raise ValueError(f"Invalid edge-list header at line {line_number}: {line}")
            declared_n, declared_m = int(fields[2]), int(fields[3])
            if declared_n < 0 or declared_m < 0:
                raise ValueError("Declared graph sizes cannot be negative")
            continue
        if fields[0].lower() == "e":
            fields = fields[1:]
        if len(fields) != 2:
            raise ValueError(f"Expected two endpoints at line {line_number}: {line}")
        u, v = (int(value) for value in fields)
        edges.append((u, v))
        observed.update((u, v))

    if declared_n is None:
        if not observed:
            raise ValueError("An empty edge list needs a 'p edge N 0' header")
        vertices = tuple(sorted(observed))
    else:
        vertices = tuple(range(1, declared_n + 1))
        outside = observed - set(vertices)
        if outside:
            raise ValueError(f"Endpoints outside declared range 1..{declared_n}: {sorted(outside)}")
        if declared_m is not None and len(edges) != declared_m:
            raise ValueError(f"Header declares {declared_m} records but file contains {len(edges)}")

    graph = Graph.from_edges(
        vertices,
        edges,
        name=source.stem,
        metadata={
            "source": source.name,
            "format": "edge-list",
            "conversion_policy": "edge_list",
            "conversion_version": CONVERSION_VERSION,
        },
    )
    return Graph(
        graph.vertices,
        graph.edges,
        graph.name,
        {
            **graph.metadata,
            "topology_sha256": compute_topology_sha256(graph),
            "graph_fingerprint": compute_graph_fingerprint(graph),
        },
    )


def read_adjacency_matrix(path: str | Path) -> Graph:
    """Read a square, symmetric, zero-diagonal CSV or whitespace matrix."""

    source = Path(path)
    lines = _meaningful_lines(source)
    matrix: list[list[float]] = []
    for line_number, line in enumerate(lines, start=1):
        fields = next(csv.reader([line])) if "," in line else line.split()
        try:
            matrix.append([float(value.strip()) for value in fields])
        except ValueError as error:
            raise ValueError(f"Non-numeric matrix entry at data line {line_number}") from error

    order = len(matrix)
    if any(len(row) != order for row in matrix):
        raise ValueError("Adjacency matrix must be square")
    if any(matrix[index][index] != 0 for index in range(order)):
        raise ValueError("Adjacency matrix diagonal must be zero")
    for row in range(order):
        for column in range(row + 1, order):
            if (matrix[row][column] != 0) != (matrix[column][row] != 0):
                raise ValueError("Adjacency matrix must be symmetric")

    edges = [
        (row + 1, column + 1)
        for row in range(order)
        for column in range(row + 1, order)
        if matrix[row][column] != 0
    ]
    graph = Graph.from_edges(
        range(1, order + 1),
        edges,
        name=source.stem,
        metadata={
            "source": source.name,
            "format": "adjacency-matrix",
            "conversion_policy": "adjacency_matrix",
            "conversion_version": CONVERSION_VERSION,
        },
    )
    return Graph(
        graph.vertices,
        graph.edges,
        graph.name,
        {
            **graph.metadata,
            "topology_sha256": compute_topology_sha256(graph),
            "graph_fingerprint": compute_graph_fingerprint(graph),
        },
    )


@dataclass(frozen=True, slots=True)
class MatrixMarketAudit:
    graph: Graph
    rows: int
    columns: int
    declared_entries: int
    diagonal_entries_removed: int
    duplicate_entries: int
    asymmetric_pairs: int
    symmetry: str
    status: str


@dataclass(frozen=True, slots=True)
class MatrixMarketForensics:
    """Detailed forensic audit of a coordinate Matrix Market file."""

    source_name: str
    header_object: str
    header_format: str
    field: str
    symmetry: str
    rows: int
    columns: int
    declared_entries: int
    diagonal_entries_total: int
    diagonal_entries_nonzero: int
    diagonal_entries_zero: int
    offdiagonal_entries_total: int
    offdiagonal_entries_nonzero: int
    offdiagonal_entries_zero: int
    explicit_zero_entries_total: int
    duplicate_entries_total: int
    duplicate_offdiagonal_nonzero: int
    duplicate_offdiagonal_all: int
    asymmetric_pairs_nonzero: int
    asymmetric_pairs_stored: int
    lower_triangular_nonzero: int
    upper_triangular_nonzero: int
    structural_symmetry_nonzero: float
    structural_symmetry_stored: float
    value_symmetry_nonzero: float
    status: str
    directed_nonzero: frozenset[tuple[int, int]]
    directed_stored: frozenset[tuple[int, int]]
    one_based_edges_by_policy: dict[str, frozenset[tuple[int, int]]]


def _read_matrix_market_lines(path: str | Path) -> tuple[str, list[str]]:
    source = Path(path)
    if source.suffix.lower() == ".gz":
        with gzip.open(source, "rt", encoding="utf-8-sig") as stream:
            raw_lines = stream.read().splitlines()
    else:
        raw_lines = source.read_text(encoding="utf-8-sig").splitlines()
    return source.name, raw_lines


def _edges_for_policy(
    directed_nonzero: frozenset[tuple[int, int]],
    directed_stored: frozenset[tuple[int, int]],
    *,
    symmetry: str,
    policy: str,
) -> frozenset[tuple[int, int]]:
    if policy not in SUPPORTED_CONVERSION_POLICIES:
        raise ValueError(
            f"Unsupported Matrix Market conversion policy {policy!r}; expected one of {SUPPORTED_CONVERSION_POLICIES}"
        )
    if policy == "nonzero_union":
        return frozenset((min(r, c), max(r, c)) for r, c in directed_nonzero)
    if policy == "stored_union":
        return frozenset((min(r, c), max(r, c)) for r, c in directed_stored)
    if policy == "nonzero_intersection":
        if symmetry != "general":
            return frozenset((min(r, c), max(r, c)) for r, c in directed_nonzero)
        return frozenset((min(r, c), max(r, c)) for r, c in directed_nonzero if (c, r) in directed_nonzero)
    if policy == "stored_intersection":
        if symmetry != "general":
            return frozenset((min(r, c), max(r, c)) for r, c in directed_stored)
        return frozenset((min(r, c), max(r, c)) for r, c in directed_stored if (c, r) in directed_stored)
    if policy == "triangular_lower":
        return frozenset((min(r, c), max(r, c)) for r, c in directed_nonzero if r > c)
    # triangular_upper
    return frozenset((min(r, c), max(r, c)) for r, c in directed_nonzero if r < c)


def parse_matrix_market_forensics(raw_lines: list[str], *, source_name: str = "<memory>") -> MatrixMarketForensics:
    """Parse coordinate Matrix Market lines once into complete forensic metadata."""

    if not raw_lines:
        raise ValueError("Matrix Market file is empty")
    banner = raw_lines[0].strip().lower().split()
    if len(banner) != 5 or banner[:3] != ["%%matrixmarket", "matrix", "coordinate"]:
        raise ValueError("Only coordinate Matrix Market matrices are supported")
    field, symmetry = banner[3], banner[4]
    if field not in {"pattern", "integer", "real", "complex"}:
        raise ValueError(f"Unsupported Matrix Market field: {field}")
    if symmetry not in {"general", "symmetric", "hermitian", "skew-symmetric"}:
        raise ValueError(f"Unsupported Matrix Market symmetry: {symmetry}")

    data = [line.strip() for line in raw_lines[1:] if line.strip() and not line.lstrip().startswith("%")]
    if not data:
        raise ValueError("Matrix Market size record is missing")
    rows, columns, declared_entries = (int(value) for value in data[0].split())
    if rows != columns:
        raise ValueError("Graph adjacency matrix must be square")
    records = data[1:]
    if len(records) != declared_entries:
        raise ValueError(
            f"Header declares {declared_entries} entries but file contains {len(records)}"
        )

    directed_nz: set[tuple[int, int]] = set()
    directed_st: set[tuple[int, int]] = set()
    nz_values: dict[tuple[int, int], tuple[float, ...]] = {}
    seen_all: set[tuple[int, int]] = set()
    diag_total = diag_nz = diag_zero = 0
    off_total = off_nz = off_zero = 0
    dup_total = dup_off_all = dup_off_nz = 0
    lower_nz = upper_nz = 0

    for index, record in enumerate(records, start=1):
        values = record.split()
        expected = 2 if field == "pattern" else (4 if field == "complex" else 3)
        if len(values) != expected:
            raise ValueError(f"Invalid Matrix Market entry {index}: {record}")
        row, column = int(values[0]), int(values[1])
        if not (1 <= row <= rows and 1 <= column <= columns):
            raise ValueError(f"Matrix Market entry outside 1..{rows}: {record}")
        parsed_nums = tuple(float(value) for value in values[2:]) if field != "pattern" else ()
        is_zero = field != "pattern" and all(v == 0.0 for v in parsed_nums)
        if (row, column) in seen_all:
            dup_total += 1
        seen_all.add((row, column))

        if row == column:
            diag_total += 1
            if is_zero:
                diag_zero += 1
            else:
                diag_nz += 1
            continue

        off_total += 1
        if (row, column) in directed_st:
            dup_off_all += 1
        directed_st.add((row, column))
        if is_zero:
            off_zero += 1
            continue

        off_nz += 1
        if row > column:
            lower_nz += 1
        else:
            upper_nz += 1
        if (row, column) in directed_nz:
            dup_off_nz += 1
        directed_nz.add((row, column))
        nz_values[(row, column)] = parsed_nums

    if symmetry != "general":
        asym_nz = 0
        asym_st = 0
        sym_nz_ratio = 1.0
        sym_st_ratio = 1.0
        val_sym_ratio = 1.0
    else:
        asym_nz = sum(1 for r, c in directed_nz if (c, r) not in directed_nz)
        asym_st = sum(1 for r, c in directed_st if (c, r) not in directed_st)
        sym_nz_ratio = (
            sum(1 for r, c in directed_nz if (c, r) in directed_nz) / len(directed_nz)
            if directed_nz
            else 1.0
        )
        sym_st_ratio = (
            sum(1 for r, c in directed_st if (c, r) in directed_st) / len(directed_st)
            if directed_st
            else 1.0
        )
        val_sym_ratio = (
            sum(
                1
                for (r, c), vals in nz_values.items()
                if (c, r) in nz_values and nz_values[(c, r)] == vals
            )
            / len(directed_nz)
            if directed_nz
            else 1.0
        )

    status = "READY" if dup_off_nz == 0 and asym_nz == 0 else "NEEDS_VERIFICATION"
    fz_nz = frozenset(directed_nz)
    fz_st = frozenset(directed_st)
    by_policy = {
        policy: _edges_for_policy(fz_nz, fz_st, symmetry=symmetry, policy=policy)
        for policy in SUPPORTED_CONVERSION_POLICIES
    }
    return MatrixMarketForensics(
        source_name=source_name,
        header_object=banner[1],
        header_format=banner[2],
        field=field,
        symmetry=symmetry,
        rows=rows,
        columns=columns,
        declared_entries=declared_entries,
        diagonal_entries_total=diag_total,
        diagonal_entries_nonzero=diag_nz,
        diagonal_entries_zero=diag_zero,
        offdiagonal_entries_total=off_total,
        offdiagonal_entries_nonzero=off_nz,
        offdiagonal_entries_zero=off_zero,
        explicit_zero_entries_total=diag_zero + off_zero,
        duplicate_entries_total=dup_total,
        duplicate_offdiagonal_nonzero=dup_off_nz,
        duplicate_offdiagonal_all=dup_off_all,
        asymmetric_pairs_nonzero=asym_nz,
        asymmetric_pairs_stored=asym_st,
        lower_triangular_nonzero=lower_nz,
        upper_triangular_nonzero=upper_nz,
        structural_symmetry_nonzero=sym_nz_ratio,
        structural_symmetry_stored=sym_st_ratio,
        value_symmetry_nonzero=val_sym_ratio,
        status=status,
        directed_nonzero=fz_nz,
        directed_stored=fz_st,
        one_based_edges_by_policy=by_policy,
    )


def inspect_matrix_market_forensics(path: str | Path) -> MatrixMarketForensics:
    """Audit a coordinate Matrix Market file without mutating raw source data."""

    source_name, raw_lines = _read_matrix_market_lines(path)
    return parse_matrix_market_forensics(raw_lines, source_name=source_name)


def graph_from_matrix_market_forensics(
    forensics: MatrixMarketForensics,
    *,
    policy: str = OFFICIAL_CONVERSION_POLICY,
    one_based: bool = True,
    require_official: bool = False,
) -> Graph:
    """Build a :class:`Graph` under an explicit conversion policy."""

    if policy not in SUPPORTED_CONVERSION_POLICIES:
        raise ValueError(
            f"Unsupported conversion policy {policy!r}; expected one of {SUPPORTED_CONVERSION_POLICIES}"
        )
    if require_official and (policy != OFFICIAL_CONVERSION_POLICY or forensics.status != "READY"):
        raise ValueError(
            f"{forensics.source_name}: refused non-official conversion (policy={policy!r}, status={forensics.status!r})"
        )

    one_based_edges = forensics.one_based_edges_by_policy[policy]
    if one_based:
        vertices = range(1, forensics.rows + 1)
        edges = one_based_edges
    else:
        vertices = range(forensics.rows)
        edges = ((u - 1, v - 1) for u, v in one_based_edges)

    base_name = forensics.source_name.removesuffix(".gz").removesuffix(".mtx")
    official_flag = forensics.status == "READY" and policy == OFFICIAL_CONVERSION_POLICY
    graph = Graph.from_edges(
        vertices,
        edges,
        name=base_name,
        metadata={
            "source": forensics.source_name,
            "format": "matrix-market",
            "conversion_policy": policy,
            "conversion_version": CONVERSION_VERSION,
            "official_benchmark_graph": official_flag,
            "matrix_market_field": forensics.field,
            "matrix_market_symmetry": forensics.symmetry,
            "diagonal_entries_removed": forensics.diagonal_entries_nonzero,
            "diagonal_entries_total": forensics.diagonal_entries_total,
            "explicit_zero_entries": forensics.explicit_zero_entries_total,
            "explicit_offdiagonal_zeros": forensics.offdiagonal_entries_zero,
            "duplicate_entries": forensics.duplicate_offdiagonal_nonzero,
            "asymmetric_pairs": forensics.asymmetric_pairs_nonzero,
        },
    )
    return Graph(
        graph.vertices,
        graph.edges,
        graph.name,
        {
            **graph.metadata,
            "topology_sha256": compute_topology_sha256(graph),
            "graph_fingerprint": compute_graph_fingerprint(graph, conversion_policy=policy),
        },
    )


def convert_matrix_market(
    path: str | Path,
    *,
    policy: str = OFFICIAL_CONVERSION_POLICY,
    one_based: bool = True,
    require_official: bool = False,
) -> Graph:
    """Convert a Matrix Market coordinate file under a declared conversion policy."""

    forensics = inspect_matrix_market_forensics(path)
    return graph_from_matrix_market_forensics(
        forensics,
        policy=policy,
        one_based=one_based,
        require_official=require_official,
    )


def inspect_matrix_market(path: str | Path) -> MatrixMarketAudit:
    """Audit a raw coordinate matrix and form the undirected off-diagonal pattern.

    An unsymmetric pattern is retained as a candidate graph but marked
    NEEDS_VERIFICATION because the paper does not state a conversion rule.
    """

    forensics = inspect_matrix_market_forensics(path)
    graph = graph_from_matrix_market_forensics(
        forensics, policy=OFFICIAL_CONVERSION_POLICY, one_based=False
    )
    return MatrixMarketAudit(
        graph,
        forensics.rows,
        forensics.columns,
        forensics.declared_entries,
        forensics.diagonal_entries_nonzero,
        forensics.duplicate_offdiagonal_nonzero,
        forensics.asymmetric_pairs_nonzero,
        forensics.symmetry,
        forensics.status,
    )


def read_matrix_market(path: str | Path) -> Graph:
    """Read a Matrix Market matrix using the shared audited official parser."""
    return convert_matrix_market(path, policy=OFFICIAL_CONVERSION_POLICY, one_based=True)


def read_graph(path: str | Path, graph_format: GraphFormat = "auto") -> Graph:
    """Read a graph, optionally inferring its format from the suffix."""

    source = Path(path)
    if graph_format == "auto":
        suffix = source.suffix.lower()
        if suffix == ".mtx" or source.name.lower().endswith(".mtx.gz"):
            graph_format = "matrix-market"
        elif suffix in {".csv", ".matrix", ".adj"}:
            graph_format = "adjacency-matrix"
        else:
            graph_format = "edge-list"
    readers = {
        "edge-list": read_edge_list,
        "adjacency-matrix": read_adjacency_matrix,
        "matrix-market": read_matrix_market,
    }
    if graph_format not in readers:
        raise ValueError(f"Unsupported graph format: {graph_format}")
    return readers[graph_format](source)


def write_edge_list(graph: Graph, path: str | Path) -> None:
    """Write a graph in the reproducible project edge-list format."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# {graph.name or 'unnamed graph'}", f"p edge {graph.order} {graph.size}"]
    lines.extend(f"{u} {v}" for u, v in sorted(graph.edges))
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
