"""Rung 8 — two producers into one consumer, done correctly.

Rung 3 grew the design forwards. This grows it SIDEWAYS, which is the shape that was quietly
broken until `check_step_arity` existed:

    pick_formal ──┐
                  ├──> collect ──> announce ──> END
    pick_casual ──┘

⛔ THE WRONG VERSION IS ALSO SHOWN, because the failure is silent and worth seeing once. Declare
`collect` as an ordinary NodeSpec with two inputs and the design renders, runs, and returns ONE
greeting — the step is invoked once per incoming edge and all but one result is discarded. Every
other check passes it: both variables are declared on both ends, everything reaches END.

A `JoinSpec` is the shape that can actually combine arrivals. Its reducer is
`(current, input) -> current`, so each arrival folds into an accumulator instead of overwriting
one.

⚠️ It lives in `joins`, not `nodes`, and a `StrategySpec` binds nothing for it. A join carries its
own reducer — there is no role here for a strategy to fill, and `varies()` will never mention it.

⚠️ `initial_factory=list`, never `initial=[]`. A mutable seed built at declaration time is shared
by every run of the graph, so one run's greetings leak into the next. `JoinSpec` refuses a
declaration that gives neither.

    uv run python3 -m examples.ladder.stage8_join
"""
from __future__ import annotations

from dataclasses import dataclass

from pydantic_graph.join import reduce_list_append

from workflow_workbench import (
    END,
    START,
    EdgeSpec,
    GraphSpec,
    JoinSpec,
    NodeSpec,
    SpecError,
    StrategySpec,
    VariableSpec,
)


@dataclass
class Guest:
    name: str = "world"


name_in = VariableSpec("name_in", str)
formal_line = VariableSpec("formal_line", str)
casual_line = VariableSpec("casual_line", str)
both = VariableSpec("both", list)
announcement = VariableSpec("announcement", str)

say_formal = NodeSpec("say_formal", inputs=(name_in,), outputs=(formal_line,))
say_casual = NodeSpec("say_casual", inputs=(name_in,), outputs=(casual_line,))
announce = NodeSpec("announce", inputs=(both,), outputs=(announcement,))

collect = JoinSpec("collect", reduce_list_append, initial_factory=list,
                   inputs=(formal_line, casual_line), outputs=(both,))
"""⚠️ Declared, so `check_reachable` can see it. Before `JoinSpec` a join could only be created
inside `build_pydantic_structure()`, which turns reachability checking off for the whole design —
so the only way to have a join was to stop checking the graph that contained it."""


class Greetings(GraphSpec):
    name = "greetings"
    state_type = Guest
    input_type, output_type = str, str
    nodes = (say_formal, say_casual, announce)
    joins = (collect,)
    edges = (EdgeSpec(START, say_formal, name_in),
             EdgeSpec(START, say_casual, name_in),
             EdgeSpec(say_formal, collect, formal_line),
             EdgeSpec(say_casual, collect, casual_line),
             EdgeSpec(collect, announce, both),
             EdgeSpec(announce, END, announcement))


async def formal(ctx) -> str:
    ctx.state.name = ctx.inputs
    return f"Hello, {ctx.inputs}!"


async def casual(ctx) -> str:
    ctx.state.name = ctx.inputs
    return f"Yo, {ctx.inputs}!"


async def announce_both(ctx) -> str:
    # ⚠️ SORTED. Two producers ran concurrently, so arrival order is not ours to assume — and a
    # test that passes on whichever order happened today is a flaky test wearing a green tick.
    return " / ".join(sorted(ctx.inputs))


greet = StrategySpec("greet", {say_formal: formal, say_casual: casual, announce: announce_both})


# ── the same shape declared WRONGLY, kept because the failure is invisible ───────────────────

collect_as_step = NodeSpec("collect", inputs=(formal_line, casual_line), outputs=(both,))


class BrokenGreetings(Greetings):
    """`collect` as an ordinary step. Renders, runs, drops a result."""

    name = "broken_greetings"
    nodes = (say_formal, say_casual, collect_as_step, announce)
    joins = ()
    edges = (EdgeSpec(START, say_formal, name_in),
             EdgeSpec(START, say_casual, name_in),
             EdgeSpec(say_formal, collect_as_step, formal_line),
             EdgeSpec(say_casual, collect_as_step, casual_line),
             EdgeSpec(collect_as_step, announce, both),
             EdgeSpec(announce, END, announcement))


def main() -> None:
    spec = Greetings()
    print(f"check(): {spec.check(greet) or 'clean'}")

    state = Guest()
    print(f"run('Ada') -> {spec.render(greet).run_sync(inputs='Ada', state=state)!r}")
    print(f"nodes:        {sorted(spec.render(greet).nodes)}\n")

    print("the same shape with `collect` as an ordinary step:")
    async def collect_step(ctx) -> list:
        return [ctx.inputs]

    broken = StrategySpec("broken", {say_formal: formal, say_casual: casual,
                                     collect_as_step: collect_step, announce: announce_both})
    for finding in BrokenGreetings().check(broken):
        print(f"  refused: {finding[:110]}...")
    try:
        BrokenGreetings().render(broken)
    except SpecError:
        print("  -> and it will not render. Before this check it rendered, ran, "
              "and returned one greeting.")

    print("\nthe design, with the join drawn as what it is:")
    print(spec.diagram(greet))


if __name__ == "__main__":
    main()
