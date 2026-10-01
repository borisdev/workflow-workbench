# The ladder — eleven rungs, each adding exactly one capability

Moved out of the README so the README can stay a walkthrough. Start with
[the greeting example](../examples/greeting.py) if you have not run anything yet; come here when
you need a capability it does not show.

Every rung is a variation of an example from
[Pydantic Graph's builder docs](https://pydantic.dev/docs/ai/graph/builder/), a module in
`examples/ladder/`, and a test in `tests/test_ladder.py`. Read them in order.

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
name_in    = VariableSpec("name_in", str)
salutation = VariableSpec("salutation", str)
greeting   = VariableSpec("greeting", str)

pick    = StepSpec("pick",    inputs=(name_in,),    outputs=(salutation,))
compose = StepSpec("compose", inputs=(salutation,), outputs=(greeting,))

class HelloWorld(GraphSpec):
    name = "hello_world"
    state_type = Guest
    input_type, output_type = str, str
    nodes = (pick, compose)
    edges = (EdgeSpec(source=START,   target=pick,    carries=name_in),
             EdgeSpec(source=pick,    target=compose, carries=salutation),
             EdgeSpec(source=compose, target=END,     carries=greeting))
```

Both print `'Hello, Ada!'` and both have the node ids `pick`, `compose`. On this rung the
declaration buys you `coherence_check()` and `diagram()` before any implementation exists, and nothing
else — it starts paying on rung 2, when `pick` has two implementations and something has to hold
them to one shape.

| rung | adds | source |
|---|---|---|
| 0 | nothing — Pydantic Graph alone, the control | [`their_hello.py`](../examples/ladder/their_hello.py) |
| 1 | the design as data; `coherence_check()` and `diagram()` with nothing implemented | [`stage1_bare.py`](../examples/ladder/stage1_bare.py) |
| 2 | **two strategies over one design**, with identical node ids | [`stage2_strategies.py`](../examples/ladder/stage2_strategies.py) |
| 3 | a new node — and a strategy that predates it is refused | [`stage3_new_node.py`](../examples/ladder/stage3_new_node.py) |
| 4 | one node implemented by a **whole child design** | [`stage4_subgraph.py`](../examples/ladder/stage4_subgraph.py) |
| 5 | a **battle** — both arms scored on the same cases, against a noise floor | [`stage5_battle.py`](../examples/ladder/stage5_battle.py) |
| 6 | the **diff diagram** neither library can draw | [`stage6_diagrams.py`](../examples/ladder/stage6_diagrams.py) |
| 7 | proof it is a real `Graph` — their `iter()` drives it unchanged | [`stage7_iter.py`](../examples/ladder/stage7_iter.py) |
| 8 | **a declared join** — two producers into one consumer, combined rather than dropped | [`stage8_join.py`](../examples/ladder/stage8_join.py) |
| 9 | **conditional routing** — branches on the type of the answer, converging again | [`stage9_decision.py`](../examples/ladder/stage9_decision.py) |
| 10 | **the three things people reach for `BaseNode` to do** — stop early, go back, dispatch — declared | [`stage10_no_basenode.py`](../examples/ladder/stage10_no_basenode.py) |

```bash
uv run python3 -m examples.ladder.stage2_strategies    # any rung
uv run pytest tests/test_ladder.py -q                  # all of them, asserted
```

## Other examples

| example | shows |
|---|---|
| [`counter.py`](../examples/counter.py) | the smallest two-node design, with `modest` / `aggressive` arms |
| [`parallel.py`](../examples/parallel.py) | a fan-out and the join that closes it |
| [`subgraph.py`](../examples/subgraph.py) | `naive` / `better` / `fancy`, where `fancy` binds a whole child design |
| [`local/extraction.py`](../examples/local/extraction.py) | a realistic extraction design |
