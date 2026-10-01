# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.0] — 2026-10-01

### ⛔ Breaking — `check()` is renamed to `coherence_check()`

**Step-by-step upgrade: [`docs/migration-0.3.md`](docs/migration-0.3.md).** One line:

```python
spec.check(strategy)              # 0.2.0
spec.coherence_check(strategy)    # 0.3.0
```

No alias. A missed call site is an `AttributeError` at the call, not a silent change of
behaviour — same choice 0.2.0 made when `NodeSpec(...)` became a `TypeError`.

**Why.** `check()` did not say what it checks, and the type it returns says `Coherence` — a word
that appeared nowhere else in the API. One concept was wearing two names, which is the thing the
house naming rule exists to prevent. `coherence_check()` grounds it.

`design_check()` was considered and rejected: `spec` *is* the design, so `spec.design_check()`
restates its own receiver.

**Unchanged:** the eleven `check_*` functions, and the `check` field on a finding — both name an
individual check, which is what they still are.

### Added — `coherence_check()` returns `CoherenceFinding`, not a bare `str`

**Backward compatible. No call site needs editing** — `CoherenceFinding` is a `str` subclass, so
`"x" in f`, `f.startswith(...)`, `"\n".join(findings)`, `f == "the message"`, sorting, hashing
and `repr()` in a printed list all behave exactly as before. Verified byte-for-byte across all 64
findings the test designs produce: nothing in the text moved.

```python
f = spec.coherence_check(strategy)[0]
f.check       # 'check_bindings' — the function that produced it
f.about       # 'compose' — a node name; 'source->target' for an edge; '' for the whole design
f.blocking    # True — False only for a `NOT CHECKED — …` stated gap

from workflow_workbench import blocking
blocking(findings)        # the filter `render()` uses; replaces startswith("NOT CHECKED")
```

**Why.** The findings were sentences, so the structure a caller needs was encoded in the prose.
`[f for f in findings if not f.startswith("NOT CHECKED")]` was load-bearing control flow in three
production call sites here and in both downstream repos — two different kinds of finding wearing
one type, told apart by a prefix match. `.claude/rules/checks.md`: *NOT CHECKED and 0 FOUND must
never render the same.* An agent using `coherence_check()` as its acceptance test could only regex it.

A frozen dataclass is tidier and costs a second breaking migration one release after `StepSpec`;
that is why the subclass wins. `blocking` is a bool rather than a severity enum — two states, and
no third has been observed.

- `CoherenceFinding`, `blocking()` and `NOT_CHECKED` are exported from the package root.
- `coherence_check()` and every `check_*` function are now annotated `list[CoherenceFinding]`.

### Upgrading

Nothing to do. `uv lock --upgrade-package workflow-workbench` when you want the fields; until
then a pinned consumer is unaffected.

## [0.2.0] — 2026-09-30

### ⛔ Breaking — `NodeSpec` is renamed to `StepSpec`

**Step-by-step upgrade: [`docs/migration-0.2.md`](docs/migration-0.2.md).** One-line summary:

```python
NodeSpec("normalize", inputs=(a,), outputs=(b,))    # 0.1.0
StepSpec("normalize", inputs=(a,), outputs=(b,))    # 0.2.0
```

`NodeSpec` still exists and is now a **type alias**, not a class:

```python
NodeSpec = StepSpec | JoinSpec | DecisionSpec        # every box a design declares
```

So `NodeSpec(...)` raises `TypeError` while `x: NodeSpec` keeps type-checking. A call site that
instantiated it fails loudly; one that only annotated with it is unaffected.

**Why.** `NodeSpec` named the general concept and meant one specific kind. Pydantic Graph puts
START and END inside `graph.nodes` and calls `step` / `join` / `decision` the kinds — and this
repo's own wire format already agreed (`payload.Node` carries `kind: str = "step"`). Two of three
layers spoke that vocabulary; the declaration layer did not, which forced a second word
(`Endpoint`) for a set that already had one.

### Added

- `NodeSpec` as an alias for `StepSpec | JoinSpec | DecisionSpec` — every declared box.
- `Bindable` = `StepSpec | TransformEdgeSpec` — everything a strategy must bind. A
  `TransformEdgeSpec` left open is a variation point declared in `edges`, so `StrategySpec` was
  never steps-only; its annotation said otherwise and rejected the documented form.
- `LICENSE` (MIT), plus `readme`, `license` and project URLs in `pyproject.toml`.
- `docs/migration-0.2.md`, and this file.

### Removed

- `Endpoint`. It was a `str` shaped like a type alias, was exported in `__all__`, and had **zero
  references anywhere in the repo**. Superseded by `NodeSpec`.

### Changed

- Four annotations that were false are now true as written. `check_names`, `check_reachable`,
  `check_variables` and `check_fan_out_rejoins` all declared `tuple[NodeSpec, ...]` and were
  called with joins and decisions in that tuple. Same types at runtime; a type checker stops
  disagreeing with the code.
- `GraphSpec._check`'s local `endpoints` is now `declared`, annotated `tuple[NodeSpec, ...]`.
- `eval_battle` names each arm's task callable, so pydantic-evals' progress bar prints the
  strategy name instead of `<lambda>` for every arm.
- README rebuilt around one runnable walkthrough ([`examples/greeting.py`](examples/greeting.py)),
  with the eleven-rung ladder, the builder-feature table and the design rationale moved to
  `docs/`. Every figure in it is asserted by `tests/test_greeting.py` — including that the mermaid
  block *is* `diff_diagram()`'s output.
- `workflow_workbench.parity` writes `docs/parity.md` (was: the README appendix) and grew
  `--write`, so the derived table is never pasted by hand.

## [0.1.0]

Initial: `GraphSpec`, `StrategySpec`, `SubgraphBinding`, the checks, the diagrams, `eval_battle`,
the report viewer.
