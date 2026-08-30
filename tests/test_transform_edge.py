"""A reshape on the wire: no node, still declared, still comparable.

⛔ This is the construct I argued AGAINST and got wrong. My position was that a transform must be
a NodeSpec "because a strategy binds it, and nodes are what strategies bind" — which is an
invariant I wrote, not a law. Put the transform on the edge and it keeps every property that
mattered (visible, checkable, comparable) and loses the one that did not (a box on the canvas).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from workflow_workbench import (
    END, START, EdgeSpec, GraphSpec, NodeSpec, SpecError, StrategySpec,
    TransformEdgeSpec, VariableSpec)


@dataclass
class Draft:
    edges: list = field(default_factory=list)


plan = VariableSpec("plan", str)
draft = VariableSpec("draft", Draft)
edge_list = VariableSpec("edge_list", list)
report = VariableSpec("report", str)

propose = NodeSpec("propose", inputs=(plan,), outputs=(draft,))
cite = NodeSpec("cite", inputs=(edge_list,), outputs=(report,))


def take_edges(ctx) -> list:
    return ctx.inputs.edges


async def do_propose(ctx) -> Draft:
    return Draft(edges=["a->b", "b->c"])


async def do_cite(ctx) -> str:
    return f"{len(ctx.inputs)} edges cited"


class Fixed(GraphSpec):
    """`apply=` — part of the design, like a JoinSpec's reducer."""

    name = "fixed"
    input_type, output_type = str, str
    nodes = (propose, cite)
    edges = (EdgeSpec(START, propose, plan),
             TransformEdgeSpec(propose, cite, draft, edge_list, apply=take_edges),
             EdgeSpec(cite, END, report))


fixed_s = StrategySpec("s", {propose: do_propose, cite: do_cite})


def test_a_fixed_transform_runs_and_creates_no_node() -> None:
    """⛔ The property the whole design turns on: `nodes` is unchanged.

    A `NodeSpec` doing the same work would add a box to every diagram of this design, and a
    reader would count it as a stage of the workflow. It is not one — it is an accessor.
    """
    spec = Fixed()
    assert spec.check(fixed_s) == []

    graph = spec.render(fixed_s)
    assert graph.run_sync(inputs="x") == "2 edges cited"
    assert sorted(graph.nodes) == ["__end__", "__start__", "cite", "propose"]


def test_a_fixed_transform_binds_nothing_and_never_varies() -> None:
    """Same contract as a JoinSpec's reducer: declared, not a variation point."""
    spec = Fixed()
    transform = next(e for e in spec.edges if isinstance(e, TransformEdgeSpec))

    assert transform not in fixed_s.bindings
    assert spec.varies(fixed_s, fixed_s) == {}


def test_the_diagram_tags_the_arrow_rather_than_drawing_a_box() -> None:
    out = Fixed().diagram(fixed_s)
    assert "draft ▸ take_edges -> edge_list" in out
    assert "take_edges[" not in out, "a transform must never render as a node shape"


# ── a variation point ───────────────────────────────────────────────────────────────────────

shape = TransformEdgeSpec(propose, cite, draft, edge_list)


class Varying(Fixed):
    name = "varying"
    edges = (EdgeSpec(START, propose, plan), shape, EdgeSpec(cite, END, report))


def all_edges(ctx) -> list:
    return ctx.inputs.edges


def first_only(ctx) -> list:
    return ctx.inputs.edges[:1]


arm_all = StrategySpec("all", {propose: do_propose, cite: do_cite, shape: all_edges})
arm_first = StrategySpec("first", {propose: do_propose, cite: do_cite, shape: first_only})


def test_two_arms_can_reshape_differently_and_varies_says_so() -> None:
    """⛔ The reason this is bindable at all. A difference nobody can see is the one that ruins a
    comparison — two arms that pruned differently would otherwise look identical."""
    spec = Varying()
    assert spec.check(arm_all) == []

    assert spec.render(arm_all).run_sync(inputs="x") == "2 edges cited"
    assert spec.render(arm_first).run_sync(inputs="x") == "1 edges cited"
    assert spec.varies(arm_all, arm_first) == {"propose->cite": ("all_edges", "first_only")}


def test_an_unbound_transform_is_refused() -> None:
    """Neither `apply=` nor a binding: the value would cross UNCHANGED while the declaration says
    it became `edge_list`, and the diagram would repeat that."""
    incomplete = StrategySpec("incomplete", {propose: do_propose, cite: do_cite})

    with pytest.raises(SpecError, match="no `apply=` and no binding"):
        Varying().render(incomplete)


def test_declaring_both_apply_and_a_binding_is_refused() -> None:
    """Which of the two runs would be a coin toss."""
    both = TransformEdgeSpec(propose, cite, draft, edge_list, apply=take_edges)

    class Both(Fixed):
        name = "both"
        edges = (EdgeSpec(START, propose, plan), both, EdgeSpec(cite, END, report))

    s = StrategySpec("both", {propose: do_propose, cite: do_cite, both: all_edges})
    with pytest.raises(SpecError, match="AND is bound by strategy"):
        Both().render(s)


def test_an_async_transform_is_refused() -> None:
    """⚠️ pydantic-graph does NOT reject it. Measured against 2.35.1: it silently produces a
    coroutine object and warns "never awaited", and that coroutine flows to the next step and
    fails there — attributed to the wrong place."""
    async def slow(ctx) -> list:
        return ctx.inputs.edges

    s = StrategySpec("bad", {propose: do_propose, cite: do_cite, shape: slow})
    with pytest.raises(SpecError, match="cannot await"):
        Varying().render(s)


def test_the_target_is_checked_against_produces_not_against_the_wire() -> None:
    """The two ends carry different variables, which is the whole shape of a transform edge."""
    wrong = VariableSpec("wrong", list)
    bad_edge = TransformEdgeSpec(propose, cite, draft, wrong, apply=take_edges)

    class Mismatched(Fixed):
        name = "mismatched"
        edges = (EdgeSpec(START, propose, plan), bad_edge, EdgeSpec(cite, END, report))

    findings = Mismatched().check(fixed_s)
    assert any("reshaped on the wire" in f and "wrong" in f for f in findings), findings


def test_delivers_is_required() -> None:
    """⚠️ And the error must be BUILDABLE. `__post_init__` puts `{self!r}` in its own message, so
    a repr assuming `delivers` is set replaced the real finding with an AttributeError raised
    from inside the reporting — the check worked and could not say so."""
    with pytest.raises(SpecError, match="needs `delivers`"):
        TransformEdgeSpec(propose, cite, draft)


def test_fan_out_and_reshape_are_separate_types() -> None:
    """⛔ Used to be a guard: `map_over` and a transform on one edge was refused in
    `__post_init__`. The guard is GONE because the shape is now unconstructible — fan-out is
    `MapEdgeSpec` and reshape is `TransformEdgeSpec`, and no edge is both.

    That is the better fix. A guard against an illegal combination is a guard that exists because
    the types allowed it; making it unrepresentable deletes the guard and the class of bug.
    """
    from workflow_workbench import MapEdgeSpec

    assert not issubclass(MapEdgeSpec, TransformEdgeSpec)
    assert not issubclass(TransformEdgeSpec, MapEdgeSpec)
    assert not hasattr(TransformEdgeSpec(propose, cite, draft, edge_list, apply=take_edges),
                       "map_over")
