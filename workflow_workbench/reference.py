"""The README's reference tables, DERIVED. SOURCE is the package's own docstrings.

Two tables, one generator:

    the data language     every word you declare a design with
    well-formedness       every rule `coherence_check()` enforces

    python3 -m workflow_workbench.reference            # print both
    python3 -m workflow_workbench.reference --write    # rewrite the README's blocks
    python3 -m workflow_workbench.reference --check    # exit 1 if either is stale

⛔ THIS MODULE INVENTS NO DESCRIPTIONS. Every cell is the first line of the thing's own
docstring, or — for the two unions — the names of their members. So a table cannot claim
something the code does not say. `.claude/rules/spec-as-code.md`: a document is either source or
derived, and mixing them is the whole failure mode.

⚠️ What IS authored here is the GROUPING — which word belongs under "boxes" and which under
"wires". That is a curation decision and it is source, which is why it is a literal below and why
`test_reference.py` asserts every export is either grouped or deliberately excluded. A new type
that silently fails to appear would make the table under-report the language.
"""
from __future__ import annotations

import inspect
import sys
import typing
from dataclasses import dataclass

import workflow_workbench as ww
from workflow_workbench import checks

__all__ = ["Word", "Rule", "vocabulary", "rules", "language_markdown", "rules_markdown"]


# ── the data language ───────────────────────────────────────────────────────────────────────
#
# AUTHORED: the grouping and the order. Nothing else.

GROUPS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("Values", "What flows. Named, so a mis-wiring is visible when the types are identical.",
     ("VariableSpec",)),
    ("Boxes", "Every box the design declares. Only a step takes an implementation.",
     ("StepSpec", "JoinSpec", "DecisionSpec", "NodeSpec")),
    ("Wires", "How values move. The kind of edge is the kind of movement.",
     ("EdgeSpec", "MapEdgeSpec", "TransformEdgeSpec")),
    ("Endpoints", "The graph's own boundary, declared like anything else.",
     ("START", "END")),
    ("The design, and what fills it", "One design, many competing sets of implementations.",
     ("GraphSpec", "StrategySpec", "SubgraphBinding", "Bindable")),
)

#: Exported, and deliberately NOT in the table above, with the reason. A reader of the data
#: language does not need these to write a design — but an unexplained omission is how a table
#: comes to under-report, so each one is named.
NOT_THE_LANGUAGE: dict[str, str] = {
    "SpecError": "raised BY the language, not part of writing one",
    "CoherenceFinding": "what a check returns — the second table's subject",
    "blocking": "a filter over findings",
    "NOT_CHECKED": "the prefix marking a stated gap",
    "diagram": "output, not declaration",
    "diff_diagram": "output, not declaration",
    **{n: "one check — the second table" for n in checks.__all__ if n.startswith("check_")},
}


@dataclass(frozen=True)
class Word:
    """One word of the data language: what you write, and what it is."""

    name: str
    what: str
    is_union: bool


def _describe(name: str) -> tuple[str, bool]:
    """A word's own description, or its members if it is a union.

    ⚠️ A `X | Y` alias has no docstring of its own — `inspect.getdoc` returns `UnionType`'s,
    which is "Represent a PEP 604 union type" and says nothing about this library. Rendering the
    MEMBERS is both truer and incapable of drifting: it is the definition.
    """
    obj = getattr(ww, name)
    members = typing.get_args(obj)
    if members:
        # ⚠️ `\|`, escaped. A bare pipe is a COLUMN SEPARATOR in a markdown table, so the
        # union rendered as three empty columns — visible only in the rendered table,
        # which is why the test below asserts on the rendered row and not on this string.
        return " \\| ".join(f"`{m.__name__}`" for m in members), True
    doc = inspect.getdoc(obj)
    if not doc:
        raise SystemExit(f"{name} has no docstring — the table's only source")
    return doc.split("\n")[0].strip(), False


def vocabulary() -> tuple[tuple[str, str, tuple[Word, ...]], ...]:
    out = []
    for title, blurb, names in GROUPS:
        words = tuple(Word(n, *_describe(n)) for n in names)
        out.append((title, blurb, words))
    return tuple(out)


def language_markdown() -> str:
    out = [
        "A design is **data** — tuples of these, in a class body. Nothing executes, which is "
        "what lets `coherence_check()` and `diagram()` read it before a single step is written.",
        "",
    ]
    for title, blurb, words in vocabulary():
        out += [f"**{title}** — {blurb}", "", "| | |", "|---|---|"]
        out += [f"| `{w.name}` | {w.what} |" for w in words]
        out += [""]
    # ⚠️ Do NOT write the retired constructor form here, even to say it is retired:
    # `test_the_docs_use_the_current_api` greps every prose doc for it and the README is not
    # exempt, deliberately. Describing the behaviour reads better anyway.
    out += ["The two unions are annotations, not classes you instantiate — calling either one "
            "raises `TypeError`. They exist so a signature can say *any declared box*, or "
            "*anything a strategy must bind*, and have it type-check."]
    return "\n".join(out)


# ── the well-formedness rules ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Rule:
    """One well-formedness rule: the check that enforces it, and what it says about itself.

    `needs_strategy` is derived from the SIGNATURE, not a hand-kept list — a check requiring a
    `strategy` cannot run on a design with nothing implemented, and that is the most useful thing
    to know before reading the rest of the row.
    """

    check: str
    rule: str
    needs_strategy: bool


def _needs_strategy(fn) -> bool:
    """A REQUIRED `strategy`. `| None` means it tolerates having none, so it still runs on a bare
    design — `check_transform_edges` is exactly that case and must not be grouped with the four
    that genuinely cannot."""
    p = inspect.signature(fn).parameters.get("strategy")
    return p is not None and "None" not in str(p.annotation)


def rules() -> tuple[Rule, ...]:
    out = []
    for name in checks.__all__:
        if not name.startswith("check_"):
            continue
        fn = getattr(checks, name)
        doc = inspect.getdoc(fn)
        if not doc:
            raise SystemExit(f"{name} has no docstring — the table's only source")
        out.append(Rule(name, doc.split("\n")[0].strip(), _needs_strategy(fn)))
    return tuple(out)


def rules_markdown() -> str:
    rs = rules()
    design = [r for r in rs if not r.needs_strategy]
    strategy = [r for r in rs if r.needs_strategy]
    out = [
        f"**{len(rs)} rules.** `coherence_check()` returns one finding per violation and an empty "
        f"list for a clean design; `render()` refuses on any finding that blocks.",
        "",
        f"**{len(design)} need no implementations at all** — runnable the moment `nodes` and "
        f"`edges` are written.",
        "",
        "| check | rule |",
        "|---|---|",
    ]
    out += [f"| `{r.check}` | {r.rule} |" for r in design]
    out += ["",
            f"**{len(strategy)} more once a strategy exists**, checking the implementations "
            f"against the roles they fill.",
            "",
            "| check | rule |",
            "|---|---|"]
    out += [f"| `{r.check}` | {r.rule} |" for r in strategy]
    return "\n".join(out)


# ── generation ──────────────────────────────────────────────────────────────────────────────

BLOCKS = (("language", language_markdown), ("rules", rules_markdown))


def _readme():
    import pathlib
    return pathlib.Path(__file__).resolve().parent.parent / "README.md"


def main() -> int:
    if "--check" not in sys.argv and "--write" not in sys.argv:
        for _, fn in BLOCKS:
            print(fn(), "\n")
        return 0
    target = _readme()
    text = target.read_text()
    rc = 0
    for tag, fn in BLOCKS:
        start, end = f"<!-- {tag}:start -->", f"<!-- {tag}:end -->"
        if start not in text or end not in text:
            print(f"README.md: {tag} markers missing")
            rc = 1
            continue
        head, rest = text.split(start, 1)
        stale, tail = rest.split(end, 1)
        body = fn()
        if "--write" in sys.argv:
            text = f"{head}{start}\n{body.strip()}\n{end}{tail}"
        elif stale.strip() != body.strip():
            print(f"README.md: the {tag} table is stale. Regenerate:\n"
                  f"  python3 -m workflow_workbench.reference --write")
            rc = 1
        else:
            print(f"README.md: {tag} table matches reference.py")
    if "--write" in sys.argv:
        target.write_text(text)
        print("README.md: both tables rewritten from reference.py")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
