"""Parallel Processing — pydantic-graph's fan-out example, via the native escape hatch.

⚠️ THE ONE CASE THE DECLARATIVE FORM CANNOT EXPRESS. `.map()` fan-out and `g.join()` collect are
pydantic-graph mechanics with no `EdgeSpec` equivalent, and inventing one would be a second
workflow language competing with theirs. So `build_pydantic_structure()` is overridden and the
`edges` declaration is decorative for this class — which `check()` reports as NOT CHECKED rather
than passing silently.

Two strategies still swap cleanly, which is the point: the escape hatch costs the reachability
check, not the comparison.

    uv run python3 examples/parallel.py
"""
from __future__ import annotations

from typing import Any

from pydantic_graph import GraphBuilder
from pydantic_graph.join import reduce_sum

from workflow_spec import END, START, EdgeSpec, GraphSpec, NodeSpec, StrategySpec, VariableSpec

number = VariableSpec("number", int)
total = VariableSpec("total", int)

transform = NodeSpec("transform", inputs=(number,), outputs=(number,))
collect = NodeSpec("collect", inputs=(number,), outputs=(total,))


class ParallelProcessing(GraphSpec):
    """Fan out over a list, transform each item, sum the results."""

    name = "parallel"
    input_type, output_type = list[int], int
    # `collect` is a JOIN, not a step, so it is not in `nodes` — a strategy has nothing to bind
    # for it. It still appears in `edges`, because it is a real node in the built graph and
    # leaving it out would make the declaration a lie about the topology.
    nodes = (transform,)
    edges = (
        EdgeSpec(START, transform, number),
        EdgeSpec(transform, collect, number),
        EdgeSpec(collect, END, total),
    )

    def build_pydantic_structure(self, g: GraphBuilder, nodes: dict[NodeSpec, Any]) -> None:
        # ⚠️ A join is NOT a step and cannot be one: `g.join()` takes a reducer
        # `(current, input) -> current` plus an `initial`, where `g.step()` takes `(ctx) -> Out`.
        # Verified — `g.join(sum)` raises "'Unset' object is not iterable" without `initial=`.
        total_node = g.join(reduce_sum, initial=0, node_id="collect")
        g.add(
            g.edge_from(g.start_node).map().to(nodes[transform]),
            g.edge_from(nodes[transform]).to(total_node),
            g.edge_from(total_node).to(g.end_node),
        )


async def square(ctx) -> int:
    return ctx.inputs * ctx.inputs


async def cube(ctx) -> int:
    return ctx.inputs ** 3


squares = StrategySpec("squares", {transform: square})
cubes = StrategySpec("cubes", {transform: cube})


def main() -> None:
    spec = ParallelProcessing()

    print("check() — the override is reported, not hidden:")
    for f in spec.check(squares):
        print(f"  {f}")

    for strategy in (squares, cubes):
        graph = spec.render(strategy)
        out = graph.run_sync(inputs=[1, 2, 3, 4])
        print(f"  {strategy.name:<9} nodes={sorted(graph.nodes)}  run([1,2,3,4]) -> {out}")

    print(f"\nwhat varies: {spec.varies(squares, cubes)}")


if __name__ == "__main__":
    main()
