"""One stable extraction role, implemented at three levels of sophistication.

The parent design always has exactly one `extract` node. What fills it changes:

    naive    one callable, a cheap model, low recall
    better   one callable, a strong model — high recall, and it keeps the junk
    fancy    a two-step child design: generate candidates, then verify them

`fancy` is the point. It is not a special node kind and not a nested runner — it is another
complete `GraphSpec + StrategySpec`, checked on its own terms, run through the parent as one step.
The parent's node ids are byte-identical across all three, which is what lets a battle align them.

    uv run python3 examples/subgraph.py
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel

from workflow_workbench import (
    END,
    START,
    EdgeSpec,
    GraphSpec,
    NodeSpec,
    StrategySpec,
    SubgraphBinding,
    VariableSpec,
)


class Document(BaseModel):
    text: str


class Candidates(BaseModel):
    items: tuple[str, ...]


class Facts(BaseModel):
    items: tuple[str, ...]


@dataclass
class ExtractionState:
    calls: list[str] = field(default_factory=list)


@dataclass
class ExtractionDeps:
    """A deterministic stand-in for the prompt/model call.

    Named `prompt` and `model` because that is the variation these strategies are really about —
    but it runs with no key and no network, so the example is a check rather than a demo.
    """

    async def extract(self, *, document: Document, prompt: str, model: str) -> Facts:
        sentences = tuple(p.strip() for p in document.text.split(".") if p.strip())
        return Facts(items=sentences[:1] if model == "cheap-model" else sentences)


document_value = VariableSpec("document", Document)
candidate_value = VariableSpec("candidate_facts", Candidates)
facts_value = VariableSpec("facts", Facts)

extract = NodeSpec("extract", inputs=(document_value,), outputs=(facts_value,))
"""The role. `Document -> Facts`, and it does not move for any of the three strategies below."""


class ExtractionWorkflow(GraphSpec):
    name = "extraction_workflow"
    state_type, deps_type = ExtractionState, ExtractionDeps
    input_type, output_type = Document, Facts
    nodes = (extract,)
    edges = (EdgeSpec(START, extract, document_value),
             EdgeSpec(extract, END, facts_value))


# ── two ordinary callables ──────────────────────────────────────────────────────────────────

async def naive_extract(ctx) -> Facts:
    ctx.state.calls.append("naive_extract")
    return await ctx.deps.extract(document=ctx.inputs, prompt="extract facts", model="cheap-model")


async def better_extract(ctx) -> Facts:
    ctx.state.calls.append("better_extract")
    return await ctx.deps.extract(
        document=ctx.inputs, prompt="extract every explicit factual statement", model="strong-model")


# ── and one child design ────────────────────────────────────────────────────────────────────

generate_candidates = NodeSpec("generate_candidates",
                               inputs=(document_value,), outputs=(candidate_value,))
verify_candidates = NodeSpec("verify_candidates",
                             inputs=(candidate_value,), outputs=(facts_value,))


class VerifiedExtraction(GraphSpec):
    """`Document -> Facts` — the same boundary as `extract`, reached in two visible steps.

    ⚠️ `candidate_facts` and `facts` are both a tuple of strings. They are separate VariableSpecs
    because a type checker cannot tell you the verifier was wired to the wrong one; a name can.
    """

    name = "verified_extraction"
    state_type, deps_type = ExtractionState, ExtractionDeps
    input_type, output_type = Document, Facts
    nodes = (generate_candidates, verify_candidates)
    edges = (EdgeSpec(START, generate_candidates, document_value),
             EdgeSpec(generate_candidates, verify_candidates, candidate_value),
             EdgeSpec(verify_candidates, END, facts_value))


async def generate(ctx) -> Candidates:
    """Deliberately broad. Recall is this step's job; precision is the next one's."""
    ctx.state.calls.append("generate")
    return Candidates(items=tuple(p.strip() for p in ctx.inputs.text.split(".") if p.strip()))


async def verify(ctx) -> Facts:
    """Drop anything too short to be a factual statement — a separate, inspectable decision."""
    ctx.state.calls.append("verify")
    return Facts(items=tuple(i for i in ctx.inputs.items if len(i.split()) >= 3))


verified = StrategySpec("verified", {generate_candidates: generate, verify_candidates: verify})

naive = StrategySpec("naive", {extract: naive_extract})
better = StrategySpec("better", {extract: better_extract})
fancy = StrategySpec("fancy", {extract: SubgraphBinding(VerifiedExtraction(), verified)})


def main() -> None:
    document = Document(text="Vitamin K2 is listed as 100 mg. That may be a unit error. "
                             "Unclear. Confirm the intended dose.")
    deps = ExtractionDeps()

    print(f"design checks clean with no strategy at all: "
          f"{ExtractionWorkflow().check() or 'yes'}")

    # The child stands on its own. If it did not, it would be a fragment, not a design.
    child_state = ExtractionState()
    child_result = VerifiedExtraction().render(verified).run_sync(
        inputs=document, state=child_state, deps=deps)
    print(f"\nthe child, run directly:  {len(child_result.items)} facts  "
          f"steps={child_state.calls}")

    print("\nthe same child, run as one node of the parent:")
    workflow = ExtractionWorkflow()
    for strategy in (naive, better, fancy):
        state = ExtractionState()
        graph = workflow.render(strategy)
        result = graph.run_sync(inputs=document, state=state, deps=deps)
        steps = ", ".join(state.calls)
        print(f"  {strategy.name:<7} parent nodes={sorted(graph.nodes)}")
        print(f"          steps run=[{steps}]  ->  {len(result.items)} facts: {result.items}")

    # ⛔ The invariant. `better` runs one step and `fancy` runs two, and the parent cannot tell:
    # its node set is identical, so a battle has something to align on.
    ids = [sorted(workflow.render(s).nodes) for s in (naive, better, fancy)]
    assert ids[0] == ids[1] == ids[2] == ["__end__", "__start__", "extract"], ids
    print(f"\nnode ids identical across all three arms: {ids[0]}")

    print(f"\nwhat varies (better vs fancy): {workflow.varies(better, fancy)}")
    print(f"\nstrategy diff:\n{workflow.diff_diagram(better, fancy)}")


if __name__ == "__main__":
    main()
