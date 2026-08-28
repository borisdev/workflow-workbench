"""The wire contract: one definition, used by the producer AND the viewer.

⚠️ THIS MODULE IMPORTS ONLY PYDANTIC. Not `graph_spec`, not `spec`, not `pydantic_graph`.

That is the actual rule, and it is narrower than "the viewer imports nothing of ours" — which is
what an earlier version of this docstring claimed and is too severe. Sharing the SCHEMA is exactly
right: it is one definition, so a producer cannot emit a shape the viewer does not accept, and the
viewer cannot quietly start reading a field nobody writes.

What must NOT be shared is the ENGINE. If this module imported `GraphSpec`, hosting the viewer
would mean installing pydantic-graph, and a report could only be rendered somewhere that can also
build graphs. The dependency the split protects is on the engine, not on the vocabulary.

    producer  builds a WorkflowReport  ──JSON──>  viewer  parses a WorkflowReport
              (has the engine)                           (has only this file + pydantic)
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = ["Variable", "Node", "Edge", "Binding", "Layer", "WorkflowReport", "START_ID", "END_ID"]

START_ID = "__start__"
END_ID = "__end__"


class Variable(BaseModel):
    """A named, typed value flowing along an edge."""

    model_config = ConfigDict(extra="forbid")
    name: str
    type: str = ""


class Node(BaseModel):
    """One stage of the design."""

    model_config = ConfigDict(extra="forbid")
    id: str
    kind: str = "step"
    inputs: list[Variable] = Field(default_factory=list)
    outputs: list[Variable] = Field(default_factory=list)


class Edge(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = ""
    source: str
    target: str
    variable: str | None = None
    type: str | None = None


class Binding(BaseModel):
    """What one strategy puts in one stage.

    ⚠️ `skipped` and `unbound` are DIFFERENT and both are explicit. Skipped means this arm
    deliberately does not run the stage; unbound means nobody wired it. `.claude/rules/checks.md`
    — NOT CHECKED and 0 FOUND must never render the same, and the same applies here to
    "chose not to" and "forgot to".
    """

    model_config = ConfigDict(extra="forbid")
    impl: str | None = None
    skipped: bool = False
    unbound: bool = False
    file: str = ""
    line: int = 0
    code: str = ""

    @model_validator(mode="after")
    def _coherent(self) -> Binding:
        if self.skipped and self.unbound:
            raise ValueError("a binding cannot be both skipped and unbound — they are opposite "
                             "claims: one is a decision, the other is an omission")
        if self.impl is None and not self.unbound:
            raise ValueError("a binding with no `impl` must set unbound=True, or it reads as a "
                             "stage nobody has an opinion about")
        return self


class Layer(BaseModel):
    """One strategy over the design: its bindings, and anything measured about it.

    `latency` and `scores` are optional and default to None rather than to {} — absent means
    NOBODY MEASURED, which the viewer must render as "not reported" rather than as a zero.
    """

    model_config = ConfigDict(extra="forbid")
    name: str
    bindings: dict[str, Binding] = Field(default_factory=dict)
    latency: dict[str, float] | None = None
    scores: dict[str, float] | None = None
    findings: list[str] = Field(default_factory=list)
    ok: bool = True


class WorkflowReport(BaseModel):
    """The whole payload. This is the contract between any producer and the viewer."""

    model_config = ConfigDict(extra="forbid")
    name: str = "workflow report"
    input_type: str = ""
    output_type: str = ""
    nodes: list[Node]
    edges: list[Edge]
    layers: list[Layer] = Field(default_factory=list)
    noise_floor: dict[str, float] | None = None
    """The bar a delta must clear to mean anything. None means no replicate ran — which the viewer
    must SAY, because without it no number on the page is known to be a result."""
    mermaid: str = ""
    meta: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _referential_integrity(self) -> WorkflowReport:
        ids = [n.id for n in self.nodes]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"two nodes share an id: {sorted(dupes)}")
        known = set(ids) | {START_ID, END_ID}
        for e in self.edges:
            for side, val in (("source", e.source), ("target", e.target)):
                if val not in known:
                    raise ValueError(
                        f"edge.{side} is {val!r}, which is not a declared node id. "
                        f"Known: {sorted(known)}")
        for layer in self.layers:
            for node_id in layer.bindings:
                if node_id not in set(ids):
                    raise ValueError(
                        f"layer {layer.name!r} binds {node_id!r}, which is not a declared node")
            for field in ("latency", "scores"):
                got = getattr(layer, field)
                if field == "latency" and got:
                    for node_id in got:
                        if node_id not in set(ids):
                            raise ValueError(
                                f"layer {layer.name!r} reports latency for {node_id!r}, "
                                f"which is not a declared node")
        return self
