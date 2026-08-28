"""graph_strategies — one Pydantic graph design, many competing strategies.

    GraphSpec      the design: nodes + edges, as DATA
    StrategySpec   one complete set of implementations for it
    spec.render(strategy) -> a real pydantic_graph.Graph

`evals` is imported separately (`from graph_strategies.evals import eval_battle`) so that `render()`
stays usable without an evaluation framework installed.
"""
from graph_strategies.checks import (
    check_bindings,
    check_implementations,
    check_names,
    check_reachable,
    check_variables,
)
from graph_strategies.diagram import diagram, diff_diagram
from graph_strategies.graph_spec import GraphSpec
from graph_strategies.spec import (
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
