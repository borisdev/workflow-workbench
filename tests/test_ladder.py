"""One test per README rung. The README, the example and this file must agree.

⚠️ Each test asserts the OUTCOME, not that the module imported. `main()` running without raising
proves the script is syntactically valid and nothing more — the same shape as a UI test that
greps a template, which `.claude/rules/checks.md` is about. So every rung below states what its
example is supposed to demonstrate, in a form that can be wrong.
"""
from __future__ import annotations

import asyncio

import pytest

from workflow_workbench import SpecError


# ── rung 0: the control ─────────────────────────────────────────────────────────────────────

def test_rung0_pydantic_graph_alone_works_fine() -> None:
    """The baseline is not a strawman. If this ever fails, the ladder's premise is wrong."""
    from examples.ladder.their_hello import Guest, build

    graph = build()
    state = Guest()
    assert graph.run_sync(inputs="Ada", state=state) == "Hello, Ada!"
    assert state.name == "Ada"


# ── rung 1: the same design, declared ───────────────────────────────────────────────────────

def test_rung1_the_declared_design_gives_the_same_answer() -> None:
    """A lateral move that had better be lateral: same result, same node ids as rung 0."""
    from examples.ladder.stage1_bare import Guest, HelloWorld, formal
    from examples.ladder.their_hello import Guest as TheirGuest, build

    ours = HelloWorld().render(formal).run_sync(inputs="Ada", state=Guest())
    theirs = build().run_sync(inputs="Ada", state=TheirGuest())
    assert ours == theirs == "Hello, Ada!"


def test_rung1_checks_before_anything_is_implemented() -> None:
    """The capability a built Graph cannot have: it cannot exist until every body is written."""
    from examples.ladder.stage1_bare import HelloWorld

    assert HelloWorld().check() == []
    assert "flowchart" in HelloWorld().diagram()


# ── rung 2: two strategies ──────────────────────────────────────────────────────────────────

def test_rung2_both_arms_share_node_ids_and_differ_only_in_bindings() -> None:
    """⛔ The load-bearing invariant of the whole library. If node ids diverged, every downstream
    rung — the diff, the battle, the report — would have nothing to align on."""
    from examples.ladder.stage1_bare import Guest, HelloWorld, formal
    from examples.ladder.stage2_strategies import casual

    spec = HelloWorld()
    a, b = spec.render(formal), spec.render(casual)

    assert sorted(a.nodes) == sorted(b.nodes) == ["__end__", "__start__", "compose", "pick"]
    assert a.run_sync(inputs="Ada", state=Guest()) == "Hello, Ada!"
    assert b.run_sync(inputs="Ada", state=Guest()) == "Yo, Ada!"
    assert spec.varies(formal, casual) == {"pick": ("pick_formal", "pick_casual")}


# ── rung 3: the design grows ────────────────────────────────────────────────────────────────

def test_rung3_a_new_node_runs_in_every_arm() -> None:
    from examples.ladder.stage1_bare import Guest
    from examples.ladder.stage3_new_node import TranslatedHello, casual_t, formal_t

    spec = TranslatedHello()
    assert spec.render(formal_t).run_sync(inputs="Ada", state=Guest()) == "Hello, Ada!"
    assert spec.render(casual_t).run_sync(inputs="Ada", state=Guest()) == "YO, ADA!"
    assert set(spec.varies(formal_t, casual_t)) == {"pick", "translate"}


def test_rung3_a_strategy_predating_the_new_node_is_refused() -> None:
    """At DECLARATION time. Mid-run it would look like the runtime's fault."""
    from examples.ladder.stage1_bare import compose_sentence, pick, pick_formal
    from examples.ladder.stage1_bare import compose as compose_node
    from examples.ladder.stage3_new_node import TranslatedHello
    from workflow_workbench import StrategySpec

    stale = StrategySpec("stale", {pick: pick_formal, compose_node: compose_sentence})
    with pytest.raises(SpecError, match="does not bind node 'translate'"):
        TranslatedHello().render(stale)


# ── rung 4: a node implemented by a child design ────────────────────────────────────────────

def test_rung4_the_child_runs_and_the_parent_does_not_grow() -> None:
    from examples.ladder.stage4_subgraph import (
        TracedGuest, TracedHello, Translation, nested, piratical, plain, shouty)

    spec = TracedHello()

    child_state = TracedGuest(name="Ada")
    assert Translation().render(piratical).run_sync(
        inputs="Hello, Ada!", state=child_state) == "Arr! Hello, Ada!"
    assert child_state.trace == ["detect", "render"]

    state = TracedGuest()
    assert spec.render(nested).run_sync(inputs="Ada", state=state) == "Arr! Hello, Ada!"
    assert state.trace == ["detect", "render"], "the child did not actually run"

    ids = [sorted(spec.render(s).nodes) for s in (plain, shouty, nested)]
    assert ids[0] == ids[1] == ids[2]
    assert "detect" not in ids[0] and "render" not in ids[0], "the child leaked into the parent"


# ── rung 5: the battle, and its floor ───────────────────────────────────────────────────────

def test_rung5_a_replicate_measures_the_floor_and_is_labelled_as_one() -> None:
    """⛔ A replicate that reported as an ordinary battle would license noise as a result."""
    from examples.ladder.stage1_bare import HelloWorld, formal
    from examples.ladder.stage2_strategies import casual
    from examples.ladder.stage5_battle import DATASET, run_with_state
    from workflow_workbench.evals import eval_battle

    spec = HelloWorld()
    floor = eval_battle(spec, formal, formal, DATASET, run=run_with_state)
    assert floor.is_replicate is True
    assert floor.per_case_spread() == {"Warmth": 0.0, "Length": 0.0}, (
        "these implementations are deterministic; a non-zero spread means something is stochastic")

    battle = eval_battle(spec, formal, casual, DATASET, run=run_with_state)
    assert battle.is_replicate is False
    assert battle.deltas()["Warmth"] == 1.0
    assert abs(battle.deltas()["Warmth"]) > floor.per_case_spread()["Warmth"]


# ── rung 6: the diagram theirs cannot draw ──────────────────────────────────────────────────

def test_rung6_their_renderer_cannot_tell_two_arms_apart() -> None:
    """The premise of `diff_diagram`, asserted rather than described."""
    from examples.ladder.stage1_bare import HelloWorld, formal
    from examples.ladder.stage2_strategies import casual

    spec = HelloWorld()
    a = spec.render(formal).render(title="same")
    b = spec.render(casual).render(title="same")
    assert a == b, "if these ever differ, diff_diagram's reason for existing has changed"

    ours = spec.diff_diagram(formal, casual)
    assert "pick_formal" in ours and "pick_casual" in ours


def test_rung6_a_state_diagram_does_carry_the_edge_variable() -> None:
    """⛔ Pins the CORRECTION. `diagram.py` claimed a state diagram has nowhere to put the edge
    variable; it does, and this is the counter-example that says so. If their renderer ever stops
    printing labels this goes red and the docstring can be revisited — deliberately, not by
    someone re-inventing the old wrong justification."""
    from examples.ladder.stage1_bare import HelloWorld, formal

    theirs = HelloWorld().render(formal).render(title="t")
    assert "stateDiagram-v2" in theirs
    assert "salutation" in theirs


# ── rung 7: it is a real Graph ──────────────────────────────────────────────────────────────

def test_rung7_their_iter_api_drives_a_rendered_graph() -> None:
    """The negative claim — we did not replace the runtime — using an API we never wrap."""
    from examples.ladder.stage1_bare import Guest, HelloWorld, formal
    from examples.ladder.stage7_iter import drive

    output, events = asyncio.run(drive(HelloWorld().render(formal), "Ada", Guest()))
    assert output == "Hello, Ada!"
    assert events, "iter() yielded nothing"


def test_rung7_a_subgraph_stays_out_of_the_parents_event_stream() -> None:
    """One parent task for `translate`; the child's two steps run inside it."""
    from examples.ladder.stage4_subgraph import TracedGuest, TracedHello, nested
    from examples.ladder.stage7_iter import drive

    state = TracedGuest()
    output, events = asyncio.run(drive(TracedHello().render(nested), "Ada", state))

    assert output == "Arr! Hello, Ada!"
    assert state.trace == ["detect", "render"]
    seen = str(events)
    assert "'translate'" in seen
    assert "'detect'" not in seen and "'render'" not in seen


# ── every rung's main() is runnable, which is what the README tells a reader to do ───────────

@pytest.mark.parametrize("module", [
    "their_hello", "stage1_bare", "stage2_strategies", "stage3_new_node",
    "stage4_subgraph", "stage5_battle", "stage6_diagrams", "stage7_iter", "stage8_join",
    "stage9_decision",
])
def test_every_rung_runs_as_a_script(module: str) -> None:
    """Weakest test here, and it earns its place: the README prints these commands, and a reader
    who pastes one and gets a traceback has been told a lie by the documentation."""
    mod = __import__(f"examples.ladder.{module}", fromlist=["main"])
    mod.main()


def test_every_readme_link_into_examples_or_docs_resolves() -> None:
    """The README↔code mapping, enforced.

    ⚠️ A README that links a file which was renamed or never written is the confidently-wrong doc
    `.claude/rules/spec-as-code.md` is about: it makes a reader skip looking at the code, and
    nothing else in this repo would notice. This is the cheapest possible check that it does not
    happen, and it goes red the moment a rung is renamed.
    """
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    readme = (root / "README.md").read_text()
    links = re.findall(r"\]\((examples/[^)#]+|docs/[^)#]+|tests/[^)#]+)\)", readme)

    assert links, "no links into the repo at all — the ladder table has gone missing"
    missing = [ln for ln in links if not (root / ln).exists()]
    assert not missing, f"README links files that do not exist: {missing}"


def test_the_readme_ladder_table_lists_every_rung_module() -> None:
    """The other direction: a rung that exists but nobody is told about."""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    readme = (root / "README.md").read_text()
    modules = sorted(p.name for p in (root / "examples" / "ladder").glob("*.py")
                     if p.name != "__init__.py")

    unlisted = [m for m in modules if f"examples/ladder/{m}" not in readme]
    assert not unlisted, f"ladder modules missing from the README table: {unlisted}"


# ── rung 8: a declared join ─────────────────────────────────────────────────────────────────

def test_rung8_a_join_actually_combines_both_arrivals() -> None:
    """⛔ The assertion that matters is `/` being present: BOTH producers reached the result.

    The pre-JoinSpec version of this design returned one greeting, and no check objected.
    """
    from examples.ladder.stage8_join import Greetings, Guest, greet

    spec = Greetings()
    assert spec.check(greet) == []

    result = spec.render(greet).run_sync(inputs="Ada", state=Guest())
    assert result == "Hello, Ada! / Yo, Ada!"
    assert "collect" in spec.render(greet).nodes


def test_rung8_the_same_shape_as_a_step_is_refused() -> None:
    from examples.ladder.stage8_join import (
        BrokenGreetings, announce, announce_both, casual, collect_as_step, formal,
        say_casual, say_formal)
    from workflow_workbench import StrategySpec

    async def collect_step(ctx) -> list:
        return [ctx.inputs]

    broken = StrategySpec("broken", {say_formal: formal, say_casual: casual,
                                     collect_as_step: collect_step, announce: announce_both})
    with pytest.raises(SpecError, match="declares 2 inputs"):
        BrokenGreetings().render(broken)


def test_rung8_a_join_is_reachability_checked_which_it_could_not_be_before() -> None:
    """The real gain. A join used to require overriding build_pydantic_structure(), which reports
    reachability as NOT CHECKED for the ENTIRE design — so having a join meant giving up the check
    on every node around it."""
    from examples.ladder.stage8_join import Greetings, greet

    findings = Greetings().check(greet)
    assert not any("NOT CHECKED" in f for f in findings), findings


def test_rung8_a_join_binds_nothing_and_never_appears_in_varies() -> None:
    """A join has no implementation, so a strategy that 'bound' it would be describing nothing."""
    from examples.ladder.stage8_join import Greetings, collect, greet

    assert collect not in greet.bindings
    assert Greetings().check(greet) == []
    assert "collect" not in Greetings().varies(greet, greet)


def test_rung8_a_mutable_seed_must_be_a_factory() -> None:
    """⚠️ `initial=[]` is built once at declaration and shared by every run of the graph, so one
    run's results leak into the next. Refused at declaration rather than debugged later."""
    from pydantic_graph.join import reduce_list_append

    from workflow_workbench import JoinSpec

    with pytest.raises(SpecError, match="exactly one of"):
        JoinSpec("bad", reduce_list_append)
    with pytest.raises(SpecError, match="exactly one of"):
        JoinSpec("bad", reduce_list_append, initial=[], initial_factory=list)

    JoinSpec("fine", reduce_list_append, initial_factory=list)
    JoinSpec("also_fine", reduce_list_append, initial=0)


# ── rung 9: conditional routing ─────────────────────────────────────────────────────────────

def test_rung9_each_branch_routes_and_only_one_fires() -> None:
    from examples.ladder.stage9_decision import Log, Triage, careful

    spec = Triage()
    assert spec.check(careful) == []
    graph = spec.render(careful)

    urgent_log = Log()
    assert "seek care now" in graph.run_sync(inputs="chest pain now", state=urgent_log)
    assert urgent_log.steps == ["intake", "escalate", "report"]

    routine_log = Log()
    assert "looked it up" in graph.run_sync(inputs="dry elbow", state=routine_log)
    assert routine_log.steps == ["intake", "research", "report"]


def test_rung9_converging_branches_are_not_a_fan_in() -> None:
    """⛔ The regression `check_step_arity`'s own docstring predicted.

    `report` has two incoming edges. If the exclusivity analysis were missing, every branching
    design would be reported as the fan-in defect rung 8 exists to catch — and the check would
    become noise that people learn to ignore, which is worse than not having it.

    Measured, not reasoned: `report` runs ONCE on each input.
    """
    from examples.ladder.stage9_decision import Log, Triage, careful, report

    spec = Triage()
    incoming = [e for e in spec.edges if e.target is report]
    assert len(incoming) == 2, "the test's premise is gone; report is no longer a convergence"

    assert spec.check(careful) == [], "a converging branch was reported as a fan-in"

    for text in ("chest pain now", "dry elbow"):
        log = Log()
        spec.render(careful).run_sync(inputs=text, state=log)
        assert log.steps.count("report") == 1, log.steps


def test_rung9_a_real_fan_in_is_still_caught_alongside_a_decision() -> None:
    """The exclusivity analysis must not become a blanket amnesty for branching designs."""
    from examples.ladder.stage9_decision import (
        Log, Triage, complaint, handled, intake, report, report_out, route, verdict)
    from workflow_workbench import EdgeSpec, NodeSpec

    sneak = NodeSpec("sneak", inputs=(verdict,), outputs=(handled,))

    class RealFanIn(Triage):
        name = "real_fan_in"
        nodes = (*Triage.nodes, sneak)
        edges = (*Triage.edges,
                 EdgeSpec(intake, sneak, verdict),      # NOT behind the decision
                 EdgeSpec(sneak, report, handled))      # a third, unconditional arrival

    findings = RealFanIn().check()
    assert any("invoked once PER EDGE" in f for f in findings), findings


def test_rung9_a_decision_binds_nothing() -> None:
    from examples.ladder.stage9_decision import Triage, alarmist, careful, route

    assert route not in careful.bindings and route not in alarmist.bindings
    assert "route" not in Triage().varies(careful, alarmist)
    assert Triage().varies(careful, alarmist) == {
        "intake": ("triage_keywords", "triage_everything_urgent")}


def test_rung9_a_branch_without_a_condition_is_refused() -> None:
    from examples.ladder.stage9_decision import (
        complaint, escalate, handled, intake, report, report_out, research, route, verdict)
    from examples.ladder.stage9_decision import Triage, Urgent, careful
    from workflow_workbench import END, START, EdgeSpec

    class NoWhen(Triage):
        name = "no_when"
        edges = (EdgeSpec(START, intake, complaint),
                 EdgeSpec(intake, route, verdict),
                 EdgeSpec(route, escalate, verdict),
                 EdgeSpec(route, research, verdict, when=Urgent),
                 EdgeSpec(escalate, report, handled),
                 EdgeSpec(research, report, handled),
                 EdgeSpec(report, END, report_out))

    with pytest.raises(SpecError, match="without a `when=` type"):
        NoWhen().render(careful)


def test_rung9_a_condition_on_an_ordinary_edge_is_refused() -> None:
    """⚠️ The nastier of the two: it would be SILENTLY IGNORED. The declaration reads as
    conditional and the graph routes unconditionally."""
    from examples.ladder.stage9_decision import (
        complaint, escalate, handled, intake, report, report_out, research, route, verdict)
    from examples.ladder.stage9_decision import Routine, Triage, Urgent, careful
    from workflow_workbench import END, START, EdgeSpec

    class StrayWhen(Triage):
        name = "stray_when"
        edges = (EdgeSpec(START, intake, complaint, when=Urgent),
                 EdgeSpec(intake, route, verdict),
                 EdgeSpec(route, escalate, verdict, when=Urgent),
                 EdgeSpec(route, research, verdict, when=Routine),
                 EdgeSpec(escalate, report, handled),
                 EdgeSpec(research, report, handled),
                 EdgeSpec(report, END, report_out))

    with pytest.raises(SpecError, match="is not a DecisionSpec"):
        StrayWhen().render(careful)


def test_rung9_reachability_runs_through_branches() -> None:
    """The gain over the escape hatch: before DecisionSpec a branching design could only be built
    by overriding build_pydantic_structure(), which reports reachability NOT CHECKED for the whole
    design — so every branching workflow was entirely unchecked."""
    from examples.ladder.stage9_decision import Triage, careful

    assert not any("NOT CHECKED" in f for f in Triage().check(careful))


def test_rung9_the_diagram_labels_branches_by_type_not_variable() -> None:
    """Both branches carry `verdict`; labelling by variable draws two identical arrows out of the
    router and hides the only thing the picture is for."""
    from examples.ladder.stage9_decision import Triage, careful

    out = Triage().diagram(careful)
    assert "route{{" in out, "a router should not be drawn as a step"
    assert "-- Urgent -->" in out and "-- Routine -->" in out


# ── the capability matrix must not go stale ─────────────────────────────────────────────────

def test_the_capability_matrix_classifies_every_public_graphbuilder_method() -> None:
    """⛔ Why this exists: the matrix was hand-written from a grep and MISSED FIVE — `stream`,
    `node`, `match_node`, `add_mapping_edge`, and the `matches=` predicate form of `match`. It
    read as a complete inventory of what this library does not cover, and it was not one.

    A hand-maintained list of someone else's API is wrong the moment they add to it, and nothing
    says so. This runs the probe, which introspects `GraphBuilder` and exits non-zero if any
    public method is unclassified — so the next thing pydantic-graph ships turns this red instead
    of silently widening a gap we describe as closed.
    """
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    proc = subprocess.run([sys.executable, "docs/probe_builder_features.py"],
                          cwd=root, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, (
        f"the capability matrix is out of date:\n{proc.stdout[-2500:]}\n{proc.stderr[-1500:]}")
    assert "all 16 public GraphBuilder methods are classified" in proc.stdout or \
           "public GraphBuilder methods are classified" in proc.stdout, proc.stdout[-800:]
