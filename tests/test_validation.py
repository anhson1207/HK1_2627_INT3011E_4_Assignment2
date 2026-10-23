from __future__ import annotations

import unittest

from bmp.core.generators import edgeless_graph, path_graph
from bmp.core.validation import validate_assignment


class ValidationTests(unittest.TestCase):
    def test_valid_path_and_edgeless_assignments(self) -> None:
        path = path_graph(5)
        report = validate_assignment(path, {vertex: vertex for vertex in path.vertices}, claimed_bandwidth=1)
        self.assertTrue(report.valid)
        self.assertEqual(report.actual_bandwidth, 1)

        empty = edgeless_graph(5)
        empty_report = validate_assignment(
            empty,
            {vertex: vertex for vertex in empty.vertices},
            claimed_bandwidth=0,
        )
        self.assertTrue(empty_report.valid)
        self.assertEqual(empty_report.actual_bandwidth, 0)

    def test_rejects_non_bijection_and_wrong_claim(self) -> None:
        graph = path_graph(3)
        duplicate = validate_assignment(graph, {1: 1, 2: 1, 3: 3})
        self.assertFalse(duplicate.valid)
        self.assertTrue(any("distinct" in error for error in duplicate.errors))

        wrong_objective = validate_assignment(
            graph,
            {1: 1, 2: 2, 3: 3},
            claimed_bandwidth=2,
        )
        self.assertFalse(wrong_objective.valid)
        self.assertEqual(wrong_objective.actual_bandwidth, 1)


if __name__ == "__main__":
    unittest.main()
