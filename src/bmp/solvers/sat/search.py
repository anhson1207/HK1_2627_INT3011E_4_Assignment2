"""Search utilities, exact domain reductions, and bounds calculation for SAT BMP solvers."""

from __future__ import annotations

from collections import deque
from functools import lru_cache
from time import monotonic
from typing import Mapping

from bmp.core.bounds import cuthill_mckee_order, degree_lower_bound, identity_upper_bound
from bmp.core.graph import Edge, Graph


@lru_cache(maxsize=256)
def _cached_component_diameters(
    vertices: tuple[int, ...], edges: frozenset[Edge]
) -> tuple[tuple[int, int], ...]:
    n = len(vertices)
    if n < 2 or not edges:
        return ()

    v_to_idx = {v: i for i, v in enumerate(vertices)}
    if n >= 40:
        try:
            import numpy as np
            from scipy.sparse import csr_matrix
            from scipy.sparse.csgraph import connected_components, shortest_path

            rows_idx: list[int] = []
            cols_idx: list[int] = []
            for u, v in edges:
                ui = v_to_idx[u]
                vi = v_to_idx[v]
                rows_idx.append(ui)
                cols_idx.append(vi)
                rows_idx.append(vi)
                cols_idx.append(ui)
            data = np.ones(len(rows_idx), dtype=np.int8)
            mat = csr_matrix((data, (rows_idx, cols_idx)), shape=(n, n))
            n_comp, labels = connected_components(mat, directed=False, return_labels=True)
            components: list[tuple[int, int]] = []
            counts = np.bincount(labels, minlength=n_comp)
            for cid in range(n_comp):
                c_size = int(counts[cid])
                if c_size >= 2:
                    idx = np.flatnonzero(labels == cid)
                    sub = mat[idx][:, idx]
                    dists = shortest_path(sub, directed=False, unweighted=True)
                    c_diam = int(np.max(dists))
                    components.append((c_size, max(1, c_diam)))
            return tuple(components)
        except ImportError:
            pass

    # Use C-speed bitmask BFS on dense graphs (|E| > 4*n) and compact array BFS on sparse graphs.
    if len(edges) > 4 * n:
        adj_mask = [0] * n
        for u, v in edges:
            ui = v_to_idx[u]
            vi = v_to_idx[v]
            adj_mask[ui] |= 1 << vi
            adj_mask[vi] |= 1 << ui
        unvisited = (1 << n) - 1
        components: list[tuple[int, int]] = []
        while unvisited:
            lsb = unvisited & -unvisited
            comp_mask = lsb
            q = lsb
            unvisited ^= lsb
            while q:
                nxt = 0
                f = q
                while f:
                    b = f & -f
                    f ^= b
                    nxt |= adj_mask[b.bit_length() - 1]
                nxt &= unvisited
                unvisited ^= nxt
                comp_mask |= nxt
                q = nxt
            c_size = comp_mask.bit_count()
            if c_size >= 2:
                c_diam = 0
                cm = comp_mask
                while cm:
                    s = cm & -cm
                    cm ^= s
                    vis = s
                    front = s
                    depth = -1
                    while front:
                        depth += 1
                        nxt = 0
                        f = front
                        while f:
                            b = f & -f
                            f ^= b
                            nxt |= adj_mask[b.bit_length() - 1]
                        nxt &= ~vis
                        vis |= nxt
                        front = nxt
                    if depth > c_diam:
                        c_diam = depth
                components.append((c_size, max(1, c_diam)))
        return tuple(components)

    adj: list[list[int]] = [[] for _ in range(n)]
    for u, v in edges:
        ui = v_to_idx[u]
        vi = v_to_idx[v]
        adj[ui].append(vi)
        adj[vi].append(ui)

    comp_visited = [False] * n
    seen_stamp = [0] * n
    stamp = 0
    components = []

    for root in range(n):
        if comp_visited[root]:
            continue
        comp_visited[root] = True
        comp_nodes = [root]
        head = 0
        while head < len(comp_nodes):
            curr = comp_nodes[head]
            head += 1
            for nbr in adj[curr]:
                if not comp_visited[nbr]:
                    comp_visited[nbr] = True
                    comp_nodes.append(nbr)

        c_size = len(comp_nodes)
        if c_size >= 2:
            c_diam = 0
            for start in comp_nodes:
                stamp += 1
                seen_stamp[start] = stamp
                frontier = [start]
                depth = -1
                while frontier:
                    depth += 1
                    next_frontier: list[int] = []
                    for u in frontier:
                        for v in adj[u]:
                            if seen_stamp[v] != stamp:
                                seen_stamp[v] = stamp
                                next_frontier.append(v)
                    frontier = next_frontier
                if depth > c_diam:
                    c_diam = depth
            components.append((c_size, max(1, c_diam)))

    return tuple(components)


def compute_component_diameters(graph: Graph) -> list[tuple[int, int]]:
    """Compute (component_size, component_diameter) for all components with >= 2 vertices."""
    return list(_cached_component_diameters(graph.vertices, graph.edges))


def compute_lower_bound(graph: Graph) -> int:
    """Compute certified lower bound for bandwidth.

    Uses:
    1. Maximum degree bound: ceil(Delta(G) / 2)
    2. Component diameter bound: max_C ceil((|C| - 1) / diam(C))
    """
    if not graph.edges or graph.order <= 1:
        return 0

    lb_degree = degree_lower_bound(graph)
    lb_component = 0
    for c_size, c_diam in compute_component_diameters(graph):
        lb_c = (c_size - 1 + c_diam - 1) // c_diam  # ceil((c_size - 1) / c_diam)
        if lb_c > lb_component:
            lb_component = lb_c

    return max(lb_degree, lb_component)


def select_anchor_vertex(graph: Graph) -> int:
    """Select a deterministic anchor vertex for reversal symmetry breaking.

    Priority:
    1. Maximum vertex degree
    2. Maximum sum of neighbor degrees
    3. Smallest vertex ID (as tie-breaker)
    """
    if not graph.vertices:
        raise ValueError("Cannot select anchor on an empty graph")

    degrees = {v: 0 for v in graph.vertices}
    nbr_deg_sum = {v: 0 for v in graph.vertices}
    adj: dict[int, list[int]] = {v: [] for v in graph.vertices}
    for u, v in graph.edges:
        degrees[u] += 1
        degrees[v] += 1
        adj[u].append(v)
        adj[v].append(u)
    for v in graph.vertices:
        nbr_deg_sum[v] = sum(degrees[nbr] for nbr in adj[v])

    return max(
        graph.vertices,
        key=lambda v: (degrees[v], nbr_deg_sum[v], -v),
    )


def extract_connected_components(graph: Graph) -> tuple[list[Graph], list[int]]:
    """Partition ``graph`` into non-trivial component subgraphs (size >= 2) and isolated vertices.

    Because edges exist only within connected components, packing each non-trivial
    component into contiguous label blocks and placing isolated vertices afterward
    preserves exact optimal bandwidth: B*(G) = max_i B*(C_i).
    """
    adj: dict[int, list[int]] = {v: [] for v in graph.vertices}
    for u, v in graph.edges:
        adj[u].append(v)
        adj[v].append(u)

    visited: set[int] = set()
    components: list[Graph] = []
    isolated: list[int] = []

    for start in graph.vertices:
        if start in visited:
            continue
        visited.add(start)
        nodes = [start]
        queue = deque([start])
        while queue:
            curr = queue.popleft()
            for nbr in adj[curr]:
                if nbr not in visited:
                    visited.add(nbr)
                    nodes.append(nbr)
                    queue.append(nbr)
        if len(nodes) == 1:
            isolated.append(nodes[0])
        else:
            node_set = set(nodes)
            sub_edges = [(u, v) for u, v in graph.edges if u in node_set and v in node_set]
            components.append(Graph.from_edges(nodes, sub_edges, name=f"{graph.name}__comp{len(components)}"))

    components.sort(key=lambda g: (-g.order, g.vertices[0]))
    return components, isolated


def reduce_isolated_vertices(graph: Graph) -> tuple[Graph, list[int]]:
    """Return induced subgraph on vertices with degree >= 1 plus the list of isolated vertices."""
    active_set: set[int] = set()
    for u, v in graph.edges:
        active_set.add(u)
        active_set.add(v)
    active = [v for v in graph.vertices if v in active_set]
    isolated = [v for v in graph.vertices if v not in active_set]
    if not isolated:
        return graph, []
    return Graph.from_edges(active, graph.edges, name=graph.name), isolated


def compose_component_permutations(
    graph: Graph,
    component_perms: list[Mapping[int, int]],
    isolated_vertices: list[int],
) -> dict[int, int]:
    """Combine valid labelings of disjoint non-trivial components + isolated vertices into a full bijection 1..n."""
    full_perm: dict[int, int] = {}
    offset = 0
    for c_perm in component_perms:
        if not c_perm:
            continue
        ordered = sorted(c_perm.items(), key=lambda item: item[1])
        for idx, (vertex, _) in enumerate(ordered, start=1):
            full_perm[vertex] = offset + idx
        offset += len(ordered)
    for idx, vertex in enumerate(isolated_vertices, start=offset + 1):
        full_perm[vertex] = idx
    if len(full_perm) != graph.order:
        raise ValueError(
            f"Composed permutation covers {len(full_perm)} vertices, expected {graph.order}"
        )
    return full_perm


def tighten_permutation_local(
    graph: Graph,
    perm: Mapping[int, int],
    *,
    max_steps: int = 250,
    time_budget_s: float = 0.25,
) -> tuple[int, dict[int, int]]:
    """Fast deterministic local refinement targeting critical edges causing peak bandwidth."""
    from bmp.core.validation import calculate_bandwidth

    cur = dict(perm)
    n = graph.order
    if n <= 2 or not graph.edges:
        return calculate_bandwidth(graph, cur), cur

    adj_lists: dict[int, list[int]] = {v: [] for v in graph.vertices}
    for u, v in graph.edges:
        adj_lists[u].append(v)
        adj_lists[v].append(u)
    adj: dict[int, tuple[int, ...]] = {v: tuple(nbrs) for v, nbrs in adj_lists.items()}
    inv: dict[int, int] = {pos: v for v, pos in cur.items()}
    cur_bw = calculate_bandwidth(graph, cur)
    edge_set = graph.edges
    start_t = monotonic()

    for _ in range(max_steps):
        if time_budget_s > 0 and (monotonic() - start_t) >= time_budget_s:
            break
        critical_edges = [(u, v) for u, v in edge_set if abs(cur[u] - cur[v]) == cur_bw]
        if not critical_edges:
            break
        improved = False
        seen_crit: set[int] = set()
        candidates: list[int] = []
        for u, v in critical_edges:
            for w in (u, v):
                if w not in seen_crit:
                    seen_crit.add(w)
                    candidates.append(w)

        # Precompute [min_nbr_pos, max_nbr_pos] per vertex once per step for O(1) swap pruning.
        lo_pos: dict[int, int] = {}
        hi_pos: dict[int, int] = {}
        for x in graph.vertices:
            xn = adj[x]
            if xn:
                vals = [cur[y] for y in xn]
                lo_pos[x] = min(vals)
                hi_pos[x] = max(vals)

        for u in candidates[:16]:
            if time_budget_s > 0 and (monotonic() - start_t) >= time_budget_s:
                break
            nbrs = adj[u]
            if not nbrs:
                continue
            lo = lo_pos[u]
            hi = hi_pos[u]
            p_u = cur[u]
            # Exact necessary condition for u_span < cur_bw (even if adjacent to v):
            # any neighbor y != v has abs(cand_pos - cur[y]) < cur_bw => hi - cur_bw < cand_pos < lo + cur_bw
            pos_lo = max(1, hi - cur_bw + 1)
            pos_hi = min(n, lo + cur_bw - 1)
            if pos_lo > pos_hi:
                continue
            mid = max(pos_lo, min(pos_hi, (lo + hi) // 2))
            best_swap_v: int | None = None
            best_u_span = max(abs(p_u - cur[x]) for x in nbrs)
            max_delta = max(mid - pos_lo, pos_hi - mid)
            for delta in range(0, max_delta + 1):
                for cand_pos in (mid - delta, mid + delta):
                    if cand_pos < pos_lo or cand_pos > pos_hi or cand_pos == p_u:
                        continue
                    v = inv[cand_pos]
                    if v in lo_pos:
                        # Exact necessary condition for v_span < cur_bw on all y != u:
                        if p_u - lo_pos[v] >= cur_bw or hi_pos[v] - p_u >= cur_bw:
                            continue
                    if (u, v) in edge_set or (v, u) in edge_set:
                        if abs(p_u - cand_pos) >= cur_bw:
                            continue
                    u_span = max(abs(cand_pos - (p_u if x == v else cur[x])) for x in nbrs)
                    if u_span >= cur_bw:
                        continue
                    v_nbrs = adj[v]
                    v_span = max((abs(p_u - (cand_pos if x == u else cur[x])) for x in v_nbrs), default=0)
                    if v_span < cur_bw and (u_span < best_u_span or v == critical_edges[0][0]):
                        best_swap_v = v
                        best_u_span = u_span
                        break
                if best_swap_v is not None:
                    break
            if best_swap_v is not None:
                v = best_swap_v
                p_v = cur[v]
                cur[u], cur[v] = p_v, p_u
                inv[p_v], inv[p_u] = u, v
                improved = True
                break
        if improved:
            new_bw = calculate_bandwidth(graph, cur)
            if new_bw < cur_bw:
                cur_bw = new_bw
            else:
                new_crit = sum(1 for u, v in edge_set if abs(cur[u] - cur[v]) == cur_bw)
                if new_crit >= len(critical_edges):
                    break
        else:
            break

    return calculate_bandwidth(graph, cur), cur


def compute_initial_upper_bound(
    graph: Graph,
    heuristic_permutation: Mapping[int, int] | None = None,
    *,
    symmetry_breaking: bool = False,
    init_mode: str = "rcm",
) -> tuple[int, dict[int, int]]:
    """Compute an initial upper bound and valid permutation.

    If symmetry_breaking is True, normalises the incumbent so the anchor vertex
    satisfies p(anchor) <= ceil(n / 2).
    """
    from bmp.core.validation import calculate_bandwidth

    if not graph.edges or graph.order <= 1:
        identity_perm = {v: i + 1 for i, v in enumerate(graph.vertices)}
        return 0, identity_perm

    if heuristic_permutation is not None:
        perm = dict(heuristic_permutation)
        bw = calculate_bandwidth(graph, perm)
    elif init_mode == "identity":
        bw, perm = identity_upper_bound(graph)
    else:
        bw, perm = identity_upper_bound(graph)
        order = cuthill_mckee_order(graph)
        for candidate_order in (order, list(reversed(order))):
            candidate = {v: label for label, v in enumerate(candidate_order, start=1)}
            candidate_bw = calculate_bandwidth(graph, candidate)
            if candidate_bw < bw:
                bw, perm = candidate_bw, candidate
        if init_mode == "rcm_tight":
            t_bw, t_perm = tighten_permutation_local(graph, perm)
            if t_bw < bw:
                bw, perm = t_bw, t_perm

    if symmetry_breaking and graph.order >= 2:
        anchor = select_anchor_vertex(graph)
        cutoff = (graph.order + 1) // 2
        if perm[anchor] > cutoff:
            perm = {v: graph.order + 1 - label for v, label in perm.items()}
            bw = calculate_bandwidth(graph, perm)

    return bw, perm


def _project_permutation(sub_graph: Graph, parent_perm: Mapping[int, int]) -> dict[int, int]:
    """Compress a valid permutation of the full graph onto vertices of ``sub_graph`` preserving relative order."""
    ordered = sorted(sub_graph.vertices, key=lambda v: parent_perm[v])
    return {v: rank for rank, v in enumerate(ordered, start=1)}


class _SingleComponentProgressProxy:
    """Forward single-component progress/events to parent worker pipe as full-graph permutations."""

    def __init__(self, conn: object, graph: Graph, isolated: list[int]) -> None:
        self._conn = conn
        self._graph = graph
        self._isolated = isolated

    def send(self, msg: tuple[str, dict[str, object]]) -> None:
        kind, payload = msg
        if kind == "progress" and self._isolated and "permutation" in payload:
            comp_perm = payload["permutation"]
            full_perm = compose_component_permutations(self._graph, [comp_perm], self._isolated)  # type: ignore[arg-type]
            updated = dict(payload)
            updated["permutation"] = full_perm
            self._conn.send((kind, updated))  # type: ignore[attr-defined]
        else:
            self._conn.send((kind, payload))  # type: ignore[attr-defined]


class _MultiComponentProgressProxy:
    """Forward multi-component progress to parent worker pipe using combined initial component perms."""

    def __init__(
        self,
        conn: object,
        graph: Graph,
        comp_perms: list[dict[int, int]],
        comp_idx: int,
        isolated: list[int],
    ) -> None:
        self._conn = conn
        self._graph = graph
        self._comp_perms = comp_perms
        self._comp_idx = comp_idx
        self._isolated = isolated

    def send(self, msg: tuple[str, dict[str, object]]) -> None:
        from bmp.core.validation import calculate_bandwidth

        kind, payload = msg
        if kind == "progress" and "permutation" in payload:
            self._comp_perms[self._comp_idx] = dict(payload["permutation"])  # type: ignore[arg-type]
            full_perm = compose_component_permutations(self._graph, self._comp_perms, self._isolated)
            full_bw = calculate_bandwidth(self._graph, full_perm)
            updated = dict(payload)
            updated["permutation"] = full_perm
            updated["bandwidth"] = full_bw
            self._conn.send((kind, updated))  # type: ignore[attr-defined]
        else:
            self._conn.send((kind, payload))  # type: ignore[attr-defined]


def solve_sat_with_decomposition(
    solver_factory: object,
    graph: Graph,
    *,
    strategy_label: str,
    timeout_seconds: float | None,
    heuristic_permutation: Mapping[int, int] | None,
    symmetry_breaking: bool,
    limits: object,
) -> object:
    """Solve BMP exactly by dropping isolated vertices and solving connected components independently."""
    from bmp.core.solution import SolutionStatus, SolverResult
    from bmp.core.validation import calculate_bandwidth

    started = monotonic()
    n = graph.order
    if n <= 1 or not graph.edges:
        identity_perm = {v: i + 1 for i, v in enumerate(graph.vertices)}
        return SolverResult(
            instance=graph.name,
            method="SAT",
            solver=getattr(solver_factory, "backend_name", "cadical"),
            encoding=getattr(getattr(solver_factory, "encoder", None), "name", "unknown"),
            strategy=strategy_label,
            status=SolutionStatus.OPTIMAL,
            bandwidth=0,
            permutation=identity_perm,
            runtime_s=0.0,
            encoding_time_s=0.0,
            solving_time_s=0.0,
            num_variables=0,
            num_clauses=0,
            sat_calls=0,
            lower_bound=0,
            upper_bound=0,
            metadata={
                "symmetry_breaking": symmetry_breaking,
                "sat_solved_any": False,
                "incumbent_source": "BOUNDS_OPTIMALITY_CERTIFICATE",
                "decomposed": True,
                "component_count": 0,
                "isolated_count": n,
            },
        )

    components, isolated = extract_connected_components(graph)
    sub_solver = solver_factory._clone_non_decomposed()  # type: ignore[attr-defined]
    parent_conn = getattr(solver_factory, "_progress_conn", None)
    if parent_conn is not None and len(components) == 1:
        sub_solver._progress_conn = (  # type: ignore[attr-defined]
            parent_conn if not isolated else _SingleComponentProgressProxy(parent_conn, graph, isolated)
        )
    shared_comp_perms: list[dict[int, int]] = [
        _project_permutation(comp, heuristic_permutation)
        if heuristic_permutation is not None
        else identity_upper_bound(comp)[1]
        for comp in components
    ]
    comp_perms: list[dict[int, int]] = []
    comp_results: list[SolverResult] = []
    comp_bws: list[int] = []
    comp_lbs: list[int] = []
    total_enc = 0.0
    total_solve = 0.0
    total_calls = 0
    max_vars = 0
    max_clauses = 0
    any_skipped = False
    skipped_reason: str | None = None
    any_error = False
    error_reason: str | None = None
    any_sat_solved = False
    any_timeout = False

    for idx, comp in enumerate(components):
        sub_heur = _project_permutation(comp, heuristic_permutation) if heuristic_permutation is not None else None
        if parent_conn is not None and len(components) > 1:
            sub_solver._progress_conn = _MultiComponentProgressProxy(  # type: ignore[attr-defined]
                parent_conn, graph, shared_comp_perms, idx, isolated
            )
        remaining = None if timeout_seconds is None else max(0.0, timeout_seconds - (monotonic() - started))
        res: SolverResult = sub_solver.solve(
            comp,
            timeout_seconds=remaining,
            heuristic_permutation=sub_heur,
            symmetry_breaking=symmetry_breaking,
            limits=limits,
        )
        comp_results.append(res)
        total_enc += float(res.encoding_time_s or 0.0)
        total_solve += float(res.solving_time_s or 0.0)
        total_calls += int(res.sat_calls or 0)
        if res.num_variables is not None:
            max_vars = max(max_vars, int(res.num_variables))
        if res.num_clauses is not None:
            max_clauses = max(max_clauses, int(res.num_clauses))

        c_perm = dict(res.permutation) if res.permutation is not None else (
            sub_heur if sub_heur is not None else identity_upper_bound(comp)[1]
        )
        shared_comp_perms[idx] = c_perm
        c_bw = calculate_bandwidth(comp, c_perm)
        comp_perms.append(c_perm)
        comp_bws.append(c_bw)
        c_lb = int(res.lower_bound) if res.lower_bound is not None else compute_lower_bound(comp)
        comp_lbs.append(c_lb)
        if (res.metadata or {}).get("sat_solved_any"):
            any_sat_solved = True
        if res.status is SolutionStatus.SKIPPED:
            any_skipped = True
            skipped_reason = skipped_reason or str((res.metadata or {}).get("skipped_reason") or "ResourceLimits")
        elif res.status is SolutionStatus.ERROR:
            any_error = True
            error_reason = error_reason or str((res.metadata or {}).get("worker_reason") or "Component error")
        elif res.status is SolutionStatus.TIMEOUT:
            any_timeout = True

    full_perm = compose_component_permutations(graph, comp_perms, isolated)
    full_bw = calculate_bandwidth(graph, full_perm)
    full_lb = max(comp_lbs, default=0)

    if any_error:
        status = SolutionStatus.ERROR
    elif full_lb == full_bw and not any_error:
        status = SolutionStatus.OPTIMAL
    elif any_skipped:
        status = SolutionStatus.SKIPPED
    elif any_timeout and not any_sat_solved:
        status = SolutionStatus.TIMEOUT
    elif any_timeout or full_lb < full_bw:
        status = SolutionStatus.FEASIBLE
    else:
        status = SolutionStatus.OPTIMAL

    return SolverResult(
        instance=graph.name,
        method="SAT",
        solver=getattr(solver_factory, "backend_name", "cadical"),
        encoding=getattr(getattr(solver_factory, "encoder", None), "name", "unknown"),
        strategy=strategy_label,
        status=status,
        bandwidth=full_bw,
        permutation=full_perm,
        runtime_s=monotonic() - started,
        encoding_time_s=total_enc,
        solving_time_s=total_solve,
        num_variables=max_vars if max_vars > 0 else None,
        num_clauses=max_clauses if max_clauses > 0 else None,
        sat_calls=total_calls,
        lower_bound=full_lb,
        upper_bound=full_bw,
        metadata={
            "symmetry_breaking": symmetry_breaking,
            "sat_solved_any": any_sat_solved,
            "incumbent_source": "SAT" if any_sat_solved else "HEURISTIC",
            "skipped_reason": skipped_reason,
            "worker_reason": error_reason,
            "decomposed": True,
            "component_count": len(components),
            "isolated_count": len(isolated),
            "largest_component_n": max((c.order for c in components), default=0),
            "component_statuses": [r.status.value for r in comp_results],
            "component_bws": comp_bws,
            "component_lbs": comp_lbs,
        },
    )


__all__ = [
    "compose_component_permutations",
    "compute_component_diameters",
    "compute_initial_upper_bound",
    "compute_lower_bound",
    "extract_connected_components",
    "reduce_isolated_vertices",
    "select_anchor_vertex",
    "solve_sat_with_decomposition",
    "tighten_permutation_local",
]
