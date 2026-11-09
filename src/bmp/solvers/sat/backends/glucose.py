"""Glucose 4 backend matching the team's SAT backend interface.

The SAT core and its registry currently live on ``origin/dev/leader``. Import
and register this class in ``backends/__init__.py`` when that core is merged.
"""

from __future__ import annotations

from collections.abc import Sequence
from threading import Lock, Timer
from types import TracebackType

from pysat.solvers import Glucose4


class GlucoseBackend:
    """Reusable Glucose 4 solver; assumptions apply to one solve call only.

    ``solve`` returns True for SAT, False for UNSAT, and raises TimeoutError if
    the solve is interrupted or its optional deadline expires.
    """

    def __init__(self) -> None:
        self._solver = Glucose4()
        self._deleted = False
        self._last_sat = False
        self._solve_lock = Lock()
        self._solving = False

    @property
    def name(self) -> str:
        return "glucose"

    @property
    def version(self) -> str:
        return "glucose4"

    def _check_open(self) -> None:
        if self._deleted:
            raise RuntimeError("Glucose 4 solver has been deleted")

    def add_clause(self, clause: Sequence[int]) -> None:
        self._check_open()
        self._last_sat = False
        self._solver.add_clause(list(clause))

    def append_formula(self, clauses: Sequence[Sequence[int]]) -> None:
        self._check_open()
        self._last_sat = False
        self._solver.append_formula([list(clause) for clause in clauses])

    def interrupt(self) -> None:
        """Stop a currently running solve from another thread."""
        self._check_open()
        with self._solve_lock:
            if self._solving:
                self._solver.interrupt()

    def solve(
        self, assumptions: Sequence[int] = (), *, timeout_seconds: float | None = None
    ) -> bool:
        self._check_open()
        if timeout_seconds is not None and timeout_seconds < 0:
            raise ValueError("timeout_seconds must be nonnegative")
        self._last_sat = False
        if timeout_seconds == 0:
            raise TimeoutError("Glucose 4 solve timed out")

        with self._solve_lock:
            if self._solving:
                raise RuntimeError("Glucose 4 solver is already solving")
            self._solving = True

        timer = Timer(timeout_seconds, self.interrupt) if timeout_seconds is not None else None
        try:
            if timer is not None:
                timer.start()
            result = self._solver.solve_limited(
                assumptions=list(assumptions), expect_interrupt=True
            )
        finally:
            with self._solve_lock:
                self._solving = False
                if timer is not None:
                    timer.cancel()
                self._solver.clear_interrupt()

        if result is None:
            raise TimeoutError("Glucose 4 solve was interrupted or timed out")
        self._last_sat = result
        return result

    def get_model(self) -> list[int] | None:
        self._check_open()
        return self._solver.get_model() if self._last_sat else None

    def delete(self) -> None:
        if not self._deleted:
            self._solver.delete()
            self._deleted = True
            self._last_sat = False

    def __enter__(self) -> GlucoseBackend:
        self._check_open()
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.delete()


__all__ = ["GlucoseBackend"]
