"""Mermaid straight from the declaration — no `Graph`, no implementations, no engine.

`pydantic_graph.Graph.render()` already emits mermaid, and this does NOT replace it. The
difference is what each can answer:

    Graph.render()      one BUILT graph. Needs every implementation to exist first.
    diagram(spec)       the DESIGN, before anything is implemented.
    diff_diagram(a, b)  what two STRATEGIES have in common and where they differ.

The third has no equivalent in pydantic-graph, and it is the reason this module exists: a built
`Graph` retains no trace of the strategy that produced it, so two rendered graphs of one design are
byte-identical mermaid — a diff of them is empty by construction, on every pair, forever. The
variation lives in the bindings, which only the declaration holds.
"""
from __future__ import annotations

from typing import Any

from workflow_workbench.spec import (
    DecisionSpec,
    EdgeSpec,
    JoinSpec,
    NodeSpec,
    StrategySpec,
    SubgraphBinding,
    _End,
    _Start,
    is_sentinel,
)

__all__ = ["diagram", "diff_diagram", "impl_name"]


def impl_name(impl: Any) -> str:
    """What to write under a node: a function's name, or a collapsed child as `graph::strategy`.

    ⚠️ A subgraph is named at the parent level and NOT flattened into it. Splicing the child's
    nodes into the parent picture would make two arms of one design draw different topologies,
    which is precisely the alignment `node_id=node.name` exists to protect. The child's internals
    are one `child.diagram(child_strategy)` away, drawn as what they are: their own design.
    """
    if isinstance(impl, SubgraphBinding):
        return f"{impl.graph.name or type(impl.graph).__name__}::{impl.strategy.name}"
    return getattr(impl, "__qualname__", None) or getattr(impl, "__name__", None) or repr(impl)


def _arrow(e: EdgeSpec) -> str:
    """The edge's label. For a BRANCH that is the type it matches, not the variable it carries.

    ⚠️ Every branch of a decision usually carries the same variable, so labelling them by variable
    draws two identical arrows out of one router — a picture that hides the only thing a reader
    is looking at it to learn.
    """
    if e.when is not None:
        return f"-- {getattr(e.when, '__name__', e.when)} -->"
    lbl = e.label or (e.variable.name if e.variable else "")
    return f"-- {lbl} -->" if lbl else "-->"


def _node_id(ep: Any) -> str:
    if isinstance(ep, _Start):
        return "START"
    if isinstance(ep, _End):
        return "END"
    return ep.name.replace(" ", "_")


def diagram(nodes: tuple[NodeSpec, ...], edges: tuple[EdgeSpec, ...], *,
            title: str = "", strategy: StrategySpec | None = None) -> str:
    """Mermaid `flowchart TD` for a design, optionally annotated with one strategy's bindings.

    ⚠️ `flowchart`, where `pydantic_graph.Graph.render()` emits `stateDiagram-v2` (verified).

    ⛔ CORRECTED. This docstring used to justify that choice by claiming the edge labels — which
    variable crosses which wire — are "the thing a state diagram has nowhere to put". **That is
    false, and `examples/ladder/stage6_diagrams.py` prints the counter-example.** Their renderer
    emits `pick --> compose: salutation`; the label survives, because `build_pydantic_structure`
    passes it to `.label()` and their renderer prints it.

    The format choice is a preference, then, not a capability gap — say so rather than inventing
    a limitation for it. What their renderer genuinely cannot do is elsewhere and is stated above:
    it needs a BUILT graph, so it cannot draw an unimplemented design, and both arms of one design
    render byte-identically because a built graph does not know which strategy produced it.
    """
    out = [f"%% {title}" if title else "%% workflow-workbench", "flowchart TD"]
    out.append("  START([START])")
    for n in nodes:
        if isinstance(n, DecisionSpec):
            # A rhombus, because a router is not a stage: nothing happens here, the value only
            # turns. Drawing it like a step would invite someone to look for its implementation.
            note = f"<br/><i>{n.note}</i>" if n.note else ""
            out.append(f"  {_node_id(n)}{{{{\"{n.name}{note}\"}}}}")
            continue
        # ⚠️ A join is drawn as a distinct shape and NEVER annotated with an implementation:
        # it has none to bind, and printing a blank line under it would read as "unbound".
        if isinstance(n, JoinSpec):
            reducer = getattr(n.reducer, "__name__", str(n.reducer))
            out.append(f"  {_node_id(n)}[/\"{n.name}<br/><i>join: {reducer}</i>\"/]")
            continue
        label = n.name
        if strategy is not None and n in strategy.bindings:
            label = f"{n.name}<br/><i>{impl_name(strategy[n])}</i>"
        out.append(f"  {_node_id(n)}[\"{label}\"]")
    out.append("  END([END])")
    for e in edges:
        out.append(f"  {_node_id(e.source)} {_arrow(e)} {_node_id(e.target)}")
    return "\n".join(out)


def diff_diagram(nodes: tuple[NodeSpec, ...], edges: tuple[EdgeSpec, ...],
                 a: StrategySpec, b: StrategySpec, *, title: str = "") -> str:
    """One diagram of the shared design, with the nodes that DIFFER between two strategies
    highlighted and both implementations named.

    This is the picture a battle needs and that neither library can draw:

      · `Graph.render()` draws one built graph, and both arms of one design render identically
      · nothing in pydantic-evals draws anything structural at all

    Shared nodes are drawn plain; varying nodes get both implementation names and a `varies` class.
    """
    varies = {n for n in nodes
              if n in a.bindings and n in b.bindings and a[n] is not b[n]}
    out = [f"%% {title or 'strategy diff'}: {a.name} vs {b.name}", "flowchart TD"]
    out.append("  START([START])")
    for n in nodes:
        if isinstance(n, DecisionSpec):
            note = f"<br/><i>{n.note}</i>" if n.note else ""
            out.append(f"  {_node_id(n)}{{{{\"{n.name}{note}\"}}}}:::shared")
            continue
        if isinstance(n, JoinSpec):
            reducer = getattr(n.reducer, "__name__", str(n.reducer))
            out.append(f"  {_node_id(n)}[/\"{n.name}<br/><i>join: {reducer}</i>\"/]:::shared")
            continue
        if n in varies:
            out.append(f"  {_node_id(n)}[\"{n.name}<br/>{a.name}: <i>{impl_name(a[n])}</i>"
                       f"<br/>{b.name}: <i>{impl_name(b[n])}</i>\"]:::varies")
        else:
            shared = impl_name(a[n]) if n in a.bindings else ""
            sub = f"<br/><i>{shared}</i>" if shared else ""
            out.append(f"  {_node_id(n)}[\"{n.name}{sub}\"]:::shared")
    out.append("  END([END])")
    for e in edges:
        out.append(f"  {_node_id(e.source)} {_arrow(e)} {_node_id(e.target)}")
    out.append("  classDef varies fill:#fde68a,stroke:#b45309,stroke-width:3px;")
    out.append("  classDef shared fill:#f1f5f9,stroke:#94a3b8;")
    return "\n".join(out)
