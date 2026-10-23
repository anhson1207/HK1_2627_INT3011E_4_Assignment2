from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bmp.io.readers import read_adjacency_matrix, read_edge_list, read_matrix_market


class ReaderTests(unittest.TestCase):
    def test_edge_list_preserves_isolated_vertices(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "graph.edgelist"
            path.write_text("p edge 4 2\n1 2\n2 3\n", encoding="utf-8")
            graph = read_edge_list(path)
        self.assertEqual(graph.vertices, (1, 2, 3, 4))
        self.assertEqual(graph.edges, frozenset({(1, 2), (2, 3)}))

    def test_adjacency_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "path.csv"
            path.write_text("0,1,0\n1,0,1\n0,1,0\n", encoding="utf-8")
            graph = read_adjacency_matrix(path)
        self.assertEqual(graph.edges, frozenset({(1, 2), (2, 3)}))

    def test_matrix_market_general_collapses_mirrored_entries(self) -> None:
        content = """%%MatrixMarket matrix coordinate pattern general
% path graph
3 3 4
1 2
2 1
2 3
3 2
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "path.mtx"
            path.write_text(content, encoding="utf-8")
            graph = read_matrix_market(path)
        self.assertEqual(graph.edges, frozenset({(1, 2), (2, 3)}))


if __name__ == "__main__":
    unittest.main()
