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
    "stage4_subgraph", "stage5_battle", "stage6_diagrams", "stage7_iter",
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
