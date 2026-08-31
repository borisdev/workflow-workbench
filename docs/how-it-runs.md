# How a Pydantic Graph actually runs, and how a `GraphSpec` maps onto it

Everything below was measured against **pydantic-graph 2.35.1**, not read off their docs — most of
it is not in their docs.

```bash
uv run python3 docs/probe_executor.py     # every claim on this page, printed
```

⚠️ **This is a document about someone else's internals, which is the shape that goes stale
silently.** Their code is free to change and nothing reads a prose file and compares it to a
library. So this page asserts nothing the probe does not print, and `tests/test_ladder.py` runs
the probe. If they change something, the test goes red before the page becomes fiction.

---

## 1. The executor is a task scheduler, not a graph walk

```python
@dataclass
class _GraphIterator:
    task_group: TaskGroup                                   # anyio; tasks run concurrently
    active_tasks: dict[TaskID, GraphTask]
    active_reducers: dict[tuple[JoinID, NodeRunID], JoinState]
    iter_stream_sender / iter_stream_receiver               # completions arrive on a stream

    while self.active_tasks or self.active_reducers:
        async for task_result in self.iter_stream_receiver:
```

A `GraphTask` is `(node_id, inputs, fork_stack, task_id)`. The loop dispatches tasks, waits on a
memory stream, and each completion produces the next tasks.

**Nobody traverses the graph.** The graph is a lookup table and the run is a work queue that ends
when nothing is in flight. Note `active_reducers` in the loop condition — a pending join keeps the
run alive even when no task is running.

## 2. The graph is a routing table

```python
edges_by_source: dict[NodeID, list[Path]]
```

**One key per node.** The value is a list, appended to by `add()`:

```python
self._edges_by_source = defaultdict(list)                   # graph_builder.py:1213
self._edges_by_source[source_node.id].append(edge.path)     # graph_builder.py:1454
```

Read it as *"when this node finishes, here are the programs to run"* — not as adjacency.

## 3. A `Path` is an instruction list

```python
PathItem = TransformMarker | MapMarker | BroadcastMarker | LabelMarker | DestinationMarker

@dataclass
class Path:
    items: list[PathItem]
```

Each fluent call appends one marker, and `.to()` closes it:

```python
g.edge_from(a).label("count").transform(f).map().to(b)
#             +LabelMarker   +TransformMarker  +MapMarker  +DestinationMarker
```

**A path ends in exactly one `DestinationMarker`** — measured. It is linear and
single-destination, which is why fan-out is not a path feature (§5).

## 4. Edge properties are read at TWO different times

This is the part with consequences.

### At `build()` — `map` and `broadcast` are eliminated

```python
if isinstance(item, MapMarker):
    upstream   = Path(items[:i] + [DestinationMarker(item.fork_id)])
    downstream = Path(items[i+1:])
```

The path is **cut in half around the fork** and a real node is spliced in. By the time the
executor runs, the marker is gone:

```python
assert not isinstance(item, MapMarker | BroadcastMarker), 'These should be removed during Graph building'
```

    `.map()` becomes a NODE at build time; no MapMarker survives
        nodes=['__end__', '__start__', 'map', 'sq', 'total']  surviving markers=['DestinationMarker']

### At runtime — `transform` and `label` survive and are walked per completion

```python
elif isinstance(item, TransformMarker):
    inputs = item.transform(StepContext(state=..., deps=..., inputs=inputs))
    return self._handle_path(path.next_path, inputs, fork_stack)
elif isinstance(item, LabelMarker):
    return self._handle_path(path.next_path, inputs, fork_stack)
```

`_handle_path` recurses down the marker list, threading `inputs` through each transform, until a
`DestinationMarker` becomes the next `GraphTask`. **That is the moment your edge is "read"** —
after a node returns, before its successor is scheduled, in the same tick.

    `.transform()` and `.label()` stay in the Path and run per completion
        __start__ path items = ['LabelMarker', 'TransformMarker', 'DestinationMarker']

⚠️ **A transform must be synchronous, and an async one is not rejected.** `item.transform(...)` is
called without `await`, so the coroutine object becomes `inputs` and flows onward:

    an ASYNC transform is accepted and silently yields a coroutine
        run(1) -> '<<coroutine object not_allowed at 0x...>>'   (RuntimeWarning: never awaited)

`TransformEdgeSpec` refuses an async binding at declaration for exactly this reason.

## 5. One-to-many is a NODE, not a path feature

`DestinationMarker` holds one id. So fan-out is represented above the path, in two ways that
normalise to the same thing:

**A list of paths from one source.** At build, if a node has more than one:

```python
if len(edges_from_source) == 1:
    new_edges[source_id] = edges_from_source        # leave it alone
    continue
new_fork = Fork(id=f'{node.id}_broadcast_fork', is_map=False, ...)
new_edges[source_id]   = [Path(items=[DestinationMarker(new_fork.id)])]
new_edges[new_fork.id] = edges_from_source          # the branches hang off the fork
```

**A `BroadcastMarker`, which nests paths.** It is the only recursive item, and `.to(a, b)` builds
one silently:

```python
if extra_destinations:
    next_item = BroadcastMarker(paths=[Path([DestinationMarker(d.id)]) for d in ...])
```

`_split_at_first_fork` then flattens it back to the first form.

    two edges out of one node become a Fork; the source keeps ONE path
        a -> [['DestinationMarker']]
        a_broadcast_fork -> [['DestinationMarker'], ['DestinationMarker']]

So **after `build()` every ordinary node has exactly one outgoing `Path`**, and anything that
branched goes through a `Fork` that owns the list. A length-2 list exists only between `add()` and
`build()`.

All three spellings converge:

```
edge_from(a).to(x)  +  edge_from(a).to(y)      ─┐
edge_from(a).to(x, y)                          ─┼──►  Fork node owning list[Path]
edge_from(a).broadcast([...to(x), ...to(y)])   ─┘
```

## 6. `fork_stack` is what makes a join possible

Every task carries a `ForkStack` — the chain of forks it descends from. A join keys its
accumulator on the fork RUN:

```python
active_reducers: dict[tuple[JoinID, NodeRunID], JoinState]

class JoinState:
    current: Any
    downstream_fork_stack: ForkStack
```

Three fanned-out tasks share a fork-run id, so the join accumulates into **one** `JoinState` and
emits when that fork's tasks drain.

**This is the mechanical reason a step cannot replace a join.** A step has no accumulator keyed on
the fork run, so each arrival is just another independent task — which is why a fan-out with no
join computes N results and returns whichever lands first. `check_fan_out_rejoins` exists for this.

---

# How a `GraphSpec` maps onto all that

| declaration | becomes | when |
|---|---|---|
| `NodeSpec` | `g.step` (or `g.stream` if `streams=True`) | build |
| `JoinSpec` | `g.join(reducer, initial=…)` | build |
| `DecisionSpec` + `when=` edges | `g.decision()` + `g.match(T).to(…)` branches | build |
| `EdgeSpec` | a `Path` of `[LabelMarker, DestinationMarker]` | build |
| `MapEdgeSpec` | a `MapMarker` → **a `Fork` node** | build, then eliminated |
| `TransformEdgeSpec` | a `TransformMarker` that **stays on the wire** | build, run per completion |
| several `EdgeSpec`s from one source | **a `Fork` node** the builder mints | build |

Two things follow, and they justify design decisions that otherwise look arbitrary.

**`MapEdgeSpec` and `TransformEdgeSpec` are separate types because they are separate kinds of
thing.** One becomes a node, one never does. A uniform "list of items on an edge" — which is what
they have — hides that until `_flatten_paths`.

**A `TransformEdgeSpec` emitting no node is structural, not cosmetic.** The marker lives in the
`Path` forever, so the diagram tagging the arrow rather than drawing a box matches what is built.

## Where the mapping loses information

Two gaps, both measured, neither with a caller yet.

### Forks are minted, never named

A `Fork` is a node the builder creates and our declaration never mentions. Fine for topology — a
fork is a scheduling artefact. What is lost is its **identity**, and identity is the handle for
join affinity: `g.join()` takes `parent_fork_id` and `preferred_parent_fork='farthest'|'closest'`,
and we expose neither.

It only matters once fan-outs nest:

    nested fan-outs make TWO forks; a join closes the outermost by default
        forks=['map', 'map_2']  parent_fork='__start__'  run -> ['<a>', '<b>', '<c>']

Map over papers, then over each paper's edges, and the join closes the **outer** fork — one flat
list. Asking for `[['<a>','<b>'], ['<c>']]` needs `'closest'`, which needs a fork id.

**Trigger to fix:** a design that fans out twice and wants the inner results grouped.

### `map` and `transform` do not compose on one edge

Theirs is an ordered list of markers, so one edge can do both:

    one edge can fan out AND reshape each item — we cannot express this
        run -> ['ADA', 'GRACE']

Ours are separate types and no edge is both. See
[issue #2](https://github.com/borisdev/workflow-workbench/issues/2) for what a path-shaped
`EdgeSpec` would cost.

**Trigger to fix:** a design wanting `carries=list[Paper], delivers=pmid` on one wire, where the
alternative is a step that exists only to unwrap.

---

⚠️ **Both gaps were found the same way and are worth noting as a pattern.** The capability matrix
in `parity.py` is keyed per API method, and "yes" means *the method is reachable* — not that every
parameter of it is. That read as more than it said twice: `map` ✓ + `transform` ✓ does not mean
both on one edge, and `join` ✓ does not include fork affinity. If a third turns up, the table
shape is wrong and should carry per-parameter coverage.
