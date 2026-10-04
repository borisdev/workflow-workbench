"""A workflow whose stages are JUDGEMENT CALLS — the shape this library is actually for.

⛔ PLACEHOLDER DOMAIN. The nouns below are stand-ins. The SHAPE is the point: four stages, each
one a judgement two competent people would implement differently, and two strategies differing in
exactly ONE of them. Swap the subject matter for your own; the declaration, the checks and the
diagrams do not care.

⚠️ NOTHING IS IMPLEMENTED HERE, and that is the demonstration rather than an omission. A design
is data, so all of this runs against stubs:

    coherence_check()   real findings on a real declaration
    diagram()           the picture, before any code exists
    diff_diagram(a, b)  the two arms, with the one differing stage highlighted

⛔ What you will NOT find is a SCORE. A battle needs real implementations; printing a number from
stubs would be a claim the artifact does not deliver — the exact failure this library exists to
catch. `examples/greeting.py` has a battle with real implementations behind it.

Contrast with `greeting.py` deliberately. There, `trim` versus `trim_and_collapse` is a question
with a right answer you could look up. Here every stage is contestable:

    gather    how wide do you cast? recall against noise, with no ground truth for either
    screen    what counts as relevant? the judgement everything downstream inherits
    weigh     how do you rank what survived? the most arguable step in any such workflow
    compose   what do you say, and what do you admit you do not know?
"""
from __future__ import annotations

from workflow_workbench import (
    END, START, EdgeSpec, GraphSpec, StepSpec, StrategySpec, VariableSpec, blocking)

# ── the values that move ────────────────────────────────────────────────────────────────────
# PLACEHOLDER: these nouns are the domain. Everything else is structure.

request = VariableSpec("request", str)
candidates = VariableSpec("candidates", list)
relevant = VariableSpec("relevant", list)
ranked = VariableSpec("ranked", list)
answer = VariableSpec("answer", str)

# ── the roles, each a slot for a CONTESTABLE algorithm ──────────────────────────────────────
#
# ⚠️ `problem` states what makes the stage HARD, not what to do. The design owns the problem;
# a strategy owns the solution.

gather = StepSpec(
    "gather", inputs=(request,), outputs=(candidates,),
    problem="Cast wide enough to find what matters, narrow enough that the next stage is not "
            "drowned. There is no ground truth for either side, so recall and noise trade off "
            "with nothing to appeal to.")

screen = StepSpec(
    "screen", inputs=(candidates,), outputs=(relevant,),
    problem="Decide what actually bears on the request. Everything later inherits this "
            "judgement, and a wrong exclusion is invisible downstream — nothing reports what "
            "was dropped.")

weigh = StepSpec(
    "weigh", inputs=(relevant,), outputs=(ranked,),
    problem="Order what survived. The most arguable step here: two reasonable rankings of one "
            "set can disagree completely, and the order is what the reader acts on.")

compose = StepSpec(
    "compose", inputs=(ranked,), outputs=(answer,),
    problem="Say what the ranking supports and no more. The temptation is to sound confident "
            "about something that was a judgement call three stages ago.")


class Assessment(GraphSpec):
    """PLACEHOLDER: `review a proposed change`, `assess a claim`, `triage an incident` — any
    task whose stages are judgements rather than lookups."""

    name = "assessment"
    input_type, output_type = str, str
    nodes = (gather, screen, weigh, compose)
    edges = (EdgeSpec(source=START, target=gather, carries=request),
             EdgeSpec(source=gather, target=screen, carries=candidates),
             EdgeSpec(source=screen, target=weigh, carries=relevant),
             EdgeSpec(source=weigh, target=compose, carries=ranked),
             EdgeSpec(source=compose, target=END, carries=answer))


# ── two arms, differing in exactly ONE stage ────────────────────────────────────────────────
#
# ⛔ STUBS, and named so. `diagram(strategy)` prints the bound function's name, so the picture
# says `..._stub` rather than implying there is an algorithm behind it.

async def gather_stub(ctx) -> list: ...
async def screen_stub(ctx) -> list: ...
async def compose_stub(ctx) -> str: ...
async def weigh_by_recency_stub(ctx) -> list: ...
async def weigh_by_agreement_stub(ctx) -> list: ...


by_recency = StrategySpec("by_recency", {
    gather: gather_stub, screen: screen_stub,
    weigh: weigh_by_recency_stub,              # the only difference
    compose: compose_stub})

by_agreement = StrategySpec("by_agreement", {
    gather: gather_stub, screen: screen_stub,
    weigh: weigh_by_agreement_stub,            # the only difference
    compose: compose_stub})


if __name__ == "__main__":
    spec = Assessment()

    print("1. the design alone — nothing implemented:")
    print(f"   coherence_check() -> {spec.coherence_check() or 'clean'}\n")

    print("2. the picture, also with nothing implemented:\n")
    print(spec.diagram(), "\n")

    print("3. with a strategy of stubs:")
    found = spec.coherence_check(by_recency)
    for f in found:
        print(f"   [{f.check} / about={f.about} / blocking={f.blocking}]")
        print(f"   {f}\n")
    print(f"   blocking: {len(blocking(found))} — so render() would succeed\n")

    print("4. the two arms, and the one stage that differs:\n")
    print(spec.diff_diagram(by_recency, by_agreement), "\n")
    print(f"   varies: {spec.varies(by_recency, by_agreement)}\n")

    print("5. the score — DELIBERATELY ABSENT.")
    print("   A battle needs real implementations. A number out of stubs would be a claim the")
    print("   artifact does not deliver. Implement the two `weigh` arms, then")
    print("   eval_battle(spec, by_recency, by_agreement, dataset) answers whether the")
    print("   difference is real — against a replicate arm as the noise floor.")
