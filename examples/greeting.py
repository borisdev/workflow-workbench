"""The introductory example: normalize a name, then compose a greeting.

One design, two competing implementations of the first step, evaluated on the same cases. This
module is the whole example — the README shows excerpts of it and nothing else.

    uv run python3 -m examples.greeting

It is a variation of `visualize_graph.py` from <https://pydantic.dev/docs/ai/graph/builder/>,
their smallest complete builder program: two steps, the second formatting the first's output.
`examples/ladder/their_hello.py` keeps that original shape with no workbench in the file at all.

The behaviour the design is supposed to deliver:

    preserve the name's words, trim surrounding whitespace, collapse repeated internal
    whitespace, and return "Hello, {name}!"

Both strategies satisfy the declared types and structure. Only evaluation separates them, which
is the whole point of the pair.
"""
from __future__ import annotations

from workflow_workbench import (
    END,
    START,
    EdgeSpec,
    GraphSpec,
    StepSpec,
    SpecError,
    StrategySpec,
    VariableSpec,
)

# ── 1. the specification ────────────────────────────────────────────────────────────────────
#
# `clean_name` and `greeting` are both `str`. That is exactly why they are separate
# VariableSpecs: no type checker can tell you `compose` was wired to the wrong one, because
# there is only one type in the room. A name can.

raw_name = VariableSpec("raw_name", str)
clean_name = VariableSpec("clean_name", str)
greeting = VariableSpec("greeting", str)

normalize = StepSpec("normalize", inputs=(raw_name,), outputs=(clean_name,))
"""Turn what the caller typed into the name to greet. THE ROLE — not one way of doing it."""

compose = StepSpec("compose", inputs=(clean_name,), outputs=(greeting,))
"""Turn a name into the sentence handed back."""


class Greeting(GraphSpec):
    """`str -> str` in two steps. Checkable and drawable before either step is written."""

    name = "greeting"
    input_type, output_type = str, str
    nodes = (normalize, compose)
    edges = (EdgeSpec(source=START, target=normalize, carries=raw_name),
             EdgeSpec(source=normalize, target=compose, carries=clean_name),
             EdgeSpec(source=compose, target=END, carries=greeting))


# ── 2. the implementations — ordinary Pydantic Graph step bodies ────────────────────────────

async def trim(ctx) -> str:
    """Surrounding whitespace only. Leaves `Ada   Lovelace` as it found it."""
    return ctx.inputs.strip()


async def trim_and_collapse(ctx) -> str:
    """Trim, and collapse every run of internal whitespace to one space."""
    return " ".join(ctx.inputs.split())


async def compose_greeting(ctx) -> str:
    return f"Hello, {ctx.inputs}!"


# ── 3. two strategies over the one design ───────────────────────────────────────────────────
#
# `compose` is bound to the SAME function object in both, so it is shared rather than varying —
# which is what `varies()` and `diff_diagram()` report.

trim_only = StrategySpec("trim_only", {normalize: trim, compose: compose_greeting})
normalize_spaces = StrategySpec("normalize_spaces",
                                {normalize: trim_and_collapse, compose: compose_greeting})


# ── 4. the cases, and exact matching against the expected greeting ──────────────────────────

CASES: tuple[tuple[str, str, str], ...] = (
    ("padded", "  Ada Lovelace  ", "Hello, Ada Lovelace!"),
    ("inner_run", "Ada   Lovelace", "Hello, Ada Lovelace!"),
    ("both", "  Grace   Hopper  ", "Hello, Grace Hopper!"),
    ("already_clean", "Alan Turing", "Hello, Alan Turing!"),
)


def dataset():
    """Built lazily so the module imports without pydantic-evals installed."""
    from pydantic_evals import Case, Dataset
    from pydantic_evals.evaluators import Evaluator, EvaluatorContext

    class ExactMatch(Evaluator):
        """A score, not an assertion — `BattleResult.deltas()` reads aggregate SCORES."""

        def evaluate(self, ctx: EvaluatorContext) -> float:
            return 1.0 if ctx.output == ctx.expected_output else 0.0

    return Dataset(
        name="greetings",
        cases=[Case(name=n, inputs=i, expected_output=o) for n, i, o in CASES],
        evaluators=[ExactMatch()],
    )


# ── the walkthrough ─────────────────────────────────────────────────────────────────────────

def main() -> None:
    spec = Greeting()

    print("1. coherence_check() with nothing implemented:", spec.coherence_check() or "clean")
    print("\n2. the specification, drawn from the declaration:")
    print(spec.diagram())

    print("\n3. what varies between the two strategies:", spec.varies(trim_only, normalize_spaces))
    print("\n   the comparison diagram:")
    print(spec.diff_diagram(trim_only, normalize_spaces))

    print("\n4. an incomplete strategy — `compose` left unbound:")
    unfinished = StrategySpec("unfinished", {normalize: trim_and_collapse})
    for finding in spec.coherence_check(unfinished):
        print(f"   check finding: {finding}")
    try:
        spec.render(unfinished)
    except SpecError as exc:
        print(f"   render refused: {str(exc).splitlines()[-1].strip()}")

    print("\n5. both strategies, on the same cases:")
    graphs = {s.name: spec.render(s) for s in (trim_only, normalize_spaces)}
    print(f"   {'case':<14} {'input':<22} {'trim_only':<26} normalize_spaces")
    for name, text, _expected in CASES:
        outs = [graphs[s.name].run_sync(inputs=text)
                for s in (trim_only, normalize_spaces)]
        print(f"   {name:<14} {text!r:<22} {outs[0]!r:<26} {outs[1]!r}")

    print("\n6. the battle — same cases, same evaluator, scored:")
    from workflow_workbench.evals import eval_battle

    data = dataset()
    floor = eval_battle(spec, trim_only, trim_only, data)
    battle = eval_battle(spec, trim_only, normalize_spaces, data)
    print(f"   noise floor (same strategy twice): {floor.per_case_spread()}")
    print(f"   trim_only        {_score(battle.report_a):.2f}")
    print(f"   normalize_spaces {_score(battle.report_b):.2f}")
    print(f"   delta            {battle.deltas()}")


def _score(report) -> float:
    """The one aggregate score. `scores` values may be a float or a wrapper — take either."""
    v = next(iter(report.averages().scores.values()))
    return float(getattr(v, "value", v))


if __name__ == "__main__":
    main()
