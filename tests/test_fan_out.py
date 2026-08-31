"""Fan-out and streaming, declared rather than hand-wired.

Both used to require `build_pydantic_structure()`, which reported reachability as NOT CHECKED for
the whole design — so a fan-out cost the checks on every node around it.
"""
from __future__ import annotations

import pytest
from pydantic_graph.join import reduce_list_append, reduce_sum

from workflow_workbench import (
    END, START, EdgeSpec, GraphSpec, JoinSpec, MapEdgeSpec, NodeSpec, SpecError,
    StrategySpec, VariableSpec)


def test_a_declared_fan_out_is_checked_and_runs() -> None:
    from examples.parallel import ParallelProcessing, cubes, squares

    spec = ParallelProcessing()
    assert spec.check() == []
    assert spec.check(squares) == []
    assert not any("NOT CHECKED" in f for f in spec.check(squares))

    assert spec.render(squares).run_sync(inputs=[1, 2, 3, 4]) == 30
    assert spec.render(cubes).run_sync(inputs=[1, 2, 3, 4]) == 100
    assert spec.varies(squares, cubes) == {"transform": ("square", "cube")}


def test_the_engine_really_inserted_a_map_node() -> None:
    """Otherwise this is a chain that happens to give the right answer on this input."""
    from examples.parallel import ParallelProcessing, squares

    assert "map" in ParallelProcessing().render(squares).nodes


def test_a_fan_out_names_the_item_so_both_ends_are_checked() -> None:
    """⛔ Why a fan-out names BOTH ends — found by running it.

    The first version was a bool. The edge carried `numbers` while the target declared `number`,
    and `check_variables` called it a wiring error. It was right: those really are two variables.
    """
    numbers = VariableSpec("numbers", list)
    number = VariableSpec("number", int)
    total = VariableSpec("total", int)

    wrong_item = VariableSpec("wrong_item", int)
    step = NodeSpec("step", inputs=(number,), outputs=(number,))
    collect = JoinSpec("collect", reduce_sum, initial=0, inputs=(number,), outputs=(total,))

    class Mismatched(GraphSpec):
        name = "mismatched_fan_out"
        input_type, output_type = list, int
        nodes = (step,)
        joins = (collect,)
        edges = (MapEdgeSpec(source=START, target=step, carries=numbers, delivers=wrong_item),
                 EdgeSpec(source=step, target=collect, carries=number),
                 EdgeSpec(source=collect, target=END, carries=total))

    async def double(ctx) -> int:
        return ctx.inputs * 2

    findings = Mismatched().check(StrategySpec("s", {step: double}))
    assert any("wrong_item" in f and "one item per run" in f for f in findings), findings


def test_a_fan_out_cannot_omit_the_collection() -> None:
    """⛔ Used to be a runtime check ("does not name the collection"). It is now a TypeError from
    the constructor, because `carries` is required and `delivers` is a second required field.

    Better: an unrepresentable state needs no guard, and the error arrives at the line that wrote
    it rather than from a checker later.
    """
    number = VariableSpec("number", int)
    step = NodeSpec("step", inputs=(number,), outputs=(number,))

    with pytest.raises(TypeError):
        MapEdgeSpec(source=START, target=step)


def test_a_streaming_node_is_declared_and_fans_out() -> None:
    """`g.stream` produces an AsyncIterable, so the items reach the next node via a MapEdgeSpec.
    The two features compose; neither needed the other to be hand-wired."""
    word = VariableSpec("word", str)
    words = VariableSpec("words", list)
    text = VariableSpec("text", str)

    split = NodeSpec("split", inputs=(text,), outputs=(words,), streams=True)
    collect = JoinSpec("collect", reduce_list_append, initial_factory=list,
                       inputs=(word,), outputs=(words,))

    class Splitter(GraphSpec):
        name = "splitter"
        input_type, output_type = str, list
        nodes = (split,)
        joins = (collect,)
        edges = (EdgeSpec(source=START, target=split, carries=text),
                 MapEdgeSpec(source=split, target=collect, carries=words, delivers=word),
                 EdgeSpec(source=collect, target=END, carries=words))

    async def by_space(ctx):
        for w in ctx.inputs.split():
            yield w

    spec = Splitter()
    strategy = StrategySpec("by_space", {split: by_space})
    assert not [f for f in spec.check(strategy) if not f.startswith("NOT CHECKED")]

    graph = spec.render(strategy)
    assert sorted(graph.run_sync(inputs="a b c")) == ["a", "b", "c"]


def test_a_generator_bound_to_a_non_streaming_node_fails_loudly() -> None:
    """What `streams=True` is actually for — and it is NOT preventing a silent failure.

    ⛔ CORRECTED while writing this test. I expected the graph to hand the generator object on as a
    value, because that is what a `g.stream` node with no fan-out had done a few minutes
    earlier. It does not: `g.step` accepts the generator at build time and then `await`s it at run
    time, which raises. Loud, not silent.

    So `streams=True` enables a capability rather than guarding against a quiet bug — which is a
    weaker justification than the one I had in mind, and worth writing down as the weaker one.
    """
    text = VariableSpec("text", str)
    out = VariableSpec("out", object)
    node = NodeSpec("node", inputs=(text,), outputs=(out,))     # streams NOT set

    class NotStreaming(GraphSpec):
        name = "not_streaming"
        input_type, output_type = str, object
        nodes = (node,)
        edges = (EdgeSpec(source=START, target=node, carries=text), EdgeSpec(source=node, target=END, carries=out))

    async def gen(ctx):
        yield ctx.inputs

    with pytest.raises(TypeError, match="async_generator"):
        NotStreaming().render(StrategySpec("s", {node: gen})).run_sync(inputs="hi")


def test_the_shopping_list_from_the_MapEdgeSpec_docstring_runs() -> None:
    """⛔ The docstring example, executed. A worked example that has never been run is a claim.

    It exists because "when would I reach for MapEdgeSpec" had no answer a reader could hold: the
    repo's only fan-out example squared integers, which shows the mechanism and not the need.
    """
    from pydantic_graph.join import reduce_sum

    shopping = VariableSpec("shopping", list)
    item = VariableSpec("item", str)
    cost = VariableSpec("cost", float)
    bill = VariableSpec("bill", float)

    price = NodeSpec("price", inputs=(item,), outputs=(cost,))
    total = JoinSpec("total", reduce_sum, initial=0.0, inputs=(cost,), outputs=(bill,))

    class Shop(GraphSpec):
        name = "shop"
        input_type, output_type = list, float
        nodes = (price,)
        joins = (total,)
        edges = (MapEdgeSpec(source=START, target=price, carries=shopping, delivers=item),
                 EdgeSpec(source=price, target=total, carries=cost),
                 EdgeSpec(source=total, target=END, carries=bill))

    prices = {"milk": 1.20, "eggs": 2.50, "bread": 1.10}
    seen: list[str] = []

    async def look_up(ctx) -> float:
        seen.append(ctx.inputs)
        return prices[ctx.inputs]

    strategy = StrategySpec("lookup", {price: look_up})
    spec = Shop()
    assert spec.check(strategy) == []

    assert round(spec.render(strategy).run_sync(inputs=list(prices)), 2) == 4.80
    # the point of the whole construct: `price` never sees the list
    assert sorted(seen) == ["bread", "eggs", "milk"]
    assert "each item" in spec.diagram(strategy)


def test_a_fan_out_that_never_rejoins_is_refused() -> None:
    """⛔ The mirror of `check_step_arity`, and it was missing until someone asked why a join is
    always needed. Measured before the check existed:

        check() -> clean
        run     -> 1.2
        price ran 3 times, with ['milk', 'eggs', 'bread']

    Three prices computed, one returned, two gone — and the survivor has the right SHAPE, which
    is what makes it survivable in production.
    """
    shopping = VariableSpec("shopping", list)
    item = VariableSpec("item", str)
    cost = VariableSpec("cost", float)
    price = NodeSpec("price", inputs=(item,), outputs=(cost,))

    class NoJoin(GraphSpec):
        name = "no_join"
        input_type, output_type = list, float
        nodes = (price,)
        edges = (MapEdgeSpec(source=START, target=price, carries=shopping, delivers=item), EdgeSpec(source=price, target=END, carries=cost))

    async def look_up(ctx) -> float:
        return 1.0

    with pytest.raises(SpecError, match="reaches END without passing a join"):
        NoJoin().render(StrategySpec("s", {price: look_up}))


def test_the_join_need_not_be_adjacent_to_the_fan_out() -> None:
    """Stated as reachability, not as "the next node must be a join" — `map -> a -> b -> join` is
    a perfectly ordinary shape and a check that rejected it would be noise."""
    from pydantic_graph.join import reduce_sum

    items = VariableSpec("items", list)
    one = VariableSpec("one", int)
    doubled = VariableSpec("doubled", int)
    total_v = VariableSpec("total_v", int)

    first = NodeSpec("first", inputs=(one,), outputs=(one,))
    second = NodeSpec("second", inputs=(one,), outputs=(doubled,))
    total = JoinSpec("total", reduce_sum, initial=0, inputs=(doubled,), outputs=(total_v,))

    class TwoStepsThenJoin(GraphSpec):
        name = "two_steps_then_join"
        input_type, output_type = list, int
        nodes = (first, second)
        joins = (total,)
        edges = (MapEdgeSpec(source=START, target=first, carries=items, delivers=one),
                 EdgeSpec(source=first, target=second, carries=one),
                 EdgeSpec(source=second, target=total, carries=doubled),
                 EdgeSpec(source=total, target=END, carries=total_v))

    async def keep(ctx) -> int:
        return ctx.inputs

    async def double(ctx) -> int:
        return ctx.inputs * 2

    spec = TwoStepsThenJoin()
    strategy = StrategySpec("s", {first: keep, second: double})
    assert spec.check(strategy) == []
    assert spec.render(strategy).run_sync(inputs=[1, 2, 3]) == 12
