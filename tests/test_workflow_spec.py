"""Tests. Where rendering is involved, they run against a REAL `pydantic_graph.Graph`.

⚠️ A test that only asserts a string appears in a declaration has not tested the design. The
render/run tests here build and execute real graphs, because the failures that matter — divergent
node ids, a swapped variable, an unbound node — are all invisible to a declaration-only assertion.
"""
from __future__ import annotations

import pytest

from workflow_workbench import (
    END,
    START,
    EdgeSpec,
    GraphSpec,
    NodeSpec,
    SpecError,
    StrategySpec,
    VariableSpec,
    check_bindings,
    check_implementations,
    check_names,
    check_reachable,
    check_variables,
)

text = VariableSpec("text", str)
other = VariableSpec("other", str)

load = NodeSpec("load", inputs=(text,), outputs=(text,))
parse = NodeSpec("parse", inputs=(text,), outputs=(text,))


class Linear(GraphSpec):
    name = "linear"
    input_type, output_type = str, str
    nodes = (load, parse)
    edges = (EdgeSpec(source=START, target=load, carries=text), EdgeSpec(source=load, target=parse, carries=text), EdgeSpec(source=parse, target=END, carries=text))


async def load_a(ctx) -> str:
    return f"a:{ctx.inputs}"


async def load_b(ctx) -> str:
    return f"b:{ctx.inputs}"


async def parse_up(ctx) -> str:
    return ctx.inputs.upper()


arm_a = StrategySpec("arm_a", {load: load_a, parse: parse_up})
arm_b = StrategySpec("arm_b", {load: load_b, parse: parse_up})


# ── spec types ──────────────────────────────────────────────────────────────────────────────

def test_field_identical_nodes_do_not_collide_as_dict_keys():
    """`eq=False`: two copy-pasted declarations must stay distinct, or one silently overwrites
    the other's implementation inside a StrategySpec literal."""
    n1 = NodeSpec("same", (text,), (text,))
    n2 = NodeSpec("same", (text,), (text,))
    assert n1 != n2
    assert len({n1: 1, n2: 2}) == 2


def test_variables_are_value_equal():
    assert VariableSpec("x", str) == VariableSpec("x", str)


def test_list_inputs_refused():
    with pytest.raises(SpecError, match="must be a tuple"):
        NodeSpec("bad", inputs=[text])


def test_edge_cannot_start_at_end_or_end_at_start():
    with pytest.raises(SpecError):
        EdgeSpec(source=END, target=load, carries=text)
    with pytest.raises(SpecError):
        EdgeSpec(source=load, target=START, carries=text)


def test_self_loop_refused():
    with pytest.raises(SpecError, match="self-loop"):
        EdgeSpec(source=load, target=load, carries=text)


# ── checks ──────────────────────────────────────────────────────────────────────────────────

def test_check_names_catches_two_nodes_one_name():
    dup = NodeSpec("load", (text,), (text,))
    assert check_names((load, dup))
    assert not check_names((load, parse))


def test_check_reachable_finds_an_orphan():
    orphan = NodeSpec("orphan")
    findings = check_reachable((load, parse, orphan), Linear.edges)
    assert any("orphan" in f and "unreachable" in f for f in findings)


def test_check_reachable_terminates_on_a_cycle():
    a, b = NodeSpec("a", outputs=(text,)), NodeSpec("b", inputs=(text,), outputs=(text,))
    edges = (EdgeSpec(source=START, target=a, carries=text), EdgeSpec(source=a, target=b, carries=text), EdgeSpec(source=b, target=a, carries=text), EdgeSpec(source=b, target=END, carries=text))
    check_reachable((a, b), edges)          # must return, not hang


def test_check_reachable_flags_an_undeclared_node():
    ghost = NodeSpec("ghost")
    edges = (*Linear.edges, EdgeSpec(source=parse, target=ghost, carries=text))
    assert any("not in `nodes`" in f for f in check_reachable((load, parse), edges))


def test_check_variables_catches_a_swap_that_set_comparison_cannot():
    """⛔ THE REGRESSION FOR THE PER-EDGE CHECK.

    Both variables are produced, both consumed, every SET matches — and the wiring is swapped.
    An aggregate check passes here; only a per-edge one fails.
    """
    a, b = VariableSpec("a", str), VariableSpec("b", str)
    split = NodeSpec("split", outputs=(a, b))
    ca = NodeSpec("consume_a", inputs=(a,))
    cb = NodeSpec("consume_b", inputs=(b,))
    swapped = (EdgeSpec(source=split, target=ca, carries=b), EdgeSpec(source=split, target=cb, carries=a))       # ⛔ crossed

    findings = check_variables((split, ca, cb), swapped)
    assert findings, "the swap was not caught"

    correct = (EdgeSpec(source=split, target=ca, carries=a), EdgeSpec(source=split, target=cb, carries=b))
    assert not check_variables((split, ca, cb), correct)

    # And the aggregate form this replaces would NOT have caught it — proven, not asserted.
    produced = {v for n in (split,) for v in n.outputs}
    consumed = {v for n in (ca, cb) for v in n.inputs}
    assert produced == consumed, "the set comparison agrees on the swapped wiring"


def test_check_bindings_catches_missing_and_extra():
    partial = StrategySpec("partial", {load: load_a})
    assert any("does not bind" in f for f in check_bindings(Linear.nodes, partial))

    stranger = NodeSpec("stranger")
    extra = StrategySpec("extra", {load: load_a, parse: parse_up, stranger: load_a})
    assert any("does not declare" in f for f in check_bindings(Linear.nodes, extra))


def test_check_implementations_catches_wrong_arity():
    async def two_args(ctx, extra) -> str:
        return ""

    bad = StrategySpec("bad", {load: two_args})
    assert any("positional" in f for f in check_implementations(bad))
    assert not check_implementations(arm_a)


def test_check_implementations_catches_non_callable():
    assert any("not callable" in f for f in check_implementations(
        StrategySpec("x", {load: "nope"})))


# ── rendering, against a real Graph ─────────────────────────────────────────────────────────

def test_render_produces_a_real_graph_that_runs():
    graph = Linear().render(arm_a)
    assert graph.run_sync(inputs="hi") == "A:HI"


def test_node_ids_are_identical_across_strategies():
    """The property the whole comparison rests on. Without `node_id=node.name` the ids come from
    the bound function's `__name__` and two arms get disjoint node sets."""
    a, b = Linear().render(arm_a), Linear().render(arm_b)
    assert sorted(a.nodes) == sorted(b.nodes)
    assert a.run_sync(inputs="x") != b.run_sync(inputs="x")     # they really are different arms


def test_two_nodes_may_share_one_implementation():
    """A real case that breaks without explicit node ids: both nodes would take the function's
    name and pydantic-graph refuses with duplicate node ids."""
    shared = StrategySpec("shared", {load: parse_up, parse: parse_up})
    assert Linear().render(shared).run_sync(inputs="hi") == "HI"


def test_render_refuses_an_incomplete_strategy():
    with pytest.raises(SpecError, match="does not bind"):
        Linear().render(StrategySpec("partial", {load: load_a}))


def test_varies_names_only_what_differs():
    assert Linear().varies(arm_a, arm_b) == {"load": ("load_a", "load_b")}


def test_check_with_no_strategy_needs_no_implementations():
    assert Linear().check() == []


# ── there is exactly one way to wire a graph ────────────────────────────────────────────────

def test_there_is_no_wiring_hook_to_override():
    """⛔ Guards a DELETION, which is the kind that quietly comes back.

    `build_pydantic_structure()` was a public, overridable hook — and the only way a built graph
    could differ from its declaration. While it existed, `edges` was decorative for any class
    that used it, `diagram()` could draw a picture the graph did not match, and reachability was
    reported NOT CHECKED for the whole design.

    A subclass defining that method now has no effect at all, which is worse than an error if
    nobody notices — so this asserts the attribute is gone AND that defining it changes nothing.
    """
    assert not hasattr(GraphSpec, "build_pydantic_structure")
    assert not hasattr(GraphSpec, "_overrides_structure")

    class TriesToOverride(Linear):
        def build_pydantic_structure(self, g, nodes):    # noqa: ARG002 — deliberately ignored
            raise AssertionError("this must never be called")

    assert TriesToOverride().check(arm_a) == []
    assert TriesToOverride().render(arm_a).run_sync(inputs="hi") == "A:HI"


# ── diagrams ────────────────────────────────────────────────────────────────────────────────

def test_diagram_needs_no_implementations_and_no_engine():
    out = Linear().diagram()
    assert "flowchart TD" in out and "load" in out and "-- text -->" in out


def test_diff_diagram_marks_only_the_varying_node():
    out = Linear().diff_diagram(arm_a, arm_b)
    load_line = next(ln for ln in out.splitlines() if ln.strip().startswith("load["))
    parse_line = next(ln for ln in out.splitlines() if ln.strip().startswith("parse["))
    assert ":::varies" in load_line
    assert ":::shared" in parse_line


def test_two_rendered_graphs_of_one_design_render_identically():
    """Why `diff_diagram` exists: pydantic-graph's own mermaid cannot show a strategy difference,
    because the built graph does not retain which strategy produced it."""
    a, b = Linear().render(arm_a), Linear().render(arm_b)
    assert a.render() == b.render()
    assert Linear().diff_diagram(arm_a, arm_b) != Linear().diagram()


def test_every_edge_field_is_keyword_only():
    """⛔ Guards a deliberate ergonomic trade, so it is not silently undone.

    Four slots that look interchangeable: `source` and `target` are the same type, and so are
    `carries` and `delivers`. Some transpositions are caught downstream — `check_variables`
    notices when a source does not declare what the edge carries — and some are NOT: in a chain
    where every wire carries the same variable, reversing two endpoints stays legal.

    ⚠️ The cost was argued before it was taken: `edges` is the most-read part of a design and the
    positional form read like the arrow it draws. Written down so the trade stays visible rather
    than becoming folklore.
    """
    import inspect

    from workflow_workbench import MapEdgeSpec, TransformEdgeSpec

    for cls in (EdgeSpec, MapEdgeSpec, TransformEdgeSpec):
        params = list(inspect.signature(cls).parameters.values())
        positional = [p for p in params if p.kind is not p.KEYWORD_ONLY]
        assert not positional, f"{cls.__name__} accepts positional args: {positional}"


def test_a_plain_edge_cannot_deliver_something_else():
    """`delivers` lives on the base so one field covers all three kinds — but a plain edge has no
    mechanism to convert, so declaring a different arrival would be a claim it cannot honour."""
    with pytest.raises(SpecError, match="cannot deliver something other than it carries"):
        EdgeSpec(source=load, target=parse, carries=text, delivers=VariableSpec("other", int))
