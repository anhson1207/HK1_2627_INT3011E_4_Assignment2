"""MiniSat22 CNF session for repeated or incremental calls."""

from collections.abc import Iterable


class MiniSat22Backend:
    def __init__(self, clauses: Iterable[Iterable[int]] = ()) -> None:
        from pysat.solvers import Minisat22

        self._solver = Minisat22()
        try:
            self._solver.append_formula(clauses)
        except BaseException:
            self.close()
            raise

    def _active_solver(self):
        if self._solver is None:
            raise RuntimeError("MiniSat22 session is closed")
        return self._solver

    def add_clause(self, clause: Iterable[int]) -> None:
        self._active_solver().add_clause(list(clause))

    def solve(self, assumptions: Iterable[int] = ()) -> bool:
        # Assumptions chỉ áp dụng cho lần solve hiện tại.
        return self._active_solver().solve(assumptions=list(assumptions))

    def get_model(self) -> list[int] | None:
        return self._active_solver().get_model()

    def close(self) -> None:
        if self._solver is not None:
            self._solver.delete()
            self._solver = None

    def __enter__(self):
        self._active_solver()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
