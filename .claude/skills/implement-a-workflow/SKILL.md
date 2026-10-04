---
name: implement-a-workflow
description: Implement or modify the step bodies of a workflow-workbench GraphSpec. Use whenever asked to implement a step, fill in a strategy, add an arm, or make coherence_check() pass on a design in this repo.
---

# Implementing a workflow

You are filling in **implementations**. You are not designing the workflow.

## The division of labour, and it is the point

| | owns | |
|---|---|---|
| the human | the **declaration** — `nodes`, `edges`, `VariableSpec`, `problem` | ~15 lines they can read |
| you | the **step bodies** | however long they need to be |
| `coherence_check()` | the contract between the two | run it; it is your acceptance test |

**Do not edit the declaration to make a check pass.** That is the one move that defeats the
whole arrangement. If a check is red because the design is wrong, say so and ask — do not widen
the contract until the red goes away.

## Start by reading the design, not the code

```python
spec = TheDesign()
spec.coherence_check()     # what is wrong right now
spec.diagram()             # the shape, as mermaid
```

Then read each `StepSpec.problem` you are implementing. **That is your brief** — it states what
makes the stage hard, deliberately not what to do. An empty `problem` means nobody wrote one; it
does **not** mean the stage is trivial.

## Your acceptance test

```python
from workflow_workbench import blocking

findings = spec.coherence_check(strategy)
blocking(findings)          # empty == render() will succeed
```

**Branch on the fields, never on the sentence.** Every finding is a `CoherenceFinding`:

```python
f.check      # which check produced it, e.g. 'check_bindings'
f.about      # the node name; 'source->target' for an edge; '' for the whole design
f.blocking   # False only for a `NOT CHECKED — …` stated gap
```

⛔ **A `NOT CHECKED` finding is not a pass.** It means a check looked and could not reach a
verdict — usually a missing return annotation. Fix the cause rather than filtering the line out.

## Rules that will save you a wasted round

- **Bind every step, including ones you did not change.** A partial strategy is refused on
  purpose, so that "what varies between these arms" is answerable without reading both files.
- **A step body takes exactly one positional argument (`ctx`)** and returns the type its role
  declares. `check_implementations` and `check_variable_types` both check this.
- **Annotate your return type.** Without it `check_variable_types` reports `NOT CHECKED` and
  nothing verifies you produced what the role promised.
- **A step receives one value.** If you need to combine two arrivals, that is a `JoinSpec` and
  it is a change to the declaration — ask.
- **A fan-out must reach a join.** Otherwise all but one result is silently discarded.

## Before you report done

```bash
uv run pytest -q
uv run python3 -m workflow_workbench.reference --check
```

Then say which findings remain and why, including the `NOT CHECKED` ones. **Do not report a
design as clean while a stated gap is open** — say what was not checked.

## When the right answer is "this should not be a node"

A stage worth declaring is one where **two competent people would implement it differently**. If
a stage is deterministic one-liner logic with a right answer you could look up, it does not need
a role, a strategy or a battle — say so rather than building scaffolding around it.
`examples/greeting.py` is deliberately below that bar; `examples/contestable.py` is above it.
