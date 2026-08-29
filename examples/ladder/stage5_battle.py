"""Rung 5 — score both arms on the same cases, against a noise floor.

Rung 2 told you WHAT differs (`pick`). This tells you whether it MATTERS.

⛔ THE REPLICATE IS NOT OPTIONAL, and it is the only reason a number here means anything. Before
comparing formal against casual, the same strategy is run against ITSELF. Whatever difference
that produces is noise, and any real delta must clear it. Without it a +0.4 reads as a result
when the floor is 0.5.

⚠️ `per_case_spread`, not difference-of-averages. A replicate whose per-case scores moved +1 and
−1 has identical averages, so a difference of averages reports a floor of 0.0 — licensing noise
as a result, which is the exact failure this rung exists to prevent.

Built ON pydantic-evals: `Case`, `Dataset` and `Evaluator` are theirs, imported and used
directly. There is no EvalCase, no Grader, no EvalReport here.

    uv run python3 -m examples.ladder.stage5_battle
"""
from __future__ import annotations

from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext

from examples.ladder.stage1_bare import Guest, HelloWorld, formal
from examples.ladder.stage2_strategies import casual
from workflow_workbench.evals import eval_battle


class Warmth(Evaluator):
    """A deliberately crude rubric — the point of this rung is the FLOOR, not the metric."""

    def evaluate(self, ctx: EvaluatorContext) -> float:
        return 1.0 if ctx.output.startswith("Yo") else 0.0


class Length(Evaluator):
    def evaluate(self, ctx: EvaluatorContext) -> float:
        return float(len(ctx.output))


DATASET = Dataset(
    name="greetings",
    cases=[Case(name=n, inputs=n) for n in ("Ada", "Grace", "Alan")],
    evaluators=[Warmth(), Length()],
)


def run_with_state(graph, inputs):
    """The design has a `state_type`, so the default runner (which passes none) will not do."""
    return graph.run_sync(inputs=inputs, state=Guest())


def main() -> None:
    spec = HelloWorld()

    # ── the floor FIRST, so there is a bar before there is a number ─────────────────────────
    floor = eval_battle(spec, formal, formal, DATASET, run=run_with_state)
    print(f"{floor!r}")
    noise = floor.per_case_spread()
    print(f"  noise floor (max per-case spread): {noise}\n")

    battle = eval_battle(spec, formal, casual, DATASET, run=run_with_state)
    print(f"{battle!r}")
    deltas = battle.deltas()
    print(f"  deltas (casual - formal):          {deltas}\n")

    # ⚠️ The floor here is a genuine 0.0 — every implementation on this ladder is deterministic,
    # so a replicate really cannot differ. Do NOT read that as "0.0 floors are fine". In a real
    # arm a 0.0 floor is usually a CACHE: the second run answered from the first one's result,
    # measured nothing, and licensed any observed difference as a result. If the arms call a
    # model, make the replicate miss the cache before believing its floor.
    print("verdict, per metric:")
    for metric, delta in sorted(deltas.items()):
        bar = noise.get(metric, 0.0)
        readable = abs(delta) > bar
        print(f"  {metric:<8} delta={delta:+.2f}  floor={bar:.2f}  "
              f"-> {'REAL' if readable else 'INSIDE THE NOISE — not a result'}")


if __name__ == "__main__":
    main()
