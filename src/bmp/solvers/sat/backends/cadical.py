"""CaDiCaL SAT solver backend via PySAT."""

from __future__ import annotations

from typing import Any, Sequence

from bmp.solvers.sat.backends.base import SATBackend, register_sat_backend


class CadicalBackend(SATBackend):
    """SAT backend integrating CaDiCaL via python-sat (PySAT)."""

    def __init__(self, solver_name: str | None = None) -> None:
        try:
            from pysat.solvers import Solver, SolverNames
        except ImportError as e:
            raise RuntimeError(
                "python-sat (pysat) is not installed in the environment."
            ) from e

        # Determine the best available cadical version if not specified
        available_names = [x for x in dir(SolverNames) if not x.startswith("_")]
        if solver_name is None:
            preferred = ["cadical195", "cadical300", "cadical153", "cadical103"]
            selected = None
            for cand in preferred:
                if cand in available_names:
                    selected = cand
                    break
            if selected is None:
                raise RuntimeError(
                    f"No CaDiCaL solver variant found in PySAT SolverNames: {available_names}"
                )
            self._solver_name = selected
        else:
            if solver_name not in available_names:
                raise RuntimeError(
                    f"Requested solver '{solver_name}' not available in PySAT SolverNames: {available_names}"
                )
            self._solver_name = solver_name

        self._solver = Solver(name=self._solver_name)
        self._deleted = False

    @classmethod
    def is_available(cls) -> bool:
        try:
            from pysat.solvers import SolverNames
            available_names = [x for x in dir(SolverNames) if not x.startswith("_")]
            return any("cadical" in name for name in available_names)
        except ImportError:
            return False

    @property
    def name(self) -> str:
        return "cadical"

    @property
    def version(self) -> str:
        return self._solver_name

    def add_clause(self, clause: Sequence[int]) -> None:
        if self._deleted:
            raise RuntimeError("Cannot add clause to deleted solver")
        self._solver.add_clause(list(clause))

    def append_formula(self, clauses: Sequence[Sequence[int]]) -> None:
        if self._deleted:
            raise RuntimeError("Cannot append formula to deleted solver")
        self._solver.append_formula([list(c) for c in clauses])

    def solve(self, assumptions: Sequence[int] = ()) -> bool:
        if self._deleted:
            raise RuntimeError("Cannot solve with deleted solver")
        return bool(self._solver.solve(assumptions=list(assumptions)))

    def get_model(self) -> list[int] | None:
        if self._deleted:
            raise RuntimeError("Cannot get model from deleted solver")
        return self._solver.get_model()

    def delete(self) -> None:
        if not self._deleted and hasattr(self, "_solver"):
            try:
                self._solver.delete()
            except Exception:
                pass
            self._deleted = True


register_sat_backend("cadical", CadicalBackend)
register_sat_backend("cadical195", lambda: CadicalBackend(solver_name="cadical195"))

__all__ = ["CadicalBackend"]

