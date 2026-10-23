"""Command-line entry point for BMP workflows and SAT solving."""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path
from typing import Sequence

from bmp.core.generators import (
    complete_graph,
    cycle_graph,
    edgeless_graph,
    erdos_renyi_graph,
    path_graph,
    star_graph,
)
from bmp.core.validation import validate_solution
from bmp.encodings.cardinality import get_amo_encoder
from bmp.encodings.pairwise import PairwiseEncoding
from bmp.io.readers import read_graph, write_edge_list
from bmp.solvers.brute_force import BruteForceSolver
from bmp.solvers.sat.repeated import RepeatedSATSolver

FORMATS = ("auto", "edge-list", "adjacency-matrix", "matrix-market")


def _solve_instance(
    input_path: Path,
    *,
    graph_format: str = "auto",
    solver_name: str = "cadical",
    encoding_name: str = "pairwise",
    strategy_name: str = "repeated",
    amo_name: str = "pairwise",
    search_mode: str = "linear",
    symmetry_breaking: bool = False,
    timeout_seconds: float | None = None,
    max_vertices: int = 10,
) -> dict[str, object]:
    graph = read_graph(input_path, graph_format)  # type: ignore[arg-type]

    if strategy_name == "brute-force" or solver_name == "brute-force":
        solver = BruteForceSolver(max_vertices=max_vertices)
        result = solver.solve(graph, timeout_seconds=timeout_seconds)
    elif strategy_name in ("repeated", "repeated_linear", "repeated_binary"):
        if encoding_name == "pairwise":
            encoder = PairwiseEncoding(amo=amo_name)
        elif encoding_name == "order":
            from bmp.encodings.order import OrderEncoding
            encoder = OrderEncoding()
        else:
            raise ValueError(f"Unknown encoding: {encoding_name}")

        mode = "binary" if "binary" in strategy_name or search_mode == "binary" else "linear"
        sat_solver = RepeatedSATSolver(
            encoder=encoder,
            backend_name=solver_name,
            search_mode=mode,
        )
        result = sat_solver.solve(
            graph,
            timeout_seconds=timeout_seconds,
            symmetry_breaking=symmetry_breaking,
        )
    elif strategy_name == "incremental":
        from bmp.solvers.sat.incremental import IncrementalSATSolver
        if encoding_name == "pairwise":
            encoder = PairwiseEncoding(amo=amo_name)
        elif encoding_name == "order":
            from bmp.encodings.order import OrderEncoding
            encoder = OrderEncoding()
        else:
            raise ValueError(f"Unknown encoding: {encoding_name}")

        inc_solver = IncrementalSATSolver(
            encoder=encoder,
            backend_name=solver_name,
        )
        result = inc_solver.solve(
            graph,
            timeout_seconds=timeout_seconds,
            symmetry_breaking=symmetry_breaking,
        )
    else:
        raise ValueError(f"Unsupported strategy: {strategy_name}")

    payload = result.to_dict()
    payload["instance_info"] = {
        "id": graph.name,
        "n": graph.order,
        "m": graph.size,
        "density": graph.density,
        "source": str(input_path),
    }

    if result.permutation is not None:
        validation = validate_solution(
            graph,
            result.permutation,
            claimed_bandwidth=result.bandwidth,
        )
        payload["validation"] = validation.to_dict()
        if not validation.valid:
            raise RuntimeError(f"Internal solver validation failed: {validation.errors}")

    return payload


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bmp",
        description="Research tools for the bandwidth minimization problem.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    solve = subparsers.add_parser("solve", help="solve an instance using SAT or brute force")
    solve.add_argument("input", nargs="?", type=Path, default=None, help="path to input graph file")
    solve.add_argument("--graph", "-g", type=Path, default=None, dest="graph_opt", help="alias for input path")
    solve.add_argument("--format", choices=FORMATS, default="auto")
    solve.add_argument("--solver", choices=("cadical", "cadical195", "brute-force"), default="cadical")
    solve.add_argument("--encoding", choices=("pairwise", "order"), default="pairwise")
    solve.add_argument("--strategy", choices=("repeated", "incremental", "brute-force"), default="repeated")
    solve.add_argument("--amo", choices=("pairwise", "sequential"), default="pairwise")
    solve.add_argument("--search-mode", choices=("linear", "binary"), default="linear")
    solve.add_argument("--symmetry-breaking", action="store_true", default=False)
    solve.add_argument("--timeout", type=float, default=None)
    solve.add_argument("--max-vertices", type=int, default=10)

    run_config = subparsers.add_parser("run-config", help="run a TOML solve configuration")
    run_config.add_argument("config", type=Path)

    inspect = subparsers.add_parser("inspect", help="parse and summarise a graph")
    inspect.add_argument("input", type=Path)
    inspect.add_argument("--format", choices=FORMATS, default="auto")

    validate = subparsers.add_parser("validate", help="validate a JSON assignment independently")
    validate.add_argument("input", type=Path)
    validate.add_argument("solution", type=Path)
    validate.add_argument("--format", choices=FORMATS, default="auto")

    generate = subparsers.add_parser("generate", help="generate a deterministic edge-list instance")
    generate.add_argument("family", choices=("path", "cycle", "complete", "star", "edgeless", "random"))
    generate.add_argument("order", type=int, help="total number of vertices")
    generate.add_argument("output", type=Path)
    generate.add_argument("--probability", type=float, default=0.25)
    generate.add_argument("--seed", type=int, default=0)

    bench = subparsers.add_parser("benchmark-sat", help="run SAT benchmark suite across configurations")
    bench.add_argument("--output-json", type=Path, default=Path("data/sat_benchmark_results.json"))
    bench.add_argument("--output-csv", type=Path, default=Path("data/sat_benchmark_results.csv"))
    bench.add_argument("--timeout", type=float, default=20.0)
    bench.add_argument("--quick", action="store_true", default=False, help="run small quick suite")
    return parser


def _run_config(path: Path) -> dict[str, object]:
    with path.open("rb") as stream:
        config = tomllib.load(stream)
    try:
        solve = config["solve"]
        configured_input = Path(solve["input"])
    except (KeyError, TypeError) as error:
        raise ValueError("Config must contain [solve] and solve.input") from error
    if not configured_input.is_absolute():
        configured_input = path.parent / configured_input

    solver_name = solve.get("solver", "cadical")
    encoding_name = solve.get("encoding", "pairwise")
    strategy_name = solve.get("strategy", "repeated")
    amo_name = solve.get("amo", "pairwise")

    return _solve_instance(
        configured_input,
        graph_format=solve.get("format", "auto"),
        solver_name=solver_name,
        encoding_name=encoding_name,
        strategy_name=strategy_name,
        amo_name=amo_name,
        timeout_seconds=solve.get("timeout_seconds"),
        max_vertices=solve.get("max_vertices", 10),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "solve":
            input_file = args.input or args.graph_opt
            if input_file is None:
                parser.error("Must specify graph input either as positional argument or via --graph/-g")

            payload = _solve_instance(
                input_file,
                graph_format=args.format,
                solver_name=args.solver,
                encoding_name=args.encoding,
                strategy_name=args.strategy,
                amo_name=args.amo,
                search_mode=args.search_mode,
                symmetry_breaking=args.symmetry_breaking,
                timeout_seconds=args.timeout,
                max_vertices=args.max_vertices,
            )
        elif args.command == "run-config":
            payload = _run_config(args.config)
        elif args.command == "inspect":
            payload = read_graph(args.input, args.format).to_dict()
        elif args.command == "validate":
            graph = read_graph(args.input, args.format)
            raw = json.loads(args.solution.read_text(encoding="utf-8"))
            assignment_data = raw.get("permutation", raw.get("assignment", raw))
            if not isinstance(assignment_data, dict):
                raise ValueError("Solution JSON must contain an assignment or permutation object")
            assignment = {int(vertex): label for vertex, label in assignment_data.items()}
            claimed = raw.get("bandwidth") if isinstance(raw, dict) else None
            payload = validate_solution(
                graph,
                assignment,
                claimed_bandwidth=claimed,
            ).to_dict()
        elif args.command == "generate":
            if args.family == "path":
                graph = path_graph(args.order)
            elif args.family == "cycle":
                graph = cycle_graph(args.order)
            elif args.family == "complete":
                graph = complete_graph(args.order)
            elif args.family == "star":
                if args.order < 2:
                    raise ValueError("A star graph needs at least two vertices")
                graph = star_graph(args.order - 1)
            elif args.family == "edgeless":
                graph = edgeless_graph(args.order)
            else:
                graph = erdos_renyi_graph(
                    args.order,
                    args.probability,
                    seed=args.seed,
                )
            write_edge_list(graph, args.output)
            payload = {"output": str(args.output), "graph": graph.to_dict()}
        elif args.command == "benchmark-sat":
            from bmp.solvers.sat.benchmark import export_csv, export_json, run_benchmark
            if args.quick:
                suite = [
                    path_graph(5),
                    star_graph(4),
                    cycle_graph(4),
                    complete_graph(5),
                    edgeless_graph(5),
                ]
            else:
                suite = [
                    path_graph(5),
                    path_graph(7),
                    cycle_graph(4),
                    cycle_graph(6),
                    star_graph(4),
                    star_graph(6),
                    complete_graph(5),
                    edgeless_graph(5),
                    erdos_renyi_graph(6, 0.35, seed=42),
                    erdos_renyi_graph(7, 0.4, seed=100),
                ]
            records = run_benchmark(suite, timeout_per_instance=args.timeout)
            if args.output_csv:
                args.output_csv.parent.mkdir(parents=True, exist_ok=True)
                export_csv(records, args.output_csv)
            if args.output_json:
                args.output_json.parent.mkdir(parents=True, exist_ok=True)
                export_json(records, args.output_json)
            payload = {
                "num_instances": len(suite),
                "num_records": len(records),
                "output_json": str(args.output_json),
                "output_csv": str(args.output_csv),
            }
        else:  # pragma: no cover
            parser.error("Unknown command")
            return 2
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "ERROR", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2

    print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
