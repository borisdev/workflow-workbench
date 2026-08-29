"""Rung 6 — the picture pydantic-graph cannot draw, next to the one it can.

Their `visualize_graph.py` renders a BUILT graph, and it is good at it. The limit is not quality:

    graph.render()      one built graph. Both arms of one design render BYTE-IDENTICALLY, because
                        a built Graph retains no trace of which strategy produced it. A diff of
                        two of them is empty by construction, on every pair, forever.
    diagram(spec)       the DESIGN, before a single implementation exists.
    diff_diagram(a, b)  what two STRATEGIES share and where they differ.

The third has no equivalent in either library, and this rung proves the claim rather than
asserting it: it renders both arms with THEIR renderer and compares the strings.

⚠️ Theirs emits `stateDiagram-v2` and ours emits `flowchart`, and that is a PREFERENCE, not a
capability gap. `diagram.py` used to justify it by claiming a state diagram cannot carry the edge
variable; run this rung and read their output — `pick --> compose: salutation`. It carries it
fine. The docstring was corrected from this example rather than the other way round.

    uv run python3 -m examples.ladder.stage6_diagrams
"""
from __future__ import annotations

from examples.ladder.stage1_bare import HelloWorld, formal
from examples.ladder.stage2_strategies import casual


def main() -> None:
    spec = HelloWorld()

    print("1. THEIR renderer, on each arm's built graph:\n")
    a = spec.render(formal).render(title="formal", direction="LR")
    b = spec.render(casual).render(title="casual", direction="LR")
    print(a)
    print(f"\n   identical apart from the title we passed in: "
          f"{a.replace('formal', 'X') == b.replace('casual', 'X')}")
    print("   -> a built graph cannot tell you which strategy made it.\n")

    print("2. OUR diagram of the DESIGN — no strategy, no implementations:\n")
    print(spec.diagram())

    print("\n3. OUR diff of the two arms — the one neither library can draw:\n")
    print(spec.diff_diagram(formal, casual))

    print(f"\n4. and the same fact as data, for a report: {spec.varies(formal, casual)}")


if __name__ == "__main__":
    main()
