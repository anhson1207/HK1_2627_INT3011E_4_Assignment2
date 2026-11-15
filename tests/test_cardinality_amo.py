"""Existential CNF equivalence checks using Glucose 4."""

from __future__ import annotations

from itertools import count, product
import unittest

from pysat.solvers import Glucose4

from bmp.encodings.cardinality import encode_binary_amo, encode_commander_amo


ENCODERS = (encode_binary_amo, encode_commander_amo)


def assert_all_assignments(
    test: unittest.TestCase, literals: list[int], clauses: list[list[int]]
) -> None:
    variable_ids = sorted({abs(literal) for literal in literals})
    with Glucose4(bootstrap_with=clauses) as solver:
        for values in product((False, True), repeat=len(variable_ids)):
            assignment = dict(zip(variable_ids, values))
            assumptions = [var if assignment[var] else -var for var in variable_ids]
            true_count = sum(
                assignment[abs(literal)] == (literal > 0) for literal in literals
            )
            with test.subTest(assumptions=assumptions):
                test.assertEqual(solver.solve(assumptions=assumptions), true_count <= 1)


class CardinalityAMOTests(unittest.TestCase):
    def test_all_assignments_for_zero_through_seven_literals(self) -> None:
        for encoder in ENCODERS:
            for n in range(8):
                with self.subTest(encoder=encoder.__name__, n=n):
                    literals = list(range(1, n + 1))
                    allocator = count(n + 1).__next__
                    clauses = encoder(literals, allocator)
                    if n <= 1:
                        self.assertEqual(clauses, [])
                    assert_all_assignments(self, literals, clauses)

    def test_negative_literals(self) -> None:
        literals = [1, -2, 3, -4, 5]
        for encoder in ENCODERS:
            with self.subTest(encoder=encoder.__name__):
                clauses = encoder(literals, count(6).__next__)
                assert_all_assignments(self, literals, clauses)

    def test_shared_allocator_and_combined_constraints(self) -> None:
        first = [1, 2, 3, 4]
        second = [-2, 5, 6, 7]
        for first_encoder in ENCODERS:
            for second_encoder in ENCODERS:
                with self.subTest(first=first_encoder.__name__, second=second_encoder.__name__):
                    allocator = count(8).__next__
                    first_clauses = first_encoder(first, allocator)
                    second_clauses = second_encoder(second, allocator)
                    first_aux = {abs(lit) for clause in first_clauses for lit in clause} - set(range(1, 8))
                    second_aux = {abs(lit) for clause in second_clauses for lit in clause} - set(range(1, 8))
                    self.assertTrue(first_aux)
                    self.assertTrue(second_aux)
                    self.assertTrue(first_aux.isdisjoint(second_aux))
                    with Glucose4(bootstrap_with=first_clauses + second_clauses) as solver:
                        for values in product((False, True), repeat=7):
                            assignment = dict(zip(range(1, 8), values))
                            assumptions = [var if assignment[var] else -var for var in range(1, 8)]
                            expected = all(
                                sum(assignment[abs(lit)] == (lit > 0) for lit in constraint) <= 1
                                for constraint in (first, second)
                            )
                            with self.subTest(assumptions=assumptions):
                                self.assertEqual(solver.solve(assumptions=assumptions), expected)

    def test_commander_multiple_recursive_levels(self) -> None:
        literals = list(range(1, 11))
        allocator = count(11).__next__
        clauses = encode_commander_amo(literals, allocator)
        auxiliary_ids = {abs(lit) for clause in clauses for lit in clause} - set(literals)
        self.assertEqual(len(auxiliary_ids), 6)
        assert_all_assignments(self, literals, clauses)

    def test_six_literal_sizes(self) -> None:
        literals = list(range(1, 7))
        expected = ((encode_binary_amo, 3, 18), (encode_commander_amo, 2, 13))
        for encoder, aux_count, clause_count in expected:
            with self.subTest(encoder=encoder.__name__):
                clauses = encoder(literals, count(7).__next__)
                used_ids = {abs(lit) for clause in clauses for lit in clause}
                self.assertEqual(len(used_ids - set(literals)), aux_count)
                self.assertEqual(len(clauses), clause_count)

    def test_allocator_must_not_reuse_input_or_auxiliary_ids(self) -> None:
        for encoder in ENCODERS:
            with self.subTest(encoder=encoder.__name__):
                with self.assertRaises(ValueError):
                    encoder([1, 2, 3, 4], lambda: 1)
                with self.assertRaises(ValueError):
                    encoder([0, 1], count(2).__next__)


if __name__ == "__main__":
    unittest.main()
