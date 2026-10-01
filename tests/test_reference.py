"""The README's two tables are DERIVED, and this is what stops them drifting.

Same shape as `test_parity.py`, for the same reason: `.claude/rules/spec-as-code.md` — an
unchecked convention drifts back within a month, so the check IS the rule.

⚠️ Three halves, and only together do they mean anything:
  · the generated blocks match the generator
  · the generator sees EVERY export — a table perfectly in sync with a generator that reads nine
    of eleven checks is perfectly in sync and wrong
  · every cell is the thing's own words, so a table cannot say what the code does not
"""
from __future__ import annotations

import inspect
import subprocess
import sys
from pathlib import Path

import workflow_workbench as ww
import workflow_workbench.checks as checks
from workflow_workbench.reference import (
    GROUPS,
    NOT_THE_LANGUAGE,
    language_markdown,
    rules,
    rules_markdown,
    vocabulary,
)

ROOT = Path(__file__).resolve().parent.parent


def test_both_readme_blocks_are_regenerated_from_reference_py() -> None:
    """Edit a docstring, regenerate, commit both. Editing the README alone turns this red."""
    proc = subprocess.run([sys.executable, "-m", "workflow_workbench.reference", "--check"],
                          cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_every_export_is_either_in_the_language_or_explicitly_excluded() -> None:
    """⛔ THE COMPLETENESS GUARD, and the one that matters most.

    A new type added to `__all__` and forgotten is the silent failure here: the table stays in
    sync with the generator and quietly under-reports the language. Excluding something is fine —
    saying nothing about it is not, which is why `NOT_THE_LANGUAGE` carries a reason per name.
    """
    grouped = {w.name for _, _, words in vocabulary() for w in words}
    assert grouped, "the vocabulary is empty — every assertion here would pass vacuously"
    unaccounted = set(ww.__all__) - grouped - set(NOT_THE_LANGUAGE)
    assert not unaccounted, (
        f"exported but neither in the table nor explained: {sorted(unaccounted)}. Add it to "
        f"GROUPS, or to NOT_THE_LANGUAGE with the reason a reader does not need it.")
    assert not (grouped & set(NOT_THE_LANGUAGE)), "a word cannot be both shown and excluded"


def test_the_exclusions_all_still_exist() -> None:
    """A stale exclusion is worse than none: it names something nobody will notice is gone, and
    the guard above goes quiet on whatever takes that name next. Copied from
    `test_parity.py`'s exemption check, which exists for exactly this."""
    missing = [n for n in NOT_THE_LANGUAGE if n not in ww.__all__]
    assert not missing, f"excluded from the table but no longer exported: {missing}"


def test_every_check_in_the_module_reaches_the_rules_table() -> None:
    public = {n for n in dir(checks)
              if n.startswith("check_") and callable(getattr(checks, n))}
    assert public, "found no checks at all"
    assert public == {r.check for r in rules()}, (
        "a check_* function is missing from checks.__all__, so the table cannot see it")


def test_no_cell_is_invented_prose() -> None:
    """⛔ The rule that makes both tables trustworthy. If a cell could be hand-written, the table
    could say something the code does not do — the whole failure a derived document removes."""
    for r in rules():
        first = inspect.getdoc(getattr(checks, r.check)).split("\n")[0].strip()
        assert r.rule == first, f"{r.check}: table text is not its docstring's first line"
        assert r.rule in rules_markdown(), f"{r.check}: its rule never reaches the table"

    for _, _, words in vocabulary():
        for w in words:
            if w.is_union:
                continue
            first = inspect.getdoc(getattr(ww, w.name)).split("\n")[0].strip()
            assert w.what == first, f"{w.name}: table text is not its docstring's first line"


def test_every_first_docstring_line_stands_alone() -> None:
    """⚠️ The invariant the table rests on, and it is not free — `_Start`'s first line used to
    end mid-sentence on 'so `mypy` can narrow a', which the table would have printed verbatim.
    A docstring whose first line wraps is a source bug once anything lifts it."""
    for _, _, words in vocabulary():
        for w in words:
            if w.is_union:
                continue
            assert w.what.endswith((".", "!")), (
                f"{w.name}: first docstring line does not end a sentence — it wraps, and the "
                f"table would print the fragment. Put the summary on one line.")


def test_a_union_renders_its_members_and_not_pythons_docstring() -> None:
    """`inspect.getdoc` on a `X | Y` alias returns 'Represent a PEP 604 union type', which says
    nothing about this library. And the members must be PIPE-ESCAPED or markdown reads them as
    column separators — a bug invisible in the source string and visible only in the table."""
    rendered = {w.name: w.what for _, _, words in vocabulary() for w in words if w.is_union}
    assert set(rendered) == {"NodeSpec", "Bindable"}, "the two unions must both be shown"
    assert "PEP 604" not in language_markdown()
    for name, cell in rendered.items():
        assert r"\|" in cell, f"{name}: unescaped pipe would break the markdown table"
        assert f"| `{name}` | {cell} |" in language_markdown()


def test_the_rules_table_counts_come_from_the_checks() -> None:
    rs = rules()
    md = rules_markdown()
    assert f"**{len(rs)} rules.**" in md
    assert f"**{sum(1 for r in rs if not r.needs_strategy)} need no implementations" in md


def test_needs_strategy_is_derived_and_matches_what_actually_runs() -> None:
    """⚠️ `check_transform_edges` takes `strategy` and tolerates `None`, so it belongs with the
    design-only group. Getting that wrong would tell a reader a design cannot be checked until it
    is implemented — the opposite of the pitch."""
    design_only = {r.check for r in rules() if not r.needs_strategy}
    assert "check_transform_edges" in design_only
    assert {"check_bindings", "check_implementations", "check_variable_types",
            "check_subgraphs"} == {r.check for r in rules() if r.needs_strategy}


def test_the_authored_part_is_only_the_grouping() -> None:
    """GROUPS carries names and headings. If it ever carried a DESCRIPTION, the table would be
    half source and half derived — which is the state this whole module exists to avoid."""
    for title, blurb, names in GROUPS:
        assert isinstance(title, str) and isinstance(blurb, str)
        assert all(isinstance(n, str) for n in names), (
            "GROUPS must hold names only — a description here would not be derived")
