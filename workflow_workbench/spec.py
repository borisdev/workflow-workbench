"""The declarative half: nodes, edges, and what fills them in.

    VariableSpec     a named, typed value that may flow along an edge
    NodeSpec         a semantic role with a typed contract — and no implementation
    EdgeSpec         source -> target, carrying one named variable
    JoinSpec         the one node kind that COMBINES several arrivals; no implementation to bind
    DecisionSpec     routes on the TYPE of the value; its branches are edges carrying `when=`
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

__all__ = ["SpecError", "VariableSpec", "NodeSpec", "EdgeSpec", "JoinSpec",
           "DecisionSpec", "SubgraphBinding", "StrategySpec", "START", "END",
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
    drew them as one. If someone wants a retry loop (the usual reason), route BACKWARDS with a
    `DecisionSpec` instead; `tests/test_subgraph.py` has a worked one. See `parity.py`.

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
    """One wire: `source -> target`, carrying `variable`.

    ⛔ FOR A FUTURE AGENT: do not add a `transform=` or a `matches=` field here. Both have been
    considered and REFUSED, and both look like obvious omissions until you see why:

        a callable on an edge is an IMPLEMENTATION living in the declaration. `diagram()` cannot
        draw what it does, `varies()` cannot compare two of them, and `check_variable_types`
        cannot check it. The declaration would then contain a step nobody can see.

    If the reshaping matters it is a stage — give it a `NodeSpec`. If it does not, do it at the
    top of the consuming step body. For routing, return a discriminating TYPE from a step and
    branch on it with `when=`. See `parity.py`, which is where this is written down for users.

    ⚠️ `variable` names WHICH declared value crosses this wire, and it is checked per-edge. A node
    with two outputs wired to two targets can have them swapped, and a check that merely aggregates
    "does the set of outputs match the set of consumed inputs" passes on the swap — verified before
    this type existed. See `checks.check_variables`.

    `variable=None` is legal and means "the edge carries whatever the source produced" — the
    ordinary single-output case, where naming it adds nothing to check.

    ⚠️ `when` is what makes this edge a BRANCH of a `DecisionSpec`: it is taken when the routed
    value is an instance of that type. Only legal on an edge leaving a DecisionSpec, and required
    on every edge that leaves one — `check_decisions` enforces both, since a branchless decision
    routes nowhere and a conditionless edge out of one cannot be built.

    ⚠️ The condition lives on the EDGE, not inside the DecisionSpec, on purpose: `edges` stays the
    single place the topology is written down, so `check_reachable` and `diagram()` keep working
    on branching designs without knowing decisions exist.

    ⚠️ `map_over` fans this edge out: `variable` is the COLLECTION on the wire, `map_over` is the
    ITEM the target receives, and the target runs once per item. pydantic-graph's `.map()`, as
    data rather than a call, so a fan-out design stays declared instead of hand-wired.

        EdgeSpec(START, square, numbers, map_over=number)   # carries `numbers`, square gets one
        JoinSpec("total", reduce_sum, initial=0, ...)       # and the join collects them

    ⛔ It names the item because a bool was not enough, and running it is what showed that. With
    `map_over=True` the edge carried `numbers` while `square` declared `number`, and
    `check_variables` — correctly — called that a wiring error. Naming both ends keeps BOTH sides
    checked: the source really produces the collection, and the target really consumes the item.

    ⚠️ NOT needed for a broadcast or a multi-source fan-in. Measured: two edges out of one source
    build the same topology as an explicit `broadcast()` (only the fork node's generated name
    differs), and separate edges into one target are byte-identical to `edge_from(a, b).to(t)`.
    Adding vocabulary for either would have been vocabulary for nothing.
    """

    source: Any                       # NodeSpec | DecisionSpec | _Start
    target: Any                       # NodeSpec | JoinSpec | DecisionSpec | _End
    variable: VariableSpec | None = None
    label: str = ""
    when: type | None = None
    map_over: VariableSpec | None = None

    def __post_init__(self) -> None:
        if isinstance(self.source, _End):
            raise SpecError("an edge cannot start at END")
        if isinstance(self.target, _Start):
            raise SpecError("an edge cannot end at START")
        if self.source is self.target:
            raise SpecError(f"self-loop on {self.source!r}: an edge from a node to itself")

    def __repr__(self) -> str:
        v = f" [{self.variable.name}]" if self.variable else ""
        return f"EdgeSpec({_ep_name(self.source)} -> {_ep_name(self.target)}{v})"


def _ep_name(ep: Any) -> str:
    return "START" if isinstance(ep, _Start) else "END" if isinstance(ep, _End) else ep.name


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
