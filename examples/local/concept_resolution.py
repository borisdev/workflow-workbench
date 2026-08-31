"""UMLS resolution as TWO nodes, because recall and selection fail differently.

    generate_cui_candidates   UMLS retrieves. Never decides.
    select_cuis               something picks among what UMLS returned. Never invents a CUI.

The deployed resolver (`apps/concept-resolver`, one `POST /resolve`) fuses both into one answer, so
its two failure modes are indistinguishable from outside: a miss can mean "the right concept was
never retrieved" or "it was retrieved and the wrong one won", and the payload looks identical.
Splitting them is the whole point — `recall@k` and `selection accuracy` become separate numbers.

⛔ MEASURED, not assumed. Against the live service on 2026-08-31:

    metformin 1000 mg -> C1329120 "Rosiglitazone 2 mg and metformin 1000 mg oral tablet"  conf 0.95
    PCOS              -> C0764201 "PCOS-PTPC"                                             conf 0.95
    oral semaglutide  -> no match                                                         conf 0.10

The first two carry `resolution_path: "exact"` and 0.95 confidence and have **zero** predications
behind them in MEDLINE-KG, while the concepts they should have found have 15,951 and 29,411. So the
service's confidence says nothing about whether the CUI can be cited, and a one-shot resolver has no
place to put that signal even if it had it. The selector does.

Run:
    PYTHONPATH=/tmp/wt-health-stack uv run python3 -m examples.local.concept_resolution
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

UMLS_DB = "data/umls/umls_concepts.db"
KG_DB = "data/semmeddb/medline_kg.db"

# The handoff's routing table: which vocabulary answers for which kind.
# ⚠️ This local slice holds SNOMEDCT_US (1,707,735) and MSH (1,032,970) and NOTHING ELSE.
# RXNORM is listed because the handoff specifies it and a reader must not conclude from its
# presence here that it is available — it is not, and drug-form questions suffer accordingly.
PREFERRED_SOURCES = {
    "intervention": ("RXNORM", "SNOMEDCT_US", "MSH"),
    "condition": ("SNOMEDCT_US", "MSH", "ICD10CM"),
    "outcome": ("SNOMEDCT_US", "MSH"),
    "assessment": ("LNC", "SNOMEDCT_US"),
}

# Dose, route and schedule are ATTRIBUTES of an intervention, not part of its identity.
# `Strattera 40 mg` resolves `Strattera`; the 40 mg belongs on the edge, not in the lookup.
_ATTRIBUTES = re.compile(
    r"\b\d+([.,]\d+)?\s*(mg|mcg|g|ml|iu|units?|%)\b"
    r"|\b(oral|iv|im|topical|daily|once|twice|weekly|nightly|bid|tid|qd|prn"
    r"|extended[- ]release|er|xr|sr|tablet|capsule|softgel)\b",
    re.I,
)


def head_term(text: str) -> str:
    """The identity, with attributes stripped. Falls back to the original rather than to ''."""
    return re.sub(r"\s+", " ", _ATTRIBUTES.sub(" ", text)).strip(" ,-") or text


@dataclass(frozen=True)
class ConceptCandidate:
    """One thing UMLS offered. `match` records HOW it was found, and that is a ranking tier."""

    cui: str
    name: str
    source: str
    match: str  # "exact" | "fts"
    support: int = 0  # predications in MEDLINE-KG; filled by the selector, not the retriever


@dataclass(frozen=True)
class Resolution:
    """The selector's answer. `cui=None` is a legal, first-class outcome."""

    cui: str | None
    name: str
    confidence: float
    why: str
    considered: int


class UmlsCandidates:
    """Retrieval only. Two tiers, and the tier is the point.

    ⛔ `is_preferred` is NOT a ranking signal across CUIs, and using it as one is the bug this
    class exists to not have. It means *"this string is the preferred name OF THIS CUI"*, so
    `Metformin pamoate` and `Allergy to metformin` both carry it while `C0025598 Metformin` — whose
    own rows are PT/OP/MH with `is_preferred=0` — does not. Ranking a mixed pool by it put the
    correct concept **11th of 61**, below `Poisoning by metformin`. Measured 2026-08-31.

    An exact name match is therefore its own tier and outranks every fuzzy hit, which is also what
    the handoff specifies: `exact`, then `normalizedString`, then `words`.
    """

    def __init__(self, db_path: str = UMLS_DB):
        self.conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        self.conn.row_factory = sqlite3.Row

    def candidates(self, mention: str, kind: str, limit: int = 10) -> tuple[ConceptCandidate, ...]:
        term = head_term(mention)
        prefs = PREFERRED_SOURCES.get(kind, ())
        pool: dict[str, ConceptCandidate] = {}

        for row in self.conn.execute(
            "SELECT cui,name,source FROM concepts WHERE lower(name)=lower(?)", (term,)
        ):
            pool.setdefault(row["cui"],
                            ConceptCandidate(row["cui"], row["name"], row["source"], "exact"))

        quoted = '"' + term.replace('"', " ") + '"'
        try:
            fts = self.conn.execute(
                "SELECT c.cui,c.name,c.source FROM concepts_fts f JOIN concepts c "
                "ON c.rowid=f.rowid WHERE concepts_fts MATCH ? LIMIT 400", (quoted,)
            ).fetchall()
        except sqlite3.OperationalError:
            fts = []
        for row in fts:
            pool.setdefault(row["cui"],
                            ConceptCandidate(row["cui"], row["name"], row["source"], "fts"))

        ordered = sorted(
            pool.values(),
            key=lambda c: (0 if c.match == "exact" else 1,
                           prefs.index(c.source) if c.source in prefs else 9,
                           len(c.name)),
        )
        return tuple(ordered[:limit])


class RichnessSelector:
    """Picks the candidate the LITERATURE treats as the clinical sense.

    `richness` is already in the store for exactly this reason (#289): "depression" is C0011570
    (~1.8K edges) or C0011581 (~69K), and picking blind lands on the thin one. Here it does a
    second job — a CUI with zero predications cannot be cited by ANY downstream step, so a
    confident answer that names one is worse than `NONE`.

    ⚠️ Deterministic and offline. That is deliberate for the first arm: it makes the candidate
    list the only variable, so `recall@k` is measured against a selector that cannot rescue a bad
    list or squander a good one. An LLM selector is the arm to compare against, not to start with.
    """

    def __init__(self, db_path: str = KG_DB, min_support: int = 1):
        self.conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        self.min_support = min_support

    def support(self, cui: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) FROM predications WHERE subject_cui=? OR object_cui=?", (cui, cui)
        ).fetchone()
        return row[0] if row else 0

    def select(self, mention: str, context: str,
               candidates: tuple[ConceptCandidate, ...]) -> Resolution:
        if not candidates:
            return Resolution(None, mention, 0.0, "no candidate retrieved", 0)
        scored = sorted(
            ((c, self.support(c.cui)) for c in candidates),
            key=lambda pair: (0 if pair[0].match == "exact" else 1, -pair[1]),
        )
        best, support = scored[0]
        if support < self.min_support:
            # ⚠️ NONE, not the best of a bad list. `.claude/rules/checks.md`: "NOT CHECKED" and
            # "0 found" must never render the same, and neither may "we guessed".
            return Resolution(None, mention, 0.0,
                              f"best candidate {best.cui} has {support} predications", len(candidates))
        return Resolution(best.cui, best.name,
                          0.9 if best.match == "exact" else 0.6,
                          f"{best.match} match, {support} predications", len(candidates))


# -- the measurement ---------------------------------------------------------------------------

# (mention, kind, wanted CUI, what the LIVE service answered)
#
# ⛔ EVERY `live` cell below was obtained by calling the deployed service, and the first draft of
# this table did not have that property. Three rows — `polycystic ovary syndrome`, `hirsutism`,
# `spironolactone` — were filled with `None`, meaning "the service missed", on the strength of not
# having asked. All three in fact resolve **correctly, at 0.95, via `exact`**, so the baseline read
# 9/15 when it was 12/15 and the comparison was inflated by three.
#
# A blank that renders as a failure is `.claude/rules/checks.md` exactly: NOT ASKED and 0 FOUND
# must never render the same. It is worth noting the direction — the error flattered the new work,
# which is the direction one is least likely to check.
LIVE_MEASURED = "2026-08-31, POST /resolve against nobsumls"
CASES = [
    ("metformin 1000 mg", "intervention", "C0025598", "C1329120"),
    ("metformin", "intervention", "C0025598", "C0025598"),
    ("PCOS", "condition", "C0032460", "C0764201"),
    ("polycystic ovary syndrome", "condition", "C0032460", "C0032460"),
    ("oral semaglutide", "intervention", "C3885068", None),
    ("semaglutide", "intervention", "C3885068", "C3885068"),
    ("Strattera 40 mg", "intervention", "C1176420", "C1176420"),
    ("daily amphetamine", "intervention", "C0002658", "C0002658"),
    ("amphetamine", "intervention", "C0002658", "C0002658"),
    ("obesity", "condition", "C0028754", "C0028754"),
    ("ADHD", "condition", "C1263846", "C1263846"),
    ("atomoxetine", "intervention", "C0076823", "C0076823"),
    ("hirsutism", "condition", "C0019572", "C0019572"),
    ("spironolactone", "intervention", "C0037982", "C0037982"),
    ("nausea", "outcome", "C0027497", "C0027497"),
]


def main() -> None:
    retriever, selector = UmlsCandidates(), RichnessSelector()

    print(f"{'mention':<27}{'k':<4}{'rec@k':<7}{'split picks':<12}{'ok':<5}"
          f"{'live service':<14}{'ok'}")
    print("-" * 84)
    recall = split_ok = live_ok = graded = 0
    for mention, kind, want, live in CASES:
        cands = retriever.candidates(mention, kind)
        got = selector.select(mention, "", cands)
        in_k = any(c.cui == want for c in cands)
        graded += 1
        recall += in_k
        split_ok += got.cui == want
        live_ok += live == want
        print(f"{mention:<27}{len(cands):<4}{('YES' if in_k else 'no'):<7}"
              f"{(got.cui or 'NONE'):<12}{('OK' if got.cui == want else 'X'):<5}"
              f"{(live or 'NONE'):<14}{'OK' if live == want else 'X'}")

    print("-" * 84)
    print(f"candidate recall@10        {recall}/{graded} = {recall/graded:.0%}")
    print(f"selection accuracy         {split_ok}/{graded} = {split_ok/graded:.0%}   (split)")
    print(f"                           {live_ok}/{graded} = {live_ok/graded:.0%}   "
          f"(deployed one-shot resolver; {LIVE_MEASURED})")
    print(f"\nselection accuracy GIVEN the concept was retrieved: {split_ok}/{recall}"
          f" = {split_ok/recall:.0%}" if recall else "")
    print("\nThe two numbers are the point. A one-shot resolver reports ONE score and cannot say "
          "whether\na miss was retrieval or selection; these can, and they fail in different "
          "places.")


if __name__ == "__main__":
    main()
