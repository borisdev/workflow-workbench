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
    edges = (EdgeSpec(START, load, text), EdgeSpec(load, parse, text), EdgeSpec(parse, END, text))


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
        EdgeSpec(END, load)
    with pytest.raises(SpecError):
        EdgeSpec(load, START)


def test_self_loop_refused():
    with pytest.raises(SpecError, match="self-loop"):
        EdgeSpec(load, load)


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
    edges = (EdgeSpec(START, a), EdgeSpec(a, b, text), EdgeSpec(b, a, text), EdgeSpec(b, END, text))
    check_reachable((a, b), edges)          # must return, not hang


def test_check_reachable_flags_an_undeclared_node():
    ghost = NodeSpec("ghost")
    edges = (*Linear.edges, EdgeSpec(parse, ghost, text))
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
    swapped = (EdgeSpec(split, ca, b), EdgeSpec(split, cb, a))       # ⛔ crossed

    findings = check_variables((split, ca, cb), swapped)
    assert findings, "the swap was not caught"

    correct = (EdgeSpec(split, ca, a), EdgeSpec(split, cb, b))
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


# ── the override escape hatch ───────────────────────────────────────────────────────────────

def test_override_reports_reachability_as_not_checked():
    class Overridden(Linear):
        def build_pydantic_structure(self, g, nodes):
            g.add(g.edge_from(g.start_node).to(nodes[load]),
                  g.edge_from(nodes[load]).to(nodes[parse]),
                  g.edge_from(nodes[parse]).to(g.end_node))

    findings = Overridden().check(arm_a)
    assert any(f.startswith("NOT CHECKED") for f in findings)
    # NOT CHECKED must not block a render — it is a stated gap, not a failure.
    assert Overridden().render(arm_a).run_sync(inputs="hi") == "A:HI"


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
