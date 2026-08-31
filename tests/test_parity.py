"""The parity appendix is DERIVED, and this is what stops it drifting.

⛔ Its ancestor was a hand-written table that missed five features while reading as a complete
inventory of the gaps. `.claude/rules/spec-as-code.md`: a document is either source or derived,
and the check is the rule — an unchecked convention drifts back within a month.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from workflow_workbench.parity import FEATURES, as_markdown

ROOT = Path(__file__).resolve().parent.parent


def test_the_readme_appendix_is_regenerated_from_parity_py() -> None:
    """Edit `parity.py`, regenerate, commit both. Editing the README alone turns this red."""
    proc = subprocess.run([sys.executable, "-m", "workflow_workbench.parity", "--check"],
                          cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_every_public_graphbuilder_method_is_covered_by_a_feature() -> None:
    """The completeness half. `parity.py` may not quietly omit part of their API.

    ⚠️ Compared against the LIVE class, not a remembered list — the whole reason the previous
    table was wrong is that nobody re-read the API after writing about it.
    """
    from pydantic_graph import GraphBuilder

    public = {n for n in dir(GraphBuilder) if not n.startswith("_")}
    covered: set[str] = set()
    for f in FEATURES:
        for part in f.api.replace("(*sources)", "").replace("(a, b)", "").split("/"):
            covered.add(part.strip().split("(")[0].strip())

    missing = sorted(public - covered)
    assert not missing, (
        f"parity.py does not mention these GraphBuilder methods: {missing}. "
        f"Add a Feature for each — including the ones we deliberately refuse, since 'refused' "
        f"and 'forgotten' must not read the same.")


def test_every_feature_shows_both_sides() -> None:
    """A row with no `theirs` is an assertion; with both, a reader can judge it themselves."""
    for f in FEATURES:
        assert f.theirs.strip(), f.api
        assert f.ours.strip(), f.api
        assert f.status in {"yes", "partial", "refused", "cannot", "plumbing"}, f.api


def test_the_status_vocabulary_keeps_refusal_and_impossibility_apart() -> None:
    """⚠️ Collapsing these into 'no' is how a deliberate design decision comes to read as a gap,
    and how the next person 'fixes' it.

    ⛔ `refused` currently has NO members, and that is the right kind of empty. `transform` was the
    only one, and it graduated to `yes` once `TransformEdgeSpec` showed the refusal had been
    argued on a bad premise — that a strategy-bound callable must be a node. The vocabulary stays
    because the distinction is still real; a refusal that returns will have somewhere honest to
    live rather than being filed as a gap.
    """
    allowed = {"yes", "partial", "refused", "cannot", "plumbing"}
    assert {f.status for f in FEATURES} <= allowed

    by_status = {f.status for f in FEATURES}
    assert "cannot" in by_status, "BaseNode is a different authoring model, not a TODO"

    # a `partial` must say which half is refused, or "partial" is just a shrug
    for f in FEATURES:
        if f.status == "partial":
            assert f.note, f.api


def test_the_appendix_names_the_workaround_for_everything_not_covered() -> None:
    """A gap with no route through it is a dead end. Every non-`yes` row must show what to do."""
    body = as_markdown()
    for f in FEATURES:
        if f.status in {"yes", "plumbing"}:
            continue
        assert f.note, f"{f.api} is not fully covered and says nothing about what to do instead"
        assert f.api.split("(")[0].split("/")[0].strip() in body


def test_the_source_warns_where_an_agent_would_trip() -> None:
    """⛔ The README appendix is for users. THIS is for whoever edits the code next.

    Every refusal looks like an obvious omission at the declaration site — `EdgeSpec` has no
    `transform=`, `NodeSpec` cannot hold a `BaseNode`, `GraphSpec` has no wiring hook — and each
    one is a decision that took measurement to reach. A warning that lives only in the README is
    a warning nobody reading `spec.py` will see.
    """
    spec_src = (ROOT / "workflow_workbench" / "spec.py").read_text()
    graph_src = (ROOT / "workflow_workbench" / "graph_spec.py").read_text()

    assert "FOR A FUTURE AGENT" in spec_src, "spec.py lost its warnings"
    assert spec_src.count("FOR A FUTURE AGENT") >= 2, "NodeSpec and EdgeSpec each need one"
    assert "BaseNode" in spec_src, "NodeSpec must say why a BaseNode is not one"
    assert "transform=" in spec_src and "matches=" in spec_src, (
        "EdgeSpec must name the two fields people try to add")
    assert "FOR A FUTURE AGENT" in graph_src, "graph_spec.py lost its warning"
    assert "build_pydantic_structure" in graph_src, (
        "the deleted hook must stay named, or someone re-adds it having never heard of it")


def test_the_probe_reads_parity_rather_than_keeping_its_own_copy() -> None:
    """Two descriptions of one thing is the drift this whole file exists to prevent — and the
    probe had its own table until parity.py absorbed it."""
    probe = (ROOT / "docs" / "probe_builder_features.py").read_text()
    assert "from workflow_workbench.parity import FEATURES" in probe
    assert "MATRIX: dict" not in probe, "the probe grew a second table again"


def test_the_readme_uses_the_current_api() -> None:
    """⛔ The README's own code stopped running and nothing said so.

    `EdgeSpec(START, increment)` sat in the opening example after `carries` became required and
    the edge specs became keyword-only — so the first thing a reader copies was a `TypeError`,
    twice over. The generated appendix beside it was correct the whole time, which is the tell:
    derived text survived, hand-written text rotted.

    This is the cheap lint that would have caught it. Not a substitute for the snippets being
    lifted from tested files — which is now how the opening example and rung 1 are written — but
    it goes red on the next rename without anyone remembering to look.
    """
    readme = (ROOT / "README.md").read_text()
    body = readme.split("⛔ This used to be a second table")[0]      # skip the note ABOUT staleness

    retired = {
        "map_over=": "renamed — a fan-out is MapEdgeSpec(carries=…, delivers=…)",
        "produces=": "renamed to `delivers`",
        "build_pydantic_structure": "deleted; there is no wiring hook",
        "check_built_topology": "deleted with the hook it policed",
    }
    for token, why in retired.items():
        assert token not in body, f"README still shows `{token}` — {why}"


def test_the_readme_never_calls_an_edge_positionally() -> None:
    """Edge fields are keyword-only. A positional example is a `TypeError` a reader would copy."""
    import re

    readme = (ROOT / "README.md").read_text()
    # `EdgeSpec(` (or a subclass) whose first argument is not a keyword
    bad = re.findall(r"\b(?:Map|Transform)?EdgeSpec\(\s*(?!source=|\s*$)[A-Za-z_]", readme)
    assert not bad, f"{len(bad)} positional edge call(s) in the README; every field is keyword-only"
