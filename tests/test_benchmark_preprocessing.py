from __future__ import annotations

import gzip
from pathlib import Path

from bmp.io.readers import inspect_matrix_market


def test_symmetric_triangle_keeps_isolates_and_removes_diagonal(tmp_path: Path) -> None:
    path = tmp_path / "small.mtx.gz"
    content = "%%MatrixMarket matrix coordinate pattern symmetric\n4 4 3\n1 1\n2 1\n3 2\n"
    path.write_bytes(gzip.compress(content.encode()))
    audit = inspect_matrix_market(path)
    assert audit.status == "READY"
    assert audit.graph.vertices == (0, 1, 2, 3)
    assert audit.graph.edges == {(0, 1), (1, 2)}
    assert audit.diagonal_entries_removed == 1


def test_unsymmetric_and_duplicate_source_needs_verification(tmp_path: Path) -> None:
    path = tmp_path / "general.mtx"
    path.write_text("%%MatrixMarket matrix coordinate pattern general\n3 3 3\n1 2\n1 2\n2 3\n")
    audit = inspect_matrix_market(path)
    assert audit.status == "NEEDS_VERIFICATION"
    assert audit.asymmetric_pairs == 2
    assert audit.duplicate_entries == 1
    assert audit.graph.edges == {(0, 1), (1, 2)}
