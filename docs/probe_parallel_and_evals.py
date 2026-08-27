"""Probe 2: a REAL working map+join fan-out, and the pydantic_evals surface evals.py sits on.

Same discipline as probe_api.py — nothing here is inferred from docs.
"""
from __future__ import annotations

import inspect
import sys

from pydantic_graph import GraphBuilder

results: list[tuple[str, bool, str]] = []


def probe(name: str):
    def deco(fn):
        try:
            results.append((name, True, fn() or ""))
        except Exception as exc:  # noqa: BLE001
            results.append((name, False, f"{type(exc).__name__}: {exc}"))
        return fn
    return deco


@probe("A. signatures of join / step / edge.map")
def _a():
    g = GraphBuilder(name="sig", state_type=type(None), input_type=list[int], output_type=int)
    out = [f"join{inspect.signature(g.join)}", f"step{inspect.signature(g.step)}"]
    eb = g.edge_from(g.start_node)
    out.append(f"edge.map{inspect.signature(eb.map)}")
    out.append(f"edge.to{inspect.signature(eb.to)}")
    return "\n        ".join(out)


@probe("B. a real fan-out + collect RUNS and returns the right answer")
def _b():
    g = GraphBuilder(name="parallel", state_type=type(None),
                     input_type=list[int], output_type=int)

    async def square(ctx) -> int:
        return ctx.inputs * ctx.inputs

    # ⚠️ A reducer is an ACCUMULATOR `(current, input) -> current`, not a plain aggregate.
    # `g.join(sum)` raises "'Unset' object is not iterable" — verified. It needs `initial=`.
    from pydantic_graph.join import reduce_sum

    sq = g.step(square, node_id="square")
    total = g.join(reduce_sum, initial=0, node_id="total")
    g.add(
        g.edge_from(g.start_node).map().to(sq),   # fan out over the input list
        g.edge_from(sq).to(total),                # collect
        g.edge_from(total).to(g.end_node),
    )
    graph = g.build()
    res = graph.run_sync(inputs=[1, 2, 3, 4])
    got = getattr(res, "output", res)
    assert got == 30, f"expected 30, got {got!r}"
    return f"nodes={sorted(graph.nodes)}  run_sync([1,2,3,4]) -> {got}"


@probe("C. Graph.render() mermaid — the format diagram.py must match")
def _c():
    g = GraphBuilder(name="mm", state_type=type(None), input_type=int, output_type=int)

    async def a(ctx) -> int:
        return 1
    n = g.step(a, node_id="alpha", label="alpha")
    g.add(g.edge_from(g.start_node).to(n), g.edge_from(n).to(g.end_node))
    txt = g.build().render()
    return repr(txt[:220])


@probe("D. pydantic_evals: imports, Dataset/Case construction, evaluate_sync")
def _d():
    from pydantic_evals import Case, Dataset
    from pydantic_evals.evaluators import Evaluator, EvaluatorContext

    class Length(Evaluator[str, str]):
        def evaluate(self, ctx: EvaluatorContext[str, str]) -> float:
            return float(len(ctx.output))

    ds = Dataset(name="probe", cases=[Case(name="c1", inputs="ab"), Case(name="c2", inputs="abcd")],
                 evaluators=[Length()])

    def task(s: str) -> str:
        return s + "!"

    rep = ds.evaluate_sync(task, name="arm_a")
    avg = rep.averages()
    return (f"report={type(rep).__name__} cases={len(rep.cases)} failures={len(rep.failures)} "
            f"averages.scores={getattr(avg, 'scores', None)}")


@probe("E. EvaluationReport baseline diffing exists")
def _e():
    from pydantic_evals import Case, Dataset
    from pydantic_evals.evaluators import Evaluator, EvaluatorContext

    class Length(Evaluator[str, str]):
        def evaluate(self, ctx: EvaluatorContext[str, str]) -> float:
            return float(len(ctx.output))

    ds = Dataset(name="probe", cases=[Case(name="c1", inputs="ab")], evaluators=[Length()])
    a = ds.evaluate_sync(lambda s: s + "!", name="a")
    b = ds.evaluate_sync(lambda s: s + "!!", name="b")
    has = [m for m in ("print", "console_table") if hasattr(b, m)]
    sig = str(inspect.signature(b.console_table)) if hasattr(b, "console_table") else "-"
    accepts_baseline = "baseline" in sig
    assert accepts_baseline, f"no baseline= in console_table{sig}"
    return f"methods={has}; console_table accepts baseline=  ✔"


@probe("F. per-CASE scores are reachable (needed for a non-cancelling noise floor)")
def _f():
    from pydantic_evals import Case, Dataset
    from pydantic_evals.evaluators import Evaluator, EvaluatorContext

    class Len(Evaluator[str, str]):
        def evaluate(self, ctx: EvaluatorContext[str, str]) -> float:
            return float(len(ctx.output))

    ds = Dataset(name="p", cases=[Case(name="c1", inputs="a"), Case(name="c2", inputs="bb")],
                 evaluators=[Len()])
    rep = ds.evaluate_sync(lambda s: s, name="x")
    per_case = {c.name: {k: v.value for k, v in c.scores.items()} for c in rep.cases}
    assert per_case, "no per-case scores"
    return f"{per_case}"


@probe("G. does pydantic_evals have ANY head-to-head/pairwise evaluator?")
def _g():
    import pydantic_evals.evaluators as ev
    names = [n for n in dir(ev) if not n.startswith("_")]
    pairwise = [n for n in names if any(w in n.lower()
                                        for w in ("pair", "compare", "versus", "battle", "head"))]
    from pydantic_evals.evaluators import EvaluatorContext
    fields = [f for f in getattr(EvaluatorContext, "__dataclass_fields__", {})]
    return (f"exports={sorted(names)}\n        pairwise-looking={pairwise or 'NONE'}\n"
            f"        EvaluatorContext fields={fields}")


for name, ok, note in results:
    print(f"{'PASS' if ok else 'FAIL'}  {name}")
    if note:
        print(f"        {note}")
failed = [n for n, ok, _ in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
