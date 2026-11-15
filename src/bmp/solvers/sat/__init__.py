"""SAT-based solvers for the Bandwidth Minimization Problem."""

from bmp.encodings.estimator import (
    CNFSizeEstimate,
    ResourceLimits,
    estimate_cnf_size,
    estimate_incremental_cnf_size,
)
from bmp.solvers.sat.backends import (
    CadicalBackend,
    GlucoseBackend,
    MiniSat22Backend,
    MiniSatBackend,
    SATBackend,
    get_sat_backend,
)
from bmp.solvers.sat.incremental import IncrementalSATSolver
from bmp.solvers.sat.repeated import RepeatedSATSolver
from bmp.solvers.sat.search import (
    compute_initial_upper_bound,
    compute_lower_bound,
)

__all__ = [
    "CNFSizeEstimate",
    "CadicalBackend",
    "GlucoseBackend",
    "IncrementalSATSolver",
    "MiniSat22Backend",
    "MiniSatBackend",
    "RepeatedSATSolver",
    "ResourceLimits",
    "SATBackend",
    "compute_initial_upper_bound",
    "compute_lower_bound",
    "estimate_cnf_size",
    "estimate_incremental_cnf_size",
    "get_sat_backend",
]
