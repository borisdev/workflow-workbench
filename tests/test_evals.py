"""Eval-layer tests, against a REAL `pydantic_evals.Dataset` — no mocks of the library."""
from __future__ import annotations

import pytest

from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext

from workflow_workbench import END, START, EdgeSpec, GraphSpec, NodeSpec, StrategySpec, VariableSpec
from workflow_workbench.evals import BattleResult, eval_battle, pairwise_battle

text = VariableSpec("text", str)
work = NodeSpec("work", inputs=(text,), outputs=(text,))


class Job(GraphSpec):
    name = "job"
    input_type, output_type = str, str
    nodes = (work,)
    edges = (EdgeSpec(START, work, text), EdgeSpec(work, END, text))


async def shout(ctx) -> str:
    return ctx.inputs.upper()


async def pad(ctx) -> str:
    return ctx.inputs + "!!!"


loud = StrategySpec("loud", {work: shout})
padded = StrategySpec("padded", {work: pad})


class Length(Evaluator[str, str]):
    def evaluate(self, ctx: EvaluatorContext[str, str]) -> float:
        return float(len(ctx.output))


def dataset() -> Dataset:
    return Dataset(name="t", evaluators=[Length()],
                   cases=[Case(name="c1", inputs="ab"), Case(name="c2", inputs="cdef")])


def test_battle_runs_both_arms_on_the_same_cases():
    res = eval_battle(Job(), loud, padded, dataset())
    assert isinstance(res, BattleResult)
    assert res.label_a == "loud" and res.label_b == "padded"
    assert len(res.report_a.cases) == len(res.report_b.cases) == 2
    assert [c.name for c in res.report_a.cases] == [c.name for c in res.report_b.cases]


def test_battle_returns_native_reports_not_a_copy():
    """The stop condition: reuse pydantic-evals' own report type rather than re-implement it."""
    from pydantic_evals.reporting import EvaluationReport
    res = eval_battle(Job(), loud, padded, dataset())
    assert isinstance(res.report_a, EvaluationReport)
    assert isinstance(res.report_b, EvaluationReport)


def test_labels_survive_into_the_report():
    res = eval_battle(Job(), loud, padded, dataset())
    assert res.report_a.name == "loud"
    assert res.report_b.name == "padded"


def test_deltas_are_computed_per_metric():
    res = eval_battle(Job(), loud, padded, dataset())
    # loud preserves length; padded adds 3 chars per case.
    assert res.deltas()["Length"] == pytest.approx(3.0)


def test_a_replicate_is_detected_and_labelled():
    res = eval_battle(Job(), loud, loud, dataset())
    assert res.is_replicate
    assert "REPLICATE" in repr(res)


def test_replicate_of_a_deterministic_strategy_has_a_zero_floor():
    res = eval_battle(Job(), loud, loud, dataset())
    assert res.deltas()["Length"] == 0.0
    assert res.per_case_spread()["Length"] == 0.0


def test_per_case_spread_does_not_cancel_where_averages_do():
    """⛔ THE REGRESSION FOR THE NOISE-FLOOR BUG.

    Two cases drift +1 and −1. The AVERAGES are identical, so a difference-of-averages reports a
    floor of 0.0 — and a real +0.5 gain elsewhere would then read as signal. The per-case spread
    reports 1.0, which is the honest bar.
    """
    a = _fake_report({"c1": 5.0, "c2": 5.0})
    b = _fake_report({"c1": 6.0, "c2": 4.0})
    res = BattleResult("s", "a", "b", a, b, is_replicate=True)

    assert res.deltas()["m"] == 0.0            # the averages agree — the trap
    assert res.per_case_spread()["m"] == 1.0   # the drift is real and reported


def test_battle_refuses_a_strategy_that_does_not_satisfy_the_spec():
    from workflow_workbench import SpecError
    with pytest.raises(SpecError):
        eval_battle(Job(), loud, StrategySpec("empty", {}), dataset())


def test_one_spec_argument_makes_cross_design_comparison_unexpressible():
    """Fairness is structural: `eval_battle` has exactly one `spec` parameter, so there is
    nowhere to put a second design."""
    import inspect
    params = list(inspect.signature(eval_battle).parameters)
    assert params[0] == "spec"
    assert sum(1 for p in params if "spec" in p) == 1


# ── pairwise mode ───────────────────────────────────────────────────────────────────────────

def test_pairwise_judge_never_sees_which_arm_is_which_and_order_is_shuffled():
    seen_first: list[str] = []

    def judge(inputs, first, second):
        seen_first.append(first)
        return ("first", "picked the first one")     # a deliberately position-biased judge

    cases = [Case(name=f"c{i}", inputs="x" * i) for i in range(1, 9)]
    res = pairwise_battle(Job(), loud, padded, cases, judge=judge, seed=0)

    assert len(res.verdicts) == 8
    # Order really varied — both arms appeared first at least once.
    assert len({v.shown_first for v in res.verdicts}) == 2
    # And the bias is measurable, which is the point of recording `shown_first`.
    bias = res.position_bias()
    assert bias["first_shown_won"] == bias["total_decided"] == 8


def test_pairwise_tally_counts_winners():
    def judge(inputs, first, second):
        return ("second", "")

    cases = [Case(name="c1", inputs="ab")]
    res = pairwise_battle(Job(), loud, padded, cases, judge=judge, seed=1)
    assert sum(res.tally().values()) == 1


def test_pairwise_is_reproducible_under_a_seed():
    def judge(inputs, first, second):
        return ("tie", "")

    cases = [Case(name=f"c{i}", inputs="x") for i in range(6)]
    a = pairwise_battle(Job(), loud, padded, cases, judge=judge, seed=7)
    b = pairwise_battle(Job(), loud, padded, cases, judge=judge, seed=7)
    assert [v.shown_first for v in a.verdicts] == [v.shown_first for v in b.verdicts]


# ── helpers ─────────────────────────────────────────────────────────────────────────────────

class _Score:
    def __init__(self, value: float):
        self.value = value


class _Case:
    def __init__(self, name: str, scores: dict[str, float]):
        self.name = name
        self.scores = {k: _Score(v) for k, v in scores.items()}


class _Report:
    """Minimal stand-in for an EvaluationReport, used ONLY where the arithmetic is under test and
    running two real graphs would add nothing. Every other test here uses the real library."""

    def __init__(self, per_case: dict[str, float]):
        self.cases = [_Case(n, {"m": v}) for n, v in per_case.items()]
        self._avg = sum(per_case.values()) / len(per_case)

    def averages(self):
        return type("A", (), {"scores": {"m": _Score(self._avg)}})()


def _fake_report(per_case: dict[str, float]) -> _Report:
    return _Report(per_case)
