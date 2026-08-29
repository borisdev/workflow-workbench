"""Every GraphBuilder feature, run — then: which of them can a `GraphSpec` DECLARE?

Two different questions, and conflating them is how a workbench comes to claim coverage it does
not have:

    does it RUN?        can the feature be reached at all from a GraphSpec, if necessary through
                        `build_pydantic_structure()`
    is it DECLARED?     is it in `nodes`/`joins`/`decisions`/`edges` as DATA — which is the only
                        form `check()`, `diagram()`, `diff_diagram()` and `varies()` can read

⚠️ The second is the whole product. An escape-hatch topology runs perfectly and is invisible to
every check this library exists to provide — `check()` says so out loud (`NOT CHECKED — ...
overrides build_pydantic_structure()`), and the middle section measures exactly that.

⛔ AND THE MATRIX IS CHECKED AGAINST THE REAL API, not maintained by hand. It was hand-written
once, from a grep of method names, and it MISSED SEVERAL — `stream`, `node`, `match_node`,
`add_mapping_edge`, and the `matches=` predicate on `match`. A hand-maintained inventory of
someone else's API is wrong the moment they add to it, and nothing would have said so. The last
section introspects `GraphBuilder` and fails if any public method is unclassified.

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


@probe("match(matches=...) — route on a PREDICATE, not just a type")
def _predicate():
    """⚠️ MISSED by the hand-written matrix. `when=` is a type; this is arbitrary logic."""
    g = GraphBuilder(name="f_pred", input_type=int, output_type=str)

    async def emit(ctx) -> int:
        return ctx.inputs

    async def big(ctx) -> str:
        return f"big {ctx.inputs}"

    async def small(ctx) -> str:
        return f"small {ctx.inputs}"

    ne, nb, ns = g.step(emit, node_id="emit"), g.step(big, node_id="big"), g.step(small, node_id="small")
    d = g.decision(node_id="size")
    d = d.branch(g.match(int, matches=lambda v: v > 10).to(nb))
    d = d.branch(g.match(int).to(ns))
    g.add(g.edge_from(g.start_node).to(ne), g.edge_from(ne).to(d),
          g.edge_from(nb).to(g.end_node), g.edge_from(ns).to(g.end_node))
    graph = g.build()
    return f"run(50) -> {graph.run_sync(inputs=50)!r}; run(2) -> {graph.run_sync(inputs=2)!r}"


@probe("stream — a step that yields")
def _stream():
    """⚠️ MISSED entirely by the hand-written matrix. A whole second kind of step body."""
    import inspect
    sig = inspect.signature(GraphBuilder.stream)
    return f"exists: GraphBuilder.stream{str(sig)[:90]}..."


@probe("node(BaseNode) — the class-based authoring API")
def _basenode():
    """⚠️ MISSED entirely. An ENTIRE alternative way to define nodes, alongside `step`."""
    import inspect
    sig = inspect.signature(GraphBuilder.node)
    return f"exists: GraphBuilder.node{sig}"


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


# ── what the escape hatch costs ─────────────────────────────────────────────────────────────
print("=" * 92)
print("can a GraphSpec DECLARE it — or does it need the escape hatch, which turns checking off?")
print("=" * 92 + "\n")

from workflow_workbench import (  # noqa: E402
    END, START, EdgeSpec, GraphSpec, NodeSpec, StrategySpec, VariableSpec)

n = VariableSpec("n", int)
double = NodeSpec("double", inputs=(n,), outputs=(n,))


class Declarative(GraphSpec):
    """A plain step chain — declared, and therefore checked."""

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
print(f"declared design   check() -> {Declarative().check(only) or 'clean, reachability VERIFIED'}")
print(f"escape-hatch one  check() -> {EscapeHatch().check(only)[0][:88]}...")
print()


# ── the matrix, keyed by the REAL API names so it can be checked ────────────────────────────
#
# status: "yes" declarable | "partial" declarable in part | "no" escape hatch only
#         "plumbing" not a topology feature — types, sentinels, the build call itself
MATRIX: dict[str, tuple[str, str]] = {
    "step":             ("yes", "NodeSpec"),
    "join":             ("yes", "JoinSpec, in `joins` — it carries a reducer, so nothing binds it"),
    "decision":         ("yes", "DecisionSpec in `decisions`; branches are EdgeSpec(..., when=T)"),
    "match":            ("partial", "the TYPE form is `when=`. The `matches=` PREDICATE form is "
                                    "not declarable — an EdgeSpec has nowhere to put a callable"),
    "edge_from":        ("partial", "one source per EdgeSpec. Several edges into one join is the "
                                    "declared fan-in; `edge_from(a, b)` as one call is not"),
    "add":              ("yes", "what the default build_pydantic_structure() does, per edge"),
    "add_edge":         ("yes", "same wire as an EdgeSpec, expressed as a helper"),
    "stream":           ("no", "a streaming step body. NodeSpec assumes `(ctx) -> Out`"),
    "node":             ("no", "the BaseNode class-based authoring API — an alternative to `step` "
                               "entirely, with no NodeSpec equivalent"),
    "match_node":       ("no", "branch on a BaseNode subclass; follows `node` being unsupported"),
    "add_mapping_edge": ("no", "the convenience form of `.map()` — fan-out, see below"),
    "build":            ("plumbing", "called by render()"),
    "decision_note":    ("yes", "DecisionSpec.note"),
    "Source":           ("plumbing", "a typing helper"),
    "Destination":      ("plumbing", "a typing helper"),
    "start_node":       ("plumbing", "START"),
    "end_node":         ("plumbing", "END"),
}
EDGE_MATRIX: dict[str, tuple[str, str]] = {
    "to":        ("partial", "single destination yes; `to(a, b, ...)` multi-destination is a fork"),
    "label":     ("yes", "EdgeSpec.label"),
    "map":       ("no", "no EdgeSpec field says 'iterate this edge'"),
    "transform": ("no", "no EdgeSpec field for a transform function"),
    "broadcast": ("no", "one EdgeSpec is one wire; a fork is a set of them sharing a fork id"),
}

ORDER = {"yes": 0, "partial": 1, "no": 2, "plumbing": 3}
print(f"{'GraphBuilder API':<20} {'declarable':>11}   how, or why not")
for api, (status, why) in sorted(MATRIX.items(), key=lambda kv: (ORDER[kv[1][0]], kv[0])):
    if status == "plumbing":
        continue
    print(f"{api:<20} {status.upper() if status == 'yes' else status:>11}   {why}")

print(f"\n{'edge builder':<20} {'declarable':>11}   how, or why not")
for api, (status, why) in sorted(EDGE_MATRIX.items(), key=lambda kv: (ORDER[kv[1][0]], kv[0])):
    print(f"{api:<20} {status.upper() if status == 'yes' else status:>11}   {why}")

topo = {k: v for k, v in MATRIX.items() if v[0] != "plumbing"}
full = sum(1 for s, _ in topo.values() if s == "yes")
part = sum(1 for s, _ in topo.values() if s == "partial")
print(f"\n{full} fully declarable, {part} partial, {len(topo) - full - part} escape-hatch only, "
      f"out of {len(topo)} topology features on GraphBuilder.")
print("Everything not declarable runs ONLY through build_pydantic_structure(), which makes `edges`")
print("decorative and reports reachability as NOT CHECKED for the WHOLE design.")


# ── ⛔ and the check that stops this list going stale ────────────────────────────────────────
print("\n" + "=" * 92)
print("is the matrix COMPLETE — does it classify every public GraphBuilder method?")
print("=" * 92)

public = {n for n in dir(GraphBuilder) if not n.startswith("_")}
classified = set(MATRIX) - {"decision_note"}
unclassified = sorted(public - classified)
stale = sorted(classified - public)

if unclassified:
    print(f"\n⛔ UNCLASSIFIED — pydantic-graph exposes these and the matrix says nothing:")
    for name in unclassified:
        print(f"     {name}")
if stale:
    print(f"\n⛔ STALE — the matrix classifies these and they no longer exist: {stale}")
if not unclassified and not stale:
    print(f"\nclean: all {len(public)} public GraphBuilder methods are classified.")

sys.exit(1 if (bad or unclassified or stale) else 0)
