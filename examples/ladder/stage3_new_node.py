"""Rung 3 — the design grows a node, and every strategy must answer for it.

A `translate` stage is added between `compose` and END. The design changed, so this is a NEW
GraphSpec rather than an edit — rungs 1 and 2 keep working, which is the point of a declaration
being a value.

⛔ THE RULE THIS RUNG EXISTS TO SHOW: a strategy binds EVERY node, including the ones it does not
change. There is no inheritance and no partial override, and that is deliberate. A partial
strategy makes "what differs between these two arms" a question you answer by opening two files
and reconstructing an override chain — which is the exact question a battle exists to answer for
you in one line.

So adding a node to a design breaks every strategy over it, loudly, at declaration time. That is
the feature. The alternative is a strategy that silently does not run a stage it never heard of.

    uv run python3 -m examples.ladder.stage3_new_node
"""
from __future__ import annotations

from examples.ladder.stage1_bare import (
    Guest,
    compose,
    compose_sentence,
    greeting,
    pick,
    pick_formal,
    salutation,
)
from examples.ladder.stage2_strategies import pick_casual
from workflow_workbench import (
    END,
    START,
    EdgeSpec,
    GraphSpec,
    NodeSpec,
    SpecError,
    StrategySpec,
    VariableSpec,
)

spoken = VariableSpec("spoken", str)

translate = NodeSpec("translate", inputs=(greeting,), outputs=(spoken,))
"""Render the greeting in the guest's language. New role, same design otherwise."""


class TranslatedHello(GraphSpec):
    name = "translated_hello"
    state_type = Guest
    input_type, output_type = str, str
    nodes = (pick, compose, translate)
    edges = (EdgeSpec(START, pick),
             EdgeSpec(pick, compose, salutation),
             EdgeSpec(compose, translate, greeting),
             EdgeSpec(translate, END, spoken))


async def translate_none(ctx) -> str:
    """English in, English out. A stage that declines to act still SAYS so by being bound."""
    return ctx.inputs


async def translate_shouty(ctx) -> str:
    return ctx.inputs.upper()


formal_t = StrategySpec("formal", {pick: pick_formal, compose: compose_sentence,
                                   translate: translate_none})
casual_t = StrategySpec("casual", {pick: pick_casual, compose: compose_sentence,
                                   translate: translate_shouty})


def main() -> None:
    spec = TranslatedHello()

    for strategy in (formal_t, casual_t):
        state = Guest()
        result = spec.render(strategy).run_sync(inputs="Ada", state=state)
        print(f"  {strategy.name:<7} -> {result!r}")

    print(f"\nnow TWO nodes vary: {spec.varies(formal_t, casual_t)}")

    # ── and the refusal, which is the actual lesson ──────────────────────────────────────────
    stale = StrategySpec("written_before_translate_existed",
                         {pick: pick_formal, compose: compose_sentence})
    print("\na strategy that predates the new node:")
    try:
        spec.render(stale)
    except SpecError as exc:
        print(f"  refused at declaration time, not mid-run:\n    {str(exc).splitlines()[-1]}")


if __name__ == "__main__":
    main()
