"""Rung 0 — the control. Pydantic Graph alone, no workbench anywhere in the file.

A variation of their `visualize_graph.py` from
<https://pydantic.dev/docs/ai/graph/builder/>, which is the smallest complete program in their
builder docs: two steps, the second formatting the first's output.

    theirs      step_a -> 10          step_b -> f'Result: {ctx.inputs}'
    ours        pick   -> 'Hello'     compose -> f'{salutation}, {name}!'

⚠️ This rung exists to be the BASELINE, not a strawman. Read it and notice that it is fine. One
graph with one implementation per step needs nothing else, and the README says so out loud: if
this is your situation, use Pydantic Graph directly and stop here.

What it cannot do is the next rung's question — "and what if `pick` were written differently?"

    uv run python3 -m examples.ladder.their_hello
"""
from __future__ import annotations

from dataclasses import dataclass

from pydantic_graph import GraphBuilder, StepContext


@dataclass
class Guest:
    name: str = "world"


def build():
    g = GraphBuilder(state_type=Guest, input_type=str, output_type=str)

    @g.step
    async def pick(ctx: StepContext[Guest, None, str]) -> str:
        ctx.state.name = ctx.inputs
        return "Hello"

    @g.step
    async def compose(ctx: StepContext[Guest, None, str]) -> str:
        return f"{ctx.inputs}, {ctx.state.name}!"

    g.add(
        g.edge_from(g.start_node).to(pick),
        g.edge_from(pick).to(compose),
        g.edge_from(compose).to(g.end_node),
    )
    return g.build()


def main() -> None:
    graph = build()
    state = Guest()
    print(f"result: {graph.run_sync(inputs='Ada', state=state)!r}")
    print(f"nodes:  {sorted(graph.nodes)}")
    print("\ntheir own mermaid, from the BUILT graph:")
    print(graph.render(title="their_hello", direction="LR"))


if __name__ == "__main__":
    main()
