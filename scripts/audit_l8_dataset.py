"""Reproduce the L8 audit from immutable, checksum-verified NIST downloads.

This is diagnostic: it never changes validation statuses or source matrices.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import re
import urllib.request
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from bmp.io.readers import inspect_matrix_market

PROVENANCE = Path("data/benchmark_provenance.json")
OUTPUT = Path("results/leader/l8_dataset_classification.csv")


def _components(n: int, edges: set[tuple[int, int]]) -> list[list[int]]:
    neighbors = [[] for _ in range(n)]
    for u, v in edges:
        neighbors[u].append(v)
        neighbors[v].append(u)
    unseen = set(range(n))
    components = []
    while unseen:
        start = unseen.pop()
        component = [start]
        queue = deque([start])
        while queue:
            for v in neighbors[queue.popleft()]:
                if v in unseen:
                    unseen.remove(v)
                    component.append(v)
                    queue.append(v)
        components.append(component)
    return components


def classify(record: dict) -> dict:
    path = Path(record["file_path"])
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != record["sha256"]:
        raise ValueError(f"Raw checksum mismatch: {record['instance']}")
    with gzip.open(path, "rt", encoding="utf-8-sig") as stream:
        lines = iter(stream)
        banner = next(lines).strip().lower().split()
        if banner[:3] != ["%%matrixmarket", "matrix", "coordinate"]:
            raise ValueError(f"Unexpected format: {record['instance']}")
        field, symmetry = banner[3:]
        size_line = next(line for line in lines if line.strip() and not line.startswith("%"))
        rows, cols, declared_entries = map(int, size_line.split())
        values: dict[tuple[int, int], tuple[float, ...]] = {}
        zero_entries = 0
        duplicates = 0
        for line in lines:
            if not line.strip() or line.startswith("%"):
                continue
            parts = line.split()
            r, c = int(parts[0]), int(parts[1])
            number = tuple(map(float, parts[2:])) if field != "pattern" else (1.0,)
            if all(value == 0 for value in number):
                zero_entries += 1
                continue
            if (r, c) in values:
                duplicates += 1
            values[r, c] = number
    offdiag = {(r, c): value for (r, c), value in values.items() if r != c}
    undirected = {(min(r, c) - 1, max(r, c) - 1) for r, c in offdiag}
    mirrored = sum(1 for r, c in undirected if (r + 1, c + 1) in offdiag and (c + 1, r + 1) in offdiag)
    one_sided = len(undirected) - mirrored
    equal_values = sum(
        1 for r, c in undirected
        if (r + 1, c + 1) in offdiag and (c + 1, r + 1) in offdiag
        and offdiag[r + 1, c + 1] == offdiag[c + 1, r + 1]
    )
    upper = sum(r < c for r, c in offdiag)
    lower = sum(r > c for r, c in offdiag)
    components = _components(rows, undirected)
    isolated = sorted(component[0] + 1 for component in components if len(component) == 1)
    parsed = inspect_matrix_market(path)
    if (parsed.rows, parsed.columns, parsed.graph.size) != (rows, cols, len(undirected)):
        raise ValueError(f"Independent parser disagrees: {record['instance']}")
    if (rows, len(undirected), len(components), max(map(len, components))) != (
        record["n"], record["m"], record["components"], record["largest_component"]
    ):
        raise ValueError(f"L7 provenance disagrees with raw source: {record['instance']}")
    source_page = record["source_url"].replace("/pub/MatrixMarket2/", "/MatrixMarket/data/").removesuffix(".mtx.gz") + ".html"
    if record["validation_status"] == "INVALID_DATA":
        decision = "INVALID_DATA"
        reason = f"Paper Table 8 n={record['paper_n']}; source n={rows}; Table 5 reports total 496 and largest component 492. No validated 492-vertex conversion."
    elif record["validation_status"] == "READY":
        decision = "READY"
        reason = (
            "Declared symmetric triangular storage" if symmetry != "general"
            else "Fully mirrored nonzero pattern in a general matrix"
        )
    else:
        decision = "NEEDS_VERIFICATION"
        reason = (
            f"General/unsymmetric source has {one_sided} one-sided off-diagonal pairs; "
            "paper does not specify union/intersection conversion or publish an edge list."
        )
        if len(components) > 1 and record["instance"] in {"fs_680_1", "fs_760_1"}:
            reason += " Candidate graph is also disconnected but absent from paper Table 5."
    return {
        "instance": record["instance"], "paper_n": record["paper_n"],
        "original_matrix_type": f"Matrix Market {field} {symmetry}",
        "matrix_rows": rows, "matrix_columns": cols, "declared_entries": declared_entries,
        "nonzero_entries": len(values), "explicit_zero_entries": zero_entries,
        "duplicate_nonzero_coordinates": duplicates,
        "upper_nonzeros": upper, "lower_nonzeros": lower,
        "triangular_only": upper == 0 or lower == 0,
        "structural_symmetry": one_sided == 0,
        "mirrored_edge_pairs": mirrored, "one_sided_edge_pairs": one_sided,
        "value_symmetry": "N/A: pattern only" if field == "pattern" else equal_values == len(undirected),
        "equal_value_mirrored_pairs": equal_values,
        "converted_graph_n": rows, "converted_graph_m": len(undirected),
        "converted_graph_components": len(components),
        "converted_graph_largest_component": max(map(len, components)),
        "isolated_vertices_1_based": ";".join(map(str, isolated)),
        "processing_rule": "Candidate only: every nonzero off-diagonal (i,j) gives undirected {i,j}; preserve all n vertices; collapse mirrored coordinates; drop diagonal",
        "evidence_source": source_page,
        "raw_sha256": digest,
        "paper_source": "https://math.nist.gov/~JBernal/DRSA.pdf",
        "validation_decision": decision, "reason": reason,
    }


def nist_metadata(row: dict) -> dict:
    """Read NIST's independent type and structural statistics for cross-checking."""
    url = row["evidence_source"]
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 BMP-research/1.0"})
    with urllib.request.urlopen(request, timeout=20) as response:
        page = response.read(500_001).decode("latin1")
    if len(page) > 500_000:
        raise ValueError(f"NIST page too large: {url}")
    size = re.search(r'(\d+)\s*x\s*(\d+),\s*(\d+)\s*entries\s*</TD>\s*<TD[^>]*>\s*([^<]+)', page, re.I)
    hb = re.search(r'\.([rcp][suhzr]a)\.gz', page, re.I)
    nonzeros_table = re.search(r"A-A[^<]*</TT>.*?</TH>(.*?)</TABLE>", page, re.I | re.S)
    counts = re.findall(r'<TD[^>]*>\s*(\d+)\s*</TD>', nonzeros_table.group(1), re.I) if nonzeros_table else []
    if not size or not hb or len(counts) < 4:
        raise ValueError(f"Could not parse NIST statistics: {url}")
    nist_nnz, nist_diag, nist_lower, nist_upper = map(int, counts[:4])
    matches = (
        int(size.group(1)) == row["matrix_rows"] and int(size.group(2)) == row["matrix_columns"]
        and nist_nnz == row["nonzero_entries"]
        and nist_diag == row["nonzero_entries"] - row["upper_nonzeros"] - row["lower_nonzeros"]
        and nist_lower == row["lower_nonzeros"] and nist_upper == row["upper_nonzeros"]
    )
    return {
        "nist_matrix_type": size.group(4).strip(), "harwell_boeing_type_code": hb.group(1).upper(),
        "nist_page_entries": int(size.group(3)), "nist_nonzeros": nist_nnz,
        "nist_diagonal_nonzeros": nist_diag,
        "nist_lower_nonzeros": nist_lower, "nist_upper_nonzeros": nist_upper,
        "nist_structural_stats_match_raw": matches,
    }


def main(*, offline: bool = False) -> None:
    records = json.loads(PROVENANCE.read_text())
    if len(records) != 113:
        raise ValueError("Expected the complete 113-instance provenance catalog")
    for record in records:
        path = Path(record["file_path"])
        if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError(f"Raw checksum mismatch: {record['instance']}")
    selected = [r for r in records if r["validation_status"] == "NEEDS_VERIFICATION" or r["instance"] == "mbeause"]
    if len(selected) != 59:
        raise ValueError("Expected 58 ambiguous cases and mbeause")
    ready = [r for r in records if r["validation_status"] == "READY"]
    if len(ready) != 54:
        raise ValueError("Expected 54 previously READY instances")
    for record in ready:
        audit = classify(record)
        justified = (
            audit["structural_symmetry"] if record["matrix_symmetry"] == "general"
            else audit["triangular_only"]
        )
        if not justified or audit["duplicate_nonzero_coordinates"]:
            raise ValueError(f"READY preprocessing rule not supported: {record['instance']}")
    rows = [classify(record) for record in selected]
    if not offline:
        with ThreadPoolExecutor(max_workers=8) as pool:
            metadata = list(pool.map(nist_metadata, rows))
        rows = [{**row, **source} for row, source in zip(rows, metadata)]
        if not all(row["nist_structural_stats_match_raw"] for row in rows):
            raise ValueError("NIST structural metadata disagrees with raw source")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(Counter(row["validation_decision"] for row in rows))
    print("Verified all 113 raw SHA-256 checksums")
    print("Rechecked 54 READY patterns: mirrored general or declared symmetric triangle")
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true", help="Skip NIST metadata cross-check")
    main(offline=parser.parse_args().offline)
