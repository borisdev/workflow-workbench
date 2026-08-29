"""Rung 2 — two strategies over ONE design. This is where the declaration starts paying.

`pick` has two implementations now. Nothing about the design moved:

    formal    pick_formal   -> 'Hello'    ->  'Hello, Ada!'
    casual    pick_casual   -> 'Yo'       ->  'Yo, Ada!'

⛔ The load-bearing fact, and the reason `node_id=node.name` exists: BOTH ARMS HAVE THE SAME NODE
IDS. Left to itself pydantic-graph names a node after the bound function, so these two would be
`{pick_formal, compose_sentence}` and `{pick_casual, compose_sentence}` — disjoint node sets, and
any comparison between them has nothing to line up. Measured both ways in `docs/probe_api.py`
probes 5 and 5b.

That is what makes rung 5's battle possible. A battle needs to say "these two differ AT `pick`",
and it can only say that if `pick` means the same node in both.

    uv run python3 -m examples.ladder.stage2_strategies
"""
from __future__ import annotations

from examples.ladder.stage1_bare import (
    Guest,
    HelloWorld,
    compose,
    compose_sentence,
    formal,
    pick,
)
from workflow_workbench import StrategySpec


async def pick_casual(ctx) -> str:
    """Same contract, same one argument, different word. That is all a strategy ever is."""
    ctx.state.name = ctx.inputs
    return "Yo"


casual = StrategySpec("casual", {pick: pick_casual, compose: compose_sentence})


def main() -> None:
    spec = HelloWorld()

    for strategy in (formal, casual):
        graph = spec.render(strategy)
        state = Guest()
        result = graph.run_sync(inputs="Ada", state=state)
        print(f"  {strategy.name:<7} nodes={sorted(graph.nodes)}  -> {result!r}")

    a, b = spec.render(formal), spec.render(casual)
    print(f"\nnode ids identical across arms: {sorted(a.nodes) == sorted(b.nodes)}")
    print(f"what actually varies:           {spec.varies(formal, casual)}")

    # ⚠️ `compose` is bound to the SAME function object in both arms, so it does not appear
    # above. "What varies" is a fact about the bindings, not about the topology — the topology
    # is identical by construction and a structural diff of these two is empty, forever.
    print(f"shared, therefore not listed:   compose -> {formal[compose].__name__}")


if __name__ == "__main__":
    main()
