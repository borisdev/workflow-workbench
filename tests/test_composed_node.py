"""A composed stage — one whose implementation is a whole child design — says so.

⛔ SHAPE, not colour, and the two channels are independent. `varies` says what is AT STAKE
between two arms; composed says what the node IS in one. A role that is a function in one arm
and a child design in the other is the most interesting cell on the canvas — "is decomposing
this stage actually better" — and one channel could not carry both facts.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_subgraph import Parent, direct_strategy, subgraph_strategy  # noqa: E402
from workflow_workbench.devserver import spec_payload  # noqa: E402
from workflow_workbench.payload import WorkflowReport  # noqa: E402


def test_a_subgraph_bound_stage_gets_its_own_shape() -> None:
    """`[[…]]` is mermaid's subroutine shape. A callable keeps the plain `[…]` box."""
    composed = Parent().diagram(subgraph_strategy)
    plain = Parent().diagram(direct_strategy)
    assert 'transform[["transform' in composed, composed
    assert 'transform["transform' in plain and "[[" not in plain, plain


def test_the_diff_keeps_the_shape_when_only_ONE_arm_is_composed() -> None:
    """⛔ The regression that matters. Judging composed-ness on arm `a` alone would drop the
    shape for exactly the comparison worth looking at — a function against a child design."""
    diff = Parent().diff_diagram(direct_strategy, subgraph_strategy)
    assert "[[" in diff, diff
    assert ":::varies" in diff, "a function vs a subgraph must still read as varying"


def test_the_payload_says_subgraph_explicitly_not_by_parsing_the_label() -> None:
    """⚠️ A viewer that string-matches `impl` for `::` is one rename away from silently losing
    every drill-down, and nothing would say so."""
    report = WorkflowReport.model_validate(
        spec_payload(Parent(), [direct_strategy, subgraph_strategy]))
    by_name = {la.name: la for la in report.layers}
    assert by_name["subgraph"].bindings["transform"].subgraph is True
    assert by_name["direct"].bindings["transform"].subgraph is False


def test_composed_and_varies_are_independent_facts() -> None:
    """Both arms composed with DIFFERENT child strategies: composed in both, and still varying.
    If the renderer merged the two channels this is the case that would lose one."""
    from workflow_workbench import StrategySpec, SubgraphBinding
    from test_subgraph import Child, child_strategy, first, second, transform

    other_child = StrategySpec("other_child", {first: child_strategy[first],
                                               second: child_strategy[second]})
    arm_b = StrategySpec("arm_b", {transform: SubgraphBinding(Child(), other_child)})

    diff = Parent().diff_diagram(subgraph_strategy, arm_b)
    assert "[[" in diff, "both arms are composed; the shape must survive"
    assert ":::varies" in diff, "different child strategies still vary"
