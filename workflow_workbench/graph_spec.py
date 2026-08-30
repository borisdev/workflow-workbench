"""`GraphSpec` — one fixed design — and `render(strategy)`, which fills it in.

    jinja_template.render(values)      values fill the placeholders
    graph_spec.render(strategy)        a strategy fills the nodes

The GraphSpec owns the DAG, declared as data (`nodes` + `edges`). A StrategySpec supplies every
implementation. Rendering produces a real `pydantic_graph.Graph`.
"""
from __future__ import annotations

from typing import Any, ClassVar

from pydantic_graph import GraphBuilder

from workflow_workbench import checks
from workflow_workbench.diagram import diagram as _diagram, diff_diagram as _diff_diagram
from workflow_workbench.spec import (
    DecisionSpec,
    EdgeSpec,
    MapEdgeSpec,
    TransformEdgeSpec,
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
    implementations and no engine.

    ⛔ There is exactly ONE way a graph comes into existence here: `edges` is compiled by `_wire`.
    No hook, no override, no escape hatch. That is what makes every check meaningful — a
    declaration that something else could quietly contradict is a decoration, and for a while
    this class had exactly that.

    ⛔ FOR A FUTURE AGENT: do not re-add a `build_pydantic_structure()` hook. It existed until
    2026-08-30 and was deleted on purpose along with ~450 lines that existed only to police it
    (`built.py`, a NOT CHECKED finding, a ladder rung, a test module). Re-adding it makes `edges`
    decorative again for anything that uses it. `test_there_is_no_wiring_hook_to_override` guards
    this, and guards the nastier half: a subclass defining that method has NO EFFECT rather than
    erroring, so nobody would notice.

    If a design genuinely cannot be declared, that is the answer: `render()` returns a real
    `pydantic_graph.Graph` — take it and use their API directly.
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
        findings += checks.check_reachable(endpoints, self.edges)
        findings += checks.check_transform_edges(self.edges, strategy)
        findings += checks.check_fan_out_rejoins(endpoints, self.edges)
        if strategy is not None:
            findings += checks.check_bindings(self._bindables(), strategy)
            findings += checks.check_implementations(strategy)
            findings += checks.check_variable_types(self, strategy)
            findings += checks.check_subgraphs(self, strategy, ancestry=(*ancestry, key))
        return findings

    def _bindables(self) -> tuple[Any, ...]:
        """Everything a strategy must bind: nodes, plus transform edges left open.

        ⚠️ Not `nodes`. A variation point is defined by the design leaving an implementation OPEN,
        not by where it is declared — a `TransformEdgeSpec` with no `apply=` is one, and it lives
        in `edges`.
        """
        open_transforms = tuple(e for e in self.edges
                                if isinstance(e, TransformEdgeSpec) and e.apply is None)
        return (*self.nodes, *open_transforms)

    # ── rendering ───────────────────────────────────────────────────────────────────────────

    def _wire(self, g: GraphBuilder, nodes: dict[Any, Any],
              strategy: StrategySpec) -> None:
        """Every edge, derived from the `edges` declaration. There is no other way to wire.

        ⛔ THIS IS PRIVATE, and that is the design. There was a public
        `build_pydantic_structure()` here, overridable for topologies the declaration could not
        express — and it was the ONLY way a built graph could differ from its declaration. Which
        meant `edges` was decorative for any class that used it, `diagram()` would draw a picture
        the graph did not match, and reachability was reported NOT CHECKED for the whole design
        because walking a declaration that no longer built anything would have been checking a
        fiction.

        It was removed once nothing needed it: `map`, `stream`, `transform`, joins, decisions,
        broadcasts and fan-in are all declarable now. What is left is the `BaseNode` API, which
        cannot be declared because a BaseNode returns its own successor — and the `matches=`
        predicate form of a branch, which is refused rather than missing.

        If you need those, `render()` hands you a real `pydantic_graph.Graph`: take it and use
        their API directly. A workbench that can express everything is just the engine with extra
        steps.
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
            builder = builder.label(e.label or e.carries.name)
            if isinstance(e, MapEdgeSpec):
                # fan out: the target runs once per item of the collection on this edge
                builder = builder.map()
            if isinstance(e, TransformEdgeSpec):
                # ⚠️ `.transform()` emits NO node. That is the point: a reshape is not a stage,
                # so it appears as a tag on the arrow rather than a box on the canvas.
                builder = builder.transform(e.apply if e.apply is not None else strategy[e])
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
        built: dict[Any, Any] = {}
        for node in self.nodes:
            # ⚠️ `g.stream` for a generator role, `g.step` otherwise. Passing an async generator
            # to `g.step` is accepted and then fails at call time, attributed to the engine.
            make = g.stream if node.streams else g.step
            built[node] = make(self._step_body(node, strategy[node]),
                               node_id=node.name, label=node.name)
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

        self._wire(g, built, strategy)
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

        # ⚠️ There was a post-build pass here (`built.check_built_topology`) that walked the
        # compiled graph and verified the declaration against it. It went when
        # `build_pydantic_structure()` did: with every graph wired from `edges`, the built
        # topology cannot disagree with the declaration, so those checks could never go red
        # again. `.claude/rules/checks.md` — a check that cannot fail is decoration.
        return self._build(strategy)

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

        def label(spec: Any) -> str:
            if isinstance(spec, TransformEdgeSpec):
                src = "START" if isinstance(spec.source, _Start) else spec.source.name
                dst = "END" if isinstance(spec.target, _End) else spec.target.name
                return f"{src}->{dst}"
            return spec.name

        # ⚠️ Transform edges are here too, because an arm may reshape a value differently — and a
        # difference nobody can see is the one that ruins a comparison.
        return {label(n): (impl_name(a[n]), impl_name(b[n]))
                for n in self._bindables()
                if n in a.bindings and n in b.bindings and a[n] is not b[n]}
