"""Rung 1 — the same hello world as a GraphSpec. Bare: one design, one strategy.

Compare with `their_hello.py` side by side. The graph that comes out is the same graph; what
changes is that the DESIGN is now data:

    theirs      the topology lives in `g.add(...)` calls inside a function
    ours        `nodes` and `edges` are tuples you can read, check and draw before any
                implementation exists

⚠️ On this rung alone that is a lateral move, and pretending otherwise would be dishonest — you
have written slightly more code for the same result. The declaration starts paying at rung 2,
when there are two implementations of `pick` and something has to hold them to one shape.

What you get already, and cannot get from a built Graph:

    HelloWorld().check()      runs with NO strategy and NO implementations
    HelloWorld().diagram()    draws the design before anything is written

    uv run python3 -m examples.ladder.stage1_bare
"""
from __future__ import annotations

from dataclasses import dataclass

from workflow_workbench import (
    END,
    START,
    EdgeSpec,
    GraphSpec,
    NodeSpec,
    StrategySpec,
    VariableSpec,
)


@dataclass
class Guest:
    """Their `CounterState`'s job: something the steps share that is not a value on an edge."""

    name: str = "world"


# ── the vocabulary ──────────────────────────────────────────────────────────────────────────
#
# `salutation` and `greeting` are BOTH `str`. That is exactly why they are separate
# VariableSpecs: no type checker can tell you `compose` was wired to the wrong one, because
# there is only one type in the room. A name can.

salutation = VariableSpec("salutation", str)
greeting = VariableSpec("greeting", str)

pick = NodeSpec("pick", outputs=(salutation,))
"""Choose how to address the guest. THE ROLE — not one way of doing it."""

compose = NodeSpec("compose", inputs=(salutation,), outputs=(greeting,))
"""Turn a salutation into the sentence that is handed back."""


class HelloWorld(GraphSpec):
    """`str -> str`, in two stages. This declaration does not change again until rung 3."""

    name = "hello_world"
    state_type = Guest
    input_type, output_type = str, str
    nodes = (pick, compose)
    edges = (EdgeSpec(START, pick),
             EdgeSpec(pick, compose, salutation),
             EdgeSpec(compose, END, greeting))


# ── one implementation of each role ─────────────────────────────────────────────────────────

async def pick_formal(ctx) -> str:
    ctx.state.name = ctx.inputs
    return "Hello"


async def compose_sentence(ctx) -> str:
    return f"{ctx.inputs}, {ctx.state.name}!"


formal = StrategySpec("formal", {pick: pick_formal, compose: compose_sentence})


def main() -> None:
    spec = HelloWorld()

    # ⚠️ No strategy, no implementations, no engine. This is the thing a built Graph cannot do,
    # because a built Graph cannot exist until every function is written.
    print(f"check() with nothing implemented: {spec.check() or 'clean'}")

    graph = spec.render(formal)
    state = Guest()
    print(f"result: {graph.run_sync(inputs='Ada', state=state)!r}")
    print(f"nodes:  {sorted(graph.nodes)}")

    print("\nthe design, drawn from the declaration:")
    print(spec.diagram(formal))


if __name__ == "__main__":
    main()
