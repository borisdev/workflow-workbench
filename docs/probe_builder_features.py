"""Every GraphBuilder feature, run — then: which of them can a `GraphSpec` DECLARE?

Two different questions, and conflating them is how a workbench comes to claim coverage it does
not have:

    does it RUN?        can the feature be reached at all from a GraphSpec, if necessary through
                        `build_pydantic_structure()`
    is it DECLARED?     is it in `nodes`/`edges` as DATA — which is the only form `check()`,
                        `diagram()`, `diff_diagram()` and `varies()` can read

⚠️ The second is the whole product. An escape-hatch topology runs perfectly and is invisible to
every check this library exists to provide — `check()` says so out loud (`NOT CHECKED — ...
overrides build_pydantic_structure()`), and the second half of this probe measures exactly that
rather than taking the docstring's word for it.

    uv run python3 docs/probe_builder_features.py
"""
from __future__ import annotations

import sys
from dataclasses import dataclass

from pydantic_graph import GraphBuilder
from pydantic_graph.join import reduce_sum

results: list[tuple[str, bool, str]] = []


def probe(name: str):
    def deco(fn):
        try:
            results.append((name, True, fn() or ""))
        except Exception as exc:  # noqa: BLE001
            results.append((name, False, f"{type(exc).__name__}: {exc}"))
        return fn
    return deco


@probe("step  — a plain step body")
def _step():
    g = GraphBuilder(name="f_step", input_type=int, output_type=int)

    async def double(ctx) -> int:
        return ctx.inputs * 2
    n = g.step(double, node_id="double")
    g.add(g.edge_from(g.start_node).to(n), g.edge_from(n).to(g.end_node))
    return f"run(5) -> {g.build().run_sync(inputs=5)}"


@probe("transform — a pure function ON AN EDGE, not a node")
def _transform():
    g = GraphBuilder(name="f_transform", input_type=int, output_type=str)

    async def show(ctx) -> str:
        return f"<{ctx.inputs}>"
    n = g.step(show, node_id="show")
    g.add(g.edge_from(g.start_node).transform(lambda ctx: ctx.inputs + 100).to(n),
          g.edge_from(n).to(g.end_node))
    graph = g.build()
    return f"run(5) -> {graph.run_sync(inputs=5)}   nodes={sorted(graph.nodes)}"


@probe("map + join — fan out over a list, reduce")
def _map_join():
    g = GraphBuilder(name="f_mapjoin", input_type=list[int], output_type=int)

    async def sq(ctx) -> int:
        return ctx.inputs * ctx.inputs
    n = g.step(sq, node_id="sq")
    j = g.join(reduce_sum, initial=0, node_id="total")
    g.add(g.edge_from(g.start_node).map().to(n), g.edge_from(n).to(j),
          g.edge_from(j).to(g.end_node))
    graph = g.build()
    return f"run([1,2,3,4]) -> {graph.run_sync(inputs=[1, 2, 3, 4])}  nodes={sorted(graph.nodes)}"


@probe("broadcast — send ONE value down several paths at once")
def _broadcast():
    g = GraphBuilder(name="f_broadcast", input_type=int, output_type=int)

    async def a(ctx) -> int:
        return ctx.inputs + 1

    async def b(ctx) -> int:
        return ctx.inputs * 10
    na, nb = g.step(a, node_id="a"), g.step(b, node_id="b")
    j = g.join(reduce_sum, initial=0, node_id="total")
    g.add(g.edge_from(g.start_node).broadcast(lambda eb: [eb.to(na), eb.to(nb)]),
          g.edge_from(na).to(j), g.edge_from(nb).to(j), g.edge_from(j).to(g.end_node))
    graph = g.build()
    return f"run(5) -> {graph.run_sync(inputs=5)}  nodes={sorted(graph.nodes)}"


@probe("decision — route on the TYPE of the value")
def _decision():
    @dataclass
    class Urgent:
        text: str

    @dataclass
    class Routine:
        text: str

    g = GraphBuilder(name="f_decision", input_type=str, output_type=str)

    async def triage(ctx) -> Urgent | Routine:
        return Urgent(ctx.inputs) if "chest pain" in ctx.inputs else Routine(ctx.inputs)

    async def escalate(ctx) -> str:
        return f"ESCALATE: {ctx.inputs.text}"

    async def research(ctx) -> str:
        return f"research: {ctx.inputs.text}"

    nt = g.step(triage, node_id="triage")
    ne = g.step(escalate, node_id="escalate")
    nr = g.step(research, node_id="research")
    d = g.decision(note="urgent or not", node_id="route")
    d = d.branch(g.match(Urgent).to(ne))
    d = d.branch(g.match(Routine).to(nr))
    g.add(g.edge_from(g.start_node).to(nt), g.edge_from(nt).to(d),
          g.edge_from(ne).to(g.end_node), g.edge_from(nr).to(g.end_node))
    graph = g.build()
    return (f"'chest pain' -> {graph.run_sync(inputs='chest pain now')!r}; "
            f"'rash' -> {graph.run_sync(inputs='rash')!r}; nodes={sorted(graph.nodes)}")


@probe("edge_from(*sources) — several sources into one target")
def _multisource():
    g = GraphBuilder(name="f_multi", input_type=int, output_type=int)

    async def a(ctx) -> int:
        return ctx.inputs + 1

    async def b(ctx) -> int:
        return ctx.inputs + 2

    async def sink(ctx) -> int:
        return ctx.inputs * 100
    na, nb = g.step(a, node_id="a"), g.step(b, node_id="b")
    ns = g.step(sink, node_id="sink")
    g.add(g.edge_from(g.start_node).to(na), g.edge_from(na).to(nb),
          g.edge_from(na, nb).to(ns), g.edge_from(ns).to(g.end_node))
    graph = g.build()
    return f"nodes={sorted(graph.nodes)}  run(1) -> {graph.run_sync(inputs=1)}"


print("does the feature RUN against raw pydantic-graph?\n")
for name, ok, note in results:
    print(f"{'PASS' if ok else 'FAIL'}  {name}")
    if note:
        print(f"        {note}")
bad = [n for n, ok, _ in results if not ok]
print(f"\n{len(results) - len(bad)}/{len(results)} builder features run\n")


# ── and now the question that decides what this library is worth ────────────────────────────
print("=" * 92)
print("can a GraphSpec DECLARE it — or does it need the escape hatch, which turns checking off?")
print("=" * 92 + "\n")

from workflow_workbench import (  # noqa: E402
    END, START, EdgeSpec, GraphSpec, NodeSpec, StrategySpec, VariableSpec)

n = VariableSpec("n", int)
double = NodeSpec("double", inputs=(n,), outputs=(n,))


class Declarative(GraphSpec):
    """A plain step chain — the ONE shape the declaration covers."""

    name = "declarative"
    input_type, output_type = int, int
    nodes = (double,)
    edges = (EdgeSpec(START, double, n), EdgeSpec(double, END, n))


class EscapeHatch(Declarative):
    """The same design, wired by hand. `edges` above is now decorative."""

    name = "escape_hatch"

    def build_pydantic_structure(self, g, nodes):
        g.add(g.edge_from(g.start_node).to(nodes[double]),
              g.edge_from(nodes[double]).to(g.end_node))


async def dbl(ctx) -> int:
    return ctx.inputs * 2


only = StrategySpec("only", {double: dbl})
declared_findings = Declarative().check(only)
hatch_findings = EscapeHatch().check(only)

print(f"declared design   check() -> {declared_findings or 'clean, reachability VERIFIED'}")
print(f"escape-hatch one  check() -> {hatch_findings[0][:88]}...")
print()

MATRIX = [
    ("step",                  True,  "NodeSpec + EdgeSpec"),
    ("join (fan-in)",         True,  "JoinSpec, in `joins` rather than `nodes` — it carries a "
                                     "reducer, so a strategy has nothing to bind for it"),
    ("map (fan-out)",         False, "no EdgeSpec field says 'iterate this edge'"),
    ("transform (on an edge)", False, "no EdgeSpec field for a transform function"),
    ("broadcast",             False, "one EdgeSpec is one wire; a fork is a set of them "
                                     "sharing a fork id"),
    ("decision",              False, "routes on the TYPE of the value; EdgeSpec has no "
                                     "condition and a Decision has no implementation to bind"),
]
print(f"{'feature':<26} {'declarable':>11}   how, or why not")
for feat, ok, why in MATRIX:
    print(f"{feat:<26} {('YES' if ok else 'no'):>11}   {why}")

declarable = sum(1 for _, ok, _ in MATRIX if ok)
print(f"\n{declarable}/{len(MATRIX)} declarable. The other {len(MATRIX) - declarable} run only "
      f"through `build_pydantic_structure()`, which makes `edges`")
print("decorative and reports reachability as NOT CHECKED for the WHOLE design — see above. That")
print("is why JoinSpec was worth adding: a join used to cost the checks on every node around it.")
sys.exit(1 if bad else 0)
