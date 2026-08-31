"""Producer, schema and TypeScript contract must describe the same document.

⛔ THIS TEST EXISTS BECAUSE THEY DRIFTED. `spec_payload` emitted `design_findings` for weeks while
the schema had never heard of it; `extra="forbid"` turned that into a 422 the first time a real
report was posted. Silent drift is the failure `.claude/rules/spec-as-code.md` names — three
descriptions of one shape, and nothing comparing them.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from workflow_workbench.payload import Binding, Edge, Layer, Node, Variable, WorkflowReport

TS = pathlib.Path(__file__).parent.parent / "frontend" / "workflow-workbench" / "src" / "contract.ts"

MODELS = {"Variable": Variable, "Node": Node, "Edge": Edge, "Binding": Binding,
          "Layer": Layer, "WorkflowReport": WorkflowReport}


def _ts_interface(name: str) -> str:
    src = TS.read_text()
    m = re.search(rf"export interface {name} \{{(.*?)\n\}}", src, re.S)
    assert m, f"contract.ts has no `export interface {name}`"
    return m.group(1)


@pytest.mark.parametrize("name", sorted(MODELS))
def test_every_python_field_exists_in_the_typescript_contract(name):
    """A field in one language only is a field somebody will silently stop sending."""
    body = _ts_interface(name)
    declared = set(re.findall(r"^\s*(\w+)\??:", body, re.M))
    missing = set(MODELS[name].model_fields) - declared
    assert not missing, f"{name}: in Python but not contract.ts -> {sorted(missing)}"


@pytest.mark.parametrize("name", sorted(MODELS))
def test_the_typescript_contract_declares_no_field_python_will_reject(name):
    """`extra="forbid"` means a TS-only field is a guaranteed 422 the first time it is sent."""
    body = _ts_interface(name)
    declared = set(re.findall(r"^\s*(\w+)\??:", body, re.M))
    extra = declared - set(MODELS[name].model_fields)
    assert not extra, f"{name}: in contract.ts but not Python -> {sorted(extra)}"


def test_the_real_producer_emits_something_the_schema_accepts():
    """The end-to-end version, over a REAL GraphSpec — this is what actually 422'd."""
    from workflow_workbench import END, START, EdgeSpec, GraphSpec, NodeSpec, StrategySpec, VariableSpec
    from workflow_workbench.devserver import spec_payload

    v = VariableSpec("v", str)
    a = NodeSpec("a", inputs=(v,), outputs=(v,))

    class S(GraphSpec):
        name = "s"
        input_type = output_type = str
        nodes = (a,)
        edges = (EdgeSpec(source=START, target=a, carries=v), EdgeSpec(source=a, target=END, carries=v))

    async def impl(ctx) -> str:
        return ctx.inputs

    payload = spec_payload(S(), [StrategySpec("x", {a: impl})])
    WorkflowReport.model_validate(payload)      # raises on any drift
