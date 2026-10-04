"""workflow_workbench — one Pydantic graph design, many competing strategies.

    GraphSpec        the design: nodes + edges, as DATA
    StepSpec         one role a strategy fills. The class you instantiate.
    NodeSpec         StepSpec | JoinSpec | DecisionSpec — every box the design declares
    Bindable         StepSpec | TransformEdgeSpec — everything a strategy must bind
    StrategySpec     one complete set of implementations for it
    SubgraphBinding  a whole child design, used as ONE node's implementation
    CoherenceFinding what a check found — a `str`, with `check` / `about` / `blocking` on it
    blocking         the findings that stop a render, i.e. all but the stated gaps
    spec.render(strategy) -> a real pydantic_graph.Graph

`evals` is imported separately (`from workflow_workbench.evals import eval_battle`) so that `render()`
stays usable without an evaluation framework installed.
"""
from workflow_workbench.checks import (
    NOT_CHECKED,
    CoherenceFinding,
    blocking,
    check_bindings,
    check_fan_out_rejoins,
    check_recursion,
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
    Bindable,
    DecisionSpec,
    EdgeSpec,
    JoinSpec,
    MapEdgeSpec,
    NodeSpec,
    StepSpec,
    SpecError,
    TransformEdgeSpec,
    StrategySpec,
    SubgraphBinding,
    VariableSpec,
)

__all__ = [
    "GraphSpec", "StepSpec", "EdgeSpec", "JoinSpec", "DecisionSpec", "MapEdgeSpec",
    "TransformEdgeSpec", "VariableSpec",
    "NodeSpec", "Bindable",
    "StrategySpec",
    "SubgraphBinding",
    "SpecError",
    "START", "END",
    "CoherenceFinding", "blocking", "NOT_CHECKED",
    "check_names", "check_reachable", "check_variables", "check_bindings",
    "check_implementations", "check_subgraphs", "check_step_arity", "check_decisions",
    "check_variable_types", "check_transform_edges", "check_fan_out_rejoins",
    "check_recursion",
    "diagram", "diff_diagram",
]
