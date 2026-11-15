"""Glucose 4 SAT solver backend via PySAT implementing SATBackend."""

from __future__ import annotations

from collections.abc import Sequence
from threading import Lock, Timer
from types import TracebackType

from bmp.solvers.sat.backends.base import SATBackend, register_sat_backend


class GlucoseBackend(SATBackend):
    """Reusable Glucose 4 solver; assumptions apply to one solve call only.

    ``solve`` returns True for SAT, False for UNSAT, and raises TimeoutError if
    an explicit ``timeout_seconds`` deadline expires. ``solve_with_timeout``
    implements the SATBackend L8 contract and returns None on timeout/interrupt.
    """

    def __init__(self) -> None:
        try:
            from pysat.solvers import Glucose4
        except ImportError as exc:
            raise RuntimeError(
                "python-sat (pysat) or Glucose4 is not installed in the environment."
            ) from exc

        self._solver = Glucose4()
        self._deleted = False
        self._last_sat = False
        self._solve_lock = Lock()
        self._solving = False

    @classmethod
    def is_available(cls) -> bool:
        try:
            from pysat.solvers import Glucose4  # noqa: F401
            return True
        except ImportError:
            return False

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
        if self._deleted:
            return
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

        if timeout_seconds is None:
            result = bool(self._solver.solve(assumptions=list(assumptions)))
            self._last_sat = result
            return result

        with self._solve_lock:
            if self._solving:
                raise RuntimeError("Glucose 4 solver is already solving")
            self._solving = True

        timer = Timer(timeout_seconds, self.interrupt)
        try:
            timer.start()
            result = self._solver.solve_limited(
                assumptions=list(assumptions), expect_interrupt=True
            )
        finally:
            with self._solve_lock:
                self._solving = False
                timer.cancel()
                self._solver.clear_interrupt()

        if result is None:
            self._last_sat = False
            raise TimeoutError("Glucose 4 solve was interrupted or timed out")
        self._last_sat = bool(result)
        return self._last_sat

    def solve_with_timeout(
        self, seconds: float | None, assumptions: Sequence[int] = ()
    ) -> bool | None:
        """Solve with optional timeout; return None when interrupted/timed out."""
        self._check_open()
        if seconds is not None and seconds < 0:
            raise ValueError("timeout seconds must be nonnegative")
        if seconds is None:
            return self.solve(assumptions)
        try:
            return self.solve(assumptions, timeout_seconds=seconds)
        except TimeoutError:
            self._last_sat = False
            return None

    def get_model(self) -> list[int] | None:
        self._check_open()
        return self._solver.get_model() if self._last_sat else None

    def delete(self) -> None:
        if not self._deleted and hasattr(self, "_solver"):
            try:
                self._solver.delete()
            except Exception:
                pass
            self._deleted = True
            self._last_sat = False

    def __enter__(self) -> GlucoseBackend:
        self._check_open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.delete()


register_sat_backend("glucose", GlucoseBackend)
register_sat_backend("glucose4", GlucoseBackend)

__all__ = ["GlucoseBackend"]
