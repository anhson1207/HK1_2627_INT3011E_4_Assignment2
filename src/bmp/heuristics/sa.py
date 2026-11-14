"""Seeded permutation simulated annealing baseline with incremental delta evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from math import exp, isfinite
from random import Random
from time import monotonic
from typing import Mapping

from bmp.core.graph import Graph
from bmp.core.solution import SolutionStatus, SolverResult
from bmp.core.validation import validate_solution
from bmp.heuristics.initial import (
    IncrementalBandwidthState,
    build_initial_permutation,
)
from bmp.solvers.sat.search import compute_lower_bound


@dataclass(slots=True)
class SimulatedAnnealingSolver:
    """Single-operator (REX vertex-label swap) simulated annealing baseline."""

    iterations: int = 2000
    initial_temperature: float = 2.0
    cooling: float = 0.995
    seed: int = 0
    minimum_temperature: float = 1e-12
    initial_mode: str = "rcm"
    use_incremental: bool = True
    verify_interval: int = 0

    def solve(
        self,
        graph: Graph,
        *,
        timeout_seconds: float | None = None,
        seed: int | None = None,
        initial_permutation: Mapping[int, int] | None = None,
        initial_mode: str | None = None,
        iterations: int | None = None,
        use_incremental: bool | None = None,
    ) -> SolverResult:
        active_iters = self.iterations if iterations is None else int(iterations)
        if (
            active_iters < 0
            or not isfinite(self.initial_temperature)
            or self.initial_temperature <= 0
        ):
            raise ValueError(
                "Expected nonnegative iterations and a positive finite temperature"
            )
        if not 0 < self.cooling < 1:
            raise ValueError("cooling must be between zero and one")
        if not 0 < self.minimum_temperature <= self.initial_temperature:
            raise ValueError(
                "Expected positive minimum_temperature <= initial_temperature"
            )
        if timeout_seconds is not None and (
            not isfinite(timeout_seconds) or timeout_seconds < 0
        ):
            raise ValueError("timeout_seconds must be finite and non-negative")

        started = monotonic()
        active_seed = self.seed if seed is None else int(seed)
        active_init_mode = self.initial_mode if initial_mode is None else initial_mode
        active_incremental = (
            self.use_incremental if use_incremental is None else bool(use_incremental)
        )
        rng = Random(active_seed)

        init_perm, initial_bw, resolved_init = build_initial_permutation(
            graph,
            mode=active_init_mode,
            rng=rng,
            initial_permutation=initial_permutation,
        )
        state = IncrementalBandwidthState(
            graph,
            init_perm,
            evaluation_mode="bandwidth_only",
            use_incremental=active_incremental,
        )
        best = state.bandwidth
        best_p_slots = state.dual.p_slots.copy()

        temperature = self.initial_temperature
        completed = 0
        accepted_moves = 0
        rejected_moves = 0
        best_updates = 0
        time_to_first_improvement_s: float | None = None
        time_to_best_s = 0.0
        timeline: list[dict[str, object]] = [
            {"evals": 0, "time_s": 0.0, "bandwidth": best, "f_value": float(best)}
        ]
        stop_reason = "max_iterations"

        n = graph.order
        if not graph.edges or n <= 1:
            stop_reason = "trivial_or_edgeless"
        elif timeout_seconds == 0 or active_iters == 0:
            stop_reason = "timeout" if timeout_seconds == 0 else "max_iterations"
        else:
            for step in range(active_iters):
                if timeout_seconds is not None and (step & 31) == 0 and (monotonic() - started) >= timeout_seconds:
                    stop_reason = "timeout"
                    break
                if temperature < self.minimum_temperature:
                    stop_reason = "minimum_temperature"
                    break
                completed += 1
                u_slot = rng.randrange(n)
                v_slot = rng.randrange(n - 1)
                if v_slot >= u_slot:
                    v_slot += 1

                prev_bw = state.bandwidth
                token = state.apply_swap_p(u_slot, v_slot)
                cand_bw = state.bandwidth
                delta = cand_bw - prev_bw
                if delta <= 0 or rng.random() < exp(-delta / temperature):
                    accepted_moves += 1
                    if cand_bw < best:
                        best = cand_bw
                        best_p_slots = state.dual.p_slots.copy()
                        best_updates += 1
                        elapsed = monotonic() - started
                        if time_to_first_improvement_s is None:
                            time_to_first_improvement_s = round(elapsed, 6)
                        time_to_best_s = round(elapsed, 6)
                        timeline.append(
                            {
                                "evals": completed,
                                "time_s": round(elapsed, 6),
                                "bandwidth": best,
                                "f_value": float(best),
                            }
                        )
                else:
                    rejected_moves += 1
                    state.undo_swap_p(u_slot, v_slot, token)

                if self.verify_interval > 0 and (step + 1) % self.verify_interval == 0:
                    state.assert_synced()

                temperature *= self.cooling

        incumbent = {
            v: best_p_slots[idx] + 1 for idx, v in enumerate(graph.vertices)
        }
        report = validate_solution(graph, incumbent, claimed_bandwidth=best)
        if not report.valid or report.actual_bandwidth is None:
            raise RuntimeError(
                f"Simulated annealing produced an invalid assignment: {report.errors}"
            )

        runtime = monotonic() - started
        abs_imp = initial_bw - report.actual_bandwidth
        rel_imp = (abs_imp / initial_bw) if initial_bw > 0 else 0.0
        lower = min(compute_lower_bound(graph), report.actual_bandwidth)
        return SolverResult(
            instance=graph.name,
            method="HEURISTIC",
            solver="sa",
            status=SolutionStatus.FEASIBLE,
            runtime_seconds=runtime,
            permutation=incumbent,
            bandwidth=report.actual_bandwidth,
            lower_bound=lower,
            upper_bound=report.actual_bandwidth,
            metadata={
                "variant": "BASELINE",
                "seed": active_seed,
                "initial_mode": resolved_init,
                "initial_bandwidth": initial_bw,
                "absolute_improvement": abs_imp,
                "relative_improvement": round(rel_imp, 6),
                "iterations": active_iters,
                "iterations_completed": completed,
                "evaluations": completed,
                "accepted_moves": accepted_moves,
                "rejected_moves": rejected_moves,
                "best_updates": best_updates,
                "time_to_first_improvement_s": time_to_first_improvement_s,
                "time_to_best_s": time_to_best_s,
                "best_so_far_timeline": timeline,
                "initial_temperature": self.initial_temperature,
                "minimum_temperature": self.minimum_temperature,
                "cooling": self.cooling,
                "use_incremental": active_incremental,
                "stop_reason": stop_reason,
                "timed_out": stop_reason == "timeout",
                "incumbent_source": "heuristic",
            },
        )


__all__ = ["SimulatedAnnealingSolver"]
