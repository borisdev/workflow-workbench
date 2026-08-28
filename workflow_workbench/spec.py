"""The declarative half: nodes, edges, and what fills them in.

    VariableSpec   a named, typed value that may flow along an edge
    NodeSpec       a semantic role with a typed contract — and no implementation
    EdgeSpec       source -> target, carrying one named variable
    StrategySpec   a complete NodeSpec -> implementation mapping

Nothing here imports `pydantic_graph`. A design must be readable, diffable and checkable without
an engine in the room; the engine appears only in `GraphSpec.render()`.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

__all__ = ["SpecError", "VariableSpec", "NodeSpec", "EdgeSpec", "StrategySpec",
           "START", "END", "Endpoint", "is_sentinel"]


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

    ⚠️ `variable` names WHICH declared value crosses this wire, and it is checked per-edge. A node
    with two outputs wired to two targets can have them swapped, and a check that merely aggregates
    "does the set of outputs match the set of consumed inputs" passes on the swap — verified before
    this type existed. See `checks.check_variables`.

    `variable=None` is legal and means "the edge carries whatever the source produced" — the
    ordinary single-output case, where naming it adds nothing to check.
    """

    source: Any                       # NodeSpec | _Start
    target: Any                       # NodeSpec | _End
    variable: VariableSpec | None = None
    label: str = ""

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


@dataclass(frozen=True)
class StrategySpec:
    """A complete NodeSpec -> implementation mapping. One competitor.

    Every node is bound explicitly, including the ones that did not change. Inheritance and
    partial overrides are deliberately absent: a partial strategy makes "what varies between these
    two arms" a question you answer by reading two files, which is the question a battle exists to
    answer for you.

    ⚠️ An implementation is a pydantic-graph step body — `async def f(ctx) -> Out` — taking
    exactly ONE argument. `checks.check_implementations` verifies that before `render()` builds.
    """

    name: str
    bindings: Mapping[NodeSpec, Callable[..., Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name:
            raise SpecError("a StrategySpec needs a name — it is what its numbers are filed under")

    def __getitem__(self, node: NodeSpec) -> Callable[..., Any]:
        return self.bindings[node]

    def __repr__(self) -> str:
        return f"StrategySpec({self.name!r}, {len(self.bindings)} bindings)"
