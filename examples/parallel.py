"""Parallel Processing — pydantic-graph's fan-out example, DECLARED.

A variation of their `parallel_processing.py` from
<https://pydantic.dev/docs/ai/graph/builder/>: map over a list, transform each item, reduce.

⛔ THIS FILE USED TO OVERRIDE `build_pydantic_structure()`, and its docstring said fan-out was
"THE ONE CASE THE DECLARATIVE FORM CANNOT EXPRESS". That is no longer true. `map_over` on an edge
and `JoinSpec` in `joins` say the same thing as data, so this design is checked, diagrammed and
diffed like any other — where before, reaching for `.map()` cost reachability checking on every
node in the file.

    EdgeSpec(START, transform, numbers, map_over=number)    the collection crosses, one item lands
    JoinSpec("collect", reduce_sum, initial=0, ...)         and the items are reduced

⚠️ `map_over` names the ITEM, not just "this fans out". Both ends get checked that way: the wire
really carries `numbers`, and `transform` really consumes a `number`. A bool was tried first and
`check_variables` immediately caught the hole — the edge said `numbers`, the node said `number`.

    uv run python3 examples/parallel.py
"""
from __future__ import annotations

from pydantic_graph.join import reduce_sum

from workflow_workbench import (
    END,
    START,
    EdgeSpec,
    GraphSpec,
    JoinSpec,
    NodeSpec,
    StrategySpec,
    VariableSpec,
)

numbers = VariableSpec("numbers", list)
number = VariableSpec("number", int)
total = VariableSpec("total", int)

transform = NodeSpec("transform", inputs=(number,), outputs=(number,))
"""The role: one number in, one number out — applied to each item of the collection."""

collect = JoinSpec("collect", reduce_sum, initial=0, inputs=(number,), outputs=(total,))
"""⚠️ In `joins`, not `nodes`. A reducer is `(current, input) -> current`, not `(ctx) -> Out`, so
there is no implementation for a strategy to bind and `varies()` will never mention it."""


class ParallelProcessing(GraphSpec):
    """Fan out over a list, transform each item, sum the results."""

    name = "parallel"
    input_type, output_type = list[int], int
    nodes = (transform,)
    joins = (collect,)
    edges = (EdgeSpec(START, transform, numbers, map_over=number),
             EdgeSpec(transform, collect, number),
             EdgeSpec(collect, END, total))


async def square(ctx) -> int:
    return ctx.inputs * ctx.inputs


async def cube(ctx) -> int:
    return ctx.inputs ** 3


squares = StrategySpec("squares", {transform: square})
cubes = StrategySpec("cubes", {transform: cube})


def main() -> None:
    spec = ParallelProcessing()

    print(f"check() with no strategy: {spec.check() or 'clean'}")
    print(f"check(squares):           {spec.check(squares) or 'clean'}")
    print("  ⚠️ neither says NOT CHECKED. A fan-out design is now checked like any other.\n")

    for strategy in (squares, cubes):
        graph = spec.render(strategy)
        out = graph.run_sync(inputs=[1, 2, 3, 4])
        print(f"  {strategy.name:<9} nodes={sorted(graph.nodes)}  run([1,2,3,4]) -> {out}")

    print(f"\nwhat varies: {spec.varies(squares, cubes)}")
    print(f"\n{spec.diagram(squares)}")


if __name__ == "__main__":
    main()
