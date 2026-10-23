"""Readers that normalise external graph data to :class:`bmp.core.Graph`."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Literal

from bmp.core.graph import Graph

GraphFormat = Literal["auto", "edge-list", "adjacency-matrix", "matrix-market"]


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

    return Graph.from_edges(
        vertices,
        edges,
        name=source.stem,
        metadata={"source": source.name, "format": "edge-list"},
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
    return Graph.from_edges(
        range(1, order + 1),
        edges,
        name=source.stem,
        metadata={"source": source.name, "format": "adjacency-matrix"},
    )


def read_matrix_market(path: str | Path) -> Graph:
    """Read a coordinate Matrix Market file as an unweighted simple graph."""

    source = Path(path)
    raw_lines = source.read_text(encoding="utf-8-sig").splitlines()
    if not raw_lines:
        raise ValueError("Matrix Market file is empty")
    banner = raw_lines[0].strip().lower().split()
    if len(banner) != 5 or banner[:3] != ["%%matrixmarket", "matrix", "coordinate"]:
        raise ValueError("Only coordinate Matrix Market matrices are supported")
    field, symmetry = banner[3], banner[4]
    if field not in {"pattern", "integer", "real"}:
        raise ValueError(f"Unsupported Matrix Market field: {field}")
    if symmetry not in {"general", "symmetric"}:
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

    edges: list[tuple[int, int]] = []
    for index, record in enumerate(records, start=1):
        values = record.split()
        expected = 2 if field == "pattern" else 3
        if len(values) != expected:
            raise ValueError(f"Invalid Matrix Market entry {index}: {record}")
        row, column = int(values[0]), int(values[1])
        if not (1 <= row <= rows and 1 <= column <= columns):
            raise ValueError(f"Matrix Market entry outside 1..{rows}: {record}")
        if field != "pattern" and float(values[2]) == 0:
            continue
        if row == column:
            raise ValueError(f"Self-loop at Matrix Market entry {index}: {record}")
        edges.append((row, column))

    return Graph.from_edges(
        range(1, rows + 1),
        edges,
        name=source.stem,
        metadata={
            "source": source.name,
            "format": "matrix-market",
            "matrix_market_field": field,
            "matrix_market_symmetry": symmetry,
        },
    )


def read_graph(path: str | Path, graph_format: GraphFormat = "auto") -> Graph:
    """Read a graph, optionally inferring its format from the suffix."""

    source = Path(path)
    if graph_format == "auto":
        suffix = source.suffix.lower()
        if suffix == ".mtx":
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
