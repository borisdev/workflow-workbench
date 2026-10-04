"""`StepSpec.problem` — the implementer's brief, and what its absence must not mean."""
from __future__ import annotations

from workflow_workbench import EdgeSpec, END, START, GraphSpec, StepSpec, VariableSpec
from workflow_workbench.devserver import spec_payload
from workflow_workbench.payload import WorkflowReport


def test_problem_is_keyword_only_so_the_fourth_positional_still_means_streams() -> None:
    """⛔ THE REGRESSION THIS FIELD ALREADY CAUSED ONCE. `problem` was inserted BEFORE `streams`
    as a positional field, so `StepSpec("x", (), (), True)` stopped meaning "a streaming node"
    and started meaning `problem=True` — no type error anywhere, and a node that silently does
    not stream. Keyword-only restores the old call's old meaning.
    """
    import dataclasses

    v = VariableSpec("v", str)
    n = StepSpec("x", (v,), (v,), True)
    assert n.streams is True, "the fourth positional argument no longer means `streams`"
    assert n.problem == ""

    f = {fld.name: fld for fld in dataclasses.fields(StepSpec)}
    assert f["problem"].kw_only, "`problem` must stay keyword-only — see the docstring above"
    assert not f["streams"].kw_only, (
        "`streams` became keyword-only, which is a SECOND breaking change to the same "
        "constructor and not what this fix was for")


def test_problem_defaults_to_empty_and_is_additive() -> None:
    """Every existing declaration keeps working — the field is new and optional."""
    assert StepSpec("x").problem == ""


def test_problem_reaches_the_browser_payload() -> None:
    """⚠️ A field nothing consumes is decoration. This is its consumer: the tool you open to
    READ a design is where the brief has to appear."""
    v = VariableSpec("v", str)
    hard = StepSpec("hard", inputs=(v,), outputs=(v,),
                    problem="Two reasonable implementations disagree completely.")

    class D(GraphSpec):
        name = "d"
        input_type, output_type = str, str
        nodes = (hard,)
        edges = (EdgeSpec(source=START, target=hard, carries=v),
                 EdgeSpec(source=hard, target=END, carries=v))

    payload = WorkflowReport.model_validate(spec_payload(D(), []))
    node = next(n for n in payload.nodes if n.id == "hard")
    assert node.problem == "Two reasonable implementations disagree completely."


def test_an_absent_brief_is_distinguishable_from_a_written_one() -> None:
    """⛔ `""` means NOBODY WROTE ONE. It must never be readable as "this stage is easy" — an
    unwritten brief and a stage with no judgement in it are different facts, and conflating them
    is `checks.md`'s NOT CHECKED versus 0 FOUND in another costume."""
    assert StepSpec("a").problem == ""
    assert StepSpec("b", problem="x").problem == "x"
    assert StepSpec("a").problem != "none", "absence must not be spelled as a claim"


def test_a_subgraph_binding_cannot_also_be_unbound_or_skipped() -> None:
    """⛔ `subgraph=True` claims a whole child design fills this role. `unbound` says nobody
    wired it and `skipped` says this arm declined to run it — both the opposite claim. The
    payload accepted the combination, so the viewer could draw a composed badge on a stage with
    nothing behind it, which is `.claude/rules/case-build.md` §3: a check that was skipped must
    never render as a value.
    """
    import pytest
    from pydantic import ValidationError

    from workflow_workbench.payload import Binding

    assert Binding(impl="child::thorough", subgraph=True).subgraph
    for bad in ({"impl": None, "unbound": True}, {"impl": "x", "skipped": True}):
        with pytest.raises(ValidationError, match="subgraph"):
            Binding(subgraph=True, **bad)
