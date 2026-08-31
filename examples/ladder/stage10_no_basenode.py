"""Rung 10 — the three things people reach for `BaseNode` to do, done without one.

`node(BaseNode)` is the one Pydantic Graph feature this library CANNOT declare, and the reason is
structural: a BaseNode's `run()` returns the next node, so its topology lives inside its
implementation. Declared `edges` would be a lie it is free to ignore, and two arms binding
different BaseNodes could be two different graphs while `diff_diagram()` drew them as one.

⚠️ But "cannot declare the feature" is not the same as "cannot do the work", and conflating them
is how a limitation gets bigger in the retelling. Nobody reaches for BaseNode because they want a
class. They reach for it to do one of three things, and all three are declarable:

    1. stop early          a gate that ends the run without doing the work
    2. go back             a retry loop
    3. dispatch            pick among several successors at run time

Each is a `DecisionSpec` branching on a type. What is actually lost is the AUTHORING STYLE, and
one real cost: porting an existing BaseNode app. For that, `render()` hands you a real
`pydantic_graph.Graph` — take it and use their API.

    uv run python3 -m examples.ladder.stage10_no_basenode
"""
from __future__ import annotations

from dataclasses import dataclass, field

from workflow_workbench import (
    END,
    START,
    DecisionSpec,
    EdgeSpec,
    GraphSpec,
    NodeSpec,
    StrategySpec,
    VariableSpec,
)


@dataclass
class Plan:
    text: str


@dataclass
class NotAPlan:
    why: str


@dataclass
class TooThin:
    text: str


@dataclass
class Log:
    steps: list = field(default_factory=list)
    attempts: int = 0


paste = VariableSpec("paste", str)
verdict = VariableSpec("verdict", object)
draft = VariableSpec("draft", str)
checked = VariableSpec("checked", object)
report = VariableSpec("report", str)

triage = NodeSpec("triage", inputs=(paste,), outputs=(verdict,))
accept = NodeSpec("accept", inputs=(verdict,), outputs=(paste,))
propose = NodeSpec("propose", inputs=(paste,), outputs=(draft,))
review = NodeSpec("review", inputs=(draft,), outputs=(checked,))
retry_seed = NodeSpec("retry_seed", inputs=(checked,), outputs=(paste,))
publish = NodeSpec("publish", inputs=(checked,), outputs=(report,))

gate = DecisionSpec("gate", note="is this a treatment plan at all?",
                    inputs=(verdict,), outputs=(verdict,))
again = DecisionSpec("again", note="good enough, or go round again?",
                     inputs=(checked,), outputs=(checked,))


class Intake(GraphSpec):
    """All three shapes in one design — a gate, a loop, and a dispatch.

                       ┌── NotAPlan ────────────────────────────> END      1. stop early
    triage ──> gate ───┤
                       └── Plan ──> accept ──> propose ──> review ──> again ──┬── Good ──> publish
                                       ▲                           │
                                       └──── retry_seed <──────────┘         2. go back
    """

    name = "intake"
    state_type = Log
    input_type, output_type = str, object
    nodes = (triage, accept, propose, review, retry_seed, publish)
    decisions = (gate, again)
    edges = (EdgeSpec(source=START, target=triage, carries=paste),
             EdgeSpec(source=triage, target=gate, carries=verdict),
             # 1. STOP EARLY — this branch has no node on it at all
             EdgeSpec(source=gate, target=END, carries=verdict, when=NotAPlan),
             EdgeSpec(source=gate, target=accept, carries=verdict, when=Plan),
             EdgeSpec(source=accept, target=propose, carries=paste),
             EdgeSpec(source=propose, target=review, carries=draft),
             EdgeSpec(source=review, target=again, carries=checked),
             # 2. GO BACK — a branch that returns to an earlier node
             EdgeSpec(source=again, target=retry_seed, carries=checked, when=TooThin),
             EdgeSpec(source=retry_seed, target=propose, carries=paste),
             EdgeSpec(source=again, target=publish, carries=checked, when=Plan),
             EdgeSpec(source=publish, target=END, carries=report))


async def do_triage(ctx) -> object:
    ctx.state.steps.append("triage")
    # 3. DISPATCH — the successor is chosen by the TYPE this returns, not by a hidden call
    return Plan(ctx.inputs) if "mg" in ctx.inputs else NotAPlan("no medication named")


async def do_accept(ctx) -> str:
    """⚠️ THE TAX, and it is the whole tax. `propose` is reached by two paths — the gate and the
    retry — and a NodeSpec cannot declare "this input arrives as EITHER a verdict or a paste". So
    each path converts to the same variable first. A BaseNode would just pass whatever it liked,
    which is exactly the freedom that makes its topology undeclarable."""
    ctx.state.steps.append("accept")
    return ctx.inputs.text


async def do_propose(ctx) -> str:
    ctx.state.attempts += 1
    ctx.state.steps.append(f"propose#{ctx.state.attempts}")
    return f"draft-{ctx.state.attempts}"


async def do_review(ctx) -> object:
    ctx.state.steps.append("review")
    return TooThin(ctx.inputs) if ctx.state.attempts < 2 else Plan(ctx.inputs)


async def do_retry_seed(ctx) -> str:
    ctx.state.steps.append("retry")
    return ctx.inputs.text


async def do_publish(ctx) -> str:
    ctx.state.steps.append("publish")
    return f"audited: {ctx.inputs.text}"


careful = StrategySpec("careful", {triage: do_triage, accept: do_accept,
                                   propose: do_propose, review: do_review,
                                   retry_seed: do_retry_seed, publish: do_publish})


async def do_triage_permissive(ctx) -> object:
    """A second arm that gates differently — WITHOUT touching the topology, which is the point."""
    ctx.state.steps.append("triage")
    return Plan(ctx.inputs)


permissive = StrategySpec("permissive", {triage: do_triage_permissive, accept: do_accept,
                                         propose: do_propose, review: do_review,
                                         retry_seed: do_retry_seed, publish: do_publish})


def main() -> None:
    spec = Intake()
    print(f"check(): {spec.check(careful) or 'clean — gate, loop and dispatch, all declared'}\n")

    graph = spec.render(careful)
    for text in ("my cat is unwell", "metformin 1000 mg daily"):
        log = Log()
        out = graph.run_sync(inputs=text, state=log)
        print(f"  {text!r}")
        print(f"     steps={log.steps}")
        print(f"     -> {out!r}")

    print("\n  ⚠️ the first paste never reached `propose`. That is `End(...)` from a BaseNode,")
    print("     expressed as a branch with no node on it.")
    print("  ⚠️ the second looped: propose ran twice, because `review` returned TooThin once.")

    log = Log()
    out = spec.render(permissive).run_sync(inputs="my cat is unwell", state=log)
    print(f"\n  a second arm gates differently, same topology: steps={log.steps}")
    print(f"  what varies: {spec.varies(careful, permissive)}")
    print("  ⚠️ a BaseNode arm could have changed the SHAPE here, and `varies()` would still")
    print("     have reported one differing node. That is the guarantee being bought.")

    print(f"\n{spec.diagram(careful)}")


if __name__ == "__main__":
    main()
