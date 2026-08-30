"""Every check, as pure data. No `pydantic_graph` import anywhere in this module.

Each returns a list of findings — strings a human can act on — and never raises. An empty list is
a pass; `GraphSpec.check()` is what turns a non-empty list into an exception.

⚠️ Findings say what is wrong AND what it costs. "node 'x' is unreachable" is a fact; "…so its
implementation never runs, and a strategy that binds it will look like it works" is a reason to
fix it.
"""
from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from workflow_workbench.spec import (
    DecisionSpec,
    EdgeSpec,
    NodeSpec,
    StrategySpec,
    SubgraphBinding,
    _End,
    _Start,
    is_sentinel,
)

__all__ = ["check_names", "check_reachable", "check_variables", "check_bindings",
           "check_implementations", "check_subgraphs", "check_step_arity", "check_decisions",
           "check_variable_types"]


def _name(ep: Any) -> str:
    return "START" if isinstance(ep, _Start) else "END" if isinstance(ep, _End) else ep.name


def _type_name(t: Any) -> str:
    """A stable name for a type in a finding. `__name__` misses generic aliases like
    `list[Fact]`, which have none — and printing `<class ...>` for one and a bare name for the
    other makes two findings about the same mistake look like two different mistakes."""
    return getattr(t, "__name__", None) or repr(t)


def check_names(nodes: tuple[NodeSpec, ...]) -> list[str]:
    """Node names must be unique — `render()` uses them as graph node ids.

    ⚠️ This check exists BECAUSE `NodeSpec` is `eq=False`. Identity keying is what stops a
    copy-pasted declaration silently overwriting another's implementation; the cost is that two
    distinct nodes may share a name, and pydantic-graph would then refuse with a message about
    node ids that points at the render, not at the declaration.
    """
    findings, seen = [], {}
    for n in nodes:
        seen.setdefault(n.name, []).append(n)
    for name, group in seen.items():
        if len(group) > 1:
            findings.append(
                f"{len(group)} different nodes are named {name!r}. Node names become graph node "
                f"ids, so this cannot be rendered — and because NodeSpec is identity-keyed these "
                f"really are separate nodes, not one node declared twice.")
    return findings


def check_reachable(nodes: tuple[NodeSpec, ...], edges: tuple[EdgeSpec, ...]) -> list[str]:
    """Every node reachable from START, and every node able to reach END.

    Pure Python over the declaration — no graph is built, so this runs before a single
    implementation exists. Cycle-safe via a seen-set (verified in `docs/probe_api.py` probe 3).

    Both directions matter and they catch different mistakes:
      · unreachable from START — the node never runs; a strategy binding it looks like it works
      · cannot reach END — the work is done and thrown away, which reads as a silent drop
    """
    findings: list[str] = []
    fwd: dict[Any, list[Any]] = {}
    bwd: dict[Any, list[Any]] = {}
    for e in edges:
        fwd.setdefault(id(e.source), []).append(e.target)
        bwd.setdefault(id(e.target), []).append(e.source)

    def walk(start: Any, adj: dict[Any, list[Any]]) -> set[int]:
        seen: set[int] = set()
        stack = [start]
        while stack:
            cur = stack.pop()
            if id(cur) in seen:
                continue
            seen.add(id(cur))
            stack.extend(adj.get(id(cur), ()))
        return seen

    starts = [e.source for e in edges if isinstance(e.source, _Start)]
    ends = [e.target for e in edges if isinstance(e.target, _End)]
    if not starts:
        findings.append("no edge leaves START — nothing in this design can ever run.")
    if not ends:
        findings.append("no edge reaches END — this design produces no output.")

    from_start: set[int] = set()
    for s in starts:
        from_start |= walk(s, fwd)
    to_end: set[int] = set()
    for t in ends:
        to_end |= walk(t, bwd)

    for n in nodes:
        if starts and id(n) not in from_start:
            findings.append(
                f"node {n.name!r} is unreachable from START — its implementation never runs, so a "
                f"strategy that binds it will appear to work while doing nothing.")
        if ends and id(n) not in to_end:
            findings.append(
                f"node {n.name!r} cannot reach END — whatever it produces is discarded, which is "
                f"indistinguishable from a step that was never wired.")

    declared = {id(n) for n in nodes}
    for e in edges:
        for ep in (e.source, e.target):
            if not is_sentinel(ep) and id(ep) not in declared:
                findings.append(
                    f"edge {e!r} references node {_name(ep)!r}, which is not in `nodes`. "
                    f"An undeclared node is invisible to every other check and to any strategy.")
    return findings


def check_variables(nodes: tuple[NodeSpec, ...], edges: tuple[EdgeSpec, ...]) -> list[str]:
    """Per edge: the variable it carries must be an output of its source and an input of its target.

    ⛔ PER EDGE, never aggregated across a node's edges. The aggregate form — "is the set of a
    node's declared outputs covered by the set of variables its successors consume" — passes on a
    SWAP, which is the exact defect this check was written for:

        split = NodeSpec("split", outputs=(stream_a, stream_b))
        EdgeSpec(split, consume_a, stream_b)      # swapped
        EdgeSpec(split, consume_b, stream_a)      # swapped

    Both variables are produced, both are consumed, every set matches — and the wiring is wrong.
    Only a per-edge check sees it.

    Edges touching START/END are skipped on the sentinel side: sentinels declare no variables, and
    the graph's own `input_type`/`output_type` is what constrains them.
    """
    findings: list[str] = []
    for e in edges:
        if e.map_over is not None and e.variable is None:
            findings.append(
                f"edge {e!r} fans out to {e.map_over.name!r} but does not name the collection it "
                f"carries. Both ends of a fan-out must be declared or only one of them is checked.")
            continue
        if e.variable is None:
            continue
        if not is_sentinel(e.source):
            if e.variable not in e.source.outputs:
                declared = ", ".join(v.name for v in e.source.outputs) or "nothing"
                findings.append(
                    f"edge {e!r} carries {e.variable.name!r}, but {e.source.name!r} does not "
                    f"declare it as an output (it declares: {declared}). Either the edge is wired "
                    f"to the wrong variable or the node's contract is out of date.")
        if not is_sentinel(e.target):
            # ⚠️ On a fan-out the two ends carry DIFFERENT variables: the collection crosses the
            # wire, the target receives one item. So the target is checked against `map_over`.
            arrives = e.map_over if e.map_over is not None else e.variable
            if arrives not in e.target.inputs:
                declared = ", ".join(v.name for v in e.target.inputs) or "nothing"
                how = " (one item per run)" if e.map_over is not None else ""
                findings.append(
                    f"edge {e!r} delivers {arrives.name!r}{how} to {e.target.name!r}, which does "
                    f"not declare it as an input (it declares: {declared}).")
    return findings


def check_bindings(nodes: tuple[NodeSpec, ...], strategy: StrategySpec) -> list[str]:
    """The strategy binds exactly the declared nodes — no missing, no extra.

    ⚠️ Compared by IDENTITY, matching `NodeSpec.__hash__`. Comparing by name would accept a
    binding keyed on a look-alike node from another design, which is the failure identity keying
    exists to prevent.
    """
    findings: list[str] = []
    declared = {id(n): n for n in nodes}
    bound = {id(n): n for n in strategy.bindings}
    for nid, n in declared.items():
        if nid not in bound:
            findings.append(
                f"strategy {strategy.name!r} does not bind node {n.name!r}. Every node is bound "
                f"explicitly, including unchanged ones — a partial strategy makes 'what varies "
                f"between these arms' unanswerable without reading both files.")
    for nid, n in bound.items():
        if nid not in declared:
            findings.append(
                f"strategy {strategy.name!r} binds {n.name!r}, which this design does not declare. "
                f"Most likely it was written against a different GraphSpec that has a node of the "
                f"same name.")
    return findings


def check_implementations(strategy: StrategySpec) -> list[str]:
    """Each bound CALLABLE is callable and takes exactly one positional argument (`ctx`).

    Caught here rather than inside `GraphBuilder`, so a strategy's fault is reported against the
    strategy instead of surfacing as a runtime error attributed to the engine.

    ⚠️ Subgraph bindings are skipped, NOT rejected. A `SubgraphBinding` is not callable and this
    function would otherwise report it as one — a finding that names the wrong defect and points
    at the wrong file. Whether a subgraph fits is a RELATIONAL fact about it and the parent node,
    so `check_subgraphs`, which is handed the parent, owns it.
    """
    findings: list[str] = []
    for node, impl in strategy.bindings.items():
        if isinstance(impl, SubgraphBinding):
            continue
        if not callable(impl):
            findings.append(
                f"{strategy.name!r} binds {node.name!r} to {impl!r}, which is not callable.")
            continue
        try:
            sig = inspect.signature(impl)
        except (TypeError, ValueError):
            continue                    # builtins etc. — unverifiable, not a finding
        positional = [p for p in sig.parameters.values()
                      if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
                      and p.default is p.empty]
        if len(positional) != 1:
            findings.append(
                f"{strategy.name!r} binds {node.name!r} to "
                f"{getattr(impl, '__qualname__', impl)}{sig}, which takes {len(positional)} "
                f"required positional arguments. A pydantic-graph step body takes exactly one "
                f"(`ctx`).")
    return findings


def _graph_name(graph: Any) -> str:
    return graph.name or type(graph).__name__


def _port_type(parent: Any, node: NodeSpec, side: str) -> tuple[Any, str | None]:
    """The type crossing one side of `node`'s boundary, and any finding about resolving it.

    ⚠️ START and END are EXCEPTIONS, and they are why this function exists instead of a length
    check. A node declaring no input variable is idiomatic when it is fed from START —

        increment = NodeSpec("increment", outputs=(count,))
        EdgeSpec(START, increment)                       # carries the graph's own input_type

    — so rejecting it would force a DESIGN edit in order to add a strategy, which is exactly the
    thing a stable `NodeSpec` is supposed to make unnecessary. There is a real type available in
    that case: the parent graph's `input_type`. Use it.

    Returns `(type, None)` when the boundary type is known, or `(None, finding)` when it is not.
    A `NOT CHECKED` finding is a stated gap and does not block `render()`; anything else does.
    """
    if side == "input":
        declared, fallback = node.inputs, parent.input_type
        adjacent = [e.source for e in parent.edges if e.target is node]
        sentinel, sentinel_name, port = _Start, "START", "input_type"
    else:
        declared, fallback = node.outputs, parent.output_type
        adjacent = [e.target for e in parent.edges if e.source is node]
        sentinel, sentinel_name, port = _End, "END", "output_type"

    if len(declared) == 1:
        return declared[0].type, None

    if len(declared) > 1:
        names = ", ".join(v.name for v in declared)
        return None, (
            f"node {node.name!r} declares {len(declared)} {side}s ({names}), and a subgraph "
            f"binding needs ONE — there is no way to say which of them the child graph's "
            f"{port} should match. Multi-port subgraph boundaries are deliberately out of "
            f"scope until something needs one.")

    if adjacent and all(isinstance(ep, sentinel) for ep in adjacent):
        return fallback, None

    return None, (
        f"NOT CHECKED — node {node.name!r} declares no {side} variable and is not wired to "
        f"{sentinel_name}, so there is nothing to compare the child graph's {port} against. "
        f"Declare the variable to get this checked. This is a stated gap, not a pass.")


def check_subgraphs(parent: Any, strategy: StrategySpec,
                    *, ancestry: tuple[tuple[type, int], ...] = ()) -> list[str]:
    """Every child design used as a node implementation fits the node it is bound to.

    ⚠️ `parent` is typed `Any` on purpose: `graph_spec` imports this module, so this module cannot
    import `GraphSpec` back without a cycle. It is always a `GraphSpec`.

    Four things must line up, and each has a different failure:

        input_type / output_type   the child's public boundary vs the parent node's contract.
                                   A mismatch is a wiring bug the parent's own checks cannot see,
                                   because to them the node is just "bound to something".
        state_type / deps_type     the child runs on the parent's EXACT objects, so identical
                                   declared types is not pedantry — it is the precondition that
                                   makes sharing them safe to state.

    Cycles are NOT checked here. `GraphSpec._check` owns that, so there is exactly one place that
    decides whether a chain has closed on itself.
    """
    findings: list[str] = []
    declared_nodes = {id(n) for n in parent.nodes}

    for node, binding in strategy.bindings.items():
        if not isinstance(binding, SubgraphBinding):
            continue
        if id(node) not in declared_nodes:
            continue                    # `check_bindings` already reports this, and better
        child, child_strategy = binding.graph, binding.strategy
        where = (f"strategy {strategy.name!r} binds node {node.name!r} to subgraph "
                 f"{_graph_name(child)}::{child_strategy.name}")

        for side, port, child_type in (("input", "input_type", child.input_type),
                                       ("output", "output_type", child.output_type)):
            want, note = _port_type(parent, node, side)
            if note is not None:
                findings.append(note if note.startswith("NOT CHECKED") else f"{where}, but {note}")
                continue
            if child_type is not want:
                verb = "accepts" if side == "input" else "produces"
                findings.append(
                    f"{where}, but the node {verb} {_type_name(want)} and the child graph "
                    f"declares {port} {_type_name(child_type)}. A subgraph is a valid "
                    f"implementation only when its public boundary matches the role it fills.")

        for attr in ("state_type", "deps_type"):
            mine, theirs = getattr(parent, attr), getattr(child, attr)
            if theirs is not mine:
                findings.append(
                    f"{where}, but the parent declares {attr} {_type_name(mine)} and the child "
                    f"declares {_type_name(theirs)}. A subgraph runs on the parent's exact "
                    f"{attr.split('_')[0]} object, so the declared types must be identical — "
                    f"there is no conversion, and inventing one would make it ambiguous who owns "
                    f"a mutation.")

        findings += child._check(child_strategy, ancestry=ancestry)

    return findings


def check_decisions(decisions: tuple[DecisionSpec, ...],
                    edges: tuple[EdgeSpec, ...]) -> list[str]:
    """`when` appears exactly on the edges leaving a decision, and nowhere else.

    Both directions are real mistakes with different consequences:

        an edge leaving a decision with no `when`     cannot be built — there is no branch to
                                                      make of it, and `g.match(None)` is not a
                                                      thing
        `when` on an ordinary edge                    silently ignored, which is worse: the
                                                      declaration reads as conditional and the
                                                      graph routes unconditionally
        a decision with no branches at all            routes nowhere; everything downstream is
                                                      unreachable and the value is dropped
    """
    findings: list[str] = []
    declared = {id(d) for d in decisions}

    for d in decisions:
        branches = [e for e in edges if e.source is d]
        if not branches:
            findings.append(
                f"decision {d.name!r} has no branches — no edge leaves it. It would route nothing "
                f"and everything it was meant to reach is unreachable.")
        for e in branches:
            if e.when is None:
                findings.append(
                    f"edge {e!r} leaves decision {d.name!r} without a `when=` type. A branch is "
                    f"chosen by the type of the routed value; without one there is nothing to "
                    f"match on and the branch cannot be built.")
        seen: dict[Any, int] = {}
        for e in branches:
            if e.when is not None:
                seen[e.when] = seen.get(e.when, 0) + 1
        for typ, n in seen.items():
            if n > 1:
                findings.append(
                    f"decision {d.name!r} has {n} branches matching {_type_name(typ)}. Only the "
                    f"first can ever be taken; the rest are dead and read as coverage.")

    for e in edges:
        if e.when is not None and id(e.source) not in declared:
            findings.append(
                f"edge {e!r} carries `when={_type_name(e.when)}` but its source is not a "
                f"DecisionSpec, so the condition is IGNORED — the declaration reads as "
                f"conditional and the graph routes unconditionally.")
    return findings


def _exclusive_groups(decisions: tuple[DecisionSpec, ...],
                      edges: tuple[EdgeSpec, ...]) -> list[set[int]]:
    """For each decision branch, everything reachable from it. Two nodes in DIFFERENT branch sets
    of the SAME decision cannot both run.

    ⚠️ Measured, not reasoned: a node downstream of two branches is invoked ONCE. Without this,
    `check_step_arity` reports every branching design as a fan-in defect — the false positive its
    own docstring predicted, arriving the moment decisions became declarable.
    """
    fwd: dict[int, list[Any]] = {}
    for e in edges:
        fwd.setdefault(id(e.source), []).append(e.target)

    def reach(start: Any) -> set[int]:
        seen: set[int] = set()
        stack = [start]
        while stack:
            cur = stack.pop()
            if id(cur) in seen:
                continue
            seen.add(id(cur))
            stack.extend(fwd.get(id(cur), ()))
        return seen

    groups: list[set[int]] = []
    for d in decisions:
        for e in edges:
            if e.source is d:
                groups.append(reach(e.target))
    return groups


def check_step_arity(nodes: tuple[NodeSpec, ...], edges: tuple[EdgeSpec, ...],
                     *, decisions: tuple[DecisionSpec, ...] = ()) -> list[str]:
    """A step body receives exactly ONE value, so a node cannot consume two inputs at once.

    ⚠️ Takes `nodes` ONLY, never joins. A `JoinSpec` exists precisely to receive several arrivals
    and is the fix this check points at; running it over joins would flag the solution.

    ⛔ This is the fan-in defect, and it is silent in every other check. Measured against
    pydantic-graph 2.35.1 with `docs/probe_builder_features.py`'s shape:

        merge = NodeSpec("merge", inputs=(left, right), outputs=(out,))
        EdgeSpec(step_a, merge, left)        # step_a produced 2
        EdgeSpec(step_b, merge, right)       # step_b produced 3

        merge was called 2 time(s), with [3, 2]
        run(1) -> 'got 3'                    <- step_a's result silently discarded

    Every existing check passes on that. `check_variables` is happy — both variables are declared
    on both ends. `check_reachable` is happy — everything reaches END. The declaration READS as
    "merge combines left and right", renders green, runs, and drops one of them.

    ⚠️ The two findings below are different mistakes and are reported separately:

        declaring >1 input      the contract is unsatisfiable by a step, whatever is wired to it
        >1 incoming edge        the node is INVOKED once per edge, and the results do not merge

    The fix for either is a `JoinSpec` in the design's `joins`, whose reducer
    `(current, input) -> current` is the shape that can actually combine two arrivals.
    `examples/ladder/stage8_join.py` shows the form.

    ⚠️ TWO shapes are NOT fan-ins and are excluded. Both were found by RUNNING a real design, and
    both shipped as false positives first:

        mutually exclusive branches   two branches of one decision converging. Measured: the node
                                      downstream runs ONCE. Handled by `_exclusive_groups`.
        a loop-back                   a retry edge returning to an earlier node. Measured against
                                      raw pydantic-graph: the cycle is legal and the node running
                                      three times is the POINT. "All but one result discarded" is
                                      false there — the invocations are separated in TIME, not
                                      concurrent. Handled by `_back_edges`.

    The lesson is in the rule's shape: it is stated in terms of edge COUNT, which is easy to
    compute and is not the question. Concurrency is.
    """
    findings: list[str] = []
    groups = _exclusive_groups(decisions, edges)
    back = _back_edges(edges)
    incoming: dict[int, list[EdgeSpec]] = {}
    for e in edges:
        if id(e) in back:
            continue                       # a loop-back is not a concurrent arrival
        if not is_sentinel(e.target):
            incoming.setdefault(id(e.target), []).append(e)

    for n in nodes:
        if len(n.inputs) > 1:
            names = ", ".join(v.name for v in n.inputs)
            findings.append(
                f"node {n.name!r} declares {len(n.inputs)} inputs ({names}), but a pydantic-graph "
                f"step body receives exactly one value — there is no invocation in which both "
                f"arrive. Combining two arrivals is what a join is for; a step cannot express it, "
                f"and the declaration reads as though it can.")

        arrivals = incoming.get(id(n), [])
        if len(arrivals) > 1 and _mutually_exclusive(arrivals, groups):
            continue
        if len(arrivals) > 1:
            froms = ", ".join(sorted(_name(e.source) for e in arrivals))
            findings.append(
                f"node {n.name!r} is fed by {len(arrivals)} edges ({froms}), so it is invoked "
                f"once PER EDGE with one value each time, and all but one result is discarded. "
                f"Measured on exactly this shape: the step ran twice and the graph returned only "
                f"the first. If the intent is to combine them, this is a join, not a step.")

    return findings


def _mutually_exclusive(arrivals: list[EdgeSpec], groups: list[set[int]]) -> bool:
    """Every arrival sits under a DIFFERENT branch of one decision, so at most one can fire.

    ⚠️ Conservative on purpose: it returns True only when each source lands in a distinct branch
    group of a single decision. Anything it cannot prove exclusive stays reported, because a
    missed fan-in is silent data loss and a false alarm is merely annoying.
    """
    if not groups:
        return False
    sources = [e.source for e in arrivals]
    for i, gi in enumerate(groups):
        if not any(id(s) in gi for s in sources):
            continue
        # which group does each source belong to, among groups of the same decision?
        assigned = []
        for s in sources:
            hits = [k for k, g in enumerate(groups) if id(s) in g]
            if not hits:
                return False
            assigned.append(hits[0])
        return len(set(assigned)) == len(sources)
    return False


def _resolve_hint(impl: Any) -> tuple[Any, str | None]:
    """The implementation's return type as an OBJECT, or a reason it could not be had.

    ⚠️ `inspect.signature` gives a STRING under `from __future__ import annotations`, which every
    module in this package uses. `typing.get_type_hints` resolves it against the function's own
    module globals — and raises for a type declared inside a function body, which is ordinary in
    tests. A failure here is "we could not look", never "it is wrong".
    """
    import typing

    try:
        hints = typing.get_type_hints(impl)
    except Exception:                       # noqa: BLE001 — unresolvable is a report, not a raise
        return None, "its annotations could not be resolved"
    if "return" not in hints:
        return None, "it has no return annotation"
    return hints["return"], None


def _produces(annotation: Any, declared: Any) -> bool | None:
    """Does `annotation` satisfy `declared`? `None` means undecidable — never a finding.

    ⛔ Undecidable must not read as a pass OR a failure. A generic alias like `list[Fact]` is not
    a class and cannot be `issubclass`-tested, and guessing either way is worse than saying so:
    a false alarm here would land on correct code and teach people to skip the output.
    """
    import typing

    if declared is object or annotation is declared:
        return True                          # `object` accepts anything; identity is identity

    origin = typing.get_origin(annotation)
    if origin is typing.Union or type(annotation).__name__ == "UnionType":
        members = typing.get_args(annotation)
        verdicts = [_produces(m, declared) for m in members]
        if any(v is None for v in verdicts):
            return None
        return all(verdicts)

    if isinstance(annotation, type) and isinstance(declared, type):
        return issubclass(annotation, declared)

    return None                              # generic aliases, TypeVars, exotic forms


def check_variable_types(parent: Any, strategy: StrategySpec) -> list[str]:
    """Each implementation returns the type its role is declared to produce.

    ⛔ WHY THIS EXISTS, measured before it was written:

        wrong = NodeSpec("wrong", inputs=(text,), outputs=(number,))   # declares int
        async def returns_a_string(ctx) -> str: ...                    # returns str

        check() -> clean
        run('x') -> "got 'not an int: x' (str)"

    Nothing objected — not `check()`, not `build(validate_graph_structure=True)`, not the run.

    ⚠️ And this gap is WORSE here than in raw pydantic-graph, which is the uncomfortable part.
    Their API never asks you to write the type down, so it promises nothing. This library invites
    `VariableSpec("number", int)`, prints it on the diagram, and then never checked it — a claim
    the artifact did not deliver, inside the package built to catch exactly that.

    ⚠️ Distinct from `check_variables`, which asks WHICH declared variable crosses a wire. This
    asks whether the implementation actually produces that variable's TYPE. Two different bugs:
    one is wiring, one is contract.

    ⚠️ Strict where it can decide, silent-but-stated where it cannot. Unannotated and unresolvable
    implementations are collected into ONE `NOT CHECKED` line rather than one finding each — a
    check that emits a finding per unannotated function is noise, and noise is how a check stops
    being read.
    """
    findings: list[str] = []
    unchecked: list[str] = []

    for node in parent.nodes:
        impl = strategy.bindings.get(node)
        if impl is None or isinstance(impl, SubgraphBinding) or not callable(impl):
            continue                         # other checks own these

        declared, note = _port_type(parent, node, "output")
        if declared is None or note is not None:
            continue                         # `check_subgraphs`-style gap; not this check's job

        annotation, why = _resolve_hint(impl)
        if annotation is None:
            unchecked.append(f"{node.name} ({getattr(impl, '__name__', impl)}: {why})")
            continue

        verdict = _produces(annotation, declared)
        if verdict is None:
            unchecked.append(
                f"{node.name} ({_type_name(annotation)} vs {_type_name(declared)}: not decidable)")
        elif verdict is False:
            findings.append(
                f"{strategy.name!r} binds {node.name!r} to "
                f"{getattr(impl, '__qualname__', impl)}, which returns "
                f"{_type_name(annotation)} — but {node.name!r} is declared to produce "
                f"{_type_name(declared)}. The declaration is what the diagram draws and what a "
                f"reader of this design believes; one of the two is wrong.")

    if unchecked:
        findings.append(
            "NOT CHECKED — return types were not compared for: " + "; ".join(sorted(unchecked)) +
            ". An unannotated or unresolvable implementation cannot be checked against its "
            "declared output, and saying nothing would make that look like a pass.")
    return findings


def _back_edges(edges: tuple[EdgeSpec, ...]) -> set[int]:
    """Edges whose source is reachable FROM their target — a loop-back, not an arrival.

    ⛔ Found by building a retry loop, which is the commonest reason anyone reaches for the
    `BaseNode` API: `propose -> validate -> route --Retry--> unwrap -> propose`. That back edge
    gives `propose` two incoming edges, and `check_step_arity` called it a fan-in whose results
    were being discarded. Measured against raw pydantic-graph: the cycle is legal, `propose` runs
    three times, and each run flows forward on its own. Nothing is discarded.
    """
    fwd: dict[int, list[Any]] = {}
    for e in edges:
        fwd.setdefault(id(e.source), []).append(e.target)

    def reaches(start: Any, goal: Any) -> bool:
        seen: set[int] = set()
        stack = list(fwd.get(id(start), ()))
        while stack:
            cur = stack.pop()
            if id(cur) in seen:
                continue
            seen.add(id(cur))
            if cur is goal:
                return True
            stack.extend(fwd.get(id(cur), ()))
        return False

    return {id(e) for e in edges
            if not is_sentinel(e.source) and not is_sentinel(e.target)
            and reaches(e.target, e.source)}
