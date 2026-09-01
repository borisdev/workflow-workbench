"""A typed NoBSmed four-pattern causal-evidence workflow.

The example is intentionally provider-neutral. ``FourPatternDeps.backend`` is the adapter seam for
the real intake extractor, UMLS resolver, SemMedDB store, and pertinence model.  The graph itself
declares the stable reasoning design:

    intake -> extract -> resolve/cluster -> five query branches -> five bounded rankers
           -> join -> canonicalize predications -> validated CaseGraph

Run the deterministic example with::

    uv run python -m examples.four_pattern_case_graph
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal, Protocol, TypeAlias

from pydantic import BaseModel, Field, model_validator
from pydantic_graph.join import reduce_list_append

from workflow_workbench import (
    END,
    START,
    EdgeSpec,
    GraphSpec,
    JoinSpec,
    NodeSpec,
    StrategySpec,
    VariableSpec,
)


# ---- Domain types -------------------------------------------------------------------------


class SemMedPredicate(StrEnum):
    CAUSES = "CAUSES"
    TREATS = "TREATS"
    PREVENTS = "PREVENTS"
    ASSOCIATED_WITH = "ASSOCIATED_WITH"
    NEG_CAUSES = "NEG_CAUSES"
    NEG_TREATS = "NEG_TREATS"
    NEG_PREVENTS = "NEG_PREVENTS"


class RawIntake(BaseModel):
    narrative: str


class ExtractedIntake(BaseModel):
    condition_mentions: tuple[str, ...]
    intervention_mentions: tuple[str, ...]
    desired_outcome_mentions: tuple[str, ...] = ()
    cohort: dict[str, str] = Field(default_factory=dict)
    observations: tuple[str, ...] = ()


class Concept(BaseModel):
    cui: str
    name: str


class ConditionConcept(Concept):
    kind: Literal["condition"] = "condition"


class InterventionConcept(Concept):
    kind: Literal["intervention"] = "intervention"


class CaseObservation(BaseModel):
    text: str
    concept: Concept | None = None


class CaseContext(BaseModel):
    """Canonical query anchors plus patient context used by every pertinence ranker."""

    conditions: tuple[ConditionConcept, ...]
    interventions: tuple[InterventionConcept, ...]
    desired_outcomes: tuple[ConditionConcept, ...] = ()
    cohort: dict[str, str] = Field(default_factory=dict)
    observations: tuple[CaseObservation, ...] = ()


class UpstreamCausePredication(BaseModel):
    kind: Literal["upstream_cause"] = "upstream_cause"
    subject: ConditionConcept
    predicate: Literal[SemMedPredicate.CAUSES]
    object: ConditionConcept


class TestingLeadPredication(BaseModel):
    kind: Literal["testing_lead"] = "testing_lead"
    subject: ConditionConcept
    predicate: Literal[SemMedPredicate.ASSOCIATED_WITH]
    object: ConditionConcept


class HarmPredication(BaseModel):
    kind: Literal["harm"] = "harm"
    subject: InterventionConcept
    predicate: Literal[SemMedPredicate.CAUSES]
    object: ConditionConcept


class TreatmentPredication(BaseModel):
    kind: Literal["treatment"] = "treatment"
    subject: InterventionConcept
    predicate: Literal[SemMedPredicate.TREATS]
    object: ConditionConcept


class PreventionPredication(BaseModel):
    kind: Literal["prevention"] = "prevention"
    subject: InterventionConcept
    predicate: Literal[SemMedPredicate.PREVENTS]
    object: ConditionConcept


class NegatedCausePredication(BaseModel):
    kind: Literal["negated_cause"] = "negated_cause"
    subject: ConditionConcept | InterventionConcept
    predicate: Literal[SemMedPredicate.NEG_CAUSES]
    object: ConditionConcept


class NegatedTreatmentPredication(BaseModel):
    kind: Literal["negated_treatment"] = "negated_treatment"
    subject: InterventionConcept
    predicate: Literal[SemMedPredicate.NEG_TREATS]
    object: ConditionConcept


class NegatedPreventionPredication(BaseModel):
    kind: Literal["negated_prevention"] = "negated_prevention"
    subject: InterventionConcept
    predicate: Literal[SemMedPredicate.NEG_PREVENTS]
    object: ConditionConcept


PositivePredication: TypeAlias = (
    UpstreamCausePredication
    | HarmPredication
    | TreatmentPredication
    | PreventionPredication
)
EvidencePredication: TypeAlias = (
    TreatmentPredication
    | PreventionPredication
    | NegatedCausePredication
    | NegatedTreatmentPredication
    | NegatedPreventionPredication
)
AnyRetrievedPredication: TypeAlias = (
    PositivePredication | TestingLeadPredication | EvidencePredication
)


class EvidenceFinding(BaseModel):
    pmid: str
    sentence: str


class Candidate(BaseModel):
    predication: AnyRetrievedPredication
    findings: tuple[EvidenceFinding, ...] = ()


class RankedCandidate(BaseModel):
    candidate: Candidate
    pertinence: float = Field(ge=0.0, le=1.0)
    rationale: str


class CandidateBatch(BaseModel):
    context: CaseContext
    items: tuple[Candidate, ...] = ()


class RankedBatch(BaseModel):
    pattern: Literal["upstream", "testing", "harms", "evidence", "alternatives"]
    context: CaseContext
    items: tuple[RankedCandidate, ...] = ()


class CanonicalPredication(BaseModel):
    subject: Concept
    predicate: Literal[
        SemMedPredicate.CAUSES,
        SemMedPredicate.TREATS,
        SemMedPredicate.PREVENTS,
    ]
    object: ConditionConcept
    discovered_by: set[str] = Field(default_factory=set)
    findings: list[EvidenceFinding] = Field(default_factory=list)

    @property
    def key(self) -> tuple[str, SemMedPredicate, str]:
        return self.subject.cui, self.predicate, self.object.cui


class EvidenceAssessment(BaseModel):
    predication_key: tuple[str, SemMedPredicate, str]
    supporting_pmids: set[str] = Field(default_factory=set)
    contesting_pmids: set[str] = Field(default_factory=set)


class CaseGraph(BaseModel):
    context: CaseContext
    concepts: dict[str, Concept]
    predications: dict[str, CanonicalPredication]
    testing_leads: list[TestingLeadPredication] = Field(default_factory=list)
    evidence: list[EvidenceAssessment] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_graph(self) -> "CaseGraph":
        for edge in self.predications.values():
            if edge.subject.cui not in self.concepts or edge.object.cui not in self.concepts:
                raise ValueError("every predication endpoint must resolve to a graph concept")
            if edge.key[1].value.startswith("NEG_"):
                raise ValueError("negated evidence must not become a causal graph edge")
        return self


# ---- Dependency seam ----------------------------------------------------------------------


class FourPatternBackend(Protocol):
    async def extract(self, intake: RawIntake) -> ExtractedIntake: ...

    async def resolve_and_cluster(self, intake: ExtractedIntake) -> CaseContext: ...

    async def query(self, pattern: str, context: CaseContext) -> CandidateBatch: ...

    async def rank(
        self, pattern: str, candidates: CandidateBatch, context: CaseContext, limit: int
    ) -> RankedBatch: ...


@dataclass
class FourPatternDeps:
    backend: FourPatternBackend
    branch_limit: int = 20


@dataclass
class FourPatternState:
    calls: list[str] = field(default_factory=list)


# ---- Declarative workflow -----------------------------------------------------------------


raw_intake_v = VariableSpec("raw_intake", RawIntake)
extracted_v = VariableSpec("extracted_intake", ExtractedIntake)
context_v = VariableSpec("case_context", CaseContext)

upstream_candidates_v = VariableSpec("upstream_candidates", CandidateBatch)
testing_candidates_v = VariableSpec("testing_candidates", CandidateBatch)
harm_candidates_v = VariableSpec("harm_candidates", CandidateBatch)
evidence_candidates_v = VariableSpec("evidence_candidates", CandidateBatch)
alternative_candidates_v = VariableSpec("alternative_candidates", CandidateBatch)

ranked_upstream_v = VariableSpec("ranked_upstream", RankedBatch)
ranked_testing_v = VariableSpec("ranked_testing", RankedBatch)
ranked_harms_v = VariableSpec("ranked_harms", RankedBatch)
ranked_evidence_v = VariableSpec("ranked_evidence", RankedBatch)
ranked_alternatives_v = VariableSpec("ranked_alternatives", RankedBatch)
joined_v = VariableSpec("pattern_results", list)
case_graph_v = VariableSpec("case_graph", CaseGraph)

extract_intake = NodeSpec("extract_intake", inputs=(raw_intake_v,), outputs=(extracted_v,))
resolve_concepts = NodeSpec("resolve_and_cluster_concepts", inputs=(extracted_v,), outputs=(context_v,))

query_upstream = NodeSpec("query_upstream_causes", inputs=(context_v,), outputs=(upstream_candidates_v,))
query_testing = NodeSpec("query_testing_leads", inputs=(context_v,), outputs=(testing_candidates_v,))
query_harms = NodeSpec("query_harms", inputs=(context_v,), outputs=(harm_candidates_v,))
query_evidence = NodeSpec("query_current_evidence", inputs=(context_v,), outputs=(evidence_candidates_v,))
query_alternatives = NodeSpec("query_alternatives", inputs=(context_v,), outputs=(alternative_candidates_v,))

rank_upstream = NodeSpec("rank_upstream", inputs=(upstream_candidates_v,), outputs=(ranked_upstream_v,))
rank_testing = NodeSpec("rank_testing", inputs=(testing_candidates_v,), outputs=(ranked_testing_v,))
rank_harms = NodeSpec("rank_harms", inputs=(harm_candidates_v,), outputs=(ranked_harms_v,))
rank_evidence = NodeSpec("rank_evidence", inputs=(evidence_candidates_v,), outputs=(ranked_evidence_v,))
rank_alternatives = NodeSpec(
    "rank_alternatives", inputs=(alternative_candidates_v,), outputs=(ranked_alternatives_v,)
)

collect_patterns = JoinSpec(
    "collect_pattern_results",
    reduce_list_append,
    initial_factory=list,
    inputs=(ranked_upstream_v, ranked_testing_v, ranked_harms_v, ranked_evidence_v,
            ranked_alternatives_v),
    outputs=(joined_v,),
)
assemble_graph = NodeSpec("dedupe_and_build_case_graph", inputs=(joined_v,), outputs=(case_graph_v,))


class FourPatternCaseGraph(GraphSpec):
    name = "four_pattern_case_graph"
    state_type, deps_type = FourPatternState, FourPatternDeps
    input_type, output_type = RawIntake, CaseGraph
    nodes = (
        extract_intake,
        resolve_concepts,
        query_upstream,
        query_testing,
        query_harms,
        query_evidence,
        query_alternatives,
        rank_upstream,
        rank_testing,
        rank_harms,
        rank_evidence,
        rank_alternatives,
        assemble_graph,
    )
    joins = (collect_patterns,)
    edges = (
        EdgeSpec(source=START, target=extract_intake, carries=raw_intake_v),
        EdgeSpec(source=extract_intake, target=resolve_concepts, carries=extracted_v),
        EdgeSpec(source=resolve_concepts, target=query_upstream, carries=context_v),
        EdgeSpec(source=resolve_concepts, target=query_testing, carries=context_v),
        EdgeSpec(source=resolve_concepts, target=query_harms, carries=context_v),
        EdgeSpec(source=resolve_concepts, target=query_evidence, carries=context_v),
        EdgeSpec(source=resolve_concepts, target=query_alternatives, carries=context_v),
        EdgeSpec(source=query_upstream, target=rank_upstream, carries=upstream_candidates_v),
        EdgeSpec(source=query_testing, target=rank_testing, carries=testing_candidates_v),
        EdgeSpec(source=query_harms, target=rank_harms, carries=harm_candidates_v),
        EdgeSpec(source=query_evidence, target=rank_evidence, carries=evidence_candidates_v),
        EdgeSpec(source=query_alternatives, target=rank_alternatives, carries=alternative_candidates_v),
        EdgeSpec(source=rank_upstream, target=collect_patterns, carries=ranked_upstream_v),
        EdgeSpec(source=rank_testing, target=collect_patterns, carries=ranked_testing_v),
        EdgeSpec(source=rank_harms, target=collect_patterns, carries=ranked_harms_v),
        EdgeSpec(source=rank_evidence, target=collect_patterns, carries=ranked_evidence_v),
        EdgeSpec(source=rank_alternatives, target=collect_patterns, carries=ranked_alternatives_v),
        EdgeSpec(source=collect_patterns, target=assemble_graph, carries=joined_v),
        EdgeSpec(source=assemble_graph, target=END, carries=case_graph_v),
    )


# ---- Strategy implementations --------------------------------------------------------------


async def extract_impl(ctx) -> ExtractedIntake:
    ctx.state.calls.append("extract")
    return await ctx.deps.backend.extract(ctx.inputs)


async def resolve_impl(ctx) -> CaseContext:
    ctx.state.calls.append("resolve")
    return await ctx.deps.backend.resolve_and_cluster(ctx.inputs)


def query_impl(pattern: str):
    async def run(ctx) -> CandidateBatch:
        ctx.state.calls.append(f"query:{pattern}")
        return await ctx.deps.backend.query(pattern, ctx.inputs)

    run.__name__ = f"query_{pattern}_impl"
    return run


def rank_impl(pattern: str):
    async def run(ctx) -> RankedBatch:
        ctx.state.calls.append(f"rank:{pattern}")
        return await ctx.deps.backend.rank(
            pattern, ctx.inputs, ctx.inputs.context, ctx.deps.branch_limit
        )

    run.__name__ = f"rank_{pattern}_impl"
    return run


def _positive_key(p: AnyRetrievedPredication) -> tuple[str, SemMedPredicate, str] | None:
    if p.predicate in {SemMedPredicate.CAUSES, SemMedPredicate.TREATS, SemMedPredicate.PREVENTS}:
        return p.subject.cui, p.predicate, p.object.cui
    return None


def _positive_of_negated(p: EvidencePredication) -> tuple[str, SemMedPredicate, str] | None:
    inverse = {
        SemMedPredicate.NEG_CAUSES: SemMedPredicate.CAUSES,
        SemMedPredicate.NEG_TREATS: SemMedPredicate.TREATS,
        SemMedPredicate.NEG_PREVENTS: SemMedPredicate.PREVENTS,
    }
    predicate = inverse.get(p.predicate)
    return None if predicate is None else (p.subject.cui, predicate, p.object.cui)


async def assemble_impl(ctx) -> CaseGraph:
    ctx.state.calls.append("assemble")
    batches: list[RankedBatch] = ctx.inputs
    if not batches:
        raise ValueError("the pattern join produced no branch results")
    context = batches[0].context
    if any(batch.context != context for batch in batches[1:]):
        raise ValueError("all pattern branches must describe the same case context")
    concepts: dict[str, Concept] = {}
    canonical: dict[tuple[str, SemMedPredicate, str], CanonicalPredication] = {}
    testing: dict[tuple[str, str], TestingLeadPredication] = {}
    support: dict[tuple[str, SemMedPredicate, str], set[str]] = {}
    contest: dict[tuple[str, SemMedPredicate, str], set[str]] = {}

    current_interventions = {c.cui for c in context.interventions}
    for batch in batches:
        for ranked in batch.items:
            candidate = ranked.candidate
            p = candidate.predication
            concepts[p.subject.cui] = p.subject
            concepts[p.object.cui] = p.object

            if isinstance(p, TestingLeadPredication):
                testing[(p.subject.cui, p.object.cui)] = p
                continue

            negated_key = _positive_of_negated(p) if p.predicate.value.startswith("NEG_") else None
            if negated_key is not None:
                contest.setdefault(negated_key, set()).update(f.pmid for f in candidate.findings)
                continue

            key = _positive_key(p)
            if key is None:
                continue

            # An intervention already in the case is current evidence, not an alternative, even
            # if the alternatives query also found it.
            discovered_as = batch.pattern
            if batch.pattern == "alternatives" and p.subject.cui in current_interventions:
                discovered_as = "evidence"

            edge = canonical.setdefault(
                key,
                CanonicalPredication(
                    subject=p.subject,
                    predicate=p.predicate,
                    object=p.object,
                ),
            )
            edge.discovered_by.add(discovered_as)
            known_pmids = {f.pmid for f in edge.findings}
            edge.findings.extend(f for f in candidate.findings if f.pmid not in known_pmids)
            support.setdefault(key, set()).update(f.pmid for f in candidate.findings)

    predications = {
        f"p{index}": edge
        for index, edge in enumerate(sorted(canonical.values(), key=lambda e: e.key), start=1)
    }
    evidence = [
        EvidenceAssessment(
            predication_key=key,
            supporting_pmids=support.get(key, set()),
            contesting_pmids=contest.get(key, set()),
        )
        for key in sorted(set(support) | set(contest))
    ]
    return CaseGraph(
        context=context,
        concepts=concepts,
        predications=predications,
        testing_leads=list(testing.values()),
        evidence=evidence,
    )


production = StrategySpec(
    "production",
    {
        extract_intake: extract_impl,
        resolve_concepts: resolve_impl,
        query_upstream: query_impl("upstream"),
        query_testing: query_impl("testing"),
        query_harms: query_impl("harms"),
        query_evidence: query_impl("evidence"),
        query_alternatives: query_impl("alternatives"),
        rank_upstream: rank_impl("upstream"),
        rank_testing: rank_impl("testing"),
        rank_harms: rank_impl("harms"),
        rank_evidence: rank_impl("evidence"),
        rank_alternatives: rank_impl("alternatives"),
        assemble_graph: assemble_impl,
    },
)


# ---- Deterministic executable backend ------------------------------------------------------


class DemoBackend:
    """Small fixture proving topology and contracts; replace this class in production."""

    async def extract(self, intake: RawIntake) -> ExtractedIntake:
        return ExtractedIntake(
            condition_mentions=("fatigue",),
            intervention_mentions=("sertraline",),
            cohort={"age": "42", "sex": "female"},
            observations=("ferritin 8 ng/mL",),
        )

    async def resolve_and_cluster(self, intake: ExtractedIntake) -> CaseContext:
        return CaseContext(
            conditions=(ConditionConcept(cui="C0015672", name="Fatigue"),),
            interventions=(InterventionConcept(cui="C0074393", name="Sertraline"),),
            cohort=intake.cohort,
            observations=tuple(CaseObservation(text=x) for x in intake.observations),
        )

    async def query(self, pattern: str, context: CaseContext) -> CandidateBatch:
        fatigue = context.conditions[0]
        sertraline = context.interventions[0]
        iron = ConditionConcept(cui="C0240066", name="Iron deficiency")
        nausea = ConditionConcept(cui="C0027497", name="Nausea")
        exercise = InterventionConcept(cui="C0015259", name="Exercise")
        finding = (EvidenceFinding(pmid="123", sentence="Example evidence sentence."),)
        rows: dict[str, tuple[Candidate, ...]] = {
            "upstream": (Candidate(predication=UpstreamCausePredication(
                subject=iron, predicate=SemMedPredicate.CAUSES, object=fatigue), findings=finding),),
            "testing": (Candidate(predication=TestingLeadPredication(
                subject=iron, predicate=SemMedPredicate.ASSOCIATED_WITH, object=fatigue), findings=finding),),
            "harms": (Candidate(predication=HarmPredication(
                subject=sertraline, predicate=SemMedPredicate.CAUSES, object=nausea), findings=finding),),
            "evidence": (Candidate(predication=TreatmentPredication(
                subject=sertraline, predicate=SemMedPredicate.TREATS, object=fatigue), findings=finding),),
            "alternatives": (Candidate(predication=TreatmentPredication(
                subject=exercise, predicate=SemMedPredicate.TREATS, object=fatigue), findings=finding),),
        }
        return CandidateBatch(context=context, items=rows[pattern])

    async def rank(
        self, pattern: str, candidates: CandidateBatch, context: CaseContext, limit: int
    ) -> RankedBatch:
        return RankedBatch(
            pattern=pattern,
            context=context,
            items=tuple(
                RankedCandidate(candidate=c, pertinence=0.9, rationale="Relevant to case context")
                for c in candidates.items[:limit]
            ),
        )


def main() -> None:
    spec = FourPatternCaseGraph()
    findings = spec.check(production)
    hard = [f for f in findings if not f.startswith("NOT CHECKED")]
    print(f"check: {hard or 'clean'}")
    result = spec.render(production).run_sync(
        inputs=RawIntake(narrative="Fatigue treated with sertraline; ferritin is 8 ng/mL."),
        state=FourPatternState(),
        deps=FourPatternDeps(backend=DemoBackend()),
    )
    print(f"concepts={len(result.concepts)} predications={len(result.predications)} "
          f"testing_leads={len(result.testing_leads)}")
    print(spec.diagram(production))


if __name__ == "__main__":
    main()
