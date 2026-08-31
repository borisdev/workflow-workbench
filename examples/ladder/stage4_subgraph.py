"""Rung 4 — one node implemented by a WHOLE CHILD DESIGN, not a callable.

`translate` grows up. Doing it properly is two decisions — which language, then render it — and
each deserves to be visible and swappable on its own. But the parent must not learn about them:
`TranslatedHello` still has three nodes, or rung 5's battle loses its alignment.

    parent      pick -> compose -> translate -> END          3 nodes, unchanged
    translate   implemented by:  detect -> render           a checked design of its own

⚠️ A subgraph is not a new node kind and not a nested runner. It is a `GraphSpec + StrategySpec`,
rendered to an ordinary `pydantic_graph.Graph`, awaited by one parent step body. Everything that
can already run a graph runs this.

⚠️ The child gets the parent's EXACT `state` object — not a copy. `check_subgraphs` demands
identical `state_type`/`deps_type` for that reason, and this example proves it by mutation: the
child appends to `ctx.state.trace` and the parent reads it afterwards.

    uv run python3 -m examples.ladder.stage4_subgraph
"""
from __future__ import annotations

from dataclasses import dataclass, field

from examples.ladder.stage1_bare import compose, compose_sentence, greeting, pick, pick_formal
from examples.ladder.stage2_strategies import pick_casual
from examples.ladder.stage3_new_node import (
    TranslatedHello,
    spoken,
    translate,
    translate_none,
    translate_shouty,
)
from workflow_workbench import (
    END,
    START,
    EdgeSpec,
    GraphSpec,
    NodeSpec,
    StrategySpec,
    SubgraphBinding,
    VariableSpec,
)


@dataclass
class TracedGuest:
    """Same job as rung 1's `Guest`, plus a trace so 'the child ran' is a fact, not a claim."""

    name: str = "world"
    trace: list[str] = field(default_factory=list)


class TracedHello(TranslatedHello):
    """The parent design, unchanged except for a state type that records what ran."""

    name = "traced_hello"
    state_type = TracedGuest


# ── the child design: the same `greeting -> spoken` boundary, in two steps ───────────────────

language = VariableSpec("language", str)

detect = NodeSpec("detect", inputs=(greeting,), outputs=(language,))
render = NodeSpec("render", inputs=(language,), outputs=(spoken,))


class Translation(GraphSpec):
    """⚠️ `input_type`/`output_type` must match what `translate` accepts and produces, and
    `state_type` must match the parent's exactly. `check_subgraphs` compares all four."""

    name = "translation"
    state_type = TracedGuest
    input_type, output_type = str, str
    nodes = (detect, render)
    edges = (EdgeSpec(source=START, target=detect, carries=greeting),
             EdgeSpec(source=detect, target=render, carries=language),
             EdgeSpec(source=render, target=END, carries=spoken))


async def detect_language(ctx) -> str:
    ctx.state.trace.append("detect")
    return f"pirate::{ctx.inputs}"


async def render_language(ctx) -> str:
    ctx.state.trace.append("render")
    dialect, _, text = ctx.inputs.partition("::")
    return f"Arr! {text}" if dialect == "pirate" else text


piratical = StrategySpec("piratical", {detect: detect_language, render: render_language})


# ── three arms of ONE design: two callables and a subgraph ───────────────────────────────────

plain = StrategySpec("plain", {pick: pick_formal, compose: compose_sentence,
                               translate: translate_none})
shouty = StrategySpec("shouty", {pick: pick_casual, compose: compose_sentence,
                                 translate: translate_shouty})
nested = StrategySpec("nested", {pick: pick_formal, compose: compose_sentence,
                                 translate: SubgraphBinding(Translation(), piratical)})


def main() -> None:
    spec = TracedHello()

    print("the child, run entirely on its own — if it could not, it would be a fragment:")
    state = TracedGuest(name="Ada")
    child_out = Translation().render(piratical).run_sync(inputs="Hello, Ada!", state=state)
    print(f"  -> {child_out!r}   trace={state.trace}\n")

    print("the same child, as one node of the parent:")
    for strategy in (plain, shouty, nested):
        state = TracedGuest()
        result = spec.render(strategy).run_sync(inputs="Ada", state=state)
        print(f"  {strategy.name:<7} nodes={sorted(spec.render(strategy).nodes)}")
        print(f"          child steps={state.trace or 'none'}  -> {result!r}")

    ids = [sorted(spec.render(s).nodes) for s in (plain, shouty, nested)]
    assert ids[0] == ids[1] == ids[2], ids
    print(f"\nparent node ids identical across all three: {ids[0]}")
    print(f"what varies (shouty vs nested): {spec.varies(shouty, nested)}")


if __name__ == "__main__":
    main()
