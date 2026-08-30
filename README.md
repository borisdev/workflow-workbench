# workflow-workbench

Define one Pydantic graph design, bind competing strategies, then check, diagram, and evaluate
them fairly.

Built on [Pydantic Graph](https://ai.pydantic.dev/graph/) and
[Pydantic Evals](https://ai.pydantic.dev/evals/). Independent; not affiliated with Pydantic.

A workbench, not a designer: **you author in Python, and this is where you look at what you
wrote.** Nothing here edits a graph — the view is read-only, by construction. It accommodates the
design, the checks, the visualization, the strategy comparison and the eval battles in one place.

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

## The ladder — start with what you already have

Every rung is a variation of an example from
[Pydantic Graph's builder docs](https://pydantic.dev/docs/ai/graph/builder/), a module in
`examples/ladder/`, and a test in `tests/test_ladder.py`. Read them in order; each adds exactly
one capability.

**Rung 0 is Pydantic Graph alone, and it is fine.** This is their `visualize_graph.py` shape —
two steps, the second formatting the first's output:

```python
g = GraphBuilder(state_type=Guest, input_type=str, output_type=str)

@g.step
async def pick(ctx: StepContext[Guest, None, str]) -> str:
    ctx.state.name = ctx.inputs
    return "Hello"

@g.step
async def compose(ctx: StepContext[Guest, None, str]) -> str:
    return f"{ctx.inputs}, {ctx.state.name}!"

g.add(g.edge_from(g.start_node).to(pick),
      g.edge_from(pick).to(compose),
      g.edge_from(compose).to(g.end_node))
```

The same thing declared, on rung 1. The topology stops being calls and becomes data:

```python
salutation = VariableSpec("salutation", str)
greeting   = VariableSpec("greeting", str)

pick    = NodeSpec("pick", outputs=(salutation,))
compose = NodeSpec("compose", inputs=(salutation,), outputs=(greeting,))

class HelloWorld(GraphSpec):
    name = "hello_world"
    state_type = Guest
    input_type, output_type = str, str
    nodes = (pick, compose)
    edges = (EdgeSpec(START, pick),
             EdgeSpec(pick, compose, salutation),
             EdgeSpec(compose, END, greeting))
```

Both print `'Hello, Ada!'` and both have the node ids `pick`, `compose`. **On this rung that is a
lateral move** — more code, same result — and the README will not pretend otherwise. It starts
paying on rung 2, when `pick` has two implementations and something has to hold them to one shape.

| rung | adds | source |
|---|---|---|
| 0 | nothing — Pydantic Graph alone, the control | [`their_hello.py`](examples/ladder/their_hello.py) |
| 1 | the design as data; `check()` and `diagram()` with nothing implemented | [`stage1_bare.py`](examples/ladder/stage1_bare.py) |
| 2 | **two strategies over one design**, with identical node ids | [`stage2_strategies.py`](examples/ladder/stage2_strategies.py) |
| 3 | a new node — and a strategy that predates it is refused | [`stage3_new_node.py`](examples/ladder/stage3_new_node.py) |
| 4 | one node implemented by a **whole child design** | [`stage4_subgraph.py`](examples/ladder/stage4_subgraph.py) |
| 5 | a **battle** — both arms scored on the same cases, against a noise floor | [`stage5_battle.py`](examples/ladder/stage5_battle.py) |
| 6 | the **diff diagram** neither library can draw | [`stage6_diagrams.py`](examples/ladder/stage6_diagrams.py) |
| 7 | proof it is a real `Graph` — their `iter()` drives it unchanged | [`stage7_iter.py`](examples/ladder/stage7_iter.py) |
| 8 | **a declared join** — two producers into one consumer, combined rather than dropped | [`stage8_join.py`](examples/ladder/stage8_join.py) |
| 9 | **conditional routing** — branches on the type of the answer, converging again | [`stage9_decision.py`](examples/ladder/stage9_decision.py) |
| 10 | **wire it by hand and stay checked** — the declaration becomes a claim verified against the built graph | [`stage10_hand_wired.py`](examples/ladder/stage10_hand_wired.py) |

```bash
uv run python3 -m examples.ladder.stage2_strategies    # any rung
uv run pytest tests/test_ladder.py -q                  # all of them, asserted
```

## Intent, implementation, execution

| Layer | Question |
|---|---|
| Problem | What outcome is needed? |
| Specification | What must a valid workflow contain and guarantee? |
| Implementation | How does each node fulfil its role? |
| Execution | How does Pydantic Graph run it? |

`GraphSpec` is the inspectable design. `StrategySpec` binds it to native Pydantic Graph step
implementations. Execution stays Pydantic Graph's.

## One node role, a step or a whole subgraph

A `NodeSpec` keeps a role's identity and typed boundary stable. A strategy fills it with one
callable:

```python
better = StrategySpec("better", {extract: better_extract})
```

…or with a complete child design:

```python
fancy = StrategySpec("fancy", {extract: SubgraphBinding(VerifiedExtraction(), verified)})
```

The child must match the node's input/output contract and share the parent's exact `state_type`
and `deps_type` — it runs on the parent's actual objects. It stays independently runnable and
checkable, and the parent keeps **one** node id either way, which is what a battle aligns on.
Where a node is wired straight to `START`/`END` and declares no variable, the graph's own
`input_type`/`output_type` is what the child is checked against.

See [`examples/subgraph.py`](examples/subgraph.py) for the `naive` / `better` / `fancy` comparison.

## Do not use this library if…

- you have **one** graph with one implementation per node → use **Pydantic Graph** directly
- you only need to evaluate **one** callable → use **Pydantic Evals** directly

Use this only when several strategies must satisfy the same graph structure and typed contracts
before being compared.

## What the declaration can express — enumerated, not remembered

`docs/probe_builder_features.py` runs every `GraphBuilder` feature and then asks which a
`GraphSpec` can declare as DATA, which is the only form `check()` and `diagram()` can read.

`docs/probe_builder_features.py` runs every `GraphBuilder` feature, then asks which a `GraphSpec`
can declare as DATA — the only form `check()` and `diagram()` can read.

| `GraphBuilder` | declarable | as |
|---|---|---|
| `step` | **yes** | `NodeSpec` |
| `join` | **yes** | `JoinSpec` in `joins` |
| `decision` | **yes** | `DecisionSpec` in `decisions` |
| `add` / `add_edge` | **yes** | `EdgeSpec` |
| `match` | partial | the type form is `when=T`; the `matches=` **predicate** form is not |
| `edge_from` | partial | one source per edge; `edge_from(a, b)` as one call is not |
| `stream` | no | a streaming step body; `NodeSpec` assumes `(ctx) -> Out` |
| `node` | no | the `BaseNode` class-based authoring API — an alternative to `step` entirely |
| `match_node` | no | branch on a `BaseNode` subclass |
| `add_mapping_edge` | no | fan-out |

…plus the edge builder: `label` yes, `to` partial (multi-destination is a fork), and `map`,
`transform`, `broadcast` no.

**6 fully declarable, 2 partial, 4 escape-hatch only.** Everything not declarable runs *only*
through `build_pydantic_structure()`.

⛔ That used to be the end of the story, and it was the expensive part: an override made `edges`
decorative and reported reachability as `NOT CHECKED` for the **whole design**. Since
`built.check_built_topology`, `render()` walks the **built** graph — so an override now costs only
the ability to check *before the implementations exist*, and the `edges` declaration became a
claim that is verified against what was actually compiled. A hand-wired design that skips,
reorders or drops a declared node is refused.

⛔ **The matrix is checked against the real API, not maintained by hand.** An earlier version was
written from a grep and missed five entries — `stream`, `node`, `match_node`, `add_mapping_edge`,
and `match(matches=...)` — while reading as a complete inventory of the gaps. The probe now
introspects `GraphBuilder` and fails if any public method is unclassified, so the next thing
Pydantic Graph ships turns it red instead of silently widening a gap we describe as closed.

⚠️ `JoinSpec` and `DecisionSpec` live in `joins` and `decisions`, never in `nodes`. Neither has an
implementation, so a strategy binds nothing for them — which keeps *"a node is a role a strategy
fills"* true of every element of `nodes`, and guarantees two arms of a branching design route
identically.

## What it owns, and what it does not

This library owns the design — `GraphSpec`, `NodeSpec`, `EdgeSpec`, `VariableSpec`,
`StrategySpec` — plus the checks, the strategy diagrams, and `eval_battle`.

Pydantic Evals owns `Case`, `Dataset`, `Evaluator`, `LLMJudge` and `EvaluationReport`; they are
imported and used directly. There is no `EvalCase`, no `EvalSuite`, no `Grader`, no `EvalReport`,
no `EvalHarness`.

It is a **strategy layer over Pydantic Graph**, not a new general workflow framework.

## The three things it adds

Most workflow tools show one executable route. This one keeps the design fixed and shows which
implementation choices vary between competing routes.

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

`workflow_workbench.serve` is a stateless viewer: POST a report, GET a page. It renders with React
Flow, or `?plain=1` for a self-contained page with no bundle at all.

```bash
export WORKFLOW_WORKBENCH_TOKEN=$(python3 -c 'import secrets;print(secrets.token_urlsafe(24))')
python3 -m workflow_workbench.cli serve --host 0.0.0.0 --port 8800
```

⚠️ The renderer depends on the **schema** (`workflow_workbench/payload.py`, which imports only
pydantic) and never on the **engine**. Hosting the viewer does not require pydantic-graph, so a
report can be displayed somewhere that cannot build graphs.

## Verify it rather than believe it

```bash
uv run pytest -q
uv run python3 docs/probe_api.py                  # every claim above, against the real library
uv run python3 docs/probe_parallel_and_evals.py
uv run python3 docs/probe_builder_features.py     # what the declaration can and cannot express
uv run python3 examples/counter.py
uv run python3 examples/parallel.py
uv run python3 examples/subgraph.py
uv run pytest tests/test_ladder.py -q              # the README's ladder, every rung
uv run python3 examples/local/extraction.py
```

The browser tests run the page in Chromium at a phone viewport. They are non-vacuous by
construction: one unbalanced brace in the renderer turns 12 of 13 red, and a corrupt island bundle
turns 13 of 14 red while the `?plain=1` fallback keeps passing.

## Related Pydantic Graph discussions

A downstream design related to community requests for
[reusable/extensible nodes](https://github.com/pydantic/pydantic-ai/issues/798) and
[reusable subgraphs](https://github.com/pydantic/pydantic-ai/issues/3901). It is a complementary
layer over native Pydantic Graph, not a proposal to change it.
