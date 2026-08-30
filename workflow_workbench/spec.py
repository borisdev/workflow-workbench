"""The declarative half: nodes, edges, and what fills them in.

    VariableSpec     a named, typed value that may flow along an edge
    NodeSpec         a semantic role with a typed contract — and no implementation
    EdgeSpec         source -> target, carrying one named variable
    JoinSpec         the one node kind that COMBINES several arrivals; no implementation to bind
    DecisionSpec     routes on the TYPE of the value; its branches are edges carrying `when=`
    MapEdgeSpec        fan out: the target runs once per item of the collection
    TransformEdgeSpec  a cheap synchronous reshape ON THE WIRE — no node, still declared
    SubgraphBinding  a whole child design, used as ONE node's implementation
    StrategySpec     a complete NodeSpec -> implementation mapping

Nothing here imports `pydantic_graph`. A design must be readable, diffable and checkable without
an engine in the room; the engine appears only in `GraphSpec.render()`.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from workflow_workbench.graph_spec import GraphSpec

__all__ = ["SpecError", "VariableSpec", "NodeSpec", "EdgeSpec", "MapEdgeSpec",
           "TransformEdgeSpec",
           "JoinSpec", "DecisionSpec", "SubgraphBinding", "StrategySpec", "START", "END",
           "Endpoint", "is_sentinel"]


class _Unset:
    """A seed sentinel. `None` cannot be it — `initial=None` is a legal seed for reduce_null."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "UNSET"


_UNSET = _Unset()


class SpecError(Exception):
    """A design that cannot be declared or rendered. Raised at declaration, never mid-run."""


class _Start:
    """The graph's entry. A class, not a bare `object()`, so `mypy` can narrow a
    `NodeSpec | _Start | _End` union — a bare sentinel makes every `edge.source` lookup unprovable."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "START"


class _End:
    """The graph's exit. See `_Start`."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "END"


START = _Start()
END = _End()

#: Anything an edge may connect. Narrows properly because the sentinels are real classes.
Endpoint = "NodeSpec | _Start | _End"


def is_sentinel(x: Any) -> bool:
    return isinstance(x, (_Start, _End))


@dataclass(frozen=True)
class VariableSpec:
    """A named, typed value that may flow along an edge.

    A Python type identifies the data structure but not its semantic role, and that gap is the
    whole reason this type exists. One step can produce two values of identical type:

        candidate_facts = VariableSpec("candidate_facts", list[Fact])
        rejected_facts  = VariableSpec("rejected_facts",  list[Fact])

    A verifier should consume `candidate_facts`. Type checking cannot tell you it was wired to
    `rejected_facts`, because both are `list[Fact]`. A NAME can.

    ⚠️ Value equality (unlike `NodeSpec`): two variables with the same name and type ARE the same
    variable, wherever they were written.
    """

    name: str
    type: type

    def __post_init__(self) -> None:
        if not self.name:
            raise SpecError("a VariableSpec needs a name — an unnamed variable is just a type")

    def __str__(self) -> str:
        return f"{self.name}: {getattr(self.type, '__name__', self.type)}"


@dataclass(frozen=True, eq=False)
class NodeSpec:
    """A semantic role with a typed contract. Deliberately implementation-free.

    ⛔ FOR A FUTURE AGENT: a `pydantic_graph.BaseNode` IS NOT THIS, and wrapping one here is a
    dead end, not a missing feature. A BaseNode's `run()` returns the NEXT NODE, so its topology
    lives inside its implementation — declared `edges` would be a lie it is free to ignore, and
    two arms binding different BaseNodes could be two different graphs while `diff_diagram()`
    drew them as one.

    ⚠️ Before concluding that costs anything: the three things BaseNode is actually USED for are
    all declarable, and `examples/ladder/stage10_no_basenode.py` does all three in one design.

        stop early   `EdgeSpec(gate, END, v, when=NotAPlan)` — their `End(...)`, as a branch
                     with no node on it
        go back      a branch to an earlier node. `_back_edges` knows it is not a fan-in
        dispatch     return a discriminating TYPE and branch on it with `when=`

    What is lost is the authoring style, plus one converter node wherever two paths reach the
    same step carrying different variables — a NodeSpec cannot declare "either of these". See
    `parity.py`.

    ## ⚠️ `eq=False` is load-bearing, not a style choice

    A `StrategySpec` keys its bindings on `NodeSpec`, so a NodeSpec is used as an IDENTITY. With
    the default value-equality of a frozen dataclass, two field-identical declarations collide:

        norm_a = NodeSpec("normalize", (text,), (text,))
        norm_b = NodeSpec("normalize", (text,), (text,))     # a copy/paste, or two designs

        StrategySpec("s", {norm_a: impl_a, norm_b: impl_b})      # len(bindings) == 1

    `impl_a` is destroyed at literal-construction time, before any check runs, and a completeness
    check CANNOT notice — `set(nodes)` and `set(bindings)` de-duplicate identically, so the counts
    match while a node silently holds the wrong implementation.

    `eq=False` restores identity semantics: each declaration is its own key, hashed by `id`.
    Verified in `docs/probe_api.py` probe 4.

    ⚠️ The cost: two NodeSpecs with the same NAME are now distinct keys, and `render()` uses
    `name` as the graph's node id. `check_names` therefore exists.
    """

    name: str
    inputs: tuple[VariableSpec, ...] = ()
    outputs: tuple[VariableSpec, ...] = ()
    streams: bool = False
    """This role is filled by an async GENERATOR, built with `g.stream` rather than `g.step`.

    ⚠️ Still a NodeSpec, not a StreamSpec — unlike a join or a decision, a stream IS a role a
    strategy fills, and it has exactly one implementation per arm. Giving it its own type would
    have split `nodes` into two kinds for no gain and made "a node is a role a strategy fills"
    false of one of them."""

    def __post_init__(self) -> None:
        if not self.name:
            raise SpecError("a NodeSpec needs a name — it becomes the node id in the graph")
        for side, vs in (("inputs", self.inputs), ("outputs", self.outputs)):
            if isinstance(vs, list):
                raise SpecError(
                    f"{self.name}.{side} is a list. It must be a tuple: a NodeSpec is hashed as a "
                    f"StrategySpec key, and a list field makes the whole declaration unhashable.")
            names = [v.name for v in vs]
            if len(names) != len(set(names)):
                raise SpecError(
                    f"{self.name} declares {side} twice under one name: {sorted(names)}. "
                    f"Two variables with one name cannot be told apart by anything downstream.")

    def __repr__(self) -> str:
        return (f"NodeSpec({self.name!r}, "
                f"({', '.join(str(v) for v in self.inputs)}) -> "
                f"({', '.join(str(v) for v in self.outputs)}))")


@dataclass(frozen=True)
class EdgeSpec:
    """One wire: `source -> target`, carrying `carries`.

    An edge is not an attribute bag — it is a small INSTRUCTION LIST for the executor, run after
    the source finishes and before the target starts. That is literally what it compiles to;
    pydantic-graph builds each one as a `Path` of markers:

        Path(items=[LabelMarker(label='handled'), DestinationMarker(destination_id='report')])

    The subclasses add instructions to that list:

        EdgeSpec           deliver what you were given
        MapEdgeSpec        deliver each ITEM of what you were given, one run per item
        TransformEdgeSpec  reshape it with a sync callable, then deliver that

    ⚠️ `carries` is REQUIRED, and was optional until it was measured: every edge in nobsmed's real
    design already named one, positionally. Only toy examples skipped it — and `check_variables`
    SKIPS an unnamed edge, so optional meant an edge nobody checked, silently. `0 FOUND` and
    `NOT CHECKED` rendering the same, one more time.

    ⚠️ `carries` names WHICH declared value crosses this wire, and it is checked PER EDGE. A node
    with two outputs wired to two targets can have them swapped, and a check that merely
    aggregates "is the set of outputs covered by the set of consumed inputs" passes on the swap.
    See `checks.check_variables`.

    ⚠️ `when` makes this edge a BRANCH of a `DecisionSpec` source: taken when the routed value is
    an instance of that type. Legal only on an edge leaving a decision, required on every edge
    that does — `check_decisions` enforces both.

    ⛔ FOR A FUTURE AGENT: do not add a `matches=` predicate field here. It looks like an obvious
    omission and is a refusal: a predicate on an edge is a decision the diagram cannot draw and
    `varies()` cannot compare. Return a discriminating TYPE from a step and branch on it with
    `when=` — `examples/ladder/stage9_decision.py` shows it, and the routing becomes a value you
    can see and battle instead of a lambda.

    ⚠️ A `transform=` field WAS refused on that same argument, and the argument was wrong. See
    `TransformEdgeSpec`: a reshape on the wire keeps every property that mattered — bound by a
    strategy, reported by `varies()`, checked against `delivers` — while emitting no node. What
    was actually wrong was insisting it be a NodeSpec, which puts a box on the canvas for
    something that is not a stage. Recorded because the shape of the mistake generalises: an
    invariant I had written ("strategies bind nodes") was defended as though it were a law.
    """

    source: Any                       # NodeSpec | DecisionSpec | _Start
    target: Any                       # NodeSpec | JoinSpec | DecisionSpec | _End
    carries: VariableSpec
    label: str = field(default="", kw_only=True)
    when: type | None = field(default=None, kw_only=True)

    @property
    def delivers(self) -> VariableSpec:
        """What ARRIVES at the target. Same as `carries` unless a subclass changes it.

        ⚠️ One property, where there used to be two fields under two names — `map_over` on the
        base and `produces` on the transform subclass, both meaning "what arrives when it differs
        from what left". Two words for one concept is `domain-language.md` rule 1, and I invented
        the second without noticing I had already invented the first.
        """
        return self.carries

    def __post_init__(self) -> None:
        if isinstance(self.source, _End):
            raise SpecError("an edge cannot start at END")
        if isinstance(self.target, _Start):
            raise SpecError("an edge cannot end at START")
        if self.source is self.target:
            raise SpecError(f"self-loop on {self.source!r}: an edge from a node to itself")
        if not isinstance(self.carries, VariableSpec):
            raise SpecError(
                f"edge {_ep_name(self.source)} -> {_ep_name(self.target)} must name what it "
                f"carries. An unnamed edge is skipped by `check_variables`, so it is not a "
                f"shorter declaration — it is an unchecked one.")

    def __repr__(self) -> str:
        # ⚠️ Must survive a half-built edge: `__post_init__` puts `{self!r}` in its own error
        # message, so a repr that assumes `delivers` is set replaces the real finding with an
        # AttributeError from inside the reporting.
        d = self.delivers
        arrives = "" if d is self.carries or d is None else f" -> {d.name}"
        return (f"{type(self).__name__}({_ep_name(self.source)} -> {_ep_name(self.target)}"
                f" [{self.carries.name}{arrives}])")


@dataclass(frozen=True, repr=False)
class MapEdgeSpec(EdgeSpec):
    """Fan out: `carries` is a collection, and the target runs ONCE PER `delivers`.

    ## The whole idea, in one shopping list

    You have a list. You have a step that handles ONE thing. Those do not fit:

        shopping = VariableSpec("shopping", list)    # ["milk", "eggs", "bread"]
        item     = VariableSpec("item", str)         # "milk"
        cost     = VariableSpec("cost", float)

        price = NodeSpec("price", inputs=(item,), outputs=(cost,))   # ONE item -> ONE price
        total = JoinSpec("total", reduce_sum, initial=0.0,
                         inputs=(cost,), outputs=(bill,))

        MapEdgeSpec(START, price, shopping, item)     # the list crosses, one item lands
        EdgeSpec(price, total, cost)
        EdgeSpec(total, END, bill)

    `price` never sees the list. It is called three times, once per item, and `total` adds up the
    three answers.

    ## Why not just loop inside the step

    You can, and then `price` declares `inputs=(shopping,)` — it takes a LIST. Three things are
    lost, and the first is the one that matters:

        the contract lies    "price" now means "price everything", and a reader of the design
                             cannot tell whether it handles one or many
        no concurrency       the engine cannot run the items in parallel; your loop is opaque
        no fan-out on the    the diagram draws one plain arrow, so nothing shows that the work
        picture              multiplies here

    The rule of thumb: **if a step handles one of something, say so in its contract, and let the
    edge do the multiplying.**

    ⚠️ Almost always paired with a `JoinSpec`. The fan-out makes N results; something has to put
    them back together, and a step cannot (it receives one value at a time).

    ⚠️ NOT needed for a broadcast or a multi-source fan-in. Measured: two edges out of one source
    build the same topology as an explicit `broadcast()`, and separate edges into one target are
    byte-identical to `edge_from(a, b).to(t)`.
    """

    delivers: VariableSpec = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.delivers, VariableSpec):
            raise SpecError(f"{self!r} needs `delivers` — the ITEM the target receives, which is "
                            f"not the collection on the wire.")


def _ep_name(ep: Any) -> str:
    return "START" if isinstance(ep, _Start) else "END" if isinstance(ep, _End) else ep.name


@dataclass(frozen=True, eq=False, repr=False)
class TransformEdgeSpec(EdgeSpec):
    """A cheap SYNCHRONOUS reshape that happens ON THE WIRE, creating no node.

        prune = TransformEdgeSpec(propose, cite, draft_graph, edge_list, apply=take_edges)

    `carries` is what leaves the source; `delivers` is what arrives at the target. In between,
    one sync callable. pydantic-graph builds this with `.transform()` and emits NO node for it —
    so the diagram draws it as a tag on the arrow, not as a stage.

    ## Why an edge and not a NodeSpec

    Because it is not a stage, and drawing it as one misleads. A workflow diagram a clinician
    reads should show the work, and `graph.edges` is not work — it is an accessor. But it is also
    not nothing: it happens on every run of every arm, so it must be visible, checkable, and
    comparable. An edge tag is all three; a box is one too many.

    ## Fixed, or a variation point — exactly one

        apply=fn        FIXED. Part of the design, like a JoinSpec's reducer. No strategy binds
                        it, and `varies()` will never mention it.
        apply=None      A VARIATION POINT. Every strategy must bind it, same rule as a node.

    ⚠️ Never both, never neither. "Neither" is a silently missing transform; "both" is a coin toss
    about which one wins. `checks.check_transform_edges` refuses either.

    ⚠️ This does NOT breach "every node is bound explicitly, no partial strategies". That rule
    exists so "what varies between these arms" is answerable without opening two files. An
    `apply=` transform is not partially bound — it is not a variation point at all. The rule it
    obeys is the one that matters: if it CAN vary, every arm states its position.

    ## Synchronous, and that is the whole constraint

    pydantic-graph's `TransformFunction` is `def __call__`, not `async def`, so a transform cannot
    await. Measured against 2.35.1: an async one is NOT rejected — it silently yields a coroutine
    object and warns "never awaited". So we refuse it at declaration instead.

    ⚠️ And be honest about the strength of that: sync does not mean cheap. `requests.get()` is
    sync and is very much work. It rules out the idiomatic async path, which is a strong
    convention in an async codebase, not a proof.

    ⚠️ Their docs do not explain `transform()` — it is absent from the builder page entirely, its
    docstrings are mechanical, and no PR or issue discusses it. Everything above about THEIR
    reasoning is inference from the code: the sync-only protocol, and `TransformMarker` sitting
    beside `LabelMarker` rather than beside a node type. Do not cite it back as theirs.
    """

    delivers: VariableSpec = None  # type: ignore[assignment]
    apply: Callable[..., Any] | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.delivers, VariableSpec):
            raise SpecError(
                f"{self!r} needs `delivers` — the variable that ARRIVES at the target. Without it "
                f"the transform's output is undeclared, so nothing can check what it returns and "
                f"the diagram cannot say what crosses the second half of the wire.")
        if self.apply is not None and not callable(self.apply):
            raise SpecError(f"{self!r}: `apply` must be callable")

    def __repr__(self) -> str:
        how = getattr(self.apply, "__name__", "bound by strategy") if self.apply else "unbound"
        arrives = self.delivers.name if self.delivers is not None else "?"
        return (f"TransformEdgeSpec({_ep_name(self.source)} -> {_ep_name(self.target)}"
                f" [{self.carries.name} -> {arrives}], {how})")


@dataclass(frozen=True, eq=False)
class JoinSpec:
    """The one thing that can combine several arrivals into one value.

    A step body is `(ctx) -> Out` and receives exactly ONE value, so a node fed by two edges is
    invoked twice and one result is discarded — silently, until `check_step_arity` existed. A
    reducer is `(current, input) -> current`, which is the shape that can actually accumulate.

        squares = JoinSpec("squares", reduce_list_append, initial_factory=list,
                           inputs=(square,), outputs=(all_squares,))

    ⚠️ A join is NOT a `NodeSpec` and lives in `GraphSpec.joins`, not `nodes`. It has no
    implementation, so a `StrategySpec` has nothing to bind for it and `varies()` can never report
    it. Putting it in `nodes` would make "a node is a role a strategy fills" false, and every
    caller of `nodes` would need to ask what kind of thing it just got.

    ⚠️ It IS a declared endpoint, so edges may reference it and `check_reachable` can see it. That
    is the improvement over hand-wiring one in `build_pydantic_structure()`: before this type, a
    join could only be reached by overriding that method, which turns reachability checking off
    for the entire design.

    `eq=False` for the same reason as `NodeSpec`: identity, not field equality, so two
    field-identical declarations stay two distinct joins.
    """

    name: str
    reducer: Callable[..., Any]
    initial: Any = _UNSET
    initial_factory: Callable[[], Any] | None = None
    inputs: tuple[VariableSpec, ...] = ()
    outputs: tuple[VariableSpec, ...] = ()

    def __post_init__(self) -> None:
        if not self.name:
            raise SpecError("a JoinSpec needs a name — it becomes the node id in the graph")
        if not callable(self.reducer):
            raise SpecError(
                f"{self.name}.reducer is not callable. A join reduces with "
                f"`(current, input) -> current`; pydantic_graph.join ships reduce_sum, "
                f"reduce_list_append, reduce_list_extend and reduce_dict_update.")
        if (self.initial is _UNSET) == (self.initial_factory is None):
            raise SpecError(
                f"{self.name} needs exactly one of `initial=` or `initial_factory=`. "
                f"⚠️ Use `initial_factory` for a MUTABLE seed — `initial=[]` is built once at "
                f"declaration and shared by every run of the graph, so one run's results leak "
                f"into the next.")

    def __repr__(self) -> str:
        seed = "initial_factory" if self.initial_factory is not None else f"initial={self.initial!r}"
        return f"JoinSpec({self.name!r}, {getattr(self.reducer, '__name__', self.reducer)}, {seed})"


@dataclass(frozen=True, eq=False)
class DecisionSpec:
    """A router. Sends the value down one branch, chosen by its TYPE.

        route = DecisionSpec("route", note="urgent or not")

        edges = (EdgeSpec(triage, route, verdict),
                 EdgeSpec(route, escalate, urgent,  when=Urgent),
                 EdgeSpec(route, research, routine, when=Routine))

    ⚠️ Like `JoinSpec`, it has NO implementation and lives in `decisions`, not `nodes`. There is no
    body to write — the routing IS the declaration. A strategy binds nothing for it, so two arms
    can differ in every step and still be guaranteed to route identically, which is what makes a
    battle over a branching design mean anything.

    ⚠️ Its absence was costing the most of anything on the capability matrix. Before it, a design
    that routed conditionally could only be built by overriding `build_pydantic_structure()` —
    which reports reachability as NOT CHECKED for the whole design. Every branching workflow was
    therefore entirely unchecked.

    ⚠️ Branches are EXCLUSIVE, and that is measured rather than assumed: a node downstream of two
    branches runs ONCE, not once per branch. `check_step_arity` has to know it, or it reports
    every branching design as a fan-in defect.
    """

    name: str
    note: str = ""
    inputs: tuple[VariableSpec, ...] = ()
    outputs: tuple[VariableSpec, ...] = ()

    def __post_init__(self) -> None:
        if not self.name:
            raise SpecError("a DecisionSpec needs a name — it becomes the node id in the graph")

    def __repr__(self) -> str:
        note = f", {self.note!r}" if self.note else ""
        return f"DecisionSpec({self.name!r}{note})"


@dataclass(frozen=True)
class SubgraphBinding:
    """A whole child design — `GraphSpec` + `StrategySpec` — used as ONE node's implementation.

    The parent still sees one `NodeSpec` with one node id. Internally that role is filled by
    another checked design, which stays independently runnable, checkable and diagrammable.

        fancy = StrategySpec("fancy", {extract: SubgraphBinding(VerifiedExtraction(), verified)})

    ⚠️ This is NOT a second execution abstraction, and adding one was the tempting mistake. There
    is no MultiStep and no nested runner: `graph.render(strategy)` produces an ordinary
    `pydantic_graph.Graph`, and the parent step body simply `await`s it. Everything that already
    knows how to run a graph runs this too.

    ⚠️ The child receives the parent's EXACT `state` and `deps` objects, so their declared types
    must be identical — `checks.check_subgraphs` enforces that. No projection, no field matching,
    no copying: each of those makes "who owns this mutation" a question the types stop answering,
    and none of them has a caller yet. An explicit adapter can be added when one does.

    ⚠️ A binding never receives the parent's `GraphBuilder`. That is what makes parent structural
    drift impossible by construction rather than by review: a strategy can change what a node
    DOES, and has no way to change what the design IS.
    """

    graph: GraphSpec
    strategy: StrategySpec

    def __repr__(self) -> str:
        name = self.graph.name or type(self.graph).__name__
        return f"SubgraphBinding({name}::{self.strategy.name})"


@dataclass(frozen=True)
class StrategySpec:
    """A complete NodeSpec -> implementation mapping. One competitor.

    Every node is bound explicitly, including the ones that did not change. Inheritance and
    partial overrides are deliberately absent: a partial strategy makes "what varies between these
    two arms" a question you answer by reading two files, which is the question a battle exists to
    answer for you.

    An implementation is one of exactly two things:

        a callable          a pydantic-graph step body — `async def f(ctx) -> Out`, ONE argument.
                            `checks.check_implementations` verifies that before `render()` builds.
        a SubgraphBinding   a complete child design filling this one role.

    ⚠️ Both are checked, but by different functions, because their faults are different kinds of
    fault. A callable's is local — wrong shape, not callable. A subgraph's is RELATIONAL: whether
    it fits depends on the parent node it is bound to, which a strategy alone cannot know. So
    `check_implementations` skips subgraphs and `check_subgraphs` (which is handed the parent)
    owns them.
    """

    name: str
    bindings: Mapping[NodeSpec, Callable[..., Any] | SubgraphBinding] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name:
            raise SpecError("a StrategySpec needs a name — it is what its numbers are filed under")

    def __getitem__(self, node: NodeSpec) -> Callable[..., Any] | SubgraphBinding:
        return self.bindings[node]

    def __repr__(self) -> str:
        return f"StrategySpec({self.name!r}, {len(self.bindings)} bindings)"
