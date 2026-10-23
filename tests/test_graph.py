from __future__ import annotations

import unittest

from bmp.core.generators import erdos_renyi_graph, path_graph
from bmp.core.graph import Graph


class GraphTests(unittest.TestCase):
    def test_graph_normalises_and_deduplicates_edges(self) -> None:
        graph = Graph.from_edges([1, 2, 3], [(2, 1), (1, 2), (2, 3)])
        self.assertEqual(graph.edges, frozenset({(1, 2), (2, 3)}))
        self.assertEqual(graph.order, 3)
        self.assertEqual(graph.size, 2)
        self.assertEqual(graph.neighbors(2), frozenset({1, 3}))

    def test_graph_rejects_self_loops_and_unknown_vertices(self) -> None:
        with self.assertRaises(ValueError):
            Graph.from_edges([1], [(1, 1)])
        with self.assertRaises(ValueError):
            Graph.from_edges([1, 2], [(1, 3)])

    def test_random_generator_is_reproducible(self) -> None:
        first = erdos_renyi_graph(8, 0.4, seed=2026)
        second = erdos_renyi_graph(8, 0.4, seed=2026)
        different = erdos_renyi_graph(8, 0.4, seed=2027)
        self.assertEqual(first.edges, second.edges)
        self.assertNotEqual(first.edges, different.edges)

    def test_density(self) -> None:
        self.assertAlmostEqual(path_graph(5).density, 0.4)


if __name__ == "__main__":
    unittest.main()
