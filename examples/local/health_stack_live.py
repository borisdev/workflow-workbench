"""The health-stack design, run against the REAL services instead of fakes.

The design in `health_stack.py` is unchanged and is imported, not copied — the point of the
workbench is that swapping infrastructure is not a new graph. What changes here is `ctx.deps`
(live UMLS resolver, live MEDLINE-KG, live findings index) and two strategies that differ on one
question:

    medline_only            cite and discover from MEDLINE-KG alone
    medline_plus_findings   the same, plus the findings index for quotable sentences and gaps

⛔ This module imports `nobs.*` and therefore does NOT run in the workbench's own venv. It is not
collected by the workbench test suite. Run it from a checkout of nobsmed-v2, whose environment has
both the clients and pydantic-graph:

    cd /home/borisdev/workspace/nobsmed-v2
    export FINDINGS_API_URL=http://127.0.0.1:8400
    export FINDINGS_API_KEY=...            # see issue #830; the server calls it FINDINGS_SEARCH_API_KEY
    PYTHONPATH=/tmp/wt-health-stack uv run python3 -m examples.local.health_stack_live

⚠️ Every number this prints is measured, and the ones that are NOT measured print as `not asked`.
`.claude/rules/checks.md`: a skipped check and a zero result must never render the same.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, replace

from examples.local.health_stack import (
    CaseGraph,
    CaseReport,
    Concept,
    DraftPredication,
    Evidence,
    ExtractedCase,
    HealthStackEvidence,
    Mention,
    Neighborhood,
    Predication,
    ProfileItem,
    Services,
    build_given_graph,
    build_stated,
    cite_given_edges,
    discover_candidate_gaps,
    extract_case,
    rank_story,
    resolve_all,
    resolve_concepts,
)
from workflow_workbench import StrategySpec

# SemMedDB predicates worth putting in front of a patient. TREATS is the largest bucket in the
# store (12.7M rows) and is EXCLUDED from `nobs.query.medline_kg.CAUSAL_PREDICATES`, which is
# correct for a causal traversal and wrong for citing a treatment plan — every user-stated edge in
# a health stack is a TREATS.
PLAN_PREDICATES = ("TREATS", "PREVENTS", "CAUSES", "PREDISPOSES", "AFFECTS", "COMPLICATES")

# Semantic types worth surfacing as a gap. Without this the top neighbours of any drug are
# `Patients`, `Woman` and other contentless concepts — the exact failure `.claude/rules/project.md`
# records, where a MAX_NEW_NODES cap was hiding a ranking problem rather than fixing it.
GAP_SEMTYPES = frozenset({
    "dsyn",  # disease or syndrome
    "sosy",  # sign or symptom
    "patf",  # pathologic function
    "neop",  # neoplastic process
    "mobd",  # mental or behavioral dysfunction
    "inpo",  # injury or poisoning
    "acab",  # acquired abnormality
    "comd",  # cell or molecular dysfunction
})


# -- live UMLS: the deployed concept resolver -------------------------------------------------

@dataclass
class LiveUMLS:
    """`apps/concept-resolver`, over HTTP. Convergently deterministic: same input, same CUI.

    It answers with ONE concept, not a candidate list — which is the boundary the handoff's design
    wants split into `candidates()` + `select()`. Recorded here rather than worked around: this
    adapter is the BASELINE that split has to beat.
    """

    calls: int = 0
    unresolved: tuple[str, ...] = ()

    async def resolve(self, mention: Mention, context: str) -> Concept:
        from nobs.concept_resolver_client import concept_resolve

        self.calls += 1
        result = await asyncio.to_thread(concept_resolve, mention.text, mention.kind)
        if not result.matched or not result.cui:
            self.unresolved = self.unresolved + (mention.text,)
            # cui=None, NOT a guessed CUI. An unresolved mention stays in the graph as itself;
            # the handoff is explicit that a forced CUI is worse than an honest miss.
            return Concept(mention.id, None, mention.text, mention.kind)
        return Concept(mention.id, result.cui, result.preferred_name, mention.kind)


# -- live evidence: MEDLINE-KG, the 6.9 GB relation store -------------------------------------

def far_end(row) -> tuple[str, str]:
    """The end of a `CausalEdge` that is NOT the seed, honouring `orientation`.

    ⛔ `outgoing_causal` returns rows SWAPPED: it puts the effect in `subject_cui` and the seed in
    `object_cui`, so the two traversal directions aggregate uniformly. The docstring says so in
    bold. Reading `row.object_cui` at face value therefore compares the seed against itself, which
    matches nothing — measured here on 2026-08-31 as `user_edges_cited: 0` across both stacks,
    against a store that has `semaglutide TREATS obesity` 96 times.

    That zero was indistinguishable from "the literature has nothing", which is the failure mode
    `.claude/rules/checks.md` names: a passing-looking result produced by never asking the right
    question. One function, used by every call site, so the un-swap cannot be forgotten twice.
    """
    if getattr(row, "orientation", "as_asserted") == "swapped":
        return row.subject_cui, row.subject_name
    return row.object_cui, row.object_name


class MedlineKgSemMed:
    """SemMedDB predications by CUI pair. PMIDs only — there is no sentence in this store."""

    def __init__(self, store, min_support: int = 3, max_gaps_per_concept: int = 4):
        self.store = store
        self.min_support = min_support
        self.max_gaps_per_concept = max_gaps_per_concept
        self.lookups = 0
        self.cited = 0
        self.uncitable_no_cui = 0

    async def evidence_for(self, edge, concepts) -> tuple[Evidence, ...]:
        by_id = {c.id: c for c in concepts}
        subject, obj = by_id.get(edge.subject_id), by_id.get(edge.object_id)
        if not (subject and obj and subject.cui and obj.cui):
            # An endpoint the resolver could not place. NOT "no evidence" — never asked.
            self.uncitable_no_cui += 1
            return ()
        self.lookups += 1
        rows = await asyncio.to_thread(
            self.store.outgoing_causal, subject.cui, PLAN_PREDICATES, None
        )
        pmids: list[int] = []
        for row in rows:
            if far_end(row)[0] == obj.cui:
                pmids.extend(row.pmids)
        if not pmids:
            return ()
        self.cited += 1
        return tuple(
            # sentence=None -- see Evidence's docstring. This store cannot quote.
            Evidence(str(pmid), None, provenance="medline_kg")
            for pmid in sorted(set(pmids))[:25]
        )

    async def neighbors(self, concept: Concept) -> Neighborhood:
        if not concept.cui:
            return Neighborhood((), ())
        rows = await asyncio.to_thread(
            self.store.outgoing_causal, concept.cui,
            ("CAUSES", "PREDISPOSES", "COMPLICATES"), GAP_SEMTYPES,
        )
        rows = [r for r in rows
                if r.support >= self.min_support and far_end(r)[0] != concept.cui]
        rows.sort(key=lambda r: r.support, reverse=True)
        rows = rows[: self.max_gaps_per_concept]
        new_concepts, edges = [], []
        for row in rows:
            effect_cui, effect_name = far_end(row)
            node_id = f"cui:{effect_cui}"
            new_concepts.append(Concept(node_id, effect_cui, effect_name, "outcome"))
            edges.append(Predication(
                concept.id, row.predicate, node_id, "discovered",
                evidence=tuple(Evidence(str(p), None, provenance="medline_kg")
                               for p in row.pmids[:25]),
                relevance=float(row.support),
            ))
        return Neighborhood(tuple(new_concepts), tuple(edges))


class FindingsAugmented(MedlineKgSemMed):
    """MEDLINE-KG for the relation, the findings index for the SENTENCE.

    The two substrates answer different questions and that is the whole point of the comparison:
    MEDLINE-KG knows that `semaglutide TREATS obesity` is asserted in N papers and cannot tell you
    what any of them SAID. The findings index has a quantified sentence per finding and no notion
    of a CUI at all.
    """

    def __init__(self, store, check_topic: bool = False, **kw):
        super().__init__(store, **kw)
        self.check_topic = check_topic
        self.findings_queries = 0
        self.quotes = 0
        self.quotes_dropped_off_topic = 0

    @staticmethod
    def _mentions(hit: dict, term: str) -> bool:
        """Does the hit's OWN PICO text name this concept?

        The index is pure cosine over PICO text with no concept resolution — the service says so
        in the `corpus` sentence it returns about itself. So a near-miss is not rare and is not
        visible in the score: measured 2026-08-31, `adverse events of Strattera` returned
        edaravone at 0.769 while `adverse events of Amphetamine` returned rimegepant at 0.765 —
        BELOW two on-topic hits at 0.77. A cosine floor cannot separate them; the structured
        `intervention` field can, and it is already in the payload.
        """
        blob = " ".join(str(hit.get(k) or "") for k in
                        ("population", "intervention", "comparator", "outcome")).lower()
        word = term.lower().strip()
        word = word[:-1] if word.endswith("s") and len(word) > 4 else word
        return word in blob

    async def _quotes_for(self, question: str, must_mention: tuple[str, ...] = (),
                          top_k: int = 3) -> tuple[Evidence, ...]:
        from nobs.findings_client import search_findings

        self.findings_queries += 1
        out = await asyncio.to_thread(search_findings, question, top_k)
        found = []
        for hit in out.get("hits", []):
            text = (hit.get("evidence_text") or "").strip()
            # A quantified sentence is the only kind worth quoting to a patient. An unquantified
            # one reads as a verdict and cannot be checked against anything on the page.
            if not text or (hit.get("effect") or {}).get("reporting") != "quantified":
                continue
            if self.check_topic and must_mention and not all(
                    self._mentions(hit, t) for t in must_mention):
                self.quotes_dropped_off_topic += 1
                continue
            found.append(Evidence(f"PMC{hit['pmc']}", text, provenance="findings"))
        self.quotes += len(found)
        return tuple(found)

    async def evidence_for(self, edge, concepts) -> tuple[Evidence, ...]:
        relations = await super().evidence_for(edge, concepts)
        by_id = {c.id: c for c in concepts}
        subject, obj = by_id.get(edge.subject_id), by_id.get(edge.object_id)
        if not (subject and obj):
            return relations
        question = (f"{subject.preferred_term} {edge.predicate.lower()} "
                    f"{obj.preferred_term}: effect size in adults")
        # ⚠️ SUBJECT ONLY, and the object check was REMOVED after measuring it.
        #
        # Demanding both ends looked obviously right — it is what would reject the spironolactone
        # HEART-FAILURE trial quoted under `Spironolactone TREATS Hirsutism`. Measured
        # 2026-08-31, it also rejected all three correct `Semaglutide TREATS Obesity` quotes,
        # dropping GLP1's quoted edges from 5 to 1. The reason is in the payload: every one of
        # those hits has an EMPTY `population` and an outcome of "Change in BMI" or "change in
        # body weight". The word "obesity" is nowhere in the finding, because the corpus labels
        # the measured endpoint, not the indication.
        #
        # So the object check does not need tightening, it needs CONCEPT EXPANSION —
        # obesity ~ BMI ~ body weight — which is precisely what the UMLS resolver holds and this
        # index, being pure cosine over PICO text, has none of. That is a real next step, not a
        # threshold to tune. `.claude/rules/project.md`: run it once without the guard, then name
        # the input where its absence shows. Here the guard was run and the input it broke is
        # named above.
        quotes = await self._quotes_for(question, (subject.preferred_term,))
        return relations + quotes

    async def neighbors(self, concept: Concept) -> Neighborhood:
        base = await super().neighbors(concept)
        if concept.kind != "intervention":
            return base
        question = (f"adverse events and safety outcomes of {concept.preferred_term} "
                    f"in adults: how often and how large")
        quotes = await self._quotes_for(question, (concept.preferred_term,), top_k=4)
        if not quotes:
            return base
        node = Concept(f"findings:{concept.id}:harms", None,
                       f"reported harms of {concept.preferred_term}", "outcome")
        edge = Predication(concept.id, "CAUSES", node.id, "discovered",
                           evidence=quotes, relevance=0.0)
        return Neighborhood(base.concepts + (node,), base.edges + (edge,))


# -- extraction: the two real health stacks, hand-typed, NOT an LLM ---------------------------

GLP1_TEXT = (
    'Man, 6\'2", 265 lb (BMI 34). ADHD, on a daily amphetamine. Goal: get to 200 lb.\n'
    "The plan I was given: oral semaglutide (Wegovy Pill) titrated 1.5 mg to 25 mg; "
    "1,500-1,800 kcal/day; 150 min/week aerobic plus resistance training; "
    "labs glucose, A1C, lipids; indefinite therapy."
)

PCOS_TEXT = (
    "Strattera (atomoxetine) 40 mg for ADHD and anxiety. Spironolactone 100 mg for hirsutism. "
    "Metformin 500 mg removed by doctor due to increasing ALT; was for obesity and "
    "hyperinsulinemia. Vitamin D3 50,000 IU weekly for deficiency. Omega-3 4,100 mg for "
    "insulin resistance and inflammation. Oral minoxidil 1.5 mg for hair loss from PCOS."
)


@dataclass(frozen=True)
class Stack:
    name: str
    text: str
    mentions: tuple[Mention, ...]
    profile: tuple[ProfileItem, ...]
    stated: tuple[tuple[str, str, str, str], ...]


GLP1 = Stack(
    "glp1", GLP1_TEXT,
    mentions=(
        Mention("semaglutide", "semaglutide", "intervention"),
        Mention("obesity", "obesity", "condition"),
        Mention("amphetamine", "amphetamine", "intervention"),
        Mention("adhd", "ADHD", "condition"),
        Mention("weight_loss", "weight loss", "outcome"),
    ),
    profile=(ProfileItem("sex", "male"), ProfileItem("anthropometric", "BMI", 34),
             ProfileItem("goal", "weight", 200, "lb")),
    stated=(
        ("semaglutide", "TREATS", "obesity", "Oral semaglutide (Wegovy Pill), titrated"),
        ("amphetamine", "TREATS", "adhd", "ADHD, on a daily amphetamine"),
        ("semaglutide", "CAUSES", "weight_loss", "Goal: get to 200 lb"),
    ),
)

PCOS = Stack(
    "pcos", PCOS_TEXT,
    mentions=(
        Mention("atomoxetine", "atomoxetine", "intervention"),
        Mention("adhd", "ADHD", "condition"),
        Mention("spironolactone", "spironolactone", "intervention"),
        Mention("hirsutism", "hirsutism", "condition"),
        Mention("metformin", "metformin", "intervention"),
        Mention("hyperinsulinemia", "hyperinsulinemia", "condition"),
        Mention("pcos", "polycystic ovary syndrome", "condition"),
        Mention("minoxidil", "minoxidil", "intervention"),
        Mention("alopecia", "alopecia", "condition"),
    ),
    profile=(ProfileItem("sex", "female"), ProfileItem("diagnosis", "PCOS")),
    stated=(
        ("atomoxetine", "TREATS", "adhd", "Strattera (atomoxetine) 40 mg for ADHD"),
        ("spironolactone", "TREATS", "hirsutism", "Spironolactone 100 mg for hirsutism"),
        ("metformin", "TREATS", "hyperinsulinemia", "was for obesity and hyperinsulinemia"),
        ("minoxidil", "TREATS", "alopecia", "Oral minoxidil 1.5 mg for hair loss"),
    ),
)


def stack_extractor(stack: Stack):
    async def extract(ctx) -> ExtractedCase:
        return ExtractedCase(
            source_text=stack.text,
            mentions=stack.mentions,
            profile=stack.profile,
            stated_predications=tuple(
                DraftPredication(s, p, o, q) for s, p, o, q in stack.stated
            ),
        )
    return extract


async def cite_stated_live(ctx) -> CaseGraph:
    """Same shape as the fixture's `cite_stated`, but `replace` rather than `__dict__` unpacking —
    a frozen dataclass has a supported way to do this, and `**edge.__dict__` breaks the moment a
    field gains a default it should not re-send."""
    cited = []
    for edge in ctx.inputs.edges:
        evidence = await ctx.deps.semmed.evidence_for(edge, ctx.inputs.concepts)
        cited.append(replace(edge, evidence=evidence))
    return CaseGraph(ctx.inputs.concepts, ctx.inputs.profile, tuple(cited))


async def discover_live(ctx) -> CaseGraph:
    candidates, concepts = [], list(ctx.inputs.concepts)
    for concept in ctx.inputs.concepts:
        hood = await ctx.deps.semmed.neighbors(concept)
        concepts.extend(hood.concepts)
        candidates.extend(hood.edges)
    existing = {(e.subject_id, e.predicate, e.object_id) for e in ctx.inputs.edges}
    novel, seen = [], set(existing)
    for edge in candidates:
        key = (edge.subject_id, edge.predicate, edge.object_id)
        if key in seen:
            continue
        seen.add(key)
        novel.append(edge)
    unique = {c.id: c for c in concepts}
    return CaseGraph(tuple(unique.values()), ctx.inputs.profile,
                     ctx.inputs.edges + tuple(novel))


async def story_live(ctx) -> CaseReport:
    """A Health Stack Story: every user-stated edge, then the best gaps, capped at 12.

    User edges are NEVER dropped. The fixture's ranking sorted `origin == "discovered"` first
    under `reverse=True`, so a long stack would push the patient's own plan out of its own story.
    """
    user = [e for e in ctx.inputs.edges if e.origin == "user"]
    gaps = sorted(
        (e for e in ctx.inputs.edges if e.origin != "user"),
        key=lambda e: (any(ev.sentence for ev in e.evidence),
                       e.relevance or 0.0, len(e.evidence)),
        reverse=True,
    )
    return CaseReport(ctx.inputs, tuple(user + gaps[: max(0, 12 - len(user))]))


def strategy_for(stack: Stack, arm: str) -> StrategySpec:
    """One implementation map. All three arms share it — they differ ONLY in `ctx.deps`.

    ⚠️ That is the honest reading of this battle and it is worth stating plainly: swapping a
    service is not a strategy (`HEALTH_STACK_HANDOFF.md`, "Strategy boundary"), so
    `spec.varies()` correctly reports NOTHING varies between these arms. What varies is
    infrastructure, and the workbench is right to say so. The comparison is still worth running —
    it is just an infrastructure comparison, not a design one.
    """
    return StrategySpec(f"{stack.name}:{arm}", {
        extract_case: stack_extractor(stack),
        resolve_concepts: resolve_all,
        build_given_graph: build_stated,
        cite_given_edges: cite_stated_live,
        discover_candidate_gaps: discover_live,
        rank_story: story_live,
    })


ARMS = ("medline_only", "plus_findings", "plus_findings_checked")


def services_for(arm: str, store):
    if arm == "medline_only":
        return MedlineKgSemMed(store)
    return FindingsAugmented(store, check_topic=(arm == "plus_findings_checked"))


# -- the battle -------------------------------------------------------------------------------

def score(report: CaseReport, umls: LiveUMLS, semmed: MedlineKgSemMed) -> dict:
    edges = report.full_graph.edges
    user = [e for e in edges if e.origin == "user"]
    gaps = [e for e in edges if e.origin != "user"]
    quoted = [e for e in edges if any(ev.sentence for ev in e.evidence)]
    return {
        "concepts": len(report.full_graph.concepts),
        "cui_resolved": sum(1 for c in report.full_graph.concepts if c.cui),
        "user_edges": len(user),
        "user_edges_cited": sum(1 for e in user if e.evidence),
        "gap_edges": len(gaps),
        "edges_with_a_quote": len(quoted),
        "distinct_pmids": len({ev.pmid for e in edges for ev in e.evidence}),
        "story_edges": len(report.story_edges),
        "uncitable_no_cui": semmed.uncitable_no_cui,
        "findings_queries": getattr(semmed, "findings_queries", "not asked"),
        "quotes_dropped_off_topic": getattr(semmed, "quotes_dropped_off_topic", "not asked"),
        "unresolved": list(umls.unresolved),
    }


def run_arm(stack: Stack, arm: str, store):
    spec = HealthStackEvidence()
    umls, semmed = LiveUMLS(), services_for(arm, store)
    t0 = time.time()
    report = spec.render(strategy_for(stack, arm)).run_sync(
        inputs=stack.text, deps=Services(umls, semmed))
    return score(report, umls, semmed), report, time.time() - t0


def main() -> None:
    from nobs.query.medline_kg import MedlineKgStore

    store = MedlineKgStore()
    spec = HealthStackEvidence()
    print(f"design check(): {spec.check() or 'clean'}")
    print(f"spec.varies() across arms: {spec.varies(strategy_for(GLP1, ARMS[0]), strategy_for(GLP1, ARMS[1])) or 'nothing -- these are INFRASTRUCTURE arms, not strategies'}\n")

    for stack in (GLP1, PCOS):
        print("=" * 92)
        print(f"{stack.name.upper()}   {stack.text.splitlines()[0][:78]}")
        print("=" * 92)
        rows = {arm: run_arm(stack, arm, store) for arm in ARMS}
        print(f"{'metric':<26}" + "".join(f"{a:>22}" for a in ARMS))
        print("-" * 92)
        for key in [k for k in rows[ARMS[0]][0] if k != "unresolved"]:
            vals = [rows[a][0][key] for a in ARMS]
            print(f"{key:<26}" + "".join(f"{str(v):>22}" for v in vals))
        for arm in ARMS:
            m, _r, secs = rows[arm]
            print(f"{arm:<26} {secs:6.1f}s   unresolved: {m['unresolved'] or 'none'}")

        for arm in ("plus_findings", "plus_findings_checked"):
            _m, report, _s = rows[arm]
            names = {c.id: c.preferred_term for c in report.full_graph.concepts}
            print(f"\n-- sentences under `{arm}` (MEDLINE-KG supplies ZERO, by construction) --")
            shown = 0
            for edge in report.story_edges:
                for ev in edge.evidence:
                    if ev.sentence and shown < 5:
                        print(f"  [{ev.pmid}] {names.get(edge.subject_id, edge.subject_id)} "
                              f"--{edge.predicate}--> {names.get(edge.object_id, edge.object_id)}")
                        print(f'      "{ev.sentence[:140]}"')
                        shown += 1
            if not shown:
                print("  none")

        print("\n-- gaps MEDLINE-KG found (support + PMIDs; no sentence available, ever) --")
        _m2, report2, _s2 = rows["medline_only"]
        names2 = {c.id: c.preferred_term for c in report2.full_graph.concepts}
        for edge in [e for e in report2.story_edges if e.origin != "user"][:6]:
            print(f"  {names2.get(edge.subject_id, edge.subject_id)} --{edge.predicate}--> "
                  f"{names2.get(edge.object_id, edge.object_id)}   "
                  f"support={int(edge.relevance or 0)}  pmids={len(edge.evidence)}  quote=none")
        print()


if __name__ == "__main__":
    main()
