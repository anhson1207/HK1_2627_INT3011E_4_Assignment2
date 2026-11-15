"""Real Glucose 4 checks for the team-compatible backend wrapper."""

from __future__ import annotations

import unittest

from bmp.solvers.sat.backends.glucose import GlucoseBackend


class GlucoseBackendTests(unittest.TestCase):
    def test_assumptions_do_not_persist_after_unsat(self) -> None:
        with GlucoseBackend() as backend:
            backend.add_clause([1, 2])
            self.assertFalse(backend.solve(assumptions=[-1, -2]))
            self.assertIsNone(backend.get_model())

            self.assertTrue(backend.solve(assumptions=[-1]))
            model = backend.get_model()
            self.assertIsNotNone(model)
            self.assertIn(-1, model)
            self.assertIn(2, model)

    def test_append_formula_and_model_invalidation(self) -> None:
        with GlucoseBackend() as backend:
            self.assertEqual(backend.name, "glucose")
            self.assertEqual(backend.version, "glucose4")
            backend.append_formula([[1, 2], [-1]])
            self.assertTrue(backend.solve())
            self.assertIn(2, backend.get_model() or [])

            backend.add_clause([-2])
            self.assertIsNone(backend.get_model())
            self.assertFalse(backend.solve())
            self.assertIsNone(backend.get_model())

    def test_timeout_is_distinct_from_unsat_and_solver_remains_usable(self) -> None:
        with GlucoseBackend() as backend:
            backend.add_clause([1])
            with self.assertRaises(TimeoutError):
                backend.solve(timeout_seconds=0)
            self.assertIsNone(backend.get_model())
            self.assertTrue(backend.solve())
            self.assertIn(1, backend.get_model() or [])
            with self.assertRaises(ValueError):
                backend.solve(timeout_seconds=-1)

    def test_delete_releases_solver_and_is_idempotent(self) -> None:
        backend = GlucoseBackend()
        backend.delete()
        backend.delete()
        with self.assertRaises(RuntimeError):
            backend.solve()
        with self.assertRaises(RuntimeError):
            backend.add_clause([1])


if __name__ == "__main__":
    unittest.main()
