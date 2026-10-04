# Upgrading to 0.3.0

Two changes. One is a rename you must make; the other needs nothing from you.

## 1. `check()` → `coherence_check()` — required

```python
spec.check()                      # 0.2.0
spec.coherence_check()            # 0.3.0

spec.check(strategy)              # 0.2.0
spec.coherence_check(strategy)    # 0.3.0
```

**There is no alias.** A missed call site raises `AttributeError: 'YourSpec' object has no
attribute 'check'` at the call — loud, and at the line that needs editing. 0.2.0 made the same
choice when `NodeSpec(...)` became a `TypeError`: a silent narrowing would be worse than a stop.

```bash
grep -rn "\.check(" --include=*.py .     # every site, and there is nothing else named .check(
sed -i 's/\.check(/.coherence_check(/g' <files>
pytest -q
```

⚠️ **One function is NEW in this release:** `check_recursion`, which is the recursive-subgraph
rule made public. It was previously enforced inside `graph_spec.py` and therefore missing from the
generated rules table. Nothing you call changes; the rule count goes 11 → 12.

**Unchanged, and deliberately so:**

| | |
|---|---|
| `check_names`, `check_reachable`, … the existing functions | unchanged — each *is* one check |
| `CoherenceFinding.check` | unchanged — it names which of them produced the finding |
| `render()`, `diagram()`, `diff_diagram()`, `varies()`, `eval_battle()` | unchanged |

### Why

`check()` did not say what it checks, and the type it returns said `Coherence` — a word that
appeared nowhere else in the API. One concept, two names.

`design_check()` was considered and rejected: `spec` *is* the design, so `spec.design_check()`
restates its own receiver, the way `file.file_close()` would.

## 2. `coherence_check()` returns `CoherenceFinding` — nothing to do

`CoherenceFinding` is a `str` subclass, so every string operation on a finding behaves exactly as
it did. Verified byte-for-byte across all 64 findings this repo's designs produce.

```python
f = spec.coherence_check(strategy)[0]

f == "the raw message"      # True, as before
"unreachable" in f          # as before
"\n".join(findings)         # as before
f.startswith("NOT CHECKED") # as before — and `f.blocking` now says the same thing as a field

f.check                     # 'check_bindings' — which check produced it
f.about                     # 'compose'; 'source->target' for an edge; '' for the whole design
f.blocking                  # False only for a `NOT CHECKED — …` stated gap
```

The prefix match is still correct and still supported. `blocking(findings)` is the shared filter
`render()` uses, if you would rather not spell it out:

```python
from workflow_workbench import blocking
blocking(spec.coherence_check(strategy))
```
