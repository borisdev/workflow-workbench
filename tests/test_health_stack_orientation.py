"""The un-swap, pinned.

`nobs.query.medline_kg.outgoing_causal` returns rows in SWAPPED orientation: the effect lands in
`subject_cui` and the seed in `object_cui`, so both traversal directions aggregate uniformly. Its
docstring says so in bold.

Reading `row.object_cui` at face value therefore compares the seed against itself and matches
nothing. Measured against the live 6.9 GB store on 2026-08-31, that produced
`user_edges_cited: 0` on both health stacks — against a store holding `semaglutide TREATS obesity`
96 times and `spironolactone TREATS hirsutism` 103 times.

⛔ The reason this test exists rather than a comment: **a zero is what a correct empty answer looks
like too.** Nothing distinguished "the literature has nothing" from "we asked the wrong question",
and the run went green and printed a table. `.claude/rules/checks.md` — name the failure, then
write the check that goes red when it happens.

No substrate needed: `far_end` is a pure function of a row's fields, so this runs in the workbench
suite in microseconds and would have caught the bug.
"""
from dataclasses import dataclass

from examples.local.health_stack_live import far_end


@dataclass(frozen=True)
class Row:
    """The fields of `nobs.query.medline_kg.CausalEdge` that `far_end` reads."""

    subject_cui: str
    subject_name: str
    object_cui: str
    object_name: str
    orientation: str = "as_asserted"


SEMAGLUTIDE, OBESITY = "C3885068", "C0028754"


def test_swapped_row_reports_the_effect_not_the_seed() -> None:
    """`outgoing_causal(semaglutide)` puts obesity in `subject_cui`. The far end is obesity."""
    row = Row(subject_cui=OBESITY, subject_name="Obesity",
              object_cui=SEMAGLUTIDE, object_name="semaglutide",
              orientation="swapped")
    assert far_end(row) == (OBESITY, "Obesity")
    # ⛔ the defect, stated as an assertion: the naive read returns the seed we asked about.
    assert row.object_cui == SEMAGLUTIDE


def test_as_asserted_row_is_left_alone() -> None:
    """`incoming_causal` is already oriented. Un-swapping it would introduce the same bug."""
    row = Row(subject_cui=SEMAGLUTIDE, subject_name="semaglutide",
              object_cui=OBESITY, object_name="Obesity")
    assert far_end(row) == (OBESITY, "Obesity")


def test_a_row_with_no_orientation_field_at_all_is_treated_as_asserted() -> None:
    """Defaulting matters: `getattr(row, 'orientation', ...)` must not un-swap an unlabelled row,
    or every hand-built or third-party row silently reverses."""

    class Bare:
        subject_cui, subject_name = SEMAGLUTIDE, "semaglutide"
        object_cui, object_name = OBESITY, "Obesity"

    assert far_end(Bare()) == (OBESITY, "Obesity")


def test_both_orientations_agree_on_which_end_is_the_far_one() -> None:
    """The property that makes the two traversals composable: whichever direction produced a row,
    `far_end` names the concept that is NOT the seed."""
    asserted = Row(SEMAGLUTIDE, "semaglutide", OBESITY, "Obesity")
    swapped = Row(OBESITY, "Obesity", SEMAGLUTIDE, "semaglutide", orientation="swapped")
    assert far_end(asserted) == far_end(swapped)
