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
    StepSpec,
    SpecError,
    StrategySpec,
    VariableSpec,
    CoherenceFinding,
    DecisionSpec,
    NOT_CHECKED,
    blocking,
    check_bindings,
    check_decisions,
    check_implementations,
    check_names,
    check_reachable,
    check_variables,
)

text = VariableSpec("text", str)
other = VariableSpec("other", str)

load = StepSpec("load", inputs=(text,), outputs=(text,))
parse = StepSpec("parse", inputs=(text,), outputs=(text,))


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
    n1 = StepSpec("same", (text,), (text,))
    n2 = StepSpec("same", (text,), (text,))
    assert n1 != n2
    assert len({n1: 1, n2: 2}) == 2


def test_variables_are_value_equal():
    assert VariableSpec("x", str) == VariableSpec("x", str)


def test_list_inputs_refused():
    with pytest.raises(SpecError, match="must be a tuple"):
        StepSpec("bad", inputs=[text])


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
    dup = StepSpec("load", (text,), (text,))
    assert check_names((load, dup))
    assert not check_names((load, parse))


def test_check_reachable_finds_an_orphan():
    orphan = StepSpec("orphan")
    findings = check_reachable((load, parse, orphan), Linear.edges)
    assert any("orphan" in f and "unreachable" in f for f in findings)


def test_check_reachable_terminates_on_a_cycle():
    a, b = StepSpec("a", outputs=(text,)), StepSpec("b", inputs=(text,), outputs=(text,))
    edges = (EdgeSpec(source=START, target=a, carries=text), EdgeSpec(source=a, target=b, carries=text), EdgeSpec(source=b, target=a, carries=text), EdgeSpec(source=b, target=END, carries=text))
    check_reachable((a, b), edges)          # must return, not hang


def test_check_reachable_flags_an_undeclared_node():
    ghost = StepSpec("ghost")
    edges = (*Linear.edges, EdgeSpec(source=parse, target=ghost, carries=text))
    assert any("not in `nodes`" in f for f in check_reachable((load, parse), edges))


def test_check_variables_catches_a_swap_that_set_comparison_cannot():
    """⛔ THE REGRESSION FOR THE PER-EDGE CHECK.

    Both variables are produced, both consumed, every SET matches — and the wiring is swapped.
    An aggregate check passes here; only a per-edge one fails.
    """
    a, b = VariableSpec("a", str), VariableSpec("b", str)
    split = StepSpec("split", outputs=(a, b))
    ca = StepSpec("consume_a", inputs=(a,))
    cb = StepSpec("consume_b", inputs=(b,))
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

    stranger = StepSpec("stranger")
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
    assert Linear().coherence_check() == []


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

    assert TriesToOverride().coherence_check(arm_a) == []
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


# ── CoherenceFinding ────────────────────────────────────────────────────────────────────────
#
# ⚠️ The 221 tests above are a real oracle for the MESSAGES — they assert substrings, so a
# reworded finding fails loudly. They cannot say anything about `check` and `about`, which are
# new and which nothing else would notice being wrong. That is what this section is for.

def test_a_finding_is_still_a_string_everywhere_it_was_one():
    """⛔ THE COMPATIBILITY ORACLE. This is why the design is a `str` subclass and not a
    dataclass: ~30 call sites here and in two downstream repos do these five things to a finding
    and none of them was edited. If this test fails, the subclass stopped being additive.
    """
    msg = "node 'orphan' is unreachable from START — it never runs."
    f = CoherenceFinding(msg, check="check_reachable", about="orphan")

    assert f == msg and str(f) == msg          # value equality, byte-for-byte text
    assert "unreachable" in f                  # substring containment
    assert not f.startswith(NOT_CHECKED)       # the prefix match, still the same answer
    assert "\n  ".join([f, f]) == f"{msg}\n  {msg}"
    assert hash(f) == hash(msg) and {f} == {msg}
    assert repr([f]) == repr([msg]), "repr must not move — examples print whole lists of these"
    assert isinstance(f, str)


def test_blocking_is_derived_and_not_checked_is_the_only_non_blocking_kind():
    assert CoherenceFinding("anything at all", check="c").blocking
    assert not CoherenceFinding(f"{NOT_CHECKED} — we could not look", check="c").blocking
    # A stated gap and a clean pass must not read the same — `.claude/rules/checks.md`.
    assert blocking([CoherenceFinding(f"{NOT_CHECKED} — x", check="c")]) == []


def test_blocking_agrees_with_the_comprehension_it_replaces():
    """`render()`, `eval_battle` and the devserver all used the same `startswith` comprehension.
    They call `blocking()` now, so the two must give the identical verdict on the same input —
    including on a PLAIN string a caller mixed in, which has no `.blocking` to read."""
    findings = [*Linear().coherence_check(StrategySpec("partial", {load: load_a})),
                f"{NOT_CHECKED} — a plain string from somewhere else",
                "a plain string that is a real defect"]
    assert blocking(findings) == [f for f in findings if not f.startswith(NOT_CHECKED)]


def test_every_check_tags_its_findings_with_its_own_name():
    """`check` must name the function that produced the finding — the whole point is that a
    caller can branch on it. A typo'd or copy-pasted name is invisible to every other test."""
    import workflow_workbench.checks as c

    produced = {f.check for f in _every_finding_we_can_provoke()}
    assert produced, "no findings were provoked — the assertions below would pass vacuously"
    for name in produced:
        if name == "GraphSpec._coherence_check":
            continue        # cycle detection needs `ancestry`; it has no `check_*` function
        assert callable(getattr(c, name, None)), f"`check={name!r}` names no function in checks"


def test_about_names_something_the_caller_can_look_up():
    """⛔ THE `about` ORACLE, and the reason it is structural rather than a list of expected
    strings: a hand-written table of 27 answers is as likely to be wrong as the code it checks.

    This asserts the INVARIANT instead — an `about` is empty, or it is a name the caller can
    resolve against the design it just handed in. An `about` that names nothing is worse than an
    empty one, because it reads as a handle and is not.
    """
    spec = _Broken()
    resolvable = {n.name for n in (*spec.nodes, *spec.joins, *spec.decisions)}
    resolvable |= {"START", "END", _broken_arm.name}

    findings = spec.coherence_check(_broken_arm)
    assert len(findings) > 5, f"only {len(findings)} findings — not enough to be a real sweep"
    for f in findings:
        if not f.about:
            continue                                   # a whole-design finding, stated as such
        for part in f.about.split("->"):
            assert part in resolvable, f"`about={f.about!r}` names {part!r}, which is not in {spec.name}"


def test_about_follows_the_subject_of_the_sentence_not_the_loop_variable():
    """The two cases where the obvious answer is the wrong one.

    An undeclared node cannot be looked up — so that finding is about the EDGE that references
    it. And a decision's branch missing a `when=` is about that one branch, not about the
    decision: a caller filtering on the decision name would be handed a finding it cannot act on
    at the granularity it asked for.
    """
    ghost = StepSpec("ghost")
    edges = (*Linear.edges, EdgeSpec(source=parse, target=ghost, carries=text))
    undeclared = [f for f in check_reachable((load, parse), edges) if "not in `nodes`" in f]
    assert [f.about for f in undeclared] == ["parse->ghost"], "named the ghost, not the edge"

    route = DecisionSpec("route")
    branch = EdgeSpec(source=route, target=parse, carries=text)      # no `when=`
    no_when = [f for f in check_decisions((route,), (branch,)) if "without a `when=`" in f]
    assert [f.about for f in no_when] == ["route->parse"]


def test_about_is_the_node_for_a_node_finding_and_the_edge_for_an_edge_finding():
    """One assertion per check that can produce a finding from a two-node design, because a
    plausible-looking `about` on the wrong axis is exactly what nothing else here would see."""
    dup = StepSpec("load", (text,), (text,))
    assert [f.about for f in check_names((load, dup))] == ["load"]

    orphan = StepSpec("orphan")
    unreachable = [f for f in check_reachable((load, parse, orphan), Linear.edges)
                   if "unreachable" in f]
    assert [f.about for f in unreachable] == ["orphan"]

    wrong = EdgeSpec(source=load, target=parse, carries=other)
    assert [f.about for f in check_variables((load, parse), (wrong,))] == \
        ["load->parse", "load->parse"]           # neither end declares it: source AND target

    partial = StrategySpec("partial", {load: load_a})
    assert [f.about for f in check_bindings(Linear.nodes, partial)] == ["parse"]

    async def two_args(ctx, extra) -> str:
        return ""
    assert [f.about for f in check_implementations(StrategySpec("bad", {load: two_args}))] \
        == ["load"]


def test_a_whole_design_finding_says_so_with_an_empty_about():
    """⚠️ `""` is a VALUE here, not a missing one. "no edge leaves START" is about the design;
    inventing a node name for it would make a filter on that node return a finding it did not
    cause."""
    stranded = StepSpec("stranded")
    assert [f.about for f in check_reachable((stranded,), ())] == ["", ""]   # no START, no END


def test_every_append_site_is_tagged_even_the_ones_no_test_provokes():
    """⛔ THE RATCHET, and it is deliberately a source scan rather than a dynamic sweep.

    `test_every_check_tags_its_findings_with_its_own_name` is the stronger test — it reads real
    `check` values off real findings — but it can only cover branches something provokes. A
    `findings.append("...")` on a rare branch would return a plain `str`, and the FIRST caller to
    read `.check` off it gets an `AttributeError` in production rather than a red test here.

    So this one asserts the shape of every append site, including the ones nothing reaches.
    """
    import inspect

    import workflow_workbench.checks as c

    src = inspect.getsource(c)
    assert src.count("findings.append(") > 20, "checks.py read as empty or tiny — vacuous"
    assert src.count("findings.append(") == src.count("findings.append(CoherenceFinding("), \
        "a findings.append() in checks.py does not build a CoherenceFinding"


# ── the broken design these sweep over ──────────────────────────────────────────────────────
#
# One design that trips as many checks at once as possible. Deliberately NOT a list of expected
# messages: it exists so the structural assertions above run over real output from most of the
# check surface rather than over one hand-picked finding.

_a, _b = VariableSpec("a", str), VariableSpec("b", int)
_split = StepSpec("split", outputs=(_a, _b))
_merge = StepSpec("merge", inputs=(_a, _b), outputs=(_a,))          # two inputs: not a step
_lost = StepSpec("lost", inputs=(_a,))                               # cannot reach END
_route = DecisionSpec("route")                                       # no branches


class _Broken(GraphSpec):
    name = "broken"
    input_type, output_type = str, str
    nodes = (_split, _merge, _lost)
    decisions = (_route,)
    edges = (EdgeSpec(source=START, target=_split, carries=_a),
             EdgeSpec(source=_split, target=_merge, carries=_a),
             EdgeSpec(source=_split, target=_merge, carries=_b),     # fan-in onto a step
             EdgeSpec(source=_split, target=_lost, carries=_a),
             EdgeSpec(source=_merge, target=END, carries=_a))


async def _untyped(ctx):                                             # no return annotation
    return ""


_broken_arm = StrategySpec("broken_arm", {_split: _untyped, _merge: _untyped, _lost: _untyped})


def _every_finding_we_can_provoke():
    """Findings from across the check surface — the broken design, plus the cases its shape
    cannot reach."""
    out = list(_Broken().coherence_check(_broken_arm))
    out += check_names((load, StepSpec("load", (text,), (text,))))
    out += check_implementations(StrategySpec("x", {load: "nope"}))
    out += check_reachable((StepSpec("stranded"),), ())
    out += check_decisions((_route,), (EdgeSpec(source=_route, target=parse, carries=text),))
    return out
