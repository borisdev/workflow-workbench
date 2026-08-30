"""Simple Counter — pydantic-graph's own flagship example, as a GraphSpec with two strategies.

Their version has ONE implementation per node. This declares the same shape once, then fills it
twice — which is the entire difference between the two libraries, in the smallest example that
shows it.

    uv run python3 examples/counter.py
"""
from __future__ import annotations

from dataclasses import dataclass

from workflow_workbench import END, START, EdgeSpec, GraphSpec, NodeSpec, StrategySpec, VariableSpec


@dataclass
class CounterState:
    value: int = 0


seed = VariableSpec("seed", int)
count = VariableSpec("count", int)

# ⚠️ `increment` DOES consume the graph input — `add_one` reads `ctx.inputs`. Declaring it
# was optional while `EdgeSpec.carries` was; now that every edge names what it carries, the
# node contract has to be honest about receiving it.
increment = NodeSpec("increment", inputs=(seed,), outputs=(count,))
double_it = NodeSpec("double_it", inputs=(count,), outputs=(count,))


class Counter(GraphSpec):
    """One design. `increment` then `double_it`, over a shared `CounterState`."""

    name = "counter"
    state_type, input_type, output_type = CounterState, int, int
    nodes = (increment, double_it)
    edges = (
        EdgeSpec(START, increment, seed),
        EdgeSpec(increment, double_it, count),
        EdgeSpec(double_it, END, count),
    )


# ── strategy 1: the obvious one ─────────────────────────────────────────────────────────────
async def add_one(ctx) -> int:
    ctx.state.value = ctx.inputs + 1
    return ctx.state.value


async def times_two(ctx) -> int:
    ctx.state.value = ctx.inputs * 2
    return ctx.state.value


# ── strategy 2: same contract, different arithmetic ─────────────────────────────────────────
async def add_ten(ctx) -> int:
    ctx.state.value = ctx.inputs + 10
    return ctx.state.value


async def times_three(ctx) -> int:
    ctx.state.value = ctx.inputs * 3
    return ctx.state.value


modest = StrategySpec("modest", {increment: add_one, double_it: times_two})
aggressive = StrategySpec("aggressive", {increment: add_ten, double_it: times_three})


def main() -> None:
    spec = Counter()

    findings = spec.check()
    print(f"check() with no strategy at all: {findings or 'clean'}")

    for strategy in (modest, aggressive):
        graph = spec.render(strategy)
        result = graph.run_sync(inputs=5, state=CounterState())
        print(f"  {strategy.name:<12} nodes={sorted(graph.nodes)}  run(5) -> {result}")

    a, b = spec.render(modest), spec.render(aggressive)
    print(f"\nnode ids identical across arms: {sorted(a.nodes) == sorted(b.nodes)}")
    print(f"what actually varies: {spec.varies(modest, aggressive)}")

    print("\n--- diff_diagram (mermaid) ---")
    print(spec.diff_diagram(modest, aggressive))


if __name__ == "__main__":
    main()
