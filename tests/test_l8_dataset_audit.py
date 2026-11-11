from __future__ import annotations

import gzip
import hashlib
import pytest

from scripts.audit_l8_dataset import classify


def test_general_asymmetric_values_and_pattern_remain_unverified(tmp_path):
    # A(1,2) and A(2,1) disagree in value; (2,3) has no mirror.
    # Both triangles occur, so this is not half-triangle storage.
    source = tmp_path / "case.mtx.gz"
    raw = ("%%MatrixMarket matrix coordinate real general\n"
           "4 4 4\n1 2 2\n2 1 3\n2 3 4\n4 4 1\n")
    source.write_bytes(gzip.compress(raw.encode()))
    record = {
        "instance": "case", "file_path": str(source),
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "source_url": "https://math.nist.gov/pub/MatrixMarket2/Harwell-Boeing/x/case.mtx.gz",
        "validation_status": "NEEDS_VERIFICATION", "paper_n": 4,
        "n": 4, "m": 2, "components": 2, "largest_component": 3,
    }
    row = classify(record)
    assert row["structural_symmetry"] is False
    assert row["value_symmetry"] is False
    assert row["triangular_only"] is False
    assert row["one_sided_edge_pairs"] == 1
    assert row["converted_graph_n"] == 4
    assert row["converted_graph_m"] == 2
    assert row["isolated_vertices_1_based"] == "4"
    assert row["validation_decision"] == "NEEDS_VERIFICATION"
    source.write_bytes(gzip.compress(raw.replace("2 3 4", "2 3 5").encode()))
    with pytest.raises(ValueError, match="Raw checksum mismatch"):
        classify(record)
