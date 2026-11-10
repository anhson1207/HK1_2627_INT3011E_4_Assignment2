"""Load the exact Table 6 and 7 Harwell–Boeing instances used by the team."""

import csv
import gzip
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

from bmp.core.graph import Graph
from bmp.io.readers import read_matrix_market


@dataclass(frozen=True, slots=True)
class Instance:
    instance: str
    table_number: int
    n: int
    paper_lb: int
    paper_best: int
    status: str
    source_url: str
    format: str
    sha256: str
    path: str
    matrix_order: str
    reason: str


class HarwellBoeingDataset:
    def __init__(self, directory: str | Path = "data/harwell_boeing") -> None:
        self.directory = Path(directory)
        self._instances: dict[str, Instance] = {}
        with (self.directory / "metadata.csv").open(
            encoding="utf-8", newline=""
        ) as stream:
            for row in csv.DictReader(stream):
                for field in ("table_number", "n", "paper_lb", "paper_best"):
                    row[field] = int(row[field])
                item = Instance(**row)
                if item.instance in self._instances or item.table_number not in (6, 7):
                    raise ValueError(
                        f"Duplicate or out-of-scope instance: {item.instance}"
                    )
                self._instances[item.instance] = item

    def instances(self, table: int | None = None) -> tuple[Instance, ...]:
        if table not in (None, 6, 7):
            raise ValueError("Expected Table 6 or Table 7")
        return tuple(
            item
            for item in self._instances.values()
            if table is None or item.table_number == table
        )

    def metadata(self, name: str) -> Instance:
        return self._instances[name]

    def available(self, name: str) -> bool:
        item = self.metadata(name)
        return item.status == "AVAILABLE" and (self.directory / item.path).is_file()

    def load(self, name: str) -> Graph:
        item = self.metadata(name)
        if item.status == "MISSING":
            raise FileNotFoundError(f"{name}: {item.reason}")
        if item.status != "AVAILABLE":
            raise ValueError(f"{name}: {item.reason}")
        payload = (self.directory / item.path).read_bytes()
        # Checksum áp dụng cho file nén gốc, trước khi chuẩn hóa
        if sha256(payload).hexdigest() != item.sha256:
            raise ValueError(f"{name}: SHA-256 mismatch")
        lines = gzip.decompress(payload).decode("ascii").splitlines()
        if not lines or len(lines[0].split()) != 5:
            raise ValueError(f"{name}: invalid Matrix Market header")
        banner, *body = lines
        records = [
            line.strip()
            for line in body
            if line.strip() and not line.lstrip().startswith("%")
        ]
        if not records:
            raise ValueError(f"{name}: missing Matrix Market dimensions")
        rows, columns, count = map(int, records[0].split())
        if rows != columns or rows != item.n:
            raise ValueError(
                f"{name}: matrix {rows}x{columns} differs from paper n={item.n}"
            )
        if count != len(records) - 1:
            raise ValueError(f"{name}: wrong Matrix Market record count")

        # Loại đường chéo trong bản tạm. Reader của Core giữ các đỉnh và gộp cạnh vô hướng
        field = banner.lower().split()[3]
        retained = []
        for record in records[1:]:
            i, j, *values = record.split()
            row, column = int(i), int(j)
            if not 1 <= row <= rows or not 1 <= column <= columns:
                raise ValueError(f"{name}: out-of-range matrix entry {record}")
            if row == column:
                if len(values) != (0 if field == "pattern" else 1):
                    raise ValueError(f"{name}: invalid diagonal record {record}")
                if values:
                    float(values[0])
            else:
                retained.append(record)

        with TemporaryDirectory() as temporary:
            normalized = Path(temporary) / f"{name}.mtx"
            normalized.write_text(
                "\n".join([banner, f"{rows} {columns} {len(retained)}", *retained]),
                encoding="ascii",
            )
            graph = read_matrix_market(normalized)
        return Graph(
            graph.vertices,
            graph.edges,
            name,
            {
                **graph.metadata,
                "source": item.source_url,
                "sha256": item.sha256,
                "table_number": item.table_number,
                "paper_lb": item.paper_lb,
                "paper_best": item.paper_best,
            },
        )
