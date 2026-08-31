"""Every claim in `docs/how-it-runs.md`, measured against the installed pydantic-graph.

A document about someone else's internals goes stale silently — theirs is free to change, and
nothing reads a prose file and compares it to a library. So the doc asserts nothing this script
does not print, and `tests/test_ladder.py` runs it.

    uv run python3 docs/probe_executor.py
"""
from __future__ import annotations

import sys

import pydantic_graph
from pydantic_graph import GraphBuilder
from pydantic_graph.join import reduce_list_append, reduce_sum

failures: list[str] = []


def claim(text: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {text}")
    if detail:
        print(f"        {detail}")
    if not ok:
        failures.append(text)


try:
    import importlib.metadata as md
    version = md.version("pydantic-graph")
except Exception:                                          # noqa: BLE001
    version = "unknown"
print(f"pydantic-graph {version}\n")


# ── 1. the routing table ────────────────────────────────────────────────────────────────────
g = GraphBuilder(name="table", input_type=int, output_type=int)


async def passthrough(ctx) -> int:
    return ctx.inputs


a, b, c = (g.step(passthrough, node_id=n) for n in ("a", "b", "c"))
g.add(g.edge_from(g.start_node).to(a),
      g.edge_from(a).to(b), g.edge_from(a).to(c),          # TWO edges out of `a`
      g.edge_from(b).to(g.end_node), g.edge_from(c).to(g.end_node))
built = g.build()
table = {str(k): [[type(i).__name__ for i in p.items] for p in v]
         for k, v in built.edges_by_source.items()}

claim("edges_by_source has ONE key per node; the value is a list[Path]",
      all(isinstance(v, list) for v in built.edges_by_source.values()),
      f"keys={sorted(table)}")
claim("two edges out of one node become a Fork; the source keeps ONE path",
      len(built.edges_by_source["a"]) == 1
      and "a_broadcast_fork" in built.nodes
      and len(built.edges_by_source["a_broadcast_fork"]) == 2,
      f"a -> {table['a']}, a_broadcast_fork -> {table['a_broadcast_fork']}")
claim("a Path ends in exactly one DestinationMarker",
      all(p[-1] == "DestinationMarker" and p.count("DestinationMarker") == 1
          for paths in table.values() for p in paths),
      "one destination per path; fan-out is a node, not a path feature")


# ── 2. map and broadcast are eliminated at BUILD time ───────────────────────────────────────
g2 = GraphBuilder(name="mapped", input_type=list, output_type=int)


async def sq(ctx) -> int:
    return ctx.inputs * ctx.inputs


n2 = g2.step(sq, node_id="sq")
j2 = g2.join(reduce_sum, initial=0, node_id="total")
g2.add(g2.edge_from(g2.start_node).map().to(n2), g2.edge_from(n2).to(j2),
       g2.edge_from(j2).to(g2.end_node))
mapped = g2.build()
markers = {type(i).__name__ for paths in mapped.edges_by_source.values()
           for p in paths for i in p.items}

claim("`.map()` becomes a NODE at build time; no MapMarker survives",
      "map" in mapped.nodes and "MapMarker" not in markers,
      f"nodes={sorted(mapped.nodes)}  surviving markers={sorted(markers)}")


# ── 3. transform and label SURVIVE to runtime ───────────────────────────────────────────────
g3 = GraphBuilder(name="transformed", input_type=int, output_type=str)


async def show(ctx) -> str:
    return f"<{ctx.inputs}>"


n3 = g3.step(show, node_id="show")
g3.add(g3.edge_from(g3.start_node).label("n").transform(lambda ctx: ctx.inputs + 100).to(n3),
       g3.edge_from(n3).to(g3.end_node))
transformed = g3.build()
surviving = [type(i).__name__ for p in transformed.edges_by_source["__start__"] for i in p.items]

claim("`.transform()` and `.label()` stay in the Path and run per completion",
      "TransformMarker" in surviving and "LabelMarker" in surviving,
      f"__start__ path items = {surviving}; run(5) -> {transformed.run_sync(inputs=5)!r}")
claim("a transform adds NO node",
      sorted(transformed.nodes) == ["__end__", "__start__", "show"],
      f"nodes={sorted(transformed.nodes)}")


# ── 4. a transform is SYNC, and an async one is not rejected ────────────────────────────────
g4 = GraphBuilder(name="async_t", input_type=int, output_type=str)
n4 = g4.step(show, node_id="show")


async def not_allowed(ctx):
    return ctx.inputs + 1


g4.add(g4.edge_from(g4.start_node).transform(not_allowed).to(n4),
       g4.edge_from(n4).to(g4.end_node))
out4 = g4.build().run_sync(inputs=1)
claim("an ASYNC transform is accepted and silently yields a coroutine",
      "coroutine" in out4,
      f"run(1) -> {out4!r}   (RuntimeWarning: never awaited)")


# ── 5. joins accumulate per FORK RUN, which is why a step cannot replace one ────────────────
g5 = GraphBuilder(name="nested", input_type=list, output_type=list)


async def explode(ctx) -> list:
    return ctx.inputs["edges"]


async def tag(ctx) -> str:
    return f"<{ctx.inputs}>"


ne, nt = g5.step(explode, node_id="explode"), g5.step(tag, node_id="tag")
j5 = g5.join(reduce_list_append, initial_factory=list, node_id="collect")
g5.add(g5.edge_from(g5.start_node).map().to(ne),
       g5.edge_from(ne).map().to(nt),
       g5.edge_from(nt).to(j5), g5.edge_from(j5).to(g5.end_node))
nested = g5.build()
result = sorted(nested.run_sync(inputs=[{"edges": ["a", "b"]}, {"edges": ["c"]}]))

claim("nested fan-outs make TWO forks; a join closes the outermost by default",
      len([n for n in nested.nodes if n.startswith("map")]) == 2
      and nested.parent_forks["collect"].fork_id == "__start__",
      f"forks={sorted(n for n in nested.nodes if n.startswith('map'))}  "
      f"parent_fork={nested.parent_forks['collect'].fork_id!r}  run -> {result}")


# ── 6. map and transform COMPOSE on one edge ────────────────────────────────────────────────
g6 = GraphBuilder(name="compose", input_type=list, output_type=list)


async def shout(ctx) -> str:
    return ctx.inputs.upper()


n6 = g6.step(shout, node_id="shout")
j6 = g6.join(reduce_list_append, initial_factory=list, node_id="collect")
g6.add(g6.edge_from(g6.start_node).map().transform(lambda ctx: ctx.inputs["name"]).to(n6),
       g6.edge_from(n6).to(j6), g6.edge_from(j6).to(g6.end_node))
composed = sorted(g6.build().run_sync(inputs=[{"name": "ada"}, {"name": "grace"}]))
claim("one edge can fan out AND reshape each item — we cannot express this",
      composed == ["ADA", "GRACE"],
      f"run -> {composed}   (MapEdgeSpec and TransformEdgeSpec are separate types)")


print(f"\n{len(failures)} failed" if failures else "\nall claims hold")
sys.exit(1 if failures else 0)
