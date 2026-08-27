"""workflow-spec — one fixed graph design, many competing implementations.

    GraphSpec      the design: nodes + edges, as DATA
    StrategySpec   one complete set of implementations for it
    spec.render(strategy) -> a real pydantic_graph.Graph

`evals` is imported separately (`from workflow_spec.evals import eval_battle`) so that `render()`
stays usable without an evaluation framework installed.
"""
from workflow_spec.checks import (
    check_bindings,
    check_implementations,
    check_names,
    check_reachable,
    check_variables,
)
from workflow_spec.diagram import diagram, diff_diagram
from workflow_spec.graph_spec import GraphSpec
from workflow_spec.spec import (
    END,
    START,
    EdgeSpec,
    NodeSpec,
    SpecError,
    StrategySpec,
    VariableSpec,
)

__all__ = [
    "GraphSpec", "NodeSpec", "EdgeSpec", "VariableSpec", "StrategySpec", "SpecError",
    "START", "END",
    "check_names", "check_reachable", "check_variables", "check_bindings",
    "check_implementations",
    "diagram", "diff_diagram",
]
