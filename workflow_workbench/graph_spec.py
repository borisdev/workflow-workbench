"""`GraphSpec` — one fixed design — and `render(strategy)`, which fills it in.

    jinja_template.render(values)      values fill the placeholders
    graph_spec.render(strategy)        a strategy fills the nodes

The GraphSpec owns the DAG, declared as data (`nodes` + `edges`). A StrategySpec supplies every
implementation. Rendering produces a real `pydantic_graph.Graph`.
"""
from __future__ import annotations

from typing import Any, ClassVar

from pydantic_graph import GraphBuilder

from workflow_workbench import built as _built, checks
from workflow_workbench.diagram import diagram as _diagram, diff_diagram as _diff_diagram
from workflow_workbench.spec import (
    DecisionSpec,
    EdgeSpec,
    JoinSpec,
    NodeSpec,
    SpecError,
    StrategySpec,
    SubgraphBinding,
    _End,
    _Start,
    is_sentinel,
)

__all__ = ["GraphSpec"]


class GraphSpec:
    """Subclass it, declare `nodes` and `edges`. That is the whole interface.

        class Extraction(GraphSpec):
            name = "extraction"
            input_type, output_type = SourceText, ExtractedFacts
            nodes = (load, extract)
            edges = (EdgeSpec(START, load),
                     EdgeSpec(load, extract, raw_text),
                     EdgeSpec(extract, END))

    The DAG is DATA, not code — which is what lets `check()` and `diagram()` run with zero
    implementations and no engine. `build_pydantic_structure()` is the escape hatch for topologies
    the declarative form cannot express (`.map()` fan-out, `stream`, `BaseNode`); overriding it
    opts a design out of the edges-derived wiring, so `check_reachable` is skipped with a stated
    reason rather than silently passing.

    ⚠️ Skipped THERE, not everywhere. `render()` checks the built graph afterwards, so an override
    no longer costs reachability — and the `edges` declaration becomes a claim verified against
    the result rather than a decorative one. See `built.py`.
    """

    name: ClassVar[str] = ""
    nodes: ClassVar[tuple[NodeSpec, ...]] = ()
    joins: ClassVar[tuple[JoinSpec, ...]] = ()
    """Nodes that COMBINE arrivals. Separate from `nodes` because a strategy binds `nodes` and
    has nothing to bind here — a join carries its own reducer. Keeping them apart is what lets
    "a node is a role a strategy fills" stay true of every element of `nodes`."""
    decisions: ClassVar[tuple[DecisionSpec, ...]] = ()
    """Routers. Separate from `nodes` for the same reason as `joins`: there is no implementation
    to bind, so a strategy has nothing to say about one. Their branches are `edges` carrying
    `when=`, which keeps the topology in one place."""
    edges: ClassVar[tuple[EdgeSpec, ...]] = ()
    state_type: ClassVar[type] = type(None)
    deps_type: ClassVar[type] = type(None)
    input_type: ClassVar[type] = type(None)
    output_type: ClassVar[type] = type(None)

    # ── checking ────────────────────────────────────────────────────────────────────────────

    def check(self, strategy: StrategySpec | None = None) -> list[str]:
        """Every applicable check, as findings. Never raises.

        With no strategy: the design's own coherence — names, reachability, variables. Usable the
        moment `nodes` and `edges` are written, before anyone has implemented a single step.

        With a strategy: the above, plus bindings and implementations.

        ⚠️ One method, not two. There is no "check the design" / "check the strategy" split
        because the no-strategy case needs no placeholder graph — the declaration is already data.

        Recursion into subgraph bindings lives in `_check`, so nested designs can carry an
        ancestry path without that bookkeeping showing up in the public signature.
        """
        return self._check(strategy, ancestry=())

    def _check(self, strategy: StrategySpec | None,
               *, ancestry: tuple[tuple[type, int], ...]) -> list[str]:
        """`check()`, plus the path of (design, strategy) pairs already open above this one.

        ⚠️ This is the ONE place a cycle is detected. `check_subgraphs` deliberately does not
        also check — two owners of one rule is how a chain ends up either reported twice or, worse,
        reported by whichever ran first with the other's message.

        ⚠️ `id(strategy)` is safe as an identity key ONLY because every strategy in a chain is
        reachable from the root strategy's bindings for the whole walk, so none can be collected
        and have its id reused underneath us.
        """
        key = (type(self), id(strategy)) if strategy is not None else None
        if key is not None and key in ancestry:
            return [
                f"recursive subgraph binding: {self.name or type(self).__name__!r} with strategy "
                f"{strategy.name!r} appears inside its own subgraph chain. Rendering it would "
                f"build child graphs until the stack ran out — a design cannot implement one of "
                f"its own nodes with itself."]

        # ⚠️ `nodes + joins` where the question is "is this a declared ENDPOINT", `nodes` alone
        # where it is "is this a ROLE a strategy fills". Conflating the two is how a join ends up
        # demanding an implementation, or an unreachable join goes unreported.
        endpoints = (*self.nodes, *self.joins, *self.decisions)
        findings = list(checks.check_names(endpoints))
        findings += checks.check_variables(endpoints, self.edges)
        findings += checks.check_decisions(self.decisions, self.edges)
        findings += checks.check_step_arity(self.nodes, self.edges,
                                            decisions=self.decisions)
        if self._overrides_structure():
            findings.append(
                f"NOT CHECKED HERE — {type(self).__name__} overrides "
                f"build_pydantic_structure(), so its real topology is not the `edges` declaration "
                f"and cannot be verified from the declaration alone. `render()` verifies it "
                f"against the BUILT graph instead (`built.check_built_topology`), including that "
                f"every declared edge is honoured. So this is 'not from here', not 'not at all' — "
                f"but it does mean this design cannot be checked before it is implemented.")
        else:
            findings += checks.check_reachable(endpoints, self.edges)
        if strategy is not None:
            findings += checks.check_bindings(self.nodes, strategy)
            findings += checks.check_implementations(strategy)
            findings += checks.check_subgraphs(self, strategy, ancestry=(*ancestry, key))
        return findings

    def _overrides_structure(self) -> bool:
        return type(self).build_pydantic_structure is not GraphSpec.build_pydantic_structure

    # ── rendering ───────────────────────────────────────────────────────────────────────────

    def build_pydantic_structure(self, g: GraphBuilder, nodes: dict[NodeSpec, Any]) -> None:
        """Wire the graph. The default derives every edge from the `edges` declaration.

        Override ONLY for topologies the declarative form cannot express — `.map()` fan-out,
        `g.join()` collect. An override makes `edges` decorative for this class, which is why
        `check()` reports reachability as NOT CHECKED rather than passing it.
        """
        for e in self.edges:
            # ⚠️ A branch is NOT an ordinary edge. It is already attached to the Decision object
            # by `_build` via `g.match(...).to(...)`; adding it again here would wire the target
            # twice — once conditionally and once unconditionally, which is not a branch at all.
            if isinstance(e.source, DecisionSpec):
                continue
            src = g.start_node if isinstance(e.source, _Start) else nodes[e.source]
            dst = g.end_node if isinstance(e.target, _End) else nodes[e.target]
            builder = g.edge_from(src)
            label = e.label or (e.variable.name if e.variable else "")
            if label:
                builder = builder.label(label)
            # Verified (probe 2): one g.add() per edge produces topology identical to one
            # combined g.add(*edges).
            g.add(builder.to(dst))

    def _build(self, strategy: StrategySpec) -> Any:
        """The GraphBuilder dance. Builds and returns a real `pydantic_graph.Graph`."""
        g = GraphBuilder(
            # ⚠️ `name` passed explicitly. Unset, pydantic-graph infers a graph name from the
            # calling frame — and every arm reaches the engine through this one method, so every
            # arm of every design would end up named the same thing.
            name=f"{self.name or type(self).__name__}::{strategy.name}",
            state_type=self.state_type, deps_type=self.deps_type,
            input_type=self.input_type, output_type=self.output_type,
        )
        # ⛔ `node_id=node.name` is the single most important line in this file.
        #
        # Without it pydantic-graph derives a node's id from the bound function's `__name__`, so
        # node identity would belong to the STRATEGY rather than the DESIGN — two arms of one
        # design get disjoint node sets and a comparison has nothing to align on. Measured both
        # ways against pydantic-graph 2.35.1 in `docs/probe_api.py` (probes 5 and 5b).
        built: dict[Any, Any] = {
            node: g.step(self._step_body(node, strategy[node]),
                         node_id=node.name, label=node.name)
            for node in self.nodes}
        # ⚠️ A join is built with `g.join`, never `g.step`. Its reducer is
        # `(current, input) -> current`, and `g.step` would accept it and then call it with one
        # argument at run time — a declaration error surfacing as a TypeError from the engine.
        for j in self.joins:
            if j.initial_factory is not None:
                built[j] = g.join(j.reducer, initial_factory=j.initial_factory, node_id=j.name)
            else:
                built[j] = g.join(j.reducer, initial=j.initial, node_id=j.name)
        # ⚠️ Decisions are assembled AFTER steps and joins, because each branch names a target
        # that must already exist — and BEFORE the edges are wired, because `d.branch()` returns a
        # NEW Decision each time. The object other edges point at must be the final one, with
        # every branch already on it.
        for dec in self.decisions:
            node = g.decision(note=dec.note or None, node_id=dec.name)
            for e in self.edges:
                if e.source is not dec:
                    continue
                target = g.end_node if isinstance(e.target, _End) else built[e.target]
                node = node.branch(g.match(e.when).to(target))
            built[dec] = node

        self.build_pydantic_structure(g, built)
        return g.build()

    def _step_body(self, node: NodeSpec, binding: Any) -> Any:
        """One binding -> one native pydantic-graph step body.

        A callable is already one, and passes through untouched.

        A `SubgraphBinding` renders its own real `Graph` once, here, and is wrapped in a single
        async step body. So the parent keeps ONE node id for the role while the child stays a
        first-class design — independently runnable, checkable and diagrammable.

        ⚠️ The child gets the parent's exact `state` and `deps` objects, which is why
        `check_subgraphs` demands identical declared types. `.run()` and not `.run_sync()`: we are
        already inside a running loop, and `run_sync` says so by deadlocking.

        ⚠️ `binding` never sees `g`. A strategy can change what a node DOES and has no way to
        change what the design IS — that is structural drift prevented by construction rather than
        by review.
        """
        if not isinstance(binding, SubgraphBinding):
            return binding

        child = binding.graph.render(binding.strategy)

        async def run_subgraph(ctx: Any) -> Any:
            return await child.run(inputs=ctx.inputs, state=ctx.state, deps=ctx.deps)

        # Named, so a traceback from inside the child says which parent role it was filling.
        run_subgraph.__name__ = f"{node.name}__subgraph"
        run_subgraph.__qualname__ = f"{type(self).__name__}.{node.name}__subgraph"
        return run_subgraph

    def render(self, strategy: StrategySpec) -> Any:
        """Check the declaration, compile, then check what was COMPILED.

        ⚠️ Returns the RAW `Graph`, with no provenance wrapper. `eval_battle` takes
        `(spec, strategy_a, strategy_b)` directly, so it never needs to recover the strategy from a
        built graph. Nothing else should compare two bare `Graph` objects — there is no way to tell
        whether they came from one design.
        """
        findings = self.check(strategy)
        hard = [f for f in findings if not f.startswith("NOT CHECKED")]
        if hard:
            raise SpecError(
                f"{self.name or type(self).__name__} cannot be rendered with strategy "
                f"{strategy.name!r}:\n  " + "\n  ".join(hard))

        graph = self._build(strategy)

        # ⛔ THE SECOND HALF, and the one that works on designs the first half cannot read.
        #
        # Everything above walked the DECLARATION. A design overriding build_pydantic_structure()
        # wires itself in code, so that walk would be checking a fiction and `check()` reports
        # NOT CHECKED instead. Here there is a real Graph that knows its own topology, so the
        # same questions get real answers however it was wired — and the `edges` declaration
        # stops being decorative and becomes a claim that is verified against the result.
        built_findings = _built.check_built_topology(self, graph)
        built_findings += _built.check_declared_branches(self, graph)
        if built_findings:
            raise SpecError(
                f"{self.name or type(self).__name__} built with strategy {strategy.name!r}, and "
                f"the result does not match its declaration:\n  " + "\n  ".join(built_findings))
        return graph

    # ── drawing ─────────────────────────────────────────────────────────────────────────────

    def diagram(self, strategy: StrategySpec | None = None) -> str:
        """Mermaid for this design, from the declaration alone — no implementations needed."""
        return _diagram((*self.nodes, *self.joins, *self.decisions), self.edges,
                        title=self.name or type(self).__name__, strategy=strategy)

    def diff_diagram(self, a: StrategySpec, b: StrategySpec) -> str:
        """Mermaid showing what two strategies SHARE and where they differ.

        Has no equivalent in either library: two arms of one design render byte-identical mermaid
        from `Graph.render()`, because the built graph does not retain which strategy produced it.
        """
        return _diff_diagram((*self.nodes, *self.joins, *self.decisions), self.edges, a, b,
                             title=self.name or type(self).__name__)

    def varies(self, a: StrategySpec, b: StrategySpec) -> dict[str, tuple[str, str]]:
        """Which nodes are bound to different implementations. `{node: (a_impl, b_impl)}`.

        ⚠️ This, not a topology diff, is what varies between two arms of one design. Both render
        from the same `nodes`/`edges`, so their structures are identical BY CONSTRUCTION — a
        structural diff reports "nothing varies" on every pair. The experiment is in the bindings.
        """
        from workflow_workbench.diagram import impl_name
        return {n.name: (impl_name(a[n]), impl_name(b[n]))
                for n in self.nodes
                if n in a.bindings and n in b.bindings and a[n] is not b[n]}
