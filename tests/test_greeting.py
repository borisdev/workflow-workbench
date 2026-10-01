"""The README's walkthrough, asserted — every number and the diagram it prints.

⛔ WHY THIS FILE EXISTS. The README shows a rendered comparison diagram and a table of outputs and
scores. Both are claims about what the code does, and a reader who pastes the commands will find
out. `.claude/rules/checks.md`: name the failure first — *the README's diagram or scores drift
from the example* — then write the check that goes red on it. These do.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from examples.greeting import (
    CASES,
    Greeting,
    compose,
    compose_greeting,
    normalize,
    normalize_spaces,
    trim_and_collapse,
    trim_only,
)
from workflow_workbench import SpecError, StrategySpec

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text()


def test_the_specification_checks_clean_with_nothing_implemented() -> None:
    """Stage 2 of the walkthrough, and the thing a built `Graph` cannot reach."""
    assert Greeting().coherence_check() == []


def test_both_strategies_satisfy_the_specification() -> None:
    """The README says every check passes for BOTH — which is what makes the point that
    structural consistency does not imply correct behaviour."""
    spec = Greeting()
    for strategy in (trim_only, normalize_spaces):
        assert spec.coherence_check(strategy) == [], strategy.name


def test_both_arms_have_the_same_node_ids_so_the_comparison_aligns() -> None:
    spec = Greeting()
    a, b = spec.render(trim_only), spec.render(normalize_spaces)
    assert sorted(a.nodes) == sorted(b.nodes)


def test_only_normalize_varies_and_compose_is_shared() -> None:
    """The diagram's whole message, as data."""
    varies = Greeting().varies(trim_only, normalize_spaces)
    assert varies == {"normalize": ("trim", "trim_and_collapse")}
    assert trim_only[compose] is normalize_spaces[compose] is compose_greeting


@pytest.mark.parametrize("case,text,expected", CASES)
def test_normalize_spaces_delivers_the_declared_behaviour(case: str, text: str,
                                                          expected: str) -> None:
    """"preserve the words, trim, collapse internal runs, return Hello, {name}!" — all four."""
    assert Greeting().render(normalize_spaces).run_sync(inputs=text) == expected


def test_trim_only_gets_exactly_the_two_cases_with_internal_runs_wrong() -> None:
    """The README's ✗ marks. If this count moves, that table is wrong."""
    graph = Greeting().render(trim_only)
    wrong = [c for c, text, expected in CASES if graph.run_sync(inputs=text) != expected]
    assert wrong == ["inner_run", "both"]


def test_an_incomplete_strategy_is_reported_and_then_refused() -> None:
    """Stage 4. The check NAMES the unbound node, and `render()` will not build around it."""
    spec = Greeting()
    unfinished = StrategySpec("unfinished", {normalize: trim_and_collapse})

    findings = spec.coherence_check(unfinished)
    assert len(findings) == 1 and "'compose'" in findings[0]

    with pytest.raises(SpecError) as exc:
        spec.render(unfinished)
    assert "'compose'" in str(exc.value)


def test_the_battle_scores_are_what_the_readme_prints() -> None:
    """0.50 / 1.00 against a 0.00 floor — the three numbers in the README's table."""
    from examples.greeting import dataset
    from workflow_workbench.evals import eval_battle

    spec, data = Greeting(), dataset()

    floor = eval_battle(spec, trim_only, trim_only, data)
    assert floor.is_replicate
    assert floor.per_case_spread() == {"ExactMatch": 0.0}

    battle = eval_battle(spec, trim_only, normalize_spaces, data)
    assert _score(battle.report_a) == pytest.approx(0.50)
    assert _score(battle.report_b) == pytest.approx(1.00)
    assert battle.deltas()["ExactMatch"] == pytest.approx(0.50)

    assert "**0.50**" in README and "**1.00**" in README


def _score(report) -> float:
    v = next(iter(report.averages().scores.values()))
    return float(getattr(v, "value", v))


def test_the_readme_mermaid_block_is_the_diagram_the_code_emits() -> None:
    """⛔ THE ONE THAT MATTERS MOST. A hand-pasted diagram is a claim about the declaration that
    stops being true the moment a node is renamed, and nothing else would notice.

    The `%%` title line is dropped because a fenced mermaid block on GitHub does not need it.
    """
    drawn = Greeting().diff_diagram(trim_only, normalize_spaces)
    body = "\n".join(ln for ln in drawn.splitlines() if not ln.startswith("%%")).strip()
    assert f"```mermaid\n{body}\n```" in README, (
        "the README's mermaid block is not what diff_diagram() emits. Regenerate it:\n"
        "  uv run python3 -m examples.greeting")


@pytest.mark.parametrize("case,text,expected", CASES)
def test_the_readme_table_shows_the_real_inputs_and_outputs(case: str, text: str,
                                                            expected: str) -> None:
    """Every row of the outputs table, against the running code."""
    spec = Greeting()
    assert f"`{case}`" in README
    assert f'`"{text}"`' in README
    for strategy in (trim_only, normalize_spaces):
        got = spec.render(strategy).run_sync(inputs=text)
        assert f"`{got}`" in README, f"{strategy.name} on {case} produced {got!r}"


def test_the_readme_quickstart_commands_are_the_ones_that_work() -> None:
    """A quickstart nobody runs is the confidently-wrong doc. These four lines were executed from
    a fresh clone; this asserts the README still names them."""
    for cmd in ("uv sync --no-dev --extra evals",
                "uv run python3 -m examples.greeting"):
        assert cmd in README, cmd


def test_the_readme_excerpt_is_lines_the_example_actually_prints() -> None:
    """⛔ The quickstart shows an output excerpt. If it is not what the program prints, a reader
    runs the command, sees something else, and stops trusting the page.

    So the excerpt is checked line by line against a real run — `...` elisions skipped, every
    other line required verbatim.
    """
    import subprocess
    import sys

    proc = subprocess.run([sys.executable, "-m", "examples.greeting"],
                          cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    printed = (proc.stdout + proc.stderr).splitlines()

    marker = "Everything it produces goes to the terminal; no files are written. Excerpt:"
    assert marker in README, "the quickstart lost its output excerpt"
    excerpt = README.split(marker, 1)[1].split("```", 2)[1].splitlines()

    wanted = [ln for ln in excerpt if ln.strip() and ln.strip() != "..."]
    assert len(wanted) >= 5, "the excerpt shrank to nothing worth checking"
    missing = [ln for ln in wanted if ln not in printed]
    assert not missing, f"README excerpt lines the example does not print: {missing}"
