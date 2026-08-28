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
    EdgeSpec,
    NodeSpec,
    SpecError,
    StrategySpec,
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
    the declarative form cannot express (fan-out via `.map()`, joins); overriding it opts a design
    out of the edges-derived wiring, and `check_reachable` is skipped with a stated reason rather
    than silently passing.
    """

    name: ClassVar[str] = ""
    nodes: ClassVar[tuple[NodeSpec, ...]] = ()
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
        """
        findings = list(checks.check_names(self.nodes))
        findings += checks.check_variables(self.nodes, self.edges)
        if self._overrides_structure():
            findings.append(
                f"NOT CHECKED — {type(self).__name__} overrides build_pydantic_structure(), so its "
                f"real topology is not the `edges` declaration and reachability was not verified. "
                f"This is a stated gap, not a pass.")
        else:
            findings += checks.check_reachable(self.nodes, self.edges)
        if strategy is not None:
            findings += checks.check_bindings(self.nodes, strategy)
            findings += checks.check_implementations(strategy)
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
        built = {node: g.step(strategy[node], node_id=node.name, label=node.name)
                 for node in self.nodes}
        self.build_pydantic_structure(g, built)
        return g.build()

    def render(self, strategy: StrategySpec) -> Any:
        """Check, then compile to a real `pydantic_graph.Graph`.

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
        return self._build(strategy)

    # ── drawing ─────────────────────────────────────────────────────────────────────────────

    def diagram(self, strategy: StrategySpec | None = None) -> str:
        """Mermaid for this design, from the declaration alone — no implementations needed."""
        return _diagram(self.nodes, self.edges,
                        title=self.name or type(self).__name__, strategy=strategy)

    def diff_diagram(self, a: StrategySpec, b: StrategySpec) -> str:
        """Mermaid showing what two strategies SHARE and where they differ.

        Has no equivalent in either library: two arms of one design render byte-identical mermaid
        from `Graph.render()`, because the built graph does not retain which strategy produced it.
        """
        return _diff_diagram(self.nodes, self.edges, a, b,
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
