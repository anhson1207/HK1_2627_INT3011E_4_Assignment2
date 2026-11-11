"""Dual Representation Simulated Annealing (DRSA) for BMPG.

Implements Torres-Jimenez et al. (2015), "A dual representation simulated annealing
algorithm for the bandwidth minimization problem on graphs", Information Sciences 303, 33-49:
  - Algorithm 1: Markov-chain temperature & chain-length increment schedule.
  - Section 3.2: Synchronized inverse dual representation (p, q).
  - Algorithm 2 & Section 3.3: Neighborhood function g with REX (0.6), NEX (0.2), ROT (0.2, r<=5).
  - Algorithm 4 & Section 3.4: Evaluation function f = b + delta via truncated continued fraction.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from random import Random
from time import monotonic
from typing import Mapping

from bmp.core.graph import Graph
from bmp.core.solution import SolutionStatus, SolverResult
from bmp.core.validation import validate_solution
from bmp.heuristics.initial import (
    DualRepresentation,
    IncrementalBandwidthState,
    build_initial_permutation,
    compute_fractional_delta_from_histogram,
    evaluate_solution_components,
)
from bmp.solvers.sat.search import compute_lower_bound


def compute_fractional_delta(
    histogram: list[int] | tuple[int, ...], bandwidth: int, order: int
) -> float:
    """Public alias for Algorithm 4 fractional score ``delta in [0, 1)``."""
    return compute_fractional_delta_from_histogram(histogram, bandwidth, order)


def evaluate_solution(
    graph: Graph,
    permutation: Mapping[int, int],
    *,
    evaluation_mode: str = "paper",
) -> tuple[int, float, float, list[int]]:
    """Evaluate a permutation returning ``(bandwidth, delta, f_value, histogram_d)``."""
    return evaluate_solution_components(
        graph, permutation, evaluation_mode=evaluation_mode
    )


def compute_increment_factor(
    initial_temperature: float,
    final_temperature: float,
    cooling: float,
    initial_chain_length: int,
    final_chain_length: int,
) -> tuple[float, float]:
    """Compute paper's ``(r, gamma)`` so ``L`` reaches ``L_f`` when ``T`` reaches ``T_f``.

    r = (log(T_f) - log(T_0)) / log(alpha)
    gamma = exp((log(L_f) - log(L_0)) / r)
    """
    if initial_temperature <= final_temperature or final_chain_length <= initial_chain_length:
        return 0.0, 1.0
    r = (math.log(final_temperature) - math.log(initial_temperature)) / math.log(cooling)
    if r <= 0:
        return 0.0, 1.0
    gamma = math.exp((math.log(final_chain_length) - math.log(initial_chain_length)) / r)
    return r, gamma


@dataclass(slots=True)
class DRSASolver:
    """Dual Representation Simulated Annealing solver (Torres-Jimenez et al., 2015)."""

    initial_temperature: float = 1000.0
    cooling: float = 0.99
    final_temperature: float = 1e-7
    initial_chain_length: int = 40
    final_chain_length: int | None = None
    p_rex: float = 0.6
    p_nex: float = 0.2
    p_rot: float = 0.2
    rot_max_separation: int = 5
    seed: int = 0
    initial_mode: str = "random"
    evaluation_mode: str = "paper"
    use_incremental: bool = True
    verify_interval: int = 0
    variant: str = "PAPER_FAITHFUL"

    def _validate_parameters(self) -> tuple[float, float, float]:
        if not math.isfinite(self.initial_temperature) or self.initial_temperature <= 0:
            raise ValueError("initial_temperature must be positive and finite")
        if not math.isfinite(self.final_temperature) or not (
            0 < self.final_temperature <= self.initial_temperature
        ):
            raise ValueError("final_temperature must lie in (0, initial_temperature]")
        if not 0 < self.cooling < 1:
            raise ValueError("cooling alpha must lie in (0, 1)")
        if self.initial_chain_length < 1:
            raise ValueError("initial_chain_length L0 must be at least 1")
        if self.final_chain_length is not None and self.final_chain_length < 1:
            raise ValueError("final_chain_length must be positive when provided")
        if self.rot_max_separation < 1:
            raise ValueError("rot_max_separation must be at least 1")
        if self.evaluation_mode not in ("paper", "bandwidth_only"):
            raise ValueError(f"Unsupported evaluation_mode: {self.evaluation_mode!r}")

        probs = (self.p_rex, self.p_nex, self.p_rot)
        if any(not math.isfinite(p) or p < 0 for p in probs):
            raise ValueError("Operator probabilities must be non-negative and finite")
        total = sum(probs)
        if total <= 0:
            raise ValueError("At least one operator must have positive probability")
        return self.p_rex / total, self.p_nex / total, self.p_rot / total

    def solve(
        self,
        graph: Graph,
        *,
        timeout_seconds: float | None = None,
        max_wall_seconds: float | None = None,
        max_total_moves: int | None = None,
        max_temperature_stages: int | None = None,
        seed: int | None = None,
        initial_permutation: Mapping[int, int] | None = None,
        initial_mode: str | None = None,
        use_incremental: bool | None = None,
    ) -> SolverResult:
        norm_rex, norm_nex, norm_rot = self._validate_parameters()

        wall_limit = max_wall_seconds if max_wall_seconds is not None else timeout_seconds
        if wall_limit is not None and (not math.isfinite(wall_limit) or wall_limit < 0):
            raise ValueError("timeout_seconds / max_wall_seconds must be finite and non-negative")
        if max_total_moves is not None and max_total_moves < 0:
            raise ValueError("max_total_moves must be non-negative")
        if max_temperature_stages is not None and max_temperature_stages < 0:
            raise ValueError("max_temperature_stages must be non-negative")

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
            evaluation_mode=self.evaluation_mode,
            use_incremental=active_incremental,
        )

        n = graph.order
        m = graph.size
        lf_target = (
            10 * n * m
            if self.final_chain_length is None
            else int(self.final_chain_length)
        )
        expected_cooling_steps, gamma = compute_increment_factor(
            self.initial_temperature,
            self.final_temperature,
            self.cooling,
            self.initial_chain_length,
            lf_target,
        )

        best_bw = state.bandwidth
        best_delta = state.delta
        best_f = state.f_value
        best_p_slots = state.dual.p_slots.copy()

        evaluations = 0
        accepted_moves = 0
        rejected_moves = 0
        best_bw_updates = 0
        best_f_updates = 0
        stage_count = 0
        cooling_steps = 0

        op_counts = {"REX": 0, "NEX": 0, "ROT": 0}
        op_accepts = {"REX": 0, "NEX": 0, "ROT": 0}
        op_bw_improvements = {"REX": 0, "NEX": 0, "ROT": 0}
        op_f_improvements = {"REX": 0, "NEX": 0, "ROT": 0}
        op_noop_counts = {"REX": 0, "NEX": 0, "ROT": 0}

        time_to_first_improvement_s: float | None = None
        time_to_best_s = 0.0
        timeline: list[dict[str, object]] = [
            {
                "evals": 0,
                "time_s": 0.0,
                "bandwidth": best_bw,
                "f_value": round(best_f, 9),
            }
        ]
        stop_reason = "final_temperature"

        temperature = self.initial_temperature
        chain_len_float = float(self.initial_chain_length)
        max_rot = min(self.rot_max_separation, max(0, n - 1))
        non_isolated = state.non_isolated_slots
        adj_neighbors = state.adj_neighbors
        cum_nex = norm_rex + norm_nex

        if m == 0 or n <= 1:
            stop_reason = "trivial_or_edgeless"
        elif wall_limit == 0 or max_total_moves == 0 or max_temperature_stages == 0:
            stop_reason = (
                "timeout"
                if wall_limit == 0
                else ("max_total_moves" if max_total_moves == 0 else "max_temperature_stages")
            )
        else:
            budget_stopped = False
            while temperature > self.final_temperature:
                if max_temperature_stages is not None and stage_count >= max_temperature_stages:
                    stop_reason = "max_temperature_stages"
                    break
                if wall_limit is not None and (monotonic() - started) >= wall_limit:
                    stop_reason = "timeout"
                    break
                if max_total_moves is not None and evaluations >= max_total_moves:
                    stop_reason = "max_total_moves"
                    break

                stage_count += 1
                improvement = False
                chain_len = max(1, int(round(chain_len_float)))

                for _ in range(chain_len):
                    if wall_limit is not None and (evaluations & 31) == 0 and (monotonic() - started) >= wall_limit:
                        stop_reason = "timeout"
                        budget_stopped = True
                        break
                    if max_total_moves is not None and evaluations >= max_total_moves:
                        stop_reason = "max_total_moves"
                        budget_stopped = True
                        break

                    evaluations += 1
                    cur_f = state.f_value
                    cur_bw = state.bandwidth
                    cur_delta = state.delta

                    u_roll = rng.random()
                    if u_roll <= norm_rex:
                        op = "REX"
                        u_slot = rng.randrange(n)
                        v_slot = rng.randrange(n - 1)
                        if v_slot >= u_slot:
                            v_slot += 1
                        op_counts["REX"] += 1
                        token = state.apply_swap_p(u_slot, v_slot)
                        move_args: tuple[int, int] = (u_slot, v_slot)
                    elif u_roll <= cum_nex:
                        op = "NEX"
                        op_counts["NEX"] += 1
                        if non_isolated:
                            u_slot = non_isolated[rng.randrange(len(non_isolated))]
                            nbrs = adj_neighbors[u_slot]
                            v_slot = nbrs[rng.randrange(len(nbrs))]
                            token = state.apply_swap_p(u_slot, v_slot)
                            move_args = (u_slot, v_slot)
                        else:
                            op_noop_counts["NEX"] += 1
                            rejected_moves += 1
                            continue
                    else:
                        op = "ROT"
                        op_counts["ROT"] += 1
                        if max_rot >= 1:
                            r = rng.randint(1, max_rot)
                            i_lbl = rng.randrange(n - r)
                            j_lbl = i_lbl + r
                            token = state.apply_rot_q(i_lbl, j_lbl)
                            move_args = (i_lbl, j_lbl)
                        else:
                            op_noop_counts["ROT"] += 1
                            rejected_moves += 1
                            continue

                    cand_f = state.f_value
                    cand_bw = state.bandwidth
                    cand_delta = state.delta
                    delta_f = float(cand_bw - cur_bw) + (cand_delta - cur_delta)

                    accepted = False
                    if (cand_bw, cand_delta) < (cur_bw, cur_delta):
                        accepted = True
                    elif temperature > 0.0:
                        exponent = -delta_f / temperature
                        if exponent >= 0.0 or (exponent > -745.0 and rng.random() < math.exp(exponent)):
                            accepted = True

                    if accepted:
                        accepted_moves += 1
                        op_accepts[op] += 1
                        if (cand_bw, cand_delta) < (best_bw, best_delta):
                            prev_best_bw = best_bw
                            best_f = cand_f
                            best_bw = cand_bw
                            best_delta = cand_delta
                            best_p_slots = state.dual.p_slots.copy()
                            best_f_updates += 1
                            op_f_improvements[op] += 1
                            improvement = True
                            if cand_bw < prev_best_bw:
                                best_bw_updates += 1
                                op_bw_improvements[op] += 1
                                elapsed = monotonic() - started
                                if time_to_first_improvement_s is None:
                                    time_to_first_improvement_s = round(elapsed, 6)
                                time_to_best_s = round(elapsed, 6)
                                timeline.append(
                                    {
                                        "evals": evaluations,
                                        "time_s": round(elapsed, 6),
                                        "bandwidth": best_bw,
                                        "f_value": round(best_f, 9),
                                    }
                                )
                    else:
                        rejected_moves += 1
                        if op == "ROT":
                            state.undo_rot_q(move_args[0], move_args[1], token)
                        else:
                            state.undo_swap_p(move_args[0], move_args[1], token)

                    if self.verify_interval > 0 and evaluations % self.verify_interval == 0:
                        state.assert_synced()

                if budget_stopped:
                    break

                # Algorithm 1 lines 22-25: cool & lengthen only when global best was NOT improved.
                if not improvement:
                    temperature *= self.cooling
                    chain_len_float *= gamma
                    cooling_steps += 1

        if self.verify_interval > 0:
            state.assert_synced()

        incumbent = {v: best_p_slots[idx] + 1 for idx, v in enumerate(graph.vertices)}
        report = validate_solution(graph, incumbent, claimed_bandwidth=best_bw)
        if not report.valid or report.actual_bandwidth is None:
            raise RuntimeError(f"DRSA produced an invalid assignment: {report.errors}")

        final_runtime = monotonic() - started
        abs_imp = initial_bw - report.actual_bandwidth
        rel_imp = (abs_imp / initial_bw) if initial_bw > 0 else 0.0
        certified_lb = compute_lower_bound(graph)
        lower = min(certified_lb, report.actual_bandwidth)

        active_variant = self.variant
        is_paper_params = (
            self.initial_temperature == 1000.0
            and self.cooling == 0.99
            and self.final_temperature == 1e-7
            and self.initial_chain_length == 40
            and self.final_chain_length is None
            and self.rot_max_separation == 5
            and self.evaluation_mode == "paper"
            and abs(norm_rex - 0.6) < 1e-9
            and abs(norm_nex - 0.2) < 1e-9
            and abs(norm_rot - 0.2) < 1e-9
            and resolved_init == "random"
        )
        if active_variant == "PAPER_FAITHFUL" and not is_paper_params:
            active_variant = "MODIFIED_VARIANT"

        return SolverResult(
            instance=graph.name,
            method="HEURISTIC",
            solver="drsa",
            status=SolutionStatus.FEASIBLE,
            runtime_seconds=final_runtime,
            permutation=incumbent,
            bandwidth=report.actual_bandwidth,
            lower_bound=lower,
            upper_bound=report.actual_bandwidth,
            metadata={
                "variant": active_variant,
                "paper_faithful_params": is_paper_params,
                "paper_reference": "Torres-Jimenez et al. (2015), Information Sciences 303, 33-49",
                "seed": active_seed,
                "initial_mode": resolved_init,
                "initial_bandwidth": initial_bw,
                "final_fractional_delta": round(best_delta, 12),
                "final_evaluation_f": round(best_f, 12),
                "absolute_improvement": abs_imp,
                "relative_improvement": round(rel_imp, 6),
                "evaluation_mode": self.evaluation_mode,
                "use_incremental": active_incremental,
                "initial_temperature": self.initial_temperature,
                "final_temperature": self.final_temperature,
                "cooling": self.cooling,
                "initial_chain_length": self.initial_chain_length,
                "final_chain_length": lf_target,
                "gamma": round(gamma, 9),
                "expected_cooling_steps": round(expected_cooling_steps, 4),
                "cooling_steps": cooling_steps,
                "temperature_stages": stage_count,
                "operator_probabilities": {
                    "REX": round(norm_rex, 6),
                    "NEX": round(norm_nex, 6),
                    "ROT": round(norm_rot, 6),
                },
                "rot_max_separation": self.rot_max_separation,
                "iterations": stage_count,
                "evaluations": evaluations,
                "accepted_moves": accepted_moves,
                "rejected_moves": rejected_moves,
                "best_updates": best_bw_updates,
                "best_f_updates": best_f_updates,
                "operator_counts": op_counts,
                "operator_accepts": op_accepts,
                "operator_improvements": op_bw_improvements,
                "operator_f_improvements": op_f_improvements,
                "operator_noop_counts": op_noop_counts,
                "time_to_first_improvement_s": time_to_first_improvement_s,
                "time_to_best_s": time_to_best_s,
                "best_so_far_timeline": timeline,
                "stop_reason": stop_reason,
                "timed_out": stop_reason == "timeout",
                "bounded_execution": stop_reason != "final_temperature" and stop_reason != "trivial_or_edgeless",
                "certified_optimal_by_lb": certified_lb == report.actual_bandwidth,
                "incumbent_source": "heuristic",
            },
        )


__all__ = [
    "DRSASolver",
    "DualRepresentation",
    "compute_fractional_delta",
    "compute_increment_factor",
    "evaluate_solution",
]
