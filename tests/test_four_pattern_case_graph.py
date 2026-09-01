from examples.four_pattern_case_graph import (
    CaseGraph,
    DemoBackend,
    FourPatternCaseGraph,
    FourPatternDeps,
    FourPatternState,
    RawIntake,
    SemMedPredicate,
    production,
)


def test_four_pattern_design_checks_and_runs() -> None:
    spec = FourPatternCaseGraph()
    assert [f for f in spec.check(production) if not f.startswith("NOT CHECKED")] == []

    state = FourPatternState()
    result = spec.render(production).run_sync(
        inputs=RawIntake(narrative="fatigue"),
        state=state,
        deps=FourPatternDeps(backend=DemoBackend(), branch_limit=3),
    )

    assert isinstance(result, CaseGraph)
    assert {edge.predicate for edge in result.predications.values()} == {
        SemMedPredicate.CAUSES,
        SemMedPredicate.TREATS,
    }
    assert len(result.testing_leads) == 1
    assert all(not edge.predicate.value.startswith("NEG_") for edge in result.predications.values())
    assert {call for call in state.calls if call.startswith("query:")} == {
        "query:upstream",
        "query:testing",
        "query:harms",
        "query:evidence",
        "query:alternatives",
    }


def test_branch_limit_is_applied_before_join() -> None:
    result = FourPatternCaseGraph().render(production).run_sync(
        inputs=RawIntake(narrative="fatigue"),
        state=FourPatternState(),
        deps=FourPatternDeps(backend=DemoBackend(), branch_limit=0),
    )
    assert result.predications == {}
    assert result.testing_leads == []
