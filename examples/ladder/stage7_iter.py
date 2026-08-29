"""Rung 7 — `render()` returns a REAL Graph, proven with their own API.

The strongest claim this library makes is a negative one: it does not replace the runtime. The
way to show that is not a sentence, it is to take a graph out of `render()` and drive it with
`graph.iter()` — a pydantic-graph API this package has never heard of, straight from their
`step_by_step.py`.

If any wrapping had crept in, this rung is where it would fail.

    uv run python3 -m examples.ladder.stage7_iter
"""
from __future__ import annotations

import asyncio

from examples.ladder.stage1_bare import Guest, HelloWorld, formal
from examples.ladder.stage4_subgraph import TracedGuest, TracedHello, nested


async def drive(graph, inputs, state):
    """Their step-by-step form, unchanged: `async with graph.iter(...)`, then iterate events."""
    events = []
    async with graph.iter(inputs=inputs, state=state) as run:
        async for event in run:
            events.append(event)
            if run.output is not None:
                break
    return run.output, events


def main() -> None:
    graph = HelloWorld().render(formal)
    state = Guest()
    output, events = asyncio.run(drive(graph, "Ada", state))
    print(f"iter() over a rendered graph -> {output!r}")
    for e in events:
        print(f"    {e}")

    # ⚠️ And through a subgraph binding, which is the case that could plausibly have leaked a
    # wrapper into the event stream. The parent emits ONE task for `translate`; the child's two
    # steps run inside it and are not parent events.
    print("\nthe same, on an arm whose `translate` is a whole child design:")
    nested_graph = TracedHello().render(nested)
    traced = TracedGuest()
    output, events = asyncio.run(drive(nested_graph, "Ada", traced))
    print(f"  -> {output!r}")
    print(f"  parent events:      {[getattr(e, 'node_id', e) for e in events]}")
    print(f"  child steps ran:    {traced.trace}")
    print("  -> the child executed, and stayed invisible to the parent's event stream.")


if __name__ == "__main__":
    main()
