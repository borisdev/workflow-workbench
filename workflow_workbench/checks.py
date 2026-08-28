"""Every check, as pure data. No `pydantic_graph` import anywhere in this module.

Each returns a list of findings — strings a human can act on — and never raises. An empty list is
a pass; `GraphSpec.check()` is what turns a non-empty list into an exception.

⚠️ Findings say what is wrong AND what it costs. "node 'x' is unreachable" is a fact; "…so its
implementation never runs, and a strategy that binds it will look like it works" is a reason to
fix it.
"""
from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from workflow_workbench.spec import EdgeSpec, NodeSpec, StrategySpec, _End, _Start, is_sentinel

__all__ = ["check_names", "check_reachable", "check_variables", "check_bindings",
           "check_implementations"]


def _name(ep: Any) -> str:
    return "START" if isinstance(ep, _Start) else "END" if isinstance(ep, _End) else ep.name


def check_names(nodes: tuple[NodeSpec, ...]) -> list[str]:
    """Node names must be unique — `render()` uses them as graph node ids.

    ⚠️ This check exists BECAUSE `NodeSpec` is `eq=False`. Identity keying is what stops a
    copy-pasted declaration silently overwriting another's implementation; the cost is that two
    distinct nodes may share a name, and pydantic-graph would then refuse with a message about
    node ids that points at the render, not at the declaration.
    """
    findings, seen = [], {}
    for n in nodes:
        seen.setdefault(n.name, []).append(n)
    for name, group in seen.items():
        if len(group) > 1:
            findings.append(
                f"{len(group)} different nodes are named {name!r}. Node names become graph node "
                f"ids, so this cannot be rendered — and because NodeSpec is identity-keyed these "
                f"really are separate nodes, not one node declared twice.")
    return findings


def check_reachable(nodes: tuple[NodeSpec, ...], edges: tuple[EdgeSpec, ...]) -> list[str]:
    """Every node reachable from START, and every node able to reach END.

    Pure Python over the declaration — no graph is built, so this runs before a single
    implementation exists. Cycle-safe via a seen-set (verified in `docs/probe_api.py` probe 3).

    Both directions matter and they catch different mistakes:
      · unreachable from START — the node never runs; a strategy binding it looks like it works
      · cannot reach END — the work is done and thrown away, which reads as a silent drop
    """
    findings: list[str] = []
    fwd: dict[Any, list[Any]] = {}
    bwd: dict[Any, list[Any]] = {}
    for e in edges:
        fwd.setdefault(id(e.source), []).append(e.target)
        bwd.setdefault(id(e.target), []).append(e.source)

    def walk(start: Any, adj: dict[Any, list[Any]]) -> set[int]:
        seen: set[int] = set()
        stack = [start]
        while stack:
            cur = stack.pop()
            if id(cur) in seen:
                continue
            seen.add(id(cur))
            stack.extend(adj.get(id(cur), ()))
        return seen

    starts = [e.source for e in edges if isinstance(e.source, _Start)]
    ends = [e.target for e in edges if isinstance(e.target, _End)]
    if not starts:
        findings.append("no edge leaves START — nothing in this design can ever run.")
    if not ends:
        findings.append("no edge reaches END — this design produces no output.")

    from_start: set[int] = set()
    for s in starts:
        from_start |= walk(s, fwd)
    to_end: set[int] = set()
    for t in ends:
        to_end |= walk(t, bwd)

    for n in nodes:
        if starts and id(n) not in from_start:
            findings.append(
                f"node {n.name!r} is unreachable from START — its implementation never runs, so a "
                f"strategy that binds it will appear to work while doing nothing.")
        if ends and id(n) not in to_end:
            findings.append(
                f"node {n.name!r} cannot reach END — whatever it produces is discarded, which is "
                f"indistinguishable from a step that was never wired.")

    declared = {id(n) for n in nodes}
    for e in edges:
        for ep in (e.source, e.target):
            if not is_sentinel(ep) and id(ep) not in declared:
                findings.append(
                    f"edge {e!r} references node {_name(ep)!r}, which is not in `nodes`. "
                    f"An undeclared node is invisible to every other check and to any strategy.")
    return findings


def check_variables(nodes: tuple[NodeSpec, ...], edges: tuple[EdgeSpec, ...]) -> list[str]:
    """Per edge: the variable it carries must be an output of its source and an input of its target.

    ⛔ PER EDGE, never aggregated across a node's edges. The aggregate form — "is the set of a
    node's declared outputs covered by the set of variables its successors consume" — passes on a
    SWAP, which is the exact defect this check was written for:

        split = NodeSpec("split", outputs=(stream_a, stream_b))
        EdgeSpec(split, consume_a, stream_b)      # swapped
        EdgeSpec(split, consume_b, stream_a)      # swapped

    Both variables are produced, both are consumed, every set matches — and the wiring is wrong.
    Only a per-edge check sees it.

    Edges touching START/END are skipped on the sentinel side: sentinels declare no variables, and
    the graph's own `input_type`/`output_type` is what constrains them.
    """
    findings: list[str] = []
    for e in edges:
        if e.variable is None:
            continue
        if not is_sentinel(e.source):
            if e.variable not in e.source.outputs:
                declared = ", ".join(v.name for v in e.source.outputs) or "nothing"
                findings.append(
                    f"edge {e!r} carries {e.variable.name!r}, but {e.source.name!r} does not "
                    f"declare it as an output (it declares: {declared}). Either the edge is wired "
                    f"to the wrong variable or the node's contract is out of date.")
        if not is_sentinel(e.target):
            if e.variable not in e.target.inputs:
                declared = ", ".join(v.name for v in e.target.inputs) or "nothing"
                findings.append(
                    f"edge {e!r} delivers {e.variable.name!r} to {e.target.name!r}, which does not "
                    f"declare it as an input (it declares: {declared}).")
    return findings


def check_bindings(nodes: tuple[NodeSpec, ...], strategy: StrategySpec) -> list[str]:
    """The strategy binds exactly the declared nodes — no missing, no extra.

    ⚠️ Compared by IDENTITY, matching `NodeSpec.__hash__`. Comparing by name would accept a
    binding keyed on a look-alike node from another design, which is the failure identity keying
    exists to prevent.
    """
    findings: list[str] = []
    declared = {id(n): n for n in nodes}
    bound = {id(n): n for n in strategy.bindings}
    for nid, n in declared.items():
        if nid not in bound:
            findings.append(
                f"strategy {strategy.name!r} does not bind node {n.name!r}. Every node is bound "
                f"explicitly, including unchanged ones — a partial strategy makes 'what varies "
                f"between these arms' unanswerable without reading both files.")
    for nid, n in bound.items():
        if nid not in declared:
            findings.append(
                f"strategy {strategy.name!r} binds {n.name!r}, which this design does not declare. "
                f"Most likely it was written against a different GraphSpec that has a node of the "
                f"same name.")
    return findings


def check_implementations(strategy: StrategySpec) -> list[str]:
    """Each bound implementation is callable and takes exactly one positional argument (`ctx`).

    Caught here rather than inside `GraphBuilder`, so a strategy's fault is reported against the
    strategy instead of surfacing as a runtime error attributed to the engine.
    """
    findings: list[str] = []
    for node, impl in strategy.bindings.items():
        if not callable(impl):
            findings.append(
                f"{strategy.name!r} binds {node.name!r} to {impl!r}, which is not callable.")
            continue
        try:
            sig = inspect.signature(impl)
        except (TypeError, ValueError):
            continue                    # builtins etc. — unverifiable, not a finding
        positional = [p for p in sig.parameters.values()
                      if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
                      and p.default is p.empty]
        if len(positional) != 1:
            findings.append(
                f"{strategy.name!r} binds {node.name!r} to "
                f"{getattr(impl, '__qualname__', impl)}{sig}, which takes {len(positional)} "
                f"required positional arguments. A pydantic-graph step body takes exactly one "
                f"(`ctx`).")
    return findings
