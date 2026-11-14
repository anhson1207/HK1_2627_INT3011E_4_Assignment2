"""Download and audit the 113 exact paper-named NIST Harwell-Boeing matrices.

Usage: .venv/bin/python scripts/acquire_benchmark.py --max-instances 113
Raw .mtx.gz files remain ignored by Git. The provenance JSON is trackable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.parse
import urllib.request
from collections import deque
from pathlib import Path

from bmp.core.benchmark_catalog import ALL_INSTANCES
from bmp.io.readers import inspect_matrix_market

INDEX_URL = "https://math.nist.gov/MatrixMarket/matrices.html"
RAW_DIR = Path("data/benchmarks/raw")
OUTPUT = Path("data/benchmark_provenance.json")
TABLE_5_LARGEST = {
    "bcsstk20": 467, "bcsstk22": 110, "dwt_234": 117,
    "gent113": 104, "impcol_a": 206, "jpwh_991": 983,
    "lns_131": 123, "lns_511": 503, "mbeacxc": 487,
    "mbeaflw": 487, "mbeause": 492, "mcca": 168,
    "mcfe": 731, "nos1": 158, "nos2": 638,
    "pores_3": 456, "saylr3": 681, "sherman1": 681,
    "sherman4": 546,
}


def _fetch(url: str, timeout: float, max_bytes: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 BMP-research/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"Source exceeds {max_bytes:,} byte limit")
    return data


def _links(html: str) -> list[str]:
    return re.findall(r'href\s*=\s*["\']?([^"\' >]+)', html, re.IGNORECASE)


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _components(graph) -> tuple[int, int]:
    adjacent = {v: [] for v in graph.vertices}
    for u, v in graph.edges:
        adjacent[u].append(v)
        adjacent[v].append(u)
    unseen = set(graph.vertices)
    sizes = []
    while unseen:
        root = unseen.pop()
        queue = deque([root])
        size = 0
        while queue:
            u = queue.popleft()
            size += 1
            for v in adjacent[u]:
                if v in unseen:
                    unseen.remove(v)
                    queue.append(v)
        sizes.append(size)
    return len(sizes), max(sizes, default=0)


def acquire(*, max_instances: int, timeout: float, max_bytes: int) -> list[dict[str, object]]:
    index = _fetch(INDEX_URL, timeout, 2_000_000).decode("latin1")
    pages = [
        urllib.parse.urljoin(INDEX_URL, link)
        for link in _links(index)
        if "/Harwell-Boeing/" in link and link.endswith(".html")
    ]
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    previous = {}
    if OUTPUT.exists():
        previous = {row["instance"]: row for row in json.loads(OUTPUT.read_text())}
    records: list[dict[str, object]] = []
    for name, meta in list(ALL_INSTANCES.items())[:max_instances]:
        old = previous.get(name)
        if old and old.get("download_status") == "DOWNLOADED":
            old_path = Path(old["file_path"])
            if old_path.exists() and hashlib.sha256(old_path.read_bytes()).hexdigest() == old["sha256"]:
                records.append(old)
                continue
        record: dict[str, object] = {
            "instance": name, "source_table": meta.source_table,
            "paper_n": meta.n, "original_matrix_name": None,
            "source_url": None, "original_format": "Matrix Market coordinate gzip",
            "file_path": None, "sha256": None,
            "download_status": "MISSING_DATA", "validation_status": "MISSING_DATA",
        }
        try:
            matches = [url for url in pages if _key(url.rsplit("/", 1)[-1][:-5]) == _key(name)]
            if len(matches) != 1:
                raise ValueError(f"Expected one NIST index match, found {len(matches)}")
            page_url = matches[0]
            page = _fetch(page_url, timeout, 500_000).decode("latin1")
            compressed = sorted({
                urllib.parse.urljoin(page_url, link)
                for link in _links(page)
                if link.lower().endswith(".mtx.gz")
                and _key(urllib.parse.unquote(link.rsplit("/", 1)[-1]).removesuffix(".mtx.gz")) == _key(name)
            })
            if len(compressed) != 1:
                raise ValueError(f"Expected one Matrix Market download, found {len(compressed)}")
            url = compressed[0]
            original = urllib.parse.unquote(url.rsplit("/", 1)[-1]).removesuffix(".mtx.gz")
            record.update(original_matrix_name=original, source_url=url)
            path = RAW_DIR / f"{name}.mtx.gz"
            data = path.read_bytes() if path.exists() else _fetch(url, timeout, max_bytes)
            if not path.exists():
                path.write_bytes(data)
            record.update(
                file_path=str(path), sha256=hashlib.sha256(data).hexdigest(),
                download_status="DOWNLOADED",
            )
            audit = inspect_matrix_market(path)
            graph = audit.graph
            components, largest = _components(graph)
            record.update(
                n=graph.order, m=graph.size, components=components,
                largest_component=largest, density=graph.density,
                diagonal_entries_removed=audit.diagonal_entries_removed,
                duplicate_entries=audit.duplicate_entries,
                asymmetric_pairs=audit.asymmetric_pairs,
                matrix_symmetry=audit.symmetry,
            )
            if graph.order != meta.n:
                status, reason = "INVALID_DATA", "Vertex count differs from paper"
            elif name in TABLE_5_LARGEST and largest != TABLE_5_LARGEST[name]:
                status, reason = "NEEDS_VERIFICATION", "Largest component differs from paper Table 5"
            elif name not in TABLE_5_LARGEST and components > 1:
                status, reason = "NEEDS_VERIFICATION", "Disconnected graph absent from paper Table 5"
            elif audit.status != "READY":
                status, reason = audit.status, "Asymmetric or duplicate source entries; conversion rule unconfirmed"
            else:
                status, reason = "READY", None
            record.update(validation_status=status, validation_reason=reason)
        except Exception as exc:
            record.update(validation_status="INVALID_DATA" if record["download_status"] == "DOWNLOADED" else "MISSING_DATA", error=f"{type(exc).__name__}: {exc}")
        records.append(record)
        print(f"{len(records):3d}/{max_instances}: {name}: {record['validation_status']}", flush=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    return records


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-instances", type=int, default=113)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--max-bytes", type=int, default=8_000_000)
    options = parser.parse_args()
    acquire(max_instances=options.max_instances, timeout=options.timeout, max_bytes=options.max_bytes)
