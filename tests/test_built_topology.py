"""The declaration is now a CLAIM about the built graph, not just an instruction for building it.

Every other test in this repo checks a design that is wired FROM its `edges`. These check designs
that are wired by hand, where `edges` used to be unverifiable — and where, before this, it could
say anything at all.
"""
from __future__ import annotations

import pytest

from workflow_workbench import (
    END, START, EdgeSpec, GraphSpec, NodeSpec, SpecError, StrategySpec, VariableSpec)

n = VariableSpec("n", int)

first = NodeSpec("first", inputs=(n,), outputs=(n,))
middle = NodeSpec("middle", inputs=(n,), outputs=(n,))
last = NodeSpec("last", inputs=(n,), outputs=(n,))


async def add_one(ctx) -> int:
    return ctx.inputs + 1


class Chain(GraphSpec):
    """first -> middle -> last, declared."""

    name = "chain"
    input_type, output_type = int, int
    nodes = (first, middle, last)
    edges = (EdgeSpec(START, first, n),
             EdgeSpec(first, middle, n),
             EdgeSpec(middle, last, n),
             EdgeSpec(last, END, n))


three = StrategySpec("three", {first: add_one, middle: add_one, last: add_one})


def test_a_hand_wired_design_that_matches_its_declaration_is_clean() -> None:
    """First: no false positives. A check that fires on correct designs is one people switch off."""
    class HandWired(Chain):
        name = "hand_wired_ok"

        def build_pydantic_structure(self, g, nodes):
            g.add(g.edge_from(g.start_node).to(nodes[first]),
                  g.edge_from(nodes[first]).to(nodes[middle]),
                  g.edge_from(nodes[middle]).to(nodes[last]),
                  g.edge_from(nodes[last]).to(g.end_node))

    assert HandWired().render(three).run_sync(inputs=0) == 3


def test_a_hand_wired_design_that_skips_a_declared_node_is_caught() -> None:
    """⛔ THE POINT. `edges` says first -> middle -> last; the wiring skips `middle`.

    Before this check the design rendered, ran, returned 2 instead of 3, `check()` said only
    NOT CHECKED, and `diagram()` drew a three-step chain that did not exist.
    """
    class Liar(Chain):
        name = "liar"

        def build_pydantic_structure(self, g, nodes):
            g.add(g.edge_from(g.start_node).to(nodes[first]),
                  g.edge_from(nodes[first]).to(nodes[last]),      # skips `middle`
                  g.edge_from(nodes[last]).to(g.end_node))

    with pytest.raises(SpecError) as exc:
        Liar().render(three)

    message = str(exc.value)
    assert "does not match its declaration" in message
    assert "middle" in message


def test_a_node_dropped_at_build_time_is_reported() -> None:
    """`g.step()` accepts a node nothing wires, and `build()` silently DROPS it — so a bound
    implementation is discarded and the run succeeds without it."""
    class Drops(Chain):
        name = "drops"

        def build_pydantic_structure(self, g, nodes):
            g.add(g.edge_from(g.start_node).to(nodes[first]),
                  g.edge_from(nodes[first]).to(nodes[last]),
                  g.edge_from(nodes[last]).to(g.end_node))

    with pytest.raises(SpecError, match="NOT in the built graph"):
        Drops().render(three)


def test_a_hand_wired_design_reversing_two_nodes_is_caught() -> None:
    """The subtler lie: every node is present and reachable, in the wrong ORDER."""
    class Reversed(Chain):
        name = "reversed"

        def build_pydantic_structure(self, g, nodes):
            g.add(g.edge_from(g.start_node).to(nodes[first]),
                  g.edge_from(nodes[first]).to(nodes[last]),      # declared: first -> middle
                  g.edge_from(nodes[last]).to(nodes[middle]),     # declared: middle -> last
                  g.edge_from(nodes[middle]).to(g.end_node))

    with pytest.raises(SpecError, match="does not match its declaration"):
        Reversed().render(three)


def test_engine_inserted_nodes_do_not_trip_the_edge_check() -> None:
    """⚠️ The reason the check permits passing through UNdeclared nodes.

    `examples/parallel.py` declares `START -> transform`, and `.map()` splices a `map` node in
    between. If the check demanded a direct edge it would fire on every fan-out design.
    """
    from examples.parallel import ParallelProcessing, squares

    graph = ParallelProcessing().render(squares)
    assert "map" in graph.nodes, "the engine no longer inserts a map node; revisit this test"
    assert graph.run_sync(inputs=[1, 2, 3, 4]) == 30


def test_declared_branches_are_verified_against_the_built_decision() -> None:
    """`DecisionBranch.source` records the matched type, so the declaration is compared with the
    engine's own record of it rather than trusted."""
    from workflow_workbench.built import check_declared_branches

    from examples.ladder.stage9_decision import Triage, careful

    spec = Triage()
    assert check_declared_branches(spec, spec.render(careful)) == []


def test_every_ladder_design_passes_the_built_check() -> None:
    """Prototyped across all of them before landing: 8/8 clean, including the hand-wired one.

    ⚠️ The first prototype reported 7 findings on the branching design, ALL FALSE, because a
    Decision's branches are not in `edges_by_source` — they hang off the Decision node. That is
    why `built_adjacency` reads both.
    """
    from workflow_workbench.built import check_built_topology

    from examples.counter import Counter, modest
    from examples.ladder.stage1_bare import HelloWorld, formal
    from examples.ladder.stage3_new_node import TranslatedHello, formal_t
    from examples.ladder.stage4_subgraph import TracedHello, nested
    from examples.ladder.stage8_join import Greetings, greet
    from examples.ladder.stage9_decision import Triage, careful
    from examples.parallel import ParallelProcessing, squares

    cases = [(HelloWorld(), formal), (TranslatedHello(), formal_t), (TracedHello(), nested),
             (Greetings(), greet), (Triage(), careful), (Counter(), modest),
             (ParallelProcessing(), squares)]
    for spec, strategy in cases:
        graph = spec.render(strategy)
        assert check_built_topology(spec, graph) == [], spec.name
