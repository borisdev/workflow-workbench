"""Every Pydantic Graph builder feature, theirs beside ours. SOURCE, not documentation.

⛔ THIS FILE IS THE ONE DEFINITION. The README appendix is GENERATED from it and
`tests/test_parity.py` fails if the two disagree — `.claude/rules/spec-as-code.md`: a document is
either source or derived, and mixing them is the whole failure mode.

    python3 -m workflow_workbench.parity          # print the markdown
    python3 -m workflow_workbench.parity --check   # exit 1 if the README is stale

Why it exists at all: an earlier version of this table lived in a probe, hand-written from a grep,
and MISSED FIVE features while reading as a complete inventory of the gaps. A list of someone
else's API is wrong the moment they add to it. `docs/probe_builder_features.py` introspects
`GraphBuilder` and fails on any public method absent from `FEATURES` below.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass

__all__ = ["Feature", "FEATURES", "as_markdown"]


@dataclass(frozen=True)
class Feature:
    """One builder capability: what they write, what we write, and whether we cover it.

    `status` is deliberately four values, not two. "partial" and "refused" are different facts and
    collapsing them into "no" is how a deliberate design decision comes to read as a gap.
    """

    api: str
    status: str          # "yes" | "partial" | "refused" | "cannot" | "plumbing"
    #: ⚠️ `status` is per FEATURE, and "yes" means the feature is reachable — NOT that every
    #: parameter of it is. Twice now that has read as more than it says: `map` yes + `transform`
    #: yes does not mean both on one edge, and `join` yes does not include `parent_fork_id` /
    #: `preferred_parent_fork`. Each is written into the row's note. If a third turns up, the
    #: table shape is wrong and should carry per-parameter coverage rather than per-method.
    #:
    #: ⚠️ `status` is per FEATURE, and a feature-by-feature table cannot express COMPOSITION.
    #: `map` is yes and `transform` is yes, and `.map().transform(f).to(b)` on one edge is still
    #: not expressible here — their Path is an ordered list of markers, ours is a typed edge.
    #: Recorded in the notes rather than left for someone to infer a capability we do not have.
    theirs: str
    ours: str
    note: str = ""


FEATURES: tuple[Feature, ...] = (
    Feature(
        "step", "yes",
        "@g.step\nasync def double(ctx) -> int:\n    return ctx.inputs * 2",
        'double = NodeSpec("double", inputs=(n,), outputs=(n,))\n'
        '# and a strategy binds the body:\n'
        'StrategySpec("s", {double: double_impl})',
        "Theirs names the node after the function. Ours names it in the DESIGN, so two "
        "strategies produce the same node ids and can be compared.",
    ),
    Feature(
        "add / add_edge / label", "yes",
        "g.add(g.edge_from(a).to(b))\ng.add_edge(a, b, label='count')",
        "EdgeSpec(source=a, target=b, carries=count)          # `carries` IS the label",
        "",
    ),
    Feature(
        "join", "yes",
        "collect = g.join(reduce_sum, initial=0)",
        'collect = JoinSpec("collect", reduce_sum, initial=0,\n'
        '                   inputs=(number,), outputs=(total,))\n'
        'class Design(GraphSpec):\n    joins = (collect,)',
        "In `joins`, not `nodes`: a reducer is `(current, input) -> current`, so there is no "
        "implementation for a strategy to bind. ⚠️ `parent_fork_id` and `preferred_parent_fork` "
        "are NOT exposed. They pick WHICH fork a join closes, which only matters once fan-outs "
        "nest — measured: map-over-papers then map-over-edges collects one flat list because the "
        "default is 'farthest'. Asking for 'closest' needs a fork id, and forks are minted by "
        "the builder and never named in a declaration.",
    ),
    Feature(
        "map / add_mapping_edge", "yes",
        "g.edge_from(g.start_node).map().to(square)",
        "MapEdgeSpec(source=START, target=square, carries=numbers, delivers=number)",
        "`carries` is the collection on the wire, `delivers` the item the target receives. "
        "Naming both is what keeps both ends checked. ⚠️ NOT COMPOSABLE with a transform: theirs "
        "is a list of markers on one edge, so `.map().transform(f).to(b)` fans out AND reshapes "
        "each item; ours are separate types and no edge is both. Measured, not assumed.",
    ),
    Feature(
        "decision", "yes",
        "d = g.decision()\n"
        "d = d.branch(g.match(Urgent).to(escalate))\n"
        "d = d.branch(g.match(Routine).to(research))",
        'route = DecisionSpec("route")\n'
        "EdgeSpec(source=route, target=escalate, carries=v, when=Urgent)\n"
        "EdgeSpec(source=route, target=research, carries=v, when=Routine)",
        "The condition lives on the EDGE so `edges` stays the only place topology is written. "
        "A decision binds nothing, so two arms are guaranteed to route identically.",
    ),
    Feature(
        "stream", "yes",
        "@g.stream\nasync def split(ctx):\n    for w in ctx.inputs.split():\n        yield w",
        'split = NodeSpec("split", inputs=(text,), outputs=(words,), streams=True)\n'
        "MapEdgeSpec(source=split, target=collect, carries=words, delivers=word)   # its output is an AsyncIterable",
        "A flag on NodeSpec, not its own type: a stream IS a role a strategy fills.",
    ),
    Feature(
        "broadcast", "yes",
        "g.edge_from(a).broadcast(lambda eb: [eb.to(x), eb.to(y)])",
        "EdgeSpec(source=a, target=x, carries=v)\nEdgeSpec(source=a, target=y, carries=v)   # two edges from one source",
        "MEASURED equivalent: same topology, same answer. Only the generated fork node's name "
        "differs. No vocabulary was added for it.",
    ),
    Feature(
        "edge_from(*sources) / to(a, b)", "yes",
        "g.edge_from(a, b).to(sink)",
        "EdgeSpec(source=a, target=sink, carries=v)\nEdgeSpec(source=b, target=sink, carries=v)",
        "MEASURED byte-identical. ⚠️ But two producers into one STEP is a real defect — the step "
        "runs once per edge and one result is discarded. Use a JoinSpec; `check_step_arity` "
        "refuses the other shape.",
    ),
    Feature(
        "match(matches=predicate)", "partial",
        "d.branch(g.match(int, matches=lambda v: v > 10).to(big))",
        "# not declarable. Return a discriminating TYPE from a step instead:\n"
        "async def triage(ctx) -> Urgent | Routine: ...\n"
        "EdgeSpec(source=route, target=escalate, carries=v, when=Urgent)",
        "REFUSED, not missing. A callable in the declaration is an implementation: `diagram()` "
        "cannot draw it and `varies()` cannot compare two. Making the decision a typed value is "
        "the better design anyway — it becomes something you can see and battle.",
    ),
    Feature(
        "transform", "yes",
        "g.edge_from(a).transform(lambda ctx: ctx.inputs.edges).to(b)",
        "# fixed — part of the design, like a JoinSpec's reducer:\n"
        "TransformEdgeSpec(source=propose, target=cite, carries=draft, delivers=edge_list, apply=take_edges)\n"
        "# or a variation point — every strategy binds it, and varies() reports it:\n"
        "shape = TransformEdgeSpec(source=propose, target=cite, carries=draft, delivers=edge_list)\n"
        'StrategySpec("all", {..., shape: all_edges})',
        "Emits NO node, exactly as theirs does, so the diagram tags the arrow rather than adding "
        "a box — a reshape is not a stage and drawing it as one misleads. `variable` is what "
        "leaves the source, `produces` what arrives. Exactly one of `apply=` or a binding: "
        "neither is a silently missing transform, both is a coin toss. Must be SYNC — an async "
        "one is not rejected by pydantic-graph, it quietly yields a coroutine.",
    ),
    Feature(
        "node(BaseNode) / match_node", "cannot",
        "class Increment(BaseNode[S, None, int]):\n"
        "    async def run(self, ctx) -> DoubleIt:       # names its OWN successor\n"
        "        return DoubleIt(...)",
        "# no equivalent for the CLASS. All three things it is used FOR are declarable:\n"
        "EdgeSpec(source=gate, target=END, carries=v, when=NotAPlan)      # 1. stop early  (their End(...))\n"
        "EdgeSpec(source=again, target=retry_seed, carries=v, when=Thin)  # 2. go back     (a loop)\n"
        "EdgeSpec(source=unwrap, target=propose, carries=seed)\n"
        "EdgeSpec(source=route, target=escalate, carries=v, when=Urgent)  # 3. dispatch    (pick a successor)",
        "A BaseNode's topology lives inside its implementation, so declared `edges` would be a "
        "lie it is free to ignore — two arms binding different BaseNodes could be two different "
        "graphs while `diff_diagram()` drew them as one. ⚠️ But what is lost is the AUTHORING "
        "STYLE, not the capability: `examples/ladder/stage10_no_basenode.py` does all three in "
        "one design. The real cost is porting an existing BaseNode app, and one converter node "
        "wherever two paths reach the same step carrying different variables.",
    ),
    Feature("build", "plumbing", "graph = g.build()", "graph = spec.render(strategy)", ""),
    Feature("start_node / end_node", "plumbing", "g.start_node, g.end_node", "START, END", ""),
    Feature("Source / Destination", "plumbing", "typing helpers", "not surfaced", ""),
)

_LABEL = {"yes": "**yes**", "partial": "partial", "refused": "refused, on purpose",
          "cannot": "cannot be declared", "plumbing": "plumbing"}


def as_markdown() -> str:
    """The appendix. Regenerate with `python3 -m workflow_workbench.parity`."""
    out = ["## Appendix: every Pydantic Graph builder feature, theirs beside ours", "",
           "<!-- GENERATED from workflow_workbench/parity.py — do not edit by hand. -->",
           "<!-- Regenerate: python3 -m workflow_workbench.parity -->", ""]
    for f in FEATURES:
        if f.status == "plumbing":
            continue
        out += [f"### `{f.api}` — {_LABEL[f.status]}", "", "Pydantic Graph:", "",
                "```python", f.theirs, "```", "", "Workflow Workbench:", "",
                "```python", f.ours, "```", ""]
        if f.note:
            out += [f"> {f.note}", ""]
    plumbing = ", ".join(f"`{f.api}`" for f in FEATURES if f.status == "plumbing")
    out += [f"**Plumbing, not topology:** {plumbing} — `render()` and `START`/`END` cover these.",
            ""]
    return "\n".join(out)


START_MARK = "<!-- parity:start -->"
END_MARK = "<!-- parity:end -->"


def _readme() -> tuple[str, str]:
    import pathlib
    p = pathlib.Path(__file__).resolve().parent.parent / "README.md"
    return p.read_text(), str(p)


def main() -> int:
    body = as_markdown()
    if "--check" not in sys.argv:
        print(body)
        return 0
    text, path = _readme()
    if START_MARK not in text or END_MARK not in text:
        print(f"{path}: parity markers missing")
        return 1
    current = text.split(START_MARK, 1)[1].split(END_MARK, 1)[0].strip()
    if current != body.strip():
        print(f"{path}: the appendix is stale. Regenerate:\n"
              f"  python3 -m workflow_workbench.parity")
        return 1
    print("README appendix matches parity.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
