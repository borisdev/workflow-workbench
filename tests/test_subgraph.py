"""A whole child design, used as ONE node's implementation.

Two claims, and they pull in opposite directions — which is why both are tested here:

    the child EXECUTES      two steps really run, on the parent's own state and deps objects
    the parent DOES NOT MOVE  its node ids are identical to a callable arm's, before and after

If only the first held we would have a nested runner. If only the second held we would have a
label. Both together are the thing: the design stays comparable while the implementation grows.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from workflow_workbench import (
    END,
    START,
    EdgeSpec,
    GraphSpec,
    NodeSpec,
    SpecError,
    StrategySpec,
    SubgraphBinding,
    VariableSpec,
)


@dataclass
class State:
    calls: list[str] = field(default_factory=list)


@dataclass
class Deps:
    prefix: str = ""


text = VariableSpec("text", str)
number = VariableSpec("number", int)

transform = NodeSpec("transform", inputs=(text,), outputs=(text,))


class Parent(GraphSpec):
    """One role, `str -> str`. Every strategy below fills it differently."""

    name = "parent"
    state_type, deps_type = State, Deps
    input_type, output_type = str, str
    nodes = (transform,)
    edges = (EdgeSpec(source=START, target=transform, carries=text),
             EdgeSpec(source=transform, target=END, carries=text))


async def direct(ctx) -> str:
    ctx.state.calls.append("direct")
    return f"{ctx.deps.prefix}{ctx.inputs.strip().upper()}"


first = NodeSpec("first", inputs=(text,), outputs=(text,))
second = NodeSpec("second", inputs=(text,), outputs=(text,))


class Child(GraphSpec):
    """The same `str -> str` boundary, reached in two inspectable steps instead of one."""

    name = "child"
    state_type, deps_type = State, Deps
    input_type, output_type = str, str
    nodes = (first, second)
    edges = (EdgeSpec(source=START, target=first, carries=text),
             EdgeSpec(source=first, target=second, carries=text),
             EdgeSpec(source=second, target=END, carries=text))


async def child_first(ctx) -> str:
    ctx.state.calls.append("first")
    return ctx.inputs.strip()


async def child_second(ctx) -> str:
    ctx.state.calls.append("second")
    return f"{ctx.deps.prefix}{ctx.inputs.upper()}"


child_strategy = StrategySpec("child_strategy", {first: child_first, second: child_second})
direct_strategy = StrategySpec("direct", {transform: direct})
subgraph_strategy = StrategySpec(
    "subgraph", {transform: SubgraphBinding(graph=Child(), strategy=child_strategy)})


# ── it runs ─────────────────────────────────────────────────────────────────────────────────

def test_subgraph_runs_as_one_parent_node() -> None:
    state = State()
    graph = Parent().render(subgraph_strategy)

    result = graph.run_sync(inputs=" hello ", state=state, deps=Deps(prefix="result:"))

    assert result == "result:HELLO"
    assert state.calls == ["first", "second"]      # two steps really executed
    # ⚠️ `Graph.nodes` includes pydantic-graph's own sentinels. Spelled out rather than filtered,
    # so this test fails if the SET changes and not merely if a name we thought to exclude does.
    assert sorted(graph.nodes) == ["__end__", "__start__", "transform"]
    assert "first" not in graph.nodes and "second" not in graph.nodes


def test_child_is_independently_runnable() -> None:
    """The same child, run on its own. If this fails, it is not a design — it is a fragment."""
    state = State()

    result = Child().render(child_strategy).run_sync(
        inputs=" hello ", state=state, deps=Deps(prefix="result:"))

    assert result == "result:HELLO"
    assert state.calls == ["first", "second"]


def test_parent_node_ids_stay_identical_across_binding_kinds() -> None:
    """⛔ The load-bearing one. A battle aligns two arms on node id; if a subgraph changed the
    parent's node set, the two arms would have nothing to compare and `varies()` would go blank."""
    callable_arm = sorted(Parent().render(direct_strategy).nodes)
    subgraph_arm = sorted(Parent().render(subgraph_strategy).nodes)

    assert callable_arm == subgraph_arm == ["__end__", "__start__", "transform"]


def test_subgraph_shares_the_parent_state_and_deps_objects() -> None:
    """Not "a state of the same type" — the SAME object. Asserted by mutation, not by type."""
    state = State()
    deps = Deps(prefix="shared:")

    result = Parent().render(subgraph_strategy).run_sync(inputs="value", state=state, deps=deps)

    assert result == "shared:VALUE"                 # the child read the parent's deps
    assert state.calls == ["first", "second"]       # and wrote to the parent's state


def test_a_callable_arm_and_a_subgraph_arm_are_one_design() -> None:
    """The point of the whole change: two arms, same design, different implementation depth."""
    spec = Parent()
    a = spec.render(direct_strategy).run_sync(inputs=" hi ", state=State(), deps=Deps("x:"))
    b = spec.render(subgraph_strategy).run_sync(inputs=" hi ", state=State(), deps=Deps("x:"))
    assert a == b == "x:HI"


# ── the boundary contract ───────────────────────────────────────────────────────────────────

def test_subgraph_input_mismatch_is_rejected() -> None:
    other = NodeSpec("other", inputs=(number,), outputs=(text,))

    class WrongInput(GraphSpec):
        name = "wrong_input"
        state_type, deps_type = State, Deps
        input_type, output_type = int, str
        nodes = (other,)
        edges = (EdgeSpec(source=START, target=other, carries=number), EdgeSpec(source=other, target=END, carries=text))

    async def run(ctx) -> str:
        return str(ctx.inputs)

    bad = StrategySpec("bad", {transform: SubgraphBinding(
        graph=WrongInput(), strategy=StrategySpec("inner", {other: run}))})

    with pytest.raises(SpecError, match="input_type"):
        Parent().render(bad)


def test_subgraph_output_mismatch_is_rejected() -> None:
    other = NodeSpec("other", inputs=(text,), outputs=(number,))

    class WrongOutput(GraphSpec):
        name = "wrong_output"
        state_type, deps_type = State, Deps
        input_type, output_type = str, int
        nodes = (other,)
        edges = (EdgeSpec(source=START, target=other, carries=text), EdgeSpec(source=other, target=END, carries=number))

    async def run(ctx) -> int:
        return len(ctx.inputs)

    bad = StrategySpec("bad", {transform: SubgraphBinding(
        graph=WrongOutput(), strategy=StrategySpec("inner", {other: run}))})

    with pytest.raises(SpecError, match="output_type"):
        Parent().render(bad)


def test_subgraph_state_mismatch_is_rejected() -> None:
    """Two state types that happen to have the same fields are still two types. The child gets
    the parent's actual object, so anything less than identity is a promise we cannot keep."""

    @dataclass
    class OtherState:
        calls: list[str] = field(default_factory=list)

    class WrongState(Child):
        state_type = OtherState

    bad = StrategySpec("bad", {transform: SubgraphBinding(
        graph=WrongState(), strategy=child_strategy)})

    with pytest.raises(SpecError, match="state_type"):
        Parent().render(bad)


def test_subgraph_deps_mismatch_is_rejected() -> None:
    @dataclass
    class OtherDeps:
        prefix: str = ""

    class WrongDeps(Child):
        deps_type = OtherDeps

    bad = StrategySpec("bad", {transform: SubgraphBinding(
        graph=WrongDeps(), strategy=child_strategy)})

    with pytest.raises(SpecError, match="deps_type"):
        Parent().render(bad)


def test_incomplete_child_strategy_is_rejected() -> None:
    """The child's own completeness rule applies through the parent. A half-bound child would
    otherwise fail at build time, attributed to the parent's render."""
    bad = StrategySpec("bad", {transform: SubgraphBinding(
        graph=Child(), strategy=StrategySpec("incomplete", {first: child_first}))})

    with pytest.raises(SpecError, match="does not bind"):
        Parent().render(bad)


# ── START and END are exceptions to the one-port rule ───────────────────────────────────────

passthrough = NodeSpec("passthrough", inputs=(text,), outputs=(text,))


class StartEndParent(GraphSpec):
    """A node wired straight to the sentinels — and now declaring what crosses each wire."""

    name = "start_end_parent"
    state_type, deps_type = State, Deps
    input_type, output_type = str, str
    nodes = (passthrough,)
    edges = (EdgeSpec(source=START, target=passthrough, carries=text), EdgeSpec(source=passthrough, target=END, carries=text))


def test_a_node_wired_to_the_sentinels_is_checked_like_any_other() -> None:
    """⛔ THIS TEST USED TO ASSERT THE OPPOSITE, and the change is worth understanding.

    It was `test_a_node_wired_to_the_sentinels_needs_no_declared_variables`: a NodeSpec declaring
    nothing, edges carrying nothing, and `_port_type` falling back to the graph's own
    input_type/output_type to check a subgraph boundary.

    That case no longer exists, and not because anyone removed the fallback. Making
    `EdgeSpec.carries` REQUIRED made node declarations required too, transitively:
    `check_variables` demands the target declare what arrives, so a node with an incoming edge
    must declare that input. A bigger consequence than "declare six variables in the examples",
    which is what I predicted when proposing it.
    """
    state = State()
    strategy = StrategySpec("sub", {passthrough: SubgraphBinding(Child(), child_strategy)})

    graph = StartEndParent().render(strategy)
    assert graph.run_sync(inputs=" hi ", state=state, deps=Deps(prefix="ok:")) == "ok:HI"
    assert state.calls == ["first", "second"]
    assert StartEndParent().check(strategy) == []


def test_a_node_that_declares_nothing_is_now_refused() -> None:
    """The transitive consequence, pinned so it is a decision rather than a surprise."""
    silent = NodeSpec("silent")

    class Silent(GraphSpec):
        name = "silent_design"
        state_type, deps_type = State, Deps
        input_type, output_type = str, str
        nodes = (silent,)
        edges = (EdgeSpec(source=START, target=silent, carries=text), EdgeSpec(source=silent, target=END, carries=text))

    async def anything(ctx) -> str:
        return ctx.inputs

    findings = Silent().check(StrategySpec("s", {silent: anything}))
    assert any("does not declare it as an input" in f for f in findings), findings


def test_a_subgraph_boundary_is_checked_against_the_declared_variables() -> None:
    """The subgraph contract still holds; it just reads the declaration rather than a fallback."""

    class IntInput(StartEndParent):
        input_type = int
        nodes = (NodeSpec("passthrough", inputs=(number,), outputs=(number,)),)
        edges = ()

    other = IntInput.nodes[0]

    class IntDesign(GraphSpec):
        name = "int_design"
        state_type, deps_type = State, Deps
        input_type, output_type = int, int
        nodes = (other,)
        edges = (EdgeSpec(source=START, target=other, carries=number), EdgeSpec(source=other, target=END, carries=number))

    strategy = StrategySpec("sub", {other: SubgraphBinding(Child(), child_strategy)})
    with pytest.raises(SpecError, match="input_type"):
        IntDesign().render(strategy)


mid_first = NodeSpec("mid_first", inputs=(text,), outputs=(text,))
mid_second = NodeSpec("mid_second", inputs=(text,), outputs=(text,))


class MidParent(GraphSpec):
    name = "mid_parent"
    state_type, deps_type = State, Deps
    input_type, output_type = str, str
    nodes = (mid_first, mid_second)
    edges = (EdgeSpec(source=START, target=mid_first, carries=text),
             EdgeSpec(source=mid_first, target=mid_second, carries=text),
             EdgeSpec(source=mid_second, target=END, carries=text))


def test_a_mid_chain_subgraph_boundary_is_checked_from_the_declaration() -> None:
    """⛔ ALSO USED TO ASSERT THE OPPOSITE. It was
    `test_an_unresolvable_boundary_says_NOT_CHECKED_and_still_renders`: a node mid-chain that
    declared nothing, where there was genuinely no type to compare a subgraph against, so the
    finding was `NOT CHECKED` and the render proceeded.

    Required `carries` removed the whole category. There is no longer an unresolvable boundary,
    because every edge names a variable and every node must declare it. `_port_type`'s
    START/END fallback is now unreachable — kept for the moment rather than deleted, because
    "unreachable today" and "unreachable" are different claims and only one of them is measured.
    """
    async def one(ctx) -> str:
        return ctx.inputs

    strategy = StrategySpec("sub", {mid_first: one,
                                    mid_second: SubgraphBinding(Child(), child_strategy)})

    assert MidParent().check(strategy) == []
    MidParent().render(strategy)


two_in = NodeSpec("two_in", inputs=(text, number), outputs=(text,))


class MultiPortParent(GraphSpec):
    name = "multi_port_parent"
    state_type, deps_type = State, Deps
    input_type, output_type = str, str
    nodes = (two_in,)
    edges = (EdgeSpec(source=START, target=two_in, carries=text), EdgeSpec(source=two_in, target=END, carries=text))


def test_a_multi_port_node_is_rejected_rather_than_guessed() -> None:
    """Two declared inputs and one child `input_type`: there is no answer, only a guess."""
    strategy = StrategySpec("sub", {two_in: SubgraphBinding(Child(), child_strategy)})

    with pytest.raises(SpecError, match="declares 2 inputs"):
        MultiPortParent().render(strategy)


# ── recursion ───────────────────────────────────────────────────────────────────────────────

def test_recursive_subgraph_binding_is_rejected() -> None:
    """A design implementing one of its own nodes with itself builds children until the stack
    ends. Caught in `_check`, which is the single owner of the ancestry path."""
    bindings: dict = {}
    recursive = StrategySpec("recursive", bindings)
    bindings[transform] = SubgraphBinding(graph=Parent(), strategy=recursive)

    with pytest.raises(SpecError, match="recursive subgraph"):
        Parent().render(recursive)


def test_mutual_recursion_between_two_designs_is_rejected() -> None:
    """The two-hop version, which a "is the child me?" check would miss entirely."""
    outer_bindings: dict = {}
    inner_bindings: dict = {}
    outer = StrategySpec("outer", outer_bindings)
    inner = StrategySpec("inner", inner_bindings)

    outer_bindings[transform] = SubgraphBinding(graph=Child(), strategy=inner)
    inner_bindings[first] = SubgraphBinding(graph=Parent(), strategy=outer)
    inner_bindings[second] = child_second

    with pytest.raises(SpecError, match="recursive subgraph"):
        Parent().render(outer)


# ── it is visible ───────────────────────────────────────────────────────────────────────────

def test_varies_names_callable_versus_subgraph() -> None:
    assert Parent().varies(direct_strategy, subgraph_strategy) == {
        "transform": ("direct", "child::child_strategy")}


def test_diff_diagram_names_the_collapsed_child() -> None:
    out = Parent().diff_diagram(direct_strategy, subgraph_strategy)
    assert "direct" in out
    assert "child::child_strategy" in out
    assert "first" not in out              # the child is NOT flattened into the parent picture


def test_devserver_payload_shows_the_child_design_not_a_blank_panel() -> None:
    """⚠️ `inspect.getsource` raises TypeError on a SubgraphBinding instance, and the generic
    path swallows it — so without the special case this stage renders as an empty code panel,
    which reads as "does nothing" rather than "is a whole child design"."""
    from workflow_workbench.devserver import spec_payload

    payload = spec_payload(Parent(), [direct_strategy, subgraph_strategy])
    layer = next(la for la in payload["layers"] if la["name"] == "subgraph")
    binding = layer["bindings"]["transform"]

    assert binding["impl"] == "child::child_strategy"
    assert binding["skipped"] is False
    assert binding["code"]                                   # not the silent empty string
    assert "first" in binding["code"] and "second" in binding["code"]
    assert binding["file"].endswith("test_subgraph.py")


# ── fan-in: the shape that ran green and dropped a result ───────────────────────────────────

left = VariableSpec("left", str)
right = VariableSpec("right", str)

split_a = NodeSpec("split_a", inputs=(text,), outputs=(left,))
split_b = NodeSpec("split_b", inputs=(text,), outputs=(right,))
merge = NodeSpec("merge", inputs=(left, right), outputs=(text,))


class FanIn(GraphSpec):
    """`plans.py::MergeCitations` in miniature: two producers, one consumer declared to take both."""

    name = "fan_in"
    state_type, deps_type = State, Deps
    input_type, output_type = str, str
    nodes = (split_a, split_b, merge)
    edges = (EdgeSpec(source=START, target=split_a, carries=text),
             EdgeSpec(source=START, target=split_b, carries=text),
             EdgeSpec(source=split_a, target=merge, carries=left),
             EdgeSpec(source=split_b, target=merge, carries=right),
             EdgeSpec(source=merge, target=END, carries=text))


def test_a_node_that_cannot_receive_both_its_inputs_is_refused() -> None:
    """⛔ Measured before this check existed: it rendered, ran, called `merge` TWICE with one
    value each, and returned one result while discarding the other. `check()` said clean.

    Every other check passes on it — both variables are declared on both ends, everything
    reaches END. Only arity sees it.
    """
    async def one(ctx) -> str:
        return ctx.inputs

    strategy = StrategySpec("s", {split_a: one, split_b: one, merge: one})
    findings = FanIn().check(strategy)

    assert len(findings) == 2, findings
    assert "declares 2 inputs" in findings[0]
    assert "invoked once PER EDGE" in findings[1]

    with pytest.raises(SpecError, match="declares 2 inputs"):
        FanIn().render(strategy)


def test_a_linear_chain_is_not_flagged() -> None:
    """The check must not fire on the ordinary shape, or it is noise nobody reads."""
    assert Parent().check(direct_strategy) == []
    assert Child().check(child_strategy) == []


# ── a loop-back is not a fan-in ─────────────────────────────────────────────────────────────

def test_a_retry_loop_is_not_reported_as_a_fan_in() -> None:
    """⛔ `check_step_arity`'s SECOND false positive, found the same way as the first — by
    building a real design instead of reasoning about the rule.

    A retry loop is the commonest reason anyone reaches for the `BaseNode` API:

        propose -> validate -> route --Retry--> unwrap -> propose

    That back edge gives `propose` two incoming edges. The check called it a fan-in whose results
    were being discarded. Measured against raw pydantic-graph: the cycle is legal, `propose` runs
    three times, and each run flows forward on its own — the invocations are separated in TIME.
    """
    from dataclasses import dataclass, field as dc_field

    from workflow_workbench import DecisionSpec

    @dataclass
    class Good:
        text: str

    @dataclass
    class Again:
        text: str

    @dataclass
    class Log:
        steps: list = dc_field(default_factory=list)
        n: int = 0

    seed = VariableSpec("seed", str)
    draft = VariableSpec("draft", str)
    verdict = VariableSpec("verdict", object)
    out_v = VariableSpec("out_v", str)

    propose = NodeSpec("propose", inputs=(seed,), outputs=(draft,))
    judge = NodeSpec("judge", inputs=(draft,), outputs=(verdict,))
    unwrap = NodeSpec("unwrap", inputs=(verdict,), outputs=(seed,))
    finish = NodeSpec("finish", inputs=(verdict,), outputs=(out_v,))
    route = DecisionSpec("route", inputs=(verdict,), outputs=(verdict,))

    class WithRetry(GraphSpec):
        name = "with_retry"
        state_type = Log
        input_type, output_type = str, str
        nodes = (propose, judge, unwrap, finish)
        decisions = (route,)
        edges = (EdgeSpec(source=START, target=propose, carries=seed),
                 EdgeSpec(source=propose, target=judge, carries=draft),
                 EdgeSpec(source=judge, target=route, carries=verdict),
                 EdgeSpec(source=route, target=unwrap, carries=verdict, when=Again),
                 EdgeSpec(source=route, target=finish, carries=verdict, when=Good),
                 EdgeSpec(source=unwrap, target=propose, carries=seed),          # the back edge
                 EdgeSpec(source=finish, target=END, carries=out_v))

    async def do_propose(ctx) -> str:
        ctx.state.n += 1
        ctx.state.steps.append(f"propose#{ctx.state.n}")
        return f"draft-{ctx.state.n}"

    async def do_judge(ctx) -> object:
        ctx.state.steps.append("judge")
        return Again(ctx.inputs) if ctx.state.n < 3 else Good(ctx.inputs)

    async def do_unwrap(ctx) -> str:
        return ctx.inputs.text

    async def do_finish(ctx) -> str:
        return f"done({ctx.inputs.text})"

    strategy = StrategySpec("s", {propose: do_propose, judge: do_judge,
                                  unwrap: do_unwrap, finish: do_finish})
    spec = WithRetry()

    assert spec.check(strategy) == [], "a loop-back was reported as a fan-in"

    log = Log()
    assert spec.render(strategy).run_sync(inputs="a plan", state=log) == "done(draft-3)"
    assert log.steps.count("propose#1") == 1
    assert [s for s in log.steps if s.startswith("propose")] == [
        "propose#1", "propose#2", "propose#3"], log.steps


def test_a_real_fan_in_is_still_caught_next_to_a_loop() -> None:
    """The back-edge exclusion must not become an amnesty for every multi-edge node."""
    a_var = VariableSpec("a_var", str)
    one = NodeSpec("one", inputs=(text,), outputs=(a_var,))
    two = NodeSpec("two", inputs=(text,), outputs=(a_var,))
    sink = NodeSpec("sink", inputs=(a_var,), outputs=(text,))

    class RealFanIn(GraphSpec):
        name = "real_fan_in"
        input_type, output_type = str, str
        nodes = (one, two, sink)
        edges = (EdgeSpec(source=START, target=one, carries=text),
                 EdgeSpec(source=START, target=two, carries=text),
                 EdgeSpec(source=one, target=sink, carries=a_var),
                 EdgeSpec(source=two, target=sink, carries=a_var),
                 EdgeSpec(source=sink, target=END, carries=text))

    assert any("invoked once PER EDGE" in f for f in RealFanIn().check()), RealFanIn().check()
