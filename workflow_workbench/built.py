"""Check the graph that was actually BUILT, not the declaration that was supposed to build it.

Every other check in this package reads `nodes`/`joins`/`decisions`/`edges` — data, before an
engine exists. That is the point of them, and it is also their limit: a design that overrides
`build_pydantic_structure()` wires itself in CODE, so walking `edges` would be checking a fiction.
`check()` says `NOT CHECKED` and stops.

This module removes the trade. After `build()` there is a real `Graph` that knows its own
topology, and it can be walked whatever produced it:

    graph.nodes             dict[node_id, node]   — a Step, Join or Decision
    graph.edges_by_source   dict[node_id, [Path]] — each Path holds DestinationMarkers
    Decision.branches       the branch targets, which are NOT in edges_by_source

So the `edges` declaration stops being decorative when overridden and becomes a CLAIM that gets
verified. That matters more than the reachability it restores: before this, a hand-wired design
could carry an `edges` declaration that was an outright lie, `diagram()` would draw the lie, and
nothing would notice.

⚠️ This is necessarily POST-BUILD, so it needs every implementation. It does not replace
`check()` — that still runs on the declaration alone, before a line of code is written, which no
amount of graph introspection can do.

⚠️ It cannot verify what the built graph does not encode. A `matches=` predicate on a branch is a
callable; that it exists is checkable, what it decides is not.
"""
from __future__ import annotations

from typing import Any

from workflow_workbench.spec import EdgeSpec, _End, _Start

__all__ = ["check_built_topology", "built_adjacency", "START_ID", "END_ID"]

START_ID = "__start__"
END_ID = "__end__"


def built_adjacency(graph: Any) -> dict[str, list[str]]:
    """`node id -> the node ids it points at`, read off the built graph.

    ⛔ Decision branches are NOT in `edges_by_source`. They hang off the `Decision` node object,
    one `DecisionBranch` per branch, each with its own `path`. Reading only `edges_by_source`
    made every branching design report its whole downstream half as unreachable — seven false
    findings on the ladder's triage example, which is how this was found. A check that fires on
    correct designs is worse than no check, because it teaches people to skip the output.
    """
    adj: dict[str, list[str]] = {}

    for node_id, node in graph.nodes.items():
        for branch in getattr(node, "branches", None) or []:
            for item in getattr(getattr(branch, "path", None), "items", ()):
                dest = getattr(item, "destination_id", None)
                if dest is not None:
                    adj.setdefault(str(node_id), []).append(str(dest))

    for src, paths in graph.edges_by_source.items():
        for path in paths:
            for item in getattr(path, "items", ()):
                dest = getattr(item, "destination_id", None)
                if dest is not None:
                    adj.setdefault(str(src), []).append(str(dest))
    return adj


def _endpoint_id(ep: Any) -> str:
    if isinstance(ep, _Start):
        return START_ID
    if isinstance(ep, _End):
        return END_ID
    return ep.name


def _reachable(adj: dict[str, list[str]], start: str,
               stop_at: frozenset[str] = frozenset()) -> set[str]:
    """Everything reachable from `start`, without expanding THROUGH anything in `stop_at`.

    The stop set is what makes the declared-edge check tolerant of engine-inserted nodes. A
    declared `START -> transform` becomes `__start__ -> map -> transform` once `.map()` is used,
    and `map` is not a node anyone declared — so passing through it is fine, while passing through
    another DECLARED node would mean the wiring is not what the declaration says.
    """
    seen: set[str] = set()
    stack = [start]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        if cur in stop_at and cur != start:
            continue
        stack.extend(adj.get(cur, ()))
    return seen


def check_built_topology(spec: Any, graph: Any) -> list[str]:
    """Three questions about the real graph, in the order their answers stop being trustworthy.

        present     is every declared node IN the built graph
        reachable   can it be reached, and can it reach END
        honoured    does every declared edge correspond to a real path

    ⚠️ `spec` is typed `Any` because `graph_spec` imports this module; it is always a `GraphSpec`.
    """
    declared = [*spec.nodes, *spec.joins, *spec.decisions]
    declared_ids = {n.name for n in declared}
    adj = built_adjacency(graph)
    findings: list[str] = []

    # ── 1. present ──────────────────────────────────────────────────────────────────────────
    #
    # ⚠️ A step that nothing wires is not an error to pydantic-graph — `g.step()` accepts it and
    # `build()` DROPS it. So a strategy can bind an implementation that is then silently deleted,
    # and the run succeeds. That is the failure this question exists for.
    for n in declared:
        if n.name not in graph.nodes:
            findings.append(
                f"{n.name!r} is declared, and is NOT in the built graph. A node nothing wires is "
                f"dropped at build time, so its implementation was bound and then discarded — the "
                f"run will succeed without it.")

    # ── 2. reachable ────────────────────────────────────────────────────────────────────────
    reverse: dict[str, list[str]] = {}
    for src, dests in adj.items():
        for d in dests:
            reverse.setdefault(d, []).append(src)
    from_start = _reachable(adj, START_ID)
    to_end = _reachable(reverse, END_ID)

    for n in declared:
        if n.name not in graph.nodes:
            continue
        if n.name not in from_start:
            findings.append(
                f"{n.name!r} is unreachable from START in the BUILT graph — not merely in the "
                f"declaration. Its implementation never runs.")
        if n.name not in to_end:
            findings.append(
                f"{n.name!r} cannot reach END in the BUILT graph. Whatever it produces is "
                f"discarded.")

    # ── 3. honoured ─────────────────────────────────────────────────────────────────────────
    #
    # ⛔ THE ONE THAT WAS MISSING ENTIRELY. Without it a hand-wired design could declare any
    # `edges` at all — the declaration was never compared to anything — and `diagram()` would
    # draw it faithfully. A wrong picture that nobody can catch is worse than no picture.
    for e in spec.edges:
        src, dst = _endpoint_id(e.source), _endpoint_id(e.target)
        if src != START_ID and src not in graph.nodes:
            continue                       # already reported by question 1
        stop = frozenset((declared_ids | {START_ID, END_ID}) - {src})
        if dst not in _reachable(adj, src, stop_at=stop):
            findings.append(
                f"the declaration says {src} -> {dst}, but in the BUILT graph {dst} is not "
                f"reachable from {src} without passing through another declared node. The "
                f"`edges` declaration does not describe what was built, so every diagram of this "
                f"design is wrong.")

    return findings


def check_declared_branches(spec: Any, graph: Any) -> list[str]:
    """Each declared `when=` type is a branch the built Decision actually has.

    Free, because `DecisionBranch.source` carries the matched type — so the declaration can be
    compared against the engine's own record of it rather than trusted.
    """
    findings: list[str] = []
    for dec in spec.decisions:
        node = graph.nodes.get(dec.name)
        built = {getattr(b, "source", None) for b in getattr(node, "branches", None) or []}
        for e in spec.edges:
            if e.source is dec and e.when is not None and e.when not in built:
                names = sorted(getattr(t, "__name__", str(t)) for t in built)
                findings.append(
                    f"decision {dec.name!r} declares a branch on "
                    f"{getattr(e.when, '__name__', e.when)}, which the built graph does not have "
                    f"(it has: {names or 'none'}).")
    return findings
