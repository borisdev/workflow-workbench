from examples.local.health_stack import (
    FakeSemMed,
    FakeUMLS,
    HealthStackEvidence,
    Services,
    compact,
    full,
)


CASE = "Man, 6'2, 265 lb (BMI 34). ADHD, daily amphetamine. Oral semaglutide plan."


def test_health_stack_design_and_mocked_run():
    spec = HealthStackEvidence()
    assert spec.check() == []
    assert spec.check(compact) == []

    report = spec.render(compact).run_sync(
        inputs=CASE,
        deps=Services(FakeUMLS(), FakeSemMed()),
    )

    assert len(report.full_graph.profile) == 5
    assert {concept.id for concept in report.full_graph.concepts} >= {"gi_tolerability"}
    assert {edge.origin for edge in report.full_graph.edges} == {"user", "discovered"}
    assert all(edge.evidence for edge in report.full_graph.edges)
    assert [item.term for item in report.full_graph.profile] == [
        "male", "height", "weight", "BMI", "weight"
    ]


def test_only_projection_policy_varies_between_strategies():
    spec = HealthStackEvidence()
    assert set(spec.varies(compact, full)) == {"rank_story"}
    assert sorted(spec.render(compact).nodes) == sorted(spec.render(full).nodes)
