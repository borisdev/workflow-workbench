"""Rung 9 — routing on the shape of the answer, with the branches converging again.

                        ┌── Urgent ──> escalate ──┐
    intake ──> route ───┤                         ├──> report ──> END
                        └── Routine ─> research ──┘

⚠️ `report` has TWO incoming edges and is NOT a fan-in. Measured before this rung was written: a
node downstream of two branches is invoked ONCE, because at most one branch fires. `check_step_arity`
would otherwise report every branching design as the fan-in defect rung 8 exists to catch, so the
exclusivity analysis shipped with `DecisionSpec` rather than after it.

⚠️ A `DecisionSpec` binds NOTHING. Two strategies can differ in every step and are still guaranteed
to route identically — which is the whole reason a battle over a branching design means anything.
If routing were a bound implementation, an arm could quietly reroute itself and the comparison
would be measuring two different workflows.

⛔ And the honest part: `intake` returns `Urgent | Routine`, so the ROUTING depends on what a step
decided. The design fixes the branches; it does not fix which one is taken. That is the correct
split — a declaration should say what the possibilities are, not predict the data.

    uv run python3 -m examples.ladder.stage9_decision
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
    SpecError,
    StrategySpec,
    VariableSpec,
)


@dataclass
class Urgent:
    text: str


@dataclass
class Routine:
    text: str


@dataclass
class Log:
    steps: list[str] = field(default_factory=list)


complaint = VariableSpec("complaint", str)
verdict = VariableSpec("verdict", object)
handled = VariableSpec("handled", str)
report_out = VariableSpec("report_out", str)

intake = NodeSpec("intake", inputs=(complaint,), outputs=(verdict,))
escalate = NodeSpec("escalate", inputs=(verdict,), outputs=(handled,))
research = NodeSpec("research", inputs=(verdict,), outputs=(handled,))
report = NodeSpec("report", inputs=(handled,), outputs=(report_out,))

route = DecisionSpec("route", note="urgent, or something to look up?",
                     inputs=(verdict,), outputs=(verdict,))


class Triage(GraphSpec):
    name = "triage"
    state_type = Log
    input_type, output_type = str, str
    nodes = (intake, escalate, research, report)
    decisions = (route,)
    edges = (EdgeSpec(source=START, target=intake, carries=complaint),
             EdgeSpec(source=intake, target=route, carries=verdict),
             EdgeSpec(source=route, target=escalate, carries=verdict, when=Urgent),
             EdgeSpec(source=route, target=research, carries=verdict, when=Routine),
             EdgeSpec(source=escalate, target=report, carries=handled),
             EdgeSpec(source=research, target=report, carries=handled),
             EdgeSpec(source=report, target=END, carries=report_out))


async def triage_keywords(ctx) -> Urgent | Routine:
    ctx.state.steps.append("intake")
    urgent = any(w in ctx.inputs.lower() for w in ("chest pain", "can't breathe"))
    return Urgent(ctx.inputs) if urgent else Routine(ctx.inputs)


async def triage_everything_urgent(ctx) -> Urgent | Routine:
    """A second arm that routes differently — by returning a different TYPE, not by rewiring."""
    ctx.state.steps.append("intake")
    return Urgent(ctx.inputs)


async def do_escalate(ctx) -> str:
    ctx.state.steps.append("escalate")
    return f"seek care now: {ctx.inputs.text}"


async def do_research(ctx) -> str:
    ctx.state.steps.append("research")
    return f"looked it up: {ctx.inputs.text}"


async def do_report(ctx) -> str:
    ctx.state.steps.append("report")
    return f"[{ctx.inputs}]"


careful = StrategySpec("careful", {intake: triage_keywords, escalate: do_escalate,
                                   research: do_research, report: do_report})
alarmist = StrategySpec("alarmist", {intake: triage_everything_urgent, escalate: do_escalate,
                                     research: do_research, report: do_report})


def main() -> None:
    spec = Triage()
    print(f"check(): {spec.check(careful) or 'clean — including reachability, through branches'}\n")

    graph = spec.render(careful)
    for text in ("chest pain since this morning", "dry skin on my elbow"):
        log = Log()
        out = graph.run_sync(inputs=text, state=log)
        print(f"  {text!r}")
        print(f"     steps={log.steps}  -> {out!r}")
        assert log.steps.count("report") == 1, log.steps

    print("\n`report` ran exactly once on each — two incoming edges, and NOT a fan-in.")
    print(f"and it binds nothing for the router: 'route' in bindings = "
          f"{route in careful.bindings}")

    print(f"\ntwo arms route differently without rewiring: "
          f"{spec.varies(careful, alarmist)}")
    log = Log()
    print(f"  alarmist on the elbow: "
          f"{spec.render(alarmist).run_sync(inputs='dry skin on my elbow', state=log)!r}")
    print(f"  steps={log.steps}")

    # ── the refusals ────────────────────────────────────────────────────────────────────────
    print("\nwhat is refused:")

    class NoWhen(Triage):
        name = "no_when"
        edges = (EdgeSpec(source=START, target=intake, carries=complaint),
                 EdgeSpec(source=intake, target=route, carries=verdict),
                 EdgeSpec(source=route, target=escalate, carries=verdict),          # <- no `when`
                 EdgeSpec(source=route, target=research, carries=verdict, when=Routine),
                 EdgeSpec(source=escalate, target=report, carries=handled),
                 EdgeSpec(source=research, target=report, carries=handled),
                 EdgeSpec(source=report, target=END, carries=report_out))

    for finding in NoWhen().check(careful):
        print(f"  {finding[:118]}...")

    class StrayWhen(Triage):
        name = "stray_when"
        edges = (EdgeSpec(source=START, target=intake, carries=complaint, when=Urgent),   # <- source is not a decision
                 EdgeSpec(source=intake, target=route, carries=verdict),
                 EdgeSpec(source=route, target=escalate, carries=verdict, when=Urgent),
                 EdgeSpec(source=route, target=research, carries=verdict, when=Routine),
                 EdgeSpec(source=escalate, target=report, carries=handled),
                 EdgeSpec(source=research, target=report, carries=handled),
                 EdgeSpec(source=report, target=END, carries=report_out))

    for finding in StrayWhen().check(careful):
        print(f"  {finding[:118]}...")

    try:
        NoWhen().render(careful)
    except SpecError:
        print("  -> neither renders.")

    print("\nthe design, with the router drawn as what it is:")
    print(spec.diagram(careful))


if __name__ == "__main__":
    main()
