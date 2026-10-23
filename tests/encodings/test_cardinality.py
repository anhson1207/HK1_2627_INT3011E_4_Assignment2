from __future__ import annotations

import unittest
from pysat.solvers import Solver

from bmp.encodings.cardinality import (
    PairwiseAMOEncoder,
    SequentialCounterAMOEncoder,
    SimpleVarAllocator,
    get_amo_encoder,
)


class CardinalityEncodingTests(unittest.TestCase):
    def test_pairwise_empty_and_trivial(self) -> None:
        enc = PairwiseAMOEncoder()
        alloc = SimpleVarAllocator(1)
        c0, a0 = enc.encode([], alloc)
        self.assertEqual(c0, [])
        self.assertEqual(a0, [])

        c1, a1 = enc.encode([1], alloc)
        self.assertEqual(c1, [])
        self.assertEqual(a1, [])

        c2, a2 = enc.encode([1, 2], alloc)
        self.assertEqual(c2, [[-1, -2]])
        self.assertEqual(a2, [])

    def test_sequential_empty_and_trivial(self) -> None:
        enc = SequentialCounterAMOEncoder()
        alloc = SimpleVarAllocator(10)
        c0, a0 = enc.encode([], alloc)
        self.assertEqual(c0, [])
        self.assertEqual(a0, [])

        c1, a1 = enc.encode([1], alloc)
        self.assertEqual(c1, [])
        self.assertEqual(a1, [])

        c2, a2 = enc.encode([1, 2], alloc)
        self.assertEqual(c2, [[-1, -2]])
        self.assertEqual(a2, [])

    def test_sequential_counts(self) -> None:
        enc = SequentialCounterAMOEncoder()
        for m in (3, 4, 5, 8, 10):
            alloc = SimpleVarAllocator(100)
            lits = list(range(1, m + 1))
            clauses, aux = enc.encode(lits, alloc)
            self.assertEqual(len(aux), m - 1)
            self.assertEqual(len(clauses), 3 * m - 4)

    def _verify_amo_semantics(self, encoder_name: str, m: int) -> None:
        enc = get_amo_encoder(encoder_name)
        alloc = SimpleVarAllocator(m + 1)
        lits = list(range(1, m + 1))
        clauses, _ = enc.encode(lits, alloc)

        # Test with PySAT solver
        # 1. 0 true literals -> SAT
        s0 = Solver(name="cadical195", bootstrap_with=clauses)
        # Assume all lits are False
        assump0 = [-lit for lit in lits]
        self.assertTrue(s0.solve(assumptions=assump0))
        s0.delete()

        # 2. Exactly 1 true literal -> SAT for each i
        for i in range(m):
            s1 = Solver(name="cadical195", bootstrap_with=clauses)
            assump1 = [-lit for lit in lits]
            assump1[i] = lits[i]
            self.assertTrue(s1.solve(assumptions=assump1))
            s1.delete()

        # 3. Two true literals -> UNSAT for all pairs
        for i in range(m):
            for j in range(i + 1, m):
                s2 = Solver(name="cadical195", bootstrap_with=clauses)
                assump2 = [lits[i], lits[j]]
                self.assertFalse(s2.solve(assumptions=assump2))
                s2.delete()

    def test_pairwise_semantics(self) -> None:
        for m in (2, 3, 4, 5):
            with self.subTest(m=m):
                self._verify_amo_semantics("pairwise", m)

    def test_sequential_semantics(self) -> None:
        for m in (2, 3, 4, 5):
            with self.subTest(m=m):
                self._verify_amo_semantics("sequential", m)


if __name__ == "__main__":
    unittest.main()
