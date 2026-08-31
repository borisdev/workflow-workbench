"""A health-stack evidence workflow built with Workflow Workbench.

The workbench graph is the PROCESS graph. Its final ``CaseReport`` contains the
separate DOMAIN graph of medical concepts and predications.

    health-stack text
      -> extract mentions + profile
      -> resolve CUIs
      -> build user-given predications
      -> attach evidence to given edges
      -> discover evidence-backed candidate gaps
      -> rank a small Health Stack Story projection

Run:
    uv run python3 -m examples.local.health_stack
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from workflow_workbench import (
    END,
    START,
    EdgeSpec,
    GraphSpec,
    NodeSpec,
    StrategySpec,
    VariableSpec,
)


# ── Domain model: the output being built ──────────────────────────────────────

@dataclass(frozen=True)
class Mention:
    id: str
    text: str
    kind: str


@dataclass(frozen=True)
class ProfileItem:
    kind: str
    term: str
    value: str | int | float | None = None
    unit: str | None = None


@dataclass(frozen=True)
class DraftPredication:
    subject_id: str
    predicate: str
    object_id: str
    quote: str


@dataclass(frozen=True)
class ExtractedCase:
    source_text: str
    mentions: tuple[Mention, ...]
    profile: tuple[ProfileItem, ...]
    stated_predications: tuple[DraftPredication, ...]


@dataclass(frozen=True)
class Concept:
    id: str
    cui: str | None
    preferred_term: str
    kind: str


@dataclass(frozen=True)
class ResolvedCase:
    source_text: str
    concepts: tuple[Concept, ...]
    profile: tuple[ProfileItem, ...]
    stated_predications: tuple[DraftPredication, ...]


@dataclass(frozen=True)
class Evidence:
    pmid: str
    sentence: str


@dataclass(frozen=True)
class Predication:
    subject_id: str
    predicate: str
    object_id: str
    origin: str
    quote: str | None = None
    evidence: tuple[Evidence, ...] = ()
    relevance: float | None = None


@dataclass(frozen=True)
class CaseGraph:
    concepts: tuple[Concept, ...]
    profile: tuple[ProfileItem, ...]
    edges: tuple[Predication, ...]


@dataclass(frozen=True)
class CaseReport:
    full_graph: CaseGraph
    story_edges: tuple[Predication, ...]


@dataclass(frozen=True)
class Neighborhood:
    concepts: tuple[Concept, ...]
    edges: tuple[Predication, ...]


# ── Replaceable infrastructure, supplied through ctx.deps ────────────────────

class UMLS(Protocol):
    async def resolve(self, mention: Mention, context: str) -> Concept: ...


class SemMed(Protocol):
    async def evidence_for(self, edge: Predication, concepts: tuple[Concept, ...]) -> tuple[Evidence, ...]: ...
    async def neighbors(self, concept: Concept) -> Neighborhood: ...


@dataclass(frozen=True)
class Services:
    umls: UMLS
    semmed: SemMed


# ── Design: stable roles and named values ────────────────────────────────────

health_stack_text = VariableSpec("health_stack_text", str)
extracted_case = VariableSpec("extracted_case", ExtractedCase)
resolved_case = VariableSpec("resolved_case", ResolvedCase)
given_graph = VariableSpec("given_graph", CaseGraph)
cited_given_graph = VariableSpec("cited_given_graph", CaseGraph)
expanded_graph = VariableSpec("expanded_graph", CaseGraph)
case_report = VariableSpec("case_report", CaseReport)

extract_case = NodeSpec("extract_case", inputs=(health_stack_text,), outputs=(extracted_case,))
resolve_concepts = NodeSpec("resolve_concepts", inputs=(extracted_case,), outputs=(resolved_case,))
build_given_graph = NodeSpec("build_given_graph", inputs=(resolved_case,), outputs=(given_graph,))
cite_given_edges = NodeSpec("cite_given_edges", inputs=(given_graph,), outputs=(cited_given_graph,))
discover_candidate_gaps = NodeSpec(
    "discover_candidate_gaps", inputs=(cited_given_graph,), outputs=(expanded_graph,)
)
rank_story = NodeSpec("rank_story", inputs=(expanded_graph,), outputs=(case_report,))


class HealthStackEvidence(GraphSpec):
    """One fixed design; extraction, discovery, and ranking may be battled."""

    name = "health_stack_evidence"
    input_type, output_type = str, CaseReport
    deps_type = Services
    nodes = (
        extract_case,
        resolve_concepts,
        build_given_graph,
        cite_given_edges,
        discover_candidate_gaps,
        rank_story,
    )
    edges = (
        EdgeSpec(source=START, target=extract_case, carries=health_stack_text),
        EdgeSpec(source=extract_case, target=resolve_concepts, carries=extracted_case),
        EdgeSpec(source=resolve_concepts, target=build_given_graph, carries=resolved_case),
        EdgeSpec(source=build_given_graph, target=cite_given_edges, carries=given_graph),
        EdgeSpec(source=cite_given_edges, target=discover_candidate_gaps, carries=cited_given_graph),
        EdgeSpec(source=discover_candidate_gaps, target=rank_story, carries=expanded_graph),
        EdgeSpec(source=rank_story, target=END, carries=case_report),
    )


# ── One deterministic strategy used by the executable test ───────────────────

async def fixture_extract(ctx) -> ExtractedCase:
    """A deterministic stand-in for the LLM; deliberately tiny, not clinical NLP."""
    text = ctx.inputs
    mentions = (
        Mention("semaglutide", "oral semaglutide", "intervention"),
        Mention("obesity", "obesity", "condition"),
        Mention("amphetamine", "daily amphetamine", "intervention"),
        Mention("adhd", "ADHD", "condition"),
    )
    return ExtractedCase(
        source_text=text,
        mentions=mentions,
        profile=(
            ProfileItem("sex", "male"),
            ProfileItem("anthropometric", "height", 74, "in"),
            ProfileItem("anthropometric", "weight", 265, "lb"),
            ProfileItem("anthropometric", "BMI", 34),
            ProfileItem("goal", "weight", 200, "lb"),
        ),
        stated_predications=(
            DraftPredication("semaglutide", "TREATS", "obesity", "oral semaglutide plan"),
            DraftPredication("amphetamine", "TREATS", "adhd", "ADHD, on a daily amphetamine"),
        ),
    )


async def resolve_all(ctx) -> ResolvedCase:
    concepts = tuple(
        [await ctx.deps.umls.resolve(m, ctx.inputs.source_text) for m in ctx.inputs.mentions]
    )
    return ResolvedCase(
        source_text=ctx.inputs.source_text,
        concepts=concepts,
        profile=ctx.inputs.profile,
        stated_predications=ctx.inputs.stated_predications,
    )


async def build_stated(ctx) -> CaseGraph:
    return CaseGraph(
        concepts=ctx.inputs.concepts,
        profile=ctx.inputs.profile,
        edges=tuple(
            Predication(e.subject_id, e.predicate, e.object_id, "user", quote=e.quote)
            for e in ctx.inputs.stated_predications
        ),
    )


async def cite_stated(ctx) -> CaseGraph:
    cited: list[Predication] = []
    for edge in ctx.inputs.edges:
        evidence = await ctx.deps.semmed.evidence_for(edge, ctx.inputs.concepts)
        cited.append(Predication(**{**edge.__dict__, "evidence": evidence}))
    edges = tuple(cited)
    return CaseGraph(ctx.inputs.concepts, ctx.inputs.profile, edges)


async def discover_neighbors(ctx) -> CaseGraph:
    candidates: list[Predication] = []
    concepts = list(ctx.inputs.concepts)
    for concept in ctx.inputs.concepts:
        neighborhood = await ctx.deps.semmed.neighbors(concept)
        concepts.extend(neighborhood.concepts)
        candidates.extend(neighborhood.edges)
    existing = {(e.subject_id, e.predicate, e.object_id) for e in ctx.inputs.edges}
    novel = tuple(
        e for e in candidates if (e.subject_id, e.predicate, e.object_id) not in existing
    )
    unique_concepts = {concept.id: concept for concept in concepts}
    return CaseGraph(tuple(unique_concepts.values()), ctx.inputs.profile, ctx.inputs.edges + novel)


async def compact_story(ctx) -> CaseReport:
    ranked = sorted(
        ctx.inputs.edges,
        key=lambda edge: (
            edge.origin == "discovered",
            edge.relevance or 0,
            len(edge.evidence),
        ),
        reverse=True,
    )
    return CaseReport(ctx.inputs, tuple(ranked[:8]))


async def full_story(ctx) -> CaseReport:
    return CaseReport(ctx.inputs, ctx.inputs.edges)


compact = StrategySpec(
    "compact",
    {
        extract_case: fixture_extract,
        resolve_concepts: resolve_all,
        build_given_graph: build_stated,
        cite_given_edges: cite_stated,
        discover_candidate_gaps: discover_neighbors,
        rank_story: compact_story,
    },
)

full = StrategySpec(
    "full",
    {
        extract_case: fixture_extract,
        resolve_concepts: resolve_all,
        build_given_graph: build_stated,
        cite_given_edges: cite_stated,
        discover_candidate_gaps: discover_neighbors,
        rank_story: full_story,
    },
)


class FakeUMLS:
    async def resolve(self, mention: Mention, context: str) -> Concept:
        cuis = {
            "semaglutide": "C3502608",
            "obesity": "C0028754",
            "amphetamine": "C0002658",
            "adhd": "C1263846",
        }
        return Concept(mention.id, cuis[mention.id], mention.text, mention.kind)


class FakeSemMed:
    async def evidence_for(self, edge, concepts):
        return (Evidence("100", f"Evidence sentence for {edge.predicate}."),)

    async def neighbors(self, concept):
        if concept.id != "semaglutide":
            return Neighborhood((), ())
        return Neighborhood(
            concepts=(Concept("gi_tolerability", "C0017178", "GI tolerability", "outcome"),),
            edges=(
                Predication(
                    "semaglutide",
                    "CAUSES",
                    "gi_tolerability",
                    "discovered",
                    evidence=(Evidence("200", "Semaglutide was associated with gastrointestinal adverse events."),),
                    relevance=0.9,
                ),
            ),
        )


def main() -> None:
    spec = HealthStackEvidence()
    services = Services(FakeUMLS(), FakeSemMed())
    report = spec.render(compact).run_sync(
        inputs="Man, 6'2, 265 lb (BMI 34), ADHD, daily amphetamine; oral semaglutide plan.",
        deps=services,
    )
    print(spec.diagram(compact))
    print(f"full edges: {len(report.full_graph.edges)}; story edges: {len(report.story_edges)}")
    print(f"varies: {spec.varies(compact, full)}")


if __name__ == "__main__":
    main()
