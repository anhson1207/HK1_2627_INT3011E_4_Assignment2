"""Extract the actual Table 6, 7, and 8 data rows from the supplied paper.

Requires pypdf; run with the path to the paper and an output CSV path.
The captions say 33 small and 80 large instances; the actual data rows are
31 in Table 6, 41 in Table 7, and 41 in Table 8.
"""

import csv
import sys
import unicodedata
from collections import Counter
from pathlib import Path

from pypdf import PdfReader


def main() -> None:
    paper = PdfReader(sys.argv[1])
    rows = []
    for table, page_index, first, last in (
        (6, 12, "arc130", "will57"),
        (7, 13, "494_bus", "gre_343"),
        (8, 14, "gre_512", "west0989"),
    ):
        lines = paper.pages[page_index].extract_text().splitlines()
        section = lines[next(i for i, line in enumerate(lines) if line.startswith(first + " ")):
                        next(i for i, line in enumerate(lines) if line.startswith(last + " ")) + 1]
        for line in section:
            parts = line.split()
            if len(parts) < 12:
                raise ValueError(f"Unexpected table row: {line}")
            name, n, lb, best = parts[:4]
            name = unicodedata.normalize("NFKC", name)
            drsa = parts[10]
            def optional_int(value):
                return "" if value in ("", "-", "–", "—") else int(value)
            rows.append(dict(instance=name, table=table, n=optional_int(n),
                             LB=optional_int(lb), Best=optional_int(best),
                             DRSA=optional_int(drsa)))
    counts = Counter(r["table"] for r in rows)
    if counts != {6: 31, 7: 41, 8: 41}:
        raise ValueError(f"Unexpected Table 6–8 row counts: {counts}")
    target = Path(sys.argv[2])
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=("instance", "table", "n", "LB", "Best", "DRSA"))
        writer.writeheader()
        writer.writerows(rows)
    duplicates = [name for name, count in Counter(r["instance"] for r in rows).items() if count > 1]
    print(f"Wrote {len(rows)} rows, {len(set(r['instance'] for r in rows))} unique instances to {target}")
    print(f"Per table: {dict(sorted(counts.items()))}; duplicated names: {duplicates}")


if __name__ == "__main__":
    main()
