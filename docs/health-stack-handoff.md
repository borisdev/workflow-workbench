# Health-stack workflow handoff

## Outcome

`examples/local/health_stack.py` expresses the evidence pipeline as one Workflow Workbench
`GraphSpec` and runs it with deterministic fake UMLS and SemMedDB services.

The workflow graph and case graph are deliberately different:

- **Workflow graph:** six processing roles declared with `NodeSpec`/`EdgeSpec`.
- **Case graph:** medical concepts, profile characteristics, predications, and evidence inside the
  final `CaseReport`.

## Fixed design

```text
health_stack_text
  -> extract_case
  -> resolve_concepts
  -> build_given_graph
  -> cite_given_edges
  -> discover_candidate_gaps
  -> rank_story
  -> CaseReport
```

Every intermediate value has a distinct `VariableSpec`. Do not collapse `given_graph`,
`cited_given_graph`, and `expanded_graph`: they share the same Python type but mean different
things, and confusing them is precisely the wiring error Workflow Workbench should detect.

## Strategy boundary

Infrastructure is supplied through `Services` (`ctx.deps`); fake versus production service clients
are not strategies. Strategies are algorithmic alternatives that deserve evaluation on the same
cases, such as:

- joint versus staged extraction;
- exact-triple versus broader neighborhood discovery;
- compact versus full story projection.

The example defines `compact` and `full`; `spec.varies(compact, full)` correctly reports only
`rank_story`.

## Important contract found while testing

SemMedDB discovery must return a `Neighborhood` containing both new `Concept`s and new
`Predication`s. Returning edges alone creates dangling object IDs.

## Verification

```bash
uv run pytest -c pyproject.toml tests/test_health_stack_example.py -q
uv run python3 -m examples.local.health_stack
```

Expected focused result: `2 passed`.

## Next implementation steps

1. Move the domain models into the NoBSmed codebase; keep this file as the integration example.
2. Replace `fixture_extract` with a structured-output LLM implementation that extracts mentions,
   profile characteristics, and only user-stated predications together.
3. Implement UMLS candidate retrieval plus contextual candidate selection. Preserve unresolved
   mentions rather than forcing a CUI.
4. Implement exact-triple SemMedDB evidence retrieval with PMID and source sentence provenance.
5. Implement typed neighborhood queries that return both concepts and predications.
6. Add an applicability model comparing `PersonProfile` characteristics against each study
   population. Applicability qualifies evidence; it is not a causal case-graph edge.
7. Add two projections from the same full `CaseGraph`: all predications and a ranked 8–15-edge
   `Health Stack Story`.
8. Turn the three real health stacks into Pydantic Evals `Case`s. Battle extraction, discovery,
   and ranking strategies with the repository's existing `eval_battle`; do not create a new eval
   harness or duplicate Pydantic Evals types.

## Do not claim yet

- The fake extractor is not clinical extraction.
- Fake CUIs and evidence prove orchestration only.
- The focused test validates the workflow contract, profile preservation, given/discovered layers,
  and strategy alignment—not medical correctness.
