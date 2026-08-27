"""`eval_battle` — run two strategies of one design over the same cases and compare them.

Built ON pydantic-evals, not beside it. `Case`, `Dataset`, `Evaluator`, `LLMJudge` and
`EvaluationReport` are imported and used directly; there is no `EvalCase`, no `EvalSuite`, no
`Grader`, no `EvalReport`, no `EvalHarness`.

## The two modes, which are genuinely different questions

    independent   each arm scored alone against a fixed rubric, then the NUMBERS are diffed.
                  "did the average move?"   -> pydantic-evals owns this entirely
                  (`EvaluationReport.console_table(baseline=...)`, verified)

    pairwise      one judge sees BOTH outputs for the same case, side by side, and picks a winner.
                  "which one is better?"    -> pydantic-evals has nothing for this

Verified rather than assumed: `pydantic_evals.evaluators` exports no pairwise/comparison evaluator
of any kind, and `EvaluatorContext` carries exactly one `output`. So mode 2 needs an adapter, and
it is the only thing here that is not a thin call into the library.
"""
from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from workflow_spec.graph_spec import GraphSpec
from workflow_spec.spec import SpecError, StrategySpec

__all__ = ["eval_battle", "compare_graphs", "BattleResult", "PairwiseVerdict", "pairwise_battle"]


@dataclass
class BattleResult:
    """Both arms' native reports, plus what our layer adds: the labels and the fairness fact.

    Deliberately NOT a re-implementation of `EvaluationReport` — it HOLDS two of them. The handoff's
    stop condition: prefer returning a small result containing native reports over copying
    pydantic's report implementation.
    """

    spec_name: str
    label_a: str
    label_b: str
    report_a: Any
    report_b: Any
    is_replicate: bool = False
    """Both arms ran the SAME strategy object. Then every difference below is noise, and that is
    the number to hold every real comparison against."""

    def print(self, **kw: Any) -> None:
        """pydantic-evals' own diff — `report_b` against `report_a` as baseline. Not ours."""
        self.report_b.print(baseline=self.report_a, **kw)

    def deltas(self) -> dict[str, float]:
        """Per-metric `b - a` on the aggregate scores."""
        a = _avg_scores(self.report_a)
        b = _avg_scores(self.report_b)
        return {k: b[k] - a[k] for k in sorted(set(a) & set(b))}

    def per_case_spread(self) -> dict[str, float]:
        """Largest per-case absolute difference, per metric.

        ⛔ NOT the difference of the averages. On a replicate whose per-case scores moved +1 and
        −1, the averages are identical and a difference-of-averages reports a noise floor of 0.0 —
        licensing noise as a result, which is the exact failure this layer exists to prevent. Take
        the spread per case, then the max.
        """
        a, b = _per_case_scores(self.report_a), _per_case_scores(self.report_b)
        out: dict[str, float] = {}
        for case in sorted(set(a) & set(b)):
            for metric in set(a[case]) & set(b[case]):
                d = abs(a[case][metric] - b[case][metric])
                out[metric] = max(out.get(metric, 0.0), d)
        return out

    def __repr__(self) -> str:
        kind = "REPLICATE" if self.is_replicate else "battle"
        return f"BattleResult({kind} {self.label_a!r} vs {self.label_b!r} on {self.spec_name!r})"


def _avg_scores(report: Any) -> dict[str, float]:
    avg = report.averages()
    if avg is None:                       # every case failed — no scores to average
        return {}
    return {k: float(getattr(v, "value", v)) for k, v in (avg.scores or {}).items()}


def _per_case_scores(report: Any) -> dict[str, dict[str, float]]:
    return {c.name: {k: float(getattr(v, "value", v)) for k, v in (c.scores or {}).items()}
            for c in report.cases}


def eval_battle(spec: GraphSpec, strategy_a: StrategySpec, strategy_b: StrategySpec,
                dataset: Any, *, run: Callable[[Any, Any], Any] | None = None) -> BattleResult:
    """Two strategies, one design, the same cases. Independent-scoring mode.

    ⚠️ Fairness is structural, not remembered: there is exactly ONE `spec` parameter, so both arms
    render against the same nodes, edges and types by construction. A caller cannot accidentally
    compare arms of two different designs, because there is nowhere to put the second design.

    `run(graph, inputs)` adapts a rendered graph to a pydantic-evals task callable. The default
    calls `graph.run_sync(inputs=...)` and returns `.output`; pass your own when a design needs
    state or deps.
    """
    if strategy_a is strategy_b:
        # Legal and useful — this is how you measure the noise floor — but it must be LABELLED,
        # never silently reported as though two different things were compared.
        pass
    for s in (strategy_a, strategy_b):
        findings = [f for f in spec.check(s) if not f.startswith("NOT CHECKED")]
        if findings:
            raise SpecError(f"strategy {s.name!r} does not satisfy "
                            f"{spec.name or type(spec).__name__}:\n  " + "\n  ".join(findings))

    graph_a = spec.render(strategy_a)
    graph_b = spec.render(strategy_b)
    return compare_graphs(graph_a, graph_b, dataset,
                          labels=(strategy_a.name, strategy_b.name),
                          spec_name=spec.name or type(spec).__name__,
                          is_replicate=strategy_a is strategy_b, run=run)


def _default_run(graph: Any, inputs: Any) -> Any:
    res = graph.run_sync(inputs=inputs)
    return getattr(res, "output", res)


def compare_graphs(graph_a: Any, graph_b: Any, dataset: Any, *, labels: tuple[str, str],
                   spec_name: str = "", is_replicate: bool = False,
                   run: Callable[[Any, Any], Any] | None = None) -> BattleResult:
    """The lower-level primitive: two ALREADY-BUILT graphs.

    ⚠️ No fairness guarantee. A built `Graph` retains no trace of the design or strategy behind it,
    so nothing here can verify the two are comparable — the caller is asserting it. Use
    `eval_battle` unless you have graphs from somewhere else and accept that trade explicitly.
    """
    runner = run or _default_run
    # ⚠️ `name=` per arm. Without it pydantic-evals labels the progress bar and the report from the
    # task callable's `__name__` — and a replicate runs the SAME callable twice, so both arms would
    # print under one name and be indistinguishable in the output.
    report_a = dataset.evaluate_sync(lambda i: runner(graph_a, i), name=labels[0])
    report_b = dataset.evaluate_sync(lambda i: runner(graph_b, i), name=labels[1])
    return BattleResult(spec_name=spec_name, label_a=labels[0], label_b=labels[1],
                        report_a=report_a, report_b=report_b, is_replicate=is_replicate)


# ── mode 2: genuine pairwise judging ────────────────────────────────────────────────────────────

@dataclass
class PairwiseVerdict:
    """One case, both outputs, one judge's answer."""

    case: str
    winner: str                  # label_a, label_b, or "tie"
    reason: str = ""
    shown_first: str = ""
    """Which arm the judge saw first. Recorded because position bias is real: a judge that always
    prefers the first candidate produces a clean, confident, meaningless sweep."""


@dataclass
class PairwiseResult:
    label_a: str
    label_b: str
    verdicts: list[PairwiseVerdict] = field(default_factory=list)

    def tally(self) -> dict[str, int]:
        out = {self.label_a: 0, self.label_b: 0, "tie": 0}
        for v in self.verdicts:
            out[v.winner] = out.get(v.winner, 0) + 1
        return out

    def position_bias(self) -> dict[str, int]:
        """How often the arm shown FIRST won. Near-total agreement with position is the tell that
        the judge is reading order rather than quality."""
        first_wins = sum(1 for v in self.verdicts if v.winner == v.shown_first)
        return {"first_shown_won": first_wins, "total_decided": sum(
            1 for v in self.verdicts if v.winner != "tie")}


def pairwise_battle(spec: GraphSpec, strategy_a: StrategySpec, strategy_b: StrategySpec,
                    cases: Sequence[Any], *, judge: Callable[[Any, Any, Any], tuple[str, str]],
                    run: Callable[[Any, Any], Any] | None = None,
                    seed: int | None = 0) -> PairwiseResult:
    """Run both arms per case and hand BOTH outputs to one judge, which picks a winner.

    `judge(inputs, first_output, second_output) -> (winner, reason)` where winner is `"first"`,
    `"second"` or `"tie"`. It never learns which arm is which — that is the point.

    ⚠️ A/B order is SHUFFLED per case, seeded for reproducibility. Position bias is a documented
    LLM-judge failure mode; presenting A first every time produces a result that is partly a
    measurement of the judge's preference for the top of the prompt.
    """
    runner = run or _default_run
    rng = random.Random(seed)
    graph_a, graph_b = spec.render(strategy_a), spec.render(strategy_b)
    result = PairwiseResult(label_a=strategy_a.name, label_b=strategy_b.name)

    for case in cases:
        inputs = getattr(case, "inputs", case)
        name = getattr(case, "name", str(inputs)[:40])
        out_a, out_b = runner(graph_a, inputs), runner(graph_b, inputs)
        a_first = rng.random() < 0.5
        first, second = (out_a, out_b) if a_first else (out_b, out_a)
        first_label = strategy_a.name if a_first else strategy_b.name
        second_label = strategy_b.name if a_first else strategy_a.name
        pick, reason = judge(inputs, first, second)
        winner = {"first": first_label, "second": second_label}.get(pick, "tie")
        result.verdicts.append(PairwiseVerdict(case=name, winner=winner, reason=reason,
                                               shown_first=first_label))
    return result
