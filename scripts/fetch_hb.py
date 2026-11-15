"""Download original HB matrices from NIST and make simple undirected graphs."""

import csv
import gzip
import hashlib
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bmp.core.graph import Graph
from bmp.io.readers import write_edge_list

ROOT = "https://math.nist.gov/MatrixMarket/data/Harwell-Boeing/"
BASE = Path(__file__).resolve().parents[1] / "data" / "hb_table6_7"


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)


def links(url):
    response = requests.get(url, timeout=25)
    response.raise_for_status()
    parser = Links()
    parser.feed(response.text)
    return [urljoin(url, href) for href in parser.links]


def key(name):
    return re.sub(r"_+", "_", name).lower()


def index():
    sets = [url for url in links(ROOT) if url.endswith(".html") and "/Harwell-Boeing/" in url]
    mapping = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(links, url): url for url in sets}
        for future in as_completed(futures):
            for url in future.result():
                if url.endswith(".html") and url != futures[future]:
                    stem = Path(url).stem
                    mapping.setdefault(key(stem), []).append(url)
    return mapping


def parse_mtx_gz(raw, name):
    lines = gzip.decompress(raw).decode("ascii").splitlines()
    banner = lines[0].lower().split()
    if banner[:3] != ["%%matrixmarket", "matrix", "coordinate"]:
        raise ValueError(f"Unsupported Matrix Market banner: {lines[0]}")
    field = banner[3]
    data = (line for line in lines[1:] if line.strip() and not line.startswith("%"))
    n, columns, count = map(int, next(data).split())
    if n != columns:
        raise ValueError(f"Non-square matrix: {n} x {columns}")
    edges = set()
    seen = 0
    for line in data:
        parts = line.split()
        row, column = map(int, parts[:2])
        if not (1 <= row <= n and 1 <= column <= n):
            raise ValueError(f"Out-of-range entry: {line}")
        seen += 1
        if row == column:
            continue
        if field == "pattern":
            nonzero = True
        elif field == "complex":
            nonzero = float(parts[2]) != 0 or float(parts[3]) != 0
        else:
            nonzero = float(parts[2]) != 0
        if nonzero:
            edges.add((min(row, column), max(row, column)))
    if seen != count:
        raise ValueError(f"Expected {count} entries, found {seen}")
    return Graph.from_edges(range(1, n + 1), edges, name=name), field, count


def fetch(row, mapping):
    name = row["instance"]
    result = dict(row, source="NIST Matrix Market / Harwell-Boeing", matrix_name="",
                  matrix_url="", sha256="", matrix_entries="", edges="", status="", reason="")
    matches = mapping.get(key(name), [])
    if len(matches) != 1:
        result.update(status="NOT_FOUND", reason=f"NIST index matches: {matches}")
        return result
    page_url = matches[0]
    matrix_name = Path(page_url).stem
    result["matrix_name"] = matrix_name
    matrix_links = [url for url in links(page_url) if url.endswith(".mtx.gz")]
    if len(matrix_links) != 1:
        result.update(status="NOT_FOUND", reason=f"Matrix download links: {matrix_links}")
        return result
    url = matrix_links[0]
    result["matrix_url"] = url
    raw = requests.get(url, timeout=40)
    raw.raise_for_status()
    body = raw.content
    result["sha256"] = hashlib.sha256(body).hexdigest()
    graph, field, entries = parse_mtx_gz(body, name)
    result["matrix_entries"] = entries
    result["edges"] = graph.size
    if graph.order != int(row["n"]):
        result.update(status="SIZE_MISMATCH", reason=f"PDF n={row['n']}; matrix n={graph.order}")
        return result
    raw_dir = BASE / "raw"
    graph_dir = BASE / "graphs"
    raw_dir.mkdir(parents=True, exist_ok=True)
    graph_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / f"{name}.mtx.gz").write_bytes(body)
    write_edge_list(graph, graph_dir / f"{name}.edgelist")
    result["status"] = "VERIFIED"
    return result


def main():
    with (BASE / "manifest.csv").open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))
    mapping = index()
    target = BASE / "sources.csv"
    fields = list(rows[0]) + ["source", "matrix_name", "matrix_url", "sha256",
                              "matrix_entries", "edges", "status", "reason"]
    old = {}
    if target.exists():
        with target.open(newline="", encoding="utf-8") as source:
            old = {row["instance"]: row for row in csv.DictReader(source)}
    for row in rows:
        name = row["instance"]
        if old.get(name, {}).get("status") == "VERIFIED" and (BASE / "graphs" / f"{name}.edgelist").exists():
            continue
        try:
            old[name] = fetch(row, mapping)
        except Exception as exc:
            old[name] = dict(row, source="NIST Matrix Market / Harwell-Boeing", matrix_name="",
                             matrix_url="", sha256="", matrix_entries="", edges="",
                             status="DOWNLOAD_ERROR", reason=f"{type(exc).__name__}: {exc}")
        with target.open("w", newline="", encoding="utf-8") as output:
            writer = csv.DictWriter(output, fieldnames=fields)
            writer.writeheader()
            writer.writerows(old[r["instance"]] for r in rows if r["instance"] in old)
        print(name, old[name]["status"], old[name]["reason"], flush=True)


if __name__ == "__main__":
    main()
