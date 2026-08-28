# pydantic-graph-strategies

Define one Pydantic graph design, bind competing strategies, then check, diagram, and evaluate
them fairly.

> An independent third-party library built on [Pydantic Graph](https://ai.pydantic.dev/graph/).
> Not affiliated with or endorsed by Pydantic.

```python
class Counter(GraphSpec):
    name = "counter"
    state_type, input_type, output_type = CounterState, int, int
    nodes = (increment, double_it)
    edges = (EdgeSpec(START, increment),
             EdgeSpec(increment, double_it, count),
             EdgeSpec(double_it, END, count))

modest     = StrategySpec("modest",     {increment: add_one,  double_it: times_two})
aggressive = StrategySpec("aggressive", {increment: add_ten,  double_it: times_three})

Counter().check()                        # no strategy, no implementations, no engine needed
graph = Counter().render(modest)         # a real pydantic_graph.Graph
eval_battle(Counter(), modest, aggressive, dataset)
```

## Do not use this library if…

- you have **one** graph with one implementation per node → use **Pydantic Graph** directly
- you only need to evaluate **one** callable → use **Pydantic Evals** directly

Use this only when several strategies must satisfy the same graph structure and typed contracts
before being compared.

## What it owns, and what it does not

This library owns the design — `GraphSpec`, `NodeSpec`, `EdgeSpec`, `VariableSpec`,
`StrategySpec` — plus the checks, the strategy diagrams, and `eval_battle`.

Pydantic Evals owns `Case`, `Dataset`, `Evaluator`, `LLMJudge` and `EvaluationReport`; they are
imported and used directly. There is no `EvalCase`, no `EvalSuite`, no `Grader`, no `EvalReport`,
no `EvalHarness`.

It is a **strategy layer over Pydantic Graph**, not a new general workflow framework.

## The three things it adds

**1. Node identity belongs to the DESIGN, not the implementation.** Without an explicit `node_id`,
pydantic-graph names a node after the bound function — so two arms of one design get disjoint node
sets and a comparison has nothing to align on. Measured both ways in `docs/probe_api.py`.

**2. A per-edge variable check.** A node with two outputs of the same type can have its two
outgoing edges swapped. Every set matches — produced == consumed — and the wiring is wrong. Only a
per-edge check sees it; the test proves the set comparison agrees with the bug.

**3. A diagram of what VARIES between two strategies.** Two arms of one design render
byte-identical mermaid from `Graph.render()`, because a built graph retains no trace of the
strategy that produced it. `diff_diagram()` reads the declaration instead.

## Viewing a report

`graph_strategies.serve` is a stateless viewer: POST a report, GET a page. It renders with React
Flow, or `?plain=1` for a self-contained page with no bundle at all.

```bash
export GRAPH_STRATEGIES_TOKEN=$(python3 -c 'import secrets;print(secrets.token_urlsafe(24))')
python3 -m graph_strategies.cli serve --host 0.0.0.0 --port 8800
```

⚠️ The renderer depends on the **schema** (`graph_strategies/payload.py`, which imports only
pydantic) and never on the **engine**. Hosting the viewer does not require pydantic-graph, so a
report can be displayed somewhere that cannot build graphs.

## Verify it rather than believe it

```bash
uv run pytest -q
uv run python3 docs/probe_api.py                  # every claim above, against the real library
uv run python3 docs/probe_parallel_and_evals.py
uv run python3 examples/counter.py
uv run python3 examples/parallel.py
uv run python3 examples/local/extraction.py
```

The browser tests run the page in Chromium at a phone viewport. They are non-vacuous by
construction: one unbalanced brace in the renderer turns 12 of 13 red, and a corrupt island bundle
turns 13 of 14 red while the `?plain=1` fallback keeps passing.
