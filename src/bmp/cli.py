"""Command-line entry point for Phase 1 workflows."""

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
from bmp.core.validation import validate_assignment
from bmp.io.readers import read_graph, write_edge_list
from bmp.solvers.brute_force import BruteForceSolver

FORMATS = ("auto", "edge-list", "adjacency-matrix", "matrix-market")


def _solve(
    input_path: Path,
    *,
    graph_format: str,
    timeout_seconds: float | None,
    max_vertices: int,
) -> dict[str, object]:
    graph = read_graph(input_path, graph_format)  # type: ignore[arg-type]
    result = BruteForceSolver(max_vertices=max_vertices).solve(
        graph,
        timeout_seconds=timeout_seconds,
    )
    payload = result.to_dict()
    payload["instance"] = {
        "id": graph.name,
        "n": graph.order,
        "m": graph.size,
        "density": graph.density,
        "source": str(input_path),
    }
    if result.assignment is not None:
        validation = validate_assignment(
            graph,
            result.assignment,
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

    solve = subparsers.add_parser("solve", help="solve a tiny instance with the exact oracle")
    solve.add_argument("input", type=Path)
    solve.add_argument("--format", choices=FORMATS, default="auto")
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
    solver = solve.get("solver", "brute-force")
    if solver != "brute-force":
        raise ValueError(f"Phase 1 supports only solver='brute-force', got {solver!r}")
    return _solve(
        configured_input,
        graph_format=solve.get("format", "auto"),
        timeout_seconds=solve.get("timeout_seconds"),
        max_vertices=solve.get("max_vertices", 10),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "solve":
            payload = _solve(
                args.input,
                graph_format=args.format,
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
            assignment_data = raw.get("assignment", raw)
            if not isinstance(assignment_data, dict):
                raise ValueError("Solution JSON must contain an assignment object")
            assignment = {int(vertex): label for vertex, label in assignment_data.items()}
            claimed = raw.get("bandwidth") if isinstance(raw, dict) else None
            payload = validate_assignment(
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
        else:  # pragma: no cover - argparse enforces a valid command
            parser.error("Unknown command")
            return 2
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "ERROR", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2

    print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
