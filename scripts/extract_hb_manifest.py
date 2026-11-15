"""Extract the requested Table 6 and Table 7 rows from the supplied paper.

Requires pypdf; run with the path to the paper and an output CSV path.
The paper's table captions say 33 and 80, but the requested sections contain
31 and 41 actual data rows respectively.
"""

import csv
import sys
from pathlib import Path

from pypdf import PdfReader


def main() -> None:
    paper = PdfReader(sys.argv[1])
    rows = []
    for table, page_index, first, last in (
        (6, 12, "arc130", "will57"),
        (7, 13, "494_bus", "gre_343"),
    ):
        lines = paper.pages[page_index].extract_text().splitlines()
        section = lines[next(i for i, line in enumerate(lines) if line.startswith(first + " ")):
                        next(i for i, line in enumerate(lines) if line.startswith(last + " ")) + 1]
        for line in section:
            parts = line.split()
            if len(parts) < 12:
                raise ValueError(f"Unexpected table row: {line}")
            name, n, lb, best = parts[:4]
            drsa = parts[10]
            rows.append(dict(instance=name, table=table, n=int(n), LB=int(lb),
                             Best=int(best), DRSA=int(drsa)))
    if len(rows) != 72 or len({r['instance'] for r in rows}) != 72:
        raise ValueError("Expected 72 unique instances")
    target = Path(sys.argv[2])
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=("instance", "table", "n", "LB", "Best", "DRSA"))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows to {target}")


if __name__ == "__main__":
    main()
