"""The dev server serves the DECLARATION — no engine, no build, no run."""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from graph_strategies import END, START, EdgeSpec, GraphSpec, NodeSpec, StrategySpec, VariableSpec
from graph_strategies.devserver import build_app, spec_payload

v = VariableSpec("v", str)
a = NodeSpec("a", inputs=(v,), outputs=(v,))
b = NodeSpec("b", inputs=(v,), outputs=(v,))


class S(GraphSpec):
    name = "s"
    input_type = output_type = str
    nodes = (a, b)
    edges = (EdgeSpec(START, a, v), EdgeSpec(a, b, v), EdgeSpec(b, END, v))


async def one(ctx) -> str:
    return ctx.inputs


async def two(ctx) -> str:
    return ctx.inputs + "!"


async def skip(ctx) -> str:
    return ctx.inputs


x = StrategySpec("x", {a: one, b: skip})
y = StrategySpec("y", {a: two, b: skip})


def client():
    return TestClient(build_app({"s": (S(), [x, y])}))


def test_payload_is_react_flow_shaped():
    d = spec_payload(S(), [x, y])
    assert [n["id"] for n in d["nodes"]] == ["a", "b"]
    e = d["edges"][0]
    assert {"id", "source", "target", "variable"} <= set(e)
    assert e["source"] == "__start__"


def test_layers_carry_bindings_and_source():
    d = spec_payload(S(), [x, y])
    names = [l["name"] for l in d["layers"]]
    assert names == ["x", "y"]
    binding = d["layers"][0]["bindings"]["a"]
    assert binding["impl"] == "one"
    assert "async def one" in binding["code"]
    assert binding["line"] > 0


def test_a_skipped_stage_is_marked_distinctly_from_unbound():
    """`checks.md`: NOT CHECKED and 0 FOUND must never render the same."""
    d = spec_payload(S(), [x])
    assert d["layers"][0]["bindings"]["b"]["skipped"] is True
    assert d["layers"][0]["bindings"]["b"]["unbound"] is False

    partial = StrategySpec("partial", {a: one})
    d2 = spec_payload(S(), [partial])
    assert d2["layers"][0]["bindings"]["b"]["unbound"] is True
    assert d2["layers"][0]["ok"] is False


def test_routes():
    c = client()
    assert c.get("/").status_code == 200
    assert c.get("/spec/s").status_code == 200
    assert c.get("/spec/s/data").status_code == 200
    assert c.get("/spec/nope/data").status_code == 404


def test_the_page_points_at_the_json_endpoint():
    """The island contract: HTML is a shell, the data comes from a url. Swapping mermaid for
    React Flow must not mean re-deriving the payload."""
    html = client().get("/spec/s").text
    assert "/data" in html
    assert "layers" in html
