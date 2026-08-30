"""Rung 10 — wire it by hand, and stay checked anyway.

Rungs 8 and 9 added vocabulary so joins and branches could be DECLARED. That approach does not
scale: pydantic-graph has `map`, `transform`, `broadcast`, `stream`, `node`, `match_node` and
`add_mapping_edge` besides, and chasing their API with a new `*Spec` per feature is a race lost
every release.

So this rung takes the other route. Wire whatever you like in `build_pydantic_structure()` — and
`render()` verifies the RESULT against the declaration:

    present     every declared node is IN the built graph
    reachable   walked on the built graph, not on `edges`
    honoured    every declared edge corresponds to a real path

⛔ The third is the one that did not exist before. A hand-wired design could declare ANY `edges`
at all — nothing compared them to anything — and `diagram()` would draw the declaration
faithfully. A wrong picture nobody can catch is worse than no picture.

⚠️ What an override still costs: checking BEFORE the implementations exist. `check()` alone reads
the declaration, and a topology written in code is not readable until it has been built. That is a
real loss and it is why `JoinSpec` and `DecisionSpec` were still worth adding.

    uv run python3 -m examples.ladder.stage10_hand_wired
"""
from __future__ import annotations

from workflow_workbench import (
    END,
    START,
    EdgeSpec,
    GraphSpec,
    NodeSpec,
    SpecError,
    StrategySpec,
    VariableSpec,
)

n = VariableSpec("n", int)

first = NodeSpec("first", inputs=(n,), outputs=(n,))
middle = NodeSpec("middle", inputs=(n,), outputs=(n,))
last = NodeSpec("last", inputs=(n,), outputs=(n,))


class Chain(GraphSpec):
    """The declaration. Three steps, each adding one, so the answer counts what ran."""

    name = "chain"
    input_type, output_type = int, int
    nodes = (first, middle, last)
    edges = (EdgeSpec(START, first, n),
             EdgeSpec(first, middle, n),
             EdgeSpec(middle, last, n),
             EdgeSpec(last, END, n))


class HandWired(Chain):
    """Wired in code, and honest about it."""

    name = "hand_wired"

    def build_pydantic_structure(self, g, nodes):
        g.add(g.edge_from(g.start_node).to(nodes[first]),
              g.edge_from(nodes[first]).to(nodes[middle]),
              g.edge_from(nodes[middle]).to(nodes[last]),
              g.edge_from(nodes[last]).to(g.end_node))


class SkipsAStage(Chain):
    """Wired in code, and NOT honest: `middle` is declared and never wired."""

    name = "skips_a_stage"

    def build_pydantic_structure(self, g, nodes):
        g.add(g.edge_from(g.start_node).to(nodes[first]),
              g.edge_from(nodes[first]).to(nodes[last]),
              g.edge_from(nodes[last]).to(g.end_node))


class WrongOrder(Chain):
    """The subtler lie: every node present and reachable, in the wrong ORDER."""

    name = "wrong_order"

    def build_pydantic_structure(self, g, nodes):
        g.add(g.edge_from(g.start_node).to(nodes[first]),
              g.edge_from(nodes[first]).to(nodes[last]),
              g.edge_from(nodes[last]).to(nodes[middle]),
              g.edge_from(nodes[middle]).to(g.end_node))


async def add_one(ctx) -> int:
    return ctx.inputs + 1


three = StrategySpec("three", {first: add_one, middle: add_one, last: add_one})


def main() -> None:
    print("check() alone — reads the declaration, which is not what these build:")
    for spec in (HandWired(), SkipsAStage(), WrongOrder()):
        finding = spec.check(three)[0]
        print(f"  {spec.name:<15} {finding[:96]}...")

    print("\nrender() — checks the graph that was actually built:")
    for spec in (HandWired(), SkipsAStage(), WrongOrder()):
        try:
            graph = spec.render(three)
            print(f"  {spec.name:<15} OK   run(0) -> {graph.run_sync(inputs=0)}  "
                  f"nodes={sorted(graph.nodes)}")
        except SpecError as exc:
            reason = str(exc).splitlines()[-1].strip()
            print(f"  {spec.name:<15} REFUSED")
            print(f"  {'':15} {reason[:150]}")

    print("\n⚠️ Note what `skips_a_stage` would have done before this check existed: it renders,")
    print("   runs, returns 2 instead of 3, and every diagram of it shows a three-step chain.")


if __name__ == "__main__":
    main()
