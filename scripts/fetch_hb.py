"""Download original HB matrices from NIST and make simple undirected graphs."""

import argparse
import csv
import gzip
import hashlib
import re
import shutil
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
PROJECT = Path(__file__).resolve().parents[1]


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


def fetch(row, mapping, base):
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
    matrix_links = sorted({url for url in links(page_url)
                           if Path(url).name.lower() == f"{matrix_name.lower()}.mtx.gz"})
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
    raw_dir = base / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / f"{name}.mtx.gz").write_bytes(body)
    if graph.order != int(row["n"]):
        result.update(status="SIZE_MISMATCH", reason=f"PDF n={row['n']}; matrix n={graph.order}")
        return result
    graph_dir = base / "graphs"
    graph_dir.mkdir(parents=True, exist_ok=True)
    write_edge_list(graph, graph_dir / f"{name}.edgelist")
    result["status"] = "VERIFIED"
    return result


def verified_local(row, source, base):
    name = row["instance"]
    raw = base / "raw" / f"{name}.mtx.gz"
    graph_file = base / "graphs" / f"{name}.edgelist"
    if source.get("status") != "VERIFIED" or not raw.exists() or not graph_file.exists():
        return False
    if hashlib.sha256(raw.read_bytes()).hexdigest() != source.get("sha256"):
        return False
    from bmp.io.readers import read_graph
    graph = read_graph(graph_file)
    return graph.order == int(row["n"]) and graph.size == int(source["edges"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=PROJECT / "data" / "hb_table6_7")
    parser.add_argument("--reuse-from", type=Path)
    args = parser.parse_args()
    base = args.base.resolve()
    with (base / "manifest.csv").open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))
    target = base / "sources.csv"
    fields = list(rows[0]) + ["source", "matrix_name", "matrix_url", "sha256",
                              "matrix_entries", "edges", "status", "reason"]
    old = {}
    if target.exists():
        with target.open(newline="", encoding="utf-8") as source:
            old = {row["instance"]: row for row in csv.DictReader(source)}
    reused = {}
    if args.reuse_from:
        reuse_base = args.reuse_from.resolve()
        with (reuse_base / "sources.csv").open(newline="", encoding="utf-8") as source:
            reused = {row["instance"]: row for row in csv.DictReader(source)}
    pending = [row for row in rows if not verified_local(row, old.get(row["instance"], {}), base)
               and not (row["instance"] in reused and verified_local(row, reused[row["instance"]], args.reuse_from.resolve()))]
    mapping = index() if pending else {}
    for row in rows:
        name = row["instance"]
        if verified_local(row, old.get(name, {}), base):
            continue
        if name in reused and verified_local(row, reused[name], args.reuse_from.resolve()):
            for folder, suffix in (("raw", ".mtx.gz"), ("graphs", ".edgelist")):
                (base / folder).mkdir(parents=True, exist_ok=True)
                shutil.copy2(args.reuse_from.resolve() / folder / f"{name}{suffix}",
                             base / folder / f"{name}{suffix}")
            old[name] = dict(row, **{field: reused[name][field] for field in fields if field not in row})
            print(name, "REUSED", flush=True)
        else:
            try:
                old[name] = fetch(row, mapping, base)
            except Exception as exc:
                old[name] = dict(row, source="NIST Matrix Market / Harwell-Boeing", matrix_name="",
                                 matrix_url="", sha256="", matrix_entries="", edges="",
                                 status="DOWNLOAD_ERROR", reason=f"{type(exc).__name__}: {exc}")
            print(name, old[name]["status"], old[name]["reason"], flush=True)
        with target.open("w", newline="", encoding="utf-8") as output:
            writer = csv.DictWriter(output, fieldnames=fields)
            writer.writeheader()
            writer.writerows(old[r["instance"]] for r in rows if r["instance"] in old)


if __name__ == "__main__":
    main()
