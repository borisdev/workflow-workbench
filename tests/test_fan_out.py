"""Fan-out and streaming, declared rather than hand-wired.

Both used to require `build_pydantic_structure()`, which reported reachability as NOT CHECKED for
the whole design — so a fan-out cost the checks on every node around it.
"""
from __future__ import annotations

import pytest
from pydantic_graph.join import reduce_list_append, reduce_sum

from workflow_workbench import (
    END, START, EdgeSpec, GraphSpec, JoinSpec, NodeSpec, SpecError, StrategySpec, VariableSpec)


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


def test_map_over_names_the_item_so_both_ends_are_checked() -> None:
    """⛔ Why `map_over` is a VariableSpec and not a bool — found by running it.

    With a bool, the edge carried `numbers` while the target declared `number`, and
    `check_variables` called it a wiring error. It was right: those really are two variables. The
    fan-out has to name both or only one end is ever checked.
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
        edges = (EdgeSpec(START, step, numbers, map_over=wrong_item),
                 EdgeSpec(step, collect, number),
                 EdgeSpec(collect, END, total))

    async def double(ctx) -> int:
        return ctx.inputs * 2

    findings = Mismatched().check(StrategySpec("s", {step: double}))
    assert any("wrong_item" in f and "one item per run" in f for f in findings), findings


def test_a_fan_out_without_a_declared_collection_is_refused() -> None:
    number = VariableSpec("number", int)
    step = NodeSpec("step", inputs=(number,), outputs=(number,))

    class NoCollection(GraphSpec):
        name = "no_collection"
        input_type, output_type = list, int
        nodes = (step,)
        edges = (EdgeSpec(START, step, map_over=number),      # no `variable=`
                 EdgeSpec(step, END, number))

    findings = NoCollection().check()
    assert any("does not name the collection" in f for f in findings), findings


def test_a_streaming_node_is_declared_and_fans_out() -> None:
    """`g.stream` produces an AsyncIterable, so the items reach the next node via `map_over`.
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
        edges = (EdgeSpec(START, split, text),
                 EdgeSpec(split, collect, words, map_over=word),
                 EdgeSpec(collect, END, words))

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
    value, because that is what a `g.stream` node with no `map_over` had done a few minutes
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
        edges = (EdgeSpec(START, node, text), EdgeSpec(node, END, out))

    async def gen(ctx):
        yield ctx.inputs

    with pytest.raises(TypeError, match="async_generator"):
        NotStreaming().render(StrategySpec("s", {node: gen})).run_sync(inputs="hi")
