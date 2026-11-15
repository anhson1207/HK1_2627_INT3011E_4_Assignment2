"""Integrity checks for the downloaded Table 6 and Table 7 benchmark."""

import csv
import hashlib
from pathlib import Path

from bmp.io.readers import read_graph


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "hb_table6_7"


def test_manifest_and_source_integrity():
    with (DATA / "manifest.csv").open(newline="", encoding="utf-8") as source:
        manifest = list(csv.DictReader(source))
    with (DATA / "sources.csv").open(newline="", encoding="utf-8") as source:
        provenance = list(csv.DictReader(source))
    assert len(manifest) == len(provenance) == 72
    assert sum(row["table"] == "6" for row in manifest) == 31
    assert sum(row["table"] == "7" for row in manifest) == 41
    assert manifest[0]["instance"] == "arc130"
    assert manifest[-1]["instance"] == "gre_343"
    assert len({row["instance"] for row in manifest}) == 72
    for expected, source in zip(manifest, provenance):
        name = expected["instance"]
        assert source["instance"] == name
        assert source["status"] == "VERIFIED"
        assert source["matrix_url"].startswith("https://math.nist.gov/")
        raw = (DATA / "raw" / f"{name}.mtx.gz").read_bytes()
        assert hashlib.sha256(raw).hexdigest() == source["sha256"]
        graph = read_graph(DATA / "graphs" / f"{name}.edgelist")
        assert graph.order == int(expected["n"])
        assert graph.size == int(source["edges"])


def test_ibm32_has_all_vertices_and_deduplicated_undirected_edges():
    graph = read_graph(DATA / "graphs" / "ibm32.edgelist")
    assert graph.order == 32
    assert graph.size == 90
    assert all(u != v and u < v for u, v in graph.edges)
