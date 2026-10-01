# What a `GraphSpec` can express — every Pydantic Graph builder feature, enumerated

`GraphSpec` declares a workflow as DATA, because data is the only form `coherence_check()` and `diagram()`
can read before any implementation exists. That buys the checks and the diagrams, and it costs
expressiveness: a few things Pydantic Graph lets you write in code cannot be written down.

**10 fully declarable, 1 partial, 1 that cannot be.** The row-by-row table is below.

## There is no escape hatch, and that is the design

`edges` is the only way a graph gets wired — no override, no hook. A declaration that something
else could quietly contradict is a decoration: `diagram()` could draw a picture the graph did not
match, and reachability would be reported over a topology nothing actually built.

So if you need a predicate branch or the `BaseNode` API: **`render()` hands you a real
`pydantic_graph.Graph` — take it and use their API directly.** A workbench that can express
everything is the engine with extra steps.

## The table is checked against the live API

`docs/probe_builder_features.py` introspects `GraphBuilder` and fails if any public method is
unclassified, so the next thing Pydantic Graph ships turns it red instead of silently widening a
gap this page describes as closed. The rows themselves are generated from
`workflow_workbench/parity.py`; `tests/test_parity.py` fails if this file and that one disagree.

```bash
python3 -m workflow_workbench.parity            # print the table
python3 -m workflow_workbench.parity --check    # exit 1 if this file is stale
```

⚠️ `status` is per FEATURE, and a feature-by-feature table cannot express COMPOSITION. `map` is
`yes` and `transform` is `yes`, and `.map().transform(f).to(b)` on one edge is still not
expressible — their `Path` is an ordered list of markers, ours is a typed edge. Likewise `join` is
`yes` and does not include `parent_fork_id` / `preferred_parent_fork`. Each caveat is written into
its own row's note.

⚠️ `JoinSpec` and `DecisionSpec` live in `joins` and `decisions`, never in `nodes`. Neither has an
implementation, so a strategy binds nothing for them — which keeps *"a node is a role a strategy
fills"* true of every element of `nodes`, and guarantees two arms of a branching design route
identically.

<!-- parity:start -->
## Every builder feature, theirs beside ours

<!-- GENERATED from workflow_workbench/parity.py — do not edit by hand. -->
<!-- Regenerate: python3 -m workflow_workbench.parity --write -->

### `step` — **yes**

Pydantic Graph:

```python
@g.step
async def double(ctx) -> int:
    return ctx.inputs * 2
```

Workflow Workbench:

```python
double = StepSpec("double", inputs=(n,), outputs=(n,))
# and a strategy binds the body:
StrategySpec("s", {double: double_impl})
```

> Theirs names the node after the function. Ours names it in the DESIGN, so two strategies produce the same node ids and can be compared.

### `add / add_edge / label` — **yes**

Pydantic Graph:

```python
g.add(g.edge_from(a).to(b))
g.add_edge(a, b, label='count')
```

Workflow Workbench:

```python
EdgeSpec(source=a, target=b, carries=count)          # `carries` IS the label
```

### `join` — **yes**

Pydantic Graph:

```python
collect = g.join(reduce_sum, initial=0)
```

Workflow Workbench:

```python
collect = JoinSpec("collect", reduce_sum, initial=0,
                   inputs=(number,), outputs=(total,))
class Design(GraphSpec):
    joins = (collect,)
```

> In `joins`, not `nodes`: a reducer is `(current, input) -> current`, so there is no implementation for a strategy to bind. ⚠️ `parent_fork_id` and `preferred_parent_fork` are NOT exposed. They pick WHICH fork a join closes, which only matters once fan-outs nest — measured: map-over-papers then map-over-edges collects one flat list because the default is 'farthest'. Asking for 'closest' needs a fork id, and forks are minted by the builder and never named in a declaration.

### `map / add_mapping_edge` — **yes**

Pydantic Graph:

```python
g.edge_from(g.start_node).map().to(square)
```

Workflow Workbench:

```python
MapEdgeSpec(source=START, target=square, carries=numbers, delivers=number)
```

> `carries` is the collection on the wire, `delivers` the item the target receives. Naming both is what keeps both ends checked. ⚠️ NOT COMPOSABLE with a transform: theirs is a list of markers on one edge, so `.map().transform(f).to(b)` fans out AND reshapes each item; ours are separate types and no edge is both. Measured, not assumed.

### `decision` — **yes**

Pydantic Graph:

```python
d = g.decision()
d = d.branch(g.match(Urgent).to(escalate))
d = d.branch(g.match(Routine).to(research))
```

Workflow Workbench:

```python
route = DecisionSpec("route")
EdgeSpec(source=route, target=escalate, carries=v, when=Urgent)
EdgeSpec(source=route, target=research, carries=v, when=Routine)
```

> The condition lives on the EDGE so `edges` stays the only place topology is written. A decision binds nothing, so two arms are guaranteed to route identically.

### `stream` — **yes**

Pydantic Graph:

```python
@g.stream
async def split(ctx):
    for w in ctx.inputs.split():
        yield w
```

Workflow Workbench:

```python
split = StepSpec("split", inputs=(text,), outputs=(words,), streams=True)
MapEdgeSpec(source=split, target=collect, carries=words, delivers=word)   # its output is an AsyncIterable
```

> A flag on StepSpec, not its own type: a stream IS a role a strategy fills.

### `broadcast` — **yes**

Pydantic Graph:

```python
g.edge_from(a).broadcast(lambda eb: [eb.to(x), eb.to(y)])
```

Workflow Workbench:

```python
EdgeSpec(source=a, target=x, carries=v)
EdgeSpec(source=a, target=y, carries=v)   # two edges from one source
```

> MEASURED equivalent: same topology, same answer. Only the generated fork node's name differs. No vocabulary was added for it.

### `edge_from(*sources) / to(a, b)` — **yes**

Pydantic Graph:

```python
g.edge_from(a, b).to(sink)
```

Workflow Workbench:

```python
EdgeSpec(source=a, target=sink, carries=v)
EdgeSpec(source=b, target=sink, carries=v)
```

> MEASURED byte-identical. ⚠️ But two producers into one STEP is a real defect — the step runs once per edge and one result is discarded. Use a JoinSpec; `check_step_arity` refuses the other shape.

### `match(matches=predicate)` — partial

Pydantic Graph:

```python
d.branch(g.match(int, matches=lambda v: v > 10).to(big))
```

Workflow Workbench:

```python
# not declarable. Return a discriminating TYPE from a step instead:
async def triage(ctx) -> Urgent | Routine: ...
EdgeSpec(source=route, target=escalate, carries=v, when=Urgent)
```

> REFUSED, not missing. A callable in the declaration is an implementation: `diagram()` cannot draw it and `varies()` cannot compare two. Making the decision a typed value is the better design anyway — it becomes something you can see and battle.

### `transform` — **yes**

Pydantic Graph:

```python
g.edge_from(a).transform(lambda ctx: ctx.inputs.edges).to(b)
```

Workflow Workbench:

```python
# fixed — part of the design, like a JoinSpec's reducer:
TransformEdgeSpec(source=propose, target=cite, carries=draft, delivers=edge_list, apply=take_edges)
# or a variation point — every strategy binds it, and varies() reports it:
shape = TransformEdgeSpec(source=propose, target=cite, carries=draft, delivers=edge_list)
StrategySpec("all", {..., shape: all_edges})
```

> Emits NO node, exactly as theirs does, so the diagram tags the arrow rather than adding a box — a reshape is not a stage and drawing it as one misleads. `variable` is what leaves the source, `produces` what arrives. Exactly one of `apply=` or a binding: neither is a silently missing transform, both is a coin toss. Must be SYNC — an async one is not rejected by pydantic-graph, it quietly yields a coroutine.

### `node(BaseNode) / match_node` — cannot be declared

Pydantic Graph:

```python
class Increment(BaseNode[S, None, int]):
    async def run(self, ctx) -> DoubleIt:       # names its OWN successor
        return DoubleIt(...)
```

Workflow Workbench:

```python
# no equivalent for the CLASS. All three things it is used FOR are declarable:
EdgeSpec(source=gate, target=END, carries=v, when=NotAPlan)      # 1. stop early  (their End(...))
EdgeSpec(source=again, target=retry_seed, carries=v, when=Thin)  # 2. go back     (a loop)
EdgeSpec(source=unwrap, target=propose, carries=seed)
EdgeSpec(source=route, target=escalate, carries=v, when=Urgent)  # 3. dispatch    (pick a successor)
```

> A BaseNode's topology lives inside its implementation, so declared `edges` would be a lie it is free to ignore — two arms binding different BaseNodes could be two different graphs while `diff_diagram()` drew them as one. ⚠️ But what is lost is the AUTHORING STYLE, not the capability: `examples/ladder/stage10_no_basenode.py` does all three in one design. The real cost is porting an existing BaseNode app, and one converter node wherever two paths reach the same step carrying different variables.

**Plumbing, not topology:** `build`, `start_node / end_node`, `Source / Destination` — `render()` and `START`/`END` cover these.
<!-- parity:end -->
