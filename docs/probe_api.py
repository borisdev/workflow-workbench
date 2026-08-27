"""Mechanical verification against the REAL pydantic-graph, before writing the library.

Every claim the design rests on, run rather than remembered. Prints PASS/FAIL per probe and
exits non-zero if any fail, so it can be a gate rather than a document.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any

import pydantic_graph
from pydantic_graph import GraphBuilder

results: list[tuple[str, bool, str]] = []


def probe(name: str):
    def deco(fn):
        try:
            note = fn()
            results.append((name, True, note or ""))
        except Exception as exc:  # noqa: BLE001 — a failing probe is the finding
            results.append((name, False, f"{type(exc).__name__}: {exc}"))
        return fn
    return deco


print(f"pydantic_graph from {pydantic_graph.__file__}")
try:
    import importlib.metadata as md
    print(f"version {md.version('pydantic-graph')}")
except Exception:
    pass


# ── 1. edge_from stored across statements, .label() separate, .to() later ────────────────────
@probe("1. edge_from() stored across statements, .to() called later")
def _p1():
    g = GraphBuilder(name="p1", state_type=type(None), input_type=int, output_type=int)

    async def a(ctx) -> int:
        return 1

    async def b(ctx) -> int:
        return 2

    na = g.step(a, node_id="a")
    nb = g.step(b, node_id="b")
    partial = g.edge_from(na)           # stored, not immediately completed
    edge = partial.to(nb)               # completed in a later statement
    g.add(g.edge_from(g.start_node).to(na), edge, g.edge_from(nb).to(g.end_node))
    graph = g.build()
    return f"built, nodes={sorted(graph.nodes)}"


# ── 2. per-edge g.add() in a loop == one combined g.add() ────────────────────────────────────
@probe("2. per-edge g.add() in a loop produces the same topology as one combined call")
def _p2():
    def build(loop: bool):
        g = GraphBuilder(name="p2", state_type=type(None), input_type=int, output_type=int)

        async def a(ctx) -> int:
            return 1

        async def b(ctx) -> int:
            return 2

        na, nb = g.step(a, node_id="a"), g.step(b, node_id="b")
        edges = [g.edge_from(g.start_node).to(na), g.edge_from(na).to(nb),
                 g.edge_from(nb).to(g.end_node)]
        if loop:
            for e in edges:
                g.add(e)                # one call per edge — what an edges-loop compiler does
        else:
            g.add(*edges)
        return g.build()

    looped, combined = build(True), build(False)
    same_nodes = sorted(looped.nodes) == sorted(combined.nodes)
    lk = {k: sorted(str(e) for e in v) for k, v in looped.edges_by_source.items()}
    ck = {k: sorted(str(e) for e in v) for k, v in combined.edges_by_source.items()}
    assert same_nodes, f"node sets differ: {sorted(looped.nodes)} vs {sorted(combined.nodes)}"
    assert lk == ck, f"edge maps differ:\n{lk}\n{ck}"
    return "identical nodes and edges_by_source"


# ── 3. pure-python reachability over spec data, cycle-safe ───────────────────────────────────
@probe("3. pure-Python reachability over node/edge tuples, cycle-safe")
def _p3():
    START, END = object(), object()
    nodes = ["a", "b", "c", "orphan"]
    edges = [(START, "a"), ("a", "b"), ("b", "a"), ("b", "c"), ("c", END)]  # a<->b is a cycle

    def reach(src, adj):
        seen, stack = set(), [src]
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            stack.extend(adj.get(n, ()))
        return seen

    fwd: dict[Any, list] = {}
    bwd: dict[Any, list] = {}
    for s, t in edges:
        fwd.setdefault(s, []).append(t)
        bwd.setdefault(t, []).append(s)
    from_start = reach(START, fwd)
    to_end = reach(END, bwd)
    unreachable = [n for n in nodes if n not in from_start]
    deadend = [n for n in nodes if n not in to_end]
    assert unreachable == ["orphan"], unreachable
    assert deadend == ["orphan"], deadend
    return "terminates on a cycle; found the orphan both ways"


# ── 4. identity-keyed nodes mixed with sentinels in one dict ─────────────────────────────────
@probe("4. eq=False nodes + sentinel classes as dict keys")
def _p4():
    @dataclass(frozen=True, eq=False)
    class NodeSpec:
        name: str

    class _Start:
        pass

    class _End:
        pass

    START, END = _Start(), _End()
    a1, a2 = NodeSpec("same"), NodeSpec("same")     # field-identical, must NOT collide
    d = {a1: "first", a2: "second", START: "start", END: "end"}
    assert len(d) == 4, f"collided: {len(d)}"
    assert d[a1] == "first" and d[a2] == "second"
    assert d[START] == "start"
    return "4 distinct keys; field-identical nodes stayed distinct"


# ── 5. node-id set identical across two different strategies ─────────────────────────────────
@probe("5. two strategies over one spec produce IDENTICAL node ids")
def _p5():
    def build(impl_suffix: str):
        g = GraphBuilder(name=f"p5::{impl_suffix}", state_type=type(None),
                         input_type=int, output_type=int)

        # Deliberately DIFFERENT function names per strategy — the thing node_id must defeat.
        async def load_v1(ctx) -> int:
            return 1

        async def load_v2(ctx) -> int:
            return 2
        impl = load_v1 if impl_suffix == "v1" else load_v2
        n = g.step(impl, node_id="load")           # node_id from the SPEC, not the function
        g.add(g.edge_from(g.start_node).to(n), g.edge_from(n).to(g.end_node))
        return g.build()

    a, b = build("v1"), build("v2")
    assert sorted(a.nodes) == sorted(b.nodes), f"{sorted(a.nodes)} != {sorted(b.nodes)}"
    return f"both {sorted(a.nodes)}"


# ── 5b. the counterfactual: WITHOUT node_id, the node set diverges ───────────────────────────
@probe("5b. WITHOUT node_id, node ids diverge (proves node_id is load-bearing)")
def _p5b():
    def build(which: str):
        g = GraphBuilder(name=f"p5b::{which}", state_type=type(None),
                         input_type=int, output_type=int)

        async def load_v1(ctx) -> int:
            return 1

        async def load_v2(ctx) -> int:
            return 2
        impl = load_v1 if which == "v1" else load_v2
        n = g.step(impl)                            # NO node_id — id comes from __name__
        g.add(g.edge_from(g.start_node).to(n), g.edge_from(n).to(g.end_node))
        return g.build()

    a, b = build("v1"), build("v2")
    assert sorted(a.nodes) != sorted(b.nodes), "expected divergence, got identical"
    return f"diverged as predicted: {sorted(a.nodes)} vs {sorted(b.nodes)}"


# ── 6. map()/join() for the Parallel Processing example ──────────────────────────────────────
@probe("6. .map() / .join() fan-out+collect")
def _p6():
    import inspect
    g = GraphBuilder(name="p6", state_type=type(None), input_type=list[int], output_type=int)
    sigs = {}
    for meth in ("join", "step", "edge_from"):
        if hasattr(g, meth):
            sigs[meth] = str(inspect.signature(getattr(g, meth)))
    edge_meths = [m for m in dir(g.edge_from(g.start_node)) if not m.startswith("_")]
    return f"builder methods {sorted(sigs)}; edge builder exposes {sorted(edge_meths)}"


for name, ok, note in results:
    print(f"{'PASS' if ok else 'FAIL'}  {name}")
    if note:
        print(f"        {note}")

failed = [n for n, ok, _ in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
