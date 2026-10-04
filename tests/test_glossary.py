"""Every glossary link resolves, and every anchor it points at exists.

⛔ A GLOSSARY WITH DEAD LINKS IS WORSE THAN NO GLOSSARY. A reader clicks a term they do not know,
lands nowhere, and learns not to click the next one — so the whole mechanism dies quietly rather
than loudly. Nothing else in this repo would notice: a markdown link is not code.

Same reasoning as `test_parity.py`'s exemption check, which exists because a stale exemption
names a file nobody will notice is gone.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GLOSSARY = ROOT / "docs" / "glossary.md"

#: `[text](... glossary.md#anchor)`, from anywhere, at any relative depth.
#
# ⛔ The fragment is `[^)]*`, NOT `[a-z0-9-]+`. A character class matching only well-formed
# slugs makes every MALFORMED link invisible — `#noise_floor`, `#Noise-Floor` and a bare
# `glossary.md#` were all skipped rather than reported, and those are the shapes a human
# actually types. A dead-link test blind to the dead links is `.claude/rules/checks.md` in one
# regex: it passed because it did not touch what breaks.
LINK = re.compile(r"\[([^\]]+)\]\(([^)#]*glossary\.md)#([^)]*)\)")


def _slug(heading: str) -> str:
    """GitHub's anchor algorithm, for the subset of punctuation this file uses: lowercase, drop
    anything that is not a word character, space or hyphen, then spaces to hyphens."""
    s = heading.strip().lower()
    s = re.sub(r"[^\w\s-]", "", s)
    return re.sub(r"\s+", "-", s)


def _anchors() -> set[str]:
    return {_slug(m) for m in re.findall(r"^## (.+)$", GLOSSARY.read_text(), re.M)}


def _markdown() -> list[Path]:
    return sorted(ROOT.glob("*.md")) + sorted(ROOT.glob("docs/*.md"))


def test_the_glossary_exists_and_has_terms() -> None:
    """Guards every assertion below from passing vacuously on an empty or moved file."""
    assert GLOSSARY.exists(), "docs/glossary.md is gone — the links below all point nowhere"
    assert len(_anchors()) >= 10, f"only {len(_anchors())} terms — did the file get truncated?"


def test_every_glossary_link_in_every_doc_resolves() -> None:
    """⚠️ Every markdown file, not just the README. A link in `docs/` rots the same way, and the
    file most likely to name a term precisely is the one written by someone being careful."""
    anchors, dead = _anchors(), []
    for p in _markdown():
        for text, _, anchor in LINK.findall(p.read_text()):
            if anchor not in anchors:
                dead.append(f"{p.relative_to(ROOT)}: [{text}](#{anchor})")
    assert not dead, (
        "these glossary links point at anchors that do not exist:\n  " + "\n  ".join(dead) +
        f"\navailable: {sorted(anchors)}")


def test_internal_cross_references_resolve_too() -> None:
    """The glossary links to ITSELF — `coherence` sends you to `consistency` and back. Those are
    bare `#anchor` links, which the test above does not match, and they rot the same way."""
    anchors = _anchors()
    text = GLOSSARY.read_text()
    bare = re.findall(r"\[([^\]]+)\]\(#([^)]*)\)", text)   # any fragment — see LINK above
    assert bare, "no internal cross-references found — this assertion would pass vacuously"
    dead = [f"[{t}](#{a})" for t, a in bare if a not in anchors]
    assert not dead, f"dead cross-references inside the glossary: {dead}"


def test_no_term_is_defined_twice() -> None:
    """Two entries for one word is the drift this repo's naming rule exists to prevent, and in a
    glossary it is self-refuting."""
    headings = re.findall(r"^## (.+)$", GLOSSARY.read_text(), re.M)
    dupes = {h for h in headings if headings.count(h) > 1}
    assert not dupes, f"defined more than once: {sorted(dupes)}"
    slugs = [_slug(h) for h in headings]
    assert len(set(slugs)) == len(slugs), "two headings collapse to the same anchor"


def test_the_readme_actually_links_the_terms_it_leans_on() -> None:
    """⛔ The failure this whole idea is meant to avoid: the glossary exists, nobody links to it,
    and the knowledge is parked where no reader will find it.

    These five carry meaning a reader cannot guess and that the README deliberately does not stop
    to explain. If the README stops using one, drop it here — but drop it on purpose.
    """
    readme = (ROOT / "README.md").read_text()
    linked = {a for _, _, a in LINK.findall(readme)}
    required = {"coherence", "well-formedness-rule", "battle", "noise-floor", "stated-gap"}
    assert required <= linked, f"README does not link: {sorted(required - linked)}"
