"""workflow_workbench — one Pydantic graph design, many competing strategies.

    GraphSpec        the design: nodes + edges, as DATA
    StrategySpec     one complete set of implementations for it
    SubgraphBinding  a whole child design, used as ONE node's implementation
    spec.render(strategy) -> a real pydantic_graph.Graph

`evals` is imported separately (`from workflow_workbench.evals import eval_battle`) so that `render()`
stays usable without an evaluation framework installed.
"""
from workflow_workbench.checks import (
    check_bindings,
    check_decisions,
    check_implementations,
    check_names,
    check_reachable,
    check_step_arity,
    check_subgraphs,
    check_transform_edges,
    check_variable_types,
    check_variables,
)
from workflow_workbench.diagram import diagram, diff_diagram
from workflow_workbench.graph_spec import GraphSpec
from workflow_workbench.spec import (
    END,
    START,
    DecisionSpec,
    EdgeSpec,
    JoinSpec,
    MapEdgeSpec,
    NodeSpec,
    SpecError,
    TransformEdgeSpec,
    StrategySpec,
    SubgraphBinding,
    VariableSpec,
)

__all__ = [
    "GraphSpec", "NodeSpec", "EdgeSpec", "JoinSpec", "DecisionSpec", "MapEdgeSpec", "TransformEdgeSpec", "VariableSpec",
    "StrategySpec",
    "SubgraphBinding",
    "SpecError",
    "START", "END",
    "check_names", "check_reachable", "check_variables", "check_bindings",
    "check_implementations", "check_subgraphs", "check_step_arity", "check_decisions",
    "check_variable_types", "check_transform_edges",
    "diagram", "diff_diagram",
]
