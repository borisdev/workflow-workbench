"""Extraction — a domain-shaped example, and the one that shows why VariableSpec exists.

`candidate_facts` and `rejected_facts` are both `list[Fact]`. A type checker cannot tell you the
verifier was wired to the wrong one. A NAME can, and `check_variables` does.

    uv run python3 examples/local/extraction.py
"""
from __future__ import annotations

from dataclasses import dataclass

from workflow_workbench import (
    END,
    START,
    EdgeSpec,
    GraphSpec,
    NodeSpec,
    SpecError,
    StrategySpec,
    VariableSpec,
)


@dataclass(frozen=True)
class Fact:
    text: str
    confidence: float


source_text = VariableSpec("source_text", str)
candidate_facts = VariableSpec("candidate_facts", list[Fact])
rejected_facts = VariableSpec("rejected_facts", list[Fact])
kept_facts = VariableSpec("kept_facts", list[Fact])

extract = NodeSpec("extract", inputs=(source_text,),
                   outputs=(candidate_facts, rejected_facts))
verify = NodeSpec("verify", inputs=(candidate_facts,), outputs=(kept_facts,))


class Extraction(GraphSpec):
    name = "extraction"
    input_type, output_type = str, list
    nodes = (extract, verify)
    edges = (
        EdgeSpec(source=START, target=extract, carries=source_text),
        EdgeSpec(source=extract, target=verify, carries=candidate_facts),   # the CANDIDATES, not the rejects
        EdgeSpec(source=verify, target=END, carries=kept_facts),
    )


async def greedy_extract(ctx) -> list[Fact]:
    return [Fact(w, 0.5) for w in ctx.inputs.split() if len(w) > 3]


async def strict_extract(ctx) -> list[Fact]:
    return [Fact(w, 0.9) for w in ctx.inputs.split() if len(w) > 6]


async def keep_all(ctx) -> list[Fact]:
    return list(ctx.inputs)


async def keep_confident(ctx) -> list[Fact]:
    return [f for f in ctx.inputs if f.confidence >= 0.8]


greedy = StrategySpec("greedy", {extract: greedy_extract, verify: keep_all})
strict = StrategySpec("strict", {extract: strict_extract, verify: keep_confident})

TEXT = "metformin reduces hepatic glucose production in patients with insulin resistance"


def main() -> None:
    spec = Extraction()
    print(f"check(): {spec.check(greedy) or 'clean'}")

    for strategy in (greedy, strict):
        graph = spec.render(strategy)
        out = graph.run_sync(inputs=TEXT)
        print(f"  {strategy.name:<7} -> {len(out)} facts: {[f.text for f in out][:4]}")

    print(f"\nvaries: {spec.varies(greedy, strict)}")

    # ── the swap that only a per-edge check can see ──────────────────────────────────────────
    class Swapped(Extraction):
        name = "extraction-swapped"
        edges = (
            EdgeSpec(source=START, target=extract, carries=source_text),
            EdgeSpec(source=extract, target=verify, carries=rejected_facts),   # ⛔ wrong variable, same TYPE
            EdgeSpec(source=verify, target=END, carries=kept_facts),
        )

    print("\nthe same design with the verifier wired to `rejected_facts` "
          "(identical type, different meaning):")
    try:
        Swapped().render(greedy)
        print("  ⛔ rendered clean — the check did NOT catch it")
    except SpecError as exc:
        print(f"  caught: {str(exc).splitlines()[1].strip()}")


if __name__ == "__main__":
    main()
