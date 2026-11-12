"""Integrity of the expanded HB dataset and reused benchmark results."""

import csv
import hashlib
import json
import tomllib
from collections import Counter
from pathlib import Path

from bmp.experiments.member2_hb import audit_legacy, expected_keys, identity, unique_instances
from bmp.io.readers import read_graph


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "hb_table6_7_8"


def rows(path):
    with path.open(newline="", encoding="utf-8") as source:
        return list(csv.DictReader(source))


def test_pdf_manifest_and_downloaded_matrix_integrity():
    manifest = rows(DATA / "manifest.csv")
    original = rows(ROOT / "data" / "hb_table6_7" / "manifest.csv")
    provenance = rows(DATA / "sources.csv")
    assert len(manifest) == len(provenance) == 113
    assert manifest[:72] == original
    assert Counter(row["table"] for row in manifest) == {"6": 31, "7": 41, "8": 41}
    assert len(unique_instances(manifest)) == 113
    assert manifest[72]["instance"] == "gre_512"
    assert manifest[-1]["instance"] == "west0989"
    assert {row["instance"]: row["status"] for row in provenance if row["status"] != "VERIFIED"} == {
        "mbeause": "SIZE_MISMATCH"}
    for item, source in zip(manifest, provenance):
        name = item["instance"]
        assert source["instance"] == name
        assert source["matrix_url"].startswith("https://math.nist.gov/")
        raw = (DATA / "raw" / f"{name}.mtx.gz").read_bytes()
        assert hashlib.sha256(raw).hexdigest() == source["sha256"]
        if source["status"] == "VERIFIED":
            graph = read_graph(DATA / "graphs" / f"{name}.edgelist")
            assert graph.order == int(item["n"])
            assert graph.size == int(source["edges"])
        else:
            assert name == "mbeause"
            assert "PDF n=492; matrix n=496" in source["reason"]
            assert not (DATA / "graphs" / f"{name}.edgelist").exists()


def test_legacy_792_keys_are_complete_and_valid():
    config = tomllib.loads((ROOT / "configs" / "member2_hb_table6_7_8.toml").read_text(encoding="utf-8"))["benchmark"]
    manifest = rows(ROOT / "data" / "hb_table6_7" / "manifest.csv")
    legacy = rows(ROOT / "results" / "member2_hb_table6_7" / "runs.csv")
    audit = audit_legacy(legacy, config, 1, manifest, DATA / "graphs", 60.0)
    assert audit == {"rows": 792, "unique_keys": 792, "duplicates": 0,
                     "missing": 0, "unexpected": 0, "instances": 72}
    assert len(expected_keys(unique_instances(rows(DATA / "manifest.csv")), config, 1)) == 1243
    assert len({identity(row) for row in legacy}) == 792
